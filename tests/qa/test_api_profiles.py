"""SPEC 6: API dei profili (CRUD, preview, validazioni -> 400 e mai 500), profile= su jobs e facets, scan/start con profile_ids."""
import pytest

from qa.qa_helpers import H, wait_scan, all_profiles, body_with, by_name, call, job, mkprofile, profile_body

pytestmark = pytest.mark.phase2


def test_db_nuovo_ha_il_profilo_cybersecurity(client):
    ps = all_profiles(client)
    assert [p["name"] for p in ps] == ["Cybersecurity"]
    p = ps[0]
    assert p["preset"] == "cybersecurity" and p["active"] is True and p["countries"] == ["it"]
    assert {"id", "created", "updated", "job_count"} <= set(p)
    assert p["job_count"] == 0


def test_crea_leggi_aggiorna_elimina(client):
    p = mkprofile(client, name="Sviluppo", preset="software_dev", titles=["sviluppatore rust"], countries=["it", "de"],
                  location={"city": "Palermo", "radius_km": 150}, seniority="junior", contracts=["permanent"], exclude=["stage"],
                  include={"rust": 8})
    assert isinstance(p["id"], int)
    got = by_name(client, "Sviluppo")
    for k in ("preset", "titles", "countries", "seniority", "contracts", "exclude", "include", "remote", "internships", "active"):
        assert got[k] == p[k], k
    assert got["location"]["city"] == "Palermo" and got["location"]["radius_km"] == 150
    # aggiorna
    st, d = call(client, "post", f"/api/profiles/{p['id']}", {**p, "name": "Sviluppo 2", "countries": ["it"], "active": False, "seniority": "any"})
    assert st == 200 and d["ok"]
    got = by_name(client, "Sviluppo 2")
    assert got["countries"] == ["it"] and got["active"] is False and got["seniority"] == "any" and got["id"] == p["id"]
    assert "Sviluppo" not in [x["name"] for x in all_profiles(client)]
    # elimina
    st, d = call(client, "post", f"/api/profiles/{p['id']}/delete")
    assert st == 200
    assert "Sviluppo 2" not in [x["name"] for x in all_profiles(client)]


def test_solo_nome_e_preset_bastano(client):
    st, d = call(client, "post", "/api/profiles", {"name": "Minimo", "preset": "data"})
    assert st == 200 and d["ok"], d
    p = d["profile"]
    assert p["countries"] == ["it"] and p["seniority"] == "any" and p["remote"] in (True, False) and p["active"] is True


def test_profilo_personalizzato_valido(client):
    st, d = call(client, "post", "/api/profiles", {"name": "Infermieri", "preset": "custom", "titles": ["infermiere"]})
    assert st == 200 and d["ok"]


def test_nome_con_spazi_ai_bordi_viene_normalizzato(client):
    p = mkprofile(client, name="   Con spazi   ")
    assert p["name"] == "Con spazi"


