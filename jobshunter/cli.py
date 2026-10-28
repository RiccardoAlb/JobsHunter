from __future__ import annotations

import csv
import os
import sys
import webbrowser
from pathlib import Path

import click
import threading
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from . import __version__, availability, cv as cvmod, cvfile, cvmatch, profiles as prof, settings
from .db import DB
from .fulltext import fetch_full
from .report import build_report
from .scanner import run_scan
from .notify import send_ntfy

console = Console()

CAT_STYLE = {
    "RED": "bold red", "BLUE": "bold dodger_blue1", "PURPLE": "bold magenta",
    "SYSADM": "bold yellow", "SEC": "bold cyan",
}

BANNER = r"""
    ___       _     _   _             _
   |_  |     | |   | | | |           | |
     | | ___ | |__ | |_| |_   _ _ __ | |_ ___ _ __
     | |/ _ \| '_ \|  _  | | | | '_ \| __/ _ \ '__|
 /\__/ / (_) | |_) | | | | |_| | | | | ||  __/ |
 \____/ \___/|_.__/\_| |_/\__,_|_| |_|\__\___|_|
"""


def banner() -> None:
    art = Text(BANNER, style="bold green")
    sub = Text(f"  Radar annunci di lavoro  v{__version__}\n", style="dim italic")
    console.print(Panel(Text.assemble(art, sub), border_style="green", box=box.DOUBLE_EDGE))


def load_cfg(path: str | None) -> dict:
    try:
        return settings.load_config(path, create_if_missing=bool(os.environ.get("JOBSHUNTER_HOME")))
    except FileNotFoundError as e:
        console.print(f"[red]Config non trovata:[/] {e}\n[dim]Copia config.example.toml in config.toml.[/]")
        sys.exit(1)


def open_db(cfg: dict) -> DB:
    return DB(settings.resolve_path(cfg["general"]["db_path"]))


def filter_args(company, where, mode, ral_min, no_unknown_ral, contract=()) -> dict:
    """Opzioni --company/--where/--mode/--ral-min in argomenti per DB.query."""
    out = {}
    if company:
        out["company"] = company
    if where:
        out["cities"] = ["" if w.lower() in ("generica", "generic") else w for w in where]
    if mode:
        out["modes"] = list(mode)
    if contract:
        out["contracts"] = list(contract)
    if ral_min:
        out["ral_min"], out["ral_unknown"] = ral_min, not no_unknown_ral
    return out


def geo_filter(city, km, include_generic):
    """Converte --city/--km in (tupla per il filtro, etichetta). Esce con errore se la citta' e' ignota."""
    if not city:
        return None, ""
    from .geo import lookup

    hit = lookup(city)
    if not hit:
        console.print(f"[red]Citta' non trovata:[/] {city}")
        sys.exit(1)
    return (hit["lat"], hit["lon"], km, include_generic), f"{city.title()} {km}km"


def cat_tag(cat: str) -> Text:
    return Text(f" {cat} ", style=CAT_STYLE.get(cat, "white") + " reverse")


