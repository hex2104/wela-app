"""Local web server for the WELA UI (standard library only).

Binds to 127.0.0.1 only - nothing is reachable from the network and no data
leaves the machine.
"""
from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__, catalog, demo, engine, parser, report, store

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
_lock = threading.Lock()


def run_analysis(paths, name=None, settings=None):
    cfg = catalog.load_config()
    if settings:
        for k, v in settings.items():
            if k in cfg["settings"] and isinstance(v, (int, float)):
                cfg["settings"][k] = v
    t0 = time.time()
    events, sources = parser.load(paths)
    if not events:
        errs = "; ".join(f"{s['file']}: {s['error']}" for s in sources if s.get("error"))
        raise ValueError("No events could be read." + (f" {errs}" if errs else
                         " Check the path contains .evtx or .xml files."))
    result = engine.analyze(events, cfg, sources)
    result["case_name"] = name or result.get("computer") or "case"
    result["input_paths"] = list(paths)
    result["analysis_seconds"] = round(time.time() - t0, 2)
    cid = store.new_id(result["case_name"])
    result["id"] = cid
    with _lock:
        store.save(cid, result, events)
    return result


def _pick(kind: str):
    """Native file/folder picker (tkinter) in a child process; returns list of paths."""
    code = (
        "import tkinter as tk, json\n"
        "from tkinter import filedialog\n"
        "r=tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        f"kind={kind!r}\n"
        "if kind=='folder':\n"
        "    p=filedialog.askdirectory(title='Select folder with event logs'); out=[p] if p else []\n"
        "else:\n"
        "    out=list(filedialog.askopenfilenames(title='Select event log files',"
        " filetypes=[('Event logs','*.evtx *.xml'),('All files','*.*')]))\n"
        "print(json.dumps(out))\n")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError("File picker not available (tkinter missing) - paste the path instead")
    return json.loads(proc.stdout.strip() or "[]")


class Handler(BaseHTTPRequestHandler):
    server_version = f"WELA/{__version__}"

    def log_message(self, fmt, *args):  # quieter console
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("  " + (fmt % args) + "\n")

    # ------------------------------------------------------------ helpers
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _err(self, msg, code=400):
        self._json({"error": msg}, code)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    # ------------------------------------------------------------ routes
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = [p for p in u.path.split("/") if p]
        try:
            if not parts or parts[0] != "api":
                return self._static(u.path)
            if parts[1:] == ["health"]:
                return self._json({"ok": True, "version": __version__})
            if parts[1:] == ["config"]:
                return self._json(catalog.load_config())
            if parts[1:] == ["cases"]:
                return self._json(store.list_cases())
            if len(parts) == 3 and parts[1] == "cases":
                r = store.load_result(parts[2])
                return self._json(r) if r else self._err("case not found", 404)
            if len(parts) == 4 and parts[1] == "cases" and parts[3] == "events":
                return self._events(parts[2], q)
            if len(parts) == 4 and parts[1] == "cases" and parts[3].startswith("export."):
                return self._export(parts[2], parts[3].split(".", 1)[1], int(q.get("tz", 0) or 0))
            return self._err("not found", 404)
        except Exception as exc:
            traceback.print_exc()
            return self._err(str(exc), 500)

    def do_POST(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        try:
            body = self._body()
            if parts == ["api", "analyze"]:
                paths = [p for p in body.get("paths", []) if p and p.strip()]
                if not paths:
                    return self._err("Give at least one file or folder path")
                return self._json(run_analysis(paths, body.get("name"), body.get("settings")))
            if parts == ["api", "demo"]:
                folder = os.path.join(store.ROOT, "_demo_logs")
                demo.build(folder)
                return self._json(run_analysis([folder], "Demo case", body.get("settings")))
            if parts == ["api", "pick"]:
                return self._json({"paths": _pick(body.get("kind", "folder"))})
            return self._err("not found", 404)
        except (ValueError, FileNotFoundError) as exc:
            return self._err(str(exc), 400)
        except Exception as exc:
            traceback.print_exc()
            return self._err(str(exc), 500)

    def do_DELETE(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if len(parts) == 3 and parts[:2] == ["api", "cases"]:
            store.delete(parts[2])
            return self._json({"ok": True})
        return self._err("not found", 404)

    # ------------------------------------------------------------ handlers
    def _static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB, rel))
        if not full.startswith(os.path.normpath(WEB)) or not os.path.isfile(full):
            return self._err("not found", 404)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as fh:
            self._send(200, fh.read(), ctype)

    def _events(self, cid, q):
        evs = store.load_events(cid)
        if "around" in q:
            i = int(q["around"])
            n = int(q.get("n", 25))
            sel = evs[max(0, i - n): i + n + 1]
        else:
            f, t = q.get("from"), q.get("to")
            text = (q.get("q") or "").lower()
            sel = []
            for e in evs:
                if f and e["time"] < f:
                    continue
                if t and e["time"] > t:
                    break
                if text and text not in f"{e['provider']} {e['eid']} {e['channel']} {json.dumps(e.get('data', {}))}".lower():
                    continue
                sel.append(e)
                if len(sel) >= int(q.get("limit", 500)):
                    break
        return self._json(sel)

    def _export(self, cid, fmt, tz):
        r = store.load_result(cid)
        if not r:
            return self._err("case not found", 404)
        name = f"WELA_{cid}"
        if fmt == "html":
            body, ct = report.to_html(r, tz), "text/html; charset=utf-8"
        elif fmt == "xlsx":
            body, ct = report.to_xlsx(r, tz), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif fmt == "csv":
            body, ct = report.to_csv(r, tz), "text/csv; charset=utf-8"
        elif fmt == "json":
            body, ct = report.to_json(r), "application/json; charset=utf-8"
        else:
            return self._err("unknown format")
        self._send(200, body, ct, {"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})


def serve(port: int = 8765, open_browser: bool = True):
    os.makedirs(store.ROOT, exist_ok=True)
    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit("No free port found")
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  WELA {__version__} running at {url}\n  (local only - press Ctrl+C to stop)\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        httpd.server_close()