@pytest.mark.parametrize("override,why", [
    ({"name": ""}, "nome vuoto"), ({"name": "   "}, "nome solo spazi"), ({"name": None}, "nome null"), ({"name": 5}, "nome numero"),
    ({"name": "x" * 300}, "nome enorme"),
    ({"preset": "nope"}, "preset sconosciuto"), ({"preset": ""}, "preset vuoto"), ({"preset": 3}, "preset numero"),
    ({"countries": ["xx"]}, "paese sconosciuto"), ({"countries": ["it", "zz"]}, "un paese sconosciuto fra validi"),
    ({"countries": "it"}, "paesi stringa"), ({"countries": [1]}, "paesi numeri"), ({"countries": [None]}, "paese null"),
    ({"seniority": "boss"}, "seniority"), ({"seniority": 3}, "seniority numero"),
    ({"contracts": ["foo"]}, "contratto"), ({"contracts": "fixed"}, "contratti stringa"), ({"contracts": ["permanent", 7]}, "contratto numero"),
    ({"location": {"city": "", "radius_km": 0}}, "raggio 0"), ({"location": {"city": "", "radius_km": -5}}, "raggio negativo"),
    ({"location": {"city": "", "radius_km": 3001}}, "raggio 3001"), ({"location": {"city": "", "radius_km": "abc"}}, "raggio testo"),
    ({"location": {"city": "", "radius_km": None}}, "raggio null"), ({"location": {"city": "", "radius_km": 1e9}}, "raggio enorme"),
    ({"location": "Palermo"}, "location stringa"), ({"location": {"city": 5, "radius_km": 10}}, "citta numero"),
    ({"remote": "forse"}, "remote testo"), ({"internships": "boh"}, "internships testo"), ({"active": "si"}, "active testo"),
    ({"titles": "infermiere"}, "titles stringa"), ({"titles": [1, 2]}, "titles numeri"), ({"titles": [["x"]]}, "titles annidati"),
    ({"exclude": "sales"}, "exclude stringa"), ({"exclude": [None]}, "exclude null"),
    ({"include": ["a"]}, "include lista"), ({"include": {"a": 0}}, "peso 0"), ({"include": {"a": 16}}, "peso 16"),
    ({"include": {"a": "x"}}, "peso testo"), ({"include": {"a": -3}}, "peso negativo"), ({"include": {"": 5}}, "termine vuoto"),
])
def test_creazione_rifiuta_con_400(client, override, why):
    st, d = call(client, "post", "/api/profiles", body_with("Valido", override))
    assert st == 400, f"{why}: atteso 400, ottenuto {st} {d}"
    assert d and isinstance(d.get("error"), str) and d["error"].strip(), f"{why}: serve un messaggio 'error'"
    assert "—" not in d["error"]
    assert [p["name"] for p in all_profiles(client)] == ["Cybersecurity"], f"{why}: un profilo non valido e' stato salvato"


@pytest.mark.parametrize("override", [
    {"location": {"city": "", "radius_km": 1}}, {"location": {"city": "", "radius_km": 3000}}, {"seniority": "junior"},
    {"seniority": "mid"}, {"seniority": "senior"}, {"contracts": ["internship", "apprenticeship", "fixed", "permanent", "other"]},
    {"countries": ["it", "gb", "de", "fr", "es", "nl", "at", "ch", "be", "pl", "us", "ca", "au", "br", "in", "mx", "nz", "sg", "za"]},
    {"include": {"a": 1}}, {"include": {"a": 15}}, {"remote": False}, {"internships": False}, {"active": False},
    {"name": "Nome con emoji \U0001F680 e accenti èù"}, {"name": "x" * 60}, {"titles": ["caffè ☕", "日本語"]},
])
def test_valori_ai_limiti_sono_accettati(client, override):
    st, d = call(client, "post", "/api/profiles", body_with("Limite", override))
    assert st == 200 and d["ok"], f"{override}: {st} {d}"


def test_nome_duplicato_rifiutato(client):
    mkprofile(client, name="Uno")
    st, d = call(client, "post", "/api/profiles", profile_body(name="Uno"))
    assert st == 400 and d["error"]
    st, d = call(client, "post", "/api/profiles", profile_body(name="Cybersecurity"))
    assert st == 400


def test_nome_duplicato_ignorando_maiuscole(client):
    """AMBIGUO (qa_notes N3): scelgo che 'uno' e 'Uno' siano lo stesso nome, per non confondere l'utente."""
    mkprofile(client, name="Uno")
    st, d = call(client, "post", "/api/profiles", profile_body(name="uno"))
    assert st == 400


def test_aggiornamento_con_proprio_nome_ok_con_nome_altrui_no(client):
    a, b = mkprofile(client, name="A"), mkprofile(client, name="B")
    st, d = call(client, "post", f"/api/profiles/{a['id']}", {**a, "titles": ["x"]})
    assert st == 200
    st, d = call(client, "post", f"/api/profiles/{a['id']}", {**a, "name": "B"})
    assert st == 400
    assert by_name(client, "A")["id"] == a["id"]


