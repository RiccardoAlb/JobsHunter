"""Genera tests/data/dedupe_cases.json (set etichettato di coppie di annunci, scritto dal TESTER).

Uso: .venv/bin/python tests/data/build_dedupe_cases.py
Ogni caso: due annunci come righe di DB, etichetta (dup = stesso identico lavoro, nodup = lavori diversi),
settore, lingua, difficolta' (easy | hard) e una nota. Le etichette sono decise dal significato dell'annuncio,
NON da cio' che fa il codice attuale.
"""
import json
from pathlib import Path

CASES: list[dict] = []


def row(t):
    title, company, loc, src = t[:4]
    salary = t[4] if len(t) > 4 else ""
    return {"title": title, "company": company, "location": loc, "source": src, "salary": salary}


def add(label, sector, lang, level, note, a, b):
    CASES.append({"id": f"c{len(CASES) + 1:03d}", "label": label, "sector": sector, "lang": lang,
                  "difficulty": level, "note": note, "a": row(a), "b": row(b)})


def D(sector, lang, level, note, a, b):
    add("dup", sector, lang, level, note, a, b)


def N(sector, lang, level, note, a, b):
    add("nodup", sector, lang, level, note, a, b)


AD, JO, CO, AR, RO = "adzuna", "jooble", "greenhouse", "arbeitnow", "remoteok"
SEC, DEV, SAN, RIS, LOG, ADM, VEN, IST = ("cybersecurity", "sviluppo software", "sanita'", "ristorazione",
                                           "logistica", "amministrazione", "vendite", "istruzione")

# =============================================================== DUPLICATI VERI ===
# --- cybersecurity
D(SEC, "it", "easy", "identici da due fonti", ("SOC Analyst", "Acme Security", "Milano", AD), ("SOC Analyst", "Acme Security", "Milano", JO))
D(SEC, "it", "hard", "suffisso S.p.A., genere, provincia", ("SOC Analyst", "Acme Security S.p.A.", "Milano", AD), ("SOC Analyst (m/f)", "Acme Security", "Milano, Provincia di Milano", JO))
D(SEC, "it", "hard", "Srl con punti e maiuscole", ("Penetration Tester", "Cyberia S.r.l.", "Roma", AD), ("PENETRATION TESTER", "CYBERIA", "Roma, Lazio", JO))
D(SEC, "it", "hard", "sede generica Italia da una parte", ("Analista SOC", "Reply S.p.A.", "Torino", AD), ("Analista SOC", "Reply", "Italia", JO))
D(SEC, "en", "hard", "Ltd e remoto/citta", ("Incident Response Engineer", "Mandiant Ltd", "London", CO), ("Incident Response Engineer", "Mandiant", "London, Greater London", AD))
D(SEC, "en", "hard", "Sr. contro Senior", ("Sr. SOC Analyst", "Sentinel Corp", "Dublin", CO), ("Senior SOC Analyst", "Sentinel Corp", "Dublin", AD))
D(SEC, "en", "hard", "parole in piu' nel titolo", ("Security Engineer", "Okta Inc", "San Francisco", CO), ("Security Engineer - Detection and Response", "Okta Inc", "San Francisco, CA", AD))
D(SEC, "en", "hard", "L1 con suffisso di team", ("Security Analyst L1", "BlueShield Ltd", "Manchester", AD), ("Security Analyst L1 - SOC", "BlueShield", "Manchester", JO))
D(SEC, "de", "hard", "GmbH e m/w/d", ("SIEM Engineer", "CrowdStrike GmbH", "Berlin", AR), ("SIEM Engineer (m/w/d)", "CrowdStrike", "Berlin", AD))
D(SEC, "de", "hard", "Genere e Deutschland", ("IT-Sicherheitsberater (m/w/d)", "Secunet AG", "Essen", AD), ("IT-Sicherheitsberater", "Secunet", "Essen, Nordrhein-Westfalen", JO))
D(SEC, "fr", "hard", "H/F non riconosciuto dal genere m/f/d", ("Ingenieur Cybersecurite", "Thales SA", "Paris", AD), ("Ingenieur Cybersecurite H/F", "Thales", "Paris, Ile-de-France", JO))
D(SEC, "es", "hard", "S.A. e (H/M)", ("Analista de Ciberseguridad", "Telefonica S.A.", "Madrid", AD), ("Analista de Ciberseguridad (H/M)", "Telefonica", "Madrid", JO))
D(SEC, "it", "easy", "stipendio presente solo in una", ("Sistemista Linux", "Exprivia", "Bari", AD, "35.000 EUR"), ("Sistemista Linux", "Exprivia S.p.A.", "Bari", JO))
D(SEC, "en", "hard", "sigla S.O.C. con punti", ("S.O.C. Analyst", "Nexus Defence", "Leeds", AD), ("SOC Analyst", "Nexus Defence", "Leeds", JO))
D(SEC, "it", "hard", "titolo con trattino e livello descrittivo in piu'", ("Cyber Security Specialist", "Leonardo S.p.A.", "Roma", CO), ("Cyber Security Specialist - Roma", "Leonardo", "Roma", AD))

