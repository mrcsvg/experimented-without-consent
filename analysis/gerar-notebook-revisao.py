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

ABERTURA = """# Segunda codificação

## O que o estudo mede

Plataformas online testam coisas nos seus usuários todos os dias. Elas mudam o que
aparece no topo da lista, o texto de uma notificação, a posição de um botão, e medem
o efeito comparando grupos de pessoas. Isso se chama experimentação comportamental e
é rotina da indústria.

A pergunta do estudo é estreita e documental: **o que cada plataforma conta ao
usuário sobre isso, e em que tipo de documento ela conta?** Ninguém aqui vai
descobrir quais experimentos existem. O trabalho é ler o que a plataforma declara e
classificar a declaração.

O tipo de documento é o centro do estudo. Uma política de privacidade obriga a
plataforma perante o usuário. Um post de blog de engenharia não obriga nada. Quando
os dois falam do mesmo assunto em termos diferentes, essa diferença é o dado.

## Os 26 serviços

Não é uma amostra, é um censo. São os 26 serviços que a Comissão Europeia designou
sob o Digital Services Act: 24 como VLOP (*very large online platform*) e 2 como
VLOSE (*very large online search engine*). A designação depende de escala, acima de
45 milhões de usuários por mês na União Europeia, e traz obrigações próprias.

A unidade de análise é o serviço, não a empresa. O Google Ireland responde por
cinco deles (Search, Maps, Play, Shopping, YouTube) e a Meta por dois (Facebook,
Instagram). Quatro são plataformas de conteúdo adulto, e estão no censo porque são
VLOPs de pleno direito.

Cada serviço tem de 3 a 10 documentos, 157 no total: política de privacidade, termos
de uso, aviso de cookies, tabela de bases legais, e o que a plataforma publicou em
blog ou central de ajuda sobre o assunto.

## Por que existe uma segunda codificação

A primeira passada já foi feita, de forma automatizada. Uma classificação com fonte
única não separa duas coisas: quanto do resultado vem do texto e quanto vem de quem
leu o texto. Duas leituras independentes do mesmo material permitem medir a
concordância entre elas, e é essa medida que torna o resultado defensável diante de
um revisor.

A palavra independente tem uma consequência prática. **Este notebook não mostra o
que a primeira passada codificou, nem os resultados do estudo.** A razão não é
desconfiança. Se você soubesse o que se espera encontrar, sua leitura deixaria de
ser uma segunda medição e passaria a confirmar a primeira.

## O que você faz

Há uma célula por serviço, e as células são independentes entre si. Dentro de uma
célula o trabalho é sequencial: a tela mostra **uma variável por vez**. Você
preenche os campos dela, clica em salvar, e a mesma célula passa para a variável
seguinte. São dez ao todo, as nove variáveis mais o log de palavras-chave, e uma
linha no alto do painel mostra quais já fecharam e em qual você está.

A ordem é fixa de propósito: você responde a V1 antes de a V2 aparecer, e nenhuma
variável fecha sem evidência preenchida. Para rever o que já respondeu, use o botão
de voltar; ele grava o que está na tela antes de sair. Pular adiante não é possível.

Embaixo de cada painel há um campo de **Notas**, para dúvidas de regra, casos de
fronteira e diferenças entre documentos do mesmo serviço. Ele vale para o serviço
inteiro e tem botão próprio de salvar.

Pode parar no meio e fechar o Colab. Quando voltar ao mesmo serviço, o painel abre
na primeira variável que ainda falta, com as anteriores já preenchidas.

**Codifique só por este notebook.** O instrumento em HTML que existiu antes é uma
versão anterior desta ferramenta, e mostra informações que não devem estar na sua
frente durante a codificação.

O critério completo de cada variável está na célula **O codebook, variável por
variável**, logo antes dos serviços. Vale ler uma vez antes de começar.

## As duas listas de evidência, nessa ordem

Primeiro vem a **busca por palavra-chave**: os 12 termos do protocolo procurados
literalmente no texto congelado, endereçados por variável e com o trecho em volta.
Não passa por modelo nenhum. Por ser busca de texto, ela dá sempre o mesmo resultado
e não deixa nada de fora. Alguns trechos chegam com aviso, porque o termo costuma
aparecer em outro sentido ("Code of Ethics" no rodapé não é revisão ética de
experimento). Quem descarta é você.

Depois vem o que **o modelo** localizou. Ele acrescenta o que a palavra-chave não
alcança: passagem que descreve experimentação sem usar nenhum dos 12 termos. Nessa
ordem ele só pode somar.

**Nenhuma das duas atribui código.** A primeira passada já foi automatizada; se um
modelo decidisse aqui também, a concordância mediria o modelo contra ele mesmo. A
evidência do modelo foi gerada numa rodada única e congelada, então todo codificador
vê a mesma tela, e **você não precisa de chave de API para nada**.

## Duas regras que afetam o resultado

**Leia sempre do corpus congelado, nunca da página ao vivo.** As plataformas
reescrevem as políticas sem avisar. Se os dois codificadores lerem versões
diferentes do mesmo documento, a discordância entre vocês fica indistinguível de
mudança no documento, e depois não há como separar as duas.

**Confira o recibo embaixo do painel.** Cada variável que você fecha é gravada num
servidor e versionada, o que permite parar no meio, fechar o Colab e voltar depois,
inclusive de outra máquina. Só não deixe o mesmo serviço aberto em duas janelas ao
mesmo tempo: se uma delas ficar para trás, o painel recusa gravar por cima da outra
e pede para rodar a célula de novo. O recibo fica **verde** quando a resposta chegou ao
servidor e **vermelho** quando não chegou. Vermelho significa parar e avisar: o
arquivo local do Colab é apagado quando a sessão recicla, e o que estiver só nele se
perde.
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
      f"{len(corpus.index['services'])} serviços")

# A procedência aparece UMA vez, aqui, e vale para as 26 células abaixo: a data do
# congelamento e o país da captura são do corpus inteiro, não de cada serviço.
# Cada painel leva só o carimbo de uma linha.
R.mostrar_procedencia(corpus)
'''

CHAVE = """## Sem chave de API

