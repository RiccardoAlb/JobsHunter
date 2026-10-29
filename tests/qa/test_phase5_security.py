"""Fase 5, audit di sicurezza: Origin/Host su ogni richiesta che modifica dati, limiti di dimensione, intestazioni, segreti, permessi."""
import re
import stat
from pathlib import Path

import sys

import pytest

from qa.qa_helpers import H, call, jget

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "jobshunter"
SECRET = "ZEBRA-QUOKKA-9913"


def routes(client):
    return sorted((r.rule, sorted(r.methods - {"HEAD", "OPTIONS"})) for r in client.application.url_map.iter_rules() if r.endpoint != "static")


def test_bind_solo_su_localhost():
    for f in PKG.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "0.0.0.0" not in text and '"::"' not in text, f
        for m in re.finditer(r"\b\w*app\.run\(([^)]*)\)", text):
            assert 'host="127.0.0.1"' in m.group(1), (f, m.group(0))


def test_nessuna_shell_con_input_utente():
    for f in PKG.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "shell=True" not in text and "os.system(" not in text and "os.popen(" not in text, f
        assert not re.search(r"\b(eval|exec)\(", text.replace("re.exec(", "")), f
        assert "pickle" not in text and "yaml.load(" not in text, f


def test_nessun_innerhtml_nella_pagina():
    html = (PKG / "gui" / "static" / "index.html").read_text(encoding="utf-8")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write(", "eval(", "new Function("):
        assert bad not in html, bad


def test_sql_solo_con_segnaposto():
    """Nei f-string delle query ci sono solo costanti del codice (nomi di colonna da whitelist), mai valori."""
    text = (PKG / "db.py").read_text(encoding="utf-8")
    for m in re.finditer(r'execute\(f"([^"]*)"', text):
        sql = m.group(1)
        for expr in re.findall(r"\{([^}]*)\}", sql):
            assert re.fullmatch(r"[A-Za-z_.' ,*()?]+", expr) and "request" not in expr, sql


@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_origin_estraneo_rifiutato_su_ogni_metodo_che_modifica(client, method):
    for rule, methods in routes(client):
        if rule.startswith("/api/") and "<" not in rule:
            r = getattr(client, method)(rule, headers=dict(H, Origin="http://evil.example"), json={})
            assert r.status_code in (403,), (method, rule, r.status_code)


def test_ogni_post_dell_api_rifiuta_origin_estraneo_anche_con_parametri(client):
    n = 0
    for rule, methods in routes(client):
        if "POST" in methods:
            url = re.sub(r"<[^>]*int:[^>]*>", "1", rule)
            url = re.sub(r"<[^>]+>", "x", url)
            r = client.post(url, headers=dict(H, Origin="http://evil.example"), json={})
            assert r.status_code == 403, (url, r.status_code)
            r = client.post(url, headers=dict(H, Origin="null"), json={})
            assert r.status_code == 403, (url, "null")
            n += 1
    assert n >= 25


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_sec_fetch_site_esterno_rifiutato(client, site):
    r = client.post("/api/news/ack", headers=dict(H, **{"Sec-Fetch-Site": site}), json={})
    assert r.status_code == 403


def test_richiesta_same_origin_ammessa(client):
    r = client.post("/api/news/ack", headers=dict(H, Origin="http://127.0.0.1:8765", **{"Sec-Fetch-Site": "same-origin"}), json={})
    assert r.status_code == 200


def test_host_estraneo_rifiutato_anche_in_get(client):
    for host in ("evil.example", "127.0.0.1:9999", "127.0.0.1.evil.example:8765", "localhost"):
        assert client.get("/api/settings", headers={"Host": host}).status_code == 403, host


def test_corpo_json_grande_rifiutato(client):
    big = {"name": "x" * 300_000}
    assert call(client, "post", "/api/profiles", big)[0] == 413
    assert call(client, "post", "/api/settings", {"values": {"home": "y" * 300_000}})[0] == 413


def test_il_cv_puo_essere_piu_grande_ma_non_oltre_il_limite(client):
    r = client.post("/api/cv", headers=H, json={"text": "a " * (150 * 1024)})
    assert r.status_code != 413
    r = client.post("/api/cv", headers=H, data=b"a" * (7 * 1024 * 1024), content_type="application/json")
    assert r.status_code == 413


def test_intestazioni_di_sicurezza(client):
    for url in ("/", "/api/settings"):
        r = client.get(url, headers=H)
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        csp = r.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
        assert "http" not in csp.replace("'self'", ""), "nessun dominio esterno ammesso"
        assert r.headers["Cache-Control"] == "no-store"


def test_la_pagina_non_carica_risorse_esterne():
    html = (PKG / "gui" / "static" / "index.html").read_text(encoding="utf-8")
    for m in re.finditer(r'(?:src|href)=["\'](https?://[^"\']+)', html):
        raise AssertionError(f"risorsa esterna caricata dalla pagina: {m.group(1)}")


def test_nessun_segreto_nelle_risposte(client, home):
    assert call(client, "post", "/api/settings", {"values": {"sources.adzuna.app_key": SECRET, "sources.jooble.api_key": SECRET + "J", "notify.topic": "topic-x"}})[0] == 200
    for url in ("/api/settings", "/api/onboarding", "/api/profiles", "/api/stats", "/api/schedule", "/api/scans", "/api/cv", "/api/jobs"):
        r = client.get(url, headers=H)
        assert SECRET not in r.get_data(as_text=True), url
    d = jget(client.get("/api/settings", headers=H))
    f = {x["key"]: x for x in d["fields"]}
    assert f["sources.adzuna.app_key"]["value"] == "" and f["sources.adzuna.app_key"]["set"] is True


def test_nessun_segreto_nei_log(client, home, caplog):
    import logging

    from jobshunter import settings

    caplog.set_level(logging.DEBUG)
    settings.save_overrides(home / "config.toml", {"sources.adzuna.app_key": SECRET, "sources.adzuna.app_id": "idfinto"})
    client.get("/api/settings", headers=H)
    client.post("/api/settings", headers=H, json={"values": {"sources.jooble.api_key": SECRET + "K"}})
    assert SECRET not in caplog.text
    assert logging.getLogger("httpx").level >= logging.WARNING


@pytest.mark.skipif(sys.platform.startswith("win"), reason="permessi POSIX (chmod/st_mode/umask): su Windows la protezione e' icacls (provata in test_portability)")
def test_permessi_riservati_su_config_settings_db_cv(client, home):
    client.post("/api/settings", headers=H, json={"values": {"general.min_score": 20}})
    client.get("/api/stats", headers=H)
    assert call(client, "post", "/api/cv", {"text": "Esperto SOC con Splunk e Wazuh, esperienza in analisi dei log e incident response. " * 20})[0] == 200
    for name in ("config.toml", "settings.json", "cv.json", "jobshunter.db"):
        p = home / name
        assert p.exists(), name
        assert stat.S_IMODE(p.stat().st_mode) == 0o600, (name, oct(p.stat().st_mode))


def test_path_traversal_sugli_asset(client):
    for url in ("/assets/../index.html", "/assets/..%2f..%2fsettings.py", "/assets/%2e%2e/%2e%2e/config.toml", "/assets/x.png/../../app.py",
                "/assets/..\\..\\x.png", "/assets//etc/passwd.png", "/assets/%00.png"):
        r = client.get(url, headers=H)
        assert r.status_code in (308, 400, 404), (url, r.status_code)
    assert client.get("/assets/index.html", headers=H).status_code == 404


def test_cartella_report_non_puo_essere_di_sistema(client, home):
    for bad in ("/etc", "../../x", "~/.ssh", "/System/Library"):
        assert call(client, "post", "/api/settings", {"values": {"report.dir": bad}})[0] == 400, bad


def test_esportazione_csv_neutralizza_le_formule():
    from jobshunter.cli import _csv_safe

    assert _csv_safe("=HYPERLINK(\"http://evil\")") == "'=HYPERLINK(\"http://evil\")"
    for s in ("+1", "-2", "@x"):
        assert _csv_safe(s).startswith("'")
    assert _csv_safe("SOC Analyst") == "SOC Analyst" and _csv_safe(42) == 42


def test_contatto_con_a_capo_rifiutato_dall_api(client):
    assert call(client, "post", "/api/settings", {"values": {"net.contact": "a\r\nX-Evil: 1"}})[0] == 400
    assert call(client, "post", "/api/settings", {"values": {"net.contact": "me@example.org"}})[0] == 200
    d = jget(client.get("/api/settings", headers=H))
    assert "contact: me@example.org" in d["user_agent"]
