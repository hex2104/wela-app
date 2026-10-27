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
        # "what triggered it?" (software) - same 0..1 scale, capped at 1.0
        "software": {
            "initiator": 0.70,          # 1074 names the process that asked for the shutdown / restart
            "reason_agrees": 0.15,      # its reason code points the same way as the process
            "supporting_events": 0.15,  # e.g. Windows Update / installer events before it
            "restart_logged": 0.60,     # no 1074, but an installer / update / service logged that it restarts the PC
            "restart_pending": 0.35,    # no 1074, but an update or install was waiting for a restart
            "critical_crash": 0.50,     # a system process (csrss, lsass, ...) crashed before a hard shutdown
            "critical_bugcheck": 0.20,  # ... and the crash code is the one Windows uses for that
            "work_in_progress": 0.40,   # an update / install was still running when it went down
            "hang": 0.35,               # apps or services hung right before a hang / forced power-off
            "driver": 0.30,             # display driver stopped responding before it
            "crash": 0.25,              # an ordinary app crashed before it
            "drive_conflict": 0.15,     # drive also had problems: the software events may only be a symptom
        },
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
    # providers that describe the platform (CPU / PCIe / memory) rather than the drive itself:
    # on their own they can make "did the drive cause it?" a *possibly*, never a *likely*
    "platform_provider_hints": ["whea"],
    # crash (bugcheck) codes that point at storage: "strong" -> likely drive-related, "possible" -> possibly
    "storage_bugchecks": {
        "0x7A": ["KERNEL_DATA_INPAGE_ERROR", "strong"],
        "0x77": ["KERNEL_STACK_INPAGE_ERROR", "strong"],
        "0x7B": ["INACCESSIBLE_BOOT_DEVICE", "strong"],
        "0xED": ["UNMOUNTABLE_BOOT_VOLUME", "strong"],
        "0xF4": ["CRITICAL_OBJECT_TERMINATION", "strong"],
        "0x24": ["NTFS_FILE_SYSTEM", "possible"],
        "0x9F": ["DRIVER_POWER_STATE_FAILURE", "possible"],
        "0xEF": ["CRITICAL_PROCESS_DIED", "possible"],
        "0x133": ["DPC_WATCHDOG_VIOLATION", "possible"],
        "0x154": ["UNEXPECTED_STORE_EXCEPTION", "possible"],
    },

    # ---- which drive an event belongs to -------------------------------------
    # Vendor rules, first match wins:
    #   names   - regex searched in every value of the event (case-insensitive)
    #   pci     - PCI vendor IDs, matched as VEN_xxxx in device paths (e.g. WHEA PrimaryDeviceName)
    #   models  - regex on model / product fields only (part numbers without the vendor name)
    # Intel and AMD have no PCI ID here on purpose: their IDs also name the CPU's own PCIe root ports.
    "drive_vendors": [
        ["Samsung", {"names": [r"\bsamsung\b"], "pci": ["144D"], "models": [r"(?<![A-Za-z0-9])MZ[-_]?[0-9A-Z]{6,}"]}],
        ["Western Digital", {"names": [r"\bwdc\b", r"\bwestern digital\b", r"\bsandisk\b", r"\bwd[_ ](black|blue|green|red)\b"],
                             "pci": ["15B7", "1B96"], "models": []}],
        ["SK hynix", {"names": [r"\bsk ?hynix\b", r"\bhynix\b"], "pci": ["1C5C"], "models": [r"(?<![A-Za-z0-9])HF[SM][0-9]{3}"]}],
        ["Kioxia / Toshiba", {"names": [r"\bkioxia\b", r"\btoshiba\b"], "pci": ["1E0F", "1179"], "models": []}],
        ["Micron / Crucial", {"names": [r"\bmicron\b", r"\bcrucial\b"], "pci": ["1344"],
                              "models": [r"(?<![A-Za-z0-9])MTFD[A-Z0-9]{4,}"]}],
        ["Intel / Solidigm", {"names": [r"\bintel\b", r"\bsolidigm\b"], "pci": ["025E"], "models": []}],
        ["Seagate", {"names": [r"\bseagate\b"], "pci": ["1BB1"], "models": []}],
        ["Kingston", {"names": [r"\bkingston\b"], "pci": ["2646"], "models": []}],
        ["Phison", {"names": [r"\bphison\b"], "pci": ["1987"], "models": []}],
        ["Silicon Motion", {"names": [r"\bsilicon motion\b"], "pci": ["126F"], "models": []}],
        ["ADATA", {"names": [r"\badata\b"], "pci": ["1CC1"], "models": []}],
        ["Lite-On / SSSTC", {"names": [r"\blite-?on\b", r"\bssstc\b"], "pci": ["14A4"], "models": []}],
    ],
    # events on this vendor's drives are highlighted everywhere
    "highlight_vendor": "Samsung",

    # ---- software / application events: [provider, event id, label, group, kind]
    # group: app / update / install / service / system
    # kind:  crash, hang, report, done, start, end, fail, restart (waiting for a restart),
    #        reboot (restarts the PC itself), driver, memory, power
    # The engine refines some rows from their data: Windows Error Reporting 1001 by its event name
    # (BlueScreen, APPCRASH, AppHangB1 ...), a crash of a critical_processes entry, and 7031 whose
    # recovery action is "Restart the computer".
    "software_events": [
        ["Application Error", 1000, "Application crashed", "app", "crash"],
        ["Application Hang", 1002, "Application hung", "app", "hang"],
        [".NET Runtime", 1026, ".NET application crashed", "app", "crash"],
        ["Windows Error Reporting", 1001, "Error report", "app", "report"],
        ["Microsoft-Windows-WindowsUpdateClient", 19, "Update installed", "update", "done"],
        ["Microsoft-Windows-WindowsUpdateClient", 20, "Update failed to install", "update", "fail"],
        ["Microsoft-Windows-WindowsUpdateClient", 21, "Update needs a restart", "update", "restart"],
        ["Microsoft-Windows-WindowsUpdateClient", 22, "Update restart scheduled", "update", "reboot"],
        ["Microsoft-Windows-WindowsUpdateClient", 43, "Update installation started", "update", "start"],
        ["Microsoft-Windows-Servicing", 2, "Windows package installed", "update", "done"],
        ["Microsoft-Windows-Servicing", 4, "Windows package needs a restart", "update", "restart"],
        ["MsiInstaller", 1033, "Software installed", "install", "done"],
        ["MsiInstaller", 1034, "Software removed", "install", "done"],
        ["MsiInstaller", 1035, "Software reconfigured", "install", "done"],
        ["MsiInstaller", 1036, "Software update installed", "install", "done"],
        ["MsiInstaller", 1037, "Software update removed", "install", "done"],
        ["MsiInstaller", 11707, "Installation completed", "install", "done"],
        ["MsiInstaller", 11724, "Removal completed", "install", "done"],
        ["MsiInstaller", 11708, "Installation failed", "install", "fail"],
        ["MsiInstaller", 1038, "Installer needs a restart", "install", "restart"],
        ["MsiInstaller", 1005, "Installer restarted the PC", "install", "reboot"],
        ["MsiInstaller", 1040, "Installer transaction started", "install", "start"],
        ["MsiInstaller", 1042, "Installer transaction ended", "install", "end"],
        ["Service Control Manager", 7031, "Service crashed", "service", "crash"],
        ["Service Control Manager", 7034, "Service crashed", "service", "crash"],
        ["Service Control Manager", 7023, "Service stopped with an error", "service", "crash"],
        ["Service Control Manager", 7024, "Service stopped with an error", "service", "crash"],
        ["Service Control Manager", 7043, "Service held up shutdown", "service", "hang"],
        ["Service Control Manager", 7022, "Service hung on start", "service", "hang"],
        ["Service Control Manager", 7011, "Service timed out", "service", "hang"],
        ["Display", 4101, "Display driver stopped responding", "system", "driver"],
        ["Microsoft-Windows-Resource-Exhaustion-Detector", 2004, "Low on memory", "system", "memory"],
        ["Microsoft-Windows-Kernel-Power", 105, "Power source changed", "system", "power"],
    ],
    # a crash of one of these makes Windows crash (0xEF / 0xF4) or restart
    "critical_processes": ["csrss.exe", "wininit.exe", "winlogon.exe", "lsass.exe", "smss.exe", "services.exe"],
    "critical_bugchecks": ["0xEF", "0xF4"],
    # who asked for a shutdown / restart: substring of the 1074 process path (lower-case) -> category.
    # First match wins, so specific entries come before generic ones ("setuphost" before "setup").
    "shutdown_initiators": [
        ["trustedinstaller.exe", "update"], ["tiworker.exe", "update"], ["mousocoreworker.exe", "update"],
        ["usoclient.exe", "update"], ["wuauclt.exe", "update"], ["musnotification", "update"],
        ["setuphost.exe", "update"], ["sihclient.exe", "update"], ["windows10upgrade", "update"],
        ["updateassistant", "update"], ["\\$windows.~bt\\", "update"],
        ["\\dell\\", "vendor"], ["dcu-cli", "vendor"], ["supportassist", "vendor"], ["\\lenovo\\", "vendor"],
        ["thininstaller", "vendor"], ["\\hp\\", "vendor"], ["hpsa", "vendor"], ["magician", "vendor"],
        ["firmware", "vendor"], ["bios", "vendor"],
        ["ccmexec.exe", "management"], ["ccmrestart", "management"], ["omadmclient.exe", "management"],
        ["deviceenroller.exe", "management"], ["intunemanagementextension", "management"],
        ["agentexecutor.exe", "management"], ["gpscript.exe", "management"], ["wmiprvse.exe", "management"],
        ["msiexec.exe", "installer"], ["setup", "installer"], ["install", "installer"], ["uninst", "installer"],
        ["shutdown.exe", "script"], ["powershell.exe", "script"], ["pwsh.exe", "script"], ["cmd.exe", "script"],
        ["wscript.exe", "script"], ["cscript.exe", "script"],
        ["services.exe", "service"],
        ["wininit.exe", "system"], ["lsass.exe", "system"], ["csrss.exe", "system"],
        ["explorer.exe", "user"], ["runtimebroker.exe", "user"], ["startmenuexperiencehost.exe", "user"],
        ["shellexperiencehost.exe", "user"], ["shellhost.exe", "user"], ["winlogon.exe", "user"],
        ["logonui.exe", "user"],
    ],

    # ---- timing / thresholds (seconds) ---------------------------------------
    "settings": {
        "boot_cluster_s": 180,        # boot markers within this span = one boot
        "boot_window_s": 900,         # look for 41/6008/1001 this long after boot
        "tail_window_s": 1800,        # look for stop signals this long before last event
        "restart_gap_s": 300,         # stop -> boot gap below this = restart (when 1074 silent)
        "long_restart_gap_s": 1800,   # 1074 says restart but gap longer -> flag
        "drive_window_s": 60,         # drive window before power-off / sleep and after boot / wake
        "software_window_s": 900,     # app / update / service events this long before power-off / sleep
        "software_after_s": 600,      # ... and this long after boot / wake
        "running_lookback_s": 3600,   # an update / install started this recently and never finished = still running
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
