"""Genera tests/data/dedupe_holdout.json: secondo set etichettato, con vocabolario NUOVO, da usare solo per controllare
che BUILDER non si sia adattato ai casi del primo set (dedupe_cases.json). Stesse regole di etichettatura."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_dedupe_cases as b  # noqa: E402

b.CASES.clear()
D, N = b.D, b.N
AD, JO, CO = b.AD, b.JO, b.CO
SEC, DEV, SAN, RIS, LOG, ADM, VEN, IST = b.SEC, b.DEV, b.SAN, b.RIS, b.LOG, b.ADM, b.VEN, b.IST

# ---- duplicati veri
D(SEC, "en", "hard", "Corp e genere", ("Threat Hunter", "Rapid7 Corp", "Boston", AD), ("Threat Hunter (m/f/d)", "Rapid7", "Boston, MA", JO))
D(SEC, "it", "hard", "Spa con puntini e sede provincia", ("Responsabile Sicurezza Informatica", "Poste Italiane S.p.A.", "Roma", AD), ("Responsabile Sicurezza Informatica", "Poste Italiane", "Provincia di Roma", JO))
D(SEC, "de", "hard", "AG e Ort", ("IT Security Analyst (m/w/d)", "Allianz SE", "Muenchen", AD), ("IT Security Analyst", "Allianz", "Muenchen, Bayern", JO))
D(SEC, "fr", "hard", "H/F e SAS", ("Analyste SOC H/F", "Sopra Steria SAS", "Nantes", AD), ("Analyste SOC", "Sopra Steria", "Nantes", JO))
D(DEV, "es", "hard", "S.L. e o/a", ("Programador/a Java", "Seidor S.L.", "Sevilla", AD), ("Programador Java", "Seidor", "Sevilla", JO))
D(DEV, "en", "hard", "titolo con coda", ("Platform Engineer", "Stripe Inc", "Dublin", CO), ("Platform Engineer - Payments", "Stripe", "Dublin", AD))
D(DEV, "it", "hard", "sigla e maiuscole", ("SVILUPPATORE C++", "Elettronica S.p.A.", "Roma", AD), ("Sviluppatore C++", "Elettronica", "Roma", JO))
D(DEV, "de", "hard", "genere con barra", ("Softwarearchitekt/in", "Otto Group", "Hamburg", AD), ("Softwarearchitekt", "Otto", "Hamburg", JO))
D(SAN, "it", "hard", "forma estesa vs sigla non prevista nel titolo: stessa parola", ("Tecnico di laboratorio biomedico", "Synlab Italia Srl", "Brescia", AD), ("Tecnico di laboratorio biomedico (M/F)", "Synlab", "Brescia", JO))
D(SAN, "en", "hard", "Trust vs NHS", ("Paediatric Nurse", "Guys and St Thomas NHS Foundation Trust", "London", AD), ("Paediatric Nurse", "Guys and St Thomas NHS Foundation Trust", "London, Greater London", JO))
D(SAN, "es", "hard", "o/a", ("Fisioterapeuta", "Sanitas S.A.", "Valencia", AD), ("Fisioterapeuta (H/M)", "Sanitas", "Valencia", JO))
D(RIS, "it", "hard", "S.n.c. e coda", ("Pizzaiolo", "Pizzeria Il Vesuvio S.n.c.", "Torino", AD), ("Pizzaiolo - serali", "Pizzeria Il Vesuvio", "Torino", JO))
D(RIS, "de", "hard", "m/w/d", ("Servicemitarbeiter (m/w/d)", "Hofbraeu GmbH", "Muenchen", AD), ("Servicemitarbeiter", "Hofbraeu", "Muenchen", JO))
D(RIS, "fr", "hard", "H/F", ("Cuisinier H/F", "Sodexo SA", "Bordeaux", AD), ("Cuisinier", "Sodexo", "Bordeaux", JO))
D(LOG, "it", "hard", "provincia e Srl", ("Operatore carrellista", "Ceva Logistics Italia Srl", "Piacenza", AD), ("Operatore carrellista (M/F)", "Ceva Logistics", "Piacenza, Provincia di Piacenza", JO))
D(LOG, "en", "hard", "Ltd e coda", ("Delivery Driver", "Yodel Delivery Network Ltd", "Birmingham", AD), ("Delivery Driver - Van", "Yodel Delivery Network", "Birmingham", JO))
D(LOG, "fr", "hard", "H/F e sede", ("Magasinier H/F", "Geodis SA", "Marseille", AD), ("Magasinier", "Geodis", "Marseille", JO))
D(ADM, "it", "hard", "Spa + F/M", ("Addetta paghe e contributi", "Zucchetti S.p.A.", "Lodi", AD), ("Addetta paghe e contributi (F/M)", "Zucchetti", "Lodi", JO))
D(ADM, "en", "hard", "Plc e sede nel titolo", ("Payroll Administrator", "Tesco Plc", "Welwyn Garden City", AD), ("Payroll Administrator", "Tesco", "Welwyn Garden City, Hertfordshire", JO))
D(ADM, "es", "hard", "o/a", ("Administrativo/a contable", "Repsol S.A.", "Madrid", AD), ("Administrativo contable", "Repsol", "Madrid", JO))
D(VEN, "it", "hard", "gruppo e coda", ("Consulente di vendita auto", "Gruppo Autotorino S.p.A.", "Milano", AD), ("Consulente di vendita auto - nuovo", "Autotorino", "Milano", JO))
D(VEN, "de", "hard", "m/w/d", ("Verkaufsberater (m/w/d)", "MediaMarkt GmbH", "Koeln", AD), ("Verkaufsberater", "MediaMarkt", "Koeln", JO))
D(VEN, "en", "hard", "Ltd e Jr", ("Jr Sales Executive", "Clearbit Ltd", "London", AD), ("Junior Sales Executive", "Clearbit", "London", JO))
D(IST, "it", "hard", "Srl e coda", ("Docente di informatica", "Scuola Futura Srl", "Bologna", AD), ("Docente di informatica (F/M) - secondaria", "Scuola Futura", "Bologna", JO))
D(IST, "fr", "hard", "H/F", ("Professeur des ecoles H/F", "Groupe Scolaire Saint Louis", "Rennes", AD), ("Professeur des ecoles", "Groupe Scolaire Saint Louis", "Rennes", JO))
D(IST, "en", "hard", "Ltd", ("Lecturer in Economics", "Kings College London Ltd", "London", AD), ("Lecturer in Economics", "Kings College London", "London", JO))
D(IST, "es", "hard", "o/a", ("Maestro/a de primaria", "Colegio San Jose S.L.", "Bilbao", AD), ("Maestro de primaria", "Colegio San Jose", "Bilbao", JO))
D(SEC, "en", "easy", "stesso annuncio, fonti diverse", ("Malware Analyst", "Kaspersky", "Prague", AD), ("Malware Analyst", "Kaspersky", "Prague", JO))
D(LOG, "de", "easy", "stesso annuncio", ("Kommissionierer (m/w/d)", "Kuehne Nagel", "Bremen", AD), ("Kommissionierer (m/w/d)", "Kuehne Nagel", "Bremen", JO))
D(ADM, "it", "hard", "azienda abbreviata", ("Impiegato ufficio acquisti", "Banca Monte dei Paschi di Siena S.p.A.", "Siena", AD), ("Impiegato ufficio acquisti", "Banca Monte dei Paschi di Siena", "Siena", JO))

# ---- non duplicati
N(SEC, "en", "hard", "Analyst vs Engineer", ("Detection Engineer", "Rapid7", "Boston", AD), ("Detection Analyst", "Rapid7", "Boston", AD))
N(SEC, "it", "hard", "Junior vs Senior", ("Analista Cyber Junior", "Poste Italiane", "Roma", AD), ("Analista Cyber Senior", "Poste Italiane", "Roma", AD))
N(SEC, "de", "hard", "Level 1 vs 2", ("Security Operations Center Analyst L1 (m/w/d)", "Allianz", "Muenchen", AD), ("Security Operations Center Analyst L2 (m/w/d)", "Allianz", "Muenchen", AD))
N(SEC, "en", "hard", "citta' diverse", ("Threat Hunter", "Rapid7", "Boston", AD), ("Threat Hunter", "Rapid7", "Belfast", AD))
N(DEV, "en", "hard", "Python vs Ruby", ("Python Developer", "Stripe", "Dublin", AD), ("Ruby Developer", "Stripe", "Dublin", AD))
N(DEV, "it", "hard", "C++ vs C#", ("Sviluppatore C++", "Elettronica", "Roma", AD), ("Sviluppatore C#", "Elettronica", "Roma", AD))
N(DEV, "de", "hard", "Front vs Back", ("Frontend Entwickler (m/w/d)", "Otto", "Hamburg", AD), ("Backend Entwickler (m/w/d)", "Otto", "Hamburg", AD))
N(DEV, "es", "hard", "Java vs PHP", ("Programador/a Java", "Seidor", "Sevilla", AD), ("Programador/a PHP", "Seidor", "Sevilla", AD))
N(DEV, "en", "hard", "Engineer vs Principal Engineer", ("Platform Engineer", "Stripe", "Dublin", AD), ("Principal Platform Engineer", "Stripe", "Dublin", AD))
N(SAN, "it", "hard", "tecnici diversi", ("Tecnico di laboratorio biomedico", "Synlab", "Brescia", AD), ("Tecnico di radiologia medica", "Synlab", "Brescia", AD))
N(SAN, "en", "hard", "Paediatric vs Adult nurse", ("Paediatric Nurse", "Guys and St Thomas NHS Foundation Trust", "London", AD), ("Adult Nurse", "Guys and St Thomas NHS Foundation Trust", "London", AD))
N(SAN, "es", "hard", "Fisio vs Osteopata", ("Fisioterapeuta", "Sanitas", "Valencia", AD), ("Osteopata", "Sanitas", "Valencia", AD))
N(SAN, "it", "hard", "Pediatria vs geriatria", ("Infermiere reparto pediatria", "Ospedale San Raffaele", "Milano", AD), ("Infermiere reparto geriatria", "Ospedale San Raffaele", "Milano", AD))
N(RIS, "it", "hard", "pizzaiolo vs aiuto", ("Pizzaiolo", "Pizzeria Il Vesuvio", "Torino", AD), ("Aiuto pizzaiolo", "Pizzeria Il Vesuvio", "Torino", AD))
N(RIS, "de", "hard", "Service vs Kueche", ("Servicemitarbeiter (m/w/d)", "Hofbraeu", "Muenchen", AD), ("Kuechenmitarbeiter (m/w/d)", "Hofbraeu", "Muenchen", AD))
N(RIS, "fr", "hard", "Cuisinier vs Commis", ("Cuisinier H/F", "Sodexo", "Bordeaux", AD), ("Commis de cuisine H/F", "Sodexo", "Bordeaux", AD))
N(RIS, "en", "hard", "nomi simili", ("Waiter", "Pizza Express", "Leeds", AD), ("Waiter", "Pizza Hut", "Leeds", AD))
N(LOG, "it", "hard", "carrellista vs magazziniere", ("Operatore carrellista", "Ceva Logistics", "Piacenza", AD), ("Operatore di magazzino", "Ceva Logistics", "Piacenza", AD))
N(LOG, "en", "hard", "Van vs HGV", ("Delivery Driver Van", "Yodel", "Birmingham", AD), ("Delivery Driver HGV", "Yodel", "Birmingham", AD))
N(LOG, "fr", "hard", "Magasinier vs Cariste", ("Magasinier H/F", "Geodis", "Marseille", AD), ("Cariste H/F", "Geodis", "Marseille", AD))
N(LOG, "de", "hard", "Kommissionierer vs Versandmitarbeiter", ("Kommissionierer (m/w/d)", "Kuehne Nagel", "Bremen", AD), ("Versandmitarbeiter (m/w/d)", "Kuehne Nagel", "Bremen", AD))
N(ADM, "it", "hard", "paghe vs contabilita'", ("Addetta paghe e contributi", "Zucchetti", "Lodi", AD), ("Addetta contabilita' generale", "Zucchetti", "Lodi", AD))
N(ADM, "en", "hard", "Payroll vs Pensions", ("Payroll Administrator", "Tesco", "Welwyn Garden City", AD), ("Pensions Administrator", "Tesco", "Welwyn Garden City", AD))
N(ADM, "es", "hard", "contable vs fiscal", ("Administrativo/a contable", "Repsol", "Madrid", AD), ("Administrativo/a fiscal", "Repsol", "Madrid", AD))
N(ADM, "it", "hard", "acquisti vs vendite", ("Impiegato ufficio acquisti", "Banca Monte dei Paschi", "Siena", AD), ("Impiegato ufficio legale", "Banca Monte dei Paschi", "Siena", AD))
N(VEN, "it", "hard", "auto nuove vs usate", ("Consulente di vendita auto nuove", "Autotorino", "Milano", AD), ("Consulente di vendita auto usate", "Autotorino", "Milano", AD))
N(VEN, "de", "hard", "citta' diverse", ("Verkaufsberater (m/w/d)", "MediaMarkt", "Koeln", AD), ("Verkaufsberater (m/w/d)", "MediaMarkt", "Duesseldorf", AD))
N(VEN, "en", "hard", "Executive vs Manager", ("Sales Executive", "Clearbit", "London", AD), ("Sales Manager", "Clearbit", "London", AD))
N(VEN, "fr", "hard", "Vendeur rayon diversi", ("Vendeur rayon bricolage H/F", "Castorama", "Lyon", AD), ("Vendeur rayon jardin H/F", "Castorama", "Lyon", AD))
N(IST, "it", "hard", "informatica vs fisica", ("Docente di informatica", "Scuola Futura", "Bologna", AD), ("Docente di fisica", "Scuola Futura", "Bologna", AD))
N(IST, "en", "hard", "Economics vs Law", ("Lecturer in Economics", "Kings College London", "London", AD), ("Lecturer in Law", "Kings College London", "London", AD))
N(IST, "es", "hard", "primaria vs secundaria", ("Maestro/a de primaria", "Colegio San Jose", "Bilbao", AD), ("Maestro/a de infantil", "Colegio San Jose", "Bilbao", AD))
N(IST, "fr", "hard", "scuole omonime di citta' diverse", ("Professeur des ecoles H/F", "Groupe Scolaire Saint Louis", "Rennes", AD), ("Professeur des ecoles H/F", "Groupe Scolaire Saint Louis", "Brest", AD))
N(SEC, "it", "hard", "societa' diverse con nome simile", ("Consulente Cybersecurity", "Almaviva S.p.A.", "Roma", AD), ("Consulente Cybersecurity", "Almawave S.p.A.", "Roma", AD))
N(DEV, "en", "hard", "societa' con nome quasi uguale", ("Data Scientist", "Palantir Technologies", "London", AD), ("Data Scientist", "Palantir Capital", "London", AD))
N(VEN, "it", "hard", "catene diverse", ("Addetto vendite", "Mediaworld", "Roma", AD), ("Addetto vendite", "Mediaworld Express", "Napoli", AD))
N(SAN, "de", "hard", "kliniken diverse", ("Pflegefachkraft (m/w/d)", "Klinikum Nord", "Hamburg", AD), ("Pflegefachkraft (m/w/d)", "Klinikum Sued", "Hamburg", AD))
N(RIS, "es", "hard", "locali diversi", ("Camarero/a", "Restaurante La Barca", "Cadiz", AD), ("Camarero/a", "Restaurante La Barra", "Cadiz", AD))
N(LOG, "it", "hard", "corrieri diversi", ("Fattorino", "Glovo Italia", "Milano", AD), ("Fattorino", "Deliveroo Italia", "Milano", AD))
N(ADM, "fr", "hard", "Gestionnaire paie vs comptable", ("Gestionnaire de paie H/F", "Adecco France", "Lille", AD), ("Comptable H/F", "Adecco France", "Lille", AD))
N(SEC, "en", "hard", "Intern vs Analyst", ("Cyber Security Intern", "Rapid7", "Boston", AD), ("Cyber Security Analyst", "Rapid7", "Boston", AD))
N(DEV, "it", "hard", "Python vs Java stessa azienda e sede", ("Sviluppatore Python", "Engineering Ingegneria Informatica", "Roma", AD), ("Sviluppatore Java", "Engineering Ingegneria Informatica", "Roma", AD))

for c in b.CASES:
    c["id"] = "h" + c["id"][1:]
b.enrich(b.CASES)

if __name__ == "__main__":
    out = Path(__file__).with_name("dedupe_holdout.json")
    out.write_text(json.dumps(b.CASES, ensure_ascii=False, indent=1), encoding="utf-8")
    d = sum(c["label"] == "dup" for c in b.CASES)
    print(f"{len(b.CASES)} casi: {d} duplicati, {len(b.CASES) - d} non duplicati -> {out}")
