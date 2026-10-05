#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exporta o piso de palavras-chave de cada serviço: um JSON por serviço.

    python3 analysis/exportar-piso.py --corpus ../experimented-without-consent-corpus/md \\
        --out ../experimented-without-consent-corpus/assistente/piso
    python3 analysis/exportar-piso.py --corpus ../experimented-without-consent-corpus/md --self-test

O piso é a varredura determinística dos 12 termos do protocolo sobre o texto
congelado (`revisao.varredura` e `revisao.piso`). A página mostra os hits por
variável, com o trecho em volta e a nota de falso positivo quando o termo tem
uma, e preenche o log de palavras-chave com as contagens por documento. Nada
aqui passa por modelo: é busca de texto, dá sempre o mesmo resultado e não
deixa nada de fora.

O QUE NÃO ENTRA: a etiqueta `role` dos documentos. Ela vem da passada 1
(`freeze-sources.py cmd_inventory`), e a página não a mostra por decisão de
03/10/2026. O self-test afirma que a palavra não aparece no arquivo.

O QUE ENTRA DESDE 04/10/2026: o tipo e o registro de cada documento, lidos de
`analysis/tipos-doc.json`. O tipo de um documento (política de privacidade,
termos de uso, aviso de pesquisa separado, central de ajuda, blog) é atributo
do corpus, decidido uma vez, à mão, antes da codificação; não é julgamento do
codificador. A página calcula o registro do teto (V1) e os locais (V9) a partir
dele e não pergunta nada sobre documentos. Documento sem tipo no arquivo
interrompe a exportação: melhor não publicar do que publicar sem.

Sem dependências externas: só a biblioteca padrão.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codebook as C  # noqa: E402
import revisao as R  # noqa: E402

TITULO_MAX = 120
TIPOS_DOC_ARQ = Path(__file__).with_name("tipos-doc.json")


