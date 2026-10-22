from collections import Counter

from krzh_monitor.traktanden import parse_traktandenliste


def test_kopf_und_umfang(traktandenliste_text):
    tl = parse_traktandenliste(traktandenliste_text)
    assert tl.sitzungsnummern == [174, 175]
    assert tl.nachmittag_ab == 39
    assert tl.warnungen == []
    assert [t.nr for t in tl.traktanden] == list(range(1, 142))
    # Einziges Traktandum ohne Geschäftsnummer: Mitteilungen
    assert [t.nr for t in tl.traktanden if t.nummer is None] == [1]


def test_einzelne_traktanden(traktandenliste_text):
    tl = parse_traktandenliste(traktandenliste_text)
    by_nr = {t.nr: t for t in tl.traktanden}

    # Wahl ohne Vorstossart, KR-Nr. auf eigener Zeile
    t = by_nr[2]
    assert t.titel == "Wahl Ersatzmitglied Obergericht für Verena Seiler"
    assert t.nummer == "369/2025" and t.vorstossart is None

    # Vorlage mit Versionssuffix und Ausgabenbremse, Direktion am Zeilenende
    t = by_nr[4]
    assert t.nummer == "6082" and t.nummer_raw == "6082a"
    assert t.direktion_kurz == "FD" and t.ausgabenbremse
    assert t.titel.startswith("Objektkredit für einen Beitrag an den Kanton Jura")
    assert "(Ausgabenbremse)" not in t.titel
    assert t.vorstossart == "Antrag"

    # KR-Nr. mit Versionssuffix
    t = by_nr[5]
    assert t.nummer == "114/2023" and t.nummer_raw == "114b/2023" and t.direktion_kurz == "FD"

    # Beratungsart über Zeilenumbruch «(Reduzierte\nDebatte)»
    t = by_nr[6]
    assert t.beratungsart == "Reduzierte Debatte"
    assert t.titel == "Einführung einer spezifischen Verkehrsflächenziffer"
    assert t.vorstossart == "Einzelinitiative"

    # gemeinsame Behandlung über zwei Zeilen
    t = by_nr[13]
    assert t.gemeinsam_mit == ["130/2026", "131/2026", "132/2026", "133/2026"]
    assert t.vorstossart == "Parlamentarische Initiative"

    # Vorstoss mit Behandlungsvermerk und Direktion JI
    t = by_nr[27]
    assert t.nummer == "288/2024"
    assert t.vorstossart == "Motion"
    assert t.behandlung == "Entgegennahme, Diskussion"
    assert t.direktion_kurz == "JI"
    assert t.detail.startswith("Motion Florian Heer (Grüne, Winterthur)")
    assert t.detail.endswith("vom 9. September 2024")

    # Titel, der mit «Bericht» beginnt, bleibt vollständig
    t = by_nr[36]
    assert t.titel == "Bericht über Massnahmen zur Qualitätssicherung in Listenspitälern"
    assert t.vorstossart == "Postulat"

    # Umbrochene Datumsangabe («vom 6. Juli» / «2026») ist keine Vorlagen-Nr.
    t = by_nr[38]
    assert t.nummer == "290/2026" and t.direktion_kurz == "GD"
    t = by_nr[54]
    assert t.nummer == "17/2025" and t.behandlung == "RRB-Nr. 266/12.3.2025"

    # RRB-Verweis mit Stellungnahme
    t = by_nr[40]
    assert t.behandlung == "RRB-Nr. 1038/2.10.2024 (Stellungnahme)" and t.direktion_kurz == "BD"

    # Nachmittag ab Traktandum 39
    assert not by_nr[38].nachmittag and by_nr[39].nachmittag

    # Vermerk «keine materielle Behandlung» mit einfachem Leerzeichen vor der Direktion
    t = by_nr[121]
    assert t.behandlung == "Entgegennahme, keine materielle Behandlung" and t.direktion_kurz == "BD"

    # Antrag der GL ohne Direktion
    t = by_nr[134]
    assert t.nummer == "18/2025" and t.direktion_kurz is None

    # Vorlage am Ende der Liste und Abschnitt «Neu auf der Traktandenliste»
    assert by_nr[140].nummer == "6112" and by_nr[140].direktion_kurz == "FD" and not by_nr[140].neu
    t = by_nr[141]
    assert t.neu and t.nummer == "294/2022" and t.beratungsart == "Kurzdebatte" and t.direktion_kurz == "BI"


def test_direktionen_und_vorstossarten(traktandenliste_text):
    tl = parse_traktandenliste(traktandenliste_text)
    dirs = Counter(t.direktion_kurz for t in tl.traktanden)
    assert dirs["JI"] == 15 and dirs["BD"] == 35
    arten = Counter(t.vorstossart for t in tl.traktanden)
    assert arten["Postulat"] == 44 and arten["Motion"] == 36 and arten["Interpellation"] == 15
    assert arten["Antrag"] == 22 and arten["Parlamentarische Initiative"] == 15 and arten["Einzelinitiative"] == 6
    assert arten[None] == 3  # Mitteilungen und die beiden Wahlen
    # Wahlen, Einzel- und parlamentarische Initiativen (2–3, 6–26) sowie die GL-Anträge 134/137
    # haben in der Quelle keine Direktion
    ohne = [t.nr for t in tl.traktanden if t.direktion_kurz is None and t.nummer]
    assert ohne == [2, 3] + list(range(6, 27)) + [134, 137]


def test_pendent_beim_regierungsrat(traktandenliste_text):
    tl = parse_traktandenliste(traktandenliste_text)
    assert len(tl.pendent_beim_rr) == 11
    assert tl.pendent_beim_rr[0] == {"nummer": "262/2026", "eingereicht": "29.6.2026", "text": "Motion Urs Waser"}
    assert tl.pendent_beim_rr[-1]["nummer"] == "378/2026"
