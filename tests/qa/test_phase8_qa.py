"""TESTER fase 8: prove avversarie su annunci salvati e tutorial (home temporanea, nessuna rete)."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from jobshunter import settings
from jobshunter.db import DB

H = {"Host": "127.0.0.1:8765"}
ROOT = Path(__file__).resolve().parent.parent.parent
HTML = (ROOT / "jobshunter" / "gui" / "static" / "index.html").read_text(encoding="utf-8")


@pytest.fixture
def client(home):
    from jobshunter.gui.app import create_app

    return create_app(None, 8765).test_client()


@pytest.fixture(autouse=True)
def _no_check(monkeypatch):
    from jobshunter import availability

    monkeypatch.setattr(availability, "checkable", lambda *a, **k: False)


@pytest.fixture
def dbx(client, home):
    c = settings.load_config()
    return DB(settings.resolve_path(c["general"]["db_path"]))


def add(db, uid, title="Ruolo", company="Acme", score=50, **extra):
    db.conn.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, score, category, matched, first_seen) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (uid, "adzuna", title, company, "Roma", "https://example.org/" + uid, "descrizione " * 10,
                                                      score, "BLUE", "", "2026-01-01T00:00:00+00:00"))
    for k, v in extra.items():
        db.conn.execute(f"UPDATE jobs SET {k}=? WHERE uid=?", (v, uid))
    db.conn.commit()


def sa(db, uid):
    return db.conn.execute("SELECT saved_at FROM jobs WHERE uid=?", (uid,)).fetchone()[0]


def saved_uids(client, **q):
    qs = "&".join(f"{k}={v}" for k, v in dict(q, saved=1).items())
    return {j["uid"] for j in client.get("/api/jobs?" + qs, headers=H).get_json()}


# ---------------------------------------------------------------- uid ostili ----
@pytest.mark.parametrize("uid", ["%25", "_", "%25%25", "u1%25", "a%2Fb", "..%2F..%2Fetc", "u1%00", "%F0%9F%98%80", "x" * 3000, "U1", " u1", "u1 "])
def test_save_uid_ostili_non_toccano_altri_annunci(client, dbx, uid):
    add(dbx, "u1")
    add(dbx, "u_2")
    for verb in ("save", "unsave"):
        r = client.post(f"/api/jobs/{uid}/{verb}", json={}, headers=H)
        assert r.status_code in (404, 405, 400, 414), (uid, verb, r.status_code)
    assert sa(dbx, "u1") is None and sa(dbx, "u_2") is None


def test_save_unsave_metodo_get_e_corpo_non_json(client, dbx):
    add(dbx, "u1")
    assert client.get("/api/jobs/u1/save", headers=H).status_code == 405
    r = client.post("/api/jobs/u1/save", data=b"\xff\xfe not json", content_type="text/plain", headers=H)
    assert r.status_code < 500
    assert client.post("/api/jobs/u1/unsave", headers=H).status_code == 200


def test_protezioni_host_origin_sec_fetch_sulle_nuove_rotte(client, dbx):
    add(dbx, "u1")
    for verb in ("save", "unsave"):
        url = f"/api/jobs/u1/{verb}"
        assert client.post(url, headers={"Host": "evil.example"}).status_code == 403
        assert client.post(url, headers=dict(H, Origin="https://evil.example")).status_code == 403
        assert client.post(url, headers=dict(H, Origin="null")).status_code == 403
        assert client.post(url, headers=dict(H, **{"Sec-Fetch-Site": "cross-site"})).status_code == 403
        assert client.post(url, headers=dict(H, **{"Sec-Fetch-Site": "same-site"})).status_code == 403
        assert client.post(url, headers=dict(H, **{"Transfer-Encoding": "chunked"})).status_code == 413
    assert client.post("/api/tutorial/seen", json={"seen": True}, headers=dict(H, Origin="https://evil.example")).status_code == 403
    assert client.post("/api/tutorial/seen", json={"seen": True}, headers={"Host": "evil.example"}).status_code == 403
    assert sa(dbx, "u1") is None


def test_stato_tutorial_valori_strani(client, dbx):
    for body in ({"seen": "false"}, {"seen": 0}, {"seen": None}, [1], "x"):
        r = client.post("/api/tutorial/seen", json=body, headers=H)
        assert r.status_code in (200, 400), body
    r = client.post("/api/tutorial/seen", data="{", content_type="application/json", headers=H)
    assert r.status_code < 500
    assert client.post("/api/tutorial/seen", json={"seen": False}, headers=H).get_json()["tutorial_seen"] is False
    assert client.get("/api/onboarding", headers=H).get_json()["tutorial_seen"] is False


# ---------------------------------------------------------------- duplicati ----
def _pair(dbx, saved=("hid",)):
    add(dbx, "keep")
    add(dbx, "hid")
    for u in saved:
        dbx.save_job(u)
    dbx.upsert_dup("keep", "hid", 80, "keep", "hid")
    return dbx.list_dups("pending")[0]["id"]


def test_B111_togliere_il_salvataggio_poi_annullare_la_coppia_non_fa_riapparire_un_salvato(dbx):
    """L'utente salva A (poi nascosto come duplicato), toglie il segnalibro dal tenuto, annulla la coppia: A non deve tornare tra i Salvati."""
    pid = _pair(dbx)
    dbx.set_dup_status(pid, "confirmed")
    assert dbx.saved_count() == 1
    dbx.unsave_job("keep")  # l'utente toglie il segnalibro dall'unico annuncio visibile
    assert dbx.saved_count() == 0
    dbx.set_dup_status(pid, "rejected")
    assert dbx.saved_count() == 0, "il nascosto era rimasto salvato e ora riappare"
    assert [r["uid"] for r in dbx.query(saved=True)] == []


