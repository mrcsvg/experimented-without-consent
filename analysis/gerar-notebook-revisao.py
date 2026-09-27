#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera os dois notebooks do 2º passe — o de codificar e o de ensaiar.

    python3 analysis/gerar-notebook-revisao.py
    python3 analysis/gerar-notebook-revisao.py --check   # não escreve, só compara

São dois arquivos com uma diferença só: `04-revisao-assistida.ipynb` grava no
servidor e vale; `05-ensaio.ipynb` monta o mesmo painel com estado descartável,
para o autor ver a tela do avaliador (ou mostrá-la a alguém) sem sujar a segunda
passada. A célula de instalação é **a mesma constante** nos dois, e é por isso
que os dois saem daqui: duplicada à mão, ela divergiria na primeira mudança de
host, e o ensaio deixaria de ensaiar o que o avaliador executa.

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

NOTEBOOKS = Path(__file__).resolve().parent.parent / "notebooks"
DESTINO = NOTEBOOKS / "04-revisao-assistida.ipynb"
DESTINO_ENSAIO = NOTEBOOKS / "05-ensaio.ipynb"

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


ABERTURA_ENSAIO = """# Ensaio — a tela do 2º codificador, sem gravar nada

Este notebook existe para **você** ver e experimentar o painel antes de entregá-lo
(ou para mostrá-lo a alguém). Ele carrega o mesmo runtime, o mesmo corpus e a mesma
evidência congelada do `04-revisao-assistida`, e monta o painel igual.

**A única diferença é o estado, e ele é descartável.** Duas travas: `offline=True`
faz o painel nascer sem servidor, e o cache vai para um arquivo temporário.
Responda, salve, avance, erre de propósito — nada entra no `coder2-data`, nada
conta como codificação e nada polui a segunda passada.

**Não codifique aqui.** O que você responder morre com a sessão do Colab. A
codificação que vale é a do `04-revisao-assistida`.

Uma consequência visível: o recibo embaixo do painel aparece **cinza**, dizendo
em que arquivo temporário a resposta caiu. No notebook real ele fica **verde** com
a hora quando a resposta chega ao servidor, e **vermelho** quando não chega — e
vermelho ali significa parar.
"""

CONFERIR = """## O que vale olhar enquanto você mexe

- **O cabeçalho**: quantos documentos o serviço tem, quantos são vinculantes, a
  data do congelamento e a vantagem (`IT`). É o que garante que os dois
  codificadores leram o mesmo texto.
- **As duas listas, separadas e rotuladas.** Primeiro o piso da varredura do §3
  — regex sobre o texto congelado, com aviso onde o termo costuma dar falso
  positivo. Depois o que o modelo acrescentou. Nessa ordem ele só pode somar.
- **O portão.** Tente avançar sem preencher a evidência ou o log do §3: a
  variável não fecha e a tela diz o que falta.
- **A ausência do botão de sugestão.** A evidência congelada traz citação e não
  sugestão de código, de propósito — quem atribui o código é o avaliador.
- **O recibo**, embaixo de tudo.
"""


def celula_ensaio() -> str:
    """A célula do ensaio. O dropdown sai do roster, que é a razão de gerar."""
    return f'''#@title Ensaio — escolha o serviço e rode {{ display-mode: "form" }}
SERVICO = "Pinterest" #@param {json.dumps(C.SERVICOS, ensure_ascii=False)}

import tempfile
from pathlib import Path
import coding_flow as F

# Duas travas, não uma. `configurar(offline=True)` faz o Estado padrão nascer
# sem servidor E corta qualquer chamada de modelo ao vivo — a evidência
# congelada continua sendo lida, que é justamente o que se quer ver. O Estado
# explícito manda o cache para um arquivo temporário, para não haver como
# confundir com o `coder2-local.json` de uma sessão de verdade.
R.configurar(offline=True)
ensaio = F.Estado(offline=True,
                  cache=Path(tempfile.mkdtemp(prefix="ensaio-")) / "estado.json")
print(f"ENSAIO · {{SERVICO}} · nada sai desta sessão ({{ensaio.cache}})")

R.painel(SERVICO, estado=ensaio)
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


def montar_ensaio() -> dict:
    celulas = [celula("markdown", ABERTURA_ENSAIO, 0),
               celula("code", SETUP, 1),
               celula("code", celula_ensaio(), 2),
               celula("markdown", CONFERIR, 3)]
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
    saidas = [(DESTINO, montar()), (DESTINO_ENSAIO, montar_ensaio())]
    if "--check" in sys.argv:
        problemas = []
        for destino, nb in saidas:
            texto = json.dumps(nb, ensure_ascii=False, indent=1) + "\n"
            if not destino.exists():
                problemas.append(f"{destino.name} não existe; rode sem --check")
            elif destino.read_text(encoding="utf-8") != texto:
                problemas.append(f"{destino.name} divergiu do roster; regenere")
        if problemas:
            print("FALHOU — " + "; ".join(problemas))
            return 1
        print(f"OK — {len(saidas)} notebooks em dia com o roster")
        return 0
    NOTEBOOKS.mkdir(exist_ok=True)
    for destino, nb in saidas:
        destino.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8")
        print(f"{len(nb['cells']):>2} células → {destino.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
