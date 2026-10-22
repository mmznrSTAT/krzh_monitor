"""HTTP-Client für die CDWS-Schnittstelle des Zürcher Kantonsrats (CMI Axioma).

Die Daten liegen auf zwei Instanzen derselben Schnittstelle:

* ``parlzh5``: Indizes ``GESCHAEFT`` und ``ABLAUFSCHRITTE``
* ``parlzh3``: Index ``SITZUNGENDETAIL``

Abfragen folgen einer CQL-ähnlichen Syntax, zum Beispiel
``sitzungsdatum_start >= "2026-10-19 00:00:00" sortBy sitzungsdatum_start/sort.descending``.
Die Antwort ist XML; ``numHits`` steht im Wurzelelement, Paginierung läuft über ``s`` (Start,
1-basiert) und ``m`` (Seitengrösse).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://parlzhcdws.cmicloud.ch"
INSTANCE_FOR_INDEX = {
    "GESCHAEFT": "parlzh5",
    "ABLAUFSCHRITTE": "parlzh5",
    "GESCHAEFT_DIREKTION": "parlzh5",
    "SITZUNGENDETAIL": "parlzh3",
}
DEFAULT_PAGE_SIZE = 100
USER_AGENT = "krzh-monitor/0.1 (+https://github.com/mmznrSTAT)"


class CdwsError(RuntimeError):
    """Fehler der Schnittstelle, inklusive der sprechenden 406-Meldungen (z. B. unknown Field)."""


@dataclass(frozen=True)
class Page:
    index: str
    query: str
    start: int
    page_size: int
    xml: str


def cql_date(d: date) -> str:
    """Datum im CQL-Format der Schnittstelle, z. B. ``"2026-10-19 00:00:00"``."""
    return f'"{d.isoformat()} 00:00:00"'


class CdwsClient:
    def __init__(
        self,
        base_url: str = BASE_URL,
        session: requests.Session | None = None,
        timeout: float = 60.0,
        pause: float = 0.3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.timeout = timeout
        self.pause = pause

    def url(self, index: str) -> str:
        instance = INSTANCE_FOR_INDEX[index.upper()]
        return f"{self.base_url}/{instance}/cdws/Index/{index.upper()}/searchdetails"

    def fetch_page(self, index: str, query: str, start: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> Page:
        params = {"q": query, "l": "de-CH", "s": start, "m": page_size}
        log.debug("GET %s %s", self.url(index), params)
        resp = self.session.get(self.url(index), params=params, timeout=self.timeout)
        if resp.status_code == 406:
            raise CdwsError(_extract_406_message(resp.text))
        resp.raise_for_status()
        # Die XML-Deklaration sagt utf-8; nicht auf das Raten von requests verlassen.
        return Page(index=index.upper(), query=query, start=start, page_size=page_size, xml=resp.content.decode("utf-8"))

    def iter_pages(self, index: str, query: str, page_size: int = DEFAULT_PAGE_SIZE, max_hits: int | None = None) -> Iterator[Page]:
        """Liefert Seite für Seite, bis ``numHits`` erreicht ist."""
        from .parse import num_hits, count_hits  # lokaler Import, vermeidet Zyklus

        start = 1
        total = None
        fetched = 0
        while True:
            page = self.fetch_page(index, query, start=start, page_size=page_size)
            if total is None:
                total = num_hits(page.xml)
            got = count_hits(page.xml)
            yield page
            fetched += got
            if got == 0 or fetched >= total or (max_hits is not None and fetched >= max_hits):
                return
            start += got
            if self.pause:
                time.sleep(self.pause)


def _extract_406_message(html: str) -> str:
    import re

    m = re.search(r"(unknown Field '[^']+'|[A-Za-z ]+Exception[^<]*)", html)
    return m.group(1) if m else "CDWS 406 Not Acceptable (Abfragesyntax prüfen)"


# --- Fertige Abfragen -------------------------------------------------------------------


def q_ablaufschritte_seit(seit: date, bis: date | None = None) -> str:
    q = f"sitzungsdatum_start >= {cql_date(seit)}"
    if bis is not None:
        q += f" and sitzungsdatum_start < {cql_date(bis)}"
    return q + " sortBy sitzungsdatum_start/sort.descending"


def q_sitzungen(von: date, bis: date) -> str:
    return (
        f"datum_start >= {cql_date(von)} and datum_start < {cql_date(bis)}"
        " sortBy datum_start/sort.ascending"
    )


def q_geschaeft_by_nummer(nummern: list[str]) -> str:
    """Geschäfte nach KR-Nr. (``288/2024``) oder Vorlagen-Nr. (``6082``) nachschlagen.

    Buchstabensuffixe (``114b/2023``, ``6082a``) bezeichnen Dokumentversionen und werden
    entfernt; das Feld ``krnr`` enthält beide Nummernarten.
    """
    from .nummern import normalize_nummer

    terms = [f'krnr adj "{normalize_nummer(n)}"' for n in nummern]
    return " or ".join(terms)


def q_geschaefte_seit(seit: date) -> str:
    """Geschäfte, die seit ``seit`` eingereicht wurden (Feld ``Beginn``)."""
    return f"beginn_start >= {cql_date(seit)} sortBy beginn_start/sort.descending"
