"""Duplicati: normalizzazione, blocking, semantica storica."""
import pytest

from jobshunter import dedupe


def row(title, company="Acme", location="Milano", **kw):
    return {"uid": kw.get("uid", f"{title}|{company}|{location}"), "title": title, "company": company, "location": location,
            "status": "new", "source": "adzuna", "salary": "", "score": 10, "full_text": ""}


@pytest.mark.parametrize("a,b", [
    (row("SOC Analyst"), row("SOC Analyst (m/f)", "Acme S.p.A.")),
    (row("Sr. SOC Analyst"), row("Senior SOC Analyst")),
    (row("Front-End Developer"), row("FRONT END DEVELOPER")),
    (row("Frontend Developer"), row("Front End Developer")),
    (row("Cuoco/a"), row("Cuoco")),
    (row("Infirmier H/F", "Ramsay"), row("Infirmier", "Ramsay")),
    (row("S.O.C. Analyst"), row("SOC Analyst")),
    (row("Security Engineer"), row("Security Engineer - Detection and Response")),
    (row("Dev", "Acme", "Milan"), row("Dev", "Acme", "Milano, Lombardia")),
    (row("Dev", "Societe Generale"), row("Dev", "Société Générale")),
    (row("Dev", "Banca Intesa Sanpaolo"), row("Dev", "Intesa Sanpaolo S.p.A.")),
    (row("Dev", "Acme", "Milano"), row("Dev", "Acme", "Italia")),
])
def test_sono_duplicati(a, b):
    pct = dedupe.similarity(a, b)
    assert pct is not None and pct >= 75


@pytest.mark.parametrize("a,b", [
    (row("Backend Developer"), row("Frontend Developer")),
    (row("Java Developer"), row("JavaScript Developer")),
    (row("Developer C#"), row("Developer C++")),
    (row("Network Security Engineer"), row("Network Engineer")),
    (row("Junior SOC Analyst"), row("Senior SOC Analyst")),
    (row("SOC Analyst L1"), row("SOC Analyst L2")),
    (row("Dev", "Deutsche Bank"), row("Dev", "Deutsche Bahn")),
    (row("Dev", location="Milano"), row("Dev", location="Roma")),
    (row("Staff Nurse"), row("Nurse Manager")),
])
def test_non_sono_duplicati(a, b):
    pct = dedupe.similarity(a, b)
    assert pct is None or pct < 75


def test_semantica_storica_invariata():
    assert dedupe.similarity(row("SOC Analyst"), row("SOC Analyst")) == 100
    assert dedupe.similarity(row("SOC Analyst", location="Milano"), row("SOC Analyst", location="Italia")) == 90  # sede generica -10
    assert dedupe.similarity(row("SOC Analyst", location="Milano"), row("SOC Analyst", location="Roma")) is None


def test_blocking_non_perde_le_coppie_vere_e_non_confronta_tutto():
    rows = [row(f"Ruolo {i} speciale", f"Azienda{i % 400}", f"Citta{i % 7}", uid=f"u{i}") for i in range(2000)]
    rows.append(row("Ruolo 5 speciale (m/f)", "Azienda5 S.p.A.", "Citta5", uid="dup"))
    pairs = {frozenset((a["uid"], b["uid"])) for a, b in dedupe.candidate_pairs(rows)}
    assert frozenset(("u5", "dup")) in pairs
    assert len(pairs) < 50_000  # non i 2 milioni di tutte le coppie


def test_find_duplicates_salva_e_non_tocca_le_decisioni(cfg, db):
    for u, comp in (("a" * 16, "Acme"), ("b" * 16, "Acme S.p.A.")):
        db.conn.execute("INSERT INTO jobs (uid,source,title,company,location,url,score,status,first_seen) VALUES (?,?,?,?,?,?,?,?,?)",
                        (u, "adzuna", "SOC Analyst", comp, "Roma", "u" + u, 30, "new", "2026-01-01"))
    db.conn.commit()
    assert dedupe.find_duplicates(db, cfg) == 1
    pid = db.conn.execute("SELECT id FROM dup_pairs").fetchone()["id"]
    db.set_dup_status(pid, "rejected")
    assert dedupe.find_duplicates(db, cfg) == 0
    assert db.conn.execute("SELECT status FROM dup_pairs").fetchone()["status"] == "rejected"


@pytest.mark.parametrize("a,b", [
    (row("Project Mgr"), row("Project Manager")),
    (row("Frontend Dev"), row("Frontend Developer")),
    (row("Vendedor"), row("Vendedro")),
    (row("Backend Developer"), row("Backend Developper")),
    (row("Infermiere", location="Roma"), row("Infermiere Roma", location="Roma")),
])
def test_abbreviazioni_e_refusi(a, b):
    assert (dedupe.similarity(a, b) or 0) >= 75


@pytest.mark.parametrize("a,b", [
    (row("Infermiere"), row("Infermiere pediatrico")),
    (row("Warehouse Picker"), row("Warehouse Packer")),
    (row("Cozinheiro", "Restaurante O Pescador"), row("Cozinheiro", "Restaurante O Pescador Novo")),
])
def test_parola_in_piu_o_diversa_cambia_il_ruolo(a, b):
    assert (dedupe.similarity(a, b) or 0) < 75


@pytest.mark.parametrize("la,lb", [("Frankfurt", "Frankfurt (Oder)"), ("Birmingham", "Birmingham, Alabama"),
                                   ("Cambridge", "Cambridge, MA"), ("Halle (Saale)", "Halle (Westfalen)"),
                                   ("Newcastle", "Newcastle-under-Lyme")])
def test_citta_con_stesso_inizio_sono_diverse(la, lb):
    assert dedupe.similarity(row("Dev", location=la), row("Dev", location=lb)) is None


@pytest.mark.parametrize("la,lb", [("San Francisco", "San Francisco, CA"), ("Milano", "Milano, Lombardia"),
                                   ("Frankfurt", "Frankfurt am Main"), ("Praha", "Praha 4")])
def test_citta_stessa_con_qualifica_benigna(la, lb):
    assert (dedupe.similarity(row("Dev", location=la), row("Dev", location=lb)) or 0) >= 75


@pytest.mark.parametrize("ca,cb", [("Skoda Auto a.s.", "Skoda Auto"), ("Orsted ApS", "Orsted"), ("Hyundai s.r.o.", "Hyundai"),
                                   ("Maersk A/S", "Maersk"), ("Lidl Stiftung & Co. KG", "Lidl"), ("NTT DATA Europe & Latam", "NTT Data Italia")])
def test_forme_societarie_e_varianti(ca, cb):
    assert (dedupe.similarity(row("Dev", ca), row("Dev", cb)) or 0) >= 75


@pytest.mark.parametrize("ca,cb", [("Siemens", "Siemens Energy"), ("Deutsche Bank", "Deutsche Bahn"), ("Volvo Cars", "Volvo Group")])
def test_aziende_diverse_con_nome_simile(ca, cb):
    assert (dedupe.similarity(row("Dev", ca), row("Dev", cb)) or 0) < 75


@pytest.mark.parametrize("a,b", [("Driver", "Diver"), ("Cleaner", "Cleaver")])
def test_refuso_su_parola_corta_non_unisce_mestieri(a, b):
    assert (dedupe.similarity(row(a), row(b)) or 0) < 75
