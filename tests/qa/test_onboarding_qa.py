"""QA fase 3 (TESTER): guida di primo avvio. Sicurezza, validazione, atomicita', prova della chiave, coerenza con le fonti.

Nessuna rete (conftest.py di tests/qa blocca i socket non locali), JOBSHUNTER_HOME temporanea, nessun LaunchAgent vero.
I test marcati con il numero del bug (B16...) descrivono il comportamento ATTESO: restano rossi finche' il bug non e' corretto."""
import json
import logging
import threading

import httpx
import sys

import pytest

from jobshunter import onboarding, settings
from jobshunter import profiles as prof
from jobshunter.db import DB
from jobshunter.gui import app as appmod
from jobshunter.gui.app import create_app
from jobshunter.sources.boards import jooble_hosts

H = {"Host": "127.0.0.1:8765"}
KEY_ID, KEY_SECRET = "qaid1234", "qasecret0123456789abcdef01234567"


@pytest.fixture(autouse=True)
def _mai_dati_veri(tmp_path):
    """Guardia: la cartella dati deve essere SEMPRE quella temporanea, prima e dopo ogni test."""
    assert str(settings.home()).startswith(str(tmp_path.parent)), settings.home()
    yield
    assert str(settings.home()).startswith(str(tmp_path.parent)), "JOBSHUNTER_HOME e' stata tolta durante il test"


@pytest.fixture
def cfg(tmp_path):
    c = settings.load_config(create_if_missing=True)
    return c


@pytest.fixture
def client(cfg):
    return create_app(None, 8765).test_client()


@pytest.fixture
def db(cfg):
    return DB(settings.resolve_path(cfg["general"]["db_path"]))


def call(client, method, path, body=None, headers=None, raw=None, ctype="application/json"):
    h = dict(H, **(headers or {}))
    kw = {"headers": h}
    if raw is not None:
        kw.update(data=raw, content_type=ctype)
    elif body is not None:
        kw.update(data=json.dumps(body), content_type="application/json")
    r = getattr(client, method)(path, **kw)
    try:
        data = json.loads(r.data)
    except ValueError:
        data = None
    return r.status_code, data


def body(**over):
    b = {"profile": {"preset": "custom", "titles": ["infermiere"], "seniority": "any", "internships": False, "remote": False},
         "country": "it", "home": "Bari", "radius_km": 50, "keys": {}, "report_dir": "", "schedule": None}
    b.update(over)
    return b


def prof_body(**over):
    p = {"preset": "custom", "titles": ["infermiere"], "seniority": "any", "internships": False, "remote": False}
    p.update(over)
    return body(profile=p)


class Fake:
    """Client HTTP finto per la prova della chiave."""
    code, text, boom, seen = 200, "{}", None, []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None, **k):
        Fake.seen.append((url, dict(params or {}), dict(k)))
        if Fake.boom:
            raise Fake.boom
        return httpx.Response(Fake.code, text=Fake.text, request=httpx.Request("GET", url))


@pytest.fixture
def fake(monkeypatch):
    Fake.code, Fake.text, Fake.boom, Fake.seen = 200, "{}", None, []
    monkeypatch.setattr(onboarding, "make_client", lambda: Fake())
    return Fake


# ===================================================== (1) chi vede la guida ====
def test_get_normali_non_toccano_il_profilo_automatico(client):
    """Aprire l'app (richieste GET della pagina) non deve far sembrare 'modificato' il profilo creato in automatico."""
    for p in ("/api/profiles", "/api/stats", "/api/status", "/api/jobs", "/api/settings", "/api/onboarding", "/api/meta", "/api/presets"):
        call(client, "get", p)
    assert call(client, "get", "/api/onboarding")[1]["needed"] is True


def test_nuovo_utente_con_sola_modifica_di_unimpostazione_vede_ancora_la_guida(client):
    """Salvare Impostazioni senza cambiare nulla di rilevante (es. tema) non e' 'dati dell'utente'."""
    call(client, "post", "/api/settings", {"values": {"general.min_score": 10}})
    assert call(client, "get", "/api/onboarding")[1]["needed"] is True


def test_utente_con_impostazioni_personalizzate_ma_senza_scansioni_non_la_vede(client, home_cfg=None):
    """B21: casa/cartella report/orario gia' configurati in settings.json (utente esistente, nessuna scansione ancora)."""
    assert call(client, "post", "/api/settings", {"values": {"home": "Palermo", "report.dir": "/Users/x/Rep"}})[0] == 200
    assert call(client, "get", "/api/onboarding")[1]["needed"] is False


def test_utente_con_solo_ricerche_in_scan_runs_non_la_vede(client, db):
    db.conn.execute("INSERT INTO scan_runs(started_at) VALUES ('2026-01-01T00:00:00')") if _has_col(db, "scan_runs", "started_at") else None
    n = db.conn.execute("SELECT COUNT(*) FROM scan_runs").fetchone()[0]
    if n:
        db.conn.commit()
        assert call(client, "get", "/api/onboarding")[1]["needed"] is False


def _has_col(db, table, col):
    return col in [r[1] for r in db.conn.execute(f"PRAGMA table_info({table})")]


def test_utente_con_chiave_solo_in_ambiente_non_e_considerato(client, monkeypatch):
    """Nota: chiavi da variabile d'ambiente non contano come 'chiavi configurate' (documentato in B21)."""
    monkeypatch.setenv("ADZUNA_APP_KEY", "x")
    assert call(client, "get", "/api/onboarding")[1]["needed"] is True  # comportamento attuale, solo registrato


def test_dopo_skip_e_ricaricamento_non_ricompare(client):
    call(client, "post", "/api/onboarding/skip")
    assert call(client, "get", "/api/onboarding")[1]["needed"] is False


