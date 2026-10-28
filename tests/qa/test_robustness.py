"""Input sporco ed estremo (unicode, stringhe enormi, JSON malformato, campi mancanti, tipi sbagliati): 400 chiaro, MAI 500."""
import json
from urllib.parse import quote

import pytest

from qa.qa_helpers import H, all_profiles, body_with, call, mkprofile, profile_body

pytestmark = pytest.mark.phase2

BAD_RAW = [
    b"", b"{", b"{'a': 1}", b"null", b"[]", b"[1,2,3]", b'"stringa"', b"123", b"true", b'{"name": }', b"\xff\xfe\x00bad",
    b"{" * 5000, b"[" * 100000, b'{"a":' * 3000, b"\x00" * 100, ("{\"name\":\"" + "a" * 2_000_000 + "\"}").encode(),
]
ENDPOINTS_POST = ["/api/profiles", "/api/profiles/preview", "/api/profiles/1", "/api/profiles/1/delete"]


@pytest.mark.parametrize("raw", BAD_RAW, ids=lambda b: f"{b[:12]!r}")
@pytest.mark.parametrize("url", ENDPOINTS_POST)
def test_json_malformato_mai_500(client, url, raw):
    call(client, "post", url, raw=raw)  # call verifica < 500
    assert len(all_profiles(client)) >= 1


@pytest.mark.parametrize("url", ["/api/profiles", "/api/profiles/preview"])
@pytest.mark.parametrize("raw", [b"{}", b'{"name":"x"}', b'{"preset":"data"}'])
def test_corpo_incompleto_400(client, url, raw):
    st, d = call(client, "post", url, raw=raw)
    assert st == 400 and d and d.get("error")


@pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", ""])
def test_content_type_sbagliato(client, ctype):
    for url in ("/api/profiles", "/api/profiles/preview"):
        st, d = call(client, "post", url, raw=json.dumps(profile_body(name="CT")).encode(), ctype=ctype)
        assert st in (200, 400, 415)


UNICODE = ["‮RTL override", "\u0000nul", "á́́́" * 50, "\U0001F600" * 40, "퟿", "��", "​​", "<script>alert(1)</script>",
           "'; DROP TABLE profiles; --", "../../etc/passwd", "%s%s%n{0}{x}", "\r\n\tCRLF", "　　"]


@pytest.mark.parametrize("s", UNICODE, ids=lambda s: repr(s)[:20])
def test_unicode_in_nome_titoli_citta_mai_500(client, s):
    st, d = call(client, "post", "/api/profiles", profile_body(name="U" + s, titles=[s], exclude=[s], include={s: 5},
                                                              location={"city": s, "radius_km": 10}))
    assert st in (200, 400)
    st2, _ = call(client, "post", "/api/profiles/preview", profile_body(name="U" + s, preset="custom", titles=[s or "x"]))
    assert st2 in (200, 400)
    call(client, "get", "/api/profiles")  # l'elenco resta leggibile
    if st == 200:
        got = [p for p in all_profiles(client) if p["name"].startswith("U")]
        assert got and "\x00" not in got[0]["name"]


def test_stringhe_enormi(client):
    huge = "x" * 1_000_000
    for body in (profile_body(name="H1", titles=[huge]), profile_body(name="H2", exclude=[huge]), profile_body(name="H3", include={huge: 3}),
                 profile_body(name=huge), profile_body(name="H5", location={"city": huge, "radius_km": 5}), profile_body(name="H6", titles=["t"] * 100000),
                 profile_body(name="H7", exclude=[str(i) for i in range(50000)]),
                 profile_body(name="H8", include={str(i): 3 for i in range(50000)})):
        st, d = call(client, "post", "/api/profiles", body)
        assert st in (200, 400, 413)
        st2, d2 = call(client, "post", "/api/profiles/preview", dict(body, preset="software_dev"))
        assert st2 in (200, 400, 413)
    assert len(all_profiles(client)) < 20, "limiti sensati: nessuna esplosione di profili"


def test_stringhe_enormi_sono_rifiutate_o_troncate(client):
    st, d = call(client, "post", "/api/profiles", profile_body(name="n" * 100000))
    assert st == 400, "un nome di 100.000 caratteri va rifiutato"
    st, d = call(client, "post", "/api/profiles", profile_body(name="T", preset="custom", titles=["t" * 100000]))
    assert st == 400, "un titolo di 100.000 caratteri va rifiutato"


def test_numeri_estremi(client):
    for r in (2**63, -(2**63), 10**30, float("1e308"), 0.5, 1.0, True, False):
        st, d = call(client, "post", "/api/profiles", profile_body(name=f"N{r!r}", location={"city": "", "radius_km": r}))
        assert st in (200, 400)
    for w in (2**63, 10**30, 0.5, 15.0, True):
        st, d = call(client, "post", "/api/profiles", profile_body(name=f"W{w!r}", include={"a": w}))
        assert st in (200, 400)