# --- sviluppo software
D(DEV, "it", "hard", "S.p.A. e m/f", ("Sviluppatore Java Full Stack", "Engineering Ingegneria Informatica S.p.A.", "Roma", AD), ("Sviluppatore Java Full Stack (m/f)", "Engineering Ingegneria Informatica", "Roma, Lazio", JO))
D(DEV, "en", "hard", "parentesi tecnologia", ("Backend Developer (Python)", "Spotify AB", "Stockholm", CO), ("Backend Developer Python", "Spotify", "Stockholm", AD))
D(DEV, "de", "easy", "m/w/d", ("Full Stack Entwickler (m/w/d)", "Zalando SE", "Berlin", AR), ("Full Stack Entwickler", "Zalando", "Berlin", AD))
D(DEV, "es", "hard", "genere con barra", ("Desarrollador Backend", "Glovo", "Barcelona", AD), ("Desarrollador/a Backend", "Glovo", "Barcelona", JO))
D(DEV, "fr", "hard", "H/F", ("Developpeur Java", "Capgemini", "Lyon", AD), ("Developpeur Java H/F", "Capgemini SE", "Lyon", JO))
D(DEV, "en", "hard", "Jr contro Junior", ("Jr Developer", "Pixel Labs Ltd", "Bristol", AD), ("Junior Developer", "Pixel Labs", "Bristol", JO))
D(DEV, "en", "easy", "Inc e LLC", ("Software Engineer", "Google LLC", "Dublin", CO), ("Software Engineer", "Google", "Dublin", AD))
D(DEV, "en", "hard", "stessa posizione remoto vs paese", ("React Developer", "Mozilla Corporation", "Remote", RO), ("React Developer", "Mozilla", "Europe", AD))
D(DEV, "it", "hard", "maiuscole, punteggiatura e sigla", ("Front-End Developer", "Var Group S.p.A.", "Empoli", AD), ("FRONT END DEVELOPER", "Var Group", "Empoli, Toscana", JO))
D(DEV, "it", "hard", "parole in piu' (modalita')", ("Sviluppatore .NET", "Dedagroup", "Trento", AD), ("Sviluppatore .NET C#", "Dedagroup S.p.A.", "Trento", JO))
D(DEV, "en", "hard", "Engineer vs Engineer II non e' dup ma qui descrizione extra", ("DevOps Engineer", "Datadog Inc", "Paris", CO), ("DevOps Engineer - Platform", "Datadog", "Paris", AD))
D(DEV, "de", "hard", "AG e Gruppe", ("Softwareentwickler Java (m/w/d)", "Deutsche Bank AG", "Frankfurt am Main", AD), ("Softwareentwickler Java", "Deutsche Bank", "Frankfurt", JO))

# --- sanita'
D(SAN, "it", "easy", "identici", ("Infermiere", "ASL Roma 1", "Roma", AD), ("Infermiere", "ASL Roma 1", "Roma", JO))
D(SAN, "it", "hard", "gruppo + m/f", ("Infermiere (m/f)", "Gruppo San Donato", "Milano", AD), ("Infermiere", "San Donato", "Milano, Provincia di Milano", JO))
D(SAN, "it", "hard", "parole in piu' del titolo", ("Infermiere professionale", "Humanitas S.p.A.", "Rozzano", AD), ("Infermiere professionale - turni", "Humanitas", "Rozzano", JO))
D(SAN, "it", "hard", "sigla OSS riformulata", ("OSS Operatore Socio Sanitario", "Korian Italia Srl", "Bologna", AD), ("Operatore Socio Sanitario OSS", "Korian", "Bologna", JO))
D(SAN, "it", "hard", "forma di genere", ("Fisioterapista", "Villa Maria S.r.l.", "Torino", AD), ("Fisioterapista (M/F)", "Villa Maria", "Torino", JO))
D(SAN, "de", "hard", "azienda con nome piu' lungo", ("Pflegefachkraft (m/w/d)", "Charite", "Berlin", AD), ("Pflegefachkraft", "Charite Universitaetsmedizin Berlin", "Berlin", JO))
D(SAN, "es", "hard", "o/a", ("Enfermero/a", "Quironsalud", "Madrid", AD), ("Enfermero", "Quironsalud", "Madrid", JO))
D(SAN, "fr", "easy", "H/F", ("Infirmier H/F", "Ramsay Sante", "Marseille", AD), ("Infirmier", "Ramsay Sante", "Marseille", JO))
D(SAN, "en", "hard", "NHS Trust", ("Staff Nurse", "NHS Foundation Trust", "Leeds", AD), ("Staff Nurse", "NHS Foundation Trust", "Leeds, West Yorkshire", JO))
D(SAN, "it", "hard", "Medico: forma abbreviata", ("Medico di Pronto Soccorso", "Policlinico Gemelli", "Roma", AD), ("Medico di Pronto Soccorso (M/F)", "Policlinico Gemelli S.p.A.", "Roma", JO))

