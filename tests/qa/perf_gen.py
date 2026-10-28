"""Generatore deterministico (seed fisso) di annunci per le prove di prestazione dei duplicati."""
from __future__ import annotations

import random

CITIES = ["Milano", "Roma", "Torino", "Napoli", "Bologna", "Firenze", "Palermo", "Genova", "Verona", "Padova", "Bari",
          "Catania", "Venezia", "Brescia", "Parma", "Modena", "Trento", "Perugia", "Cagliari", "Trieste", "Bergamo",
          "Reggio Emilia", "Livorno", "Pisa", "Ancona", "Lecce", "Monza", "Udine", "Vicenza", "Salerno"]
ROLES = {
    "sec": ["SOC Analyst", "Penetration Tester", "Security Engineer", "Analista Sicurezza Informatica", "Incident Response Specialist",
            "Vulnerability Analyst", "Sistemista Linux", "Network Administrator", "Cloud Security Engineer", "GRC Analyst"],
    "dev": ["Sviluppatore Java", "Sviluppatore Python", "Backend Developer", "Frontend Developer", "Full Stack Developer",
            "DevOps Engineer", "Data Engineer", "QA Engineer", "Sviluppatore .NET", "Mobile Developer iOS"],
    "san": ["Infermiere", "Fisioterapista", "Operatore Socio Sanitario", "Medico di Pronto Soccorso", "Tecnico di Radiologia",
            "Farmacista collaboratore", "Ostetrica", "Educatore professionale", "Logopedista", "Biologo"],
    "ris": ["Cameriere di sala", "Cuoco", "Barista", "Aiuto cuoco", "Pizzaiolo", "Addetto al banco", "Lavapiatti", "Sommelier",
            "Responsabile di sala", "Commis di cucina"],
    "log": ["Magazziniere carrellista", "Addetto al magazzino", "Autista patente C", "Operatore logistico", "Addetto picking",
            "Corriere", "Responsabile magazzino", "Impiegato logistica", "Addetto spedizioni", "Mulettista"],
    "adm": ["Impiegata amministrativa", "Addetto contabilita'", "Segretaria di direzione", "Addetto paghe", "Receptionist",
            "Assistente HR", "Controller", "Addetto fatturazione", "Responsabile acquisti", "Back office"],
    "ven": ["Addetto vendite", "Agente di commercio", "Account Manager", "Store Manager", "Commesso", "Venditore B2B",
            "Responsabile commerciale", "Addetto telemarketing", "Key Account", "Promoter"],
    "ist": ["Insegnante di inglese", "Insegnante di matematica", "Educatrice asilo nido", "Tutor didattico", "Formatore",
            "Maestra scuola primaria", "Docente di sostegno", "Assistente di laboratorio", "Insegnante di musica", "Istruttore"],
}
LEVELS = ["", "", "", " Junior", " Senior", " Part Time", " Full Time", " Turno notte", " Settore nord", " Settore sud"]
NAME_A = ["Alfa", "Beta", "Gamma", "Delta", "Omega", "Nova", "Prisma", "Orizzonte", "Vega", "Sirio", "Titano", "Aurora", "Elios", "Kappa",
          "Linea", "Mediterranea", "Adriatica", "Ligure", "Padana", "Tirrena", "Etrusca", "Sabauda", "Lombarda", "Veneta", "Sicula"]
NAME_B = ["Servizi", "Logistica", "Sanita'", "Software", "Costruzioni", "Consulting", "Ristorazione", "Formazione", "Energia", "Trasporti",
          "Digital", "Sistemi", "Hotel", "Retail", "Cooperativa"]
SUFFIX = ["", " S.p.A.", " S.r.l.", " Srl", " SpA", " GmbH", " Ltd", " Group"]


def make_company(rng: random.Random, i: int) -> str:
    return f"{rng.choice(NAME_A)} {rng.choice(NAME_B)} {i // 40 + 1}" if i % 3 else f"{rng.choice(NAME_A)} {rng.choice(NAME_B)}"


