#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""O copiloto do 2º codificador: uma nota por trecho e um tipo por documento, congelados.

    python3 analysis/copiloto.py --corpus <md> --estimar                 # tokens, sem gastar
    python3 analysis/copiloto.py --corpus <md> --out <corpus>/assistente/copiloto --so Wikipedia
    python3 analysis/copiloto.py --corpus <md> --out <corpus>/assistente/copiloto
    python3 analysis/copiloto.py --corpus <md> --out <corpus>/assistente/copiloto --check
    python3 analysis/copiloto.py --simular --corpus <md>                 # self-test, sem rede

A chave da API vem de EWC_ANTHROPIC_KEY, lida inline no comando:
    EWC_ANTHROPIC_KEY="$(security find-generic-password -s ewc-anthropic-key -w)" python3 ...

FORMATO 2 (04/10/2026). Na página, o codificador dá uma nota a cada trecho e
a resposta da variável é calculada do critério congelado (assistente/core.mjs,
`derivar`). O copiloto acompanha: para cada trecho de cada variável, sugere a
nota (nas opções de `codebook.json: notas`, ou "x" para "não é isso"); para
cada documento, sugere o tipo (`tipos_doc`); e preenche as perguntas avulsas
(`extras`). A página aplica a sugestão só onde o codificador ainda não disse
nada. O formato 1 (uma resposta final por variável) saiu com a decisão B.

O QUE O MODELO RECEBE, por serviço: o codebook (critério congelado, guia,
opções de nota de cada variável), a lista de documentos (número, título, URL,
tamanho), a contagem de palavras-chave por documento e os trechos de cada
variável com seus ids (busca por palavra-chave e citações verificadas).

O QUE ELE NÃO RECEBE: códigos ou anotações da passada 1; a etiqueta `role`
(vinculante) dos documentos; respostas do 2º codificador.

IDS DOS TRECHOS. `c:V1-3` é a 3ª citação da V1 em sugestoes/<slug>.json;
`h:<8 hex>` é um hit da busca, FNV-1a de "arquivo\\ntrecho". O cálculo é o
mesmo de core.mjs (`idDoHit`); o self-test confere contra valores gerados lá.

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

FORMATO = 2
MODELO_PADRAO = "claude-opus-5-5"
MAX_TOKENS = 16000
RAZAO_MAX = 400
LINHA_MAX = 200
VARIAVEIS_DO_COPILOTO = ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9")
NAO_E_ISSO = "x"

SISTEMA = """\
Você é o copiloto de um codificador humano num estudo documental. O estudo
classifica o que plataformas online declaram sobre experimentação com os
próprios usuários, e em que tipo de documento declaram.

Para um serviço de cada vez, você recebe: o codebook (o critério congelado e o
guia de cada variável, com as notas possíveis por trecho), a lista de
documentos congelados, a contagem de 12 palavras-chave por documento e, para
cada variável, os trechos localizados nos documentos, cada um com um
identificador. Você julga cada trecho e classifica cada documento.

Regras:
1. Só o material fornecido conta. Não use conhecimento externo sobre a plataforma.
2. Para cada trecho de cada variável, dê a nota que o trecho mostra, nas opções
   daquela variável, ou "x" quando o trecho não é isso (falso positivo, outro
   sentido, outro assunto). Julgue o trecho, não o serviço: a resposta da
   variável é calculada depois, a partir das notas.
3. Nas variáveis de nota múltipla, um trecho pode receber mais de uma nota.
4. Para o tipo de cada documento, use a função do documento, pela URL e pelo
   título. Aviso de cookies e tabela de bases legais contam como política de
   privacidade. Em caso de dúvida: o documento se declara parte do acordo com
   o usuário? Se sim, política de privacidade ou termos de uso.
5. Na V4, campo v4_region_gated: quando os documentos não trazem tabela de
   bases legais por finalidade, a resposta é "not-verifiable (vantage)", nunca
   "No". Em v4_mapped_purpose, escreva a finalidade declarada que cobre
   experimentação (por exemplo "improve our services").
6. Na V6, se algum trecho recebeu nota, escreva em v6_which o nome do programa.
   Na V3, escreva em v3_targets os alvos nomeados, separados por ponto e vírgula.
7. Na V9, julgue também os trechos herdados da V1: a pergunta é se aquele trecho
   divulga experimentação naquele documento.
8. A decisão é do codificador humano. Você sugere. Não insista e não use
   linguagem persuasiva. A razão de cada variável tem no máximo duas frases.
9. Responda só com JSON, no formato pedido.
"""