# --- ristorazione
D(RIS, "it", "hard", "Ristorante nel nome", ("Cameriere di sala", "Ristorante Da Mario Srl", "Napoli", AD), ("Cameriere di sala", "Da Mario", "Napoli", JO))
D(RIS, "en", "easy", "Ltd", ("Chef de Partie", "Hilton Ltd", "London", AD), ("Chef de Partie", "Hilton", "London", JO))
D(RIS, "en", "hard", "Company/Inc", ("Barista", "Starbucks Coffee Company", "Seattle", AD), ("Barista", "Starbucks", "Seattle, WA", JO))
D(RIS, "fr", "hard", "slash tra generi", ("Serveur / Serveuse", "Accor SA", "Paris", AD), ("Serveur/Serveuse", "Accor", "Paris", JO))
D(RIS, "de", "easy", "m/w/d", ("Koch (m/w/d)", "Steigenberger Hotels AG", "Hamburg", AD), ("Koch", "Steigenberger Hotels", "Hamburg", JO))
D(RIS, "es", "hard", "o/a e S.L.", ("Camarero/a de sala", "Grupo Tragaluz S.L.", "Barcelona", AD), ("Camarero de sala", "Tragaluz", "Barcelona", JO))
D(RIS, "it", "hard", "cuoco/a e punteggiatura", ("Cuoco/a", "Hotel Excelsior S.p.A.", "Venezia", AD), ("Cuoco", "Hotel Excelsior", "Venezia", JO))
D(RIS, "it", "hard", "parte del titolo stagionale", ("Cameriere", "Grand Hotel Savoia", "Cortina d'Ampezzo", AD), ("Cameriere - stagione invernale", "Grand Hotel Savoia", "Cortina d'Ampezzo", JO))
D(RIS, "en", "hard", "Commis Chef con ruolo extra", ("Commis Chef", "The Ritz London Ltd", "London", AD), ("Commis Chef (Full Time)", "The Ritz London", "London", JO))

# --- logistica / magazzino
D(LOG, "it", "hard", "S.p.A. e m/f", ("Magazziniere carrellista", "Logista Italia S.p.A.", "Milano", AD), ("Magazziniere Carrellista (m/f)", "Logista", "Milano, Lombardia", JO))
D(LOG, "it", "easy", "identici", ("Addetto al magazzino", "Brt S.p.A.", "Bologna", AD), ("Addetto al magazzino", "Brt S.p.A.", "Bologna", JO))
D(LOG, "en", "hard", "Ltd", ("Warehouse Operative", "DHL Supply Chain Ltd", "Manchester", AD), ("Warehouse Operative", "DHL Supply Chain", "Manchester", JO))
D(LOG, "de", "hard", "Lagerist m/w/d", ("Lagerist (m/w/d)", "Rhenus SE", "Duisburg", AD), ("Lagerist", "Rhenus", "Duisburg", JO))
D(LOG, "fr", "easy", "H/F e SA", ("Chauffeur-livreur H/F", "Chronopost SA", "Lyon", AD), ("Chauffeur livreur", "Chronopost", "Lyon", JO))
D(LOG, "it", "hard", "azienda abbreviata e sede provincia", ("Autista patente C+E", "Number 1 Logistics Group", "Verona", AD), ("Autista patente C+E", "Number 1 Logistics", "Provincia di Verona", JO))
D(LOG, "es", "hard", "mozo/a", ("Mozo de almacen", "Seur", "Zaragoza", AD), ("Mozo/a de almacen", "SEUR S.A.", "Zaragoza", JO))
D(LOG, "it", "hard", "Part time aggiunto", ("Operatore logistico", "GXO Logistics Italia Srl", "Piacenza", AD), ("Operatore logistico part time", "GXO Logistics", "Piacenza", JO))

# --- amministrazione
D(ADM, "it", "hard", "S.r.l. e F/M", ("Impiegata amministrativa", "Studio Rossi e Associati Srl", "Padova", AD), ("Impiegata amministrativa (F/M)", "Studio Rossi e Associati", "Padova", JO))
D(ADM, "it", "easy", "identici", ("Addetto contabilita'", "Edilcasa S.p.A.", "Brescia", AD), ("Addetto contabilita'", "Edilcasa S.p.A.", "Brescia", JO))
D(ADM, "en", "hard", "Ltd e specificazione", ("Accounts Payable Clerk", "Barclays Ltd", "Glasgow", AD), ("Accounts Payable Clerk", "Barclays", "Glasgow, Scotland", JO))
D(ADM, "de", "hard", "m/w/d", ("Buchhalter (m/w/d)", "Bosch GmbH", "Stuttgart", AD), ("Buchhalter", "Robert Bosch", "Stuttgart", JO))
D(ADM, "es", "hard", "Auxiliar con o/a", ("Auxiliar administrativo/a", "Mapfre S.A.", "Madrid", AD), ("Auxiliar administrativo", "Mapfre", "Madrid", JO))
D(ADM, "fr", "easy", "Assistant e H/F", ("Assistant administratif H/F", "Randstad France", "Toulouse", AD), ("Assistant administratif", "Randstad", "Toulouse", JO))
D(ADM, "en", "hard", "Office Manager con luogo in titolo", ("Office Manager", "Wise Plc", "London", AD), ("Office Manager - Central London", "Wise Plc", "London", JO))
D(ADM, "it", "hard", "segretaria di direzione", ("Segretaria di direzione", "Banca Intesa Sanpaolo S.p.A.", "Torino", AD), ("Segretaria di direzione (M/F)", "Intesa Sanpaolo", "Torino", JO))

