"""Lädt die Daten eines Zeitfensters in den Store.

Ablauf:

1. Ablaufschritte der letzten Tage (alle Typen) aus ``ABLAUFSCHRITTE``.
2. Sitzungen (Rat und Kommissionen) im Fenster aus ``SITZUNGENDETAIL``; bei Ratssitzungen
   ohne strukturierte Traktanden wird die Traktandenliste aus dem PDF-Volltext geparst.
3. Alle referenzierten Geschäftsnummern, die noch fehlen, aus ``GESCHAEFT`` nachladen
   (inklusive Volltext der Dokumente).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import cdws
from .models import Sitzung
from .parse import parse_ablaufschritte, parse_geschaefte, parse_sitzungen
from .store import Store
from .traktanden import parse_traktandenliste

log = logging.getLogger(__name__)

LOOKUP_BATCH = 15


@dataclass
class SyncResult:
    stichtag: date
    ablauf_von: date
    ablauf_bis: date
    sitzung_von: date
    sitzung_bis: date
    neue_ablaufschritte: int = 0
    ablaufschritte_total: int = 0
    sitzungen: int = 0
    traktanden_pdf: int = 0
    traktanden_struktur: int = 0
    geschaefte_nachgeladen: int = 0
    nicht_gefunden: list[str] = field(default_factory=list)
    warnungen: list[str] = field(default_factory=list)


def fenster(stichtag: date, rueckblick_tage: int = 7, vorschau_tage: int = 14) -> tuple[date, date, date, date]:
    """Zeitfenster: Ablaufschritte rückwärts, Sitzungen rückwärts und vorwärts."""
    ablauf_von = stichtag - timedelta(days=rueckblick_tage)
    ablauf_bis = stichtag + timedelta(days=1)
    sitzung_von = stichtag - timedelta(days=rueckblick_tage)
    sitzung_bis = stichtag + timedelta(days=vorschau_tage)
    return ablauf_von, ablauf_bis, sitzung_von, sitzung_bis


def run_sync(client, store: Store, stichtag: date | None = None, rueckblick_tage: int = 7, vorschau_tage: int = 14) -> SyncResult:
    stichtag = stichtag or date.today()
    a_von, a_bis, s_von, s_bis = fenster(stichtag, rueckblick_tage, vorschau_tage)
    res = SyncResult(stichtag, a_von, a_bis, s_von, s_bis)
    nummern: set[str] = set()

    # 1. Ablaufschritte
    for page in client.iter_pages("ABLAUFSCHRITTE", cdws.q_ablaufschritte_seit(a_von, a_bis)):
        for a in parse_ablaufschritte(page.xml):
            res.ablaufschritte_total += 1
            if store.upsert_ablaufschritt(a):
                res.neue_ablaufschritte += 1
            if a.geschaeft.krnr:
                nummern.add(a.geschaeft.krnr)
    store.conn.commit()

    # 2. Sitzungen und Traktanden
    for page in client.iter_pages("SITZUNGENDETAIL", cdws.q_sitzungen(s_von, s_bis), page_size=30):
        for s in parse_sitzungen(page.xml):
            _ergaenze_traktanden_aus_pdf(s, res)
            store.upsert_sitzung(s)
            res.sitzungen += 1
            for t in s.traktanden:
                if t.quelle == "pdf":
                    res.traktanden_pdf += 1
                else:
                    res.traktanden_struktur += 1
                if t.nummer:
                    nummern.add(t.nummer)

    # 3. Geschäfte nachladen
    fehlend = store.fehlende_nummern(sorted(nummern))
    gefunden: set[str] = set()
    for i in range(0, len(fehlend), LOOKUP_BATCH):
        batch = fehlend[i : i + LOOKUP_BATCH]
        for page in client.iter_pages("GESCHAEFT", cdws.q_geschaeft_by_nummer(batch), page_size=LOOKUP_BATCH * 2):
            for g in parse_geschaefte(page.xml):
                if g.nummer in gefunden:
                    continue
                store.upsert_geschaeft(g)
                gefunden.add(g.nummer)
    res.geschaefte_nachgeladen = len(gefunden)
    res.nicht_gefunden = [n for n in fehlend if n not in gefunden]
    return res


def _ergaenze_traktanden_aus_pdf(s: Sitzung, res: SyncResult) -> None:
    if s.traktanden or not s.traktandenliste_text:
        return
    tl = parse_traktandenliste(s.traktandenliste_text)
    for w in tl.warnungen:
        res.warnungen.append(f"{s.titel}: {w}")
    traktanden = tl.traktanden
    # Doppelsitzung: ein PDF für zwei Sitzungen; die Nachmittagsgeschäfte gehören zur zweiten.
    if s.nummer and len(tl.sitzungsnummern) >= 2 and tl.nachmittag_ab is not None:
        if s.nummer == tl.sitzungsnummern[0]:
            traktanden = [t for t in traktanden if not t.nachmittag]
        elif s.nummer in tl.sitzungsnummern[1:]:
            traktanden = [t for t in traktanden if t.nachmittag]
    if s.nummer and tl.sitzungsnummern and s.nummer not in tl.sitzungsnummern:
        res.warnungen.append(f"{s.titel}: Traktandenliste nennt Sitzungen {tl.sitzungsnummern}")
    s.traktanden = traktanden
