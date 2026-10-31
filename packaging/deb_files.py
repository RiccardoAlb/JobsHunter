"""File di un pacchetto .deb di JobsHunter: control, voce .desktop, postinst/prerm e l'albero da dare a `dpkg-deb --build`.

Uso (da build_linux.sh):  python packaging/deb_files.py <albero> <cartella PyInstaller> <icona.png> <licenza> <versione> <architettura>
Le funzioni sono pure (si provano su ogni sistema): `dpkg-deb` serve solo a impacchettare l'albero, e c'e' solo su Debian/Ubuntu.

Contenuto del pacchetto: /opt/jobshunter (la cartella PyInstaller), /usr/bin/jobshunter (collegamento), la voce di menu e l'icona.
Nessuno script scrive nelle cartelle dell'utente; i dati restano dove li vuole osinfo.py (~/.local/share/jobshunter).
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import sys
from pathlib import Path

PACKAGE = "jobshunter"
OPT = "opt/jobshunter"
DEPENDS = "libc6 (>= 2.35)"  # costruito su Ubuntu 22.04 (glibc 2.35): il resto (Python, librerie) e' dentro la cartella
RECOMMENDS = "xdg-utils"  # per aprire la pagina nel browser predefinito quando la finestra nativa non c'e'
MAINTAINER = "JobsHunter <jobshunter@example.invalid>"
ARCHES = ("amd64", "arm64")


def control(version: str, arch: str, installed_size_kb: int) -> str:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"versione non valida: {version!r}")
    if arch not in ARCHES:
        raise ValueError(f"architettura non gestita: {arch!r}")
    return (f"Package: {PACKAGE}\n"
            f"Version: {version}\n"
            "Section: utils\n"
            "Priority: optional\n"
            f"Architecture: {arch}\n"
            f"Installed-Size: {int(installed_size_kb)}\n"
            f"Depends: {DEPENDS}\n"
            f"Recommends: {RECOMMENDS}\n"
            f"Maintainer: {MAINTAINER}\n"
            "Description: radar personale di annunci di lavoro, in locale\n"
            " JobsHunter raccoglie annunci da piu' fonti, li valuta, toglie i doppioni,\n"
            " controlla che siano ancora aperti e ti fa seguire le candidature.\n"
            " Dati e chiavi restano sul tuo computer, senza account e senza telemetria.\n"
            " Il pacchetto contiene il proprio Python. La finestra nativa su Linux non e'\n"
            " inclusa: l'interfaccia si apre nel browser predefinito.\n")


def desktop() -> str:
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            "Name=JobsHunter\n"
            "Comment=Radar personale di annunci di lavoro\n"
            "Comment[en]=Personal job search radar\n"
            f"Exec={PACKAGE}\n"
            f"Icon={PACKAGE}\n"
            "Categories=Office;Utility;\n"
            "Terminal=false\n")


# Gli script del pacchetto aggiornano solo le cache di sistema del menu e delle icone (se gli strumenti ci sono) e non toccano la HOME.
POSTINST = """#!/bin/sh
set -e
# nessun file dell'utente viene creato o letto: solo le cache di sistema di menu e icone, se esistono gli strumenti
if [ "$1" = "configure" ]; then
  if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q /usr/share/applications || true; fi
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true; fi
fi
exit 0
"""

PRERM = """#!/bin/sh
set -e
# niente da fermare: JobsHunter non installa servizi. La scansione pianificata (se l'utente l'ha attivata) e i dati dell'utente restano
# dove sono; per toglierla: jobshunter --help e le Impostazioni dell'app.
exit 0
"""


def populate(tree: Path, dist: Path, icon: Path, license_file: Path, version: str, arch: str) -> Path:
    """Costruisce l'albero del pacchetto in `tree` (che deve essere vuoto o inesistente) e lo ritorna."""
    tree = Path(tree)
    if tree.exists() and any(tree.iterdir()):
        raise FileExistsError(f"{tree} non e' vuota")
    opt = tree / OPT
    shutil.copytree(dist, opt, symlinks=True)
    (tree / "usr" / "bin").mkdir(parents=True)
    os.symlink(f"/{OPT}/JobsHunter", tree / "usr" / "bin" / PACKAGE)
    apps = tree / "usr" / "share" / "applications"
    apps.mkdir(parents=True)
    (apps / f"{PACKAGE}.desktop").write_text(desktop(), encoding="utf-8")
    icons = tree / "usr" / "share" / "icons" / "hicolor" / "512x512" / "apps"
    icons.mkdir(parents=True)
    shutil.copyfile(icon, icons / f"{PACKAGE}.png")
    doc = tree / "usr" / "share" / "doc" / PACKAGE
    doc.mkdir(parents=True)
    shutil.copyfile(license_file, doc / "copyright")
    deb = tree / "DEBIAN"
    deb.mkdir()
    size_kb = 0
    for root, _dirs, files in os.walk(tree):
        if Path(root) == deb:
            continue
        for f in files:
            p = Path(root) / f
            if not p.is_symlink():
                size_kb += (p.stat().st_size + 1023) // 1024
    (deb / "control").write_text(control(version, arch, size_kb), encoding="utf-8")
    (deb / "postinst").write_text(POSTINST, encoding="utf-8")
    (deb / "prerm").write_text(PRERM, encoding="utf-8")
    normalize_modes(tree)
    return tree


def normalize_modes(tree: Path) -> None:
    """Cartelle 755, file 644, eseguibili 755, script del pacchetto 755 (dpkg-deb rifiuta permessi strani nella cartella DEBIAN)."""
    for root, dirs, files in os.walk(tree):
        for d in dirs:
            os.chmod(Path(root) / d, 0o755)
        for f in files:
            p = Path(root) / f
            if p.is_symlink():
                continue
            mode = p.stat().st_mode
            executable = bool(mode & stat.S_IXUSR) or p.parent.name == "DEBIAN" and f in ("postinst", "prerm")
            os.chmod(p, 0o755 if executable else 0o644)
    os.chmod(tree, 0o755)


def main(argv: list[str]) -> int:
    if len(argv) != 7:
        print(__doc__, file=sys.stderr)
        return 2
    _, tree, dist, icon, lic, version, arch = argv
    populate(Path(tree), Path(dist), Path(icon), Path(lic), version, arch)
    print(f"Albero del pacchetto pronto in {tree}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
