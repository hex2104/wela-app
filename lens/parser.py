"""Load event logs into normalised Event objects.

Supported inputs
  * .evtx  - on Windows via the built-in `wevtutil` (no install needed),
             falling back to PowerShell Get-WinEvent; on other OSes via the
             optional `python-evtx` package.
  * .xml   - events exported as XML (wevtutil qe ... /f:xml, Event Viewer's
             "Save as XML", or LENS demo logs).
On Windows each event also gets its message - the words Event Viewer shows on
the General tab - rendered by this PC's Windows; python-evtx cannot render them.
A path may be a file or a folder (searched recursively). From a folder only the
FOLDER_LOGS are read; a file given by itself is always read.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Iterable, Iterator, List, Tuple

from .models import Event, no_gc, parse_time

_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
MSG_MAX = 8000
SUPPORTED = (".evtx", ".xml")
# A claim folder - often a copy of C:\Windows\System32\winevt\Logs - holds hundreds of logs; only these are read
# from it. winevt\Logs names each file after its channel, with %4 for "/".
FOLDER_LOGS = ("System", "Application", "Microsoft-Windows-Storage-Storport/Operational",
               "Microsoft-Windows-Storage-Storport/Health")


_PIECE = 1 << 20                      # XML is read 1M characters at a time
_TAGS: dict = {}


def _local(tag: str) -> str:
    """'{namespace}EventData' -> 'EventData' (worked out once per tag name)."""
    name = _TAGS.get(tag)
    if name is None:
        name = _TAGS[tag] = sys.intern(tag.rsplit("}", 1)[-1])
    return name


def _message(text: str | None) -> str:
    """The General text, tidied: Windows line ends, trailing spaces and the invisible direction marks before times."""
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u200e", "").replace("\u200f", "")
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    return (re.sub(r"\n{3,}", "\n\n", s) if "\n\n\n" in s else s).strip()[:MSG_MAX]


def _event_from_elem(ev: ET.Element, source: str) -> Event | None:
    system = None
    payload: dict = {}
    msg = ""
    for child in ev:
        name = _local(child.tag)
        if name == "System":
            system = child
        elif name == "EventData":
            n = 0
            for d in child:
                if _local(d.tag) != "Data":
                    continue
                key = d.get("Name")
                if not key:
                    n += 1
                    key = f"param{n}"
                payload[sys.intern(key)] = (d.text or "").strip()
        elif name == "UserData":
            for leaf in child.iter():
                if len(leaf) == 0 and leaf is not child:
                    txt = (leaf.text or "").strip()
                    if txt:
                        payload[_local(leaf.tag)] = txt
        elif name == "RenderingInfo":     # RenderedXml / Event Viewer's "Save as XML": the message in words
            m = next((r for r in child if _local(r.tag) == "Message"), None)
            msg = _message(m.text if m is not None else "")
    if system is None:
        return None
    prov, eid, rid, level, chan, comp, t = "", 0, None, 4, "", "", None
    for s in system:
        name = _local(s.tag)
        if name == "Provider":
            prov = s.get("Name") or s.get("EventSourceName") or ""
        elif name == "EventID":
            try:
                eid = int((s.text or "0").strip()) & 0xFFFF
            except ValueError:
                eid = 0
        elif name == "EventRecordID":
            try:
                rid = int((s.text or "").strip())
            except ValueError:
                rid = None
        elif name == "Level":
            try:
                level = int((s.text or "4").strip())
            except ValueError:
                level = 4
        elif name == "Channel":
            chan = (s.text or "").strip()
        elif name == "Computer":
            comp = (s.text or "").strip()
        elif name == "TimeCreated":
            st = s.get("SystemTime")
            if st:
                try:
                    t = parse_time(st)
                except ValueError:
                    t = None
    if t is None:
        return None
    # the same few names in every event: one copy of each instead of one per event
    return Event(time=t, channel=sys.intern(chan), provider=sys.intern(prov), eid=eid, rid=rid, level=level,
                 computer=sys.intern(comp), data=payload, msg=msg, source=source)


def parse_xml_text(text: str, source: str, partial: bool = False) -> List[Event]:
    """Parse a blob of XML containing <Event> elements (with or without a root).
    partial: the text may stop part way - keep the events read up to there."""
    return _parse_pieces((text[i:i + _PIECE] for i in range(0, len(text), _PIECE)), source, partial)


def parse_xml_file(path: str) -> List[Event]:
    """Parse an XML log file a piece at a time: the whole file is never in memory."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        return _parse_pieces(iter(lambda: fh.read(_PIECE), ""), path)


