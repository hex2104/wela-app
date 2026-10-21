"""Command line:
    python -m wela                      start the UI (default)
    python -m wela serve [--port 8765] [--no-browser]
    python -m wela analyze <path> [<path> ...] [--out report.html|.xlsx|.csv|.json] [--tz 330]
    python -m wela demo [folder]        write demo logs
"""
from __future__ import annotations

import argparse
import sys

from . import catalog, demo, engine, parser, report


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wela", description="Windows Event Log Analyzer")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="start the local UI")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    a = sub.add_parser("analyze", help="analyse logs from the command line")
    a.add_argument("paths", nargs="+")
    a.add_argument("--out", help="write report (.html, .xlsx, .csv or .json)")
    a.add_argument("--tz", type=int, default=0, help="display offset in minutes, e.g. 330 for IST")
    d = sub.add_parser("demo", help="write demo logs")
    d.add_argument("folder", nargs="?", default="demo_logs")
    args = ap.parse_args(argv)

    if args.cmd in (None, "serve"):
        from .server import serve
        return serve(getattr(args, "port", 8765), not getattr(args, "no_browser", False))
    if args.cmd == "demo":
        for f in demo.build(args.folder):
            print(f)
        return
    events, sources = parser.load(args.paths)
    for s_ in sources:
        status = s_["error"] or f"{s_['events']} events via {s_['reader']}"
        print(f"  {s_['file']}: {status}")
    if not events:
        sys.exit("No events read.")
    r = engine.analyze(events, catalog.load_config(), sources)
    c = r["counts"]
    print(f"\n  {r['computer']}  {r['coverage']['start']} .. {r['coverage']['end']}")
    print(f"  shutdown {c['shutdown']}  restart {c['restart']}  hard {c['hard']}  undetermined {c['unknown']}  "
          f"sleep {c['sleep']}  hibernate {c['hibernate']}  modern-standby {c['modern_standby']}  "
          f"needs review {c['needs_review']}")
    print(f"  drive caused it: likely {c['drive_likely']}  possibly {c['drive_possible']}  "
          f"no drive evidence {c['drive_no_evidence']}  can't tell {c['drive_unknown']}  "
          f"drive errors after boot/wake {c['drive_effect']}\n")
    for it in r["items"]:
        mark = "!" if it["needs_review"] else " "
        d = it["drive"]
        cause = f"  caused it? {d['cause_label']}" if it["type"] != "sleep" else ""
        print(f" {mark} {it['id']:>4}  {it['time'][:19]}  {it['type']:<9} {it['subtype'][:44]:<44} "
              f"{int(it['confidence'] * 100):>3}%  drive:{d['state']:<8}{cause}")
    if args.out:
        fmt = args.out.rsplit(".", 1)[-1].lower()
        fn = {"html": report.to_html, "xlsx": report.to_xlsx, "csv": report.to_csv}.get(fmt)
        data = fn(r, args.tz) if fn else report.to_json(r)
        with open(args.out, "wb") as fh:
            fh.write(data)
        print(f"\n  report written to {args.out}")


if __name__ == "__main__":
    main()
