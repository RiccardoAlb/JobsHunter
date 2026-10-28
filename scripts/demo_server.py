#!/usr/bin/env python3
"""Server di prova con DATI FINTI, per fare gli screenshot della documentazione (o per provare la GUI).

Uso:  .venv/bin/python scripts/demo_server.py [--port 8851]

Crea una cartella dati TEMPORANEA (mai quella vera), usa una fonte finta (nessuna rete), inventa annunci, duplicati,
candidature e un CV di esempio, poi serve la GUI su 127.0.0.1. Ctrl+C per fermarlo: la cartella temporanea viene cancellata.
Aziende, persone e annunci sono inventati (indirizzi example.org).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

D = ("Descrizione sintetica dell'offerta usata per la documentazione. Responsabilita': {r}. Requisiti: {q}. "
     "Offriamo ambiente dinamico, formazione continua e possibilita' di lavoro ibrido.")

JOBS = [  # (titolo, azienda, sede, fonte, stipendio, responsabilita', requisiti)
    ("Junior SOC Analyst", "Aurora Cyber Srl", "Milano", "adzuna", "28.000-34.000 EUR", "triage degli alert su SIEM e EDR, incident response di primo livello", "SIEM, Splunk, Wazuh, Linux, Python, inglese B2"),
    ("SOC Analyst Tier 1", "Nordlicht Security", "Torino", "adzuna", "30.000-36.000 EUR", "monitoraggio 24/7, analisi dei log, escalation", "SIEM, EDR, MITRE ATT&CK, Active Directory"),
    ("Penetration Tester Junior", "Cobalto Labs", "Roma", "adzuna", "32.000-40.000 EUR", "penetration test su web e rete, report ai clienti", "Burp Suite, Metasploit, Kali Linux, OWASP, Python"),
    ("Penetration Tester Junior (m/f)", "Cobalto Labs S.p.A.", "Roma, Lazio", "jooble:jobsite", "", "penetration test su web e rete, report ai clienti", "Burp Suite, Metasploit, Kali Linux, OWASP"),
    ("Tecnico Sistemista", "Gemini Infrastrutture", "Bologna", "adzuna", "26.000-30.000 EUR", "gestione server Windows e Linux, Active Directory, backup", "Windows Server, Active Directory, VMware, PowerShell"),
    ("Tecnico Sistemista", "Gemini Infrastrutture Srl", "Bologna", "jooble:jobsite", "", "gestione server Windows e Linux, Active Directory, backup", "Windows Server, Active Directory, VMware"),
    ("Security Analyst (m/f)", "Quarzo Systems", "Napoli", "adzuna", "", "analisi delle vulnerabilita', gestione delle patch, threat intelligence", "vulnerability assessment, Nessus, SIEM, Linux"),
    ("Stage Cybersecurity", "Aurora Cyber Srl", "Milano", "adzuna", "", "affiancamento al team SOC, stage di sei mesi", "interesse per la sicurezza, Linux, networking"),
    ("Blue Team Engineer", "Helios Digital", "Remoto (Italia)", "remotive", "", "detection engineering, regole Sigma, tuning del SIEM", "Splunk, Elastic, Sigma, Python, incident response"),
    ("Incident Response Specialist", "Helios Digital", "Remoto (Italia)", "remotive", "", "gestione degli incidenti, analisi forense, DFIR", "DFIR, forensic, malware analysis, EDR"),
    ("IT Support Specialist", "Fabbrica Nuova Spa", "Padova", "adzuna", "24.000-27.000 EUR", "assistenza agli utenti, help desk, gestione postazioni", "help desk, Windows, Office 365, Active Directory"),
    ("Network Administrator", "Ponente Reti", "Genova", "adzuna", "", "gestione di rete e firewall, VPN", "networking, firewall, VPN, Linux"),
    ("Senior Security Architect", "Quarzo Systems", "Milano", "adzuna", "70.000-85.000 EUR", "architettura di sicurezza cloud", "cloud security, architecture, SIEM, 8 anni di esperienza"),
    ("Red Team Operator", "Cobalto Labs", "Roma", "adzuna", "", "simulazioni di attacco, red team", "red team, Active Directory, Cobalt Strike, OSCP"),
    ("Cloud Security Engineer", "Nuvola Group", "Milano", "adzuna", "45.000-55.000 EUR", "sicurezza AWS e Azure, automazione", "AWS, Azure, Terraform, Python, SIEM"),
    ("Vulnerability Analyst Junior", "Nordlicht Security", "Torino", "adzuna", "", "scansioni, triage delle vulnerabilita'", "vulnerability assessment, Nessus, Linux, Python"),
]

CV = """Marco Esempio (CV di prova, persona inventata)
Analista SOC junior

