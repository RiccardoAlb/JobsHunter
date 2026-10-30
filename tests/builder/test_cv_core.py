"""Competenze, estrazione del testo, profilo del CV e punteggio di affinita' (nessuna rete, dati sintetici)."""
import io
import json
import os
import socket
import stat
import zipfile
from pathlib import Path

import sys

import pytest

from conftest import t as tlimit
from cvguard import _cv_guardia  # noqa: F401  (autouse: home temporanea, niente rete)
from jobshunter import cv, cvfile, cvmatch, skills
from jobshunter.db import DB

DATA = Path(__file__).parent.parent / "data" / "cv"


def load_sample(name):
    p = DATA / name
    return cvfile.extract(p.read_bytes(), name)


def profile_of(name):
    text, kind = load_sample(name)
    return cv.build_profile({"text": text, "words": cvfile.count_words(text)})


# ---------------------------------------------------------------- vocabolario ----
@pytest.mark.parametrize("text,expected", [
    ("Esperienza con SIEM e Splunk", {"SIEM", "Splunk"}),
    ("penetration testing e pentester", {"Penetration Testing"}),
    ("Active Directory su Windows Server 2022", {"Active Directory", "Windows Server"}),
    ("Docker, Kubernetes e CI/CD", {"Docker", "Kubernetes", "CI/CD"}),
    ("Conoscenza di Python3 e SQL", {"Python", "SQL"}),
    ("C++, C# e .NET", {"C++", "C#"}),
    ("Node.js e React", {"JavaScript", "React"}),
    ("Linguaggi: Python, C, Bash", {"Python", "C", "Bash"}),
    ("Python, R, SQL", {"Python", "R", "SQL"}),
    ("Python, Go, Rust", {"Python", "Go", "Rust"}),
    ("Sono un Infermiere con BLSD", {"Assistenza infermieristica", "BLS/BLSD"}),
])
def test_riconosce(text, expected):
    got = set(skills.find_skills(text))
    assert expected <= got, got


@pytest.mark.parametrize("text,absent", [
    ("social network e social media", "SOC"),
    ("Vitamina C e proteine", "C"),
    ("Piano C per il futuro", "C"),
    ("Let's go to the market", "Go"),
    ("Il gruppo R. Bianchi", "R"),
    ("Consegna ai clienti entro lunedi", "AI"),
    ("solo javascript qui", "Java"),
    ("ticket restaurant e buoni pasto", "Ticketing"),
    ("Via San Marino 3, Roma", "Storage"),
    ("ids e ips in minuscolo", "IDS/IPS"),
])
def test_prudenza_falsi_positivi(text, absent):
    assert absent not in skills.find_skills(text)


def test_sigle_maiuscole():
    assert "IDS/IPS" in skills.find_skills("Esperienza con IDS e IPS")
    assert "AI" in skills.find_skills("Progetti di AI generativa")


def test_plurali_e_maiuscole():
    assert "Firewall" in skills.find_skills("FIREWALLS Fortinet")
    assert "Database" in skills.find_skills("Gestione dei database")
    assert "Assistenza infermieristica" in skills.find_skills("infermieri e infermiere")


def test_accenti():
    assert "Contabilità" in skills.find_skills("Contabilità generale e bilancio")
    assert "Contabilità" in skills.find_skills("contabilita generale")


def test_parola_intera_non_dentro_altra():
    assert "SOC" not in skills.find_skills("socializzazione, sociale")
    assert "Git" not in skills.find_skills("digital")


def test_vocabolario_ampio():
    assert len(skills.all_skill_names()) >= 250
    cats = {skills.category_of(n) for n in skills.all_skill_names()}
    assert {"cyber", "sistemi", "sviluppo", "dati", "cloud", "rete", "soft", "lingue", "generali"} <= cats


