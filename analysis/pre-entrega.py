#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Confere o caminho do 2º codificador de ponta a ponta, antes de entregar.

    python3 analysis/pre-entrega.py              # ~2 min; não usa API, não escreve nada
    python3 analysis/pre-entrega.py --completo   # confere o sha dos 157 documentos
    python3 analysis/pre-entrega.py --gravar     # grava e apaga um registro no arquivo de ENSAIO

POR QUE ESTE ARQUIVO EXISTE. Os `--check` de cada script conferem o repositório
local, e o repositório local não é o que o codificador toca. Ele abre uma
página que lê o codebook, o piso, as citações e o copiloto DO SITE do corpus, e
grava as respostas num endpoint do site do instrumento. Já aconteceu de o local
estar impecável e o publicado, quebrado. Este script exercita o que está no ar.

O QUE ELE NÃO FAZ. Não chama modelo (as sugestões estão congeladas) e, sem
`--gravar`, não escreve em lugar nenhum. Com `--gravar` ele usa a chave de
ENSAIO (do Keychain, `ewc-coder2-key`/`ensaio`, ou da variável EWC_KEY_ENSAIO),
grava um registro de teste no arquivo de ensaio, confere que voltou igual e o
apaga. O arquivo real nunca é tocado.

O QUE ELE NÃO COBRE: a aparência da página no navegador. Isso se vê abrindo o
link de ensaio.
"""
from __future__ import annotations

import hashlib
import json
import os
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
ASSISTENTE = ("index.html", "assistente/app.js", "assistente/core.mjs", "assistente/copiloto.html")


def verificacoes_locais() -> list[tuple[str, list[str], Path | None]]:
    """Rótulo, argumentos e o repositório irmão de que a conferência depende."""
    md = CORPUS_LOCAL / "md"
    frozen = PAPER / "audit" / "frozen"
    return [
        ("revisao: self-test", ["analysis/revisao.py", "--self-test"], md),
        ("coding_flow: self-test", ["analysis/coding_flow.py"], None),
        ("codebook em dia com o roster", ["analysis/codebook.py", "--check"], None),
        ("corpus em Markdown íntegro",
         ["analysis/build-md-corpus.py", "--check", "--frozen", str(frozen), "--out", str(md)], frozen),
        ("assistente/ publicado = exportadores de agora",
         ["analysis/publicar-corpus.py", "--check", "--destino", str(CORPUS_LOCAL)], CORPUS_LOCAL),
        ("evidência congelada completa",
         ["analysis/congelar-sugestoes.py", "--check", "--out", str(CORPUS_LOCAL / "sugestoes")], CORPUS_LOCAL),
        ("copiloto: 26 arquivos válidos, com o prompt de hoje",
         ["analysis/copiloto.py", "--check", "--corpus", str(md), "--out", str(CORPUS_LOCAL / "assistente" / "copiloto")], md),
        ("copiloto: self-test", ["analysis/copiloto.py", "--simular", "--corpus", str(md)], md),
        ("exportar-codebook: self-test", ["analysis/exportar-codebook.py", "--self-test"], None),
        ("exportar-piso: self-test", ["analysis/exportar-piso.py", "--self-test", "--corpus", str(md)], md),
        ("concordância: region_gated fora do κ, vocabulário da V9",
         ["analysis/compute-agreement.py", "--self-test"], None),
        ("validador: self-test", ["analysis/validar-assistente.py", "--simular", "--corpus", str(md)], md),
        ("congelamento: self-test", ["analysis/congelar-sugestoes.py", "--simular", "--corpus", str(md)], md),
    ]


def sha(bruto: bytes) -> str:
    return hashlib.sha256(bruto).hexdigest()


def baixar(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def status(url: str, metodo: str = "GET", cabecalhos: dict | None = None, corpo: bytes | None = None, timeout: int = 40):
    req = urllib.request.Request(url, data=corpo, method=metodo, headers=cabecalhos or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Placar:
    def __init__(self):
        self.falhas: list[str] = []
        self.n = 0

    def secao(self, titulo: str):
        print(f"\n{titulo}")

    def checar(self, desc: str, cond: bool, detalhe: str = ""):
        self.n += 1
        print(("  ok    " if cond else "  FALHA ") + desc + (f" ({detalhe})" if detalhe else ""))
        if not cond:
            self.falhas.append(desc)
        return cond


def locais(p: Placar) -> None:
    p.secao("1. o repositório local")
    env = {**os.environ, "CORPUS_MD": str(CORPUS_LOCAL / "md")}
    for desc, args, exige in verificacoes_locais():
        if exige is not None and not exige.exists():
            print(f"  pulou {desc}: falta {exige}")
            continue
        r = subprocess.run([sys.executable, *args], cwd=RAIZ, env=env, capture_output=True, text=True)
        saida = [l for l in ((r.stdout or "") + (r.stderr or "")).strip().splitlines() if l.strip()]
        if r.returncode == 0 and saida and saida[0].startswith("pulou"):
            print(f"  pulou {desc}: {saida[0][7:]}")
            continue
        p.checar(desc, r.returncode == 0, "" if r.returncode == 0 else saida[-1] if saida else "")
    # Os testes em JavaScript: o núcleo do servidor e o núcleo da página.
    r = subprocess.run(["node", "--test", "server/*.test.mjs", "assistente/*.test.mjs"],
                       cwd=RAIZ, capture_output=True, text=True)
    m = re.search(r"ℹ pass (\d+)", r.stdout or "")
    f = re.search(r"ℹ fail (\d+)", r.stdout or "")
    p.checar("servidor e página: testes em Node", r.returncode == 0 and f and f.group(1) == "0",
             f"{m.group(1) if m else '?'} passaram" if r.returncode == 0 else (r.stderr or r.stdout or "").strip().splitlines()[-1])


def pagina_no_repositorio(p: Placar) -> None:
    p.secao("2. a página, no repositório")
    for rel in ASSISTENTE:
        p.checar(f"{rel} existe", (RAIZ / rel).exists())
    index = (RAIZ / "index.html").read_text(encoding="utf-8")
    p.checar("index.html é o assistente (carrega assistente/app.js)", "/assistente/app.js" in index)
    p.checar("index.html pede noindex", "noindex" in index)
    textos = "".join((RAIZ / rel).read_text(encoding="utf-8") for rel in ASSISTENTE)
    p.checar("nenhum travessão nos textos da página", "—" not in textos)
    app = (RAIZ / "assistente" / "app.js").read_text(encoding="utf-8")
    p.checar("a página não lê a etiqueta role nem dados do instrumento antigo",
             ".role" not in app and "DATA.services" not in app and "ANCHORS" not in app)
    p.checar("a página só aceita corpus alternativo em localhost",
             'location.hostname === "localhost"' in app)
    vi = (RAIZ / ".vercelignore").read_text(encoding="utf-8") if (RAIZ / ".vercelignore").exists() else ""
    p.checar(".vercelignore deixa fora análise, instrumento antigo, notebooks e docs",
             all(x in vi for x in ("analysis/", "instrument/", "notebooks/", "docs/")))
    p.checar("o instrumento antigo continua no repositório, fora da raiz",
             (RAIZ / "instrument" / "index.html").exists())
    p.checar("os notebooks do Colab saíram",
             not (RAIZ / "notebooks" / "04-revisao-assistida.ipynb").exists()
             and not (RAIZ / "analysis" / "gerar-notebook-revisao.py").exists())


def publicado_bate(p: Placar) -> None:
    p.secao("3. o que está no ar é o que está no repositório")
    # Site do corpus: assistente/ e os índices.
    try:
        man = json.loads(baixar(f"{SITE}/assistente/manifest.json"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        p.checar("manifesto do assistente responde", False, str(e))
        return
    p.checar("manifesto do assistente responde", True, f"publicado {man['publicado_em'][:10]}, {len(man['arquivos'])} arquivos")
    local_man = CORPUS_LOCAL / "assistente" / "manifest.json"
    p.checar("manifesto no ar = repo", local_man.exists() and json.loads(local_man.read_text())["arquivos"] == man["arquivos"])
    for rel in ("codebook.json", "piso/index.json", "copiloto/index.json", "copiloto/prompt.md", "piso/zalando.json", "copiloto/zalando.json"):
        esperado = next((a["sha256"] for a in man["arquivos"] if a["file"] == rel), None)
        try:
            remoto = baixar(f"{SITE}/assistente/{rel}")
        except (urllib.error.URLError, OSError) as e:
            p.checar(f"assistente/{rel} no ar", False, str(e))
            continue
        p.checar(f"assistente/{rel} no ar = manifesto", esperado is not None and sha(remoto) == esperado)
    for nome, caminho in (("corpus", "md/index.json"), ("evidência", "sugestoes/index.json")):
        try:
            remoto = baixar(f"{SITE}/{caminho}")
        except (urllib.error.URLError, OSError) as e:
            p.checar(f"{nome}: índice responde", False, str(e))
            continue
        local = CORPUS_LOCAL / caminho
        p.checar(f"{nome}: índice no ar = repo", local.exists() and sha(local.read_bytes()) == sha(remoto))
    cod, _ = status(f"{SITE}/lib/index.html")
    p.checar("lib/ (runtime do notebook e instrumento antigo) saiu do ar", cod == 404, f"HTTP {cod}")
    # O prompt do copiloto vivo é o que gerou os 26 arquivos.
    sys.path.insert(0, str(RAIZ / "analysis"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("copiloto", RAIZ / "analysis" / "copiloto.py")
    CP = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CP)
    cb = CP.EC.exportar()
    idx = json.loads(baixar(f"{SITE}/assistente/copiloto/index.json"))
    p.checar("o prompt do copiloto de hoje é o que gerou as sugestões publicadas",
             idx["prompt_sha"] == CP.impressao_do_prompt(cb), f"vivo {CP.impressao_do_prompt(cb)} · publicado {idx['prompt_sha']}")
    p.checar("copiloto cobre os 26 serviços sem resposta inválida",
             len(idx["servicos"]) == 26 and not any(s["invalida"] for s in idx["servicos"]))
    # A evidência congelada (citações) continua presa ao prompt que a gerou.
    R = importlib.import_module("revisao")
    sidx = json.loads(baixar(f"{SITE}/sugestoes/index.json"))
    congeladas = {json.loads((CORPUS_LOCAL / "sugestoes" / a["file"]).read_text())["prompt"] for a in sidx["arquivos"]}
    p.checar("o prompt das citações de hoje é o que gerou a evidência congelada",
             congeladas == {R.impressao_do_prompt()}, f"vivo {R.impressao_do_prompt()} · congelado {sorted(congeladas)}")

    # Site do instrumento: a página publicada é a do repositório.
    for rel in ASSISTENTE:
        url = f"{INSTRUMENTO}/" if rel == "index.html" else f"{INSTRUMENTO}/{rel}"
        try:
            remoto = baixar(url)
        except (urllib.error.URLError, OSError) as e:
            p.checar(f"{rel} no ar = repo", False, str(e))
            continue
        p.checar(f"{rel} no ar = repo", sha(remoto) == sha((RAIZ / rel).read_bytes()))
    cod, _ = status(f"{INSTRUMENTO}/instrument/index.html")
    p.checar("o instrumento antigo não está publicado", cod == 404, f"HTTP {cod}")
    cod, _ = status(f"{INSTRUMENTO}/analysis/codebook.py")
    p.checar("analysis/ não está publicado", cod == 404, f"HTTP {cod}")


def caminho_do_codificador(p: Placar, completo: bool) -> None:
    p.secao("4. o que a página lê do site, como ela lê")
    try:
        cb = json.loads(baixar(f"{SITE}/assistente/codebook.json"))
        idx = json.loads(baixar(f"{SITE}/md/index.json"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        p.checar("codebook e índice do corpus respondem", False, str(e))
        return
    p.checar("codebook e índice do corpus respondem", True)
    p.checar("codebook: 10 variáveis, 26 serviços, critério congelado com SHA",
             len(cb["variaveis"]) == 10 and len(cb["servicos"]) == 26
             and all(v["crit_sha"] for v in cb["variaveis"] if v["vid"] != "KW"))
    p.checar("corpus completo pelo site", len(idx["services"]) == 26 and sum(len(s["docs"]) for s in idx["services"]) == 157,
             f"{len(idx['services'])} serviços · {sum(len(s['docs']) for s in idx['services'])} documentos")
    p.checar("corpus é o congelado de vantagem UE",
             idx.get("vantage") == "IT" and (idx.get("frozen_at") or "").startswith("2026-08"))
    nomes = {s["name"] for s in idx["services"]}
    p.checar("os 26 nomes do codebook existem no corpus", set(cb["servicos"]) <= nomes)
    slug = next(s["slug"] for s in idx["services"] if s["name"] == "Zalando")
    piso = json.loads(baixar(f"{SITE}/assistente/piso/{slug}.json"))
    sug = json.loads(baixar(f"{SITE}/sugestoes/{slug}.json"))
    cop = json.loads(baixar(f"{SITE}/assistente/copiloto/{slug}.json"))
    p.checar("piso do Zalando: hits de V8 com nota de falso positivo, sem role",
             any(h["flag"] for h in piso["por_variavel"].get("V8", [])) and '"role"' not in json.dumps(piso))
    p.checar("piso traz o log sugerido, uma linha por documento",
             len(piso["log_sugerido"].splitlines()) == len([d for d in piso["docs"] if d["log_line"]]))
    p.checar("citações do Zalando: só frase, documento e localização",
             all(set(c) <= {"doc", "file", "onde", "role", "verbatim"} for lista in sug["citacoes"].values() for c in lista)
             and "sugestao" not in json.dumps(sug))
    p.checar("copiloto do Zalando: 9 variáveis com campos, razão, confiança e citações",
             set(cop["variaveis"]) == {f"V{i}" for i in range(1, 10)}
             and all({"campos", "razao", "confianca", "citacoes"} <= set(v) for v in cop["variaveis"].values()))
    p.checar("copiloto não traz etiqueta role nem nada da passada 1",
             '"role"' not in json.dumps(cop) and "passada 1" not in json.dumps(cop) and "codificado em" not in json.dumps(cop))
    cod_md, cab = (lambda r: (r.status, r.headers.get("content-type", "")))(urllib.request.urlopen(f"{SITE}/md/{piso['docs'][0]['file']}", timeout=60))
    p.checar("o Markdown congelado abre como texto no navegador", cod_md == 200 and cab.startswith("text/plain"), cab)

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


def chave_de_ensaio() -> str | None:
    if os.environ.get("EWC_KEY_ENSAIO"):
        return os.environ["EWC_KEY_ENSAIO"]
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", "ewc-coder2-key", "-a", "ensaio", "-w"],
                           capture_output=True, text=True)
        return r.stdout.strip() or None
    except OSError:
        return None


def servidor(p: Placar, gravar: bool) -> None:
    p.secao("5. o servidor onde as respostas caem")
    cod, corpo = status(f"{INSTRUMENTO}/api/state")
    p.checar("/api/state recusa leitura sem chave", cod == 401, f"HTTP {cod}")
    cod, corpo = status(f"{INSTRUMENTO}/api/state", cabecalhos={"x-ewc-key": "chave-errada"})
    p.checar("/api/state recusa chave inválida", cod == 401, f"HTTP {cod}")
    chave = chave_de_ensaio()
    if not chave:
        print("  pulou leitura e escrita de ensaio: sem chave de ensaio (Keychain ou EWC_KEY_ENSAIO)")
        return
    cab = {"x-ewc-key": chave, "content-type": "application/json"}
    cod, corpo = status(f"{INSTRUMENTO}/api/state", cabecalhos=cab)
    if not p.checar("/api/state responde à chave de ensaio", cod == 200, f"HTTP {cod}"):
        return
    antes = json.loads(corpo)
    p.checar("a chave de ensaio cai no arquivo de ensaio", antes.get("modo") == "ensaio")
    regs = antes.get("records") or {}
    print(f"        ensaio: {len(regs)} serviço(s) gravado(s)")
    if not gravar:
        print("        (escrita não testada; rode com --gravar para fechar a volta no ensaio)")
        return
    base = (regs.get("Zalando") or {}).get("_ts") or 0
    corpo_put = json.dumps({"servico": "Zalando", "registro": {"v1_code": "1", "notes": "pre-entrega --gravar"}, "base_ts": base}).encode("utf-8")
    cod, corpo = status(f"{INSTRUMENTO}/api/state", "PUT", cab, corpo_put)
    p.checar("/api/state aceita escrita com a chave de ensaio", cod == 200, f"HTTP {cod} {corpo[:80]!r}")
    cod, corpo = status(f"{INSTRUMENTO}/api/state", cabecalhos=cab)
    depois = json.loads(corpo)
    p.checar("o que voltou é o que foi, com _ts do servidor",
             (depois["records"].get("Zalando") or {}).get("notes") == "pre-entrega --gravar"
             and (depois["records"]["Zalando"].get("_ts") or 0) > base)
    cod, corpo = status(f"{INSTRUMENTO}/api/state", "PUT", cab,
                        json.dumps({"servico": "Zalando", "registro": {"v1_code": "2"}, "base_ts": base}).encode("utf-8"))
    p.checar("gravação com versão velha é recusada (409)", cod == 409, f"HTTP {cod}")
    # Limpa o que este teste pôs, restaurando o registro anterior se havia um.
    anterior = regs.get("Zalando")
    ts_atual = depois["records"]["Zalando"]["_ts"]
    if anterior:
        cod, _ = status(f"{INSTRUMENTO}/api/state", "PUT", cab,
                        json.dumps({"servico": "Zalando", "registro": {k: v for k, v in anterior.items() if k not in ("_ts", "service")}, "base_ts": ts_atual}).encode("utf-8"))
        p.checar("registro anterior do ensaio restaurado", cod == 200, f"HTTP {cod}")
    else:
        cod, _ = status(f"{INSTRUMENTO}/api/state", "DELETE", cab)
        p.checar("ensaio zerado depois do teste", cod == 200, f"HTTP {cod}")


def da_pagina_ao_kappa(p: Placar) -> None:
    """O que a página grava tem de entrar no cálculo de concordância sem conversão.

    Foi nesta costura que se achou, em 02/10, a V9 com grafias diferentes nas
    duas passadas. O registro é montado aqui do jeito que a página monta: um
    valor por campo do codebook, no formato {"records": {serviço: registro}}.
    """
    p.secao("6. do que a página grava até o κ")
    passada1 = PAPER / "audit" / "coded-data.json"
    if not passada1.exists():
        print(f"  pulou a ponte: falta {passada1}")
        return
    sys.path.insert(0, str(RAIZ / "analysis"))
    import importlib
    C = importlib.import_module("codebook")
    records = {}
    for i, servico in enumerate(("Pinterest", "Booking.com")):
        reg = {"service": servico, "_ts": 1000 + i}
        for v in C.VARIAVEIS:
            for c in v.campos:
                ops = [o for o in c.opcoes if o]
                reg[c.chave] = ops[0] if c.tipo == "select" else ops[:2] if c.tipo == "checks" else "x"
        records[servico] = reg
    with tempfile.TemporaryDirectory(prefix="ponte-") as tmp:
        arq = Path(tmp) / "ensaio.json"
        arq.write_text(json.dumps({"records": records, "saved_at": "2026-10-03T00:00:00Z", "modo": "ensaio"}), encoding="utf-8")
        r = subprocess.run([sys.executable, str(RAIZ / "analysis" / "compute-agreement.py"), str(passada1), str(arq)],
                           capture_output=True, text=True)
    out = r.stdout or ""
    p.checar("o cálculo lê o arquivo do servidor sem conversão", r.returncode == 0,
             (r.stderr or "").strip().splitlines()[-1] if r.stderr else "")
    p.checar("os serviços codificados são pareados com a passada 1", "Serviços pareados: 2" in out)
    p.checar("todas as variáveis do κ aparecem na tabela",
             all(v in out for v in ("v1_code", "v5_optout", "v9_register", "v9_where")))
    p.checar("region_gated fica fora do κ, à parte", "v4_region_gated: FORA DO κ" in out)


def main() -> int:
    completo = "--completo" in sys.argv
    gravar = "--gravar" in sys.argv
    p = Placar()
    print(f"pré-entrega · corpus {SITE}\n              instrumento {INSTRUMENTO}")
    locais(p)
    pagina_no_repositorio(p)
    publicado_bate(p)
    caminho_do_codificador(p, completo)
    servidor(p, gravar)
    da_pagina_ao_kappa(p)
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
