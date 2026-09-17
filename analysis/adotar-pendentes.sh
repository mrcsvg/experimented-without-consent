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
  # A página pode ter redirecionado — a Booking acrescenta ?label=…, a Meta
  # acrescenta parâmetros —, e aí a URL gravada no arquivo não é a da lista.
  # Casa então sem query, fragmento e barra final, e só se sobrar UMA linha: dois
  # candidatos é ambiguidade, e ambiguidade não se resolve em silêncio.
  if [ -z "$linha" ]; then
    linha=$(awk -F'\t' -v u="$url" '
      function base(s,   host, resto) {
        sub(/[?#].*$/, "", s); sub(/^https?:\/\//, "", s); sub(/\/$/, "", s)
        # Segmento de idioma no começo do caminho (/en-gb/, /pt/) também sai: a
        # Meta e o Google servem o mesmo documento em caminhos por idioma, e o
        # corpus é em inglês, então a URL capturada carrega o idioma que a da
        # lista não tem.
        if (s ~ /^[^\/]+\/[a-z][a-z](-[a-z][a-z])?(\/|$)/) {
          host = substr(s, 1, index(s, "/") - 1); resto = substr(s, index(s, "/") + 1)
          sub(/^[a-z][a-z](-[a-z][a-z])?(\/|$)/, "", resto)
          s = host "/" resto
        }
        return s
      }
      base($4) == base(u) { n++; l = $0 }
      END { if (n == 1) print l }' "$TSV")
  fi
  if [ -z "$linha" ]; then
    printf '  ?       %s\n          não casa com pendentes.tsv — se redirecionou para outro caminho, adote com --url\n' "${url:0:78}"
    ruim=$((ruim+1)); continue
  fi
  papel=$(printf '%s' "$linha" | cut -f2)
  servico=$(printf '%s' "$linha" | cut -f3)
  # O manifesto guarda a URL da lista, que é a chave do inventário: gravar a URL
  # redirecionada deixaria a entrada com erro intacta e o documento órfão. O
  # redirecionamento fica registrado na nota, que é procedência.
  alvo=$(printf '%s' "$linha" | cut -f4)
  # A nota é procedência e vai para o manifesto. Sobrescreva com NOTA= quando a
  # captura não foi um humano salvando à mão — a diferença importa, porque o
  # navegador sob automação já saiu por outra vantagem que a da máquina.
  nota="${NOTA:-salvo pelo navegador na VPN da UE}"
  # Pode diferir por redirecionamento do site ou por parâmetro acrescentado na
  # captura (as páginas da Meta respondem no idioma do navegador, e o corpus é
  # em inglês). Em qualquer dos casos, o que vale registrar é a URL de fato lida.
  [ "$alvo" != "$url" ] && nota="$nota; URL capturada: $url"
  printf '%s\n' "$alvo" >> "$VISTAS"
  if saida=$(python3 analysis/freeze-sources.py adopt --out-dir "$FROZEN" \
               --file "$arq" --url "$alvo" --service "$servico" --role "$papel" \
               --vantage "$VANT" --note "$nota" 2>&1); then
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
