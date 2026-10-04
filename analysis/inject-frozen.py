#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Injeta o mapa do corpus congelado no instrumento.

    python3 inject-frozen.py --manifest <frozen>/manifest.json --html instrument/index.html

O `index.html` é single-file por desenho — sem build, sem dependência — então o
mapa `const FROZEN` entra por substituição de linha em vez de virar um fetch.
Rodar de novo depois de novas capturas simplesmente reescreve a linha.

Só entram documentos que passaram na porta de espessura: apontar o avaliador
para um arquivo vazio é pior que deixá-lo abrir a página, porque parece
congelado. O que ficar de fora continua como link ao vivo, que é o
comportamento anterior.

O caminho gravado é relativo à raiz do kit (`text/<serviço>/<arquivo>.txt`),
que é como o corpus chega ao avaliador via `freeze-sources.py package`.
"""
import argparse, json, re, sys
from pathlib import Path

MARK = re.compile(r"^const FROZEN = \{.*?\};$", re.M | re.S)
BASE = re.compile(r'^const CORPUS_BASE = ".*?";$', re.M)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--html", default="instrument/index.html")
    ap.add_argument("--min-text", type=int, default=1000)
    ap.add_argument("--base-url", default=None,
                    help="onde o corpus é servido, ex.: https://corpus-....vercel.app/ "
                         "— com isto o documento abre num clique; sem, o avaliador "
                         "lê da pasta do zip. Passe '' para voltar ao modo zip.")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    man = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    frozen = {}
    for d in man["documents"]:
        if d.get("error") or not d.get("text_path"):
            continue
        if d.get("capture_method") != "manual" and (d.get("text_chars") or 0) < a.min_text:
            continue
        frozen[d["url"]] = {"f": d["text_path"], "c": d["text_chars"]}

    html = Path(a.html).read_text(encoding="utf-8")
    if not MARK.search(html):
        sys.exit(f"não achei a linha `const FROZEN = {{...}};` em {a.html} — "
                 "o instrumento não está preparado para o corpus.")

    # separadores compactos: o mapa entra numa linha só, e são ~145 entradas
    linha = "const FROZEN = " + json.dumps(frozen, ensure_ascii=False,
                                           separators=(",", ":")) + ";"
    novo = MARK.sub(lambda _: linha, html, count=1)

    if a.base_url is not None:
        if not BASE.search(novo):
            sys.exit("não achei a linha `const CORPUS_BASE = \"...\";`")
        # barra final obrigatória: o mapa guarda caminho relativo (text/x/y.txt),
        # e sem ela a concatenação come o último segmento da base.
        b = a.base_url.strip()
        if b and not b.endswith("/"):
            b += "/"
        novo = BASE.sub(lambda _: f'const CORPUS_BASE = "{b}";', novo, count=1)
        print(f"  base do corpus: {b or '(vazia — modo zip)'}")

    manual = sum(1 for d in man["documents"]
                 if d.get("capture_method") == "manual" and d["url"] in frozen)
    print(f"{len(frozen)} documentos mapeados ({manual} capturados à mão)")
    print(f"  fora do mapa (seguem como link ao vivo): "
          f"{len(man['documents']) - len(frozen)}")
    if a.dry_run:
        print("  --dry-run: nada escrito")
        return 0
    Path(a.html).write_text(novo, encoding="utf-8")
    print(f"  {a.html} atualizado ({len(linha):,} bytes na linha do mapa)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
