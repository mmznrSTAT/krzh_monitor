"""XML-Parser für die drei genutzten CDWS-Indizes.

Die Antworten mischen mehrere Namensräume; der Parser entfernt sie beim Einlesen, damit
Pfade wie ``Geschaeft/Geschaeft/KRNr`` ohne Präfixe funktionieren. Zwei Eigenheiten der
Quelle:

* Dokumente heissen im Index ``GESCHAEFT`` ``eDocument``, in ``ABLAUFSCHRITTE`` ``eDokument``.
* Referenzen sind doppelt geschachtelt (``<Geschaeft><Geschaeft OBJ_GUID=...>``).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime

from .models import Ablaufschritt, Beteiligung, Dokument, Geschaeft, GeschaeftRef, Sitzung, Traktandum
from .nummern import parse_nummer


def _strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def parse_root(xml: str) -> ET.Element:
    return _strip_ns(ET.fromstring(xml))


def num_hits(xml: str) -> int:
    m = re.search(r'numHits="(\d+)"', xml[:2000])
    return int(m.group(1)) if m else 0


def count_hits(xml: str) -> int:
    return len(parse_root(xml).findall("Hit"))


def _text(el: ET.Element | None, path: str | None = None) -> str | None:
    if el is None:
        return None
    node = el.find(path) if path else el
    if node is None or node.text is None:
        return None
    t = node.text.strip()
    return t or None


def _date(el: ET.Element | None, path: str) -> date | None:
    t = _text(el, path)
    if not t:
        return None
    try:
        return datetime.fromisoformat(t[:19]).date()
    except ValueError:
        return None


def _norm_nummer(raw: str | None) -> str | None:
    if not raw:
        return None
    n = parse_nummer(raw)
    return n.key if n else raw.strip()


def _dokumente(parent: ET.Element | None) -> list[Dokument]:
    out: list[Dokument] = []
    if parent is None:
        return out
    for d in parent.findall("Dokument"):
        edoc = d.find("eDocument")
        if edoc is None:
            edoc = d.find("eDokument")
        version = None
        if edoc is not None:
            versions = [v for v in edoc.findall("Version") if v.find("Rendition") is not None]
            if versions:
                version = int(versions[-1].get("Nr", "1"))
        out.append(
            Dokument(
                guid=d.get("OBJ_GUID", ""),
                titel=_text(d, "Titel") or "",
                edoc_id=edoc.get("ID") if edoc is not None else None,
                version=version,
                fulltext=_text(edoc, "Fulltext") if edoc is not None else None,
            )
        )
    return out


def _geschaeft_ref(el: ET.Element | None) -> GeschaeftRef:
    """Liest ``<Geschaeft><Geschaeft OBJ_GUID=...>...</Geschaeft></Geschaeft>``."""
    inner = el.find("Geschaeft") if el is not None else None
    if inner is None:
        inner = el
    if inner is None:
        return GeschaeftRef(guid=None, krnr=None, titel=None)
    raw = _text(inner, "KRNr") or _text(inner, "KRNummer") or _text(inner, "VorlageNr")
    return GeschaeftRef(
        guid=inner.get("OBJ_GUID"),
        krnr=_norm_nummer(raw),
        titel=_text(inner, "Titel"),
        geschaeftsart=_text(inner, "Geschaeftsart"),
        kommission=_text(inner, "BehandelndeKommission"),
        direktion=_text(inner, "Direktion"),
    )


def _ablaufschritt(a: ET.Element, geschaeft: GeschaeftRef | None = None) -> Ablaufschritt:
    return Ablaufschritt(
        guid=a.get("OBJ_GUID", ""),
        typ=_text(a, "AblaufschrittTyp") or "",
        status_text=_text(a, "StatusText") or "",
        datum=_date(a, "Sitzungsdatum/Start"),
        geschaeft=geschaeft if geschaeft is not None else _geschaeft_ref(a.find("Geschaeft")),
        dokumente=_dokumente(a.find("Dokumente")),
    )


# --- Index ABLAUFSCHRITTE --------------------------------------------------------------


def parse_ablaufschritte(xml: str) -> list[Ablaufschritt]:
    root = parse_root(xml)
    return [_ablaufschritt(a) for a in root.iter("Ablaufschritt") if a.get("IDX") == "Ablaufschritte"]


# --- Index GESCHAEFT -------------------------------------------------------------------


def parse_geschaefte(xml: str) -> list[Geschaeft]:
    root = parse_root(xml)
    out: list[Geschaeft] = []
    for g in root.iter("Geschaeft"):
        if g.get("IDX") != "Geschaeft":
            continue
        pendent = g.find("PendentBeiNeu/Organisationseinheit/Name")
        erst = _text(g, "SortErstPublikation")
        beteiligungen = [
            Beteiligung(
                name=_text(b, "Name") or "",
                vorname=_text(b, "Vorname") or "",
                rolle=_text(b, "Rolle") or "",
                partei=_text(b, "ParteiKurzname") or _text(b, "Partei") or "",
                gemeinde=_text(b, "PolitischeGemeinde") or "",
                ist_kantonsrat=(_text(b, "IstKantonsrat") == "true"),
            )
            for b in g.findall("Beteiligungen/Beteiligung")
        ]
        guid = g.get("OBJ_GUID", "")
        krnr_raw = _text(g, "KRNr")
        vorlage = _text(g, "VorlageNr")
        ref = GeschaeftRef(guid=guid, krnr=_norm_nummer(krnr_raw or vorlage), titel=_text(g, "Titel"))
        out.append(
            Geschaeft(
                guid=guid,
                krnr=_norm_nummer(krnr_raw) if krnr_raw and "/" in krnr_raw else None,
                vorlage_nr=_norm_nummer(vorlage) if vorlage else (_norm_nummer(krnr_raw) if krnr_raw and "/" not in krnr_raw else None),
                titel=_text(g, "Titel") or "",
                geschaeftsart=_text(g, "Geschaeftsart") or "",
                kommission=_text(g, "BehandelndeKommission"),
                kommission_kurz=_text(g, "BehandelndeKommissionKurzname"),
                direktion=_text(g, "Direktion"),
                direktion_kurz=_text(g, "DirektionKurzname"),
                beginn=_date(g, "Beginn/Start"),
                zusammenfassung=_text(g, "Zusammenfassung"),
                pendent_bei=_text(pendent),
                erstpublikation=datetime.strptime(erst, "%Y%m%d").date() if erst and erst.isdigit() else None,
                beteiligungen=beteiligungen,
                ablaufschritte=[_ablaufschritt(a, ref) for a in g.findall("Ablaufschritte/Ablaufschritt")],
                verknuepfte=[t for t in (_text(v, "KRNr") for v in g.findall("VerknuepfteGeschaefte//Geschaeft")) if t],
            )
        )
    return out


# --- Index SITZUNGENDETAIL --------------------------------------------------------------


def parse_sitzungen(xml: str) -> list[Sitzung]:
    root = parse_root(xml)
    out: list[Sitzung] = []
    for s in root.iter("Sitzung"):
        if s.get("IDX") != "SitzungenDetail":
            continue
        datum = _date(s, "Datum/Start")
        if datum is None:
            continue
        nummer = _text(s, "Sitzungsnummer")
        dokumente = _dokumente(s.find("Sitzungsdokumente"))
        kategorien = {
            _text(d, "Kategorie"): d for d in s.findall("Sitzungsdokumente/Dokument")
        }
        traktanden: list[Traktandum] = []
        for t in s.findall("Traktanden/Traktandum"):
            ref = _geschaeft_ref(t.find("Geschaeft"))
            raw = _text(t, "Geschaeft/Geschaeft/KRNummer") or _text(t, "Geschaeft/Geschaeft/VorlageNr")
            nr_text = _text(t, "TraktandenNr")
            traktanden.append(
                Traktandum(
                    nr=int(nr_text) if nr_text and nr_text.isdigit() else 0,
                    titel=_clean_struktur_titel(_text(t, "Titel") or "", raw),
                    nummer=ref.krnr,
                    nummer_raw=raw,
                    geschaeft_guid=ref.guid,
                    quelle="struktur",
                )
            )
        traktanden.sort(key=lambda t: t.nr)
        out.append(
            Sitzung(
                guid=s.get("OBJ_GUID", ""),
                titel=_text(s, "Titel") or "",
                nummer=int(nummer) if nummer and nummer.isdigit() else None,
                datum=datum,
                uhrzeit=_text(s, "Uhrzeit"),
                gremium_name=_text(s, "Gremium/Gremium/Name") or "",
                gremium_kurz=_text(s, "Gremium/Gremium/Kurzname") or "",
                gremium_typ=_text(s, "Gremium/Gremium/GremiumTyp") or "",
                traktanden=traktanden,
                traktandenliste_text=_fulltext_of(kategorien.get("Traktandenliste")),
                vorschau_text=_fulltext_of(kategorien.get("Vorschau")),
                dokumente=dokumente,
            )
        )
    return out


def _fulltext_of(dok: ET.Element | None) -> str | None:
    if dok is None:
        return None
    edoc = dok.find("eDokument")
    if edoc is None:
        edoc = dok.find("eDocument")
    return _text(edoc, "Fulltext") if edoc is not None else None


def _clean_struktur_titel(titel: str, nummer_raw: str | None) -> str:
    """Kommissionen stellen die Nummer dem Titel voran (``6116  Bauprogramm ...``)."""
    if nummer_raw and titel.startswith(nummer_raw):
        return titel[len(nummer_raw):].strip()
    return titel.strip()
