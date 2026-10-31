"""Controllo di Python in `jh` e `jh.bat` (fase 9): versione, ordine dei candidati, conferma prima di installare, niente installazioni
senza terminale interattivo, `jh setup`. Tutto con comandi FINTI in una cartella temporanea: nessuna rete, nessuna modifica al sistema.
`jh` e' uno script sh (macOS e Linux); `jh.bat` si prova qui in modo statico (il flusso vero si prova su un Windows)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import t

ROOT = Path(__file__).resolve().parent.parent.parent
POSIX = pytest.mark.skipif(sys.platform.startswith("win"), reason="jh e' uno script sh (su Windows c'e' jh.bat)")

FAKE_PY = """#!/bin/sh
# python finto: -c risponde secondo la versione, -m venv crea un python finto, -m pip e -m jobshunter si limitano a scrivere
echo "PY $0 $*" >> "$FAKE_LOG"
case "$1" in
  -c) exit @OK@ ;;
  -m)
    case "$2" in
      venv) mkdir -p "$3/bin" && cp "$0" "$3/bin/python" && sed 's/^OKCODE=.*/OKCODE=0/' "$3/bin/python" > "$3/bin/python.tmp" && cat "$3/bin/python.tmp" > "$3/bin/python" && rm "$3/bin/python.tmp"; exit 0 ;;
      pip) echo "PIP $*"; exit 0 ;;
      jobshunter) shift 2; echo "JH_RAN $*"; exit 0 ;;
    esac ;;