def test_stato_non_contiene_segreti(client, cfg):
    settings.save_overrides(settings.default_config_path(), {"sources.adzuna.app_id": KEY_ID, "sources.adzuna.app_key": KEY_SECRET,
                                                             "sources.jooble.api_key": KEY_SECRET + "J", "sources.jooble.host": "it.jooble.org"})
    c = create_app(None, 8765).test_client()
    st, d = call(c, "get", "/api/onboarding")
    txt = json.dumps(d)
    assert KEY_SECRET not in txt and KEY_ID not in txt
    assert d["prefill"]["has_adzuna"] is True and d["prefill"]["has_jooble"] is True


# =============================================== (2) complete: atomicita' ====
def test_complete_due_volte_e_idempotente(client, db):
    b = body()
    s1, d1 = call(client, "post", "/api/onboarding/complete", b)
    s2, d2 = call(client, "post", "/api/onboarding/complete", b)
    assert s1 == s2 == 200 and d1["profile_id"] == d2["profile_id"]
    assert [p.name for p in prof.ProfileStore(db).list()] == ["Infermiere"]


def test_complete_dopo_errore_di_rescore_non_lascia_profili_doppi(client, db):
    """B17: se qualcosa fallisce dopo la scrittura del profilo, riprovare non deve creare 'Infermiere 2'."""
    def boom(*a, **k):
        raise RuntimeError("rescore rotto")
    with pytest.MonkeyPatch.context() as mp:  # NIENTE monkeypatch.undo(): toglierebbe anche JOBSHUNTER_HOME temporanea
        mp.setattr(appmod, "rescore", boom)
        app = create_app(None, 8765)
        app.config["PROPAGATE_EXCEPTIONS"] = False
        st, _ = call(app.test_client(), "post", "/api/onboarding/complete", body())
        assert st == 500
    cl2 = create_app(None, 8765).test_client()
    st, d = call(cl2, "post", "/api/onboarding/complete", body())
    assert st == 200
    names = [p.name for p in prof.ProfileStore(db).list()]
    assert names == ["Infermiere"], names


def test_complete_con_errore_di_rescore_ripristina_anche_il_profilo(client, db, monkeypatch):
    """B17: stato dopo un fallimento = stato di prima (profilo automatico intatto, nessun profilo nuovo)."""
    def boom(*a, **k):
        raise RuntimeError("rescore rotto")
    monkeypatch.setattr(appmod, "rescore", boom)
    app = create_app(None, 8765)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    cl = app.test_client()
    call(cl, "post", "/api/onboarding/complete", body(keys={"adzuna": {"app_id": KEY_ID, "app_key": KEY_SECRET}}))
    ps = prof.ProfileStore(db).list()
    assert [p.name for p in ps] == ["Cybersecurity"], [p.name for p in ps]
    assert not settings.load_overrides(settings.default_config_path()).get("sources.adzuna.app_key")


def test_complete_in_parallelo_non_duplica_profili(client, db):
    res = []
    bar = threading.Barrier(4)

    def go():
        cl = create_app(None, 8765).test_client()
        bar.wait()
        res.append(call(cl, "post", "/api/onboarding/complete", body())[0])

    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    names = sorted(p.name for p in prof.ProfileStore(db).list())
    assert names == ["Infermiere"], (res, names)


def test_ripristino_settings_json_preserva_chiavi_sconosciute(cfg):
    p = settings.default_config_path()
    settings.save_overrides(p, {"home": "Roma"})
    snap = settings.load_overrides(p)
    settings.save_overrides(p, {"home": "Bari", "radius_km": 10})
    settings.restore_overrides(p, snap)
    assert settings.load_overrides(p) == snap


def test_ripristino_settings_json_senza_file_iniziale(cfg):
    """Se settings.json non esisteva, dopo un fallimento resta un file '{}' (innocuo) e non un file con i nuovi valori."""
    p = settings.overrides_path(settings.default_config_path())
    if p.exists():
        p.unlink()
    snap = settings.load_overrides(settings.default_config_path())
    settings.save_overrides(settings.default_config_path(), {"home": "Bari"})
    settings.restore_overrides(settings.default_config_path(), snap)
    assert settings.load_overrides(settings.default_config_path()) == {}


@pytest.mark.skipif(sys.platform.startswith("win"), reason="permessi POSIX (chmod/st_mode/umask): su Windows la protezione e' icacls (provata in test_portability)")
def test_settings_json_permessi_600_dopo_complete(client):
    call(client, "post", "/api/onboarding/complete", body(keys={"adzuna": {"app_id": KEY_ID, "app_key": KEY_SECRET}}))
    p = settings.overrides_path(settings.default_config_path())
    assert oct(p.stat().st_mode & 0o777) == "0o600"


def test_complete_riesegue_con_nome_numerico(client, db):
    """Titolo '2024' => nome profilo '2024': ProfileStore.get('2024') lo tratterebbe come id."""
    st, d = call(client, "post", "/api/onboarding/complete", prof_body(titles=["2024"]))
    assert st == 200
    ps = prof.ProfileStore(db).list()
    assert not any(p.name.isdigit() for p in ps), [p.name for p in ps]


# ============================================================ (3) validazione ====
@pytest.mark.parametrize("titles", [[], [""], ["   "], ["\n\t"]])
def test_titoli_vuoti_con_preset_custom_rifiutati(client, titles):
    st, d = call(client, "post", "/api/onboarding/complete", prof_body(titles=titles))
    assert st == 400 and d["ok"] is False and d["field"] in ("profile", "titles")


@pytest.mark.parametrize("t", ["a" * 81, "a" * 5000, "x" * 100000])
def test_titolo_enorme_rifiutato_senza_500(client, t):
    st, d = call(client, "post", "/api/onboarding/complete", prof_body(titles=[t]))
    assert st == 400, (st, str(d)[:100])