def test_duplicato_entrambi_salvati_resta_il_piu_vecchio_e_nessun_errore(dbx):
    add(dbx, "k")
    add(dbx, "h")
    dbx.conn.execute("UPDATE jobs SET saved_at='2026-03-01T00:00:00+00:00' WHERE uid='k'")
    dbx.conn.execute("UPDATE jobs SET saved_at='2026-01-01T00:00:00+00:00' WHERE uid='h'")
    dbx.conn.commit()
    dbx.upsert_dup("k", "h", 90, "k", "h")
    pid = dbx.list_dups("pending")[0]["id"]
    dbx.set_dup_status(pid, "confirmed", swap=True)  # scambio: ora tiene h
    assert dbx.saved_count() == 1 and [r["uid"] for r in dbx.query(saved=True)] == ["h"]
    assert sa(dbx, "h") == "2026-01-01T00:00:00+00:00"


def test_duplicato_auto_confermato_con_uid_uguale_o_nullo(dbx):
    add(dbx, "k")
    dbx.save_job("k")
    dbx._merge_saved("k", "k")
    dbx._merge_saved(None, "k")
    assert dbx.saved_count() == 1


# ---------------------------------------------------------------- vista Salvati ----
def test_salvato_chiuso_e_di_profilo_spento_resta_in_elenco_e_conteggio(client, dbx):
    add(dbx, "c", avail="closed")
    dbx.save_job("c")
    assert saved_uids(client) == {"c"}
    assert client.get("/api/stats", headers=H).get_json()["saved"] == 1


def test_B112_il_ricalcolo_dei_profili_non_nasconde_i_salvati_nella_vista_di_un_profilo(client, dbx, home):
    """Dopo un ricalcolo un salvato non pertinente al profilo sparisce dalla vista Salvati di quel profilo (e dal suo conteggio)."""
    from jobshunter.profiles import ProfileStore
    from jobshunter.rescore import rescore

    add(dbx, "u1", title="Zzz Specialist", company="Acme")
    store = ProfileStore(dbx)
    p = store.list()[0]
    dbx.set_job_profile("u1", p.id, 70, "BLUE", [])
    dbx.commit()
    dbx.save_job("u1")
    assert saved_uids(client, profile=p.id) == {"u1"}
    rescore(dbx, settings.load_config(), [p.id])  # "Zzz Specialist" non e' pertinente: la riga di job_profiles sparisce
    assert saved_uids(client) == {"u1"}  # in "tutti" si vede ancora
    assert saved_uids(client, profile=p.id) == {"u1"}, "salvato sparito dalla vista Salvati del profilo"
    assert client.get(f"/api/stats?profile={p.id}", headers=H).get_json()["saved"] == 1


