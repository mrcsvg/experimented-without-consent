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
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codebook as C  # noqa: E402
import patterns as P  # noqa: E402
import revisao as R  # noqa: E402

CONGELADO_EM = "2026-07-04"

# As regras que valem para as dez variáveis, ditas uma vez antes delas. Texto
# próprio da página: aqui não há notebook nem painel, e a etiqueta `role` da
# passada 1 continua fora (decisão de 03/10/2026). O tipo de cada documento é
# metadado do corpus (analysis/tipos-doc.json, decisão de 04/10/2026): a página
# o mostra ao lado de cada trecho e não pergunta nada sobre documentos.
REGRAS_GERAIS = [
    ("Codifique só pelo que está escrito",
     "nos documentos congelados desta página. O que você sabe da plataforma por "
     "outras fontes não entra."),
    ("Evidência são os trechos que você marcou.",
     "A página monta a evidência de cada variável com os trechos marcados, a nota "
     "e o comentário de cada um, e o nome do documento de onde vieram. Você não "
     "digita evidência."),
    ("Vinculante ou não vinculante já vem decidido para cada documento.",
     "Política de privacidade, termos de uso, aviso de cookies e tabela de bases "
     "legais são vinculantes. Blog, central de ajuda e páginas de pesquisa não são. "
     "O tipo de cada documento aparece ao lado de cada trecho; se achar que um "
     "está errado, anote em Notas."),
    ("No tem dois casos.",
     "O documento pode tratar do assunto e não oferecer o mecanismo, ou o assunto "
     "pode nunca aparecer. Nos dois casos a resposta é No; diga na evidência qual "
     "dos dois é."),
    ("Dúvida sobre a regra não trava o trabalho.",
     "Codifique a sua melhor leitura e anote a dúvida no campo Notas, no fim da "
     "tela. A discussão acontece depois, quando as duas codificações forem "
     "comparadas."),
]


# ---------------------------------------------------------- notas por trecho
# Decisão de 04/10/2026: o codificador dá uma nota a cada trecho e a resposta da
# variável é calculada do critério congelado. As opções de nota são as do
# próprio codebook (V2, V4, V5) ou tags que apontam para os campos (V3). "x",
# não se aplica, existe em toda variável e não entra aqui. A ausência (0, No,
# none, not stated) é o que sobra quando nenhum trecho recebe nota.
#
# Dois rótulos por opção. `rotulo` é o que o copiloto recebeu na mensagem
# (analysis/copiloto.py: montar_mensagem) e está congelado com os 26 arquivos:
# mudá-lo invalidaria o que foi publicado. `tela` é o que o codificador lê
# (reescrito em 05/10/2026 depois do teste do Marcus: "só melhorar" e "testar
# usuários" eram estranhos). O valor e o critério são os mesmos nos dois.
NOTAS = {
    "V1": {"modo": "um", "opcoes": [
        {"valor": "1", "rotulo": "1 · só melhorar", "tela": "1 · só fala em melhorar o serviço"},
        {"valor": "2", "rotulo": "2 · testar usuários", "tela": "2 · admite testar, sem dizer como"},
        {"valor": "3", "rotulo": "3 · experimento, A/B, randomização", "tela": "3 · nomeia experimento, teste A/B ou randomização"}]},
    "V2": {"modo": "varios", "opcoes": [
        {"valor": "service improvement", "rotulo": "melhoria do serviço", "tela": "melhoria do serviço"},
        {"valor": "research", "rotulo": "pesquisa", "tela": "pesquisa"},
        {"valor": "human-subjects research", "rotulo": "pesquisa com humanos", "tela": "pesquisa com seres humanos"},
        {"valor": "social-good/community", "rotulo": "bem da comunidade", "tela": "bem social ou da comunidade"}]},
    "V3": {"modo": "varios", "opcoes": [
        {"valor": "activities", "rotulo": "nomeia atividades", "tela": "nomeia o que é testado (features, layout, ranking)", "campo": "v3_activities"},
        {"valor": "specific", "rotulo": "experimento específico", "tela": "descreve um experimento específico", "campo": "v3_specific"},
        {"valor": "pricing", "rotulo": "preço como alvo", "tela": "preço é alvo de teste", "campo": "v3_pricing"}]},
    "V4": {"modo": "varios", "opcoes": [
        {"valor": "legitimate interest", "rotulo": "interesse legítimo", "tela": "interesse legítimo"},
        {"valor": "consent", "rotulo": "consentimento", "tela": "consentimento"},
        {"valor": "contract", "rotulo": "contrato", "tela": "contrato"}]},
    "V5": {"modo": "um", "opcoes": [
        {"valor": "GDPR-objection-only", "rotulo": "só a objeção genérica do GDPR", "tela": "só a objeção genérica do GDPR"},
        {"valor": "cookie/ads-only", "rotulo": "só cookies ou anúncios", "tela": "só opt-out de cookies ou anúncios"},
        {"valor": "dedicated", "rotulo": "opt-out dedicado a experimentos", "tela": "opt-out dedicado a experimentos"},
        {"valor": "opt-in", "rotulo": "opt-in", "tela": "opt-in: só participa quem aceita"}]},
    "V6": {"modo": "um", "opcoes": [{"valor": "sim", "rotulo": "programa beta ou opt-in", "tela": "descreve programa beta ou opt-in"}]},
    "V7": {"modo": "um", "opcoes": [{"valor": "sim", "rotulo": "é debriefing", "tela": "avisa depois que a pessoa participou"}]},
    "V8": {"modo": "um", "opcoes": [{"valor": "sim", "rotulo": "revisão ética, comitê ou risco", "tela": "menciona revisão ética, comitê ou avaliação de risco"}]},
    "V9": {"modo": "um", "opcoes": [{"valor": "sim", "rotulo": "divulga experimentação aqui", "tela": "este documento divulga experimentação"}]},
}

