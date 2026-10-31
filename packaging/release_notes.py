"""Estrae da CHANGELOG.md la sezione di una versione (per le note della release). Uso: python packaging/release_notes.py 0.4.0"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def section(text: str, version: str) -> str:
    """Il testo sotto `## [X.Y.Z]` fino alla sezione successiva. Stringa vuota se la versione non c'e'."""
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", argv[1]):
        print("Uso: release_notes.py X.Y.Z", file=sys.stderr)
        return 2
    changelog = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    body = section(changelog.read_text(encoding="utf-8"), argv[1])
    if not body:
        print(f"Nessuna sezione per la versione {argv[1]} in CHANGELOG.md", file=sys.stderr)
        return 1
    sys.stdout.write(body + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
