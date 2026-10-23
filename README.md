# krzh-monitor

Beobachtet die Geschäfte des Zürcher Kantonsrats und bereitet daraus eine Wochenübersicht
auf: Was ist neu eingereicht, was hat der Regierungsrat beantwortet, was steht am Montag auf
der Traktandenliste. Ein Relevanzprofil je Amt (zuerst das Amt für Statistik und Daten,
später die Ämter der JI) filtert daraus das Montagsbriefing.

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
krzh sync                                  # Ablaufschritte der letzten 7 Tage, Sitzungen der nächsten 14 Tage
krzh report --out report.md                # Markdown-Rohliste, alles ohne Bewertung
krzh briefing --profil profiles/asd.toml --out briefing.md --html briefing.html
krzh relevanz --profil profiles/asd.toml   # alle geladenen Geschäfte mit Score, zum Kalibrieren
krzh stats
pytest                                     # Tests laufen offline gegen Fixtures in tests/fixtures
```

## Relevanzprofil und Briefing

`profiles/asd.toml` beschreibt die Themen eines Amts als gewichtete reguläre Ausdrücke in
vier Gruppen (Statistik, Daten und Data Governance, Politische Rechte, Digitalisierung und
Verwaltung). Treffer im Titel zählen dreifach, in der Zusammenfassung doppelt, im Volltext
einfach und gedeckelt. Drei Stufen:

* **relevant**: Score über der Schwelle und ein Titel- oder Zusammenfassungstreffer mit
  Gewicht ≥ 2 (z. B. «Datenlage», «Unterschriftensammlung», «Open Source»).
* **prüfen**: Score über der Prüfschwelle, aber nur schwache oder reine Volltexttreffer.
* **keine**: alles andere; Ausschlussmuster fangen parlamentsinterne Wahlen, Budget und
  Geschäftsbericht ab, die jedes Amt erwähnen.

Das Briefing (`krzh briefing`) zeigt für den Sitzungstag drei Blöcke: traktandierte
Geschäfte der Ratssitzung, Ablaufschritte der vergangenen Woche, Kommissionssitzungen.
Relevante Geschäfte erscheinen mit Begründung («Warum: Datenlage (Titel), …»), Geschäfte zur
Prüfung als Einzeiler, der Rest als Zähler. Ausgabe als Markdown und als HTML für den
Mailversand. Ein weiteres Amt bekommt eine eigene TOML-Datei; der Code ändert sich nicht.

Standard-Datenbank ist `krzh.sqlite` im Arbeitsverzeichnis (`--db` ändert das). `sync`
ist idempotent: bereits bekannte Ablaufschritte werden erkannt, Traktanden einer Sitzung
ersetzt statt verdoppelt, fehlende Geschäfte nachgeladen.

Der GitHub-Workflow (`.github/workflows/weekly.yml`) läuft montags um 06:00/07:00 Uhr,
schreibt `reports/latest.md` (Rohliste) und `briefings/briefing-latest.md` und `.html`
und committet Datenbank, Rohliste und Briefing. Manuell lässt er sich mit einem
beliebigen Stichtag starten. Den Mailversand übernimmt derzeit eine geplante Aufgabe in
Claude (montags 07:45 Uhr, Gmail); ein SMTP-Schritt im Workflow wäre die Alternative ohne
diese Abhängigkeit.

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
  relevanz.py    Profil laden, Geschäfte bewerten
  briefing.py    Montagsbriefing (Markdown, HTML)
  cli.py         Kommandozeile
profiles/        Relevanzprofile je Amt (TOML)
tests/fixtures/  Echte Antworten der Schnittstelle vom 22.10.2026, gekürzt
```

## Nächste Iterationen

1. Profil kalibrieren: Rückmeldungen aus den ersten Briefings einarbeiten (Begriffe,
   Gewichte, Ausschlüsse); optional semantisches Modell hinter derselben Schnittstelle.
2. Mailversand direkt aus dem Workflow (SMTP), unabhängig von Claude.
3. Weitere Ämter der JI als eigene Profile.
4. Abonnement einzelner Geschäfte: Tabelle `abos`, Benachrichtigung bei jedem neuen
   Ablaufschritt.
