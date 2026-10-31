#!/bin/sh
# Costruisce su Linux: jobshunter_<versione>_<amd64|arm64>.deb e, su x86_64, JobsHunter-<versione>-Linux-x86_64.AppImage.
# Uso: packaging/build_linux.sh [--out CARTELLA] [--no-smoke] [--no-appimage]      (stesse opzioni usate dalla CI)
#
# - Si costruisce su Ubuntu 22.04 (glibc 2.35, quindi il .deb dichiara libc6 >= 2.35). Python e le librerie sono DENTRO il pacchetto.
# - La finestra nativa su Linux richiederebbe GTK/WebKit di sistema: non si includono, `app` apre il browser predefinito.
# - .deb: dpkg-deb (solo Debian/Ubuntu). Albero: /opt/jobshunter, /usr/bin/jobshunter, voce .desktop, icona hicolor, copyright.
# - AppImage: serve appimagetool, SOLO la versione e l'hash SHA256 scritti in packaging/appimagetool.txt (o APPIMAGETOOL=percorso).
#   Senza hash la AppImage viene saltata (non si scarica nulla senza poterlo verificare).
# - Il test di fumo con installazione del .deb (apt) non si fa qui ma in packaging/smoke_deb.sh, solo in CI o con --yes.
set -e
cd "$(dirname "$0")/.."
PROJ="$(pwd)"
if [ -z "${PY:-}" ]; then
  if [ -x "$PROJ/.venv/bin/python" ]; then PY="$PROJ/.venv/bin/python"; else PY=python3; fi
fi
WORK="${JH_WORK:-${TMPDIR:-/tmp}/jobshunter-build-release}"
OUT="$PROJ/dist-release"
SMOKE=1
APPIMAGE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --no-smoke) SMOKE=0; shift ;;
    --no-appimage) APPIMAGE=0; shift ;;
    *) echo "Opzione sconosciuta: $1"; exit 2 ;;
  esac
done
command -v dpkg-deb >/dev/null 2>&1 || { echo "Serve dpkg-deb (Debian o Ubuntu)."; exit 1; }
VER="$($PY -c 'import jobshunter; print(jobshunter.__version__)')"
MACHINE="$(uname -m)"
DEB_ARCH="$(dpkg --print-architecture)"
case "$DEB_ARCH" in amd64 | arm64) ;; *) echo "Architettura non gestita: $DEB_ARCH"; exit 1 ;; esac
DEB="jobshunter_${VER}_${DEB_ARCH}.deb"
APPIMG="JobsHunter-$VER-Linux-$MACHINE.AppImage"

$PY -m pip install -q pyinstaller pillow
$PY branding/make_icons.py

rm -rf "${WORK:?}"
mkdir -p "$WORK" "$OUT"
"$PY" -m PyInstaller --noconfirm --clean --distpath "$WORK/dist" --workpath "$WORK/work" packaging/JobsHunter.spec
du -sh "$WORK/dist/JobsHunter"

# ---- .deb ----
"$PY" packaging/deb_files.py "$WORK/deb" "$WORK/dist/JobsHunter" branding/JobsHunter.png LICENSE "$VER" "$DEB_ARCH"
rm -f "${OUT:?}/${DEB:?}"
dpkg-deb --root-owner-group -Zxz --build "$WORK/deb" "$OUT/$DEB"
dpkg-deb --info "$OUT/$DEB"
echo "Creato: $OUT/$DEB"

# ---- AppImage (solo x86_64, con appimagetool verificato) ----
if [ "$APPIMAGE" = 1 ] && [ "$MACHINE" = "x86_64" ]; then
  TOOL="${APPIMAGETOOL:-}"
  if [ -z "$TOOL" ] && [ -f packaging/appimagetool.txt ]; then
    URL="$(grep -E '^url=' packaging/appimagetool.txt | cut -d= -f2-)"
    SUM="$(grep -E '^sha256=' packaging/appimagetool.txt | cut -d= -f2-)"
    if [ -n "$URL" ] && echo "$SUM" | grep -Eq '^[0-9a-f]{64}$'; then
      curl -fsSL -o "$WORK/appimagetool" "$URL"
      echo "$SUM  $WORK/appimagetool" | sha256sum -c -
      chmod +x "$WORK/appimagetool"
      TOOL="$WORK/appimagetool"
    fi
  fi
  if [ -n "$TOOL" ]; then
    APPDIR="$WORK/JobsHunter.AppDir"
    mkdir -p "$APPDIR/usr/lib"
    cp -R "$WORK/dist/JobsHunter" "$APPDIR/usr/lib/JobsHunter"
    cp branding/JobsHunter.png "$APPDIR/JobsHunter.png"
    cp branding/JobsHunter.png "$APPDIR/.DirIcon"
    cat > "$APPDIR/JobsHunter.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=JobsHunter
Comment=Radar personale di annunci di lavoro
Exec=JobsHunter
Icon=JobsHunter
Categories=Office;Utility;
Terminal=false
DESK
    cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/JobsHunter/JobsHunter" "$@"
RUN
    chmod +x "$APPDIR/AppRun"
    ARCH="$MACHINE" "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUT/$APPIMG"
    chmod +x "$OUT/$APPIMG"
    echo "Creato: $OUT/$APPIMG"
  else
    echo "AppImage non costruita: manca l'hash SHA256 di appimagetool in packaging/appimagetool.txt (vedi docs/RELEASING.md)."
  fi
fi
ls -l "$OUT"
if [ "$SMOKE" = 1 ]; then
  if [ -f "$OUT/$APPIMG" ]; then sh packaging/smoke.sh "$OUT/$APPIMG"; fi
  echo "Il test di fumo del .deb (installazione con apt) e' packaging/smoke_deb.sh: si lancia in CI o a mano con --yes."
fi