# O que o copiloto recebeu, opção por opção. O self-test prende `rotulo` a
# isto: quem quiser outro texto na tela muda `tela`.
ROTULOS_DO_PROMPT = {
    "V1": ["1 · só melhorar", "2 · testar usuários", "3 · experimento, A/B, randomização"],
    "V2": ["melhoria do serviço", "pesquisa", "pesquisa com humanos", "bem da comunidade"],
    "V3": ["nomeia atividades", "experimento específico", "preço como alvo"],
    "V4": ["interesse legítimo", "consentimento", "contrato"],
    "V5": ["só a objeção genérica do GDPR", "só cookies ou anúncios", "opt-out dedicado a experimentos", "opt-in"],
    "V6": ["programa beta ou opt-in"], "V7": ["é debriefing"],
    "V8": ["revisão ética, comitê ou risco"], "V9": ["divulga experimentação aqui"],
}

# Tipos de documento, na ordem das opções de v9_where, com o registro padrão.
# O tipo de cada documento está em analysis/tipos-doc.json (metadado do corpus,
# decisão de 04/10/2026); um registro diferente do padrão se declara lá
# ("registro não é hospedagem"). A página não pergunta.
TIPOS_DOC = [
    {"valor": "privacy policy", "rotulo": "política de privacidade (inclui aviso de cookies e tabela de bases legais)", "registro": "binding"},
    {"valor": "ToS/conditions", "rotulo": "termos de uso", "registro": "binding"},
    {"valor": "research notice separado", "rotulo": "aviso de pesquisa separado", "registro": "non-binding"},
    {"valor": "help centre", "rotulo": "central de ajuda", "registro": "non-binding"},
    {"valor": "blog/PR/site de pesquisa", "rotulo": "blog, imprensa ou site de pesquisa", "registro": "non-binding"},
]

# Perguntas que não vêm de trecho e continuam perguntas.
EXTRAS = {"V3": ["v3_targets"], "V4": ["v4_mapped_purpose", "v4_region_gated"], "V6": ["v6_which"]}

# Rótulos de tela dos campos de resposta (06/10/2026). O `rotulo` continua o
# do instrumento congelado ("V3a: atividades/superfícies nomeadas?", "Bases
# declaradas (multi)"); a caixa "Resposta calculada" mostra `tela`.
ROTULOS_TELA = {
    "v1_code": "Nível (teto)",
    "v1_register": "Registro do teto",
    "v2_framing": "Enquadramentos presentes",
    "v3_activities": "Nomeia atividades ou superfícies testadas?",
    "v3_specific": "Divulga um experimento específico ou ativo?",
    "v3_pricing": "Preço nomeado como alvo?",
    "v3_targets": "Alvos nomeados",
    "v4_basis": "Bases legais declaradas",
    "v4_mapped_purpose": "Finalidade que cobre os testes",
    "v4_region_gated": "Tabela de bases só da UE?",
    "v5_optout": "Saída dos experimentos",
    "v6_optin_beta": "Existe programa opt-in?",
    "v6_which": "Qual programa",
    "v7_debrief": "Avisa depois que a pessoa participou?",
    "v8_ethics": "Menciona revisão ética, comitê ou risco?",
    "v9_where": "Locais da divulgação",
    "v9_register": "Registro agregado",
}

