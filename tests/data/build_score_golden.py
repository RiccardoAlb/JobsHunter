"""Genera tests/data/score_golden.json con i punteggi del codice di FASE 1 (profile=None, cybersecurity da config.example.toml).

Usa la copia fedele del codice di fase 1 in tests/data/phase1_reference.py (indipendente da BUILDER). Il file generato e' il riferimento
per "score_job(profile=None) identico a oggi" e per "stessi punteggi dopo la migrazione".
"""
import json
import sys
import tempfile
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.environ["JOBSHUNTER_HOME"] = tempfile.mkdtemp()

from jobshunter import settings  # noqa: E402
from jobshunter.models import Job  # noqa: E402
sys.path.insert(0, str(ROOT / 'tests' / 'data'))
from phase1_reference import score_job  # noqa: E402  (copia fedele del codice di fase 1)

D = "Lavorerai su {}. Richiesta esperienza con {}."
J = [  # (titolo, azienda, sede, descrizione, remoto)
    ("SOC Analyst", "Acme Security", "Roma", D.format("triage SIEM", "Splunk EDR e incident response"), False),
    ("Junior SOC Analyst", "Acme Security", "Milano", D.format("eventi", "Wazuh e QRadar"), False),
    ("Senior SOC Analyst", "Acme Security", "Milano", D.format("eventi", "Wazuh e QRadar"), False),
    ("Penetration Tester", "Cyberia", "Palermo", D.format("test", "Metasploit Burp OSCP"), False),
    ("Pentester Junior", "Cyberia", "Catania", D.format("vulnerability assessment", "Kali linux"), False),
    ("Red Team Operator", "Offensive Srl", "Torino", D.format("red team", "exploit"), False),
    ("Blue Team Engineer", "DefendIT", "Roma", D.format("detection engineering", "threat hunting DFIR"), False),
    ("Sistemista Linux", "Exprivia", "Bari", D.format("server", "Linux VMware Proxmox backup"), False),
    ("Tecnico Sistemista", "Infra Spa", "Palermo", D.format("assistenza", "Active Directory Windows Server"), False),
    ("System Administrator", "Hosting Ltd", "Napoli", D.format("sistemi", "Linux networking"), False),
    ("IT Support Specialist", "Helpdesk Srl", "Roma", D.format("supporto", "help desk"), False),
    ("Cyber Security Specialist", "Leonardo", "Roma", D.format("sicurezza", "information security"), False),
    ("Security Engineer", "Okta", "Remote", D.format("platform security", "cloud"), True),
    ("Security Analyst", "Palantir", "Bagheria", D.format("analisi", "SIEM"), False),
    ("Stage Cybersecurity", "BlueShield", "Milano", D.format("affiancamento", "sicurezza informatica"), False),
    ("Tirocinio SOC", "Reply", "Torino", D.format("SOC", "SIEM"), False),
    ("Internship Security", "Mandiant", "Roma", D.format("security", "malware analysis"), False),
    ("Apprendistato Sistemista", "Rete Srl", "Trapani", D.format("rete", "Linux"), False),
    ("Sales Engineer Security", "Vendor", "Milano", D.format("vendite", "security"), False),
    ("Marketing Manager Cybersecurity", "Vendor", "Milano", D.format("marketing", "security"), False),
    ("Account Executive", "SecurCo", "Roma", D.format("vendite", "cybersecurity"), False),
    ("Security Architect", "BigBank", "Milano", D.format("architettura", "security SIEM"), False),
    ("Head of Security", "BigBank", "Roma", D.format("guida team", "security"), False),
    ("Lead SOC Analyst", "BigBank", "Roma", D.format("guida", "SIEM"), False),
    ("Principal Security Researcher", "Lab", "Roma", D.format("ricerca", "exploit"), False),
    ("Sviluppatore Java", "Engineering", "Roma", D.format("backend", "Spring"), False),
    ("Infermiere", "Humanitas", "Milano", D.format("reparto", "turni"), False),
    ("Cuoco", "Hotel Excelsior", "Venezia", D.format("cucina", "HACCP"), False),
    ("Magazziniere carrellista", "Logista", "Milano", D.format("magazzino", "carrello"), False),
    ("Social Media Specialist", "Agency", "Milano", D.format("social", "social media"), False),
    ("Analista SOC", "Reply", "Torino", D.format("monitoraggio", "SIEM Splunk"), False),
    ("Threat Intelligence Analyst", "Mandiant", "Remote", D.format("intelligence", "threat intelligence"), True),
    ("DevOps Engineer", "Datadog", "Paris", D.format("infrastructure", "linux kubernetes"), False),
    ("Vulnerability Management Specialist", "Atlas", "Roma", D.format("scansioni", "vulnerability assessment"), False),
    ("Cloud Security Engineer", "Okta", "Remote - USA", D.format("cloud", "security"), True),
    ("Network Administrator", "TelcoItalia", "Catania", D.format("rete", "networking"), False),
    ("Digital Forensics Analyst", "Polizia Postale", "Roma", D.format("indagini", "forensic"), False),
    ("AppSec Engineer", "Spotify", "Remote", D.format("appsec", "application security"), True),
    ("Junior Penetration Tester", "Cyberia", "Palermo", D.format("test", "bug bounty"), False),
    ("Social Engineer", "Agency", "Roma", D.format("campagne", "social"), False),
    ("Security Guard", "Vigilanza Srl", "Roma", D.format("sorveglianza", "security"), False),
    ("EDR Specialist Entry Level", "Sentinel", "Milano", D.format("endpoint", "EDR MDR"), False),
]

if __name__ == "__main__":
    cfg = settings.load_config(create_if_missing=True)
    out = []
    for t, c, loc, d, rem in J:
        job = Job(source="fake", title=t, company=c, location=loc, url="https://example.org/x", description=d, remote=rem)
        r = score_job(job, cfg)
        out.append({"title": t, "company": c, "location": loc, "description": d, "remote": rem,
                    "expected": None if r is None else {"score": r.score, "category": r.category, "matched": r.matched,
                                                         "near_home": r.near_home}})
    (Path(__file__).with_name("score_golden.json")).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    kept = sum(1 for o in out if o["expected"])
    print(len(out), "annunci,", kept, "con punteggio")