# --- vendite
D(VEN, "it", "hard", "azienda con Italia + Srl", ("Addetto vendite", "Zara Italia Srl", "Milano", AD), ("Addetto vendite", "Zara", "Milano", JO))
D(VEN, "en", "easy", "Ltd", ("Sales Representative", "Salesforce Ltd", "Dublin", AD), ("Sales Representative", "Salesforce", "Dublin", JO))
D(VEN, "en", "hard", "Account Manager + (EMEA)", ("Account Manager", "HubSpot Inc", "Dublin", CO), ("Account Manager (EMEA)", "HubSpot", "Dublin", AD))
D(VEN, "de", "hard", "m/w/d + Aussendienst", ("Vertriebsmitarbeiter (m/w/d)", "Siemens AG", "Muenchen", AD), ("Vertriebsmitarbeiter", "Siemens", "Muenchen", JO))
D(VEN, "fr", "hard", "H/F e commerciale", ("Commercial B2B H/F", "Orange SA", "Nantes", AD), ("Commercial B2B", "Orange", "Nantes", JO))
D(VEN, "es", "hard", "Dependiente/a", ("Dependiente/a de tienda", "Inditex S.A.", "A Coruna", AD), ("Dependiente de tienda", "Inditex", "A Coruna", JO))
D(VEN, "it", "hard", "Store Manager + sigla", ("Store Manager", "Leroy Merlin Italia S.r.l.", "Verona", AD), ("Store Manager (M/F)", "Leroy Merlin", "Verona", JO))
D(VEN, "it", "hard", "Agente di commercio con zona", ("Agente di commercio", "Fastweb S.p.A.", "Napoli", AD), ("Agente di commercio - Campania", "Fastweb", "Napoli", JO))

# --- istruzione
D(IST, "it", "hard", "Insegnante: F/M", ("Insegnante di inglese", "Wall Street English Italia Srl", "Roma", AD), ("Insegnante di inglese (F/M)", "Wall Street English", "Roma", JO))
D(IST, "en", "easy", "Teacher", ("Teacher of Mathematics", "Harris Academy Ltd", "London", AD), ("Teacher of Mathematics", "Harris Academy", "London", JO))
D(IST, "de", "hard", "m/w/d", ("Lehrer (m/w/d) Mathematik", "Phorms Education SE", "Berlin", AD), ("Lehrer Mathematik", "Phorms Education", "Berlin", JO))
D(IST, "es", "hard", "Profesor/a", ("Profesor/a de secundaria", "Colegio Montessori S.L.", "Valencia", AD), ("Profesor de secundaria", "Colegio Montessori", "Valencia", JO))
D(IST, "fr", "hard", "H/F", ("Enseignant d'anglais H/F", "Wall Street English", "Lille", AD), ("Enseignant d'anglais", "Wall Street English France", "Lille", JO))
D(IST, "it", "hard", "Educatrice asilo nido", ("Educatrice asilo nido", "Cooperativa Sociale Il Girasole", "Reggio Emilia", AD), ("Educatrice asilo nido (F/M)", "Il Girasole Cooperativa Sociale", "Reggio Emilia", JO))
D(IST, "it", "hard", "Tutor + istituto", ("Tutor didattico", "Universita' Bocconi", "Milano", AD), ("Tutor didattico", "Universita Bocconi", "Milano", JO))
D(IST, "en", "hard", "Teaching Assistant - Level 3 non e' un livello", ("Teaching Assistant", "Oasis Academy Trust", "Birmingham", AD), ("Teaching Assistant - Primary", "Oasis Academy Trust", "Birmingham", JO))

