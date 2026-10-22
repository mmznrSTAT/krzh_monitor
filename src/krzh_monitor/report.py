"""Markdown-Rohliste für ein Zeitfenster: Traktanden der kommenden Sitzungen und
Ablaufschritte der vergangenen Tage. Noch ohne Relevanzbewertung.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

from .models import KANTONSRAT_GESCHAEFT_URL
from .store import Store

TYP_REIHENFOLGE = [
    "Eingereicht",
    "Antwort Regierungsrat",
    "Stellungnahme Regierungsrat",
    "Antrag Regierungsrat",
    "Entgegennahme",
    "Antrag Kommission",
    "Medienmitteilung",
    "Antrag auf Diskussion",
    "Überweisung an Regierungsrat",
    "Zustimmung",
    "Ablehnung",
    "Rückweisung",
]


def _d(iso: str | None) -> str:
    if not iso:
        return ""
    y, m, d = iso[:10].split("-")
    return f"{d}.{m}.{y}"


def _link(nummer: str | None, guid: str | None, nummer_raw: str | None = None) -> str:
    label = nummer_raw or nummer or "–"
    if guid:
        return f"[{label}]({KANTONSRAT_GESCHAEFT_URL.format(guid=guid)})"
    return label


def _esc(s: str | None) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def render_report(store: Store, stichtag: date, ablauf_von: date, ablauf_bis: date, sitzung_von: date, sitzung_bis: date) -> str:
    out: list[str] = []
    out.append(f"# Kantonsrat Zürich – Wochenübersicht per {_d(stichtag.isoformat())}\n")
    out.append(
        f"Rohliste ohne Relevanzbewertung. Quelle: Geschäftsdatenbank des Kantonsrats "
        f"(CDWS-Schnittstelle), abgerufen am {_d(date.today().isoformat())}.\n"
    )

    # --- Sitzungen ---------------------------------------------------------------------
    sitzungen = store.sitzungen_zwischen(sitzung_von, sitzung_bis)
    rat = [s for s in sitzungen if s["gremium_typ"] == "Kantonsrat" and s["datum"] >= stichtag.isoformat()]
    kommissionen = [s for s in sitzungen if s["gremium_typ"] != "Kantonsrat"]

    out.append(f"## Kommende Ratssitzungen ({_d(stichtag.isoformat())} bis {_d(sitzung_bis.isoformat())})\n")
    if not rat:
        out.append("Keine Ratssitzung im Fenster.\n")
    for s in rat:
        traktanden = store.traktanden_der_sitzung(s["guid"])
        out.append(f"### {s['titel']} – {_d(s['datum'])}, {s['uhrzeit'] or ''}\n")
        if not traktanden:
            out.append("Noch keine Traktandenliste publiziert.\n")
            continue
        out.append("| Nr. | Geschäft | Titel | Art | Dir. | Behandlung |")
        out.append("|---:|---|---|---|---|---|")
        for t in traktanden:
            guid = t["geschaeft_guid"] or t["g_guid"]
            dirk = t["direktion_kurz"] or t["g_direktion_kurz"] or ""
            art = t["vorstossart"] or t["g_geschaeftsart"] or ""
            beh = ", ".join(x for x in [t["beratungsart"], t["behandlung"], "neu" if t["neu"] else None] if x)
            out.append(
                f"| {t['nr']} | {_link(t['nummer'], guid, t['nummer_raw'])} | {_esc(t['titel'])} | {_esc(art)} | {dirk} | {_esc(beh)} |"
            )
        out.append("")

    if kommissionen:
        out.append(
            f"## Kommissionssitzungen mit publizierten Traktanden "
            f"({_d(sitzung_von.isoformat())} bis {_d(sitzung_bis.isoformat())})\n"
        )
        any_row = False
        for s in kommissionen:
            traktanden = store.traktanden_der_sitzung(s["guid"])
            if not traktanden:
                continue
            any_row = True
            out.append(f"### {s['titel']} – {_d(s['datum'])}\n")
            for t in traktanden:
                guid = t["geschaeft_guid"] or t["g_guid"]
                out.append(f"- {_link(t['nummer'], guid, t['nummer_raw'])} {_esc(t['titel'])}")
            out.append("")
        if not any_row:
            out.append("Keine Kommission hat Traktanden publiziert.\n")

    # --- Ablaufschritte ------------------------------------------------------------------
    out.append(f"## Ablaufschritte vom {_d(ablauf_von.isoformat())} bis {_d(stichtag.isoformat())}\n")
    schritte = store.ablaufschritte_zwischen(ablauf_von, ablauf_bis)
    if not schritte:
        out.append("Keine Ablaufschritte im Fenster.\n")
    gruppen: dict[str, list] = defaultdict(list)
    for a in schritte:
        gruppen[a["typ"]].append(a)
    reihenfolge = [t for t in TYP_REIHENFOLGE if t in gruppen] + sorted(t for t in gruppen if t not in TYP_REIHENFOLGE)
    for typ in reihenfolge:
        rows = gruppen[typ]
        out.append(f"### {typ} ({len(rows)})\n")
        for a in rows:
            g = store.geschaeft_by_guid(a["geschaeft_guid"]) if a["geschaeft_guid"] else None
            dirk = (g["direktion_kurz"] if g else None) or _kurz(a["direktion"])
            art = (g["geschaeftsart"] if g else None) or ""
            titel = a["geschaeft_titel"] or (g["titel"] if g else "") or "(ohne Titel)"
            nummer = a["geschaeft_nummer"] or (g["nummer"] if g else None)
            label = _link(nummer, a["geschaeft_guid"], None)
            meta = " · ".join(x for x in [art, dirk, _d(a["datum"])] if x)
            out.append(f"- {label} **{_esc(titel)}** ({meta})")
            if typ not in ("Eingereicht",) and a["status_text"] and a["status_text"] != typ:
                out.append(f"  - {_esc(_kurztext(a['status_text']))}")
            doks = json.loads(a["dokumente"] or "[]")
            for d in doks[:3]:
                if d.get("edoc_id") and d.get("version"):
                    out.append(f"  - [{_esc(d['titel'])}](https://parlzhcdws.cmicloud.ch/parlzh5/cdws/Files/{d['edoc_id']}/{d['version']}/pdf)")
        out.append("")
    return "\n".join(out)


_KURZ = {
    "Direktion der Justiz und des Innern": "JI",
    "Sicherheitsdirektion": "DS",
    "Finanzdirektion": "FD",
    "Volkswirtschaftsdirektion": "VD",
    "Gesundheitsdirektion": "GD",
    "Bildungsdirektion": "BI",
    "Baudirektion": "BD",
    "Staatskanzlei": "SK",
}


def _kurz(direktion: str | None) -> str:
    if not direktion:
        return ""
    return _KURZ.get(direktion, direktion)


def _kurztext(text: str, limit: int = 300) -> str:
    import re

    t = re.sub(r"<[^>]+>", "", text)  # HTML-Links in StatusText
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"