@pytest.mark.parametrize("field", ["name", "preset", "active", "titles", "include", "exclude", "seniority", "contracts", "countries", "location", "remote", "internships"])
@pytest.mark.parametrize("value", [None, 0, 1, -1, 3.14, "", "testo", [], {}, [None], [[]], {"a": {"b": 1}}, True, False])
def test_ogni_campo_con_ogni_tipo_mai_500(client, field, value):
    st, d = call(client, "post", "/api/profiles", body_with("Tipi", {field: value}))
    assert st in (200, 400)
    if st == 400:
        assert d and d.get("error")
    st, d = call(client, "post", "/api/profiles/preview", body_with("Tipi", {field: value}))
    assert st in (200, 400)


@pytest.mark.parametrize("missing", ["name", "preset", "titles", "countries", "location", "include", "exclude", "contracts", "seniority", "remote", "internships", "active"])
def test_campo_mancante_mai_500(client, missing):
    b = profile_body(name="Mancante")
    b.pop(missing)
    st, d = call(client, "post", "/api/profiles", b)
    assert st in (200, 400)
    if missing in ("name", "preset"):
        assert st == 400


def test_campi_sconosciuti_ignorati_o_rifiutati(client):
    st, d = call(client, "post", "/api/profiles", dict(profile_body(name="Extra"), id=999, job_count=5, created="x", pippo={"a": 1}, __proto__={"x": 1}))
    assert st in (200, 400)
    if st == 200:
        assert d["profile"]["id"] != 999, "l'id non si sceglie dal client"


def test_aggiornamento_con_id_nel_corpo_diverso(client):
    a, b = mkprofile(client, name="A"), mkprofile(client, name="B")
    st, d = call(client, "post", f"/api/profiles/{a['id']}", dict(a, id=b["id"], name="A2"))
    assert st in (200, 400)
    names = {p["name"] for p in all_profiles(client)}
    assert "B" in names and len(names) == 3, "l'id nel corpo non deve sovrascrivere un altro profilo"


@pytest.mark.parametrize("q", ["limit=abc", "limit=-5", "limit=99999999999999999999", "min=abc", "min=-1", "new=abc", "km=abc&city=Roma",
                               "km=1e9&city=Roma", "city=" + quote("☃"), "city=" + "x" * 5000, "cat=%00", "q=" + "%" * 10, "q=" + quote("'; --"),
                               "ral_min=abc", "ral_min=" + "9" * 30, "where=" + "a" * 10000, "mode=zzz", "contract=zzz", "status=zzz", "group=zzz", "closed=zzz"])
def test_api_jobs_esistente_con_parametri_sporchi_mai_500(client, q):
    st, d = call(client, "get", "/api/jobs?" + q)
    assert st in (200, 400, 422)


@pytest.mark.parametrize("q", ["group=zzz", "profile=abc", "group=" + "x" * 5000, "profile=%00"])
def test_api_facets_con_parametri_sporchi_mai_500(client, q):
    st, d = call(client, "get", "/api/facets?" + q)
    assert st in (200, 400)


@pytest.mark.parametrize("body", [{"cat": 5}, {"min": "abc"}, {"limit": "x"}, {"city": "Roma", "km": "abc"}, {"city": 5}, {"profile": "abc"}, {"profile": [1]}, {"group": 5}])
def test_report_con_input_sporco_mai_500(client, body):
    st, d = call(client, "post", "/api/report", body)
    assert st in (200, 400, 404, 422)


def test_scan_start_corpo_sporco_mai_500(client):
    for raw in (b"{", b"[]", b"null", b'{"profile_ids": null}', b'{"profile_ids": [1, "x", null]}'):
        st, d = call(client, "post", "/api/scan/start", raw=raw)
        assert st in (200, 400)
        from qa.qa_helpers import wait_scan

        wait_scan(client)


def _concorrenti(client, n=6):
    import threading

    res = []

    def go():
        res.append(client.post("/api/profiles", headers=H, json=profile_body(name="Gemello")).status_code)

    ts = [threading.Thread(target=go) for _ in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return res


def test_richieste_concorrenti_creazione_stesso_nome(client):
    """Due creazioni quasi insieme con lo stesso nome (DB gia' aperto): al massimo una passa, nessun 500."""
    all_profiles(client)
    res = _concorrenti(client)
    assert all(r < 500 for r in res), res
    assert sum(1 for p in all_profiles(client) if p["name"] == "Gemello") == 1


def test_prima_apertura_concorrente_del_db_nessun_500(client):
    """B3: piu' richieste insieme sul primo avvio con DB nuovo (migrazione in corso) non devono dare 500
    ('duplicate column name' da ALTER TABLE eseguito due volte)."""
    res = _concorrenti(client)
    assert all(r < 500 for r in res), res