esac
exit 0
"""

LOGGER = """#!/bin/sh
echo "@NAME@ $*" >> "$FAKE_LOG"
@EXTRA@
exit 0
"""


class Box:
    """Una cartella di comandi finti (unico PATH del processo) e un progetto con spazi nel nome."""

    def __init__(self, tmp: Path):
        self.bin = tmp / "bin finti"
        self.bin.mkdir()
        self.proj = tmp / "Mio Progetto è"
        self.proj.mkdir()
        self.log = tmp / "comandi.log"
        self.log.write_text("", encoding="utf-8")
        shutil.copy(ROOT / "jh", self.proj / "jh")
        (self.proj / "jh").chmod(0o755)
        (self.proj / "requirements.txt").write_text("flask\n", encoding="utf-8")
        for tool in ("dirname", "readlink", "mkdir", "cp", "sed", "cat", "rm", "id"):  # gli unici comandi veri che servono allo script e ai finti
            real = shutil.which(tool)
            assert real, tool
            (self.bin / tool).symlink_to(real)

    def py(self, name: str, ok: bool = True):
        p = self.bin / name
        p.write_text(FAKE_PY.replace("@OK@", "0" if ok else "1"), encoding="utf-8")
        p.chmod(0o755)

    def tool(self, name: str, extra: str = ""):
        p = self.bin / name
        p.write_text(LOGGER.replace("@NAME@", name).replace("@EXTRA@", extra), encoding="utf-8")
        p.chmod(0o755)

    def uname(self, system: str):
        p = self.bin / "uname"
        p.write_text(f'#!/bin/sh\necho {system}\n', encoding="utf-8")
        p.chmod(0o755)

    def venv(self, ok: bool = True):
        d = self.proj / ".venv" / "bin"
        d.mkdir(parents=True)
        p = d / "python"
        p.write_text(FAKE_PY.replace("@OK@", "0" if ok else "1"), encoding="utf-8")
        p.chmod(0o755)

    def run(self, *args, answers: str = "", interactive: bool = False):
        env = {"PATH": str(self.bin), "FAKE_LOG": str(self.log), "HOME": str(self.proj.parent)}
        if interactive:
            env["JH_FORCE_INTERACTIVE"] = "1"
        r = subprocess.run(["/bin/sh", str(self.proj / "jh"), *args], input=answers, env=env, cwd=str(self.proj.parent), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=t(60))
        return r

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


def ran(box_: Box, prefix: str) -> list[str]:
    return [c for c in box_.calls() if c.startswith(prefix)]


# ---------------------------------------------------------------- strada normale ----
@POSIX
def test_con_il_venv_adatto_lancia_il_programma_senza_domande(box):
    box.venv()
    r = box.run("gui", "--no-browser")
    assert r.returncode == 0 and "JH_RAN gui --no-browser" in r.stdout
    assert not ran(box, "brew") and not ran(box, "sudo")


@POSIX
def test_venv_con_python_vecchio_non_si_usa_e_non_si_cancella_nulla(box):
    box.venv(ok=False)
    r = box.run("gui")
    assert r.returncode == 1 and "piu' vecchio della 3.11" in r.stderr and "./jh setup" in r.stderr
    assert (box.proj / ".venv").is_dir()


# ------------------------------------------------------------ rilevamento versione ----
@POSIX
@pytest.mark.parametrize("candidates,expected", [
    ({"python3.13": True, "python3.12": True, "python3.11": True, "python3": True}, "python3.13"),
    ({"python3.13": False, "python3.12": True, "python3": True}, "python3.12"),
    ({"python3.12": False, "python3.11": True, "python3": False}, "python3.11"),
    ({"python3": True, "python": True}, "python3"),
    ({"python3.11": False, "python3": False, "python": True}, "python"),
])
def test_ordine_dei_candidati_e_versioni_vecchie_scartate(box, candidates, expected):
    for name, ok in candidates.items():
        box.py(name, ok)
    r = box.run("setup", "--yes")
    assert r.returncode == 0, r.stderr
    parsed = [re.match(r"^PY .*/(python[\d.]*) (-[cm])( venv)?", c) for c in ran(box, "PY ")]
    created = [m.group(1) for m in parsed if m and m.group(2) == "-m" and m.group(3)]
    assert created == [expected], (created, box.calls())
    # i candidati piu' nuovi si provano per primi, e dopo il primo adatto non se ne prova nessun altro
    probed = [m.group(1) for m in parsed if m and m.group(2) == "-c"]
    existing = [n for n in ["python3.13", "python3.12", "python3.11", "python3", "python"] if n in candidates]
    assert probed == existing[: existing.index(expected) + 1]


@POSIX
def test_setup_crea_il_venv_e_installa_i_requisiti_in_un_percorso_con_spazi(box):
    box.py("python3.13")
    r = box.run("setup", "--yes")
    assert r.returncode == 0 and "Fatto" in r.stderr
    assert (box.proj / ".venv" / "bin" / "python").is_file()
    pip = ran(box, "PY ")[-1]
    assert " -m pip install -r " in pip and str(box.proj / "requirements.txt") in pip


@POSIX
def test_setup_senza_yes_chiede_conferma_prima_di_scaricare(box):
    box.py("python3.13")
    r = box.run("setup", interactive=True, answers="n\n")
    assert r.returncode == 1 and "Continuo? [s/N]" in r.stderr and "mi fermo" in r.stderr
    assert not [c for c in box.calls() if " -m pip " in c]
    r = box.run("setup", interactive=True, answers="s\n")
    assert r.returncode == 0 and [c for c in box.calls() if " -m pip install" in c]


@POSIX
def test_setup_non_interattivo_senza_yes_non_scarica(box):
    box.py("python3.13")
    r = box.run("setup")
    assert r.returncode == 1 and "non scarico" in r.stderr and "--yes" in r.stderr
    assert not [c for c in box.calls() if " -m pip " in c]


@POSIX
def test_setup_argomento_sconosciuto(box):
    box.py("python3.13")
    assert box.run("setup", "--boh").returncode == 2


# ----------------------------------------------------------- Python mancante o vecchio ----
@POSIX
def test_python_vecchio_non_interattivo_stampa_il_messaggio_ed_esce_senza_installare(box):
    box.py("python3", ok=False)
    box.uname("Darwin")
    box.tool("brew")
    box.tool("curl")
    r = box.run("gui")
    assert r.returncode == 1
    for frase in ("Python 3.11 o superiore", "python3.13, python3.12, python3.11, python3, python", "brew install python@3.13", "non installo nulla", "contengono il proprio Python"):
        assert frase in r.stderr, frase
    assert not ran(box, "brew") and not ran(box, "curl")


@POSIX
def test_senza_python_macos_con_brew_chiede_e_con_no_non_installa(box):
    box.uname("Darwin")
    box.tool("brew")
    r = box.run("gui", interactive=True, answers="n\n")
    assert r.returncode == 1 and "Vuoi installarlo ora? [s/N]" in r.stderr
    assert not ran(box, "brew")


@POSIX
def test_risposta_vuota_o_strana_vale_no(box):
    box.uname("Darwin")
    box.tool("brew")
    for answer in ("\n", "forse\n", ""):
        box.run("gui", interactive=True, answers=answer)
    assert not ran(box, "brew")


@POSIX
def test_senza_python_macos_con_brew_e_si_installa_poi_continua(box):
    box.uname("Darwin")
    new_python = FAKE_PY.replace("@OK@", "0").replace("$", r"\$").replace("`", r"\`").replace('"', r'\"')
    box.tool("brew", extra=f'printf "%s" "{new_python}" > "{box.bin}/python3.13" && chmod +x "{box.bin}/python3.13"')
    box.tool("chmod")
    (box.bin / "chmod").unlink()
    (box.bin / "chmod").symlink_to(shutil.which("chmod"))
    r = box.run("setup", "--yes", interactive=True, answers="s\n")
    assert ran(box, "brew install python@3.13") == ["brew install python@3.13"]
    assert r.returncode == 0 and (box.proj / ".venv" / "bin" / "python").is_file(), r.stderr


@POSIX
def test_senza_python_macos_senza_brew_apre_la_pagina_solo_dopo_conferma_e_non_scarica_nulla(box):
    box.uname("Darwin")
    box.tool("open")
    box.tool("curl")
    box.tool("wget")
    r = box.run("gui", interactive=True, answers="n\n")
    assert "https://www.python.org/downloads/macos/" in r.stderr and not ran(box, "open")
    r = box.run("gui", interactive=True, answers="s\n")
    assert ran(box, "open") == ["open https://www.python.org/downloads/macos/"] and r.returncode == 1
    assert not ran(box, "curl") and not ran(box, "wget")


@POSIX
@pytest.mark.parametrize("manager,expected", [
    ("apt-get", "sudo apt-get install -y python3 python3-venv python3-pip"),
    ("dnf", "sudo dnf install -y python3.13"),
    ("pacman", "sudo pacman -S --noconfirm python"),
])
def test_linux_comando_con_sudo_solo_dopo_la_conferma(box, manager, expected):
    box.uname("Linux")
    box.tool(manager)
    box.tool("sudo", extra='"$@"')  # il sudo finto esegue il comando che riceve (che e' a sua volta finto)
    r = box.run("gui", interactive=True, answers="n\n")
    assert expected in r.stderr and not ran(box, "sudo") and not ran(box, manager)
    r = box.run("gui", interactive=True, answers="s\n")
    assert ran(box, "sudo") == [expected] or ran(box, "sudo")[0] == expected
    assert r.returncode == 1  # il Python finto non compare nel PATH: si invita a riaprire il terminale
    assert "riapri il terminale" in r.stderr


@POSIX
def test_linux_senza_gestore_noto_mostra_cosa_fare_e_non_esegue_nulla(box):
    box.uname("Linux")
    box.tool("sudo")
    r = box.run("gui", interactive=True, answers="s\n")
    assert r.returncode == 1 and "python.org" in r.stderr and not ran(box, "sudo")


@POSIX
def test_linux_non_interattivo_non_installa(box):
    box.uname("Linux")
    box.tool("apt-get")
    box.tool("sudo", extra='"$@"')
    r = box.run("gui")
    assert r.returncode == 1 and "non installo nulla" in r.stderr and not ran(box, "apt-get") and not ran(box, "sudo")


# ------------------------------------------------------------ primo avvio senza .venv ----
@POSIX
def test_gui_senza_venv_propone_setup_e_poi_parte(box):
    box.py("python3.12")
    r = box.run("gui", interactive=True, answers="s\ns\n")
    assert r.returncode == 0 and "Vuoi prepararlo ora con ./jh setup? [s/N]" in r.stderr and "JH_RAN gui" in r.stdout


@POSIX
def test_gui_senza_venv_non_interattivo_non_crea_nulla(box):
    box.py("python3.12")
    r = box.run("gui")
    assert r.returncode == 1 and "./jh setup" in r.stderr
    assert not (box.proj / ".venv").exists()


@POSIX
def test_gui_senza_venv_con_no_non_crea_nulla(box):
    box.py("python3.12")
    r = box.run("gui", interactive=True, answers="n\n")
    assert r.returncode == 1 and not (box.proj / ".venv").exists()


# ----------------------------------------------------------------- sicurezza statica ----
def test_nessun_download_ne_esecuzione_di_file_negli_script():
    sh = (ROOT / "jh").read_text(encoding="utf-8")
    bat = (ROOT / "jh.bat").read_bytes().decode("ascii")
    for text in (sh, bat):
        assert not re.search(r"(?i)\b(curl|wget|Invoke-WebRequest|bitsadmin|certutil)\b", text.replace("# ", ""))
        assert not re.search(r"\|\s*(ba|z)?sh\b", text)
        assert "eval " not in text
    assert "brew install python@3.13" in sh and "https://www.python.org/downloads/macos/" in sh
    assert "winget install -e --id Python.Python.3.13 --scope user" in bat and "https://www.python.org/downloads/windows/" in bat
    assert '"--yes"' in sh or "--yes" in sh


def test_jh_bat_ha_la_stessa_logica_di_jh():
    bat = (ROOT / "jh.bat").read_bytes().decode("ascii")
    sh = (ROOT / "jh").read_text(encoding="utf-8")
    assert bat.count("\r\n") == bat.count("\n") and all(ord(c) < 128 for c in bat)
    # stesso ordine di ricerca
    assert [m for m in re.findall(r'try_py "([^"]+)"', bat)] == ["py -3.13", "py -3.12", "py -3.11", "py -3", "python"]
    assert re.search(r"for c in python3\.13 python3\.12 python3\.11 python3 python;", sh)
    for fragment in ("sys.version_info >= (3, 11)", "Vuoi installarlo ora?", "setup", "--yes", "requirements.txt"):
        assert fragment in bat and fragment in sh, fragment
    # senza risposta affermativa esplicita non si installa: ogni installazione sta dopo un controllo della risposta
    for m in re.finditer(r"(?m)^:do_winget\n", bat.replace("\r\n", "\n")):
        before = bat.replace("\r\n", "\n")[: m.start()]
        assert 'if /i "%ANS%"=="s" goto do_winget' in before


def test_comando_setup_del_programma_controlla_l_ambiente():
    from click.testing import CliRunner

    from jobshunter.cli import main

    r = CliRunner().invoke(main, ["setup"])
    assert r.exit_code == 0 and "Python" in r.output and "tutte presenti" in r.output
