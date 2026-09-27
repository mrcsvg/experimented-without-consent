#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Confere o caminho do 2º codificador de ponta a ponta, antes de entregar.

    python3 analysis/pre-entrega.py              # ~2 min; não usa API, não escreve nada
    python3 analysis/pre-entrega.py --completo   # confere o sha dos 157 documentos
    python3 analysis/pre-entrega.py --gravar     # inclui a volta de escrita no /api/state

POR QUE ESTE ARQUIVO EXISTE. Os `--check` de cada script conferem o repositório
local, e o repositório local não é o que o avaliador toca. Ele abre um notebook
que baixa o runtime e o corpus DO SITE, e grava as respostas num endpoint. Já
aconteceu duas vezes de o local estar impecável e o publicado, quebrado: o
runtime ficou duas horas sem importar porque um arquivo fora do pacote de seis
passou a ser carregado no topo de outro, e a evidência congelada morreu no 12º
serviço porque o teto de saída cobria pensamento mais JSON. Nenhum `--check`
local pegaria os dois. Este pega, porque exercita o que está no ar.

O QUE ELE NÃO FAZ. Não chama modelo (a evidência está congelada) e, sem
`--gravar`, não escreve em lugar nenhum — dá para rodar quantas vezes quiser.
Com `--gravar` ele lê o estado do codificador, devolve o mesmo conteúdo e
confere que voltou igual: prova que a escrita chega ao GitHub, ao custo de um
commit de autosave no branch `coder2-data`, que é revertível como qualquer outro.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SITE = "https://experimented-without-consent-corpus.vercel.app"
INSTRUMENTO = "https://experimented-without-consent.vercel.app"
CORPUS_LOCAL = RAIZ.parent / "experimented-without-consent-corpus"
PAPER = RAIZ.parent / "ethics-in-digita-experimentation"

def verificacoes_locais() -> list[tuple[str, list[str], Path | None]]:
    """Rótulo, argumentos e o repositório irmão de que a conferência depende.

    Três dos `--check` só fazem sentido com os repositórios do paper e do corpus
    ao lado. Quem clonou só o instrumento não deve ver isso como falha — vê como
    pulado, com o motivo.
    """
    md = CORPUS_LOCAL / "md"
    frozen = PAPER / "audit" / "frozen"
    return [
        ("revisao: self-test", ["analysis/revisao.py", "--self-test"], md),
        ("coding_flow: self-test", ["analysis/coding_flow.py"], None),
        ("codebook em dia com o roster", ["analysis/codebook.py", "--check"], None),
        ("corpus em Markdown íntegro",
         ["analysis/build-md-corpus.py", "--check", "--frozen", str(frozen),
          "--out", str(md)], frozen),
        ("pacote publicável importa isolado",
         ["analysis/publicar-corpus.py", "--check", "--destino", str(CORPUS_LOCAL)],
         CORPUS_LOCAL),
        ("evidência congelada completa",
         ["analysis/congelar-sugestoes.py", "--check", "--out",
          str(CORPUS_LOCAL / "sugestoes")], CORPUS_LOCAL),
        ("notebook em dia com o roster", ["analysis/gerar-notebook-revisao.py", "--check"], None),
        ("validador: self-test", ["analysis/validar-assistente.py", "--simular",
                                  "--corpus", str(md)], md),
        ("congelamento: self-test", ["analysis/congelar-sugestoes.py", "--simular",
                                     "--corpus", str(md)], md),
    ]

