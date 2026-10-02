#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Concordância entre avaliadores — auditoria de disclosures (codebook v2).

Uso:
    python3 compute-agreement.py coded-data.json coded-data-coder2.json

Entrada 1: passe primário (26 registros). Entrada 2: export do instrumento do
2º avaliador (qualquer N; alinha por `service`, prefixo-match no nome curto).

Política estatística (validada com o 2º avaliador em 2026-07-22):
- Variáveis degeneradas/quase-degeneradas no passe 1 (v7, v8; v5): concordância
  percentual + tabela de contingência. κ é reportado quando definido, mas a
  estatística citável nessas é a percentual + o log de palavras-chave.
- v1_code (ordinal 0–3): κ ponderado (pesos lineares) além do κ simples.
- Multi-seleção (v2_framing, v4_basis, v9_where): Jaccard médio + concordância
  por categoria.
- v4_region_gated: "not-verifiable (vantage)" do coder 2 é excluído do pareamento
  (contado à parte) — vantagem BR não enxerga gating; não é discordância.

Saída: tabela por variável + lista de divergências para a adjudicação
(que acontece DEPOIS deste cálculo, nunca antes).
"""
import json, sys, unicodedata
from collections import Counter

CAT_VARS = ["v1_code", "v1_register", "v3_activities", "v3_specific", "v3_pricing",
            "v4_region_gated", "v5_optout", "v6_optin_beta", "v7_debrief",
            "v8_ethics", "v9_register"]
MULTI_VARS = ["v2_framing", "v4_basis", "v9_where"]
DEGENERATE_NOTE = {"v7_debrief": "degenerada no passe 1 (26×No) — citar % + keyword log",
                   "v8_ethics": "degenerada no passe 1 (26×No) — citar % + keyword log",
                   "v5_optout": "quase-degenerada no passe 1 (25/1) — citar % + keyword log"}

def norm(v):
    """Normaliza representações entre os dois passes (bool/str/num)."""
    if v is None: return None
    if isinstance(v, bool): return "yes" if v else "no"
    if isinstance(v, (int, float)): return str(int(v))
    s = unicodedata.normalize("NFKC", str(v)).strip().lower()
    if s in ("", "—", "-"): return None
    if s in ("true", "yes", "y", "sim"): return "yes"
    if s in ("false", "no", "n", "não", "nao"): return "no"
    return s

def norm_multi(v):
    if v is None: return set()
    if isinstance(v, str):
        parts = [p.strip() for p in v.replace(";", ",").split(",")]
    else:
        parts = list(v)
    return {norm(p) for p in parts if norm(p)}

def short(name):  # "Google Play (Google Ireland...)" -> "google play"
    return norm(name.split("(")[0])

def cohens_kappa(pairs):
    """(κ ou None se indefinido, Po, Pe). pairs = [(a,b)] já sem None."""
    n = len(pairs)
    if n == 0: return None, None, None
    po = sum(1 for a, b in pairs if a == b) / n
    ma, mb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum((ma[c] / n) * (mb[c] / n) for c in set(ma) | set(mb))
    if abs(1 - pe) < 1e-12: return None, po, pe          # degenerado: 0/0
    return (po - pe) / (1 - pe), po, pe

def weighted_kappa(pairs, levels):
    """κ ponderado linear para ordinal; None se indefinido."""
    n = len(pairs)
    if n == 0: return None
    L = {lv: i for i, lv in enumerate(levels)}
    if not all(a in L and b in L for a, b in pairs): return None
    k = len(levels) - 1
    w = lambda a, b: 1 - abs(L[a] - L[b]) / k
    po = sum(w(a, b) for a, b in pairs) / n
    ma, mb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(w(x, y) * (ma[x] / n) * (mb[y] / n) for x in L for y in L)
    if abs(1 - pe) < 1e-12: return None
    return (po - pe) / (1 - pe)

def main(f1, f2):
    p1 = {short(r["service"]): r for r in json.load(open(f1))}
    p2 = {short(r["service"]): r for r in json.load(open(f2))}
    common = [s for s in p2 if s in p1 and p2[s]]
    if not common:
        sys.exit("Nenhum serviço em comum entre os dois arquivos.")
    print(f"Serviços pareados: {len(common)} — {', '.join(sorted(common))}\n")

    diverg = []
    print(f"{'variável':18} {'N':>3} {'%conc':>6} {'κ':>7}  nota")
    print("-" * 78)
    for var in CAT_VARS:
        pairs, excl = [], 0
        for s in common:
            a, b = norm(p1[s].get(var)), norm(p2[s].get(var))
            if var == "v4_region_gated" and b and "not-verifiable" in b:
                excl += 1; continue
            if a is None or b is None: continue
            pairs.append((a, b))
            if a != b: diverg.append((s, var, a, b))
        if not pairs:
            print(f"{var:18} {'0':>3} {'—':>6} {'—':>7}  sem pares codificados"
                  + (f" ({excl} not-verifiable)" if excl else ""))
            continue
        kap, po, pe = cohens_kappa(pairs)
        note = DEGENERATE_NOTE.get(var, "")
        if kap is None and po is not None:
            note = (note + " · κ indefinido (Pe=1)").strip(" ·")
        if var == "v1_code":
            wk = weighted_kappa(pairs, ["0", "1", "2", "3"])
            note = (note + f" · κ ponderado linear = "
                    + (f"{wk:+.3f}" if wk is not None else "indefinido")).strip(" ·")
        if excl: note = (note + f" · {excl} not-verifiable excluídos").strip(" ·")
        print(f"{var:18} {len(pairs):>3} {po*100:>5.1f}% "
              f"{(f'{kap:+.3f}' if kap is not None else '  n/d'):>7}  {note}")

    print()
    for var in MULTI_VARS:
        pairs = [(norm_multi(p1[s].get(var)), norm_multi(p2[s].get(var)))
                 for s in common if p1[s].get(var) is not None and p2[s].get(var) is not None]
        pairs = [(a, b) for a, b in pairs if a or b]
        if not pairs:
            print(f"{var:18}   0 pares"); continue
        jac = sum(len(a & b) / len(a | b) for a, b in pairs) / len(pairs)
        cats = set().union(*(a | b for a, b in pairs))
        percat = {c: sum(((c in a) == (c in b)) for a, b in pairs) / len(pairs) for c in sorted(cats)}
        print(f"{var:18} {len(pairs):>3} pares · Jaccard médio = {jac:.3f}")
        for c, v in percat.items():
            print(f"{'':22}{c:<38} {v*100:5.1f}% conc.")
        for s in common:
            if p1[s].get(var) is None or p2[s].get(var) is None:
                continue  # mesmo filtro dos pares: só diverge quem ambos codificaram
            a, b = norm_multi(p1[s].get(var)), norm_multi(p2[s].get(var))
            if (a or b) and a != b:
                diverg.append((s, var, "|".join(sorted(a)) or "∅", "|".join(sorted(b)) or "∅"))

    if diverg:
        print(f"\nDIVERGÊNCIAS PARA ADJUDICAÇÃO ({len(diverg)}):")
        for s, var, a, b in sorted(diverg):
            print(f"  {s:16} {var:16} passe1={a!r:30} coder2={b!r}")
    else:
        print("\nNenhuma divergência nos pares codificados.")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