# =============================================================== NON DUPLICATI ===
# --- livelli e gradi (stesso titolo, stessa azienda e citta')
N(SEC, "en", "hard", "Junior vs Senior", ("Junior SOC Analyst", "Acme Security", "Milano", AD), ("Senior SOC Analyst", "Acme Security", "Milano", AD))
N(SEC, "en", "hard", "L1 vs L2", ("SOC Analyst L1", "Acme Security", "Milano", AD), ("SOC Analyst L2", "Acme Security", "Milano", AD))
N(SEC, "en", "hard", "Specialist vs Expert", ("Security Specialist", "Atlas Cyber", "Roma", AD), ("Security Expert", "Atlas Cyber", "Roma", AD))
N(SEC, "en", "hard", "Analyst vs Senior Analyst", ("Threat Intelligence Analyst", "Mandiant", "London", AD), ("Senior Threat Intelligence Analyst", "Mandiant", "London", AD))
N(SEC, "it", "hard", "Pentester Junior vs Lead", ("Penetration Tester Junior", "Cyberia", "Roma", AD), ("Penetration Tester Lead", "Cyberia", "Roma", AD))
N(SEC, "en", "hard", "Tier 1 vs Tier 2", ("SOC Analyst Tier 1", "Sentinel Corp", "Dublin", AD), ("SOC Analyst Tier 2", "Sentinel Corp", "Dublin", AD))
N(SEC, "en", "hard", "Engineer vs Manager", ("Security Engineer", "Okta Inc", "San Francisco", AD), ("Security Engineering Manager", "Okta Inc", "San Francisco", AD))
N(DEV, "en", "hard", "Junior vs Senior", ("Junior Backend Developer", "Spotify AB", "Stockholm", AD), ("Senior Backend Developer", "Spotify AB", "Stockholm", AD))
N(DEV, "en", "hard", "Developer vs Lead Developer", ("Java Developer", "Capgemini", "London", AD), ("Lead Java Developer", "Capgemini", "London", AD))
N(DEV, "de", "hard", "Junior vs Senior", ("Junior Softwareentwickler (m/w/d)", "SAP SE", "Walldorf", AD), ("Senior Softwareentwickler (m/w/d)", "SAP SE", "Walldorf", AD))
N(DEV, "it", "hard", "Trainee vs Senior", ("Sviluppatore Python Senior", "Var Group", "Empoli", AD), ("Sviluppatore Python Trainee", "Var Group", "Empoli", AD))
N(SAN, "it", "hard", "Infermiere vs Coordinatore (livello)", ("Infermiere", "Humanitas", "Rozzano", AD), ("Infermiere Coordinatore", "Humanitas", "Rozzano", AD))
N(SAN, "en", "hard", "Nurse vs Senior Nurse", ("Staff Nurse", "NHS Foundation Trust", "Leeds", AD), ("Senior Staff Nurse", "NHS Foundation Trust", "Leeds", AD))
N(RIS, "en", "hard", "Chef vs Head Chef", ("Chef de Partie", "Hilton", "London", AD), ("Head Chef", "Hilton", "London", AD))
N(RIS, "it", "hard", "Cuoco vs Capo cuoco (sous)", ("Cuoco", "Hotel Excelsior", "Venezia", AD), ("Sous Chef", "Hotel Excelsior", "Venezia", AD))
N(LOG, "en", "hard", "Operative vs Team Leader", ("Warehouse Operative", "DHL Supply Chain", "Manchester", AD), ("Warehouse Team Leader", "DHL Supply Chain", "Manchester", AD))
N(ADM, "en", "hard", "Clerk vs Senior Clerk", ("Accounts Payable Clerk", "Barclays", "Glasgow", AD), ("Senior Accounts Payable Clerk", "Barclays", "Glasgow", AD))
N(VEN, "en", "hard", "Rep vs Senior Rep", ("Sales Representative", "Salesforce", "Dublin", AD), ("Senior Sales Representative", "Salesforce", "Dublin", AD))
N(VEN, "it", "hard", "Addetto vs Responsabile", ("Addetto vendite", "Zara Italia", "Milano", AD), ("Responsabile vendite", "Zara Italia", "Milano", AD))
N(IST, "en", "hard", "Teacher vs Head of Department", ("Teacher of Mathematics", "Harris Academy", "London", AD), ("Head of Mathematics", "Harris Academy", "London", AD))
N(ADM, "it", "hard", "Junior contro Senior contabile", ("Contabile Junior", "Edilcasa", "Brescia", AD), ("Contabile Senior", "Edilcasa", "Brescia", AD))
N(SEC, "en", "hard", "Associate vs Principal", ("Associate Security Consultant", "Deloitte", "London", AD), ("Principal Security Consultant", "Deloitte", "London", AD))