def _parse_pieces(pieces: Iterator[str], source: str, partial: bool = False) -> List[Event]:
    """Events from XML text that arrives in pieces. No copy of the whole text is made, and each event's elements
    are dropped as soon as it is read, so memory holds the events, not the XML."""
    source = os.path.basename(source)
    p = ET.XMLPullParser(events=("end",))
    out: List[Event] = []
    first, wrapped = True, False
    try:
        for s in pieces:
            s = _INVALID_XML.sub("", s)
            if first:
                s = re.sub(r"^\s*<\?xml[^>]*\?>", "", s.lstrip("\ufeff"))
                wrapped = not re.match(r"\s*<Events[\s>]", s)    # wevtutil without /e, several roots: give them one
                if wrapped:
                    p.feed("<Events>")
                first = False
            p.feed(s)
            _take(p, out, source)
        if first:                                                    # no text at all: no events
            p.feed("<Events>")
            wrapped = True
        if wrapped:
            p.feed("</Events>")
        p.close()
        _take(p, out, source)
    except ET.ParseError:
        if not partial:
            raise
    return out


def _take(p: ET.XMLPullParser, out: List[Event], source: str) -> None:
    for _, elem in p.read_events():
        if _local(elem.tag) == "Event":
            e = _event_from_elem(elem, source)
            if e:
                out.append(e)
            elem.clear()


def _decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        import locale
        return raw.decode(locale.getpreferredencoding(False) or "cp1252", errors="replace")


