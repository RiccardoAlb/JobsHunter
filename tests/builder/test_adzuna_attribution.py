"""Attribuzione Adzuna ("Jobs by Adzuna") e interruttore del testo completo (home temporanea, nessuna rete)."""
import csv
import re
from pathlib import Path

import pytest

from cvguard import _cv_guardia  # noqa: F401  (autouse: home temporanea, niente rete)
from jobshunter import availability, report, settings
from jobshunter.db import DB

H = {"Host": "127.0.0.1:8765"}
HTML = (Path(__file__).parent.parent.parent / "jobshunter" / "gui" / "static" / "index.html").read_text(encoding="utf-8")


@pytest.fixture
def client(home):
    from jobshunter.gui.app import create_app

    return create_app(None, 8765).test_client()


@pytest.fixture
def dbx(client, home):
    c = settings.load_config()
    return DB(settings.resolve_path(c["general"]["db_path"]))


def add(db, uid, source, title="Analista", full=""):
    db.conn.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, full_text, score, category, matched, first_seen, avail, avail_checked) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (uid, source, title, "Acme", "Roma", "https://example.org/" + uid, "Descrizione " * 40, full, 50, "BLUE", "",
                                                           "2026-01-01T00:00:00+00:00", "open", "2099-01-01T00:00:00+00:00"))
    db.conn.commit()


def test_api_segnala_gli_annunci_adzuna(client, dbx):
    add(dbx, "a" * 10, "adzuna", "Da Adzuna")
    add(dbx, "b" * 10, "arbeitnow", "Altra fonte")
    add(dbx, "c" * 10, "jooble:it", "Da Jooble")
    jobs = {j["title"]: j for j in client.get("/api/jobs?group=all", headers=H).get_json()}
    assert jobs["Da Adzuna"]["adzuna"] is True
    assert jobs["Altra fonte"]["adzuna"] is False and jobs["Da Jooble"]["adzuna"] is False


def test_scheda_annuncio_ha_il_flag(client, dbx, monkeypatch):
    monkeypatch.setattr(availability, "checkable", lambda *a, **k: False)
    add(dbx, "abcdef1234", "adzuna")
    assert client.get("/api/job/abcdef1234", headers=H).get_json()["adzuna"] is True


def test_etichetta_nella_pagina_rispetta_le_regole():
    assert 'const ADZUNA_URL = "https://www.adzuna.co.uk"' in HTML
    m = re.search(r"a\.adz \{([^}]*)\}", HTML)
    css = m.group(1)
    assert "min-width: 116px" in css and "min-height: 23px" in css
    badge = re.search(r"const adzunaBadge = .*", HTML).group(0)
    assert 'rel: "noopener noreferrer"' in badge and 'target: "_blank"' in badge and "href: ADZUNA_URL" in badge
    assert "Jobs by" in badge and "Adzuna" in badge
    assert "j.adzuna ? adzunaBadge()" in HTML                       # lista e scheda
    assert HTML.count("adzunaBadge()") >= 3                         # lista, scheda, informazioni
    assert "<img" not in badge and "adzuna.co.uk/" not in re.sub(r"https://www\.adzuna\.co\.uk", "", HTML.replace("adzuna.co.uk/press.html", ""))


def test_nessun_logo_adzuna_nel_repository():
    root = Path(__file__).parent.parent.parent
    names = [p.name.lower() for p in root.rglob("*") if p.is_file() and ".venv" not in p.parts and ".git" not in p.parts and "__pycache__" not in p.parts]
    assert not [n for n in names if "adzuna" in n and n.endswith((".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp"))]


def test_report_markdown_con_etichetta_solo_per_adzuna(dbx):
    add(dbx, "a" * 10, "adzuna", "Da Adzuna")
    add(dbx, "b" * 10, "arbeitnow", "Altra fonte")
    rows = dbx.query(min_score=0, limit=10)
    md = report.render(rows, title="Prova")
    assert md.count("[Jobs by Adzuna](https://www.adzuna.co.uk)") >= 2
    only_other = report.render([r for r in rows if r["source"] == "arbeitnow"], title="Prova")
    assert "Adzuna" not in only_other


