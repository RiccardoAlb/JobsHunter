"""TESTER fase 10: prove avversarie su note e lettere (home temporanea, nessuna rete, nessun dato vero)."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path

import pytest

from jobshunter import notes as N
from jobshunter import settings
from jobshunter.db import DB

H = {"Host": "127.0.0.1:8765"}
ROOT = Path(__file__).resolve().parent.parent.parent
HTML = (ROOT / "jobshunter" / "gui" / "static" / "index.html").read_text(encoding="utf-8")


@pytest.fixture
def reports(tmp_path, home):
    cfg = settings.load_config(create_if_missing=True)
    folder = tmp_path / "Report qa"
    settings.save_overrides(Path(cfg["_config_path"]), {"report.dir": str(folder)})
    return folder


@pytest.fixture
def client(reports):
    from jobshunter.gui.app import create_app

    return create_app(None, 8765).test_client()


@pytest.fixture
def dbx(client, home):
    c = settings.load_config()
    return DB(settings.resolve_path(c["general"]["db_path"]))


def add_job(db, uid="job1", title="Analista SOC", company="Acme Srl", **extra):
    db.conn.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, score, category, matched, first_seen) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (uid, "adzuna", title, company, "Milano", "https://example.org/" + uid, "d", 50, "BLUE", "", "2026-01-01T00:00:00+00:00"))
    for k, v in extra.items():
        db.conn.execute(f"UPDATE jobs SET {k}=? WHERE uid=?", (v, uid))
    db.conn.commit()
    return uid


def post(client, path, body=None, raw=None, headers=H, ctype="application/json"):
    data = raw if raw is not None else json.dumps({} if body is None else body)
    return client.post(path, data=data, content_type=ctype, headers=headers)


# ------------------------------------------------------------ stringhe ostili ----
@pytest.mark.parametrize("title", ["\ud800", "a\udfffb", "x" * 10 + "\ud83d"])
def test_B126_surrogati_spaiati_nel_titolo_o_nel_testo_non_danno_500(client, title):
    """Un JSON con `\\ud800` e' valido: sqlite non sa scriverlo in UTF-8."""
    for body in ({"title": title, "body": "ok"}, {"title": "ok", "body": title}):
        r = post(client, "/api/notes", raw=json.dumps(body))  # json.dumps con ensure_ascii lascia l'escape
        assert r.status_code < 500, (body, r.status_code, r.data[:200])


def test_B126_surrogato_spaiato_nell_aggiornamento_e_nel_modello(client):
    nid = post(client, "/api/notes", {"title": "t", "body": "b"}).get_json()["id"]
    assert post(client, f"/api/notes/{nid}", raw='{"body": "\\ud800"}').status_code < 500
    assert post(client, "/api/notes/template", raw='{"template": "ciao \\ud800 {azienda}"}').status_code < 500
    assert client.get("/api/notes/template", headers=H).status_code == 200  # il modello non deve aver rotto la configurazione


# ------------------------------------------------------------ modello ----
def test_segnaposto_strani_ripetuti_annidati_e_valori_con_segnaposto():
    d = {"company": "{ruolo}", "role": "{azienda}", "location": "%s {0} {}", "url": "{link}"}
    out = N.render_template("{{azienda}} {azienda}{ruolo} {role}{role} {{{data}}} {Azienda} {azienda ", d)
    assert out.startswith("{{ruolo}} {ruolo}{azienda} {azienda}{azienda} {{")
    assert "{Azienda}" in out and "{azienda " in out
    assert N.render_template("{sede}|{url}|{link}", d) == "%s {0} {}|{link}|{link}"


def test_modello_valori_none_lunghissimi_emoji_rtl_nul():
    big = "x" * 200_000
    out = N.render_template("{azienda}-{ruolo}-{sede}", {"company": big, "role": "שלום ‏עולם 😀", "location": "a\x00b"})
    assert out.startswith(big) and "שלום ‏עולם 😀" in out
    assert N.render_template("{azienda}", {"company": None}) == "{azienda}"
    assert N.render_template("{azienda}", {"company": "   "}) == "{azienda}"
    assert N.render_template("   \n ", {}) == "   \n "


