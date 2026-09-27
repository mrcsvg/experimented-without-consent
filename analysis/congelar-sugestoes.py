#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Congela, uma vez, as citações que o modelo localiza — e publica só elas.

    python3 analysis/congelar-sugestoes.py --corpus <pasta-ou-url> --out <destino>/sugestoes
    python3 analysis/congelar-sugestoes.py --out <destino>/sugestoes --check
    python3 analysis/congelar-sugestoes.py --simular            # self-test, sem gastar

POR QUE CONGELAR. A validação de 20/09/2026 mediu duas rodadas do mesmo serviço
e achou Jaccard de 0,60, 0,60 e 0,00 em variáveis isoladas — numa delas, o
debriefing do Instagram, uma rodada trazia evidência à tela e a outra não. Com
chamada ao vivo, o que o avaliador vê depende de quando ele clicou na célula, e
isso não é uma propriedade aceitável de um instrumento. Congelado, todo avaliador
vê a mesma tela, o arquivo é citável no método, e ninguém precisa de chave de
API para codificar.

O QUE NÃO ENTRA NO ARQUIVO: a sugestão de código do modelo. O desenho a mantinha
atrás de um botão, com o clique registrado, justamente para separar conferência
de influência. Num arquivo publicado ela seria legível direto, e o botão viraria
enfeite. Então ela fica fora — o que o arquivo leva é evidência localizada, que
é a parte cujo valor a validação confirmou (as duas âncoras do piloto foram
achadas em 250 mil e 392 mil caracteres).

O QUE O ARQUIVO NÃO PRECISA GARANTIR: cobertura. Essa passou a ser invariante do
piso determinístico (`revisao.piso`), que roda sem modelo e sem rede. O que está
aqui é acréscimo em cima de um chão que não esquece.

Sem dependências além do `anthropic`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codebook as C  # noqa: E402
import revisao as R  # noqa: E402

FORMATO = 1  # versão do formato do arquivo, para o leitor saber o que esperar


def sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def congelar_um(servico: str, corpus, modelo: str, cliente=None) -> dict:
    sug = R.sugerir(servico, corpus, modelo=modelo, cliente=cliente)
    # Só as citações verificadas. `sugestao` e `confianca` ficam de fora de
    # propósito — ver o cabeçalho.
    return {
        "formato": FORMATO,
        "servico": servico,
        "modelo": sug.modelo,
        "prompt": R.impressao_do_prompt() if hasattr(R, "impressao_do_prompt") else None,
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus_frozen_at": corpus.index.get("frozen_at"),
        "corpus_built_at": corpus.index.get("built_at"),
        # Parâmetros de geração, porque teto de saída e modo de pensamento fazem
        # parte das condições sob as quais a evidência foi produzida.
        "geracao": {"max_tokens": R.MAX_TOKENS, "thinking": "adaptive"},
        "citacoes": {vid: v["citacoes"] for vid, v in sug.por_variavel.items()},
        "descartadas": len(sug.descartadas),
        "uso": sug.uso,
    }


