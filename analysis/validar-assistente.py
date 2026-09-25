#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Valida o assistente de localização de evidência, com critério fixado antes.

    python3 analysis/validar-assistente.py --corpus <url-ou-pasta>            # só estima
    python3 analysis/validar-assistente.py --corpus <...> --go --out relatorio.md
    python3 analysis/validar-assistente.py --simular                          # self-test, sem gastar

O QUE ESTÁ SENDO VALIDADO, E O QUE NÃO. O notebook 04 usa o modelo para
localizar passagens; o código é do avaliador humano. Então o que precisa de
validação é a BUSCA, não o julgamento: se o modelo deixa de mostrar uma
passagem que existe, o avaliador pode marcar "No" sem nunca tê-la visto, e o
"No" entra como achado. Num estudo cujo resultado central é uma coluna de
zeros, esse é o modo de falha que importa.

POR QUE OS CRITÉRIOS ESTÃO NESTE ARQUIVO. Porque critério escolhido depois de
ver o resultado não é critério. Eles estão em CRITERIOS, com o número e a
justificativa, e o relatório é gerado contra eles. Mudar um critério é um
commit, com data — e não deve ser feito no mesmo dia em que se olha o
resultado.

O QUE NÃO SE USA PARA CALIBRAR: as codificações da passada 1. Ajustar o prompt
até o modelo achar o que a passada 1 achou faria o segundo avaliador ler
evidência moldada pela primeira passada, e a independência que o κ mede iria
embora por uma porta que ninguém veria. A referência aqui é a varredura
determinística dos 12 termos (`patterns.py`) e as âncoras publicadas do
codebook — ambas independentes da passada 1.

A AMOSTRA (5 serviços, escolhidos antes de rodar, pelos números da varredura):

- Google Search, Facebook, Amazon Store — os três do piloto, os únicos com
  âncora publicada no codebook.
- Zalando — a maior variedade de termos fortes (A-B, experiment, randomize,
  ethics, risk assessment) em 5 de 8 documentos. É onde há mais o que achar.
- Instagram — CONTROLE NEGATIVO: 362 mil caracteres de política e termos da
  Meta, e a varredura determinística não acha um único termo forte. Se o modelo
  inventa evidência em algum lugar, é aqui.

Nada aqui grava no `coder2-data`: `sugerir` não toca em estado. O relatório não
vai para o segundo avaliador.

Sem dependências além do `anthropic` (que o `revisao.py` já exige).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import patterns as P  # noqa: E402
import revisao as R  # noqa: E402

# Termos sem `flag`: os que não têm falso positivo notório. "test", "trial" e
# "beta" ficam fora porque "free trial" e "testing" de QA não são
# experimentação, e a triagem deles é julgamento humano, não cobertura.
FORTES = [t for t, spec in P.PATTERNS.items() if not spec["flag"]]

AMOSTRA = ["Google Search", "Facebook", "Amazon Store", "Zalando", "Instagram"]
DUAS_RODADAS = ["Google Search", "Zalando", "Instagram"]
CONTROLE_NEGATIVO = "Instagram"

# Âncoras publicadas no codebook v2 §2, vindas do piloto de 04/jul. Não são
# codificações da passada 1: estão no instrumento, à vista do avaliador.
ANCORAS = {
    "Google Search": "700,000 experiments",
    "Facebook": "testing and troubleshooting new features",
}

