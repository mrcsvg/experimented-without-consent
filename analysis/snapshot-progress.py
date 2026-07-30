#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Snapshot do progresso do 2º passe — data e completitude, nunca códigos.

Uso:
    python3 snapshot-progress.py --roster index.html \\
                                 --progress audit/coder2-progress.json \\
                                 --out-dir audit

Lê o estado que o instrumento grava no branch `coder2-data` e emite dois
artefatos: um `PROGRESS.md` rolante e um snapshot datado em `snapshots/`. O
roster de 26 serviços vem de `index.html` (o `const DATA` do instrumento), não
de uma lista repetida aqui — se o frame mudar, o denominador muda junto.

CEGUEIRA. O 2º passe é cego e as codificações ficam retidas até a adjudicação
(README, "What is not here yet"). Este script existe dentro dessa restrição:
a saída é construída campo a campo a partir de escalares derivados — contagens,
booleanos de presença, carimbos de tempo — e em nenhum ponto copia o valor de
um campo do registro. Nem código, nem evidência, nem log de palavras-chave,
nem notas. Se um dia alguém precisar do conteúdo, o lugar é o export do
instrumento, não daqui.

Saída de status:
    0  snapshot novo escrito
    3  nada mudou desde o último snapshot (o chamador pode pular o commit)