def score_bar(score: int) -> Text:
    filled = min(score // 10, 10)
    color = "green" if score >= 40 else "yellow" if score >= 25 else "red"
    t = Text("█" * filled + "░" * (10 - filled), style=color)
    t.append(f" {score}", style="bold")
    return t


@click.group()
@click.option("-c", "--config", "config_path", default=None, help="Percorso config.toml")
@click.pass_context
def main(ctx, config_path):
    """JobsHunter: radar annunci di lavoro per profili di ricerca (cybersecurity, IT, sviluppo, dati, ufficio, vendite o su misura)."""
    ctx.obj = load_cfg(config_path)


@main.command()
@click.option("--port", default=8765, show_default=True, type=click.IntRange(1024, 65535), help="Porta locale (127.0.0.1)")
@click.option("--no-browser", is_flag=True, help="Non aprire il browser da solo")
@click.pass_obj
def gui(cfg, port, no_browser):
    """Apre la GUI nel browser (solo su 127.0.0.1; Ctrl+C per chiuderla)."""
    from .gui.app import serve

    serve(cfg["_config_path"], port, open_browser=not no_browser)


@main.command("app")
def app_window():
    """Apre la finestra nativa (come JobsHunter.app, senza impacchettare). Richiede macOS e `pip install pywebview`."""
    try:
        import webview  # noqa: F401
    except ImportError:
        console.print("[red]Manca pywebview.[/] Installalo con: [bold].venv/bin/pip install pywebview[/]  (solo macOS)")
        sys.exit(1)
    from .macapp import main as app_main

    app_main()


@main.command()
@click.option("--no-notify", is_flag=True, help="Non inviare notifiche ntfy")
@click.option("--profile", "profile_names", multiple=True, help="Cerca solo per questo profilo (si puo' ripetere); senza, tutti i profili attivi")
@click.pass_obj
def scan(cfg, no_notify, profile_names):
    """Interroga tutte le fonti attive e salva i nuovi annunci (Ctrl+C per fermare)."""
    db = open_db(cfg)
    profile_ids = None
    if profile_names:  # si controllano i nomi PRIMA di iniziare: un errore di battitura non deve far partire la scansione
        store = prof.ProfileStore(db)
        profile_ids = []
        for n in profile_names:
            p = store.get(n)
            if p is None:
                console.print(f"[red]Profilo non trovato:[/] {escape(n)}  [dim](vedi ./jh profiles list)[/]")
                sys.exit(1)
            profile_ids.append(p.id)
    banner()
    cancel = threading.Event()
    tasks: dict[str, int] = {}

    with Progress(
        SpinnerColumn(style="green"), TextColumn("[bold]{task.description:<12}"),
        BarColumn(bar_width=24, complete_style="green"), TextColumn("{task.fields[info]}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        def on_event(kind, d):
            if kind == "queued":
                tasks[d["name"]] = progress.add_task(d["name"], total=1, info="[dim]in coda")
            elif kind == "start":
                progress.update(tasks[d["name"]], info="[dim]fetch...")
            elif kind == "error":
                progress.update(tasks[d["name"]], completed=1, info="[red]errore")
            elif kind == "done":
                progress.update(tasks[d["name"]], completed=1,
                                info=f"[green]{d['read']}[/] letti, [cyan]{d['kept']}[/] rilevanti, [bold yellow]{d['new']}[/] nuovi")

        try:
            res = run_scan(cfg, db, cancel=cancel, on_event=on_event, profile_ids=profile_ids)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrotto (Ctrl+C).[/] Le fonti gia' completate sono state salvate.")
            return

    console.print()
    summary = Table.grid(padding=(0, 2))
    summary.add_row("Annunci letti", f"[bold]{res.read}[/]")
    summary.add_row("Rilevanti", f"[bold cyan]{res.kept}[/]")
    summary.add_row("Nuovi", f"[bold yellow]{res.new}[/]")
    console.print(Panel(summary, title="Riepilogo" + (f" (interrotto: {res.reason})" if res.cancelled else ""),
                        border_style="yellow" if res.cancelled else "cyan", expand=False))
    for n, e in res.errors:
        console.print(f"[red]x[/] {n}: {e}")

    notif = cfg.get("notify", {})
    if not no_notify and notif.get("topic"):
        rows = db.unnotified(notif.get("min_score", 40))
        if rows and send_ntfy(notif, rows):
            db.mark_notified([r["uid"] for r in rows])
            console.print(f"[green]Notifica inviata[/] ({len(rows)} annunci)")

    if res.new:
        console.print("\n[dim]Vedi i migliori con:[/] [bold]./jh list[/]")


@main.command("scan-auto")
@click.option("--no-notify", is_flag=True, help="Non inviare notifiche")
@click.pass_obj
def scan_auto(cfg, no_notify):
    """Scansione senza interfaccia (quella che lancia la pianificazione): blocco, cronologia e notifiche."""
    import logging

    from .autoscan import run_auto

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    res, info = run_auto(cfg, open_db(cfg), kind="auto", notify=not no_notify)
    if info.get("skipped"):
        logging.info("scansione saltata: %s", info["message"])
        return
    logging.info("scansione completata: %d letti, %d rilevanti, %d nuovi, %d chiusi, %d duplicati%s",
                 res.read, res.kept, res.new, res.closed_found, res.dups_new,
                 f", errori: {', '.join(n for n, _ in res.errors)}" if res.errors else "")


@main.group()
def schedule():
    """Scansione automatica su macOS (parte anche con l'app chiusa)."""


@schedule.command("status")
@click.pass_obj
def schedule_status(cfg):
    """Mostra se la scansione automatica e' attiva."""
    from . import scheduler

    st = scheduler.status(cfg)
    if not st["supported"]:
        console.print("[yellow]Disponibile solo su macOS.[/]")
        return
    state = "[green]attiva[/]" if st["installed"] else ("[yellow]impostata ma non caricata[/]" if st["enabled"] else "[dim]spenta[/]")
    when = f"ogni giorno alle {st['times']}" if st["kind"] == "daily" else f"ogni {st['hours']} ore"
    console.print(f"Scansione automatica: {state}  ({when}; notifiche {'si' if st['notify'] else 'no'})")
    if st["next"]:
        console.print(f"Prossima: {st['next']}")


@schedule.command("on")
@click.option("--at", "times", default="09:00", show_default=True, help="Orari, es. \"09:00, 18:30\" (da 1 a 4)")
@click.option("--every", "hours", type=click.Choice([str(h) for h in (1, 2, 3, 4, 6, 8, 12, 24)]), help="Invece degli orari: ogni N ore")
@click.option("--no-notify", is_flag=True, help="Nessuna notifica")
@click.pass_obj
def schedule_on(cfg, times, hours, no_notify):
    """Attiva la scansione automatica."""
    from . import scheduler

    try:
        parsed = scheduler.parse_times(times)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)
    kind = "every" if hours else "daily"
    settings.save_overrides(Path(cfg["_config_path"]), {
        "schedule.enabled": True, "schedule.kind": kind, "schedule.times": scheduler.format_times(parsed),
        "schedule.hours": int(hours or 6), "schedule.notify": not no_notify})
    scheduler.install(kind, parsed, int(hours or 6))
    console.print("[green]Scansione automatica attivata.[/] Si toglie con [bold]./jh schedule off[/].")


@schedule.command("off")
@click.pass_obj
def schedule_off(cfg):
    """Disattiva la scansione automatica."""
    from . import scheduler

    settings.save_overrides(Path(cfg["_config_path"]), {"schedule.enabled": False})
    scheduler.uninstall()
    console.print("Scansione automatica [bold]disattivata[/].")


@main.group()
def profiles():
    """Profili di ricerca: cosa cerchi (settore, paesi, livello, luogo)."""


def _profile_store(cfg) -> prof.ProfileStore:
    return prof.ProfileStore(open_db(cfg))


def _find_profile(store: prof.ProfileStore, name: str) -> prof.Profile:
    p = store.get(name)
    if p is None:
        console.print(f"[red]Profilo non trovato:[/] {escape(name)}  [dim](vedi ./jh profiles list)[/]")
        sys.exit(1)
    return p


def _where(p: prof.Profile) -> str:
    return f"{p.city} ({p.radius_km} km)" if p.city else "tutto il paese"


@profiles.command("list")
@click.pass_obj
def profiles_list(cfg):
    """Elenca i profili di ricerca."""
    store = _profile_store(cfg)
    table = Table(box=box.ROUNDED, border_style="green", header_style="bold green")
    for col in ("Nome", "Tipo", "Paesi", "Luogo", "Stato", "Annunci"):
        table.add_column(col)
    for p in store.list():
        table.add_row(escape(p.name), prof.PRESETS[p.preset]["label"], ", ".join(p.countries), escape(_where(p)),
                      "[green]attivo[/]" if p.active else "[dim]spento[/]", str(store.job_count(p.id)))
    console.print(table)


@profiles.command("show")
@click.argument("name")
@click.pass_obj
def profiles_show(cfg, name):
    """Mostra tutte le impostazioni di un profilo."""
    store = _profile_store(cfg)
    p = _find_profile(store, name)
    rows = [("Nome", p.name), ("Tipo", prof.PRESETS[p.preset]["label"]), ("Stato", "attivo" if p.active else "spento"),
            ("Titoli", ", ".join(p.titles) or "(quelli del tipo di profilo)"),
            ("Parole extra", ", ".join(f"{k}={v}" for k, v in p.include.items()) or "-"),
            ("Parole da escludere", ", ".join(p.exclude) or "-"), ("Livello", p.seniority),
            ("Contratti", ", ".join(p.contracts) or "tutti"),
            ("Paesi", ", ".join(f"{c} ({prof.COUNTRIES[c]['name']})" for c in p.countries)),
            ("Categorie", "; ".join(f"{c['label']}: {', '.join(c['terms'][:6])}{'...' if len(c['terms']) > 6 else ''}" for c in p.categories)
             or "(quelle del tipo di profilo, non modificabili: usa 'profiles categories --restore-preset' per copiarle)"),
            ("Luogo", _where(p)), ("Remoto", "si" if p.remote else "no"), ("Stage", "si" if p.internships else "no"),
            ("Annunci", str(store.job_count(p.id)))]
    grid = Table.grid(padding=(0, 2))
    for k, v in rows:
        grid.add_row(f"[bold]{k}[/]", escape(v))
    console.print(Panel(grid, title=escape(p.name), border_style="green", expand=False))


def _parse_cats(items) -> list[dict]:
    out = []
    for it in items:
        label, sep, words = it.partition("=")
        if not sep:
            raise prof.ProfileError(f"categorie: scrivi ETICHETTA=parola1,parola2 (manca il segno = in «{it[:30]}»)")
        out.append({"label": label, "terms": [w for w in words.split(",")]})
    return out


@profiles.command("categories")
@click.argument("name")
@click.option("--set", "cats", multiple=True, help="Sostituisce le categorie: \"ETICHETTA=parola1,parola2\" (si puo' ripetere)")
@click.option("--add", "add_cats", multiple=True, help="Aggiunge o sostituisce UNA categoria \"ETICHETTA=parola1,parola2\"")
@click.option("--remove", "remove", multiple=True, help="Toglie la categoria con questa etichetta")
@click.option("--restore-preset", is_flag=True, help="Ripristina le categorie del tipo di profilo")
@click.option("--clear", is_flag=True, help="Toglie tutte le categorie")
@click.pass_obj
def profiles_categories(cfg, name, cats, add_cats, remove, restore_preset, clear):
    """Mostra o cambia le categorie personali di un profilo (poi ricalcola gli annunci gia' salvati)."""
    from .rescore import rescore

    store = _profile_store(cfg)
    p = _find_profile(store, name)
    current = [dict(c) for c in p.categories]
    changed = False
    try:
        if clear:
            current, changed = [], True
        if restore_preset:
            current, changed = prof.preset_categories(p.preset, cfg), True
        if cats:
            current, changed = _parse_cats(cats), True
        for c in _parse_cats(add_cats):
            label = prof.normalize_label(c["label"])
            current = [x for x in current if x["label"] != label] + [c]
            changed = True
        for r_ in remove:
            label = prof.normalize_label(r_)
            if not any(x["label"] == label for x in current):
                raise prof.ProfileError(f"categorie: non c'e' nessuna categoria «{label}»")
            current = [x for x in current if x["label"] != label]
            changed = True
        if changed:
            data = p.to_dict()
            data["categories"] = current
            new = store.update(p.id, data)
            store.db.snapshot()
            n = rescore(store.db, cfg, [p.id])
            console.print(f"[green]Categorie aggiornate[/] [dim]({n} annunci ricalcolati)[/]")
            p = new
    except prof.ProfileError as e:
        console.print(f"[red]Categorie non valide:[/] {escape(str(e))}")
        sys.exit(1)
    if not p.categories:
        console.print("[dim]Nessuna categoria personale: valgono quelle del tipo di profilo.[/]")
    for c in p.categories:
        console.print(f"[bold]{escape(c['label'])}[/]: {escape(', '.join(c['terms']))}")


@profiles.command("add")
@click.option("--name", "name", required=True, help="Nome del profilo (unico)")
@click.option("--preset", default="custom", show_default=True, type=click.Choice(list(prof.PRESETS)), help="Tipo di profilo")
@click.option("--title", "titles", multiple=True, help="Lavoro cercato (si puo' ripetere); obbligatorio con --preset custom")
@click.option("--exclude", "exclude", multiple=True, help="Parola che scarta l'annuncio se e' nel titolo (si puo' ripetere)")
@click.option("--country", "countries", multiple=True, help="Codice paese, es. it, gb, de (si puo' ripetere; default it)")
@click.option("--city", default="", help="Citta' di riferimento (vuota = tutto il paese)")
@click.option("--km", type=int, default=100, show_default=True, help="Raggio in km attorno a --city")
@click.option("--seniority", default="any", show_default=True, help="any, junior, mid o senior")
@click.option("--no-remote", is_flag=True, help="Non accettare annunci da remoto")
@click.option("--no-internships", is_flag=True, help="Non cercare stage e tirocini")
@click.option("--category", "cats", multiple=True, help="Categoria personale \"ETICHETTA=parola1,parola2\" (si puo' ripetere)")
@click.pass_obj
def profiles_add(cfg, name, preset, titles, exclude, countries, city, km, seniority, no_remote, no_internships, cats):
    """Crea un profilo di ricerca."""
    store = _profile_store(cfg)
    data = {"name": name, "preset": preset, "titles": list(titles), "exclude": list(exclude),
            "countries": list(countries) or ["it"], "location": {"city": city, "radius_km": km},
            "seniority": seniority, "remote": not no_remote, "internships": not no_internships}
    try:
        if cats:
            data["categories"] = _parse_cats(cats)
        p = store.add(data, cfg)
    except prof.ProfileError as e:
        console.print(f"[red]Profilo non valido:[/] {escape(str(e))}")
        sys.exit(1)
    from .rescore import rescore

    n = rescore(store.db, cfg, [p.id])
    console.print(f"[green]Profilo creato:[/] {escape(p.name)}  [dim]({n} annunci già salvati risultano pertinenti)[/]")


@profiles.command("rm")
@click.argument("name")
@click.pass_obj
def profiles_rm(cfg, name):
    """Elimina un profilo (gli annunci restano)."""
    store = _profile_store(cfg)
    p = _find_profile(store, name)
    try:
        store.delete(p.id)
    except prof.ProfileError as e:
        console.print(f"[red]Non posso eliminarlo:[/] {escape(str(e))}")
        sys.exit(1)
    console.print(f"Profilo [bold]{escape(p.name)}[/] eliminato.")


def _set_active(cfg, name: str, active: bool) -> None:
    store = _profile_store(cfg)
    p = _find_profile(store, name)
    store.set_active(p.id, active)
    store.db.refresh_best()
    console.print(f"Profilo [bold]{escape(p.name)}[/] {'acceso' if active else 'spento'}.")


@profiles.command("on")
@click.argument("name")
@click.pass_obj
def profiles_on(cfg, name):
    """Accende un profilo (viene cercato a ogni scansione)."""
    _set_active(cfg, name, True)


@profiles.command("off")
@click.argument("name")
@click.pass_obj
def profiles_off(cfg, name):
    """Spegne un profilo (non viene cercato e i suoi annunci non si vedono)."""
    _set_active(cfg, name, False)


@main.command("list")
@click.option("-t", "--type", "category", help="Categoria (BLUE, RED, SYSADM, SEC, PURPLE, oppure il gruppo di un altro profilo)")
@click.option("--profile", "profile_name", help="Solo gli annunci di questo profilo (col suo punteggio)")
@click.option("-s", "--min-score", default=0, help="Score minimo")
@click.option("-n", "--limit", default=25)
@click.option("--status", type=click.Choice(["new", "seen", "applied", "discarded"]))
@click.option("-q", "--search", help="Cerca in titolo/azienda")
@click.option("--near", is_flag=True, help="Solo annunci vicini a casa (raggio da home)")
@click.option("--source", "group", type=click.Choice(["main", "jooble", "all"]), default="main", show_default=True,
              help="main = fonti con testo completo, jooble = solo anteprime Jooble")
@click.option("--city", help="Citta' di riferimento per il raggio (es. Milano)")
@click.option("--km", default=100, show_default=True, help="Raggio in km attorno a --city")
@click.option("--no-generic", is_flag=True, help="Con --city: escludi annunci con sede generica o remoti")
@click.option("--company", help="Solo questa azienda (anche parte del nome)")
@click.option("--where", "where", multiple=True, help="Solo questa citta' (si puo' ripetere); \"generica\" = sede generica")
@click.option("--mode", "mode", multiple=True, type=click.Choice(["remote", "hybrid", "onsite", "unknown"]), help="Modalita' di lavoro (si puo' ripetere)")
@click.option("--ral-min", type=int, default=0, help="RAL minima in euro (es. 30000)")
@click.option("--no-unknown-ral", is_flag=True, help="Con --ral-min: escludi gli annunci senza RAL indicata")
@click.option("--contract", "contract", multiple=True, type=click.Choice(["internship", "apprenticeship", "fixed", "permanent", "other", "unknown"]), help="Tipo di contratto (si puo' ripetere), es. --contract internship per gli stage")
@click.option("--closed", is_flag=True, help="Mostra anche gli annunci verificati come chiusi")
@click.option("--cv-min", type=click.IntRange(0, 100), default=0, help="Solo annunci con affinita' col CV almeno questa (serve un CV: ./jh cv set)")
@click.option("--by-cv", is_flag=True, help="Ordina per affinita' col CV invece che per punteggio")
@click.pass_obj
def list_(cfg, category, profile_name, min_score, limit, status, search, near, group, city, km, no_generic,
          company, where, mode, ral_min, no_unknown_ral, contract, closed, cv_min, by_cv):
    """Mostra gli annunci ordinati per score."""
    db = open_db(cfg)
    pid = None
    if profile_name:
        p = prof.ProfileStore(db).get(profile_name)
        if p is None:
            console.print(f"[red]Profilo non trovato:[/] {escape(profile_name)}")
            sys.exit(1)
        pid = p.id
    cprof = cvmod.current()
    if (cv_min or by_cv) and cprof is None:
        console.print("[red]Per usare --cv-min e --by-cv serve un CV:[/] [bold]./jh cv set <file>[/]")
        sys.exit(1)
    if cprof is not None:
        cvmatch.recompute(db, cprof)  # solo cio' che e' nuovo o cambiato
    rows = db.query(profile=pid, category=category, min_score=min_score, status=status, limit=limit, search=search, near_only=near,
                                 cv_min=cv_min, cv_version=cprof.version if cprof else None, order_cv=by_cv,
                                 group=None if group == "all" else group,
                                 geo=geo_filter(city, km, not no_generic)[0], include_closed=closed,
                                 **filter_args(company, where, mode, ral_min, no_unknown_ral, contract))
    if not rows:
        console.print("[yellow]Nessun annuncio. Lancia prima[/] [bold]jobshunter scan[/]")
        return
    table = Table(box=box.ROUNDED, border_style="green", header_style="bold green", title_style="bold")
    table.add_column("ID", style="dim")
    table.add_column("Tipo", justify="center")
    table.add_column("Score")
    if cprof is not None:
        table.add_column("CV", justify="right")
    table.add_column("Titolo", overflow="fold", max_width=44)
    table.add_column("Azienda", style="cyan", overflow="fold", max_width=18)
    table.add_column("Dove", style="dim", overflow="fold", max_width=28)
    table.add_column("St.", justify="center")
    st_icon = {"new": "[bold yellow]●[/]", "seen": "[dim]○[/]", "applied": "[green]✔[/]", "discarded": "[red]✘[/]"}
    cvs = cvmatch.scores_for(db, [r["uid"] for r in rows], cprof.version) if cprof is not None else {}
    for r in rows:
        extra = []
        if cprof is not None:
            c = cvs.get(r["uid"])
            extra = [("?" if c is None else f"{c[0]}" + ("~" if c[1] == "anteprima" else ""))]
        table.add_row(r["uid"][:6], cat_tag(r["category"]), score_bar(r["score"]), *extra, ("[chiuso] " if r["avail"] == "closed" else "") + r["title"],
                      r["company"], ((r["location"] or "-").split(",")[0][:22] + (" 📍" if r["near_home"] else "")), st_icon.get(r["status"], ""))
    console.print(table)
    console.print("[dim]jobshunter show <ID> · open <ID> · mark <ID> applied|discarded[/]")
    if cprof is not None:
        console.print("[dim]CV: affinita' col tuo CV (0-100); \"~\" = basata su anteprima, quindi prudente.[/]")


def _find(cfg, prefix):
    db = open_db(cfg)
    row = db.get(prefix)
    if not row:
        console.print(f"[red]ID non trovato o ambiguo:[/] {prefix}")
        sys.exit(1)
    return db, row


@main.command()
@click.argument("job_id")
@click.pass_obj
def show(cfg, job_id):
    """Dettaglio di un annuncio (lo segna come visto)."""
    db, r = _find(cfg, job_id)
    head = Text.assemble(cat_tag(r["category"]), "  ", (r["title"], "bold"))
    body = Text()
    body.append(f"{r['company']}", style="cyan")
    body.append(f"  ·  {r['location'] or '-'}  ·  fonte: {r['source']}\n", style="dim")
    body.append("Score ").append(score_bar(r["score"])).append("\n")
    body.append(f"Match: {r['matched'].replace(',', ', ')}\n\n", style="green")
    if r["salary"]:
        body.append(f"Stipendio: {r['salary']}\n", style="bold green")
    body.append((r["full_text"] or r["description"] or "(nessuna descrizione)")[:1800] + "\n\n")
    body.append(r["url"], style="underline blue")
    console.print(Panel(body, title=head, border_style="green"))
    if r["status"] == "new":
        db.set_status(r["uid"], "seen")


@main.command("open")
@click.argument("job_id")
@click.pass_obj
def open_(cfg, job_id):
    """Apre l'annuncio nel browser."""
    db, r = _find(cfg, job_id)
    webbrowser.open(r["url"])
    if r["status"] == "new":
        db.set_status(r["uid"], "seen")


@main.command()
@click.argument("job_id")
@click.argument("status", type=click.Choice(["new", "seen", "applied", "discarded"]))
@click.pass_obj
def mark(cfg, job_id, status):
    """Cambia stato: applied / discarded / seen / new."""
    db, r = _find(cfg, job_id)
    db.set_status(r["uid"], status)
    console.print(f"[green]ok[/] {r['title']} -> [bold]{status}[/]")


@main.command()
@click.pass_obj
def stats(cfg):
    """Statistiche per categoria."""
    rows = open_db(cfg).stats()
    table = Table(box=box.SIMPLE_HEAD, header_style="bold green")
    for col in ("Categoria", "Annunci", "Score medio", "Top"):
        table.add_column(col, justify="right" if col != "Categoria" else "left")
    for r in rows:
        table.add_row(cat_tag(r["category"]), str(r["n"]), str(r["avg"]), str(r["top"]))
    console.print(table)


@main.command()
@click.option("-t", "--type", "category", help="Categoria (BLUE, RED... oppure una categoria personale di un profilo)")
@click.option("-s", "--min-score", default=30, show_default=True)
@click.option("-n", "--limit", default=20, show_default=True)
@click.option("--near", is_flag=True, help="Solo annunci vicini a casa")
@click.option("--new", "only_new", is_flag=True, help="Solo annunci non ancora visti")
@click.option("--source", "group", type=click.Choice(["main", "jooble", "all"]), default="main", show_default=True)
@click.option("--city", help="Citta' di riferimento per il raggio (es. Milano)")
@click.option("--km", default=100, show_default=True, help="Raggio in km attorno a --city")
@click.option("--no-generic", is_flag=True, help="Con --city: escludi annunci con sede generica o remoti")
@click.option("--company", help="Solo questa azienda (anche parte del nome)")
@click.option("--where", "where", multiple=True, help="Solo questa citta' (si puo' ripetere); \"generica\" = sede generica")
@click.option("--mode", "mode", multiple=True, type=click.Choice(["remote", "hybrid", "onsite", "unknown"]), help="Modalita' di lavoro (si puo' ripetere)")
@click.option("--ral-min", type=int, default=0, help="RAL minima in euro (es. 30000)")
@click.option("--no-unknown-ral", is_flag=True, help="Con --ral-min: escludi gli annunci senza RAL indicata")
@click.option("--contract", "contract", multiple=True, type=click.Choice(["internship", "apprenticeship", "fixed", "permanent", "other", "unknown"]), help="Tipo di contratto (si puo' ripetere), es. --contract internship per gli stage")
@click.option("-o", "--out-dir", default=None, help="Cartella di output (default: [report].dir)")
@click.pass_obj
def report(cfg, category, min_score, limit, near, only_new, group, city, km, no_generic,
           company, where, mode, ral_min, no_unknown_ral, contract, out_dir):
    """Genera un report Markdown (Obsidian) con il testo completo degli annunci."""
    db = open_db(cfg)
    geo, geo_label = geo_filter(city, km, not no_generic)
    with Progress(SpinnerColumn(style="green"), TextColumn("[bold]Scarico testi completi"),
                  BarColumn(bar_width=24, complete_style="green"),
                  TextColumn("{task.completed}/{task.total}"), console=console, transient=True) as progress:
        task = progress.add_task("", total=None)

        def on_progress(i, n):
            progress.update(task, completed=i, total=n)

        result = build_report(cfg, db, category=category, min_score=min_score, limit=limit,
                              near=near, only_new=only_new, group=None if group == "all" else group,
                              geo=geo, geo_label=geo_label, filters=filter_args(company, where, mode, ral_min, no_unknown_ral, contract),
                              out_dir=out_dir, on_progress=on_progress)
    if not result:
        console.print("[yellow]Nessun annuncio con questi filtri.[/]")
        return
    path, n, full, closed, blocked = result
    if blocked:
        console.print("[yellow]Il sito ha limitato le richieste: alcuni annunci non sono stati verificati.[/]")
    if path is None:
        console.print(f"[yellow]Tutti gli annunci ({closed}) risultano chiusi: nessun report creato.[/]")
        return
    extra = f"\n[yellow]{closed}[/] annunci chiusi esclusi" if closed else ""
    console.print(Panel(f"[bold green]{n}[/] annunci ([cyan]{full}[/] con testo completo){extra}\n[underline]{path}[/]",
                        title="Report creato", border_style="green", expand=False))


@main.command()
@click.option("-n", "--limit", default=40, show_default=True, help="Quanti annunci controllare")
@click.option("--force", is_flag=True, help="Ricontrolla anche quelli verificati da poco o gia' chiusi")
@click.argument("ids", nargs=-1)
@click.pass_obj
def check(cfg, limit, force, ids):
    """Verifica quali annunci sono ancora aperti (uno ogni 2 secondi; si ferma se il sito limita le richieste)."""
    db = open_db(cfg)
    uids = None
    if ids:
        uids = []
        for i in ids:
            row = db.get(i)
            if not row:
                console.print(f"[red]ID non trovato:[/] {i}")
                sys.exit(1)
            uids.append(row["uid"])
    hours = cfg.get("availability", {}).get("recheck_hours", 24)
    todo = len(db.to_check(hours=hours, limit=limit, uids=uids, force=force))
    if not todo:
        console.print("[green]Niente da verificare[/] (tutti controllati da meno di %d ore, oppure non verificabili)." % hours)
        return
    colors = {"open": "green", "closed": "red", "unknown": "yellow"}
    labels = {"open": "aperto", "closed": "CHIUSO", "unknown": "non verificato"}
    with Progress(SpinnerColumn(style="green"), TextColumn("[bold]Verifico"), BarColumn(bar_width=24, complete_style="green"),
                  TextColumn("{task.completed}/{task.total}"), TextColumn("{task.fields[last]}"), console=console) as progress:
        task = progress.add_task("", total=todo, last="")

        def on_progress(i, n, row, res):
            progress.update(task, completed=i, last=f"[{colors[res.state]}]{labels[res.state]}[/] {row['title'][:34]}")

        try:
            out = availability.run_check(db, cfg, uids=uids, limit=limit, force=force, on_progress=on_progress)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrotto.[/] Gli annunci gia' controllati sono stati salvati.")
            return
    console.print(Panel(f"[green]{out['open']}[/] aperti   [red]{out['closed']}[/] chiusi   [yellow]{out['unknown']}[/] non verificati",
                        title=f"Verificati {out['checked']} annunci", border_style="red" if out["closed"] else "green", expand=False))
    if out["blocked"]:
        console.print("[yellow]Il sito sta limitando le richieste: controllo fermato.[/] Riprova tra un po', senza insistere.")


@main.command("app-import")
@click.option("--force", is_flag=True, help="Sovrascrive i dati gia' presenti nell'app")
def app_import(force):
    """Copia configurazione, impostazioni e database di questo progetto nei dati dell'app Mac.

    Gli originali restano dove sono. Senza --force non sovrascrive un database gia' presente nell'app."""
    import shutil
    import sqlite3

    from . import migrate
    from .macapp import APP_DIR

    if APP_DIR == migrate.support_dir():  # prima i dati del vecchio nome (JobHunter): altrimenti l'importazione li bloccherebbe per sempre
        _, outcome = migrate.migrate_app_data()
        if outcome == "copied":
            console.print("[green]Copiati i dati del vecchio nome (JobHunter) nella nuova cartella dell'app.[/]")
    src_db = settings.resolve_path(settings.load_config(None)["general"]["db_path"])
    src_cfg = settings.default_config_path()
    dst_db = APP_DIR / Path(settings.load_config(None)["general"]["db_path"]).name
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if dst_db.exists() and dst_db.stat().st_size > 0 and not force:
        console.print(f"[yellow]L'app ha gia' un database[/] ({dst_db}). Usa --force per sovrascriverlo.")
        sys.exit(1)
    if not src_db.exists():
        console.print(f"[red]Database di origine non trovato:[/] {src_db}")
        sys.exit(1)

    # copia coerente del database (anche se e' in uso) tramite l'API di backup di SQLite
    src, dst = sqlite3.connect(src_db), sqlite3.connect(dst_db)
    with dst:
        src.backup(dst)
    src.close(); dst.close()
    os.chmod(dst_db, 0o600)
    shutil.copyfile(src_cfg, APP_DIR / "config.toml")
    os.chmod(APP_DIR / "config.toml", 0o600)
    ov = settings.overrides_path(src_cfg)
    if ov.exists():
        shutil.copyfile(ov, APP_DIR / "settings.json")
        os.chmod(APP_DIR / "settings.json", 0o600)
    console.print(Panel(f"Dati copiati in [underline]{APP_DIR}[/]\n[dim]Gli originali sono rimasti dove erano.[/]",
                        title="Importazione completata", border_style="green", expand=False))


def _csv_safe(v):
    """Neutralizza le "formule" (=, +, -, @) che Excel e Numbers eseguirebbero aprendo il CSV."""
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


@main.command()
@click.argument("out", default="jobs.csv")
@click.option("-s", "--min-score", default=0)
@click.pass_obj
def export(cfg, out, min_score):
    """Esporta gli annunci in CSV."""
    rows = open_db(cfg).query(min_score=min_score, limit=100000)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["score", "category", "title", "company", "location", "status", "url", "attribution"])
        for r in rows:
            attr = "Jobs by Adzuna (https://www.adzuna.co.uk)" if (r["source"] or "").startswith("adzuna") else ""
            w.writerow([_csv_safe(v) for v in (r["score"], r["category"], r["title"], r["company"], r["location"], r["status"], r["url"], attr)])
    console.print(f"[green]{len(rows)} annunci esportati in[/] {out}")


# ------------------------------------------------------------------ il tuo CV ----
def _cv_progress_recompute(db, cprof) -> int:
    with Progress(SpinnerColumn(), TextColumn("Confronto gli annunci col CV"), BarColumn(), TextColumn("{task.completed}/{task.total}"),
                  TimeElapsedColumn(), console=console, transient=True) as bar:
        task = bar.add_task("cv", total=None)
        return cvmatch.recompute(db, cprof, progress=lambda i, n: bar.update(task, completed=i, total=n))


def _print_cv_summary(prof) -> None:
    s = cvmod.summary(prof)
    t = Table(box=box.ROUNDED, border_style="green", show_header=False)
    t.add_row("Caricato", s["updated"][:10] + f" ({s['source']})")
    t.add_row("Parole", str(s["words"]))
    t.add_row("Anni di esperienza stimati", "non riesco a stimarli" if s["years"] is None else str(s["years"]).replace(".", ","))
    t.add_row("Lingue", ", ".join(l["lang"] + (f" {l['level']}" if l["level"] else "") for l in s["languages"]) or "nessuna indicata")
    t.add_row("Competenze", ", ".join(s["skills"]) or "nessuna riconosciuta")
    if s["skills_manual"]:
        t.add_row("Aggiunte a mano", ", ".join(s["skills_manual"]))
    if s["skills_removed"]:
        t.add_row("Tolte a mano", ", ".join(s["skills_removed"]))
    console.print(t)


@main.group("cv")
def cv_group():
    """Il tuo CV: confronto locale con gli annunci (il CV non esce mai dal tuo Mac)."""


@cv_group.command("set")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path))
@click.pass_obj
def cv_set(cfg, file):
    """Carica (o sostituisce) il CV da un file .pdf, .docx, .txt o .md. Si tiene solo il testo, non il file."""
    try:
        if file.stat().st_size > cvfile.MAX_BYTES:
            raise cvfile.CvError("Il file e' troppo grande: il limite e' 5 MB.")
        with open(file, "rb") as f:
            text, source = cvfile.extract(f.read(cvfile.MAX_BYTES + 1), file.name)
    except cvfile.CvError as e:
        console.print(f"[red]{escape(str(e))}[/]")
        sys.exit(1)
    cvmod.save_text(text, source)
    prof = cvmod.current()
    console.print(f"[green]CV caricato.[/] Ne ho tenuto solo il testo, in {escape(str(cvmod.path()))} (permessi riservati).")
    _print_cv_summary(prof)
    n = _cv_progress_recompute(open_db(cfg), prof)
    console.print(f"[dim]Confrontati {n} annunci.[/]")


