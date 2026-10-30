"""Fase 8, pagina: segnalibro, filtro Salvati e tutorial a schede (controlli statici su index.html, niente browser, niente rete)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[2] / "jobshunter" / "gui" / "static" / "index.html").read_text(encoding="utf-8")


def block(start: str, end: str) -> str:
    return HTML[HTML.index(start):HTML.index(end)]


TOUR_JS = block("/* ---- tutorial a schede ---- */", "/* ---- guida di primo avvio ---- */")
SAVE_JS = block("/* ---- segnalibro ---- */", "/* ---- drawer ---- */")
STEPS = re.findall(r'\{ id: "([^"]+)", sel: (\'[^\']+\'|"[^"]+"), title: "([^"]+)", text: "((?:[^"\\]|\\.)*)" \}', TOUR_JS)


def test_nessun_cdn_nessun_trattino_lungo_nessuna_rete_esterna():
    assert "—" not in HTML and "–" not in HTML
    assert not re.search(r'<(script|link)[^>]+(src|href)="https?://', HTML)
    assert "@import" not in HTML and "fonts.googleapis" not in HTML
    for js in (TOUR_JS, SAVE_JS):
        assert "https://" not in js and "http://" not in js
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            assert bad not in js


# ------------------------------------------------------------------ segnalibro ----
def test_segnalibro_accessibile_con_aria_pressed_e_nome():
    assert 'class: "star"' in SAVE_JS and 'type: "button"' in SAVE_JS  # un vero <button>: raggiungibile da tastiera
    assert '"aria-pressed"' in SAVE_JS and '"aria-label"' in SAVE_JS
    assert "Togli dai salvati" in SAVE_JS and "Salva: " in SAVE_JS
    assert ".star:focus-visible" in HTML
    assert "e.stopPropagation()" in SAVE_JS  # il clic sul segnalibro non apre il pannello


def test_aggiornamento_ottimistico_con_ripristino():
    i = SAVE_JS.index("async function toggleSave")
    body = SAVE_JS[i:]
    assert body.index("paintSaved(uid, now)") < body.index("await api(")  # prima la pagina, poi la conferma dell'API
    assert "catch (e)" in body and "paintSaved(uid, was)" in body  # ripristino se l'API fallisce
    assert '/api/jobs/${uid}/${now ? "save" : "unsave"}' in body


def test_filtro_salvati_con_conteggio_visibile_anche_vuoto():
    assert 'id: "chipSaved"' in HTML and "★ Salvati (${savedCount})" in HTML
    assert "Salva un annuncio con il segnalibro per ritrovarlo qui" in HTML
    assert 'p.set("saved", "1")' in HTML and "s.saved" in HTML  # query e conteggio dalle statistiche
    chip = HTML[HTML.index('view === "jobs" ? el("button", { class: "chip" + (F.saved'):][:420]
    assert "closedCount" not in chip  # il chip non dipende da altri contatori: c'e' anche con 0 salvati


def test_etichetta_non_piu_online_e_accenti():
    assert "non più online" in HTML and "non piu' online" not in HTML
    assert 'j.saved && j.avail === "closed"' in HTML
    for bad in ("e' ", "perche'", "piu'"):
        assert bad not in SAVE_JS and bad not in TOUR_JS


def test_scartare_un_salvato_non_e_silenzioso():
    assert "askDiscardSaved" in HTML and "unsave: true" in HTML
    assert 'role: "alert"' in HTML and "Scarta e togli dai salvati" in HTML
    assert "Segna candidato" in HTML  # "ho inviato candidatura" resta nel pannello, salvato o no


def test_colonna_segnalibro_con_intestazione_accessibile():
    assert '<th class="sv"><span class="sr">Salvato</span></th>' in HTML
    assert ".sr {" in HTML


# -------------------------------------------------------------------- tutorial ----
def test_tour_ha_almeno_otto_passi_con_testi_italiani_brevi():
    assert len(STEPS) >= 8 and len(STEPS) == len(re.findall(r"^  \{ id: \"", TOUR_JS, re.M))  # il formato dei passi e' letto per intero
    ids = [s[0] for s in STEPS]
    assert len(set(ids)) == len(ids)
    for _id, _sel, title, text in STEPS:
        assert 3 < len(title) < 30 and 20 < len(text) < 260, _id
        assert "—" not in text and "–" not in text


def test_ogni_selettore_di_passo_esiste_nella_pagina():
    page = HTML.replace(TOUR_JS, "")  # i selettori vanno cercati fuori dal tour stesso
    for _id, sel, _t, _x in STEPS:
        for one in sel.strip("'\"").split(","):
            one = one.strip()
            m = re.search(r'\[data-tour="([^"]+)"\]', one)
            if m:
                assert f'"data-tour": "{m.group(1)}"' in page, one
                continue
            m = re.search(r'\[data-flt-chip\]', one)
            if m:
                assert '"data-flt-chip"' in page, one
                continue
            m = re.search(r'\[data-v="([^"]+)"\]', one)
            if m:
                assert f'data-v="{m.group(1)}"' in page, one
                continue
            m = re.fullmatch(r"#([A-Za-z]+)", one)
            if m:
                assert f'id="{m.group(1)}"' in page, one
                continue
            # "#rows tr.row .classe": tbody, classe della riga e della cella
            assert 'id="rows"' in page and 'class: "row' in page, one
            cls = re.findall(r"\.([a-z]+)", one)[-1]
            assert f'"{cls}"' in page or f"{cls}" in page, one


def test_il_tour_e_un_dialogo_modale_accessibile():
    assert 'role: "dialog"' in TOUR_JS and '"aria-modal": "true"' in TOUR_JS
    assert '"aria-labelledby": "tourTitle"' in TOUR_JS and '"aria-describedby": "tourText"' in TOUR_JS
    assert 'tabindex: "-1"' in TOUR_JS
    assert "app.inert = true" in TOUR_JS and "app.inert = false" in TOUR_JS
    assert "prefers-reduced-motion" in HTML


def test_tastiera_esc_frecce_invio_e_focus_trap():
    for key in ('"Escape"', '"ArrowRight"', '"ArrowLeft"', '"Enter"', '"Tab"'):
        assert key in TOUR_JS
    assert "e.shiftKey" in TOUR_JS and "first.focus()" in TOUR_JS and "last.focus()" in TOUR_JS
    assert "t.prevFocus" in TOUR_JS and "back.focus()" in TOUR_JS  # il focus torna dov'era


def test_pulsanti_indietro_avanti_salta_e_indicatore_n_di_n():
    for label in ('"Indietro"', '"Avanti"', '"Salta"', '"Fine"'):
        assert label in TOUR_JS
    assert "`${i + 1} di ${steps.length}`" in TOUR_JS


def test_passi_assenti_o_non_visibili_si_saltano_e_il_conteggio_si_adatta():
    assert "function tourVisible(" in TOUR_JS and "r.width > 0 && r.height > 0" in TOUR_JS
    assert "TOUR_STEPS.filter((st) => tourVisible(st.sel))" in TOUR_JS
    assert "const steps = tourSteps()" in TOUR_JS  # n e N si ricalcolano a ogni passo
    assert "if (tourSteps().length === 0) return false" in TOUR_JS  # nessun passo visibile: il tour non parte nemmeno


def test_posizione_ricalcolata_su_resize_e_scroll_e_listener_tolti_alla_chiusura():
    assert 'window.addEventListener("resize", TOUR.onLayout)' in TOUR_JS
    assert 'window.addEventListener("scroll", TOUR.onLayout, true)' in TOUR_JS
    assert 'window.removeEventListener("resize", t.onLayout)' in TOUR_JS and 'document.removeEventListener("keydown", t.onKey, true)' in TOUR_JS


def test_il_tour_parte_una_volta_dopo_la_guida_e_non_riparte():
    # parte solo da obClose quando la guida e' stata completata (non rifatta) e solo se il server dice "non ancora visto"
    close = block("function obClose(", "async function obSkip")
    assert "const first = !rerun" in close and "if (first) maybeStartTour()" in close
    assert 'obClose(false)' in HTML[HTML.index("async function obSkip"):][:400]  # saltare la guida non lancia il tour
    maybe = block("async function maybeStartTour", "/* ---- guida di primo avvio ---- */")
    assert "o.tutorial_seen" in maybe and maybe.index("o.tutorial_seen") < maybe.index("startTour()")
    # si segna come visto subito all'avvio (nelle impostazioni del server, non in localStorage)
    assert '/api/tutorial/seen", { seen: true }' in TOUR_JS
    assert "localStorage" not in TOUR_JS and "sessionStorage" not in TOUR_JS


def test_rivedi_il_tutorial_dalle_impostazioni():
    assert "Rivedi il tutorial" in HTML and 'id: "btnTour"' in HTML
    btn = HTML[HTML.index('id: "btnTour"'):][:200]
    assert 'setView("jobs")' in btn and "startTour()" in btn


def test_il_tour_non_parte_se_c_e_gia_la_guida():
    assert "if (TOUR || OB) return false" in TOUR_JS


@pytest.mark.parametrize("ident", ["btnScan", "rows"])
def test_elementi_evidenziati_esistono_nel_markup(ident):
    assert f'id="{ident}"' in HTML