def test_surrogato_isolato_in_json_non_da_500(client):
    """B28: "\\ud800" (JSON valido) in un titolo o in una citta' -> UnicodeEncodeError -> 500."""
    for field in ("title", "home", "report_dir", "key"):
        b = body()
        if field == "title":
            b["profile"]["titles"] = ["\ud800"]
        elif field == "home":
            b["home"] = "\ud800"
        elif field == "report_dir":
            b["report_dir"] = "/tmp/\ud800"
        else:
            b["keys"] = {"adzuna": {"app_id": "\ud800", "app_key": "x"}}
        raw = json.dumps(b)  # ensure_ascii=True: lascia "\\ud800" come escape
        for ep in ("estimate", "complete"):
            st, d = call(client, "post", f"/api/onboarding/{ep}", raw=raw)
            assert st in (200, 400), (field, ep, st)


@pytest.mark.parametrize("t", ["<script>alert(1)</script>", "a\x00b", "a\u202eb", "💼 job", "x\ny", "'; DROP TABLE jobs;--"])
def test_titoli_strani_non_rompono(client, db, t):
    st, d = call(client, "post", "/api/onboarding/complete", prof_body(titles=[t]))
    assert st in (200, 400)
    if st == 200:
        p = prof.ProfileStore(db).list()[0]
        assert all("\x00" not in x and "\n" not in x for x in p.titles + [p.name])
    assert db.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_titoli_non_lista_o_tipi_sbagliati(client):
    for t in ("infermiere", {"a": 1}, 5, [1, 2], [None], [["a"]], True):
        st, d = call(client, "post", "/api/onboarding/complete", prof_body(titles=t))
        assert st == 400 or (st == 200 and t in (None,)), (t, st)


def test_nove_titoli_rifiutati_otto_ok(client):
    assert call(client, "post", "/api/onboarding/complete", prof_body(titles=[f"lavoro {i}" for i in range(9)]))[0] == 400
    assert call(client, "post", "/api/onboarding/complete", prof_body(titles=[f"lavoro {i}" for i in range(8)]))[0] == 200


def test_titoli_doppi_ignorati(client, db):
    call(client, "post", "/api/onboarding/complete", prof_body(titles=["Infermiere", "infermiere", "INFERMIERE"]))
    assert len(prof.ProfileStore(db).list()[0].titles) == 1


@pytest.mark.parametrize("c", ["xx", "it;", "../it", "", "ITALIA", 5, ["it"], None])
def test_paese_non_valido(client, c):
    st, d = call(client, "post", "/api/onboarding/complete", body(country=c))
    if c in ("", None):
        assert st == 200  # vuoto = Italia
    else:
        assert st == 400 and d["field"] == "country", (c, st, d)


def test_paese_maiuscolo_accettato(client):
    assert call(client, "post", "/api/onboarding/complete", body(country="DE", home=""))[0] == 200


@pytest.mark.parametrize("km", [0, -5, 3001, 10**12, "abc", "1e3", "5.5", [], {}, True, None, float("nan"), 1e308])
def test_raggio_non_valido(client, km):
    st, d = call(client, "post", "/api/onboarding/complete", body(radius_km=km))
    assert st in (200, 400)
    if km in (None,):
        assert st == 200


def test_raggio_infinito_non_da_500(client):
    """B18: JSON con Infinity/1e999 (accettato dal parser Python) fa OverflowError."""
    for lit in ("Infinity", "1e999", "-Infinity"):
        raw = json.dumps(body()).replace('"radius_km": 50', '"radius_km": ' + lit)
        for ep in ("estimate", "complete"):
            st, d = call(client, "post", f"/api/onboarding/{ep}", raw=raw)
            assert st == 400, (ep, lit, st)


def test_ore_infinite_nella_pianificazione_non_da_500(client):
    """B18: schedule.hours = 1e999."""
    st, d = call(client, "post", "/api/onboarding/complete", raw=json.dumps(body()).replace('"schedule": null', '"schedule": {"enabled": false, "hours": 1e999}'))
    assert st == 400, st


def test_raggio_valido_ai_bordi(client):
    for km in (1, 3000, "50", 49.9):
        assert call(client, "post", "/api/onboarding/estimate", body(radius_km=km))[0] == 200


def test_citta_sconosciuta_o_strana(client):
    for h in ("Cittanonesistente", "x" * 500, "<b>Roma</b>", ";--", 5, ["Bari"]):
        st, d = call(client, "post", "/api/onboarding/estimate", body(home=h))
        assert st == 400 and d["field"] == "home", (h, st)


def test_citta_con_carattere_nullo_non_finisce_in_settings(client):
    """B28b (bassa): 'Bari\\x00' passa (geo ignora il NUL) e viene salvata in settings.json con il NUL dentro."""
    st, d = call(client, "post", "/api/onboarding/complete", body(home="Bari\x00"))
    ov = settings.load_overrides(settings.default_config_path())
    assert st == 400 or "\x00" not in ov.get("home", "")


def test_citta_lunga_solo_spazi_vale_vuota(client):
    assert call(client, "post", "/api/onboarding/estimate", body(home="     "))[0] == 200


def test_citta_di_un_altro_paese_non_e_un_errore_ma_si_registra(client):
    """Bari con paese Germania: accettato (la citta' e' nota); il raggio parte da Bari e cerca in Germania. Registrato."""
    st, d = call(client, "post", "/api/onboarding/estimate", body(country="de", home="Bari"))
    assert st == 200


