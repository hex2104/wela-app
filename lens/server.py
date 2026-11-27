"""Local web server for the LENS UI (standard library only).

Binds to 127.0.0.1 only - nothing is reachable from the network and no data
leaves the machine.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__, catalog, demo, engine, parser, reference, report, store

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
_lock = threading.Lock()


class Cancelled(BaseException):
    """The analysis was stopped from the UI. A BaseException, like KeyboardInterrupt, so that no reader's
    "this file failed, try the next" handler takes it for a broken log."""


class Job:
    """What one analysis is doing, for the UI's progress view: the step and its counts, kept for GET /api/progress.
    Called by the parser, the engine and the store as they go; after cancel() its next call stops the analysis."""

    def __init__(self):
        self.state = {"step": "start"}
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def __call__(self, step, **info):
        if self.cancelled and step != "save":   # a case being written is finished rather than left half-saved
            raise Cancelled()
        self.state = {"step": step, **info}


_jobs: dict = {}                 # job id (made by the page) -> Job, while its analysis runs
_JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def run_analysis(paths, name=None, settings=None, progress=None):
    """progress: a Job (or any callable taking a step name and counts) told what the analysis is doing."""
    step = progress or (lambda *a, **k: None)
    cfg = catalog.load_config()
    if settings:
        for k, v in settings.items():
            if k in cfg["settings"] and isinstance(v, (int, float)):
                cfg["settings"][k] = v
    t0 = time.time()
    events, sources, skipped = parser.load(paths, step)
    if not events:
        errs = "; ".join(f"{s['file']}: {s['error']}" for s in sources if s.get("error"))
        if not sources and skipped:
            raise ValueError(f"No System, Application or Storport log in the folder ({len(skipped)} other logs skipped).")
        raise ValueError("No events could be read." + (f" {errs}" if errs else
                         " Check the path contains .evtx or .xml files."))
    result = engine.analyze(events, cfg, sources, step)
    result["case_name"] = name or result.get("computer") or "case"
    result["input_paths"] = list(paths)
    result["skipped_files"] = len(skipped)
    result["analysis_seconds"] = round(time.time() - t0, 2)
    cid = store.new_id(result["case_name"])
    result["id"] = cid
    found = {"events": len(events), "power_cycles": result["counts"]["power_cycles"], "sleeps": len(result["items"])
             - result["counts"]["power_cycles"]}
    step("review", **found)   # the last chance to stop: nothing is saved yet
    step("save", frac=0.0, **found)
    with _lock:
        store.save(cid, result, events, lambda f: step("save", frac=f, **found))
    return result


def _start_job(body) -> tuple:
    """The Job for the id the page sent with its request, or (None, None) when it sent none."""
    jid = body.get("job")
    if not isinstance(jid, str) or not _JOB_ID.fullmatch(jid):
        return None, None
    job = _jobs[jid] = Job()
    return jid, job


def _warm(case_id: str):
    try:
        store.warm(case_id)
    except Exception:   # the request that needs it reports the error
        pass


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
    server_version = f"LENS/{__version__}"

    def log_message(self, fmt, *args):  # quieter console: API calls only, not the progress view's polls
        line = str(args[0]) if args else ""
        if "/api/" in line and "/api/progress/" not in line:
            sys.stderr.write("  " + (fmt % args) + "\n")

    # ------------------------------------------------------------ helpers
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", headers=None):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except ConnectionError:   # the page was closed or moved on before the answer arrived: no one to tell
            pass

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
            if len(parts) == 3 and parts[1] == "progress":   # what a running analysis is doing
                job = _jobs.get(parts[2])
                return self._json(job.state) if job else self._err("no analysis running with this id", 404)
            if parts[1:] == ["config"]:
                return self._json(catalog.load_config())
            if parts[1:] == ["reference"]:
                return self._reference()
            if parts[1:] == ["cases"]:
                return self._json(store.list_cases())
            if len(parts) == 3 and parts[1] == "cases":
                body = store.result_bytes(parts[2])
                if body is None:
                    return self._err("case not found", 404)
                # open its events in the background: the timeline line and the References tab need them next
                threading.Thread(target=_warm, args=(parts[2],), daemon=True).start()
                return self._send(200, body)
            if len(parts) == 4 and parts[1] == "cases" and parts[3] == "events":
                return self._events(parts[2], q)
            if len(parts) == 4 and parts[1] == "cases" and parts[3] == "index":
                return self._send(200, store.index_bytes(parts[2]))
            if len(parts) == 4 and parts[1] == "cases" and parts[3] == "ids":
                return self._ids(parts[2])
            if len(parts) == 4 and parts[1] == "cases" and parts[3] == "rows":
                if "ids" in q:   # a range: the events it lists, wherever they are
                    return self._json(store.event_rows_at(parts[2], [int(i) for i in q["ids"].split(",") if i][:4096]))
                i0 = int(q.get("from", 0))
                return self._json(store.event_rows(parts[2], i0, min(int(q.get("to", i0 + 256)), i0 + 4096)))
            if len(parts) == 4 and parts[1] == "cases" and parts[3].startswith("export."):
                return self._export(parts[2], parts[3].split(".", 1)[1], int(q.get("tz", 0) or 0), q.get("names") == "1")
            return self._err("not found", 404)
        except Exception as exc:
            traceback.print_exc()
            return self._err(str(exc), 500)

    def do_POST(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        jid = None
        try:
            body = self._body()
            if parts in (["api", "analyze"], ["api", "demo"]):
                # the page sends an id of its own, polls /api/progress/<id> meanwhile and can stop it with .../cancel
                jid, job = _start_job(body)
                if parts[1] == "demo":
                    folder = os.path.join(store.ROOT, "_demo_logs")   # its files one by one: Partition is read too
                    return self._json(run_analysis(demo.build(folder), "Demo case", body.get("settings"), job))
                paths = [p for p in body.get("paths", []) if p and p.strip()]
                if not paths:
                    return self._err("Give at least one file or folder path")
                return self._json(run_analysis(paths, body.get("name"), body.get("settings"), job))
            if len(parts) == 4 and parts[:2] == ["api", "progress"] and parts[3] == "cancel":
                job = _jobs.get(parts[2])
                if job:   # it stops at its next check: in moments, or once Windows has exported the .evtx being read
                    job.cancel()
                return self._json({"ok": bool(job)})
            if parts == ["api", "pick"]:
                return self._json({"paths": _pick(body.get("kind", "folder"))})
            return self._err("not found", 404)
        except Cancelled:
            return self._json({"error": "Analysis stopped", "cancelled": True}, 409)
        except (ValueError, FileNotFoundError) as exc:
            return self._err(str(exc), 400)
        except Exception as exc:
            traceback.print_exc()
            return self._err(str(exc), 500)
        finally:
            if jid:
                _jobs.pop(jid, None)

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
        if "around" in q:
            return self._json(store.events_around(cid, int(q["around"]), int(q.get("n", 25))))
        # tag=software|storage: only events with that tag, without their data; last=1: the last `limit` of them
        tag = q.get("tag") if q.get("tag") in ("software", "storage") else None
        return self._json(store.find_events(cid, q.get("from"), q.get("to"), tag, q.get("q") or "",
                                            int(q.get("limit", 500)), bool(q.get("last"))))

    def _reference(self):
        """What each event ID means, with what LENS uses it for."""
        cfg = catalog.load_config()
        known = reference.uses(cfg)
        rows = []
        for k, provs, eid, title, text in reference.table(cfg):
            first = int(str(eid).split("-")[0])
            rows.append([k, provs, eid, title, text, reference.use_of(provs.split("|")[0], first, cfg, known)])
        self._json(rows)

    def _ids(self, cid):
        """The event IDs in a case, each with what LENS uses it for."""
        cfg = catalog.load_config()
        known = reference.uses(cfg)
        self._json([{**s, "u": reference.use_of(s["p"], s["e"], cfg, known)} for s in store.event_ids(cid)])

    def _export(self, cid, fmt, tz, names=False):
        r = store.load_result(cid)
        if not r:
            return self._err("case not found", 404)
        if not names:   # a report leaves the PC: people's account names stay behind unless asked for
            r = report.redact(r)
        name = f"LENS_{cid}"
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
    print(f"\n  LENS {__version__} running at {url}\n  (local only - press Ctrl+C to stop)\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        httpd.server_close()