def escrever(destino: Path, registro: dict) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    alvo = destino / f"{R.B.slug(registro['servico'])}.json"
    alvo.write_text(json.dumps(registro, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    return alvo


def reindexar(destino: Path) -> dict:
    """Índice com o sha de cada arquivo: o painel diz 'íntegra' com base nisto."""
    arquivos = []
    for p in sorted(destino.glob("*.json")):
        if p.name == "index.json":
            continue
        dados = json.loads(p.read_text(encoding="utf-8"))
        arquivos.append({
            "file": p.name, "servico": dados["servico"],
            "sha256": sha(p.read_text(encoding="utf-8")),
            "citacoes": sum(len(v) for v in dados["citacoes"].values()),
            "gerado_em": dados["gerado_em"], "modelo": dados["modelo"],
            "corpus_frozen_at": dados.get("corpus_frozen_at"),
        })
    indice = {"formato": FORMATO,
              "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "arquivos": arquivos}
    (destino / "index.json").write_text(
        json.dumps(indice, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return indice


def checar(destino: Path) -> int:
    problemas = []
    caminho = destino / "index.json"
    if not caminho.exists():
        print(f"FALHOU — {caminho} não existe")
        return 1
    indice = json.loads(caminho.read_text(encoding="utf-8"))
    vistos = set()
    for a in indice["arquivos"]:
        p = destino / a["file"]
        if not p.exists():
            problemas.append(f"{a['file']}: no índice, ausente em disco")
            continue
        bruto = p.read_text(encoding="utf-8")
        if sha(bruto) != a["sha256"]:
            problemas.append(f"{a['file']}: conteúdo não bate com o sha do índice")
        dados = json.loads(bruto)
        if "sugestao" in json.dumps(dados):
            problemas.append(f"{a['file']}: traz sugestão de código, que não deve ser publicada")
        vistos.add(dados["servico"])
    for faltando in sorted(set(C.SERVICOS) - vistos):
        problemas.append(f"{faltando}: sem evidência congelada")
    orfaos = {p.name for p in destino.glob("*.json")} - {a["file"] for a in indice["arquivos"]}
    for o in sorted(orfaos - {"index.json"}):
        problemas.append(f"{o}: em disco, fora do índice")

    if problemas:
        print(f"FALHOU — {len(problemas)} problema(s):")
        for p in problemas[:30]:
            print(f"  - {p}")
        return 1
    total = sum(a["citacoes"] for a in indice["arquivos"])
    print(f"OK — {len(indice['arquivos'])} serviços, {total} citações congeladas, "
          f"nenhuma sugestão de código publicada")
    return 0


def _self_test(corpus_origem: str) -> int:
    falhas = []

    def checar_um(desc, cond):
        print(("  ok    " if cond else "  FALHA ") + desc)
        if not cond:
            falhas.append(desc)

    import tempfile
    corpus = R.configurar(corpus=corpus_origem, modelo="modelo-de-teste")

    class Falso:
        """Devolve uma citação real e uma inventada, como no validador."""

        def __init__(self, corpus, servico):
            texto = corpus.texto(corpus.docs(servico)[0]) or ""
            trecho = texto[200:320]
            corpo = json.dumps({"variaveis": [{"vid": "V1", "sugestao": "2",
                                               "confianca": "alta",
                                               "citacoes": [
                                                   {"doc": corpus.docs(servico)[0]["n"],
                                                    "verbatim": trecho, "onde": "x",
                                                    "por_que": "y"},
                                                   {"doc": corpus.docs(servico)[0]["n"],
                                                    "verbatim": "isto não existe no corpus",
                                                    "onde": "x", "por_que": "y"}]}]})

            class _Bloco:
                type, text = "text", corpo

            class _Msg:
                content, stop_reason = [_Bloco()], "end_turn"
                usage = type("U", (), {"input_tokens": 10, "output_tokens": 2})()

            import contextlib

            @contextlib.contextmanager
            def ctx(**kw):
                yield type("F", (), {"get_final_message": staticmethod(lambda: _Msg())})()
            self.messages = type("M", (), {"stream": staticmethod(ctx)})()

    with tempfile.TemporaryDirectory(prefix="sug-") as tmp:
        destino = Path(tmp) / "sugestoes"
        for servico in ("Pinterest", "Wikipedia"):
            reg = congelar_um(servico, corpus, "modelo-de-teste", Falso(corpus, servico))
            checar_um(f"{servico}: citação verificada entra", len(reg["citacoes"]["V1"]) == 1)
            checar_um(f"{servico}: citação inventada é descartada", reg["descartadas"] == 1)
            checar_um(f"{servico}: sugestão de código fica fora do registro",
                      "sugestao" not in json.dumps(reg))
            escrever(destino, reg)
        reindexar(destino)
        checar_um("índice lista os dois serviços",
                  len(json.loads((destino / "index.json").read_text())["arquivos"]) == 2)
        # O check exige os 26; com dois, tem de reprovar.
        checar_um("check reprova corpus de evidência incompleto", checar(destino) == 1)
        # E tem de pegar sugestão publicada por acidente.
        p = destino / "pinterest.json"
        d = json.loads(p.read_text())
        d["citacoes"]["V1"][0]["sugestao"] = "3"
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        reindexar(destino)
        checar_um("check pega sugestão de código publicada", checar(destino) == 1)

    print(f"\n{'FALHOU: ' + str(len(falhas)) if falhas else 'tudo ok'}")
    return 1 if falhas else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default="../experimented-without-consent-corpus/md")
    ap.add_argument("--out", type=Path,
                    default=Path("../experimented-without-consent-corpus/sugestoes"))
    ap.add_argument("--modelo", default=R.MODELO_PADRAO)
    ap.add_argument("--servicos", nargs="+", help="só estes (o default são os 26)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()

    if a.simular:
        return _self_test(a.corpus)
    if a.check:
        return checar(a.out)

    corpus = R.configurar(corpus=a.corpus, modelo=a.modelo)
    alvo = a.servicos or C.SERVICOS
    entrada = saida_tok = 0
    for i, servico in enumerate(alvo, 1):
        t0 = time.time()
        reg = congelar_um(servico, corpus, a.modelo)
        p = escrever(a.out, reg)
        entrada += reg["uso"].get("input", 0)
        saida_tok += reg["uso"].get("output", 0)
        n = sum(len(v) for v in reg["citacoes"].values())
        print(f"  [{i}/{len(alvo)}] {servico:<16} {n:>3} citações, "
              f"{reg['descartadas']} descartadas, {time.time() - t0:.0f}s → {p.name}",
              flush=True)
    indice = reindexar(a.out)
    custo = entrada / 1e6 * 5 + saida_tok / 1e6 * 25
    print(f"\n{len(indice['arquivos'])} serviços · {entrada:,} tokens de entrada · "
          f"{saida_tok:,} de saída · US$ {custo:.2f}".replace(",", "."))
    return checar(a.out)


if __name__ == "__main__":
    sys.exit(main())