def test_extra_json(home):
    (home / "skills_extra.json").write_text(json.dumps({"Mia Tecnologia": ["miatec"], "Altra": {"cat": "cloud", "aliases": ["altra cosa"]}}), encoding="utf-8")
    assert "Mia Tecnologia" in skills.find_skills("uso miatec ogni giorno")
    assert "Altra" in skills.find_skills("lavoro con altra cosa")
    assert skills.category_of("Altra") == "cloud"
    sig = skills.vocab_signature()
    (home / "skills_extra.json").write_text(json.dumps({"Nuova": ["nuovissima"]}), encoding="utf-8")
    assert skills.vocab_signature() != sig
    assert "Nuova" in skills.find_skills("nuovissima")


def test_extra_json_rotto_ignorato(home):
    (home / "skills_extra.json").write_text("{non json", encoding="utf-8")
    assert "Python" in skills.find_skills("python")
    (home / "skills_extra.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert "Python" in skills.find_skills("python")


def test_velocita_su_grandi_volumi():
    import time

    from conftest import t as tlimit

    text = ("Cerchiamo analista SOC con SIEM Splunk Python e Linux, inglese richiesto. " * 70)[:5000]
    t = time.time()
    for _ in range(2000):
        skills.find_skills(text)
    assert time.time() - t < tlimit(8)


# ------------------------------------------------------------------ estrazione ----
def test_estrae_tutti_i_formati():
    for name, kind in (("cyber_junior.txt", "txt"), ("sistemista.docx", "docx"), ("sviluppatore.pdf", "pdf"), ("infermiere.md", "md")):
        text, k = load_sample(name)
        assert k == kind and cvfile.count_words(text) > 30


def test_scansione_senza_testo():
    with pytest.raises(cvfile.CvError) as e:
        load_sample("scansione_senza_testo.pdf")
    assert "scansione" in str(e.value)


def test_estensione_non_ammessa():
    with pytest.raises(cvfile.CvError):
        cvfile.extract(b"ciao " * 50, "cv.exe")
    with pytest.raises(cvfile.CvError):
        cvfile.extract(b"ciao " * 50, "cv")


def test_pdf_finto():
    with pytest.raises(cvfile.CvError) as e:
        cvfile.extract(b"questo non e un pdf " * 20, "cv.pdf")
    assert "PDF" in str(e.value)


def test_docx_finto():
    with pytest.raises(cvfile.CvError):
        cvfile.extract(b"testo " * 50, "cv.docx")


def test_txt_che_e_un_archivio():
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("a.txt", "ciao")
    with pytest.raises(cvfile.CvError):
        cvfile.extract(z.getvalue(), "cv.txt")


def test_txt_che_e_un_pdf():
    with pytest.raises(cvfile.CvError):
        cvfile.extract((DATA / "sviluppatore.pdf").read_bytes(), "cv.txt")


def test_troppo_grande():
    with pytest.raises(cvfile.CvError) as e:
        cvfile.extract(b"a" * (cvfile.MAX_BYTES + 1), "cv.txt")
    assert "5 MB" in str(e.value)


def test_file_vuoto_e_testo_corto():
    with pytest.raises(cvfile.CvError):
        cvfile.extract(b"", "cv.txt")
    with pytest.raises(cvfile.CvError):
        cvfile.extract(b"poche parole", "cv.txt")


def test_binario_nel_txt():
    with pytest.raises(cvfile.CvError):
        cvfile.extract(b"abc\x00def" * 100, "cv.txt")


def test_codifica_cp1252():
    raw = ("Esperienza lavorativa: gestione della contabilità e dei clienti " * 5).encode("cp1252")
    text, _ = cvfile.extract(raw, "cv.txt")
    assert "contabilità" in text


def test_zip_bomb_docx():
    big = b"<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body>" + b"<w:p><w:r><w:t>aaaa</w:t></w:r></w:p>" * 10 + b"</w:body></w:document>"
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.writestr("word/document.xml", big + b" " * (60 * 1024 * 1024))
    assert len(z.getvalue()) < cvfile.MAX_BYTES
    with pytest.raises(cvfile.CvError) as e:
        cvfile.extract(z.getvalue(), "cv.docx")
    assert "sicurezza" in str(e.value)


def test_docx_con_entita_rifiutato():
    doc = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "bbbbbbbbbb">]><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&a;</w:t></w:r></w:p></w:body></w:document>'
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("word/document.xml", doc)
    with pytest.raises(cvfile.CvError):
        cvfile.extract(z.getvalue(), "cv.docx")


