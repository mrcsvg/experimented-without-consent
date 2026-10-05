#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""O tipo de cada documento do corpus: rascunho, tabela e conferência.

    python3 analysis/tipos-doc.py --rascunho            # escreve analysis/tipos-doc.json (recusa sobrescrever)
    python3 analysis/tipos-doc.py --rascunho --forcar   # reescreve o rascunho (perde o que foi conferido à mão)
    python3 analysis/tipos-doc.py --tabela              # Markdown por serviço, com a coluna "conferir"
    python3 analysis/tipos-doc.py --tabela --so-conferir
    python3 analysis/tipos-doc.py --check               # cobre o corpus inteiro? tipos válidos?
    python3 analysis/tipos-doc.py --self-test

POR QUE ESTE ARQUIVO EXISTE. Decisão de 04/10/2026: o tipo de um documento
(política de privacidade, termos de uso, aviso de pesquisa separado, central de
ajuda, blog) é atributo do corpus, não julgamento do codificador. A página do
2º codificador não pergunta mais o tipo; ela o lê do piso, e o piso o lê de
`analysis/tipos-doc.json`. Este script escreve o rascunho desse arquivo e
aponta o que precisa de conferência humana.

TRÊS SINAIS, e nenhum decide sozinho:
  url       padrões na URL e no título congelado (privacy, terms, help, blog...)
  copiloto  o tipo que o modelo sugeriu lendo o texto (assistente/copiloto/<slug>.json)
  captura   a etiqueta binding/non-binding dada na captura (md/index.json, `role`);
            existe em 55 dos 157 documentos
Regra do rascunho: url e copiloto concordam, fica o tipo, sem conferir. Só o
copiloto fala, fica o dele, e conferir = a captura não corrobora. Os dois
discordam, fica o do copiloto (ele leu o texto) e conferir = sim. A captura
contradizendo o registro do tipo escolhido sempre pede conferência.

O registro sai do tipo (TIPOS_DOC do exportar-codebook.py). "Registro não é
hospedagem": o Privacy Notice da Amazon servido sob /help/ é vinculante porque
é uma política de privacidade, e é esse tipo que ele recebe. Um registro
diferente do padrão do tipo, se um dia for preciso, se declara no próprio
arquivo, campo `registro`.

Sem dependências externas: só a biblioteca padrão.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CORPUS = RAIZ.parent / "experimented-without-consent-corpus"
ARQ = Path(__file__).with_name("tipos-doc.json")


