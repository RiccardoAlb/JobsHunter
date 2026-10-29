"""B3/B4 con PROCESSI separati (come app + scansione pianificata): apertura DB e creazione profili in parallelo."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.phase2
ROOT = Path(__file__).resolve().parent.parent.parent

OPEN = "from jobshunter.db import DB; from jobshunter import settings; c=settings.load_config(create_if_missing=True); DB(settings.resolve_path(c['general']['db_path'])); print('ok')"
ADD = ("from jobshunter.gui.app import create_app; c=create_app(None,8765).test_client(); "
       "r=c.post('/api/profiles',headers={'Host':'127.0.0.1:8765'},json={'name':'Gemello','preset':'data'}); print(r.status_code)")


def run_many(code, home, n=6):
    env = dict(os.environ, JOBSHUNTER_HOME=str(home))
    ps = [subprocess.Popen([sys.executable, "-c", code], cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace") for _ in range(n)]
    return [(p.communicate(timeout=120), p.returncode) for p in ps]


@pytest.mark.parametrize("round_", range(4))
def test_apertura_db_nuovo_da_processi_paralleli(tmp_path, round_):
    home = tmp_path / "h"
    home.mkdir()
    res = run_many(OPEN, home)
    bad = [(o[1][-300:], rc) for o, rc in res if rc != 0]
    assert not bad, bad
    import sqlite3
    con = sqlite3.connect(home / "jobshunter.db")
    assert con.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 1, "profilo di default creato piu' volte"


@pytest.mark.parametrize("round_", range(3))
def test_creazione_stesso_nome_da_processi_paralleli(tmp_path, round_):
    home = tmp_path / "h"
    home.mkdir()
    res = run_many(OPEN, home, 1)  # DB gia' pronto
    res = run_many(ADD, home)
    codes = [o[0].strip().splitlines()[-1] if o[0].strip() else "ERR:" + o[1][-200:] for o, rc in res]
    assert all(c in ("200", "400") for c in codes), codes
    assert codes.count("200") == 1, codes
