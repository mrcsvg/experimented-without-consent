#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""O codebook v2 legível de Python — lido do instrumento, não recopiado.

    import codebook as C
    C.VARIAVEIS[0].titulo          # 'Reconhecimento de experimentação'
    C.VARIAVEIS[0].campos[0].opcoes
    C.criterio("v1")               # o critério completo, em HTML
    C.ancoras("v1", "Google Play") # âncoras do piloto, já suprimidas

    python3 analysis/codebook.py --check   # valida a extração

POR QUE LER O index.html EM VEZ DE TRANSCREVER DE NOVO. O canônico é
`protocol/codebook-v2.md`, congelado em 04/jul. As constantes do instrumento já
são uma transcrição dele, feita sob regra de fidelidade declarada e auditada.
Uma segunda transcrição, para Python, seria uma segunda chance de divergir — e
a divergência apareceria como discordância entre codificadores, indistinguível
de discordância real. Lendo do instrumento existe uma transcrição só.

O custo é acoplamento à forma do `index.html`. Por isso `--check`: ele afirma o
que a extração tem que encontrar, e quebra ruidosamente se alguém reformatar o
arquivo. Falhar na hora é o comportamento desejado — o modo de falha ruim é
devolver um codebook pela metade e ninguém notar.

O instrumento é single-file por desenho (sem build, sem dependência), então as
constantes vivem em JS. Isto aqui lê JS o suficiente para elas: objetos e
arrays literais, string em aspas simples, duplas ou crase, chave sem aspas, e
identificador que referencia outra constante. Nada além disso — não é um
interpretador, e não deve virar um.

