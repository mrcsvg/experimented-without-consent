#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera `notebooks/04-revisao-assistida.ipynb` — uma célula por serviço.

    python3 analysis/gerar-notebook-revisao.py
    python3 analysis/gerar-notebook-revisao.py --check   # não escreve, só compara

POR QUE GERAR EM VEZ DE EDITAR À MÃO. São 26 células idênticas a menos do nome
do serviço, e o nome tem que sair do roster do instrumento — que é a mesma
fonte que o `codebook.py` lê. Um notebook editado à mão diverge do roster na
primeira vez que alguém renomeia um serviço, e a divergência aparece como
célula que levanta KeyError no meio da sessão do avaliador.

O cabeçalho em Markdown antes de cada célula existe para o índice lateral do
Colab: com ele o revisor pula direto para o serviço que quer, sem rolar.

Saída sem output, como o resto do repositório (ver `nb-clean.py`): output de
notebook carrega passagens que o modelo achou, e isso não pode viajar num
clone do repo enquanto a passada de concordância está aberta.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codebook as C  # noqa: E402

DESTINO = Path(__file__).resolve().parent.parent / "notebooks" / "04-revisao-assistida.ipynb"

ABERTURA = """# Revisão assistida — 2º passe

Uma célula por serviço. Rode a célula, leia a evidência que já vem localizada,
responda as nove variáveis e o log do §3, salve. O progresso vai para o mesmo lugar do
instrumento em HTML (`coder2-data`), então dá para alternar entre os dois.

**A tela tem dois andares, e a ordem importa.**

O **piso** é a busca por palavra-chave do §3: os 12 termos, endereçados por
variável, com o trecho em volta. É uma expressão regular sobre o texto
congelado, então não esquece nada — e chega com aviso quando o termo costuma dar
falso positivo ("Code of Ethics" no menu não é revisão ética de experimento).
Quem descarta é você.

Em cima dele vem o que **o modelo** localizou. Ele acrescenta o que a palavra-
chave não acha: passagem que descreve experimentação sem usar nenhum dos 12
termos. Nessa ordem ele só pode somar.

**Nenhum dos dois atribui código.** A passada 1 já foi automatizada; se um modelo
decidisse aqui também, o κ mediria o modelo contra ele mesmo em vez de
concordância entre codificadores. A evidência do modelo foi congelada numa rodada
única e publicada — todo avaliador vê a mesma tela, e **você não precisa de chave
de API para nada**.

**Leia sempre do corpus congelado, nunca da página ao vivo.** Os documentos
mudam sem aviso; se os dois codificadores lerem versões diferentes, a
discordância vira deriva do documento e não há como separar as duas depois.

**Onde suas respostas ficam.** Cada variável que você fecha é gravada num
servidor e versionada, então dá para parar no meio, fechar o Colab e voltar
depois — inclusive de outra máquina. Embaixo do painel há uma linha de recibo:
**verde** quando a resposta chegou ao servidor, **vermelha** quando não chegou.
Vermelha significa parar e avisar: o arquivo local do Colab é apagado quando a
sessão recicla, e o que estiver só nele se perde.
"""

SETUP = '''#@title Instalação e configuração { display-mode: "form" }
# Roda uma vez por sessão. ~15 s. O SDK da Anthropic não entra: a evidência do
# modelo já vem congelada, e este notebook não chama modelo nenhum.
!pip -q install ipywidgets

import hashlib, json, sys, urllib.request
from pathlib import Path

SITE = "https://experimented-without-consent-corpus.vercel.app"

# O runtime vem do mesmo host do corpus, não de um clone: os repositórios são
# privados, e pedir um token dentro de uma célula seria pior que o problema que
# resolve. Cada arquivo é conferido contra o manifesto — isso pega download
# truncado e cópia velha, não é barreira contra adversário.
destino = Path("/content/ewc")
manifesto = json.load(urllib.request.urlopen(f"{SITE}/lib/manifest.json", timeout=60))
for arquivo in manifesto["arquivos"]:
    with urllib.request.urlopen(f"{SITE}/lib/{arquivo['file']}", timeout=60) as r:
        dados = r.read()
    if hashlib.sha256(dados).hexdigest() != arquivo["sha256"]:
        raise SystemExit(f"{arquivo['file']}: download não bate com o manifesto")
    alvo = destino / arquivo["file"]
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_bytes(dados)
print(f"runtime publicado em {manifesto['publicado_em'][:10]} · "
      f"{len(manifesto['arquivos'])} arquivos conferidos")

sys.path.insert(0, str(destino / "analysis"))
import revisao as R

# O corpus é lido do mesmo site. Para trabalhar offline, baixe `md/` e aponte
# CORPUS para a pasta local — o resto do notebook não muda.
corpus = R.configurar(corpus=f"{SITE}/md", modelo="claude-opus-5")
print(f"{sum(len(s['docs']) for s in corpus.index['services'])} documentos · "
      f"{len(corpus.index['services'])} serviços · congelado "
      f"{corpus.index['frozen_at'][:10]} · vantagem {corpus.index['vantage']}")
'''

