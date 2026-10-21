"""Synthetic demo logs (wevtutil-style XML) covering the tricky cases.

Every scenario below is something WELA has to get right; the expected verdict
is listed so tests can check it. Times are UTC. All data is fictitious.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

NS = "http://schemas.microsoft.com/win/2004/08/events/event"
HOST = "DEMO-LAPTOP-01"
SYS = "System"
APP = "Application"
STP = "Microsoft-Windows-Storage-Storport/Operational"
PART = "Microsoft-Windows-Partition/Diagnostic"

# (id, expected type, expected subtype contains)  - used by tests
EXPECTED_TRANSITIONS = [
    ("T1", "unknown", "Previous session not in log"),
    ("T2", "shutdown", "Full shutdown"),
    ("T3", "restart", "Restart"),
    ("T4", "shutdown", "Fast Startup"),
    ("T5", "hard", "Power loss"),
    ("T6", "shutdown", "Full shutdown"),          # 6006 missing, still clean
    ("T7", "hard", "Crash"),
    ("T8", "hard", "long-press"),
    ("T9", "hard", "during sleep"),
    ("T10", "hard", "Inferred"),
    ("T11", "unknown", "Log gap"),
    ("T12", "shutdown", "Full shutdown"),
    ("T13", "restart", "Restart"),                # no 1074, inferred from gap
    ("T14", "shutdown", "Full shutdown"),
]


def _t(day: int, hhmm: str, sec: int = 0) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=day - 1, hours=h, minutes=m, seconds=sec)


def _ts(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond:06d}0Z"


class Log:
    def __init__(self):
        self.ev = []                       # (time, seq, channel, provider, id, level, data, qualifiers)
        self.skips = []
        self.rid = {SYS: 5000, APP: 12000, STP: 300, PART: 40}

    def add(self, t, prov, eid, level=4, data=None, chan=SYS, qualifiers=None):
        self.ev.append((t, len(self.ev), chan, prov, eid, level, data, qualifiers))

    @staticmethod
    def _xml(t, rid, chan, prov, eid, level, data, qualifiers):
        if isinstance(data, dict):
            body = "".join(f'<Data Name="{k}">{escape(str(v))}</Data>' for k, v in data.items())
        elif isinstance(data, list):
            body = "".join(f"<Data>{escape(str(v))}</Data>" for v in data)
        else:
            body = ""
        q = f' Qualifiers="{qualifiers}"' if qualifiers is not None else ""
        return (f'<Event xmlns="{NS}"><System><Provider Name="{prov}"/>'
                f"<EventID{q}>{eid}</EventID><Version>0</Version><Level>{level}</Level>"
                f'<Task>0</Task><Opcode>0</Opcode><Keywords>0x8000000000000000</Keywords>'
                f'<TimeCreated SystemTime="{_ts(t)}"/><EventRecordID>{rid}</EventRecordID>'
                f'<Correlation/><Execution ProcessID="4" ThreadID="8"/><Channel>{chan}</Channel>'
                f"<Computer>{HOST}</Computer><Security/></System><EventData>{body}</EventData></Event>")

    def skip(self, chan, n, at):
        """Drop n record IDs just before time `at` (simulates lost records)."""
        self.skips.append((chan, n, at))

    # --- building blocks --------------------------------------------------
    def boot(self, t, boot_type=0, app=True, inventory=True):
        self.add(t, "Microsoft-Windows-Kernel-General", 12, data={"StartTime": _ts(t - timedelta(seconds=8))})
        self.add(t + timedelta(seconds=1), "Microsoft-Windows-Kernel-Boot", 27, data={"BootType": boot_type, "LoadOptions": ""})
        self.add(t + timedelta(seconds=14), "EventLog", 6009, data=["10.00.", "22631", "", "Multiprocessor Free", "0"], qualifiers=32768)
        self.add(t + timedelta(seconds=14), "EventLog", 6005, data=[], qualifiers=32768)
        if inventory:
            self.add(t + timedelta(seconds=3), "Microsoft-Windows-Partition", 1006, chan=PART, data={
                "Manufacturer": "DEMO", "Model": "DEMO NVMe SSD 1TB", "Revision": "FW1.0-DEMO",
                "SerialNumber": "DEMO-SN-0001", "BusType": "17", "Capacity": "1024209543168"})

    def clean_stop(self, t, kind="power off", with_6006=True, with_1074=True, reason="Other (Unplanned)",
                   process="C:\\Windows\\System32\\RuntimeBroker.exe (DEMO-LAPTOP-01)"):
        self.add(t - timedelta(seconds=20), "Microsoft-Windows-Winlogon", 7002, data={"TSId": "1", "UserSid": "S-1-5-21-DEMO"})
        if with_1074:
            self.add(t - timedelta(seconds=18), "User32", 1074, qualifiers=32768, data={
                "param1": process, "param2": HOST, "param3": reason, "param4": "0x0",
                "param5": kind, "param6": "", "param7": "DEMO\\engineer"})
        self.add(t - timedelta(seconds=4), "Microsoft-Windows-Kernel-Power", 109, data={
            "ShutdownActionType": "5", "ShutdownEventCode": "0", "ShutdownReason": "1"})
        self.add(t - timedelta(seconds=2), "Microsoft-Windows-Kernel-General", 13, data={"StopTime": _ts(t)})
        if with_6006:
            self.add(t, "EventLog", 6006, data=[], qualifiers=32768)

    def k41(self, t, bugcheck=0, power_button=0, sleep=0):
        self.add(t, "Microsoft-Windows-Kernel-Power", 41, level=1, data={
            "BugcheckCode": bugcheck, "BugcheckParameter1": "0x0", "BugcheckParameter2": "0x0",
            "BugcheckParameter3": "0x0", "BugcheckParameter4": "0x0", "SleepInProgress": sleep,
            "PowerButtonTimestamp": power_button, "BootAppStatus": "0", "Checkpoint": "0",
            "ConnectedStandbyInProgress": "false", "SystemSleepTransitionsToOn": "0"})

    def e6008(self, t, prev):
        self.add(t, "EventLog", 6008, level=2, qualifiers=32768,
                 data=[prev.strftime("%H:%M:%S"), prev.strftime("%d-%m-%Y"), "", "", "1234", "", ""])

    def sleep(self, t_sleep, t_wake, enter=True, resume=True, report=True, target=4, wake="Power Button"):
        if enter:
            self.add(t_sleep, "Microsoft-Windows-Kernel-Power", 42, data={"TargetState": target, "EffectiveState": target,
                                                                         "Reason": "7", "Flags": "0"})
        if resume:
            self.add(t_wake, "Microsoft-Windows-Kernel-Power", 107, data={})
        if report:
            self.add(t_wake + timedelta(seconds=12), "Microsoft-Windows-Power-Troubleshooter", 1, data={
                "SleepTime": _ts(t_sleep), "WakeTime": _ts(t_wake), "TargetState": target,
                "WakeSourceType": "5", "WakeSourceText": wake})

    def filler(self, t0, t1, every_min=20):
        t = t0 + timedelta(minutes=3)
        n = 0
        while t < t1 - timedelta(minutes=1):
            self.add(t, "Service Control Manager", 7036, qualifiers=16384,
                     data={"param1": "Background Intelligent Transfer Service", "param2": "running"})
            if n % 3 == 0 and t.day >= 2:
                self.add(t + timedelta(seconds=30), "Microsoft-Windows-Security-SPP", 16384, chan=APP,
                         data={"param1": "2026-09-30T00:00:00Z", "param2": "RulesEngine"})
            if t >= _t(3, "00:00") and n % 3 == 1:
                self.add(t + timedelta(seconds=5), "Microsoft-Windows-StorPort", 505, chan=STP,
                         data={"Port": "0", "Bus": "0", "Target": "0", "LUN": "0", "ClassDeviceGuid": "{DEMO}"})
            t += timedelta(minutes=every_min)
            n += 1

    def drive_trouble(self, t, resets=2, retries=5, storport_warn=3):
        for i in range(retries):
            self.add(t + timedelta(seconds=4 * i), "disk", 153, level=3, qualifiers=32772,
                     data=["\\Device\\Harddisk0\\DR0", "0x1A2B3C00", "0", "", "", ""])
        for i in range(resets):
            self.add(t + timedelta(seconds=10 + 15 * i), "stornvme", 129, level=3, qualifiers=32772,
                     data=["\\Device\\RaidPort0", ""])
        if t >= _t(3, "00:00"):
            for i in range(storport_warn):
                self.add(t + timedelta(seconds=2 + 9 * i), "Microsoft-Windows-StorPort", 549, level=3, chan=STP,
                         data={"Port": "0", "Bus": "0", "Target": "0", "LUN": "0", "Opcode": "42"})

    def write(self, folder):
        os.makedirs(folder, exist_ok=True)
        files = {SYS: "System.xml", APP: "Application.xml", STP: "Storport-Operational.xml", PART: "Partition-Diagnostic.xml"}
        for chan, name in files.items():
            rows = sorted((e for e in self.ev if e[2] == chan), key=lambda e: (e[0], e[1]))
            pending = sorted((x for x in self.skips if x[0] == chan), key=lambda x: x[2])
            rid = self.rid[chan]
            with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
                fh.write("<Events>\n")
                for e in rows:
                    while pending and pending[0][2] <= e[0]:
                        rid += pending.pop(0)[1]
                    rid += 1
                    fh.write(self._xml(e[0], rid, *e[2:]) + "\n")
                fh.write("</Events>\n")
        return [os.path.join(folder, n) for n in files.values()]


def build(folder: str) -> list:
    L = Log()
    # Log starts with a boot (previous session not recorded)                 -> T1 unknown
    L.boot(_t(1, "09:00"))
    L.filler(_t(1, "09:00"), _t(1, "18:30"))
    L.add(_t(1, "12:00"), "EventLog", 6013, qualifiers=32768, data=["", "", "", "", "10800", "60", "India Standard Time"])
    L.clean_stop(_t(1, "18:30"))                                            # -> T2 full shutdown
    L.boot(_t(2, "08:55"))
    L.filler(_t(2, "08:55"), _t(2, "12:30"))
    L.sleep(_t(2, "12:30"), _t(2, "13:15"))                                 # S: full evidence
    L.filler(_t(2, "13:15"), _t(2, "17:00"))
    L.clean_stop(_t(2, "17:00"), kind="restart", reason="Operating System: Upgrade (Planned)",
                 process="C:\\Windows\\servicing\\TrustedInstaller.exe (DEMO-LAPTOP-01)")
    L.boot(_t(2, "17:01", 25))                                              # -> T3 restart
    L.filler(_t(2, "17:01"), _t(2, "20:00"))
    L.clean_stop(_t(2, "20:00"))
    L.boot(_t(3, "09:00"), boot_type=1)                                     # -> T4 Fast Startup
    L.filler(_t(3, "09:00"), _t(3, "11:41"), every_min=15)
    L.drive_trouble(_t(3, "11:41", 30))
    L.add(_t(3, "11:42", 12), "Service Control Manager", 7036, qualifiers=16384, data={"param1": "Windows Update", "param2": "running"})
    L.boot(_t(3, "11:44"))                                                  # -> T5 hard, power loss
    L.k41(_t(3, "11:44", 20))
    L.e6008(_t(3, "11:44", 16), _t(3, "11:42", 12))
    L.add(_t(3, "11:45"), "Microsoft-Windows-StorPort", 549, level=3, chan=STP, data={"Port": "0", "Opcode": "42"})
    L.filler(_t(3, "11:44"), _t(3, "14:10"))
    L.sleep(_t(3, "14:10"), _t(3, "15:00"), enter=False, wake="Lid")        # S: 42 missing
    L.filler(_t(3, "15:00"), _t(3, "19:00"))
    L.clean_stop(_t(3, "19:00"), with_6006=False)                           # -> T6 clean, 6006 missing
    L.boot(_t(4, "08:30"))
    L.filler(_t(4, "08:30"), _t(4, "10:15"))
    for i in range(4):
        L.add(_t(4, "10:14", 10 + 8 * i), "Microsoft-Windows-WHEA-Logger", 17, level=3, data={
            "ErrorSource": "4", "PrimaryDeviceName": "PCI\\VEN_DEMO&DEV_0001", "SecondaryDeviceName": ""})
    L.add(_t(4, "10:14", 50), "Application Error", 1000, level=2, chan=APP, data=["demo.exe", "1.0", "0xc0000005"])
    L.boot(_t(4, "10:17"))                                                  # -> T7 crash
    L.k41(_t(4, "10:17", 20), bugcheck=159)
    L.e6008(_t(4, "10:17", 16), _t(4, "10:15"))
    L.add(_t(4, "10:19"), "Microsoft-Windows-WER-SystemErrorReporting", 1001, level=2, qualifiers=16384, data={
        "param1": "0x0000009f (0x0000000000000003, 0xffffdemo, 0xffffdemo, 0xffffdemo)",
        "param2": "C:\\Windows\\MEMORY.DMP", "param3": "DEMO"})
    L.filler(_t(4, "10:17"), _t(4, "12:58"))
    L.drive_trouble(_t(4, "12:58"), resets=3, retries=2)
    L.boot(_t(4, "13:03"))                                                  # -> T8 long-press
    L.k41(_t(4, "13:03", 20), power_button=133700000000000000)
    L.e6008(_t(4, "13:03", 16), _t(4, "12:59"))
    L.filler(_t(4, "13:03"), _t(4, "16:00"))
    L.sleep(_t(4, "16:00"), _t(4, "16:40"), enter=False, resume=False, wake="Keyboard")  # S: only PT-1
    L.filler(_t(4, "16:40"), _t(4, "22:00"))
    L.sleep(_t(4, "22:00"), None, resume=False, report=False)               # never resumed
    L.boot(_t(5, "09:00"))                                                  # -> T9 power lost in sleep
    L.k41(_t(5, "09:00", 20), sleep=1)
    L.e6008(_t(5, "09:00", 16), _t(4, "22:00"))
    L.filler(_t(5, "09:00"), _t(5, "12:00"))
    L.boot(_t(5, "12:20"))                                                  # -> T10 silent end (inferred)
    L.filler(_t(5, "12:20"), _t(5, "17:00"))
    L.skip(SYS, 37, at=_t(5, "17:24"))                                                         # records lost
    L.boot(_t(5, "17:25"))                                                  # -> T11 log gap
    L.filler(_t(5, "17:25"), _t(5, "21:00"))
    L.clean_stop(_t(5, "21:00"))
    L.boot(_t(6, "08:40"))                                                  # -> T12 full shutdown
    L.filler(_t(6, "08:40"), _t(6, "10:00"))
    L.sleep(_t(6, "10:00"), _t(6, "11:00"), resume=False, target=5, wake="Power Button")  # hibernate
    L.add(_t(6, "11:00", 2), "Microsoft-Windows-Kernel-Boot", 27, data={"BootType": 2, "LoadOptions": ""})
    L.filler(_t(6, "11:00"), _t(6, "18:00"))
    L.add(_t(6, "12:00"), "Microsoft-Windows-Kernel-General", 1, data={
        "NewTime": _ts(_t(6, "10:00")), "OldTime": _ts(_t(6, "12:00")), "Reason": "2",
        "ProcessName": "C:\\Windows\\System32\\rundll32.exe"})
    L.clean_stop(_t(6, "18:00"), with_1074=False)
    L.boot(_t(6, "18:01"))                                                  # -> T13 restart inferred
    L.filler(_t(6, "18:01"), _t(6, "18:30"))
    L.clean_stop(_t(6, "18:30"))
    L.boot(_t(7, "09:00"))                                                  # -> T14 full shutdown
    L.filler(_t(7, "09:00"), _t(7, "12:00"))
    return L.write(folder)


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(__file__)), "demo_logs")
    for f in build(out):
        print(f)
