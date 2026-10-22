from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def traktandenliste_text() -> str:
    return (FIXTURES / "traktandenliste_2026-10-26.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def sitzungen_xml(traktandenliste_text: str) -> str:
    """Sitzungs-XML mit eingesetztem Traktandenlisten-Volltext (im Fixture ein Platzhalter)."""
    xml = (FIXTURES / "sitzungen.xml").read_text(encoding="utf-8")
    text = traktandenliste_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return xml.replace("[TRAKTANDENLISTE_2026-10-26]", text)


@pytest.fixture(scope="session")
def ablaufschritte_xml() -> str:
    return (FIXTURES / "ablaufschritte.xml").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def geschaefte_xml() -> str:
    return (FIXTURES / "geschaefte.xml").read_text(encoding="utf-8")


class FakeClient:
    """Liefert je Index eine feste Antwortseite, unabhängig von der Abfrage."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.queries: list[tuple[str, str]] = []

    def iter_pages(self, index: str, query: str, page_size: int = 100, max_hits=None):
        from krzh_monitor.cdws import Page

        self.queries.append((index, query))
        xml = self.pages.get(index.upper())
        if xml is None:
            return
        yield Page(index=index.upper(), query=query, start=1, page_size=page_size, xml=xml)


@pytest.fixture
def fake_client(ablaufschritte_xml, sitzungen_xml, geschaefte_xml) -> FakeClient:
    return FakeClient({"ABLAUFSCHRITTE": ablaufschritte_xml, "SITZUNGENDETAIL": sitzungen_xml, "GESCHAEFT": geschaefte_xml})
