"""WELA analysis engine.

Pipeline
  1. tag      - mark every event with its power signal / storage meaning
  2. integrity- coverage per channel, record-ID gaps, cleared logs, clock jumps
  3. boots    - cluster boot markers (12 / 6005 / 6009 / 27) into boots
  4. sessions - everything between two boots is one boot session
  5. classify - for every boot, decide how the *previous* session ended
                (normal shutdown / restart / hard shutdown / unknown) from
                redundant evidence + timing, with a confidence score
  6. sleeps   - sleep / hibernate / Modern Standby episodes inside sessions,
                rebuilt from 42 / 107 / Power-Troubleshooter 1 / 506 / 507
  7. drive    - all storage events (Storport included, every level) in a window
                before power-off / sleep and after boot / wake
  8. assess   - did the drive cause the transition, and what was the effect on it
"""
from __future__ import annotations

import bisect
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from . import __version__
from .catalog import DEFAULTS
from .models import Event, iso, parse_time

STATE_RANK = {"missing": 5, "reset": 4, "error": 3, "slow": 2, "warning": 1, "info": 0, "healthy": 0}
BOOT_SIGNALS = {"BOOT_OS_START", "BOOT_LOG_START", "BOOT_OS_VERSION", "BOOT_TYPE"}
CLEAN_SIGNALS = ["SHUTDOWN_REQUEST", "OS_STOP", "LOG_STOP", "KP_SHUTDOWN_INIT", "USER_LOGOFF"]
HARD_SIGNALS = ["KP_UNEXPECTED", "UNEXPECTED_PREV", "BUGCHECK"]
BOOT_TYPE_NAMES = {0: "Cold boot", 1: "Hybrid boot (Fast Startup)", 2: "Resume from hibernate"}
CAUSE_LABELS = {"likely": "Likely", "possible": "Possibly", "no_evidence": "No drive evidence", "unknown": "Can't tell"}
EFFECT_LABELS = {"missing": "Drive missing after {on}", "errors": "Errors after {on}", "warnings": "Warnings after {on}",
                 "none": "Healthy after {on}", "unknown": "No data after {on}"}
# SCSI opcodes as seen in Storport events (NVMe I/O is translated to SCSI by stornvme)
SCSI_OPS = {0x00: "TEST UNIT READY", 0x03: "REQUEST SENSE", 0x12: "INQUIRY", 0x1A: "MODE SENSE(6)",
            0x1B: "START STOP UNIT", 0x25: "READ CAPACITY(10)", 0x28: "READ(10)", 0x2A: "WRITE(10)",
            0x35: "SYNCHRONIZE CACHE(10)", 0x42: "UNMAP", 0x4D: "LOG SENSE", 0x5A: "MODE SENSE(10)",
            0x88: "READ(16)", 0x8A: "WRITE(16)", 0x91: "SYNCHRONIZE CACHE(16)", 0x9E: "SERVICE ACTION IN(16)",
            0xA0: "REPORT LUNS"}
# event data keys shown first in the per-event field summary
FIELD_HINTS = ("opcode", "status", "sense", "asc", "error", "reason", "latency", "duration", "timeout", "reset")


# --------------------------------------------------------------------------- helpers
def channel_kind(ch: str) -> str:
    c = (ch or "").lower()
    if "storport" in c:
        return "storport"
    if c == "system":
        return "system"
    if c == "application":
        return "application"
    return "other"


def _int(v, default=None):
    try:
        s = str(v).strip()
        return int(s, 16) if s.lower().startswith("0x") else int(s)
    except (TypeError, ValueError):
        return default


def _try_time(v) -> Optional[datetime]:
    try:
        return parse_time(v) if v else None
    except ValueError:
        return None


def _flag(sev: str, text: str) -> dict:
    return {"severity": sev, "text": text}


def _clamp(x: float) -> float:
    return round(max(0.0, min(1.0, x)), 2)


def _fmt_dur(sec: Optional[float]) -> str:
    if sec is None:
        return "?"
    sec = int(round(sec))
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60}s"
    if sec < 86400:
        return f"{sec // 3600}h {(sec % 3600) // 60}m"
    return f"{sec // 86400}d {(sec % 86400) // 3600}h"


def _fields(data: dict, limit: int = 8) -> str:
    """Short 'key=value' summary of an event's data, most diagnostic keys first."""
    items = [(k, str(v).strip()) for k, v in (data or {}).items() if str(v).strip()]
    items.sort(key=lambda kv: 0 if any(h in kv[0].lower() for h in FIELD_HINTS) else 1)
    out = []
    for k, v in items[:limit]:
        s = f"{k}={v[:60]}"
        op = _int(v) if "opcode" in k.lower() else None
        if op in SCSI_OPS:
            s += f" ({SCSI_OPS[op]})"
        out.append(s)
    return "  ".join(out)


def _counts_text(counts: dict) -> str:
    return ", ".join(f"{label} x{n}" for label, n in sorted(counts.items(), key=lambda kv: -kv[1]))


