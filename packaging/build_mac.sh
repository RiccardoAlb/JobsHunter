#!/bin/sh
# Costruisce JobsHunter-<versione>-macOS-<arch>.zip (JobsHunter.app dentro) e lo prova con --smoke.
# NON installa niente (per installare l'app nella cartella Applicazioni dell'utente c'e' ../build_mac_app.sh).
# Uso: packaging/build_mac.sh [--out CARTELLA] [--no-smoke]      (stesse opzioni usate dalla CI)
#
# Richiede macOS, Python 3.11+ con le dipendenze del progetto (requirements.txt).
# Variabili: PY (interprete, predefinito: .venv/bin/python del progetto), JH_WORK (cartella di lavoro, FUORI dal progetto).
# Si costruisce fuori da Desktop/Documenti (iCloud aggiunge attributi che impediscono la firma).
set -e
cd "$(dirname "$0")/.."
PROJ="$(pwd)"
PY="${PY:-$PROJ/.venv/bin/python}"
WORK="${JH_WORK:-$HOME/Library/Caches/JobsHunterBuild/release}"
OUT="$PROJ/dist-release"
SMOKE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --no-smoke) SMOKE=0; shift ;;
    *) echo "Opzione sconosciuta: $1"; exit 2 ;;
  esac
done
VER="$($PY -c 'import jobshunter; print(jobshunter.__version__)')"
ARCH="$(uname -m)"
ZIP="JobsHunter-$VER-macOS-$ARCH.zip"

$PY -m pip install -q pyinstaller pywebview pillow
$PY branding/make_icns.py

rm -rf "${WORK:?}"
mkdir -p "$WORK" "$OUT"
"$PY" -m PyInstaller --noconfirm --clean --distpath "$WORK/dist" --workpath "$WORK/work" packaging/JobsHunter.spec

# firma "ad hoc" (non e' una firma di uno sviluppatore: serve solo perche' i Mac Apple Silicon rifiutano codice senza alcuna firma)
xattr -cr "$WORK/dist/JobsHunter.app"
codesign --force --deep --sign - "$WORK/dist/JobsHunter.app"
codesign --verify --deep --strict "$WORK/dist/JobsHunter.app"

rm -f "${OUT:?}/${ZIP:?}"
ditto -c -k --keepParent --norsrc --noextattr "$WORK/dist/JobsHunter.app" "$OUT/$ZIP"
echo "Creato: $OUT/$ZIP"
du -sh "$WORK/dist/JobsHunter.app" "$OUT/$ZIP"
if [ "$SMOKE" = 1 ]; then
  sh packaging/smoke.sh "$OUT/$ZIP"
fi
