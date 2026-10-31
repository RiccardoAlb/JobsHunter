"""README IT/EN: logo, ordine delle sezioni iniziali, collegamenti interni e ai file, allineamento fra le due lingue, comandi coerenti."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
FILES = {"it": ROOT / "README.md", "en": ROOT / "README.en.md"}
TEXT = {k: p.read_text(encoding="utf-8") for k, p in FILES.items()}
START = {"it": "Inizia in un minuto", "en": "Get started in a minute"}
INDEX = {"it": "## Indice", "en": "## Contents"}
INSTALL = {"it": "## Installazione", "en": "## Installation"}
DOWNLOAD = {"it": "## Scarica", "en": "## Download"}


def slug(heading: str) -> str:
    """Ancora come la calcola GitHub: minuscole, via la punteggiatura, spazi in trattini."""
    h = re.sub(r"[`*_]", "", heading.strip().lower())
    h = re.sub(r"[^\w\- ]", "", h, flags=re.U)
    return h.replace(" ", "-")


def anchors(text: str) -> set[str]:
    out, seen = set(), {}
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        m = None if in_code else re.match(r"^#{1,6}\s+(.*)$", line)
        if m:
            s = slug(m.group(1))
            n = seen.get(s, 0)
            seen[s] = n + 1
            out.add(s if n == 0 else f"{s}-{n}")
    return out


@pytest.mark.parametrize("lang", ["it", "en"])
def test_logo_in_cima_centrato_e_raggiungibile(lang):
    text = TEXT[lang]
    m = re.match(r'<p align="center"><img src="([^"]+)" alt="([^"]+)" width="(\d+)"></p>', text)
    assert m, "il README deve cominciare con il logo centrato"
    src, alt, width = m.groups()
    assert (ROOT / src).is_file() and src == "branding/JobsHunter.png"
    assert len(alt) > 5 and 80 <= int(width) <= 300
    assert '<h1 align="center">JobsHunter</h1>' in text[:600]
    assert ("README.en.md" if lang == "it" else "README.md") in text[:900]  # link all'altra lingua


@pytest.mark.parametrize("lang", ["it", "en"])
def test_ordine_logo_inizia_screenshot_indice(lang):
    text = TEXT[lang]
    pos = [text.index('<img src="branding/JobsHunter.png"'), text.index(f"## {START[lang]}"), text.index("docs/screenshots/01-lista.png"), text.index(INDEX[lang])]
    assert pos == sorted(pos) and len(set(pos)) == 4
    head = text[: pos[1]]
    assert head.count("\n") < 20  # in cima: logo, titolo, link, UNA riga di descrizione, avvisi brevi
    for word in ("MIT", "0.4.0"):
        assert word in head
    assert any(w in head for w in ("Non affiliato", "Not affiliated"))


@pytest.mark.parametrize("lang", ["it", "en"])
def test_descrizione_multipiattaforma_senza_il_solo_mac(lang):
    head = TEXT[lang][: TEXT[lang].index(f"## {START[lang]}")]
    assert "macOS" in head and "Windows" in head and "Linux" in head
    assert not re.search(r"(sul tuo Mac|on your Mac)", TEXT[lang])


@pytest.mark.parametrize("lang", ["it", "en"])
def test_nessun_trattino_lungo(lang):
    assert "—" not in TEXT[lang]


@pytest.mark.parametrize("lang", ["it", "en"])
def test_collegamenti_interni_e_ai_file_non_sono_rotti(lang):
    text = TEXT[lang]
    valid = anchors(text)
    broken = []
    without_code = re.sub(r"```.*?```", "", text, flags=re.S)
    for target in re.findall(r"\]\(([^)\s]+)\)", without_code) + re.findall(r'(?:src|href)="([^"]+)"', without_code):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, frag = target.partition("#")
        if path:
            if not (ROOT / path).exists():
                broken.append(target)
            if frag and path.endswith(".md") and frag not in anchors((ROOT / path).read_text(encoding="utf-8")):
                broken.append(target)
        elif frag not in valid:
            broken.append(target)
    assert not broken, broken


def test_it_e_en_allineati():
    it, en = TEXT["it"], TEXT["en"]
    h = lambda t: [l for l in t.splitlines() if re.match(r"^## ", l)]
    assert len(h(it)) == len(h(en)), (len(h(it)), len(h(en)))
    count = lambda t: len(re.findall(r"^\d+\. \[", t[t.index("## Indice" if t is it else "## Contents"):][:2500], re.M))
    assert count(it) == count(en)
    # stesse tabelle dei pacchetti e stessi nomi di file
    for name in ("JobsHunter-<versione>-macOS-arm64.zip", "JobsHunter-<versione>-Windows-x64.zip"):
        assert name in it and name.replace("versione", "version") in en


def block_commands(text: str, start: str, end: str) -> list[str]:
    seg = text[text.index(start): text.index(end, text.index(start) + 5)]
    cmds = []
    for code in re.findall(r"```(?:bash|bat)\n(.*?)```", seg, re.S):
        cmds += [l.strip() for l in code.splitlines() if l.strip() and not l.strip().startswith(("#", "REM"))]
    return cmds


@pytest.mark.parametrize("lang", ["it", "en"])
def test_i_comandi_principali_non_si_contraddicono_tra_inizia_e_installazione(lang):
    text = TEXT[lang]
    quick = block_commands(text, f"## {START[lang]}", INDEX[lang])
    detail = block_commands(text, INSTALL[lang], "### Where" if lang == "en" else "### Dove stanno")
    essential = [c for c in quick if c.startswith(("git clone", "cd ", "./jh", "jh.bat"))]
    assert essential == ["git clone https://github.com/RiccardoAlb/JobsHunter.git jobshunter", "cd jobshunter", "./jh setup", "./jh gui",
                         "git clone https://github.com/RiccardoAlb/JobsHunter.git jobshunter", "cd jobshunter", "jh.bat setup", "jh.bat gui"]
    assert [c for c in detail if c.startswith(("git clone", "cd ", "./jh", "jh.bat"))] == essential
    # nessun comando dei due blocchi usa un modo diverso di preparare l'ambiente
    for c in quick + detail:
        assert "pip install" not in c and "venv" not in c


@pytest.mark.parametrize("lang", ["it", "en"])
def test_le_due_strade_e_il_python_dei_pacchetti(lang):
    text = TEXT[lang]
    seg = text[text.index(f"## {START[lang]}"): text.index(INDEX[lang])]
    assert "A." in seg and "B." in seg and "0.4.0" in seg and "releases" in seg
    assert any(w in seg for w in ("contiene già il suo Python", "already contains its own Python"))
    assert "3.11" in seg and ("conferma" in seg or "confirmation" in seg)
    inst = text[text.index(INSTALL[lang]):][:3500]
    for w in ("winget install -e --id Python.Python.3.13 --scope user", "brew install python@3.13", "sudo", "[s/N]"):
        assert w in inst, w
    assert "inizia-in-un-minuto" in text[text.index(INSTALL[lang]):][:400] or "get-started-in-a-minute" in text[text.index(INSTALL[lang]):][:400]
    assert "inizia-in-un-minuto" in text[text.index(DOWNLOAD[lang]):][:400] or "get-started-in-a-minute" in text[text.index(DOWNLOAD[lang]):][:400]
