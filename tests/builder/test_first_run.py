"""Primo avvio: se manca config.toml lo si crea dal file di esempio (mai sopra uno esistente)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from jobshunter import osinfo, settings
from jobshunter.cli import main

ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE = ROOT / "tests" / "data" / "fixture_root" / "config.example.toml"


def test_config_creato_dall_esempio_con_una_riga_informativa(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path))
    r = CliRunner().invoke(main, ["profiles", "list"])
    assert "Config non trovata" not in r.output
    p = tmp_path / "config.toml"
    assert p.exists() and p.read_text(encoding="utf-8") == EXAMPLE.read_text(encoding="utf-8")
    assert not (tmp_path / ".config.toml.lock").exists() and not list(tmp_path.glob("*.tmp"))


def test_messaggio_una_sola_volta(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path))
    settings.load_config(create_if_missing=True)
    settings.load_config(create_if_missing=True)
    err = capsys.readouterr().err
    assert err.count("Creato config.toml dal file di esempio: lo trovi in") == 1 and str(tmp_path / "config.toml") in err


def test_config_esistente_non_si_sovrascrive(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text("[general]\nmin_score = 77\n", encoding="utf-8")
    cfg = settings.load_config(create_if_missing=settings.auto_create())
    assert cfg["general"]["min_score"] == 77
    assert (tmp_path / "config.toml").read_text(encoding="utf-8") == "[general]\nmin_score = 77\n"
    assert "Creato" not in capsys.readouterr().err


def test_esempio_mancante_mantiene_l_errore_con_istruzioni(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "bundled_root", lambda: tmp_path / "vuota")
    r = CliRunner().invoke(main, ["profiles", "list"])
    assert r.exit_code == 1 and "Config non trovata" in r.output and "config.example.toml" in r.output and "repository" in r.output
    assert not (tmp_path / "config.toml").exists()


def test_config_indicato_a_mano_e_inesistente_resta_un_errore(tmp_path, monkeypatch):
    monkeypatch.delenv("JOBSHUNTER_HOME")
    r = CliRunner().invoke(main, ["--config", str(tmp_path / "refuso.toml"), "profiles", "list"])
    assert r.exit_code == 1 and "Config non trovata" in r.output and "Copia config.example.toml" in r.output
    assert not (tmp_path / "refuso.toml").exists()


def test_percorso_con_spazi_e_accenti(tmp_path, monkeypatch):
    d = tmp_path / "Mia cartella è1"
    monkeypatch.setenv("JOBSHUNTER_HOME", str(d))
    settings.load_config(create_if_missing=True)
    assert (d / "config.toml").exists()


def test_windows_simulato(tmp_path, monkeypatch):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(settings.fsperm.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, "", ""))
    monkeypatch.setattr(settings.fsperm, "_whoami_output", lambda: None)
    monkeypatch.setenv("USERNAME", "utente")
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path))
    settings.load_config(create_if_missing=True)
    assert (tmp_path / "config.toml").exists()


def test_due_processi_insieme_creano_un_solo_config(tmp_path):
    code = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from jobshunter import settings\n"
        "settings.bundled_root = lambda: Path(sys.argv[2])\n"
        "while time.time() < float(sys.argv[3]): pass\n"
        "settings.load_config(create_if_missing=True)\n"
    )
    import time

    start = str(time.time() + 1.5)
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    env.update(JOBSHUNTER_HOME=str(tmp_path), PYTHONPATH=str(ROOT))
    procs = [subprocess.Popen([sys.executable, "-c", code, "x", str(EXAMPLE.parent), start], env=env, cwd=tmp_path,
                              stderr=subprocess.PIPE, text=True, encoding="utf-8") for _ in range(2)]
    errs = [p.communicate(timeout=60)[1] for p in procs]
    assert [p.returncode for p in procs] == [0, 0], errs
    assert sum("Creato config.toml" in e for e in errs) == 1
    assert (tmp_path / "config.toml").read_text(encoding="utf-8") == EXAMPLE.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(sys.platform.startswith("win"), reason="permessi POSIX (chmod/st_mode/umask): su Windows la protezione e' icacls (provata in test_windows_simulato)")
def test_permessi_600_su_posix(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path))
    settings.load_config(create_if_missing=True)
    assert (tmp_path / "config.toml").stat().st_mode & 0o777 == 0o600
