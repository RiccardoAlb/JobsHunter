"""Genera un report Markdown (compatibile Obsidian) con gli annunci completi."""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx

from . import availability, net, settings

ICON = {"RED": "🔴", "BLUE": "🔵", "PURPLE": "🟣", "SYSADM": "🟡", "SEC": "🔷"}
ORDER = ["PURPLE", "BLUE", "RED", "SEC", "SYSADM"]
MODE_LABEL = {"remote": "remoto", "hybrid": "ibrido", "onsite": "in presenza"}
CONTRACT_LABEL = {"internship": "stage/tirocinio", "apprenticeship": "apprendistato", "fixed": "tempo determinato",
                  "permanent": "tempo indeterminato", "other": "altro (somministrazione, P.IVA...)"}


ADZUNA_URL = "https://www.adzuna.co.uk"
ADZUNA_LABEL = f"[Jobs by Adzuna]({ADZUNA_URL})"


def is_adzuna(r) -> bool:
    return (r["source"] or "").startswith("adzuna")


def _h(r) -> str:
    """Titolo-heading senza caratteri che rompono i link interni di Obsidian."""
    city = (r["location"] or "").split(",")[0]
    raw = f"{r['title']} - {r['company']}" + (f" ({city})" if city else "")
    for ch in '#|^:[]\\/%':
        raw = raw.replace(ch, " ")
    return " ".join(raw.split())


_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")
_EMBED = re.compile(r"!\[\[([^\]]*)\]\]")
_HTML_TAG = re.compile(r"<\s*/?\s*(img|iframe|embed|object|script|video|audio|source|link|style)\b[^>]*>", re.I)


def safe_text(text: str) -> str:
    """Testo di un annuncio reso innocuo per Obsidian: niente immagini esterne (tracker), incorporamenti ![[nota]] o tag HTML attivi.
    Le immagini diventano un normale collegamento testuale, gli incorporamenti perdono il punto esclamativo e le doppie parentesi."""
    text = _HTML_TAG.sub("", text or "")
    text = _EMBED.sub(lambda m: "(" + m.group(1) + ")", text)
    text = _IMG.sub(lambda m: f"[{m.group(1) or 'immagine'}] ({m.group(2)})", text)
    return text.replace("[[", "[ [")


def avail_label(r) -> str:
    """Riga 'Disponibilita'' del box dettagli."""
    if r["avail"] == "open":
        until = f", scade il {availability.day_label(r['valid_until'])}" if r["valid_until"] else ""
        return f"aperto, verificato il {availability.day_label((r['avail_checked'] or '')[:10])}{until}"
    return "non verificata"


def render(rows, *, title: str, closed_excluded: int = 0) -> str:
    now = datetime.now()
    cats = sorted({r["category"] for r in rows}, key=lambda c: ORDER.index(c) if c in ORDER else 99)
    out = [
        "---",
        f"created: {now:%Y-%m-%d}",
        "tags: [lavoro, annunci, jobshunter]",
        f"annunci: {len(rows)}",
        "---",
        f"# {title}",
        *([f"*Annunci Adzuna: {ADZUNA_LABEL}*"] if any(is_adzuna(r) for r in rows) else []),
        f"*Generato il {now:%d/%m/%Y alle %H:%M} da JobsHunter. {len(rows)} annunci." + (f" {closed_excluded} annunci chiusi esclusi." if closed_excluded else "") + "*",
        "",
        "## Indice",
        "| Score | Tipo | Ruolo | Azienda | Sede | Stipendio |",
        "|---:|:-:|---|---|---|---|",
    ]
    for r in rows:
        near = " 📍" if r["near_home"] else ""
        out.append(
            f"| {r['score']} | {ICON.get(r['category'], '')} {r['category']} | "
            f"[[#{_h(r)}\\|{r['title'][:50].replace('|', '/')}]] | {r['company']} | "
            f"{(r['location'] or '-')[:30]}{near} | {r['salary'] or '-'} |"
        )
    out.append("")

    for cat in cats:
        group = [r for r in rows if r["category"] == cat]
        out += [f"# {ICON.get(cat, '')} {cat} ({len(group)})", ""]
        for r in group:
            out += [
                f"## {_h(r)}",
                "",
                "> [!info] Dettagli",
                f"> - **Azienda:** {r['company']}",
                f"> - **Sede:** {r['location'] or '-'}{' 📍 vicino a casa' if r['near_home'] else ''}",
                f"> - **Score:** {r['score']} ({r['category']})",
                f"> - **Stipendio:** {r['salary'] or 'non indicato'}",
                f"> - **Modalità:** {MODE_LABEL.get(r['work_mode'], 'non indicata')}",
                f"> - **Contratto:** {CONTRACT_LABEL.get(r['contract'], 'non indicato')}",
                f"> - **Disponibilità:** {avail_label(r)}",
                f"> - **Pubblicato:** {(r['posted_at'] or '')[:10] or 'n/d'}",
                f"> - **Keyword:** {(r['matched'] or '').replace(',', ', ')}",
                f"> - **Fonte:** {r['source']}" + (f" ({ADZUNA_LABEL})" if is_adzuna(r) else ""),
                f"> - **ID:** `{r['uid'][:6]}`",
                "",
                f"👉 **[Apri annuncio e candidati]({r['url']})**",
                "",
                *([f"*{ADZUNA_LABEL}*", ""] if is_adzuna(r) else []),
                "- [ ] Candidato",
                "",
                safe_text(r["full_text"] or r["description"] or "_Testo non disponibile._"),
                "",
                "---",
                "",
            ]
    return "\n".join(out)


