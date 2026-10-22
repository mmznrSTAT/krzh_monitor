from datetime import date
from pathlib import Path

from krzh_monitor.briefing import baue_briefing, naechster_montag, render_html, render_markdown
from krzh_monitor.relevanz import bewerte, lade_profil
from krzh_monitor.store import Store
from krzh_monitor.sync import run_sync

PROFIL = Path(__file__).resolve().parents[1] / "profiles" / "asd.toml"


def test_profil_laedt():
    p = lade_profil(PROFIL)
    assert p.name == "ASD"
    assert len(p.begriffe) > 30
    assert p.schwelle_relevant > p.schwelle_pruefen


def test_bewertung_titeltreffer():
    p = lade_profil(PROFIL)
    b = bewerte(p, "Kantonales Verbot von bezahltem Sammeln von Unterschriften", direktion_kurz="JI")
    assert b.stufe == "relevant" and "Politische Rechte" in b.themen
    assert "Sammeln von Unterschriften (Titel)" in b.begruendung

    b = bewerte(p, "Datenlage und Unterstützung intermittierend Beschäftigter im Kanton Zürich")
    assert b.stufe == "relevant" and b.themen == ["Statistik"]

    # Komposita: Subventionsdatenbank, Kriminalstatistik
    assert bewerte(p, "Öffentlich zugängliche Subventionsdatenbank").stufe == "relevant"
    assert bewerte(p, "Polizeiliche Kriminalstatistik 2025 veröffentlichen").stufe == "relevant"

    # Schwache Titeltreffer (Gewicht 1) reichen nicht für «relevant», mit Volltext für «prüfen»
    assert bewerte(p, "Regelmässige Transparenz über Steuerabzüge natürlicher Personen").stufe == "keine"
    b = bewerte(p, "Regelmässige Transparenz über Steuerabzüge natürlicher Personen", volltext="Die Datengrundlage fehlt.")
    assert b.stufe == "pruefen"

    # Ohne Treffer
    assert bewerte(p, "Mehr Tempo bei Baubewilligungen").stufe == "keine"


def test_bewertung_volltext_und_ausschluss():
    p = lade_profil(PROFIL)
    # Volltext allein führt höchstens zu «prüfen», auch bei vielen Treffern
    text = "Statistik " * 10 + "Datenlage Monitoring Indikatoren Open Government Data"
    b = bewerte(p, "Attraktivität des Hausarztberufes", volltext=text)
    assert b.stufe == "pruefen"
    assert b.score <= p.volltext_max + 0.01

    # Volltext bestätigt einen Titeltreffer
    b = bewerte(p, "Bericht zum Stand der Digitalisierung", volltext="Interoperabilität Schnittstellen Daten")
    assert b.stufe == "relevant"

    # Floskel «untersteht dem fakultativen Referendum» bleibt unter der Prüfschwelle
    b = bewerte(p, "Objektkredit Neubau", volltext="Dieser Beschluss untersteht dem fakultativen Referendum.")
    assert b.stufe == "keine"

    # Ausschlüsse: parlamentsinterne Wahlen, Budget
    assert bewerte(p, "Wahl Ersatzmitglied Obergericht für Verena Seiler", volltext="Statistik Daten Wahlrecht").ausgeschlossen
    assert bewerte(p, "Festsetzung Budget für das Rechnungsjahr 2027", volltext="Amt für Statistik und Daten " * 30).stufe == "keine"

    # «Kandidaten» ist kein Datentreffer
    b = bewerte(p, "Anhörung", volltext="Die Kandidaten stellen sich vor.")
    assert b.score == 0

    # Abkürzungen nur in Grossschreibung
    assert bewerte(p, "Bericht", volltext="Die Kinder ki ki").score == 0
    assert bewerte(p, "Bericht", volltext="Einsatz von KI in der Verwaltung").score > 0


def test_naechster_montag():
    assert naechster_montag(date(2026, 10, 22)) == date(2026, 10, 26)
    assert naechster_montag(date(2026, 10, 26)) == date(2026, 10, 26)
    assert naechster_montag(date(2026, 10, 27)) == date(2026, 11, 2)


def test_briefing_aus_fixtures(tmp_path, fake_client):
    store = Store(tmp_path / "t.sqlite")
    run_sync(fake_client, store, stichtag=date(2026, 10, 22))
    profil = lade_profil(PROFIL)
    b = baue_briefing(store, profil, date(2026, 10, 26), rohliste_url="https://example.org/latest.md")

    assert [blk.titel[:5] for blk in b.bloecke] == ["Heute", "Verga", "In de"]
    rat = b.bloecke[0]
    assert rat.titel == "Heute im Kantonsrat: 174. KR-Sitzung"
    assert rat.total == 37  # Traktanden 2–38 (Mitteilungen ohne Nummer zählt nicht)
    relevante = {e.nummer for e in rat.relevant}
    # 288/2024 ist als Geschäft geladen (Volltext), 91/2026 nur über den Titel aus der Traktandenliste
    assert {"288/2024", "91/2026"} <= relevante
    e = next(e for e in rat.relevant if e.nummer == "288/2024")
    assert e.url.endswith("75871c1609de433e814b705f53c5272d")
    assert e.kontext == "Traktandum 27 · Entgegennahme, Diskussion"
    assert e.direktion == "JI" and e.art == "Motion"

    woche = b.bloecke[1]
    assert woche.total == 5  # Ablaufschritte 19.–25.10. im Fixture (2 Eingereicht, 1 Entgegennahme, 2 Medienmitteilungen)
    komm = b.bloecke[2]
    assert komm.total == 7  # KPB 20.10.

    md = render_markdown(b)
    assert md.startswith("# ASD-Briefing Kantonsrat, Montag 26.10.2026")
    assert "**[288/2024](https://www.kantonsrat.zh.ch/geschaefte/geschaeft?id=75871c1609de433e814b705f53c5272d) Kantonales Verbot" in md
    assert "Warum: Sammeln von Unterschriften (Titel)" in md
    assert "Vollständige Rohliste: https://example.org/latest.md" in md

    html = render_html(b)
    assert "<title>ASD-Briefing Kantonsrat 26.10.2026</title>" in html
    assert 'href="https://www.kantonsrat.zh.ch/geschaefte/geschaeft?id=75871c1609de433e814b705f53c5272d"' in html
    assert "Kantonales Verbot von bezahltem Sammeln von Unterschriften" in html
    assert "Warum: Sammeln von Unterschriften (Titel)" in html
    store.close()


def test_briefing_ohne_sitzung(tmp_path, fake_client):
    store = Store(tmp_path / "t.sqlite")
    run_sync(fake_client, store, stichtag=date(2026, 10, 22))
    b = baue_briefing(store, lade_profil(PROFIL), date(2026, 12, 7))
    assert b.bloecke[0].hinweis.startswith("Keine Ratssitzung")
    md = render_markdown(b)
    assert "Keine Ratssitzung in den nächsten sieben Tagen." in md
    store.close()