"""
import argparse, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

# Espelha filledCount() em index.html — 13 campos centrais por serviço.
CORE = ["v1_code", "v1_register", "v2_framing", "v3_activities", "v3_specific",
        "v3_pricing", "v4_basis", "v5_optout", "v6_optin_beta", "v7_debrief",
        "v8_ethics", "v9_where", "v9_register"]
# Cada código carrega citação verbatim; a cobertura de evidência é o segundo
# eixo de completitude, e não anda junto com o primeiro.
EVIDENCE = ["v1_evidence", "v2_evidence", "v3_evidence", "v4_evidence",
            "v5_evidence", "v7_evidence", "v9_evidence"]

STATUS_DONE, STATUS_PARTIAL, STATUS_EMPTY = "concluído", "parcial", "não iniciado"
# Caminho canônico do estado no branch de dados (o default de api/state.js). O
# script recebe um caminho de checkout, que é volátil; o registrado é este.
CANONICAL_PATH = "audit/coder2-progress.json"


def roster(path):
    """Os 26 serviços designados, na ordem em que o instrumento os apresenta."""
    src = Path(path).read_text(encoding="utf-8")
    m = re.search(r"^const DATA = (\{.*\});$", src, re.M)
    if not m:
        sys.exit(f"não achei o bloco `const DATA = {{...}};` em {path}")
    return json.loads(m.group(1))["order"]


def filled(rec, keys):
    """Um campo conta como preenchido pelo mesmo critério da UI: multi-seleção
    precisa de ao menos um item; o resto precisa ser não-vazio."""
    n = 0
    for k in keys:
        v = rec.get(k)
        if isinstance(v, list):
            n += 1 if v else 0
        elif v not in (None, "", []):
            n += 1
    return n


def iso(ts):
    """`_ts` do instrumento é epoch em ms; devolve ISO-8601 UTC ou None."""
    if not isinstance(ts, (int, float)):
        return None
    return datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat(timespec="seconds")


def measure(order, records):
    rows, unknown = [], sorted(set(records) - set(order))
    for name in order:
        rec = records.get(name) or {}
        core, ev = filled(rec, CORE), filled(rec, EVIDENCE)
        docs = rec.get("docs_read")
        rows.append({
            "service": name,
            "status": STATUS_DONE if rec.get("done") else (STATUS_PARTIAL if core or ev else STATUS_EMPTY),
            "core_filled": core,
            "core_expected": len(CORE),
            "evidence_filled": ev,
            "evidence_expected": len(EVIDENCE),
            "keyword_log": bool(str(rec.get("keyword_log") or "").strip()),
            "docs_read": len(docs) if isinstance(docs, list) else 0,
            "last_edit": iso(rec.get("_ts")),
        })
    n = len(rows)
    tally = lambda s: sum(1 for r in rows if r["status"] == s)
    pct = lambda a, b: round(100 * a / b, 1) if b else 0.0
    core_sum = sum(r["core_filled"] for r in rows)
    ev_sum = sum(r["evidence_filled"] for r in rows)
    return {
        "services": n,
        "concluded": tally(STATUS_DONE),
        "partial": tally(STATUS_PARTIAL),
        "not_started": tally(STATUS_EMPTY),
        "core_fields": {"filled": core_sum, "expected": n * len(CORE),
                        "pct": pct(core_sum, n * len(CORE))},
        "evidence_fields": {"filled": ev_sum, "expected": n * len(EVIDENCE),
                            "pct": pct(ev_sum, n * len(EVIDENCE))},
        "keyword_log": {"present": sum(1 for r in rows if r["keyword_log"]), "expected": n},
        "unrecognised_records": unknown,
    }, rows


def markdown(payload):
    t, rows = payload["totals"], payload["services"]
    src = payload["source"]
    bar = lambda r: "●" if r["status"] == STATUS_DONE else ("◐" if r["status"] == STATUS_PARTIAL else "○")
    out = [
        "# Progresso do 2º passe de codificação",
        "",
        "Gerado automaticamente por `.github/workflows/coding-snapshot.yml`.",
        "**Metadados apenas** — quantos campos estão preenchidos e quando, nunca",
        "o que foi codificado. As codificações ficam retidas até a adjudicação.",
        "",
        f"| Snapshot | `{payload['generated_at']}` |",
        "|---|---|",
        f"| Último autosave do instrumento | `{src['saved_at'] or '—'}` |",
        f"| Serviços concluídos | **{t['concluded']}/{t['services']}** |",
        f"| Em andamento | {t['partial']} |",
        f"| Não iniciados | {t['not_started']} |",
        f"| Campos centrais | {t['core_fields']['filled']}/{t['core_fields']['expected']} ({t['core_fields']['pct']}%) |",
        f"| Campos de evidência | {t['evidence_fields']['filled']}/{t['evidence_fields']['expected']} ({t['evidence_fields']['pct']}%) |",
        f"| Log de palavras-chave | {t['keyword_log']['present']}/{t['keyword_log']['expected']} |",
        "",
        "| | Serviço | Centrais | Evidência | KW | Docs | Última edição |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| {bar(r)} | {r['service']} | {r['core_filled']}/{r['core_expected']} "
            f"| {r['evidence_filled']}/{r['evidence_expected']} "
            f"| {'sim' if r['keyword_log'] else '—'} | {r['docs_read']} "
            f"| {r['last_edit'] or '—'} |"
        )
    out += ["", "● concluído · ◐ em andamento · ○ não iniciado", ""]
    if t["unrecognised_records"]:
        out += ["> **Registros fora do frame:** "
                + ", ".join(f"`{s}`" for s in t["unrecognised_records"])
                + " — nomes que não constam do roster de `index.html`.", ""]
    return "\n".join(out)


def previous(snapdir):
    """O snapshot mais recente já gravado, para decidir se algo mudou."""
    files = sorted(Path(snapdir).glob("*.json"))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roster", required=True, help="index.html do instrumento")
    ap.add_argument("--progress", required=True, help="audit/coder2-progress.json")
    ap.add_argument("--out-dir", required=True, help="diretório audit/ do branch de dados")
    ap.add_argument("--branch", default="coder2-data")
    args = ap.parse_args()

    order = roster(args.roster)
    try:
        state = json.loads(Path(args.progress).read_text(encoding="utf-8"))
    except FileNotFoundError:
        state = {"records": {}, "saved_at": None}
    records = state.get("records") or {}

    totals, rows = measure(order, records)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {"branch": args.branch, "path": CANONICAL_PATH,
                   "saved_at": state.get("saved_at")},
        "totals": totals,
        "services": rows,
    }

    # A série de snapshots só deve registrar progresso real. `generated_at` anda
    # a cada execução, e `saved_at` anda a cada autosave — inclusive os que o app
    # dispara sem que nenhum registro mude. O sinal honesto é `totals`+`services`,
    # onde o `last_edit` de cada serviço já carrega o carimbo da última edição.
    substantive = lambda p: (p.get("totals"), p.get("services"))
    prev = previous(Path(args.out_dir) / "snapshots")
    unchanged = prev is not None and substantive(prev) == substantive(payload)

    md = markdown(payload)
    print(md)
    if unchanged:
        print("\n<!-- sem mudança desde o snapshot anterior -->")
        return 3

    out = Path(args.out_dir)
    (out / "snapshots").mkdir(parents=True, exist_ok=True)
    stamp = payload["generated_at"][:10]
    (out / "snapshots" / f"{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "PROGRESS.md").write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