def write_report(rows, out_dir: Path, title: str, filename: str | None = None, closed_excluded: int = 0) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = title.replace("/", "-")
    name = filename or f"{stem} {datetime.now():%Y-%m-%d %H%M%S}.md"
    path = out_dir / name
    path.write_text(render(rows, title=title, closed_excluded=closed_excluded), encoding="utf-8")
    return path


def build_report(cfg: dict, db, *, category: str | None = None, min_score: int = 30, limit: int = 20,
                 near: bool = False, only_new: bool = False, group: str | None = None, geo: tuple | None = None, geo_label: str = "",
                 filters: dict | None = None, out_dir: str | None = None,
                 on_progress: Callable[[int, int], None] | None = None):
    """Scarica i testi mancanti, verifica che gli annunci siano aperti e scrive il report.

    Ritorna None se non c'e' nulla, altrimenti (path, n_annunci, n_con_testo, n_chiusi_esclusi, bloccato).
    path e' None se tutti gli annunci risultano chiusi."""
    rows = db.query(category=category, min_score=min_score, limit=limit, near_only=near, only_new=only_new, group=group, geo=geo, **(filters or {}))
    if not rows:
        return None
    # una sola richiesta per annuncio: serve sia il testo completo (se manca) sia la verifica che sia ancora aperto
    hours = cfg.get("availability", {}).get("recheck_hours", 24)
    todo = [r for r in rows if availability.checkable(r["source"], r["url"], cfg)
            and (not r["full_text"] or availability.is_stale(r["avail_checked"], hours))]
    blocked = False
    if todo:
        with net.client(timeout=20, follow_redirects=True) as c:
            for i, r in enumerate(todo, 1):
                res = availability.check(c, r["url"], r["source"])
                if res.blocked:
                    blocked = True
                    break
                availability.apply(db, r, res)
                if on_progress:
                    on_progress(i, len(todo))
                if i < len(todo):
                    time.sleep(availability.DELAY)
        rows = [db.get(r["uid"]) for r in rows]
    closed = [r for r in rows if r["avail"] == "closed"]
    rows = [r for r in rows if r["avail"] != "closed"]
    if not rows:
        return None, 0, 0, len(closed), blocked
    target = settings.resolve_path(out_dir or cfg.get("report", {}).get("dir", "reports"))
    label = " ".join(filter(None, ["Annunci", "Jooble" if group == "jooble" else "", category.upper() if category else "", "vicino a casa" if near else "", geo_label]))
    path = write_report(rows, target, title=label, closed_excluded=len(closed))
    return path, len(rows), sum(1 for r in rows if r["full_text"]), len(closed), blocked
