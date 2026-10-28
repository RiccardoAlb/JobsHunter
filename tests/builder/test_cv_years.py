"""Stima degli anni di esperienza su CV a due colonne e abbreviazioni dei mesi (CV sintetico, nessun dato reale)."""
from pathlib import Path

import pytest

from cvguard import _cv_guardia  # noqa: F401  (autouse: home temporanea, niente rete)
from jobshunter import cv, cvfile, cvmatch

DATA = Path(__file__).parent.parent / "data" / "cv"
LONG = " Offriamo un ambiente dinamico e un percorso di crescita nel team, con formazione continua e sede a Milano." * 3


@pytest.fixture(autouse=True)
def oggi(monkeypatch):
    monkeypatch.setattr(cv, "_today_year", lambda: 2026.8)


def test_due_colonne_conta_solo_il_lavoro():
    text, _ = cvfile.extract((DATA / "due_colonne_junior.pdf").read_bytes(), "cv.pdf")
    # l'ordine e' mescolato: studi e corsi vengono prima del titolo "Esperienze professionali"
    assert text.index("ISTITUTO") < text.index("Esperienze professionali")
    years, certain = cv.estimate_years_ex(text)
    assert years == 3.0 and certain is True


def test_profilo_due_colonne_e_summary():
    text, _ = cvfile.extract((DATA / "due_colonne_junior.pdf").read_bytes(), "cv.pdf")
    p = cv.build_profile({"text": text, "words": 90})
    assert p.years == 3.0 and p.years_certain
    assert {"SIEM", "Splunk", "Linux", "Python"} <= p.skills
    assert cv.summary(p)["years"] == 3.0


@pytest.mark.parametrize("line,expected", [
    ("| FEB. 2023 - MARZ. 2026 |", 3.0),
    ("| SETT. 2020 - GIU. 2022 |", 2.0),
    ("| GEN. 2024 - OGGI |", 3.0),
    ("| NOV. 2024 - in corso |", 2.0),
    ("| Luglio 2023 - Dicembre 2024 |", 1.5),
])
def test_abbreviazioni_dei_mesi(line, expected):
    assert cv.estimate_years_ex(line) == (expected, True)


def test_studi_corsi_e_anni_singoli_non_contano():
    t = ("Esperienze professionali\n2014 - 2019 | ISTITUTO TECNICO INDUSTRIALE DI ESEMPIO |\n2019 - 2021 | UNIVERSITA' DI ESEMPIO |\n"
         "2026 | ACADEMY INSTITUTE OF TECHNOLOGY |\nAgosto 2026 | Certificazione di esempio |\nMaggio 2026 | Corso online |\n")
    assert cv.estimate_years_ex(t) == (None, True)


def test_datore_con_nome_da_scuola_ma_con_presso_conta():
    t = "Esperienza\n2016 - presente Infermiere presso Istituto Clinico di Esempio"
    assert cv.estimate_years_ex(t) == (11.0, True)


def test_intervallo_senza_indizi_e_senza_sezione_e_incerto():
    years, certain = cv.estimate_years_ex("Qualcosa di vago\n2015 - 2019 | Mansioni varie\n")
    assert years is None and certain is False


def test_intervallo_senza_indizi_con_sezione_studio_non_e_incerto():
    assert cv.estimate_years_ex("Istruzione\n2015 - 2019 | Mansioni varie\n") == (None, True)


def test_incerto_sottostima_ma_non_penalizza():
    p_inc = cv.CvProfile(detected={"SIEM": 1, "Splunk": 1, "Python": 1, "Linux": 1}, years=0.5, years_certain=False)
    p_ok = cv.CvProfile(detected={"SIEM": 1, "Splunk": 1, "Python": 1, "Linux": 1}, years=0.5, years_certain=True)
    txt = "SIEM Splunk Python Linux incident response." + LONG
    senior = cvmatch.match(p_inc, "Senior SOC Analyst", txt + " Almeno 5 anni di esperienza")
    assert senior["explain"]["livello"]["esito"] == "sconosciuto" and senior["explain"]["livello"]["anni_cv"] is None
    assert any("nessuna penalita" in n for n in senior["explain"]["note"])
    # lo stesso CV con anni certi (0,5) verrebbe penalizzato: l'incerto no
    penal = cvmatch.match(p_ok, "Senior SOC Analyst", txt + " Almeno 5 anni di esperienza")
    assert penal["explain"]["livello"]["esito"] == "sotto" and senior["score"] > penal["score"]
    # su uno stage: niente "sovraqualificato" ne' "sotto" con anni incerti
    p_big = cv.CvProfile(detected={"SIEM": 1, "Splunk": 1, "Python": 1, "Linux": 1}, years=9.0, years_certain=False)
    stage = cvmatch.match(p_big, "Stage SOC Analyst", txt)
    assert stage["explain"]["livello"]["esito"] == "sconosciuto"


def test_con_anni_sicuri_il_junior_non_e_penalizzato_su_annuncio_junior():
    text, _ = cvfile.extract((DATA / "due_colonne_junior.pdf").read_bytes(), "cv.pdf")
    p = cv.build_profile({"text": text, "words": 90})
    r = cvmatch.match(p, "SOC Analyst Junior", "SIEM Splunk Wazuh Linux Python incident response." + LONG)
    assert r["explain"]["livello"]["esito"] in ("in_linea", "sopra") and r["score"] >= 60


def test_versione_cambia_se_cambia_la_certezza():
    a = cv.CvProfile(detected={"SIEM": 1}, years=1.0, years_certain=True)
    b = cv.CvProfile(detected={"SIEM": 1}, years=1.0, years_certain=False)
    assert a.version != b.version


def test_i_vecchi_casi_restano():
    assert cv.estimate_years("Esperienza\n2019-2021 Dev") == 2.0
    assert cv.estimate_years("Istruzione\n2010-2015 Laurea\nEsperienza\n2016-2018 Dev") == 2.0
    assert cv.estimate_years("Ho 10 anni di esperienza nel settore") == 10.0