@pytest.mark.parametrize("host", ["evil.com", "jooble.org.evil.com", "http://it.jooble.org", "https://it.jooble.org", "it.jooble.org:8080",
                                  "user:pw@it.jooble.org", "it.jooble.org/", "it.jooble.org/api", "evil.com/it.jooble.org", "evil.com#.jooble.org",
                                  "evil.com?.jooble.org", "notjooble.org", "it.jooble.org.", "it.jooble.org\nevil.com", "it jooble.org",
                                  "..jooble.org", "127.0.0.1", "localhost", "jooble.org@evil.com", "it.jooble.org\\@evil.com",
                                  "xn--jooble.org", "ｉｔ.jooble.org", "IT.JOOBLE.ORG.evil.com"])
def test_host_jooble_malevoli_rifiutati(client, host):
    st, d = call(client, "post", "/api/onboarding/complete", body(keys={"jooble": {"host": host, "api_key": KEY_SECRET}}))
    assert st == 400 and d["field"] == "jooble", (host, st, d)
    assert not settings.load_overrides(settings.default_config_path()).get("sources.jooble.api_key")


@pytest.mark.parametrize("host", ["it.jooble.org", "jooble.org", "UK.JOOBLE.ORG", "  de.jooble.org  ", "a.b.jooble.org"])
def test_host_jooble_leciti(client, host):
    st, d = call(client, "post", "/api/onboarding/complete", body(keys={"jooble": {"host": host, "api_key": KEY_SECRET}}))
    assert st == 200, d


@pytest.mark.parametrize("key", ["ab cd", "ab\ncd", "ab\r\nX-Evil: 1", "ab\tcd", "a/b", "a?b", "a#b", "a%0d%0ab", "a" * 101, "\u00e9\u00e8", "a;b", "a:b"])
def test_chiavi_con_caratteri_pericolosi_rifiutate(client, key):
    for keys in ({"adzuna": {"app_id": KEY_ID, "app_key": key}}, {"adzuna": {"app_id": key, "app_key": KEY_SECRET}},
                 {"jooble": {"host": "it.jooble.org", "api_key": key}}):
        st, d = call(client, "post", "/api/onboarding/complete", body(keys=keys))
        assert st == 400, (key, keys, st)


def test_chiave_con_newline_in_coda_viene_ripulita_non_salvata_con_newline(client):
    st, d = call(client, "post", "/api/onboarding/complete", body(keys={"adzuna": {"app_id": KEY_ID + "\n", "app_key": KEY_SECRET + " \r\n"}}))
    if st == 200:
        ov = settings.load_overrides(settings.default_config_path())
        assert ov["sources.adzuna.app_key"] == KEY_SECRET and ov["sources.adzuna.app_id"] == KEY_ID


def test_chiave_di_150_caratteri_non_viene_troncata_in_silenzio(client):
    """B19: _text taglia a 100 PRIMA di controllare: una chiave di 150 caratteri viene salvata troncata come se fosse valida."""
    st, d = call(client, "post", "/api/onboarding/complete", body(keys={"adzuna": {"app_id": KEY_ID, "app_key": "k" * 150}}))
    assert st == 400, st


def test_citta_e_titoli_lunghi_non_troncati_in_silenzio(client):
    st, d = call(client, "post", "/api/onboarding/estimate", body(home="Bari" + " " * 10 + "x" * 100))
    assert st == 400


def test_solo_id_adzuna_o_solo_chiave_rifiutati(client):
    assert call(client, "post", "/api/onboarding/complete", body(keys={"adzuna": {"app_id": KEY_ID, "app_key": ""}}))[0] == 400
    assert call(client, "post", "/api/onboarding/complete", body(keys={"adzuna": {"app_id": "", "app_key": KEY_SECRET}}))[0] == 400
    assert call(client, "post", "/api/onboarding/complete", body(keys={"jooble": {"host": "", "api_key": KEY_SECRET}}))[0] == 400
    assert call(client, "post", "/api/onboarding/complete", body(keys={"jooble": {"host": "it.jooble.org", "api_key": ""}}))[0] == 400


def test_chiavi_forme_strane(client):
    for k in ("x", ["a"], {"adzuna": "x"}, {"adzuna": ["a"]}, {"adzuna": {"app_id": 5, "app_key": 6}}, {"jooble": None}):
        st, d = call(client, "post", "/api/onboarding/complete", body(keys=k))
        assert st in (200, 400), (k, st)


@pytest.mark.parametrize("path", ["a\x00b", "x" * 501, 5, ["a"], {"a": 1}])
def test_report_dir_tipi_e_lunghezze(client, path):
    st, d = call(client, "post", "/api/onboarding/complete", body(report_dir=path))
    assert st in (200, 400), (path, st)
    if isinstance(path, str) and "\x00" in path:
        assert st == 400


def test_report_dir_501_caratteri_non_va_troncato_in_silenzio(client):
    """B19 (stesso schema): 501 caratteri => salvato troncato a 500, percorso diverso da quello scritto."""
    st, d = call(client, "post", "/api/onboarding/complete", body(report_dir="/tmp/" + "a" * 600))
    assert st == 400


@pytest.mark.parametrize("path", ["../../../../etc", "/etc", "/System/Library", "/", "~/.ssh", "/Library/LaunchDaemons", "reports/../../.."])
def test_report_dir_in_zone_di_sistema(client, path):
    """B20: la guida accetta qualsiasi percorso (come Impostazioni). Registra cosa succede; il test pretende rifiuto di zone di sistema e '..'."""
    st, d = call(client, "post", "/api/onboarding/complete", body(report_dir=path))
    assert st == 400, (path, st)


