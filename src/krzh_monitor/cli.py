"""Kommandozeile.

    krzh sync   [--db krzh.sqlite] [--stichtag 2026-10-22] [--rueckblick 7] [--vorschau 14]
    krzh report [--db krzh.sqlite] [--stichtag 2026-10-22] [--out report.md]
    krzh stats  [--db krzh.sqlite]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from .cdws import CdwsClient
from .report import render_report
from .store import Store
from .sync import fenster, run_sync


def _date(s: str) -> date:
    return date.fromisoformat(s)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="krzh", description="Geschäfte des Zürcher Kantonsrats beobachten")
    p.add_argument("--db", default="krzh.sqlite", help="SQLite-Datei (Standard: krzh.sqlite)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sync", help="Ablaufschritte, Sitzungen und Geschäfte laden")
    s.add_argument("--stichtag", type=_date, default=None, help="Bezugsdatum (Standard: heute)")
    s.add_argument("--rueckblick", type=int, default=7, help="Tage rückwärts für Ablaufschritte")
    s.add_argument("--vorschau", type=int, default=14, help="Tage vorwärts für Sitzungen")

    r = sub.add_parser("report", help="Markdown-Rohliste schreiben")
    r.add_argument("--stichtag", type=_date, default=None)
    r.add_argument("--rueckblick", type=int, default=7)
    r.add_argument("--vorschau", type=int, default=14)
    r.add_argument("--out", type=Path, default=None, help="Zieldatei (Standard: stdout)")

    b = sub.add_parser("briefing", help="Montagsbriefing mit den für ein Amt relevanten Geschäften")
    b.add_argument("--profil", type=Path, default=Path("profiles/asd.toml"), help="Relevanzprofil (TOML)")
    b.add_argument("--stichtag", type=_date, default=None, help="Sitzungstag (Standard: nächster Montag)")
    b.add_argument("--out", type=Path, default=None, help="Markdown-Zieldatei (Standard: stdout)")
    b.add_argument("--html", type=Path, default=None, help="zusätzlich HTML-Datei für den Mailversand")
    b.add_argument("--rohliste-url", default=None, help="Link auf die vollständige Rohliste")

    rl = sub.add_parser("relevanz", help="Alle geladenen Geschäfte bewerten (zum Kalibrieren des Profils)")
    rl.add_argument("--profil", type=Path, default=Path("profiles/asd.toml"))
    rl.add_argument("--stufe", choices=["relevant", "pruefen", "alle"], default="pruefen", help="Mindeststufe (Standard: prüfen)")

    sub.add_parser("stats", help="Zeilen je Tabelle")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    with Store(args.db) as store:
        if args.cmd == "sync":
            res = run_sync(CdwsClient(), store, args.stichtag, args.rueckblick, args.vorschau)
            print(
                f"Ablaufschritte: {res.ablaufschritte_total} ({res.neue_ablaufschritte} neu) · "
                f"Sitzungen: {res.sitzungen} · Traktanden: {res.traktanden_pdf} aus PDF, "
                f"{res.traktanden_struktur} strukturiert · Geschäfte nachgeladen: {res.geschaefte_nachgeladen}"
            )
            if res.nicht_gefunden:
                print("Nicht gefunden:", ", ".join(res.nicht_gefunden))
            for w in res.warnungen:
                print("Warnung:", w)
        elif args.cmd == "report":
            stichtag = args.stichtag or date.today()
            a_von, a_bis, s_von, s_bis = fenster(stichtag, args.rueckblick, args.vorschau)
            md = render_report(store, stichtag, a_von, a_bis, s_von, s_bis)
            if args.out:
                args.out.write_text(md, encoding="utf-8")
                print(f"Report geschrieben: {args.out}")
            else:
                sys.stdout.write(md)
        elif args.cmd == "briefing":
            from .briefing import baue_briefing, naechster_montag, render_html, render_markdown
            from .relevanz import lade_profil

            profil = lade_profil(args.profil)
            stichtag = args.stichtag or naechster_montag()
            b = baue_briefing(store, profil, stichtag, rohliste_url=args.rohliste_url)
            md = render_markdown(b)
            if args.out:
                args.out.write_text(md, encoding="utf-8")
                print(f"Briefing geschrieben: {args.out} ({b.anzahl_relevant} relevant, {b.anzahl_pruefen} zur Prüfung)")
            else:
                sys.stdout.write(md)
            if args.html:
                args.html.write_text(render_html(b), encoding="utf-8")
                print(f"HTML geschrieben: {args.html}")
        elif args.cmd == "relevanz":
            from .relevanz import bewerte_row, lade_profil

            profil = lade_profil(args.profil)
            rows = store.conn.execute("SELECT * FROM geschaefte").fetchall()
            bewertet = sorted(((bewerte_row(profil, r), r) for r in rows), key=lambda x: -x[0].score)
            stufen = {"relevant": ("relevant",), "pruefen": ("relevant", "pruefen"), "alle": ("relevant", "pruefen", "keine")}[args.stufe]
            for bw, r in bewertet:
                if bw.stufe in stufen:
                    print(f"{bw.score:5.1f} {bw.stufe:8s} {r['nummer'] or '':9s} {r['direktion_kurz'] or '':4s} {r['titel'][:70]:70s} | {bw.begruendung}")
        elif args.cmd == "stats":
            for k, v in store.counts().items():
                print(f"{k:15s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
