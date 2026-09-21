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
código é do avaliador. A sugestão do modelo existe, mas fica atrás de um botão,
e o registro guarda se ela foi revelada antes ou depois da resposta. Assim o
κ pode ser reportado com a ressalva certa, e dá para medir quantas vezes o
avaliador simplesmente carimbou.

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

import json
import os
import re
import sys
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


def corpus_carregado() -> "Corpus":
    if CFG._corpus_obj is None:
        CFG._corpus_obj = Corpus(CFG.corpus)
    return CFG._corpus_obj


# --------------------------------------------------------------------- corpus

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


def _cliente():
    """Cliente Anthropic com a chave vinda do cofre do Colab, não do notebook.

    Ordem: variável de ambiente, depois os Secrets do Colab (o cadeado na barra
    lateral, com "Notebook access" ligado). A chave nunca entra numa célula —
    este repositório é público, e output de notebook já viajou para dentro de
    clone antes (ver `nb-clean.py`).
    """
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("falta o SDK: pip install -q anthropic")
    chave = os.environ.get("ANTHROPIC_API_KEY")
    if not chave:
        try:
            from google.colab import userdata
            chave = userdata.get("ANTHROPIC_API_KEY")
        except Exception:
            chave = None
    if not chave:
        raise RuntimeError(
            "sem ANTHROPIC_API_KEY. No Colab: cadeado da barra lateral → "
            "novo secret ANTHROPIC_API_KEY → ligar 'Notebook access'.")
    return anthropic.Anthropic(api_key=chave, timeout=600.0)


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
        max_tokens=16000,
        system=SISTEMA,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": ESQUEMA}},
        messages=[{"role": "user", "content": _prompt(servico, docs, textos)}],
    ) as fluxo:
        resposta = fluxo.get_final_message()

    if getattr(resposta, "stop_reason", None) == "refusal":
        raise RuntimeError(f"o modelo recusou ({resposta.stop_details}) — recorte o pedido")

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
        self.estado = estado if estado is not None else F.Estado(offline=CFG.offline)
        # O `Fluxo` resolve o serviço contra o dossiê na construção; passamos o
        # dossiê já chaveado pelo nome canônico, que é o do roster.
        self.fluxo = F.Fluxo(servico, self.estado, {servico: self.dossie_local})
        self.sugestao = sugestao
        self.assistir = assistir
        self.revelou: dict[str, bool] = {}
        self._respondeu: set[str] = set()

    # ------------------------------------------------------------ assistência
    def carregar_sugestao(self):
        if self.sugestao is None and self.assistir and not CFG.offline:
            self.sugestao = sugerir(self.servico, self.corpus)
        return self.sugestao

    def evidencia_de(self, vid: str) -> list[dict]:
        s = self.sugestao.por_variavel.get(vid, {}) if self.sugestao else {}
        return s.get("citacoes", [])

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
        return {"modelo": self.sugestao.modelo if self.sugestao else None,
                "revelada": bool(self.revelou.get(vid)),
                "antes_de_responder": bool(self.revelou.get(vid)) and vid not in self._respondeu,
                "sugestao": (self.sugestao.por_variavel.get(vid, {}).get("sugestao")
                             if self.sugestao else None)}

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
        vinc = sum(1 for d in self.docs if d["role"] == "binding")
        perdidos = self.corpus.excluidos(self.servico)
        feitas, total = self.fluxo.progresso()
        linhas = [f"{self.servico} · {len(self.docs)} documentos ({vinc} vinculantes) · "
                  f"congelado {self.corpus.index.get('frozen_at', '?')[:10]} "
                  f"vantagem {self.corpus.index.get('vantage')} · {feitas}/{total} variáveis"]
        if perdidos:
            linhas.append(f"⚠ {len(perdidos)} documento(s) que o congelamento não pegou — "
                          "isso é lacuna de corpus, não ausência de divulgação")
        if self.corpus.quarentena:
            linhas.append(f"⚠ {len(self.corpus.quarentena)} em quarentena (hash)")
        return "\n".join(linhas)

    def texto_dos_documentos(self) -> str:
        linhas = []
        for doc, d in zip(self.docs, self.dossie_local):
            acesos = [f"{t}:{n}" for t, n in d["counts"].items() if n]
            linhas.append(f"  {doc['n']:02d} [{doc['role']:<11}] {Path(doc['file']).name} "
                          f"· {doc['chars']//1000}k · " + (", ".join(acesos) or "nenhum termo"))
        return "\n".join(linhas)

    def imprimir(self, vid: str | None = None):
        """Modo texto — é o que roda fora do Colab (e no self-test)."""
        print(self.cabecalho())
        print(self.texto_dos_documentos())
        passo = self.fluxo.atual()
        vid = vid or passo.vid
        print(f"\n[{passo.vid}] {passo.titulo}\n    {re.sub('<[^>]+>', '', passo.regra)}")
        cits = self.evidencia_de(vid)
        print(f"    evidência localizada: {len(cits)}")
        for c in cits[:4]:
            print(f"      “{c['verbatim'][:150]}” — doc {c['doc']} · {c['onde']}")
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

        docs_html = "".join(
            f"<div style='padding:2px 0'><b>{d['n']:02d}</b> "
            f"<span style='color:{'#0a7' if d['role'] == 'binding' else '#888'}'>"
            f"[{d['role']}]</span> "
            f"<a href='{_esc(d['url'])}' target='_blank'>{_esc(Path(d['file']).name)}</a> "
            f"<span style='color:#888'>{d['chars'] // 1000}k · "
            f"{_esc(', '.join(f'{t}:{n}' for t, n in v['counts'].items() if n) or 'nenhum termo')}"
            f"</span></div>"
            for d, v in zip(self.docs, self.dossie_local))

        topo = W.HTML(f"<h3 style='margin:0'>{_esc(self.cabecalho())}</h3>"
                      f"<div style='font:12px/1.5 ui-monospace,monospace'>{docs_html}</div>")
        area = W.Output()
        caixa = W.VBox([topo, area])
        display(caixa)
        self._render_variavel(area)
        return caixa

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
        ev = "".join(
            f"<div style='margin:6px 0;padding:6px 10px;border-left:3px solid #0a7'>"
            f"“{_esc(c['verbatim'][:400])}”<br>"
            f"<span style='color:#888;font-size:12px'>doc {c['doc']} · {_esc(c['onde'])} "
            f"· {_esc(c.get('por_que', ''))[:160]}</span></div>"
            for c in cits) or "<i style='color:#888'>o modelo não localizou passagem para esta variável</i>"

        btn_sug = W.Button(description="ver sugestão do modelo", icon="eye")
        saida_sug = W.Output()

        def _ver(_):
            r = self.revelar(vid)
            with saida_sug:
                clear_output()
                aviso = ("<b style='color:#b00'>revelada ANTES da resposta</b> — "
                         "isso fica registrado") if r["antes_de_responder"] else \
                        "<span style='color:#888'>revelada depois da resposta</span>"
                display(HTML(f"sugestão: <b>{_esc(r['sugestao'])}</b> "
                             f"(confiança {_esc(r['confianca'])})<br>{aviso}"))
        btn_sug.on_click(_ver)

        btn_ok = W.Button(description=f"salvar {vid} e avançar", button_style="success")
        saida_ok = W.Output()

        def _salvar(_):
            respostas = {}
            for chave, w in campos.items():
                valor = w.value
                respostas[chave] = list(valor) if isinstance(valor, tuple) else valor
            self.responder(vid, respostas)
            with saida_ok:
                clear_output()
                pend = self.fluxo.faltando()
                if pend:
                    display(HTML("<b style='color:#b00'>portão fechado</b> — falta " +
                                 _esc(", ".join(f"{k} ({p})" for k, p in pend))))
                    return
            if self.fluxo.avancar():
                self._render_variavel(area)
            else:
                with area:
                    clear_output()
                    display(HTML(f"<b>{_esc(self.servico)} concluído.</b> "
                                 "As nove variáveis e o log do §3 fecharam o portão."))
        btn_ok.on_click(_salvar)

        with area:
            clear_output()
            display(HTML(
                f"<h4 style='margin:12px 0 2px'>[{vid}] {_esc(passo.titulo)}</h4>"
                f"<div style='color:#555'>{passo.regra}</div>"
                f"<details><summary style='cursor:pointer;color:#06c'>critério completo</summary>"
                f"{passo.criterio}</details>"
                f"<div style='margin-top:8px'><b>evidência localizada ({len(cits)})</b>{ev}</div>"))
            display(W.VBox([W.HBox([W.Label(c.rotulo, layout=W.Layout(width="260px")), w])
                            for c, w in zip(passo.campos, campos.values())]))
            display(W.HBox([btn_ok, btn_sug]))
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

    print(f"\n{'FALHOU: ' + str(len(falhas)) if falhas else 'tudo ok'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    print(__doc__)
