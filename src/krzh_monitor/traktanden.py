"""Parser für die Traktandenliste (PDF-Volltext) einer Ratssitzung.

Für künftige Sitzungen liefert die Schnittstelle das Element ``Traktanden`` leer; die
Traktandenliste liegt aber als Volltext des PDF vor. Der Aufbau ist über Jahre stabil:

    Einladung
    zur Doppelsitzung auf Montag, 26. Oktober 2026, 8.15 Uhr (Nr. 174) und
    14.30 Uhr (Nr. 175), ...
    Die Behandlung der Geschäfte ab Traktandum 39 ist auf den Beginn der
    Nachmittagssitzung angesetzt.
    Verhandlungsgegenstände:
    1.   Mitteilungen
    27.   Kantonales Verbot von bezahltem Sammeln von Unterschriften
    Motion Florian Heer (Grüne, Winterthur), ... vom 9. September 2024
    KR-Nr. 288/2024, Entgegennahme, Diskussion                                JI
    4.   Objektkredit für einen Beitrag ...
    Antrag des Regierungsrates vom 1. April 2026 und Antrag der STGK
    vom 26. Juni 2026
    6082a                                                                      FD
    ...
    Neu auf der Traktandenliste:
    141.   ...
    Zürich, 19. Oktober 2026                                  Die Präsidentin:
    Vom Regierungsrat noch nicht behandelte Vorstösse:
    KR-Nr.  262  29.6.2026         Motion Urs Waser

Jedes Traktandum beginnt mit ``N.`` und fortlaufender Nummer; die Nummernzeile am Ende
nennt KR-Nr. oder Vorlagen-Nr., bei Vorstössen die Behandlungsart und rechts das Kürzel
der zuständigen Direktion. Zwischen den Einträgen stehen einzelne Seitenzahlen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Traktandum
from .nummern import parse_nummer

DIREKTIONEN = {"JI", "DS", "FD", "VD", "GD", "BI", "BD", "SK", "GL"}

_ITEM_START = re.compile(r"^(\d{1,3})\.\s+(\S.*)$")
_PAGE_NUMBER = re.compile(r"^\d{1,3}$")
_KRNR_LINE = re.compile(r"^KR-Nr\.\s*(\d{1,4}[a-z]?/\d{4}[a-z]?)\s*(?:,\s*(.*?))?\s*$")
_VORLAGE_LINE = re.compile(r"^(\d{4}[a-z]?)\s*$")
_TRAILING_DIR = re.compile(r"\s+(" + "|".join(sorted(DIREKTIONEN)) + r")\s*$")
_GEMEINSAM = re.compile(r"gemeinsame Behandlung mit KR-Nrn?\.\s*(.*)", re.S)
_BERATUNGSART = re.compile(r"\s*\((Reduzierte\s+Debatte|Kurzdebatte|schriftliches\s+Verfahren)\)", re.I)
_AUSGABENBREMSE = re.compile(r"\s*\(Ausgabenbremse\)", re.I)
_MONATSENDE = re.compile(
    r"(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|\d{1,2}\.)\s*$"
)
_VORSTOSSART = re.compile(
    r"^(Motion|Postulat|Interpellation|Anfrage|Parlamentarische Initiative|Einzelinitiative|"
    r"Behördeninitiative|Volksinitiative|Antrag des Regierungsrates|Antrag der [A-Za-zÄÖÜäöü]+|Antrag des [A-Za-zÄÖÜäöü]+)\b"
)
_NACHMITTAG = re.compile(r"ab Traktandum (\d+) ist auf den Beginn der\s*Nachmittagssitzung", re.S)
_SITZUNGSNR = re.compile(r"\(Nr\.\s*(\d+)\)")
_PENDENT_LINE = re.compile(r"^KR-Nr\.\s+(\d{1,4})\s+(\d{1,2}\.\d{1,2}\.(\d{4}))\s+(\S.*)$")


@dataclass
class Traktandenliste:
    sitzungsnummern: list[int]
    traktanden: list[Traktandum]
    nachmittag_ab: int | None = None
    pendent_beim_rr: list[dict] = field(default_factory=list)  # noch nicht behandelte Vorstösse
    warnungen: list[str] = field(default_factory=list)


def parse_traktandenliste(text: str) -> Traktandenliste:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]

    header, body, footer = _split_sections(lines)
    header_text = "\n".join(header)
    sitzungsnummern = [int(n) for n in _SITZUNGSNR.findall(header_text)]
    m = _NACHMITTAG.search(header_text)
    nachmittag_ab = int(m.group(1)) if m else None

    blocks, warnungen = _split_items(body)
    traktanden = [_parse_block(nr, blk, neu) for nr, blk, neu in blocks]
    if nachmittag_ab is not None:
        for t in traktanden:
            t.nachmittag = t.nr >= nachmittag_ab

    pendent = []
    for ln in footer:
        m = _PENDENT_LINE.match(ln.strip())
        if m:
            nr, datum, jahr, rest = m.groups()
            pendent.append({"nummer": f"{int(nr)}/{jahr}", "eingereicht": datum, "text": rest.strip()})

    return Traktandenliste(
        sitzungsnummern=sitzungsnummern,
        traktanden=traktanden,
        nachmittag_ab=nachmittag_ab,
        pendent_beim_rr=pendent,
        warnungen=warnungen,
    )


def _split_sections(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Trennt Kopf (bis «Verhandlungsgegenstände:»), Rumpf und Fuss (ab Datum/Unterschrift)."""
    start = 0
    for i, ln in enumerate(lines):
        if ln.strip().startswith("Verhandlungsgegenst"):
            start = i + 1
            break
    end = len(lines)
    for i in range(start, len(lines)):
        s = lines[i].strip()
        if re.match(r"^Zürich,\s+\d{1,2}\.\s*\w+\s+\d{4}", s) or s.startswith("Vom Regierungsrat noch nicht behandelte"):
            end = i
            break
    return lines[:start], lines[start:end], lines[end:]


