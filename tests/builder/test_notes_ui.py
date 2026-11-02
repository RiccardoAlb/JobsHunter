"""Fase 10, pagina: blocco note e lettere (controlli statici su index.html, niente browser, niente rete)."""
from __future__ import annotations

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "jobshunter" / "gui" / "static" / "index.html").read_text(encoding="utf-8")


def block(start: str, end: str) -> str:
    return HTML[HTML.index(start):HTML.index(end)]


NOTE_JS = block("/* ---- note e lettere ---- */", "/* ---- ponte con l'app nativa")
TOUR_JS = block("/* ---- tutorial a schede ---- */", "/* ---- guida di primo avvio ---- */")
T_START = NOTE_JS.index("const T_NOTE = {")
T_END = NOTE_JS.index("\n};\n", T_START) + 4
T_NOTE_JS = NOTE_JS[T_START:T_END]
CODE_JS = NOTE_JS[:T_START] + NOTE_JS[T_END:]  # tutto tranne i testi
NOTE_CSS = HTML[HTML.index("/* note e lettere */"):HTML.index("/* toast */")]
APPS_JS = block("/* ---- candidature ---- */", "/* ---- note e lettere ---- */")
DRAWER_JS = block("/* ---- drawer ---- */", "function askDiscardSaved")


# ------------------------------------------------------------------ regole generali ----
def test_nessun_cdn_nessun_trattino_lungo_nessuna_rete_esterna():
    assert "—" not in NOTE_JS and "–" not in NOTE_JS and "—" not in NOTE_CSS
    assert "https://" not in NOTE_JS and "http://" not in NOTE_JS
    assert not re.search(r'<(script|link)[^>]+(src|href)="https?://', HTML)
    # l'unica rete e' il server locale, attraverso gli helper della pagina
    assert "fetch(" not in NOTE_JS and "XMLHttpRequest" not in NOTE_JS and "WebSocket" not in NOTE_JS and "sendBeacon" not in NOTE_JS
    assert "localStorage" not in NOTE_JS and "sessionStorage" not in NOTE_JS  # le note non finiscono nel browser


def test_mai_innerhtml_con_testi_dell_utente():
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert bad not in HTML, bad
    # il DOM si costruisce con el(): testo sempre come nodo di testo o textContent
    assert "document.createTextNode(c)" in HTML
    assert "textContent" in NOTE_JS


def test_testi_in_italiano_con_accenti_veri():
    for bad in ("e' ", "perche'", "piu'", "pero'", "gia'", "puo'", "cosi'", "E' "):
        assert bad not in NOTE_JS, bad
    for good in ("Annuncio non più online", "È il testo da cui parte", "L'annuncio non è più online", "Modificata il"):
        assert good in T_NOTE_JS, good


def test_tutti_i_testi_nuovi_stanno_in_t_note():
    assert T_NOTE_JS.startswith("const T_NOTE = {") and NOTE_JS.count("const T_NOTE") == 1
    for label in ("Nuova nota", "Nuova lettera", "Copia testo", "Esporta in Markdown", "Elimina", "Ripristina modello",
                  "Salvato", "Modello di lettera", "Le tue note", "Tutte", "Lettere", "Appunti", "Generali", "Salva ora"):
        assert f'"{label}"' in T_NOTE_JS, label
        assert f'"{label}"' not in CODE_JS, f"{label} fuori da T_NOTE"
    # il codice fuori da T_NOTE non contiene frasi italiane scritte a mano (testi in stringa con almeno due parole e maiuscola iniziale)
    frasi = [m for m in re.findall(r'"([A-ZÈ][a-zàèéìòù]+ [^"]{3,})"', CODE_JS) if " " in m]
    assert frasi == [], frasi


def test_plurale_e_singolare():
    assert 'countOne: "1 nota"' in T_NOTE_JS and "`${n} note`" in T_NOTE_JS
    assert '"1 nota collegata"' in T_NOTE_JS and "`${n} note collegate`" in T_NOTE_JS
    assert 'n === 1 ? "E un\'altra nota."' in T_NOTE_JS
    assert "const nCount = (n) => (n === 1 ? T_NOTE.countOne : T_NOTE.countMany(n))" in NOTE_JS