# --- stessa azienda, ruoli diversi ma titoli molto simili
N(DEV, "en", "hard", "Backend vs Frontend", ("Software Engineer Backend", "Zalando SE", "Berlin", AD), ("Software Engineer Frontend", "Zalando SE", "Berlin", AD))
N(DEV, "en", "hard", "Java vs JavaScript", ("Java Developer", "Capgemini", "Lyon", AD), ("JavaScript Developer", "Capgemini", "Lyon", AD))
N(DEV, "en", "hard", "Data Engineer vs Data Scientist", ("Data Engineer", "Spotify", "Stockholm", AD), ("Data Scientist", "Spotify", "Stockholm", AD))
N(DEV, "en", "hard", "iOS vs Android", ("iOS Developer", "Glovo", "Barcelona", AD), ("Android Developer", "Glovo", "Barcelona", AD))
N(DEV, "it", "hard", "Frontend vs Backend", ("Sviluppatore Frontend", "Engineering", "Roma", AD), ("Sviluppatore Backend", "Engineering", "Roma", AD))
N(DEV, "en", "hard", "QA vs DevOps Engineer", ("QA Engineer", "Datadog", "Paris", AD), ("DevOps Engineer", "Datadog", "Paris", AD))
N(SEC, "en", "hard", "Network Security vs Network Engineer", ("Network Security Engineer", "Cisco Systems", "Milano", AD), ("Network Engineer", "Cisco Systems", "Milano", AD))
N(SEC, "en", "hard", "Application Security vs Cloud Security", ("Application Security Engineer", "Okta", "Dublin", AD), ("Cloud Security Engineer", "Okta", "Dublin", AD))
N(SEC, "it", "hard", "Analista SOC vs Analista GRC", ("Analista SOC", "Reply", "Torino", AD), ("Analista GRC", "Reply", "Torino", AD))
N(SEC, "it", "hard", "Penetration Tester vs Vulnerability Analyst", ("Penetration Tester", "Leonardo", "Roma", AD), ("Vulnerability Analyst", "Leonardo", "Roma", AD))
N(SEC, "de", "hard", "Pentester vs Security Architect", ("Pentester (m/w/d)", "Secunet AG", "Essen", AD), ("Security Architect (m/w/d)", "Secunet AG", "Essen", AD))
N(SAN, "it", "hard", "Infermiere sala operatoria vs pronto soccorso", ("Infermiere di sala operatoria", "Humanitas", "Rozzano", AD), ("Infermiere di pronto soccorso", "Humanitas", "Rozzano", AD))
N(SAN, "it", "hard", "Fisioterapista vs Logopedista", ("Fisioterapista", "Villa Maria", "Torino", AD), ("Logopedista", "Villa Maria", "Torino", AD))
N(SAN, "de", "hard", "Intensiv vs Ambulant", ("Pflegefachkraft Intensivstation (m/w/d)", "Charite", "Berlin", AD), ("Pflegefachkraft Ambulante Pflege (m/w/d)", "Charite", "Berlin", AD))
N(SAN, "en", "hard", "Staff Nurse vs Healthcare Assistant", ("Staff Nurse", "NHS Foundation Trust", "Leeds", AD), ("Healthcare Assistant", "NHS Foundation Trust", "Leeds", AD))
N(SAN, "es", "hard", "Enfermero vs Auxiliar", ("Enfermero/a de urgencias", "Quironsalud", "Madrid", AD), ("Enfermero/a de quirofano", "Quironsalud", "Madrid", AD))
N(SAN, "it", "hard", "Medico vs Medico radiologo", ("Medico di Pronto Soccorso", "Policlinico Gemelli", "Roma", AD), ("Medico Radiologo", "Policlinico Gemelli", "Roma", AD))
N(RIS, "it", "hard", "Cameriere sala vs bar", ("Cameriere di sala", "Hotel Excelsior", "Venezia", AD), ("Cameriere di bar", "Hotel Excelsior", "Venezia", AD))
N(RIS, "en", "hard", "Barista vs Bartender", ("Barista", "Starbucks", "Seattle", AD), ("Bartender", "Starbucks", "Seattle", AD))
N(RIS, "fr", "hard", "Serveur vs Cuisinier", ("Serveur / Serveuse", "Accor", "Paris", AD), ("Cuisinier / Cuisiniere", "Accor", "Paris", AD))
N(RIS, "de", "hard", "Koch vs Kuechenhilfe", ("Koch (m/w/d)", "Steigenberger", "Hamburg", AD), ("Kuechenhilfe (m/w/d)", "Steigenberger", "Hamburg", AD))
N(RIS, "es", "hard", "Camarero vs Cocinero", ("Camarero/a de sala", "Tragaluz", "Barcelona", AD), ("Cocinero/a", "Tragaluz", "Barcelona", AD))
N(LOG, "it", "hard", "Magazziniere notturno vs diurno", ("Magazziniere turno notte", "Logista", "Milano", AD), ("Magazziniere turno giorno", "Logista", "Milano", AD))
N(LOG, "it", "hard", "Magazziniere vs Autista", ("Magazziniere carrellista", "BRT", "Bologna", AD), ("Autista corriere", "BRT", "Bologna", AD))
N(LOG, "en", "hard", "Picker vs Packer", ("Warehouse Picker", "Amazon", "Manchester", AD), ("Warehouse Packer", "Amazon", "Manchester", AD))
N(LOG, "de", "hard", "Lagerist vs Staplerfahrer", ("Lagerist (m/w/d)", "Rhenus", "Duisburg", AD), ("Staplerfahrer (m/w/d)", "Rhenus", "Duisburg", AD))
N(LOG, "fr", "hard", "Chauffeur livreur vs Preparateur", ("Chauffeur-livreur H/F", "Chronopost", "Lyon", AD), ("Preparateur de commandes H/F", "Chronopost", "Lyon", AD))
N(ADM, "it", "hard", "Contabilita' clienti vs fornitori", ("Addetto contabilita' clienti", "Edilcasa", "Brescia", AD), ("Addetto contabilita' fornitori", "Edilcasa", "Brescia", AD))
N(ADM, "en", "hard", "AP vs AR Clerk", ("Accounts Payable Clerk", "Barclays", "Glasgow", AD), ("Accounts Receivable Clerk", "Barclays", "Glasgow", AD))
N(ADM, "de", "hard", "Buchhalter vs Bilanzbuchhalter", ("Buchhalter (m/w/d)", "Bosch", "Stuttgart", AD), ("Bilanzbuchhalter (m/w/d)", "Bosch", "Stuttgart", AD))
N(ADM, "es", "hard", "Administrativo vs Recepcionista", ("Auxiliar administrativo/a", "Mapfre", "Madrid", AD), ("Recepcionista", "Mapfre", "Madrid", AD))
N(ADM, "it", "hard", "Segretaria vs HR", ("Segretaria di direzione", "Intesa Sanpaolo", "Torino", AD), ("Responsabile risorse umane", "Intesa Sanpaolo", "Torino", AD))
N(VEN, "it", "hard", "Abbigliamento vs Calzature", ("Addetto vendite abbigliamento", "Zara Italia", "Milano", AD), ("Addetto vendite calzature", "Zara Italia", "Milano", AD))
N(VEN, "en", "hard", "Account Manager vs Account Executive", ("Account Manager", "HubSpot", "Dublin", AD), ("Account Executive", "HubSpot", "Dublin", AD))
N(VEN, "de", "hard", "Innendienst vs Aussendienst", ("Vertriebsmitarbeiter Innendienst (m/w/d)", "Siemens", "Muenchen", AD), ("Vertriebsmitarbeiter Aussendienst (m/w/d)", "Siemens", "Muenchen", AD))
N(VEN, "fr", "hard", "Commercial vs Charge de recrutement", ("Commercial B2B H/F", "Orange", "Nantes", AD), ("Commercial B2C H/F", "Orange", "Nantes", AD))
N(VEN, "es", "hard", "Dependiente vs Encargado", ("Dependiente/a de tienda", "Inditex", "A Coruna", AD), ("Encargado/a de tienda", "Inditex", "A Coruna", AD))
N(VEN, "it", "hard", "Agente di commercio vs Telemarketing", ("Agente di commercio", "Fastweb", "Napoli", AD), ("Addetto telemarketing", "Fastweb", "Napoli", AD))
N(IST, "it", "hard", "Matematica vs inglese", ("Insegnante di matematica", "Istituto Maria Ausiliatrice", "Roma", AD), ("Insegnante di inglese", "Istituto Maria Ausiliatrice", "Roma", AD))
N(IST, "it", "hard", "Infanzia vs primaria", ("Maestra scuola infanzia", "Cooperativa Il Girasole", "Reggio Emilia", AD), ("Maestra scuola primaria", "Cooperativa Il Girasole", "Reggio Emilia", AD))
N(IST, "en", "hard", "Maths vs English teacher", ("Teacher of Mathematics", "Harris Academy", "London", AD), ("Teacher of English", "Harris Academy", "London", AD))
N(IST, "de", "hard", "Mathematik vs Deutsch", ("Lehrer (m/w/d) Mathematik", "Phorms Education", "Berlin", AD), ("Lehrer (m/w/d) Deutsch", "Phorms Education", "Berlin", AD))
N(IST, "es", "hard", "Profesor ingles vs mates", ("Profesor/a de ingles", "Colegio Montessori", "Valencia", AD), ("Profesor/a de matematicas", "Colegio Montessori", "Valencia", AD))
N(IST, "fr", "hard", "anglais vs maths", ("Enseignant d'anglais H/F", "Wall Street English", "Lille", AD), ("Enseignant de mathematiques H/F", "Wall Street English", "Lille", AD))

