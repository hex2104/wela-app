# LENS — Log Event Navigation System

Rebuilds every **power cycle** (normal shutdown, restart, hard shutdown, sleep / hibernate / Modern Standby)
from a claim's Windows event logs, shows what the **SSD** was doing around each one — and **which drive** it was,
with **Samsung** drives highlighted — finds the **app crash, update, installer or service failure** that triggered it,
and flags anything uncertain.

- **No installs on Windows.** Pure Python standard library; `.evtx` is read with Windows' own `wevtutil`.
- **Runs locally.** The UI is served on `127.0.0.1` only. No internet, no data leaves the PC.
- **Explainable.** Every verdict lists the events behind it, the expected events that were *not* logged, and a confidence score.

## Run it

Needs Python 3.9+ (python.org installer, "Add to PATH").

```bash
python run_lens.py
```

Your browser opens at `http://127.0.0.1:8765`. Paste a folder or `.evtx` paths (or use **Browse**), then click **Analyze**.
From a folder (e.g. a copy of `C:\Windows\System32\winevt\Logs`) LENS reads only **System**, **Application** and
**Storport** (Operational and Health) and skips every other log; a file you add by itself is always read.
Click **Try demo data** to see a synthetic case with every tricky scenario.

In **VS Code**: open this folder, then press **F5** and pick **LENS: start UI**. The Run menu also has a CLI launch and a test launch.

### Command line

```bash
python -m lens analyze "D:\Claims\DELL-123\Logs" --out report.html --tz 330
python -m lens analyze System.evtx Application.evtx --out report.xlsx
python -m lens analyze System.evtx --out report.xlsx --names   # keep people's account names (hidden by default)
python -m unittest discover -s tests -v
```

### Getting the logs from a machine

```bat
wevtutil epl System System.evtx
wevtutil epl Application Application.evtx
wevtutil epl Microsoft-Windows-Storage-Storport/Operational Storport.evtx
wevtutil epl Microsoft-Windows-Storage-Storport/Health Storport-Health.evtx
wevtutil epl Microsoft-Windows-Partition/Diagnostic Partition.evtx   (optional: disk model / FW / serial, ties disk events to a drive)
wevtutil epl Setup Setup.evtx                                         (optional: Windows servicing "needs a restart" events)
```

Partition and Setup are not read from a folder: add them as files of their own.

## How power cycles are identified

1. **Merge** all logs into one UTC timeline. Check coverage per log, gaps in record IDs, cleared logs and clock changes.
2. **Find boots**: Kernel-General 12, EventLog 6005/6009 and Kernel-Boot 27 within 3 minutes count as one boot.
   Everything between two boots is one *boot session*.
3. **For every boot, decide how the previous session ended**:

| Evidence | Verdict |
|---|---|
| 1074 / 109 / 13 / 6006 near the end of the session | Clean stop → **restart** (1074 says restart, or boot follows quickly) or **shutdown** |
| Kernel-Boot 27 BootType=1 on next boot | Shutdown was **Fast Startup** (kernel hibernated) |
| 41 and/or 6008 after the boot (+1001) | **Hard shutdown**. Event 41 fields give the cause: `BugcheckCode`≠0 → crash, `PowerButtonTimestamp`≠0 → long-press, `SleepInProgress`≠0 → power lost while asleep, otherwise power loss / hang |
| Stop started (1074) but then 41 | Shutdown **hung** and did not complete |
| No stop events, no 41/6008 | **Inferred** hard shutdown, low confidence, flagged |
| Record gap at the boundary / log starts at the boot | **Undetermined** — not guessed |

4. **Sleep** inside a session: 42 → 107 → Power-Troubleshooter 1. Any one of them is enough to rebuild the episode,
   because PT‑1 carries both sleep and wake time. Modern Standby uses 506/507. Hibernate resume uses 27 BootType=2.
5. **Drive around every power cycle**: every storage event — all Storport events at every level, disk
   7/11/51/153/157, stornvme/storahci 129, NTFS, volmgr and WHEA — in the 60 s before power-off (or sleep) and the
   60 s after boot (or wake), each with its offset and key fields (SCSI opcodes decoded). The drive is labelled
   *healthy / slow / reset / error / missing*; Information events are the drive's **normal activity** — listed, drawn as
   thin green ticks on the timeline's drive lanes and kept in the Drive tab (*Show: Normal activity*), but they don't
   change the label. NTFS 98 logged as Information ("Volume C: is healthy", at every boot) is normal activity; logged
   as an error it is "volume needs repair".
