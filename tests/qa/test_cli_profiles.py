"""SPEC 7: ./jh profiles list|show|add|rm|on|off e ./jh scan --profile (output in italiano, codice di uscita != 0 su errore)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from qa.qa_helpers import job

pytestmark = pytest.mark.phase2
ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def run(qcfg, home):
    from jobshunter.cli import main

    def _run(*args, ok=None):
        r = CliRunner().invoke(main, list(args), catch_exceptions=True)
        assert not (r.exception and not isinstance(r.exception, SystemExit)), f"eccezione non gestita: {r.exception!r}\n{r.output}"
        assert "—" not in r.output, "trattino lungo nell'output"
        assert "Traceback" not in r.output
        if ok is True:
            assert r.exit_code == 0, r.output
        if ok is False:
            assert r.exit_code != 0, f"atteso codice di uscita != 0: {r.output}"
        return r

    return _run


def test_list_mostra_il_profilo_di_default(run):
    r = run("profiles", "list", ok=True)
    assert "Cybersecurity" in r.output


def test_add_show_list_rm(run):
    r = run("profiles", "add", "--name", "Infermieri", "--preset", "custom", "--title", "infermiere", "--title", "OSS",
            "--country", "it", "--country", "de", "--city", "Bari", "--km", "60", "--seniority", "junior", "--no-remote", ok=True)
    out = run("profiles", "list", ok=True).output
    assert "Infermieri" in out and "Cybersecurity" in out
    s = run("profiles", "show", "Infermieri", ok=True).output
    for frag in ("infermiere", "OSS", "Bari", "60", "junior"):
        assert frag.lower() in s.lower(), f"manca '{frag}' in show:\n{s}"
    assert "de" in s.lower() and "it" in s.lower()
    run("profiles", "rm", "Infermieri", ok=True)
    assert "Infermieri" not in run("profiles", "list", ok=True).output


def test_on_off(run):
    run("profiles", "add", "--name", "Dev", "--preset", "software_dev", ok=True)
    run("profiles", "off", "Dev", ok=True)
    assert "spento" in run("profiles", "show", "Dev", ok=True).output.lower() or "no" in run("profiles", "show", "Dev").output.lower()
    run("profiles", "on", "Dev", ok=True)


@pytest.mark.parametrize("args", [
    ("add", "--name", "", "--preset", "software_dev"),
    ("add", "--name", "Cybersecurity", "--preset", "software_dev"),            # duplicato
    ("add", "--name", "X", "--preset", "nope"),
    ("add", "--name", "X", "--preset", "custom"),                              # custom senza --title
    ("add", "--name", "X", "--preset", "software_dev", "--country", "xx"),
    ("add", "--name", "X", "--preset", "software_dev", "--seniority", "boss"),
    ("add", "--name", "X", "--preset", "software_dev", "--city", "Roma", "--km", "0"),
    ("add", "--name", "X", "--preset", "software_dev", "--city", "Roma", "--km", "99999"),
    ("add", "--name", "X", "--preset", "software_dev", "--km", "abc"),
    ("show", "NonEsiste"), ("rm", "NonEsiste"), ("on", "NonEsiste"), ("off", "NonEsiste"),
    ("rm", "Cybersecurity"),                                                   # e' l'ultimo
    ("add",), ("show",),
])
def test_errori_danno_codice_di_uscita_non_zero(run, args):
    r = run("profiles", *args, ok=False)
    assert r.output.strip(), "serve un messaggio d'errore leggibile"
    assert "Usage" in r.output or any(w in r.output.lower() for w in ("non", "gia", "già", "errore", "manca", "valid", "trovat", "ultimo", "serve"))
    assert "Cybersecurity" in run("profiles", "list", ok=True).output


def test_input_strano_nella_cli(run):
    for name in ("☃ neve", "a" * 5000, "x\x00y", "--help", "'; DROP TABLE profiles; --"):
        r = run("profiles", "add", "--name", name, "--preset", "software_dev")
        assert r.exit_code in (0, 1, 2)
    assert "Cybersecurity" in run("profiles", "list", ok=True).output


def test_scan_con_profilo(run, qcfg, qdb, fake_jobs):
    run("profiles", "add", "--name", "Infermieri", "--preset", "custom", "--title", "infermiere", ok=True)
    fake_jobs([job("Infermiere professionale", "Humanitas", "Milano", "Reparto turni assistenza", n=1),
               job("SOC Analyst", "Acme", "Roma", "SIEM EDR", n=2)])
    run("scan", "--no-notify", "--profile", "Infermieri", ok=True)
    titles = {r["title"] for r in qdb.conn.execute("SELECT title FROM jobs")}
    assert titles == {"Infermiere professionale"}


def test_scan_con_piu_profili_ripetibile(run, qdb, fake_jobs):
    run("profiles", "add", "--name", "Infermieri", "--preset", "custom", "--title", "infermiere", ok=True)
    fake_jobs([job("Infermiere", "Humanitas", "Milano", "Reparto turni", n=1), job("SOC Analyst", "Acme", "Roma", "SIEM EDR", n=2)])
    run("scan", "--no-notify", "--profile", "Infermieri", "--profile", "Cybersecurity", ok=True)
    assert qdb.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2


def test_scan_con_profilo_inesistente_fallisce_senza_scansionare(run, qdb, fake_jobs):
    fake_jobs([job("SOC Analyst", "Acme", "Roma", "SIEM EDR", n=2)])
    run("scan", "--no-notify", "--profile", "Fantasma", ok=False)
    assert qdb.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_scan_senza_profile_come_oggi(run, qdb, fake_jobs):
    fake_jobs([job("SOC Analyst", "Acme", "Roma", "SIEM EDR", n=2)])
    run("scan", "--no-notify", ok=True)
    assert qdb.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_help_elenca_profiles_e_scan_profile(run):
    assert "profiles" in run("--help", ok=True).output
    assert "--profile" in run("scan", "--help", ok=True).output
    out = run("profiles", "--help", ok=True).output
    for sub in ("list", "show", "add", "rm", "on", "off"):
        assert sub in out


def test_comandi_di_oggi_funzionano_ancora(run):
    for args in (["list"], ["stats"], ["schedule", "status"]):
        run(*args, ok=True)


def test_launcher_jh_da_processo_vero(home):
    """Il vero ./jh (processo separato) con JOBSHUNTER_HOME temporanea: nessun dato dell'utente toccato."""
    if not (ROOT / ".venv" / "bin" / "python").exists():
        pytest.skip("il launcher ./jh usa la .venv del progetto: nessuna .venv in questo clone")
    env = dict(os.environ, JOBSHUNTER_HOME=str(home))
    proj_db = ROOT / "jobshunter.db"
    before = proj_db.stat().st_mtime if proj_db.exists() else None
    r = subprocess.run([str(ROOT / "jh"), "profiles", "list"], capture_output=True, text=True, env=env, timeout=60, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr[-400:]
    assert "Cybersecurity" in r.stdout
    assert (home / "jobshunter.db").exists()
    assert (proj_db.stat().st_mtime if proj_db.exists() else None) == before, "il db del progetto non va toccato"