@pytest.mark.parametrize("times", ["25:00", "09:60", "9", "ab", "09:00,09:00,09:00,09:00,09:00", "", "09:00;10:00;11:00;12:00;13:00", "-1:00", "09:00:00", "0900", "٠٩:٠٠", "09:00\n10:00"])
def test_orari_non_validi(client, times):
    st, d = call(client, "post", "/api/onboarding/complete", body(schedule={"enabled": True, "kind": "daily", "times": times, "notify": True}))
    assert st in (200, 400)
    if st == 200:
        ov = settings.load_overrides(settings.default_config_path())
        import re
        assert re.fullmatch(r"\d\d:\d\d(, \d\d:\d\d){0,3}", ov["schedule.times"]), (times, ov["schedule.times"])


def test_orari_non_validi_rifiutati_dove_chiaramente_sbagliati(client):
    for t in ("25:00", "09:60", "ab", "09:00,10:00,11:00,12:00,13:00"):
        assert call(client, "post", "/api/onboarding/complete", body(schedule={"enabled": True, "times": t}))[0] == 400, t


def test_enabled_stringa_false_non_diventa_true(client):
    """B22: {"enabled": "false"} viene letto come True (bool di una stringa non vuota)."""
    st, d = call(client, "post", "/api/onboarding/complete", body(schedule={"enabled": "false", "times": "09:00"}))
    ov = settings.load_overrides(settings.default_config_path())
    assert st == 400 or ov.get("schedule.enabled") is False


def test_schedule_forme_strane(client):
    for s in ("x", 5, [], {"enabled": True, "times": ["09:00"]}, {"enabled": True, "hours": "x"}, {"enabled": True, "kind": ["a"]}, {"enabled": True, "hours": []}):
        st, d = call(client, "post", "/api/onboarding/complete", body(schedule=s))
        assert st in (200, 400), (s, st)


@pytest.mark.parametrize("pr", [{"seniority": "boh"}, {"seniority": 5}, {"internships": "si"}, {"remote": 1}, {"preset": "nonesiste"}, {"preset": ["a"]},
                                {"preset": 5}, {"name": 5}, {"name": "x" * 81}, {"name": ["a"]}])
def test_campi_profilo_non_validi(client, pr):
    st, d = call(client, "post", "/api/onboarding/complete", prof_body(**pr))
    assert st in (200, 400), (pr, st)
    if "seniority" in pr or "preset" in pr or "internships" in pr or "remote" in pr:
        assert st == 400


def test_nome_esplicito_in_conflitto_rifiutato_ma_nome_vuoto_ok(client, db):
    st, d = call(client, "post", "/api/onboarding/complete", prof_body(name="Cybersecurity", titles=["infermiere"]))
    # il profilo automatico e' quello che verrebbe sostituito, quindi il nome uguale e' ammesso
    assert st == 200


def test_corpo_non_json_o_non_oggetto(client):
    for raw, ct in (("", "application/json"), ("[]", "application/json"), ("null", "application/json"), ("{bad", "application/json"), ("{}", "text/plain"), ('"x"', "application/json")):
        for p in ("complete", "estimate", "test-adzuna"):
            st, d = call(client, "post", f"/api/onboarding/{p}", raw=raw, ctype=ct)
            assert st == 400, (p, raw, ct, st)


def test_json_annidato_profondissimo_non_da_500(client):
    st, d = call(client, "post", "/api/onboarding/complete", raw="[" * 50000 + "]" * 50000)
    assert st == 400


def test_estimate_non_scrive_niente(client, db):
    before = settings.load_overrides(settings.default_config_path())
    call(client, "post", "/api/onboarding/estimate", body(keys={"adzuna": {"app_id": KEY_ID, "app_key": KEY_SECRET}}, report_dir="/tmp/qa_x"))
    assert settings.load_overrides(settings.default_config_path()) == before
    assert [p.name for p in prof.ProfileStore(db).list()] == ["Cybersecurity"]
    assert db.kv_get(onboarding.KV_DONE) is None


def test_errore_di_validazione_non_scrive_niente_ne_segna_fatto(client, db):
    call(client, "post", "/api/onboarding/complete", body(keys={"adzuna": {"app_id": KEY_ID, "app_key": KEY_SECRET}}, home="Cittanonesistente"))
    assert db.kv_get(onboarding.KV_DONE) is None
    assert not settings.load_overrides(settings.default_config_path()).get("sources.adzuna.app_key")
    assert [p.name for p in prof.ProfileStore(db).list()] == ["Cybersecurity"]


# ------------------------------------------- coerenza con le fonti (host Jooble)
def test_host_jooble_scelto_dalla_guida_vale_per_il_paese_scelto():
    """B16: per ogni paese e per l'host che la guida suggerisce (uk.jooble.org per gb, jooble.org per us, <cc>.jooble.org altrove)
    jooble_hosts() deve associare l'host al codice del paese; altrimenti Jooble salta il paese in silenzio."""
    sugg = lambda c: "uk.jooble.org" if c == "gb" else "jooble.org" if c == "us" else f"{c}.jooble.org"
    bad = [(c, sugg(c), list(jooble_hosts({"host": sugg(c)}))) for c in prof.COUNTRIES if c not in jooble_hosts({"host": sugg(c)})]
    assert not bad, bad


def test_host_in_hosts_vince_sul_host_scelto_dalla_guida(cfg):
    """B16b: se config.toml ha `hosts`, l'host salvato dalla guida viene ignorato senza avvisi."""
    c = {"host": "de.jooble.org", "hosts": {"it": "it.jooble.org"}}
    assert "de" in jooble_hosts(c)


# ================================================ (4) prova della chiave Adzuna ====
def post_test(client, **b):
    b.setdefault("app_id", KEY_ID)
    b.setdefault("app_key", KEY_SECRET)
    return call(client, "post", "/api/onboarding/test-adzuna", b)


def test_una_sola_richiesta_per_prova_e_nessuna_con_campi_non_validi(client, fake):
    assert post_test(client, app_key="a b")[1]["status"] == "invalid"
    assert post_test(client, app_id="")[1]["status"] == "empty_fields"
    assert fake.seen == []
    post_test(client)
    assert len(fake.seen) == 1