6. **Did the drive cause it?** For hard shutdowns and undetermined power cycles: **Likely** (drive reset, error or
   surprise removal before power-off, or a storage crash code such as 0x7A), **Possibly** (slow I/O or warnings,
   WHEA-only errors, or a crash code such as 0x9F), **No drive evidence** (drive quiet before power-off) or
   **Can't tell** (no log). **Effect on the drive** describes the minute after boot or wake. Each verdict lists its
   reasons, and the Excel export has a *Drive windows* sheet with every event from both windows of every power cycle.
   *No drive evidence* is not proof the drive is fine: Windows keeps its logs on the system drive, so a drive that
   froze suddenly may never have saved its last events. Cross-check the drive's own SMART and error logs.
7. **Which drive?** Every storage event is tied to a physical drive, and the basis is shown next to it:

   | Basis | How | Shown as |
   |---|---|---|
   | Named in the event | Storport `VendorId` / `ProductId` / `SerialNumber`, Partition `Model`, a PCI ID such as `VEN_144D` (WHEA), or a Samsung `MZ…` part number | **Samsung** (solid) |
   | Disk number | the event names `\Device\HarddiskN`, and the Partition/Diagnostic 1006 inventory *of that boot* says which drive was disk N (numbers can change between boots) | **Samsung** (solid) |
   | Only drive | the event names no drive (e.g. `stornvme 129` on `RaidPort0`), but only one drive is in that boot — or in the logs — and the event does not point at another disk number | **Samsung?** (outlined, "probably") |
   | Not identified | two or more drives and nothing names one, or a WHEA event naming e.g. an Intel root port | no badge |

   WHEA events are never guessed — their PCIe device may be a Wi-Fi card or the GPU. The same drive seen as
   `SAMSUNG MZVL2512` (Storport, 16 characters) and `SAMSUNG MZVL2512HCJQ-00B00` (Partition) is merged, also when one log
   reports the serial and the other the NVMe EUI-64. Samsung warning / error events are highlighted in teal in the UI,
   the HTML report and the Excel workbook. Change `highlight_vendor` in `catalog.py` to highlight another vendor.
8. **What triggered it?** (software) For every power cycle, the 15 min before power-off and the 10 min after boot:

   | Evidence | Verdict |
   |---|---|
   | User32 1074 names the process that asked | **Confirmed** — Windows Update (TrustedInstaller, MoUsoCoreWorker …), software installer (msiexec …), OEM / vendor tool (Dell Command Update, Samsung Magician …), IT management (SCCM, Intune), script (shutdown.exe, PowerShell), system process crash (wininit, *"lsass.exe terminated unexpectedly"*) or user request (Start menu). The 1074 **reason code** is decoded too — it is the same in every Windows language, so "Update and restart" from the Start menu counts as Windows Update. The account the request ran under is shown with its kind — a user account, or Windows itself (SYSTEM), a service or the computer's own account; the logs do not say whether an account is an administrator |
   | No 1074, but MsiInstaller 1005, Windows Update 22 or a 7031 service crash whose recovery action restarts the PC | **Likely** |
   | No 1074, but an update / install was waiting for a restart (WU 21, MSI 1038, Servicing 4) | **Possibly** (restarts only) |
   | Hard shutdown after a system process crash (csrss, lsass …), likely if the crash code is 0xEF / 0xF4 | **Likely / Possibly** |
   | Hard shutdown while an update (WU 43) or install (MSI 1040) was still running | **Possibly** |
   | Hard shutdown right after apps or services hung (1002, 7043, 7011), a display driver timeout (4101) or an app crash (1000) | **Possibly** |
   | Application and System logs cover the window, nothing found | **No software evidence** |

   If the drive *also* logged problems right before, the software verdict says so and loses confidence: a stalling drive
   makes apps hang and crash, so those may be a symptom rather than the cause. Each verdict has its own confidence
   (weights in `catalog.py` under `weights.software`) and lists every event behind it.

   The verdict reads only those minutes, but the lists next to it run from the **previous power cycle to this one** (since
   its boot / wake) and from **this one to the next** (until its power-off / sleep), so a cause that started hours
   earlier is still there; one power cycle's "after" list is the next one's "before" list. Each list opens at the end
   nearest the power cycle with the 100 nearest events (`software_list_max`); **Show … earlier / later events** loads
   the rest. Problems older than the verdict window are summed up as *"Earlier, since T4 boot: …"*. The verdict never
   reads past the list: if the power cycle before is less than 15 min away, it reads only the time since that boot /
   wake (*"… in the 30s since T33 boot"*), so a crash before T33 is not blamed on T34.
9. **Confidence** is the sum of evidence weights, minus penalties for conflicts and log gaps.
   Anything below 0.6, or with a warning, is marked **Needs review**.
