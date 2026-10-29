"""SPEC 2.3 e 2.4 (parte punteggio): score_job(profile=None) identico a oggi, punteggio per profilo, job_profiles."""
import json
from pathlib import Path

import pytest

from qa.qa_helpers import call, job, job_profiles, mkprofile, by_name, all_profiles

DATA = Path(__file__).resolve().parent.parent / "data"


def golden():
    return json.loads((DATA / "score_golden.json").read_text(encoding="utf-8"))


def as_job(g):
    from jobshunter.models import Job

    return Job(source="fake", title=g["title"], company=g["company"], location=g["location"], url="https://example.org/x",
               description=g["description"], remote=g["remote"])


def check(r, g):
    exp = g["expected"]
    if exp is None:
        assert r is None, f"{g['title']}: doveva essere scartato"
        return
    assert r is not None, f"{g['title']}: non doveva essere scartato"
    assert (r.score, r.category, r.matched, r.near_home) == (exp["score"], exp["category"], exp["matched"], exp["near_home"]), g["title"]


def test_score_job_senza_profilo_e_identico_a_fase_1(qcfg):
    """Regressione: il comportamento di oggi (cybersecurity da config) non deve cambiare di un punto."""
    from jobshunter.scoring import score_job

    for g in golden():
        check(score_job(as_job(g), qcfg), g)


@pytest.mark.phase2
def test_score_job_profile_none_esplicito_e_identico(qcfg):
    from jobshunter.scoring import score_job

    for g in golden():
        check(score_job(as_job(g), qcfg, profile=None), g)


@pytest.mark.phase2
def test_default_dopo_scansione_ha_gli_stessi_punteggi_di_prima(client, qcfg, qdb, fake_jobs):
    """Il profilo Cybersecurity creato in automatico, dentro una scansione vera, vale quanto il codice di fase 1."""
    from jobshunter.scanner import run_scan

    gs = golden()
    fake_jobs([as_job(g) for g in gs])
    run_scan(qcfg, qdb)
    rows = {r["uid"]: r for r in qdb.conn.execute("SELECT uid, score, category, matched FROM jobs")}
    minscore = qcfg["general"]["min_score"]
    n_checked = 0
    for g in gs:
        j = as_job(g)
        exp = g["expected"]
        if g["location"] not in ("Roma", "Milano", "Torino", "Palermo", "Remote"):
            continue  # le altre sedi dipendono dal filtro di sede (cambia con i paesi): non e' questo il test
        if exp is None or exp["score"] < minscore:
            assert j.uid not in rows, f"{g['title']}: non doveva essere salvato"
            continue
        r = rows.get(j.uid)
        assert r is not None, f"{g['title']}: manca (atteso score {exp['score']})"
        assert (r["score"], r["category"], r["matched"]) == (exp["score"], exp["category"], ",".join(exp["matched"])), g["title"]
        n_checked += 1
    assert n_checked >= 20


def jp_map(db):
    return {(r["job_uid"], r["profile_id"]): r for r in job_profiles(db)}


@pytest.fixture
def three_profiles(client):
    return {
        "nurse": mkprofile(client, name="Infermieri", preset="custom", titles=["infermiere"]),
        "dev": mkprofile(client, name="Sviluppo", preset="software_dev"),
        "cyber": by_name(client, "Cybersecurity"),
    }


JOBS = [
    ("Infermiere professionale", "Humanitas", "Milano", "Reparto di degenza, turni, assistenza ai pazienti."),
    ("Sviluppatore Python Backend", "Engineering", "Roma", "Django Flask REST API SQL, sviluppo backend."),
    ("SOC Analyst", "Acme Security", "Roma", "Triage SIEM EDR incident response."),
    ("Cuoco", "Hotel Excelsior", "Venezia", "Cucina, HACCP."),
]