def test_docx_senza_testo_principale_e_corrotto():
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("altro.xml", "<a/>")
    with pytest.raises(cvfile.CvError):
        cvfile.extract(z.getvalue(), "cv.docx")
    with pytest.raises(cvfile.CvError):
        cvfile.extract(b"PK\x03\x04" + b"rotto" * 100, "cv.docx")


def test_pdf_corrotto():
    with pytest.raises(cvfile.CvError) as e:
        cvfile.extract(b"%PDF-1.4\n" + os.urandom(2000), "cv.pdf")
    assert "danneggiato" in str(e.value)


def test_pdf_troppe_pagine():
    import importlib.util

    spec = importlib.util.spec_from_file_location("bld", Path(__file__).parent.parent / "data" / "build_cv_samples.py")
    bld = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bld)
    pages = [["Competenze Python SQL Linux " * 3]] * (cvfile.MAX_PAGES + 1)
    with pytest.raises(cvfile.CvError) as e:
        cvfile.extract(bld.pdf_bytes(pages), "cv.pdf")
    assert "pagine" in str(e.value)


def test_pdf_cifrato():
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter()
    for p in PdfReader(str(DATA / "sviluppatore.pdf")).pages:
        w.add_page(p)
    w.encrypt("segreta")
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(cvfile.CvError) as e:
        cvfile.extract(buf.getvalue(), "cv.pdf")
    assert "password" in str(e.value)


def test_errori_senza_contenuto_del_cv():
    secret = "ZXQ-segreto-12345 " * 30
    for raw, name in ((secret.encode(), "cv.pdf"), (secret.encode(), "cv.docx"), (b"%PDF-1.4 " + secret.encode(), "cv.pdf"), (b"PK\x03\x04" + secret.encode(), "cv.docx")):
        with pytest.raises(cvfile.CvError) as e:
            cvfile.extract(raw, name)
        assert "ZXQ" not in str(e.value)


def test_nome_file_non_e_un_percorso(home):
    text, _ = cvfile.extract(("Python SQL Linux Docker Git " * 10).encode(), "../../etc/passwd.txt")
    assert "Python" in text
    assert not (home.parent / "etc").exists()


# ---------------------------------------------------------------- archiviazione ----
def test_salva_e_nessun_temporaneo(home):
    cv.save_text("Python SQL Linux " * 20, "txt")
    p = cv.path()
    assert p.parent == home and p.name == "cv.json"
    assert not list(home.glob(".cv-*.tmp"))
    assert cv.load()["words"] == 60


@pytest.mark.skipif(sys.platform.startswith("win"), reason="permessi POSIX (chmod/st_mode/umask): su Windows la protezione e' icacls (provata in test_portability)")
def test_cv_json_ha_permessi_600(home):
    cv.save_text("Python SQL Linux " * 20, "txt")
    assert stat.S_IMODE(cv.path().stat().st_mode) == 0o600


def test_elimina_davvero(home):
    cv.save_text("Python SQL Linux " * 20, "txt")
    assert cv.delete() is True
    assert not cv.path().exists() and cv.current() is None
    assert cv.delete() is False


def test_sostituisci_azzera_modifiche_a_mano(home):
    cv.save_text("Python SQL Linux Splunk SIEM " * 10, "txt")
    cv.change_skills(add=["Docker"], remove=["Python"])
    assert cv.load()["skills_manual"] == ["Docker"]
    cv.save_text("Java Spring Kubernetes " * 10, "txt")
    d = cv.load()
    assert d["skills_manual"] == [] and d["skills_removed"] == []


def test_competenze_a_mano(home):
    cv.save_text("Esperienza con Python e Linux per molti progetti diversi nel tempo " * 3, "txt")
    p = cv.current()
    assert "Python" in p.skills and "Docker" not in p.skills
    cv.change_skills(add=["docker"])
    assert "Docker" in cv.current().skills
    cv.change_skills(remove=["Python"])
    assert "Python" not in cv.current().skills
    assert "Python" in cv.summary(cv.current())["skills_removed"]
    cv.change_skills(restore=["Python"])
    assert "Python" in cv.current().skills
    cv.change_skills(remove=["Docker"])
    assert "Docker" not in cv.current().skills and cv.load()["skills_manual"] == []