Sem dependências externas: só a biblioteca padrão.
"""
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent / "index.html"

# Constantes lidas do instrumento, na ordem em que uma pode referenciar a anterior.
CONSTANTES = ["DATA", "KWTERMS", "FRAMING", "BASIS", "WHERE", "REG", "YN", "V5",
              "VALHELP", "FIELDHELP", "META_SVC", "GOOGLE_SVC", "ANCHORS", "CRIT",
              "GLOSA"]


class ErroDeExtracao(RuntimeError):
    """O index.html não tem a forma que este módulo espera."""


# ---------------------------------------------------------------- leitor de JS

class _Leitor:
    """Lê literais JS. Identificador não-reservado resolve na tabela de símbolos."""

    def __init__(self, texto, simbolos):
        self.s, self.i, self.simbolos = texto, 0, simbolos

    def _espaco(self):
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif self.s.startswith("/*", self.i):
                fim = self.s.find("*/", self.i)
                self.i = len(self.s) if fim < 0 else fim + 2
            elif self.s.startswith("//", self.i):
                fim = self.s.find("\n", self.i)
                self.i = len(self.s) if fim < 0 else fim + 1
            else:
                return

    def _string(self):
        aspas = self.s[self.i]
        self.i += 1
        out = []
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == "\\":
                seg = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\",
                       '"': '"', "'": "'", "`": "`"}
                self.i += 1
                out.append(seg.get(self.s[self.i], self.s[self.i]))
            elif c == aspas:
                self.i += 1
                return "".join(out)
            else:
                out.append(c)
            self.i += 1
        raise ErroDeExtracao("string sem fechamento")

    def valor(self):
        self._espaco()
        if self.i >= len(self.s):
            raise ErroDeExtracao("fim inesperado")
        c = self.s[self.i]
        if c in "\"'`":
            return self._string()
        if c == "[":
            self.i += 1
            itens = []
            while True:
                self._espaco()
                if self.s[self.i] == "]":
                    self.i += 1
                    return itens
                itens.append(self.valor())
                self._espaco()
                if self.s[self.i] == ",":
                    self.i += 1
        if c == "{":
            self.i += 1
            obj = {}
            while True:
                self._espaco()
                if self.s[self.i] == "}":
                    self.i += 1
                    return obj
                chave = self._string() if self.s[self.i] in "\"'" else self._identificador()
                self._espaco()
                if self.s[self.i] != ":":
                    raise ErroDeExtracao(f"esperava ':' depois de {chave!r}")
                self.i += 1
                obj[chave] = self.valor()
                self._espaco()
                if self.s[self.i] == ",":
                    self.i += 1
        m = re.compile(r"-?\d+(\.\d+)?").match(self.s, self.i)
        if m:
            self.i = m.end()
            return float(m.group()) if "." in m.group() else int(m.group())
        nome = self._identificador()
        if nome in ("true", "false"):
            return nome == "true"
        if nome == "null":
            return None
        if nome not in self.simbolos:
            raise ErroDeExtracao(f"identificador desconhecido: {nome!r}")
        return self.simbolos[nome]

    def _identificador(self):
        m = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*").match(self.s, self.i)
        if not m:
            raise ErroDeExtracao(f"esperava identificador em {self.s[self.i:self.i+30]!r}")
        self.i = m.end()
        return m.group()


def _ler_const(fonte, nome, simbolos):
    m = re.search(r"^const\s+%s\s*=\s*" % re.escape(nome), fonte, re.M)
    if not m:
        raise ErroDeExtracao(f"const {nome} não encontrada em {HTML.name}")
    return _Leitor(fonte, simbolos).__class__(fonte[m.end():], simbolos).valor()


# ------------------------------------------------------------------- variáveis

@dataclass
class Campo:
    chave: str
    rotulo: str
    tipo: str                      # select · checks · text · line
    opcoes: list = field(default_factory=list)
    placeholder: str = ""


@dataclass
class Variavel:
    vid: str                       # V1…V9, KW
    titulo: str
    regra: str                     # o parágrafo .rule, em HTML
    campos: list = field(default_factory=list)

    @property
    def crit_key(self):
        return self.vid.lower()


_CARD = re.compile(r'<div class="vcard"><h3><span class="vid">([^<]+)</span>\s*([^<]+)</h3>(.*?)'
                   r'(?=\n\s*</div>\s*\n\s*<div class="vcard"|\n\s*</div>\s*\n\s*<div class="done-row")',
                   re.S)
_REGRA = re.compile(r'<p class="rule">(.*?)</p>', re.S)
_CHAMADA = re.compile(r'\bf(Select|Checks|Text|Line)\(rec,\s*', re.S)


def _args(fonte, pos, simbolos):
    """Lê os argumentos de uma chamada f*(rec, …) até o parêntese que fecha."""
    leitor = _Leitor(fonte, simbolos)
    leitor.i = pos
    out = []
    while True:
        leitor._espaco()
        if leitor.s[leitor.i] == ")":
            return out, leitor.i + 1
        out.append(leitor.valor())
        leitor._espaco()
        if leitor.s[leitor.i] == ",":
            leitor.i += 1


def _ler_variaveis(fonte, simbolos):
    vars_ = []
    for vid, titulo, corpo in _CARD.findall(fonte):
        regra_m = _REGRA.search(corpo)
        v = Variavel(vid.strip(), titulo.strip(),
                     " ".join(regra_m.group(1).split()) if regra_m else "")
        for m in _CHAMADA.finditer(corpo):
            tipo = m.group(1).lower()
            args, _ = _args(corpo, m.end(), simbolos)
            if len(args) < 2:
                raise ErroDeExtracao(f"chamada f{tipo} sem chave/rótulo em {vid}")
            chave, rotulo = args[0], args[1]
            opcoes, ph = [], ""
            if tipo in ("select", "checks"):
                opcoes = args[2] if len(args) > 2 and isinstance(args[2], list) else []
            elif len(args) > 2 and isinstance(args[2], str):
                ph = args[2]
            v.campos.append(Campo(chave, rotulo, tipo, opcoes, ph))
        vars_.append(v)
    return vars_


# --------------------------------------------------------------------- público

_fonte = HTML.read_text(encoding="utf-8")
_simb = {}
for _nome in CONSTANTES:
    _simb[_nome] = _ler_const(_fonte, _nome, _simb)

DATA = _simb["DATA"]
KWTERMS = _simb["KWTERMS"]
VALHELP = _simb["VALHELP"]
FIELDHELP = _simb["FIELDHELP"]
ANCHORS = _simb["ANCHORS"]
CRIT = _simb["CRIT"]
GLOSA = _simb["GLOSA"]
OPCOES = {n: _simb[n] for n in ("FRAMING", "BASIS", "WHERE", "REG", "YN", "V5")}
SERVICOS = DATA["order"]
VARIAVEIS = _ler_variaveis(_fonte, _simb)


def criterio(v):
    """O critério completo da variável (§2 do codebook), em HTML.

    É transcrição fiel do `protocol/codebook-v2.md`, congelado em 04/jul/2026 e
    usado para codificar a passada 1. Não reescrever: duas passadas contra
    instrumentos diferentes produzem desacordo que não é desacordo. Para explicar
    melhor, use a `glosa_criterio` — ela fica ao lado, marcada como explicação.
    """
    c = CRIT.get(v.lower())
    return c["html"] if c else ""


# sha256 (12 hex) do HTML de cada critério, como está no codebook congelado em
# 04/jul/2026. Não é integridade contra adversário: é trava contra a tentação de
# "melhorar a redação" do instrumento depois que a passada 1 já foi codificada com
# ele. Se um destes mudar, o `--check` reprova e diz o que fazer.
CRIT_CONGELADO = {
    "v1": "49dc0105e1de", "v2": "bac8d56c51f6", "v3": "c8818742ca4b",
    "v4": "990413ff6366", "v5": "b7b90f255219", "v6": "8b0b6ac097ca",
    "v7": "27eaf0796fa9", "v8": "a65d7654af6a", "v9": "147540427538",
}


def glosa_criterio(v):
    """O guia da variável em linguagem direta, em HTML. Explica, não substitui."""
    return (GLOSA.get(v.lower()) or {}).get("html", "")


def pergunta(v):
    """A pergunta que a variável responde, numa frase."""
    return (GLOSA.get(v.lower()) or {}).get("pergunta", "")


def lembrete(v):
    """A linha que vai em cada célula de trabalho."""
    return (GLOSA.get(v.lower()) or {}).get("lembrete", "")


def glosa(chave, valor):
    """Definição do valor, com procedência. (texto, procedência) ou None."""
    e = VALHELP.get(f"{chave}:{valor}")
    return (e[0], e[1]) if e else None


def ancoras(v, servico):
    """Âncoras do piloto para a variável, JÁ suprimidas para o serviço em tela.

    Devolve (mostrar, suprimidas). A supressão é a mesma regra do instrumento: o
    .md é público e o avaliador alcança as âncoras de qualquer jeito; o que não
    pode é a ferramenta exibir a resposta no momento e no lugar da decisão. Por
    isso `suprimidas` volta preenchida — a omissão é anunciada, nunca silenciosa.
    """
    mostrar, ocultas = [], []
    for a in ANCHORS.get(v.lower(), []):
        (ocultas if servico in a["svc"] else mostrar).append(a["html"])
    return mostrar, ocultas


CAMPOS_CENTRAIS = [c.chave for v in VARIAVEIS for c in v.campos
                   if not c.chave.endswith(("_evidence", "_note", "_notes"))]


def _check():
    erros, avisos = [], []

    def exigir(cond, msg):
        if not cond:
            erros.append(msg)

    exigir(len(SERVICOS) == 26, f"esperava 26 serviços, achei {len(SERVICOS)}")
    exigir(len(DATA["services"]) == 26,
           f"esperava 26 manifestos, achei {len(DATA['services'])}")
    exigir(len(KWTERMS) == 12, f"esperava 12 termos §3, achei {len(KWTERMS)}")

    vids = [v.vid for v in VARIAVEIS]
    esperado = ["V%d" % n for n in range(1, 10)] + ["KW"]
    exigir(vids == esperado, f"variáveis fora de ordem ou faltando: {vids}")
    exigir(all(v.regra for v in VARIAVEIS), "variável sem parágrafo de regra")
    exigir(all(v.campos for v in VARIAVEIS), "variável sem nenhum campo")
    for n in range(1, 10):
        exigir(criterio(f"v{n}"), f"critério completo ausente para v{n}")
        for parte, fn in (("guia", glosa_criterio), ("pergunta", pergunta),
                          ("lembrete", lembrete)):
            exigir(fn(f"v{n}"), f"v{n}: {parte} em linguagem direta ausente na GLOSA")
        import hashlib
        agora = hashlib.sha256(criterio(f"v{n}").encode("utf-8")).hexdigest()[:12]
        exigir(agora == CRIT_CONGELADO[f"v{n}"],
               f"v{n}: o texto do critério mudou ({agora}). Ele é transcrição do "
               "codebook congelado em 04/jul, usado na passada 1 — reescrevê-lo faz "
               "as duas passadas usarem instrumentos diferentes. Para explicar "
               "melhor, mexa na GLOSA. Se a mudança é deliberada e o codebook "
               "também mudou, atualize CRIT_CONGELADO no mesmo commit.")

    # Todo campo select/checks tem que ter chegado com opções resolvidas.
    for v in VARIAVEIS:
        for c in v.campos:
            if c.tipo in ("select", "checks"):
                exigir(c.opcoes, f"{c.chave}: opções não resolveram")

    # As chaves que o compute-agreement.py parea têm que existir no formulário.
    todas = {c.chave for v in VARIAVEIS for c in v.campos}
    ag = Path(__file__).resolve().parent / "compute-agreement.py"
    if ag.exists():
        fonte = ag.read_text(encoding="utf-8")
        for lista in ("CAT_VARS", "MULTI_VARS"):
            m = re.search(lista + r"\s*=\s*\[(.*?)\]", fonte, re.S)
            if not m:
                avisos.append(f"{lista} não encontrada em compute-agreement.py")
                continue
            for chave in re.findall(r'"([^"]+)"', m.group(1)):
                exigir(chave in todas,
                       f"{chave} é pareada pelo compute-agreement.py mas não existe no formulário")

    # VALHELP só pode glosar valores que o formulário oferece.
    ofertados = {(c.chave, o) for v in VARIAVEIS for c in v.campos for o in c.opcoes}
    for k in VALHELP:
        chave, _, valor = k.rpartition(":")
        if chave and (chave, valor) not in ofertados and chave in {c for c, _ in ofertados}:
            avisos.append(f"VALHELP glosa {k!r}, que não é opção oferecida")

    print(f"{HTML.name}: {len(SERVICOS)} serviços · {len(VARIAVEIS)} variáveis · "
          f"{len(todas)} campos · {len(VALHELP)} glosas · {len(KWTERMS)} termos §3")
    for v in VARIAVEIS:
        campos = " ".join(f"{c.chave}[{c.tipo}{'·%d' % len(c.opcoes) if c.opcoes else ''}]"
                          for c in v.campos)
        print(f"  {v.vid:3} {v.titulo[:34]:36} {campos}")
    for a in avisos:
        print(f"  aviso: {a}", file=sys.stderr)
    if erros:
        print("\nEXTRAÇÃO INVÁLIDA:", file=sys.stderr)
        for e in erros:
            print(f"  {e}", file=sys.stderr)
        return 1
    print("\nextração válida")
    return 0


if __name__ == "__main__":
    sys.exit(_check() if "--check" in sys.argv[1:] else _check())