def _wevtutil(exe: str, path: str, fmt: str) -> Tuple[str, str]:
    """(output, error) of wevtutil qe; error is "" when it read the whole log."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run([exe, "qe", path, "/lf:true", f"/f:{fmt}", "/e:Events"],
                          capture_output=True, creationflags=flags)
    err = "" if proc.returncode == 0 else _decode(proc.stderr).strip() or f"wevtutil exit {proc.returncode}"
    return _decode(proc.stdout), err


def _parse_evtx_wevtutil(path: str) -> List[Event]:
    exe = shutil.which("wevtutil")
    if not exe:
        raise RuntimeError("wevtutil not found")
    # RenderedXml adds each event's message, worded by this PC's Windows (empty for a provider it does not have)
    text, err = _wevtutil(exe, path, "RenderedXml")
    if not err:
        return parse_xml_text(text, path)
    # it stopped part way (a provider whose messages Windows could not load): read every event, keep the words it got
    raw, err = _wevtutil(exe, path, "xml")
    if err:
        raise RuntimeError(err)
    events = parse_xml_text(raw, path)
    words = {e.rid: e.msg for e in parse_xml_text(text, path, partial=True) if e.msg and e.rid is not None}
    for e in events:
        e.msg = words.get(e.rid, "")
    return events


def _parse_evtx_powershell(path: str) -> List[Event]:
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        raise RuntimeError("PowerShell not found")
    p = path.replace("'", "''")
    # each event's XML with its message added the way RenderedXml carries it
    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
              f"Get-WinEvent -Path '{p}' -Oldest -ErrorAction SilentlyContinue | "
              "ForEach-Object { $x = $_.ToXml(); $m = $null; try { $m = $_.Message } catch { }; "
              "if ($m) { $x = $x.Substring(0, $x.LastIndexOf('</Event>')) + '<RenderingInfo><Message>' + "
              "[Security.SecurityElement]::Escape($m) + '</Message></RenderingInfo></Event>' }; $x }")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, creationflags=flags)
    if proc.returncode != 0 and not proc.stdout:
        raise RuntimeError(_decode(proc.stderr).strip() or "PowerShell failed")
    return parse_xml_text(_decode(proc.stdout), path)


def _parse_evtx_python(path: str) -> List[Event]:
    try:
        import Evtx.Evtx as evtx  # optional: pip install python-evtx
    except ImportError as exc:
        raise RuntimeError("Reading .evtx outside Windows needs the optional "
                           "package python-evtx (pip install python-evtx)") from exc
    out: List[Event] = []
    with evtx.Evtx(path) as log:
        for rec in log.records():
            try:
                elem = ET.fromstring(_INVALID_XML.sub("", rec.xml()))
            except Exception:
                continue
            e = _event_from_elem(elem, os.path.basename(path))
            if e:
                out.append(e)
    return out


def parse_evtx(path: str) -> Tuple[List[Event], str]:
    errors = []
    readers = []
    if os.name == "nt":
        readers += [("wevtutil", _parse_evtx_wevtutil), ("powershell", _parse_evtx_powershell)]
    readers.append(("python-evtx", _parse_evtx_python))
    for name, fn in readers:
        try:
            return fn(path), name
        except Exception as exc:  # try the next reader
            errors.append(f"{name}: {exc}")
    raise RuntimeError("; ".join(errors))


def folder_log(name: str) -> bool:
    """Is this file in a folder one of the FOLDER_LOGS? Judged by its name, as exported or as in winevt\\Logs."""
    s = os.path.splitext(os.path.basename(name))[0].lower()
    if "%4" in s:                         # named after its channel: Microsoft-Windows-Storage-Storport%4Health
        return s.replace("%4", "/") in {c.lower() for c in FOLDER_LOGS}
    if "storport" in s:                   # exported under a name of its own: Storport.evtx, Storport-Health.evtx
        return True
    if s.startswith("microsoft-"):        # another log named after its channel
        return False
    return bool(re.search(r"(?<![a-z])(system|application)", s))   # System.evtx, PC01_Application.evtx


def expand_paths(paths: Iterable[str]) -> Tuple[List[str], List[str]]:
    """Return (files to read, files skipped in folders because they are not FOLDER_LOGS)."""
    files: List[str] = []
    skipped: List[str] = []
    for p in paths:
        p = os.path.expanduser(p.strip().strip('"').strip("'"))
        if not p:
            continue
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in sorted(names):
                    if n.lower().endswith(SUPPORTED):
                        (files if folder_log(n) else skipped).append(os.path.join(root, n))
        elif os.path.isfile(p):
            files.append(p)
        else:
            raise FileNotFoundError(f"Path not found: {p}")
    return files, skipped


def load(paths: Iterable[str]) -> Tuple[List[Event], List[dict], List[str]]:
    """Return (events, per-file source info, files skipped in folders)."""
    with no_gc():
        return _load(paths)


def _load(paths: Iterable[str]) -> Tuple[List[Event], List[dict], List[str]]:
    events: List[Event] = []
    sources: List[dict] = []
    files, skipped = expand_paths(paths)
    for f in files:
        info = {"file": os.path.basename(f), "path": f, "events": 0, "reader": None, "error": None}
        try:
            if f.lower().endswith(".xml"):
                evs = parse_xml_file(f)
                info["reader"] = "xml"
            else:
                evs, info["reader"] = parse_evtx(f)
            info["events"] = len(evs)
            info["messages"] = sum(1 for e in evs if e.msg)
            info["channels"] = sorted({e.channel for e in evs})
            events.extend(evs)
        except Exception as exc:
            info["error"] = str(exc)
        sources.append(info)
    return events, sources, skipped