def test_competenza_sconosciuta_e_nomi_strani(home):
    cv.save_text("Python " * 40, "txt")
    for bad in ("parolainesistentexyz", "", "x" * 100, 5, None):
        with pytest.raises(cvfile.CvError):
            cv.change_skills(add=[bad])
    with pytest.raises(cvfile.CvError):
        cv.change_skills(add=["Inglese"])


def test_senza_cv_non_si_modificano_competenze(home):
    with pytest.raises(cvfile.CvError):
        cv.change_skills(add=["Python"])


def test_cv_json_illeggibile(home):
    cv.path().write_text("{rotto", encoding="utf-8")
    assert cv.current() is None
    cv.path().write_text(json.dumps({"text": ""}), encoding="utf-8")
    assert cv.current() is None


def test_versione_non_contiene_il_testo_e_cambia_con_le_competenze(home):
    cv.save_text("Python SQL Linux Docker " * 15, "txt")
    v1 = cv.current().version
    assert len(v1) == 16
    cv.change_skills(remove=["Docker"])
    v2 = cv.current().version
    assert v2 != v1
    cv.change_skills(restore=["Docker"])
    assert cv.current().version == v1
    cv.save_text("Python SQL Linux Docker e tante altre parole inutili senza competenze " * 15, "txt")
    assert cv.current().version == v1  # stesso profilo elaborato: niente ricalcolo


# --------------------------------------------------------------- anni e lingue ----
@pytest.fixture
def oggi(monkeypatch):
    monkeypatch.setattr(cv, "_today_year", lambda: 2026.0)


def test_anni_dai_campioni(oggi):
    assert profile_of("cyber_junior.txt").years == 0.5      # lo studio 2020-2023 non conta
    assert profile_of("sviluppatore.pdf").years == 5.0
    assert profile_of("infermiere.md").years == 5.0
    assert profile_of("sistemista.docx").years == 14.0      # 2012-2016 + 2016-oggi (unione)
    assert profile_of("english_data_analyst.txt").years == 6.5


def test_anni_espliciti():
    assert cv.estimate_years("Sono un tecnico con 8 anni di esperienza nel settore") == 8.0
    assert cv.estimate_years("Over 10 years of experience in IT") == 10.0
    assert cv.estimate_years("niente date qui") is None


def test_intervalli_sovrapposti_non_si_sommano(oggi):
    t = "Esperienza\n2018 - 2022 Azienda A\n2019 - 2021 Azienda B (in parallelo)\n"
    assert cv.estimate_years(t) == 4.0


def test_formati_di_data(oggi):
    assert cv.estimate_years("Esperienza\n03/2020 - 03/2022 Ruolo\n") == 2.0
    assert cv.estimate_years("Experience\nMar 2020 - Mar 2022 Role\n") == 2.0
    assert cv.estimate_years("Esperienza\n2024 - presente Ruolo\n") == 2.0


def test_date_assurde_ignorate(oggi):
    assert cv.estimate_years("Esperienza\n2030 - 2040 futuro\n") is None or cv.estimate_years("Esperienza\n2030 - 2040 futuro\n") == 0.0


def test_lingue():
    langs = {d["lang"]: d["level"] for d in profile_of("sistemista.docx").languages}
    assert langs == {"Inglese": "B1", "Tedesco": "base"}
    langs = {d["lang"]: d["level"] for d in profile_of("cyber_junior.txt").languages}
    assert langs["Inglese"] == "B2" and langs["Italiano"] == "madrelingua"
    langs = {d["lang"]: d["level"] for d in profile_of("english_data_analyst.txt").languages}
    assert langs["Inglese"] == "madrelingua" and langs["Italiano"] == "B2"
    assert {d["lang"]: d["level"] for d in profile_of("sviluppatore.pdf").languages} == {"Inglese": "C1", "Spagnolo": "B1"}


