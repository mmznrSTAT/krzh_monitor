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
        elif args.cmd == "stats":
            for k, v in store.counts().items():
                print(f"{k:15s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
