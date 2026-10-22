# krzh-monitor

Beobachtet die Geschäfte des Zürcher Kantonsrats und bereitet daraus eine Wochenübersicht
auf: Was ist neu eingereicht, was hat der Regierungsrat beantwortet, was steht am Montag auf
der Traktandenliste. Iteration 2: Datenzugriff, Ablage und Rohliste. Die Relevanzbewertung
für ein Amt (zuerst das Amt für Statistik und Daten, später die Ämter der JI) folgt in
Iteration 3.

## Datenquelle

Die Geschäftsdatenbank des Kantonsrats ist über die CDWS-Schnittstelle von CMI Axioma
abfragbar (`parlzhcdws.cmicloud.ch`). Sie wird auf opendata.swiss als Datensatz
«Organisation und Geschäfte des Zürcher Kantonsrats» geführt. Genutzt werden drei Indizes:

| Index | Instanz | Inhalt | Verwendung |
|---|---|---|---|
| `ABLAUFSCHRITTE` | parlzh5 | Ereignisse je Geschäft: Eingereicht, Antwort/Antrag/Stellungnahme Regierungsrat, Antrag Kommission, Entgegennahme, Überweisung, Zustimmung, Ablehnung, Rückweisung, Medienmitteilung | Was ist in den letzten Tagen passiert |
| `SITZUNGENDETAIL` | parlzh3 | Sitzungen von Rat und Kommissionen mit Traktanden und Sitzungsdokumenten (Traktandenliste, Vorschau als PDF-Volltext) | Was steht am Montag an |
| `GESCHAEFT` | parlzh5 | Stammdaten je Geschäft: Titel, Art, Direktion, Kommission, Unterzeichnende, Status, Dokumente mit Volltext | Anreicherung, Volltext für die Relevanzprüfung |

Abfragen folgen einer CQL-ähnlichen Syntax, zum Beispiel
`sitzungsdatum_start >= "2026-10-19 00:00:00" sortBy sitzungsdatum_start/sort.descending`.
Die Antwort ist XML; unbekannte Felder quittiert die Schnittstelle mit einem sprechenden
HTTP 406 («unknown Field 'x'»). Deep Links auf die Website:
`https://www.kantonsrat.zh.ch/geschaefte/geschaeft?id=<GUID>`.

Zwei Eigenheiten, die der Code abfängt:

* Für künftige Ratssitzungen ist das Element `Traktanden` leer; die Traktandenliste liegt
  aber als PDF-Volltext in der Antwort. `traktanden.py` parst daraus Nummer, Titel,
  Vorstossart, Behandlungsvermerk und zuständige Direktion. Bei Doppelsitzungen (ein PDF
  für Vormittag und Nachmittag) werden die Traktanden anhand des Vermerks «ab Traktandum N»
  auf die beiden Sitzungen verteilt.
* Buchstabensuffixe an Geschäftsnummern (`114b/2023`, `6082a`) bezeichnen Dokumentversionen.
  Schlüssel in der Datenbank ist die Nummer ohne Suffix (`nummern.py`).

## Installation und Nutzung

```bash
pip install -e ".[dev]"
krzh sync                      # Ablaufschritte der letzten 7 Tage, Sitzungen der nächsten 14 Tage
krzh report --out report.md    # Markdown-Rohliste
krzh stats
pytest                         # Tests laufen offline gegen Fixtures in tests/fixtures
```

Standard-Datenbank ist `krzh.sqlite` im Arbeitsverzeichnis (`--db` ändert das). `sync`
ist idempotent: bereits bekannte Ablaufschritte werden erkannt, Traktanden einer Sitzung
ersetzt statt verdoppelt, fehlende Geschäfte nachgeladen.

Der GitHub-Workflow (`.github/workflows/weekly.yml`) läuft freitags, schreibt
`reports/<Datum>.md` sowie `reports/latest.md` und committet Datenbank und Report.

## Aufbau

```
src/krzh_monitor/
  cdws.py        HTTP-Client, Paginierung, fertige Abfragen
  parse.py       XML → Dataclasses (drei Indizes)
  traktanden.py  Parser für die Traktandenliste (PDF-Volltext)
  nummern.py     KR-Nr. / Vorlagen-Nr. normalisieren
  models.py      Dataclasses
  store.py       SQLite (geschaefte, ablaufschritte, sitzungen, traktanden)
  sync.py        Ladevorgang für ein Zeitfenster
  report.py      Markdown-Rohliste
  cli.py         Kommandozeile
tests/fixtures/  Echte Antworten der Schnittstelle vom 22.10.2026, gekürzt
```

## Nächste Iterationen

1. Relevanzmodell: Amtsprofile als Text (zuerst VASD-basiert), Scoring gegen Titel und
   Volltext, Stichprobe von Hand beurteilen und als Messlatte ablegen.
2. Briefing: nur relevante Geschäfte, gruppiert nach Auslöser (traktandiert, neu,
   Antwort des Regierungsrats), Versand per Mail oder als GitHub-Commit.
3. Abonnement einzelner Geschäfte: Tabelle `abos`, Benachrichtigung bei jedem neuen
   Ablaufschritt.
