"""Quinto set (blind3, giro 4): citta' omonime, forme societarie rare, marchio contro ragione sociale, refusi corti e lunghi, una lettera che cambia il mestiere,
abbreviazioni, code di rumore o che specializzano. Include la regola di sicurezza: la fascia pct == 100 (conferma automatica) deve avere precisione 1.0."""
import json
from pathlib import Path

import pytest

from qa import dedupe_eval as ev

pytestmark = pytest.mark.phase2
SETS = ["dedupe_cases.json", "dedupe_holdout.json", "dedupe_blind.json", "dedupe_blind2.json", "dedupe_blind3.json"]


@pytest.mark.parametrize("name", SETS)
def test_conferma_automatica_solo_su_veri_duplicati(name):
    """pct >= 100 nasconde un annuncio senza che l'utente lo veda: nessun falso duplicato ammesso."""
    cases = json.loads((Path(ev.DATA).parent / name).read_text(encoding="utf-8"))
    pred = ev.predict_similarity(cases, 100)
    bad = [(c["a"]["title"], c["a"]["company"], c["b"]["company"], c["_pct"]) for c in cases if pred[c["id"]] and c["label"] == "nodup"]
    assert not bad, bad


@pytest.mark.xfail(reason="B15: limite noto accettato (elenchi aperti di sigle, forme societarie e nomi di citta in altre lingue); resta il controllo di sicurezza sulle conferme automatiche", strict=False)
def test_blind3_precisione_richiamo():
    cases = [c for c in ev.load_cases(blind3=True) if c["difficulty"] != "syn"]
    m = ev.metrics(cases, ev.predict_similarity(cases, 75))
    assert m["precision"] >= 0.95 and m["recall"] >= 0.85, (round(m["precision"], 3), round(m["recall"], 3), [(c["a"]["title"], c["a"]["company"], c["b"]["company"]) for c in m["fn"]][:15])


@pytest.mark.xfail(reason="B15: limite noto accettato (elenchi aperti di sigle, forme societarie e nomi di citta in altre lingue); resta il controllo di sicurezza sulle conferme automatiche", strict=False)
@pytest.mark.parametrize("a,b", [("Tech", "Technician"), ("Rep", "Representative"), ("Exec", "Executive"), ("Mech.", "Mechanical"), ("Supv", "Supervisor"), ("Dir.", "Director")])
def test_abbreviazioni_comuni(a, b):
    """B15: abbreviazioni comuni non riconosciute (solo l'elenco ABBREV)."""
    from jobshunter import dedupe

    base = {"title": f"Maintenance {a}", "company": "Pemberton Holdings", "location": "Cardiff"}
    pct = dedupe.similarity(ev.as_row(base), ev.as_row(dict(base, title=f"Maintenance {b}")))
    assert pct is not None and pct >= 75, f"{a}/{b}: {pct}"


@pytest.mark.xfail(reason="B15: limite noto accettato (elenchi aperti di sigle, forme societarie e nomi di citta in altre lingue); resta il controllo di sicurezza sulle conferme automatiche", strict=False)
@pytest.mark.parametrize("a,b", [("Femsa S.A. de C.V.", "Femsa"), ("Alicorp S.A.A.", "Alicorp"), ("Nordea Bank Abp", "Nordea Bank"), ("Ryanair DAC", "Ryanair"), ("Merck KGaA", "Merck")])
def test_forme_societarie_rare(a, b):
    """B15: S.A. de C.V., S.A.A., Abp, DAC."""
    from jobshunter import dedupe

    base = {"title": "Maintenance Technician", "company": a, "location": "Brno"}
    pct = dedupe.similarity(ev.as_row(base), ev.as_row(dict(base, company=b)))
    assert pct is not None and pct >= 75, f"{a} / {b}: {pct}"


@pytest.mark.xfail(reason="B15: limite noto accettato (elenchi aperti di sigle, forme societarie e nomi di citta in altre lingue); resta il controllo di sicurezza sulle conferme automatiche", strict=False)
@pytest.mark.parametrize("a,b", [("Prague", "Praha 2"), ("Zurich, Switzerland", "Zuerich"), ("St. Gallen", "Sankt Gallen"), ("Antwerp", "Antwerpen")])
def test_stessa_citta_scritta_in_modi_diversi(a, b):
    """B15: varianti di scrittura e traduzione di citta' (alcune gia' coperte, altre no)."""
    from jobshunter import dedupe

    base = {"title": "Quality Inspector", "company": "Halvorsen Industrier", "location": a}
    pct = dedupe.similarity(ev.as_row(base), ev.as_row(dict(base, location=b)))
    assert pct is not None and pct >= 75, f"{a} / {b}: {pct}"


@pytest.mark.xfail(reason="B15: limite noto accettato (elenchi aperti di sigle, forme societarie e nomi di citta in altre lingue); resta il controllo di sicurezza sulle conferme automatiche", strict=False)
def test_honda_financial_services_non_e_honda():
    """B15: 'Financial Services' e' un'altra societa' del gruppo (90%): vale per Honda, Ford Credit, Toyota..."""
    from jobshunter import dedupe

    base = {"title": "Customer Advisor", "company": "Honda", "location": "Lyon"}
    pct = dedupe.similarity(ev.as_row(base), ev.as_row(dict(base, company="Honda Financial Services")))
    assert pct is None or pct < 75
