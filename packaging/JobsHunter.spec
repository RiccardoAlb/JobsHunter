# -*- mode: python ; coding: utf-8 -*-
# Specifica PyInstaller comune a macOS, Windows e Linux (modalita' CARTELLA, non file singolo).
# Si usa dagli script `build_mac.sh`, `build_windows.ps1`, `build_linux.sh` (le stesse opzioni della CI):
#   pyinstaller --noconfirm --clean --distpath <dist> --workpath <work> packaging/JobsHunter.spec
#
# Cosa entra nel pacchetto: il codice di `jobshunter`, config.example.toml, la pagina (jobshunter/gui/static), i SOLI file di
# geonamescache che servono (cities15000.json e countries.json), pypdf, cryptography e, dove serve, pywebview.
# Cosa NON entra: tests/, docs/, scripts/, config.toml, database, CV, chiavi o altri file personali (PyInstaller include solo quello
# che il codice importa e i file elencati qui sotto: nessun file del progetto viene copiato "a cartella intera").
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - SPECPATH lo definisce PyInstaller
sys.path.insert(0, str(Path(SPECPATH).resolve()))  # noqa: F821
import versioninfo  # noqa: E402

VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "jobshunter" / "__init__.py").read_text(encoding="utf-8")).group(1)
IS_MAC, IS_WIN, IS_LINUX = sys.platform == "darwin", sys.platform.startswith("win"), sys.platform.startswith("linux")

import geonamescache  # noqa: E402

GEO = Path(geonamescache.__file__).resolve().parent / "data"

datas = [
    (str(ROOT / "config.example.toml"), "."),
    (str(ROOT / "jobshunter" / "gui" / "static"), "jobshunter/gui/static"),
    (str(GEO / "cities15000.json"), "geonamescache/data"),
    (str(GEO / "countries.json"), "geonamescache/data"),
]
hiddenimports = ["pypdf", "cryptography"]
# moduli che il programma non usa: tolgono MB inutili
excludes = ["tkinter", "matplotlib", "numpy", "scipy", "pandas", "PIL", "IPython", "pytest", "setuptools", "pip", "wheel"]  # NON escludere distutils: l'hook di setuptools di PyInstaller vi crea un alias e la build fallisce (provato su Windows)
if IS_LINUX:
    excludes.append("webview")  # su Linux la finestra nativa usa GTK/WebKit di sistema: non si include, se mancano si apre il browser

icon = None
if IS_MAC:
    icon = str(ROOT / "branding" / "JobsHunter.icns")
elif IS_WIN:
    icon = str(ROOT / "branding" / "JobsHunter.ico")

version_file = None
if IS_WIN:
    version_file = str(Path(tempfile.gettempdir()) / "jobshunter-version-info.txt")
    Path(version_file).write_text(versioninfo.render(VERSION), encoding="utf-8")

from PyInstaller.utils.hooks import collect_submodules  # noqa: E402

a = Analysis(  # noqa: F821
    [str(ROOT / "run_app.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports + collect_submodules("pypdf"),
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JobsHunter",
    console=IS_LINUX,  # macOS e Windows: nessuna console (e nessuna finestra nera); Linux: si avvia anche da terminale
    icon=icon,
    version=version_file,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="JobsHunter")  # noqa: F821
if IS_MAC:
    app = BUNDLE(  # noqa: F821
        coll,
        name="JobsHunter.app",
        icon=icon,
        bundle_identifier="local.jobshunter.app",
        info_plist={
            "CFBundleName": "JobsHunter",
            "CFBundleDisplayName": "JobsHunter",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
        },
    )