def _split_items(body: list[str]) -> tuple[list[tuple[int, list[str], bool]], list[str]]:
    blocks: list[tuple[int, list[str], bool]] = []
    warnungen: list[str] = []
    current: list[str] | None = None
    current_nr = 0
    current_neu = False
    neu = False  # Abschnitt «Neu auf der Traktandenliste» erreicht
    expected = 1
    for ln in body:
        s = ln.strip()
        if not s:
            continue
        if _PAGE_NUMBER.match(s):
            continue  # Seitenzahl
        if s.startswith("Neu auf der Traktandenliste"):
            neu = True
            continue
        m = _ITEM_START.match(s)
        if m and int(m.group(1)) == expected:
            if current is not None:
                blocks.append((current_nr, current, current_neu))
            current_nr = int(m.group(1))
            current = [m.group(2).strip()]
            current_neu = neu
            expected = current_nr + 1
            continue
        if m and current is not None and int(m.group(1)) > expected:
            warnungen.append(f"Nummernsprung: erwartet {expected}, gefunden {m.group(1)} ({s[:60]})")
        if current is None:
            warnungen.append(f"Zeile vor erstem Traktandum ignoriert: {s[:80]}")
            continue
        current.append(s)
    if current is not None:
        blocks.append((current_nr, current, current_neu))
    return blocks, warnungen


def _parse_block(nr: int, lines: list[str], neu: bool) -> Traktandum:
    titel_lines: list[str] = []
    detail_lines: list[str] = []
    nummer_raw: str | None = None
    behandlung: str | None = None
    direktion: str | None = None
    gemeinsam: list[str] = []
    in_title = True
    tail_lines: list[str] = []

    prev = ""
    for ln in lines:
        s = ln.strip()
        # Nummernzeile: KR-Nr. ... [Behandlung] [DIR]
        core, dir_ = _split_direktion(s)
        m = _KRNR_LINE.match(core)
        if m and nummer_raw is None:
            nummer_raw = m.group(1)
            behandlung = (m.group(2) or "").strip(" ,") or None
            direktion = dir_
            in_title = False
            prev = s
            continue
        m = _VORLAGE_LINE.match(core)
        if m and nummer_raw is None and not _ist_jahreszahl(m.group(1), prev):
            if not in_title or titel_lines:
                # Vorlagen-Nr. nach der Antragszeile oder direkt nach dem Titel
                nummer_raw = m.group(1)
                direktion = dir_
                in_title = False
                prev = s
                continue
        if nummer_raw is not None:
            tail_lines.append(s)
            prev = s
            continue
        if in_title and titel_lines and _VORSTOSSART.match(s):
            in_title = False  # Urheberzeile beendet den Titel; die erste Zeile ist immer Titel
        if in_title:
            titel_lines.append(s)
        else:
            detail_lines.append(s)
        prev = s

    # «gemeinsame Behandlung mit KR-Nrn. ...» kann über mehrere Zeilen laufen
    if tail_lines:
        g = _GEMEINSAM.search(" ".join(tail_lines))
        if g:
            gemeinsam.extend(_norm_list(g.group(1)))

    titel = _join_wrapped(titel_lines)
    ausgabenbremse = bool(_AUSGABENBREMSE.search(titel))
    titel = _AUSGABENBREMSE.sub("", titel).strip()
    beratungsart = None
    bm = _BERATUNGSART.search(titel)
    if bm:
        beratungsart = re.sub(r"\s+", " ", bm.group(1))
        titel = _BERATUNGSART.sub("", titel).strip()
    detail = _join_wrapped(detail_lines) or None
    vorstossart = None
    if detail:
        vm = _VORSTOSSART.match(detail)
        if vm:
            vorstossart = vm.group(1)
            if vorstossart.startswith("Antrag"):
                vorstossart = "Antrag"

    n = parse_nummer(nummer_raw) if nummer_raw else None
    return Traktandum(
        nr=nr,
        titel=titel,
        nummer=n.key if n else None,
        nummer_raw=nummer_raw,
        direktion_kurz=direktion,
        vorstossart=vorstossart,
        beratungsart=beratungsart,
        behandlung=behandlung,
        detail=detail,
        gemeinsam_mit=[x for x in gemeinsam if x],
        ausgabenbremse=ausgabenbremse,
        neu=neu,
        quelle="pdf",
    )


def _ist_jahreszahl(token: str, prev_line: str) -> bool:
    """Eine umbrochene Datumsangabe («vom 6. Juli» / «2026») darf nicht als Vorlagen-Nr. gelten."""
    if not token.isdigit() or not (1990 <= int(token) <= 2099):
        return False
    return bool(_MONATSENDE.search(prev_line))


def _split_direktion(s: str) -> tuple[str, str | None]:
    m = _TRAILING_DIR.search(s)
    if m:
        return s[: m.start()].rstrip(), m.group(1)
    return s, None


def _norm_list(text: str) -> list[str]:
    out = []
    for raw in re.findall(r"\d{1,4}[a-z]?/\d{4}", text):
        n = parse_nummer(raw)
        out.append(n.key if n else raw)
    return out


def _join_wrapped(lines: list[str]) -> str:
    """Fügt umbrochene Zeilen zusammen; Trennstriche am Zeilenende werden entfernt."""
    out = ""
    for ln in lines:
        s = re.sub(r"\s{2,}", " ", ln.strip())
        if not s:
            continue
        if out.endswith("-") and s[:1].islower():
            out = out[:-1] + s
        elif out:
            out += " " + s
        else:
            out = s
    return out.strip()