A evidência do modelo já está congelada e publicada ao lado do corpus, então o
notebook não chama modelo nenhum e não precisa de credencial.

A célula abaixo confirma que a evidência congelada chegou, e mostra a data em que
foi gerada. Se ela disser que não achou, me avise antes de começar a codificar:
sem ela a busca por palavra-chave continua funcionando, mas você perde as
passagens que o modelo acrescenta.
"""

CUSTO = '''# Confere a evidência congelada. Não chama modelo, não gasta nada.
import json, urllib.request
idx = json.load(urllib.request.urlopen(f"{SITE}/sugestoes/index.json", timeout=60))
total = sum(a["citacoes"] for a in idx["arquivos"])
print(f"evidência congelada: {len(idx['arquivos'])} serviços · {total} citações · "
      f"gerada em {idx['gerado_em'][:10]}")
print(f"modelo: {sorted({a['modelo'] for a in idx['arquivos']})}")
'''

CODEBOOK_MD = """## O codebook, variável por variável

A célula abaixo é o guia de codificação. Ela começa por cinco regras que valem para
todas as variáveis. Depois vem cada variável: a pergunta que ela responde, o que
procurar nos documentos, o que cada opção do formulário significa e os erros mais
comuns. Vale ler a célula inteira uma vez antes de começar, e voltar a ela sempre que
precisar.

No fim da célula está o **texto oficial do codebook**, congelado em 04/07/2026. O guia
diz as mesmas regras em linguagem direta. Em caso de dúvida, vale o texto oficial.

Nas células de trabalho fica só um lembrete de uma linha por variável.

Os exemplos reais do estudo piloto não entram aqui. Cada um vem de um serviço do
censo e mostra como ele foi codificado no piloto. Num bloco único, eles poriam a
resposta de um serviço na sua frente enquanto você codifica outro.
"""

CODEBOOK = """# Mostra as dez variáveis com o critério completo. Nada de rede, nada de modelo.
R.mostrar_codebook()
"""

SERVICOS_MD = """## Os 26 serviços

Cada célula abaixo é independente: rode na ordem que quiser, pare no meio,
volte depois. O que já foi respondido reaparece preenchido.
"""

FECHAMENTO = '''# Onde a segunda codificação está. Só contagens: nenhuma resposta aparece aqui.
# "Completo" é a mesma definição do painel: as dez variáveis com o portão fechado.
import coding_flow as F
e = F.Estado()
andamento = {s: F.Fluxo(s, e).progresso() for s in R.C.SERVICOS}
completos = sum(1 for feitas, total in andamento.values() if feitas == total)
print(f"{completos}/26 serviços com as dez variáveis fechadas")
for s, (feitas, total) in sorted(andamento.items(), key=lambda x: -x[1][0]):
    if feitas:
        print(f"  {feitas:2d} de {total} · {s}")
'''


ABERTURA_ENSAIO = """# Ensaio: a tela do 2º codificador, sem gravar nada

Este notebook existe para **você** ver e experimentar o painel antes de entregá-lo
(ou para mostrá-lo a alguém). Ele carrega o mesmo runtime, o mesmo corpus e a mesma
evidência congelada do `04-revisao-assistida`, e monta o painel igual.

**A única diferença é o estado, e ele é descartável.** Duas travas: `offline=True`
faz o painel nascer sem servidor, e o cache vai para um arquivo temporário.
Responda, salve, avance, erre de propósito: nada entra no `coder2-data`, nada
conta como codificação e nada polui a segunda passada.

**Não codifique aqui.** O que você responder morre com a sessão do Colab. A
codificação que vale é a do `04-revisao-assistida`.

Uma consequência visível: o recibo embaixo do painel aparece **cinza**, dizendo
em que arquivo temporário a resposta caiu. No notebook real ele fica **verde** com
a hora quando a resposta chega ao servidor, e **vermelho** quando não chega; e
vermelho ali significa parar.
"""

CONFERIR = """## O que vale olhar enquanto você mexe

- **O cabeçalho**: quantos documentos o serviço tem, quantos são vinculantes, a
  data do congelamento e a vantagem (`IT`). É o que garante que os dois
  codificadores leram o mesmo texto.
- **As duas listas, separadas e com explicação.** Primeiro a busca por
  palavra-chave, com aviso onde o termo costuma dar falso positivo. Depois o que
  o modelo acrescentou. Nessa ordem ele só pode somar.
- **O portão.** Tente avançar sem a evidência ou sem o log de palavras-chave: a
  variável não fecha e a tela diz o que falta.
- **A ausência do botão de sugestão.** A evidência congelada traz citação e não
  sugestão de código, de propósito: quem atribui o código é o avaliador.
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
    add("markdown", CODEBOOK_MD)
    add("code", CODEBOOK)
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
    # O codebook entra aqui também: com o critério fora da célula de trabalho, ver
    # "a mesma experiência do avaliador" inclui ver onde o critério foi morar.
    celulas = [celula("markdown", ABERTURA_ENSAIO, 0),
               celula("code", SETUP, 1),
               celula("markdown", CODEBOOK_MD, 2),
               celula("code", CODEBOOK, 3),
               celula("code", celula_ensaio(), 4),
               celula("markdown", CONFERIR, 5)]
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