def _exportar_codebook():
    spec = importlib.util.spec_from_file_location("exportar_codebook", Path(__file__).with_name("exportar-codebook.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def registro_por_tipo() -> dict[str, str]:
    return {t["valor"]: t["registro"] for t in _exportar_codebook().TIPOS_DOC}


# Ordem = prioridade. "privacy" antes de "help": a política de privacidade
# publicada dentro da central de ajuda continua política de privacidade.
PADROES = [
    ("privacy policy", r"privacy|privacidade|datenschutz|confidentialit|cookie|data[-_ ]policy|legal[-_ ]bas|lawful[-_ ]bas|personal[-_ ]data|data[-_ ]protection|gdpr|informativa"),
    ("ToS/conditions", r"\bterms?\b|conditions|\btos\b|eula|user[-_ ]agreement|legal[-_ ]agreement|termos|condiciones|\bagb\b|nutzungsbedingungen"),
    ("help centre", r"\bhelp\b|support|\bfaq\b|/hc/|customer[-_ ]service|ajuda|service[-_ ]cent|helpcenter|help-center"),
    ("blog/PR/site de pesquisa", r"\bblog|newsroom|\bnews\b|\bpress\b|engineering|medium\.com|about\.|research|transparency|\btech\b|stories|insights|science|\bai\b|machine[-_ ]learning"),
]


def tipo_pela_url(url: str, titulo: str = "") -> str | None:
    texto = f"{url} {titulo}".lower()
    for tipo, rx in PADROES:
        if re.search(rx, texto):
            return tipo
    return None


def decidir(pela_url: str | None, do_copiloto: str | None, captura: str | None, registro_de: dict[str, str]) -> tuple[str, bool, str]:
    """(tipo, conferir, motivo) a partir dos três sinais."""
    if pela_url and do_copiloto and pela_url == do_copiloto:
        tipo, conferir, motivo = pela_url, False, "url e copiloto concordam"
    elif do_copiloto and not pela_url:
        tipo = do_copiloto
        if captura is None:
            conferir, motivo = True, "só o copiloto fala; sem etiqueta da captura"
        elif captura == registro_de[tipo]:
            conferir, motivo = False, "só o copiloto fala; a captura corrobora o registro"
        else:
            conferir, motivo = True, "só o copiloto fala"
    elif do_copiloto and pela_url:
        tipo, conferir, motivo = do_copiloto, True, f"url diz {pela_url}; copiloto diz {do_copiloto}"
    elif pela_url:
        tipo, conferir, motivo = pela_url, True, "só a url fala; sem copiloto"
    else:
        tipo, conferir, motivo = "help centre", True, "nenhum sinal"
    if captura and captura != registro_de[tipo]:
        conferir = True
        motivo += f"; a captura diz {captura}"
    return tipo, conferir, motivo


def _ler_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def rascunho(corpus_dir: Path = CORPUS) -> dict:
    registro_de = registro_por_tipo()
    idx = _ler_json(corpus_dir / "md" / "index.json")
    docs_out: dict[str, dict] = {}
    for s in idx["services"]:
        slug = s["slug"]
        piso_p = corpus_dir / "assistente" / "piso" / f"{slug}.json"
        titulos = {d["file"]: d["titulo"] for d in _ler_json(piso_p)["docs"]} if piso_p.exists() else {}
        cop_p = corpus_dir / "assistente" / "copiloto" / f"{slug}.json"
        sug = (_ler_json(cop_p).get("documentos") or {}) if cop_p.exists() else {}
        for d in s["docs"]:
            titulo = titulos.get(d["file"], "")
            pela_url = tipo_pela_url(d["url"], titulo)
            do_copiloto = (sug.get(str(d["n"])) or {}).get("tipo")
            if do_copiloto not in registro_de:
                do_copiloto = None
            captura = d.get("role") if d.get("role") in ("binding", "non-binding") else None
            tipo, conferir, motivo = decidir(pela_url, do_copiloto, captura, registro_de)
            docs_out[d["file"]] = {
                "servico": s["name"], "n": d["n"], "titulo": titulo, "url": d["url"],
                "tipo": tipo, "conferir": conferir, "motivo": motivo,
                "sinais": {"url": pela_url, "copiloto": do_copiloto, "captura": captura},
            }
    return {
        "o_que_e": "Tipo de cada documento do corpus congelado: metadado do corpus, decidido à mão (decisão de 04/10/2026). "
                   "O exportar-piso.py publica `tipo` e `registro` por documento; a página do 2º codificador lê de lá e não pergunta.",
        "rascunho_em": date.today().isoformat(),
        "conferido_em": None,
        "registro": "sai do tipo (exportar-codebook.py: TIPOS_DOC); para fugir ao padrão, declare `registro` no documento",
        "documentos": docs_out,
    }


def _ordem(dados: dict, corpus_dir: Path = CORPUS) -> list[str]:
    idx = _ler_json(corpus_dir / "md" / "index.json")
    nomes = [s["name"] for s in idx["services"]]
    return sorted(dados["documentos"], key=lambda f: (nomes.index(dados["documentos"][f]["servico"]) if dados["documentos"][f]["servico"] in nomes else 99,
                                                      dados["documentos"][f]["n"]))


def tabela(dados: dict, so_conferir: bool = False, corpus_dir: Path = CORPUS) -> str:
    def curta(url: str) -> str:
        u = re.sub(r"^https?://(www\.)?", "", url)
        return u if len(u) <= 70 else u[:69] + "…"
    linhas = ["| serviço | n | título | URL | tipo | url · copiloto · captura | conferir |", "|---|---|---|---|---|---|---|"]
    for f in _ordem(dados, corpus_dir):
        d = dados["documentos"][f]
        if so_conferir and not d.get("conferir"):
            continue
        s = d.get("sinais", {})
        sinais = " · ".join(str(s.get(k) or "–") for k in ("url", "copiloto", "captura"))
        linhas.append(f"| {d['servico']} | {d['n']} | {d['titulo'][:60]} | {curta(d['url'])} | **{d['tipo']}** | {sinais} | {'SIM: ' + d.get('motivo', '') if d.get('conferir') else ''} |")
    return "\n".join(linhas)


def checar(dados: dict, corpus_dir: Path = CORPUS) -> int:
    registro_de = registro_por_tipo()
    idx = _ler_json(corpus_dir / "md" / "index.json")
    todos = {d["file"] for s in idx["services"] for d in s["docs"]}
    docs = dados["documentos"]
    problemas = []
    faltam = sorted(todos - set(docs))
    sobram = sorted(set(docs) - todos)
    if faltam:
        problemas.append(f"{len(faltam)} documento(s) do corpus sem tipo: {faltam[:5]}")
    if sobram:
        problemas.append(f"{len(sobram)} entrada(s) que não estão no corpus: {sobram[:5]}")
    for f, d in docs.items():
        if d.get("tipo") not in registro_de:
            problemas.append(f"{f}: tipo inválido {d.get('tipo')!r}")
        if d.get("registro") not in (None, "binding", "non-binding"):
            problemas.append(f"{f}: registro inválido {d.get('registro')!r}")
    pend = [f for f, d in docs.items() if d.get("conferir")]
    por_tipo: dict[str, int] = {}
    for d in docs.values():
        por_tipo[d.get("tipo")] = por_tipo.get(d.get("tipo"), 0) + 1
    print(f"{len(docs)} documentos · {len(pend)} a conferir · conferido em {dados.get('conferido_em') or 'ainda não'}")
    for t, n in sorted(por_tipo.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3d}  {t}")
    for p in problemas:
        print(f"  PROBLEMA: {p}")
    return 0 if not problemas else 1


def _self_test() -> int:
    falhas = []

    def ok(desc, cond):
        print(f"  {'ok  ' if cond else 'FALHA'} {desc}")
        if not cond:
            falhas.append(desc)

    ok("privacy dentro da central de ajuda é privacy policy", tipo_pela_url("https://help.instagram.com/519522125107875", "Privacy Policy") == "privacy policy")
    ok("terms.alicdn.com/legal-agreement é ToS", tipo_pela_url("https://terms.alicdn.com/legal-agreement/terms/suit_bu1_aliexpress/x.html") == "ToS/conditions")
    ok("cookie notice é privacy policy", tipo_pela_url("https://x.com/en/cookies", "How X uses cookies") == "privacy policy")
    ok("central de ajuda", tipo_pela_url("https://support.google.com/youtube/answer/1", "Experiments on YouTube") == "help centre")
    ok("blog de engenharia", tipo_pela_url("https://engineering.linkedin.com/blog/x", "A/B testing at scale") == "blog/PR/site de pesquisa")
    ok("sem sinal devolve None", tipo_pela_url("https://example.com/xyz", "Hello") is None)
    reg = {"privacy policy": "binding", "ToS/conditions": "binding", "research notice separado": "non-binding",
           "help centre": "non-binding", "blog/PR/site de pesquisa": "non-binding"}
    ok("concordância não pede conferência", decidir("help centre", "help centre", None, reg) == ("help centre", False, "url e copiloto concordam"))
    ok("só copiloto, captura corrobora: sem conferir", decidir(None, "privacy policy", "binding", reg)[:2] == ("privacy policy", False))
    ok("só copiloto, sem captura: conferir", decidir(None, "privacy policy", None, reg)[:2] == ("privacy policy", True))
    ok("discordância fica com o copiloto e pede conferência", decidir("help centre", "privacy policy", None, reg)[:2] == ("privacy policy", True))
    ok("captura contradizendo o registro pede conferência mesmo com concordância",
       decidir("help centre", "help centre", "binding", reg)[1] is True)
    ok("nenhum sinal: help centre, conferir", decidir(None, None, None, reg)[:2] == ("help centre", True))
    print("\n" + ("tudo ok" if not falhas else f"{len(falhas)} falha(s)"))
    return 0 if not falhas else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", type=Path, default=CORPUS, help="raiz do repositório do corpus (com md/ e assistente/)")
    ap.add_argument("--arquivo", type=Path, default=ARQ)
    ap.add_argument("--rascunho", action="store_true")
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--tabela", action="store_true")
    ap.add_argument("--so-conferir", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return _self_test()
    if a.rascunho:
        if a.arquivo.exists() and not a.forcar:
            print(f"{a.arquivo} já existe; use --forcar para reescrever (perde o que foi conferido à mão)")
            return 1
        dados = rascunho(a.corpus)
        a.arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        n = sum(1 for d in dados["documentos"].values() if d["conferir"])
        print(f"rascunho: {len(dados['documentos'])} documentos, {n} a conferir → {a.arquivo}")
        return 0
    if not a.arquivo.exists():
        print(f"falta {a.arquivo}; rode --rascunho")
        return 1
    dados = _ler_json(a.arquivo)
    if a.tabela:
        print(tabela(dados, a.so_conferir, a.corpus))
        return 0
    if a.check:
        return checar(dados, a.corpus)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