def test_filtro_saved_con_valori_strani(client, dbx):
    add(dbx, "u1")
    dbx.save_job("u1")
    for v in ("0", "", "true", "1;DROP", "%25"):
        r = client.get(f"/api/jobs?saved={v}", headers=H)
        assert r.status_code == 200


def test_ordine_salvati_stessa_data(client, dbx):
    for u in ("a", "b", "c"):
        add(dbx, u)
        dbx.conn.execute("UPDATE jobs SET saved_at='2026-01-01T00:00:00+00:00' WHERE uid=?", (u,))
    dbx.conn.commit()
    assert len(client.get("/api/jobs?saved=1", headers=H).get_json()) == 3


# ---------------------------------------------------------------- scarto ----
def test_B113_la_cli_mark_discarded_non_fa_sparire_in_silenzio_un_salvato(dbx, home):
    from click.testing import CliRunner
    from jobshunter.cli import main

    add(dbx, "abc123")
    dbx.save_job("abc123")
    res = CliRunner().invoke(main, ["mark", "abc123", "discarded"])
    still = dbx.query(saved=True)
    # o rifiuta/chiede conferma, oppure toglie esplicitamente il salvataggio: non puo' restare salvato e invisibile
    assert res.exit_code != 0 or sa(dbx, "abc123") is None or len(still) == 1, "salvato e scartato: invisibile nei Salvati"


def test_scarto_con_unsave_non_booleano(client, dbx):
    add(dbx, "u1")
    dbx.save_job("u1")
    for v in ("true", 1, "1", None, []):
        r = client.post("/api/job/u1/status", json={"status": "discarded", "unsave": v}, headers=H)
        assert r.status_code == 409, v
    assert sa(dbx, "u1")
    r = client.post("/api/job/u1/status", json={"status": "discarded", "unsave": True}, headers=H)
    assert r.status_code == 200 and sa(dbx, "u1") is None


def test_salvato_candidato_poi_scarto_e_riapertura(client, dbx):
    add(dbx, "u1")
    dbx.save_job("u1")
    assert client.post("/api/job/u1/status", json={"status": "applied"}, headers=H).status_code == 200
    assert saved_uids(client) == {"u1"}
    assert client.post("/api/job/u1/status", json={"status": "discarded"}, headers=H).status_code == 409
    assert client.post("/api/job/u1/status", json={"status": "seen"}, headers=H).status_code == 200


# ---------------------------------------------------------------- concorrenza ----
def test_salvataggi_concorrenti(client, home, dbx):
    import threading

    for i in range(6):
        add(dbx, f"u{i}")
    res = []

    def go(u, verb):
        from jobshunter.gui.app import create_app

        c = create_app(None, 8765).test_client()
        res.append(c.post(f"/api/jobs/{u}/{verb}", json={}, headers=H).status_code)

    ts = [threading.Thread(target=go, args=(f"u{i % 3}", "save" if i % 2 == 0 else "unsave")) for i in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert all(c == 200 for c in res), res


# ---------------------------------------------------------------- migrazione ----
def test_migrazione_db_molto_vecchio_e_api(tmp_path, monkeypatch):
    """DB creato prima di quasi tutte le colonne: la GUI parte, elenca e salva."""
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path / "h"))
    (tmp_path / "h").mkdir()
    c = settings.load_config(create_if_missing=True)
    p = settings.resolve_path(c["general"]["db_path"])
    con = sqlite3.connect(p)
    con.executescript("CREATE TABLE jobs (uid TEXT PRIMARY KEY, source TEXT, title TEXT, company TEXT, location TEXT, url TEXT, description TEXT,"
                      " posted_at TEXT, remote INTEGER, score INTEGER, category TEXT, matched TEXT, status TEXT DEFAULT 'new', notified INTEGER DEFAULT 0, first_seen TEXT);"
                      "INSERT INTO jobs (uid,source,title,company,location,url,description,score,category,matched,first_seen) VALUES "
                      "('old1','adzuna','Vecchio','Acme','Roma','https://example.org/1','d',60,'BLUE','','2025-01-01');")
    con.commit()
    con.close()
    from jobshunter.gui.app import create_app

    cl = create_app(None, 8765).test_client()
    assert cl.get("/api/jobs", headers=H).status_code == 200
    assert cl.post("/api/jobs/old1/save", json={}, headers=H).status_code == 200
    assert {j["uid"] for j in cl.get("/api/jobs?saved=1", headers=H).get_json()} == {"old1"}
    assert cl.get("/api/stats", headers=H).get_json()["saved"] == 1