# ------------------------------------------------------------------ menu e vista ----
def test_voce_note_nel_menu_con_conteggio():
    assert re.search(r'<button class="tab" data-v="notes"[^>]*>Note<span class="pill soft" id="noteBadge" hidden></span></button>', HTML)
    assert '<section class="apps" id="noteview" hidden>' in HTML and 'id="notecontent"' in HTML
    assert '$("noteview").hidden = v !== "notes"' in HTML and 'v === "notes" ? loadNotes()' in HTML
    assert "setNoteBadge(s.notes || 0)" in HTML  # il conteggio viene da /api/stats
    assert 'b.hidden = !n' in NOTE_JS and "aria-label" in block("function setNoteBadge", "async function fetchNotes")


def test_vista_elenco_ricerca_filtri_e_pulsanti():
    v = block("async function loadNotes", "/* sezione note collegate")
    assert 'type: "search"' in v and '"aria-label": T.searchLabel' in v
    assert "setTimeout" in v and "250" in v  # ricerca ritardata
    assert 'role: "group"' in v and '"aria-pressed"' in v and "data-note-filter" in v
    for k in ("all", "letter", "note", "general"):
        assert f"{k}:" in T_NOTE_JS.split("filters:")[1].split("}")[0]
    assert "T.newLetter" in v and "T.newNote" in v
    assert 'o.kind = "letter"' in NOTE_JS and 'o.kind = "note"' in NOTE_JS and "o.general = true" in NOTE_JS
    assert 'p.set("general", "1")' in NOTE_JS and 'p.set("q", o.q)' in NOTE_JS
    assert "/api/notes?" in NOTE_JS
    assert 'role: "status", "aria-live": "polite"' in v  # il conteggio viene annunciato


def test_risposte_vecchie_ignorate_e_errori_non_silenziosi():
    r = block("async function refreshNoteList", "function tplInsert")
    assert "++noteSeq" in r and "seq !== noteSeq" in r
    assert "T_NOTE.loadFail" in r and 'role: "alert"' in r
    assert "T_NOTE.emptySearch" in r and "T_NOTE.emptyAll" in r and "T_NOTE.emptyFilter" in r


def test_scheda_nota_e_un_pulsante_con_nome_accessibile():
    r = block("function noteRow", "/* vista Note */")
    assert 'el("button", { type: "button", class: "nt-card"' in r and '"aria-label"' in r
    assert "T.tagClosed" in r and "job_open === false" in r  # annuncio chiuso: etichetta, la nota resta
    assert "Array.from(" in r  # niente emoji spezzate nell'anteprima
    assert ".nt-card:focus-visible" in NOTE_CSS


# ------------------------------------------------------------------ modello di lettera ----
def test_modello_di_lettera_con_segnaposto_salva_e_ripristina():
    b = block("function tplBox", "async function loadNotes")
    assert "/api/notes/template" in b
    assert 'postRaw("/api/notes/template", { template: ta.value })' in b
    assert 'postRaw("/api/notes/template", { template: "" })' in b  # stringa vuota = ripristina il predefinito
    for ph in ("{azienda}", "{ruolo}", "{sede}", "{data}", "{link}"):
        assert f'"{ph}"' in T_NOTE_JS, ph
    assert "setRangeText" in NOTE_JS  # i segnaposto si inseriscono dove sta il cursore
    assert "T.tplReset" in b and "T.tplResetConfirm" in b and "armed" in b  # ripristino con conferma
    assert 'el("details"' in b and "maxlength: 20000" in b
    assert 'for: "ntTplText"' in b  # etichetta collegata alla casella
    assert "T.tplFail" in b and "ta.value" in b


def test_modello_non_si_perde_se_il_salvataggio_fallisce():
    b = block("function tplBox", "async function loadNotes")
    save = b[b.index("const save"):b.index("let armed")]
    assert "ta.value =" not in save  # in caso d'errore la casella non viene toccata


