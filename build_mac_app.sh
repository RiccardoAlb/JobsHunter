#!/bin/sh
# Costruisce JobsHunter.app (app Mac con finestra nativa) e la installa in ~/Applications.
# Richiede macOS e il venv del progetto. Uso: ./build_mac_app.sh
#
# Si costruisce FUORI dalla cartella del progetto: Desktop e Documenti sono sincronizzati con iCloud, che
# aggiunge attributi ai file e impedisce la firma del pacchetto ("detritus not allowed").
set -e
cd "$(dirname "$0")"
PROJ="$(pwd)"
PY="$PROJ/.venv/bin/python"
WORK="$HOME/Library/Caches/JobsHunterBuild"
DEST="$HOME/Applications"
GEO="$($PY -c 'import geonamescache, os; print(os.path.join(os.path.dirname(geonamescache.__file__), "data"))')"

$PY -m pip install -q pyinstaller pywebview pillow pypdf cryptography
$PY branding/make_icns.py

rm -rf "$WORK"
mkdir -p "$WORK"

# del dataset delle citta' serve solo cities15000.json (16 MB), non tutto il pacchetto (179 MB)
"$PROJ/.venv/bin/pyinstaller" --noconfirm --clean --windowed \
  --name JobsHunter \
  --icon "$PROJ/branding/JobsHunter.icns" \
  --osx-bundle-identifier local.jobshunter.app \
  --add-data "$PROJ/config.example.toml:." \
  --add-data "$PROJ/jobshunter/gui/static:jobshunter/gui/static" \
  --add-data "$GEO/cities15000.json:geonamescache/data" \
  --add-data "$GEO/countries.json:geonamescache/data" \
  --hidden-import pypdf --collect-submodules pypdf --hidden-import cryptography \
  --distpath "$WORK/dist" --workpath "$WORK/work" --specpath "$WORK" \
  "$PROJ/run_app.py"

# firma "ad hoc": basta per far girare l'app sul proprio Mac (per distribuirla ad altri servono Developer ID e notarizzazione)
xattr -cr "$WORK/dist/JobsHunter.app"
codesign --force --deep --sign - "$WORK/dist/JobsHunter.app"
codesign --verify --deep --strict "$WORK/dist/JobsHunter.app" && echo "Firma verificata (ad hoc)"

mkdir -p "$DEST"
rm -rf "$DEST/JobsHunter.app"
ditto --norsrc --noextattr "$WORK/dist/JobsHunter.app" "$DEST/JobsHunter.app"

echo
echo "Fatto: $DEST/JobsHunter.app"
du -sh "$DEST/JobsHunter.app"
if [ -d "$DEST/JobHunter.app" ]; then
  echo
  echo "Nota: nel vecchio nome esiste ancora $DEST/JobHunter.app (non e' stato toccato)."
  echo "Quando hai verificato che JobsHunter.app funziona, toglila con: ./scripts/remove_old_app.sh"
fi
