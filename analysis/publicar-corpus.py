#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publica no site do corpus o que o notebook 04 precisa: o Markdown e o runtime.

    python3 analysis/publicar-corpus.py \
        --frozen ../<repo-do-paper>/audit/frozen \
        --destino ../experimented-without-consent-corpus
    python3 analysis/publicar-corpus.py --destino ../experimented-without-consent-corpus --check

Escreve dois diretórios no destino:

    md/                 o corpus congelado em Markdown (build-md-corpus.py)
    lib/
      index.html        cópia do instrumento — é de onde o codebook é lido
      manifest.json     arquivos do runtime + sha256, para o notebook conferir
      analysis/*.py     o runtime que o notebook importa

POR QUE COPIAR O RUNTIME PARA CÁ. Os repositórios são privados; o site do corpus
é público. O revisor no Colab não consegue clonar o repositório do instrumento
sem um token, e token dentro de célula é exatamente o que não queremos pedir a
ele. Servindo os arquivos pelo mesmo host do corpus, o setup do notebook é um
download sem autenticação.

O PREÇO DISSO É DERIVA, E ELA JÁ MORDEU DUAS VEZES AQUI — o kit de julho ficou
com o corpus velho, o `const FROZEN` ficou apontando para arquivos renumerados.
Por isso a cópia não é manual: sai deste script, e `--check` falha se o que está
publicado divergir da fonte. A fonte é sempre este repositório.

O `manifest.json` traz o sha256 de cada arquivo do runtime. Isso pega download
truncado e cópia velha; não é barreira de segurança, porque quem pudesse trocar
os arquivos trocaria o manifesto junto. Serve para o que foi feito: detectar
divergência, não deter adversário.

`index.html` vai junto porque o `codebook.py` lê o codebook do instrumento em
vez de transcrevê-lo de novo, e procura o arquivo um nível acima do seu. O
`index.html` do site do corpus é outro arquivo (a página que lista os
documentos) e não é tocado: por isso a cópia vive dentro de `lib/`.

Sem dependências externas: só a biblioteca padrão.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# O que o notebook importa em tempo de execução. `build-md-corpus.py` entra
# porque o `revisao.py` carrega dele o par separar/sha256.
RUNTIME = [
    "analysis/codebook.py",
    "analysis/coding_flow.py",
    "analysis/patterns.py",
    "analysis/revisao.py",
    "analysis/build-md-corpus.py",
    "index.html",
]


def sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def publicar_runtime(destino: Path) -> dict:
    lib = destino / "lib"
    arquivos = []
    for rel in RUNTIME:
        origem = RAIZ / rel
        if not origem.exists():
            raise FileNotFoundError(f"runtime ausente na fonte: {rel}")
        alvo = lib / rel
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem, alvo)
        arquivos.append({"file": rel, "sha256": sha256(origem),
                         "bytes": origem.stat().st_size})

    manifesto = {
        "publicado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fonte": "github.com/mrcsvg/experimented-without-consent",
        "arquivos": arquivos,
    }
    (lib / "manifest.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifesto


def importavel(destino: Path) -> str | None:
    """Importa o runtime publicado num processo limpo, com só `lib/` no caminho.

    O pacote leva seis arquivos. Basta um `import` novo em qualquer um deles
    para a célula de setup morrer no Colab, e o erro não aparece aqui, onde o
    repositório inteiro está ao lado — foi exatamente assim que o
    `build-md-corpus.py` passou a carregar o `freeze-sources.py` no topo e
    deixou o runtime publicado sem subir. Este teste roda o import a partir de
    uma cópia isolada do que foi publicado, que é o que o revisor recebe.

    Devolve None se importa, ou a última linha do erro.
    """
    with tempfile.TemporaryDirectory(prefix="lib-") as tmp:
        alvo = Path(tmp) / "lib"
        shutil.copytree(destino / "lib", alvo)
        r = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'lib/analysis'); "
             "import patterns, codebook, coding_flow, revisao; "
             "assert revisao.CORPUS_PADRAO and len(codebook.SERVICOS) == 26"],
            cwd=tmp, capture_output=True, text=True)
        return None if r.returncode == 0 else (r.stderr.strip().splitlines() or ["?"])[-1]


def checar(destino: Path) -> int:
    problemas = []
    lib = destino / "lib"
    caminho = lib / "manifest.json"
    if not caminho.exists():
        print(f"FALHOU — {caminho} não existe; rode sem --check")
        return 1

    manifesto = json.loads(caminho.read_text(encoding="utf-8"))
    publicados = {a["file"]: a["sha256"] for a in manifesto["arquivos"]}

    for rel in RUNTIME:
        origem = RAIZ / rel
        alvo = lib / rel
        if rel not in publicados:
            problemas.append(f"{rel}: no runtime, fora do manifesto publicado")
            continue
        if not alvo.exists():
            problemas.append(f"{rel}: no manifesto, ausente no destino")
            continue
        if sha256(origem) != publicados[rel]:
            problemas.append(f"{rel}: publicado está velho — a fonte mudou desde a publicação")
        elif sha256(alvo) != publicados[rel]:
            problemas.append(f"{rel}: cópia no destino não bate com o manifesto")
    for extra in sorted(set(publicados) - set(RUNTIME)):
        problemas.append(f"{extra}: publicado, mas não faz parte do runtime")

    md = destino / "md" / "index.json"
    if not md.exists():
        problemas.append("md/index.json: corpus não publicado")

    erro = importavel(destino)
    if erro:
        problemas.append(f"lib/ não importa isolado (o setup do notebook morreria): {erro}")

    if problemas:
        print(f"FALHOU — {len(problemas)} problema(s):")
        for p in problemas:
            print(f"  - {p}")
        return 1
    print(f"OK — runtime em dia ({len(RUNTIME)} arquivos) e corpus publicado")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--destino", type=Path, required=True,
                    help="raiz do repositório do site do corpus")
    ap.add_argument("--frozen", type=Path, help="audit/frozen do repo do paper")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    if a.check:
        return checar(a.destino)
    if not a.frozen:
        ap.error("--frozen é obrigatório para publicar")

    # O corpus em Markdown é construído direto no destino: uma cópia a menos
    # para alguém confundir com a fonte.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "build_md_corpus", RAIZ / "analysis" / "build-md-corpus.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    build.construir(a.frozen, a.destino / "md")

    manifesto = publicar_runtime(a.destino)
    print(f"runtime: {len(manifesto['arquivos'])} arquivos → {a.destino / 'lib'}")
    return checar(a.destino)


if __name__ == "__main__":
    sys.exit(main())