# ------------------------------------------------------------------ editor ----
def test_editor_e_un_dialogo_modale_accessibile():
    e = block("function openNoteEditor", "async function neRequestClose")
    assert 'role: "dialog"' in e and '"aria-modal": "true"' in e and '"aria-labelledby": "neHead"' in e
    assert 'tabindex: "-1"' in e
    assert "app.inert = true" in e and "app.inert = false" in NOTE_JS
    assert 'for: "neTitle"' in e and 'for: "neBody"' in e  # etichette vere
    assert 'role: "status", "aria-live": "polite"' in e  # indicatore Salvato
    assert 'role: "alert"' in e  # errori e conferma di eliminazione
    assert "maxlength: NOTE_TITLE_MAX" in e and "maxlength: NOTE_BODY_MAX" in e
    assert "NOTE_TITLE_MAX = 200" in NOTE_JS and "NOTE_BODY_MAX = 100000" in NOTE_JS
    assert "prevFocus" in e and "neFinish" in NOTE_JS  # il focus torna dov'era


def test_tastiera_esc_ctrl_s_e_focus_trap():
    e = block("function openNoteEditor", "async function neRequestClose")
    assert '(e.ctrlKey || e.metaKey)' in e and '"s"' in e and "neFlush()" in e
    assert '"Escape"' in e and "neRequestClose()" in e
    assert '"Tab"' in e and "e.shiftKey" in e and "first.focus()" in e and "last.focus()" in e
    assert 'document.addEventListener("keydown", s.onKey, true)' in e
    assert 'document.removeEventListener("keydown", s.onKey, true)' in NOTE_JS
    assert "e.isComposing" in e
    # le scorciatoie della lista (j, k, Esc) non scattano con l'editor aperto
    assert "|| NE ||" in HTML.split("document.addEventListener(\"keydown\", (e) => {")[1][:400]


def test_salvataggio_automatico_ritardato_e_ordinato():
    assert "setTimeout(() => neFlush(), 900)" in NOTE_JS
    assert "s.chain = s.chain.then(() => neDoSave(s))" in NOTE_JS  # un salvataggio alla volta
    d = block("async function neDoSave", "function openNoteEditor")
    assert 'postRaw("/api/notes", {' in d and 'postRaw("/api/notes/" + s.id, { title, body })' in d
    assert "title === s.last.title && body === s.last.body" in d  # idempotente: niente richieste inutili
    assert "!title.trim() && !body.trim()" in d  # una nota vuota non viene creata
    assert 'neState(s, "saved")' in d and 'neState(s, "saving")' in d and 'neState(s, "dirty")' in d
    assert 'stateSaved: "Salvato"' in T_NOTE_JS


def test_se_il_salvataggio_fallisce_il_testo_resta_nella_casella():
    assert ".body.value =" not in NOTE_JS and ".title.value =" not in NOTE_JS.replace("value: s.last.title", "")  # mai riscritte dal codice
    d = block("async function neDoSave", "function openNoteEditor")
    fail = d[d.index("if (!r.ok)"):d.index("if (s.id == null) s.id")]
    assert "s.failed = true" in fail and "T_NOTE.saveFail" in fail and "return false" in fail
    assert "s.last =" not in fail  # l'ultimo testo salvato resta quello vero: il prossimo tentativo rimanda tutto
    c = block("async function neRequestClose", "function neFinish")
    assert "if (!ok && !s.warned)" in c and "return;" in c and "T_NOTE.closeWarn" in c  # Esc con errore: non chiude al primo colpo
    assert "T_NOTE.saveFail(" in T_NOTE_JS or "saveFail:" in T_NOTE_JS


def test_chiusura_salva_prima_di_chiudere():
    c = block("async function neRequestClose", "function neFinish")
    assert c.index("await neFlush()") < c.index("neFinish(s)")
    assert "if (s.changed) afterNoteChange()" in NOTE_JS


def test_copia_esporta_elimina():
    assert "navigator.clipboard.writeText(text)" in NOTE_JS and 'execCommand("copy")' in NOTE_JS  # con ripiego
    assert "T_NOTE.copyFail" in NOTE_JS  # se non copia lo dice
    x = block("async function neExport", "async function neDelete")
    assert x.index("await neFlush()") < x.index("/export")  # prima salva
    assert "`/api/notes/${s.id}/export`" in x and "r.data.path" in x
    d = block("async function neDelete", "\n/* ---- ponte")
    assert "`/api/notes/${s.id}/delete`" in d
    e = block("function openNoteEditor", "async function neRequestClose")
    assert "askDelete" in e and "T.delAsk" in e and "T.delYes" in e and "T.delNo" in e  # conferma esplicita
    assert 'class: "dconfirm", role: "alert"' in e
    assert "Non si può annullare" in T_NOTE_JS


