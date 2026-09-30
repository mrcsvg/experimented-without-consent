"""Protocolo de busca por palavra-chave do codebook v2, §3.

Fonte única dos 12 termos. Importado pelos notebooks e por qualquer script de
produção que gere o dossiê do instrumento — se os padrões divergirem entre o
que valida e o que roda em massa, o log deixa de ser auditável.

A máquina localiza; o humano decide. Nada aqui emite código de variável, e
nenhuma exclusão é aplicada automaticamente: falsos positivos conhecidos são
*sinalizados* (`flag`) para triagem, porque distinguir "test" experimental de
"contest" é julgamento, e julgamento é do segundo avaliador.

Sem dependências além da stdlib — roda no Colab sem `pip install`.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# §3 — os 12 termos obrigatórios, por documento
# ---------------------------------------------------------------------------

# `label` é o nome usado no log do codebook ("experiment:0 / A-B:0 / test:3").
# `flag` marca padrões cujos hits notoriamente incluem falsos positivos; a nota
# vai junto do hit na tela do avaliador.
PATTERNS: dict[str, dict] = {
    "experiment": {
        "regex": r"\bexperiment\w*",
        "flag": None,
    },
    "A-B": {
        # "A/B test", "A-B testing", "A / B". Não casa com "A&B" nem siglas soltas.
        "regex": r"\bA\s*[/\-]\s*B\b",
        "flag": None,
    },
    "randomize": {
        "regex": r"\brandomi[sz]\w*",
        "flag": None,
    },
    "test": {
        # \b antes de "test" já exclui "contest"/"protest" (não há fronteira ali),
        # mas pega "testimonial" e "testing" genérico de software.
        "regex": r"\btest\w*",
        "flag": "verificar sentido: 'testimonial', 'testing' de QA e 'test account' "
                "não são experimentação comportamental",
    },
    "trial": {
        "regex": r"\btrial\w*",
        "flag": "falso positivo comum: 'free trial' / período de teste de assinatura "
                "NÃO é experimentação (ver V1)",
    },
    "beta": {
        "regex": r"\bbeta\b",
        "flag": "verificar: 'beta' de programa de acesso antecipado ≠ experimento "
                "com grupos de controle",
    },
    "control group": {
        "regex": r"\bcontrol\s+group\w*",
        "flag": None,
    },
    "debrief": {
        "regex": r"\bdebrief\w*",
        "flag": None,
    },
    "ethics": {
        "regex": r"\bethic\w*",
        # Medido no Zalando (20/09/2026): os dois únicos hits eram "Our Code of
        # Ethics" e "Report violations of ethical and compliance policies", ambos
        # no menu do site. Conduta empresarial não é revisão ética de
        # experimento, e a V8 pergunta pela segunda.
        "flag": "falso positivo comum: 'code of ethics' / conduta empresarial no menu ou "
                "rodapé NÃO é revisão ética de experimento (ver V8)",
    },
    "review board": {
        "regex": r"\breview\s+board\w*",
        "flag": None,
    },
    "IRB": {
        # Case-sensitive: "irb" minúsculo em texto corrido é quase sempre ruído.
        "regex": r"\bIRB\b",
        "flag": None,
        "case_sensitive": True,
    },
    "risk assessment": {
        "regex": r"\brisk\s+assessment\w*",
        # Dois falsos positivos previsíveis, ambos vistos no corpus: escore
        # antifraude no checkout ("risk assessment for the user's end device …
        # likelihood of attempted fraud", Zalando) e a avaliação de risco
        # sistêmico dos Arts. 34-35 do DSA, que é da plataforma inteira e não
        # revisão prévia por experimento — a distinção que o §4 do paper faz.
        "flag": "falso positivo comum: escore antifraude e avaliação de risco sistêmico do "
                "DSA (Arts. 34-35) não são revisão ética por experimento (ver V8)",
    },
}

KWIC_WINDOW = 90  # caracteres de contexto de cada lado do hit


def _compile(name: str, spec: dict) -> re.Pattern:
    flags = 0 if spec.get("case_sensitive") else re.IGNORECASE
    return re.compile(spec["regex"], flags)


COMPILED: dict[str, re.Pattern] = {name: _compile(name, spec) for name, spec in PATTERNS.items()}


# ---------------------------------------------------------------------------
# Extração
# ---------------------------------------------------------------------------

@dataclass
class Hit:
    """Uma ocorrência de um termo, com o contexto que o avaliador vai ler."""

    term: str
    start: int
    end: int
    match: str
    kwic: str
    flag: str | None = None

    def to_dict(self) -> dict:
        d = {"term": self.term, "start": self.start, "match": self.match, "kwic": self.kwic}
        if self.flag:
            d["flag"] = self.flag
        return d


@dataclass
class DocumentHits:
    file: str
    url: str
    sha256: str
    chars: int
    counts: dict[str, int] = field(default_factory=dict)
    hits: list[Hit] = field(default_factory=list)

    @property
    def log_line(self) -> str:
        """O log do §3 no formato do codebook: 'experiment:0 / A-B:0 / test:3'."""
        return " / ".join(f"{term}:{self.counts.get(term, 0)}" for term in PATTERNS)

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "url": self.url,
            "sha256": self.sha256,
            "chars": self.chars,
            "counts": self.counts,
            "log_line": self.log_line,
            "hits": [h.to_dict() for h in self.hits],
        }


def _normalize(text: str) -> str:
    """NFC + colapso de espaço não-quebrável.

    Políticas capturadas de HTML vêm cheias de \\xa0 e quebras estranhas; sem
    isso, 'control\\xa0group' escapa do padrão `control\\s+group`.
    """
    text = unicodedata.normalize("NFC", text)
    return text.replace(" ", " ").replace("​", "")


def _kwic(text: str, start: int, end: int, window: int = KWIC_WINDOW) -> str:
    left = max(0, start - window)
    right = min(len(text), end + window)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    snippet = " ".join(text[left:right].split())
    return f"{prefix}{snippet}{suffix}"


def scan_text(text: str) -> tuple[dict[str, int], list[Hit]]:
    """Roda os 12 padrões sobre um texto. Retorna (contagens, hits em ordem)."""
    text = _normalize(text)
    counts: dict[str, int] = {}
    hits: list[Hit] = []
    for term, pattern in COMPILED.items():
        found = list(pattern.finditer(text))
        counts[term] = len(found)
        flag = PATTERNS[term].get("flag")
        for m in found:
            hits.append(
                Hit(
                    term=term,
                    start=m.start(),
                    end=m.end(),
                    match=m.group(0),
                    kwic=_kwic(text, m.start(), m.end()),
                    flag=flag,
                )
            )
    hits.sort(key=lambda h: h.start)
    return counts, hits


# ---------------------------------------------------------------------------
# Corpus congelado
# ---------------------------------------------------------------------------

class HashMismatch(RuntimeError):
    """O arquivo em disco não é o que o manifesto diz que é."""


def load_manifest(corpus_root: Path) -> dict:
    """Lê o index.json do corpus congelado.

    O manifesto é a autoridade sobre o que é o corpus — nunca varrer o disco
    com glob. O repo tem diretórios duplicados criados pelo macOS ('pinterest 2')
    que não são rastreados pelo git e inflariam a contagem de 143.
    """
    with open(Path(corpus_root) / "index.json", encoding="utf-8") as fh:
        return json.load(fh)


_RULE = "-" * 78
_BANNER = "=" * 78


def strip_provenance_header(text: str) -> str:
    """Remove o cabeçalho de procedência, devolvendo só o corpo capturado.

    Cada arquivo do corpus abre com sete linhas (FONTE / CAPTURADO / MÉTODO /
    SHA-256) entre uma faixa de '=' e uma régua de '-'. O sha256 do manifesto
    cobre **o corpo**, não o arquivo inteiro — o próprio cabeçalho diz isso,
    já que não poderia conter o hash de si mesmo. Conferir contra o arquivo
    todo dá mismatch em 143 de 143.
    """
    if not text.startswith(_BANNER):
        return text  # arquivo sem cabeçalho: já é o corpo
    marker = "\n" + _RULE + "\n\n"
    _, sep, body = text.partition(marker)
    return body if sep else text


def read_document(corpus_root: Path, entry: dict, verify: bool = True) -> str:
    """Lê um documento, tira o cabeçalho e confere o sha256 do corpo."""
    path = Path(corpus_root) / entry["file"]
    body = strip_provenance_header(path.read_text(encoding="utf-8"))
    if verify:
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if digest != entry["sha256"]:
            raise HashMismatch(
                f"{entry['file']}: manifesto diz {entry['sha256'][:12]}…, "
                f"corpo em disco é {digest[:12]}…"
            )
    return body


def scan_corpus(corpus_root: Path, verify: bool = True) -> dict[str, list[DocumentHits]]:
    """Varre o corpus inteiro. Retorna {serviço: [DocumentHits, ...]}."""
    manifest = load_manifest(corpus_root)
    out: dict[str, list[DocumentHits]] = {}
    for service, entries in manifest["services"].items():
        docs = []
        for entry in entries:
            text = read_document(corpus_root, entry, verify=verify)
            counts, hits = scan_text(text)
            docs.append(
                DocumentHits(
                    file=entry["file"],
                    url=entry["url"],
                    sha256=entry["sha256"],
                    chars=entry["chars"],
                    counts=counts,
                    hits=hits,
                )
            )
        out[service] = docs
    return out