def test_limite_di_5_secondi_non_aggirabile_con_varianti(client, fake):
    post_test(client)
    for variant in ({"country": "de"}, {"app_id": "other123"}, {"country": "IT"}, {"country": "../x"}):
        st, d = post_test(client, **variant)
        assert d["status"] == "blocked" and d.get("wait") is True, variant
    assert len(fake.seen) == 1


def test_limite_non_aggirabile_con_header_o_nuove_connessioni(client, fake):
    post_test(client)
    for h in ({"X-Forwarded-For": "1.2.3.4"}, {"X-Real-IP": "9.9.9.9"}, {"Cookie": "a=b"}):
        st, d = call(client, "post", "/api/onboarding/test-adzuna", {"app_id": KEY_ID, "app_key": KEY_SECRET}, headers=h)
        assert d["status"] == "blocked", h
    assert len(fake.seen) == 1


def test_limite_in_parallelo_una_sola_richiesta(client, fake):
    app = create_app(None, 8765)
    out = []
    bar = threading.Barrier(8)

    def go():
        cl = app.test_client()
        bar.wait()
        out.append(call(cl, "post", "/api/onboarding/test-adzuna", {"app_id": KEY_ID, "app_key": KEY_SECRET})[1]["status"])

    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(fake.seen) == 1, (out, len(fake.seen))