def sha(texto: str, n: int | None = None) -> str:
    h = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    return h[:n] if n else h


def hash8(texto: str) -> str:
    """FNV-1a de 32 bits sobre UTF-8, 8 hex. Igual a core.mjs `hash8`."""
    h = 0x811C9DC5
    for b in texto.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def id_do_hit(hit: dict) -> str:
    return f"h:{hash8(hit['file'] + chr(10) + hit['kwic'])}"


def texto_de(html: str) -> str:
    """HTML do codebook em texto corrido, para o prompt."""
    t = re.sub(r"<(br|/p|/li|/h\d|/tr|/div)\b[^>]*>", "\n", html or "", flags=re.I)
    t = re.sub(r"<li\b[^>]*>", "\n- ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html_mod.unescape(t)
    linhas = [" ".join(l.split()) for l in t.splitlines()]
    return "\n".join(l for l in linhas if l).strip()


# ------------------------------------------------------------------- trechos

def citacoes_com_id(sugestoes: dict) -> dict:
    """{vid: [citação com id c:Vn-i]}, sem `role`."""
    saida = {}
    for vid, lista in (sugestoes.get("citacoes") or {}).items():
        saida[vid] = [{"id": f"c:{vid}-{i}", **{k: c[k] for k in ("doc", "file", "onde", "verbatim") if k in c}}
                      for i, c in enumerate(lista, 1)]
    return saida


def trechos_da_variavel(vid: str, piso: dict, cits: dict) -> list[dict]:
    """Mesma lista que core.mjs `trechosDaVariavel`, para o copiloto julgar.

    Na V9 entram todos os trechos da V1 (a página só mostra os que o
    codificador julgou relevantes na V1; a nota sugerida para os outros é
    ignorada lá).
    """
    hits = (piso.get("por_variavel") or {}).get(vid, [])
    lista = [{"id": id_do_hit(h), "origem": "piso", "verbatim": h["kwic"], "doc": h["n"],
              "onde": f'palavra-chave "{h["termo"]}"', "file": h["file"]} for h in hits]
    lista += [{"id": c["id"], "origem": "modelo", "verbatim": c.get("verbatim", ""), "doc": c.get("doc"),
               "onde": c.get("onde", ""), "file": c.get("file")} for c in cits.get(vid, [])]
    if vid == "V9":
        vistos = {t["id"] for t in lista}
        lista += [{**t, "origem": "v1"} for t in trechos_da_variavel("V1", piso, cits) if t["id"] not in vistos]
    return lista


# ------------------------------------------------------------ esquema de saída

def esquema(cb: dict | None = None) -> dict:
    """Compacto, em forma de lista: a API recusa esquemas grandes por variável."""
    nota = {"type": "object",
            "properties": {"id": {"type": "string"}, "nota": {"type": "string"},
                           "valores": {"type": "array", "items": {"type": "string"}}},
            "required": ["id", "nota", "valores"], "additionalProperties": False}
    extra = {"type": "object", "properties": {"chave": {"type": "string"}, "valor": {"type": "string"}},
             "required": ["chave", "valor"], "additionalProperties": False}
    variavel = {"type": "object",
                "properties": {"vid": {"type": "string"},
                               "notas": {"type": "array", "items": nota},
                               "extras": {"type": "array", "items": extra},
                               "razao": {"type": "string"}},
                "required": ["vid", "notas", "extras", "razao"], "additionalProperties": False}
    documento = {"type": "object", "properties": {"n": {"type": "integer"}, "tipo": {"type": "string"}},
                 "required": ["n", "tipo"], "additionalProperties": False}
    return {"type": "object",
            "properties": {"documentos": {"type": "array", "items": documento},
                           "variaveis": {"type": "array", "items": variavel}},
            "required": ["documentos", "variaveis"], "additionalProperties": False}


def impressao_do_prompt(cb: dict) -> str:
    """Identidade do que o modelo recebeu: sistema + esquema + formato. 12 hex."""
    return sha(SISTEMA + json.dumps(esquema(cb), sort_keys=True) + f"formato={FORMATO}", 12)


def normalizar(bruto: dict, cb: dict) -> dict:
    """Da lista do esquema para {documentos: {n: {tipo, registro}}, variaveis: {vid: {notas, extras, razao}}}."""
    modos = {vid: spec["modo"] for vid, spec in cb["notas"].items()}
    registro = {t["valor"]: t["registro"] for t in cb["tipos_doc"]}
    docs = {}
    for d in (bruto or {}).get("documentos", []) if isinstance(bruto, dict) else []:
        if isinstance(d, dict) and "n" in d:
            docs[str(d["n"])] = {"tipo": d.get("tipo"), "registro": registro.get(d.get("tipo"))}
    variaveis = {}
    for item in (bruto or {}).get("variaveis", []) if isinstance(bruto, dict) else []:
        if not isinstance(item, dict):
            continue
        vid = item.get("vid")
        notas = {}
        for n in item.get("notas", []) or []:
            if not isinstance(n, dict) or not n.get("id"):
                continue
            if modos.get(vid) == "varios" and n.get("nota") != NAO_E_ISSO:
                vals = n.get("valores") or ([n["nota"]] if n.get("nota") else [])
                notas[n["id"]] = [str(x) for x in vals]
            else:
                notas[n["id"]] = str(n.get("nota") or "")
        extras = {e["chave"]: str(e.get("valor") or "") for e in (item.get("extras") or []) if isinstance(e, dict) and e.get("chave")}
        variaveis[vid] = {"notas": notas, "extras": extras, "razao": item.get("razao")}
    return {"documentos": docs, "variaveis": variaveis}


def para_bruto(normalizado: dict, cb: dict) -> dict:
    """O inverso de `normalizar`, para a simulação e para testes."""
    modos = {vid: spec["modo"] for vid, spec in cb["notas"].items()}
    docs = [{"n": int(n), "tipo": d["tipo"]} for n, d in normalizado.get("documentos", {}).items()]
    lista = []
    for vid, item in normalizado.get("variaveis", {}).items():
        notas = []
        for nid, val in item["notas"].items():
            if modos.get(vid) == "varios" and isinstance(val, list):
                notas.append({"id": nid, "nota": "", "valores": list(val)})
            else:
                notas.append({"id": nid, "nota": str(val), "valores": []})
        lista.append({"vid": vid, "notas": notas,
                      "extras": [{"chave": k, "valor": v} for k, v in item.get("extras", {}).items()],
                      "razao": item.get("razao", "")})
    return {"documentos": docs, "variaveis": lista}


# ------------------------------------------------------------------ mensagem

def montar_mensagem(servico: str, cb: dict, trechos: dict, piso: dict) -> str:
    partes = [f"SERVIÇO: {servico}", "", "DOCUMENTOS (dê o tipo de cada um):"]
    for d in piso["docs"]:
        partes.append(f"{d['n']}. {d['titulo'] or '(sem título)'} · {d['url']} ({d['chars']} caracteres)")
    partes.append("Tipos possíveis: " + "; ".join(f"\"{t['valor']}\" = {t['rotulo']}" for t in cb["tipos_doc"]))
    partes += ["", "CONTAGEM DE PALAVRAS-CHAVE POR DOCUMENTO:"]
    for d in piso["docs"]:
        partes.append(f"{d['n']}: {d['log_line'] or 'sem varredura'}")
    partes += ["", "CODEBOOK E TRECHOS, POR VARIÁVEL:"]
    for v in cb["variaveis"]:
        vid = v["vid"]
        if vid not in VARIAVEIS_DO_COPILOTO:
            continue
        spec = cb["notas"][vid]
        partes.append(f"\n[{vid}] {v['titulo']}")
        partes.append(f"Pergunta: {v['pergunta']}")
        partes.append(f"Critério congelado:\n{texto_de(v['crit_html'])}")
        partes.append(f"Guia:\n{texto_de(v['guia_html'])}")
        modo = "uma nota por trecho" if spec["modo"] == "um" else "uma ou mais notas por trecho"
        partes.append(f"Notas possíveis ({modo}): " + "; ".join(f"\"{o['valor']}\" = {o['rotulo']}" for o in spec["opcoes"])
                      + f"; \"{NAO_E_ISSO}\" = não é isso")
        extras = (cb.get("extras") or {}).get(vid) or []
        if extras:
            linhas = []
            for ch in extras:
                campo = next(c for c in v["campos"] if c["chave"] == ch)
                ops = ", ".join(o for o in campo["opcoes"] if o) if campo["tipo"] in ("select", "checks") else "texto curto"
                linhas.append(f"- {ch} ({campo['tipo']}): {ops}")
            partes.append("Perguntas avulsas (extras):\n" + "\n".join(linhas))
        lista = trechos.get(vid, [])
        if not lista:
            partes.append("Trechos: nenhum.")
        else:
            partes.append("Trechos:")
            for t in lista:
                herd = " [herdado da V1]" if t["origem"] == "v1" else ""
                partes.append(f"{t['id']} (documento {t['doc']}, {t['onde']}){herd}: \"{t['verbatim']}\"")
    partes += ["", "FORMATO DA RESPOSTA: um objeto JSON {\"documentos\": [...], \"variaveis\": [...]}. "
               "Em \"documentos\", um item por documento: {\"n\", \"tipo\"}. Em \"variaveis\", um item por "
               "variável de V1 a V9: {\"vid\", \"notas\", \"extras\", \"razao\"}. Em \"notas\", um item por "
               "trecho listado: {\"id\", \"nota\", \"valores\"}; nas variáveis de nota única use \"nota\" e "
               "deixe \"valores\" vazio; nas de nota múltipla use \"valores\" e deixe \"nota\" vazio, ou "
               "\"nota\": \"x\" para não é isso. Em \"extras\", {\"chave\", \"valor\"} para cada pergunta "
               "avulsa da variável. \"razao\": até duas frases."]
    return "\n".join(partes)


# ----------------------------------------------------------------- validação

def validar(norm: dict, cb: dict, trechos: dict, docs: list) -> tuple[list[str], list[str]]:
    """(problemas que invalidam, avisos). Trecho sem nota é aviso: a página deixa o codificador julgar."""
    problemas, avisos = [], []
    tipos = {t["valor"] for t in cb["tipos_doc"]}
    docs_norm = norm.get("documentos") or {}
    for d in docs:
        t = (docs_norm.get(str(d["n"])) or {}).get("tipo")
        if t not in tipos:
            problemas.append(f"documento {d['n']}: tipo {t!r} fora de {sorted(tipos)}")
    campos = {c["chave"]: c for v in cb["variaveis"] for c in v["campos"]}
    for vid in VARIAVEIS_DO_COPILOTO:
        item = (norm.get("variaveis") or {}).get(vid)
        if not isinstance(item, dict):
            problemas.append(f"{vid}: ausente")
            continue
        spec = cb["notas"][vid]
        opcoes = {o["valor"] for o in spec["opcoes"]}
        ids = {t["id"] for t in trechos.get(vid, [])}
        notas = item.get("notas") or {}
        for nid, val in notas.items():
            if nid not in ids:
                problemas.append(f"{vid}: id de trecho desconhecido {nid}")
                continue
            if spec["modo"] == "um":
                if val not in opcoes and val != NAO_E_ISSO:
                    problemas.append(f"{vid}.{nid}: nota {val!r} fora de {sorted(opcoes)} e x")
            else:
                if val == NAO_E_ISSO:
                    continue
                if not isinstance(val, list) or not val or not set(val) <= opcoes:
                    problemas.append(f"{vid}.{nid}: esperada lista dentro de {sorted(opcoes)} ou x, veio {val!r}")
        faltam = sorted(ids - set(notas))
        if faltam:
            avisos.append(f"{vid}: {len(faltam)} trecho(s) sem nota sugerida")
        permitidos = set((cb.get("extras") or {}).get(vid) or [])
        for ch, val in (item.get("extras") or {}).items():
            if ch not in permitidos:
                problemas.append(f"{vid}: extra desconhecido {ch}")
                continue
            campo = campos[ch]
            if campo["tipo"] == "select":
                if val and val not in [o for o in campo["opcoes"] if o]:
                    problemas.append(f"{vid}.{ch}: valor {val!r} fora das opções")
            elif len(val) > LINHA_MAX:
                problemas.append(f"{vid}.{ch}: texto longo demais")
        if vid == "V4" and not (item.get("extras") or {}).get("v4_region_gated"):
            problemas.append("V4.v4_region_gated: obrigatório")
        razao = item.get("razao")
        if not isinstance(razao, str) or not razao.strip() or len(razao) > RAZAO_MAX:
            problemas.append(f"{vid}: razão ausente ou longa demais")
    return problemas, avisos


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
    return normalizar(json.loads(_limpar_json(texto)), cb), uso


def entradas(servico: str, corpus) -> tuple[dict, dict]:
    """(trechos por variável, piso) do serviço."""
    slug = corpus.por_servico[servico]["slug"]
    try:
        sug = json.loads(corpus.ler_irmao(f"sugestoes/{slug}.json"))
    except Exception:
        sug = {}
    if sug.get("servico") not in (None, servico):
        sug = {}
    piso = EP.exportar_um(servico, corpus)
    cits = citacoes_com_id(sug)
    trechos = {vid: trechos_da_variavel(vid, piso, cits) for vid in VARIAVEIS_DO_COPILOTO}
    return trechos, piso


def gerar_um(servico: str, corpus, cb: dict, modelo: str, cliente) -> dict:
    trechos, piso = entradas(servico, corpus)
    mensagem = montar_mensagem(servico, cb, trechos, piso)
    norm, uso = _chamar(cliente, modelo, cb, mensagem)
    problemas, avisos = validar(norm, cb, trechos, piso["docs"])
    tentativas = 1
    if problemas:
        extra = "\n\nA resposta anterior tinha estes problemas; corrija-os:\n- " + "\n- ".join(problemas[:40])
        norm, uso2 = _chamar(cliente, modelo, cb, mensagem + extra)
        uso = {k: uso[k] + uso2[k] for k in uso}
        problemas, avisos = validar(norm, cb, trechos, piso["docs"])
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
        "n_trechos": {vid: len(lista) for vid, lista in trechos.items()},
        "documentos": {} if problemas else norm["documentos"],
        "variaveis": {} if problemas else {vid: norm["variaveis"][vid] for vid in VARIAVEIS_DO_COPILOTO},
        "avisos": avisos,
        "uso": uso,
    }
    if problemas:
        registro["invalida"] = problemas
    return registro