def test_aggiornamento_non_valido_non_modifica(client):
    a = mkprofile(client, name="A", titles=["uno"])
    st, d = call(client, "post", f"/api/profiles/{a['id']}", {**a, "countries": ["xx"], "titles": ["due"]})
    assert st == 400
    g = by_name(client, "A")
    assert g["countries"] == ["it"] and g["titles"] == ["uno"]


@pytest.mark.parametrize("pid", ["99999", "0", "-1", "abc", "1.5", "%00", "9" * 40])
def test_id_inesistente_o_strano(client, pid):
    st, d = call(client, "post", f"/api/profiles/{pid}", profile_body(name="Fantasma"))
    assert st in (400, 404)
    st, d = call(client, "post", f"/api/profiles/{pid}/delete")
    assert st in (400, 404)


def test_non_si_elimina_l_ultimo_profilo(client):
    only = all_profiles(client)[0]
    st, d = call(client, "post", f"/api/profiles/{only['id']}/delete")
    assert st == 400 and d["error"]
    assert len(all_profiles(client)) == 1
    other = mkprofile(client, name="Altro")
    st, d = call(client, "post", f"/api/profiles/{only['id']}/delete")
    assert st == 200
    st, d = call(client, "post", f"/api/profiles/{other['id']}/delete")
    assert st == 400


def test_eliminare_un_profilo_conserva_gli_annunci(client, qcfg, qdb, fake_jobs):
    """AMBIGUO (qa_notes N5): gli annunci restano nell'archivio; spariscono solo le valutazioni di quel profilo."""
    from jobshunter.scanner import run_scan

    p = mkprofile(client, name="Infermieri", preset="custom", titles=["infermiere"])
    j = job("Infermiere professionale", "Humanitas", "Milano", "Reparto turni assistenza")
    fake_jobs([j])
    run_scan(qcfg, qdb)
    assert qdb.conn.execute("SELECT COUNT(*) FROM job_profiles WHERE profile_id=?", (p["id"],)).fetchone()[0] == 1
    st, d = call(client, "post", f"/api/profiles/{p['id']}/delete")
    assert st == 200
    assert qdb.conn.execute("SELECT COUNT(*) FROM job_profiles WHERE profile_id=?", (p["id"],)).fetchone()[0] == 0
    assert qdb.conn.execute("SELECT COUNT(*) FROM jobs WHERE uid=?", (j.uid,)).fetchone()[0] == 1


def test_job_count(client, qcfg, qdb, fake_jobs):
    from jobshunter.scanner import run_scan

    p = mkprofile(client, name="Infermieri", preset="custom", titles=["infermiere"])
    fake_jobs([job("Infermiere professionale", "Humanitas", "Milano", "Reparto turni assistenza", n=1),
               job("Infermiere di sala", "Humanitas", "Roma", "Sala operatoria assistenza", n=2),
               job("SOC Analyst", "Acme", "Roma", "SIEM EDR", n=3)])
    run_scan(qcfg, qdb)
    assert by_name(client, "Infermieri")["job_count"] == 2
    assert by_name(client, "Cybersecurity")["job_count"] == 1


# --------------------------------------------------------------------- preview ----
def test_preview_forma_e_non_salva(client):
    st, d = call(client, "post", "/api/profiles/preview", profile_body(name="Anteprima", preset="software_dev", countries=["it", "de"]))
    assert st == 200
    assert set(d) >= {"queries", "keywords", "requests", "notes"}
    assert d["queries"] and all({"q", "country", "where", "pages"} <= set(q) for q in d["queries"])
    assert d["keywords"] and all({"term", "weight", "group"} <= set(k) for k in d["keywords"])
    assert isinstance(d["requests"], dict) and isinstance(d["notes"], list)
    assert all(isinstance(n, str) and "—" not in n for n in d["notes"])
    assert [p["name"] for p in all_profiles(client)] == ["Cybersecurity"], "l'anteprima NON deve salvare"