@pytest.mark.phase2
def test_ogni_annuncio_e_valutato_per_ogni_profilo_attivo(client, qcfg, qdb, fake_jobs, three_profiles):
    from jobshunter.scanner import run_scan

    P = three_profiles
    jobs = [job(t, c, l, d) for t, c, l, d in JOBS]
    fake_jobs(jobs)
    run_scan(qcfg, qdb)
    m = jp_map(qdb)
    nurse, dev, cyber = (P[k]["id"] for k in ("nurse", "dev", "cyber"))
    assert (jobs[0].uid, nurse) in m and m[(jobs[0].uid, nurse)]["score"] >= qcfg["general"]["min_score"]
    assert (jobs[1].uid, dev) in m
    assert (jobs[2].uid, cyber) in m
    assert (jobs[0].uid, cyber) not in m and (jobs[0].uid, dev) not in m, "l'infermiere non e' un lavoro da cybersecurity o da sviluppatore"
    assert (jobs[2].uid, nurse) not in m
    # il cuoco non interessa a nessun profilo: non viene salvato
    assert not qdb.conn.execute("SELECT 1 FROM jobs WHERE uid=?", (jobs[3].uid,)).fetchone()
    # jobs.score = punteggio del profilo ATTIVO piu' alto
    for j in jobs[:3]:
        best = max(r["score"] for (u, _), r in m.items() if u == j.uid)
        assert qdb.conn.execute("SELECT score FROM jobs WHERE uid=?", (j.uid,)).fetchone()[0] == best


@pytest.mark.phase2
def test_scansione_solo_dei_profili_indicati(client, qcfg, qdb, fake_jobs, three_profiles):
    from jobshunter.scanner import run_scan

    P = three_profiles
    jobs = [job(t, c, l, d) for t, c, l, d in JOBS]
    fake_jobs(jobs)
    run_scan(qcfg, qdb, profile_ids=[P["nurse"]["id"]])
    m = jp_map(qdb)
    assert {pid for (_, pid) in m} == {P["nurse"]["id"]}
    assert not qdb.conn.execute("SELECT 1 FROM jobs WHERE uid=?", (jobs[2].uid,)).fetchone(), "il SOC non e' del profilo scansionato"


@pytest.mark.phase2
def test_profilo_spento_non_viene_valutato(client, qcfg, qdb, fake_jobs, three_profiles):
    from jobshunter.scanner import run_scan

    P = three_profiles
    st, d = call(client, "post", f"/api/profiles/{P['nurse']['id']}", {**P["nurse"], "active": False})
    assert st == 200, d
    jobs = [job(t, c, l, d) for t, c, l, d in JOBS]
    fake_jobs(jobs)
    run_scan(qcfg, qdb)
    assert (jobs[0].uid, P["nurse"]["id"]) not in jp_map(qdb)


def scan_with(client, qcfg, qdb, fake_jobs, jobs):
    from jobshunter.scanner import run_scan

    fake_jobs(jobs)
    run_scan(qcfg, qdb)
    return jp_map(qdb)


@pytest.mark.phase2
def test_exclude_scarta_se_nel_titolo(client, qcfg, qdb, fake_jobs):
    p = mkprofile(client, name="Mag", preset="custom", titles=["magazziniere"], exclude=["notte"])
    j1, j2 = job("Magazziniere", "Logista", "Milano", "Gestione merci"), job("Magazziniere turno notte", "Logista", "Milano", "Gestione merci")
    m = scan_with(client, qcfg, qdb, fake_jobs, [j1, j2])
    assert (j1.uid, p["id"]) in m and (j2.uid, p["id"]) not in m


@pytest.mark.phase2
def test_include_aggiunge_keyword_con_peso(client, qcfg, qdb, fake_jobs):
    p = mkprofile(client, name="Mag", preset="custom", titles=["magazziniere"], include={"zzcarrello": 9})
    j1 = job("Magazziniere", "Logista", "Milano", "Uso del zzcarrello elevatore", n=1)
    j2 = job("Magazziniere", "Brt", "Milano", "Gestione merci", n=2)
    m = scan_with(client, qcfg, qdb, fake_jobs, [j1, j2])
    a, b = m[(j1.uid, p["id"])], m[(j2.uid, p["id"])]
    assert "zzcarrello" in a["matched"] and a["score"] > b["score"]


@pytest.mark.phase2
def test_livello_junior_preferito_a_senior(client, qcfg, qdb, fake_jobs):
    p = mkprofile(client, name="Jr", preset="software_dev", seniority="junior")
    jj = job("Junior Python Developer", "Eng", "Roma", "Python Django backend", n=1)
    ss = job("Senior Python Developer", "Eng", "Roma", "Python Django backend", n=2)
    m = scan_with(client, qcfg, qdb, fake_jobs, [jj, ss])
    assert (jj.uid, p["id"]) in m
    if (ss.uid, p["id"]) in m:  # AMBIGUO (vedi qa_notes): scartato o penalizzato, ma mai preferito
        assert m[(jj.uid, p["id"])]["score"] > m[(ss.uid, p["id"])]["score"]