def test_creazione_lettera_dal_modello_del_server():
    n = block("async function newLetter", "/* scelta dell'annuncio")
    assert 'kind: "letter"' in n and "job_uid: ctx.job" in n and "app_id: ctx.app" in n
    assert "body" not in n  # il testo lo riempie il server con il modello
    assert "T_NOTE.letterFail" in n and "openNoteEditor(r.data, true)" in n


# ------------------------------------------------------------------ annunci e candidature ----
def test_sezione_le_tue_note_nel_pannello_annuncio():
    assert "noteHost({ job: uid })" in DRAWER_JS
    h = block("function noteHost", "async function fillHost")
    assert "T.secTitle" in h and "T.newLetter" in h and "T.newNote" in h
    assert '"aria-labelledby": id' in h
    f = block("async function fillHost", "function refreshNoteHosts")
    assert "list.slice(0, 5)" in f and "T.more(more)" in f and "T.noneHere" in f  # elenco corto


def test_sezione_le_tue_note_nella_scheda_candidatura_e_conteggio():
    assert "noteHost({ app: a.id })" in APPS_JS
    assert "appNotes[a.id]" in APPS_JS and "T_NOTE.linked(appNotes[a.id])" in APPS_JS
    assert "x.note_count" in APPS_JS and "appNotes[x.id] = x.note_count" in APPS_JS  # conteggio dal server
    # il vecchio campo Note della candidatura resta com'e'
    assert 'el("label", { class: "fl" }, "Note", notes)' in APPS_JS
    assert 'post("/api/apps/" + a.id, { notes: notes.value })' in APPS_JS
    assert 'placeholder: "Appunti: referente, domande fatte, impressioni..."' in APPS_JS


def test_dopo_segna_candidato_la_vista_si_rinfresca():
    act = DRAWER_JS[DRAWER_JS.index("const act ="):DRAWER_JS.index("const recheck")]
    assert 'if (status === "applied") afterNoteChange()' in act
    a = block("function afterNoteChange", "async function newLetter")
    assert "refreshNoteHosts()" in a and 'view === "notes"' in a and 'view === "apps"' in a and "loadStats()" in a


def test_hosts_orfani_vengono_dimenticati():
    r = block("function refreshNoteHosts", "function afterNoteChange")
    assert "document.contains(h.sec)" in r and "NOTE_HOSTS.delete(h)" in r


# ------------------------------------------------------------------ tema e finestra stretta ----
def test_tema_chiaro_e_scuro_senza_colori_fissi():
    css = NOTE_CSS.replace("rgba(0,0,0,.55)", "").replace("rgba(0,0,0,.45)", "")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "colori fissi nel CSS delle note"
    assert "var(--panel)" in NOTE_CSS and "var(--line" in NOTE_CSS and "var(--text)" in NOTE_CSS


def test_finestra_stretta_e_movimento_ridotto():
    assert "@media (max-width: 600px)" in NOTE_CSS and ".nt-dlg { inset: 0" in NOTE_CSS
    assert "grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))" in NOTE_CSS and "overflow-wrap: anywhere" in NOTE_CSS
    assert "min(820px, calc(100vw - 24px))" in NOTE_CSS and "max-height: calc(100vh - 24px)" in NOTE_CSS
    assert "prefers-reduced-motion" in NOTE_CSS
    assert ".toast { z-index: 90; }" in NOTE_CSS  # il toast resta sopra la finestra dell'editor
    assert ".nt-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap" in NOTE_CSS


# ------------------------------------------------------------------ tutorial ----
def test_passo_note_nel_tutorial_presente_e_saltabile():
    step = re.search(r'\{ id: "notes", sel: \'(\.tab\[data-v="notes"\])\', title: "Note", text: "((?:[^"\\]|\\.)*)" \}', TOUR_JS)
    assert step, "passo Note mancante"
    assert 20 < len(step.group(2)) < 260 and "—" not in step.group(2)
    assert TOUR_JS.index('id: "notes"') < TOUR_JS.index('id: "scan"')
    assert 'data-v="notes"' in HTML  # l'elemento evidenziato esiste nella pagina
    # se l'elemento non si vede il passo si salta, come per gli altri
    assert "TOUR_STEPS.filter((st) => tourVisible(st.sel))" in TOUR_JS and "function tourVisible(" in TOUR_JS