def test_italiano_senza_livello_non_conta():
    assert cv.detect_languages("Lavoro in un'azienda italiana, guido auto italiano per la ditta") == []


def test_competenze_dei_campioni():
    assert {"SIEM", "Splunk", "Wazuh", "Nmap", "Python"} <= profile_of("cyber_junior.txt").skills
    assert {"Active Directory", "VMware", "PowerShell", "Windows Server"} <= profile_of("sistemista.docx").skills
    assert {"Python", "Docker", "React", "PostgreSQL"} <= profile_of("sviluppatore.pdf").skills
    assert {"BLS/BLSD", "Triage", "Prelievi"} <= profile_of("infermiere.md").skills
    assert {"SQL", "Power BI", "Tableau"} <= profile_of("english_data_analyst.txt").skills
    assert "Inglese" not in profile_of("sistemista.docx").skills  # le lingue non sono competenze


# -------------------------------------------------------------------- punteggio ----
LONG = " Offriamo un ambiente dinamico e un percorso di crescita nel team, con formazione continua e sede a Milano." * 3


def job_text(skills_part):
    return skills_part + "." + LONG


def score(name, title, text, **kw):
    return cvmatch.match(profile_of(name), title, text, **kw)


def test_cyber_su_annuncio_soc_alto():
    r = score("cyber_junior.txt", "SOC Analyst Junior", job_text("Triage alert su SIEM Splunk, incident response, analisi log, Wireshark, Python e Linux. Inglese richiesto"))
    assert r["score"] >= 70 and r["base"] == "completo"
    assert {"SIEM", "Splunk"} <= set(r["explain"]["in_comune"])
    assert r["explain"]["lingue"]["in_comune"] == ["Inglese"]


def test_infermiere_su_annuncio_soc_bassissimo():
    r = score("infermiere.md", "SOC Analyst", job_text("SIEM Splunk incident response threat hunting EDR"))
    assert r["score"] <= 10
    assert "SIEM" in r["explain"]["mancanti"]


def test_sviluppatore_su_annuncio_soc_basso_su_backend_alto():
    soc = score("sviluppatore.pdf", "SOC Analyst", job_text("SIEM Splunk incident response EDR threat hunting"))["score"]
    dev = score("sviluppatore.pdf", "Sviluppatore Backend Python", job_text("Python Django PostgreSQL Docker REST API Git CI/CD. Esperienza di 3 anni"))["score"]
    assert soc < 15 and dev > 70


def test_titolo_pesa_piu_del_corpo():
    p = profile_of("cyber_junior.txt")
    a = cvmatch.match(p, "Analista Splunk", job_text("Kubernetes Terraform AWS Azure"))["score"]
    b = cvmatch.match(p, "Cloud Engineer", job_text("Splunk e Kubernetes Terraform AWS Azure"))["score"]
    assert a > b


def test_competenze_ripetute_pesano_di_piu():
    p = profile_of("cyber_junior.txt")
    a = cvmatch.match(p, "Tecnico", job_text("Splunk Splunk Splunk Splunk Kubernetes"))["score"]
    b = cvmatch.match(p, "Tecnico", job_text("Splunk Kubernetes Kubernetes Kubernetes Kubernetes"))["score"]
    assert a > b


def test_penalita_per_mancanti_chiave():
    p = profile_of("cyber_junior.txt")
    with_missing = cvmatch.match(p, "SOC Analyst", job_text("SIEM Splunk Wazuh Kubernetes Terraform AWS"))
    without = cvmatch.match(p, "SOC Analyst", job_text("SIEM Splunk Wazuh"))
    assert without["score"] > with_missing["score"]
    assert set(with_missing["explain"]["mancanti"]) >= {"Kubernetes", "Terraform", "AWS"}


def test_livello_senior_con_cv_junior(oggi):
    p = profile_of("cyber_junior.txt")
    jr = cvmatch.match(p, "SOC Analyst Junior", job_text("SIEM Splunk Wazuh Wireshark"))
    sr = cvmatch.match(p, "Senior SOC Analyst", job_text("SIEM Splunk Wazuh Wireshark. Almeno 5 anni di esperienza"))
    assert jr["score"] > sr["score"]
    assert sr["explain"]["livello"]["esito"] == "sotto" and jr["explain"]["livello"]["esito"] in ("in_linea", "sopra")
    assert sr["explain"]["livello"]["anni_richiesti"] == 5


