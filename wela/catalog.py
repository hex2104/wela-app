"""Event catalogue and tunable settings.

Everything the engine "knows" about Windows events lives here, so rules can be
reviewed and tuned by the team without touching the engine logic. Any key can
be overridden by a `wela_config.json` file next to run_wela.py (same shape).
"""
from __future__ import annotations

import copy
import json
import os

DEFAULTS = {
    # ---- power signals: name -> list of [provider, event id] -----------------
    "signals": {
        "BOOT_OS_START":     [["Microsoft-Windows-Kernel-General", 12]],
        "BOOT_LOG_START":    [["EventLog", 6005]],
        "BOOT_OS_VERSION":   [["EventLog", 6009]],
        "BOOT_TYPE":         [["Microsoft-Windows-Kernel-Boot", 27]],
        "SHUTDOWN_REQUEST":  [["User32", 1074]],
        "OS_STOP":           [["Microsoft-Windows-Kernel-General", 13]],
        "LOG_STOP":          [["EventLog", 6006]],
        "KP_SHUTDOWN_INIT":  [["Microsoft-Windows-Kernel-Power", 109]],
        "USER_LOGOFF":       [["Microsoft-Windows-Winlogon", 7002]],
        "KP_UNEXPECTED":     [["Microsoft-Windows-Kernel-Power", 41]],
        "UNEXPECTED_PREV":   [["EventLog", 6008]],
        "BUGCHECK":          [["Microsoft-Windows-WER-SystemErrorReporting", 1001],
                              ["BugCheck", 1001]],
        "SLEEP_ENTER":       [["Microsoft-Windows-Kernel-Power", 42]],
        "SLEEP_RESUME":      [["Microsoft-Windows-Kernel-Power", 107]],
        "SLEEP_REPORT":      [["Microsoft-Windows-Power-Troubleshooter", 1]],
        "MS_ENTER":          [["Microsoft-Windows-Kernel-Power", 506]],
        "MS_EXIT":           [["Microsoft-Windows-Kernel-Power", 507]],
        "UPTIME":            [["EventLog", 6013]],
        "TIME_CHANGE":       [["Microsoft-Windows-Kernel-General", 1]],
        "LOG_CLEARED":       [["Microsoft-Windows-Eventlog", 104],
                              ["Microsoft-Windows-Eventlog", 1102]],
    },
    "signal_labels": {
        "BOOT_OS_START": "OS started (Kernel-General 12)",
        "BOOT_LOG_START": "Event log started (6005)",
        "BOOT_OS_VERSION": "OS version at boot (6009)",
        "BOOT_TYPE": "Boot type (Kernel-Boot 27)",
        "SHUTDOWN_REQUEST": "Shutdown requested (User32 1074)",
        "OS_STOP": "OS stopped (Kernel-General 13)",
        "LOG_STOP": "Event log stopped (6006)",
        "KP_SHUTDOWN_INIT": "Kernel shutdown initiated (Kernel-Power 109)",
        "USER_LOGOFF": "User logoff (Winlogon 7002)",
        "KP_UNEXPECTED": "Unclean shutdown reported (Kernel-Power 41)",
        "UNEXPECTED_PREV": "Previous shutdown unexpected (6008)",
        "BUGCHECK": "Bugcheck / crash (1001)",
        "SLEEP_ENTER": "Entering sleep (Kernel-Power 42)",
        "SLEEP_RESUME": "Resumed from sleep (Kernel-Power 107)",
        "SLEEP_REPORT": "Sleep/wake report (Power-Troubleshooter 1)",
        "MS_ENTER": "Modern Standby enter (Kernel-Power 506)",
        "MS_EXIT": "Modern Standby exit (Kernel-Power 507)",
        "UPTIME": "Uptime heartbeat (6013)",
        "TIME_CHANGE": "System time changed (Kernel-General 1)",
        "LOG_CLEARED": "Log cleared (104/1102)",
    },

    # ---- evidence weights (sum is capped at 1.0) -----------------------------
    "weights": {
        "clean": {"SHUTDOWN_REQUEST": 0.35, "OS_STOP": 0.30, "LOG_STOP": 0.30,
                  "KP_SHUTDOWN_INIT": 0.20, "USER_LOGOFF": 0.05},
        "hard": {"KP_UNEXPECTED": 0.50, "UNEXPECTED_PREV": 0.40, "BUGCHECK": 0.20},
        "silent_end": 0.30,          # session ends with no stop signal at all
        "explicit_type_bonus": 0.10,  # 1074 states restart / power off
        "conflict_penalty": 0.25,
        "integrity_penalty": 0.30,
    },

    # ---- storage events: [provider (case-insensitive), event id or "*", label, state]
    # state precedence: missing > reset > error > slow > warning > info
    "storage_events": [
        ["disk", 7, "Bad block", "error"],
        ["disk", 11, "Controller error", "error"],
        ["disk", 51, "Paging I/O error", "error"],
        ["disk", 52, "Predicted failure (SMART)", "error"],
        ["disk", 153, "I/O retried", "slow"],
        ["disk", 154, "I/O failed (hardware error)", "error"],
        ["disk", 157, "Disk surprise removed", "missing"],
        ["stornvme", 11, "NVMe controller error", "error"],
        ["stornvme", 129, "Reset to device", "reset"],
        ["storahci", 129, "Reset to device", "reset"],
        ["iaStorAC", 129, "Reset to device (Intel RST)", "reset"],
        ["iaStorA", 129, "Reset to device (Intel RST)", "reset"],
        ["iaStorVD", 129, "Reset to device (Intel VMD)", "reset"],
        ["Microsoft-Windows-Ntfs", 55, "File system corruption", "error"],
        ["Ntfs", 55, "File system corruption", "error"],
        ["Microsoft-Windows-Ntfs", 98, "Volume needs repair", "error"],
        ["Microsoft-Windows-Ntfs", 140, "Failed to flush log", "error"],
        ["Microsoft-Windows-Ntfs", 50, "Delayed write failed", "error"],
        ["volmgr", 161, "Dump file creation failed", "error"],
        ["volmgr", 46, "Crash dump init failed", "warning"],
        ["Microsoft-Windows-WHEA-Logger", 17, "Corrected PCIe error", "warning"],
        ["Microsoft-Windows-WHEA-Logger", 18, "Fatal hardware error", "error"],
        ["Microsoft-Windows-WHEA-Logger", 19, "Corrected hardware error", "warning"],
        ["Microsoft-Windows-WHEA-Logger", 47, "Corrected memory error", "warning"],
        ["Microsoft-Windows-WHEA-Logger", 1, "WHEA hardware error", "error"],
        ["Microsoft-Windows-Partition", 1006, "Disk inventory", "info"],
        ["Microsoft-Windows-StorPort", "*", "Storport event", "auto"],
    ],
    # any other provider whose name contains one of these is treated as storage
    "storage_provider_hints": ["stornvme", "storahci", "storport", "nvme", "iastor", "disk"],

    # ---- timing / thresholds (seconds) ---------------------------------------
    "settings": {
        "boot_cluster_s": 180,        # boot markers within this span = one boot
        "boot_window_s": 900,         # look for 41/6008/1001 this long after boot
        "tail_window_s": 1800,        # look for stop signals this long before last event
        "restart_gap_s": 300,         # stop -> boot gap below this = restart (when 1074 silent)
        "long_restart_gap_s": 1800,   # 1074 says restart but gap longer -> flag
        "drive_window_s": 60,         # storage correlation window around transitions
        "pt1_merge_s": 300,           # Power-Troubleshooter 1 merges into a nearby resume
        "unexplained_gap_s": 7200,    # quiet gap inside a session worth flagging
        "time_change_flag_s": 300,    # clock jump bigger than this is flagged
        "review_threshold": 0.6,      # confidence below this -> needs review
    },

    # localised words found in 1074 "shutdown type" (param5)
    "restart_words": ["restart", "reboot", "neustart", "neu starten", "redémarr", "redemarr",
                      "reinici", "riavvi", "herstart", "reinicia", "再起動", "重新启动", "重新啟動",
                      "다시 시작", "перезагруз"],
    "poweroff_words": ["power off", "poweroff", "shutdown", "shut down", "herunterfahren",
                       "ausschalten", "arrêt", "arret", "apagar", "apagado", "spegni", "uitschakelen",
                       "シャットダウン", "关机", "關機", "종료", "выключ", "завершение"],
    "expected_channels": {
        "System": "system",
        "Application": "application",
        "Storport": "storport",
    },
}


def load_config(path: str | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if path is None:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, "wela_config.json")
    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as fh:
            user = json.load(fh)
        _merge(cfg, user)
    return cfg


def _merge(base: dict, over: dict) -> None:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