def test_preview_accetta_il_nome_di_un_profilo_esistente(client):
    """L'anteprima serve anche in modifica: non deve protestare per il nome gia' usato dallo stesso profilo."""
    p = mkprofile(client, name="Esiste")
    body = {k: v for k, v in p.items() if k not in ("id", "created", "updated", "job_count")}
    st, d = call(client, "post", "/api/profiles/preview", body)
    assert st == 200, d


def test_preview_note_avvisano_se_manca_la_chiave(client):
    st, d = call(client, "post", "/api/profiles/preview", profile_body(name="X", preset="software_dev"))
    assert st == 200
    assert d["notes"], "senza chiavi Adzuna/Jooble l'utente deve essere avvisato in una nota"


@pytest.mark.parametrize("over", [{"preset": "nope"}, {"countries": ["xx"]}, {"location": {"city": "", "radius_km": 0}}, {"seniority": "boss"}, {"contracts": ["foo"]}])
def test_preview_rifiuta_con_400(client, over):
    st, d = call(client, "post", "/api/profiles/preview", body_with("P", over))
    assert st == 400 and d["error"]


# --------------------------------------------------------------------- jobs e facets per profilo ----
@pytest.fixture
def popolato(client, qcfg, qdb, fake_jobs):
    from jobshunter.scanner import run_scan

    nurse = mkprofile(client, name="Infermieri", preset="custom", titles=["infermiere"])
    cyber = by_name(client, "Cybersecurity")
    jobs = [job("Infermiere professionale", "Humanitas", "Milano", "Reparto turni assistenza", n=1),
            job("Infermiere di sala", "Gruppo San Donato", "Roma", "Sala operatoria assistenza", n=2),
            job("SOC Analyst", "Acme Security", "Roma", "SIEM EDR incident response", n=3),
            job("Penetration Tester", "Cyberia", "Torino", "Metasploit Burp OSCP", n=4)]
    fake_jobs(jobs)
    run_scan(qcfg, qdb)
    return {"nurse": nurse, "cyber": cyber, "jobs": jobs}


def uids(client, q):
    st, d = call(client, "get", "/api/jobs?" + q)
    assert st == 200, d
    return {j["uid"] for j in d}, d


def test_jobs_per_profilo(client, popolato):
    P, J = popolato, popolato["jobs"]
    allu, _ = uids(client, "profile=all")
    assert allu == {j.uid for j in J}
    nurse, rows = uids(client, f"profile={P['nurse']['id']}")
    assert nurse == {J[0].uid, J[1].uid}
    cyber, _ = uids(client, f"profile={P['cyber']['id']}")
    assert cyber == {J[2].uid, J[3].uid}
    noparam, _ = uids(client, "")
    assert noparam == allu, "senza profile= il comportamento di oggi: tutti"


def test_job_dict_ha_profili_e_paese(client, popolato):
    _, rows = uids(client, "profile=all")
    by = {r["uid"]: r for r in rows}
    j = by[popolato["jobs"][0].uid]
    assert "country" in j
    assert isinstance(j["profiles"], list) and j["profiles"]
    for p in j["profiles"]:
        assert set(p) >= {"id", "name", "score"} and isinstance(p["score"], int)
    assert [p["name"] for p in j["profiles"]] == ["Infermieri"]
    for k in ("uid", "title", "company", "location", "url", "score", "category", "status", "mode", "contract", "matched"):
        assert k in j, f"campo di oggi sparito: {k}"
    assert not any(v is None and k in ("title", "company", "profiles") for k, v in j.items())


def test_facets_per_profilo(client, popolato):
    st, allf = call(client, "get", "/api/facets?profile=all")
    st, nf = call(client, "get", f"/api/facets?profile={popolato['nurse']['id']}")
    assert st == 200
    assert sum(c["n"] for c in allf["companies"]) == 4 and sum(c["n"] for c in nf["companies"]) == 2
    st, nof = call(client, "get", "/api/facets")
    assert nof == allf


