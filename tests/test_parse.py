from datetime import date

from krzh_monitor.nummern import parse_nummer, normalize_nummer
from krzh_monitor.parse import num_hits, parse_ablaufschritte, parse_geschaefte, parse_sitzungen


def test_nummern():
    assert normalize_nummer("288/2024") == "288/2024"
    assert normalize_nummer("114b/2023") == "114/2023"
    assert normalize_nummer("234a/2024a") == "234/2024"
    assert normalize_nummer("6082a") == "6082"
    assert normalize_nummer(" 6112 ") == "6112"
    n = parse_nummer("30b/2025")
    assert n.art == "krnr" and n.version == "b" and n.display == "KR-Nr. 30b/2025"
    assert parse_nummer("6068a").display == "Vorlage 6068a"
    assert parse_nummer("Mitteilungen") is None


def test_num_hits(ablaufschritte_xml):
    assert num_hits(ablaufschritte_xml) == 102


def test_parse_ablaufschritte(ablaufschritte_xml):
    schritte = parse_ablaufschritte(ablaufschritte_xml)
    assert len(schritte) == 20
    typen = {a.typ for a in schritte}
    assert {"Eingereicht", "Antwort Regierungsrat", "Zustimmung", "Rückweisung", "Medienmitteilung"} <= typen

    eingereicht = [a for a in schritte if a.typ == "Eingereicht"]
    a = next(x for x in eingereicht if x.geschaeft.krnr == "382/2026")
    assert a.datum == date(2026, 10, 19)
    assert a.geschaeft.guid == "ef598da0ab5f45f99135f7972fd665de"
    assert a.geschaeft.titel.startswith("Vertragspaket Schweiz")
    assert a.geschaeft.geschaeftsart == "Anfrage"
    assert a.geschaeft.direktion is None  # frisch eingereicht: noch keine Zuteilung
    assert a.dokumente[0].edoc_id == "01f792dea3234d238f09133185a93998-332"
    assert a.dokumente[0].version == 1
    assert a.dokumente[0].pdf_url().endswith("/01f792dea3234d238f09133185a93998-332/1/pdf")

    # Vorlage ohne KR-Nr.: Referenz nur über GUID und Titel
    mm = next(x for x in schritte if x.typ == "Medienmitteilung")
    assert mm.geschaeft.krnr is None
    assert mm.geschaeft.direktion == "Bildungsdirektion"

    # JI-Geschäft mit Direktion
    rr = next(x for x in schritte if x.geschaeft.krnr == "209/2023")
    assert rr.typ == "Antrag Regierungsrat"
    assert rr.geschaeft.direktion == "Direktion der Justiz und des Innern"


def test_parse_geschaefte(geschaefte_xml):
    gs = {g.nummer: g for g in parse_geschaefte(geschaefte_xml)}
    assert set(gs) == {"382/2026", "6082", "288/2024"}

    g = gs["288/2024"]
    assert g.krnr == "288/2024" and g.vorlage_nr is None
    assert g.direktion_kurz == "JI"
    assert g.geschaeftsart == "Motion"
    assert g.beginn == date(2024, 9, 10)
    assert g.erstpublikation == date(2024, 9, 9)
    assert g.pendent_bei == "Kantonsrat"
    assert [b.name for b in g.beteiligungen] == ["Heer", "Grossen-Aerni", "Stofer", "Yuste"]
    assert g.beteiligungen[0].rolle.startswith("Erstunterzeichner")
    assert g.beteiligungen[0].partei == "Grüne"
    assert [a.typ for a in g.ablaufschritte] == ["Eingereicht", "Entgegennahme", "Antrag auf Diskussion"]
    assert "bezahlten Unterschriftensammlung" in g.volltext
    assert g.url == "https://www.kantonsrat.zh.ch/geschaefte/geschaeft?id=75871c1609de433e814b705f53c5272d"
    # Dokument mit mehreren Versionen: letzte Version mit Rendition zählt
    assert g.ablaufschritte[0].dokumente[0].version == 3

    v = gs["6082"]
    assert v.krnr is None and v.vorlage_nr == "6082"
    assert v.kommission_kurz == "STGK" and v.direktion_kurz == "FD"
    assert v.ablaufschritte[1].dokumente[0].titel.startswith("Antrag STGK 6082a")


def test_parse_sitzungen(sitzungen_xml):
    sitzungen = {s.titel: s for s in parse_sitzungen(sitzungen_xml)}
    assert set(sitzungen) == {"173. KR-Sitzung", "104. KPB-Sitzung", "174. KR-Sitzung"}

    s173 = sitzungen["173. KR-Sitzung"]
    assert s173.datum == date(2026, 10, 19) and s173.nummer == 173 and s173.ist_ratssitzung
    assert [t.nr for t in s173.traktanden] == [2, 3, 4, 5, 6, 7]
    assert s173.traktanden[0].nummer == "333/2026"
    assert s173.traktanden[0].geschaeft_guid == "8b63147e88c147e0aa80634e78392f04"
    assert s173.traktanden[2].nummer == "6047"  # Vorlage
    assert all(t.quelle == "struktur" for t in s173.traktanden)
    assert s173.traktandenliste_text == "[FULLTEXT]"

    kpb = sitzungen["104. KPB-Sitzung"]
    assert kpb.gremium_typ == "Sachkommission" and kpb.gremium_kurz == "KPB"
    assert [t.nr for t in kpb.traktanden] == [3, 4, 5, 6, 7, 8, 9]
    t = next(t for t in kpb.traktanden if t.nummer == "6116")
    assert t.titel == "Bauprogramm der Staatsstrassen für die Jahre 2027–2029"  # Nummernpräfix entfernt
    t = next(t for t in kpb.traktanden if t.nummer == "66/2024")
    assert t.titel == "Kantonales Verbandsbeschwerderecht"

    s174 = sitzungen["174. KR-Sitzung"]
    assert s174.traktanden == []
    assert s174.traktandenliste_text.startswith("Einladung")
    assert s174.vorschau_text == "[FULLTEXT]"
