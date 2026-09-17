#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Converte o corpus congelado em Markdown com nomes padronizados.

    python3 analysis/build-md-corpus.py --frozen ../<repo-do-paper>/audit/frozen \
                                        --out corpus-md
    python3 analysis/build-md-corpus.py --out corpus-md --check

Saída:

    corpus-md/
      index.json                     roster + metadados de cada documento
      booking-com/01-content-privacy.md
      booking-com/02-terms-and-conditions.md
      ...

POR QUE MARKDOWN COM FRONT MATTER. O `.txt` do kit carrega a procedência num
cabeçalho de texto que só um humano lê, e que a ferramenta tem que aprender a
pular antes de conferir o hash. Em Markdown a procedência é front matter YAML —
o Colab renderiza, e o notebook lê com três linhas de parser. O corpo abaixo do
front matter é *exatamente* o texto congelado, byte a byte, para o
`sha256_text` do manifesto continuar valendo. Se um dia divergir, o notebook
põe o documento em quarentena em vez de codificar em cima dele.

POR QUE RENOMEAR. Os diretórios do congelamento saíram de duas gerações de
captura: uns com o nome curto do serviço (`pinterest`), outros com o nome longo
da designação da Comissão (`facebook-meta-platforms-ireland-limited-dsa-vlop`).
Isso já custou caro uma vez — o dossiê do fluxo de codificação é chaveado por
serviço, e 11 dos 26 devolviam log vazio em silêncio porque a chave não batia.
Aqui o nome canônico é sempre o do roster do instrumento (`codebook.SERVICOS`),
resolvido pela mesma regra do `coding_flow.resolver_servico`: exato, ou prefixo
único, ou erro. Uma origem só para o nome, e ela não é o sistema de arquivos.

POR QUE A ORDEM É binding → unknown → non-binding. O `01-` de cada serviço é o
documento que mais importa para a codificação. Quem abre só os primeiros abre
os vinculantes, que é onde a alegação central do paper vive. `unknown` vem antes
de `non-binding` porque o rótulo saiu do texto que antecedia a URL na passada 1,
e 100 dos 162 documentos ficaram sem ele — inclusive a Privacy Policy e os
Terms do Facebook. Na ordem anterior, o `01-` do Facebook era uma matéria do
TechCrunch. `non-binding` é o único rótulo que afirma algo: PR, blog, ajuda.

O PORTÃO DE ILEGIBILIDADE. Documento com mais de 2% de U+FFFD não entra: sai
para `excluidos` no índice, com o motivo. É o mesmo limiar do
`freeze-sources.py`, e existe porque o kit de 31/jul foi distribuído com o
conjunto vinculante do Pinterest em 43% de caractere de substituição, sob um
cabeçalho com SHA-256 de aparência impecável — o hash batia com o corpo
corrompido, então nada acusou. Um "No" lido daquilo seria artefato de captura
entrando no κ como discordância.

Sem dependências externas: só a biblioteca padrão.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codebook as C  # noqa: E402


