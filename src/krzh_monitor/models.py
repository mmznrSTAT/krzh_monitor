"""Datenmodell: schlanke Dataclasses für Geschäfte, Ablaufschritte, Sitzungen und Traktanden."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

KANTONSRAT_GESCHAEFT_URL = "https://www.kantonsrat.zh.ch/geschaefte/geschaeft?id={guid}"
CDWS_PDF_URL = "https://parlzhcdws.cmicloud.ch/{instance}/cdws/Files/{edoc_id}/{version}/pdf"


@dataclass
class Dokument:
    guid: str
    titel: str
    edoc_id: str | None  # z. B. "01f792dea3234d238f09133185a93998-332"
    version: int | None
    fulltext: str | None = None

    def pdf_url(self, instance: str = "parlzh5") -> str | None:
        if not self.edoc_id or self.version is None:
            return None
        return CDWS_PDF_URL.format(instance=instance, edoc_id=self.edoc_id, version=self.version)


@dataclass
class Beteiligung:
    name: str
    vorname: str
    rolle: str
    partei: str
    gemeinde: str
    ist_kantonsrat: bool


@dataclass
class GeschaeftRef:
    """Kurzreferenz auf ein Geschäft, wie sie in Ablaufschritten und Traktanden vorkommt."""

    guid: str | None
    krnr: str | None  # normalisiert ("288/2024" oder "6082")
    titel: str | None
    geschaeftsart: str | None = None
    kommission: str | None = None
    direktion: str | None = None

    @property
    def url(self) -> str | None:
        return KANTONSRAT_GESCHAEFT_URL.format(guid=self.guid) if self.guid else None


@dataclass
class Ablaufschritt:
    guid: str
    typ: str
    status_text: str
    datum: date | None
    geschaeft: GeschaeftRef
    dokumente: list[Dokument] = field(default_factory=list)


@dataclass
class Geschaeft:
    guid: str
    krnr: str | None  # normalisiert
    vorlage_nr: str | None
    titel: str
    geschaeftsart: str
    kommission: str | None
    kommission_kurz: str | None
    direktion: str | None
    direktion_kurz: str | None
    beginn: date | None
    zusammenfassung: str | None
    pendent_bei: str | None
    erstpublikation: date | None
    beteiligungen: list[Beteiligung] = field(default_factory=list)
    ablaufschritte: list[Ablaufschritt] = field(default_factory=list)
    verknuepfte: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return KANTONSRAT_GESCHAEFT_URL.format(guid=self.guid)

    @property
    def nummer(self) -> str:
        return self.krnr or self.vorlage_nr or self.guid

    @property
    def volltext(self) -> str:
        """Zusammengesetzter Text aller Dokumente, für die spätere Relevanzprüfung."""
        parts = [d.fulltext for s in self.ablaufschritte for d in s.dokumente if d.fulltext]
        return "\n\n".join(parts)


@dataclass
class Traktandum:
    nr: int
    titel: str
    nummer: str | None  # normalisiert
    nummer_raw: str | None  # wie in der Quelle, z. B. "114b/2023"
    geschaeft_guid: str | None = None
    direktion_kurz: str | None = None
    vorstossart: str | None = None
    beratungsart: str | None = None  # "Reduzierte Debatte", "Kurzdebatte", "schriftliches Verfahren"
    behandlung: str | None = None  # z. B. "Entgegennahme, Diskussion" / "RRB-Nr. 1038/2.10.2024 (Stellungnahme)"
    detail: str | None = None  # Urheberzeile(n)
    gemeinsam_mit: list[str] = field(default_factory=list)
    ausgabenbremse: bool = False
    neu: bool = False  # Abschnitt "Neu auf der Traktandenliste"
    nachmittag: bool = False
    quelle: str = "pdf"  # "pdf" (aus Traktandenliste geparst) oder "struktur" (aus <Traktanden>)


@dataclass
class Sitzung:
    guid: str
    titel: str
    nummer: int | None
    datum: date
    uhrzeit: str | None
    gremium_name: str
    gremium_kurz: str
    gremium_typ: str
    traktanden: list[Traktandum] = field(default_factory=list)
    traktandenliste_text: str | None = None
    vorschau_text: str | None = None
    dokumente: list[Dokument] = field(default_factory=list)

    @property
    def ist_ratssitzung(self) -> bool:
        return self.gremium_typ == "Kantonsrat"