# A linha abaixo da pergunta, em cada tela (07/10/2026). As do instrumento
# congelado (GLOSA.lembrete) falavam em "marcar" campos e em "dizer em que
# documento"; na versão B o codificador dá nota a trechos, o tipo do documento
# já vem dado e a resposta é calculada. Reescritas para o que a tela pede.
LEMBRETES = {
    "V1": "Dê a cada trecho o nível que ele mostra, de 1 a 3, ou \"não se aplica\". A resposta é o nível mais alto; "
          "o tipo do documento já vem dado. Período grátis de teste (free trial) não conta.",
    "V2": "Marque em cada trecho os enquadramentos que ele traz; pode ser mais de um. A resposta é a união de todos.",
    "V3": "Em cada trecho, marque o que ele mostra: nomeia o que é testado, descreve um experimento específico, preço como alvo. "
          "Os alvos nomeados você escreve na caixa de resposta. Personalização não é alvo de teste.",
    "V4": "Na tabela de bases legais, ache a finalidade que cobre os testes (em geral, melhorar o serviço) e marque em cada trecho "
          "a base declarada para ela. Sem tabela nos documentos, a resposta fica \"não declarada\". "
          "O nome da finalidade você escreve na caixa de resposta.",
    "V5": "Em cada trecho, o degrau que ele mostra; a resposta é o mais alto. Só sobre experimentação: banner de cookies que rege "
          "publicidade é \"só opt-out de cookies ou anúncios\", não \"opt-out dedicado\".",
    "V6": "Marque os trechos que descrevem um programa beta ou opt-in e escreva qual é na caixa de resposta. "
          "Beta por adesão é diferente da V5: não é saída dos experimentos, e as duas nunca se somam.",
    "V7": "Marque só os trechos em que a plataforma avisa, depois, que a pessoa participou. Aviso de tratamento de dados, "
          "de decisão automatizada ou de mudança no serviço não conta. Sem trecho, a resposta é No; se o tema aparece e o "
          "mecanismo não, diga no comentário.",
    "V8": "Marque só os trechos que mencionam revisão ética, comitê ou avaliação de risco de experimentos. Linguagem vaga de "
          "impacto não conta, nem avaliação de risco do DSA fora dos documentos ao usuário; nesses casos, diga no comentário.",
    "V9": "Os trechos que receberam nível na V1 já entram marcados; desmarque o que não divulga experimentação e marque o que "
          "faltar. Os locais e o registro são calculados do tipo de cada documento.",
    "KW": "O log já vem com a contagem bruta por documento. Corrija os números, tirando o que você marcou como \"não se aplica\".",
}

