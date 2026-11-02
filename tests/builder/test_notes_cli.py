"""Fase 10, blocco note: comandi `jh notes ...` con home temporanea (nessuna rete, nessun dato vero)."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from jobshunter import notes as N
from jobshunter import settings
from jobshunter.cli import main
from jobshunter.db import DB


@pytest.fixture
def env(tmp_path, home):
    cfg = settings.load_config(create_if_missing=True)
    reports = tmp_path / "Report CLI è"
    settings.save_overrides(Path(cfg["_config_path"]), {"report.dir": str(reports)})
    db = DB(settings.resolve_path(cfg["general"]["db_path"]))
    db.conn.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, score, category, matched, first_seen) "
                    "VALUES ('abcdef123456', 'adzuna', 'Analista SOC', 'Acme Srl', 'Milano', 'https://example.org/a', 'd', 50, 'BLUE', '', '2026-01-01T00:00:00+00:00')")
    db.conn.commit()
    return db, reports


def run(*args):
    return CliRunner().invoke(main, ["notes", *args])


def test_add_list_show(env):
    db, _ = env
    r = run("add", "--title", "Appunto del colloquio", "--body", "Chiedere dello smart working. 100% serio")
    assert r.exit_code == 0 and "nota n. 1 creata" in r.output
    r = run("list")
    assert r.exit_code == 0 and "Appunto del colloquio" in r.output and "nota" in r.output and "1 nota" in r.output
    r = run("show", "1")
    assert r.exit_code == 0 and "Appunto del colloquio" in r.output and "Chiedere dello smart working. 100% serio" in r.output


def test_list_vuoto_e_ricerca(env):
    assert "Nessuna nota" in run("list").output
    run("add", "--title", "Uno", "--body", "mela")
    run("add", "--title", "Due", "--body", "pera [rosso]")
    out = run("list", "--q", "PERA").output
    assert "Due" in out and "Uno" not in out
    assert "Nessuna nota" in run("list", "--q", "banana").output
    assert "[rosso]" in run("show", "2").output  # le parentesi quadre del testo non sono interpretate come stile


def test_lettera_dal_modello_con_i_dati_dell_annuncio(env):
    db, _ = env
    r = run("add", "--letter", "--job", "abcdef")  # basta l'inizio dell'ID
    assert r.exit_code == 0 and "lettera n. 1 creata" in r.output
    n = db.get_note(1)
    assert n["kind"] == "letter" and n["job_uid"] == "abcdef123456" and n["title"] == "Lettera per Acme Srl, Analista SOC" and "Acme Srl" in n["body"]
    assert "Lettera per Acme Srl" in run("list", "--job", "abcdef").output
    assert run("add", "--letter").exit_code == 1  # serve l'annuncio
    r = run("add", "--letter", "--job", "zzzz")
    assert r.exit_code == 1 and "ID non trovato" in r.output


def test_errori_chiari_in_italiano(env):
    assert run("add").exit_code == 1
    r = run("add", "--title", "t" * 201)
    assert r.exit_code == 1 and "Titolo troppo lungo" in r.output
    r = run("add", "--body", "b" * 100_001)
    assert r.exit_code == 1 and "Testo troppo lungo" in r.output
    r = run("show", "99")
    assert r.exit_code == 1 and "Nota non trovata" in r.output
    assert run("show", "abc").exit_code == 2  # non e' un numero
    assert run("export", "99").exit_code == 1


def test_export_una_o_tutte_senza_sovrascrivere(env):
    db, reports = env
    run("add", "--title", "Prima", "--body", "uno")
    run("add", "--title", "Prima", "--body", "due")
    r = run("export", "1")
    assert r.exit_code == 0 and str(reports / "Note" / "Prima.md") in r.output.replace("\n", "")
    r = run("export")
    assert r.exit_code == 0
    assert sorted(p.name for p in (reports / "Note").iterdir()) == ["Prima-2.md", "Prima-3.md", "Prima.md"]
    assert (reports / "Note" / "Prima.md").read_text(encoding="utf-8").startswith("---\ntitolo: Prima\ntipo: nota\n")


def test_export_senza_note(env):
    r = run("export")
    assert r.exit_code == 1 and "Nessuna nota da esportare" in r.output


def test_export_cartella_protetta(env, tmp_path):
    cfg = settings.load_config()
    import sys

    protected = "C:\\Windows\\System32" if sys.platform.startswith("win") else "/etc"
    settings.save_overrides(Path(cfg["_config_path"]), {"report.dir": protected})
    run("add", "--title", "x")
    r = run("export")
    assert r.exit_code == 1 and "report" in r.output
    assert not Path(protected, "Note").exists()


def test_template_mostra_e_ripristina(env):
    out = run("template").output
    assert "Modello predefinito" in out and "{azienda}" in out and "{company}" in out
    cfg = settings.load_config()
    settings.save_overrides(Path(cfg["_config_path"]), {N.TEMPLATE_KEY: "Ciao {azienda}"})
    out = run("template").output
    assert "Modello personalizzato" in out and "Ciao {azienda}" in out
    r = run("template", "--reset")
    assert r.exit_code == 0 and "ripristinato" in r.output
    assert "Modello predefinito" in run("template").output


def test_la_candidatura_dal_cli_porta_le_note(env):
    db, _ = env
    run("add", "--title", "prima", "--job", "abcdef")
    r = CliRunner().invoke(main, ["mark", "abcdef", "applied"])
    assert r.exit_code == 0
    n = db.get_note(1)
    assert n["app_id"] == db.conn.execute("SELECT id FROM applications").fetchone()[0]
