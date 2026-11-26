"""Case storage on local disk: cases/<id>/result.json, events.jsonl.gz, index.json and events.idx.json.

events.jsonl.gz holds the events in time order, one per line, compressed as blocks of BLOCK lines - each block a gzip
member, so the file is still one ordinary gzip file to any reader. events.idx.json says where each block starts and
lists the event IDs in the case; index.json is every event's time and log for the timeline. An open case keeps only
the compressed file, those block starts and times, and the last blocks it read: a request decodes just the blocks
it needs, so memory stays a small fraction of the events' size however big the case.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import threading
import zlib
from array import array
from bisect import bisect_left, bisect_right
from collections import Counter, OrderedDict
from datetime import date, datetime
from typing import Iterable, List, Optional

from . import catalog, reference
from .engine import _fields, channel_kind
from .models import Event, no_gc, parse_time

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cases")
BLOCK = 256        # events per compressed block
KEEP = 24          # decoded blocks kept per open case (6,144 events)
FORMAT = 2         # events.idx.json layout


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
    with no_gc():
        case = _write(d, (e.to_dict() for e in events))   # one event at a time: never a second copy of them all
    _commit(d)
    with _lock:   # the case opens next: keep it instead of reading it back
        _cache.clear()
        _cache[case_id] = case


def result_bytes(case_id: str) -> Optional[bytes]:
    """The saved result as stored - already JSON, so the UI gets it without decoding and re-encoding it."""
    p = os.path.join(_dir(case_id), "result.json")
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as fh:
        return fh.read()


def load_result(case_id: str) -> Optional[dict]:
    p = os.path.join(_dir(case_id), "result.json")
    if not os.path.isfile(p):
        return None
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------ the open case
# one case at a time; the lock makes a second request wait for the first one's read
_lock = threading.RLock()
_cache = {}
_labels = {}
_titles = {}
_KIND = {"system": "s", "application": "a", "storport": "p"}
_ENC = json.JSONEncoder(ensure_ascii=False, separators=(",", ":")).encode


class _Case:
    """An open case: its compressed events, where each block starts, every event's time (ms) and its event IDs."""
    __slots__ = ("blob", "off", "ms", "ids", "blocks")

    def __init__(self, blob: bytes, off: List[int], ms: array, ids: list):
        self.blob, self.off, self.ms, self.ids = blob, off, ms, ids
        self.blocks = OrderedDict()   # block number -> its events, the last KEEP read

    def __len__(self):
        return len(self.ms)

    def block(self, b: int) -> List[dict]:
        evs = self.blocks.get(b)
        if evs is None:
            raw = zlib.decompress(self.blob[self.off[b]:self.off[b + 1]], 31)
            evs = json.loads(b"[" + raw.rstrip(b"\n").replace(b"\n", b",") + b"]")   # one line per event
            self.blocks[b] = evs
            if len(self.blocks) > KEEP:
                self.blocks.popitem(last=False)
        else:
            self.blocks.move_to_end(b)
        return evs

    def slice(self, i0: int, i1: int) -> List[dict]:
        """Events i0 .. i1-1."""
        i0, i1 = max(0, i0), min(len(self), i1)
        out = []
        for b in range(i0 // BLOCK, (i1 - 1) // BLOCK + 1) if i1 > i0 else ():
            out += self.block(b)[max(0, i0 - b * BLOCK):i1 - b * BLOCK]
        return out


def _case(case_id: str) -> _Case:
    with _lock:
        c = _cache.get(case_id)
        if c is None:
            c = _read(_dir(case_id))
            _cache.clear()
            _cache[case_id] = c
        return c


def _paths(d: str):
    return (os.path.join(d, "events.jsonl.gz"), os.path.join(d, "index.json"), os.path.join(d, "events.idx.json"))


def _read(d: str) -> _Case:
    ev, ix, meta = _paths(d)
    if not os.path.isfile(ev):
        return _Case(b"", [0], array("q"), [])
    try:
        with open(meta, "r", encoding="utf-8") as fh:
            m = json.load(fh)
        if m.get("v") != FORMAT or m.get("size") != os.path.getsize(ev):
            raise ValueError("index out of date")
        with open(ev, "rb") as fh:
            blob = fh.read()
        with open(ix, "r", encoding="utf-8") as fh:
            t = json.load(fh)
        return _Case(blob, m["off"], _times(t), m["ids"])
    except (OSError, ValueError, KeyError):
        pass
    # saved by an earlier version as one gzip stream: write it as blocks with its index, once
    with gzip.open(ev, "rt", encoding="utf-8") as fh, no_gc():
        case = _write(d, (json.loads(line) for line in fh if line.strip()))
    _commit(d)
    return case


def _times(ix: dict) -> array:
    ms, t = array("q"), ix["t0"]
    for step in ix["d"]:
        t += step
        ms.append(t)
    return ms


def _ms(t: str, days: dict) -> int:
    """'2026-09-03T11:42:12.123Z' -> milliseconds since 1970 (the format every saved event uses)."""
    if len(t) != 24:
        return round(parse_time(t).timestamp() * 1000)
    d = days.get(t[:10])
    if d is None:
        d = days[t[:10]] = date(int(t[:4]), int(t[5:7]), int(t[8:10])).toordinal() - 719163
    return (((d * 24 + int(t[11:13])) * 60 + int(t[14:16])) * 60 + int(t[17:19])) * 1000 + int(t[20:23])


def _write(d: str, rows: Iterable[dict]) -> _Case:
    """Write events (dicts, in time order) as compressed blocks, with the timeline index and the event IDs in the case,
    to .tmp files that _commit puts in place."""
    ev, ix, meta = _paths(d)
    off, parts, lines, days, kinds = [0], [], [], {}, {}
    ms, steps, letters, ids = array("q"), [], [], {}

    def flush():
        z = zlib.compressobj(6, zlib.DEFLATED, 31)          # a gzip member
        part = z.compress(("\n".join(lines) + "\n").encode("utf-8")) + z.flush()
        fh.write(part)
        parts.append(part)
        off.append(off[-1] + len(part))
        lines.clear()

    with open(ev + ".tmp", "wb") as fh:
        for r in rows:
            lines.append(_ENC(r))
            t = _ms(r["time"], days)
            steps.append(t - (ms[-1] if ms else t))
            ms.append(t)
            ch = r["channel"]
            k = kinds.get(ch)
            if k is None:
                k = kinds[ch] = _KIND.get(channel_kind(ch), "o")
            letters.append(k)
            _count(ids, k, r)
            if len(lines) == BLOCK:
                flush()
        if lines:
            flush()
    summary = [_summary(s) for s in ids.values()]
    with open(ix + ".tmp", "w", encoding="utf-8") as fh:
        json.dump({"t0": ms[0] if ms else 0, "d": steps, "k": "".join(letters)}, fh, separators=(",", ":"))
    with open(meta + ".tmp", "w", encoding="utf-8") as fh:
        json.dump({"v": FORMAT, "size": off[-1], "block": BLOCK, "off": off, "ids": summary}, fh,
                  ensure_ascii=False, separators=(",", ":"))
    return _Case(b"".join(parts), off, ms, summary)


def _commit(d: str) -> None:
    """Put the files _write made in place - the index last, so a half-done write is redone on the next open."""
    for p in _paths(d):
        os.replace(p + ".tmp", p)


# ------------------------------------------------------------------ event IDs in the case
_RANK = {1: 0, 2: 0, 3: 1}   # error, warning; anything else (information, verbose, always) after them


def _count(ids: dict, k: str, r: dict) -> None:
    """One event into its event ID's tally: how many, the worst level, first and last, what it says."""
    key = (k, r["provider"], r["eid"])
    s = ids.get(key)
    if s is None:
        s = ids[key] = {"k": k, "p": r["provider"], "e": r["eid"], "n": 0, "er": 0, "wa": 0, "f": r["idx"],
                        "ft": r["time"], "m": "", "r": 3, "said": Counter()}
    s["n"] += 1
    rank = _RANK.get(r.get("level"), 2)
    if rank == 0:
        s["er"] += 1
    elif rank == 1:
        s["wa"] += 1
    s["l"], s["lt"] = r["idx"], r["time"]
    msg = r.get("msg")
    if msg and rank < s["r"]:   # what the worst of them says
        s["m"], s["r"] = msg[:400], rank
    said = str((r.get("data") or {}).get("MiniportEventDescription") or "").strip()
    if said:   # Storport's miniport events: what the driver says happened
        s["said"][said[:120]] += 1


def _summary(s: dict) -> dict:
    said = s.pop("said")
    s.pop("r")
    if said:
        s["said"] = said.most_common(6)
        s["kinds"] = len(said)
    return s


def warm(case_id: str) -> None:
    """Open the case now - the timeline and the References tab need it next."""
    _case(case_id)


def event_ids(case_id: str) -> List[dict]:
    """Every event ID in the case, once per log and provider: how many (errors, warnings), first and last event, what
    the worst of them says (its message) and, for Storport's miniport events, what the driver said, by count."""
    return _case(case_id).ids


# ------------------------------------------------------------------ reading events
def event_index(case_id: str) -> dict:
    """Every event's time and log, in time order, for the timeline cursor: t0 (ms) plus the step to each next
    event (ms), and one letter per event - s System, a Application, p Storport, o any other log."""
    return json.loads(index_bytes(case_id))


def index_bytes(case_id: str) -> bytes:
    """The timeline index as stored - JSON already."""
    d = _dir(case_id)
    _case(case_id)   # an earlier version's case gets its index here
    try:
        with open(_paths(d)[1], "rb") as fh:
            return fh.read()
    except OSError:
        return b'{"t0":0,"d":[],"k":""}'


def event_rows(case_id: str, i0: int, i1: int) -> List[dict]:
    """Events i0 .. i1-1 (an event's index is its place in time order), short: what each one is and says - the app or
    update it names, what the drive's driver said, else the first line of its message (Event Viewer's General text),
    else its key fields."""
    with _lock:
        return [_row(e) for e in _case(case_id).slice(i0, i1)]


def event_rows_at(case_id: str, ids: List[int]) -> List[dict]:
    """The same for the events with these indexes - a range's lists show events that can be far apart."""
    with _lock:
        c = _case(case_id)
        return [_row(c.block(i // BLOCK)[i % BLOCK]) for i in ids if 0 <= i < len(c)]


def events_around(case_id: str, i: int, n: int) -> List[dict]:
    """Event i with the n before and after it, in full."""
    with _lock:
        return _case(case_id).slice(i - n, i + n + 1)


def find_events(case_id: str, start: str = None, end: str = None, tag: str = None, text: str = "",
                limit: int = 500, last: bool = False) -> List[dict]:
    """Events from start to end (ISO times), only those with this tag (software / storage: then short, without their
    data), or whose text has these words; the first `limit` of them, or the last ones."""
    text = (text or "").lower()
    with _lock:
        c, days = _case(case_id), {}
        i0 = bisect_left(c.ms, _ms(start, days)) if start else 0
        i1 = bisect_right(c.ms, _ms(end, days)) if end else len(c)
        out = []
        for b in range(i0 // BLOCK, (i1 - 1) // BLOCK + 1) if i1 > i0 else ():
            for e in c.block(b)[max(0, i0 - b * BLOCK):i1 - b * BLOCK]:
                if tag and not e.get(tag):
                    continue
                if text and text not in f"{e['provider']} {e['eid']} {e['channel']} {e.get('msg', '')} {json.dumps(e.get('data', {}))}".lower():
                    continue
                out.append({**{k: e[k] for k in ("idx", "time", "provider", "eid", "channel")}, **e[tag]} if tag else e)
                if not last and len(out) >= limit:
                    return out
        return out[max(0, len(out) - limit):]


def _row(e: dict) -> dict:
    if not _labels:   # "Unclean shutdown reported (Kernel-Power 41)": the row shows the ID and provider already
        cfg = catalog.load_config()
        _labels.update({k: re.sub(r"\s*\([^()]*\)$", "", v) for k, v in cfg["signal_labels"].items()})
        _titles.update(reference.titles(cfg))
    sw, st = e.get("software"), e.get("storage")
    tag, msg, data = sw or st or {}, e.get("msg") or "", e.get("data") or {}
    text = " · ".join(x for x in (tag.get("subject"), tag.get("detail")) if x) if sw else ""
    said = str(data.get("MiniportEventDescription") or "").strip()
    label = _labels.get(e.get("signal")) or tag.get("label") or ""
    if not label or label.endswith(f" {e['eid']}"):   # no name, or a generic one ("Storport event 527"): the reference's
        label = _titles.get((e["provider"].lower(), e["eid"])) or label
    row = {"idx": e["idx"], "time": e["time"], "eid": e["eid"], "level": e.get("level", 4),
           "provider": e["provider"], "channel": e["channel"], "label": label,
           "text": text or said or msg.split("\n", 1)[0][:300] or _fields(data, 6 if st else 4),
           "state": tag.get("state") or ""}
    if msg:   # the start of it for the row's tooltip; the whole message comes with the event's data
        row["msg"] = msg[:600]
    return row


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
    if os.path.isdir(d):
        shutil.rmtree(d)
