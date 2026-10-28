"""Guida di primo avvio, lato pagina: controlli statici su index.html (niente browser, niente rete)."""
import re
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[2] / "jobshunter" / "gui" / "static" / "index.html").read_text(encoding="utf-8")
ONB_JS = HTML[HTML.index("/* ---- guida di primo avvio ---- */"):HTML.index("loadProfiles().then(() => { renderToolbar(); loadJobs(); })")]


def test_nessun_trattino_lungo():
    assert "—" not in HTML


def test_il_dom_si_costruisce_solo_con_testo():
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert bad not in ONB_JS


@pytest.mark.parametrize("ident", ["onb", "onbProg", "onbBody", "onbFoot", "onbSkip"])
def test_contenitori_presenti(ident):
    assert f'id="{ident}"' in HTML


def test_overlay_accessibile_e_nascosto_all_inizio():
    m = re.search(r'<div class="onb" id="onb"[^>]*>', HTML)
    assert m and 'role="dialog"' in m.group(0) and "aria-modal" in m.group(0) and " hidden" in m.group(0)


def test_ogni_passo_ha_il_suo_disegno_e_ci_sono_sei_passi():
    for fn in ("obStep1", "obStep2", "obStep3", "obStep4", "obStep5", "obStep6"):
        assert f"function {fn}(" in ONB_JS
    assert "Rifai la guida" in HTML and "openOnboarding(true)" in HTML


def test_filtro_dei_figli_nulli():
    # replaceChildren stampa "null" se riceve null: i punti in cui si usa devono filtrare
    assert "[back, el(\"span\", { class: \"grow\" }), save, next].filter(Boolean)" in ONB_JS
    assert "replaceChildren(...body.filter(Boolean)" in ONB_JS


def test_link_esterni_sicuri():
    for m in re.finditer(r'href: "https://[^"]+"[^}]*', ONB_JS):
        assert 'target: "_blank"' in m.group(0) and "noopener" in m.group(0)
    assert "https://developer.adzuna.com/" in ONB_JS

