"""Giro 2: coerenza funzionale con profili liberi, due paesi, fonte finta con settori misti."""
import pytest

from jobshunter.models import Job
from qa.qa_helpers import all_profiles, by_name, call, mkprofile

pytestmark = pytest.mark.phase2


def J(title, loc, country="", remote=False, desc="", company="Azienda", n=0):
    return Job(source="fake", title=title, company=company + str(n or abs(hash((title, loc))) % 9999), location=loc,
               url=f"https://example.org/{abs(hash((title, loc, country)))}", description=desc, remote=remote, country=country)


def scan_titles(client, qcfg, qdb, fake_jobs, jobs, pid):
    from jobshunter.scanner import run_scan

    fake_jobs(jobs)
    run_scan(qcfg, qdb, profile_ids=[pid])
    return {r["title"] for r in qdb.conn.execute("SELECT j.title FROM job_profiles p JOIN jobs j ON j.uid=p.job_uid WHERE p.profile_id=?", (pid,))}


MIXED = [
    J("Infermiere professionale", "Milano", "it"), J("Krankenpfleger (m/w/d)", "Berlin", "de"), J("Nurse", "London", "gb"),
    J("Infermiere", "Remote - USA", "us", remote=True), J("Infermiera domiciliare", "Lombardia", ""),
    J("Infermiere", "Remote", "fr", remote=True), J("Cuoco", "Milano", "it"), J("Software Engineer", "Berlin", "de"),
    J("Infermieri pediatrici", "Roma", "it"), J("Krankenpfleger Intensiv", "Zurich", "ch"), J("Infermiere", "Napoli", "it"),
]


def test_custom_infermiere_due_paesi(client, qcfg, qdb, fake_jobs):
    p = mkprofile(client, name="Infermieri", preset="custom", titles=["infermiere", "Krankenpfleger"], countries=["it", "de"])
    got = scan_titles(client, qcfg, qdb, fake_jobs, MIXED, p["id"])
    assert {"Infermiere professionale", "Krankenpfleger (m/w/d)", "Infermiera domiciliare", "Infermieri pediatrici"} <= got
    for bad in ("Cuoco", "Software Engineer", "Nurse", "Krankenpfleger Intensiv"):
        assert bad not in got, f"'{bad}' non dovrebbe essere pertinente (paese o mestiere sbagliato)"


def test_remoto_di_un_altro_paese_dipende_dal_flag_remote(client, qcfg, qdb, fake_jobs):
    on = mkprofile(client, name="ConRemoto", preset="custom", titles=["infermiere"], countries=["it"], remote=True)
    off = mkprofile(client, name="SenzaRemoto", preset="custom", titles=["infermiere"], countries=["it"], remote=False)
    j = J("Infermiere", "Remote", "fr", remote=True, n=7)
    from jobshunter.scanner import run_scan

    fake_jobs([j])
    run_scan(qcfg, qdb)
    rows = {r["profile_id"] for r in qdb.conn.execute("SELECT profile_id FROM job_profiles WHERE job_uid=?", (j.uid,))}
    assert on["id"] in rows and off["id"] not in rows


@pytest.mark.parametrize("region", ["Lombardia", "Lazio", "Sicilia", "Veneto", "Toscana", "Emilia-Romagna", "Campania", "Puglia"])
def test_regione_italiana_con_paese_ignoto_passa_per_profilo_italia(client, qcfg, qdb, fake_jobs, region):
    """B6: le righe migrate (country vuoto) e le fonti globali hanno sedi come 'Lombardia': per un profilo solo Italia sono Italia."""
    p = mkprofile(client, name="Infermieri", preset="custom", titles=["infermiere"], countries=["it"])
    got = scan_titles(client, qcfg, qdb, fake_jobs, [J("Infermiere", region, "", n=3)], p["id"])
    assert "Infermiere" in got, f"sede {region!r} scartata"