Profilo
Neolaureato in informatica con stage in un SOC. Cerco il primo impiego come analista di sicurezza (Blue Team).

Esperienza
03/2024 - 09/2024  Stage Security Analyst presso Acme Security Srl (azienda inventata)
Triage degli alert su SIEM Splunk e Wazuh, analisi dei log, gestione di ticket di incident response, report settimanali.
Uso di Wireshark e Nmap per analisi del traffico e vulnerability assessment di base.

Istruzione
2020 - 2023  Laurea triennale in Informatica, Universita' di Esempio

Competenze
SIEM, Splunk, Wazuh, EDR, MITRE ATT&CK, Wireshark, Nmap, Kali Linux, Metasploit, Active Directory, Linux, Windows, Python, Bash, SQL, Git.
Cybersecurity, penetration testing, OWASP Top 10, CTF su TryHackMe e HackTheBox.

Lingue
Italiano madrelingua. Inglese B2 (scritto e parlato).
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8851)
    args = ap.parse_args()
    if args.port in (8765, 8791, 8793, 8794, 8802, 8811):
        sys.exit("porta riservata ad altri usi: scegline un'altra")
    tmp = Path(tempfile.mkdtemp(prefix="jobshunter-demo-"))
    os.environ["JOBSHUNTER_HOME"] = str(tmp)
    os.environ["HOME"] = str(tmp)  # mai ~/Library vero (LaunchAgent, log...)
    try:
        run(tmp, args.port)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(tmp: Path, port: int) -> None:
    from jobshunter import cv as cvmod, scheduler, settings
    from jobshunter.db import DB
    from jobshunter.gui.app import create_app
    from jobshunter.models import Job
    from jobshunter.scanner import run_scan
    from jobshunter.sources import REGISTRY
    from jobshunter.sources.base import Source

    scheduler.install = lambda *a, **k: None  # niente LaunchAgent nemmeno per sbaglio
    scheduler.uninstall = lambda *a, **k: None
    scheduler.is_loaded = lambda: False
    now = datetime.now(timezone.utc)

    class Demo(Source):
        name = "demo"

        def fetch_queries(self, queries):
            out = []
            for i, (title, company, loc, src, sal, resp, req) in enumerate(JOBS):
                out.append(Job(source=src, title=title, company=company, location=loc, url=f"https://example.org/demo/{i}",
                               description=D.format(r=resp, q=req), posted_at=now - timedelta(days=i % 9), salary=sal,
                               remote="Remoto" in loc, country="it"))
            return out

        def fetch(self):
            return self.fetch_queries([])

    REGISTRY["demo"] = Demo
    cfg = settings.load_config(create_if_missing=True)
    cfg["sources"] = {"demo": {"enabled": True}}
    cfg["general"]["min_score"] = 5
    cfg.setdefault("dedupe", {})["auto_confirm_percent"] = 101  # le coppie restano "da rivedere", cosi' si vedono nello screenshot
    cfg.setdefault("availability", {})["auto_check_after_scan"] = 0
    db = DB(settings.resolve_path(cfg["general"]["db_path"]), cfg)
    run_scan(cfg, db)
    rows = db.query(min_score=0, limit=100)
    for r in rows:
        if r["source"] == "adzuna":
            db.set_full_text(r["uid"], D.format(r=r["title"], q=r["company"]) + "\n\nSede: " + (r["location"] or ""), r["salary"] or "")
            db.set_avail(r["uid"], "open", None, "annuncio presente")
    if rows:
        db.set_avail(rows[-1]["uid"], "closed", "2026-10-01", "scaduto il 01/10/2026")
        for r in rows[:3]:
            db.set_status(r["uid"], "seen")
        db.set_status(rows[1]["uid"], "applied")
        db.ensure_application(rows[1]["uid"])
    a = db.add_application(company="Gemini Infrastrutture", role="Tecnico Sistemista", location="Bologna", contact="HR Gemini (esempio)",
                           applied_at=(now - timedelta(days=12)).date().isoformat(), follow_up=(now - timedelta(days=1)).date().isoformat())
    db.set_app_stage(a, "hr", (now - timedelta(days=6)).date().isoformat())
    b = db.add_application(company="Helios Digital", role="Blue Team Engineer", location="Remoto",
                           applied_at=(now - timedelta(days=20)).date().isoformat())
    db.set_app_stage(b, "tech", (now - timedelta(days=3)).date().isoformat())
    db.kv_set("onboarding_done", "1")
    cvmod.save_text(CV, "incollato")
    db.commit()
    app = create_app(None, port)
    print(f"Demo con dati finti su http://127.0.0.1:{port}  (cartella temporanea {tmp}). Ctrl+C per uscire.", flush=True)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