def _exportar_codebook():
    import importlib.util
    spec = importlib.util.spec_from_file_location("exportar_codebook", Path(__file__).with_name("exportar-codebook.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def tipos_doc(arquivo: Path = TIPOS_DOC_ARQ) -> dict[str, dict]:
    """{file: {tipo, registro}} de analysis/tipos-doc.json.

    O tipo tem de ser um dos cinco de TIPOS_DOC (exportar-codebook.py); o
    registro, quando o arquivo não diz, é o padrão do tipo. Tipo desconhecido
    ou registro inválido interrompem: o arquivo é curado à mão e um erro de
    digitação não pode virar metadado publicado.
    """
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    validos = {t["valor"]: t["registro"] for t in _exportar_codebook().TIPOS_DOC}
    saida = {}
    for file, d in (dados.get("documentos") or {}).items():
        tipo = (d or {}).get("tipo")
        if tipo not in validos:
            raise ValueError(f"{arquivo.name}: {file}: tipo inválido {tipo!r} (válidos: {sorted(validos)})")
        registro = d.get("registro") or validos[tipo]
        if registro not in ("binding", "non-binding"):
            raise ValueError(f"{arquivo.name}: {file}: registro inválido {registro!r}")
        saida[file] = {"tipo": tipo, "registro": registro}
    return saida


def titulo_do(texto: str | None) -> str:
    """Primeira linha não vazia do corpo congelado, encurtada."""
    for linha in (texto or "").splitlines():
        t = " ".join(linha.split())
        if t:
            return t if len(t) <= TITULO_MAX else t[:TITULO_MAX - 1].rstrip() + "…"
    return ""


def exportar_um(servico: str, corpus, tipos: dict[str, dict] | None = None) -> dict:
    docs = corpus.docs(servico)
    dossie = R.varredura(servico, corpus)
    por_arquivo = {d["file"]: d for d in dossie}
    por_variavel = R.piso(servico, corpus, dossie=dossie)
    n_do = {d["file"]: d["n"] for d in docs}
    if tipos is None:
        tipos = tipos_doc()

    saida_docs = []
    for d in docs:
        v = por_arquivo.get(d["file"])
        if d["file"] not in tipos:
            raise KeyError(f"{servico}: {d['file']} sem tipo em {TIPOS_DOC_ARQ.name}; rode analysis/tipos-doc.py --check")
        saida_docs.append({
            "n": d["n"], "file": d["file"], "url": d["url"], "chars": d["chars"],
            "titulo": titulo_do(corpus.texto(d)),
            "tipo": tipos[d["file"]]["tipo"],
            "registro": tipos[d["file"]]["registro"],
            "counts": dict(v["counts"]) if v else {},
            "log_line": v["log_line"] if v else "",
            "quarentena": v is None,
        })
    hits = {
        vid: [{"termo": h["termo"], "kwic": h["kwic"], "flag": h["flag"], "file": h["file"],
               "n": n_do.get(h["file"]), "total_no_doc": h["total_no_doc"]} for h in lista]
        for vid, lista in por_variavel.items()
    }
    # Mesmo formato do `coding_flow.Fluxo.log_sugerido`: nome do arquivo e as
    # contagens, uma linha por documento.
    log = "\n".join(f"{Path(d['file']).name}: {d['log_line']}" for d in saida_docs if d["log_line"])
    return {
        "servico": servico,
        "slug": corpus.por_servico[servico]["slug"],
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus_built_at": corpus.index.get("built_at"),
        "corpus_frozen_at": corpus.index.get("frozen_at"),
        "docs": saida_docs,
        "por_variavel": hits,
        "log_sugerido": log,
    }


def escrever_todos(corpus, destino: Path) -> list[dict]:
    destino.mkdir(parents=True, exist_ok=True)
    indice = []
    tipos = tipos_doc()
    for servico in C.SERVICOS:
        d = exportar_um(servico, corpus, tipos=tipos)
        texto = json.dumps(d, ensure_ascii=False, indent=1) + "\n"
        alvo = destino / f"{d['slug']}.json"
        alvo.write_text(texto, encoding="utf-8")
        indice.append({"servico": servico, "slug": d["slug"], "file": alvo.name,
                       "sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
                       "hits": sum(len(v) for v in d["por_variavel"].values())})
    (destino / "index.json").write_text(json.dumps({
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "servicos": indice,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return indice


# ---------------------------------------------------------------- self-test

def _self_test(corpus) -> int:
    falhas = []

    def checar(desc, cond):
        print(f"  {'ok  ' if cond else 'FALHA'} {desc}")
        if not cond:
            falhas.append(desc)

    variaveis_do_piso = {v for vs in R.TERMO_PARA_VARIAVEL.values() for v in vs}
    tipos_validos = {t["valor"]: t["registro"] for t in _exportar_codebook().TIPOS_DOC}
    for servico in ("Wikipedia", "Zalando"):
        d = exportar_um(servico, corpus)
        bruto = json.dumps(d, ensure_ascii=False)
        checar(f"{servico}: mesmo número de documentos que o índice do corpus",
               len(d["docs"]) == len(corpus.docs(servico)))
        checar(f"{servico}: nenhuma etiqueta role no arquivo", '"role"' not in bruto)
        checar(f"{servico}: todo documento traz tipo (um dos cinco) e registro (binding ou non-binding)",
               all(x.get("tipo") in tipos_validos and x.get("registro") in ("binding", "non-binding") for x in d["docs"]))
        checar(f"{servico}: hits só nas variáveis que o piso endereça",
               set(d["por_variavel"]) <= variaveis_do_piso)
        ns = {x["n"] for x in d["docs"]}
        checar(f"{servico}: todo hit tem trecho e aponta para um documento existente",
               all(h["kwic"] and h["n"] in ns for lista in d["por_variavel"].values() for h in lista))
        checar(f"{servico}: todo documento tem título",
               all(x["titulo"] for x in d["docs"]))
        checar(f"{servico}: log sugerido tem uma linha por documento varrido",
               len(d["log_sugerido"].splitlines()) == sum(1 for x in d["docs"] if x["log_line"]))
        checar(f"{servico}: slug é o do corpus", d["slug"] == corpus.por_servico[servico]["slug"])
    z = exportar_um("Zalando", corpus)
    checar("Zalando: os hits de ethics e risk assessment chegam com a nota de falso positivo",
           any(h["termo"] == "ethics" and h["flag"] for h in z["por_variavel"].get("V8", [])))
    checar("título é encurtado em 120 caracteres", len(titulo_do("x" * 300)) <= TITULO_MAX)
    checar("título ignora linhas vazias", titulo_do("\n\n  Privacy  Policy \n") == "Privacy Policy")

    # tipos-doc.json: cobre o corpus inteiro, sem sobras, e recusa o que não é um dos cinco tipos.
    todos = {d["file"] for s in C.SERVICOS for d in corpus.docs(s)}
    tipos = tipos_doc()
    checar("tipos-doc.json cobre exatamente os documentos do corpus (nenhum a mais, nenhum a menos)",
           set(tipos) == todos, )
    checar("tipos-doc.json: 157 documentos", len(tipos) == 157)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        arq = Path(tmp) / "tipos.json"
        arq.write_text(json.dumps({"documentos": {"a.md": {"tipo": "help centre"},
                                                   "b.md": {"tipo": "help centre", "registro": "binding"}}}), encoding="utf-8")
        t = tipos_doc(arq)
        checar("sem registro no arquivo, vale o padrão do tipo", t["a.md"] == {"tipo": "help centre", "registro": "non-binding"})
        checar("registro explícito no arquivo vence o padrão (registro não é hospedagem)", t["b.md"]["registro"] == "binding")
        arq.write_text(json.dumps({"documentos": {"a.md": {"tipo": "cookie banner"}}}), encoding="utf-8")
        try:
            tipos_doc(arq)
            checar("tipo fora dos cinco é recusado", False)
        except ValueError:
            checar("tipo fora dos cinco é recusado", True)
        try:
            exportar_um("Wikipedia", corpus, tipos={})
            checar("documento sem tipo interrompe a exportação", False)
        except KeyError:
            checar("documento sem tipo interrompe a exportação", True)
        idx = escrever_todos(corpus, Path(tmp))
        checar("26 arquivos escritos, com índice", len(idx) == 26 and (Path(tmp) / "index.json").exists())
        checar("nenhum role em nenhum dos 26",
               not any('"role"' in p.read_text(encoding="utf-8") for p in Path(tmp).glob("*.json")))

    print("\n" + ("tudo ok" if not falhas else f"{len(falhas)} falha(s)"))
    return 0 if not falhas else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True, help="pasta md/ do corpus congelado (ou URL)")
    ap.add_argument("--out", type=Path, help="pasta de destino (assistente/piso)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    corpus = R.Corpus(a.corpus)
    if a.self_test:
        return _self_test(corpus)
    if not a.out:
        ap.error("informe --out ou --self-test")
    idx = escrever_todos(corpus, a.out)
    print(f"piso: {len(idx)} serviços, {sum(i['hits'] for i in idx)} hits → {a.out}")
    if corpus.quarentena:
        print(f"  atenção: {len(corpus.quarentena)} documento(s) em quarentena: {corpus.quarentena}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
