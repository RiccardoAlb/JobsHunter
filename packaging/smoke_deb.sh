#!/bin/sh
# Test di fumo di un .deb: lo INSTALLA con apt, lancia `jobshunter --smoke`, controlla i file e poi lo toglie con `apt remove`.
# Installa un pacchetto vero sul sistema: si lancia solo su un runner o in un contenitore usa e getta (CI=true), oppure a mano con --yes.
# Uso: packaging/smoke_deb.sh [--yes] <jobshunter_<versione>_<arch>.deb>
set -e
YES=0
if [ "$1" = "--yes" ]; then YES=1; shift; fi
DEB="$1"
[ -n "$DEB" ] && [ -f "$DEB" ] || { echo "Uso: $0 [--yes] <pacchetto.deb>"; exit 2; }
if [ "$YES" != 1 ] && [ "${CI:-}" != "true" ]; then
  echo "Questo script installa e poi rimuove un pacchetto con apt: lancialo in CI o con --yes su una macchina usa e getta."
  exit 2
fi
DEB="$(cd "$(dirname "$DEB")" && pwd)/$(basename "$DEB")"
SUDO=""
if [ "$(id -u)" != "0" ]; then SUDO="sudo"; fi
T="$(mktemp -d "${TMPDIR:-/tmp}/jobshunter deb smoke.XXXXXX")"
trap 'rm -rf "${T:?}"' EXIT
BEFORE="$(ls -A "$HOME" 2>/dev/null | sort | tr '\n' ' ')"

$SUDO apt-get install -y "$DEB"
test -x /usr/bin/jobshunter || { echo "Manca /usr/bin/jobshunter"; exit 1; }
test -x /opt/jobshunter/JobsHunter || { echo "Manca /opt/jobshunter/JobsHunter"; exit 1; }
test -f /usr/share/applications/jobshunter.desktop || { echo "Manca la voce di menu"; exit 1; }
test -f /usr/share/icons/hicolor/512x512/apps/jobshunter.png || { echo "Manca l'icona"; exit 1; }
if command -v desktop-file-validate >/dev/null 2>&1; then desktop-file-validate /usr/share/applications/jobshunter.desktop; fi

jobshunter --smoke --smoke-log "$T/smoke.log"

$SUDO apt-get remove -y jobshunter
if [ -e /opt/jobshunter ] || [ -e /usr/bin/jobshunter ] || [ -e /usr/share/applications/jobshunter.desktop ]; then
  echo "Dopo apt remove restano file del pacchetto"; exit 1
fi
AFTER="$(ls -A "$HOME" 2>/dev/null | sort | tr '\n' ' ')"
[ "$BEFORE" = "$AFTER" ] || { echo "Installare o togliere il pacchetto ha cambiato la cartella dell'utente: prima [$BEFORE] dopo [$AFTER]"; exit 1; }
echo "Test di fumo del .deb riuscito: $DEB"
