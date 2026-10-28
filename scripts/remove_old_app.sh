#!/bin/sh
# PASSO SEPARATO, da lanciare a mano solo dopo aver verificato che JobsHunter.app funziona.
# Toglie dalla cartella Applicazioni dell'utente il vecchio JobHunter.app. NON tocca i dati
# (~/Library/Application Support/JobHunter): quelli restano come copia di sicurezza.
set -e
DEST="$HOME/Applications"
OLD="$DEST/JobHunter.app"
NEW="$DEST/JobsHunter.app"
[ -d "$NEW" ] || { echo "JobsHunter.app non trovata in $DEST: costruiscila prima con ./build_mac_app.sh"; exit 1; }
[ -d "$HOME/Library/Application Support/JobsHunter" ] || echo "Attenzione: JobsHunter.app non risulta ancora avviata (manca ~/Library/Application Support/JobsHunter): aprila una volta prima di togliere la vecchia."
[ -d "$OLD" ] || { echo "Il vecchio JobHunter.app non c'e' piu': niente da fare."; exit 0; }
printf "Rimuovere %s ? [s/N] " "$OLD"
read -r ans
case "$ans" in
  s|S|si|SI|y|Y) rm -rf "$OLD"; echo "Rimossa. I dati in ~/Library/Application Support/JobHunter non sono stati toccati." ;;
  *) echo "Annullato." ;;
esac
