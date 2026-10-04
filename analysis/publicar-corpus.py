#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publica no site do corpus o que a página do assistente precisa.

    python3 analysis/publicar-corpus.py \\
        --frozen ../<repo-do-paper>/audit/frozen \\
        --destino ../experimented-without-consent-corpus
    python3 analysis/publicar-corpus.py --destino ../experimented-without-consent-corpus --so-assistente
    python3 analysis/publicar-corpus.py --destino ../experimented-without-consent-corpus --check

Escreve no destino:

    md/                       o corpus congelado em Markdown (build-md-corpus.py)
    assistente/
      codebook.json           exportar-codebook.py
      piso/<slug>.json        exportar-piso.py (26 + index.json)
      copiloto/<slug>.json    copiloto.py (26 + prompt.md + index.json); NÃO é
                              regenerado aqui, porque custa uma chamada ao modelo
                              por serviço. Só entra no manifesto.
      manifest.json           sha256 de cada arquivo de assistente/

POR QUE PUBLICAR AQUI. O repositório do instrumento é público, mas a página roda
no site do instrumento e lê os dados do site do corpus, que já serve o Markdown
e as citações com CORS aberto. Um só lugar para tudo o que é congelado.

O PREÇO É DERIVA, E ELA JÁ MORDEU: o kit de julho ficou com o corpus velho, o
`const FROZEN` ficou apontando para arquivos renumerados. Por isso a cópia não é
manual: sai deste script, e `--check` falha se o codebook ou o piso publicados
divergirem do que os exportadores gerariam agora (ignorando só a data de
geração), ou se o manifesto não bater com os arquivos.

O QUE NÃO VAI MAIS. `lib/` (o runtime do notebook e uma cópia do instrumento
antigo com anotações da passada 1) saiu em 03/10/2026. O `--check` reprova se
a pasta reaparecer.

Sem dependências externas: só a biblioteca padrão.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "analysis"))

IGNORAR_AO_COMPARAR = {"gerado_em", "corpus_built_at"}


def sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _modulo(nome: str):
    spec = importlib.util.spec_from_file_location(nome.replace("-", "_").replace(".py", ""),
                                                  RAIZ / "analysis" / nome)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _sem_datas(d):
    if isinstance(d, dict):
        return {k: _sem_datas(v) for k, v in d.items() if k not in IGNORAR_AO_COMPARAR}
    if isinstance(d, list):
        return [_sem_datas(x) for x in d]
    return d


def escrever_manifesto(destino: Path) -> dict:
    pasta = destino / "assistente"
    arquivos = []
    for p in sorted(pasta.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            arquivos.append({"file": str(p.relative_to(pasta)), "sha256": sha256(p),
                             "bytes": p.stat().st_size})
    manifesto = {
        "publicado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fonte": "github.com/mrcsvg/experimented-without-consent",
        "arquivos": arquivos,
    }
    (pasta / "manifest.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return manifesto


def publicar_assistente(destino: Path) -> dict:
    import revisao as R
    corpus = R.Corpus(destino / "md")
    EC = _modulo("exportar-codebook.py")
    EP = _modulo("exportar-piso.py")
    EC.escrever(destino / "assistente" / "codebook.json")
    EP.escrever_todos(corpus, destino / "assistente" / "piso")
    return escrever_manifesto(destino)


def checar(destino: Path) -> int:
    problemas = []
    pasta = destino / "assistente"
    manifesto_p = pasta / "manifest.json"
    if (destino / "lib").exists():
        problemas.append("lib/ existe no destino: o runtime do notebook e o instrumento antigo saíram em 03/10/2026")
    if not (destino / "md" / "index.json").exists():
        problemas.append("md/index.json: corpus não publicado")
    if not manifesto_p.exists():
        problemas.append("assistente/manifest.json não existe; rode sem --check")
    else:
        manifesto = json.loads(manifesto_p.read_text(encoding="utf-8"))
        publicados = {a["file"]: a["sha256"] for a in manifesto["arquivos"]}
        presentes = {str(p.relative_to(pasta)) for p in pasta.rglob("*")
                     if p.is_file() and p.name != "manifest.json"}
        for rel in sorted(presentes - set(publicados)):
            problemas.append(f"assistente/{rel}: no destino, fora do manifesto")
        for rel in sorted(set(publicados) - presentes):
            problemas.append(f"assistente/{rel}: no manifesto, ausente no destino")
        for rel in sorted(presentes & set(publicados)):
            if sha256(pasta / rel) != publicados[rel]:
                problemas.append(f"assistente/{rel}: não bate com o manifesto")
        for obrigatorio in ("codebook.json", "piso/index.json", "copiloto/index.json", "copiloto/prompt.md"):
            if obrigatorio not in presentes:
                problemas.append(f"assistente/{obrigatorio}: ausente")

    # O que está publicado é o que os exportadores gerariam agora?
    try:
        import revisao as R
        corpus = R.Corpus(destino / "md")
        EC = _modulo("exportar-codebook.py")
        EP = _modulo("exportar-piso.py")
        cb_pub = json.loads((pasta / "codebook.json").read_text(encoding="utf-8"))
        if _sem_datas(cb_pub) != _sem_datas(EC.exportar()):
            problemas.append("assistente/codebook.json: publicado está velho; a fonte mudou")
        import codebook as C
        for servico in C.SERVICOS:
            slug = corpus.por_servico[servico]["slug"]
            p = pasta / "piso" / f"{slug}.json"
            if not p.exists():
                problemas.append(f"assistente/piso/{slug}.json: ausente")
                continue
            if _sem_datas(json.loads(p.read_text(encoding="utf-8"))) != _sem_datas(EP.exportar_um(servico, corpus)):
                problemas.append(f"assistente/piso/{slug}.json: publicado está velho; o corpus ou o piso mudaram")
        for p in (pasta / "piso").glob("*.json"):
            if '"role"' in p.read_text(encoding="utf-8"):
                problemas.append(f"assistente/piso/{p.name}: traz etiqueta role")
    except Exception as e:  # sem corpus ou sem exportadores, o manifesto já foi conferido
        problemas.append(f"não consegui comparar com os exportadores: {e}")

    if problemas:
        print(f"FALHOU: {len(problemas)} problema(s):")
        for p in problemas:
            print(f"  - {p}")
        return 1
    n = len(json.loads(manifesto_p.read_text(encoding="utf-8"))["arquivos"])
    print(f"OK: assistente/ em dia ({n} arquivos no manifesto) e corpus publicado")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--destino", type=Path, required=True,
                    help="raiz do repositório do site do corpus")
    ap.add_argument("--frozen", type=Path, help="audit/frozen do repo do paper (reconstrói md/)")
    ap.add_argument("--so-assistente", action="store_true",
                    help="não reconstruir md/; só regenerar assistente/ e o manifesto")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    if a.check:
        return checar(a.destino)
    if not a.frozen and not a.so_assistente:
        ap.error("--frozen é obrigatório para publicar (ou use --so-assistente)")

    if a.frozen:
        # O corpus em Markdown é construído direto no destino: uma cópia a menos
        # para alguém confundir com a fonte.
        build = _modulo("build-md-corpus.py")
        build.construir(a.frozen, a.destino / "md")

    manifesto = publicar_assistente(a.destino)
    print(f"assistente: {len(manifesto['arquivos'])} arquivos → {a.destino / 'assistente'}")
    return checar(a.destino)


if __name__ == "__main__":
    sys.exit(main())
