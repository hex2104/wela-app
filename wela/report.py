"""Exports: self-contained HTML report, Excel (.xlsx, no dependencies), CSV, JSON."""
from __future__ import annotations

import csv
import html
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

TYPE_LABEL = {"shutdown": "Normal shutdown", "restart": "Restart", "hard": "Hard shutdown",
              "unknown": "Undetermined", "sleep": "Sleep / resume"}


def _fmt(ts_iso, offset_min=0):
    if not ts_iso:
        return ""
    t = datetime.strptime(ts_iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return (t + timedelta(minutes=offset_min)).strftime("%Y-%m-%d %H:%M:%S")


def _tz_label(offset_min):
    if not offset_min:
        return "UTC"
    sign = "+" if offset_min > 0 else "-"
    m = abs(offset_min)
    return f"UTC{sign}{m // 60:02d}:{m % 60:02d}"


def _hv(result: dict) -> str:
    return result.get("highlight_vendor") or "Samsung"


def _hl_text(hl: str, hv: str) -> str:
    """Per-event drive attribution as a filterable cell value."""
    return {"yes": hv, "probably": f"probably {hv}", "no": "other drive"}.get(hl, "not identified")


def _sw_verdict(sw: dict) -> str:
    conf = sw.get("confidence")
    return (sw.get("strength_label") or "") + (f" ({round(conf * 100)}%)" if conf is not None else "")


def rows(result: dict, offset_min: int = 0):
    out, hv = [], _hv(result)
    for it in result["items"]:
        drv, sw = it.get("drive", {}), it.get("software") or {}
        init = sw.get("initiator") or {}
        out.append({
            "ID": it["id"],
            f"Time ({_tz_label(offset_min)})": _fmt(it.get("time"), offset_min),
            "Type": TYPE_LABEL.get(it["type"], it["type"]),
            "Detail": it.get("subtype") or "",
            "Confidence": it["confidence"],
            "Needs review": "yes" if it.get("needs_review") else "",
            "Drive state": drv.get("state", ""),
            "Drive caused it?": drv.get("cause_label", ""),
            f"{hv} drive?": drv.get("highlight_label", ""),
            "Effect on drive": drv.get("effect_label", ""),
            "Storage events": "; ".join(f"{k} x{v}" for d in (drv.get("before"), drv.get("after"))
                                        if d for k, v in d.get("counts", {}).items()),
            "Drive reasons": "; ".join(drv.get("reasons", [])),
            "Software trigger": sw.get("label", ""),
            "Software verdict": _sw_verdict(sw),
            "Requested by": " - ".join(x for x in (init.get("process"), init.get("reason"), init.get("reason_code")) if x),
            "Software reasons": "; ".join(sw.get("reasons", [])),
            "Off / gap": it.get("gap") or it.get("duration") or "",
            "Boot type": it.get("boot_type") or "",
            "Wake source": it.get("wake_source") or "",
            "Evidence found": "; ".join(f"{e['eid']} {e['label']}" for e in it.get("evidence_found", [])),
            "Evidence missing": "; ".join(it.get("evidence_missing", [])),
            "Flags": "; ".join(f["text"] for f in it.get("flags", [])),
        })
    return out


def drive_rows(result: dict, offset_min: int = 0):
    """One row per storage event in the before / after window of every power cycle and sleep."""
    hv = _hv(result)
    hdr = ["ID", "Type", "Detail", "Drive caused it?", "Window", "Offset (s)", f"Time ({_tz_label(offset_min)})",
           "Provider", "Event ID", "Meaning", "State", f"{hv}?", "Drive", "How identified", "Log", "Fields"]
    out = [hdr]
    for it in result["items"]:
        drv = it.get("drive", {})
        sleep = it["type"] == "sleep"
        for side, label in (("before", "before sleep" if sleep else "before power-off"),
                            ("after", "after wake" if sleep else "after boot")):
            w = drv.get(side)
            if not w:
                continue
            head = [it["id"], TYPE_LABEL.get(it["type"], it["type"]), it.get("subtype") or "",
                    drv.get("cause_label", ""), label]
            if not w["events"]:
                out.append(head + ["", "", "", "", "(no drive events in this window)", w["state"], "", "", "", "", ""])
            for e in w["events"]:
                out.append(head + [e.get("offset_s", ""), _fmt(e["time"], offset_min), e["provider"], e["eid"],
                                   e["label"], e["state"], _hl_text(e.get("hl", ""), hv), e.get("dev", ""),
                                   e.get("dev_basis", ""), e.get("channel", ""), e.get("fields", "")])
    return out


def software_rows(result: dict, offset_min: int = 0):
    """One row per app / update / service event in the before / after window of every power cycle and sleep."""
    hdr = ["ID", "Type", "Detail", "Software trigger", "Window", "Offset (s)", f"Time ({_tz_label(offset_min)})",
           "Provider", "Event ID", "What", "App / update / service", "Details", "Severity", "Log"]
    out = [hdr]
    for it in result["items"]:
        sw = it.get("software") or {}
        sleep = it["type"] == "sleep"
        for side, label in (("before", "before sleep" if sleep else "before power-off"),
                            ("after", "after wake" if sleep else "after boot")):
            w = sw.get(side)
            if not w:
                continue
            head = [it["id"], TYPE_LABEL.get(it["type"], it["type"]), it.get("subtype") or "", sw.get("label", ""), label]
            if not w["events"]:
                out.append(head + ["", "", "", "", "(no app, update or service events in this window)", "", "", "", ""])
            for e in w["events"]:
                out.append(head + [e.get("offset_s", ""), _fmt(e["time"], offset_min), e["provider"], e["eid"],
                                   e["label"], e.get("subject", ""), e.get("detail", ""), e.get("state", ""),
                                   e.get("channel", "")])
    return out


def to_json(result: dict) -> bytes:
    return json.dumps(result, indent=2, ensure_ascii=False).encode("utf-8")


def to_csv(result: dict, offset_min: int = 0) -> bytes:
    data = rows(result, offset_min)
    buf = io.StringIO()
    if data:
        w = csv.DictWriter(buf, fieldnames=list(data[0].keys()))
        w.writeheader()
        w.writerows(data)
    return ("﻿" + buf.getvalue()).encode("utf-8")


# ----------------------------------------------------------------- minimal XLSX writer
def _col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _sheet_xml(table, widths, fill=None):
    """fill: row -> bool; rows it accepts get the highlight fill (the highlighted vendor's drive)."""
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
           "<cols>"]
    for i, w in enumerate(widths, 1):
        out.append(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>')
    out.append("</cols><sheetData>")
    for r, row in enumerate(table, 1):
        out.append(f'<row r="{r}">')
        filled = r > 1 and fill is not None and fill(row)
        for c, v in enumerate(row, 1):
            ref = f"{_col(c)}{r}"
            style = ' s="1"' if r == 1 else ' s="2"' if filled else ""
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(f'<c r="{ref}"{style}><v>{v}</v></c>')
            else:
                out.append(f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{escape(str(v or ""))}</t></is></c>')
        out.append("</row>")
    out.append("</sheetData>")
    if len(table) > 1:
        out.append(f'<autoFilter ref="A1:{_col(len(table[0]))}{len(table)}"/>')
    out.append("</worksheet>")
    return "".join(out)


def to_xlsx(result: dict, offset_min: int = 0) -> bytes:
    data = rows(result, offset_min)
    hv = _hv(result)
    hl_cells = (hv, f"probably {hv}")

    def hl_problem(state_col, who_col):   # a warning / error on the highlighted vendor's drive
        return lambda row: row[who_col] in hl_cells and row[state_col] not in ("info", "healthy", "no data")

    sheets = []   # (name, table, widths, which rows get the highlight fill)
    if data:
        hdr = list(data[0].keys())
        col = hdr.index(f"{hv} drive?")
        sheets.append(("Power cycles", [hdr] + [[r[h] for h in hdr] for r in data],
                       [6, 20, 16, 34, 11, 12, 12, 16, 22, 22, 34, 70, 22, 18, 40, 70, 12, 26, 14, 60, 50, 60],
                       lambda row: row[col] in (f"{hv} drive", f"Probably the {hv} drive")))
        sheets.append(("Drive windows", drive_rows(result, offset_min),
                       [6, 16, 30, 14, 16, 10, 20, 28, 9, 26, 10, 16, 30, 34, 36, 70], hl_problem(10, 11)))
        sheets.append(("Software windows", software_rows(result, offset_min),
                       [6, 16, 30, 22, 16, 10, 20, 34, 9, 30, 44, 40, 10, 16], None))
    c = result["counts"]
    summary = [["Metric", "Value"], ["Computer", result.get("computer", "")],
               ["Coverage start (UTC)", _fmt(result["coverage"]["start"])],
               ["Coverage end (UTC)", _fmt(result["coverage"]["end"])],
               ["Events analysed", result["event_count"]],
               ["Normal shutdowns", c["shutdown"]], ["Restarts", c["restart"]],
               ["Hard shutdowns", c["hard"]], ["Undetermined", c["unknown"]],
               ["Sleep (S3)", c["sleep"]], ["Hibernate", c["hibernate"]],
               ["Modern Standby", c["modern_standby"]], ["Needs review", c["needs_review"]],
               ["Drive caused it - likely", c.get("drive_likely", "")],
               ["Drive caused it - possibly", c.get("drive_possible", "")],
               ["Drive caused it - no drive evidence", c.get("drive_no_evidence", "")],
               ["Drive caused it - can't tell", c.get("drive_unknown", "")],
               ["Drive errors right after boot / wake", c.get("drive_effect", "")],
               [f"Power cycles with {hv} drive problems", c.get("hl_cycles", "")],
               [f"Drive suspected and it is the {hv} drive", c.get("hl_suspect", "")],
               [f"{hv} drive warning / error events", c.get("hl_events", "")],
               ["Power cycles triggered by software (not the user)", c.get("software", "")]]
    for k, v in result.get("hard_breakdown", {}).items():
        summary.append([f"Hard shutdown - {k}", v])
    labels = result.get("trigger_labels", {})
    for k, v in sorted(result.get("software_breakdown", {}).items(), key=lambda kv: -kv[1]):
        summary.append([f"Triggered by - {labels.get(k, k)}", v])
    sheets.insert(0, ("Summary", summary, [44, 30], None))
    st = [["Time (UTC)", "Provider", "Event ID", "Meaning", "State", f"{hv}?", "Drive", "How identified", "Channel"]] + [
        [_fmt(e["time"]), e["provider"], e["eid"], e["label"], e["state"], _hl_text(e.get("hl", ""), hv),
         e.get("dev", ""), e.get("dev_basis", ""), e["channel"]] for e in result.get("storage_events", [])]
    sheets.append(("Storage events", st, [20, 34, 9, 30, 10, 16, 30, 34, 44], hl_problem(4, 5)))
    se = [["Time (UTC)", "Provider", "Event ID", "What", "App / update / service", "Details", "Severity", "Channel"]] + [
        [_fmt(e["time"]), e["provider"], e["eid"], e["label"], e.get("subject", ""), e.get("detail", ""), e.get("state", ""),
         e["channel"]] for e in result.get("software_events", [])]
    sheets.append(("Software events", se, [20, 34, 9, 30, 44, 40, 10, 30], None))
    ch = [["Channel", "Events", "From (UTC)", "To (UTC)"]] + [
        [x["channel"], x["events"], _fmt(x["start"]), _fmt(x["end"])] for x in result["channels"]]
    sheets.append(("Coverage", ch, [48, 10, 20, 20], None))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(sheets) + 1)) + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(s[0])}" sheetId="{i}" r:id="rId{i}"/>' for i, s in enumerate(sheets, 1))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   "</Relationships>")
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
                   '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>'
                   '<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
                   '<fill><patternFill patternType="solid"><fgColor rgb="FF1428A0"/></patternFill></fill>'
                   '<fill><patternFill patternType="solid"><fgColor rgb="FFD3EFF3"/></patternFill></fill></fills>'
                   '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
                   '<cellXfs count="3"><xf/><xf fontId="1" fillId="2" applyFont="1" applyFill="1"/>'
                   '<xf fillId="3" applyFill="1"/></cellXfs>'
                   "</styleSheet>")
        for i, (_, table, widths, fill) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(table, widths, fill))
    return buf.getvalue()


