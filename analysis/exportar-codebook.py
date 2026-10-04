#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exporta o codebook para o assistente: um JSON que a página lê.

    python3 analysis/exportar-codebook.py --out ../experimented-without-consent-corpus/assistente/codebook.json
    python3 analysis/exportar-codebook.py --self-test

A fonte continua sendo `codebook.py`, que lê o instrumento congelado
(`instrument/index.html`). Este script não reescreve nada do critério: copia o
HTML exato (`crit_html`, com o SHA pinado em `CRIT_CONGELADO`) e o guia em
linguagem direta (`guia_html`, `pergunta`, `lembrete`). O que ele acrescenta
são as cinco regras gerais, redigidas para a página.

O QUE NÃO ENTRA: as âncoras do piloto (`ANCHORS`), que trazem nomes de serviço
e apontariam a resposta; e qualquer coisa do `DATA.services` do instrumento
antigo, que carrega anotações da passada 1. O self-test afirma as duas coisas.

Sem dependências externas: só a biblioteca padrão.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codebook as C  # noqa: E402
import patterns as P  # noqa: E402
import revisao as R  # noqa: E402

CONGELADO_EM = "2026-07-04"

# As regras que valem para as dez variáveis, ditas uma vez antes delas. Texto
# próprio da página: aqui não há notebook, painel nem etiqueta de tipo de
# documento (a página não mostra a etiqueta, por decisão de 03/10/2026).
REGRAS_GERAIS = [
    ("Codifique só pelo que está escrito",
     "nos documentos congelados desta página. O que você sabe da plataforma por "
     "outras fontes não entra."),
    ("Evidência é a frase exata",
     "copiada do documento, com o nome do documento de onde ela veio. O botão "
     "\"usar como evidência\" faz isso por você."),
    ("Vinculante ou não vinculante se decide pela função do documento.",
     "Política de privacidade, termos de uso, aviso de cookies e tabela de bases "
     "legais são vinculantes. Blog, central de ajuda e páginas de pesquisa não são. "
     "Na dúvida, pergunte se o documento se declara parte do acordo com o usuário."),
    ("No tem dois casos.",
     "O documento pode tratar do assunto e não oferecer o mecanismo, ou o assunto "
     "pode nunca aparecer. Nos dois casos a resposta é No; diga na evidência qual "
     "dos dois é."),
    ("Dúvida sobre a regra não trava o trabalho.",
     "Codifique a sua melhor leitura e anote a dúvida no campo Notas, no fim da "
     "tela. A discussão acontece depois, quando as duas codificações forem "
     "comparadas."),
]


def regras_gerais_html() -> str:
    lis = "".join(f"<li><b>{t}</b> {d}</li>" for t, d in REGRAS_GERAIS)
    return f"<h3>Cinco regras que valem para todas as variáveis</h3><ol>{lis}</ol>"


def sha12(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12]


def exportar() -> dict:
    variaveis = []
    for v in C.VARIAVEIS:
        k = v.crit_key
        variaveis.append({
            "vid": v.vid,
            "titulo": v.titulo,
            "regra_html": v.regra,
            "pergunta": C.pergunta(k),
            "lembrete": C.lembrete(k),
            "guia_html": C.glosa_criterio(k),
            "crit_html": C.criterio(k),
            "crit_sha": C.CRIT_CONGELADO.get(k),
            "campos": [{
                "chave": c.chave, "rotulo": c.rotulo, "tipo": c.tipo,
                "opcoes": list(c.opcoes or []), "placeholder": _texto(c.placeholder or ""),
            } for c in v.campos],
        })
    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "congelado_em": CONGELADO_EM,
        "fonte_crit": R.FONTE_CRIT,
        "servicos": list(C.SERVICOS),
        "variaveis": variaveis,
        "termos": [{"term": nome, "label": spec.get("label", nome), "flag": spec.get("flag")}
                   for nome, spec in P.PATTERNS.items()],
        "termo_para_variavel": {t: list(vs) for t, vs in R.TERMO_PARA_VARIAVEL.items()},
        "regras_gerais_html": regras_gerais_html(),
        # Ajuda por valor e por campo, do instrumento, em texto. Sem o travessão
        # tipográfico e sem a procedência (§), que aqui não ajudam.
        "ajuda_valores": {k: _texto(v[0] if isinstance(v, (list, tuple)) else v) for k, v in C.VALHELP.items()},
        "ajuda_campos": {k: _texto(v.get("note", "")) for k, v in C.FIELDHELP.items() if isinstance(v, dict) and v.get("note")},
    }