CHAVE = """## Sem chave de API

A evidência do modelo já está congelada e publicada ao lado do corpus, então o
notebook não chama modelo nenhum e não precisa de credencial.

A célula abaixo confirma que a evidência congelada chegou, e mostra a data em que
foi gerada. Se ela disser que não achou, me avise antes de começar a codificar:
sem ela o piso da busca por palavra-chave continua funcionando, mas você perde a
camada que o modelo acrescenta.
"""

CUSTO = '''# Confere a evidência congelada. Não chama modelo, não gasta nada.
import json, urllib.request
idx = json.load(urllib.request.urlopen(f"{SITE}/sugestoes/index.json", timeout=60))
total = sum(a["citacoes"] for a in idx["arquivos"])
print(f"evidência congelada: {len(idx['arquivos'])} serviços · {total} citações · "
      f"gerada em {idx['gerado_em'][:10]}")
print(f"modelo: {sorted({a['modelo'] for a in idx['arquivos']})}")
'''

SERVICOS_MD = """## Os 26 serviços

Cada célula abaixo é independente: rode na ordem que quiser, pare no meio,
volte depois. O que já foi respondido reaparece preenchido.
"""

FECHAMENTO = '''# Onde a segunda passada está — metadados, sem revelar codificação.
e = R.F.Estado()
feitos = {s: sum(1 for k in r if not k.startswith("_") and r[k])
          for s, r in e.records.items()}
print(f"{sum(1 for n in feitos.values() if n >= 13)}/26 serviços com os 13 campos centrais")
for s, n in sorted(feitos.items(), key=lambda x: -x[1]):
    print(f"  {n:2d} campos · {s}")
'''


def celula(tipo: str, texto: str, n: int) -> dict:
    # `source` como lista de linhas terminadas em \n é o que o nbformat espera;
    # gravado como string única, o Colab colapsa a célula inteira numa linha.
    base = {"cell_type": tipo, "id": f"c{n:03d}", "metadata": {},
            "source": texto.splitlines(keepends=True)}
    if tipo == "code":
        base |= {"execution_count": None, "outputs": []}
    return base


def montar() -> dict:
    celulas, n = [], 0

    def add(tipo, texto):
        nonlocal n
        celulas.append(celula(tipo, texto, n))
        n += 1

    add("markdown", ABERTURA)
    add("code", SETUP)
    add("markdown", CHAVE)
    add("code", CUSTO)
    add("markdown", SERVICOS_MD)
    for servico in C.SERVICOS:
        add("markdown", f"### {servico}\n")
        add("code", f'R.painel("{servico}")\n')
    add("markdown", "## Progresso\n")
    add("code", FECHAMENTO)

    return {
        "cells": celulas,
        "metadata": {
            "colab": {"provenance": [], "toc_visible": True},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> int:
    nb = montar()
    texto = json.dumps(nb, ensure_ascii=False, indent=1) + "\n"
    if "--check" in sys.argv:
        if not DESTINO.exists():
            print(f"FALHOU — {DESTINO.name} não existe; rode sem --check")
            return 1
        igual = DESTINO.read_text(encoding="utf-8") == texto
        print("OK — notebook em dia com o roster" if igual else
              "FALHOU — notebook divergiu do roster; regenere")
        return 0 if igual else 1
    DESTINO.parent.mkdir(exist_ok=True)
    DESTINO.write_text(texto, encoding="utf-8")
    print(f"{len(nb['cells'])} células ({len(C.SERVICOS)} serviços) → {DESTINO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