def test_cv_esperto_su_stage(oggi):
    p = profile_of("sistemista.docx")
    r = cvmatch.match(p, "Stage Sistemista", job_text("Windows Server Active Directory Linux VMware"))
    assert r["explain"]["livello"]["richiesto"] == "stage"
    assert r["explain"]["livello"]["esito"] == "sopra"
    assert any("esperienza" in n for n in r["explain"]["note"])


def test_lingua_richiesta_mancante():
    p2 = profile_of("infermiere.md")
    a = cvmatch.match(p2, "Infermiere", job_text("Assistenza infermieristica, triage, BLSD, prelievi, somministrazione terapie. Richiesta ottima conoscenza del francese"))
    b = cvmatch.match(p2, "Infermiere", job_text("Assistenza infermieristica, triage, BLSD, prelievi, somministrazione terapie"))
    assert a["explain"]["lingue"]["mancanti"] == ["Francese"] and a["score"] < b["score"]
    c = cvmatch.match(p2, "Infermiere", job_text("Assistenza infermieristica, triage, BLSD, prelievi, terapie. Inglese richiesto"))
    assert c["explain"]["lingue"]["in_comune"] == ["Inglese"]
    d = cvmatch.match(p2, "Infermiere", job_text("Assistenza infermieristica, triage, BLSD, prelievi, terapie. Francese gradito"))
    assert d["explain"]["lingue"]["mancanti"] == [] and d["explain"]["lingue"]["gradite"] == ["Francese"]


def test_anteprima_prudente():
    p = profile_of("cyber_junior.txt")
    full = cvmatch.match(p, "SOC Analyst", job_text("SIEM Splunk Wazuh Wireshark Nmap Python"))
    short = cvmatch.match(p, "SOC Analyst", "SIEM Splunk Wazuh Wireshark Nmap Python")
    jooble = cvmatch.match(p, "SOC Analyst", job_text("SIEM Splunk Wazuh Wireshark Nmap Python"), source="jooble:it")
    assert full["base"] == "completo" and short["base"] == "anteprima" and jooble["base"] == "anteprima"
    assert short["score"] <= 60 and jooble["score"] <= 60 and full["score"] > short["score"]
    assert short["explain"]["note"][0].startswith("Basato su anteprima")
    assert short["explain"]["confidenza"] in ("media", "bassa")


def test_adzuna_snippet_senza_testo_completo_e_anteprima():
    p = profile_of("cyber_junior.txt")
    t = job_text("SIEM Splunk Wazuh")
    assert cvmatch.match(p, "SOC", t, source="adzuna", full_text="")["base"] == "anteprima"
    assert cvmatch.match(p, "SOC", t, source="adzuna", full_text=t)["base"] == "completo"


def test_mai_alto_con_pochi_dati():
    p = profile_of("cyber_junior.txt")
    one = cvmatch.match(p, "Tecnico", job_text("Splunk"))
    two = cvmatch.match(p, "Tecnico", job_text("Splunk e SIEM"))
    assert one["score"] <= 52 and two["score"] <= 64


def test_annuncio_senza_competenze_riconoscibili():
    r = cvmatch.match(profile_of("cyber_junior.txt"), "Addetto", "Si cerca persona seria e volenterosa per lavoro presso la nostra sede. " * 8)
    assert r["score"] == 0 and any("Non riconosco" in n for n in r["explain"]["note"])


def test_cv_senza_competenze(home):
    cv.save_text("Mi chiamo nessuno e ho fatto cose varie nella vita per tanti anni senza dettagli " * 3, "txt")
    p = cv.current()
    r = cvmatch.match(p, "SOC Analyst", job_text("SIEM Splunk"))
    assert r["score"] == 0 and any("aggiungile a mano" in n for n in r["explain"]["note"])


