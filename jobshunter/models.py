from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&nbsp;|&amp;|&#\d+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class Job:
    source: str
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    posted_at: datetime | None = None
    remote: bool = False
    salary: str = ""
    near_home: bool = False
    country: str = ""  # codice paese di provenienza (it, gb, de...), quando la fonte lo sa
    near_where: set = field(default_factory=set)  # luoghi (minuscolo) delle ricerche con raggio che l'hanno trovato
    # valorizzati dallo scoring
    score: int = 0
    category: str = ""
    matched: list[str] = field(default_factory=list)

    @property
    def uid(self) -> str:
        key = f"{self.company.lower()}|{self.title.lower()}|{self.location.lower()}"
        return hashlib.sha1(key.encode()).hexdigest()[:16]
