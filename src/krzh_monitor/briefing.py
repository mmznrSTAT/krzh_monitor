"""Montagsbriefing: nur die für ein Amt relevanten Geschäfte.

Drei Blöcke, jeweils mit den Stufen «relevant» (ausführlich) und «prüfen» (eine Zeile):

1. Ratssitzung am Stichtag (oder die nächste innerhalb einer Woche): traktandierte Geschäfte
2. Ablaufschritte der vergangenen Woche: neu eingereicht, Antworten und Anträge des
   Regierungsrats, Kommissionsanträge, Beschlüsse
3. Kommissionssitzungen der Woche davor und danach mit publizierten Traktanden

Die Daten kommen aus dem Store, die Bewertung aus ``relevanz.py``. Ausgabe als Markdown
(für GitHub) und als HTML (für den Mailversand), aus derselben Struktur gerendert.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from .models import KANTONSRAT_GESCHAEFT_URL
from .relevanz import Bewertung, Profil, bewerte, bewerte_row
from .report import TYP_REIHENFOLGE, _d, _kurz, _kurztext
from .store import Store

PDF_URL = "https://parlzhcdws.cmicloud.ch/parlzh5/cdws/Files/{edoc_id}/{version}/pdf"
MAX_PRUEFEN = 8


@dataclass
class Eintrag:
    nummer: str | None
    nummer_raw: str | None
    titel: str
    url: str | None
    bewertung: Bewertung
    art: str | None = None
    direktion: str | None = None
    kontext: str | None = None  # Traktandum-Nr./Behandlung, Ablaufschritt-Typ, Kommission
    datum: str | None = None
    status_text: str | None = None
    dokumente: list[tuple[str, str]] = field(default_factory=list)  # (Titel, URL)

    def __post_init__(self) -> None:
        self.titel = " ".join((self.titel or "").split())  # Zeilenumbrüche aus Sammelvorlagen

    @property
    def label(self) -> str:
        return self.nummer_raw or self.nummer or "–"


@dataclass
class Block:
    titel: str
    untertitel: str | None
    relevant: list[Eintrag]
    pruefen: list[Eintrag]
    total: int
    hinweis: str | None = None


@dataclass
class Briefing:
    stichtag: date
    profil_name: str
    bloecke: list[Block]
    rohliste_url: str | None = None

    @property
    def anzahl_relevant(self) -> int:
        return sum(len(b.relevant) for b in self.bloecke)

    @property
    def anzahl_pruefen(self) -> int:
        return sum(len(b.pruefen) for b in self.bloecke)


# --- Aufbau -------------------------------------------------------------------------


class _Bewerter:
    """Bewertet jedes Geschäft nur einmal, mit Fallback auf den Titel, wenn es nicht geladen ist."""

    def __init__(self, store: Store, profil: Profil) -> None:
        self.store = store
        self.profil = profil
        self.cache: dict[str, Bewertung] = {}

    def fuer(self, nummer: str | None, guid: str | None, titel: str | None, direktion_kurz: str | None = None):
        key = guid or nummer or titel or ""
        if key in self.cache:
            return self.cache[key], self._row(nummer, guid)
        row = self._row(nummer, guid)
        if row is not None:
            b = bewerte_row(self.profil, row)
        else:
            b = bewerte(self.profil, titel or "", direktion_kurz=direktion_kurz)
        self.cache[key] = b
        return b, row

    def _row(self, nummer: str | None, guid: str | None):
        if guid:
            r = self.store.geschaeft_by_guid(guid)
            if r is not None:
                return r
        if nummer:
            return self.store.geschaeft_by_nummer(nummer)
        return None


def _sortiert(eintraege: list[Eintrag]) -> tuple[list[Eintrag], list[Eintrag]]:
    rel = sorted([e for e in eintraege if e.bewertung.stufe == "relevant"], key=lambda e: -e.bewertung.score)
    pr = sorted([e for e in eintraege if e.bewertung.stufe == "pruefen"], key=lambda e: -e.bewertung.score)[:MAX_PRUEFEN]
    return rel, pr


def baue_briefing(store: Store, profil: Profil, stichtag: date, rohliste_url: str | None = None) -> Briefing:
    bew = _Bewerter(store, profil)
    bloecke: list[Block] = []

    # 1. Ratssitzung(en) am Stichtag oder die nächste innerhalb von 7 Tagen
    sitzungen = [s for s in store.sitzungen_zwischen(stichtag, stichtag + timedelta(days=8)) if s["gremium_typ"] == "Kantonsrat"]
    if sitzungen:
        erster_tag = sitzungen[0]["datum"]
        heutige = [s for s in sitzungen if s["datum"] == erster_tag]
        eintraege: list[Eintrag] = []
        total = 0
        for s in heutige:
            for t in store.traktanden_der_sitzung(s["guid"]):
                if not t["nummer"]:
                    continue
                total += 1
                b, row = bew.fuer(t["nummer"], t["geschaeft_guid"] or t["g_guid"], t["titel"], t["direktion_kurz"] or t["g_direktion_kurz"])
                guid = t["geschaeft_guid"] or t["g_guid"]
                beh = ", ".join(x for x in [t["beratungsart"], t["behandlung"], "neu auf der Liste" if t["neu"] else None] if x)
                eintraege.append(
                    Eintrag(
                        nummer=t["nummer"], nummer_raw=t["nummer_raw"], titel=t["titel"],
                        url=KANTONSRAT_GESCHAEFT_URL.format(guid=guid) if guid else None,
                        bewertung=b,
                        art=t["vorstossart"] or t["g_geschaeftsart"],
                        direktion=t["direktion_kurz"] or t["g_direktion_kurz"],
                        kontext=f"Traktandum {t['nr']}" + (f" · {beh}" if beh else ""),
                    )
                )
        rel, pr = _sortiert(eintraege)
        titel_namen = " und ".join(s["titel"] for s in heutige)
        wann = "Heute" if erster_tag == stichtag.isoformat() else f"Am {_d(erster_tag)}"
        bloecke.append(Block(f"{wann} im Kantonsrat: {titel_namen}", f"{total} traktandierte Geschäfte", rel, pr, total))
    else:
        bloecke.append(Block("Kantonsrat", None, [], [], 0, hinweis="Keine Ratssitzung in den nächsten sieben Tagen."))

    # 2. Ablaufschritte der vergangenen Woche
    von = stichtag - timedelta(days=7)
    schritte = store.ablaufschritte_zwischen(von, stichtag)
    eintraege = []
    for a in schritte:
        b, row = bew.fuer(a["geschaeft_nummer"], a["geschaeft_guid"], a["geschaeft_titel"], _kurz(a["direktion"]) or None)
        doks = []
        for d in json.loads(a["dokumente"] or "[]"):
            if d.get("edoc_id") and d.get("version"):
                doks.append((d["titel"], PDF_URL.format(edoc_id=d["edoc_id"], version=d["version"])))
        nummer = a["geschaeft_nummer"] or (row["nummer"] if row else None)
        eintraege.append(
            Eintrag(
                nummer=nummer, nummer_raw=None,
                titel=a["geschaeft_titel"] or (row["titel"] if row else "") or "(ohne Titel)",
                url=KANTONSRAT_GESCHAEFT_URL.format(guid=a["geschaeft_guid"]) if a["geschaeft_guid"] else None,
                bewertung=b,
                art=(row["geschaeftsart"] if row else None),
                direktion=(row["direktion_kurz"] if row else None) or _kurz(a["direktion"]) or None,
                kontext=a["typ"],
                datum=a["datum"],
                status_text=a["status_text"] if a["status_text"] != a["typ"] else None,
                dokumente=doks,
            )
        )
    rel, pr = _sortiert(eintraege)
    rel.sort(key=lambda e: (TYP_REIHENFOLGE.index(e.kontext) if e.kontext in TYP_REIHENFOLGE else 99, -e.bewertung.score))
    bloecke.append(Block("Vergangene Woche: Eingänge, Antworten, Beschlüsse", f"{_d(von.isoformat())} bis {_d((stichtag - timedelta(days=1)).isoformat())}, {len(schritte)} Ablaufschritte", rel, pr, len(schritte)))

    # 3. Kommissionen
    komm = [s for s in store.sitzungen_zwischen(von, stichtag + timedelta(days=8)) if s["gremium_typ"] != "Kantonsrat"]
    eintraege = []
    total = 0
    for s in komm:
        for t in store.traktanden_der_sitzung(s["guid"]):
            if not t["nummer"]:
                continue
            total += 1
            guid = t["geschaeft_guid"] or t["g_guid"]
            b, row = bew.fuer(t["nummer"], guid, t["titel"], t["g_direktion_kurz"])
            eintraege.append(
                Eintrag(
                    nummer=t["nummer"], nummer_raw=t["nummer_raw"], titel=t["titel"],
                    url=KANTONSRAT_GESCHAEFT_URL.format(guid=guid) if guid else None,
                    bewertung=b, art=t["g_geschaeftsart"], direktion=t["g_direktion_kurz"],
                    kontext=f"{s['gremium_kurz']} {_d(s['datum'])}", datum=s["datum"],
                )
            )
    rel, pr = _sortiert(eintraege)
    bloecke.append(Block("In den Kommissionen", f"{len(komm)} Sitzungen mit {total} publizierten Traktanden", rel, pr, total))

    return Briefing(stichtag=stichtag, profil_name=profil.name, bloecke=bloecke, rohliste_url=rohliste_url)


# --- Markdown -----------------------------------------------------------------------


def _md_link(e: Eintrag) -> str:
    return f"[{e.label}]({e.url})" if e.url else e.label


def _meta_line(e: Eintrag) -> str:
    teile = [e.art, e.direktion, e.kontext]
    if e.datum and e.kontext in TYP_REIHENFOLGE:
        teile.append(_d(e.datum))
    return " · ".join(x for x in teile if x)


def render_markdown(b: Briefing) -> str:
    out = [f"# ASD-Briefing Kantonsrat, {_wochentag(b.stichtag)} {_d(b.stichtag.isoformat())}\n"]
    out.append(
        f"{b.anzahl_relevant} relevante Geschäfte, {b.anzahl_pruefen} zur Prüfung. "
        f"Auswahl nach Profil «{b.profil_name}» (Schlüsselwörter in Titel, Zusammenfassung und Volltext).\n"
    )
    for blk in b.bloecke:
        out.append(f"## {blk.titel}\n")
        if blk.untertitel:
            out.append(f"*{blk.untertitel}*\n")
        if blk.hinweis:
            out.append(blk.hinweis + "\n")
            continue
        if not blk.relevant and not blk.pruefen:
            out.append("Nichts mit Bezug zum Profil.\n")
            continue
        for e in blk.relevant:
            out.append(f"**{_md_link(e)} {e.titel}**  ")
            out.append(f"{_meta_line(e)}  ")
            out.append(f"Warum: {e.bewertung.begruendung}")
            if e.status_text:
                out.append(f"> {_kurztext(e.status_text, 400)}")
            for titel, url in e.dokumente[:3]:
                out.append(f"- [{titel}]({url})")
            out.append("")
        if blk.pruefen:
            out.append("Zur Prüfung:\n")
            for e in blk.pruefen:
                out.append(f"- {_md_link(e)} {e.titel} ({_meta_line(e)}) – {e.bewertung.begruendung}")
            out.append("")
        rest = blk.total - len(blk.relevant) - len(blk.pruefen)
        if rest > 0:
            out.append(f"{rest} weitere ohne Bezug zum Profil.\n")
    if b.rohliste_url:
        out.append(f"---\nVollständige Rohliste: {b.rohliste_url}\n")
    return "\n".join(out)


# --- HTML (Mail) ----------------------------------------------------------------------


def render_html(b: Briefing) -> str:
    """HTML mit Inline-Styles, damit es auch in Outlook und Gmail so aussieht wie gedacht."""
    h = html.escape
    S = {
        "body": "font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;font-size:15px;line-height:1.45;color:#222222;max-width:760px;margin:0 auto;padding:16px",
        "h1": "font-size:22px;margin:0 0 4px 0;font-weight:700",
        "h2": "font-size:17px;margin:28px 0 4px 0;border-bottom:1px solid #dddddd;padding-bottom:4px;font-weight:700",
        "sub": "color:#666666;font-size:13px;margin:0 0 12px 0",
        "item": "margin:0 0 14px 0;padding-left:10px;border-left:3px solid #0f62fe",
        "meta": "color:#555555;font-size:13px",
        "why": "font-size:13px;color:#444444",
        "quote": "font-size:13px;color:#444444;background:#f5f5f5;padding:6px 8px;margin:4px 0",
        "ul": "font-size:14px;padding-left:18px;margin:4px 0 12px 0",
        "rest": "color:#666666;font-size:13px",
        "a": "color:#0f62fe;text-decoration:none",
        "foot": "color:#888888;font-size:12px;margin-top:28px",
    }

    def a(url: str, text: str) -> str:
        return f'<a href="{h(url)}" style="{S["a"]}">{h(text)}</a>'

    def link(e: Eintrag) -> str:
        return a(e.url, e.label) if e.url else h(e.label)

    parts = [
        '<!doctype html><html lang="de"><head><meta charset="utf-8">',
        f"<title>ASD-Briefing Kantonsrat {h(_d(b.stichtag.isoformat()))}</title></head>",
        f'<body style="margin:0;padding:0;background:#ffffff"><div style="{S["body"]}">',
        f'<h1 style="{S["h1"]}">ASD-Briefing Kantonsrat, {h(_wochentag(b.stichtag))} {h(_d(b.stichtag.isoformat()))}</h1>',
        f'<p style="{S["sub"]}">{b.anzahl_relevant} relevante Geschäfte, {b.anzahl_pruefen} zur Prüfung · Profil «{h(b.profil_name)}»</p>',
    ]
    for blk in b.bloecke:
        parts.append(f'<h2 style="{S["h2"]}">{h(blk.titel)}</h2>')
        if blk.untertitel:
            parts.append(f'<p style="{S["sub"]}">{h(blk.untertitel)}</p>')
        if blk.hinweis:
            parts.append(f"<p>{h(blk.hinweis)}</p>")
            continue
        if not blk.relevant and not blk.pruefen:
            parts.append("<p>Nichts mit Bezug zum Profil.</p>")
            continue
        for e in blk.relevant:
            parts.append(f'<div style="{S["item"]}">')
            parts.append(f"<div><strong>{link(e)} {h(e.titel)}</strong></div>")
            parts.append(f'<div style="{S["meta"]}">{h(_meta_line(e))}</div>')
            parts.append(f'<div style="{S["why"]}">Warum: {h(e.bewertung.begruendung)}</div>')
            if e.status_text:
                parts.append(f'<div style="{S["quote"]}">{h(_kurztext(e.status_text, 400))}</div>')
            if e.dokumente:
                parts.append(f'<div style="{S["meta"]}">' + " · ".join(a(u, t) for t, u in e.dokumente[:3]) + "</div>")
            parts.append("</div>")
        if blk.pruefen:
            parts.append(f'<p style="{S["meta"]};margin:8px 0 0 0"><strong>Zur Prüfung</strong></p><ul style="{S["ul"]}">')
            for e in blk.pruefen:
                parts.append(f'<li>{link(e)} {h(e.titel)} <span style="{S["meta"]}">({h(_meta_line(e))}) – {h(e.bewertung.begruendung)}</span></li>')
            parts.append("</ul>")
        rest = blk.total - len(blk.relevant) - len(blk.pruefen)
        if rest > 0:
            parts.append(f'<p style="{S["rest"]}">{rest} weitere ohne Bezug zum Profil.</p>')
    foot = "Quelle: Geschäftsdatenbank des Kantonsrats Zürich (CDWS-Schnittstelle)."
    if b.rohliste_url:
        foot += " Vollständige Rohliste: " + a(b.rohliste_url, b.rohliste_url)
    parts.append(f'<p style="{S["foot"]}">{foot}</p></div></body></html>')
    return "\n".join(parts)


def _wochentag(d: date) -> str:
    return ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][d.weekday()]


def naechster_montag(heute: date | None = None) -> date:
    heute = heute or date.today()
    return heute + timedelta(days=(7 - heute.weekday()) % 7)