# --- stesso titolo, citta' diverse (posizioni diverse)
N(SEC, "it", "hard", "citta' diverse", ("SOC Analyst", "Acme Security", "Milano", AD), ("SOC Analyst", "Acme Security", "Roma", AD))
N(SAN, "it", "hard", "citta' diverse", ("Infermiere", "Gruppo San Donato", "Milano", AD), ("Infermiere", "Gruppo San Donato", "Bergamo", AD))
N(RIS, "it", "hard", "citta' diverse vicine", ("Cameriere di sala", "Hotel Excelsior", "Venezia", AD), ("Cameriere di sala", "Hotel Excelsior", "Mestre", AD))
N(LOG, "it", "hard", "citta' diverse", ("Magazziniere carrellista", "Logista Italia", "Milano", AD), ("Magazziniere carrellista", "Logista Italia", "Napoli", AD))
N(LOG, "en", "hard", "citta' diverse", ("Warehouse Operative", "DHL Supply Chain", "Manchester", AD), ("Warehouse Operative", "DHL Supply Chain", "Leeds", AD))
N(VEN, "it", "hard", "negozi in citta' diverse", ("Addetto vendite", "Zara Italia", "Milano", AD), ("Addetto vendite", "Zara Italia", "Torino", AD))
N(VEN, "de", "hard", "citta' diverse", ("Vertriebsmitarbeiter (m/w/d)", "Siemens", "Muenchen", AD), ("Vertriebsmitarbeiter (m/w/d)", "Siemens", "Berlin", AD))
N(IST, "es", "hard", "citta' diverse", ("Profesor/a de secundaria", "Colegio Montessori", "Valencia", AD), ("Profesor/a de secundaria", "Colegio Montessori", "Sevilla", AD))
N(DEV, "fr", "hard", "citta' diverse", ("Developpeur Java H/F", "Capgemini", "Lyon", AD), ("Developpeur Java H/F", "Capgemini", "Paris", AD))
N(ADM, "it", "hard", "citta' diverse stessa regione", ("Impiegata amministrativa", "Studio Rossi e Associati", "Padova", AD), ("Impiegata amministrativa", "Studio Rossi e Associati", "Verona", AD))
N(DEV, "en", "hard", "paesi diversi stesso nome citta'", ("Software Engineer", "Google", "Cambridge, UK", AD), ("Software Engineer", "Google", "Boston", AD))