# Roda o setup do notebook de verdade, num processo limpo, e responde em JSON.
# É deliberadamente uma cópia do que a célula de instalação faz: se divergir, o
# teste deixa de testar o que o avaliador executa.
SONDA = r'''
import hashlib, json, sys, urllib.request
from pathlib import Path
SITE, destino = sys.argv[1], Path(sys.argv[2])
man = json.load(urllib.request.urlopen(f"{SITE}/lib/manifest.json", timeout=60))
for a in man["arquivos"]:
    with urllib.request.urlopen(f"{SITE}/lib/{a['file']}", timeout=60) as r:
        dados = r.read()
    if hashlib.sha256(dados).hexdigest() != a["sha256"]:
        raise SystemExit(f"{a['file']}: download não bate com o manifesto")
    alvo = destino / a["file"]
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_bytes(dados)
sys.path.insert(0, str(destino / "analysis"))
import revisao as R
corpus = R.configurar(corpus=f"{SITE}/md", modelo="claude-opus-5")
sug = R.congelada("Zalando", corpus)
chao = R.piso("Zalando", corpus)
print(json.dumps({
    "arquivos_runtime": len(man["arquivos"]),
    "servicos": len(corpus.index["services"]),
    "docs": sum(len(s["docs"]) for s in corpus.index["services"]),
    "frozen_at": corpus.index.get("frozen_at"),
    "vantage": corpus.index.get("vantage"),
    "fonte": (sug.origem or {}).get("fonte") if sug else None,
    "v8_piso": len(chao.get("V8") or []),
    "v8_modelo": len((sug.por_variavel.get("V8") or {}).get("citacoes") or []) if sug else 0,
    "sugestao_de_codigo_vazou": bool(sug and (sug.por_variavel.get("V8") or {}).get("sugestao")),
    "tem_recibo": hasattr(R.Painel, "_recibo_inicial"),
    "prompt": sug.origem.get("prompt") if sug else None,
}))
'''


def sha(bruto: bytes) -> str:
    return hashlib.sha256(bruto).hexdigest()