def test_punteggio_deterministico_e_nel_range():
    p = profile_of("sviluppatore.pdf")
    t = job_text("Python Django Docker AWS Terraform Kubernetes")
    outs = {json.dumps(cvmatch.match(p, "Dev", t), sort_keys=True) for _ in range(5)}
    assert len(outs) == 1
    assert 0 <= cvmatch.match(p, "Dev", t)["score"] <= 100


def test_spiegazione_senza_testo_del_cv():
    p = profile_of("cyber_junior.txt")
    raw = json.dumps(cvmatch.match(p, "SOC", job_text("SIEM Splunk")))
    text, _ = load_sample("cyber_junior.txt")
    for frase in ("Acme Security Srl", "Marco Esempio", "Universita'"):
        assert frase not in raw


def test_livelli_rilevati():
    assert cvmatch.detect_level("Senior Python Developer", "")[0] == "senior"
    assert cvmatch.detect_level("Junior Analyst", "")[0] == "junior"
    assert cvmatch.detect_level("Stage in cybersecurity", "")[0] == "stage"
    assert cvmatch.detect_level("Team Leader IT", "")[0] == "lead"
    assert cvmatch.detect_level("Sviluppatore", "Richiesti 3-4 anni di esperienza")[1] == 3
    assert cvmatch.detect_level("Sviluppatore", "esperienza di almeno 6 anni")[0] == "senior"
    assert cvmatch.detect_level("Tecnico", "nessuna indicazione") == (None, None)


# ------------------------------------------------------------- database e riuso ----
def make_db(home, n=0):
    db = DB(home / "t.db")
    return db


def add_job(db, uid, title, desc, source="adzuna", full=""):
    db.conn.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, full_text, score, category, matched, first_seen) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (uid, source, title, "Acme", "Roma", "https://example.org/" + uid, desc, full, 50, "BLUE", "", "2026-01-01T00:00:00+00:00"))
    db.conn.commit()


def test_ricalcolo_solo_se_serve(home):
    db = make_db(home)
    cv.save_text("Python SQL Linux Docker Git SIEM Splunk " * 10, "txt")
    p = cv.current()
    for i in range(5):
        add_job(db, f"j{i}", "SOC Analyst", job_text("SIEM Splunk Python"), full=job_text("SIEM Splunk Python"))
    assert cvmatch.stale_count(db, p.version) == 5
    assert cvmatch.recompute(db, p) == 5
    assert cvmatch.stale_count(db, p.version) == 0
    assert cvmatch.recompute(db, p) == 0               # niente da rifare
    add_job(db, "nuovo", "Dev", job_text("Python Docker"), full=job_text("Python Docker"))
    assert cvmatch.recompute(db, p) == 1               # solo il nuovo
    db.set_full_text("j0", job_text("SIEM Splunk Python Kubernetes Terraform AWS Azure"))
    assert cvmatch.stale_count(db, p.version) == 1     # testo cambiato
    assert cvmatch.recompute(db, p) == 1
    cv.change_skills(remove=["Splunk"])
    assert cvmatch.recompute(db, cv.current()) == 6    # CV diverso: si rifanno tutti


def test_for_job_e_scores_for(home):
    db = make_db(home)
    cv.save_text("Python SQL Linux Docker Git SIEM Splunk " * 10, "txt")
    p = cv.current()
    add_job(db, "a", "Analista", job_text("SIEM Splunk"), full=job_text("SIEM Splunk"))
    m = cvmatch.for_job(db, p, "a")
    assert m["score"] > 50 and cvmatch.for_job(db, p, "inesistente") is None
    assert cvmatch.scores_for(db, ["a"], p.version)["a"][0] == m["score"]
    assert cvmatch.scores_for(db, ["a"], "altraversione") == {}


def test_query_cv_min_e_ordine(home):
    db = make_db(home)
    cv.save_text("Python SQL Linux Docker Git SIEM Splunk " * 10, "txt")
    p = cv.current()
    add_job(db, "alto", "Analista", job_text("SIEM Splunk Python"), full=job_text("SIEM Splunk Python"))
    add_job(db, "basso", "Infermiere", job_text("triage BLSD prelievi"), full=job_text("triage BLSD prelievi"))
    cvmatch.recompute(db, p)
    db.conn.execute("UPDATE jobs SET score=90 WHERE uid='basso'")
    db.conn.commit()
    assert [r["uid"] for r in db.query()] == ["basso", "alto"]
    assert [r["uid"] for r in db.query(cv_version=p.version, order_cv=True)] == ["alto", "basso"]
    assert [r["uid"] for r in db.query(cv_min=50, cv_version=p.version)] == ["alto"]