def test_export_csv_con_attribuzione(home, dbx):
    from click.testing import CliRunner

    from jobshunter.cli import main

    add(dbx, "a" * 10, "adzuna", "Da Adzuna")
    add(dbx, "b" * 10, "arbeitnow", "Altra fonte")
    out = home / "x.csv"
    assert CliRunner().invoke(main, ["export", str(out)]).exit_code == 0
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    by = {r["title"]: r for r in rows}
    assert by["Da Adzuna"]["attribution"] == "Jobs by Adzuna (https://www.adzuna.co.uk)" and by["Altra fonte"]["attribution"] == ""


# ---------------------------------------------------------------- interruttore del testo completo ----
def test_interruttore_predefinito_attivo_e_visibile_nelle_impostazioni(client):
    f = {x["key"]: x for x in client.get("/api/settings", headers=H).get_json()["fields"]}
    assert f["sources.adzuna.full_text"]["value"] is True
    assert f["sources.adzuna.full_text"]["label"] == "Scarica il testo completo degli annunci Adzuna"
    assert 'row("sources.adzuna.full_text")' in HTML


def test_interruttore_si_salva_e_spegne_le_pagine_adzuna(client, monkeypatch):
    r = client.post("/api/settings", json={"values": {"sources.adzuna.full_text": False}}, headers=H)
    assert r.status_code == 200
    f = {x["key"]: x for x in client.get("/api/settings", headers=H).get_json()["fields"]}
    assert f["sources.adzuna.full_text"]["value"] is False
    cfg = settings.load_config()
    assert availability.checkable("adzuna", "https://www.adzuna.it/x", cfg) is False
    assert availability.checkable("arbeitnow", "https://example.org/x", cfg) is True
    assert availability.checkable("adzuna", "https://www.adzuna.it/x") is True   # senza configurazione: attivo


def test_con_interruttore_spento_nessuna_richiesta_adzuna(client, dbx, monkeypatch):
    add(dbx, "abcdef1234", "adzuna")
    client.post("/api/settings", json={"values": {"sources.adzuna.full_text": False}}, headers=H)

    def boom(*a, **k):
        raise AssertionError("richiesta di rete vietata")

    monkeypatch.setattr(availability, "check", boom)
    dbx.conn.execute("UPDATE jobs SET avail_checked=NULL, avail='unknown'")
    dbx.conn.commit()
    assert client.get("/api/job/abcdef1234", headers=H).status_code == 200
    r = client.post("/api/job/abcdef1234/check", headers=H).get_json()
    assert r["ok"] is False
    cfg = settings.load_config()
    assert availability.run_check(dbx, cfg, force=True)["total"] == 0


def test_con_interruttore_acceso_il_comportamento_resta(client, dbx, monkeypatch):
    add(dbx, "abcdef1234", "adzuna")
    dbx.conn.execute("UPDATE jobs SET avail_checked=NULL, avail='unknown'")
    dbx.conn.commit()
    calls = []

    def fake(c, url, source):
        calls.append(url)
        return availability.Result(availability.OPEN, "ok")

    monkeypatch.setattr(availability, "check", fake)
    client.get("/api/job/abcdef1234", headers=H)
    assert calls == ["https://example.org/abcdef1234"]


def test_frase_senza_licenza_non_dice_software_libero():
    root = Path(__file__).parent.parent.parent
    for f in ("README.md", "README.en.md", "jobshunter/gui/static/index.html"):
        t = (root / f).read_text(encoding="utf-8").lower()
        assert "software libero" not in t and "free software" not in t, f
    assert "strumento personale, senza garanzie" in (root / "README.md").read_text(encoding="utf-8").lower() or "senza garanzie" in HTML


def test_readme_hanno_la_riga_adzuna_con_i_termini():
    root = Path(__file__).parent.parent.parent
    for f in ("README.md", "README.en.md"):
        t = (root / f).read_text(encoding="utf-8")
        assert "https://developer.adzuna.com/docs/terms_of_service" in t and "adzuna.co.uk/press.html" in t and "full_text = false" in t
