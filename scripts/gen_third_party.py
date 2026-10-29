#!/usr/bin/env python3
"""Genera THIRD_PARTY_NOTICES.md leggendo i metadati dei pacchetti installati nel venv (nessuna rete).

Uso:  .venv/bin/python scripts/gen_third_party.py            (riscrive THIRD_PARTY_NOTICES.md)
Include le dipendenze dirette (pyproject.toml) e quelle transitive installate, piu' gli strumenti facoltativi
usati solo per costruire l'app Mac (se presenti).
"""
from __future__ import annotations

import re
import sys
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_ONLY = ["pywebview", "pyinstaller", "pillow"]


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(req: str) -> tuple[str, bool]:
    """(nome, e_condizionale): ignora gli extra e i marker non applicabili."""
    base = re.split(r"[;\s\[(<>=!~]", req, maxsplit=1)[0]
    return norm(base), "extra ==" in req


def license_of(dist: metadata.Distribution) -> str:
    md = dist.metadata
    expr = md.get("License-Expression")
    if expr:
        return expr
    lic = (md.get("License") or "").strip()
    if lic and len(lic) < 80 and "\n" not in lic:
        return lic
    cls = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
    cls = [c for c in cls if c not in ("OSI Approved",)]
    if cls:
        return ", ".join(cls)
    return lic.splitlines()[0][:80] if lic else "non indicata nei metadati"


def closure(roots: list[str]) -> dict[str, metadata.Distribution]:
    seen: dict[str, metadata.Distribution] = {}
    todo = [norm(r) for r in roots]
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        try:
            dist = metadata.distribution(n)
        except metadata.PackageNotFoundError:
            continue
        seen[n] = dist
        for req in dist.requires or []:
            name, extra = requirement_name(req)
            if not extra and name not in seen:
                todo.append(name)
    return seen


def main() -> int:
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    direct = [requirement_name(d)[0] for d in deps]
    runtime = closure(direct)
    build = {n: d for n, d in closure([b for b in BUILD_ONLY]).items() if n not in runtime}
    lines = [
        "# Avvisi sulle componenti di terze parti",
        "",
        "JobsHunter usa le librerie qui sotto, ciascuna con la propria licenza. L'elenco e' generato dai metadati dei pacchetti installati",
        "(`scripts/gen_third_party.py`, senza rete): per i testi completi delle licenze vedi il pacchetto di ciascuna libreria.",
        "Le licenze indicate sono quelle dichiarate dai pacchetti; vanno ricontrollate prima di ogni pubblicazione.",
        "",
        "## Librerie usate a runtime",
        "",
        "| Pacchetto | Versione | Licenza | Sito |",
        "|---|---|---|---|",
    ]
    for n in sorted(runtime):
        d = runtime[n]
        home = d.metadata.get("Home-page") or next((u.split(",", 1)[1].strip() for u in d.metadata.get_all("Project-URL") or [] if "," in u), "")
        lines.append(f"| {d.metadata['Name']} | {d.version} | {license_of(d)} | {home} |")
    if build:
        lines += ["", "## Strumenti per costruire l'app Mac (non inclusi nel codice del progetto)", "", "| Pacchetto | Versione | Licenza |", "|---|---|---|"]
        for n in sorted(build):
            d = build[n]
            lines.append(f"| {d.metadata['Name']} | {d.version} | {license_of(d)} |")
        lines += ["", "PyInstaller incorpora nell'app le librerie del runtime e l'interprete Python (licenza PSF). PyInstaller e' GPLv2 con eccezione",
                  "per il bootloader: le app prodotte non sono vincolate alla GPL. `certifi` (MPL-2.0) e' inclusa cosi' com'e', senza modifiche."]
    lines += [
        "",
        "## Dati",
        "",
        "- **GeoNames** (<https://www.geonames.org>): coordinate e nomi delle citta' con piu' di 15.000 abitanti, tramite il pacchetto `geonamescache`.",
        "  Licenza **Creative Commons Attribution 4.0** (<https://creativecommons.org/licenses/by/4.0/>): serve citare GeoNames (CC BY 4.0), come fa questo file.",
        "- **Adzuna** (<https://developer.adzuna.com>) e **Jooble** (<https://jooble.org/api/about>): annunci ricevuti tramite le loro API con chiavi personali.",
        "  I contenuti restano dei rispettivi titolari e dei loro termini d'uso; non sono ridistribuiti da questo progetto.",
        "",
        "Logo (`branding/logo-original.jpg`): origine e licenza da confermare a cura dell'autore prima della pubblicazione.",
        "",
    ]
    (ROOT / "THIRD_PARTY_NOTICES.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"scritto THIRD_PARTY_NOTICES.md ({len(runtime)} librerie runtime, {len(build)} di build)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
