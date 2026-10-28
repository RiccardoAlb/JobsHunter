"""Procedura guidata di primo avvio: stato, prova della chiave, validazione, applicazione atomica, idempotenza.

Nessuna rete vera (il client HTTP è finto e i socket non locali falliscono) e nessun dato vero (JOBSHUNTER_HOME temporanea)."""
import json
import socket

import httpx
import pytest

from conftest import make_job
from jobshunter import onboarding, scheduler, settings
from jobshunter import profiles as prof
from jobshunter.db import DB
from jobshunter.gui.app import create_app

H = {"Host": "127.0.0.1:8765"}
SECRET_ID, SECRET_KEY = "abcd1234", "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _no_rete(monkeypatch):
    real = socket.socket.connect

    def only_local(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(address, tuple) and host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"RETE VIETATA nei test: {address!r}")
        return real(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", only_local)
    monkeypatch.setattr(scheduler, "install", lambda *a, **k: calls.append(("install", a)))
    monkeypatch.setattr(scheduler, "uninstall", lambda *a, **k: calls.append(("uninstall", a)))
    monkeypatch.setattr(scheduler, "is_loaded", lambda: False)
    calls.clear()


calls: list = []


@pytest.fixture
def client(cfg, home):
    return create_app(None, 8765).test_client()


@pytest.fixture
def db(cfg):
    return DB(settings.resolve_path(cfg["general"]["db_path"]))


def get(client, path):
    r = client.get(path, headers=H)
    return r.status_code, json.loads(r.data)


def post(client, path, body=None):
    r = client.post(path, headers=H, data=json.dumps(body if body is not None else {}), content_type="application/json")
    return r.status_code, json.loads(r.data)


def payload(**over):
    b = {"profile": {"preset": "custom", "titles": ["infermiere"], "seniority": "any", "internships": False, "remote": False},
         "country": "it", "home": "Bari", "radius_km": 50, "keys": {}, "report_dir": "", "schedule": None}
    b.update(over)
    return b


# ---------------------------------------------------------------- stato ----
def test_installazione_nuova_la_guida_serve(client):
    st, d = get(client, "/api/onboarding")
    assert st == 200 and d["needed"] is True and d["done"] is False
    assert d["has_keys"] is False and d["has_data"] is False and d["has_profiles"] is False
    assert d["step_hint"] == "welcome"


def test_utente_con_annunci_non_la_vede(client, db):
    db.upsert(make_job())
    db.conn.commit()
    st, d = get(client, "/api/onboarding")
    assert d["needed"] is False and d["has_data"] is True


def test_utente_con_sole_candidature_non_la_vede(client, db):
    db.add_application(company="Acme", role="SOC")
    assert get(client, "/api/onboarding")[1]["needed"] is False


def test_utente_con_chiavi_non_la_vede(cfg, home):
    settings.save_overrides(settings.default_config_path(), {"sources.adzuna.app_key": SECRET_KEY})
    c = create_app(None, 8765).test_client()
    assert get(c, "/api/onboarding")[1]["needed"] is False


def test_utente_con_profilo_suo_non_la_vede(client, db):
    prof.ProfileStore(db).add({"name": "Mio", "preset": "data"})
    assert get(client, "/api/onboarding")[1]["needed"] is False


def test_profilo_cyber_modificato_conta_come_dell_utente(client, db):
    store = prof.ProfileStore(db)
    p = store.list()[0]
    store.update(p.id, {**p.to_dict(), "seniority": "junior"})
    assert get(client, "/api/onboarding")[1]["needed"] is False


def test_salta_la_segna_fatta_senza_perdere_niente(client, db):
    st, d = post(client, "/api/onboarding/skip")
    assert st == 200 and d["ok"]
    s, d = get(client, "/api/onboarding")
    assert d["needed"] is False and d["done"] is True and d["step_hint"] == "rerun"
    assert [p.name for p in prof.ProfileStore(db).list()] == ["Cybersecurity"]


# ---------------------------------------------------------- prova chiave ----
class FakeClient:
    """Sostituisce httpx.Client: registra le richieste e risponde col codice scelto."""
    code = 200
    boom = None
    seen: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None, **k):
        FakeClient.seen.append((url, dict(params or {})))
        if FakeClient.boom:
            raise FakeClient.boom
        return httpx.Response(FakeClient.code, json={"results": []}, request=httpx.Request("GET", url))


