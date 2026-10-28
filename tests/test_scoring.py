"""Riconoscimento delle parole chiave nei titoli."""
import pytest

from jobshunter.scoring import _has, score_job
from conftest import make_job


@pytest.mark.parametrize("term,text", [
    ("pentest", "senior pentester"), ("pentest", "web pentesting"), ("penetration test", "penetration tester junior"),
    ("soc", "soc analyst"), ("siem", "esperienza con siem e edr"), ("analyst", "soc analysts"),
])
def test_riconosce_parola_e_desinenze(term, text):
    assert _has(term, text)


@pytest.mark.parametrize("term,text", [
    ("soc", "social media manager"), ("siem", "siemens energy"), ("edr", "federico"), ("intern", "internal tools"),
])
def test_non_confonde_parole_piu_lunghe(term, text):
    assert not _has(term, text)


def test_pentester_non_viene_piu_scartato(cfg):
    assert score_job(make_job("Penetration Tester", desc="Test di sicurezza"), cfg) is not None
    assert score_job(make_job("Pentester", desc="Test di sicurezza"), cfg) is not None