@pytest.mark.phase2
def test_livello_senior_preferito_a_junior(client, qcfg, qdb, fake_jobs):
    p = mkprofile(client, name="Sr", preset="software_dev", seniority="senior")
    jj = job("Junior Python Developer", "Eng", "Roma", "Python Django backend", n=1)
    ss = job("Senior Python Developer", "Eng", "Roma", "Python Django backend", n=2)
    m = scan_with(client, qcfg, qdb, fake_jobs, [jj, ss])
    assert (ss.uid, p["id"]) in m
    if (jj.uid, p["id"]) in m:
        assert m[(ss.uid, p["id"])]["score"] > m[(jj.uid, p["id"])]["score"]


@pytest.mark.phase2
def test_stage_premiati_solo_se_internships(client, qcfg, qdb, fake_jobs):
    pt = mkprofile(client, name="ConStage", preset="software_dev", internships=True)
    pf = mkprofile(client, name="SenzaStage", preset="software_dev", internships=False)
    s = job("Stage Sviluppatore Python", "Eng", "Roma", "Python Django backend sviluppo", n=1)
    m = scan_with(client, qcfg, qdb, fake_jobs, [s])
    assert (s.uid, pt["id"]) in m
    if (s.uid, pf["id"]) in m:
        assert m[(s.uid, pt["id"])]["score"] > m[(s.uid, pf["id"])]["score"]


@pytest.mark.phase2
def test_categoria_per_profili_non_cyber_e_il_nome_del_gruppo(client, qcfg, qdb, fake_jobs):
    p = mkprofile(client, name="Dev", preset="software_dev")
    j = job("Backend Developer Python", "Eng", "Roma", "Python Django REST API", n=1)
    m = scan_with(client, qcfg, qdb, fake_jobs, [j])
    cat = m[(j.uid, p["id"])]["category"]
    assert cat, "categoria vuota"
    st, pre = call(client, "get", "/api/presets")
    labels = {g["label"] for pp in pre if pp["key"] == "software_dev" for g in pp["groups"]}
    assert cat in labels, f"categoria '{cat}' non e' un gruppo del preset ({labels})"


@pytest.mark.phase2
def test_categorie_cyber_restano_quelle_di_oggi(client, qcfg, qdb, fake_jobs):
    j = job("SOC Analyst", "Acme", "Roma", "SIEM Splunk EDR", n=1)
    m = scan_with(client, qcfg, qdb, fake_jobs, [j])
    cyb = by_name(client, "Cybersecurity")["id"]
    assert m[(j.uid, cyb)]["category"] in ("BLUE", "RED", "PURPLE", "SYSADM", "SEC")


@pytest.mark.phase2
def test_bonus_di_vicinanza_usa_la_citta_del_profilo(client, qcfg, qdb, fake_jobs):
    """home_bonus segue la 'location' del profilo, non una citta' fissa."""
    pa = mkprofile(client, name="Vicino Milano", preset="custom", titles=["magazziniere"], location={"city": "Milano", "radius_km": 50})
    pb = mkprofile(client, name="Vicino Napoli", preset="custom", titles=["magazziniere"], location={"city": "Napoli", "radius_km": 50})
    j = job("Magazziniere", "Logista", "Milano", "Gestione merci", n=1)
    m = scan_with(client, qcfg, qdb, fake_jobs, [j])
    sa, sb = m[(j.uid, pa["id"])]["score"], m[(j.uid, pb["id"])]["score"]
    assert sa > sb, f"il bonus 'vicino a casa' doveva premiare solo il profilo di Milano ({sa} vs {sb})"


@pytest.mark.phase2
def test_tabella_job_profiles_chiave_unica_e_nessun_duplicato(client, qcfg, qdb, fake_jobs):
    from jobshunter.scanner import run_scan

    j = job("SOC Analyst", "Acme", "Roma", "SIEM Splunk EDR", n=1)
    fake_jobs([j])
    run_scan(qcfg, qdb)
    run_scan(qcfg, qdb)  # seconda scansione: nessuna riga doppia, nessun errore
    n = qdb.conn.execute("SELECT COUNT(*) FROM job_profiles WHERE job_uid=?", (j.uid,)).fetchone()[0]
    assert n >= 1
    dup = qdb.conn.execute("SELECT job_uid, profile_id, COUNT(*) c FROM job_profiles GROUP BY 1,2 HAVING c>1").fetchall()
    assert not dup