@pytest.fixture
def fake_http(monkeypatch):
    FakeClient.code, FakeClient.boom, FakeClient.seen = 200, None, []
    monkeypatch.setattr(onboarding, "make_client", lambda: FakeClient())
    return FakeClient


def test_campi_vuoti_non_fanno_richieste(client, fake_http):
    for body in ({}, {"app_id": "", "app_key": "x"}, {"app_id": "  ", "app_key": " "}, {"app_id": 5, "app_key": None}):
        st, d = post(client, "/api/onboarding/test-adzuna", body)
        assert st == 200 and d["status"] == "empty_fields" and d["ok"] is False
    assert fake_http.seen == []


def test_chiave_ok_una_sola_richiesta_e_nessun_segreto_nella_risposta(client, fake_http):
    st, d = post(client, "/api/onboarding/test-adzuna", {"app_id": SECRET_ID, "app_key": SECRET_KEY, "country": "it"})
    assert d["ok"] is True and d["status"] == "ok"
    assert len(fake_http.seen) == 1
    url, params = fake_http.seen[0]
    assert url.startswith("https://api.adzuna.com/") and params["results_per_page"] == 1
    assert SECRET_KEY not in json.dumps(d) and SECRET_ID not in json.dumps(d)


@pytest.mark.parametrize("code,status", [(401, "invalid"), (400, "invalid"), (403, "blocked"), (429, "blocked"), (503, "network"),
                                         (404, "network"), (302, "network")])
def test_esiti_per_codice(client, fake_http, code, status):
    fake_http.code = code
    st, d = post(client, "/api/onboarding/test-adzuna", {"app_id": SECRET_ID, "app_key": SECRET_KEY})
    assert d["status"] == status and d["ok"] is False
    if status == "blocked":
        assert "riprova" in d["message"].lower()


def test_rete_assente(client, fake_http):
    fake_http.boom = httpx.ConnectError("boom " + SECRET_KEY)
    st, d = post(client, "/api/onboarding/test-adzuna", {"app_id": SECRET_ID, "app_key": SECRET_KEY})
    assert d["status"] == "network" and SECRET_KEY not in json.dumps(d)
    fake_http.boom = httpx.ReadTimeout("t")
    # nuova app = limite azzerato
    c2 = create_app(None, 8765).test_client()
    assert post(c2, "/api/onboarding/test-adzuna", {"app_id": SECRET_ID, "app_key": SECRET_KEY})[1]["status"] == "network"


def test_limite_una_prova_ogni_5_secondi(client, fake_http):
    b = {"app_id": SECRET_ID, "app_key": SECRET_KEY}
    assert post(client, "/api/onboarding/test-adzuna", b)[1]["status"] == "ok"
    d = post(client, "/api/onboarding/test-adzuna", b)[1]
    assert d["status"] == "blocked" and d.get("wait") is True and "attendi" in d["message"].lower()
    assert len(fake_http.seen) == 1


def test_limiter_riapre_dopo_l_intervallo():
    lim = onboarding.Limiter(interval=0.05)
    assert lim.allow() and not lim.allow()
    import time

    time.sleep(0.06)
    assert lim.allow()


def test_caratteri_strani_nelle_chiavi_non_partono(client, fake_http):
    st, d = post(client, "/api/onboarding/test-adzuna", {"app_id": "ab cd", "app_key": "k?x=1&y=2"})
    assert d["status"] == "invalid" and fake_http.seen == []