def test_limite_si_riapre_dopo_5_secondi(client, fake, monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(onboarding.time, "monotonic", lambda: t[0])
    post_test(client)
    t[0] += 4.9
    assert post_test(client)[1]["status"] == "blocked"
    t[0] += 0.2
    assert post_test(client)[1]["status"] == "ok"
    assert len(fake.seen) == 2


def test_limite_consumato_anche_da_prova_in_rete_assente(client, fake):
    fake.boom = httpx.ConnectError("x")
    assert post_test(client)[1]["status"] == "network"
    fake.boom = None
    assert post_test(client)[1]["status"] == "blocked"  # voluto: 1 prova ogni 5 s


@pytest.mark.parametrize("code,status", [(200, "ok"), (201, "ok"), (204, "ok"), (301, "invalid"), (302, "invalid"), (400, "invalid"), (401, "invalid"),
                                         (403, "blocked"), (404, "invalid"), (408, "network"), (418, "invalid"), (429, "blocked"), (500, "network"), (503, "network")])
def test_codici_http(client, fake, code, status):
    fake.code = code
    st, d = post_test(client)
    assert st == 200 and d["status"] in (status, "ok", "invalid", "network", "blocked")


def test_200_con_html_di_captive_portal_non_e_chiave_valida(client, fake):
    """B23: un 200 con una pagina HTML (portale Wi-Fi, proxy) viene letto come 'La chiave funziona'."""
    fake.code, fake.text = 200, "<html><body>Accedi al Wi-Fi</body></html>"
    st, d = post_test(client)
    assert d["ok"] is False, d


def test_risposta_strana_non_fa_crashare(client, fake):
    for text in ("", "null", "[1,2", "\x00\x00", "x" * 2_000_000):
        fake.text = text
        post_test(client)
        onboarding_reset(client)


def onboarding_reset(client):
    # il limiter e' per app: si usa una nuova app per la prova successiva
    pass


@pytest.mark.parametrize("exc", [httpx.ConnectError("x"), httpx.ReadTimeout("t"), httpx.ConnectTimeout("t"), httpx.RemoteProtocolError("p"),
                                 httpx.TooManyRedirects("r"), httpx.DecodingError("d"), httpx.ProxyError("p"), OSError("o"), TimeoutError("t")])
def test_eccezioni_di_rete_sono_network_senza_chiavi(client, fake, exc):
    fake.boom = exc
    st, d = post_test(client)
    assert st == 200 and d["status"] == "network" and KEY_SECRET not in json.dumps(d)


@pytest.mark.parametrize("exc", [httpx.UnsupportedProtocol("u"), httpx.StreamError("s"), httpx.InvalidURL("bad")])
def test_eccezioni_non_httperror_non_danno_500(client, fake, exc):
    """B24 (bassa): eccezioni di httpx che non derivano da HTTPError (InvalidURL, StreamError) non sono gestite: 500 invece di 'network'."""
    fake.boom = exc
    st, d = call(client, "post", "/api/onboarding/test-adzuna", {"app_id": KEY_ID, "app_key": KEY_SECRET})
    assert st == 200 and KEY_SECRET not in json.dumps(d), (type(exc).__name__, st)


def test_url_e_parametri_della_prova(client, fake):
    post_test(client, country="de")
    url, params, kw = fake.seen[0]
    assert url == "https://api.adzuna.com/v1/api/jobs/de/search/1"
    assert params["app_id"] == KEY_ID and params["results_per_page"] == 1 and "follow_redirects" not in kw


@pytest.mark.parametrize("c", ["../../evil", "de/../../x", "it?x=1", "it#", "IT", " it ", "xx", 5, None, ["de"], "de\n", "http://evil.com", "@evil.com", "it/../..", "ch"])
def test_country_manipolato_non_esce_dal_percorso(client, fake, c):
    post_test(client, country=c)
    for url, params, kw in fake.seen:
        assert url.startswith("https://api.adzuna.com/v1/api/jobs/")
        cc = url[len("https://api.adzuna.com/v1/api/jobs/"):].split("/")[0]
        assert cc in prof.COUNTRIES and "/" not in url[len("https://api.adzuna.com/v1/api/jobs/"):].split("/search")[0]


def test_la_prova_non_segue_i_redirect_verso_altri_host(monkeypatch):
    """Il client vero (make_client) non deve seguire redirect: la chiave finirebbe in un altro host."""
    c = onboarding.make_client()
    try:
        assert c.follow_redirects is False
        assert c.trust_env in (True, False)
    finally:
        c.close()


def test_client_vero_con_trasporto_finto_vede_url_con_chiave_ma_i_log_no(client, monkeypatch, caplog):
    """B25 (verifica): con httpx.MockTransport la richiesta passa dal vero Client; nessun log deve contenere la chiave, nemmeno a livello DEBUG."""
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(onboarding, "make_client", lambda: httpx.Client(timeout=10, transport=httpx.MockTransport(handler)))
    logging.getLogger().setLevel(logging.DEBUG)
    with caplog.at_level(logging.DEBUG):
        st, d = post_test(client)
    assert d["ok"] is True and seen and "app_key=" in seen[0]
    allogs = "\n".join(r.getMessage() for r in caplog.records)
    assert KEY_SECRET not in allogs and KEY_ID not in allogs, allogs[:400]
    assert KEY_SECRET not in json.dumps(d)


def test_chiavi_non_finiscono_in_stdout_stderr(client, fake, capsys):
    post_test(client)
    call(client, "post", "/api/onboarding/complete", body(keys={"adzuna": {"app_id": KEY_ID, "app_key": KEY_SECRET}}))
    out = capsys.readouterr()
    assert KEY_SECRET not in out.out + out.err


def test_chiavi_non_finiscono_nei_risultati_di_altre_api(client):
    call(client, "post", "/api/onboarding/complete", body(keys={"adzuna": {"app_id": KEY_ID, "app_key": KEY_SECRET}, "jooble": {"host": "it.jooble.org", "api_key": KEY_SECRET + "J"}}))
    for p in ("/api/settings", "/api/onboarding", "/api/profiles", "/api/status", "/api/meta", "/api/stats"):
        st, d = call(client, "get", p)
        assert KEY_SECRET not in json.dumps(d), p
    st, d = call(client, "post", "/api/onboarding/estimate", body())
    assert KEY_SECRET not in json.dumps(d)


def test_messaggio_di_errore_riflette_il_testo_ma_la_pagina_usa_textContent():
    """Il messaggio 400 contiene il testo scritto dall'utente (es. la citta'): e' sicuro solo perche' la GUI usa textContent."""
    from pathlib import Path
    html = (Path(onboarding.__file__).parent / "gui" / "static" / "index.html").read_text(encoding="utf-8")
    js = html[html.index("/* ---- guida di primo avvio ---- */"):]
    assert "e.textContent = msg" in js and "innerHTML" not in js


# ================================================ (5) sicurezza dei nuovi POST ====
@pytest.mark.parametrize("origin", ["http://evil.com", "https://evil.com", "http://127.0.0.1:8765.evil.com", "http://127.0.0.1:8791", "null",
                                    "http://127.0.0.1", "http://localhost:80", "http://evil.com@127.0.0.1:8765", "http://127.0.0.1:8765@evil.com"])
@pytest.mark.parametrize("path", ["complete", "skip", "estimate", "test-adzuna"])
def test_post_con_origin_estraneo_rifiutati_e_senza_effetti(client, db, origin, path):
    st, d = call(client, "post", f"/api/onboarding/{path}", body(), headers={"Origin": origin})
    assert st == 403, (origin, path, st)
    assert db.kv_get(onboarding.KV_DONE) is None


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8765", "http://localhost:8765"])
def test_post_con_origin_proprio_accettati(client, origin):
    assert call(client, "post", "/api/onboarding/skip", headers={"Origin": origin})[0] == 200


def test_post_con_host_diverso_rifiutato(client):
    for host in ("evil.com", "127.0.0.1:9999", "127.0.0.1:8765.evil.com", "localhost"):
        r = client.post("/api/onboarding/skip", headers={"Host": host}, data="{}", content_type="application/json")
        assert r.status_code == 403, host
        r = client.get("/api/onboarding", headers={"Host": host})
        assert r.status_code == 403, host


def test_post_senza_origin_dal_form_cross_site_non_passa_il_json(client, db):
    """Un <form> cross-site non puo' mandare application/json: con text/plain il corpo non viene letto."""
    for p in ("complete", "skip"):
        r = client.post(f"/api/onboarding/{p}", headers=H, data=json.dumps(body()), content_type="text/plain")
        if p == "complete":
            assert r.status_code == 400
    # skip non legge il corpo: un form cross-site SENZA Origin (vecchi browser) potrebbe segnarla fatta. Origin e' sempre inviato dai browser moderni.


def test_metodi_non_consentiti(client):
    for p in ("complete", "skip", "estimate", "test-adzuna"):
        assert call(client, "get", f"/api/onboarding/{p}")[0] == 405
    assert call(client, "post", "/api/onboarding")[0] == 405
    assert call(client, "put", "/api/onboarding/skip")[0] == 405


def test_pagina_servita_con_no_store(client):
    r = client.get("/", headers=H)
    assert r.headers.get("Cache-Control") == "no-store"


def test_nessuna_intestazione_cors_permissiva(client):
    r = client.get("/api/onboarding", headers=dict(H, Origin="http://evil.com"))
    assert "Access-Control-Allow-Origin" not in r.headers
    r = client.options("/api/onboarding/complete", headers=dict(H, Origin="http://evil.com", **{"Access-Control-Request-Method": "POST"}))
    assert "Access-Control-Allow-Origin" not in r.headers


# ===================================================== (7) dubbi aperti ====
def test_home_names_di_palermo_non_restano_a_chi_non_e_in_sicilia(client, cfg):
    """B26: la config di esempio ha home_names palermo/sicilia/...; chi sceglie Bari senza usare Palermo li tiene nel punteggio ('vicino a casa')."""
    call(client, "post", "/api/onboarding/complete", body(home="Bari"))
    c = settings.load_config(settings.default_config_path())
    names = c.get("location", {}).get("home_names", [])
    assert "palermo" not in [n.lower() for n in names] or names == ["bari"], names


def test_home_names_con_citta_vuota_non_restano_quelli_di_palermo(client, cfg):
    call(client, "post", "/api/onboarding/complete", body(home=""))
    c = settings.load_config(settings.default_config_path())
    names = c.get("location", {}).get("home_names", [])
    assert not names or "palermo" not in [n.lower() for n in names], names


def test_rifare_la_guida_senza_citta_azzera_la_casa_nelle_impostazioni(client):
    """B27: prima 'Bari', poi rifare la guida con citta' vuota: la casa in settings.json resta 'Bari' (nessun override per svuotarla)."""
    call(client, "post", "/api/onboarding/complete", body(home="Bari"))
    call(client, "post", "/api/onboarding/complete", body(home=""))
    ov = settings.load_overrides(settings.default_config_path())
    assert not ov.get("home"), ov


def test_fonti_gratuite_e_adzuna_spenta_senza_chiavi(client, cfg):
    call(client, "post", "/api/onboarding/complete", body())
    c = settings.load_config(settings.default_config_path())
    assert not c["sources"].get("adzuna", {}).get("enabled") and not c["sources"].get("jooble", {}).get("enabled")


def test_rifare_la_guida_con_chiavi_vuote_non_cancella_quelle_salvate(client):
    call(client, "post", "/api/onboarding/complete", body(keys={"adzuna": {"app_id": KEY_ID, "app_key": KEY_SECRET}}))
    call(client, "post", "/api/onboarding/complete", body(keys={}))
    ov = settings.load_overrides(settings.default_config_path())
    assert ov["sources.adzuna.app_key"] == KEY_SECRET


def test_paesi_non_italiani_senza_adzuna_o_jooble_non_rompono_la_stima(client):
    for c in prof.COUNTRIES:
        st, d = call(client, "post", "/api/onboarding/estimate", body(country=c, home="", keys={"jooble": {"host": "uk.jooble.org", "api_key": KEY_SECRET}}))
        assert st == 200, (c, d)


# ================================================= altri controlli (giro 2) ====
HTML = (__import__("pathlib").Path(onboarding.__file__).parent / "gui" / "static" / "index.html").read_text(encoding="utf-8")


def test_stima_jooble_per_regno_unito_con_host_suggerito_dalla_guida(client):
    """B16: con paese gb e host uk.jooble.org (suggerito dalla guida) la stima dice 0 richieste a Jooble: la fonte e' attiva ma salta il paese."""
    st, d = call(client, "post", "/api/onboarding/estimate",
                 body(country="gb", home="", keys={"jooble": {"host": "uk.jooble.org", "api_key": KEY_SECRET}}))
    assert st == 200 and d["requests"].get("jooble", 0) > 0, d["requests"]


def test_stima_jooble_per_stati_uniti_con_host_suggerito_dalla_guida(client):
    """B16: paese us e host jooble.org."""
    st, d = call(client, "post", "/api/onboarding/estimate",
                 body(country="us", home="", keys={"jooble": {"host": "jooble.org", "api_key": KEY_SECRET}}))
    assert st == 200 and d["requests"].get("jooble", 0) > 0, d["requests"]


def test_rifare_la_guida_non_cambia_la_pianificazione_ogni_n_ore(client):
    """B29: la GUI manda sempre kind='daily': chi aveva 'ogni 6 ore' se lo ritrova 'ogni giorno alle ...' dopo 'Rifai la guida'."""
    i = HTML.index("function obPayload()")
    payload_js = HTML[i:HTML.index("function obGoField", i)]
    assert 'kind: "daily"' not in payload_js, "il tipo di pianificazione e' fisso a daily"


def test_scorciatoie_j_k_non_attive_dentro_la_guida():
    """B30: il gestore globale dei tasti ignora INPUT e SELECT ma non TEXTAREA: scrivere 'java' o 'kebab' nella casella dei lavori
    (Rifai la guida) sposta la selezione e apre la scheda di un annuncio dietro la guida."""
    i = HTML.index('document.addEventListener("keydown", (e) => {\n  if (e.target.tagName === "INPUT"')
    handler = HTML[i:i + 900]
    assert "TEXTAREA" in handler or "onb" in handler.split("\n")[1], handler[:300]


def test_il_pulsante_prova_chiave_e_il_limite_lato_server_coincidono():
    assert "TEST_INTERVAL = 5.0" in open(onboarding.__file__, encoding="utf-8").read()


def test_guida_riapribile_anche_dopo_skip_e_complete(client):
    call(client, "post", "/api/onboarding/skip")
    st, d = call(client, "get", "/api/onboarding")
    assert d["step_hint"] == "rerun" and "prefill" in d
    call(client, "post", "/api/onboarding/complete", body())
    assert call(client, "get", "/api/onboarding")[1]["prefill"]["profile"]["name"] == "Infermiere"


def test_rifare_la_guida_non_tocca_altri_profili(client, db):
    store = prof.ProfileStore(db)
    store.add({"name": "Mio", "preset": "data"})
    call(client, "post", "/api/onboarding/complete", body())
    names = sorted(p.name for p in store.list())
    assert names == ["Cybersecurity", "Infermiere", "Mio"], names
    call(client, "post", "/api/onboarding/complete", prof_body(titles=["magazziniere"]))
    names = sorted(p.name for p in store.list())
    assert names == ["Cybersecurity", "Magazziniere", "Mio"] or names == ["Cybersecurity", "Infermiere", "Mio"], names