def prompt_md(cb: dict, modelo: str) -> str:
    return "\n".join([
        "# Como o copiloto funciona",
        "",
        f"Modelo: `{modelo}`. Impressão do prompt (SHA-256, 12 hex): `{impressao_do_prompt(cb)}`. Formato {FORMATO}.",
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
        "o guia em linguagem direta, as notas possíveis por trecho e as perguntas avulsas.",
        "4. Os trechos de cada variável, com identificadores: os da busca por palavra-chave "
        "(`h:`) e as citações verificadas (`c:`).",
        "",
        "O modelo não recebe códigos nem anotações da primeira codificação, nem a etiqueta "
        "de tipo de documento, nem respostas do segundo codificador.",
        "",
        "## O que o modelo devolve",
        "",
        "Para cada documento, o tipo (política de privacidade, termos de uso, aviso de pesquisa "
        "separado, central de ajuda, blog ou imprensa). Para cada trecho de cada variável, a nota "
        "que o trecho mostra, nas opções do codebook, ou \"x\" quando não é isso. Para as perguntas "
        "avulsas (alvos nomeados, finalidade mapeada, tabela só na UE, qual programa), o valor. "
        "E uma razão de até duas frases por variável.",
        "",
        "A resposta de cada variável não vem do modelo: a página a calcula das notas, pelo "
        "critério congelado (teto na V1, união nas de múltipla escolha, degrau mais alto na V5, "
        "qualquer trecho nas de Sim/Não, tipos dos documentos na V9). A página aplica a sugestão "
        "só nos trechos e documentos que o codificador ainda não julgou.",
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
        "DOCUMENTOS (dê o tipo de cada um): <n>. <título> · <url> (<caracteres>) / Tipos possíveis: ...",
        "CONTAGEM DE PALAVRAS-CHAVE POR DOCUMENTO: <n>: termo:número / ...",
        "CODEBOOK E TRECHOS, POR VARIÁVEL: [Vn] título / Pergunta / Critério congelado / Guia /",
        "    Notas possíveis / Perguntas avulsas / Trechos: <id> (documento n, onde): \"verbatim\"",
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
                       "sha256": sha(texto), "invalida": bool(reg.get("invalida")), "uso": reg["uso"]})
        estado = "INVÁLIDA" if reg.get("invalida") else "ok"
        aviso = f" · {len(reg['avisos'])} aviso(s)" if reg.get("avisos") else ""
        print(f"  {servico}: {estado} · {reg['uso']['input']} in / {reg['uso']['output']} out{aviso}")
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
                      "formato": d.get("formato"), "invalida": bool(d.get("invalida")), "uso": d.get("uso", {})})
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
        if d.get("formato") != FORMATO:
            problemas.append(f"{servico}: formato {d.get('formato')} (esperado {FORMATO})")
            continue
        if d.get("invalida"):
            problemas.append(f"{servico}: resposta inválida ({d['invalida'][:2]})")
            continue
        if d.get("prompt_sha") != esperado:
            problemas.append(f"{servico}: gerado com outro prompt ({d.get('prompt_sha')} ≠ {esperado})")
        trechos, piso = entradas(servico, corpus)
        erros, _ = validar({"documentos": d.get("documentos", {}), "variaveis": d.get("variaveis", {})}, cb, trechos, piso["docs"])
        if erros:
            problemas.append(f"{servico}: {erros[:2]}")
        if '"role"' in json.dumps(d):
            problemas.append(f"{servico}: traz etiqueta role")
    for p in problemas:
        print(f"  FALHA {p}")
    print(f"copiloto: {26 - sum(1 for p in problemas if ':' in p)} serviços válidos, {len(problemas)} problema(s)")
    return 0 if not problemas else 1