class Analyzer:
    def __init__(self, events: List[Event], cfg: dict = None, sources: List[dict] = None):
        self.cfg = cfg or DEFAULTS
        self.s = self.cfg["settings"]
        self.labels = self.cfg["signal_labels"]
        self.sources = sources or []
        events.sort(key=lambda e: (e.ts, 0 if channel_kind(e.channel) == "system" else 1, e.rid or 0))
        for i, e in enumerate(events):
            e.idx = i
        self.events = events
        self.times = [e.ts for e in events]

    # ------------------------------------------------------------------ 1. tagging
    def tag(self):
        sig = {}
        for name, pairs in self.cfg["signals"].items():
            for prov, eid in pairs:
                sig[(prov.lower(), int(eid))] = name
        exact, wild = {}, {}
        for prov, eid, label, state in self.cfg["storage_events"]:
            if eid == "*":
                wild[prov.lower()] = (label, state)
            else:
                exact[(prov.lower(), int(eid))] = (label, state)
        hints = [h.lower() for h in self.cfg["storage_provider_hints"]]
        for e in self.events:
            p = e.provider.lower()
            e.signal = sig.get((p, e.eid))
            hit = exact.get((p, e.eid))
            if hit is None and p in wild:
                hit = (f"{wild[p][0]} {e.eid}", wild[p][1])
            if hit is None and channel_kind(e.channel) == "storport":
                hit = (f"Storport event {e.eid}", "auto")
            if hit is None and e.level in (1, 2, 3) and any(h in p for h in hints):
                hit = (f"{e.provider} {e.eid}", "auto")
            if hit:
                label, state = hit
                if state == "auto":
                    state = "error" if e.level in (1, 2) else "warning" if e.level == 3 else "info"
                e.storage = {"label": label, "state": state}
        self.storage = [e for e in self.events if e.storage]
        self.storage_times = [e.ts for e in self.storage]

    # ------------------------------------------------------------------ 2. integrity
    def integrity(self):
        by_chan: Dict[str, List[Event]] = defaultdict(list)
        by_file_chan: Dict[Tuple[str, str], List[Event]] = defaultdict(list)
        for e in self.events:
            by_chan[e.channel].append(e)
            by_file_chan[(e.source, e.channel)].append(e)

        channels = []
        for ch, evs in by_chan.items():
            channels.append({
                "channel": ch, "kind": channel_kind(ch), "events": len(evs),
                "start": iso(evs[0].time), "end": iso(evs[-1].time),
                "start_ts": evs[0].ts, "end_ts": evs[-1].ts,
            })
        channels.sort(key=lambda c: ({"system": 0, "application": 1, "storport": 2}.get(c["kind"], 3), c["channel"]))
        self.channels = channels

        gaps, clock_back = [], []
        for (src, ch), evs in by_file_chan.items():
            withrid = sorted((e for e in evs if e.rid is not None), key=lambda e: e.rid)
            for a, b in zip(withrid, withrid[1:]):
                if b.rid - a.rid > 1:
                    gaps.append({"channel": ch, "source": src, "after_rid": a.rid, "before_rid": b.rid,
                                 "missing": b.rid - a.rid - 1, "start": iso(a.time), "end": iso(b.time),
                                 "start_ts": a.ts, "end_ts": b.ts})
                if b.ts < a.ts - 60:
                    clock_back.append({"channel": ch, "rid": b.rid, "time": iso(b.time),
                                       "back_by_s": round(a.ts - b.ts)})
        self.record_gaps = sorted(gaps, key=lambda g: g["start_ts"])

        clears = [{"time": iso(e.time), "channel": e.channel, "idx": e.idx, "eid": e.eid,
                   "detail": e.data.get("Channel") or e.data.get("SubjectUserName") or ""}
                  for e in self.events if e.signal == "LOG_CLEARED"]

        kinds = {c["kind"] for c in channels}
        missing = [name for name, kind in self.cfg["expected_channels"].items() if kind not in kinds]
        self.integrity_out = {
            "record_gaps": self.record_gaps, "clears": clears, "clock_backwards": clock_back,
            "missing_channels": missing, "time_changes": [], "unexplained_gaps": [],
            "unreadable_files": [s for s in self.sources if s.get("error")],
        }

    def _covered(self, kind: str, t0: float, t1: float) -> bool:
        return any(c["kind"] == kind and c["start_ts"] <= t1 and c["end_ts"] >= t0 for c in self.channels)

    def _gap_overlaps(self, t0: float, t1: float) -> List[dict]:
        return [g for g in self.record_gaps if channel_kind(g["channel"]) == "system"
                and g["start_ts"] <= t1 and g["end_ts"] >= t0]

    # ------------------------------------------------------------------ 3. boots
    def find_boots(self):
        clusters = []
        for e in self.events:
            if e.signal not in BOOT_SIGNALS:
                continue
            c = clusters[-1] if clusters else None
            if (c and e.ts - c["start_ts"] <= self.s["boot_cluster_s"]
                    and e.signal not in c["signals"]):
                c["events"].append(e)
                c["signals"].add(e.signal)
            else:
                clusters.append({"start_ts": e.ts, "events": [e], "signals": {e.signal}})
        boots, hib_resumes = [], []
        for c in clusters:
            bt = None
            for e in c["events"]:
                if e.signal == "BOOT_TYPE":
                    bt = _int(e.data.get("BootType"))
            c["boot_type"] = bt
            c["start"] = c["events"][0].time
            real = bool(c["signals"] & {"BOOT_OS_START", "BOOT_LOG_START"}) or (
                "BOOT_TYPE" in c["signals"] and bt in (0, 1))
            if real:
                boots.append(c)
            elif bt == 2:
                hib_resumes.append(c)
        self.boots = boots
        self.hib_resumes = hib_resumes
        self.boot_ts = [b["start_ts"] for b in boots]

    def _session_of(self, ts: float) -> int:
        """-1 = before first boot in the log."""
        return bisect.bisect_right(self.boot_ts, ts) - 1

    # ------------------------------------------------------------------ 4/6. sessions + sleep
    def build_sessions(self):
        sessions: Dict[int, List[Event]] = defaultdict(list)
        for e in self.events:
            sessions[self._session_of(e.ts)].append(e)
        self.session_events = sessions
        self.sessions = []
        for k in sorted(sessions):
            evs = sessions[k]
            b = self.boots[k] if k >= 0 else None
            self.sessions.append({
                "id": k, "start": iso(b["start"] if b else evs[0].time), "end": iso(evs[-1].time),
                "start_ts": b["start_ts"] if b else evs[0].ts, "end_ts": evs[-1].ts,
                "partial_start": b is None,
                "boot_type": BOOT_TYPE_NAMES.get(b["boot_type"]) if b else None,
                "events": len(evs),
            })

    def _ev(self, e: Event, note: str = "") -> dict:
        return {"signal": e.signal, "label": self.labels.get(e.signal, f"{e.provider} {e.eid}"),
                "eid": e.eid, "provider": e.provider, "time": iso(e.time), "idx": e.idx, "note": note}

    def find_sleeps(self):
        s = self.s
        out = []
        hib_by_session = defaultdict(list)
        for c in self.hib_resumes:
            hib_by_session[self._session_of(c["start_ts"])].append(c["events"][0])
        for k, evs in self.session_events.items():
            stream = [e for e in evs if e.signal in ("SLEEP_ENTER", "SLEEP_RESUME", "SLEEP_REPORT", "MS_ENTER", "MS_EXIT")]
            stream += hib_by_session.get(k, [])
            stream.sort(key=lambda e: e.idx)
            eps: List[dict] = []
            open_ep: Optional[dict] = None

            def new_ep(kind, start_e=None, start_ts=None):
                return {"kind": kind, "session": k, "start_ts": start_e.ts if start_e else start_ts,
                        "end_ts": None, "found": [], "flags": [], "wake_source": None, "target": None,
                        "_sig": set()}

            for e in stream:
                sig = e.signal
                if sig in ("SLEEP_ENTER", "MS_ENTER"):
                    kind = "modern_standby" if sig == "MS_ENTER" else "sleep"
                    if open_ep and e.ts - open_ep["start_ts"] <= 10:
                        open_ep["found"].append(self._ev(e))
                        open_ep["_sig"].add(sig)
                        continue
                    if open_ep:
                        open_ep["flags"].append(_flag("warn", "No resume logged before the next sleep entry"))
                        eps.append(open_ep)
                    open_ep = new_ep(kind, e)
                    tgt = _int(e.data.get("TargetState"))
                    if tgt == 5:
                        open_ep["kind"] = "hibernate"
                    open_ep["target"] = tgt
                    open_ep["found"].append(self._ev(e, f"TargetState={e.data.get('TargetState', '?')}"))
                    open_ep["_sig"].add(sig)
                elif sig in ("SLEEP_RESUME", "MS_EXIT", "BOOT_TYPE"):
                    note = "Kernel-Boot 27 BootType=2 (resume from hibernate)" if sig == "BOOT_TYPE" else ""
                    if open_ep is None:
                        kind = "modern_standby" if sig == "MS_EXIT" else "hibernate" if sig == "BOOT_TYPE" else "sleep"
                        open_ep = new_ep(kind, start_ts=None)
                        open_ep["flags"].append(_flag("info", "Sleep entry not logged - rebuilt from resume"))
                    if sig == "BOOT_TYPE":
                        open_ep["kind"] = "hibernate"
                    open_ep["end_ts"] = e.ts
                    open_ep["found"].append(self._ev(e, note))
                    open_ep["_sig"].add(sig)
                    eps.append(open_ep)
                    open_ep = None
                elif sig == "SLEEP_REPORT":
                    st, wt = _try_time(e.data.get("SleepTime")), _try_time(e.data.get("WakeTime"))
                    src = e.data.get("WakeSourceText") or None
                    tgt = _int(e.data.get("TargetState"))
                    note = f"Sleep {iso(st) or '?'} -> wake {iso(wt) or '?'}" + (f", wake source: {src}" if src else "")
                    target = None
                    last = eps[-1] if eps else None
                    if open_ep is not None:
                        target = open_ep
                        target["end_ts"] = wt.timestamp() if wt else e.ts
                        eps.append(open_ep)
                        open_ep = None
                    elif last and last["end_ts"] and abs(e.ts - last["end_ts"]) <= s["pt1_merge_s"] \
                            and "SLEEP_REPORT" not in last["_sig"]:
                        target = last
                    else:
                        target = new_ep("sleep", start_ts=st.timestamp() if st else None)
                        target["end_ts"] = wt.timestamp() if wt else e.ts
                        target["flags"].append(_flag("info", "Entry and resume events not logged - rebuilt from Power-Troubleshooter 1"))
                        eps.append(target)
                    if target["start_ts"] is None and st:
                        target["start_ts"] = st.timestamp()
                    if tgt == 5:
                        target["kind"] = "hibernate"
                    target["wake_source"] = src
                    target["found"].append(self._ev(e, note))
                    target["_sig"].add(sig)
            if open_ep:
                open_ep["flags"].append(_flag("warn", "No resume logged - session ended while asleep"))
                open_ep["open"] = True
                eps.append(open_ep)
            out.extend(eps)

        sleeps = []
        for ep in out:
            sigs = ep.pop("_sig")
            if ep["kind"] == "modern_standby":
                expected = ["MS_ENTER", "MS_EXIT"]
                conf = 0.9 if {"MS_ENTER", "MS_EXIT"} <= sigs else 0.5
            else:
                expected = ["SLEEP_ENTER", "SLEEP_RESUME", "SLEEP_REPORT"]
                have = len(sigs & {"SLEEP_ENTER", "SLEEP_RESUME", "SLEEP_REPORT", "BOOT_TYPE"})
                conf = {0: 0.3, 1: 0.6, 2: 0.85}.get(have, 1.0)
            if ep.get("open"):
                conf = min(conf, 0.5)
            missing = [self.labels[x] for x in expected if x not in sigs]
            if ep["kind"] == "hibernate" and "BOOT_TYPE" in sigs and "SLEEP_RESUME" in missing:
                missing.remove(self.labels["SLEEP_RESUME"])
            start_ts = ep["start_ts"]
            end_ts = ep["end_ts"]
            sub = {"sleep": "Sleep (S3)", "hibernate": "Hibernate (S4)",
                   "modern_standby": "Modern Standby"}[ep["kind"]]
            sleeps.append({
                "type": "sleep", "kind": ep["kind"], "subtype": sub, "session": ep["session"],
                "time": iso(datetime.fromtimestamp(start_ts, timezone.utc)) if start_ts else None,
                "end": iso(datetime.fromtimestamp(end_ts, timezone.utc)) if end_ts else None,
                "time_ts": start_ts if start_ts else end_ts, "start_ts": start_ts, "end_ts": end_ts,
                "duration_s": round(end_ts - start_ts) if start_ts and end_ts else None,
                "duration": _fmt_dur(end_ts - start_ts) if start_ts and end_ts else "?",
                "wake_source": ep["wake_source"], "open": bool(ep.get("open")),
                "evidence_found": ep["found"], "evidence_missing": missing, "flags": ep["flags"],
                "confidence": _clamp(conf),
            })
        self.sleeps = sorted(sleeps, key=lambda x: x["time_ts"] or 0)

    # ------------------------------------------------------------------ 5. classify boundaries
    def _shutdown_kind_from_1074(self, e: Event) -> Optional[str]:
        txt = " ".join(str(v) for v in e.data.values()).lower()
        t5 = (e.data.get("param5") or "").lower() or txt
        for w in self.cfg["restart_words"]:
            if w in t5:
                return "restart"
        for w in self.cfg["poweroff_words"]:
            if w in t5:
                return "shutdown"
        return None

    def classify(self):
        s, W = self.s, self.cfg["weights"]
        open_sleep_by_session = {sl["session"]: sl for sl in self.sleeps if sl["open"]}
        transitions = []
        for k, boot in enumerate(self.boots):
            prev = self.session_events.get(k - 1, [])
            cur = self.session_events.get(k, [])
            bstart = boot["start_ts"]
            boot_type = boot["boot_type"]
            flags: List[dict] = []
            found: List[dict] = []

            last_alive = prev[-1] if prev else None
            tail = [e for e in prev if last_alive and e.ts >= last_alive.ts - s["tail_window_s"]]
            stop = {}
            for e in tail:
                if e.signal in CLEAN_SIGNALS:
                    stop[e.signal] = e  # keep the latest
            bwin = [e for e in cur if e.ts <= bstart + s["boot_window_s"]]
            hard = {}
            for e in bwin:
                if e.signal in HARD_SIGNALS and e.signal not in hard:
                    hard[e.signal] = e
            sleep_open = open_sleep_by_session.get(k - 1)
            prev_visible = bool(prev)
            sys_prev = any(channel_kind(e.channel) == "system" for e in prev)

            # integrity around the boundary
            t0 = (last_alive.ts if last_alive else bstart) - s["tail_window_s"]
            gaps = self._gap_overlaps(t0, bstart + s["boot_window_s"])
            integrity_issue = bool(gaps) or (prev_visible and not sys_prev)
            if gaps:
                flags.append(_flag("warn", f"System log has {sum(g['missing'] for g in gaps)} missing record(s) "
                                           f"at this boundary - stop events may be lost"))
            if prev_visible and not sys_prev:
                flags.append(_flag("warn", "System log does not cover the end of the previous session"))

            for e in list(stop.values()) + list(hard.values()):
                note = ""
                if e.signal == "SHUTDOWN_REQUEST":
                    note = ", ".join(x for x in [
                        f"type: {e.data.get('param5')}" if e.data.get("param5") else "",
                        f"process: {e.data.get('param1')}" if e.data.get("param1") else "",
                        f"reason: {e.data.get('param3')}" if e.data.get("param3") else "",
                        f"user: {e.data.get('param7')}" if e.data.get("param7") else ""] if x)
                elif e.signal == "KP_UNEXPECTED":
                    bc = _int(e.data.get("BugcheckCode"), 0) or 0
                    note = (f"BugcheckCode=0x{bc:X}, PowerButtonTimestamp={e.data.get('PowerButtonTimestamp', '?')}, "
                            f"SleepInProgress={e.data.get('SleepInProgress', '?')}")
                elif e.signal == "BUGCHECK":
                    note = e.data.get("param1", "")
                found.append(self._ev(e, note))
            for e in boot["events"]:
                note = f"BootType={boot_type} ({BOOT_TYPE_NAMES.get(boot_type, '?')})" if e.signal == "BOOT_TYPE" else ""
                found.append(self._ev(e, note))
            found.sort(key=lambda x: x["idx"])

            clean_score = min(1.0, sum(W["clean"].get(x, 0) for x in stop))
            stop_time = max((e.ts for e in stop.values()), default=None)
            t = {"type": None, "subtype": None, "boot_index": k}
            bc = 0

            if hard:
                e41 = hard.get("KP_UNEXPECTED")
                bc = _int(e41.data.get("BugcheckCode"), 0) if e41 else 0
                if not bc and "BUGCHECK" in hard:  # 1001 param1 starts with the code, e.g. "0x0000009f (...)"
                    m = re.search(r"0x[0-9a-fA-F]+", hard["BUGCHECK"].data.get("param1", ""))
                    bc = int(m.group(0), 16) if m else 0
                pbt = _int(e41.data.get("PowerButtonTimestamp"), 0) if e41 else 0
                sip = _int(e41.data.get("SleepInProgress"), 0) if e41 else 0
                score = sum(W["hard"].get(x, 0) for x in hard)
                if not stop:
                    score += W["silent_end"] if prev_visible else 0
                if "BUGCHECK" in hard or (bc or 0) != 0:
                    sub = f"Crash (bugcheck 0x{bc:X})" if bc else "Crash (bugcheck)"
                elif pbt:
                    sub = "Power button long-press"
                elif sip or sleep_open:
                    sub = "Power lost during sleep/hibernate"
                elif stop:
                    sub = "Shutdown started but did not complete (hang)"
                else:
                    sub = "Power loss / hang / forced reset"
                if "OS_STOP" in stop and "LOG_STOP" in stop:
                    score -= W["conflict_penalty"]
                    flags.append(_flag("warn", "Clean stop (13 + 6006) recorded, yet Windows reports an unclean "
                                               "shutdown on next boot - check manually"))
                if "KP_UNEXPECTED" in hard and "UNEXPECTED_PREV" not in hard:
                    flags.append(_flag("info", "41 logged without 6008"))
                if "UNEXPECTED_PREV" in hard and "KP_UNEXPECTED" not in hard:
                    flags.append(_flag("info", "6008 logged without 41"))
                t.update(type="hard", subtype=sub)
                expected = ["KP_UNEXPECTED", "UNEXPECTED_PREV"]
            elif stop:
                kind, explicit = None, False
                if "SHUTDOWN_REQUEST" in stop:
                    kind = self._shutdown_kind_from_1074(stop["SHUTDOWN_REQUEST"])
                    explicit = kind is not None
                gap = bstart - stop_time if stop_time else None
                if boot_type == 1:
                    if kind == "restart":
                        flags.append(_flag("warn", "1074 says restart, but next boot is a Fast Startup hybrid boot"))
                    kind, explicit = "shutdown", True
                if kind is None:
                    kind = "restart" if gap is not None and gap <= s["restart_gap_s"] else "shutdown"
                    flags.append(_flag("info", f"Restart vs shutdown inferred from {_fmt_dur(gap)} gap "
                                               f"(1074 type not available)"))
                if kind == "restart" and gap is not None and gap > s["long_restart_gap_s"]:
                    flags.append(_flag("warn", f"Restart requested but next boot came {_fmt_dur(gap)} later"))
                score = clean_score + (W["explicit_type_bonus"] if explicit else 0)
                if kind == "shutdown":
                    sub = {1: "Fast Startup (kernel hibernated)", 0: "Full shutdown"}.get(boot_type, "Shutdown")
                else:
                    sub = "Restart"
                if sleep_open:
                    flags.append(_flag("info", "A sleep without resume preceded this shutdown"))
                t.update(type=kind, subtype=sub)
                expected = ["SHUTDOWN_REQUEST", "OS_STOP", "LOG_STOP"]
            else:
                expected = ["SHUTDOWN_REQUEST", "OS_STOP", "LOG_STOP", "KP_UNEXPECTED", "UNEXPECTED_PREV"]
                if not prev_visible:
                    t.update(type="unknown", subtype="Previous session not in log")
                    score = 0.0
                    flags.append(_flag("info", "Log starts at this boot - how the machine was turned off before is not recorded"))
                elif integrity_issue:
                    t.update(type="unknown", subtype="Log gap at boundary")
                    score = 0.2
                elif sleep_open:
                    t.update(type="hard", subtype="Power lost during sleep (inferred)")
                    score = W["silent_end"]
                    flags.append(_flag("warn", "Inferred: machine was asleep and next event is a fresh boot, "
                                               "with no stop or 41/6008 events"))
                else:
                    t.update(type="hard", subtype="Inferred: no stop events before boot")
                    score = W["silent_end"]
                    flags.append(_flag("warn", "Inferred: log ends with no stop events and no 41/6008 on boot"))

            if integrity_issue and t["type"] != "unknown":
                score -= W["integrity_penalty"]
            conf = _clamp(score)
            missing = [self.labels[x] for x in expected if x not in stop and x not in hard]
            alive_ts = last_alive.ts if last_alive else None
            gap_s = bstart - alive_ts if alive_ts else None
            t.update({
                "time": iso(last_alive.time) if last_alive else iso(boot["start"]),
                "time_ts": alive_ts if alive_ts else bstart,
                "last_alive": iso(last_alive.time) if last_alive else None,
                "last_alive_ts": alive_ts,
                "stop_time": iso(datetime.fromtimestamp(stop_time, timezone.utc)) if stop_time else None,
                "boot_time": iso(boot["start"]), "boot_ts": bstart,
                "boot_type": BOOT_TYPE_NAMES.get(boot_type) if boot_type is not None else None,
                "gap_s": round(gap_s) if gap_s is not None else None,
                "gap": _fmt_dur(gap_s) if gap_s is not None else "?",
                "bugcheck": bc or None,
                "confidence": conf, "evidence_found": found, "evidence_missing": missing, "flags": flags,
            })
            transitions.append(t)
        self.transitions = transitions

    # ------------------------------------------------------------------ 7. drive correlation
    def _storage_between(self, t0: float, t1: float, info: bool = False) -> List[Event]:
        i = bisect.bisect_left(self.storage_times, t0)
        j = bisect.bisect_right(self.storage_times, t1)
        return [e for e in self.storage[i:j] if info or e.storage["state"] != "info"]

    def _is_platform(self, e: Event) -> bool:
        p = e.provider.lower()
        return any(h in p for h in self.cfg.get("platform_provider_hints", []))

    def _window(self, t0: float, t1: float, anchor: float) -> dict:
        """Every storage event in [t0, t1]; informational ones are listed but do not change the state."""
        evs = self._storage_between(t0, t1, info=True)
        bad = [e for e in evs if e.storage["state"] != "info"]
        covered = self._covered("system", t0, t1) or self._covered("storport", t0, t1)

        def worst(xs):
            if xs:
                return max((e.storage["state"] for e in xs), key=lambda x: STATE_RANK.get(x, 0))
            return "healthy" if covered else "no data"

        return {"state": worst(bad), "drive_state": worst([e for e in bad if not self._is_platform(e)]),
                "from": iso(datetime.fromtimestamp(t0, timezone.utc)),
                "to": iso(datetime.fromtimestamp(t1, timezone.utc)),
                "anchor": iso(datetime.fromtimestamp(anchor, timezone.utc)),
                "storport_covered": self._covered("storport", t0, t1),
                "counts": dict(Counter(e.storage["label"] for e in bad)),
                "platform_counts": dict(Counter(e.storage["label"] for e in bad if self._is_platform(e))),
                "first_issue_s": round(bad[0].ts - anchor, 1) if bad else None,
                "last_issue_s": round(bad[-1].ts - anchor, 1) if bad else None,
                "total": len(evs), "info_count": len(evs) - len(bad),
                "events": [{"idx": e.idx, "time": iso(e.time), "offset_s": round(e.ts - anchor, 1),
                            "provider": e.provider, "eid": e.eid, "channel": e.channel,
                            "label": e.storage["label"], "state": e.storage["state"], "level": e.level,
                            "fields": _fields(e.data)} for e in evs[:300]]}

    def correlate(self):
        w = self.s["drive_window_s"]

        def attach(item, t_before, t_after):
            pre = self._window(t_before - w, t_before + 5, t_before) if t_before else None
            post = self._window(t_after, t_after + w, t_after) if t_after else None
            states = [x["state"] for x in (pre, post) if x]
            real = [x for x in states if x != "no data"]
            state = max(real, key=lambda x: STATE_RANK.get(x, 0)) if real else "no data"
            item["drive"] = {"state": state, "window_s": w, "before": pre, "after": post,
                             "storport_covered": any(x["storport_covered"] for x in (pre, post) if x)}
            if not item["drive"]["storport_covered"] and self._covered("storport", 0, 1e12):
                item["flags"].append(_flag("info", "Storport log does not cover this time"))

        for t in self.transitions:
            attach(t, t["last_alive_ts"], t["boot_ts"])
        for sl in self.sleeps:
            attach(sl, sl["start_ts"], sl["end_ts"])

    # ------------------------------------------------------------------ 8. did the drive cause it?
    def _bugcheck_info(self, code: Optional[int]) -> Optional[Tuple[str, str]]:
        for k, (name, strength) in self.cfg.get("storage_bugchecks", {}).items():
            if code and _int(k) == code:
                return name, strength
        return None

    def assess(self):
        for t in self.transitions:
            self._assess(t, sleep=False)
        for sl in self.sleeps:
            self._assess(sl, sleep=True)

    def _assess(self, it: dict, sleep: bool):
        d, w = it["drive"], round(self.s["drive_window_s"])
        pre, post = d["before"], d["after"]
        off, on = ("sleep", "wake") if sleep else ("power-off", "boot")
        quiet = ("healthy", "no data")

        def coverage_note(win):
            note = "" if win["storport_covered"] else " (no Storport log for this time - only System-log disk events checked)"
            return note + (f"; {win['info_count']} informational event(s)" if win["info_count"] else "")

        before, after, notes = [], [], []
        if pre is None:
            before.append("Sleep start not logged - the drive before it can't be checked" if sleep
                          else "The log has nothing before this boot")
        elif pre["state"] == "no data":
            before.append(f"No log covers the {w} s before {off}")
        elif pre["state"] not in quiet:
            last = pre["last_issue_s"]
            if last >= -0.5:
                when = "the last one right at sleep entry" if sleep else "a drive event was the last thing logged"
            else:
                when = f"the last one {abs(last):.0f} s before " + ("sleep" if sleep else "the last logged event")
            before.append(f"{w} s before {off}: {_counts_text(pre['counts'])} - {when}")
        else:
            before.append(f"No drive warnings or errors in the {w} s before {off}" + coverage_note(pre))

        if post is None:
            after.append("No wake logged - the session ended while asleep")
        elif post["state"] == "no data":
            after.append(f"No log covers the {w} s after {on}")
        elif post["state"] not in quiet:
            after.append(f"{w} s after {on}: {_counts_text(post['counts'])} - "
                         f"the first one {post['first_issue_s']:.0f} s after {on}")
        else:
            after.append(f"No drive warnings or errors in the {w} s after {on}" + coverage_note(post))

        typ = it["type"]
        if sleep:
            cause, cause_label = "n/a", "n/a"
        elif typ in ("shutdown", "restart"):
            cause, cause_label = "n/a", "No (orderly)"
            if pre and pre["state"] not in quiet:
                notes.append("The shutdown was orderly, so these drive problems did not cause it - "
                             "but check for failed writes or flushes")
        else:
            bc = it.get("bugcheck")
            bci = self._bugcheck_info(bc)
            ds = pre["drive_state"] if pre else None
            ps = pre["state"] if pre else None
            if bci:
                before.append(f"Crash code 0x{bc:X} ({bci[0]}) " +
                              ("points at storage" if bci[1] == "strong" else "is sometimes caused by storage"))
            if (bci and bci[1] == "strong") or ds in ("missing", "reset", "error"):
                cause = "likely"
            elif bci or ds in ("slow", "warning") or ps not in (None, "healthy", "no data"):
                cause = "possible"
            elif ps == "healthy":
                cause = "no_evidence"
            else:
                cause = "unknown"
            if pre and pre["platform_counts"] and ds in quiet:
                notes.append("Only platform (WHEA) hardware errors were logged - they may come from another device")
            if typ == "unknown":
                cause = {"likely": "possible", "no_evidence": "unknown"}.get(cause, cause)
                notes.append("How this session ended is undetermined, so the drive verdict is uncertain too")
            if cause == "no_evidence":
                notes.append("A quiet log does not clear the drive: Windows keeps its logs on the system drive, so if that "
                             "drive froze suddenly its last events may never have been saved - cross-check the drive's "
                             "own SMART and error logs")
            if cause in ("likely", "possible") and any(x in it["subtype"].lower() for x in ("hang", "long-press")):
                notes.append("Drive trouble right before a hang or forced power-off fits a drive that stopped responding")
            cause_label = CAUSE_LABELS[cause]

        if post is None or post["state"] == "no data":
            effect = "unknown"
        else:
            effect = {"missing": "missing", "reset": "errors", "error": "errors", "slow": "warnings",
                      "warning": "warnings"}.get(post["drive_state"], "none" if post["state"] == "healthy" else "warnings")
        d.update(cause=cause, cause_label=cause_label, effect=effect,
                 effect_label=EFFECT_LABELS[effect].format(on=on), reasons=before + after + notes)

    # ------------------------------------------------------------------ extra data-quality checks
    def quality(self):
        s = self.s
        tc = []
        for e in self.events:
            if e.signal != "TIME_CHANGE":
                continue
            new, old = _try_time(e.data.get("NewTime")), _try_time(e.data.get("OldTime"))
            if not (new and old):
                continue
            delta = (new - old).total_seconds()
            k = self._session_of(e.ts)
            near_boot = k >= 0 and e.ts - self.boot_ts[k] < 180
            if abs(delta) >= s["time_change_flag_s"] and not near_boot:
                tc.append({"time": iso(e.time), "idx": e.idx, "delta_s": round(delta),
                           "delta": ("+" if delta > 0 else "-") + _fmt_dur(abs(delta)),
                           "process": e.data.get("ProcessName", "")})
        self.integrity_out["time_changes"] = tc

        sleep_spans = [(sl["start_ts"] or sl["end_ts"], sl["end_ts"] or sl["start_ts"]) for sl in self.sleeps]
        ug = []
        for k, evs in self.session_events.items():
            for a, b in zip(evs, evs[1:]):
                if b.ts - a.ts >= s["unexplained_gap_s"]:
                    if any(x0 is not None and x0 <= b.ts and (x1 or x0) >= a.ts for x0, x1 in sleep_spans):
                        continue
                    ug.append({"start": iso(a.time), "end": iso(b.time), "duration": _fmt_dur(b.ts - a.ts),
                               "session": k, "idx": a.idx})
        self.integrity_out["unexplained_gaps"] = ug

    # ------------------------------------------------------------------ disk inventory
    def inventory(self):
        seen, out = set(), []
        keys = ("model", "serial", "revision", "firmware", "manufacturer", "bustype", "capacity", "location")
        for e in self.storage:
            if e.storage["label"] != "Disk inventory":
                continue
            d = {k: v for k, v in e.data.items() if any(x in k.lower() for x in keys) and v}
            sig = (d.get("Model"), d.get("SerialNumber"))
            if d and sig not in seen:
                seen.add(sig)
                d["first_seen"] = iso(e.time)
                out.append(d)
        self.disks = out

    # ------------------------------------------------------------------ run
    def run(self) -> dict:
        self.tag()
        self.integrity()
        self.find_boots()
        self.build_sessions()
        self.find_sleeps()
        self.classify()
        self.correlate()
        self.assess()
        self.quality()
        self.inventory()
        thr = self.s["review_threshold"]
        items = []
        for i, t in enumerate(self.transitions):
            t["id"] = f"T{i + 1}"
            t["needs_review"] = t["confidence"] < thr or any(f["severity"] == "warn" for f in t["flags"])
            items.append(t)
        for i, sl in enumerate(self.sleeps):
            sl["id"] = f"S{i + 1}"
            sl["needs_review"] = sl["confidence"] < thr or any(f["severity"] == "warn" for f in sl["flags"])
            items.append(sl)
        items.sort(key=lambda x: x["time_ts"] or 0)

        counts = Counter(t["type"] for t in self.transitions)
        sleep_kinds = Counter(sl["kind"] for sl in self.sleeps)
        hard_breakdown = Counter(t["subtype"] for t in self.transitions if t["type"] == "hard")
        computers = Counter(e.computer for e in self.events if e.computer)
        storage_counts = Counter(e.storage["label"] for e in self.storage if e.storage["state"] != "info")
        flags_total = sum(len(x["flags"]) for x in items)
        causes = Counter(t["drive"]["cause"] for t in self.transitions)
        effects = Counter(x["drive"]["effect"] for x in items)
        return {
            "wela_version": __version__,
            "generated": iso(datetime.now(timezone.utc)),
            "computer": computers.most_common(1)[0][0] if computers else "",
            "event_count": len(self.events),
            "coverage": {"start": iso(self.events[0].time) if self.events else None,
                         "end": iso(self.events[-1].time) if self.events else None,
                         "start_ts": self.events[0].ts if self.events else None,
                         "end_ts": self.events[-1].ts if self.events else None},
            "sources": self.sources,
            "channels": self.channels,
            "counts": {
                "shutdown": counts.get("shutdown", 0), "restart": counts.get("restart", 0),
                "hard": counts.get("hard", 0), "unknown": counts.get("unknown", 0),
                "sleep": sleep_kinds.get("sleep", 0), "hibernate": sleep_kinds.get("hibernate", 0),
                "modern_standby": sleep_kinds.get("modern_standby", 0),
                "boots": len(self.boots), "power_cycles": len(self.transitions),
                "needs_review": sum(1 for x in items if x["needs_review"]), "flags": flags_total,
                "drive_likely": causes.get("likely", 0), "drive_possible": causes.get("possible", 0),
                "drive_no_evidence": causes.get("no_evidence", 0), "drive_unknown": causes.get("unknown", 0),
                "drive_effect": effects.get("errors", 0) + effects.get("missing", 0),
            },
            "hard_breakdown": dict(hard_breakdown),
            "storage_counts": dict(storage_counts),
            "items": items,
            "sessions": self.sessions,
            "storage_events": [{"idx": e.idx, "time": iso(e.time), "provider": e.provider, "eid": e.eid,
                                "channel": e.channel, "label": e.storage["label"], "state": e.storage["state"],
                                "level": e.level} for e in self.storage if e.storage["state"] != "info"][:5000],
            "disks": self.disks,
            "integrity": self.integrity_out,
            "settings": self.s,
        }


def analyze(events: List[Event], cfg: dict = None, sources: List[dict] = None) -> dict:
    return Analyzer(events, cfg, sources).run()