@cv_group.command("show")
@click.pass_obj
def cv_show(cfg):
    """Mostra cosa ho riconosciuto nel CV (mai il testo del CV)."""
    prof = cvmod.current()
    if prof is None:
        console.print("[yellow]Nessun CV caricato.[/] Usa [bold]./jh cv set <file>[/]")
        return
    _print_cv_summary(prof)


@cv_group.command("clear")
@click.option("-y", "--yes", is_flag=True, help="Non chiedere conferma")
@click.pass_obj
def cv_clear(cfg, yes):
    """Elimina il CV e tutti i confronti (cancella davvero il file)."""
    if cvmod.current() is None and not cvmod.path().exists():
        console.print("[yellow]Nessun CV da eliminare.[/]")
        return
    if not yes and not click.confirm("Elimino il CV e i confronti con gli annunci?"):
        return
    cvmod.delete()
    cvmatch.clear(open_db(cfg))
    console.print("[green]CV eliminato.[/]")


@cv_group.command("match")
@click.option("-n", "--limit", default=15, show_default=True, help="Quanti annunci mostrare")
@click.option("--force", is_flag=True, help="Rifai tutti i confronti anche se aggiornati")
@click.pass_obj
def cv_match(cfg, limit, force):
    """Confronta gli annunci col CV e mostra i piu' affini."""
    prof = cvmod.current()
    if prof is None:
        console.print("[yellow]Nessun CV caricato.[/] Usa [bold]./jh cv set <file>[/]")
        sys.exit(1)
    db = open_db(cfg)
    if force:
        cvmatch.clear(db)
    n = _cv_progress_recompute(db, prof)
    console.print(f"[dim]Confrontati {n} annunci.[/]")
    rows = db.query(limit=limit, cv_version=prof.version, order_cv=True)
    if not rows:
        console.print("[yellow]Nessun annuncio. Lancia prima[/] [bold]./jh scan[/]")
        return
    sc = cvmatch.scores_for(db, [r["uid"] for r in rows], prof.version)
    table = Table(box=box.ROUNDED, border_style="green", header_style="bold green")
    table.add_column("ID", style="dim")
    table.add_column("CV", justify="right")
    table.add_column("Titolo", overflow="fold", max_width=40)
    table.add_column("Azienda", style="cyan", overflow="fold", max_width=18)
    table.add_column("In comune", overflow="fold", max_width=30)
    for r in rows:
        m = cvmatch.for_job(db, prof, r["uid"])
        e = m["explain"]
        table.add_row(r["uid"][:6], f"{m['score']}" + ("~" if m["base"] == "anteprima" else ""), r["title"], r["company"],
                      ", ".join(e["in_comune"][:5]) or "-")
    console.print(table)
    console.print("[dim]\"~\" = basata su anteprima, quindi prudente. Dettagli di un annuncio: ./jh show <ID>[/]")


if __name__ == "__main__":
    main()
