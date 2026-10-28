"""Percorsi e impostazioni, uguali da terminale (./jh) e dentro JobsHunter.app.

- `home()` e' la cartella dei dati: JOBSHUNTER_HOME se impostata (l'app Mac la mette in
  ~/Library/Application Support/JobsHunter), altrimenti la cartella del progetto.
- Le modifiche fatte dalla scheda Impostazioni stanno in `settings.json` accanto a `config.toml`
  e vengono sovrapposte alla configurazione: cosi' `config.toml` (con i suoi commenti) non si riscrive mai.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tomllib
from pathlib import Path

from . import net

SOURCE_ROOT = Path(__file__).resolve().parent.parent


def bundled_root() -> Path:
    """Dove stanno i file inclusi nell'app (config.example.toml); in sviluppo e' la cartella del progetto."""
    return Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))


_warned_legacy_env = [False]


def home() -> Path:
    env = os.environ.get("JOBSHUNTER_HOME")
    if not env and os.environ.get("JOBHUNTER_HOME"):  # variabile del vecchio nome: ancora valida come ripiego, ma si avvisa
        env = os.environ["JOBHUNTER_HOME"]
        if not _warned_legacy_env[0]:
            _warned_legacy_env[0] = True
            import logging
            import sys as _sys

            logging.getLogger("jobshunter").warning("JOBHUNTER_HOME e' la variabile del vecchio nome: usa JOBSHUNTER_HOME")
            print("Avviso: JOBHUNTER_HOME e' la variabile del vecchio nome (JobHunter); usa JOBSHUNTER_HOME.", file=_sys.stderr)
    return Path(env).expanduser() if env else SOURCE_ROOT


def resolve_path(p: str | Path) -> Path:
    """Percorso assoluto: i relativi si intendono dentro la cartella dati."""
    p = Path(p).expanduser()
    return p if p.is_absolute() else home() / p


def default_config_path() -> Path:
    return home() / "config.toml"


def overrides_path(config_path: Path) -> Path:
    return config_path.with_name("settings.json")


# ---- impostazioni modificabili dalla GUI ----------------------------------------------------------
# (chiave, etichetta, tipo, segreto)
FIELDS = [
    ("sources.adzuna.enabled", "Adzuna attivo", "bool", False),
    ("sources.adzuna.full_text", "Scarica il testo completo degli annunci Adzuna", "bool", False),
    ("sources.adzuna.app_id", "Adzuna, Application ID", "text", False),
    ("sources.adzuna.app_key", "Adzuna, Application Key", "text", True),
    ("sources.jooble.enabled", "Jooble attivo", "bool", False),
    ("sources.jooble.host", "Jooble, host del tuo paese", "text", False),
    ("sources.jooble.api_key", "Jooble, chiave API", "text", True),
    ("search.internships", "Cerca anche stage e tirocini", "bool", False),
    ("schedule.enabled", "Scansione automatica", "bool", False),
    ("schedule.kind", "Frequenza", "text", False),
    ("schedule.times", "Orari", "text", False),
    ("schedule.hours", "Ogni quante ore", "int", False),
    ("schedule.notify", "Notifica quando ci sono novità", "bool", False),
    ("home", "Città di casa", "text", False),
    ("radius_km", "Raggio di ricerca (km)", "int", False),
    ("report.dir", "Cartella dei report (Obsidian)", "path", False),
    ("notify.topic", "Topic ntfy (notifiche)", "text", False),
    ("general.min_score", "Punteggio minimo da salvare", "int", False),
    ("net.contact", "Contatto nell'User-Agent (facoltativo)", "text", False),
    ("net.user_agent", "User-Agent personalizzato (avanzato)", "text", False),
]
FIELD_KEYS = {f[0] for f in FIELDS}
DEFAULTS = {"sources.adzuna.full_text": True, "search.internships": True, "schedule.enabled": False, "schedule.kind": "daily",
            "schedule.times": "09:00", "schedule.hours": 6, "schedule.notify": True}  # valori quando la configurazione non li indica
SECRET_KEYS = {f[0] for f in FIELDS if f[3]}


def _get(cfg: dict, dotted: str, default=None):
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _set(cfg: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = cfg
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def apply_overrides(cfg: dict, ov: dict) -> dict:
    for key, value in ov.items():
        if key not in FIELD_KEYS:
            continue
        if key == "home":
            orig = str(_get(cfg, "sources.adzuna.home", "")).lower()
            for src in ("adzuna", "jooble"):
                _set(cfg, f"sources.{src}.home", value)
            if not value:  # nessuna casa: niente bonus "vicino a casa" per nomi di una citta' che non e' la sua
                _set(cfg, "location.home_names", [])
            elif value.lower() != orig:  # citta' diversa: i nomi "di casa" originali non valgono piu'
                _set(cfg, "location.home_names", [value.lower()])
        elif key == "radius_km":
            for src in ("adzuna", "jooble"):
                _set(cfg, f"sources.{src}.radius_km", value)
        else:
            _set(cfg, key, value)
    return cfg


def load_overrides(config_path: Path) -> dict:
    p = overrides_path(config_path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_config(path: str | Path | None = None, *, create_if_missing: bool = False) -> dict:
    """Legge config.toml + settings.json. Con create_if_missing crea la config da config.example.toml."""
    p = Path(path) if path else default_config_path()
    if not p.exists():
        example = bundled_root() / "config.example.toml"
        if create_if_missing and example.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")  # copia atomica: un altro processo non legge mai un file a meta'
            shutil.copyfile(example, tmp)
            os.chmod(tmp, 0o600)  # puo' ricevere chiavi API
            if (p.parent / "jobhunter.db").exists() and not (p.parent / "jobshunter.db").exists():
                # dati migrati dal vecchio nome senza config: il database ha ancora il nome di prima
                text = tmp.read_text().replace('db_path = "jobshunter.db"', 'db_path = "jobhunter.db"')
                tmp.write_text(text)
            os.replace(tmp, p)
        else:
            raise FileNotFoundError(p)
    cfg = tomllib.loads(p.read_text())
    apply_overrides(cfg, load_overrides(p))
    cfg["_config_path"] = str(p)
    net.configure(cfg)  # User-Agent dichiarato per tutte le richieste in uscita
    return cfg


def save_overrides(config_path: Path, updates: dict, clear: list[str] | None = None) -> None:
    """Aggiorna settings.json (permessi 600: puo' contenere chiavi API)."""
    current = load_overrides(config_path)
    for k, v in updates.items():
        if k in FIELD_KEYS:
            current[k] = v
    for k in clear or []:
        current.pop(k, None)
    p = overrides_path(config_path)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    tmp.replace(p)


_SYSTEM_ROOTS = ("/etc", "/usr", "/bin", "/sbin", "/var", "/private", "/System", "/Library", "/Applications", "/dev", "/opt", "/cores")
_PRIVATE_OK = ("/private/tmp", "/private/var/folders")  # cartelle temporanee (anche dei test)
_HOME_SENSITIVE = (".ssh", ".gnupg", ".aws", ".config", "Library/LaunchAgents", "Library/Keychains", "Library/LaunchDaemons")


def check_report_dir(text: str) -> None:
    """Rifiuta come cartella dei report le zone di sistema e le cartelle sensibili dell'home (dopo aver risolto i collegamenti).
    Ammesse la home (Documenti, vault di Obsidian...), /Volumes e le cartelle temporanee. ValueError in italiano."""
    bad = ValueError("Questa cartella non va bene per i report (è una zona di sistema o contiene dati riservati): scegline una nei Documenti o nella tua vault.")
    if ".." in Path(text).parts or "\x00" in text:
        raise ValueError("percorso non valido (non può contenere \"..\" né caratteri strani)")
    try:
        real = resolve_path(text).resolve()
    except (OSError, RuntimeError, ValueError):
        raise ValueError("percorso non valido") from None
    r = str(real)
    if r == "/":
        raise bad
    home_dir = Path.home().resolve()
    for sub in _HOME_SENSITIVE:  # prima di tutto: vale anche se la home sta in una zona temporanea
        guarded = home_dir / sub
        if real == guarded or guarded in real.parents:
            raise bad
    if any(r == p or r.startswith(p + "/") for p in _PRIVATE_OK):
        return
    if any(r == p or r.startswith(p + "/") for p in _SYSTEM_ROOTS):
        raise bad


def clean_values(values: dict) -> dict:
    """Valida e pulisce i valori di Impostazioni (usata anche dalla guida di primo avvio). ValueError con messaggio in italiano.

    Un segreto lasciato vuoto significa "invariato" e non compare nel risultato."""
    kinds = {f[0]: f[2] for f in FIELDS}
    clean = {}
    for key, val in (values or {}).items():
        if key not in kinds:
            raise ValueError(f"impostazione sconosciuta: {key}")
        if key in SECRET_KEYS and (val is None or str(val).strip() == ""):
            continue
        if kinds[key] == "bool":
            clean[key] = bool(val)
        elif kinds[key] == "int":
            try:
                n = int(val)
            except (TypeError, ValueError):
                raise ValueError(f"{key}: numero non valido") from None
            lo, hi = (1, 3000) if key == "radius_km" else (0, 1000)
            clean[key] = max(lo, min(hi, n))
        else:
            text = ("" if val is None else str(val)).strip()[:500]  # null = vuoto, mai la stringa "None"
            if key == "net.contact":
                text = net.clean_contact(text)
            elif key == "net.user_agent":
                text = net.clean_user_agent(text)
            if kinds[key] == "path" and text:
                check_report_dir(text)
            clean[key] = text
    return clean


def restore_overrides(config_path: Path, snapshot: dict) -> None:
    """Rimette settings.json com'era (serve ad annullare un'operazione a più passi andata male)."""
    p = overrides_path(config_path)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def describe(cfg: dict) -> list[dict]:
    """Elenco dei campi con il valore attuale. I segreti non escono mai: solo 'impostato' si' o no."""
    out = []
    for key, label, kind, secret in FIELDS:
        if key == "home":
            val = _get(cfg, "sources.adzuna.home", "")
        elif key == "radius_km":
            val = _get(cfg, "sources.adzuna.radius_km", 100)
        elif key == "net.user_agent":
            val = _get(cfg, key, "")
        else:
            val = _get(cfg, key, DEFAULTS.get(key, "" if kind != "bool" else False))
        item = {"key": key, "label": label, "type": kind, "secret": secret}
        if secret:
            item["set"] = bool(val)
            item["value"] = ""
        else:
            item["value"] = val
        out.append(item)
    return out
