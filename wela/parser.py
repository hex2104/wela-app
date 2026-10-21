"""Load event logs into normalised Event objects.

Supported inputs
  * .evtx  - on Windows via the built-in `wevtutil` (no install needed),
             falling back to PowerShell Get-WinEvent; on other OSes via the
             optional `python-evtx` package.
  * .xml   - events exported as XML (wevtutil qe ... /f:xml, or WELA demo logs).
A path may be a file or a folder (searched recursively).
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from typing import Iterable, List, Tuple

from .models import Event, parse_time

_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
SUPPORTED = (".evtx", ".xml")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _event_from_elem(ev: ET.Element, source: str) -> Event | None:
    system = None
    payload: dict = {}
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
                payload[key] = (d.text or "").strip()
        elif name == "UserData":
            for leaf in child.iter():
                if len(leaf) == 0 and leaf is not child:
                    txt = (leaf.text or "").strip()
                    if txt:
                        payload[_local(leaf.tag)] = txt
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
    return Event(time=t, channel=chan, provider=prov, eid=eid, rid=rid, level=level,
                 computer=comp, data=payload, source=os.path.basename(source))


def parse_xml_text(text: str, source: str) -> List[Event]:
    """Parse a blob of XML containing <Event> elements (with or without a root)."""
    text = _INVALID_XML.sub("", text)
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    if not re.match(r"\s*<Events[\s>]", text):
        text = "<Events>" + text + "</Events>"
    out: List[Event] = []
    for _, elem in ET.iterparse(io.StringIO(text), events=("end",)):
        if _local(elem.tag) == "Event":
            e = _event_from_elem(elem, source)
            if e:
                out.append(e)
            elem.clear()
    return out


def _decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        import locale
        return raw.decode(locale.getpreferredencoding(False) or "cp1252", errors="replace")


def _parse_evtx_wevtutil(path: str) -> List[Event]:
    exe = shutil.which("wevtutil")
    if not exe:
        raise RuntimeError("wevtutil not found")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run([exe, "qe", path, "/lf:true", "/f:xml", "/e:Events"],
                          capture_output=True, creationflags=flags)
    if proc.returncode != 0:
        raise RuntimeError(_decode(proc.stderr).strip() or f"wevtutil exit {proc.returncode}")
    return parse_xml_text(_decode(proc.stdout), path)


def _parse_evtx_powershell(path: str) -> List[Event]:
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        raise RuntimeError("PowerShell not found")
    p = path.replace("'", "''")
    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
              f"Get-WinEvent -Path '{p}' -Oldest -ErrorAction SilentlyContinue | "
              "ForEach-Object { $_.ToXml() }")
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
            e = _event_from_elem(elem, path)
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


def expand_paths(paths: Iterable[str]) -> List[str]:
    files: List[str] = []
    for p in paths:
        p = os.path.expanduser(p.strip().strip('"').strip("'"))
        if not p:
            continue
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in sorted(names):
                    if n.lower().endswith(SUPPORTED):
                        files.append(os.path.join(root, n))
        elif os.path.isfile(p):
            files.append(p)
        else:
            raise FileNotFoundError(f"Path not found: {p}")
    return files


def load(paths: Iterable[str]) -> Tuple[List[Event], List[dict]]:
    """Return (events, per-file source info)."""
    events: List[Event] = []
    sources: List[dict] = []
    for f in expand_paths(paths):
        info = {"file": os.path.basename(f), "path": f, "events": 0, "reader": None, "error": None}
        try:
            if f.lower().endswith(".xml"):
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    evs = parse_xml_text(fh.read(), f)
                info["reader"] = "xml"
            else:
                evs, info["reader"] = parse_evtx(f)
            info["events"] = len(evs)
            info["channels"] = sorted({e.channel for e in evs})
            events.extend(evs)
        except Exception as exc:
            info["error"] = str(exc)
        sources.append(info)
    return events, sources
