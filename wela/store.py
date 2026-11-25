"""Case storage on local disk: cases/<id>/result.json + events.jsonl.gz"""
from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import threading
from datetime import date, datetime
from typing import List, Optional

from . import catalog
from .engine import _fields, channel_kind
from .models import Event, parse_time

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cases")


def _dir(case_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", case_id or ""):
        raise ValueError("bad case id")
    return os.path.join(ROOT, case_id)


def new_id(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name or "case").strip("-")[:40] or "case"
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + slug


def save(case_id: str, result: dict, events: List[Event]) -> None:
    d = _dir(case_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False)
    rows = [e.to_dict() for e in events]
    with gzip.open(os.path.join(d, "events.jsonl.gz"), "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with _lock:   # the case opens next: keep its events instead of reading them back
        _cache.clear()
        _index.clear()
        _cache[case_id] = rows


def load_result(case_id: str) -> Optional[dict]:
    p = os.path.join(_dir(case_id), "result.json")
    if not os.path.isfile(p):
        return None
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


# the open case's events, one case at a time; the lock makes a second request wait for the first load
_lock = threading.RLock()
_cache = {}
_index = {}
_labels = {}


def load_events(case_id: str) -> List[dict]:
    with _lock:
        if case_id in _cache:
            return _cache[case_id]
        p = os.path.join(_dir(case_id), "events.jsonl.gz")
        out = []
        if os.path.isfile(p):
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                out = [json.loads(line) for line in fh if line.strip()]
        _cache.clear()
        _index.clear()
        _cache[case_id] = out
        return out


_KIND = {"system": "s", "application": "a", "storport": "p"}


def _ms(t: str, days: dict) -> int:
    """'2026-09-03T11:42:12.123Z' -> milliseconds since 1970 (the format every saved event uses)."""
    if len(t) != 24:
        return round(parse_time(t).timestamp() * 1000)
    d = days.get(t[:10])
    if d is None:
        d = days[t[:10]] = date(int(t[:4]), int(t[5:7]), int(t[8:10])).toordinal() - 719163
    return (((d * 24 + int(t[11:13])) * 60 + int(t[14:16])) * 60 + int(t[17:19])) * 1000 + int(t[20:23])


def event_index(case_id: str) -> dict:
    """Every event's time and log, in time order, for the timeline cursor: t0 (ms) plus the step to each next
    event (ms), and one letter per event - s System, a Application, p Storport, o any other log."""
    with _lock:
        if case_id not in _index:
            evs, days, kinds = load_events(case_id), {}, {}
            ms = [_ms(e["time"], days) for e in evs]
            for e in evs:
                if e["channel"] not in kinds:
                    kinds[e["channel"]] = _KIND.get(channel_kind(e["channel"]), "o")
            t0 = ms[0] if ms else 0
            _index[case_id] = {"t0": t0, "d": [b - a for a, b in zip([t0] + ms, ms)],
                               "k": "".join(kinds[e["channel"]] for e in evs)}
        return _index[case_id]


def event_rows(case_id: str, i0: int, i1: int) -> List[dict]:
    """Events i0 .. i1-1 (an event's index is its place in time order), short: what each one is and says."""
    if not _labels:   # "Unclean shutdown reported (Kernel-Power 41)": the row shows the ID and provider already
        _labels.update({k: re.sub(r"\s*\([^()]*\)$", "", v) for k, v in catalog.load_config()["signal_labels"].items()})
    out = []
    for e in load_events(case_id)[max(0, i0):max(0, i1)]:
        sw, st = e.get("software"), e.get("storage")
        tag = sw or st or {}
        text = " · ".join(x for x in (tag.get("subject"), tag.get("detail")) if x) if sw else ""
        out.append({"idx": e["idx"], "time": e["time"], "eid": e["eid"], "level": e.get("level", 4),
                    "provider": e["provider"], "channel": e["channel"],
                    "label": _labels.get(e.get("signal")) or tag.get("label") or "",
                    "text": text or _fields(e.get("data") or {}, 6 if st else 4), "state": tag.get("state") or ""})
    return out


def list_cases() -> List[dict]:
    if not os.path.isdir(ROOT):
        return []
    out = []
    for cid in sorted(os.listdir(ROOT), reverse=True):
        p = os.path.join(ROOT, cid, "result.json")
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                r = json.load(fh)
        except Exception:
            continue
        out.append({"id": cid, "name": r.get("case_name") or cid, "computer": r.get("computer"),
                    "generated": r.get("generated"), "counts": r.get("counts"), "coverage": r.get("coverage")})
    return out


def delete(case_id: str) -> None:
    d = _dir(case_id)
    with _lock:
        _cache.pop(case_id, None)
        _index.pop(case_id, None)
    if os.path.isdir(d):
        shutil.rmtree(d)