def _texto(html: str) -> str:
    import html as html_mod
    import re
    t = re.sub(r"<[^>]+>", "", html or "")
    t = html_mod.unescape(t).replace(" — ", ": ").replace("—", ":")
    return " ".join(t.split())


def escrever(destino: Path) -> dict:
    d = exportar()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return d


# ---------------------------------------------------------------- self-test

def _self_test() -> int:
    falhas = []

    def checar(desc, cond):
        print(f"  {'ok  ' if cond else 'FALHA'} {desc}")
        if not cond:
            falhas.append(desc)

    d = exportar()
    vids = [v["vid"] for v in d["variaveis"]]
    checar("dez variáveis na ordem V1..V9, KW",
           vids == ["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "KW"])
    checar("26 serviços, na ordem do instrumento", d["servicos"] == list(C.SERVICOS) and len(d["servicos"]) == 26)
    for v in d["variaveis"]:
        checar(f"{v['vid']}: pergunta, lembrete e guia presentes",
               bool(v["pergunta"]) and bool(v["lembrete"]) and bool(v["guia_html"]))
        if v["vid"] != "KW":
            checar(f"{v['vid']}: critério congelado presente e com SHA pinado",
                   bool(v["crit_html"]) and v["crit_sha"] == C.CRIT_CONGELADO[v["vid"].lower()])
            checar(f"{v['vid']}: SHA do critério bate com o HTML exportado",
                   sha12(v["crit_html"]) == v["crit_sha"])
        checar(f"{v['vid']}: todo campo tem chave, tipo e opções coerentes",
               all(c["chave"] and c["tipo"] in ("select", "checks", "text", "line")
                   and (c["tipo"] not in ("select", "checks") or len(c["opcoes"]) > 1)
                   for c in v["campos"]))
    texto_dos_guias = json.dumps([(v["guia_html"], v["crit_html"], v["regra_html"]) for v in d["variaveis"]],
                                 ensure_ascii=False)
    checar("nenhum nome de serviço no guia, no critério ou na regra",
           not any(s in texto_dos_guias for s in C.SERVICOS))
    checar("nenhuma âncora do piloto exportada", "ANCHORS" not in json.dumps(d) and "anchor" not in json.dumps(d).lower())
    checar("nenhuma anotação do instrumento antigo (DATA.services) exportada",
           not any(k in d for k in ("services", "DATA", "docs")))
    checar("12 termos, cada um com rótulo", len(d["termos"]) == 12 and all(t["label"] for t in d["termos"]))
    checar("endereço termo→variável igual ao do painel", d["termo_para_variavel"] == {t: list(v) for t, v in R.TERMO_PARA_VARIAVEL.items()})
    checar("regras gerais: cinco itens, sem travessão", d["regras_gerais_html"].count("<li>") == 5 and "—" not in d["regras_gerais_html"])
    checar("nenhum travessão em pergunta ou lembrete",
           not any("—" in (v["pergunta"] + v["lembrete"]) for v in d["variaveis"]))
    checar("ajuda por valor: 18 entradas, em texto, sem travessão",
           len(d["ajuda_valores"]) == 18 and all("<" not in t and "—" not in t for t in d["ajuda_valores"].values()))
    checar("nenhum travessão em placeholder",
           not any("—" in c["placeholder"] for v in d["variaveis"] for c in v["campos"]))
    checar("ajuda por campo: só texto, sem travessão",
           d["ajuda_campos"] and all("<" not in t and "—" not in t for t in d["ajuda_campos"].values()))

    # Escreve num temporário e relê, para pegar problema de serialização.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        alvo = Path(tmp) / "codebook.json"
        escrever(alvo)
        relido = json.loads(alvo.read_text(encoding="utf-8"))
        checar("arquivo escrito relê igual", relido["servicos"] == d["servicos"] and len(relido["variaveis"]) == 10)

    print("\n" + ("tudo ok" if not falhas else f"{len(falhas)} falha(s)"))
    return 0 if not falhas else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, help="destino do codebook.json")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return _self_test()
    if not a.out:
        ap.error("informe --out ou --self-test")
    d = escrever(a.out)
    print(f"codebook: {len(d['variaveis'])} variáveis, {len(d['servicos'])} serviços → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
