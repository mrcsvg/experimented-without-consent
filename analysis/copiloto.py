#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""O copiloto do 2º codificador: uma sugestão de código por variável, congelada.

    python3 analysis/copiloto.py --corpus <md> --estimar                 # tokens, sem gastar
    python3 analysis/copiloto.py --corpus <md> --out <corpus>/assistente/copiloto --so Wikipedia
    python3 analysis/copiloto.py --corpus <md> --out <corpus>/assistente/copiloto
    python3 analysis/copiloto.py --corpus <md> --out <corpus>/assistente/copiloto --check
    python3 analysis/copiloto.py --simular                               # self-test, sem rede

A chave da API vem de EWC_ANTHROPIC_KEY, lida inline no comando:
    EWC_ANTHROPIC_KEY="$(security find-generic-password -s ewc-anthropic-key -w)" python3 ...

O QUE É. A página do assistente tem, em cada variável, o botão "ver sugestão do
copiloto". O que aparece ali sai deste script, rodado uma vez antes da
codificação. Decisão de 03/10/2026: a IA é um acelerador, a responsabilidade é
do codificador, e a transparência se garante publicando o prompt e as saídas.

O QUE O MODELO RECEBE, por serviço: o codebook (critério congelado e guia de
cada variável, com as opções de cada campo), as citações verbatim já
verificadas (`sugestoes/<slug>.json`), a contagem de palavras-chave por
documento e a lista de documentos (número, título, URL, tamanho).

O QUE ELE NÃO RECEBE: códigos ou anotações da passada 1; a etiqueta `role`
(vinculante) dos documentos; respostas do 2º codificador. O self-test afirma
isso sobre a mensagem montada.

O QUE ELE DEVOLVE, por variável V1..V9: um valor por campo (dentro das opções
do codebook, garantido pelo esquema de saída e conferido de novo aqui), uma
razão de até duas frases, a confiança e os ids das citações usadas. Os campos
de texto (evidência e nota) não são pedidos: a página os preenche com as
citações indicadas.

Dependências: `anthropic` (só para gerar). O self-test roda sem ele.
"""
from __future__ import annotations

import argparse
import hashlib
import html as html_mod
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import codebook as C  # noqa: E402
import revisao as R  # noqa: E402


def _modulo(nome_arquivo: str, apelido: str):
    spec = importlib.util.spec_from_file_location(apelido, AQUI / nome_arquivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


EC = _modulo("exportar-codebook.py", "exportar_codebook")
EP = _modulo("exportar-piso.py", "exportar_piso")

FORMATO = 1
MODELO_PADRAO = "claude-opus-5-5"
MAX_TOKENS = 12000
CONFIANCAS = ("alta", "média", "baixa")
RAZAO_MAX = 400
LINHA_MAX = 200
VARIAVEIS_DO_COPILOTO = ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9")

SISTEMA = """\
Você é o copiloto de um codificador humano num estudo documental. O estudo
classifica o que plataformas online declaram sobre experimentação com os
próprios usuários, e em que tipo de documento declaram.

Para um serviço de cada vez, você recebe: o codebook (o critério congelado e o
guia de cada variável), citações copiadas palavra por palavra dos documentos
congelados do serviço, cada uma com um identificador, e a contagem de 12
palavras-chave por documento. Você propõe um valor para cada campo de cada
variável, com uma razão curta.

Regras:
1. Só o material fornecido conta. Não use conhecimento externo sobre a plataforma.
2. Cada razão cita as citações usadas pelos identificadores (por exemplo V1-2).
   Se nenhuma citação sustenta outra resposta, proponha a resposta de ausência
   prevista no codebook (0, No, none, not stated) e escreva na razão: "nenhuma
   citação sustenta outra resposta".
3. Os valores vêm da lista de opções de cada campo, escritos exatamente como na
   lista. Campo de múltipla escolha recebe uma lista. Campo de linha recebe
   texto curto, ou vazio.
4. Para decidir se um documento é vinculante, use a função do documento, pela
   URL e pelo título: política de privacidade, termos de uso e tabela de bases
   legais obrigam a plataforma; blog, central de ajuda e material de imprensa
   não obrigam.
5. Na variável V4, campo v4_region_gated: quando os documentos não trazem
   tabela de bases legais por finalidade, a resposta é "not-verifiable
   (vantage)", nunca "No".
