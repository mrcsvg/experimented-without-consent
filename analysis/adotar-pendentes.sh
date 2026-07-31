#!/usr/bin/env bash
# Adota de uma vez os documentos salvos à mão pelo navegador.
#
# Existe porque a automação de navegador não sai pela VPN da UE — medido: a
# máquina sai em IT, o navegador dirigido por ferramenta sai em US, mesmo IP em
# dois navegadores distintos. Como parte destes documentos varia por região, a
# captura tem de ser feita pelo navegador, à mão, na VPN. Este script cuida de
# tudo depois disso.
#
# Uso:
#   1. VPN da UE ligada. Confirme:  python3 analysis/freeze-sources.py preflight
#   2. Para cada URL de analysis/pendentes.tsv: abra no Chrome, espere carregar,
#      DevTools (⌥⌘I) > Console, cole:
#
#          copy(document.documentElement.outerHTML)
#
#      e no terminal:   pbpaste > ~/Downloads/<apelido>.html
#      (o apelido é a 1ª coluna do .tsv: temu-tos, shein-privacy, x-legal-bases…)
#
#   3. Rode este script. Ele adota o que encontrar e lista o que falta.
#
set -uo pipefail
cd "$(dirname "$0")/.."
TSV="analysis/pendentes.tsv"
FROZEN="${1:-../ethics-in-digita-experimentation/audit/frozen}"
DL="${2:-$HOME/Downloads}"
VANT="${VANTAGEM:-IT}"

ok=0; falta=0
while IFS=$'\t' read -r apelido papel servico url; do
  [ -z "${apelido:-}" ] && continue
  arq="$DL/$apelido.html"
  if [ ! -f "$arq" ]; then
    printf '  falta   %-18s %s\n' "$apelido" "${url:0:64}"
    falta=$((falta+1)); continue
  fi
  if python3 analysis/freeze-sources.py adopt \
       --out-dir "$FROZEN" --url "$url" --file "$arq" \
       --service "$servico" --role "$papel" --vantage "$VANT" >/dev/null 2>&1; then
    printf '  ADOTADO %-18s %s\n' "$apelido" "${url:0:64}"
    ok=$((ok+1))
  else
    # a guarda de espessura recusou: quase sempre é código-fonte em vez do DOM
    printf '  RUIM    %-18s ' "$apelido"
    python3 analysis/freeze-sources.py adopt --out-dir "$FROZEN" --url "$url" \
      --file "$arq" --service "$servico" --role "$papel" --vantage "$VANT" 2>&1 | head -1
    falta=$((falta+1))
  fi
done < "$TSV"

echo
echo "adotados $ok · pendentes $falta"
[ "$falta" -eq 0 ] && python3 analysis/freeze-sources.py status --out-dir "$FROZEN" | tail -3
