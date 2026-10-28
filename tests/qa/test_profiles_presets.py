"""SPEC 2.2: preset completi (it ed en obbligatori), gruppi con pesi, blacklist; profilo custom da titoli liberi."""
import tomllib
from pathlib import Path

import pytest

from qa.qa_helpers import call, profile_body

pytestmark = pytest.mark.phase2

ROOT = Path(__file__).resolve().parent.parent.parent
PRESET_KEYS = ["cybersecurity", "it_support", "software_dev", "data", "admin_office", "sales_marketing"]
DASHES = ("—", "–")  # em dash ed en dash: vietati nei testi per l'utente (spec 0.6)


def presets():
    from jobshunter.profiles import PRESETS

    return PRESETS


def test_i_sei_preset_e_custom_esistono():
    p = presets()
    for k in PRESET_KEYS:
        assert k in p, f"manca il preset {k}"


@pytest.mark.parametrize("key", PRESET_KEYS)
def test_preset_completo(key):
    p = presets()[key]
    assert isinstance(p["label"], str) and p["label"].strip()
    assert isinstance(p["description"], str) and p["description"].strip()
    q = p["queries"]
    for lang in ("it", "en"):
        assert q.get(lang) and all(isinstance(x, str) and x.strip() for x in q[lang]), f"{key}: query '{lang}' mancanti"
    assert len(q["it"]) >= 3 and len(q["en"]) >= 3
    for lang, lst in q.items():
        assert lang in ("it", "en", "de", "fr", "es"), f"{key}: lingua inattesa {lang}"
        assert len(set(x.lower() for x in lst)) == len(lst), f"{key}: query duplicate in {lang}"
    assert isinstance(p["blacklist"], (list, tuple, set))
    assert p["groups"], f"{key}: nessun gruppo di keyword"


@pytest.mark.parametrize("key", PRESET_KEYS)
def test_preset_senza_trattini_lunghi_nei_testi(key):
    p = presets()[key]
    assert not any(d in p["label"] + p["description"] for d in DASHES)


def test_preset_non_scarta_se_stesso():
    """Una parola della blacklist non puo' essere anche una query o una keyword dello stesso preset."""
    for key in PRESET_KEYS:
        p = presets()[key]
        bl = {str(b).lower() for b in p["blacklist"]}
        queries = {x.lower() for lst in p["queries"].values() for x in lst}
        assert not (bl & queries), f"{key}: blacklist e query in conflitto: {bl & queries}"
        for q in queries:
            words = set(q.split())
            assert not (bl & words), f"{key}: la query '{q}' contiene una parola in blacklist {bl & words}"


def test_api_presets_forma_e_contenuto(client):
    st, d = call(client, "get", "/api/presets")
    assert st == 200 and isinstance(d, list)
    by = {p["key"]: p for p in d}
    for k in PRESET_KEYS:
        assert k in by
        p = by[k]
        assert p["label"] and p["description"]
        assert isinstance(p["default_titles"], list) and p["default_titles"]
        assert p["groups"] and all(g["label"] and isinstance(g["terms"], dict) and g["terms"] for g in p["groups"])
        for g in p["groups"]:
            for term, w in g["terms"].items():
                assert term.strip() and isinstance(w, int) and 1 <= w <= 15, (k, term, w)
        assert not any(dd in p["label"] + p["description"] for dd in DASHES)
    assert [p["key"] for p in d].count("cybersecurity") == 1


def test_etichette_dei_preset_secondo_la_spec(client):
    st, d = call(client, "get", "/api/presets")
    labels = {p["key"]: p["label"] for p in d}
    assert labels["cybersecurity"].lower().startswith("cybersecurity")
    assert labels["it_support"] == "Sistemista e assistenza IT"
    assert labels["software_dev"] == "Sviluppo software"
    assert labels["data"] == "Dati e analisi"
    assert labels["admin_office"] == "Amministrazione e ufficio"
    assert labels["sales_marketing"] == "Vendite e marketing"


def test_cybersecurity_conserva_le_keyword_del_config_di_oggi(client):
    cfgfile = tomllib.loads((ROOT / "config.example.toml").read_text())
    expected = {c["label"]: c["terms"] for c in cfgfile["keywords"].values()}
    st, d = call(client, "get", "/api/presets")
    groups = {g["label"]: g["terms"] for g in next(p for p in d if p["key"] == "cybersecurity")["groups"]}
    merged = {t: w for g in groups.values() for t, w in g.items()}
    for label, terms in expected.items():
        for term, w in terms.items():
            assert merged.get(term) == w, f"cybersecurity: '{term}' ({label}) atteso peso {w}, trovato {merged.get(term)}"
    assert {"BLUE", "RED", "SYSADM", "SEC"} <= set(groups), f"gruppi trovati: {set(groups)}"


