"""SQLite-Ablage. Eine Datei, vier Tabellen, keine ORM-Abhängigkeit.

Die Tabellen halten die Rohdaten der Schnittstelle; Relevanz und Benachrichtigung
kommen in späteren Iterationen als eigene Tabellen dazu (``bewertungen``, ``gesendet``).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from .models import Ablaufschritt, Geschaeft, Sitzung

SCHEMA = """
CREATE TABLE IF NOT EXISTS geschaefte (
    guid            TEXT PRIMARY KEY,
    nummer          TEXT,            -- normalisiert: "288/2024" oder "6082"
    krnr            TEXT,
    vorlage_nr      TEXT,
    titel           TEXT NOT NULL,
    geschaeftsart   TEXT,
    kommission      TEXT,
    kommission_kurz TEXT,
    direktion       TEXT,
    direktion_kurz  TEXT,
    beginn          TEXT,            -- ISO-Datum
    erstpublikation TEXT,
    pendent_bei     TEXT,
    zusammenfassung TEXT,
    beteiligungen   TEXT,            -- JSON
    volltext        TEXT,            -- zusammengesetzte Dokumentvolltexte
    json            TEXT NOT NULL,   -- vollständiger Datensatz
    geladen_am      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_geschaefte_nummer ON geschaefte(nummer);

CREATE TABLE IF NOT EXISTS ablaufschritte (
    guid            TEXT PRIMARY KEY,
    typ             TEXT NOT NULL,
    datum           TEXT,
    status_text     TEXT,
    geschaeft_guid  TEXT,
    geschaeft_nummer TEXT,
    geschaeft_titel TEXT,
    direktion       TEXT,
    kommission      TEXT,
    dokumente       TEXT,            -- JSON
    erstmals_gesehen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ablauf_datum ON ablaufschritte(datum);
CREATE INDEX IF NOT EXISTS ix_ablauf_geschaeft ON ablaufschritte(geschaeft_guid);

CREATE TABLE IF NOT EXISTS sitzungen (
    guid            TEXT PRIMARY KEY,
    titel           TEXT NOT NULL,
    nummer          INTEGER,
    datum           TEXT NOT NULL,
    uhrzeit         TEXT,
    gremium_kurz    TEXT,
    gremium_typ     TEXT,
    traktandenliste_text TEXT,
    vorschau_text   TEXT,
    geladen_am      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS traktanden (
    sitzung_guid    TEXT NOT NULL,
    nr              INTEGER NOT NULL,
    titel           TEXT NOT NULL,
    nummer          TEXT,
    nummer_raw      TEXT,
    geschaeft_guid  TEXT,
    direktion_kurz  TEXT,
    vorstossart     TEXT,
    beratungsart    TEXT,
    behandlung      TEXT,
    detail          TEXT,
    gemeinsam_mit   TEXT,            -- JSON
    neu             INTEGER DEFAULT 0,
    nachmittag      INTEGER DEFAULT 0,
    quelle          TEXT,
    PRIMARY KEY (sitzung_guid, nr, quelle)
);
CREATE INDEX IF NOT EXISTS ix_traktanden_nummer ON traktanden(nummer);
"""


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _json_default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(type(o))


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- Geschäfte ---------------------------------------------------------------

    def upsert_geschaeft(self, g: Geschaeft) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            """INSERT INTO geschaefte (guid, nummer, krnr, vorlage_nr, titel, geschaeftsart, kommission,
                 kommission_kurz, direktion, direktion_kurz, beginn, erstpublikation, pendent_bei,
                 zusammenfassung, beteiligungen, volltext, json, geladen_am)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(guid) DO UPDATE SET
                 nummer=excluded.nummer, krnr=excluded.krnr, vorlage_nr=excluded.vorlage_nr,
                 titel=excluded.titel, geschaeftsart=excluded.geschaeftsart, kommission=excluded.kommission,
                 kommission_kurz=excluded.kommission_kurz, direktion=excluded.direktion,
                 direktion_kurz=excluded.direktion_kurz, beginn=excluded.beginn,
                 erstpublikation=excluded.erstpublikation, pendent_bei=excluded.pendent_bei,
                 zusammenfassung=excluded.zusammenfassung, beteiligungen=excluded.beteiligungen,
                 volltext=excluded.volltext, json=excluded.json, geladen_am=excluded.geladen_am""",
            (
                g.guid, g.nummer, g.krnr, g.vorlage_nr, g.titel, g.geschaeftsart, g.kommission,
                g.kommission_kurz, g.direktion, g.direktion_kurz, _iso(g.beginn), _iso(g.erstpublikation),
                g.pendent_bei, g.zusammenfassung,
                json.dumps([asdict(b) for b in g.beteiligungen], ensure_ascii=False),
                g.volltext or None,
                json.dumps(asdict(g), ensure_ascii=False, default=_json_default),
                now,
            ),
        )
        for a in g.ablaufschritte:
            self.upsert_ablaufschritt(a)
        self.conn.commit()

    def geschaeft_by_nummer(self, nummer: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM geschaefte WHERE nummer = ?", (nummer,)).fetchone()

    def geschaeft_by_guid(self, guid: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM geschaefte WHERE guid = ?", (guid,)).fetchone()

    def fehlende_nummern(self, nummern: list[str]) -> list[str]:
        """Welche der Nummern sind noch nicht in der Datenbank?"""
        out = []
        for n in nummern:
            if self.geschaeft_by_nummer(n) is None:
                out.append(n)
        return out

    # --- Ablaufschritte ----------------------------------------------------------

    def upsert_ablaufschritt(self, a: Ablaufschritt) -> bool:
        """Gibt True zurück, wenn der Schritt neu war."""
        now = datetime.now().isoformat(timespec="seconds")
        existed = self.conn.execute("SELECT 1 FROM ablaufschritte WHERE guid = ?", (a.guid,)).fetchone()
        self.conn.execute(
            """INSERT INTO ablaufschritte (guid, typ, datum, status_text, geschaeft_guid, geschaeft_nummer,
                 geschaeft_titel, direktion, kommission, dokumente, erstmals_gesehen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(guid) DO UPDATE SET
                 typ=excluded.typ, datum=excluded.datum, status_text=excluded.status_text,
                 geschaeft_guid=COALESCE(excluded.geschaeft_guid, ablaufschritte.geschaeft_guid),
                 geschaeft_nummer=COALESCE(excluded.geschaeft_nummer, ablaufschritte.geschaeft_nummer),
                 geschaeft_titel=COALESCE(excluded.geschaeft_titel, ablaufschritte.geschaeft_titel),
                 direktion=COALESCE(excluded.direktion, ablaufschritte.direktion),
                 kommission=COALESCE(excluded.kommission, ablaufschritte.kommission),
                 dokumente=excluded.dokumente""",
            (
                a.guid, a.typ, _iso(a.datum), a.status_text, a.geschaeft.guid, a.geschaeft.krnr,
                a.geschaeft.titel, a.geschaeft.direktion, a.geschaeft.kommission,
                json.dumps([{k: v for k, v in asdict(d).items() if k != "fulltext"} for d in a.dokumente], ensure_ascii=False),
                now,
            ),
        )
        return existed is None

    def ablaufschritte_zwischen(self, von: date, bis: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM ablaufschritte WHERE datum >= ? AND datum < ? ORDER BY datum DESC, typ, geschaeft_nummer",
            (von.isoformat(), bis.isoformat()),
        ).fetchall()

    # --- Sitzungen und Traktanden --------------------------------------------------

    def upsert_sitzung(self, s: Sitzung) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            """INSERT INTO sitzungen (guid, titel, nummer, datum, uhrzeit, gremium_kurz, gremium_typ,
                 traktandenliste_text, vorschau_text, geladen_am)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(guid) DO UPDATE SET titel=excluded.titel, nummer=excluded.nummer,
                 datum=excluded.datum, uhrzeit=excluded.uhrzeit, gremium_kurz=excluded.gremium_kurz,
                 gremium_typ=excluded.gremium_typ,
                 traktandenliste_text=COALESCE(excluded.traktandenliste_text, sitzungen.traktandenliste_text),
                 vorschau_text=COALESCE(excluded.vorschau_text, sitzungen.vorschau_text),
                 geladen_am=excluded.geladen_am""",
            (s.guid, s.titel, s.nummer, s.datum.isoformat(), s.uhrzeit, s.gremium_kurz, s.gremium_typ,
             s.traktandenliste_text, s.vorschau_text, now),
        )
        quellen = {t.quelle for t in s.traktanden}
        for q in quellen:
            self.conn.execute("DELETE FROM traktanden WHERE sitzung_guid = ? AND quelle = ?", (s.guid, q))
        self.conn.executemany(
            """INSERT INTO traktanden (sitzung_guid, nr, titel, nummer, nummer_raw, geschaeft_guid, direktion_kurz,
                 vorstossart, beratungsart, behandlung, detail, gemeinsam_mit, neu, nachmittag, quelle)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (s.guid, t.nr, t.titel, t.nummer, t.nummer_raw, t.geschaeft_guid, t.direktion_kurz, t.vorstossart,
                 t.beratungsart, t.behandlung, t.detail, json.dumps(t.gemeinsam_mit), int(t.neu), int(t.nachmittag), t.quelle)
                for t in s.traktanden
            ],
        )
        self.conn.commit()

    def sitzungen_zwischen(self, von: date, bis: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM sitzungen WHERE datum >= ? AND datum < ? ORDER BY datum, uhrzeit",
            (von.isoformat(), bis.isoformat()),
        ).fetchall()

    def traktanden_der_sitzung(self, sitzung_guid: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT t.*, g.titel AS g_titel, g.direktion_kurz AS g_direktion_kurz, g.geschaeftsart AS g_geschaeftsart,
                      g.guid AS g_guid, g.kommission_kurz AS g_kommission_kurz
               FROM traktanden t LEFT JOIN geschaefte g ON g.nummer = t.nummer
               WHERE t.sitzung_guid = ? ORDER BY t.nr""",
            (sitzung_guid,),
        ).fetchall()

    # --- Statistik -----------------------------------------------------------------

    def counts(self) -> dict[str, int]:
        return {
            t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("geschaefte", "ablaufschritte", "sitzungen", "traktanden")
        }