10. **Search**: the Power cycles, Drive and Apps & updates tabs and the detail panel have a search box. A number finds
    exactly those event IDs (`41`, or `41, 6008`); anything else is a text search. In the detail panel it searches
    the whole stretch, not only the events loaded. The **Near** column shows the time since the power cycle before
    an event and to the one after it; click either to open it.
11. **The timeline line**: drag the black line on the Timeline (or click anywhere, or step with ← → — Shift steps a
    power cycle) and the System, Application and Storport events within ± 5 s (1–60 s to choose) are listed under it,
    each with its offset from the line and its log time to the millisecond. **Range** (or Shift-drag on the timeline)
    gives a start and an end line instead: every event between them is listed, 200 more each time a list is scrolled
    to its end, and ← → move the range by its own length. The browser loads every event's time and log once per case
    (`/api/cases/<id>/index`), so the lines move with no round trip; what each event says comes from
    `/api/cases/<id>/rows` 256 at a time (`?ids=` for the ones a range lists) and is kept.
12. **What each event says**: on Windows every event is read with its message — the text Event Viewer shows on the
    *General* tab (`wevtutil /f:RenderedXml`, worded by the analysing PC's Windows; Event Viewer's *Save as XML* exports
    carry it too). The timeline rows show its first line, a click opens all of it above the event's fields, and
    search finds words in it. A provider that PC does not have, and python-evtx outside Windows, give no message; the
    Data quality tab counts the events read with one per file.
13. **What each event ID means**: click any event ID — in the timeline's lists, the detail panel, the Drive and Apps &
    updates tables — for what it means, what LENS uses it for, how often the case logged it (first and last, a click
    shows it on the timeline) and the message Windows wrote for it. The **References** tab lists them by log (System,
    Application, Storport): the IDs in this case first — errors, then warnings, then the most frequent — then the other
    known ones, with a search (an ID or words). Storport's *miniport* events (516–534, 567–571 — "The miniport logged an
    event") are the storage driver's own; LENS shows what the driver said (`MiniportEventDescription`), counted. A storage
    event with no rule of its own is named by its meaning (Storport 549 *First I/O error in a period*), not "Storport
    event 549". The meanings — about 230 lines, worded from the providers' own message texts — are in
    `lens/reference.py`; a `"references"` list in `lens_config.json` adds IDs or replaces lines (same shape).

All event IDs, weights, vendor rules and thresholds live in `lens/catalog.py`. Override any of them with `lens_config.json`
next to `run_lens.py`, e.g.

```json
{ "settings": { "drive_window_s": 120, "restart_gap_s": 600, "software_window_s": 1800 } }
```

## Big cases

Logs are read a piece at a time, and a saved case keeps its events in compressed blocks of 256 with a small index
(`events.jsonl.gz` stays one ordinary gzip file): an open case holds only those, and each request decodes just the
blocks it needs. On 268,066 events (204 MB of XML), on a laptop: reading 7.0 → 4.5 s with peak memory 1.5 GB → 330 MB;
saving 2.5 → 1.6 s; opening a saved case 1.0 s → 0.1 s, holding 727 MB → 7 MB. The analysis step grows in step with the
log: 203,600 events (6,400 power cycles) in 1.7 s (was 5.1 s). A case saved by an earlier version is rewritten in the
new layout the first time it is opened.

## Project layout

```
run_lens.py            start the UI
lens/
  parser.py            .evtx (wevtutil / PowerShell / python-evtx) and .xml -> events with their messages;
                       which logs a folder gives
  catalog.py           event IDs, weights, thresholds, drive vendors, software events  <- tune here
  reference.py         what each event ID means (References tab, a click on an ID)
  engine.py            timeline, integrity, boots, sessions, classification, sleep, drive identity +
                       correlation, software trigger
  report.py            HTML / Excel / CSV / JSON export (no dependencies)
  server.py            local HTTP server + API
  store.py             cases saved under ./cases: events in compressed blocks + index, read a block at a time
  demo.py              synthetic demo logs with expected verdicts
web/                   UI (vanilla HTML/CSS/JS, works offline)
tests/                 unittest suite (demo scenario, rule tests, random-input robustness test)
docs/                  team walkthrough (.pptx / .pdf) and LENS-technical-reference.pdf (how every
                       verdict is made, demo script, limitations, roadmap, AI integration);
                       src/ holds its HTML source and screenshots (print command at the top)
```

## Before relying on it

The event IDs are the standard Windows ones, but validate on your own data: run LENS on 20–30 closed claims with
known answers, and on lab machines where you trigger each power cycle type on purpose. Then tune `catalog.py`.
In particular, check on real claims that the Storport events name the drive (open one in the drawer — the Drive line
says how it was identified), and trigger a Windows Update restart, an installer restart and a forced power-off
during an app hang on a lab machine to see the software verdicts.
