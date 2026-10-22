"""Relevanzbewertung eines Geschäfts gegen ein Amtsprofil (TOML, siehe profiles/asd.toml).

Schlüsselwortbasiert und absichtlich einfach: reguläre Ausdrücke mit Gewichten, getrennt nach
Fundstelle (Titel, Zusammenfassung, Volltext). Das Ergebnis trägt die Treffer mit, damit das
Briefing begründen kann, warum ein Geschäft erscheint. Ein semantisches Modell kann später an
derselben Stelle angeschlossen werden (gleiche ``Bewertung``-Struktur).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

STUFEN = ("relevant", "pruefen", "keine")


@dataclass(frozen=True)
class Begriff:
    thema: str
    muster: re.Pattern
    gewicht: float


@dataclass
class Profil:
    name: str
    beschreibung: str
    begriffe: list[Begriff]
    ausschluss_titel: list[re.Pattern]
    gewicht_titel: float
    gewicht_zusammenfassung: float
    gewicht_volltext: float
    volltext_max: float
    schwelle_relevant: float
    schwelle_pruefen: float
    titel_min_gewicht: float  # «relevant» braucht einen Titel-/Zusammenfassungstreffer mit mindestens diesem Gewicht
    bonus_direktion: dict[str, float]


@dataclass
class Treffer:
    thema: str
    begriff: str  # tatsächlich getroffener Text, z. B. "Datenlage"
    feld: str  # "titel" | "zusammenfassung" | "volltext"
    anzahl: int
    punkte: float


@dataclass
class Bewertung:
    score: float
    stufe: str
    treffer: list[Treffer] = field(default_factory=list)
    themen: list[str] = field(default_factory=list)
    ausgeschlossen: bool = False

    @property
    def begruendung(self) -> str:
        """Kurzfassung der stärksten Treffer, für das Briefing."""
        if self.ausgeschlossen:
            return "ausgeschlossen (Profilregel)"
        if not self.treffer:
            return ""
        parts: list[str] = []
        seen: set[tuple[str, str]] = set()
        for t in sorted(self.treffer, key=lambda t: -t.punkte):
            key = (t.begriff.lower(), t.feld)
            if key in seen:
                continue
            seen.add(key)
            feld = {"titel": "Titel", "zusammenfassung": "Zusammenfassung", "volltext": "Text"}[t.feld]
            mal = f" ×{t.anzahl}" if t.anzahl > 1 and t.feld == "volltext" else ""
            parts.append(f"{t.begriff}{mal} ({feld})")
            if len(parts) >= 4:
                break
        return ", ".join(parts)


def lade_profil(path: str | Path) -> Profil:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    begriffe: list[Begriff] = []
    for thema in data.get("thema", []):
        for b in thema.get("begriffe", []):
            flags = 0 if b.get("cs") else re.I  # cs = case sensitive (Abkürzungen wie KI, BIP, OGD)
            begriffe.append(Begriff(thema=thema["name"], muster=re.compile(b["re"], flags), gewicht=float(b["gewicht"])))
    sc = data.get("scoring", {})
    return Profil(
        name=data.get("meta", {}).get("name", Path(path).stem),
        beschreibung=data.get("meta", {}).get("beschreibung", ""),
        begriffe=begriffe,
        ausschluss_titel=[re.compile(p, re.I) for p in data.get("ausschluss", {}).get("titel", [])],
        gewicht_titel=float(sc.get("gewicht_titel", 3.0)),
        gewicht_zusammenfassung=float(sc.get("gewicht_zusammenfassung", 2.0)),
        gewicht_volltext=float(sc.get("gewicht_volltext", 1.0)),
        volltext_max=float(sc.get("volltext_max", 6.0)),
        schwelle_relevant=float(sc.get("schwelle_relevant", 6.0)),
        schwelle_pruefen=float(sc.get("schwelle_pruefen", 3.0)),
        titel_min_gewicht=float(sc.get("titel_min_gewicht", 2.0)),
        bonus_direktion={k: float(v) for k, v in sc.get("bonus_direktion", {}).items()},
    )


def bewerte(
    profil: Profil,
    titel: str,
    zusammenfassung: str | None = None,
    volltext: str | None = None,
    direktion_kurz: str | None = None,
) -> Bewertung:
    if any(p.search(titel or "") for p in profil.ausschluss_titel):
        return Bewertung(score=0.0, stufe="keine", ausgeschlossen=True)

    treffer: list[Treffer] = []
    score = 0.0

    for feld, text, gewicht_feld in (
        ("titel", titel, profil.gewicht_titel),
        ("zusammenfassung", zusammenfassung, profil.gewicht_zusammenfassung),
    ):
        if not text:
            continue
        for b in profil.begriffe:
            m = b.muster.search(text)
            if m:
                punkte = b.gewicht * gewicht_feld
                treffer.append(Treffer(b.thema, m.group(0), feld, 1, punkte))
                score += punkte

    if volltext:
        vt_sum = 0.0
        for b in profil.begriffe:
            matches = list(b.muster.finditer(volltext))
            if not matches:
                continue
            n = len(matches)
            faktor = 1.0 + 0.5 * min(n - 1, 2)  # 1×, 1.5×, 2× für 1, 2, ≥3 Vorkommen
            punkte = b.gewicht * profil.gewicht_volltext * faktor
            treffer.append(Treffer(b.thema, matches[0].group(0), "volltext", n, punkte))
            vt_sum += punkte
        score += min(vt_sum, profil.volltext_max)

    if treffer and direktion_kurz and direktion_kurz in profil.bonus_direktion:
        score += profil.bonus_direktion[direktion_kurz]

    starker_titeltreffer = any(
        t.feld != "volltext" and t.punkte >= profil.titel_min_gewicht * (profil.gewicht_zusammenfassung if t.feld == "zusammenfassung" else profil.gewicht_titel)
        for t in treffer
    )
    if score >= profil.schwelle_relevant and starker_titeltreffer:
        stufe = "relevant"
    elif score >= profil.schwelle_pruefen:
        stufe = "pruefen"
    else:
        stufe = "keine"
    themen = sorted({t.thema for t in treffer if t.feld != "volltext"} or {t.thema for t in treffer})
    return Bewertung(score=round(score, 1), stufe=stufe, treffer=treffer, themen=themen)


def bewerte_row(profil: Profil, row) -> Bewertung:
    """Bewertet eine Zeile der Tabelle ``geschaefte`` (sqlite3.Row)."""
    return bewerte(
        profil,
        titel=row["titel"] or "",
        zusammenfassung=row["zusammenfassung"],
        volltext=row["volltext"],
        direktion_kurz=row["direktion_kurz"],
    )