@pytest.mark.parametrize("val", ["abc", "-1", "99999", "1.5", "", "%00", "1;DROP TABLE jobs", "9" * 50, "all,all", "☃"])
def test_profile_param_strano_mai_500(client, popolato, val):
    from urllib.parse import quote

    for url in ("/api/jobs?profile=", "/api/facets?profile="):
        st, d = call(client, "get", url + quote(val))
        assert st in (200, 400, 404)
    n = call(client, "get", "/api/jobs?profile=all")[1]
    assert len(n) == 4, "un parametro strano non deve rovinare i dati"


# --------------------------------------------------------------------- scan/start con profile_ids ----
def test_scan_start_senza_corpo_come_oggi(client, fake_jobs):
    fake_jobs([])
    r = client.post("/api/scan/start", headers=H)
    assert r.status_code == 200
    wait_scan(client)


def test_scan_start_con_profile_ids(client, popolato, fake_jobs):
    # nuovo annuncio infermiere: solo il profilo scelto lo deve vedere
    fake_jobs([job("Infermiere pediatrico", "Meyer", "Firenze", "Reparto pediatria assistenza turni", n=77),
               job("SOC Analyst II", "Zeta Cyber", "Roma", "SIEM EDR", n=78)])
    st, d = call(client, "post", "/api/scan/start", {"profile_ids": [popolato["nurse"]["id"]]})
    assert st == 200 and d["ok"]
    wait_scan(client)
    names = {j["title"] for j in call(client, "get", "/api/jobs?profile=all")[1]}
    assert "Infermiere pediatrico" in names and "SOC Analyst II" not in names


@pytest.mark.parametrize("body", [
    {"profile_ids": "1"}, {"profile_ids": [999999]}, {"profile_ids": ["a"]}, {"profile_ids": [None]}, {"profile_ids": {"a": 1}},
    {"profile_ids": [1.5]}, {"profile_ids": [-1]}, {"profile_ids": list(range(1, 5000))}, {"profile_ids": [True]},
])
def test_scan_start_profile_ids_sporchi_400(client, body):
    st, d = call(client, "post", "/api/scan/start", body)
    assert st == 400 and d.get("error")
    assert call(client, "get", "/api/status")[1]["running"] is False, "non deve partire alcuna scansione"


def test_scan_start_profile_ids_vuoto_significa_tutti_o_400(client, fake_jobs):
    fake_jobs([])
    st, d = call(client, "post", "/api/scan/start", {"profile_ids": []})
    assert st in (200, 400)
    wait_scan(client)


def test_scan_start_tutti_i_profili_attivi(client, popolato, fake_jobs):
    fake_jobs([job("Infermiere geriatrico", "RSA Serena", "Bologna", "Assistenza anziani turni", n=91),
               job("Pentester Junior", "Hacklab", "Roma", "Metasploit Burp OSCP", n=92)])
    st, d = call(client, "post", "/api/scan/start", {})
    assert st == 200
    wait_scan(client)
    names = {j["title"] for j in call(client, "get", "/api/jobs?profile=all")[1]}
    assert {"Infermiere geriatrico", "Pentester Junior"} <= names


def test_origine_esterna_rifiutata_sulle_api_nuove(client):
    h = {"Origin": "http://evil.com"}
    for url in ("/api/profiles", "/api/profiles/preview", "/api/profiles/1", "/api/profiles/1/delete"):
        r = client.post(url, headers={**H, **h}, json=profile_body())
        assert r.status_code == 403, url
    r = client.post("/api/profiles", headers={"Host": "evil.com"}, json=profile_body())
    assert r.status_code == 403
    r = client.get("/api/profiles", headers={"Host": "evil.com"})
    assert r.status_code == 403