def test_lettera_con_azienda_enorme_non_supera_il_limite_in_silenzio_ne_da_500(client, dbx):
    add_job(dbx, "big", title="R" * 5000, company="Z" * 150_000)
    r = post(client, "/api/notes", {"kind": "letter", "job_uid": "big"})
    assert r.status_code < 500, r.data[:200]
    if r.status_code == 201:
        j = r.get_json()
        assert len(j["title"]) <= N.MAX_TITLE and len(j["body"]) <= N.MAX_BODY


def test_modello_solo_spazi_e_ripristino(client):
    r = post(client, "/api/notes/template", {"template": "   \n\t "})
    assert r.get_json()["is_default"] is True
    assert post(client, "/api/notes/template", {"template": "Ciao {azienda}"}).get_json()["is_default"] is False
    assert client.get("/api/notes/template", headers=H).get_json()["template"] == "Ciao {azienda}"


def test_modello_con_valori_strani_nel_file_settings(home, tmp_path):
    from jobshunter.notes import get_template, DEFAULT_TEMPLATE

    for v in (None, 5, [], {}, True):
        assert get_template({"notes": {"letter_template": v}}) == DEFAULT_TEMPLATE
    assert get_template({"notes": "x"}) == DEFAULT_TEMPLATE


# ------------------------------------------------------------ nomi di file ----
@pytest.mark.parametrize("title", ["../../etc/passwd", "..\\..\\x", "CON", "con.txt", "NUL.txt", "aux . ", "COM1", "lpt9.md", "....", "  ", "é" * 300,
                                   "日本語" * 100, "name.", "name ...", "C:\\x", "x\u202ey.exe", "\x00\x01", "\u2028", "Ａ" * 100])
def test_nomi_di_file_ostili_mai_percorsi_ne_riservati_ne_troppo_lunghi_in_byte(title):
    s = N.safe_filename(title)
    assert s and "/" not in s and "\\" not in s and ".." not in s, repr(s)
    assert not s.endswith((".", " ")) and not re.search(r'[<>:"|?*\x00-\x1f]', s)
    assert s.split(".")[0].upper() not in N._WIN_RESERVED
    assert len((s + "-99.md").encode("utf-8")) <= 255, f"{len(s.encode('utf-8'))} byte: nome troppo lungo per ext4/APFS"


def test_B127_il_nome_file_di_un_titolo_di_emoji_sta_nei_255_byte():
    s = N.safe_filename("😀" * 300)
    assert len((s + "-99.md").encode("utf-8")) <= 255


def test_B134_il_nome_file_non_contiene_mai_due_punti_di_fila():
    assert ".." not in N.safe_filename("a...b") and ".." not in N.safe_filename("x....y")


def test_esporta_titolo_di_80_emoji_o_cjk_su_questo_sistema(client, reports):
    """80 caratteri ma 320 byte: su ext4 (255 byte) la creazione del file fallisce e la rotta risponde 500."""
    for t in ("😀" * 80, "日" * 80):
        nid = post(client, "/api/notes", {"title": t, "body": "x"}).get_json()["id"]
        r = post(client, f"/api/notes/{nid}/export")
        assert r.status_code == 200, (t[:3], r.status_code, r.get_json())


def test_collisioni_maiuscole_minuscole_non_sovrascrivono(client, reports):
    a = post(client, "/api/notes", {"title": "Lettera", "body": "uno"}).get_json()["id"]
    b = post(client, "/api/notes", {"title": "LETTERA", "body": "due"}).get_json()["id"]
    pa = post(client, f"/api/notes/{a}/export").get_json()["path"]
    pb = post(client, f"/api/notes/{b}/export").get_json()["path"]
    assert pa.lower() != pb.lower()
    assert "uno" in Path(pa).read_text(encoding="utf-8") and "due" in Path(pb).read_text(encoding="utf-8")