def test_cybersecurity_conserva_la_blacklist_di_oggi():
    cfgfile = tomllib.loads((ROOT / "config.example.toml").read_text())
    bl = {b.lower() for b in presets()["cybersecurity"]["blacklist"]}
    assert set(cfgfile["penalties"]["blacklist"]) <= bl


def test_vendite_non_scarta_le_vendite():
    bl = {b.lower() for b in presets()["sales_marketing"]["blacklist"]}
    assert not ({"sales", "marketing", "vendite", "account executive", "business development"} & bl)


# ---------------------------------------------------------------- profilo custom: query e keyword dai titoli ----
def preview(client, **over):
    st, d = call(client, "post", "/api/profiles/preview", profile_body(preset="custom", **over))
    assert st == 200, d
    return d


def kw(d):
    return {k["term"].lower(): k["weight"] for k in d["keywords"]}


def test_custom_infermiere(client):
    d = preview(client, name="Infermieri", titles=["infermiere"])
    assert "infermiere" in kw(d) and kw(d)["infermiere"] >= 5
    qs = {q["q"].lower() for q in d["queries"]}
    assert "infermiere" in qs
    assert {q["country"] for q in d["queries"]} == {"it"}


def test_custom_titolo_a_due_parole_ha_frase_e_parole_singole(client):
    d = preview(client, name="Mag", titles=["magazziniere carrellista"])
    k = kw(d)
    assert {"magazziniere carrellista", "magazziniere", "carrellista"} <= set(k)
    assert k["magazziniere carrellista"] > k["magazziniere"] and k["magazziniere carrellista"] > k["carrellista"]
    assert k["magazziniere"] > 0 and k["carrellista"] > 0
    assert "magazziniere carrellista" in {q["q"].lower() for q in d["queries"]}


def test_custom_software_engineer_backend(client):
    d = preview(client, name="Dev", titles=["software engineer backend"])
    k = kw(d)
    assert "software engineer backend" in k
    for w in ("software", "engineer", "backend"):
        assert w in k and k[w] < k["software engineer backend"]


@pytest.mark.parametrize("title,stop", [
    ("responsabile di magazzino", ["di"]),
    ("addetto alla vendita", ["alla"]),
    ("head of the kitchen and bar", ["of", "the", "and"]),
    ("chef de cuisine", ["de"]),
    ("jefe de cocina", ["de"]),
    ("leiter der logistik", ["der"]),
])
def test_custom_esclude_le_parole_vuote(client, title, stop):
    d = preview(client, name="X", titles=[title])
    k = kw(d)
    assert title in k, "la frase intera deve restare una keyword"
    for s in stop:
        assert s not in k, f"la parola vuota '{s}' non deve diventare una keyword (trovate: {sorted(k)})"
    assert len(k) >= 2


def test_custom_piu_titoli_aggregati(client):
    d = preview(client, name="Due", titles=["infermiere", "operatore socio sanitario"])
    k = kw(d)
    assert {"infermiere", "operatore socio sanitario", "operatore", "socio", "sanitario"} <= set(k)
    assert {"infermiere", "operatore socio sanitario"} <= {q["q"].lower() for q in d["queries"]}


def test_custom_senza_titoli_non_e_valido(client):
    for t in ([], None, [""], ["   "]):
        body = profile_body(name="Vuoto", preset="custom")
        if t is None:
            body.pop("titles")
        else:
            body["titles"] = t
        st, d = call(client, "post", "/api/profiles", body)
        assert st == 400 and d and d.get("error"), f"titles={t!r}: atteso 400, ottenuto {st}"
        st, d = call(client, "post", "/api/profiles/preview", body)
        assert st == 400, f"anche l'anteprima deve rifiutare custom senza titoli (titles={t!r}): {st}"


def test_titoli_dell_utente_si_aggiungono_a_quelli_del_preset(client):
    st, base = call(client, "post", "/api/profiles/preview", profile_body(preset="software_dev", name="A"))
    st, more = call(client, "post", "/api/profiles/preview", profile_body(preset="software_dev", name="B", titles=["sviluppatore cobol"]))
    qa = {q["q"].lower() for q in base["queries"]}
    qb = {q["q"].lower() for q in more["queries"]}
    assert qa < qb and "sviluppatore cobol" in qb, "i titoli liberi si AGGIUNGONO alle query del preset"
    assert "sviluppatore cobol" in kw(more)


def test_preview_include_e_pesi_entro_i_limiti(client):
    d = preview(client, name="Inc", titles=["autista"], include={"patente c": 12})
    assert kw(d).get("patente c") == 12
    for k in d["keywords"]:
        assert isinstance(k["weight"], int) and 1 <= k["weight"] <= 40, k
        assert k.get("group")
