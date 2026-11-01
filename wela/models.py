"""Core data model: one normalised event record."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional


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
    source: str = ""               # file it came from
    idx: int = 0                   # global index after sorting
    signal: Optional[str] = None   # power signal tag (set by engine)
    storage: Optional[dict] = None # storage classification + drive identity (set by engine)
    software: Optional[dict] = None  # app / update / service classification (set by engine)

    @property
    def ts(self) -> float:
        return self.time.timestamp()

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
            source=d.get("source", ""),
            idx=d.get("idx", 0),
        )


def iso(t: Optional[datetime]) -> Optional[str]:
    if t is None:
        return None
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_time(s: str) -> datetime:
    """Parse Windows SystemTime strings like 2026-09-03T09:02:17.5000000Z."""
    s = (s or "").strip()
    if not s:
        raise ValueError("empty time")
    tz = timezone.utc
    if s.endswith("Z"):
        s = s[:-1]
    elif len(s) > 6 and s[-6] in "+-" and s[-3] == ":":
        sign = 1 if s[-6] == "+" else -1
        hh, mm = int(s[-5:-3]), int(s[-2:])
        from datetime import timedelta
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