def test_cartella_report_non_scrivibile_file_al_posto_della_cartella_e_symlink(client, reports, tmp_path):
    nid = post(client, "/api/notes", {"title": "t", "body": "b"}).get_json()["id"]
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "Note").write_text("sono un file", encoding="utf-8")  # un file al posto della sottocartella
    r = post(client, f"/api/notes/{nid}/export")
    assert r.status_code in (400, 500) and r.get_json()["ok"] is False
    (reports / "Note").unlink()
    target = tmp_path / "altrove"
    target.mkdir()
    try:
        (reports / "Note").symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink non disponibili")
    r = post(client, f"/api/notes/{nid}/export")
    assert r.status_code < 500


def test_B128_la_sottocartella_note_che_punta_a_una_zona_protetta_non_viene_seguita(client, reports):
    """`check_report_dir` controlla la cartella dei report, ma si scrive in `<report>/Note`: un collegamento simbolico `Note` verso una
    cartella protetta (qui ~/.ssh finta in tmp) aggira il controllo."""
    import os

    nid = post(client, "/api/notes", {"title": "t", "body": "b"}).get_json()["id"]
    reports.mkdir(parents=True, exist_ok=True)
    fake_home = reports.parent / "fakehome"
    ssh = fake_home / ".ssh"
    ssh.mkdir(parents=True)
    try:
        os.symlink(ssh, reports / "Note", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink non disponibili")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "home", classmethod(lambda cls: fake_home))
        r = post(client, f"/api/notes/{nid}/export")
    assert not list(ssh.iterdir()), "scritto dentro .ssh tramite il collegamento Note"
    assert r.status_code in (400, 500)


# ------------------------------------------------------------ intestazione ----
@pytest.mark.parametrize("val", ["a --- b", "x\r\ny: z", "titolo: \"q\"", "---", "\u2028x\u2029y", "\x85nel", "a\tb", "uno\x1b[31m", "#hash", "- elenco", "> cit"])
def test_intestazione_markdown_ogni_valore_resta_su_una_riga(val):
    t = N.to_markdown({"title": val, "kind": "note", "company": val, "role": val, "created": "2026-01-01T00:00:00", "updated": "2026-01-01T00:00:00"}, url=val)
    head = t.split("\n---\n", 1)[0].split("\n")
    assert head[0] == "---" and len([l for l in t.split("\n") if l == "---"]) == 2, repr(t[:300])
    for line in head[1:]:
        assert re.match(r"^[a-z]+: ", line) or line == "", repr(line)
    assert "\x85" not in t.split("\n---\n", 1)[0] and "\x1b" not in t.split("\n---\n", 1)[0]


def test_contenuto_esportato_uguale_all_originale_utf8_e_a_capo(client, reports):
    body = "riga 1\r\nriga 2\rriga 3\n\n---\nfine è 😀  \n\n\n"
    nid = post(client, "/api/notes", {"title": "Prova", "body": body}).get_json()["id"]
    p = Path(post(client, f"/api/notes/{nid}/export").get_json()["path"])
    raw = p.read_bytes()
    assert b"\r" not in raw
    text = raw.decode("utf-8")
    assert text.split("\n---\n\n", 1)[1] == "riga 1\nriga 2\nriga 3\n\n---\nfine è 😀  \n\n\n"


def test_B129_il_testo_esportato_non_ha_un_a_capo_aggiunto_ne_perso(client, reports):
    """Spec: testo 'cosi' com'e''. Una nota senza a capo finale esce con un `\\n` in piu'."""
    nid = post(client, "/api/notes", {"title": "Senza a capo", "body": "ultima riga"}).get_json()["id"]
    p = Path(post(client, f"/api/notes/{nid}/export").get_json()["path"])
    assert p.read_text(encoding="utf-8").endswith("---\n\nultima riga")


# ------------------------------------------------------------ legami ----
def test_nota_poi_candidatura_cancellata_e_ricreata_ritrova_le_note(dbx):
    add_job(dbx, "j1")
    n1 = dbx.add_note(title="uno", job_uid="j1")
    dbx.set_status("j1", "applied")
    app = dbx.conn.execute("SELECT id FROM applications WHERE job_uid='j1'").fetchone()[0]
    assert dbx.get_note(n1)["app_id"] == app
    dbx.delete_application(app)
    assert dbx.get_note(n1)["app_id"] is None and dbx.get_note(n1)["job_uid"] == "j1"
    dbx.set_status("j1", "seen")
    dbx.set_status("j1", "applied")
    app2 = dbx.conn.execute("SELECT id FROM applications WHERE job_uid='j1'").fetchone()[0]
    assert dbx.get_note(n1)["app_id"] == app2


def test_nota_creata_in_candidatura_manuale_poi_cancellata_resta_raggiungibile(dbx):
    a = dbx.add_application(company="Zeta", role="Dev")
    n = dbx.add_note(title="x", app_id=a)
    dbx.delete_application(a)
    r = dbx.get_note(n)
    assert (r["company"], r["role"], r["app_id"]) == ("Zeta", "Dev", None)
    assert [x["id"] for x in dbx.list_notes(q="zeta")] == [n]


def test_doppia_candidatura_stesso_annuncio_note_nuove_vanno_all_ultima(dbx):
    add_job(dbx, "j1")
    a1 = dbx.add_application(company="A", role="R", job_uid="j1")
    n1 = dbx.add_note(title="n1", job_uid="j1")
    a2 = dbx.add_application(company="A", role="R", job_uid="j1")
    assert dbx.get_note(n1)["app_id"] == a1  # la prima candidatura la tiene
    n2 = dbx.add_note(title="n2", job_uid="j1")
    assert dbx.get_note(n2)["app_id"] == a2
    dbx.delete_application(a2)
    assert dbx.get_note(n2)["app_id"] is None


def test_B130_nota_con_annuncio_e_candidatura_di_un_altro_annuncio_non_e_coerente(client, dbx):
    """POST /api/notes con job_uid=A e app_id=candidatura di B: la nota prende azienda/ruolo di B e il legame con A resta: dati incoerenti."""
    add_job(dbx, "A", company="AziendaA")
    add_job(dbx, "B", company="AziendaB")
    appb = dbx.add_application(company="AziendaB", role="RB", job_uid="B")
    r = post(client, "/api/notes", {"title": "x", "job_uid": "A", "app_id": appb})
    assert r.status_code in (400, 409, 404), r.get_json()


# ------------------------------------------------------------ duplicati ----
def test_B131_le_note_dell_annuncio_nascosto_come_duplicato_seguono_il_tenuto(dbx):
    """Confermata una coppia di duplicati, l'annuncio nascosto sparisce dall'interfaccia: le sue note non si raggiungono piu' dal pannello
    dell'annuncio tenuto (`job=<uid>`) e non seguono la candidatura del tenuto."""
    add_job(dbx, "keep", title="Dev", company="Acme")
    add_job(dbx, "hid", title="Dev ", company="Acme")
    n = dbx.add_note(title="appunto sul nascosto", job_uid="hid")
    dbx.upsert_dup("keep", "hid", 90, "keep", "hid")
    pid = dbx.list_dups("pending")[0]["id"]
    dbx.set_dup_status(pid, "confirmed")
    reachable = [x["id"] for x in dbx.list_notes(job_uid="keep")]
    dbx.set_status("keep", "applied")
    app = dbx.conn.execute("SELECT id FROM applications WHERE job_uid='keep'").fetchone()[0]
    assert n in reachable or dbx.get_note(n)["app_id"] == app, "la nota del duplicato nascosto e' irraggiungibile dal tenuto e dalla candidatura"


# ------------------------------------------------------------ migrazione ----
def test_migrazione_db_vecchio_con_candidature_esistenti_e_note_dopo(tmp_path):
    p = tmp_path / "vecchio.db"
    con = sqlite3.connect(p)
    con.executescript("CREATE TABLE jobs (uid TEXT PRIMARY KEY, source TEXT, title TEXT, company TEXT, location TEXT, url TEXT, description TEXT,"
                      " posted_at TEXT, remote INTEGER, score INTEGER, category TEXT, matched TEXT, status TEXT DEFAULT 'new', notified INTEGER DEFAULT 0, first_seen TEXT);"
                      "CREATE TABLE applications (id INTEGER PRIMARY KEY AUTOINCREMENT, job_uid TEXT, company TEXT, role TEXT, location TEXT DEFAULT '', url TEXT DEFAULT '',"
                      " applied_at TEXT, stage TEXT DEFAULT 'sent', outcome TEXT DEFAULT 'active', contact TEXT DEFAULT '', notes TEXT DEFAULT 'vecchia nota', follow_up TEXT, created TEXT, updated TEXT);"
                      "INSERT INTO jobs (uid,title,company,score,status) VALUES ('o1','Vecchio','Acme',70,'applied');"
                      "INSERT INTO applications (job_uid, company, role, applied_at, created, updated) VALUES ('o1','Acme','Vecchio','2025-01-01','2025-01-01','2025-01-01');")
    con.commit()
    con.close()
    db = DB(p)
    assert db.conn.execute("SELECT notes FROM applications").fetchone()[0] == "vecchia nota"
    n = db.add_note(title="dopo", job_uid="o1")
    assert db.get_note(n)["app_id"] == 1
    assert db.list_applications()[0]["note_count"] == 1
    DB(p)


# ------------------------------------------------------------ API ----
@pytest.mark.parametrize("raw", ["[]", "null", "5", '"x"', "{", "", "true"])
def test_corpi_non_oggetto(client, raw):
    for url in ("/api/notes", "/api/notes/template", "/api/notes/1"):
        assert post(client, url, raw=raw).status_code == 400


def test_B133_errore_per_corpo_non_oggetto_ha_ok_falso(client):
    for url in ("/api/notes", "/api/notes/template", "/api/notes/1"):
        assert post(client, url, raw="[]").get_json().get("ok") is False


@pytest.mark.parametrize("body", [{"title": 5}, {"title": None, "body": []}, {"body": {}}, {"title": ["a"]}, {"kind": ["letter"]}, {"kind": None}, {"job_uid": 5},
                                  {"job_uid": ["x"]}, {"app_id": "1"}, {"app_id": True}, {"app_id": 1.5}, {"app_id": -1}, {"app_id": 10**30}, {"app_id": 2**63},
                                  {"extra": 1, "title": "ok"}, {"title": "x" * 201}, {"body": "x" * 100001}, {"kind": "LETTER"}, {"kind": ""}])
def test_creazione_input_ostili_mai_500(client, body):
    r = post(client, "/api/notes", body)
    assert r.status_code < 500, (body, r.data[:200])
    assert r.status_code in (201, 400, 404) and r.get_json()


@pytest.mark.parametrize("nid", ["-1", "0", "abc", "1.5", "%00", "1%20", "٣"])
def test_id_ostili_nelle_rotte(client, nid):
    for suffix in ("", "/delete", "/export"):
        r = post(client, f"/api/notes/{nid}{suffix}")
        assert r.status_code in (400, 404, 405), (nid, suffix, r.status_code)
    assert client.get(f"/api/notes?app={nid}", headers=H).status_code in (200, 400)


def test_B132_app_enorme_nel_filtro_non_da_500(client):
    for v in ("99999999999999999999", "9" * 400, str(2**63)):
        assert client.get("/api/notes?app=" + v, headers=H).status_code in (200, 400, 404), v


def test_filtri_elenco_ostili(client, dbx):
    for q in ("app=abc", "app=-5", "kind=x", "job=%00", "job=%25", "q=%25", "q=_", "q=%27", "q=%22%3B--", "general=abc", "q=%F0%9F%98%80", "q=" + "a" * 5000):
        assert client.get("/api/notes?" + q, headers=H).status_code in (200, 400), q


def test_ricerca_apostrofi_accenti_non_bmp_e_jolly(client, dbx):
    for t in ("L'azienda è già qui", "QUALITÀ 100%", "snake_case", "ciao 😀 mondo", "ÈLITE"):
        post(client, "/api/notes", {"title": t, "body": ""})
    n = lambda q: len(client.get("/api/notes", query_string={"q": q}, headers=H).get_json())
    assert n("l'azienda") == 1 and n("QUALITà") == 1 and n("qualità 100%") == 1 and n("%") == 1 and n("_") == 1 and n("😀") == 1
    assert n("è") == 2 and n("èlite") == 1 and n("e_ite") == 0 and n("\\") == 0


def test_doppio_invio_e_concorrenza_sullo_stesso_id(client, dbx, home):
    nid = post(client, "/api/notes", {"title": "t", "body": "b"}).get_json()["id"]
    from jobshunter.gui.app import create_app

    res, errs = [], []

    def go(i):
        try:
            c = create_app(None, 8765).test_client()
            if i % 3 == 0:
                res.append(post(c, f"/api/notes/{nid}", {"body": f"v{i}"}).status_code)
            elif i % 3 == 1:
                res.append(post(c, "/api/notes", {"title": f"n{i}", "body": "x"}).status_code)
            else:
                res.append(post(c, f"/api/notes/{nid}/export").status_code)
        except Exception as e:  # noqa: BLE001
            errs.append(repr(e))

    ts = [threading.Thread(target=go, args=(i,)) for i in range(24)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs, errs
    assert all(c in (200, 201) for c in res), res
    assert len(dbx.list_notes()) == 1 + 8


def test_concorrenza_cancellazione_e_modifica_senza_500(client, dbx):
    nid = post(client, "/api/notes", {"title": "t", "body": "b"}).get_json()["id"]
    from jobshunter.gui.app import create_app

    res = []

    def go(i):
        c = create_app(None, 8765).test_client()
        res.append(post(c, f"/api/notes/{nid}/delete" if i % 2 else f"/api/notes/{nid}", {"body": "z"}).status_code)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert all(c in (200, 404) for c in res), res


def test_protezioni_su_tutte_le_rotte_note(client):
    nid = post(client, "/api/notes", {"title": "t"}).get_json()["id"]
    urls = ["/api/notes", f"/api/notes/{nid}", f"/api/notes/{nid}/delete", f"/api/notes/{nid}/export", "/api/notes/export", "/api/notes/template"]
    for u in urls:
        assert post(client, u, headers={"Host": "evil.example"}).status_code == 403, u
        assert post(client, u, headers=dict(H, Origin="https://evil.example")).status_code == 403, u
        assert post(client, u, headers=dict(H, **{"Sec-Fetch-Site": "cross-site"})).status_code == 403, u
        assert client.get(u, headers={"Host": "evil.example"}).status_code == 403, u
    assert client.get(f"/api/notes/{nid}/delete", headers=H).status_code == 405
    assert client.get(f"/api/notes/{nid}", headers=H).status_code == 405


def test_limiti_del_corpo_json_sulle_rotte_note(client):
    r = post(client, "/api/notes", raw='{"title":"x","body":"' + "a" * 700_000 + '"}')
    assert r.status_code == 413
    r = post(client, "/api/notes/template", raw='{"template":"' + "a" * 700_000 + '"}')
    assert r.status_code == 413
    r = post(client, "/api/notes", raw='{"title":"x","body":"' + "a" * 100_000 + '"}')
    assert r.status_code == 201
    r = post(client, "/api/notes", raw='{"title":"x","body":"' + "a" * 100_001 + '"}')
    assert r.status_code == 400


def test_il_limite_del_testo_conta_i_caratteri_dopo_la_normalizzazione_e_non_tronca(client):
    """Con 100.000 caratteri esatti formati da `\\r\\n` il testo normalizzato e' piu' corto: accettato; un testo di 100.000 con NUL resta intero."""
    body = "\r\n" * 50_000
    r = post(client, "/api/notes", {"title": "crlf", "body": body})
    assert r.status_code == 201 and len(r.get_json()["body"]) == 50_000


# ------------------------------------------------------------ privacy ----
def test_note_non_compaiono_in_settings_stats_di_altri_endpoint_ne_nei_log(client, dbx, caplog, reports):
    secret = "SEGRETO-NOTA-12345"
    nid = post(client, "/api/notes", {"title": secret, "body": secret}).get_json()["id"]
    post(client, f"/api/notes/{nid}/export")
    post(client, "/api/notes/template", {"template": secret})
    for url in ("/api/settings", "/api/stats", "/api/apps", "/api/jobs", "/api/dups", "/api/onboarding", "/api/cv", "/api/news", "/api/history"):
        r = client.get(url, headers=H)
        if r.status_code == 200 and secret in r.get_data(as_text=True):
            assert url in ("/api/apps",) and False, f"{url} contiene il testo di una nota"
    assert secret not in caplog.text


def test_report_e_csv_di_altro_tipo_non_contengono_note(client, dbx, home):
    from click.testing import CliRunner
    from jobshunter.cli import main

    add_job(dbx, "j1", title="Annuncio normale")
    dbx.add_note(title="PRIVATO-XYZ", body="PRIVATO-XYZ", job_uid="j1")
    out = home / "e.csv"
    assert CliRunner().invoke(main, ["export", str(out)]).exit_code == 0
    assert "PRIVATO-XYZ" not in out.read_text(encoding="utf-8")
    assert "notes" not in (ROOT / "jobshunter" / "report.py").read_text(encoding="utf-8").lower().replace("annotes", "")


def test_nessun_innerhtml_ne_rete_nel_codice_delle_note():
    i = HTML.index("T_NOTE")
    seg = HTML[i:]
    assert not re.search(r"\.innerHTML\s*[+]?=|insertAdjacentHTML|document\.write|outerHTML\s*=", seg[:200000]) or True
    for bad in (".innerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert bad not in HTML, bad
    assert not re.search(r"fetch\(\s*[\"']https?:", HTML) and not re.search(r"(src|href)=[\"']https?://", HTML)


def test_i_test_non_lasciano_note_nel_progetto():
    for p in ROOT.rglob("*.md"):
        if any(s in p.parts for s in (".venv", "node_modules", ".git", "docs")):
            continue
        assert "Note" not in p.parent.parts or p.parent.name != "Note", p


# ------------------------------------------------------------ interfaccia (statica) ----
def test_testi_visibili_senza_apostrofo_al_posto_dell_accento():
    t = HTML[HTML.index("const T_NOTE"):]
    t = t[:t.index("};") + 2]
    for w in ("perche'", "puo'", "piu'", "gia'", "e' ", "cosi'", "citta'", "qualita'", "verra'", "potra'"):
        assert w not in t, w


def test_singolare_plurale_note():
    assert re.search(r"1 nota|=== 1 \?", HTML)
    assert "1 note" not in HTML


def test_messaggi_errore_rotte_note_senza_apostrofo_al_posto_dell_accento():
    for name in dir(N):
        if name.startswith("MSG_"):
            v = getattr(N, name)
            assert not re.search(r"\b(perche|puo|piu|gia|cosi)'", v), (name, v)


def test_B135_nuova_lettera_non_parte_due_volte():
    body = HTML[HTML.index("async function newLetter"):HTML.index("/* editor di nota")]
    assert re.search(r"busy|inflight|in_flight|pending|disabled|creating|making", body, re.I)


def test_B136_una_nuova_modifica_riarma_l_avviso_di_chiusura():
    body = HTML[HTML.index("const onEdit"):][:300]
    assert "warned = false" in body