# --- stesso ruolo, aziende diverse con nome simile
N(SEC, "it", "hard", "nomi simili", ("SOC Analyst", "Alpha Security Srl", "Milano", AD), ("SOC Analyst", "Alpha Securities Srl", "Milano", AD))
N(SAN, "it", "hard", "farmacie diverse", ("Farmacista collaboratore", "Farmacia Rossi", "Palermo", AD), ("Farmacista collaboratore", "Farmacia Russo", "Palermo", AD))
N(RIS, "it", "hard", "ristoranti con nome simile", ("Cameriere di sala", "Ristorante Da Luigi", "Napoli", AD), ("Cameriere di sala", "Ristorante Da Luca", "Napoli", AD))
N(LOG, "it", "hard", "corrieri con nome simile", ("Autista corriere", "Logistica Nord Srl", "Verona", AD), ("Autista corriere", "Logistica Sud Srl", "Verona", AD))
N(VEN, "it", "hard", "catene diverse", ("Addetto vendite", "Conad Centro Nord", "Bologna", AD), ("Addetto vendite", "Conad Sicilia", "Bologna", AD))
N(ADM, "it", "hard", "studi con nome simile", ("Impiegata amministrativa", "Studio Bianchi Srl", "Padova", AD), ("Impiegata amministrativa", "Studio Bianchini Srl", "Padova", AD))
N(IST, "it", "hard", "cooperative con nome simile", ("Educatrice asilo nido", "Cooperativa Sociale Il Girasole", "Reggio Emilia", AD), ("Educatrice asilo nido", "Cooperativa Sociale Il Gabbiano", "Reggio Emilia", AD))
N(DEV, "en", "hard", "azienda con nome simile", ("Backend Developer", "Pixel Labs Ltd", "Bristol", AD), ("Backend Developer", "Pixel Lab Studios Ltd", "Bristol", AD))
N(DEV, "de", "hard", "aziende diverse", ("Softwareentwickler (m/w/d)", "Deutsche Bank AG", "Frankfurt", AD), ("Softwareentwickler (m/w/d)", "Deutsche Bahn AG", "Frankfurt", AD))
N(ADM, "en", "hard", "banche diverse", ("Accounts Payable Clerk", "Barclays", "Glasgow", AD), ("Accounts Payable Clerk", "Barclay Partners", "Glasgow", AD))
N(SEC, "fr", "hard", "societa diverse", ("Ingenieur Cybersecurite H/F", "Thales SA", "Paris", AD), ("Ingenieur Cybersecurite H/F", "Talan SA", "Paris", AD))
N(VEN, "es", "hard", "cataloghi diversi", ("Dependiente/a de tienda", "Zara Espana", "Madrid", AD), ("Dependiente/a de tienda", "Sara Moda Espana", "Madrid", AD))

# --- aziende e ruoli completamente diversi (facili)
N(SEC, "it", "easy", "tutto diverso", ("SOC Analyst", "Acme Security", "Milano", AD), ("Cuoco", "Hotel Excelsior", "Venezia", AD))
N(DEV, "en", "easy", "tutto diverso", ("Java Developer", "Capgemini", "London", AD), ("Warehouse Operative", "DHL", "London", AD))
N(SAN, "it", "easy", "stessa citta' ma tutto diverso", ("Infermiere", "Humanitas", "Milano", AD), ("Sviluppatore Python", "Engineering", "Milano", AD))
N(LOG, "de", "easy", "stessa citta' ma tutto diverso", ("Lagerist (m/w/d)", "Rhenus", "Berlin", AD), ("Lehrer (m/w/d)", "Phorms Education", "Berlin", AD))
N(VEN, "es", "easy", "stessa citta' ma tutto diverso", ("Dependiente/a de tienda", "Inditex", "Madrid", AD), ("Enfermero/a", "Quironsalud", "Madrid", AD))
N(ADM, "fr", "easy", "stessa citta' ma tutto diverso", ("Assistant administratif H/F", "Randstad", "Paris", AD), ("Serveur H/F", "Accor", "Paris", AD))
N(IST, "it", "easy", "stessa azienda, ruoli lontani", ("Insegnante di inglese", "Wall Street English", "Roma", AD), ("Addetto reception", "Wall Street English", "Roma", AD))
N(RIS, "en", "easy", "stessa azienda, ruoli lontani", ("Chef de Partie", "Hilton", "London", AD), ("IT Support Technician", "Hilton", "London", AD))

# --- stesso lavoro/azienda ma sedi generiche opposte: non dup se la citta' e' due citta' diverse
N(LOG, "it", "hard", "una citta' contro un'altra, entrambe note", ("Operatore logistico", "GXO Logistics", "Piacenza", AD), ("Operatore logistico", "GXO Logistics", "Parma", AD))
N(SEC, "en", "hard", "Analyst vs Analyst Intern: tirocinio diverso dal ruolo", ("Security Analyst", "BlueShield", "Manchester", AD), ("Security Analyst Intern", "BlueShield", "Manchester", AD))
N(DEV, "en", "hard", "Engineer vs Engineering Manager", ("Software Engineer", "Mozilla", "London", AD), ("Software Engineering Manager", "Mozilla", "London", AD))
N(ADM, "en", "hard", "Office Manager vs Office Assistant", ("Office Manager", "Wise", "London", AD), ("Office Assistant", "Wise", "London", AD))
N(SAN, "en", "hard", "Nurse vs Nurse Manager", ("Staff Nurse", "NHS Foundation Trust", "Leeds", AD), ("Nurse Manager", "NHS Foundation Trust", "Leeds", AD))
N(VEN, "en", "hard", "Sales Rep vs Sales Manager", ("Sales Representative", "HubSpot", "Dublin", AD), ("Sales Manager", "HubSpot", "Dublin", AD))

def enrich(cases):
    """Completa le righe con le altre colonne di una riga di DB."""
    for c in cases:
        for side in ("a", "b"):
            r = c[side]
            r.setdefault("url", f"https://example.org/{c['id']}/{side}")
            r["description"] = f"Descrizione generica dell'offerta ({c['id']}{side})."
            r["full_text"] = "" if side == "b" else f"Testo completo della posizione {c['id']}."
            r["status"] = "new"
            r["score"] = 40 if side == "a" else 35
            r["posted_at"] = None
            r["remote"] = 0


enrich(CASES)


if __name__ == "__main__":
    out = Path(__file__).with_name("dedupe_cases.json")
    out.write_text(json.dumps(CASES, ensure_ascii=False, indent=1))
    d = sum(c["label"] == "dup" for c in CASES)
    print(f"{len(CASES)} casi: {d} duplicati, {len(CASES) - d} non duplicati -> {out}")
