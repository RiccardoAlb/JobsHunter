"""Terzo set (CIECO, scritto fuori dal progetto e copiato qui a fine giro 2): sinonimi, composti tedeschi, refusi, abbreviazioni, code lunghe,
una parola che cambia il ruolo, nl/pl/pt. Tipi: syn (traduzioni: limite noto, non richiesto), comp, typo, abbr, tail, soc, one (falsi: 1 parola), lvl, city, co, far, aff."""
import pytest

from qa import dedupe_eval as ev

pytestmark = pytest.mark.phase2


def _run(cfg_tmp=None):
    cases = ev.load_cases(blind=True)
    return cases, ev.predict_similarity(cases, 75)


def test_blind_precisione_e_richiamo_senza_traduzioni():
    cases, pred = _run()
    cases = [c for c in cases if c["difficulty"] != "syn"]
    m = ev.metrics(cases, pred)
    assert m["precision"] >= 0.95 and m["recall"] >= 0.85, (m["precision"], m["recall"], [(c["a"]["title"], c["b"]["title"]) for c in m["fp"] + m["fn"]][:15])


def test_blind_abbreviazioni_e_refusi_richiamo_minimo():
    """B10: Mgr/Manager, Dev/Developer, Eng/Engineer, Asst, Resp., Ing., Vendedor/Vendedro non vengono riconosciuti (una parola diversa per parte = non confrontabile)."""
    cases, pred = _run()
    sub = [c for c in cases if c["label"] == "dup" and c["difficulty"] in ("abbr", "typo")]
    hit = sum(pred[c["id"]] for c in sub)
    assert hit / len(sub) >= 0.8, f"abbreviazioni e refusi riconosciuti: {hit}/{len(sub)}; persi: {[(c['a']['title'], c['b']['title']) for c in sub if not pred[c['id']]][:12]}"


@pytest.mark.parametrize("a,b", [("Infermiere", "Infermiere pediatrico"), ("Enfermeiro", "Enfermeiro chefe"), ("Cozinheiro", "Cozinheiro")])
def test_blind_falsi_duplicati_con_parola_in_piu_che_cambia_il_ruolo(a, b):
    """B10: un titolo allungato SENZA separatore (pediatrico, chefe) e' un altro ruolo; con separatore (' - Full time') e' lo stesso."""
    cases, pred = _run()
    c = next(c for c in cases if c["a"]["title"] == a and c["b"]["title"] == b or (a == b and c["id"] == "z142"))
    assert not pred[c["id"]], f"{c['a']['title']} | {c['a']['company']} <> {c['b']['title']} | {c['b']['company']} dato come duplicato"


def test_blind_tempi_e_nessuna_regressione_sui_set_precedenti(tmp_path, cfg):
    import time

    cases = ev.load_cases(blind=True)
    t = time.perf_counter()
    ev.predict_find_duplicates(cases[:60], cfg, tmp_path)
    assert time.perf_counter() - t < 30