def test_parole_singole_generiche_non_rendono_pertinente_qualunque_cosa(client, qcfg, qdb, fake_jobs):
    """'software engineer backend': 'Mechanical Engineer' non c'entra, 'Backend Developer' si'."""
    p = mkprofile(client, name="Dev", preset="custom", titles=["software engineer backend"], countries=["it"])
    jobs = [J("Backend Developer", "Roma", "it", desc="API REST", n=1), J("Mechanical Engineer", "Roma", "it", n=2),
            J("Software Engineer Backend", "Roma", "it", n=3), J("Civil Engineer", "Milano", "it", n=4), J("Software Tester", "Milano", "it", n=5),
            J("Frontend Developer", "Roma", "it", n=6)]
    got = scan_titles(client, qcfg, qdb, fake_jobs, jobs, p["id"])
    assert {"Software Engineer Backend", "Backend Developer"} <= got
    assert not ({"Mechanical Engineer", "Civil Engineer"} & got), f"ingegneri non software scambiati per pertinenti: {got}"


def test_magazziniere_carrellista(client, qcfg, qdb, fake_jobs):
    p = mkprofile(client, name="Mag", preset="custom", titles=["magazziniere carrellista"], countries=["it"])
    jobs = [J("Magazziniere carrellista", "Milano", "it", n=1), J("Carrellista", "Torino", "it", n=2), J("Magazziniere", "Verona", "it", n=3),
            J("Addetto magazzino con patentino carrello elevatore", "Bari", "it", desc="carrellista", n=4), J("Cuoco", "Roma", "it", n=5),
            J("Autista patente C", "Roma", "it", n=6)]
    got = scan_titles(client, qcfg, qdb, fake_jobs, jobs, p["id"])
    assert {"Magazziniere carrellista", "Carrellista", "Magazziniere"} <= got
    assert not ({"Cuoco", "Autista patente C"} & got)


def test_seniority_junior_su_cybersecurity_non_premia_i_senior(client, qcfg, qdb, fake_jobs):
    p = by_name(client, "Cybersecurity")
    call(client, "post", f"/api/profiles/{p['id']}", {**p, "seniority": "junior"})
    from jobshunter.scanner import run_scan

    jr, sr = J("Junior SOC Analyst", "Roma", "it", desc="SIEM EDR", n=1), J("Senior SOC Analyst", "Roma", "it", desc="SIEM EDR", n=2)
    fake_jobs([jr, sr])
    run_scan(qcfg, qdb, profile_ids=[p["id"]])
    sc = dict(qdb.conn.execute("SELECT job_uid, score FROM job_profiles WHERE profile_id=?", (p["id"],)).fetchall())
    assert jr.uid in sc and (sr.uid not in sc or sc[jr.uid] > sc[sr.uid] + 10)


def test_seniority_any_su_profilo_non_cyber_non_penalizza_nessuno(client, qcfg, qdb, fake_jobs):
    p = mkprofile(client, name="Dev", preset="software_dev", seniority="any")
    a, b = J("Senior Python Developer", "Roma", "it", desc="Django", n=1), J("Python Developer", "Roma", "it", desc="Django", n=2)
    from jobshunter.scanner import run_scan

    fake_jobs([a, b])
    run_scan(qcfg, qdb, profile_ids=[p["id"]])
    sc = dict(qdb.conn.execute("SELECT job_uid, score FROM job_profiles WHERE profile_id=?", (p["id"],)).fetchall())
    assert sc[a.uid] == sc[b.uid], f"con livello 'qualsiasi' il titolo Senior non deve cambiare il punteggio: {sc}"


def test_citta_impostata_non_perde_i_remoti_e_i_nazionali(client, qcfg, qdb, fake_jobs):
    """Deviazione 2: con citta' impostata si cerca solo nel raggio. Gli annunci remoti/nazionali che arrivano da altre fonti restano valutati."""
    p = mkprofile(client, name="Bari", preset="custom", titles=["elettricista"], countries=["it"], location={"city": "Bari", "radius_km": 40})
    jobs = [J("Elettricista", "Bari", "it", n=1), J("Elettricista", "Italia", "it", n=2), J("Elettricista", "Remote", "it", remote=True, n=3),
            J("Elettricista", "Milano", "it", n=4)]
    got = scan_titles(client, qcfg, qdb, fake_jobs, jobs, p["id"])
    n = qdb.conn.execute("SELECT COUNT(*) FROM job_profiles WHERE profile_id=?", (p["id"],)).fetchone()[0]
    assert n >= 3, f"con citta' impostata solo {n} annunci su 4 (Bari, Italia, Remote, Milano): i nazionali e remoti non devono sparire"