def _variant(rng: random.Random, r: dict) -> dict:
    """Come lo stesso annuncio appare su un'altra fonte: forma societaria, genere, maiuscole, sede, parole in piu'."""
    v = dict(r)
    v["source"] = rng.choice(["jooble", "adzuna", "greenhouse"]) if r["source"] == "adzuna" else "adzuna"
    comp = r["company"]
    k = rng.random()
    if k < 0.35:
        comp = comp + rng.choice([" S.p.A.", " S.r.l.", " Srl", " GmbH", " Ltd"])
    elif k < 0.5:
        comp = comp.upper()
    v["company"] = comp
    t = r["title"]
    k = rng.random()
    if k < 0.3:
        t += rng.choice([" (m/f)", " (M/F)", " (m/w/d)"])
    elif k < 0.45:
        t = t.upper()
    elif k < 0.55:
        t += " - " + rng.choice(["urgente", "Full Time"])
    v["title"] = t
    city = r["location"]
    k = rng.random()
    if k < 0.3:
        v["location"] = f"{city}, Provincia di {city}"
    elif k < 0.45:
        v["location"] = "Italia"
    elif k < 0.6:
        v["location"] = f"{city}, Lombardia"
    v["url"] = r["url"] + "-v"
    v["salary"] = rng.choice(["", "", "28.000 - 32.000 EUR"])
    v["full_text"] = ""
    return v


def generate(n: int = 5000, dup_rate: float = 0.10, seed: int = 20260101):
    """(righe, coppie_piantate): righe = lista di dict per la tabella jobs; coppie = lista di (uid_a, uid_b)."""
    rng = random.Random(seed)
    n_dup = int(n * dup_rate)
    n_base = n - n_dup
    companies = [make_company(rng, i) + rng.choice(SUFFIX[:1]) for i in range(max(60, n_base // 7))]
    seen, base = set(), []
    while len(base) < n_base:
        sector = rng.choice(list(ROLES))
        title = rng.choice(ROLES[sector]) + rng.choice(LEVELS)
        comp = rng.choice(companies)
        city = rng.choice(CITIES)
        key = (comp, title, city)
        if key in seen:
            continue
        seen.add(key)
        i = len(base)
        base.append({"uid": f"b{i:07d}".ljust(16, "0"), "source": rng.choice(["adzuna", "adzuna", "greenhouse"]), "title": title,
                     "company": comp, "location": city, "url": f"https://example.org/p/{i}", "description": f"Offerta {i}",
                     "posted_at": None, "remote": 0, "score": rng.randint(15, 80), "status": "new", "salary": "", "full_text": ""})
    rows, pairs = list(base), []
    for j, idx in enumerate(rng.sample(range(n_base), n_dup)):
        v = _variant(rng, base[idx])
        v["uid"] = f"v{j:07d}".ljust(16, "0")
        rows.append(v)
        pairs.append((base[idx]["uid"], v["uid"]))
    rng.shuffle(rows)
    return rows, pairs


def load_into(db, rows) -> None:
    cols = ["source", "title", "company", "location", "url", "description", "posted_at", "remote", "score", "status", "salary", "full_text"]
    db.conn.executemany(
        f"INSERT INTO jobs (uid,{','.join(cols)},first_seen) VALUES (?,{','.join('?' * len(cols))},?)",
        [[r["uid"], *[r[c] for c in cols], "2026-01-01T00:00:00+00:00"] for r in rows])
    db.conn.commit()
    db.backfill_meta()


def run_once(db_path, n, cfg, seed=20260101):
    """Genera n annunci, li carica e misura find_duplicates. Ritorna (secondi, richiamo, coppie_totali, piantate)."""
    import time

    from jobshunter import dedupe
    from jobshunter.db import DB

    rows, planted = generate(n, seed=seed)
    db = DB(db_path)
    load_into(db, rows)
    t0 = time.perf_counter()
    dedupe.find_duplicates(db, cfg)
    dt = time.perf_counter() - t0
    found = {frozenset((r["uid_a"], r["uid_b"])) for r in db.conn.execute("SELECT uid_a, uid_b FROM dup_pairs")}
    hit = sum(1 for a, b in planted if frozenset((a, b)) in found)
    total = len(found)
    db.conn.close()
    return dt, (hit / len(planted) if planted else 1.0), total, len(planted)