CRITERIOS = {
    "C1": ("Cobertura documental: todo documento com termo forte é citado ao menos uma vez",
           "Documento que menciona experimentação e não aparece na tela é documento que o "
           "avaliador pode nunca abrir. Meta: 100%."),
    "C2": ("Cobertura de termos: ≥80% dos termos fortes presentes aparecem na evidência citada",
           "Não se exige citar cada ocorrência — vinte 'experiment' no mesmo blog são "
           "redundantes —, mas cada TIPO de termo presente tem de aparecer em alguma citação."),
    "C3": ("Descarte ≤5%: citações que não se localizam no texto congelado",
           "Citação inventada é pior que nenhuma, porque parece evidência. O verificador já "
           "as derruba; esta taxa mede a qualidade do prompt, não a segurança."),
    "C4": ("Âncoras: a citação âncora do codebook é localizada onde existe no corpus",
           "É a única referência externa de 'o que um humano consideraria a passagem certa' "
           "que não vem da passada 1."),
    "C5": ("Controle negativo: zero descartes no serviço sem termo forte",
           "Serviço sem nada a achar é o que provoca invenção. Descarte aqui é o sinal."),
    "C6": ("Estabilidade: Jaccard ≥0,80 dos documentos citados por variável entre duas rodadas",
           "Se duas rodadas mostram evidências diferentes, o avaliador vê uma tela que depende "
           "de quando rodou a célula. Abaixo disso, congelar a saída em vez de chamar ao vivo."),
}
META_C1, META_C2, META_C3, META_C6 = 1.00, 0.80, 0.05, 0.80

PRECO = {"entrada": 5.0, "saida": 25.0}  # US$ por milhão, Opus 5


