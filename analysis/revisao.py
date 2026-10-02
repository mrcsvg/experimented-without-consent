#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Revisão assistida: o modelo localiza a evidência, o avaliador decide o código.

    import revisao as R
    R.configurar(corpus="https://…/corpus-md/")   # ou uma pasta local
    R.painel("Facebook")                           # uma célula por serviço

    python3 analysis/revisao.py --self-test

O QUE O MODELO FAZ E O QUE ELE NÃO FAZ. O caro, na codificação, é achar a
passagem: são 142 documentos, alguns de 60 mil caracteres, e a maior parte deles
não diz nada sobre experimentação. Isso é busca, e busca é máquina. O que a
máquina não pode fazer é o veredito — não porque erraria mais que o humano, mas
porque a passada 1 também foi automatizada, e um κ entre duas rodadas de modelo
não mede concordância entre codificadores: mede o modelo consigo mesmo. O
número que o paper reporta deixaria de significar o que ele diz significar.

Daí a divisão: o painel entrega as citações verbatim já localizadas, e o
código é do avaliador.

A TELA MOSTRA DUAS LISTAS, e a ordem importa. A primeira é a varredura
determinística dos 12 termos do protocolo, endereçada por variável (`piso`): uma
regex sobre o texto congelado não esquece nada, roda sem rede e sem chave, e
chega com a nota de falso positivo quando o termo tem uma. A triagem é do
avaliador. A segunda é o que o modelo acrescentou. Nessa ordem ele só pode somar.

Foi a validação de 20/09/2026 que impôs esse desenho. Ela mediu o modelo
filtrando em silêncio os hits de `ethics` e `risk assessment` do Zalando —
acertando o conteúdo, porque eram menu e antifraude, mas tirando do avaliador uma
triagem que era dele. E mediu duas rodadas do mesmo serviço devolvendo seleções
diferentes, com Jaccard de 0,00 numa variável.

POR ISSO A EVIDÊNCIA DO MODELO É CONGELADA. `congelar-sugestoes.py` roda uma vez
e publica as citações ao lado do corpus; `congelada()` as lê. Todo avaliador vê a
mesma tela, ninguém precisa de chave de API, e o arquivo é citável no método. O
arquivo publicado NÃO traz a sugestão de código: ela existe apenas no caminho ao
vivo, atrás de um botão cujo clique fica registrado, para separar conferência de
influência. Num arquivo público ela seria legível direto, e o botão viraria
enfeite.

CITAÇÃO QUE NÃO EXISTE NO CORPUS É DESCARTADA. Toda `verbatim` devolvida pelo
modelo é procurada no texto congelado (com espaço em branco normalizado) e
jogada fora se não for localizável ali. É a mesma regra do notebook 02. Uma
citação inventada que chegasse à tela seria pior que nenhuma: ela parece
evidência.

AS ÂNCORAS DO PILOTO SÃO SUPRIMIDAS TAMBÉM PARA O MODELO. O instrumento esconde
do avaliador humano a âncora que nomeia o serviço sendo codificado. Mandá-la no
prompt seria contar ao modelo a resposta que o desenho decidiu não contar ao
humano.

Dependências: `anthropic` para a chamada; `ipywidgets` para o painel (ambos já
existem no Colab). Sem nenhum dos dois o módulo ainda carrega, varre o corpus e
imprime em texto — é assim que o self-test roda.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codebook as C  # noqa: E402
import coding_flow as F  # noqa: E402
import patterns as P  # noqa: E402


