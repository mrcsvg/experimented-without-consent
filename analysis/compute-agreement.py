#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Concordância entre avaliadores — auditoria de disclosures (codebook v2).

Uso:
    python3 compute-agreement.py coded-data.json coded-data-coder2.json
    python3 compute-agreement.py --self-test

Entrada 1: passe primário (26 registros). Entrada 2: export do instrumento do
2º avaliador (qualquer N; alinha por `service`, prefixo-match no nome curto).

Política estatística (validada com o 2º avaliador em 2026-07-22):
- Variáveis degeneradas/quase-degeneradas no passe 1 (v7, v8; v5): concordância
  percentual + tabela de contingência. κ é reportado quando definido, mas a
  estatística citável nessas é a percentual + o log de palavras-chave.
- v1_code (ordinal 0–3): κ ponderado (pesos lineares) além do κ simples.
- Multi-seleção (v2_framing, v4_basis, v9_where): Jaccard médio + concordância
  por categoria.
- v4_region_gated: FORA DO κ (decisão de 02/10/2026, tomada antes de existir
  qualquer codificação da passada 2). A passada 1 leu os documentos ao vivo, de fora
  da UE; a passada 2 lê o corpus capturado de dentro da UE. Pelas definições do
  codebook, quem lê só a captura da UE vê se a tabela de bases está presente, mas
  não se ela some para quem acessa de fora: presente é No, ausente é
  not-verifiable, e Yes fica inalcançável. Qualquer discordância seria de vantagem
  de captura, não de julgamento, e entraria no κ como se fosse desacordo entre
  codificadores. O campo sai do κ e da lista de adjudicação, e é reportado à parte
  como comparação das duas vantagens (`secao_vantagem`).

Saída: tabela por variável + lista de divergências para a adjudicação
(que acontece DEPOIS deste cálculo, nunca antes).
"""
import json, sys, unicodedata
from collections import Counter

CAT_VARS = ["v1_code", "v1_register", "v3_activities", "v3_specific", "v3_pricing",
            "v5_optout", "v6_optin_beta", "v7_debrief", "v8_ethics", "v9_register"]
# Campos codificados pelas duas passadas mas fora da concordância, com o motivo.
# Ver a política no topo deste arquivo; a decisão é anterior a qualquer dado da
# passada 2, e é isso que a separa de escolher variável depois de ver o resultado.
FORA_DO_KAPPA = {"v4_region_gated": "vantagem de captura diferente entre as passadas "
                                    "(decisão de 02/10/2026, antes da passada 2)"}
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

def secao_vantagem(common, p1, p2):
    """v4_region_gated lado a lado: comparação de vantagens, não concordância.

    Nada daqui entra na lista de adjudicação. Uma linha (Yes, No) não é erro de
    ninguém: é a tabela que some para quem lê de fora da UE e aparece na captura
    feita de dentro, ou seja, o próprio gating observado dos dois lados.
    """
    var = "v4_region_gated"
    linhas = [(s, norm(p1[s].get(var)), norm(p2[s].get(var))) for s in sorted(common)]
    linhas = [(s, a, b) for s, a, b in linhas if a is not None or b is not None]
    print(f"\n{var}: FORA DO κ · {FORA_DO_KAPPA[var]}")
    print("  passe 1 = documentos ao vivo, de fora da UE · coder 2 = corpus capturado na UE")
    if not linhas:
        print("  sem pares")
        return linhas
    leitura = {("yes", "no"): "a tabela some fora da UE e aparece na captura da UE: "
                              "o gating, visto dos dois lados",
               ("no", "no"): "tabela visível nas duas vantagens"}
    for (a, b), n in sorted(Counter((a, b) for _, a, b in linhas).items(),
                            key=lambda x: (-x[1], str(x[0]))):
        nota = leitura.get((a, b), "")
        if not nota and b and "not-verifiable" in b:
            nota = "tabela ausente até na captura da UE: conferir o documento congelado"
        print(f"  {n:>2}× passe1={a!s:<6} coder2={b!s:<26} {nota}")
    return linhas


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

    secao_vantagem(common, p1, p2)

    if diverg:
        print(f"\nDIVERGÊNCIAS PARA ADJUDICAÇÃO ({len(diverg)}):")
        for s, var, a, b in sorted(diverg):
            print(f"  {s:16} {var:16} passe1={a!r:30} coder2={b!r}")
    else:
        print("\nNenhuma divergência nos pares codificados.")

def _self_test():
    """Prende a decisão de 02/10: region_gated fora do κ e fora da adjudicação."""
    import contextlib, io, os, tempfile
    base = {"v1_code": 3, "v1_register": "binding", "v3_activities": True,
            "v3_specific": False, "v3_pricing": False, "v5_optout": "GDPR-objection-only",
            "v6_optin_beta": False, "v7_debrief": False, "v8_ethics": False,
            "v9_register": "both", "v2_framing": ["research"], "v4_basis": ["consent"],
            "v9_where": ["privacy policy"]}
    p1 = [dict(base, service="Alfa (Alfa Ltd)", v4_region_gated=True),
          dict(base, service="Beta", v4_region_gated=False),
          dict(base, service="Gama", v4_region_gated=True, v1_code=2)]
    p2 = [dict(base, service="Alfa", v4_region_gated="No"),
          dict(base, service="Beta", v4_region_gated="No"),
          dict(base, service="Gama", v4_region_gated="not-verifiable (vantage)")]
    falhas = []

    def checar(desc, cond):
        print(("  ok    " if cond else "  FALHA ") + desc)
        if not cond:
            falhas.append(desc)

    with tempfile.TemporaryDirectory() as tmp:
        f1, f2 = os.path.join(tmp, "p1.json"), os.path.join(tmp, "p2.json")
        json.dump(p1, open(f1, "w")); json.dump(p2, open(f2, "w"))
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            main(f1, f2)
    out = saida.getvalue()
    tabela_kappa = out.split("v2_framing")[0]
    adjudicacao = out.split("DIVERGÊNCIAS PARA ADJUDICAÇÃO")[-1] if "DIVERGÊNCIAS" in out else ""
    checar("v4_region_gated não tem linha na tabela de κ", "v4_region_gated" not in tabela_kappa)
    checar("as outras variáveis continuam com κ", "v1_code" in tabela_kappa
           and "κ ponderado" in tabela_kappa)
    checar("v4_region_gated aparece na seção de vantagem, com o motivo",
           "v4_region_gated: FORA DO κ" in out and "antes da passada 2" in out)
    checar("(Yes, No) é lido como gating observado dos dois lados",
           "o gating, visto dos dois lados" in out)
    checar("not-verifiable na captura da UE pede conferência do documento",
           "conferir o documento congelado" in out)
    checar("nenhuma linha de region_gated vai para a adjudicação",
           "v4_region_gated" not in adjudicacao)
    checar("a divergência real (V1 do Gama) continua indo para a adjudicação",
           "v1_code" in adjudicacao and "gama" in adjudicacao)
    print(f"\n{'FALHOU: ' + str(len(falhas)) if falhas else 'tudo ok'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(_self_test())
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
