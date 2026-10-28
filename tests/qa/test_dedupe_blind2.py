"""Quarto set (blind2, giro 3): lingue nuove (sv, da, ro, cs, tr), citta' con nome piu' lungo, suffissi societari di altri paesi, aziende contenute,
abbreviazioni, refusi, coda. Tipi: risk (rischi dichiarati da BUILDER), city, co, one, lvl, coS, far, abbr, typo, tail, soc, comp, easy."""
import pytest

from qa import dedupe_eval as ev

pytestmark = pytest.mark.phase2


def run():
    cases = ev.load_cases(blind2=True)
    return cases, ev.predict_similarity(cases, 75)


def test_blind2_forma():
    cases = ev.load_cases(blind2=True)
    assert len(cases) >= 150 and sum(c["label"] == "dup" for c in cases) >= 70


def test_blind2_precisione_richiamo_generale():
    cases, pred = run()
    m = ev.metrics(cases, pred)
    assert m["precision"] >= 0.95 and m["recall"] >= 0.85, (round(m["precision"], 3), round(m["recall"], 3))


@pytest.mark.parametrize("a,b", [("Frankfurt am Main", "Frankfurt Oder"), ("Frankfurt", "Frankfurt (Oder)"), ("Newcastle", "Newcastle-under-Lyme"),
                                  ("Halle (Saale)", "Halle (Westfalen)"), ("Birmingham", "Birmingham, Alabama"), ("Cambridge", "Cambridge, MA")])
def test_citta_con_stesso_inizio_ma_diverse_non_sono_duplicati(a, b):
    """B11: 'una citta' con nome piu' lungo e' compatibile' fa coincidere citta' diverse (specie con piu' paesi: Birmingham UK/AL, Cambridge UK/MA)."""
    from jobshunter import dedupe

    base = {"title": "Site Engineer", "company": "Balfour Beatty", "location": a}
    pct = dedupe.similarity(ev.as_row(base), ev.as_row(dict(base, location=b)))
    assert pct is None or pct < 75, f"{a!r} contro {b!r}: {pct}"


@pytest.mark.parametrize("a,b", [("Skoda Auto a.s.", "Skoda Auto"), ("Kofola a.s.", "Kofola"), ("Orsted ApS", "Orsted"), ("Maersk A/S", "Maersk"),
                                  ("Hyundai Motor Manufacturing s.r.o.", "Hyundai Motor Manufacturing"), ("Rixos Hotels A.S.", "Rixos Hotels"),
                                  ("Kiwi.com s.r.o.", "Kiwi.com"),
                                  ("Turkcell A.S.", "Turkcell"), ("Dacia SA", "Dacia")])
def test_forme_societarie_di_altri_paesi_sono_rumore(a, b):
    """B12: a.s., s.r.o., ApS, A/S, A.S., KG... non vengono tolti dal nome azienda: la stessa azienda scende al 70% e il duplicato e' perso."""
    from jobshunter import dedupe

    base = {"title": "Technik udrzby", "company": a, "location": "Praha"}
    pct = dedupe.similarity(ev.as_row(base), ev.as_row(dict(base, company=b)))
    assert pct is not None and pct >= 75, f"{a!r} / {b!r}: {pct}"


def test_blind2_confronto_con_i_set_precedenti():
    """Sovradattamento: la qualita' sul set nuovo non deve scendere di piu' di 0.10 rispetto ai set gia' visti da BUILDER."""
    _, p2 = run()
    new = ev.metrics(ev.load_cases(blind2=True), p2)
    old_cases = ev.load_cases(blind=True)
    old_cases = [c for c in old_cases if c["difficulty"] != "syn"]
    old = ev.metrics(old_cases, ev.predict_similarity(old_cases, 75))
    assert old["recall"] - new["recall"] <= 0.10 and old["precision"] - new["precision"] <= 0.05, (old["precision"], old["recall"], new["precision"], new["recall"])


@pytest.mark.parametrize("a,b", [("Driver", "Diver"), ("Cleaner", "Cleaver"), ("Porter", "Potter")])
def test_refuso_di_una_lettera_non_unisce_mestieri_diversi(a, b):
    """B13 (bassa): l'ammissione dei refusi (una lettera) unisce 'Driver' e 'Diver' (97%). Suggerimento: refusi solo da 6 lettere in su o non fra parole di un dizionario di mestieri."""
    from jobshunter import dedupe

    base = {"title": a, "company": "Rixos", "location": "Antalya"}
    pct = dedupe.similarity(ev.as_row(base), ev.as_row(dict(base, title=b)))
    assert pct is None or pct < 75, f"{a}/{b}: {pct}"
