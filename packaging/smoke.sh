#!/bin/sh
# Prova un pacchetto GIA' costruito su macOS: lo scompatta in una cartella temporanea CON SPAZI, lancia `--smoke`
# (server locale con dati temporanei, nessuna rete, nessuna finestra) e controlla che il codice di uscita sia 0.
# Uso: packaging/smoke.sh <file .zip>
set -e
PKG="$1"
[ -n "$PKG" ] && [ -f "$PKG" ] || { echo "Uso: $0 <pacchetto>"; exit 2; }
PKG="$(cd "$(dirname "$PKG")" && pwd)/$(basename "$PKG")"
T="$(mktemp -d "${TMPDIR:-/tmp}/jobshunter smoke.XXXXXX")"
trap 'rm -rf "${T:?}"' EXIT
case "$PKG" in
  *.zip)
    ditto -x -k "$PKG" "$T" 2>/dev/null || unzip -q "$PKG" -d "$T"
    BIN="$T/JobsHunter.app/Contents/MacOS/JobsHunter" ;;
  *) echo "Formato non riconosciuto: $PKG"; exit 2 ;;
esac
[ -x "$BIN" ] || { echo "Eseguibile non trovato dentro $PKG"; exit 1; }
"$BIN" --smoke --smoke-log "$T/smoke.log"
echo "Test di fumo riuscito: $PKG"