# ----------------------------------------------------------------- HTML report
CSS = """
:root{--ink:#1b2130;--muted:#5d6577;--line:#e3e6ee;--bg:#f6f7fb;--card:#fff;--navy:#1428a0;
--ok:#16865a;--warn:#b7791f;--bad:#c0392b;--purple:#6b4fbb;--grey:#7a8194}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 "Segoe UI",system-ui,sans-serif;color:var(--ink);background:var(--bg)}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px}h1{margin:0;color:var(--navy);font-size:24px}
.sub{color:var(--muted);margin:4px 0 20px}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;border-top:4px solid var(--c)}
.tile b{display:block;font-size:28px;line-height:1.1}.tile span{color:var(--muted);font-size:12.5px}
h2{font-size:16px;margin:26px 0 10px}table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th{background:var(--navy);color:#fff;text-align:left;font-weight:600;font-size:12.5px;padding:8px 10px}
td{padding:7px 10px;border-top:1px solid var(--line);vertical-align:top;font-size:13px}tr:nth-child(even) td{background:#fafbfe}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;color:#fff;font-size:11.5px;font-weight:600;white-space:nowrap}
.shutdown{background:var(--ok)}.restart{background:var(--navy)}.hard{background:var(--bad)}.unknown{background:var(--grey)}.sleep{background:var(--purple)}
.healthy{background:var(--ok)}.slow,.warning{background:var(--warn)}.reset,.error,.missing{background:var(--bad)}.nodata,.info{background:var(--grey)}
.small{color:var(--muted);font-size:12px}.flag{color:var(--warn)}
:root{--sam:#0a7f8f;--sam-soft:#d3eff3}.samchip{background:var(--sam)}.samp{background:#fff;color:var(--sam);box-shadow:inset 0 0 0 1px var(--sam)}
tr.sam td{background:var(--sam-soft)!important}tr.sam td:first-child{box-shadow:inset 4px 0 0 var(--sam)}
.legend{font-size:12px;color:var(--muted);margin:-4px 0 8px}
"""