def estimar(corpus, modelo: str, cliente) -> int:
    cb = EC.exportar()
    total = 0
    for servico in C.SERVICOS:
        trechos, piso = entradas(servico, corpus)
        msg = montar_mensagem(servico, cb, trechos, piso)
        r = cliente.messages.count_tokens(model=modelo, system=SISTEMA,
                                          messages=[{"role": "user", "content": msg}])
        n = sum(len(v) for v in trechos.values())
        print(f"  {servico}: {r.input_tokens} tokens de entrada, {n} trechos a julgar")
        total += r.input_tokens
    print(f"total: {total} tokens de entrada em 26 chamadas")
    return 0


# ---------------------------------------------------------------- simulação

class _ClienteFalso:
    """Devolve uma resposta válida montada do esquema, sem rede."""

    def __init__(self, cb: dict, trechos: dict, docs: list, forcar=None):
        self.cb, self.trechos, self.docs, self.forcar = cb, trechos, docs, forcar
        self.chamadas = 0
        self.messages = self

    def resposta_canonica(self) -> dict:
        documentos = {str(d["n"]): {"tipo": self.cb["tipos_doc"][0]["valor"],
                                    "registro": self.cb["tipos_doc"][0]["registro"]} for d in self.docs}
        variaveis = {}
        for vid in VARIAVEIS_DO_COPILOTO:
            spec = self.cb["notas"][vid]
            primeira = spec["opcoes"][0]["valor"]
            notas = {t["id"]: ([primeira] if spec["modo"] == "varios" else primeira) for t in self.trechos.get(vid, [])}
            extras = {}
            for ch in (self.cb.get("extras") or {}).get(vid) or []:
                extras[ch] = "No" if ch == "v4_region_gated" else "simulação"
            variaveis[vid] = {"notas": notas, "extras": extras, "razao": "simulação: primeira nota de cada trecho."}
        return {"documentos": documentos, "variaveis": variaveis}

    def stream(self, **kw):
        self.chamadas += 1
        corpo = self.resposta_canonica()
        if self.forcar:
            corpo = self.forcar(corpo, self.chamadas)
        corpo = para_bruto(corpo, self.cb)

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
    # Ids iguais aos do core.mjs (valores gerados lá em 04/10/2026).
    checar_um("hash8 bate com o JavaScript (ascii)", hash8("a.md\nab") == "6bce0a48")
    checar_um("id_do_hit bate com o JavaScript (unicode)",
              id_do_hit({"file": "s/01.md", "kwic": "…we may experiment with features…"}) == "h:2710ce78")

    try:
        corpus = R.Corpus(corpus_dir) if corpus_dir else None
    except Exception:
        corpus = None
    if corpus:
        servico = "Wikipedia"
        trechos, piso = entradas(servico, corpus)
        docs = piso["docs"]
    else:
        servico = "Serviço X"
        piso = {"docs": [{"n": 1, "titulo": "Privacy Policy", "url": "https://x.example/privacy", "chars": 100,
                          "log_line": "experiment:1", "file": "x/01.md"}],
                "por_variavel": {"V1": [{"termo": "experiment", "kwic": "we run experiments", "file": "x/01.md", "n": 1, "flag": None, "total_no_doc": 1}]}}
        cits = {"V9": [{"id": "c:V9-1", "doc": 1, "file": "x/01.md", "onde": "Seção 2", "verbatim": "we test things"}]}
        trechos = {vid: trechos_da_variavel(vid, piso, cits) for vid in VARIAVEIS_DO_COPILOTO}
        docs = piso["docs"]
    checar_um("V9 herda os trechos da V1 com origem v1",
              any(t["origem"] == "v1" for t in trechos["V9"]) and all(t["id"] in {x["id"] for x in trechos["V9"]} for t in trechos["V1"]))
    checar_um("ids de citação têm o prefixo c:", all(t["id"].startswith("c:") for t in trechos["V9"] if t["origem"] == "modelo"))
    msg = montar_mensagem(servico, cb, trechos, piso)
    checar_um("mensagem traz o serviço, os tipos, as notas possíveis e os ids",
              servico in msg and "Tipos possíveis" in msg and "Notas possíveis" in msg
              and all(t["id"] in msg for t in trechos["V1"]))
    checar_um("mensagem não traz etiqueta de tipo de documento nem nada da passada 1",
              '"role"' not in msg and "[vinculante]" not in msg and "passada 1" not in msg and "codificado em" not in msg)
    esq = esquema(cb)
    checar_um("esquema é compacto e cabe em 1.500 caracteres", len(json.dumps(esq)) < 1500 and "documentos" in esq["properties"])

    falso = _ClienteFalso(cb, trechos, docs)
    canon = falso.resposta_canonica()
    probs, avisos = validar(canon, cb, trechos, docs)
    checar_um("validar aceita a resposta canônica, sem avisos", probs == [] and avisos == [])
    checar_um("normalizar desfaz para_bruto", normalizar(para_bruto(canon, cb), cb) == canon)
    ruim = json.loads(json.dumps(canon)); ruim["documentos"]["1"]["tipo"] = "cookie banner"
    checar_um("validar rejeita tipo de documento fora da lista", any("documento 1" in p for p in validar(ruim, cb, trechos, docs)[0]))
    ruim = json.loads(json.dumps(canon)); ruim["variaveis"]["V1"]["notas"]["h:00000000"] = "3"
    checar_um("validar rejeita id de trecho desconhecido", any("desconhecido" in p for p in validar(ruim, cb, trechos, docs)[0]))
    if trechos["V1"]:
        pid = trechos["V1"][0]["id"]
        ruim = json.loads(json.dumps(canon)); ruim["variaveis"]["V1"]["notas"][pid] = "7"
        checar_um("validar rejeita nota fora das opções", any(pid in p for p in validar(ruim, cb, trechos, docs)[0]))
        ruim = json.loads(json.dumps(canon)); del ruim["variaveis"]["V1"]["notas"][pid]
        p2, a2 = validar(ruim, cb, trechos, docs)
        checar_um("trecho sem nota sugerida é aviso, não erro", p2 == [] and any("sem nota" in a for a in a2))
        ruim = json.loads(json.dumps(canon)); ruim["variaveis"]["V1"]["notas"][pid] = NAO_E_ISSO
        checar_um("x é aceito em qualquer variável", validar(ruim, cb, trechos, docs)[0] == [])
    ruim = json.loads(json.dumps(canon)); ruim["variaveis"]["V4"]["extras"]["v4_region_gated"] = "talvez"
    checar_um("validar rejeita extra fora das opções", any("v4_region_gated" in p for p in validar(ruim, cb, trechos, docs)[0]))
    ruim = json.loads(json.dumps(canon)); ruim["variaveis"]["V4"]["extras"]["v4_region_gated"] = ""
    checar_um("validar exige v4_region_gated", any("obrigatório" in p for p in validar(ruim, cb, trechos, docs)[0]))
    if trechos.get("V2"):
        pid = trechos["V2"][0]["id"]
        bruto = para_bruto(canon, cb)
        checar_um("nota múltipla viaja em valores", any(n["id"] == pid and n["valores"] for v in bruto["variaveis"] if v["vid"] == "V2" for n in v["notas"]))

    if corpus:
        reg = gerar_um(servico, corpus, cb, "modelo-falso", falso)
        checar_um("gerar_um devolve documentos, 9 variáveis, SHAs e uso",
                  set(reg["variaveis"]) == set(VARIAVEIS_DO_COPILOTO) and len(reg["documentos"]) == len(docs)
                  and re.fullmatch(r"[0-9a-f]{12}", reg["prompt_sha"]) and reg["formato"] == FORMATO and "invalida" not in reg)
        checar_um("gerar_um não traz etiqueta role", '"role"' not in json.dumps(reg).replace('"registro"', ""))

        def estragar(corpo, chamada):
            if chamada == 1:
                corpo["documentos"]["1"]["tipo"] = "errado"
            return corpo
        teimoso = _ClienteFalso(cb, trechos, docs, forcar=estragar)
        reg2 = gerar_um(servico, corpus, cb, "modelo-falso", teimoso)
        checar_um("resposta inválida ganha uma segunda tentativa, que passa",
                  teimoso.chamadas == 2 and "invalida" not in reg2 and reg2["geracao"]["tentativas"] == 2)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            idx = escrever_todos(corpus, dest, "modelo-falso", _ClienteFalso(cb, trechos, docs), so=servico)
            checar_um("escrever_todos grava o arquivo, o prompt.md e o index.json",
                      len(idx) == 1 and (dest / "prompt.md").exists() and (dest / "index.json").exists())
            checar_um("prompt.md traz o sistema inteiro, a impressão e o formato",
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
