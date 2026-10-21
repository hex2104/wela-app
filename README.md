# WELA — Windows Event Log Analyzer

Rebuilds every **power cycle** (normal shutdown, restart, hard shutdown, sleep / hibernate / Modern Standby)
from a claim's Windows event logs, shows what the **SSD** was doing around each one, and flags anything uncertain.

- **No installs on Windows.** Pure Python standard library; `.evtx` is read with Windows' own `wevtutil`.
- **Runs locally.** The UI is served on `127.0.0.1` only. No internet, no data leaves the PC.
- **Explainable.** Every verdict lists the events behind it, the expected events that were *not* logged, and a confidence score.

## Run it

Needs Python 3.9+ (python.org installer, "Add to PATH").

```bash
python run_wela.py
```

Your browser opens at `http://127.0.0.1:8765`. Paste a folder or `.evtx` paths (or use **Browse**), then click **Analyze**.
Click **Try demo data** to see a synthetic case with every tricky scenario.

In **VS Code**: open this folder, then press **F5** and pick **WELA: start UI**. The Run menu also has a CLI launch and a test launch.

### Command line

```bash
python -m wela analyze "D:\Claims\DELL-123\Logs" --out report.html --tz 330
python -m wela analyze System.evtx Application.evtx --out report.xlsx
python -m unittest discover -s tests -v
```

### Getting the logs from a machine

```bat
wevtutil epl System System.evtx
wevtutil epl Application Application.evtx
wevtutil epl Microsoft-Windows-Storage-Storport/Operational Storport.evtx
wevtutil epl Microsoft-Windows-Partition/Diagnostic Partition.evtx   (optional: disk model / FW / serial)
```

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
5. **Drive correlation**: disk 7/11/51/153/157, stornvme/storahci 129, NTFS, volmgr, WHEA 17/18/19 and all
   Storport events within ±60 s of every transition. The drive is labelled *healthy / slow / reset / error / missing*.
6. **Confidence** is the sum of evidence weights, minus penalties for conflicts and log gaps.
   Anything below 0.6, or with a warning, is marked **Needs review**.
7. **SMART check** tab: enter the drive's Power Cycles / Unsafe Shutdowns delta to cross-check the OS logs against the SSD.

All event IDs, weights and thresholds live in `wela/catalog.py`. Override any of them with `wela_config.json`
next to `run_wela.py`, e.g.

```json
{ "settings": { "drive_window_s": 120, "restart_gap_s": 600 } }
```

## Project layout

```
run_wela.py            start the UI
wela/
  parser.py            .evtx (wevtutil / PowerShell / python-evtx) and .xml -> events
  catalog.py           event IDs, weights, thresholds  <- tune here
  engine.py            timeline, integrity, boots, sessions, classification, sleep, drive correlation
  report.py            HTML / Excel / CSV / JSON export (no dependencies)
  server.py            local HTTP server + API
  store.py             cases saved under ./cases
  demo.py              synthetic demo logs with expected verdicts
web/                   UI (vanilla HTML/CSS/JS, works offline)
tests/                 unittest suite (demo scenario + rule tests)
```

## Before relying on it

The event IDs are the standard Windows ones, but validate on your own data: run WELA on 20–30 closed claims with
known answers, and on lab machines where you trigger each power cycle type on purpose. Then tune `catalog.py`.
