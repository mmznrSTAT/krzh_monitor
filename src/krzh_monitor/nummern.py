"""Umgang mit Geschäftsnummern des Kantonsrats.

Zwei Nummernkreise kommen vor:

* KR-Nr. für Vorstösse: ``288/2024``; Dokumentversionen tragen ein Suffix, ``114b/2023``.
* Vorlagen-Nr. für Vorlagen des Regierungsrats: ``6082``; Versionen ``6082a``.

Die Schnittstelle führt beide im Feld ``KRNr`` ohne Suffix. Für Nachschlagen und als
Schlüssel in der Datenbank wird deshalb die normalisierte Form ohne Suffix verwendet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_KRNR = re.compile(r"^(\d{1,4})([a-z])?/(\d{4})([a-z])?$")
_VORLAGE = re.compile(r"^(\d{4})([a-z])?$")


@dataclass(frozen=True)
class Nummer:
    key: str  # normalisiert, z. B. "288/2024" oder "6082"
    art: str  # "krnr" oder "vorlage"
    version: str | None = None  # Buchstabensuffix, z. B. "b"

    @property
    def display(self) -> str:
        if self.art == "krnr":
            nr, jahr = self.key.split("/")
            return f"KR-Nr. {nr}{self.version or ''}/{jahr}"
        return f"Vorlage {self.key}{self.version or ''}"


def parse_nummer(raw: str) -> Nummer | None:
    s = raw.strip().replace(" ", "")
    m = _KRNR.match(s)
    if m:
        nr, suffix, jahr, suffix2 = m.groups()
        return Nummer(key=f"{int(nr)}/{jahr}", art="krnr", version=suffix or suffix2)
    m = _VORLAGE.match(s)
    if m:
        nr, suffix = m.groups()
        return Nummer(key=nr, art="vorlage", version=suffix)
    return None


def normalize_nummer(raw: str) -> str:
    n = parse_nummer(raw)
    if n is None:
        raise ValueError(f"Keine gültige Geschäftsnummer: {raw!r}")
    return n.key
