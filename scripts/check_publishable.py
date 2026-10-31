#!/usr/bin/env python3
"""Controllo prima della pubblicazione: il progetto non deve contenere segreti, dati personali o percorsi dell'autore.

Uso:  python scripts/check_publishable.py [cartella]      (esce con codice 1 se trova qualcosa)

Cerca (escluse le cartelle e i file ignorati da .gitignore, .venv e le cache):
  - segreti: chiavi Adzuna/Jooble plausibili assegnate a variabili, token noti (GitHub, Slack, AWS, chiavi private);
  - percorsi personali (/Users/<nome>, /home/<nome>, C:\\Users\\<nome>) e indirizzi email;
  - nomi specifici dell'autore;
  - config.toml, il database, settings.json, reports/ e cv.json devono essere in .gitignore e non essere tracciati.
Gli indirizzi email di esempio (example.org, example.com, invalid) e i segnaposto (x, name, utente...) sono ammessi.
"""
from __future__ import annotations

import fnmatch
import os
import re
import sys
from pathlib import Path

ALWAYS_SKIP_DIRS = {".git"}  # il resto si ignora solo se .gitignore lo esclude (quello che Git traccerebbe va controllato)
BINARY_SUFFIXES = {".db", ".pyc", ".png", ".jpg", ".jpeg", ".gif", ".icns", ".ico", ".pdf", ".docx", ".zip", ".woff", ".woff2"}  # immagini, PDF e simili: si ignorano
REQUIRED_IGNORED = ["config.toml", "jobshunter.db", "jobhunter.db", "settings.json", "reports/", "cv.json"]
MAX_BYTES = 50_000_000  # oltre questa dimensione il file non si legge ma si SEGNALA
# file che contengono di proposito esempi "cattivi" per provare questo stesso controllo
SELF_TEST_FILES = {"tests/test_phase5.py", "tests/qa/test_phase5_qa.py", "tests/qa/test_phase5_qa2.py"}

def forbidden_words(root: Path | None = None) -> list[str]:
    """Parole che identificano l'autore (nome, cognome, soprannomi...): NON stanno in questo file pubblico.
    Si leggono dalla variabile d'ambiente PUBLISH_FORBIDDEN_WORDS (separate da virgole) e dal file `.publish-forbidden.txt`
    (una per riga) nella cartella del progetto, che .gitignore esclude."""
    words = [w.strip() for w in os.environ.get("PUBLISH_FORBIDDEN_WORDS", "").split(",") if w.strip()]
    for base in {Path(__file__).resolve().parent.parent, root} - {None}:
        f = Path(base) / ".publish-forbidden.txt"
        if f.is_file():
            words += [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    return words


def _personal_regex(root: Path | None = None):
    words = forbidden_words(root)
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.I) if words else None


