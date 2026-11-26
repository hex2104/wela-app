"""Core data model: one normalised event record."""
from __future__ import annotations

import gc
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

_UTC = timezone.utc


@contextmanager
def no_gc():
    """Pause Python's cycle collector while many objects are made: events hold no cycles, and its passes over the
    growing heap can more than double the time it takes to read a big log."""
    was = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if was:
            gc.enable()


@dataclass
class Event:
    time: datetime                 # always timezone-aware UTC
    channel: str                   # e.g. "System"
    provider: str                  # e.g. "Microsoft-Windows-Kernel-Power"
    eid: int                       # event ID
    rid: Optional[int]             # EventRecordID (per channel/file)
    level: int                     # 1 critical, 2 error, 3 warning, 4 info, 0 always
    computer: str = ""
    data: Dict[str, str] = field(default_factory=dict)
    msg: str = ""                  # what the event says in words (Event Viewer's General tab), when Windows rendered it
    source: str = ""               # file it came from
    idx: int = 0                   # global index after sorting
    signal: Optional[str] = None   # power signal tag (set by engine)
    storage: Optional[dict] = None # storage classification + drive identity (set by engine)
    software: Optional[dict] = None  # app / update / service classification (set by engine)
    ts: float = field(init=False, repr=False, compare=False, default=0.0)   # time as seconds since 1970, worked out once

    def __post_init__(self):
        self.ts = self.time.timestamp()

    def to_dict(self, full: bool = True) -> dict:
        d = {
            "idx": self.idx,
            "time": iso(self.time),
            "channel": self.channel,
            "provider": self.provider,
            "eid": self.eid,
            "rid": self.rid,
            "level": self.level,
        }
        if self.signal:
            d["signal"] = self.signal
        if self.storage:
            d["storage"] = self.storage
        if self.software:
            d["software"] = self.software
        if full:
            d["data"] = self.data
            if self.msg:
                d["msg"] = self.msg
            d["computer"] = self.computer
            d["source"] = self.source
        return d

    @staticmethod
    def from_dict(d: dict) -> "Event":
        return Event(
            time=parse_time(d["time"]),
            channel=d.get("channel", ""),
            provider=d.get("provider", ""),
            eid=int(d.get("eid", 0)),
            rid=d.get("rid"),
            level=int(d.get("level", 4) or 4),
            computer=d.get("computer", ""),
            data=d.get("data") or {},
            msg=d.get("msg") or "",
            source=d.get("source", ""),
            idx=d.get("idx", 0),
        )


def iso(t: Optional[datetime]) -> Optional[str]:
    if t is None:
        return None
    if t.tzinfo is not _UTC:
        t = t.astimezone(_UTC)
    return f"{t.year:04d}-{t.month:02d}-{t.day:02d}T{t.hour:02d}:{t.minute:02d}:{t.second:02d}.{t.microsecond // 1000:03d}Z"


def parse_time(s: str) -> datetime:
    """Parse Windows SystemTime strings like 2026-09-03T09:02:17.5000000Z."""
    s = (s or "").strip()
    if not s:
        raise ValueError("empty time")
    # the form every log uses, read without strptime (several times faster): 2026-09-03T09:02:17[.5000000]Z
    if len(s) >= 20 and s[-1] == "Z" and s[4] == "-" and s[7] == "-" and s[10] in "T " and s[13] == ":" and s[16] == ":":
        frac = s[20:-1] if s[19] == "." else ""
        if (s[19] == "Z" or frac.isdigit()) and s[:4].isdigit():
            try:
                return datetime(int(s[:4]), int(s[5:7]), int(s[8:10]), int(s[11:13]), int(s[14:16]), int(s[17:19]),
                                int((frac + "000000")[:6]) if frac else 0, _UTC)
            except ValueError:
                pass
    tz = timezone.utc
    if s.endswith("Z"):
        s = s[:-1]
    elif len(s) > 6 and s[-6] in "+-" and s[-3] == ":":
        sign = 1 if s[-6] == "+" else -1
        hh, mm = int(s[-5:-3]), int(s[-2:])
        tz = timezone(sign * timedelta(hours=hh, minutes=mm))
        s = s[:-6]
    s = s.replace(" ", "T")
    if "." in s:
        main, frac = s.split(".", 1)
        frac = (frac + "000000")[:6]
        s = main + "." + frac
        fmt = "%Y-%m-%dT%H:%M:%S.%f"
    else:
        fmt = "%Y-%m-%dT%H:%M:%S"
    return datetime.strptime(s, fmt).replace(tzinfo=tz).astimezone(timezone.utc)