def _carregar_freeze_sources():
    # Hífen no nome: não importa por `import`. A regra de pertença dos documentos
    # vive lá e só lá — reescrevê-la aqui seria a segunda cópia que divergiria.
    import importlib.util
    caminho = Path(__file__).resolve().parent / "freeze-sources.py"
    spec = importlib.util.spec_from_file_location("freeze_sources", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FS = _carregar_freeze_sources()

LIMIAR_ILEGIVEL = 0.02  # mesmo limiar do freeze-sources.py
ORDEM_REGISTRO = {"binding": 0, "unknown": 1, None: 1, "non-binding": 2}

# Palavras que não distinguem um documento do outro e só alongam o nome.
RUIDO_NO_NOME = {
    "html", "htm", "php", "aspx", "en", "en-us", "en-gb", "index", "page",
    "legal", "www", "com", "policies", "policy-page", "id", "web",
}


class ErroDeEntrada(RuntimeError):
    """O manifesto ou o corpus não têm a forma que este script espera."""


# ------------------------------------------------------------------ utilidades

def slug(texto: str, limite: int = 48) -> str:
    """Slug ASCII estável. Sem acento, sem pontuação, sem hífen dobrado."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = t.encode("ascii", "ignore").decode("ascii").lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    if len(t) > limite:
        t = t[:limite].rstrip("-")
    return t or "doc"


def nome_do_documento(doc: dict) -> str:
    """Nome legível a partir da URL: o que distingue este documento dos outros.

    Não tentamos ler o título do texto. As capturas trazem menu, rodapé e
    banner de cookie junto (o LEIA-ME do kit avisa disso), então a primeira
    linha do texto costuma ser navegação, não título. A URL é a informação
    que o congelamento garante correta.
    """
    url = doc.get("url") or doc.get("final_url") or ""
    caminho = re.sub(r"^https?://", "", url).split("?")[0].split("#")[0]
    partes = [p for p in caminho.split("/")[1:] if p]
    # Segmento que parece hash, data ou id numérico não nomeia nada.
    partes = [p for p in partes if not re.fullmatch(r"[0-9a-f]{8,}|\d{6,}", p)]
    palavras: list[str] = []
    for parte in partes[-3:]:
        for palavra in re.split(r"[-_.]+", parte):
            p = slug(palavra, 32)
            if p and p not in RUIDO_NO_NOME and p not in palavras:
                palavras.append(p)
    return slug("-".join(palavras) or caminho.split("/")[0], 52)


def canonizar(nome_do_manifesto: str) -> str:
    """Nome do manifesto → nome do roster do instrumento.

    O manifesto chama de "Temu (Whaleco Technology Limited; DSA VLOP)" o que o
    instrumento chama de "Temu"; 11 dos 26 diferem assim. A regra é a mesma do
    `coding_flow.resolver_servico`, e por um motivo: um `.get()` com default
    silencioso é como um serviço inteiro sai do corpus sem ninguém notar.
    """
    if nome_do_manifesto in C.SERVICOS:
        return nome_do_manifesto
    # Prefixo só vale terminando em fronteira de palavra. Sem isso, "XVideos
    # (WebGroup…)" casa com "X" e com "XVideos", e "Google Play (…)" casaria com
    # qualquer roster que tivesse "Google". A fronteira é o que separa nome
    # completo de começo de outro nome.
    cand = sorted((s for s in C.SERVICOS
                   if nome_do_manifesto.startswith(s)
                   and not nome_do_manifesto[len(s):len(s) + 1].isalnum()),
                  key=len, reverse=True)
    if len(cand) == 1:
        return cand[0]
    raise ErroDeEntrada(
        f"{nome_do_manifesto!r} resolveu para {cand or 'nada'} no roster — esperava exatamente 1")


def ilegibilidade(texto: str) -> float:
    """Fração de U+FFFD — o rastro que a decodificação errada deixa."""
    return texto.count("�") / max(len(texto), 1)


def sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def front_matter(campos: dict) -> str:
    """YAML mínimo. Só escalares — nada aqui precisa de lista ou aninhamento."""
    linhas = ["---"]
    for chave, valor in campos.items():
        if valor is None:
            linhas.append(f"{chave}: null")
        elif isinstance(valor, bool):
            linhas.append(f"{chave}: {'true' if valor else 'false'}")
        elif isinstance(valor, int):
            linhas.append(f"{chave}: {valor}")
        else:
            texto = str(valor).replace('"', '\\"')
            linhas.append(f'{chave}: "{texto}"')
    linhas.append("---")
    return "\n".join(linhas)


def separar(markdown: str) -> tuple[dict, str]:
    """Devolve (front matter, corpo). O corpo é o texto congelado intocado."""
    if not markdown.startswith("---\n"):
        raise ErroDeEntrada("arquivo sem front matter")
    fim = markdown.find("\n---\n", 4)
    if fim < 0:
        raise ErroDeEntrada("front matter sem fechamento")
    meta = {}
    for linha in markdown[4:fim].splitlines():
        if ":" not in linha:
            continue
        chave, _, valor = linha.partition(":")
        valor = valor.strip()
        if valor.startswith('"') and valor.endswith('"'):
            valor = valor[1:-1].replace('\\"', '"')
        elif valor == "null":
            valor = None
        elif valor.isdigit():
            valor = int(valor)
        meta[chave.strip()] = valor
    corpo = markdown[fim + 5:]
    # A linha em branco entre o front matter e o texto é enfeite de Markdown, não
    # é o documento. Ela sai antes do hash, senão nada bate com o manifesto.
    return meta, corpo[1:] if corpo.startswith("\n") else corpo


# --------------------------------------------------------------------- build

def carregar_membros(frozen: Path) -> tuple[dict, list[dict]]:
    """(manifesto, [documento com o serviço que o USA]) — um item por par serviço–URL.

    Documento compartilhado aparece uma vez para cada serviço cuja lista da
    passada 1 o inclui. Ver `membros` em `freeze-sources.py` para o porquê: agrupar
    pelo `service` do manifesto tirava cinco documentos do Google Search.
    """
    if not (frozen / "manifest.json").exists():
        raise ErroDeEntrada(f"manifesto não encontrado em {frozen / 'manifest.json'}")
    manifesto, grupos = FS.carregar_membros(frozen)
    docs = [d for entradas in grupos.values() for d in entradas]
    if not docs:
        raise ErroDeEntrada("manifesto sem documentos")
    return manifesto, docs


def construir(frozen: Path, saida: Path, verboso: bool = True) -> dict:
    manifesto, docs = carregar_membros(frozen)
    vantagem = (manifesto.get("vantage") or {}).get("country")

    servicos: dict[str, list[dict]] = {}
    excluidos: list[dict] = []

    for doc in docs:
        if not doc.get("service"):
            continue
        servico = canonizar(doc["service"])
        registro = {"servico": servico, "url": doc.get("url"),
                    "role": doc.get("role_hint")}

        if doc.get("error"):
            # A nota de recaptura, quando existe, é o que o codificador precisa
            # ler: o `error` é a medição da tentativa automatizada, e depois de
            # uma recaptura manual ele pode ter virado conselho obsoleto.
            motivo = f"captura falhou: {doc['error']}"
            if doc.get("recapture_note"):
                motivo += f" · {doc['recapture_note']}"
            excluidos.append({**registro, "motivo": motivo})
            continue
        if not doc.get("text_path"):
            excluidos.append({**registro, "motivo": "sem texto extraído"})
            continue

        arquivo = frozen / doc["text_path"]
        if not arquivo.exists():
            excluidos.append({**registro, "motivo": f"arquivo ausente: {doc['text_path']}"})
            continue

        texto = arquivo.read_text(encoding="utf-8", errors="replace")
        ruim = ilegibilidade(texto)
        if ruim > LIMIAR_ILEGIVEL:
            excluidos.append({**registro,
                              "motivo": f"ilegível: {ruim:.1%} de U+FFFD"})
            continue
        # O hash do manifesto é sobre o texto extraído. Se não bater, a cópia em
        # disco não é a que foi congelada — não dá para saber qual das duas é a
        # boa, e codificar em cima disso contamina o κ.
        esperado = doc.get("sha256_text")
        if esperado and sha256(texto) != esperado:
            excluidos.append({**registro, "motivo": "hash não confere com o manifesto"})
            continue

        servicos.setdefault(servico, []).append({"doc": doc, "texto": texto})

    indice = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "frozen_at": manifesto.get("captured_at"),
        "vantage": vantagem,
        "limiar_ilegivel": LIMIAR_ILEGIVEL,
        "services": [],
        "excluidos": excluidos,
    }

    saida.mkdir(parents=True, exist_ok=True)
    for servico in sorted(servicos):
        pasta_slug = slug(servico)
        pasta = saida / pasta_slug
        pasta.mkdir(exist_ok=True)

        itens = sorted(
            servicos[servico],
            key=lambda i: (ORDEM_REGISTRO.get(i["doc"].get("role_hint"), 2),
                           i["doc"].get("text_path") or ""),
        )

        docs_indice = []
        usados: set[str] = set()
        for n, item in enumerate(itens, start=1):
            doc, texto = item["doc"], item["texto"]
            base = nome_do_documento(doc)
            # Dois documentos podem reduzir ao mesmo nome (a mesma política em
            # dois domínios, por exemplo). Desempata pelo número, que é estável.
            nome = f"{n:02d}-{base}"
            if base in usados:
                nome = f"{n:02d}-{base}-{n}"
            usados.add(base)
            arquivo = f"{nome}.md"

            meta = {
                "service": servico,
                "service_slug": pasta_slug,
                "doc": n,
                "role": doc.get("role_hint") or "unknown",
                "url": doc.get("url"),
                "final_url": doc.get("final_url"),
                "captured_at": doc.get("captured_at"),
                "vantage": doc.get("vantage_country") or vantagem,
                "sha256_text": doc.get("sha256_text") or sha256(texto),
                "chars": len(texto),
                "wayback_url": doc.get("wayback_url"),
            }
            (pasta / arquivo).write_text(
                front_matter(meta) + "\n\n" + texto, encoding="utf-8")

            docs_indice.append({
                "n": n, "file": f"{pasta_slug}/{arquivo}", "role": meta["role"],
                "url": meta["url"], "chars": meta["chars"],
                "sha256_text": meta["sha256_text"],
                "captured_at": meta["captured_at"],
            })

        indice["services"].append({
            "name": servico, "slug": pasta_slug, "docs": docs_indice,
            "n_binding": sum(1 for d in docs_indice if d["role"] == "binding"),
        })

    # Resto de build anterior tem de sair. Uma recaptura renumera os documentos
    # do serviço, e o arquivo com o nome velho continuaria em disco, fora do
    # índice: quem navegasse a pasta em vez de ler o índice leria uma versão que
    # o corpus já não declara. O `--check` acusa isso, e aqui é onde se resolve.
    declarados = {saida / d["file"] for s in indice["services"] for d in s["docs"]}
    sobraram = [p for p in saida.rglob("*.md") if p not in declarados]
    for p in sobraram:
        p.unlink()
    for pasta in saida.iterdir():
        if pasta.is_dir() and not any(pasta.iterdir()):
            pasta.rmdir()

    (saida / "index.json").write_text(
        json.dumps(indice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if verboso and sobraram:
        print(f"{len(sobraram)} arquivo(s) de build anterior removidos "
              f"(ex.: {sobraram[0].relative_to(saida)})")
    if verboso:
        total = sum(len(s["docs"]) for s in indice["services"])
        print(f"{total} documentos · {len(indice['services'])} serviços · "
              f"vantagem {vantagem} → {saida}")
        if excluidos:
            print(f"{len(excluidos)} excluídos:")
            for e in excluidos[:8]:
                print(f"  - {e['servico']}: {e['motivo']}")
            if len(excluidos) > 8:
                print(f"  … e mais {len(excluidos) - 8}")
    return indice


# --------------------------------------------------------------------- check

def checar(saida: Path, frozen: Path | None = None) -> int:
    """Afirma o que o corpus tem que satisfazer. Ruidoso de propósito.

    Com `frozen`, confere também a pertença contra o inventário: todo par
    serviço–URL da passada 1 com captura boa tem de estar no serviço dele. É o
    teste que teria pego o Google Search com dois documentos em vez de sete.
    """
    problemas: list[str] = []
    indice = json.loads((saida / "index.json").read_text(encoding="utf-8"))

    if frozen is not None:
        _, docs = carregar_membros(frozen)
        publicados = {(s["name"], d["url"]) for s in indice["services"] for d in s["docs"]}
        excluidos = {(e["servico"], e["url"]) for e in indice.get("excluidos", [])}
        for d in docs:
            par = (canonizar(d["service"]), d["url"])
            if par not in publicados and par not in excluidos:
                problemas.append(f"{par[0]}: {par[1][:70]} está no inventário "
                                 "e sumiu do corpus sem ir para excluídos")

    declarados = set()
    for servico in indice["services"]:
        if servico["slug"] != slug(servico["name"]):
            problemas.append(f"{servico['name']}: slug fora do padrão")
        for d in servico["docs"]:
            declarados.add(d["file"])
            caminho = saida / d["file"]
            if not caminho.exists():
                problemas.append(f"{d['file']}: declarado no índice, ausente em disco")
                continue
            meta, corpo = separar(caminho.read_text(encoding="utf-8"))
            if sha256(corpo) != d["sha256_text"]:
                problemas.append(f"{d['file']}: corpo não bate com o sha256 do índice")
            if meta.get("service") != servico["name"]:
                problemas.append(f"{d['file']}: front matter aponta outro serviço")
            if ilegibilidade(corpo) > LIMIAR_ILEGIVEL:
                problemas.append(f"{d['file']}: ilegível passou pelo portão")

    em_disco = {str(p.relative_to(saida)) for p in saida.rglob("*.md")}
    for orfao in sorted(em_disco - declarados):
        problemas.append(f"{orfao}: em disco, fora do índice")

    # O censo é dos 26 designados. Serviço que sumiu do corpus não pode sumir em
    # silêncio: sem documento, o codificador não tem o que ler, e o "No" dele
    # seria ausência de corpus, não ausência de divulgação.
    presentes = {s["name"] for s in indice["services"]}
    for faltando in sorted(set(C.SERVICOS) - presentes):
        problemas.append(f"{faltando}: no roster, sem nenhum documento no corpus")
    for intruso in sorted(presentes - set(C.SERVICOS)):
        problemas.append(f"{intruso}: no corpus, fora do roster dos 26")

    if problemas:
        print(f"FALHOU — {len(problemas)} problema(s):")
        for p in problemas[:40]:
            print(f"  - {p}")
        return 1
    print(f"OK — {len(declarados)} documentos conferem com o índice "
          f"({len(indice['services'])} serviços, {len(indice['excluidos'])} excluídos)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--frozen", type=Path, help="diretório audit/frozen do repo do paper")
    ap.add_argument("--out", type=Path, default=Path("corpus-md"))
    ap.add_argument("--check", action="store_true",
                    help="valida um corpus já construído em --out")
    args = ap.parse_args()

    if args.check:
        return checar(args.out, args.frozen)
    if not args.frozen:
        ap.error("--frozen é obrigatório para construir")
    try:
        construir(args.frozen, args.out)
    except ErroDeEntrada as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    return checar(args.out, args.frozen)


if __name__ == "__main__":
    sys.exit(main())