def test_le_chiavi_non_finiscono_nei_log(client, fake_http, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        post(client, "/api/onboarding/test-adzuna", {"app_id": SECRET_ID, "app_key": SECRET_KEY})
    assert SECRET_KEY not in caplog.text
    assert logging.getLogger("httpx").level >= logging.WARNING


# ------------------------------------------------------------- complete ----
def test_complete_crea_profilo_e_impostazioni(client, db, home):
    st, d = post(client, "/api/onboarding/complete", payload(report_dir="~/Documents/JobsHunter"))
    assert st == 200 and d["ok"] and isinstance(d["profile_id"], int)
    ps = prof.ProfileStore(db).list()
    assert [p.name for p in ps] == ["Infermiere"]  # il profilo automatico mai toccato viene sostituito
    p = ps[0]
    assert p.id == d["profile_id"] and p.titles == ["infermiere"] and p.countries == ["it"]
    assert p.city == "Bari" and p.radius_km == 50 and p.remote is False and p.internships is False
    ov = settings.load_overrides(settings.default_config_path())
    assert ov["home"] == "Bari" and ov["radius_km"] == 50 and ov["report.dir"] == "~/Documents/JobsHunter"
    assert "sources.adzuna.app_key" not in ov
    assert get(client, "/api/onboarding")[1]["done"] is True


def test_complete_con_preset(client, db):
    b = payload(profile={"preset": "software_dev", "titles": [], "seniority": "junior", "internships": True, "remote": True})
    assert post(client, "/api/onboarding/complete", b)[0] == 200
    p = prof.ProfileStore(db).list()[0]
    assert p.preset == "software_dev" and p.name == "Sviluppo software" and p.seniority == "junior"


def test_complete_con_chiavi_attiva_le_fonti(client, db, cfg):
    keys = {"adzuna": {"app_id": SECRET_ID, "app_key": SECRET_KEY}, "jooble": {"host": "it.jooble.org", "api_key": "aaaa-bbbb-cccc"}}
    st, d = post(client, "/api/onboarding/complete", payload(keys=keys))
    assert st == 200
    ov = settings.load_overrides(settings.default_config_path())
    assert ov["sources.adzuna.enabled"] is True and ov["sources.adzuna.app_key"] == SECRET_KEY
    assert ov["sources.jooble.enabled"] is True and ov["sources.jooble.host"] == "it.jooble.org"
    # i segreti non escono dalle API di lettura
    s, desc = get(client, "/api/settings")
    assert SECRET_KEY not in json.dumps(desc) and "aaaa-bbbb-cccc" not in json.dumps(desc)
    assert SECRET_KEY not in json.dumps(post(client, "/api/onboarding/complete", payload(keys=keys))[1])
    p = get(client, "/api/onboarding")[1]
    assert p["prefill"]["has_adzuna"] is True and SECRET_KEY not in json.dumps(p)


def test_complete_idempotente(client, db):
    b = payload()
    a = post(client, "/api/onboarding/complete", b)[1]
    c = post(client, "/api/onboarding/complete", b)[1]
    assert a["ok"] and c["ok"] and a["profile_id"] == c["profile_id"]
    assert len(prof.ProfileStore(db).list()) == 1
    # cambiando idea la guida aggiorna lo stesso profilo invece di crearne un altro
    b2 = payload(profile={"preset": "custom", "titles": ["cuoco", "pizzaiolo"], "seniority": "any"})
    d = post(client, "/api/onboarding/complete", b2)[1]
    ps = prof.ProfileStore(db).list()
    assert len(ps) == 1 and ps[0].id == a["profile_id"] and ps[0].titles == ["cuoco", "pizzaiolo"]


def test_rifare_la_guida_non_tocca_i_profili_dell_utente(client, db):
    store = prof.ProfileStore(db)
    mio = store.add({"name": "Dati miei", "preset": "data", "include": {"spark": 9}})
    st, d = post(client, "/api/onboarding/complete", payload())
    assert st == 200
    names = sorted(p.name for p in store.list())
    assert "Dati miei" in names and "Infermiere" in names
    assert store.get(mio.id).include == {"spark": 9}


def test_nome_automatico_in_conflitto_prende_un_numero(client, db):
    prof.ProfileStore(db).add({"name": "Infermiere", "preset": "custom", "titles": ["infermiere"]})
    st, d = post(client, "/api/onboarding/complete", payload())
    assert st == 200
    assert "Infermiere 2" in [p.name for p in prof.ProfileStore(db).list()]


def test_nome_scelto_in_conflitto_e_un_errore_leggibile(client, db):
    prof.ProfileStore(db).add({"name": "Scelto", "preset": "data"})
    b = payload(profile={"preset": "custom", "titles": ["x1"], "name": "scelto"})
    st, d = post(client, "/api/onboarding/complete", b)
    assert st == 400 and d["ok"] is False and "esiste già" in d["error"].lower() and d["field"] == "profile"


@pytest.mark.parametrize("mut,field", [
    (lambda b: b.update(profile=None), "profile"),
    (lambda b: b["profile"].update(preset="inesistente"), "profile"),
    (lambda b: b["profile"].update(titles=[]), "profile"),
    (lambda b: b["profile"].update(titles=[f"lavoro{i}" for i in range(9)]), "titles"),
    (lambda b: b["profile"].update(titles="infermiere"), "titles"),
    (lambda b: b["profile"].update(seniority="boss"), "profile"),
    (lambda b: b["profile"].update(remote="si"), "profile"),
    (lambda b: b.update(country="xx"), "country"),
    (lambda b: b.update(country=5), "country"),
    (lambda b: b.update(home="Cittàchenonesiste"), "home"),
    (lambda b: b.update(home=["Roma"]), "home"),
    (lambda b: b.update(radius_km=0), "radius_km"),
    (lambda b: b.update(radius_km=99999), "radius_km"),
    (lambda b: b.update(radius_km="molti"), "radius_km"),
    (lambda b: b.update(radius_km=True), "radius_km"),
    (lambda b: b.update(keys={"adzuna": {"app_id": "solo"}}), "adzuna"),
    (lambda b: b.update(keys={"adzuna": {"app_id": "a b", "app_key": "c d"}}), "adzuna"),
    (lambda b: b.update(keys={"jooble": {"host": "evil.example.com", "api_key": "abc"}}), "jooble"),
    (lambda b: b.update(keys={"jooble": {"host": "jooble.org.evil.com", "api_key": "abc"}}), "jooble"),
    (lambda b: b.update(keys={"jooble": {"host": "it.jooble.org"}}), "jooble"),
    (lambda b: b.update(keys="chiave"), "keys"),
    (lambda b: b.update(report_dir=["x"]), "report_dir"),
    (lambda b: b.update(schedule={"enabled": True, "times": "25:99"}), "schedule"),
    (lambda b: b.update(schedule={"enabled": True, "kind": "every", "hours": 5}), "schedule"),
    (lambda b: b.update(schedule="si"), "schedule"),
])
def test_validazione_server_senza_scrivere_niente(client, db, mut, field):
    b = payload()
    mut(b)
    before = settings.load_overrides(settings.default_config_path())
    st, d = post(client, "/api/onboarding/complete", b)
    assert st == 400 and d["ok"] is False and d["error"] and d["field"] == field, d
    assert "—" not in d["error"]
    assert settings.load_overrides(settings.default_config_path()) == before
    assert [p.name for p in prof.ProfileStore(db).list()] == ["Cybersecurity"]
    assert get(client, "/api/onboarding")[1]["done"] is False


def test_corpo_non_json_e_400(client):
    for path in ("complete", "estimate", "test-adzuna"):
        r = client.post(f"/api/onboarding/{path}", headers=H, data="no", content_type="application/json")
        assert r.status_code == 400
        assert json.loads(r.data)["error"]


def test_report_dir_con_nul_rifiutato(client):
    st, d = post(client, "/api/onboarding/complete", payload(report_dir="/tmp/a\x00b"))
    assert st == 400


def test_atomico_se_il_profilo_fallisce_le_impostazioni_tornano_come_prima(client, db, monkeypatch):
    settings.save_overrides(settings.default_config_path(), {"general.min_score": 20})
    before = settings.load_overrides(settings.default_config_path())

    def boom(*a, **k):
        raise RuntimeError("disco pieno")

    monkeypatch.setattr(prof.ProfileStore, "add", boom)
    monkeypatch.setattr(prof.ProfileStore, "update", boom)
    c = create_app(None, 8765).test_client()
    r = c.post("/api/onboarding/complete", headers=H, data=json.dumps(payload(report_dir="/tmp/x")), content_type="application/json")
    assert r.status_code == 500
    assert settings.load_overrides(settings.default_config_path()) == before
    assert get(c, "/api/onboarding")[1]["done"] is False


def test_scansione_in_corso_blocca_il_completamento(client):
    # simula una scansione in corso avviandone una con una fonte finta lenta non serve: basta lo stato interno
    import threading

    from jobshunter.gui import app as appmod  # noqa: F401

    app = create_app(None, 8765)
    c = app.test_client()
    for fn in app.view_functions.values():
        cl = getattr(fn, "__closure__", None) or ()
        for cell in cl:
            try:
                v = cell.cell_contents
            except ValueError:
                continue
            if isinstance(v, dict) and "running" in v and "cancel" in v:
                v["running"] = True
    st, d = post(c, "/api/onboarding/complete", payload())
    assert st == 409 and d["ok"] is False


# ---------------------------------------------------- pianificazione ----
def test_schedule_attivata_e_installata(client, monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(onboarding.sys, "platform", "darwin")
    b = payload(schedule={"enabled": True, "kind": "daily", "times": "08:30", "notify": False})
    st, d = post(client, "/api/onboarding/complete", b)
    assert st == 200
    assert calls and calls[-1][0] == "install" and calls[-1][1][1] == [(8, 30)]
    ov = settings.load_overrides(settings.default_config_path())
    assert ov["schedule.enabled"] is True and ov["schedule.times"] == "08:30" and ov["schedule.notify"] is False


def test_schedule_spenta_non_tocca_il_sistema(client):
    st, d = post(client, "/api/onboarding/complete", payload(schedule={"enabled": False}))
    assert st == 200 and calls == []


def test_schedule_fallita_non_blocca_il_resto(client, monkeypatch):
    monkeypatch.setattr(onboarding.sys, "platform", "darwin")

    def fail(*a, **k):
        raise RuntimeError("launchctl")

    monkeypatch.setattr(scheduler, "install", fail)
    st, d = post(client, "/api/onboarding/complete", payload(schedule={"enabled": True, "times": "09:00"}))
    assert st == 200 and d["ok"] and any("automatica" in n for n in d["notes"])
    assert settings.load_overrides(settings.default_config_path())["schedule.enabled"] is False
    assert get(client, "/api/onboarding")[1]["done"] is True


# ------------------------------------------------------------- stima ----
def test_stima_senza_chiavi_solo_fonti_gratuite_e_non_scrive(client):
    before = settings.load_overrides(settings.default_config_path())
    st, d = post(client, "/api/onboarding/estimate", payload())
    assert st == 200 and d["ok"]
    assert "adzuna" not in d["requests"] and d["total"] == sum(d["requests"].values())
    assert any("fonti gratuite" in n for n in d["notes"])
    assert settings.load_overrides(settings.default_config_path()) == before


def test_stima_con_chiavi_conta_adzuna(client):
    keys = {"adzuna": {"app_id": SECRET_ID, "app_key": SECRET_KEY}}
    st, d = post(client, "/api/onboarding/estimate", payload(keys=keys))
    assert d["requests"].get("adzuna", 0) > 0
    assert SECRET_KEY not in json.dumps(d)


def test_stima_errore_leggibile(client):
    st, d = post(client, "/api/onboarding/estimate", payload(home="Nowhereville"))
    assert st == 400 and d["field"] == "home"


# ----------------------------------------------- impostazioni (regressione) ----
def test_impostazioni_usa_ancora_la_stessa_validazione(client):
    st, d = post(client, "/api/settings", {"values": {"radius_km": "abc"}})
    assert st == 400 and "numero non valido" in d["error"]
    st, d = post(client, "/api/settings", {"values": {"chiave.inventata": 1}})
    assert st == 400
    st, d = post(client, "/api/settings", {"values": {"radius_km": 99999, "sources.adzuna.app_key": ""}})
    assert st == 200
    assert settings.load_overrides(settings.default_config_path())["radius_km"] == 3000


def test_nessun_trattino_lungo_nei_testi_della_guida():
    src = open(onboarding.__file__, encoding="utf-8").read()
    assert "—" not in src


def test_200_senza_json_non_e_una_chiave_valida(client, monkeypatch):
    class Html(FakeClient):
        def get(self, url, params=None, **k):
            return httpx.Response(200, text="<html>Accedi al Wi-Fi</html>", request=httpx.Request("GET", url))

    monkeypatch.setattr(onboarding, "make_client", lambda: Html())
    d = post(client, "/api/onboarding/test-adzuna", {"app_id": SECRET_ID, "app_key": SECRET_KEY})[1]
    assert d["ok"] is False and d["status"] == "network" and "inattesa" in d["message"]


def test_impostazioni_personali_non_fanno_comparire_la_guida(client):
    post(client, "/api/settings", {"values": {"home": "Roma"}})
    assert get(client, "/api/onboarding")[1]["needed"] is False


def test_numeri_enormi_e_testi_lunghi_sono_400_non_troncati(client):
    for b in (payload(radius_km=1e999), payload(home="x" * 81), payload(report_dir="/a/" + "b" * 600)):
        assert post(client, "/api/onboarding/estimate", b)[0] == 400
    r = client.post("/api/onboarding/complete", headers=H, data=json.dumps(payload()).replace('"radius_km": 50', '"radius_km": Infinity'), content_type="application/json")
    assert r.status_code == 400


def test_report_dir_con_puntini_rifiutata(client):
    assert post(client, "/api/onboarding/complete", payload(report_dir="../../etc"))[0] == 400
    assert post(client, "/api/settings", {"values": {"report.dir": "a/../b"}})[0] == 400


def test_titolo_numerico_non_diventa_nome_numerico(client, db):
    p = payload(profile={"preset": "custom", "titles": ["2024"]})
    assert post(client, "/api/onboarding/complete", p)[0] == 200
    assert [x.name for x in prof.ProfileStore(db).list()] == ["Ricerca 2024"]


def test_pianificazione_ogni_n_ore_si_conserva(client, monkeypatch):
    monkeypatch.setattr(onboarding.sys, "platform", "darwin")
    sched = {"enabled": True, "kind": "every", "hours": 6, "times": "09:00"}
    assert post(client, "/api/onboarding/complete", payload(schedule=sched))[0] == 200
    ov = settings.load_overrides(settings.default_config_path())
    assert ov["schedule.kind"] == "every" and ov["schedule.hours"] == 6
    assert post(client, "/api/onboarding/complete", payload(schedule={"enabled": "false"}))[0] == 400


@pytest.mark.parametrize("path,ok", [("/etc", False), ("/", False), ("/usr/local", False), ("/var/log", False), ("/System/Library", False),
                                     ("/Applications/X", False), ("~/.ssh", False), ("~/.gnupg/x", False), ("~/Library/LaunchAgents", False),
                                     ("~/Documents/JobsHunter", True), ("~/Obsidian/My Vault/Annunci", True), ("reports", True),
                                     ("/Volumes/Disco/Report", True), ("/tmp/jh-report", True)])
def test_cartella_report_zone_di_sistema(client, path, ok):
    st = post(client, "/api/onboarding/estimate", payload(report_dir=path))[0]
    assert (st == 200) == ok
    st2 = post(client, "/api/settings", {"values": {"report.dir": path}})[0]
    assert (st2 == 200) == ok
