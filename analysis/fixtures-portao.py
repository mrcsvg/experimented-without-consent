#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Casos de teste da trava (portão), gerados pelo Python para o JavaScript reproduzir.

    python3 analysis/fixtures-portao.py --out assistente/test/portao.json

A regra do portão vive em `coding_flow.Fluxo.faltando`: toda pergunta
respondida e o campo de evidência preenchido; `v6_which` exigido quando
`v6_optin_beta` = Yes; o log de palavras-chave obrigatório. A página do
assistente reimplementa a regra em `assistente/core.mjs`. Em vez de confiar
que as duas cópias dizem o mesmo, este script monta registros parciais e grava
o que o Python espera; o teste em JavaScript percorre a lista e compara.

Sem dependências externas: só a biblioteca padrão.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codebook as C  # noqa: E402
import coding_flow as F  # noqa: E402


def _primeira_opcao(campo):
    return next(o for o in campo.opcoes if o)


def casos() -> list[dict]:
    tmp = Path(tempfile.mkdtemp()) / "estado.json"
    estado = F.Estado(cache=tmp, offline=True)
    saida = []

    def registrar(vid: str, reg: dict, nome: str):
        f = F.Fluxo("Pinterest", estado)
        f.rec = dict(reg)
        n = [v.vid for v in f.passos].index(vid)
        saida.append({"vid": vid, "nome": nome, "reg": reg,
                      "esperado": [list(p) for p in f.faltando(n)]})

    for v in C.VARIAVEIS:
        registrar(v.vid, {}, "vazio")
        # Só as perguntas, sem evidência.
        so_perguntas = {}
        for c in v.campos:
            if c.tipo == "select":
                so_perguntas[c.chave] = _primeira_opcao(c)
            elif c.tipo == "checks":
                so_perguntas[c.chave] = [_primeira_opcao(c)]
        if so_perguntas:
            registrar(v.vid, so_perguntas, "só as perguntas")
        # Tudo preenchido.
        completo = dict(so_perguntas)
        for c in v.campos:
            if c.tipo in ("text", "line"):
                completo[c.chave] = "texto"
        registrar(v.vid, completo, "completo")
        # Lista vazia conta como não respondido.
        for c in v.campos:
            if c.tipo == "checks":
                registrar(v.vid, {**completo, c.chave: []}, f"{c.chave} vazio")
        # Texto só com espaços não conta? (o Python trata "" como vazio; espaços passam)
        for c in v.campos:
            if c.tipo == "text":
                registrar(v.vid, {**completo, c.chave: ""}, f"{c.chave} vazio")

    # V6: a linha exigida pela resposta.
    registrar("V6", {"v6_optin_beta": "Yes"}, "beta Yes sem qual")
    registrar("V6", {"v6_optin_beta": "Yes", "v6_which": "TestFlight"}, "beta Yes com qual")
    registrar("V6", {"v6_optin_beta": "No"}, "beta No sem qual")
    # KW: o log é obrigatório.
    registrar("KW", {}, "log vazio")
    registrar("KW", {"keyword_log": "01.md: experiment:0"}, "log preenchido")
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    lista = casos()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    # As definições dos campos vão junto, para o teste em JavaScript não depender
    # do codebook.json publicado no repositório do corpus.
    variaveis = [{"vid": v.vid, "titulo": v.titulo,
                  "campos": [{"chave": c.chave, "rotulo": c.rotulo, "tipo": c.tipo,
                              "opcoes": list(c.opcoes or [])} for c in v.campos]}
                 for v in C.VARIAVEIS]
    # As regras das notas por trecho vêm do mesmo exportador que a página lê.
    import importlib.util
    spec = importlib.util.spec_from_file_location("exportar_codebook", Path(__file__).resolve().parent / "exportar-codebook.py")
    EC = importlib.util.module_from_spec(spec); spec.loader.exec_module(EC)
    a.out.write_text(json.dumps({
        "origem": "analysis/fixtures-portao.py, a partir de coding_flow.Fluxo.faltando",
        "variaveis": variaveis,
        "servicos": list(C.SERVICOS),
        "notas": EC.NOTAS,
        "tipos_doc": EC.TIPOS_DOC,
        "extras": EC.EXTRAS,
        "casos": lista,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"portão: {len(lista)} casos → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