PRIVATE_IP = re.compile(r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}|169\.254\.\d{1,3}\.\d{1,3})\b")
OK_EMAIL_DOMAINS = {"example.org", "example.com", "example.net", "invalid", "localhost", "users.noreply.github.com", "evil.com", "127.0.0.1"}  # evil.com: indirizzi ostili usati nei test di sicurezza
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
USER_PATH = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)([A-Za-z0-9._-]+)")
OK_USERS = {"x", "name", "nome", "utente", "user", "you", "tu", "example", "esempio", "tuonome", "yourname", "username", "me", "shared", "Shared"}
SECRET_PATTERNS = [
    ("chiave Adzuna", re.compile(r"""app_key["']?\s*[:=]\s*["']([0-9a-f]{32})["']""", re.I)),
    ("ID Adzuna", re.compile(r"""app_id["']?\s*[:=]\s*["']([0-9a-f]{8})["']""", re.I)),
    ("chiave Jooble", re.compile(r"""api_key["']?\s*[:=]\s*["']([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})["']""", re.I)),
    ("chiave non quotata", re.compile(r"""\b(?:[A-Z0-9_]*(?:APP_KEY|API_KEY|APIKEY|SECRET|TOKEN|PASSWORD|PASSWD)[A-Z0-9_]*)\s*[:=]\s*["']?([A-Za-z0-9_\-.]{20,})["']?""", re.I)),
    ("chiave generica lunga", re.compile(r"""(?:api[_-]?key|secret|token|password|passwd)["']?\s*[:=]\s*["']([A-Za-z0-9_\-]{24,})["']""", re.I)),
    ("token GitHub", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}")),
    ("token Slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("chiave AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("chiave privata", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY")),
    ("token Anthropic/OpenAI", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{24,}")),
]
# segnaposto accettati come valore di una chiave nei test e negli esempi
PLACEHOLDER = re.compile(r"(?i)(x{3,}|0{6,}|fake|finta|test|prova|example|esempio|dummy|segreto|secret|zebra|a{6,}|placeholder|your|tuo|changeme|\*\*\*)")


def _gitignore_rules(root: Path) -> list[str]:
    f = root / ".gitignore"
    if not f.exists():
        return []
    return [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]  # le righe "!regola" riammettono un file (vince l'ultima regola che corrisponde, come in Git)


def _matches(rel: str, is_dir: bool, rule: str) -> bool:
    parts = rel.split("/")
    dir_only = rule.endswith("/")
    pat = rule.strip("/")
    if "/" in pat:  # ancorata alla radice
        return fnmatch.fnmatch(rel, pat) or rel.startswith(pat + "/")
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if dir_only and last and not is_dir:
            continue
        if fnmatch.fnmatch(part, pat):
            return True
    return False


def _ignored(rel: str, is_dir: bool, rules: list[str]) -> bool:
    ignored = False
    for rule in rules:  # come Git: l'ultima regola che corrisponde decide; "!regola" riammette
        if rule.startswith("!"):
            if ignored and _matches(rel, is_dir, rule[1:]):
                ignored = False
        elif _matches(rel, is_dir, rule):
            ignored = True
    return ignored


def iter_files(root: Path):
    rules = _gitignore_rules(root)
    stack = [root]
    while stack:
        d = stack.pop()
        for p in sorted(d.iterdir()):
            rel = p.relative_to(root).as_posix()
            if p.is_dir():
                if p.name in ALWAYS_SKIP_DIRS or _ignored(rel, True, rules):
                    continue
                stack.append(p)
            elif p.is_file() and not _ignored(rel, False, rules):
                yield p, rel


def scan_text(rel: str, text: str, personal=None) -> list[str]:
    problems = []
    personal = personal if personal is not None else _personal_regex()
    for n, line in enumerate(text.splitlines(), 1):
        for label, rx in SECRET_PATTERNS:
            m = rx.search(line)
            if m and not (m.groups() and PLACEHOLDER.search(m.group(1))):
                problems.append(f"{rel}:{n}: possibile segreto ({label})")
        for m in USER_PATH.finditer(line):
            if m.group(1) not in OK_USERS:
                problems.append(f"{rel}:{n}: percorso personale ({m.group(0)})")
        for m in EMAIL.finditer(line):
            domain = m.group(1).lower()
            if re.fullmatch(r"v?\d+(?:\.\d+)*", domain):  # "actions/checkout@v4.2.2": una versione, non un indirizzo
                continue
            if domain not in OK_EMAIL_DOMAINS and not domain.endswith((".example", ".invalid", ".test", "jooble.org")):  # jooble.org: host nei test (utente@host)
                problems.append(f"{rel}:{n}: indirizzo email ({m.group(0)})")
        if PRIVATE_IP.search(line):
            problems.append(f"{rel}:{n}: indirizzo IP privato o di rete personale ({PRIVATE_IP.search(line).group(0)})")
        if personal and personal.search(line):
            problems.append(f"{rel}:{n}: nome dell'autore")
    return problems


def check_gitignore(root: Path) -> list[str]:
    f = root / ".gitignore"
    if not f.exists():
        return [".gitignore mancante"]
    rules = _gitignore_rules(root)
    out = []
    for item in REQUIRED_IGNORED:
        is_dir = item.endswith("/")
        if not _ignored(item.rstrip("/") + ("/x" if is_dir else ""), False, rules) and not _ignored(item.rstrip("/"), is_dir, rules):
            out.append(f".gitignore non esclude {item}")
    return out


def _read(path: Path) -> str | None:
    """Testo del file (UTF-8, UTF-16 o Latin-1 come ripiego), o None se sembra binario."""
    data = path.read_bytes()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def check(root: Path) -> list[str]:
    problems = check_gitignore(root)
    me = Path(__file__).resolve()
    personal = _personal_regex(root)
    for path, rel in iter_files(root):
        if path.resolve() == me or rel in SELF_TEST_FILES or path.suffix.lower() in BINARY_SUFFIXES:
            continue
        if path.stat().st_size > MAX_BYTES:
            problems.append(f"{rel}: file troppo grande per essere controllato ({path.stat().st_size // 1_000_000} MB): verificalo a mano")
            continue
        text = _read(path)
        if text is None:
            problems.append(f"{rel}: file binario non riconosciuto: verificalo a mano o aggiungilo a .gitignore")
            continue
        problems += scan_text(rel, text, personal)
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parent.parent
    problems = check(root)
    if problems:
        print("Il progetto NON e' pronto per la pubblicazione:")
        for p in problems:
            print("  -", p)
        return 1
    print("OK: nessun segreto, percorso personale o email trovati; i file di dati personali sono ignorati.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
