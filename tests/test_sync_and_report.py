from datetime import date

from krzh_monitor.report import render_report
from krzh_monitor.store import Store
from krzh_monitor.sync import fenster, run_sync


def test_sync_end_to_end(tmp_path, fake_client):
    store = Store(tmp_path / "t.sqlite")
    stichtag = date(2026, 10, 22)
    res = run_sync(fake_client, store, stichtag=stichtag)

    assert res.ablaufschritte_total == 20 and res.neue_ablaufschritte == 20
    assert res.sitzungen == 3
    assert res.traktanden_struktur == 6 + 7
    # 174 ist die Vormittagssitzung der Doppelsitzung: nur Traktanden 1–38 aus dem PDF
    assert res.traktanden_pdf == 38
    assert res.warnungen == []
    # Nachladen: der Fake liefert drei Geschäfte, alle anderen Nummern bleiben offen
    assert res.geschaefte_nachgeladen == 3
    assert "288/2024" not in res.nicht_gefunden
    assert "369/2025" in res.nicht_gefunden

    counts = store.counts()
    assert counts["geschaefte"] == 3
    assert counts["sitzungen"] == 3
    assert counts["traktanden"] == 6 + 7 + 38
    # Ablaufschritte der nachgeladenen Geschäfte kommen dazu; gleiche GUIDs (382/2026 «Eingereicht»)
    # werden nicht verdoppelt: 20 aus dem Index + (1 + 3 + 3) aus den Geschäften - 1 Überschneidung
    assert counts["ablaufschritte"] == 20 + 7 - 1

    # Zweiter Lauf: nichts ist neu, Traktanden werden ersetzt statt verdoppelt
    res2 = run_sync(fake_client, store, stichtag=stichtag)
    assert res2.neue_ablaufschritte == 0
    assert store.counts()["traktanden"] == 6 + 7 + 38

    # Join Traktandum ↔ Geschäft über die normalisierte Nummer
    s174 = next(s for s in store.sitzungen_zwischen(date(2026, 10, 26), date(2026, 10, 27)) if s["nummer"] == 174)
    rows = store.traktanden_der_sitzung(s174["guid"])
    t27 = next(r for r in rows if r["nr"] == 27)
    assert t27["nummer"] == "288/2024"
    assert t27["g_guid"] == "75871c1609de433e814b705f53c5272d"
    assert t27["g_direktion_kurz"] == "JI"
    t4 = next(r for r in rows if r["nr"] == 4)
    assert t4["nummer"] == "6082" and t4["g_guid"] == "b7ea39c8a14b441988d115a59265c179"

    # Fenster
    a_von, a_bis, s_von, s_bis = fenster(stichtag)
    assert (a_von, a_bis, s_von, s_bis) == (date(2026, 10, 15), date(2026, 10, 23), date(2026, 10, 15), date(2026, 11, 5))
    store.close()


def test_report(tmp_path, fake_client):
    store = Store(tmp_path / "t.sqlite")
    stichtag = date(2026, 10, 22)
    run_sync(fake_client, store, stichtag=stichtag)
    md = render_report(store, stichtag, *fenster(stichtag))
    store.close()

    assert "# Kantonsrat Zürich – Wochenübersicht per 22.10.2026" in md
    assert "### 174. KR-Sitzung – 26.10.2026, 08:15" in md
    # Verlinkung über die GUID aus dem nachgeladenen Geschäft
    assert "[288/2024](https://www.kantonsrat.zh.ch/geschaefte/geschaeft?id=75871c1609de433e814b705f53c5272d)" in md
    assert "| 27 | [288/2024]" in md and "Kantonales Verbot von bezahltem Sammeln von Unterschriften | Motion | JI | Entgegennahme, Diskussion |" in md
    # Nachmittagsgeschäfte (ab 39) gehören nicht zur 174. Sitzung
    assert "| 39 |" not in md
    assert "### 104. KPB-Sitzung – 20.10.2026" in md
    assert "### Eingereicht (2)" in md
    assert "[382/2026](https://www.kantonsrat.zh.ch/geschaefte/geschaeft?id=ef598da0ab5f45f99135f7972fd665de) **Vertragspaket Schweiz" in md
    assert "### Entgegennahme (1)" in md and "### Medienmitteilung (2)" in md
    # Schritte vor dem Fenster (30.09.) erscheinen nicht
    assert "### Antwort Regierungsrat" not in md
    # HTML-Links im StatusText werden entfernt
    assert "<a href" not in md