def normalizar(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip().lower()


# A impressão do prompt vive no `revisao.py`, junto do prompt que ela identifica.
impressao_do_prompt = R.impressao_do_prompt


# ------------------------------------------------------------------ referência

def referencia(servico: str, corpus) -> dict:
    """O que a varredura determinística acha no serviço. Independe do modelo."""
    docs, termos, por_doc = {}, set(), {}
    for d in R.varredura(servico, corpus):
        presentes = {t for t in FORTES if d["counts"][t]}
        por_doc[d["file"]] = presentes
        if presentes:
            docs[d["file"]] = presentes
            termos |= presentes
    return {"docs_com_termo": docs, "termos": termos, "por_doc": por_doc}


def medir(servico: str, sug, ref: dict) -> dict:
    """Confronta a sugestão do modelo com a referência determinística."""
    citacoes = [c for v in sug.por_variavel.values() for c in v["citacoes"]]
    arquivos_citados = {c["file"] for c in citacoes}
    termos_citados = {t for c in citacoes for t in FORTES
                      if P.COMPILED[t].search(c["verbatim"])}

    esperados = set(ref["docs_com_termo"])
    c1 = len(esperados & arquivos_citados) / len(esperados) if esperados else None
    c2 = len(ref["termos"] & termos_citados) / len(ref["termos"]) if ref["termos"] else None
    total = len(citacoes) + len(sug.descartadas)
    c3 = len(sug.descartadas) / total if total else 0.0

    ancora = ANCORAS.get(servico)
    c4 = None
    if ancora:
        no_corpus = any(normalizar(ancora) in normalizar(corpus_texto)
                        for corpus_texto in ref.get("_textos", []))
        achou = any(normalizar(ancora) in normalizar(c["verbatim"]) for c in citacoes)
        c4 = achou if no_corpus else None

    return {
        "citacoes": len(citacoes), "descartadas": len(sug.descartadas),
        "docs_esperados": sorted(esperados), "docs_citados": sorted(arquivos_citados),
        "docs_faltando": sorted(esperados - arquivos_citados),
        "termos_esperados": sorted(ref["termos"]), "termos_citados": sorted(termos_citados),
        "C1": c1, "C2": c2, "C3": c3, "C4": c4,
        "por_variavel": {vid: sorted({c["file"] for c in v["citacoes"]})
                         for vid, v in sug.por_variavel.items()},
        "uso": sug.uso,
    }


def jaccard(a: set, b: set) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def estabilidade(m1: dict, m2: dict) -> dict:
    vids = set(m1["por_variavel"]) | set(m2["por_variavel"])
    por_v = {v: jaccard(set(m1["por_variavel"].get(v, [])), set(m2["por_variavel"].get(v, [])))
             for v in sorted(vids)}
    return {"por_variavel": por_v,
            "minimo": min(por_v.values()) if por_v else None,
            "mediana": statistics.median(por_v.values()) if por_v else None}


# --------------------------------------------------------------------- relatório

def veredito(valor, meta, maior_melhor=True):
    if valor is None:
        return "n/a"
    ok = valor >= meta if maior_melhor else valor <= meta
    return "PASSA" if ok else "FALHA"


def relatorio(res: dict) -> str:
    L = [f"# Validação do assistente de evidência",
         "",
         f"- Modelo: `{res['modelo']}`",
         f"- Corpus: {res['corpus']} · congelado {res['frozen_at']} · vantagem {res['vantagem']}",
         f"- Impressão do prompt: `{res['prompt']}` (muda o prompt, caduca a validação)",
         f"- Rodado em: {res['quando']}",
         f"- Custo: {res['tokens_entrada']:,} tokens de entrada, {res['tokens_saida']:,} de saída "
         f"· **US$ {res['custo']:.2f}**".replace(",", "."),
         "",
         "## Critérios, fixados antes de rodar", ""]
    for k, (titulo, porque) in CRITERIOS.items():
        L += [f"**{k}. {titulo}**  ", f"<sub>{porque}</sub>", ""]

    L += ["## Resultado por serviço", "",
          "| serviço | citações | descartes | C1 docs | C2 termos | C3 descarte | C4 âncora |",
          "|---|---|---|---|---|---|---|"]
    for s, m in res["servicos"].items():
        pct = lambda v: "n/a" if v is None else f"{v:.0%}"
        L.append(f"| {s} | {m['citacoes']} | {m['descartadas']} | "
                 f"{pct(m['C1'])} {veredito(m['C1'], META_C1)} | "
                 f"{pct(m['C2'])} {veredito(m['C2'], META_C2)} | "
                 f"{pct(m['C3'])} {veredito(m['C3'], META_C3, False)} | "
                 f"{'n/a' if m['C4'] is None else ('PASSA' if m['C4'] else 'FALHA')} |")

    if res.get("estabilidade"):
        L += ["", "## C6 — estabilidade entre duas rodadas", "",
              "| serviço | Jaccard mínimo | mediana | veredito |", "|---|---|---|---|"]
        for s, e in res["estabilidade"].items():
            L.append(f"| {s} | {e['minimo']:.2f} | {e['mediana']:.2f} | "
                     f"{veredito(e['minimo'], META_C6)} |")

    neg = res["servicos"].get(CONTROLE_NEGATIVO)
    if neg:
        L += ["", f"## C5 — controle negativo ({CONTROLE_NEGATIVO})", "",
              f"A varredura determinística não acha termo forte em nenhum dos "
              f"{len(neg['docs_citados']) or 'seis'} documentos. O modelo devolveu "
              f"{neg['citacoes']} citações verificadas e {neg['descartadas']} descartadas. "
              f"**{'PASSA' if neg['descartadas'] == 0 else 'FALHA'}** — descarte aqui é "
              f"invenção sob pressão de não haver nada."]

    faltando = {s: m["docs_faltando"] for s, m in res["servicos"].items() if m["docs_faltando"]}
    if faltando:
        L += ["", "## Documentos com termo forte que o modelo não citou", "",
              "Cada linha é um documento que menciona experimentação e que o avaliador "
              "não veria pela tela do painel.", ""]
        for s, docs in faltando.items():
            for d in docs:
                L.append(f"- **{s}** · `{d}`")

    L += ["", "## O que esta validação não cobre", "",
          "- O julgamento: nenhum código foi atribuído aqui, e o acerto do código não é medido.",
          "- Recall absoluto: a referência é a varredura dos 12 termos, que também tem lacuna "
          "(é o que o notebook 02 mede). Passagem que nenhum dos 12 termos acha não conta aqui.",
          f"- Generalização: {len(res['servicos'])} serviços dos 26, escolhidos por densidade de "
          "evidência e pelas âncoras, não por sorteio.",
          ""]
    return "\n".join(L)


# ----------------------------------------------------------------------- execução

def rodar(corpus_origem: str, modelo: str, gastar: bool, cliente=None,
          servicos: list[str] | None = None, rodadas_extra: list[str] | None = None) -> dict:
    # A amostra pré-registrada é o default. `--servicos` existe para provar o
    # caminho com um serviço barato antes de gastar a rodada inteira, e para
    # repetir um serviço isolado depois de uma falha de rede — não para escolher
    # amostra a gosto depois de ver resultado.
    amostra = servicos or AMOSTRA
    duas = rodadas_extra if rodadas_extra is not None else DUAS_RODADAS
    corpus = R.configurar(corpus=corpus_origem, modelo=modelo)
    res = {"modelo": modelo, "corpus": corpus_origem, "quando": datetime.now(timezone.utc)
           .isoformat(timespec="seconds"), "prompt": impressao_do_prompt(),
           "frozen_at": (corpus.index.get("frozen_at") or "?")[:10],
           "vantagem": corpus.index.get("vantage"),
           "servicos": {}, "estabilidade": {}, "tokens_entrada": 0, "tokens_saida": 0}

    if not gastar:
        total = chamadas = 0
        print("amostra e estimativa (nada foi chamado):\n")
        for s in amostra:
            n = sum(d["chars"] for d in corpus.docs(s))
            rodadas = 2 if s in duas else 1
            tok = int(n / 3.6) * rodadas
            total += tok
            chamadas += rodadas
            print(f"  {s:<16} {len(corpus.docs(s))} docs · {n:>7} ch · "
                  f"{rodadas} rodada(s) · ~{tok:>7,} tokens".replace(",", "."))
        # ~8 mil tokens de saída por chamada (pensamento + o JSON do esquema).
        saida = chamadas * 8_000
        custo = total / 1e6 * PRECO["entrada"] + saida / 1e6 * PRECO["saida"]
        print(f"\n  {chamadas} chamada(s) · ~{total:,} tokens de entrada · "
              f"~{saida:,} de saída · estimativa ~US$ {custo:.2f}".replace(",", "."))
        print("\n  heurística de 3,6 caracteres por token; a contagem exata precisa da chave.")
        print("  para rodar de verdade: acrescente --go")
        return res

    for servico in amostra:
        ref = referencia(servico, corpus)
        ref["_textos"] = [corpus.texto(d) or "" for d in corpus.docs(servico)]
        medidas = []
        for rodada in range(2 if servico in duas else 1):
            t0 = time.time()
            sug = R.sugerir(servico, corpus, modelo=modelo, cliente=cliente)
            m = medir(servico, sug, ref)
            medidas.append(m)
            res["tokens_entrada"] += sug.uso.get("input", 0)
            res["tokens_saida"] += sug.uso.get("output", 0)
            # flush: uma rodada leva minutos, e fora de terminal o Python
            # segura a saída no buffer — quem está esperando não vê progresso.
            print(f"  {servico:<16} rodada {rodada + 1}: {m['citacoes']} citações, "
                  f"{m['descartadas']} descartes, {time.time() - t0:.0f}s", flush=True)
        res["servicos"][servico] = medidas[0]
        if len(medidas) == 2:
            res["estabilidade"][servico] = estabilidade(medidas[0], medidas[1])

    res["custo"] = (res["tokens_entrada"] / 1e6 * PRECO["entrada"]
                    + res["tokens_saida"] / 1e6 * PRECO["saida"])
    return res


# ----------------------------------------------------------------------- self-test

class _ClienteFalso:
    """Devolve uma resposta com a forma do esquema, para exercitar as medidas.

    Cita de propósito um documento a menos que o esperado e uma citação que não
    existe no texto, para que o self-test veja C1 abaixo de 100% e C3 acima de
    zero — medida que nunca falhou não foi testada.
    """

    def __init__(self, corpus, servico):
        self.corpus, self.servico = corpus, servico

        class _M:
            def __init__(self, pai):
                self.pai = pai

            def stream(self, **kw):
                return self.pai._fluxo(kw)
        self.messages = _M(self)

    def _fluxo(self, kw):
        import contextlib
        corpus, servico = self.corpus, self.servico
        docs = corpus.docs(servico)
        citacoes = []
        for d in docs:
            texto = corpus.texto(d) or ""
            for t in FORTES:
                m = P.COMPILED[t].search(texto)
                if m:
                    citacoes.append({"doc": d["n"], "verbatim": texto[max(0, m.start() - 60):m.end() + 60],
                                     "onde": d["file"], "por_que": f"termo {t}"})
                    break
            if len(citacoes) >= 1:  # cita só o primeiro documento: C1 tem de cair
                break
        citacoes.append({"doc": docs[0]["n"], "verbatim": "frase que não existe no congelado",
                         "onde": "inventada", "por_que": "para o descarte aparecer"})
        corpo = json.dumps({"variaveis": [
            {"vid": "V1", "citacoes": citacoes, "sugestao": "2", "confianca": "media"}]})

        class _Bloco:
            type, text = "text", corpo

        class _Msg:
            content, stop_reason = [_Bloco()], "end_turn"
            usage = type("U", (), {"input_tokens": 1000, "output_tokens": 100})()

        @contextlib.contextmanager
        def ctx():
            yield type("F", (), {"get_final_message": staticmethod(lambda: _Msg())})()
        return ctx()


def _self_test(corpus_origem: str) -> int:
    falhas = []

    def checar(desc, cond):
        print(("  ok    " if cond else "  FALHA ") + desc)
        if not cond:
            falhas.append(desc)

    corpus = R.configurar(corpus=corpus_origem, modelo="modelo-de-teste")
    servico = "Zalando"
    ref = referencia(servico, corpus)
    checar("referência acha documentos com termo forte", len(ref["docs_com_termo"]) >= 3)
    checar("referência acha mais de um tipo de termo", len(ref["termos"]) >= 3)

    sug = R.sugerir(servico, corpus, modelo="modelo-de-teste",
                    cliente=_ClienteFalso(corpus, servico))
    ref["_textos"] = [corpus.texto(d) or "" for d in corpus.docs(servico)]
    m = medir(servico, sug, ref)
    checar("citação inventada é descartada", m["descartadas"] == 1)
    checar("C3 reflete o descarte", 0 < m["C3"] <= 1)
    checar("C1 cai quando documento com termo não é citado", m["C1"] is not None and m["C1"] < 1.0)
    checar("documentos faltando são listados", len(m["docs_faltando"]) >= 1)
    checar("C2 mede termos citados", m["C2"] is not None)

    e = estabilidade(m, m)
    checar("estabilidade de duas rodadas iguais é 1,0", e["minimo"] == 1.0)
    e2 = estabilidade(m, {"por_variavel": {"V1": []}})
    checar("estabilidade cai quando as rodadas divergem", e2["minimo"] == 0.0)

    texto = relatorio({**{"modelo": "x", "corpus": corpus_origem, "quando": "agora",
                          "prompt": impressao_do_prompt(), "frozen_at": "2026-08-03",
                          "vantagem": "IT", "tokens_entrada": 1, "tokens_saida": 1,
                          "custo": 0.0},
                       "servicos": {servico: m, CONTROLE_NEGATIVO: m},
                       "estabilidade": {servico: e}})
    checar("relatório traz os seis critérios", all(k in texto for k in CRITERIOS))
    checar("relatório marca PASSA/FALHA", "PASSA" in texto and "FALHA" in texto)

    print(f"\n{'FALHOU: ' + str(len(falhas)) if falhas else 'tudo ok'}")
    return 1 if falhas else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default="../experimented-without-consent-corpus/md")
    ap.add_argument("--modelo", default=R.MODELO_PADRAO)
    ap.add_argument("--go", action="store_true", help="chama o modelo de verdade (gasta)")
    ap.add_argument("--simular", action="store_true", help="self-test com cliente falso")
    ap.add_argument("--out", type=Path, help="onde gravar o relatório em Markdown")
    ap.add_argument("--servicos", nargs="+", help="sobrepõe a amostra pré-registrada")
    ap.add_argument("--uma-rodada", action="store_true", help="sem a segunda rodada de C6")
    a = ap.parse_args()

    if a.simular:
        return _self_test(a.corpus)

    res = rodar(a.corpus, a.modelo, a.go, servicos=a.servicos,
                rodadas_extra=[] if a.uma_rodada else None)
    if not a.go:
        return 0
    texto = relatorio(res)
    print("\n" + texto)
    if a.out:
        a.out.write_text(texto, encoding="utf-8")
        a.out.with_suffix(".json").write_text(
            json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"\nrelatório: {a.out} · números crus: {a.out.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