6. Confiança: "alta" quando a citação diz literalmente o que o campo pergunta;
   "média" quando exige interpretação; "baixa" quando a evidência é indireta
   ou ambígua.
7. A decisão é do codificador humano. Você sugere. Não insista e não use
   linguagem persuasiva.
8. Responda só com JSON, no formato pedido. Razões em português, com no máximo
   duas frases.
"""


def sha(texto: str, n: int | None = None) -> str:
    h = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    return h[:n] if n else h


def texto_de(html: str) -> str:
    """HTML do codebook em texto corrido, para o prompt."""
    t = re.sub(r"<(br|/p|/li|/h\d|/tr|/div)\b[^>]*>", "\n", html or "", flags=re.I)
    t = re.sub(r"<li\b[^>]*>", "\n- ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html_mod.unescape(t)
    linhas = [" ".join(l.split()) for l in t.splitlines()]
    return "\n".join(l for l in linhas if l).strip()


# ------------------------------------------------------------ esquema de saída

def esquema(cb: dict) -> dict:
    """JSON Schema da resposta, gerado do codebook: as opções viram enum."""
    props = {}
    for v in cb["variaveis"]:
        if v["vid"] not in VARIAVEIS_DO_COPILOTO:
            continue
        campos = {}
        for c in v["campos"]:
            if c["tipo"] == "text":
                continue
            opcoes = [o for o in c["opcoes"] if o != ""]
            if c["tipo"] == "select":
                campos[c["chave"]] = {"type": "string", "enum": opcoes}
            elif c["tipo"] == "checks":
                campos[c["chave"]] = {"type": "array", "items": {"type": "string", "enum": opcoes}}
            else:  # line
                campos[c["chave"]] = {"type": "string"}
        props[v["vid"]] = {
            "type": "object",
            "properties": {
                "campos": {"type": "object", "properties": campos,
                           "required": list(campos), "additionalProperties": False},
                "razao": {"type": "string"},
                "confianca": {"type": "string", "enum": list(CONFIANCAS)},
                "citacoes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["campos", "razao", "confianca", "citacoes"],
            "additionalProperties": False,
        }
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def impressao_do_prompt(cb: dict) -> str:
    """Identidade do que o modelo recebeu: sistema + esquema. 12 hex."""
    return sha(SISTEMA + json.dumps(esquema(cb), sort_keys=True), 12)


# ------------------------------------------------------------------ mensagem

def citacoes_com_id(sugestoes: dict) -> dict:
    """{id: citação} na ordem do arquivo congelado. Sem `role`."""
    saida = {}
    for vid, lista in (sugestoes.get("citacoes") or {}).items():
        for i, c in enumerate(lista, 1):
            saida[f"{vid}-{i}"] = {k: c[k] for k in ("doc", "file", "onde", "verbatim") if k in c}
    return saida


def montar_mensagem(servico: str, cb: dict, ids: dict, piso: dict) -> str:
    partes = [f"SERVIÇO: {servico}", "", "DOCUMENTOS:"]
    for d in piso["docs"]:
        partes.append(f"{d['n']}. {d['titulo'] or '(sem título)'} · {d['url']} ({d['chars']} caracteres)")
    partes += ["", "CONTAGEM DE PALAVRAS-CHAVE POR DOCUMENTO:"]
    for d in piso["docs"]:
        partes.append(f"{d['n']}: {d['log_line'] or 'sem varredura'}")
    partes += ["", "CODEBOOK:"]
    for v in cb["variaveis"]:
        if v["vid"] not in VARIAVEIS_DO_COPILOTO:
            continue
        partes.append(f"\n[{v['vid']}] {v['titulo']}")
        partes.append(f"Pergunta: {v['pergunta']}")
        partes.append(f"Critério congelado:\n{texto_de(v['crit_html'])}")
        partes.append(f"Guia:\n{texto_de(v['guia_html'])}")
        linhas = []
        for c in v["campos"]:
            if c["tipo"] == "text":
                continue
            ops = ", ".join(o for o in c["opcoes"] if o) if c["tipo"] in ("select", "checks") else "texto curto"
            linhas.append(f"- {c['chave']} ({c['tipo']}): {ops}")
        partes.append("Campos:\n" + "\n".join(linhas))
    partes += ["", "CITAÇÕES:"]
    if not ids:
        partes.append("(nenhuma citação verificada para este serviço)")
    for cid, c in ids.items():
        partes.append(f"{cid} (documento {c.get('doc')}, {c.get('onde', '')}): \"{c.get('verbatim', '')}\"")
    partes += ["", "FORMATO DA RESPOSTA: um objeto JSON com as chaves V1 a V9. Em cada uma: "
               "\"campos\" (um valor por campo listado acima), \"razao\" (até duas frases), "
               "\"confianca\" (alta, média ou baixa) e \"citacoes\" (lista de identificadores usados)."]
    return "\n".join(partes)


# ----------------------------------------------------------------- validação

def validar(resposta: dict, cb: dict, ids: dict) -> list[str]:
    problemas = []
    if not isinstance(resposta, dict):
        return ["resposta não é um objeto JSON"]
    for v in cb["variaveis"]:
        vid = v["vid"]
        if vid not in VARIAVEIS_DO_COPILOTO:
            continue
        item = resposta.get(vid)
        if not isinstance(item, dict):
            problemas.append(f"{vid}: ausente")
            continue
        campos = item.get("campos")
        if not isinstance(campos, dict):
            problemas.append(f"{vid}: 'campos' ausente")
            campos = {}
        for c in v["campos"]:
            if c["tipo"] == "text":
                continue
            val = campos.get(c["chave"])
            opcoes = [o for o in c["opcoes"] if o != ""]
            if c["tipo"] == "select":
                if val not in opcoes:
                    problemas.append(f"{vid}.{c['chave']}: valor {val!r} fora das opções {opcoes}")
            elif c["tipo"] == "checks":
                if not isinstance(val, list) or not val or not set(val) <= set(opcoes):
                    problemas.append(f"{vid}.{c['chave']}: esperada lista não vazia dentro de {opcoes}, veio {val!r}")
            else:
                if not isinstance(val, str) or len(val) > LINHA_MAX:
                    problemas.append(f"{vid}.{c['chave']}: esperado texto curto, veio {val!r}")
        if campos.get("v6_optin_beta") == "Yes" and not (campos.get("v6_which") or "").strip():
            problemas.append("V6.v6_which: exigido quando v6_optin_beta = Yes")
        if item.get("confianca") not in CONFIANCAS:
            problemas.append(f"{vid}: confiança {item.get('confianca')!r} fora de {CONFIANCAS}")
        razao = item.get("razao")
        if not isinstance(razao, str) or not razao.strip() or len(razao) > RAZAO_MAX:
            problemas.append(f"{vid}: razão ausente ou longa demais")
        cits = item.get("citacoes")
        if not isinstance(cits, list) or any(c not in ids for c in cits):
            problemas.append(f"{vid}: citações inválidas {cits!r}")
    return problemas


def _limpar_json(texto: str) -> str:
    t = texto.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t


# ------------------------------------------------------------------- geração

def _chamar(cliente, modelo: str, cb: dict, mensagem: str):
    with cliente.messages.stream(
        model=modelo,
        max_tokens=MAX_TOKENS,
        system=SISTEMA,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": esquema(cb)}},
        messages=[{"role": "user", "content": mensagem}],
    ) as fluxo:
        resposta = fluxo.get_final_message()
    parada = getattr(resposta, "stop_reason", None)
    if parada == "refusal":
        raise RuntimeError(f"o modelo recusou ({getattr(resposta, 'stop_details', '')})")
    if parada == "max_tokens":
        raise RuntimeError(f"resposta truncada em {MAX_TOKENS} tokens de saída")
    texto = next(b.text for b in resposta.content if b.type == "text")
    uso = {"input": resposta.usage.input_tokens, "output": resposta.usage.output_tokens}
    return json.loads(_limpar_json(texto)), uso


def entradas(servico: str, corpus) -> tuple[dict, dict]:
    """(ids das citações congeladas, piso) do serviço."""
    slug = corpus.por_servico[servico]["slug"]
    try:
        sug = json.loads(corpus.ler_irmao(f"sugestoes/{slug}.json"))
    except Exception:
        sug = {}
    if sug.get("servico") not in (None, servico):
        sug = {}
    return citacoes_com_id(sug), EP.exportar_um(servico, corpus)


def gerar_um(servico: str, corpus, cb: dict, modelo: str, cliente) -> dict:
    ids, piso = entradas(servico, corpus)
    mensagem = montar_mensagem(servico, cb, ids, piso)
    resposta, uso = _chamar(cliente, modelo, cb, mensagem)
    problemas = validar(resposta, cb, ids)
    tentativas = 1
    if problemas:
        # Uma segunda chance, com a lista do que veio errado.
        extra = "\n\nA resposta anterior tinha estes problemas; corrija-os:\n- " + "\n- ".join(problemas)
        resposta, uso2 = _chamar(cliente, modelo, cb, mensagem + extra)
        uso = {k: uso[k] + uso2[k] for k in uso}
        problemas = validar(resposta, cb, ids)
        tentativas = 2
    registro = {
        "formato": FORMATO,
        "servico": servico,
        "slug": corpus.por_servico[servico]["slug"],
        "modelo": modelo,
        "prompt_sha": impressao_do_prompt(cb),
        "entrada_sha": sha(mensagem, 12),
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus_frozen_at": corpus.index.get("frozen_at"),
        "corpus_built_at": corpus.index.get("built_at"),
        "geracao": {"max_tokens": MAX_TOKENS, "thinking": "adaptive", "tentativas": tentativas},
        "n_citacoes": len(ids),
        "variaveis": {} if problemas else {vid: resposta[vid] for vid in VARIAVEIS_DO_COPILOTO},
        "uso": uso,
    }
    if problemas:
        registro["invalida"] = problemas
    return registro


def prompt_md(cb: dict, modelo: str) -> str:
    return "\n".join([
        "# Como o copiloto funciona",
        "",
        f"Modelo: `{modelo}`. Impressão do prompt (SHA-256, 12 hex): `{impressao_do_prompt(cb)}`.",
        "",
        "O copiloto roda uma vez por serviço, antes da codificação, e o resultado fica "
        "congelado num arquivo por serviço nesta mesma pasta. A página só lê o arquivo. "
        "Não há chamada ao modelo durante a codificação.",
        "",
        "## O que o modelo recebe",
        "",
        "1. O nome do serviço e a lista de documentos congelados (número, título, URL, tamanho).",
        "2. A contagem dos 12 termos do protocolo em cada documento.",
        "3. O codebook: para cada variável, a pergunta, o critério congelado em 04/07/2026, "
        "o guia em linguagem direta e os campos com as opções.",
        "4. As citações verificadas do serviço (`sugestoes/`), cada uma com um identificador.",
        "",
        "O modelo não recebe códigos nem anotações da primeira codificação, nem a etiqueta "
        "de tipo de documento, nem respostas do segundo codificador.",
        "",
        "## O que o modelo devolve",
        "",
        "Para cada variável V1 a V9: um valor por campo (dentro das opções do codebook, "
        "garantido pelo esquema de saída), uma razão de até duas frases, a confiança "
        "(alta, média ou baixa) e os identificadores das citações usadas. Os campos de "
        "evidência não são pedidos ao modelo: a página os preenche com as citações indicadas.",
        "",
        "## Prompt de sistema, na íntegra",
        "",
        "```",
        SISTEMA.rstrip(),
        "```",
        "",
        "## Estrutura da mensagem por serviço",
        "",
        "```",
        "SERVIÇO: <nome>",
        "DOCUMENTOS: <n>. <título> · <url> (<caracteres>)",
        "CONTAGEM DE PALAVRAS-CHAVE POR DOCUMENTO: <n>: termo:número / ...",
        "CODEBOOK: [Vn] título / Pergunta / Critério congelado / Guia / Campos",
        "CITAÇÕES: Vn-i (documento n, onde): \"verbatim\"",
        "FORMATO DA RESPOSTA: ...",
        "```",
        "",
        f"Gerado em {datetime.now(timezone.utc).isoformat(timespec='seconds')}.",
        "",
    ])


def escrever_todos(corpus, destino: Path, modelo: str, cliente, so: str | None = None) -> list[dict]:
    destino.mkdir(parents=True, exist_ok=True)
    cb = EC.exportar()
    servicos = [so] if so else list(C.SERVICOS)
    indice = []
    for servico in servicos:
        reg = gerar_um(servico, corpus, cb, modelo, cliente)
        texto = json.dumps(reg, ensure_ascii=False, indent=1) + "\n"
        alvo = destino / f"{reg['slug']}.json"
        alvo.write_text(texto, encoding="utf-8")
        indice.append({"servico": servico, "slug": reg["slug"], "file": alvo.name,
                       "sha256": sha(texto), "invalida": bool(reg.get("invalida")),
                       "uso": reg["uso"]})
        estado = "INVÁLIDA" if reg.get("invalida") else "ok"
        print(f"  {servico}: {estado} · {reg['uso']['input']} in / {reg['uso']['output']} out")
    (destino / "prompt.md").write_text(prompt_md(cb, modelo), encoding="utf-8")
    atualizar_indice(destino, cb, modelo)
    return indice


def atualizar_indice(destino: Path, cb: dict, modelo: str) -> dict:
    """index.json a partir dos arquivos presentes (serve para rodadas parciais)."""
    itens = []
    for p in sorted(destino.glob("*.json")):
        if p.name == "index.json":
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        itens.append({"servico": d["servico"], "slug": d["slug"], "file": p.name,
                      "sha256": sha(p.read_text(encoding="utf-8")),
                      "invalida": bool(d.get("invalida")), "uso": d.get("uso", {})})
    idx = {"formato": FORMATO, "modelo": modelo, "prompt_sha": impressao_do_prompt(cb),
           "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "servicos": itens,
           "uso_total": {"input": sum(i["uso"].get("input", 0) for i in itens),
                         "output": sum(i["uso"].get("output", 0) for i in itens)}}
    (destino / "index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return idx


def checar(corpus, destino: Path) -> int:
    cb = EC.exportar()
    problemas = []
    if not (destino / "prompt.md").exists():
        problemas.append("prompt.md ausente")
    if not (destino / "index.json").exists():
        problemas.append("index.json ausente")
    esperado = impressao_do_prompt(cb)
    for servico in C.SERVICOS:
        slug = corpus.por_servico[servico]["slug"]
        p = destino / f"{slug}.json"
        if not p.exists():
            problemas.append(f"{servico}: arquivo ausente")
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("invalida"):
            problemas.append(f"{servico}: resposta inválida ({d['invalida'][:2]})")
            continue
        if d.get("prompt_sha") != esperado:
            problemas.append(f"{servico}: gerado com outro prompt ({d.get('prompt_sha')} ≠ {esperado})")
        ids, _ = entradas(servico, corpus)
        erros = validar(d.get("variaveis", {}), cb, ids)
        if erros:
            problemas.append(f"{servico}: {erros[:2]}")
        if '"role"' in json.dumps(d):
            problemas.append(f"{servico}: traz etiqueta role")
    for p in problemas:
        print(f"  FALHA {p}")
    print(f"copiloto: {26 - sum(1 for p in problemas if ':' in p)} serviços válidos, "
          f"{len(problemas)} problema(s)")
    return 0 if not problemas else 1


def estimar(corpus, modelo: str, cliente) -> int:
    cb = EC.exportar()
    total = 0
    for servico in C.SERVICOS:
        ids, piso = entradas(servico, corpus)
        msg = montar_mensagem(servico, cb, ids, piso)
        r = cliente.messages.count_tokens(model=modelo, system=SISTEMA,
                                          messages=[{"role": "user", "content": msg}])
        print(f"  {servico}: {r.input_tokens} tokens de entrada, {len(ids)} citações")
        total += r.input_tokens
    print(f"total: {total} tokens de entrada em 26 chamadas (saída: cerca de 1 a 2 mil por serviço)")
    return 0


# ---------------------------------------------------------------- simulação

class _ClienteFalso:
    """Devolve uma resposta válida montada do esquema, sem rede."""

    def __init__(self, cb: dict, ids: dict, forcar=None):
        self.cb, self.ids, self.forcar = cb, ids, forcar
        self.chamadas = 0
        self.messages = self

    def resposta_canonica(self) -> dict:
        saida = {}
        for v in self.cb["variaveis"]:
            if v["vid"] not in VARIAVEIS_DO_COPILOTO:
                continue
            campos = {}
            for c in v["campos"]:
                if c["tipo"] == "text":
                    continue
                ops = [o for o in c["opcoes"] if o]
                campos[c["chave"]] = ops[0] if c["tipo"] == "select" else ([ops[0]] if c["tipo"] == "checks" else "")
            if campos.get("v6_optin_beta") == "Yes":
                campos["v6_which"] = "programa beta"
            cits = [k for k in self.ids if k.startswith(v["vid"] + "-")][:1]
            saida[v["vid"]] = {"campos": campos, "razao": "simulação: primeira opção de cada campo.",
                               "confianca": "baixa", "citacoes": cits}
        return saida

    def stream(self, **kw):
        self.chamadas += 1
        corpo = self.resposta_canonica()
        if self.forcar:
            corpo = self.forcar(corpo, self.chamadas)
        cliente = self

        class _Ctx:
            def __enter__(self_inner):
                class _Msg:
                    stop_reason = "end_turn"
                    content = [type("B", (), {"type": "text", "text": json.dumps(corpo, ensure_ascii=False)})()]
                    usage = type("U", (), {"input_tokens": 1000, "output_tokens": 300})()
                return type("F", (), {"get_final_message": staticmethod(lambda: _Msg())})()

            def __exit__(self_inner, *a):
                return False
        return _Ctx()


def _self_test(corpus_dir: str | None) -> int:
    falhas = []

    def checar_um(desc, cond):
        print(f"  {'ok  ' if cond else 'FALHA'} {desc}")
        if not cond:
            falhas.append(desc)

    cb = EC.exportar()
    # Entradas: do corpus local se houver; senão, um serviço sintético.
    try:
        corpus = R.Corpus(corpus_dir) if corpus_dir else None
    except Exception:
        corpus = None
    if corpus:
        servico = "Wikipedia"
        ids, piso = entradas(servico, corpus)
    else:
        servico = "Serviço X"
        ids = {"V1-1": {"doc": 1, "file": "x/01.md", "onde": "Seção 2", "verbatim": "we run experiments"}}
        piso = {"docs": [{"n": 1, "titulo": "Privacy Policy", "url": "https://x.example/privacy",
                          "chars": 100, "log_line": "experiment:1"}]}
    msg = montar_mensagem(servico, cb, ids, piso)
    checar_um("mensagem traz o serviço, o codebook e as citações",
              servico in msg and "[V1]" in msg and "[V9]" in msg and ("V1-1" in msg or not ids))
    checar_um("mensagem não traz etiqueta de tipo de documento",
              '"role"' not in msg and "[vinculante]" not in msg and "não vinculante]" not in msg)
    checar_um("mensagem não traz anotação da passada 1",
              "codificado em" not in msg and "passada 1" not in msg and "primeira passada" not in msg)
    checar_um("mensagem não traz âncora do piloto", "âncora" not in msg.lower())
    checar_um("critério vira texto, sem tags", "<" not in texto_de(cb["variaveis"][0]["crit_html"]))

    esq = esquema(cb)
    checar_um("esquema cobre V1..V9 e nada mais", list(esq["properties"]) == list(VARIAVEIS_DO_COPILOTO))
    checar_um("esquema pede os campos sem os de texto",
              "v1_evidence" not in esq["properties"]["V1"]["properties"]["campos"]["properties"]
              and "v1_code" in esq["properties"]["V1"]["properties"]["campos"]["properties"])
    checar_um("v1_code no esquema é enum sem o vazio",
              esq["properties"]["V1"]["properties"]["campos"]["properties"]["v1_code"]["enum"] == ["0", "1", "2", "3"])

    falso = _ClienteFalso(cb, ids)
    canon = falso.resposta_canonica()
    checar_um("validar aceita a resposta canônica", validar(canon, cb, ids) == [])
    ruim = json.loads(json.dumps(canon)); ruim["V1"]["campos"]["v1_code"] = "7"
    checar_um("validar rejeita valor fora das opções", any("v1_code" in p for p in validar(ruim, cb, ids)))
    ruim = json.loads(json.dumps(canon)); ruim["V2"]["campos"]["v2_framing"] = []
    checar_um("validar rejeita múltipla escolha vazia", any("v2_framing" in p for p in validar(ruim, cb, ids)))
    ruim = json.loads(json.dumps(canon)); del ruim["V5"]
    checar_um("validar rejeita variável ausente", "V5: ausente" in validar(ruim, cb, ids))
    ruim = json.loads(json.dumps(canon)); ruim["V1"]["citacoes"] = ["V1-99"]
    checar_um("validar rejeita citação inexistente", any("citações inválidas" in p for p in validar(ruim, cb, ids)))
    ruim = json.loads(json.dumps(canon)); ruim["V6"]["campos"]["v6_optin_beta"] = "Yes"; ruim["V6"]["campos"]["v6_which"] = ""
    checar_um("validar exige v6_which quando há programa beta", any("v6_which" in p for p in validar(ruim, cb, ids)))
    ruim = json.loads(json.dumps(canon)); ruim["V3"]["confianca"] = "altíssima"
    checar_um("validar rejeita confiança fora da escala", any("confiança" in p for p in validar(ruim, cb, ids)))
    checar_um("JSON com cerca de código é limpo", json.loads(_limpar_json("```json\n{\"a\": 1}\n```")) == {"a": 1})

    if corpus:
        reg = gerar_um(servico, corpus, cb, "modelo-falso", falso)
        checar_um("gerar_um devolve as 9 variáveis, modelo, SHAs e uso",
                  set(reg["variaveis"]) == set(VARIAVEIS_DO_COPILOTO) and reg["modelo"] == "modelo-falso"
                  and re.fullmatch(r"[0-9a-f]{12}", reg["prompt_sha"]) and re.fullmatch(r"[0-9a-f]{12}", reg["entrada_sha"])
                  and reg["uso"] == {"input": 1000, "output": 300} and "invalida" not in reg)
        checar_um("gerar_um não traz etiqueta role", '"role"' not in json.dumps(reg))

        def estragar(corpo, chamada):
            if chamada == 1:
                corpo["V1"]["campos"]["v1_code"] = "9"
            return corpo
        teimoso = _ClienteFalso(cb, ids, forcar=estragar)
        reg2 = gerar_um(servico, corpus, cb, "modelo-falso", teimoso)
        checar_um("resposta inválida ganha uma segunda tentativa, que passa",
                  teimoso.chamadas == 2 and "invalida" not in reg2 and reg2["geracao"]["tentativas"] == 2)
        sempre = _ClienteFalso(cb, ids, forcar=lambda c, n: (c["V1"]["campos"].__setitem__("v1_code", "9"), c)[1])
        reg3 = gerar_um(servico, corpus, cb, "modelo-falso", sempre)
        checar_um("duas respostas inválidas: registro marcado como inválido, sem variáveis",
                  reg3.get("invalida") and reg3["variaveis"] == {})

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            idx = escrever_todos(corpus, dest, "modelo-falso", _ClienteFalso(cb, ids), so=servico)
            checar_um("escrever_todos grava o arquivo, o prompt.md e o index.json",
                      len(idx) == 1 and (dest / "prompt.md").exists() and (dest / "index.json").exists())
            checar_um("prompt.md traz o sistema inteiro e a impressão",
                      SISTEMA.strip() in (dest / "prompt.md").read_text(encoding="utf-8")
                      and impressao_do_prompt(cb) in (dest / "prompt.md").read_text(encoding="utf-8"))
    else:
        print("  pulou  (sem corpus local: gerar_um e escrever_todos não exercitados)")

    checar_um("nenhum travessão no prompt de sistema", "—" not in SISTEMA)
    print("\n" + ("tudo ok" if not falhas else f"{len(falhas)} falha(s)"))
    return 0 if not falhas else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", help="pasta md/ do corpus congelado (ou URL)")
    ap.add_argument("--out", type=Path, help="pasta de destino (assistente/copiloto)")
    ap.add_argument("--modelo", default=MODELO_PADRAO)
    ap.add_argument("--so", help="gerar só este serviço")
    ap.add_argument("--estimar", action="store_true", help="contar tokens, sem gerar")
    ap.add_argument("--check", action="store_true", help="conferir o que está em --out")
    ap.add_argument("--simular", action="store_true", help="self-test sem rede")
    a = ap.parse_args()
    if a.simular:
        return _self_test(a.corpus)
    if not a.corpus:
        ap.error("informe --corpus")
    corpus = R.Corpus(a.corpus)
    if a.check:
        if not a.out:
            ap.error("--check precisa de --out")
        return checar(corpus, a.out)
    cliente = R._cliente()
    if a.estimar:
        return estimar(corpus, a.modelo, cliente)
    if not a.out:
        ap.error("informe --out")
    idx = escrever_todos(corpus, a.out, a.modelo, cliente, so=a.so)
    inv = sum(1 for i in idx if i["invalida"])
    print(f"copiloto: {len(idx)} serviço(s), {inv} inválido(s) → {a.out}")
    return 0 if not inv else 1


if __name__ == "__main__":
    sys.exit(main())