def test_clear(home):
    db = make_db(home)
    cv.save_text("Python SQL Linux Docker Git " * 10, "txt")
    add_job(db, "a", "SOC", job_text("SIEM"), full=job_text("SIEM"))
    cvmatch.recompute(db, cv.current())
    cvmatch.clear(db)
    assert db.conn.execute("SELECT COUNT(*) FROM cv_match").fetchone()[0] == 0


def test_migrazione_db_esistente(home):
    import sqlite3

    path = home / "vecchio.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE jobs (uid TEXT PRIMARY KEY, source TEXT, title TEXT, company TEXT, location TEXT, url TEXT, description TEXT, posted_at TEXT, remote INTEGER, score INTEGER, category TEXT, matched TEXT, status TEXT DEFAULT 'new', notified INTEGER DEFAULT 0, first_seen TEXT)")
    c.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, score) VALUES ('x','fake','SOC','A','Roma','u','SIEM',50)")
    c.commit()
    c.close()
    db = DB(path)
    assert db.conn.execute("SELECT COUNT(*) FROM cv_match").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_prestazioni_5000_annunci(home):
    import time

    db = make_db(home)
    cv.save_text("Python SQL Linux Docker Git SIEM Splunk Wazuh " * 10, "txt")
    p = cv.current()
    body = job_text("Cerchiamo analista con SIEM Splunk Python Linux Docker AWS Kubernetes. Inglese richiesto. 3 anni di esperienza") * 4
    rows = [(f"u{i}", "adzuna", f"Analista {i}", "Acme", "Roma", "u", body[:5000], body, 50, "BLUE", "", "2026-01-01T00:00:00+00:00") for i in range(5000)]
    db.conn.executemany("INSERT INTO jobs (uid, source, title, company, location, url, description, full_text, score, category, matched, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.conn.commit()
    t = time.time()
    seen = []
    cvmatch.recompute(db, p, progress=lambda a, b: seen.append((a, b)))
    assert time.time() - t < tlimit(15)
    assert seen[-1] == (5000, 5000)
    assert cvmatch.stale_count(db, p.version) == 0


def test_annullamento_ricalcolo(home):
    import threading

    db = make_db(home)
    cv.save_text("Python SQL Linux Docker Git " * 10, "txt")
    for i in range(30):
        add_job(db, f"j{i}", "Dev", job_text("Python"), full=job_text("Python"))
    ev = threading.Event()
    ev.set()
    assert cvmatch.recompute(db, cv.current(), cancel=ev) == 0


# ----------------------------------------------------------------------- rete ----
def test_nessuna_connessione_di_rete(home, monkeypatch):
    """Blocca ogni socket: estrazione, profilo e confronto devono funzionare comunque."""
    def boom(*a, **k):
        raise AssertionError("rete vietata")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    text, _ = load_sample("sistemista.docx")
    text2, _ = load_sample("sviluppatore.pdf")
    cv.save_text(text, "docx")
    p = cv.current()
    assert cvmatch.match(p, "Sistemista", job_text("Windows Server Active Directory"))["score"] > 50
    db = make_db(home)
    add_job(db, "a", "Sistemista", job_text("Linux"), full=job_text("Linux"))
    cvmatch.recompute(db, p)
    assert text2


def test_il_codice_del_cv_non_importa_librerie_di_rete():
    import re

    for mod in ("cv.py", "cvfile.py", "cvmatch.py", "skills.py"):
        src = (Path(cv.__file__).parent / mod).read_text(encoding="utf-8")
        assert not re.search(r"^\s*(?:import|from)\s+(?:httpx|requests|urllib|socket|http\.client|aiohttp)\b", src, re.M), mod