def baixar(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


class Placar:
    def __init__(self):
        self.falhas: list[str] = []
        self.n = 0

    def secao(self, titulo: str):
        print(f"\n{titulo}")

    def checar(self, desc: str, cond: bool, detalhe: str = ""):
        self.n += 1
        print(("  ok    " if cond else "  FALHA ") + desc + (f" — {detalhe}" if detalhe else ""))
        if not cond:
            self.falhas.append(desc)
        return cond


def locais(p: Placar) -> None:
    p.secao("1. o repositório local")
    ambiente = {"CORPUS_MD": str(CORPUS_LOCAL / "md")}
    import os
    env = {**os.environ, **ambiente}
    for desc, args, exige in verificacoes_locais():
        if exige is not None and not exige.exists():
            print(f"  pulou {desc} — falta {exige}")
            continue
        r = subprocess.run([sys.executable, *args], cwd=RAIZ, env=env,
                           capture_output=True, text=True)
        saida = [l for l in ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
                 if l.strip()]
        p.checar(desc, r.returncode == 0, "" if r.returncode == 0 else saida[-1] if saida else "")


def publicado_bate(p: Placar) -> None:
    p.secao("2. o que está no ar é o que está no repositório")
    try:
        man = json.loads(baixar(f"{SITE}/lib/manifest.json"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        p.checar("manifesto do runtime responde", False, str(e))
        return
    p.checar("manifesto do runtime responde", True, f"publicado {man['publicado_em'][:10]}")
    for a in man["arquivos"]:
        local = CORPUS_LOCAL / "lib" / a["file"]
        p.checar(f"runtime no ar = repo: {a['file']}",
                 local.exists() and sha(local.read_bytes()) == a["sha256"])
    for nome, caminho in (("corpus", "md/index.json"), ("evidência", "sugestoes/index.json")):
        try:
            remoto = baixar(f"{SITE}/{caminho}")
        except (urllib.error.URLError, OSError) as e:
            p.checar(f"{nome}: índice responde", False, str(e))
            continue
        local = CORPUS_LOCAL / caminho
        p.checar(f"{nome}: índice no ar = repo",
                 local.exists() and sha(local.read_bytes()) == sha(remoto))
    idx = json.loads(baixar(f"{SITE}/sugestoes/index.json"))
    p.checar("evidência cobre os 26 serviços", len(idx["arquivos"]) == 26,
             f"{len(idx['arquivos'])}")
    p.checar("uma impressão de prompt para todos",
             len({json.loads((CORPUS_LOCAL / 'sugestoes' / a['file']).read_text())['prompt']
                  for a in idx["arquivos"]}) == 1)


def caminho_do_avaliador(p: Placar, completo: bool) -> None:
    p.secao("3. o caminho do avaliador, de um ambiente vazio")
    with tempfile.TemporaryDirectory(prefix="pre-entrega-") as tmp:
        sonda = Path(tmp) / "sonda.py"
        sonda.write_text(SONDA, encoding="utf-8")
        r = subprocess.run([sys.executable, str(sonda), SITE, str(Path(tmp) / "ewc")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            p.checar("setup do notebook roda num processo limpo", False,
                     (r.stderr or "").strip().splitlines()[-1] if r.stderr else "")
            return
        d = json.loads(r.stdout.strip().splitlines()[-1])
    p.checar("setup do notebook roda num processo limpo", True,
             f"{d['arquivos_runtime']} arquivos conferidos")
    p.checar("corpus completo pelo site", d["servicos"] == 26 and d["docs"] == 157,
             f"{d['servicos']} serviços · {d['docs']} documentos")
    p.checar("corpus é o congelado de vantagem UE",
             d["vantage"] == "IT" and (d["frozen_at"] or "").startswith("2026-08"),
             f"{(d['frozen_at'] or '')[:10]} · {d['vantage']}")
    p.checar("painel lê a evidência congelada, sem chave", d["fonte"] == "congelada")
    p.checar("o runtime no ar já tem o recibo de gravação", d["tem_recibo"])
    p.checar("piso determinístico chega à tela", d["v8_piso"] >= 9,
             f"V8 do Zalando: piso={d['v8_piso']} modelo={d['v8_modelo']}")
    p.checar("o modelo só acrescenta, não substitui", d["v8_modelo"] > 0)
    p.checar("nenhuma sugestão de código vazou para o publicado",
             not d["sugestao_de_codigo_vazou"])

    # O corpo de cada .md tem de bater com o `sha256_text` da captura, senão o
    # que o 2º codificador lê não é o documento que o 1º leu — e a discordância
    # viraria deriva do documento, que é justamente o que o congelamento evita.
    idx = json.loads(baixar(f"{SITE}/md/index.json"))
    servicos = idx["services"] if completo else idx["services"][:3]
    ruins = []
    for s in servicos:
        for doc in s["docs"]:
            bruto = baixar(f"{SITE}/md/{doc['file']}").decode("utf-8")
            corpo = bruto.split("---\n", 2)[-1].lstrip("\n")
            if hashlib.sha256(corpo.encode("utf-8")).hexdigest() != doc["sha256_text"]:
                ruins.append(doc["file"])
    n = sum(len(s["docs"]) for s in servicos)
    p.checar(f"corpo de {n} documento(s) bate com o sha da captura", not ruins,
             ", ".join(ruins[:3]) if ruins else ("completo" if completo else "amostra de 3 serviços"))


def estado_do_codificador(p: Placar, gravar: bool) -> None:
    p.secao("4. onde as respostas do 2º codificador vão cair")
    try:
        antes = json.loads(baixar(f"{INSTRUMENTO}/api/state", timeout=40))
    except (urllib.error.URLError, OSError, ValueError) as e:
        p.checar("/api/state responde à leitura", False, str(e))
        return
    regs = antes.get("records") or {}
    p.checar("/api/state responde à leitura", True,
             f"{len(regs)} serviço(s), salvo em {(antes.get('saved_at') or '?')[:16]}")
    campos = {s: sum(1 for k, v in r.items() if not k.startswith("_") and v)
              for s, r in regs.items()}
    preenchidos = {s: n for s, n in campos.items() if n}
    if preenchidos:
        for s, n in sorted(preenchidos.items(), key=lambda x: -x[1]):
            print(f"        {n:2d} campo(s) preenchido(s) · {s}")
    # Resto de teste no estado é pior que estado vazio: o avaliador abre o painel,
    # vê um campo já respondido e supõe que alguém codificou aquilo.
    suspeitos = [f"{s}.{k}" for s, r in regs.items() for k, v in r.items()
                 if isinstance(v, str) and v.strip().lower() in {"teste", "test", "x", "xxx", "asd"}]
    p.checar("nenhum resto de teste no estado", not suspeitos, ", ".join(suspeitos))

    if not gravar:
        print("        (escrita não testada — rode com --gravar para fechar a volta)")
        return
    corpo = json.dumps({"records": regs}).encode("utf-8")
    req = urllib.request.Request(f"{INSTRUMENTO}/api/state", data=corpo, method="PUT",
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            ok = r.status == 200
    except (urllib.error.URLError, OSError) as e:
        p.checar("/api/state aceita escrita", False, str(e))
        return
    depois = json.loads(baixar(f"{INSTRUMENTO}/api/state", timeout=40))
    p.checar("/api/state aceita escrita", ok)
    p.checar("o que voltou é igual ao que foi",
             (depois.get("records") or {}) == regs)
    p.checar("o servidor marcou a hora da gravação",
             (depois.get("saved_at") or "") > (antes.get("saved_at") or ""))


def notebook(p: Placar) -> None:
    p.secao("5. o notebook que o avaliador abre")
    caminho = RAIZ / "notebooks" / "04-revisao-assistida.ipynb"
    if not p.checar("notebook existe", caminho.exists()):
        return
    nb = json.loads(caminho.read_text(encoding="utf-8"))
    paineis = [c for c in nb["cells"]
               if c["cell_type"] == "code" and "".join(c["source"]).startswith("R.painel(")]
    p.checar("uma célula de painel por serviço", len(paineis) == 26, f"{len(paineis)}")
    p.checar("nenhuma saída viaja no arquivo",
             all(not c.get("outputs") for c in nb["cells"] if c["cell_type"] == "code"))
    # A menção em prosa é esperada, e há uma no comentário da célula de setup
    # explicando por que o SDK não entra. O que não pode é instalar ou importar,
    # porque isso abre o caminho ao vivo — que custa chave e devolve seleção
    # diferente a cada rodada. Daí a checagem ser por forma, não por palavra.
    codigo = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    p.checar("nenhuma célula instala o SDK da Anthropic",
             not re.search(r"pip\s[^\n]*\banthropic\b", codigo, re.I))
    p.checar("nenhuma célula importa o SDK da Anthropic",
             not re.search(r"^\s*(?:import|from)\s+anthropic\b", codigo, re.M))

    ensaio = RAIZ / "notebooks" / "05-ensaio.ipynb"
    if not p.checar("notebook de ensaio existe", ensaio.exists()):
        return
    ne = json.loads(ensaio.read_text(encoding="utf-8"))
    # A célula de instalação tem de ser a MESMA nos dois, senão o ensaio deixa de
    # ensaiar o que o avaliador executa. Elas saem da mesma constante do gerador;
    # esta conferência é o que impede alguém de editar uma das duas à mão.
    p.checar("ensaio e codificação compartilham a célula de instalação",
             "".join(ne["cells"][1]["source"]) == "".join(nb["cells"][1]["source"]))
    corpo_ensaio = "\n".join("".join(c["source"]) for c in ne["cells"]
                             if c["cell_type"] == "code")
    p.checar("o ensaio nasce offline, sem servidor e sem modelo",
             "offline=True" in corpo_ensaio and "configurar(offline=True)" in corpo_ensaio)
    p.checar("o ensaio manda o cache para arquivo temporário",
             "mkdtemp" in corpo_ensaio)


def main() -> int:
    completo = "--completo" in sys.argv
    gravar = "--gravar" in sys.argv
    p = Placar()
    print(f"pré-entrega · corpus {SITE}\n              instrumento {INSTRUMENTO}")
    locais(p)
    publicado_bate(p)
    caminho_do_avaliador(p, completo)
    estado_do_codificador(p, gravar)
    notebook(p)
    print(f"\n{p.n - len(p.falhas)}/{p.n} conferências passaram")
    if p.falhas:
        print("FALHOU:")
        for f in p.falhas:
            print(f"  - {f}")
        return 1
    print("pode entregar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
