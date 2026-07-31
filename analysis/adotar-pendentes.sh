#!/usr/bin/env bash
# Adota tudo que foi salvo pelo navegador, sem você digitar nome nem URL.
#
# A automação de navegador não serve para esta parte: medido, a máquina sai em
# IT com a VPN ligada, mas o navegador sob controle de ferramenta sai em US —
# mesmo IP em dois navegadores distintos. Como parte destes documentos varia
# por região, a captura tem de ser à mão, na VPN. O resto é este script.
#
# Uso:
#   1. VPN da UE ligada:   python3 analysis/freeze-sources.py preflight
#   2. Em cada página (aberta e JÁ CARREGADA), DevTools > Console, cole o
#      conteúdo de analysis/salvar-dom.js. O arquivo cai em ~/Downloads com a
#      URL gravada dentro.
#   3. Rode isto. Quantas vezes quiser, conforme forem chegando.
#
# Só recursos de bash 3.2: o macOS ainda vem com ele, e `mapfile`/`declare -A`
# não existem lá.
set -uo pipefail
cd "$(dirname "$0")/.."
TSV="analysis/pendentes.tsv"
FROZEN="${1:-../ethics-in-digita-experimentation/audit/frozen}"
DL="${2:-$HOME/Downloads}"
VANT="${VANTAGEM:-IT}"
VISTAS="$(mktemp)"; trap 'rm -f "$VISTAS"' EXIT

ok=0; ruim=0
# O vínculo arquivo->documento vem do marcador dentro do arquivo, não do nome:
# o nome quem decide é o navegador, e casar por nome erra em silêncio.
for arq in $(grep -rl "FREEZE-SOURCE" "$DL" --include="*.html" 2>/dev/null | sort); do
  url=$(sed -n 's/.*<!-- FREEZE-SOURCE \(.*\) -->.*/\1/p' "$arq" | head -1)
  [ -z "$url" ] && continue
  linha=$(awk -F'\t' -v u="$url" '$4==u {print; exit}' "$TSV")
  if [ -z "$linha" ]; then
    printf '  ?       %s\n          não está em pendentes.tsv — pulando\n' "${url:0:78}"
    ruim=$((ruim+1)); continue
  fi
  papel=$(printf '%s' "$linha" | cut -f2)
  servico=$(printf '%s' "$linha" | cut -f3)
  printf '%s\n' "$url" >> "$VISTAS"
  if saida=$(python3 analysis/freeze-sources.py adopt --out-dir "$FROZEN" \
               --file "$arq" --service "$servico" --role "$papel" --vantage "$VANT" 2>&1); then
    printf '  ADOTADO %-62s %s\n' "${url:0:62}" \
      "$(printf '%s' "$saida" | sed -n 's/.*  \([0-9][0-9]*\) chars.*/\1 ch/p' | head -1)"
    ok=$((ok+1))
  else
    printf '  RUIM    %s\n          %s\n' "${url:0:70}" "$(printf '%s' "$saida" | head -1)"
    ruim=$((ruim+1))
  fi
done

echo
while IFS=$'\t' read -r apelido papel servico url; do
  [ -z "${apelido:-}" ] && continue
  grep -qxF "$url" "$VISTAS" 2>/dev/null || printf '  falta   %-16s %s\n' "$apelido" "${url:0:70}"
done < "$TSV"

echo
echo "adotados $ok · com problema $ruim"
python3 analysis/freeze-sources.py status --out-dir "$FROZEN" | tail -3