def test_b135_b136_guardia_creazione_e_avviso_riarmato():
    n = block("let creatingLetter", "/* scelta dell'annuncio")
    assert "if (creatingLetter) return" in n and "btn.disabled = true" in n and "finally" in n and "creatingLetter = false" in n
    assert "newLetter(ctx, e.currentTarget)" in NOTE_JS  # pannelli annuncio e candidatura: come prima
    assert "openLetterPicker(e.currentTarget)" in NOTE_JS  # vista Note: scelta dell'annuncio
    assert "s.warned = false" in NOTE_JS[NOTE_JS.index("const onEdit"):][:200]


PICK_JS = block("/* scelta dell'annuncio per una nuova lettera", "/* editor di nota (finestra di dialogo) */")


def test_selettore_annuncio_dialogo_accessibile():
    assert 'role: "dialog", "aria-modal": "true", "aria-labelledby": "pkHead", "aria-describedby": "pkIntro", tabindex: "-1"' in PICK_JS
    assert '"aria-label": T.pickSearchLabel' in PICK_JS and 'type: "search"' in PICK_JS
    assert '"Escape"' in PICK_JS and '"Tab"' in PICK_JS and "e.shiftKey" in PICK_JS and "first.focus()" in PICK_JS and "last.focus()" in PICK_JS
    assert "app.inert = true" in PICK_JS and "app.inert = false" in PICK_JS
    assert "k.opener" in PICK_JS and ".focus()" in PICK_JS  # focus restituito
    assert 'role: "status"' in PICK_JS or '"aria-live": "polite"' in PICK_JS and 'role: "alert"' in PICK_JS
    assert "|| NE || PK ||" in HTML  # le scorciatoie della lista restano ferme
    assert "if (PK || NE) return" in PICK_JS


def test_selettore_solo_dalla_vista_note_e_alimentato_dalle_rotte_esistenti():
    v = block("async function loadNotes", "/* sezione note collegate")
    assert "openLetterPicker(e.currentTarget)" in v and "newLetter(" not in v
    assert "newLetter(ctx, e.currentTarget)" in block("function noteHost", "async function fillHost")
    assert '"/api/apps?outcome=all"' in PICK_JS and 'saved: "1"' in PICK_JS and "limit: 20" in PICK_JS and "q: k.q" in PICK_JS
    assert "slice(0, 20)" in PICK_JS and 'j.avail !== "closed"' in PICK_JS  # i chiusi non compaiono tra i trovati
    assert "k.q.length < 2" in PICK_JS and "setTimeout" in PICK_JS and "250" in PICK_JS  # ricerca ritardata
    assert "{ app: a.id }" in PICK_JS and "{ job: j.uid }" in PICK_JS and "pickerChoose(k, {}," in PICK_JS


def test_selettore_guardia_in_corso_e_errori_senza_perdere_lo_stato():
    assert "newLetter(ctx, btn, () => pickerClose())" in PICK_JS  # il dialogo si chiude solo a lettera creata
    assert "if (onCreated) onCreated()" in NOTE_JS and "if (creatingLetter) return" in NOTE_JS
    assert "seq !== k.seq" in PICK_JS and "k.foundErr = true" in PICK_JS and "T.pickFail" in PICK_JS and "T.pickSearchFail" in PICK_JS
    assert "Promise.allSettled" in PICK_JS  # un elenco che non carica non blocca l'altro


def test_selettore_testi_in_t_note_e_dom_sicuro():
    for label in ("Per quale annuncio è la lettera?", "Le tue candidature", "Annunci salvati", "Nessuna candidatura", "Nessun annuncio salvato",
                  "Nessun risultato", "Nessuno, lettera generale"):
        assert f'"{label}"' in T_NOTE_JS and f'"{label}"' not in CODE_JS, label
    assert 'pickResults: (n) => (n === 1 ? "1 risultato" : `${n} risultati`)' in T_NOTE_JS
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "fetch(", "https://"):
        assert bad not in PICK_JS
    assert ".pk-dlg input[type=search]" in HTML and ".nt-dlg { inset: 0" in NOTE_CSS  # tutto schermo sotto 600px