# O que fazer em cada pergunta avulsa, dito na própria caixa.
AJUDA_TELA = {
    "v3_targets": "O que o texto diz que é testado: ordem dos resultados, preço, mensagem, emoção, fricção, opções padrão. "
                  "Lista aberta; separe os itens por vírgula. Pode ficar vazio.",
    "v4_mapped_purpose": "Qual finalidade declarada na tabela de bases legais você entendeu como a que cobre os testes. "
                         "Em geral é algo como \"melhorar nossos serviços\". Copie o nome que o documento usa.",
    "v4_region_gated": "Só se testa capturando de dentro e de fora da UE. Você lê texto congelado, capturado da UE, "
                       "então fica como não verificável. Fora do cálculo de concordância.",
    "v6_which": "Nome do programa e como ele funciona, em uma linha.",
}


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
            "lembrete": LEMBRETES.get(v.vid, C.lembrete(k)),
            "guia_html": C.glosa_criterio(k),
            "crit_html": C.criterio(k),
            "crit_sha": C.CRIT_CONGELADO.get(k),
            "campos": [{
                "chave": c.chave, "rotulo": _texto(c.rotulo), "tipo": c.tipo,
                "opcoes": list(c.opcoes or []), "placeholder": _texto(c.placeholder or ""),
                **({"tela": ROTULOS_TELA[c.chave]} if c.chave in ROTULOS_TELA else {}),
                **({"ajuda_tela": AJUDA_TELA[c.chave]} if c.chave in AJUDA_TELA else {}),
            } for c in v.campos],
        })
    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "congelado_em": CONGELADO_EM,
        "fonte_crit": R.FONTE_CRIT,
        "servicos": list(C.SERVICOS),
        "variaveis": variaveis,
        "termos": [{"term": nome, "label": spec.get("label", nome), "flag": spec.get("flag"),
                    "regex": spec["regex"], "case_sensitive": bool(spec.get("case_sensitive"))}
                   for nome, spec in P.PATTERNS.items()],
        "termo_para_variavel": {t: list(vs) for t, vs in R.TERMO_PARA_VARIAVEL.items()},
        "regras_gerais_html": regras_gerais_html(),
        # Ajuda por valor e por campo, do instrumento, em texto. Sem o travessão
        # tipográfico e sem a procedência (§), que aqui não ajudam.
        "ajuda_valores": {k: _texto(v[0] if isinstance(v, (list, tuple)) else v) for k, v in C.VALHELP.items()},
        "ajuda_campos": {k: _texto(v.get("note", "")) for k, v in C.FIELDHELP.items() if isinstance(v, dict) and v.get("note")},
        "notas": NOTAS,
        "tipos_doc": TIPOS_DOC,
        "extras": EXTRAS,
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
    checar("cada termo traz a regex do §3, para a página marcar as ocorrências no documento",
           all(t.get("regex") and re.compile(t["regex"]) for t in d["termos"]))
    checar("endereço termo→variável igual ao do painel", d["termo_para_variavel"] == {t: list(v) for t, v in R.TERMO_PARA_VARIAVEL.items()})
    checar("regras gerais: cinco itens, sem travessão", d["regras_gerais_html"].count("<li>") == 5 and "—" not in d["regras_gerais_html"])
    checar("nenhum travessão em pergunta ou lembrete",
           not any("—" in (v["pergunta"] + v["lembrete"]) for v in d["variaveis"]))
    checar("ajuda por valor: 18 entradas, em texto, sem travessão",
           len(d["ajuda_valores"]) == 18 and all("<" not in t and "—" not in t for t in d["ajuda_valores"].values()))
    checar("nenhum travessão em placeholder nem em rótulo de campo",
           not any("—" in c["placeholder"] + c["rotulo"] for v in d["variaveis"] for c in v["campos"]))
    # Notas por trecho: as opções têm de ser as do codebook, letra por letra.
    opcoes = {c["chave"]: [o for o in c["opcoes"] if o] for v in d["variaveis"] for c in v["campos"] if c["opcoes"]}
    vals = lambda vid: [o["valor"] for o in d["notas"][vid]["opcoes"]]
    checar("notas V2 = opções de v2_framing", vals("V2") == opcoes["v2_framing"])
    checar("notas V4 = opções de v4_basis sem not stated", vals("V4") == [o for o in opcoes["v4_basis"] if o != "not stated"])
    checar("notas V5 = escada de v5_optout sem none, na ordem", vals("V5") == [o for o in opcoes["v5_optout"] if o != "none"])
    checar("notas V1 = níveis 1..3", vals("V1") == ["1", "2", "3"])
    checar("notas V3 apontam para os três campos Yes/No",
           [o["campo"] for o in d["notas"]["V3"]["opcoes"]] == ["v3_activities", "v3_specific", "v3_pricing"])
    checar("tipos de documento = opções de v9_where, na ordem", [t["valor"] for t in d["tipos_doc"]] == opcoes["v9_where"])
    checar("todo tipo de documento tem registro padrão válido", all(t["registro"] in ("binding", "non-binding") for t in d["tipos_doc"]))
    checar("extras são campos de linha ou select existentes",
           all(ch in {c["chave"] for v in d["variaveis"] for c in v["campos"]} for chs in d["extras"].values() for ch in chs))
    checar("nenhum travessão nas notas e nos tipos", "—" not in json.dumps(d["notas"], ensure_ascii=False) + json.dumps(d["tipos_doc"], ensure_ascii=False))
    checar("rotulo das notas é o que o copiloto recebeu (para outro texto na tela, mude `tela`)",
           {vid: [o["rotulo"] for o in s["opcoes"]] for vid, s in d["notas"].items()} == ROTULOS_DO_PROMPT)
    checar("toda nota tem rótulo de tela, não vazio e sem travessão",
           all(o.get("tela") and "—" not in o["tela"] for s in d["notas"].values() for o in s["opcoes"]))
    campos_resposta = [c for v in d["variaveis"] for c in v["campos"] if c["tipo"] != "text"]
    checar("todo campo de resposta tem rótulo de tela, sem travessão, sem prefixo V3a e sem (multi)",
           all(c.get("tela") and "—" not in c["tela"] and not re.match(r"^V\d", c["tela"]) and "(multi)" not in c["tela"]
               for c in campos_resposta))
    extras_chaves = {ch for lista in d["extras"].values() for ch in lista}
    checar("toda pergunta avulsa tem ajuda de tela",
           all(c.get("ajuda_tela") for c in campos_resposta if c["chave"] in extras_chaves))
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
