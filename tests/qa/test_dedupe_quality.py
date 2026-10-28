"""Qualita' dei duplicati: precisione e richiamo sul set etichettato del TESTER (tests/data/dedupe_cases.json).

Due harness: (1) dedupe.similarity con la soglia di default; (2) dedupe.find_duplicates su un DB temporaneo.
I test di struttura passano gia' oggi; quelli sulle soglie della spec (precisione >= 0.95, richiamo >= 0.85)
sono `phase2` finche' BUILDER non consegna il checkpoint P2c.
"""
import pytest

from qa import dedupe_eval as ev

MIN_PREC, MIN_REC = 0.95, 0.85


def test_dataset_ben_formato():
    cases = ev.load_cases()
    dup = [c for c in cases if c["label"] == "dup"]
    non = [c for c in cases if c["label"] == "nodup"]
    assert len(cases) >= 160 and len(dup) >= 70 and len(non) >= 90
    assert len({c["sector"] for c in cases}) >= 8
    assert len({c["lang"] for c in cases}) >= 4
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        for side in ("a", "b"):
            for k in ev.DB_COLS:
                assert k in c[side], (c["id"], k)


def _report(m, name):
    fp = [f"{c['id']} {c['a']['title']}|{c['a']['company']}|{c['a']['location']} <> {c['b']['title']}|{c['b']['company']}|{c['b']['location']} ({c['note']})" for c in m["fp"]]
    fn = [f"{c['id']} {c['a']['title']}|{c['a']['company']}|{c['a']['location']} <> {c['b']['title']}|{c['b']['company']}|{c['b']['location']} ({c['note']})" for c in m["fn"]]
    return (f"{name}: precisione {m['precision']:.3f}, richiamo {m['recall']:.3f}\n"
            f"FALSI DUPLICATI ({len(fp)}):\n  " + "\n  ".join(fp) + f"\nDUPLICATI MANCATI ({len(fn)}):\n  " + "\n  ".join(fn))


@pytest.mark.phase2
def test_similarity_precisione_e_richiamo_sul_set_etichettato():
    cases = ev.load_cases()
    m = ev.metrics(cases, ev.predict_similarity(cases, 75))
    assert m["precision"] >= MIN_PREC and m["recall"] >= MIN_REC, _report(m, "similarity")


@pytest.mark.phase2
def test_find_duplicates_precisione_e_richiamo_sul_set_etichettato(tmp_path, cfg):
    cases = ev.load_cases()
    m = ev.metrics(cases, ev.predict_find_duplicates(cases, cfg, tmp_path))
    assert m["precision"] >= MIN_PREC and m["recall"] >= MIN_REC, _report(m, "find_duplicates")


def test_find_duplicates_e_similarity_concordano(tmp_path, cfg):
    """Il blocking non deve cambiare l'esito: stessa decisione di similarity sulla soglia di default."""
    cases = ev.load_cases()
    a = ev.predict_similarity(cases, cfg.get("dedupe", {}).get("min_percent", 75))
    b = ev.predict_find_duplicates(cases, cfg, tmp_path)
    diff = [c["id"] for c in cases if a[c["id"]] != b[c["id"]]]
    assert not diff, f"similarity e find_duplicates discordano su {len(diff)} casi: {diff[:20]}"


def test_find_duplicates_non_tocca_le_decisioni_dell_utente(tmp_path, cfg):
    from jobshunter import dedupe
    from jobshunter.db import DB

    c = next(x for x in ev.load_cases() if x["label"] == "dup" and x["difficulty"] == "easy")
    db = DB(tmp_path / "x.db")
    ua, ub = ev.insert_case(db, c)
    db.backfill_meta()
    dedupe.find_duplicates(db, cfg)
    pid = db.conn.execute("SELECT id FROM dup_pairs").fetchone()["id"]
    db.conn.execute("UPDATE dup_pairs SET status='rejected' WHERE id=?", (pid,))
    db.conn.commit()
    dedupe.find_duplicates(db, cfg)
    rows = db.conn.execute("SELECT status FROM dup_pairs").fetchall()
    assert [r["status"] for r in rows] == ["rejected"]  # niente coppia duplicata, decisione intatta


# ---- secondo set (vocabolario nuovo): serve a scoprire se il codice si e' adattato ai casi del primo set
@pytest.mark.phase2
def test_holdout_similarity(cfg):
    cases = ev.load_cases(holdout=True)
    assert len(cases) >= 60
    m = ev.metrics(cases, ev.predict_similarity(cases, 75))
    assert m["precision"] >= MIN_PREC and m["recall"] >= MIN_REC, _report(m, "similarity (holdout)")


@pytest.mark.phase2
def test_holdout_find_duplicates(tmp_path, cfg):
    cases = ev.load_cases(holdout=True)
    m = ev.metrics(cases, ev.predict_find_duplicates(cases, cfg, tmp_path))
    assert m["precision"] >= MIN_PREC and m["recall"] >= MIN_REC, _report(m, "find_duplicates (holdout)")


@pytest.mark.phase2
def test_soglie_di_default_invariate(cfg):
    """Spec 5: stesse soglie (min_percent 75) e auto_confirm_percent che di default non conferma mai da solo."""
    d = cfg.get("dedupe", {})
    assert d.get("min_percent", 75) == 75 and d.get("auto_confirm_percent", 100) >= 100


@pytest.mark.phase2
def test_formula_invariata_su_titoli_e_aziende_identici():
    """Spec 5: 'stessa formula di similarity'. Con titolo e azienda identici l'esito resta quello di fase 1 (100, meno penalita' di sede/livello)."""
    ph1 = ev.phase1()
    from jobshunter import dedupe

    base = {"title": "Cuoco", "company": "Hotel Excelsior", "location": "Venezia"}
    variants = [("Venezia", 100), ("Italia", 90), ("Provincia di Venezia", 100), ("Remote", 90)]
    for loc, expect in variants:
        a, b = ev.as_row(base), ev.as_row(dict(base, location=loc))
        assert ph1.similarity(a, b) == expect  # il riferimento stesso
        assert dedupe.similarity(a, b) == expect, f"sede {loc!r}: la penalita' di sede e' cambiata"
    a, b = ev.as_row(dict(base, title="Junior Cuoco")), ev.as_row(dict(base, title="Senior Cuoco"))
    assert dedupe.similarity(a, b) is None or dedupe.similarity(a, b) < 75
    assert dedupe.similarity(ev.as_row(base), ev.as_row(dict(base, location="Roma"))) is None, "citta' diverse = posizioni diverse"
