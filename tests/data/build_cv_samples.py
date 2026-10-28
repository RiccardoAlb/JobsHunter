"""Genera i CV SINTETICI di prova in tests/data/cv/ (persone e aziende inventate, nessun dato reale).

Uso: .venv/bin/python tests/data/build_cv_samples.py   (i file sono gia' in repo; serve solo per rigenerarli)
Niente librerie esterne: il PDF e il DOCX si scrivono a mano.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).parent / "cv"

CYBER_JUNIOR = """Marco Esempio (CV di prova, persona inventata)
Analista SOC junior

Profilo
Neolaureato in informatica con stage in un SOC. Cerco il primo impiego come analista di sicurezza (Blue Team).

Esperienza
03/2024 - 09/2024  Stage Security Analyst presso Acme Security Srl (azienda inventata)
Triage degli alert su SIEM Splunk e Wazuh, analisi dei log, gestione di ticket di incident response, report settimanali.
Uso di Wireshark e Nmap per analisi del traffico e vulnerability assessment di base.

Istruzione
2020 - 2023  Laurea triennale in Informatica, Universita' di Esempio
2015 - 2020  Diploma di perito informatico

Competenze
SIEM, Splunk, Wazuh, EDR, MITRE ATT&CK, Wireshark, Nmap, Kali Linux, Metasploit, Active Directory, Linux, Windows, Python, Bash, SQL, Git.
Cybersecurity, penetration testing, OWASP Top 10, CTF su TryHackMe e HackTheBox. Certificazione eJPT.

Lingue
Italiano madrelingua. Inglese B2 (scritto e parlato).
"""

SISTEMISTA = """Luigi Prova (CV di prova, persona inventata)
Sistemista Windows e Linux

Esperienza
2016 - presente  Sistemista senior presso Beta Informatica (azienda inventata)
Gestione di server Windows Server 2019 e 2022, Active Directory, Group Policy, Microsoft 365 e Exchange Online.
Virtualizzazione con VMware vSphere e Hyper-V, backup con Veeam, monitoraggio con Zabbix e Grafana.
Amministrazione di server Linux (Debian, Ubuntu), scripting in PowerShell e Bash, firewall Fortinet e pfSense, VPN.
Help desk di secondo livello, ticketing con GLPI, ITIL.

2012 - 2016  Tecnico help desk presso Gamma Service (azienda inventata)
Assistenza utenti, gestione stampanti, reti LAN e VLAN, Cisco e MikroTik.

Istruzione
2007 - 2012  Diploma di perito informatico

Lingue
Inglese B1, tedesco base.
"""

SVILUPPATORE = """Giulia Campione (CV di prova, persona inventata)
Sviluppatrice full stack

Esperienza
2019 - 2024  Sviluppatrice backend presso Delta Software (azienda inventata)
Sviluppo di API REST in Python con Django e FastAPI, database PostgreSQL e Redis, deploy con Docker e Kubernetes.
Frontend in React e TypeScript. Pipeline CI/CD con GitLab CI e GitHub Actions, test con pytest, metodologia Agile e Scrum.
Cloud AWS (EC2, S3, Lambda) e Terraform.

Istruzione
2014 - 2019  Laurea magistrale in Ingegneria informatica

Competenze
Python, JavaScript, TypeScript, Java, SQL, Git, Linux, Docker, REST API, microservizi.

Lingue
Inglese C1, spagnolo B1.
"""

INFERMIERE = """Anna Esempio (CV di prova, persona inventata)
Infermiera professionale

Esperienza
2018 - 2023  Infermiera presso Ospedale di Esempio (struttura inventata), reparto di Pronto Soccorso
Triage, assistenza ai pazienti, somministrazione terapie, prelievi venosi, medicazioni, gestione della cartella clinica.
Corso BLSD e primo soccorso. Lavoro in team con medici e OSS, turni su 24 ore.

Istruzione
2015 - 2018  Laurea in Infermieristica

Lingue
Inglese B1.
"""

ENGLISH = """Sam Sample (synthetic test CV, invented person)
Data Analyst

Professional experience
Jan 2021 - Present  Data Analyst at Orange Analytics Ltd (invented company)
Built dashboards in Power BI and Tableau, wrote SQL queries on PostgreSQL and SQL Server, automated reports with Python and pandas.
Statistics, ETL pipelines, data quality checks. Worked in an Agile team with strong communication skills and attention to detail.

Jun 2019 - Dec 2020  Junior analyst at Blue Retail Ltd (invented company)
Excel reporting with pivot tables and VBA.

Education
2015 - 2019  BSc in Statistics, Example University