def test_esportazione_csv_con_titolo_pericoloso_e_salvato(dbx, home):
    import csv

    from click.testing import CliRunner
    from jobshunter.cli import main

    add(dbx, "u1", title="=HYPERLINK(\"http://x\")", company="@cmd")
    dbx.save_job("u1")
    out = home / "e.csv"
    assert CliRunner().invoke(main, ["export", str(out)]).exit_code == 0
    row = next(csv.DictReader(out.open(encoding="utf-8")))
    assert not row["title"].startswith("=") and not row["company"].startswith("@")


# ---------------------------------------------------------------- pagina ----
def test_pagina_senza_cdn_ne_html_iniettato_dai_titoli():
    assert not re.search(r"(src|href)=[\"']https?://", HTML)
    # i titoli entrano solo come testo: nessun innerHTML/insertAdjacentHTML nel codice di Salvati e tutorial
    seg = HTML[HTML.index("/* ---- segnalibro"):HTML.index("/* ---- guida di primo avvio")]
    assert "innerHTML" not in seg and "insertAdjacentHTML" not in seg and "document.write" not in seg


# ---------------------------------------------------------------- bug trovati (verdi dopo la correzione) ----
def _fn(name: str, nxt: str = "\nfunction ") -> str:
    i = HTML.index(name)
    j = HTML.find(nxt, i + 10)
    return HTML[i:j if j > 0 else len(HTML)]


def test_B114_il_testo_di_elenco_vuoto_nei_salvati_non_nega_i_salvati_se_ci_sono_filtri():
    """Con un filtro attivo (Solo nuovi, categoria, score, ricerca) Salvati (1) mostra 'Nessun annuncio salvato': falso."""
    body = _fn("function renderRows()")
    empty = body[body.index('$("empty").textContent'):][:400]
    assert re.search(r"savedCount|filtr", empty, re.I), "il messaggio non distingue 'nessun salvato' da 'nessun salvato con questi filtri'"


def test_B115_con_il_tutorial_aperto_le_scorciatoie_j_k_esc_della_lista_non_agiscono():
    """j/k aprono (e segnano 'visto') l'annuncio dietro il fumetto, Esc chiude il pannello: il gestore globale guarda solo OB."""
    i = HTML.index('document.addEventListener("keydown", (e) => {\n  if (e.target.tagName === "INPUT"')
    guard = HTML[i:i + 400]
    assert "TOUR" in guard or "tourOpen" in guard


def test_B116_due_clic_veloci_sul_segnalibro_non_mandano_richieste_fuori_ordine():
    """Tre clic in 0 ms mandano save/unsave/save in parallelo: il server puo' finire in uno stato diverso da quello mostrato (visto 2 volte su 15)."""
    body = HTML[HTML.index("async function toggleSave"):HTML.index("/* ---- drawer")]
    assert re.search(r"inflight|in_flight|pending|busy|saving|queue|chain|lock|disabled", body, re.I), "nessuna serializzazione per annuncio"


def test_B117_la_ricerca_con_percentuale_o_trattino_basso_non_e_un_jolly(client, dbx):
    add(dbx, "u1", title="Analista SOC", company="Acme")
    for q in ("%25", "_", "A_alista"):
        r = client.get(f"/api/jobs?q={q}", headers=H).get_json()
        assert r == [], f"q={q!r} trova {len(r)} annunci"


def test_B118_i_readme_non_usano_salvato_per_due_cose_diverse():
    """Dalla fase 8 'salvato' vuol dire 'con segnalibro': README parla ancora di annunci 'gia' salvati' per quelli in archivio."""
    for name, bad in (("README.md", r"già salvati"), ("README.en.md", r"already saved|profile's saved postings")):
        t = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(bad, t, re.I), name
