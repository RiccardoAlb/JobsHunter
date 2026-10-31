"""Testo del file di versione di Windows (le proprieta' del .exe: nome, versione, descrizione, copyright).

Non contiene dati personali: solo il nome del programma e la licenza. Lo usa JobsHunter.spec su Windows.
"""
from __future__ import annotations


def parse(version: str) -> tuple[int, int, int, int]:
    parts = [int(p) for p in version.split(".") if p.isdigit()][:4]
    return tuple(parts + [0] * (4 - len(parts)))  # type: ignore[return-value]


def render(version: str) -> str:
    v = parse(version)
    t = ", ".join(str(n) for n in v)
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({t}), prodvers=({t}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'JobsHunter'),
      StringStruct('FileDescription', 'JobsHunter, radar personale di annunci di lavoro'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'JobsHunter'),
      StringStruct('LegalCopyright', 'Licenza MIT, vedi LICENSE'),
      StringStruct('OriginalFilename', 'JobsHunter.exe'),
      StringStruct('ProductName', 'JobsHunter'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


if __name__ == "__main__":
    import sys

    print(render(sys.argv[1] if len(sys.argv) > 1 else "0.0.0"), end="")