Languages
English (native), Italian B2.
"""


def pdf_bytes(pages: list[list[str]], with_text: bool = True) -> bytes:
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)

    add(b"")  # 1 catalogo (riempito dopo)
    add(b"")  # 2 pagine (riempito dopo)
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    kids = []
    for lines in pages:
        if with_text:
            parts = ["BT", "/F1 11 Tf", "14 TL", "50 790 Td"]
            for ln in lines:
                esc = ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                parts.append(f"({esc}) Tj T*")
            parts.append("ET")
        else:  # solo grafica: una scansione non ha testo selezionabile
            parts = ["0.8 g", "50 400 400 300 re", "f"]
        stream = "\n".join(parts).encode("cp1252", "replace")
        c = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        p = add(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>" % (font, c))
        kids.append(p)
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)
    out = b"%PDF-1.4\n"
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def pdf_positioned(items: list[tuple[int, int, str]]) -> bytes:
    """PDF con testo in posizioni assolute (x, y, testo), scritto nell'ordine dato: serve a imitare i CV a due colonne,
    dove l'ordine del testo nel file non e' quello di lettura (i titoli di sezione arrivano dopo i contenuti di un'altra colonna)."""
    parts = ["BT", "/F1 10 Tf"]
    cx = cy = 0
    for x, y, t in items:
        esc = t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        parts.append(f"{x - cx} {y - cy} Td ({esc}) Tj")
        cx, cy = x, y
    parts.append("ET")
    stream = "\n".join(parts).encode("cp1252", "replace")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out = b"%PDF-1.4\n"
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


# CV a due colonne (persona e aziende inventate): colonna sinistra = contatti, competenze, corsi; destra = studi ed esperienza.
# L'ordine nel file e' volutamente "sbagliato": gli studi e i corsi arrivano PRIMA del titolo "Esperienze professionali".
DUE_COLONNE = [
    (40, 800, "Paolo Fittizio"), (40, 785, "Junior security analyst in transizione dalla logistica"),
    (40, 760, "Competenze"), (40, 745, "SIEM, Splunk, Wazuh, Wireshark, Nmap, Linux, Python, Bash"), (40, 730, "Active Directory, incident response, OWASP"),
    (310, 800, "Istruzione"),
    (310, 780, "2014 - 2019 | ISTITUTO TECNICO INDUSTRIALE DI ESEMPIO |"), (310, 765, "Diploma di perito informatico"),
    (310, 745, "2019 - 2021 | UNIVERSITA' DEGLI STUDI DI ESEMPIO |"), (310, 730, "Laurea triennale in Informatica (non conclusa)"),
    (310, 710, "2026 | ACADEMY DI ESEMPIO INSTITUTE OF TECHNOLOGY |"),
    (310, 690, "Esperienze professionali"),
    (310, 672, "| FEB. 2023 - MARZ. 2026 |"), (310, 658, "Addetto magazzino, Logistica Esempio Srl"), (310, 644, "Gestione ordini, uso del gestionale e lavoro di squadra"),
    (40, 700, "Corsi e certificazioni"),
    (40, 685, "Agosto 2026 | Certificazione di esempio junior penetration tester |"), (40, 670, "Maggio 2026 | Introduzione alla sicurezza informatica (corso online) |"),
    (40, 655, "Giugno 2025 | Corso di Linux di base |"),
    (40, 630, "Lingue"), (40, 615, "Italiano madrelingua, Inglese B2"),
]


def wrap(text: str, width: int = 95) -> list[str]:
    out = []
    for raw in text.splitlines():
        while len(raw) > width:
            cut = raw.rfind(" ", 0, width)
            cut = cut if cut > 0 else width
            out.append(raw[:cut])
            raw = raw[cut:].lstrip()
        out.append(raw)
    return out


def paginate(lines: list[str], per: int = 50) -> list[list[str]]:
    return [lines[i:i + per] for i in range(0, len(lines), per)] or [[]]


def docx_bytes(text: str) -> bytes:
    paras = "".join(f'<w:p><w:r><w:t xml:space="preserve">{escape(l)}</w:t></w:r></w:p>' for l in text.splitlines())
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + paras + "</w:body></w:document>")
    ct = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cyber_junior.txt").write_text(CYBER_JUNIOR, encoding="utf-8")
    (OUT / "sistemista.docx").write_bytes(docx_bytes(SISTEMISTA))
    (OUT / "sviluppatore.pdf").write_bytes(pdf_bytes(paginate(wrap(SVILUPPATORE))))
    (OUT / "infermiere.md").write_text("# Infermiera\n\n" + INFERMIERE, encoding="utf-8")
    (OUT / "english_data_analyst.txt").write_text(ENGLISH, encoding="utf-8")
    (OUT / "due_colonne_junior.pdf").write_bytes(pdf_positioned(DUE_COLONNE))
    (OUT / "scansione_senza_testo.pdf").write_bytes(pdf_bytes([[]], with_text=False))
    print("scritti:", ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()