# `build-md-corpus.py` tem hífen no nome e não é importável por `import`. O que
# precisamos dele é o par separar/sha256; reescrevê-los aqui seria a segunda
# transcrição que o resto do pacote evita, então carregamos por caminho.
def _carregar_builder():
    import importlib.util
    caminho = Path(__file__).resolve().parent / "build-md-corpus.py"
    spec = importlib.util.spec_from_file_location("build_md_corpus", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _carregar_builder()

MODELO_PADRAO = "claude-opus-5"
# Teto de saída: cobre pensamento adaptativo + o JSON das citações. Vai junto no
# arquivo congelado, como parâmetro de geração — 16 mil truncou o Bing.
MAX_TOKENS = 64000
CORPUS_PADRAO = "corpus-md"
TIMEOUT = 60


# --------------------------------------------------------------- configuração

@dataclass
class Config:
    corpus: object = CORPUS_PADRAO
    modelo: str = MODELO_PADRAO
    offline: bool = False
    _corpus_obj: object = None


CFG = Config()


def configurar(corpus=None, modelo=None, offline=None):
    """Chame uma vez, na primeira célula. Devolve o corpus já carregado."""
    if corpus is not None:
        CFG.corpus, CFG._corpus_obj = corpus, None
    if modelo is not None:
        CFG.modelo = modelo
    if offline is not None:
        CFG.offline = offline
    return corpus_carregado()


def _de_onde(idx) -> tuple:
    cod = idx.get("vantage") or "?"
    pais = VANTAGENS.get(cod, cod)
    onde = (f"capturado na União Europeia (VPN com saída na {pais})" if cod in UE
            else f"capturado em {pais}")
    return _data_br(idx.get("frozen_at")), onde


# Legenda da lista de documentos. Igual nos 26 serviços, como a procedência — e
# pelo mesmo motivo vai para o alto do notebook em vez de repetir em cada painel.
LEGENDA_DOCUMENTOS = (
    "O nome do arquivo abre o <b>texto congelado</b>, que é o que você codifica; "
    "<b>original ↗</b> abre a página ao vivo, só para conferir procedência.<br>"
    "<b>vinculante</b> = política ou termos que a plataforma se obriga a cumprir · "
    "<b>não vinculante</b> = blog, central de ajuda, wiki técnica · "
    "<b>sem classificação</b> = o congelamento não registrou o papel. A etiqueta é "
    "uma dica e muitas vezes falta: quem decide se um documento é vinculante é você, "
    "pela função dele (ver as regras gerais no codebook).")


def procedencia(corpus=None) -> str:
    """De onde vem o texto e por que é este. Igual para os 26 serviços.

    Vive fora do `Painel` porque não é propriedade de serviço nenhum: a data do
    congelamento e o país da captura são do corpus inteiro. Repetido em cada uma
    das 26 células, o parágrafo virava coisa que se aprende a pular — e é
    justamente a instrução que não pode ser pulada. Então o texto longo aparece
    uma vez, na célula de instalação, e cada painel leva a linha curta.
    """
    quando, onde = _de_onde((corpus or corpus_carregado()).index)
    return (f"O texto foi congelado em {quando}, {onde}. É esta versão que vale, e é dela "
            "que você codifica, nunca da página ao vivo. Duas razões: as plataformas "
            "mostram texto diferente conforme o país de quem acessa, e por isso a captura "
            "foi feita da UE; e elas reescrevem as políticas sem avisar, então se cada "
            "codificador ler uma versão diferente, a discordância entre vocês fica "
            "indistinguível de mudança no documento, e depois não há como separar as duas.")


def procedencia_curta(corpus=None) -> str:
    """A mesma coisa em uma linha, para o carimbo de cada painel."""
    quando, onde = _de_onde((corpus or corpus_carregado()).index)
    return (f"texto congelado em {quando} · {onde} · leia daqui, nunca da página ao vivo")


def mostrar_procedencia(corpus=None):
    """O que vale para os 26 serviços, dito uma vez no alto do notebook.

    Duas coisas moram aqui: de onde o texto vem e como ler a lista de documentos
    de cada painel. Nenhuma das duas depende do serviço, e as duas eram repetidas
    26 vezes — o que transforma instrução em moldura, que se aprende a pular.
    """
    texto = procedencia(corpus)
    try:
        from IPython.display import display, HTML
    except ImportError:
        print(texto)
        print(re.sub("<[^>]+>", "", LEGENDA_DOCUMENTOS.replace("<br>", "\n")))
        return
    caixa = ("border-left:3px solid #0a7;background:#f6fbf9;padding:10px 14px;"
             "max-width:820px;font-size:13px;line-height:1.55;margin-top:8px")
    display(HTML(f"<div style='{caixa}'>"
                 f"<b>De onde vem o texto que você vai ler</b><br>{_esc(texto)}</div>"
                 f"<div style='{caixa}'>"
                 f"<b>Como ler a lista de documentos de cada serviço</b><br>"
                 f"{LEGENDA_DOCUMENTOS}</div>"))


FONTE_CRIT = "texto exato do codebook v2, congelado em 04/07/2026"


def _regras_gerais(corpus=None) -> str:
    """As regras que valem para as dez variáveis, ditas uma vez antes delas."""
    sem_papel = ""
    try:
        idx = (corpus or corpus_carregado()).index
        docs = [d for sv in idx["services"] for d in sv["docs"]]
        n = sum(1 for d in docs if d.get("role") == "unknown")
        if n:
            sem_papel = (f" Neste corpus, {n} dos {len(docs)} documentos estão como "
                         f"<i>sem classificação</i>, incluindo políticas de privacidade.")
    except Exception:  # sem corpus carregado o guia ainda serve; só sem o número
        pass
    itens = [
        ("Codifique só pelo que está escrito",
         "nos documentos congelados deste notebook. O que você sabe da plataforma por "
         "outras fontes não entra."),
        ("Evidência é a frase exata",
         "copiada do documento, com o nome do documento de onde ela veio."),
        ("Vinculante ou não vinculante se decide pela função do documento",
         "e não pela etiqueta que aparece ao lado dele. A etiqueta vem do congelamento e "
         "muitas vezes falta." + sem_papel + " Política de privacidade, termos de uso, "
         "aviso de cookies e tabela de bases legais são vinculantes. Blog, central de "
         "ajuda e páginas de pesquisa não são. Na dúvida, pergunte se o documento se "
         "declara parte do acordo com o usuário."),
        ("No tem dois casos.",
         "O documento pode tratar do assunto e não oferecer o mecanismo, ou o assunto pode "
         "nunca aparecer. Nos dois casos a resposta é No; diga qual dos dois é."),
        ("Dúvida sobre a regra não trava o trabalho.",
         "Codifique a sua melhor leitura e anote a dúvida no campo Notas, embaixo do painel "
         "de cada serviço. A discussão acontece depois, quando as duas codificações forem "
         "comparadas."),
    ]
    lis = "".join(f"<li><b>{t}</b> {d}</li>" for t, d in itens)
    return (f"<h4 style='margin:4px 0 4px'>Cinco regras que valem para todas as variáveis</h4>"
            f"<ol style='font-size:13px;line-height:1.55'>{lis}</ol>")


def codebook_html(corpus=None) -> str:
    """O guia das dez variáveis, e no fim o texto oficial. Sem as âncoras do piloto.

    O codificador lê o guia: para cada variável, a pergunta que ela responde, o que
    procurar, o que cada opção do formulário significa e os cuidados. O texto
    oficial do codebook vem depois, todo junto, porque é ele que vale e não pode
    ser reescrito (`codebook.criterio`); repeti-lo variável por variável, ao lado
    do guia, punha três versões da mesma regra na tela.

    As âncoras do piloto nomeiam serviços, e o instrumento as suprime para não pôr
    a resposta no campo de visão de quem decide. Num bloco único não há serviço em
    tela para suprimir contra, então nenhuma entra. Quem quiser consultá-las
    deliberadamente tem `protocol/codebook-v2.md`.
    """
    partes = [_regras_gerais(corpus)]
    for v in C.VARIAVEIS:
        partes.append(
            f"<div style='margin-top:22px;padding-top:10px;border-top:1px solid #e5e5e5'>"
            f"<h4 style='margin:0'>[{_esc(v.vid)}] {_esc(C.pergunta(v.vid))}</h4>"
            f"<div style='color:#888;font-size:11.5px;margin-bottom:4px'>"
            f"{_esc(v.titulo)}</div>"
            f"<div style='font-size:13px;line-height:1.55'>{C.glosa_criterio(v.vid)}</div>"
            f"</div>")
    oficiais = "".join(
        f"<div style='margin-top:10px'><b>[{_esc(v.vid)}] {_esc(v.titulo)}</b>"
        f"<div style='color:#555;font-size:12.5px'>{C.criterio(v.crit_key)}</div></div>"
        for v in C.VARIAVEIS if C.criterio(v.crit_key))
    partes.append(
        f"<div style='margin-top:30px;padding-top:12px;border-top:2px solid #ccc'>"
        f"<h4 style='margin:0'>Texto oficial do codebook</h4>"
        f"<div style='color:#666;font-size:12px;max-width:780px'>{FONTE_CRIT}. O guia "
        f"acima diz as mesmas regras em linguagem direta. Em caso de dúvida, vale este "
        f"texto, que é o que a primeira codificação usou.</div>{oficiais}</div>")
    return "".join(partes)


def mostrar_codebook(corpus=None):
    """Exibe o codebook uma vez, no alto do notebook.

    O critério é igual nos 26 serviços, como a procedência e a legenda — e é longo.
    Dez blocos desses repetidos 26 vezes transformariam a célula de trabalho num
    documento, e o que ela precisa ser é uma tela de decisão. Aqui aparece uma vez;
    na célula de trabalho fica o lembrete de uma linha e o ponteiro para cá.
    """
    try:
        from IPython.display import display, HTML
    except ImportError:
        print(re.sub(r"\n\s*\n+", "\n\n",
                     re.sub("<[^>]+>", "", codebook_html(corpus).replace("<h4", "\n<h4"))))
        return
    display(HTML(f"<div style='max-width:820px'>{codebook_html(corpus)}</div>"))


def corpus_carregado() -> "Corpus":
    if CFG._corpus_obj is None:
        CFG._corpus_obj = Corpus(CFG.corpus)
    return CFG._corpus_obj


# --------------------------------------------------------------------- corpus

# A tela falava em "vantagem IT" e "[binding]" — código interno de quem montou o
# congelamento, não vocabulário de quem codifica. Estes três mapas existem para a
# tela dizer o que a coisa é.
VANTAGENS = {"IT": "Itália", "DE": "Alemanha", "FR": "França", "IE": "Irlanda",
             "NL": "Países Baixos", "ES": "Espanha", "BR": "Brasil",
             "US": "Estados Unidos"}
UE = {"IT", "DE", "FR", "IE", "NL", "ES"}
PAPEIS = {"binding": "vinculante", "non-binding": "não vinculante",
          "unknown": "sem classificação"}


def _data_br(iso) -> str:
    """'2026-08-03T01:38:14+00:00' → '03/08/2026'."""
    if not iso or len(str(iso)) < 10:
        return "data desconhecida"
    ano, mes, dia = str(iso)[:10].split("-")
    return f"{dia}/{mes}/{ano}"


class Corpus:
    """Os 26 serviços em Markdown, lidos de uma pasta ou de uma URL.

    Cada documento é conferido contra o `sha256_text` do índice na leitura. Não
    bater significa que este arquivo não é o que foi congelado, e aí ele vai
    para a quarentena em vez de ser codificado: documento ilegível e documento
    que não menciona experimentação produzem o mesmo zero na tela, e só o
    segundo é achado.
    """

    def __init__(self, origem):
        # Qualquer coisa com esquema vai por urllib; o resto é caminho em disco.
        # Vale `file://` também, e não por acaso: é o que deixa exercitar o
        # caminho de rede no teste sem depender de o site estar no ar.
        self.remoto = bool(re.match(r"^[a-z][a-z0-9+.\-]*://", str(origem)))
        self.origem = str(origem).rstrip("/") if self.remoto else Path(origem)
        self.quarentena: list[dict] = []
        self._cache: dict[str, str] = {}
        self.index = json.loads(self._ler("index.json"))
        self.por_servico = {s["name"]: s for s in self.index["services"]}
        faltando = sorted(set(C.SERVICOS) - set(self.por_servico))
        if faltando:
            raise RuntimeError(f"corpus sem {len(faltando)} serviço(s) do roster: {faltando}")

    def _ler(self, relativo: str) -> str:
        if self.remoto:
            with urllib.request.urlopen(f"{self.origem}/{relativo}", timeout=TIMEOUT) as r:
                return r.read().decode("utf-8")
        return (self.origem / relativo).read_text(encoding="utf-8")

    def ler_irmao(self, relativo: str) -> str:
        """Lê algo ao lado do corpus, não dentro dele — `sugestoes/` é irmão de `md/`.

        A evidência congelada não é corpus: é derivada dele. Misturar as duas
        dentro da mesma pasta faria o `--check` do corpus ter de conhecer arquivo
        que não é documento, e faria quem navega a pasta achar que é.
        """
        if self.remoto:
            base = self.origem.rsplit("/", 1)[0]
            with urllib.request.urlopen(f"{base}/{relativo}", timeout=TIMEOUT) as r:
                return r.read().decode("utf-8")
        return (self.origem.parent / relativo).read_text(encoding="utf-8")

    def url_do_congelado(self, doc) -> str | None:
        """Endereço do documento congelado, para o link da tela abrir ESTE texto.

        O link da tela apontava para a página original, que é o oposto do que a
        tela pede: a página ao vivo já mudou, e codificar a partir dela desfaz o
        congelamento. A original continua na tela, num link separado e rotulado,
        porque conferir procedência é legítimo — codificar dali não é.
        """
        return f"{self.origem}/{doc['file']}" if self.remoto else None

    # ------------------------------------------------------------- consultas
    def docs(self, servico: str) -> list[dict]:
        return list(self.por_servico[servico]["docs"])

    def texto(self, doc: dict) -> str | None:
        """Corpo congelado do documento, ou None se ele estiver em quarentena."""
        if doc["file"] in self._cache:
            return self._cache[doc["file"]]
        try:
            bruto = self._ler(doc["file"])
        except Exception as e:  # rede, permissão, arquivo sumido
            self.quarentena.append({"file": doc["file"], "motivo": f"não abriu: {e}"})
            return None
        _, corpo = B.separar(bruto)
        if B.sha256(corpo) != doc["sha256_text"]:
            self.quarentena.append({"file": doc["file"], "motivo": "sha256 não confere"})
            return None
        self._cache[doc["file"]] = corpo
        return corpo

    def excluidos(self, servico: str) -> list[dict]:
        """Documentos que o congelamento perdeu neste serviço, com o motivo."""
        return [e for e in self.index.get("excluidos", []) if e.get("servico") == servico]


# ------------------------------------------------------------------ varredura

def varredura(servico: str, corpus: "Corpus | None" = None) -> list[dict]:
    """O log do §3 deste serviço: 12 termos por documento, com contexto.

    Devolve a mesma forma que `coding_flow.Fluxo` espera no dossiê, para o
    painel e o fluxo linear lerem a mesma coisa.
    """
    corpus = corpus or corpus_carregado()
    saida = []
    for doc in corpus.docs(servico):
        texto = corpus.texto(doc)
        if texto is None:
            continue
        counts, hits = P.scan_text(texto)
        saida.append({
            "file": doc["file"], "url": doc["url"], "role": doc["role"],
            "sha256": doc["sha256_text"], "chars": doc["chars"], "counts": counts,
            "log_line": " / ".join(f"{t}:{n}" for t, n in counts.items()),
            "hits": [{"term": h.term, "kwic": h.kwic, "flag": h.flag} for h in hits],
        })
    return saida


# --------------------------------------------------------- piso determinístico

# Endereço de cada termo do §3: a qual variável o hit interessa. É endereço, não
# julgamento — o hit chega à tela da variável, e quem decide se ele vale é o
# avaliador. Um termo pode servir a mais de uma.
TERMO_PARA_VARIAVEL = {
    "experiment": ("V1", "V3"),
    "A-B": ("V1", "V3"),
    "randomize": ("V1", "V3"),
    "control group": ("V1", "V3"),
    "test": ("V1", "V6"),
    "trial": ("V1", "V6"),
    "beta": ("V6",),
    "debrief": ("V7",),
    "ethics": ("V8",),
    "review board": ("V8",),
    "IRB": ("V8",),
    "risk assessment": ("V8",),
}

# Por (variável, termo, documento). Sem teto, 421 ocorrências de "experiment"
# afogariam a V1; a contagem completa por documento continua na lista de
# documentos e no log do §3, que é o que o codebook exige registrar.
TETO_POR_TERMO_DOC = 3


def piso(servico: str, corpus: "Corpus | None" = None, dossie: list | None = None) -> dict:
    """Hits da varredura determinística, endereçados por variável. O chão da tela.

    Uma regex sobre o texto congelado não esquece nada, e é por isso que ela vem
    primeiro: o que o modelo devolve só pode ACRESCENTAR. A triagem segue sendo
    do avaliador, e o hit chega com a nota de falso positivo quando o termo tem
    uma — distinguir "Our Code of Ethics" no menu de revisão ética de
    experimento é julgamento, e julgamento não é da máquina.

    POR QUE ESTE PISO EXISTE. Medido em 20/09/2026, na validação: no Zalando o
    modelo filtrou em silêncio os hits de `ethics` e `risk assessment`. Sobre o
    conteúdo ele estava certo — eram item de menu e escore antifraude —, mas
    quem tinha de descartar era o avaliador, e ele nunca os viu. O modelo também
    não devolvia a mesma seleção em duas rodadas. Com o piso, a tela deixa de
    depender de qual passagem o modelo achou decisiva naquela vez.
    """
    dossie = dossie if dossie is not None else varredura(servico, corpus)
    por_variavel: dict[str, list] = {}
    for d in dossie:
        vistos: dict[tuple, int] = {}
        for h in d["hits"]:
            for vid in TERMO_PARA_VARIAVEL.get(h["term"], ()):
                chave = (vid, h["term"], d["file"])
                vistos[chave] = vistos.get(chave, 0) + 1
                if vistos[chave] > TETO_POR_TERMO_DOC:
                    continue
                por_variavel.setdefault(vid, []).append({
                    "termo": h["term"], "kwic": h["kwic"], "flag": h["flag"],
                    "file": d["file"], "role": d["role"],
                    "total_no_doc": d["counts"][h["term"]],
                })
    return por_variavel


# ------------------------------------------------------------------ o modelo

SISTEMA = """Você localiza evidência em documentos congelados de plataformas online. \
Você NÃO codifica: quem atribui o código é o avaliador humano.

Regras absolutas:
1. Toda citação tem que ser VERBATIM do documento fornecido, copiada caractere a \
caractere. Citação parafraseada, resumida ou reconstruída é descartada na verificação.
2. Se um documento não sustenta a variável, devolva lista de citações vazia. \
Ausência é um achado do estudo, não uma falha sua — não force uma citação fraca.
3. Não use conhecimento externo sobre a plataforma. Só o texto fornecido conta.
4. A sugestão de código é opinião auxiliar, e o avaliador pode nunca vê-la. \
Marque `confianca` como "baixa" quando a evidência for ambígua."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "variaveis": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "vid": {"type": "string"},
                    "citacoes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "doc": {"type": "integer"},
                                "verbatim": {"type": "string"},
                                "onde": {"type": "string"},
                                "por_que": {"type": "string"},
                            },
                            "required": ["doc", "verbatim", "onde", "por_que"],
                            "additionalProperties": False,
                        },
                    },
                    "sugestao": {"type": "string"},
                    "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
                },
                "required": ["vid", "citacoes", "sugestao", "confianca"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["variaveis"],
    "additionalProperties": False,
}


@dataclass
class Sugestao:
    servico: str
    modelo: str
    por_variavel: dict = field(default_factory=dict)
    descartadas: list = field(default_factory=list)
    uso: dict = field(default_factory=dict)
    # De onde a evidência veio: congelada (o caminho do avaliador) ou chamada ao
    # vivo (desenvolvimento). Vai para o registro, porque muda o que o dado é.
    origem: dict = field(default_factory=lambda: {"fonte": "ao vivo"})


def _cliente():
    """Cliente Anthropic com a chave vinda do cofre, nunca de dentro do notebook.

    Ordem: `EWC_ANTHROPIC_KEY`, depois `ANTHROPIC_API_KEY`, depois os Secrets do
    Colab (o cadeado na barra lateral, com "Notebook access" ligado). A chave
    nunca entra numa célula — este repositório é público, e output de notebook
    já viajou para dentro de clone antes (ver `nb-clean.py`).

    POR QUE UM NOME PRÓPRIO VEM PRIMEIRO. Numa máquina de trabalho, exportar
    `ANTHROPIC_API_KEY` no perfil do shell muda o comportamento de outras
    ferramentas: a CLI do Claude, por exemplo, passa a autenticar por chave de
    API e a cobrar creditos de API em vez do plano. `EWC_ANTHROPIC_KEY` só
    existe para este projeto, e quem exporta essa não altera mais nada.
    """
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("falta o SDK: pip install -q anthropic")
    chave = os.environ.get("EWC_ANTHROPIC_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not chave:
        try:
            from google.colab import userdata
            chave = userdata.get("ANTHROPIC_API_KEY")
        except Exception:
            chave = None
    if not chave:
        raise RuntimeError(
            "sem chave. Local: exporte EWC_ANTHROPIC_KEY no perfil do shell. "
            "No Colab: cadeado da barra lateral → novo secret ANTHROPIC_API_KEY "
            "→ ligar 'Notebook access'.")
    return anthropic.Anthropic(api_key=chave, timeout=600.0)


def impressao_do_prompt() -> str:
    """Identidade do que o modelo recebeu: prompt de sistema + esquema de saída.

    Vai no relatório da validação e em cada arquivo de evidência congelada. Se o
    prompt mudar, a validação caduca e a evidência foi gerada sob outras regras —
    e isso tem de ser legível sem comparar arquivos à mão.
    """
    corpo = SISTEMA + json.dumps(ESQUEMA, sort_keys=True)
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()[:12]


def _normalizar(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip().lower()


def _prompt(servico: str, docs: list[dict], textos: dict[str, str]) -> str:
    partes = [f"SERVIÇO: {servico}", "", "DOCUMENTOS CONGELADOS:"]
    for doc in docs:
        texto = textos.get(doc["file"])
        if texto is None:
            continue
        partes.append(
            f"\n<documento id=\"{doc['n']}\" registro=\"{doc['role']}\" "
            f"url=\"{doc['url']}\">\n{texto}\n</documento>")

    partes += ["", "VARIÁVEIS A LOCALIZAR (codebook v2, congelado):"]
    for v in C.VARIAVEIS:
        if v.crit_key == "kw":
            continue  # o log de palavras-chave é contagem determinística, não busca
        # `ancoras` já devolve suprimida a âncora que nomeia este serviço.
        mostrar, _ = C.ancoras(v.crit_key, servico)
        criterio = re.sub(r"<[^>]+>", "", C.criterio(v.crit_key))
        criterio = re.sub(r"\s+", " ", criterio).strip()
        opcoes = []
        for campo in v.campos:
            if campo.opcoes:
                opcoes.append(f"{campo.chave}: {', '.join(o for o in campo.opcoes if o)}")
        partes.append(
            f"\n[{v.vid}] {v.titulo}\ncritério: {criterio}"
            + (f"\nvalores: {' | '.join(opcoes)}" if opcoes else "")
            + (f"\nâncoras do piloto: {'; '.join(re.sub(r'<[^>]+>', '', a) for a in mostrar)}"
               if mostrar else ""))

    partes.append(
        "\nPara cada variável devolva as citações verbatim que um avaliador "
        "precisaria ler para decidir, com o id do documento e onde no documento. "
        "`sugestao` recebe o valor do primeiro campo da variável.")
    return "\n".join(partes)


def sugerir(servico: str, corpus: "Corpus | None" = None, modelo: str | None = None,
            cliente=None) -> Sugestao:
    """Uma chamada por serviço. Devolve evidência verificada + sugestão."""
    corpus = corpus or corpus_carregado()
    modelo = modelo or CFG.modelo
    docs = corpus.docs(servico)
    textos = {d["file"]: corpus.texto(d) for d in docs}
    por_id = {d["n"]: d for d in docs}

    cliente = cliente or _cliente()
    with cliente.messages.stream(
        model=modelo,
        # O teto cobre pensamento + JSON. Com 16 mil, o Bing (405 mil caracteres,
        # muitas citações) truncou o JSON no meio de uma string: o pensamento
        # adaptativo come parte do teto, e o que sobrou não bastou. Streaming
        # permite teto alto sem risco de timeout, e teto alto não gasta mais —
        # o modelo para quando acaba.
        max_tokens=MAX_TOKENS,
        system=SISTEMA,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": ESQUEMA}},
        messages=[{"role": "user", "content": _prompt(servico, docs, textos)}],
    ) as fluxo:
        resposta = fluxo.get_final_message()

    parada = getattr(resposta, "stop_reason", None)
    if parada == "refusal":
        raise RuntimeError(f"o modelo recusou ({resposta.stop_details}) — recorte o pedido")
    # Truncamento tem de ser erro explícito. Sem esta porta, a resposta cortada
    # chega ao `json.loads` e estoura com "Unterminated string" — mensagem que não
    # diz o que aconteceu —, e no caso pior o JSON fecha por acidente e entrega
    # evidência pela metade como se fosse completa.
    if parada == "max_tokens":
        raise RuntimeError(
            f"resposta truncada em {MAX_TOKENS} tokens de saída ({servico}): a evidência "
            f"viria pela metade. Aumente MAX_TOKENS ou divida o serviço por documento.")

    bruto = json.loads(next(b.text for b in resposta.content if b.type == "text"))
    sug = Sugestao(servico=servico, modelo=modelo,
                   uso={"input": resposta.usage.input_tokens,
                        "output": resposta.usage.output_tokens})

    for item in bruto.get("variaveis", []):
        boas, ruins = [], []
        for cit in item.get("citacoes", []):
            doc = por_id.get(cit.get("doc"))
            texto = textos.get(doc["file"]) if doc else None
            if texto and _normalizar(cit["verbatim"]) in _normalizar(texto):
                boas.append({**cit, "file": doc["file"], "role": doc["role"]})
            else:
                ruins.append({"vid": item["vid"], "verbatim": cit.get("verbatim", "")[:120]})
        sug.descartadas += ruins
        sug.por_variavel[item["vid"]] = {
            "citacoes": boas,
            "sugestao": item.get("sugestao", ""),
            "confianca": item.get("confianca", "baixa"),
        }
    return sug


def congelada(servico: str, corpus: "Corpus | None" = None) -> "Sugestao | None":
    """Lê a evidência congelada deste serviço, se estiver publicada ao lado do corpus.

    É o caminho normal do avaliador: sem chave de API, sem chamada, e a mesma
    tela para todo mundo — a validação de 20/09 mostrou que duas rodadas ao vivo
    não devolvem a mesma seleção. O arquivo não traz sugestão de código, então
    aqui ela vem vazia, e é assim que tem de ser.
    """
    corpus = corpus or corpus_carregado()
    try:
        bruto = corpus.ler_irmao(f"sugestoes/{B.slug(servico)}.json")
    except Exception:
        return None
    d = json.loads(bruto)
    if d.get("servico") != servico:
        return None
    sug = Sugestao(servico=servico, modelo=d.get("modelo") or "?", uso=d.get("uso") or {})
    sug.por_variavel = {vid: {"citacoes": cits, "sugestao": "", "confianca": ""}
                        for vid, cits in d.get("citacoes", {}).items()}
    sug.origem = {"fonte": "congelada", "gerado_em": d.get("gerado_em"),
                  "prompt": d.get("prompt"), "corpus_frozen_at": d.get("corpus_frozen_at")}
    return sug


def estimar(servico: str, corpus: "Corpus | None" = None, modelo: str | None = None) -> int:
    """Tokens de entrada da chamada deste serviço, antes de gastar."""
    corpus = corpus or corpus_carregado()
    docs = corpus.docs(servico)
    textos = {d["file"]: corpus.texto(d) for d in docs}
    r = _cliente().messages.count_tokens(
        model=modelo or CFG.modelo, system=SISTEMA,
        messages=[{"role": "user", "content": _prompt(servico, docs, textos)}])
    return r.input_tokens


# --------------------------------------------------------------------- painel

def _esc(t: str) -> str:
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class Painel:
    """Uma célula por serviço: documentos à vista, uma variável por vez.

    A ordem importa e é a do fluxo linear: o avaliador responde V1 antes de V2
    existir. O que o painel acrescenta ao `coding_flow` é a evidência já
    localizada — e o botão que revela a sugestão do modelo, cujo uso fica
    registrado.
    """

    def __init__(self, servico, corpus=None, estado=None, sugestao=None, assistir=True):
        self.corpus = corpus or corpus_carregado()
        self.servico = servico
        self.docs = self.corpus.docs(servico)
        self.dossie_local = varredura(servico, self.corpus)
        # O piso é montado na construção e não depende de rede nem de chave: a
        # tela tem evidência para mostrar mesmo sem o modelo.
        self.piso = piso(servico, self.corpus, self.dossie_local)
        self.estado = estado if estado is not None else F.Estado(offline=CFG.offline)
        # O `Fluxo` resolve o serviço contra o dossiê na construção; passamos o
        # dossiê já chaveado pelo nome canônico, que é o do roster.
        self.fluxo = F.Fluxo(servico, self.estado, {servico: self.dossie_local})
        self.sugestao = sugestao
        self.assistir = assistir
        self.revelou: dict[str, bool] = {}
        self._respondeu: set[str] = set()
        self.recibo = None  # widget do recibo; só existe no modo ipywidgets
        # Carimbo do registro que este painel leu. Se o do servidor ficar mais novo
        # (outra janela, outra máquina), gravar daqui apagaria aquela versão: o
        # servidor guarda o registro do serviço inteiro, não campo a campo.
        self._ts_visto = (self.estado.records.get(servico) or {}).get("_ts") or 0

    # ------------------------------------------------------------ assistência
    def carregar_sugestao(self):
        """Evidência congelada primeiro; chamada ao vivo só se não houver.

        O avaliador nunca deve cair no caminho ao vivo: ele custa chave de API e
        devolve seleção diferente a cada rodada. O caminho ao vivo fica para
        desenvolvimento e para gerar o congelamento.
        """
        if self.sugestao is None:
            self.sugestao = congelada(self.servico, self.corpus)
        if self.sugestao is None and self.assistir and not CFG.offline:
            self.sugestao = sugerir(self.servico, self.corpus)
        return self.sugestao

    def evidencia_de(self, vid: str) -> list[dict]:
        """O que o MODELO acrescentou nesta variável. Pode ser vazio."""
        s = self.sugestao.por_variavel.get(vid, {}) if self.sugestao else {}
        return s.get("citacoes", [])

    def piso_de(self, vid: str) -> list[dict]:
        """O que a varredura determinística achou nesta variável. Nunca esquece."""
        return self.piso.get(vid, [])

    def revelar(self, vid: str) -> dict:
        """Mostra a sugestão do modelo e registra que ela foi vista.

        `antes_de_responder` é o campo que interessa na análise: sugestão vista
        depois da resposta é conferência, vista antes é influência.
        """
        self.revelou[vid] = True
        s = (self.sugestao.por_variavel.get(vid, {}) if self.sugestao else {})
        return {"sugestao": s.get("sugestao", ""), "confianca": s.get("confianca", ""),
                "antes_de_responder": vid not in self._respondeu}

    def _assist_meta(self, vid: str) -> dict:
        s = self.sugestao
        meta = {"modelo": s.modelo if s else None,
                "fonte": (s.origem.get("fonte") if s else "sem assistência"),
                "evidencia_gerada_em": (s.origem.get("gerado_em") if s else None),
                "prompt": (s.origem.get("prompt") if s else None),
                "piso_hits": len(self.piso_de(vid)),
                "revelada": bool(self.revelou.get(vid)),
                "antes_de_responder": bool(self.revelou.get(vid)) and vid not in self._respondeu}
        # Só existe sugestão de código no caminho ao vivo; o arquivo congelado
        # não a publica, e registrar campo vazio faria parecer que houve uma.
        proposta = (s.por_variavel.get(vid, {}).get("sugestao") if s else None)
        if proposta:
            meta["sugestao"] = proposta
        return meta

    def responder(self, vid: str, respostas: dict, rede: bool = True):
        """Grava a resposta do avaliador e a proveniência da assistência."""
        assist = dict(self.fluxo.rec.get("_assist") or {})
        assist[vid] = self._assist_meta(vid)
        self.fluxo.rec["_assist"] = assist
        ok = self.fluxo.responder(respostas, rede=rede)
        self._respondeu.add(vid)
        return ok

    # ------------------------------------------------------------- renderização
    def cabecalho(self) -> str:
        # Sem "(N vinculantes)": a contagem vinha das etiquetas, e a etiqueta falta
        # em 102 dos 157 documentos. O Instagram aparecia com "0 vinculantes",
        # política de privacidade e termos de uso incluídos.
        perdidos = self.corpus.excluidos(self.servico)
        feitas, total = self.fluxo.progresso()
        linhas = [f"{self.servico} · {len(self.docs)} documentos · "
                  f"{feitas} de {total} variáveis respondidas"]
        if perdidos:
            linhas.append(f"⚠ {len(perdidos)} documento(s) que o congelamento não pegou: "
                          "isso é lacuna de corpus, não ausência de divulgação")
        if self.corpus.quarentena:
            linhas.append(f"⚠ {len(self.corpus.quarentena)} em quarentena (hash)")
        return "\n".join(linhas)

    def procedencia(self) -> str:
        return procedencia(self.corpus)

    def procedencia_curta(self) -> str:
        return procedencia_curta(self.corpus)

    def texto_dos_documentos(self) -> str:
        linhas = []
        for doc, d in zip(self.docs, self.dossie_local):
            acesos = [f"{t}:{n}" for t, n in d["counts"].items() if n]
            papel = PAPEIS.get(doc["role"], doc["role"])
            linhas.append(f"  {doc['n']:02d} [{papel:<17}] {Path(doc['file']).name} "
                          f"· {doc['chars']//1000}k · " + (", ".join(acesos) or "nenhum termo"))
        return "\n".join(linhas)

    def imprimir(self, vid: str | None = None):
        """Modo texto — é o que roda fora do Colab (e no self-test)."""
        print(self.cabecalho())
        print(self.procedencia_curta())
        print(self.texto_dos_documentos())
        passo = self.fluxo.atual()
        vid = vid or passo.vid
        feitas, total = self.fluxo.progresso()
        print(f"\n[{passo.vid}] {passo.titulo}  (variável {feitas + 1} de {total} "
              f"nesta célula)\n    {C.lembrete(passo.vid)}")
        chao = self.piso_de(vid)
        print(f"    busca por palavra-chave ({len(chao)} trechos): os 12 termos do "
              "protocolo, sem modelo nenhum; a triagem é sua:")
        for h in chao[:4]:
            nota = f"  ⚠ {h['flag'][:70]}" if h["flag"] else ""
            print(f"      [{h['termo']}] …{h['kwic'][:120]}… · {h['file']}{nota}")
        cits = self.evidencia_de(vid)
        print(f"    acrescentado pelo modelo ({len(cits)} citações): o que a busca "
              "não acha porque não usa os termos:")
        for c in cits[:4]:
            print(f"      “{c['verbatim'][:150]}” · doc {c['doc']} · {c['onde']}")
        pend = self.fluxo.faltando()
        print(f"    portão: {'aberto' if not pend else 'falta ' + ', '.join(k for k, _ in pend)}")

    def _ipywidgets(self):
        try:
            import ipywidgets as W
            from IPython.display import display, HTML
            return W, display, HTML
        except ImportError:
            return None, None, None

    def mostrar(self):
        W, display, HTML = self._ipywidgets()
        if W is None:
            return self.imprimir()
        self.carregar_sugestao()

        def _linha_doc(d, v):
            termos = ", ".join(f"{t}:{n}" for t, n in v["counts"].items() if n) or "nenhum termo"
            nome = Path(d["file"]).name
            congelado = self.corpus.url_do_congelado(d)
            alvo = (f"<a href='{_esc(congelado)}' target='_blank' title='abre o texto "
                    f"congelado, que é o que vale'>{_esc(nome)}</a>" if congelado
                    else _esc(nome))
            return (f"<div style='padding:2px 0'><b>{d['n']:02d}</b> "
                    f"<span style='color:{'#0a7' if d['role'] == 'binding' else '#888'}'>"
                    f"[{_esc(PAPEIS.get(d['role'], d['role']))}]</span> {alvo} "
                    f"<span style='color:#888'>{d['chars'] // 1000}k · {_esc(termos)}</span> "
                    f"<a href='{_esc(d['url'])}' target='_blank' style='color:#aaa;"
                    f"font-size:11px' title='a página ao vivo, só para conferir procedência "
                    f"(não codifique a partir dela)'>original ↗</a></div>")

        docs_html = "".join(_linha_doc(d, v) for d, v in zip(self.docs, self.dossie_local))
        linhas_cab = self.cabecalho().split("\n")
        avisos = "".join(f"<div style='color:#a15c00;font-size:12px'>{_esc(l)}</div>"
                         for l in linhas_cab[1:])

        topo = W.HTML(
            f"<h3 style='margin:0 0 4px'>{_esc(linhas_cab[0])}</h3>{avisos}"
            f"<div style='color:#666;font:12px/1.5 ui-monospace,monospace;margin:4px 0 10px'>"
            f"{_esc(self.procedencia_curta())}</div>"
            f"<div style='font:12px/1.7 ui-monospace,monospace'>{docs_html}</div>")
        area = W.Output()
        # O recibo fica FORA da `area`: `_render_variavel` limpa a área a cada
        # avanço, e recibo que desaparece junto não é recibo. Ele existe porque
        # no Colab o cache local mora em /content, que a sessão apaga ao
        # reciclar — se a gravação não chegar ao servidor e ninguém disser nada,
        # o avaliador codifica uma tarde inteira e perde tudo em silêncio.
        self.recibo = W.HTML(self._recibo_inicial())
        caixa = W.VBox([topo, area, self._bloco_notas(W), self.recibo])
        display(caixa)
        self._render_variavel(area)
        # NÃO devolva a caixa. A célula do notebook é `R.painel("X")`, e o Colab
        # exibe o valor da última expressão da célula — devolver o widget que já
        # foi exibido faz o painel inteiro aparecer duas vezes, como duas visões
        # do mesmo modelo. Quem exibe aqui é o `display` acima, uma vez.
        return None

    # ------------------------------------------------------------------ notas
    def _bloco_notas(self, W):
        """O campo Notas do serviço, fora do fluxo das variáveis.

        O codebook manda "anotar em Notes" em quatro lugares (V1, V2, V3, V7) e na
        regra de dúvida, e o notebook não tinha onde. A chave é `notes`, a mesma do
        instrumento em HTML, então as duas superfícies leem e gravam o mesmo campo.
        Fica fora do `Fluxo` porque não é variável: não tem portão e vale para o
        serviço inteiro.
        """
        caixa = W.Textarea(
            value=self.fluxo.rec.get("notes") or "",
            placeholder="Dúvidas de regra, casos de fronteira, diferenças entre "
                        "documentos do mesmo serviço",
            layout=W.Layout(width="100%", height="70px"))
        botao = W.Button(description="salvar notas")

        def _salvar(_):
            if not self._pode_gravar():
                return
            self.fluxo.rec["notes"] = caixa.value
            ok = self.estado.gravar(self.servico, self.fluxo.rec)
            self._gravou()
            if self.recibo is not None:
                self.recibo.value = self._recibo_notas(ok)
        botao.on_click(_salvar)
        return W.VBox([
            W.HTML("<div style='margin-top:14px'><b>Notas</b> <span style='color:#888;"
                   "font-size:12px'>valem para o serviço inteiro. Salve depois de "
                   "escrever: elas não são gravadas junto com as variáveis.</span></div>"),
            caixa, botao])

    def _recibo_notas(self, ok: bool) -> str:
        if self.estado.offline:
            return (f"<div style='{self._RECIBO};color:#888'>notas gravadas em "
                    f"{_esc(str(self.estado.cache))} (offline, sem servidor)</div>")
        if ok:
            return (f"<div style='{self._RECIBO};color:#0a7'>notas salvas no servidor · "
                    f"{time.strftime('%H:%M:%S')}</div>")
        return (f"<div style='{self._RECIBO};color:#b00'><b>as notas NÃO chegaram ao "
                "servidor</b>. Estão só nesta sessão do Colab, que apaga o arquivo ao "
                "reciclar. Confira a rede e salve de novo.</div>")

    # -------------------------------------------------------- outra janela
    def _alterado_fora(self) -> bool:
        """O registro deste serviço mudou no servidor depois que este painel o leu?"""
        if self.estado.offline:
            return False
        try:
            no_servidor = (self.estado._get().get(self.servico) or {}).get("_ts") or 0
        except Exception:
            return False  # sem rede, a gravação falha e o recibo vermelho já avisa
        return no_servidor > self._ts_visto

    def _pode_gravar(self) -> bool:
        if not self._alterado_fora():
            return True
        if self.recibo is not None:
            self.recibo.value = (
                f"<div style='{self._RECIBO};color:#b00'><b>nada foi gravado.</b> "
                f"{_esc(self.servico)} foi alterado em outra janela ou máquina depois que "
                "este painel abriu, e gravar agora apagaria aquela versão. Rode a célula "
                "de novo para carregar o que está no servidor.</div>")
        return False

    def _gravou(self):
        """Depois de gravar, o carimbo deste painel passa a ser o do que ele gravou."""
        self._ts_visto = (self.estado.records.get(self.servico) or {}).get("_ts") \
            or self._ts_visto

    # ----------------------------------------------------------------- recibo
    _RECIBO = "margin-top:8px;font:12px/1.5 ui-monospace,monospace"

    def _recibo_inicial(self) -> str:
        if self.estado.offline:
            return (f"<div style='{self._RECIBO};color:#888'>modo offline: as "
                    f"respostas ficam só em {_esc(str(self.estado.cache))}</div>")
        if not self.estado.online:
            return (f"<div style='{self._RECIBO};color:#b00'><b>sem contato com o "
                    "servidor</b>. Não comece a codificar: no Colab o arquivo local "
                    "é apagado quando a sessão recicla, então o que você responder "
                    "agora pode não existir amanhã. Rode a célula de novo; se "
                    "continuar assim, avise antes de responder qualquer variável.</div>")
        return (f"<div style='{self._RECIBO};color:#0a7'>servidor respondeu. Cada "
                "variável que fechar é gravada lá, versionada</div>")

    def _recibo_gravacao(self, vid: str, ok: bool) -> str:
        if self.estado.offline:
            return (f"<div style='{self._RECIBO};color:#888'>{_esc(vid)} gravado em "
                    f"{_esc(str(self.estado.cache))} (offline, sem servidor)</div>")
        if ok:
            return (f"<div style='{self._RECIBO};color:#0a7'>{_esc(vid)} salvo no "
                    f"servidor · {time.strftime('%H:%M:%S')}</div>")
        return (f"<div style='{self._RECIBO};color:#b00'><b>{_esc(vid)} NÃO chegou ao "
                "servidor</b>. Está só nesta sessão do Colab, que apaga o arquivo ao "
                "reciclar. Pare aqui, confira a rede e salve de novo antes de "
                "seguir.</div>")

    # As duas listas da tela precisavam de nome e de explicação. "varredura do §3"
    # é referência ao protocolo, não descrição: quem lê a tela não sabe o que é a
    # §3 nem por que ela vem antes do modelo.
    SUB_PISO = ("Os 12 termos do protocolo, procurados <b>literalmente</b> no texto "
                "congelado. Não passa por modelo nenhum: é busca de texto, dá sempre o "
                "mesmo resultado e não deixa nada de fora, e por isso vem primeiro. Boa "
                "parte vai ser falso positivo, e os marcados com ⚠ costumam ser: o aviso "
                "diz por quê. Descartar é seu trabalho; o que a tela garante é que nada "
                "foi escondido de você.")
    SUB_MODELO = ("Passagens que a busca acima não acha, porque descrevem experimentação "
                  "sem usar nenhum dos 12 termos. Foram geradas uma única vez e "
                  "congeladas, então todo codificador vê exatamente estas. O modelo "
                  "localiza; ele não atribui código nenhum.")

    def _trilha_html(self, vid_atual: str) -> str:
        """Onde você está nas dez variáveis, e quais já fecharam.

        A célula mostra uma variável por vez e troca de variável quando você salva.
        Sem esta linha a tela parece pedir só a V1, e não existe nada em volta que
        diga que faltam nove: o contador do cabeçalho some assim que a área é
        redesenhada, e o botão "salvar V1 e avançar" é a única pista.
        """
        pecas = []
        for i, passo in enumerate(self.fluxo.passos):
            if passo.vid == vid_atual:
                pecas.append(f"<b style='background:#eef6ff;border:1px solid #9cf;"
                             f"border-radius:3px;padding:1px 5px'>{_esc(passo.vid)}</b>")
            elif not self.fluxo.faltando(i):
                pecas.append(f"<span style='color:#0a7'>{_esc(passo.vid)}✓</span>")
            else:
                pecas.append(f"<span style='color:#bbb'>{_esc(passo.vid)}</span>")
        feitas, total = self.fluxo.progresso()
        return (f"<div style='font:12px/1.9 ui-monospace,monospace;margin-top:6px'>"
                + " · ".join(pecas) +
                f"<div style='color:#888;font-size:11.5px'>variável {feitas + 1} de "
                f"{total} nesta célula. Ela troca para a próxima quando você salva, "
                f"e você responde as dez antes de passar ao próximo serviço.</div></div>")

    def _render_variavel(self, area):
        import ipywidgets as W
        from IPython.display import display, HTML, clear_output

        passo = self.fluxo.atual()
        vid = passo.vid
        campos = {}
        for campo in passo.campos:
            rotulo = W.Label(campo.rotulo, layout=W.Layout(width="260px"))
            if campo.tipo == "select":
                w = W.Dropdown(options=[o for o in campo.opcoes], value=self.fluxo.rec.get(campo.chave) or "")
            elif campo.tipo == "checks":
                w = W.SelectMultiple(options=[o for o in campo.opcoes if o],
                                     value=tuple(self.fluxo.rec.get(campo.chave) or ()),
                                     rows=min(6, len(campo.opcoes)))
            elif campo.tipo == "line":
                w = W.Text(value=self.fluxo.rec.get(campo.chave) or "",
                           placeholder=campo.placeholder)
            else:
                w = W.Textarea(value=self.fluxo.rec.get(campo.chave) or "",
                               placeholder=campo.placeholder,
                               layout=W.Layout(width="600px", height="80px"))
            campos[campo.chave] = w
        if vid == "KW":
            campos["keyword_log"].value = campos["keyword_log"].value or self.fluxo.log_sugerido()

        cits = self.evidencia_de(vid)
        # Só a frase, o documento e onde ela está. A justificativa do modelo
        # (`por_que`) NÃO vai para a tela: em 446 das 1.440 citações ela dizia o
        # código ("patamar mínimo da escada (nível 1)", "decisivo para
        # v9_register"), ou seja, a sugestão de código que o congelamento omite
        # de propósito voltava por outro campo. A localização é fato; a
        # justificativa é juízo, e o juízo é do avaliador.
        ev = "".join(
            f"<div style='margin:6px 0;padding:6px 10px;border-left:3px solid #0a7'>"
            f"“{_esc(c['verbatim'][:400])}”<br>"
            f"<span style='color:#888;font-size:12px'>doc {c['doc']} · {_esc(c['onde'])}"
            f"</span></div>"
            for c in cits) or "<i style='color:#888'>o modelo não acrescentou nada nesta variável</i>"

        # O piso vem primeiro na tela, em cinza: é o que a regex achou, com a
        # nota de falso positivo quando o termo tem uma. Quem descarta é você.
        chao = self.piso_de(vid)

        def _bloco_piso(h):
            quantos = (f" · {h['total_no_doc']} ocorrências neste documento"
                       if h["total_no_doc"] > 1 else "")
            aviso = (f"<br><span style='color:#a15c00;font-size:11.5px'>⚠ "
                     f"{_esc(h['flag'])}</span>" if h["flag"] else "")
            congelado = self.corpus.url_do_congelado(h)
            onde = (f"<a href='{_esc(congelado)}' target='_blank' style='color:#888'>"
                    f"{_esc(Path(h['file']).name)}</a>" if congelado
                    else _esc(Path(h["file"]).name))
            return (f"<div style='margin:5px 0;padding:5px 10px;border-left:3px solid #999;"
                    f"background:#fafafa;font-size:12.5px'>"
                    f"<b style='color:#555'>[{_esc(h['termo'])}]</b> "
                    f"…{_esc(h['kwic'][:300])}…<br>"
                    f"<span style='color:#888;font-size:11.5px'>"
                    f"{onde}{quantos}</span>{aviso}</div>")

        piso_html = "".join(_bloco_piso(h) for h in chao) or (
            "<div style='color:#888;font-size:12.5px;margin:6px 0'><i>Nenhum dos termos "
            "desta variável aparece nos documentos deste serviço. Isso é informação, não "
            "falha da ferramenta: é o que sustenta codificar ausência.</i></div>")

        # O botão só existe se houver sugestão para revelar. Com a evidência
        # congelada não há: o congelamento publica citação e omite a sugestão de
        # propósito, porque num JSON público ela seria legível direto e o botão
        # viraria enfeite. Enfeite é pior que ausência — o avaliador clica, vê
        # branco e conclui que a ferramenta está quebrada.
        tem_sugestao = bool((self.sugestao.por_variavel.get(vid) or {}).get("sugestao")
                            if self.sugestao else False)
        btn_sug = W.Button(description="ver sugestão do modelo", icon="eye")
        saida_sug = W.Output()

        def _ver(_):
            r = self.revelar(vid)
            with saida_sug:
                clear_output()
                aviso = ("<b style='color:#b00'>revelada ANTES da resposta</b>: "
                         "isso fica registrado") if r["antes_de_responder"] else \
                        "<span style='color:#888'>revelada depois da resposta</span>"
                display(HTML(f"sugestão: <b>{_esc(r['sugestao'])}</b> "
                             f"(confiança {_esc(r['confianca'])})<br>{aviso}"))
        btn_sug.on_click(_ver)

        btn_ok = W.Button(description=f"salvar {vid} e avançar", button_style="success")
        saida_ok = W.Output()

        def _respostas():
            return {chave: (list(w.value) if isinstance(w.value, tuple) else w.value)
                    for chave, w in campos.items()}

        def _salvar(_):
            if not self._pode_gravar():
                return
            ok = self.responder(vid, _respostas())
            self._gravou()
            if self.recibo is not None:
                self.recibo.value = self._recibo_gravacao(vid, ok)
            with saida_ok:
                clear_output()
                pend = self.fluxo.faltando()
                if pend:
                    display(HTML("<b style='color:#b00'>portão fechado</b>: falta " +
                                 _esc(", ".join(f"{k} ({p})" for k, p in pend))))
                    return
            if self.fluxo.avancar():
                self._render_variavel(area)
            else:
                with area:
                    clear_output()
                    display(HTML(f"<b>{_esc(self.servico)} concluído.</b> As dez "
                                 "variáveis estão respondidas e gravadas. Para rever "
                                 "alguma, rode a célula de novo e use o botão de voltar."))
        btn_ok.on_click(_salvar)

        # Voltar grava o que está na tela antes de sair, sem exigir o portão: quem
        # volta no meio de uma variável não perde o que digitou. O portão só
        # decide o avançar.
        btn_volta = W.Button(description="voltar à variável anterior", icon="arrow-left")

        def _voltar(_):
            if not self._pode_gravar():
                return
            ok = self.responder(vid, _respostas())
            self._gravou()
            if self.recibo is not None:
                self.recibo.value = self._recibo_gravacao(vid, ok)
            if self.fluxo.voltar():
                self._render_variavel(area)
        btn_volta.on_click(_voltar)
        botoes = ([btn_volta] if self.fluxo.i > 0 else []) + [btn_ok] + \
                 ([btn_sug] if tem_sugestao else [])

        with area:
            clear_output()
            # O critério inteiro mora no alto do notebook, uma vez. Aqui fica a
            # regra de uma linha (logo abaixo do título) e o ponteiro — a célula de
            # trabalho é tela de decisão, não documento.
            criterio = (f"<div style='color:#888;font-size:11.5px;margin-top:8px'>"
                        f"Critério completo da {_esc(vid)} no alto do notebook, em "
                        f"<b>O codebook, variável por variável</b>.</div>")
            display(HTML(
                self._trilha_html(vid) +
                f"<h4 style='margin:14px 0 2px'>[{vid}] {_esc(passo.titulo)}</h4>"
                f"<div style='color:#555;max-width:780px'>{_esc(C.lembrete(vid))}</div>"
                f"{criterio}"
                f"<div style='margin-top:16px'><b>Busca por palavra-chave: {len(chao)} "
                f"{'trecho' if len(chao) == 1 else 'trechos'}</b>"
                f"<div style='color:#666;font-size:12px;max-width:780px'>{self.SUB_PISO}</div>"
                f"{piso_html}</div>"
                f"<div style='margin-top:16px'><b>Acrescentado pelo modelo: {len(cits)} "
                f"{'citação' if len(cits) == 1 else 'citações'}</b>"
                f"<div style='color:#666;font-size:12px;max-width:780px'>{self.SUB_MODELO}</div>"
                f"{ev}</div>"))
            display(W.VBox([W.HBox([W.Label(c.rotulo, layout=W.Layout(width="260px")), w])
                            for c, w in zip(passo.campos, campos.values())]))
            display(W.HBox(botoes))
            if not tem_sugestao:
                display(HTML("<div style='color:#888;font:12px/1.5 ui-monospace,"
                             "monospace;margin-top:4px'>a evidência congelada traz "
                             "citação, não sugestão de código: quem atribui o código "
                             "é você</div>"))
            display(saida_ok, saida_sug)


def painel(servico: str, **kw):
    """O que cada célula do notebook chama."""
    return Painel(servico, **kw).mostrar()


# ------------------------------------------------------------------ self-test

def _self_test() -> int:
    corpus_dir = os.environ.get("CORPUS_MD", CORPUS_PADRAO)
    falhas = []

    def checar(desc, cond):
        print(("  ok   " if cond else "  FALHA") + f" {desc}")
        if not cond:
            falhas.append(desc)

    print("corpus")
    c = Corpus(corpus_dir)
    checar("os 26 serviços do roster estão no corpus", set(c.por_servico) == set(C.SERVICOS))
    checar("slug de serviço é padronizado",
           all(s["slug"] == B.slug(s["name"]) for s in c.index["services"]))
    doc = c.docs("Pinterest")[0]
    texto = c.texto(doc)
    checar("documento abre e o hash confere", texto is not None)
    checar("vinculante vem primeiro", c.docs("Pinterest")[0]["role"] == "binding")
    checar("front matter não entra no corpo", not texto.startswith("---"))

    print("varredura")
    d = varredura("X", c)
    checar("varredura devolve um item por documento", len(d) == len(c.docs("X")))
    checar("o log do §3 tem os 12 termos", all(len(x["counts"]) == 12 for x in d))

    print("verificação de citação")
    normal = _normalizar("  Olá   MUNDO ")
    checar("normalização colapsa espaço e caixa", normal == "olá mundo")
    checar("citação ausente do texto é rejeitada",
           _normalizar("frase que não existe") not in _normalizar(texto))

    print("prompt")
    p = _prompt("Pinterest", c.docs("Pinterest"),
                {x["file"]: c.texto(x) for x in c.docs("Pinterest")})
    checar("prompt traz os documentos com id", '<documento id="1"' in p)
    checar("prompt traz as 9 variáveis", all(f"[{v.vid}]" in p for v in C.VARIAVEIS if v.crit_key != "kw"))
    # A âncora do piloto que nomeia o serviço tem que estar fora — é o mesmo
    # corte que o instrumento faz para o humano.
    mostrar, ocultas = C.ancoras("v1", "Google Play")
    p_google = _prompt("Google Play", c.docs("Google Play"),
                       {x["file"]: c.texto(x) for x in c.docs("Google Play")})
    checar("âncora do próprio serviço fica fora do prompt",
           not ocultas or all(re.sub("<[^>]+>", "", a)[:40] not in p_google for a in ocultas))

    print("piso determinístico")
    # As três propriedades que o piso tem de garantir POR CONSTRUÇÃO — e que não
    # precisam de chamada ao modelo para serem verificadas. Substituem, no
    # desenho novo, os critérios de cobertura que a validação de 20/09 mediu
    # contra o modelo: cobertura deixa de ser esperança e passa a ser invariante.
    for servico in ("Zalando", "Google Search", "Instagram"):
        dossie = varredura(servico, c)
        chao = piso(servico, c, dossie)
        endereçados = {(h["file"], h["termo"]) for hits in chao.values() for h in hits}
        esperados = {(d["file"], t) for d in dossie for t, n in d["counts"].items()
                     if n and t in TERMO_PARA_VARIAVEL}
        checar(f"{servico}: todo par documento–termo chega a alguma variável",
               esperados <= endereçados)
        com_flag = [h for hits in chao.values() for h in hits
                    if P.PATTERNS[h["termo"]]["flag"]]
        checar(f"{servico}: hit de termo com falso positivo carrega a nota",
               all(h["flag"] for h in com_flag))

    # Regressão do defeito achado em 20/09: no Zalando o modelo filtrou `ethics`
    # e `risk assessment`, e o avaliador nunca os viu. Agora eles chegam à V8.
    chao_z = piso("Zalando", c)
    termos_v8 = {h["termo"] for h in chao_z.get("V8", [])}
    checar("Zalando: ethics e risk assessment chegam ao piso da V8",
           {"ethics", "risk assessment"} <= termos_v8)
    checar("Zalando: os dois vêm com nota de falso positivo",
           all(h["flag"] for h in chao_z["V8"] if h["termo"] in {"ethics", "risk assessment"}))
    teto = {}
    for h in chao_z.get("V1", []):
        teto[(h["termo"], h["file"])] = teto.get((h["termo"], h["file"]), 0) + 1
    checar("teto por termo e documento é respeitado",
           all(v <= TETO_POR_TERMO_DOC for v in teto.values()))

    print("evidência congelada")
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory(prefix="cong-") as tmp:
        # Monta um site de mentira: md/ ao lado de sugestoes/, como no publicado.
        raiz = Path(tmp)
        shutil.copytree(Path(corpus_dir), raiz / "md")
        (raiz / "sugestoes").mkdir()
        doc = json.loads((raiz / "md" / "index.json").read_text())["services"][0]["docs"][0]
        (raiz / "sugestoes" / f"{B.slug('Pinterest')}.json").write_text(json.dumps({
            "formato": 1, "servico": "Pinterest", "modelo": "modelo-congelado",
            "gerado_em": "2026-09-24T00:00:00+00:00", "prompt": "abc123",
            "corpus_frozen_at": "2026-08-03",
            "citacoes": {"V1": [{"doc": 1, "verbatim": "x", "onde": "y", "por_que": "z",
                                 "file": doc["file"], "role": doc["role"]}]},
        }, ensure_ascii=False), encoding="utf-8")
        c2 = Corpus(raiz / "md")
        sug = congelada("Pinterest", c2)
        checar("congelada é lida de sugestoes/, irmã de md/", sug is not None)
        checar("vem com a marca de congelada", sug.origem["fonte"] == "congelada")
        checar("não traz sugestão de código", not sug.por_variavel["V1"]["sugestao"])
        checar("serviço sem arquivo devolve None", congelada("Temu", c2) is None)
        pa2 = Painel("Pinterest", corpus=c2,
                     estado=F.Estado(offline=True, cache=raiz / "cache.json"))
        pa2.carregar_sugestao()
        checar("painel prefere a congelada à chamada ao vivo",
               pa2.sugestao is not None and pa2.sugestao.modelo == "modelo-congelado")
        meta = pa2._assist_meta("V1")
        checar("proveniência registra a fonte e a data da evidência",
               meta["fonte"] == "congelada" and meta["evidencia_gerada_em"].startswith("2026-09"))
        checar("proveniência não inventa sugestão de código", "sugestao" not in meta)

    print("painel (modo texto, sem rede)")
    CFG.offline = True
    pa = Painel("Pinterest", corpus=c, estado=F.Estado(offline=True,
                                                       cache=Path(os.devnull + "x")), assistir=False)
    checar("painel constrói sem modelo", pa.fluxo.atual().vid == "V1")
    pa.sugestao = Sugestao("Pinterest", "modelo-de-teste", por_variavel={
        "V1": {"citacoes": [{"doc": 1, "verbatim": "x", "onde": "y", "por_que": "z"}],
               "sugestao": "2", "confianca": "alta"}})
    r = pa.revelar("V1")
    checar("revelar antes de responder é marcado", r["antes_de_responder"] is True)
    pa._respondeu.add("V2")
    checar("revelar depois de responder não é marcado",
           pa.revelar("V2")["antes_de_responder"] is False)
    meta = pa._assist_meta("V1")
    checar("proveniência guarda modelo e sugestão",
           meta["modelo"] == "modelo-de-teste" and meta["sugestao"] == "2")

    print("recibo de gravação")
    est = F.Estado(offline=True, cache=Path(os.devnull + "x"))
    pa3 = Painel("Pinterest", corpus=c, estado=est, assistir=False)
    checar("offline: o recibo diz onde o arquivo ficou",
           "offline" in pa3._recibo_inicial())
    est.offline, est.online = False, False
    checar("sem servidor: o recibo manda não começar",
           "ão comece a codificar" in pa3._recibo_inicial())
    checar("gravação que não chegou ao servidor é alarme vermelho",
           "NÃO chegou ao servidor" in pa3._recibo_gravacao("V1", False))
    est.online = True
    checar("servidor respondeu: o recibo confirma",
           "versionada" in pa3._recibo_inicial())
    checar("gravação que chegou vem com hora",
           "salvo no servidor" in pa3._recibo_gravacao("V1", True))
    # O defeito de origem não era a mensagem, era o retorno descartado: o
    # `_salvar` chamava `responder` e jogava fora o booleano que diz se a
    # resposta saiu da máquina. Este teste prende o cano, não o texto.
    pa3.fluxo.responder = lambda respostas, rede=True: "SENTINELA"
    checar("responder devolve ao chamador o resultado da gravação",
           pa3.responder("V1", {}) == "SENTINELA")

    print("botão de sugestão")
    # Com a congelada (o caso real do avaliador) não há sugestão nenhuma, então o
    # botão não deve ser oferecido. Com sugestão — desenvolvimento, ou uma
    # chamada ao vivo — deve.
    pa4 = Painel("Pinterest", corpus=c, estado=F.Estado(offline=True,
                                                        cache=Path(os.devnull + "x")),
                 assistir=False)
    pa4.sugestao = Sugestao("Pinterest", "congelado", por_variavel={
        "V1": {"citacoes": [{"doc": 1, "verbatim": "x", "onde": "y", "por_que": "z"}]}})
    checar("congelada não oferece sugestão de código para revelar",
           not pa4.revelar("V1")["sugestao"])
    pa4.sugestao.por_variavel["V1"]["sugestao"] = "2"
    checar("com sugestão presente, revelar devolve o valor",
           pa4.revelar("V1")["sugestao"] == "2")

    print("caminho de widgets (com um ipywidgets falso)")
    # O painel de widgets não tinha teste nenhum: o ipywidgets não está instalado
    # aqui, e `mostrar()` caía no modo texto. Foi assim que dois defeitos de tela
    # passaram — o botão que abria em branco e a exibição em dobro. Um stub
    # genérico basta para exercitar o caminho inteiro.
    import types

    class _FalsoW:
        """Widget de mentira: aceita qualquer construtor e serve de contexto."""

        def __init__(self, *a, **kw):
            # Guarda o HTML passado por posição também: é o que deixa conferir o
            # que a tela realmente diz, em vez de só conferir que não estourou.
            self.value = kw.get("value", a[0] if a and isinstance(a[0], str) else "")
            self.filhos = a[0] if a and isinstance(a[0], (list, tuple)) else ()
            self.kw = kw
            self._click = None

        def on_click(self, f):
            self._click = f

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

    class _FalsoModulo(types.ModuleType):
        def __getattr__(self, nome):
            return _FalsoW

    exibidos = []
    ipd = types.ModuleType("IPython.display")
    ipd.display = lambda *a, **k: exibidos.extend(a)
    ipd.HTML = lambda h="": h
    ipd.clear_output = lambda *a, **k: None
    guarda = {k: sys.modules.get(k) for k in ("ipywidgets", "IPython", "IPython.display")}
    sys.modules["ipywidgets"] = _FalsoModulo("ipywidgets")
    sys.modules["IPython"] = types.ModuleType("IPython")
    sys.modules["IPython.display"] = ipd
    try:
        pa5 = Painel("Pinterest", corpus=c,
                     estado=F.Estado(offline=True, cache=Path(os.devnull + "x")),
                     assistir=False)
        devolvido = pa5.mostrar()
        checar("o caminho de widgets monta sem estourar", exibidos != [])
        # O defeito de 27/set: `mostrar` exibia a caixa E a devolvia, e a célula do
        # Colab exibe o valor da última expressão — então o painel inteiro aparecia
        # duas vezes. Este é o teste que faltava.
        checar("mostrar() não devolve o widget que acabou de exibir", devolvido is None)
        checar("a caixa do painel é exibida uma vez só",
               sum(1 for x in exibidos if x is exibidos[0]) == 1)
        checar("o recibo entra na caixa exibida", pa5.recibo is not None)

        # O que a tela diz, não só que ela monta. Os quatro defeitos de
        # legibilidade relatados em 30/09 estão presos aqui.
        topo_html = exibidos[0].filhos[0].value
        variavel_html = "".join(x for x in exibidos if isinstance(x, str))
        checar("o cabeçalho não fala em sigla de vantagem",
               "vantagem" not in topo_html.lower())
        checar("o carimbo do painel diz a data, a VPN e o país",
               "VPN" in topo_html and "Itália" in topo_html
               and "03/08/2026" in topo_html)
        # O parágrafo longo é o mesmo nos 26 serviços, então ele aparece uma vez
        # na célula de instalação. Repetido em cada painel, viraria texto que se
        # aprende a pular — e é a instrução que não pode ser pulada.
        checar("o parágrafo longo não se repete em cada painel",
               "indistinguível" not in topo_html)
        checar("a legenda dos documentos também não se repete",
               "central de ajuda" not in topo_html)
        checar("mas a regra de onde ler continua no painel",
               "nunca da página ao vivo" in topo_html)
        # O que sai do painel é a EXPLICAÇÃO, não a coisa explicada: os rótulos e
        # os dois links continuam em cada linha de documento.
        checar("os rótulos e os dois links continuam em cada documento",
               "[vinculante]" in topo_html and "original ↗" in topo_html)
        checar("os papéis dos documentos vêm em português",
               "vinculante" in topo_html and "[binding]" not in topo_html)
        # O critério inteiro saiu da célula de trabalho e foi para o alto, como a
        # procedência e a legenda. O que fica aqui é a regra de uma linha e o
        # ponteiro — e nenhum `<details>`, que foi o defeito original.
        checar("a célula de trabalho não carrega o critério inteiro",
               "é isso que o codebook chama de" not in variavel_html
               and "Escada." not in variavel_html
               and "<details>" not in variavel_html)
        checar("o lembrete em linguagem direta fica logo abaixo do título",
               "Escolha o nível mais alto, de 0 a 3" in variavel_html)
        checar("a regra telegráfica antiga saiu da célula de trabalho",
               "Codifique o teto e onde ele vive" not in variavel_html)
        checar("a trilha mostra as dez variáveis e onde você está",
               all(f">{v.vid}" in variavel_html or f">{v.vid}✓" in variavel_html
                   for v in C.VARIAVEIS)
               and "variável 1 de 10 nesta célula" in variavel_html)
        checar("a trilha diz que a célula avança sozinha",
               "troca para a próxima quando você salva" in variavel_html)
        checar("e há ponteiro para onde o critério inteiro está",
               "Critério completo da V1 no alto do notebook" in variavel_html)
        checar("as duas listas têm título e explicação",
               "Busca por palavra-chave:" in variavel_html
               and "Acrescentado pelo modelo:" in variavel_html
               and "12 termos do protocolo" in variavel_html)
        checar("a tela não manda o codificador procurar o que é a §3",
               "§3" not in topo_html and "§3" not in variavel_html)
    finally:
        pass

    print("notas do serviço")
    # O stub de widgets guarda o callback do botão; clicar é chamar o callback.
    import types as _t
    exibidos_n = []
    ipd_n = _t.ModuleType("IPython.display")
    ipd_n.display = lambda *a, **k: exibidos_n.extend(a)
    ipd_n.HTML = lambda h="": h
    ipd_n.clear_output = lambda *a, **k: None
    sys.modules["ipywidgets"] = _FalsoModulo("ipywidgets")
    sys.modules["IPython"] = _t.ModuleType("IPython")
    sys.modules["IPython.display"] = ipd_n
    try:
        cache_n = Path(tempfile.mkdtemp()) / "notas.json"
        est_n = F.Estado(offline=True, cache=cache_n)
        pn = Painel("Pinterest", corpus=c, estado=est_n, assistir=False)
        pn.mostrar()
        filhos = exibidos_n[0].filhos
        bloco = filhos[2]
        caixa_txt, botao = bloco.filhos[1], bloco.filhos[2]
        checar("o painel tem o campo Notas, entre as variáveis e o recibo",
               len(filhos) == 4 and "Notas" in bloco.filhos[0].value)
        caixa_txt.value = "dúvida de regra na V3"
        botao._click(None)
        gravado = json.loads(cache_n.read_text())["records"]["Pinterest"]
        checar("salvar notas grava a chave `notes`, a mesma do instrumento em HTML",
               gravado.get("notes") == "dúvida de regra na V3")
        checar("e o recibo confirma a gravação das notas",
               "notas gravadas" in pn.recibo.value)
        checar("notas não abrem nem fecham nenhuma variável",
               pn.fluxo.progresso()[0] == 0)
    finally:
        for k, v in guarda.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    print("revisão de 02/10: o que a simulação completa achou")
    sys.modules["ipywidgets"] = _FalsoModulo("ipywidgets")
    sys.modules["IPython"] = _t.ModuleType("IPython")
    sys.modules["IPython.display"] = ipd_n
    try:
        def _arvore(x):
            yield x
            for f in getattr(x, "filhos", ()) or ():
                yield from _arvore(f)

        def _botao(prefixo):
            bs = [w for x in exibidos_n if isinstance(x, _FalsoW) for w in _arvore(x)
                  if isinstance(w, _FalsoW) and str(w.kw.get("description", "")).startswith(prefixo)]
            return bs[-1] if bs else None

        def _campos(painel):
            caixa = [x for x in exibidos_n if isinstance(x, _FalsoW) and x.filhos and all(
                isinstance(h, _FalsoW) and len(h.filhos) == 2 for h in x.filhos)][-1]
            por_rotulo = {c.rotulo: c.chave for c in painel.fluxo.atual().campos}
            return {por_rotulo[h.filhos[0].value]: h.filhos[1] for h in caixa.filhos}

        def _responder_tudo(campos):
            for chave, w in campos.items():
                c = next(c for v in C.VARIAVEIS for c in v.campos if c.chave == chave)
                if c.tipo == "select":
                    w.value = [o for o in c.opcoes if o][0]
                elif c.tipo == "checks":
                    w.value = tuple(o for o in c.opcoes if o)[:1]
                elif chave != "keyword_log":
                    w.value = "x"

        exibidos_n.clear()
        cache_r = Path(tempfile.mkdtemp()) / "rev.json"
        pr = Painel("Instagram", corpus=c, estado=F.Estado(offline=True, cache=cache_r),
                    assistir=False)
        pr.sugestao = Sugestao("Instagram", "congelado", por_variavel={"V1": {"citacoes": [
            {"doc": 1, "verbatim": "trecho", "onde": "Seção 2",
             "por_que": "patamar mínimo da escada (nível 1)"}]}})
        pr.mostrar()
        tela_txt = "".join(x for x in exibidos_n if isinstance(x, str)) + \
            "".join(w.value for x in exibidos_n if isinstance(x, _FalsoW)
                    for w in _arvore(x) if isinstance(w.value, str))
        checar("a justificativa do modelo não aparece na tela (ela dizia o código)",
               "patamar mínimo" not in tela_txt and "nível 1" not in tela_txt)
        checar("mas a frase e a localização aparecem", "trecho" in tela_txt and "Seção 2" in tela_txt)
        checar("o cabeçalho não afirma quantos documentos são vinculantes",
               "vinculantes)" not in tela_txt)
        checar("na V1 não há botão de voltar", _botao("voltar") is None)
        _responder_tudo(_campos(pr))
        _botao("salvar V1")._click(None)
        checar("na V2 aparece o botão de voltar", _botao("voltar") is not None)
        _campos(pr)["v2_evidence"].value = "digitado e não salvo"
        _botao("voltar")._click(None)
        checar("voltar leva à V1", pr.fluxo.atual().vid == "V1")
        checar("e não perde o que estava digitado na V2",
               json.loads(cache_r.read_text())["records"]["Instagram"].get("v2_evidence")
               == "digitado e não salvo")
        for _ in range(10):
            vid = pr.fluxo.atual().vid
            _responder_tudo(_campos(pr))
            _botao(f"salvar {vid}")._click(None)
        fim = [x for x in exibidos_n if isinstance(x, str) and "concluído" in x][-1:]
        checar("a conclusão chega, sem jargão de protocolo",
               bool(fim) and "§3" not in fim[0] and "portão" not in fim[0])

        # Duas janelas no mesmo serviço, com um servidor de mentira entre elas.
        servidor = {"records": {}}

        def _estado_online():
            e = F.Estado(offline=True, cache=Path(tempfile.mkdtemp()) / "o.json")
            e.offline = False
            e._get = lambda: json.loads(json.dumps(servidor["records"]))

            def _put(regs):
                servidor["records"] = json.loads(json.dumps(regs))
                return True
            e._put = _put
            e.records = e._get()
            return e
        janela_a = Painel("Temu", corpus=c, estado=_estado_online(), assistir=False)
        janela_b = Painel("Temu", corpus=c, estado=_estado_online(), assistir=False)
        janela_a.recibo = _FalsoW("")
        respostas_v1 = {"v1_code": "3", "v1_register": "both", "v1_evidence": "b"}
        janela_b.responder("V1", respostas_v1)
        janela_b._gravou()
        checar("a janela que ficou para trás não grava por cima",
               janela_a._pode_gravar() is False and "nada foi gravado" in janela_a.recibo.value)
        checar("a que gravou continua podendo gravar", janela_b._pode_gravar() is True)
        checar("rodar a célula de novo resolve",
               Painel("Temu", corpus=c, estado=_estado_online(),
                      assistir=False)._pode_gravar() is True)
    finally:
        for k, v in guarda.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    print("procedência: uma vez longa, sempre curta")
    checar("o parágrafo longo existe e explica as duas razões",
           "indistinguível de mudança no documento" in procedencia(c))
    # 130 não é número escolhido a dedo: é o que cabe na caixa de 780px do
    # cabeçalho em monoespaçada de 12px. O que interessa é ser UMA linha.
    checar("a linha curta é uma linha e cabe na caixa do painel",
           "\n" not in procedencia_curta(c) and len(procedencia_curta(c)) <= 130)
    checar("a legenda explica os dois links e os três papéis",
           all(t in LEGENDA_DOCUMENTOS for t in
               ("texto congelado", "original ↗", "vinculante", "não vinculante",
                "sem classificação")))
    checar("as duas dizem a mesma data e o mesmo país",
           "03/08/2026" in procedencia(c) and "03/08/2026" in procedencia_curta(c)
           and "Itália" in procedencia_curta(c))

    print("codebook em um bloco")
    cb = codebook_html()
    checar("as dez variáveis entram", all(f"[{v.vid}]" in cb for v in C.VARIAVEIS))
    checar("cada variável abre pela pergunta que ela responde",
           all(C.pergunta(v.vid) in cb for v in C.VARIAVEIS))
    checar("as cinco regras gerais vêm antes das variáveis",
           cb.index("Cinco regras") < cb.index("[V1]"))
    # O texto oficial aparece uma vez, no fim, inteiro. Variável por variável, ao
    # lado do guia, punha três versões da mesma regra na tela.
    checar("o texto oficial aparece uma vez, depois de todo o guia",
           cb.count("Texto oficial do codebook") == 1
           and cb.index("Texto oficial do codebook") > cb.index(C.pergunta("KW")))
    checar("os nove critérios congelados estão no texto oficial, intactos",
           all(C.criterio(v.crit_key) in cb for v in C.VARIAVEIS if v.crit_key != "kw"))
    guia = cb[:cb.index("Texto oficial do codebook")]
    checar("o guia não tem travessão (o texto oficial pode ter: é congelado)",
           "—" not in guia)
    checar("o guia não nomeia nenhum dos 26 serviços",
           not [sv for sv in C.SERVICOS if f">{sv}<" in guia or f" {sv} " in guia
                or f" {sv}." in guia or f" {sv}," in guia])
    # As âncoras nomeiam serviços; num bloco único não há serviço em tela contra o
    # qual suprimir, então nenhuma pode entrar — senão a resposta de um serviço
    # fica no campo de visão de quem codifica outro.
    todas = [h for v in C.VARIAVEIS if v.crit_key
             for h in C.ancoras(v.crit_key, "serviço-que-não-existe")[0]]
    checar(f"nenhuma das {len(todas)} âncoras do piloto entra no bloco",
           not any(a in cb for a in todas))

    print("link do documento (corpus remoto, via file://)")
    # `file://` faz o Corpus tomar o caminho remoto sem depender do site no ar —
    # é a única forma de testar o link, que é o defeito relatado: ele levava à
    # página original em vez do documento congelado.
    c_remoto = Corpus(Path(corpus_dir).resolve().as_uri())
    doc = c_remoto.docs("Wikipedia")[0]
    alvo = c_remoto.url_do_congelado(doc)
    checar("corpus remoto devolve endereço do documento congelado",
           bool(alvo) and alvo.endswith(doc["file"]))
    checar("o endereço é do congelado, não da página original",
           alvo != doc["url"] and doc["url"] not in alvo)
    checar("corpus em disco não inventa link", c.url_do_congelado(doc) is None)
    sys.modules["ipywidgets"] = _FalsoModulo("ipywidgets")
    sys.modules["IPython"] = types.ModuleType("IPython")
    sys.modules["IPython.display"] = ipd
    try:
        exibidos.clear()
        Painel("Wikipedia", corpus=c_remoto,
               estado=F.Estado(offline=True, cache=Path(os.devnull + "x")),
               assistir=False).mostrar()
        html = exibidos[0].filhos[0].value
        checar("o nome do arquivo na tela aponta para o congelado", alvo in html)
        checar("a página original continua na tela, rotulada",
               doc["url"] in html and "original ↗" in html)
    finally:
        for k, v in guarda.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    print(f"\n{'FALHOU: ' + str(len(falhas)) if falhas else 'tudo ok'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    print(__doc__)