def to_html(result: dict, offset_min: int = 0) -> bytes:
    e = html.escape
    c = result["counts"]
    tz = _tz_label(offset_min)
    tiles = [("Normal shutdowns", c["shutdown"], "var(--ok)"), ("Restarts", c["restart"], "var(--navy)"),
             ("Hard shutdowns", c["hard"], "var(--bad)"),
             ("Sleep / hibernate", c["sleep"] + c["hibernate"] + c["modern_standby"], "var(--purple)"),
             ("Undetermined", c["unknown"], "var(--grey)"), ("Needs review", c["needs_review"], "var(--warn)")]
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>WELA report - {e(result.get('computer') or 'case')}</title><style>{CSS}</style></head><body><div class='wrap'>",
             f"<h1>WELA power-cycle report</h1><div class='sub'>{e(result.get('computer') or '')} &middot; "
             f"{_fmt(result['coverage']['start'], offset_min)} to {_fmt(result['coverage']['end'], offset_min)} ({tz}) &middot; "
             f"{result['event_count']:,} events &middot; generated {_fmt(result['generated'], offset_min)}</div><div class='tiles'>"]
    for label, val, col in tiles:
        parts.append(f"<div class='tile' style='--c:{col}'><b>{val}</b><span>{label}</span></div>")
    parts.append("</div>")
    if result.get("hard_breakdown"):
        parts.append("<h2>Hard shutdown breakdown</h2><table><tr><th>Cause</th><th>Count</th></tr>")
        for k, v in result["hard_breakdown"].items():
            parts.append(f"<tr><td>{e(k)}</td><td>{v}</td></tr>")
        parts.append("</table>")
    hv = _hv(result)
    parts.append(f"<h2>Power cycles &amp; sleep episodes</h2><table><tr><th>ID</th><th>Time ({tz})</th><th>Type</th>"
                 "<th>Detail</th><th>Conf.</th><th>Drive</th><th>Software trigger</th><th>Evidence</th><th>Flags</th></tr>")
    for it in result["items"]:
        drv, sw = it.get("drive", {}), it.get("software") or {}
        ds = drv.get("state", "")
        counts = "; ".join(f"{k} x{v}" for d in (drv.get("before"), drv.get("after")) if d
                           for k, v in d.get("counts", {}).items())
        ev = "<br>".join(f"{x['eid']} {e(x['label'])}" for x in it["evidence_found"])
        miss = "<br>".join(f"missing: {e(x)}" for x in it["evidence_missing"])
        fl = "<br>".join(f"<span class='flag'>{e(f['text'])}</span>" for f in it["flags"])
        cause = drv.get("cause_label", "")
        verdict = " &middot; ".join(x for x in [
            f"caused it? <b>{e(cause)}</b>" if cause and it["type"] != "sleep" else "",
            e(drv.get("effect_label", ""))] if x)
        hl = drv.get("highlight")
        sam = (f"<span class='chip {'samchip' if hl == 'yes' else 'samp'}'>{e(drv.get('highlight_label', ''))}</span>"
               if hl in ("yes", "probably") else "")
        swc = (f"<b>{e(sw.get('label', ''))}</b><div class='small'>{e(_sw_verdict(sw))}</div>"
               if sw and it["type"] != "sleep" else "")
        tr = "<tr class='sam'>" if sam else "<tr>"
        parts.append(f"{tr}<td>{it['id']}</td><td>{_fmt(it.get('time'), offset_min)}</td>"
                     f"<td><span class='chip {it['type']}'>{TYPE_LABEL.get(it['type'], it['type'])}</span></td>"
                     f"<td>{e(it.get('subtype') or '')}<div class='small'>{e(it.get('gap') or it.get('duration') or '')}</div></td>"
                     f"<td>{int(it['confidence'] * 100)}%</td>"
                     f"<td><span class='chip {ds.replace(' ', '')}'>{e(ds)}</span> {sam}<div class='small'>{verdict}</div>"
                     f"<div class='small'>{e(counts)}</div></td><td>{swc}</td>"
                     f"<td class='small'>{ev}<br>{miss}</td><td class='small'>{fl}</td></tr>")
    parts.append("</table>")
    win_rows = drive_rows(result, offset_min)[1:]
    if win_rows:
        parts.append(f"<h2>Drive around each power cycle</h2><div class='legend'>Highlighted rows: warnings and errors on the "
                     f"{e(hv)} drive (outlined badge = probably: the event names no drive, but it is the only one seen)</div>"
                     f"<table><tr><th>ID</th><th>Caused it?</th><th>Window</th><th>Offset</th><th>Time ({tz})</th>"
                     f"<th>Event</th><th>State</th><th>Drive</th><th>Fields</th></tr>")
        for idv, _, _, cause, window, off, t, prov, eid, label, state, who, dev, basis, _, fields in win_rows:
            ev_txt = f"{eid} {e(label)} <span class='small'>&middot; {e(prov)}</span>" if eid != "" else e(label)
            hit = who in (hv, f"probably {hv}")
            badge = f"<span class='chip {'samchip' if who == hv else 'samp'}'>{e(who)}</span> " if hit else ""
            drive = f"{badge}{e(dev or ('' if hit or eid == '' else who))}<div class='small'>{e(basis)}</div>" if eid != "" else ""
            tr = "<tr class='sam'>" if hit and state != "info" else "<tr>"   # only problems get the row tint
            parts.append(f"{tr}<td>{idv}</td><td>{e(cause)}</td><td>{e(window)}</td>"
                         f"<td>{f'{off:+.0f} s' if isinstance(off, (int, float)) else ''}</td><td>{t}</td><td>{ev_txt}</td>"
                         f"<td><span class='chip {state.replace(' ', '')}'>{e(state)}</span></td>"
                         f"<td>{drive}</td><td class='small'>{e(fields)}</td></tr>")
        parts.append("</table>")
    sw_rows = [r for r in software_rows(result, offset_min)[1:] if r[8] != ""]
    sw_items = [it for it in result["items"] if it["type"] != "sleep" and it.get("software")]
    if sw_items:
        parts.append("<h2>Software around each power cycle</h2><table><tr><th>ID</th><th>Type</th><th>What triggered it?</th>"
                     "<th>Verdict</th><th>Why</th></tr>")
        for it in sw_items:
            sw = it["software"]
            parts.append(f"<tr><td>{it['id']}</td><td><span class='chip {it['type']}'>{TYPE_LABEL.get(it['type'], it['type'])}"
                         f"</span></td><td><b>{e(sw.get('label', ''))}</b></td><td>{e(_sw_verdict(sw))}</td>"
                         f"<td class='small'>{'<br>'.join(e(x) for x in sw.get('reasons', []))}</td></tr>")
        parts.append("</table>")
    if sw_rows:
        parts.append(f"<h2>App, update and service events around each power cycle</h2><table><tr><th>ID</th><th>Window</th>"
                     f"<th>Offset</th><th>Time ({tz})</th><th>Event</th><th>App / update / service</th><th>Severity</th></tr>")
        for idv, _, _, _, window, off, t, prov, eid, label, subject, detail, sev, _ in sw_rows:
            parts.append(f"<tr><td>{idv}</td><td>{e(window)}</td>"
                         f"<td>{f'{off:+.0f} s' if isinstance(off, (int, float)) else ''}</td><td>{t}</td>"
                         f"<td>{eid} {e(label)} <span class='small'>&middot; {e(prov)}</span></td>"
                         f"<td>{e(subject)}<div class='small'>{e(detail)}</div></td>"
                         f"<td><span class='chip {e(sev)}'>{e(sev)}</span></td></tr>")
        parts.append("</table>")
    parts.append("<h2>Log coverage</h2><table><tr><th>Channel</th><th>Events</th><th>From</th><th>To</th></tr>")
    for ch in result["channels"]:
        parts.append(f"<tr><td>{e(ch['channel'])}</td><td>{ch['events']:,}</td><td>{_fmt(ch['start'], offset_min)}</td>"
                     f"<td>{_fmt(ch['end'], offset_min)}</td></tr>")
    parts.append("</table>")
    integ = result["integrity"]
    notes = []
    if integ["missing_channels"]:
        notes.append("Missing logs: " + ", ".join(integ["missing_channels"]))
    for g in integ["record_gaps"]:
        notes.append(f"{g['channel']}: {g['missing']} records missing between {_fmt(g['start'], offset_min)} and {_fmt(g['end'], offset_min)}")
    for x in integ["clears"]:
        notes.append(f"Log cleared at {_fmt(x['time'], offset_min)}")
    for x in integ["time_changes"]:
        notes.append(f"System clock changed by {x['delta']} at {_fmt(x['time'], offset_min)}")
    if notes:
        parts.append("<h2>Data quality</h2><table>" + "".join(f"<tr><td>{e(n)}</td></tr>" for n in notes) + "</table>")
    parts.append("<p class='small'>Generated by WELA. Verdicts are rule-based; check items marked for review.</p></div></body></html>")
    return "".join(parts).encode("utf-8")
