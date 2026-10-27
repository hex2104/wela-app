"""Run with:  python -m unittest discover -s tests -v"""
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wela import catalog, demo, engine, parser, report  # noqa: E402
from wela.models import Event, parse_time  # noqa: E402


def ev(t, prov, eid, chan="System", rid=None, level=4, **data):
    return Event(time=parse_time(t), channel=chan, provider=prov, eid=eid, rid=rid, level=level, data={k: str(v) for k, v in data.items()})


KG, KP, EL = "Microsoft-Windows-Kernel-General", "Microsoft-Windows-Kernel-Power", "EventLog"
STP = "Microsoft-Windows-Storage-Storport/Operational"
PART = "Microsoft-Windows-Partition/Diagnostic"
SAMSUNG = {"Model": "SAMSUNG MZVL2512HCJQ-00B00", "SerialNumber": "S6DEMO0001", "BusType": 17}
WD = {"Model": "WDC PC SN730 SDBQNTY-512G", "SerialNumber": "WD-DEMO-0002", "BusType": 17}


def inv(t, disk, drive):
    return ev(t, "Microsoft-Windows-Partition", 1006, chan=PART, DiskNumber=disk, **drive)


def storport(t, eid=549, level=3, **ident):
    return ev(t, "Microsoft-Windows-StorPort", eid, chan=STP, level=level, Port=0, Opcode=42, **ident)


def app(t, prov, eid, level=2, **data):
    return ev(t, prov, eid, chan="Application", level=level, **data)


def req(t, process, code, kind="restart", comment=""):
    """User32 1074 as Windows writes it: unnamed params, process with ' (COMPUTER)' appended."""
    return ev(t, "User32", 1074, param1=f"{process} (PC)", param2="PC", param3="", param4=code, param5=kind,
              param6=comment, param7="PC\\user")


def clean_cycle(before=(), stop=True, after=()):
    """Session ends with an orderly stop at 18:00:10 (13 + 6006), next boot 18:01 -> restart."""
    return (boot("2026-01-01T08:00:00Z") + [ev("2026-01-01T17:30:00Z", "Service Control Manager", 7036)] + list(before)
            + ([ev("2026-01-01T18:00:09Z", KG, 13), ev("2026-01-01T18:00:10Z", EL, 6006)] if stop else [])
            + boot("2026-01-01T18:01:00Z") + list(after))


def boot(t, bt=0):
    return [ev(t, KG, 12), ev(t, "Microsoft-Windows-Kernel-Boot", 27, BootType=bt), ev(t, EL, 6005)]


def hard_cycle(before=(), after=(), **k41):
    """Session ends 10:00:00 with no stop events, boot 10:05 logs 41; extra events go before / after."""
    fields = {"BugcheckCode": 0, "PowerButtonTimestamp": 0, "SleepInProgress": 0, **k41}
    return (boot("2026-01-01T08:00:00Z") + list(before) + [ev("2026-01-01T10:00:00Z", "Service Control Manager", 7036)]
            + boot("2026-01-01T10:05:00Z") + [ev("2026-01-01T10:05:20Z", KP, 41, **fields)] + list(after))


def run(events):
    return engine.analyze(events, catalog.load_config())


def transitions(r):
    return [x for x in r["items"] if x["type"] != "sleep"]


class DemoScenario(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        demo.build(cls.tmp)
        events, cls.sources = parser.load([cls.tmp])
        cls.r = engine.analyze(events, catalog.load_config(), cls.sources)

    def test_files_parsed(self):
        self.assertTrue(all(s["error"] is None for s in self.sources))
        self.assertEqual(len(self.sources), 4)

    def test_every_transition_classified_as_expected(self):
        got = {t["id"]: t for t in transitions(self.r)}
        self.assertEqual(len(got), len(demo.EXPECTED_TRANSITIONS))
        for tid, typ, sub in demo.EXPECTED_TRANSITIONS:
            with self.subTest(tid):
                self.assertEqual(got[tid]["type"], typ, got[tid]["subtype"])
                self.assertIn(sub.lower(), got[tid]["subtype"].lower())

    def test_sleep_episodes(self):
        sl = [x for x in self.r["items"] if x["type"] == "sleep"]
        self.assertEqual(len(sl), 5)
        self.assertEqual(sum(1 for x in sl if x["kind"] == "hibernate"), 1)
        self.assertTrue(any(x["open"] for x in sl))
        rebuilt = [x for x in sl if any("rebuilt" in f["text"] for f in x["flags"])]
        self.assertEqual(len(rebuilt), 2)

    def test_drive_correlation(self):
        t5 = next(t for t in self.r["items"] if t["id"] == "T5")
        self.assertEqual(t5["drive"]["state"], "reset")
        self.assertIn("Reset to device", t5["drive"]["before"]["counts"])

    def test_drive_cause_and_effect(self):
        d = {x["id"]: x["drive"] for x in self.r["items"]}
        for tid, cause in [("T5", "likely"), ("T8", "likely"), ("T7", "possible"), ("T9", "no_evidence"),
                           ("T10", "no_evidence"), ("T1", "unknown"), ("T11", "unknown"), ("T2", "n/a"), ("S1", "n/a")]:
            with self.subTest(tid):
                self.assertEqual(d[tid]["cause"], cause)
                # only a quiet log gets the "does not clear the drive" caveat
                self.assertEqual(any("does not clear the drive" in x for x in d[tid]["reasons"]), cause == "no_evidence")
        self.assertEqual(d["T5"]["effect"], "warnings")
        self.assertEqual(d["T5"]["before"]["events"][-1]["offset_s"], -17.0)
        self.assertEqual(self.r["counts"]["drive_likely"], 2)

    def test_quality(self):
        q = self.r["integrity"]
        self.assertEqual(len(q["record_gaps"]), 1)
        self.assertEqual(q["record_gaps"][0]["missing"], 37)
        self.assertEqual(len(q["time_changes"]), 1)
        self.assertEqual(q["missing_channels"], [])
        self.assertEqual(self.r["disks"][0]["Model"], demo.SSD["Model"])

    def test_samsung_drive_identified(self):
        d = {x["id"]: x["drive"] for x in self.r["items"]}
        self.assertEqual((d["T5"]["highlight"], d["T8"]["highlight"]), ("yes", "yes"))
        self.assertTrue(any("on the Samsung drive" in x for x in d["T5"]["reasons"]))
        self.assertEqual(self.r["counts"]["hl_suspect"], 2)
        # the USB drive's error is pinned on it, the NTFS error (two drives present) on nothing
        s3 = d["S3"]
        self.assertEqual(s3["highlight"], "unknown")
        self.assertEqual({e["hl"] for e in s3["before"]["events"] if e["state"] != "info"}, {"no", ""})
        self.assertTrue(any(x.startswith("Other drive (WDC") for x in s3["reasons"]))
        disks = {x["Model"]: x for x in self.r["disks"]}
        self.assertEqual(len(disks), 2)   # Storport's "SAMSUNG MZVL21T0" + other serial format = the same drive
        self.assertTrue(disks[demo.SSD["Model"]]["highlight"])
        self.assertFalse(disks[demo.USB["Model"]]["highlight"])
        bases = {(e["hl"], e["dev_basis"].split(" - ")[0]) for e in self.r["storage_events"]}
        self.assertTrue({("yes", "named in the event"), ("yes", "Disk 0 in the Partition inventory"),
                         ("probably", "only drive in this boot"), ("no", "Disk 1 in the Partition inventory")} <= bases)

    def test_software_triggers(self):
        sw = {x["id"]: x["software"] for x in self.r["items"]}
        for tid, trig, strength in demo.EXPECTED_TRIGGERS:
            with self.subTest(tid):
                self.assertEqual((sw[tid]["trigger"], sw[tid]["strength"]), (trig, strength), sw[tid]["reasons"])
        self.assertEqual(sw["T3"]["initiator"]["process"], "TrustedInstaller.exe")
        self.assertEqual(sw["T3"]["confidence"], 1.0)
        self.assertTrue(any("symptom of the drive" in x for x in sw["T8"]["reasons"]))
        self.assertTrue(any("lsass.exe" in x for x in sw["T16"]["reasons"]))
        self.assertEqual(sw["T7"]["after"]["counts"], {"Crash report: blue screen": 1})
        self.assertEqual(sw["S1"]["trigger"], "n/a")

    def test_exports(self):
        html = report.to_html(self.r, 330)
        self.assertIn(b"WELA power-cycle report", html)
        self.assertIn(b"Drive around each power cycle", html)
        self.assertIn(b"Software around each power cycle", html)
        self.assertIn(b"class='sam'", html)
        x = report.to_xlsx(self.r)
        with zipfile.ZipFile(__import__("io").BytesIO(x)) as z:
            self.assertIn("xl/worksheets/sheet2.xml", z.namelist())
            wb = z.read("xl/workbook.xml").decode()
            for sheet in ("Drive windows", "Software windows", "Software events"):
                self.assertIn(sheet, wb)
            self.assertIn('s="2"', z.read("xl/worksheets/sheet3.xml").decode())   # Samsung rows filled
        self.assertTrue(report.to_csv(self.r).startswith("﻿ID".encode("utf-8")))
        json.loads(report.to_json(self.r))


class Rules(unittest.TestCase):
    def test_clean_shutdown_with_6006_missing_still_clean(self):
        e = boot("2026-01-01T08:00:00Z") + [
            ev("2026-01-01T18:00:00Z", "User32", 1074, param5="power off"),
            ev("2026-01-01T18:00:10Z", KG, 13),
        ] + boot("2026-01-02T08:00:00Z")
        t = transitions(run(e))[1]
        self.assertEqual(t["type"], "shutdown")
        self.assertIn("Event log stopped (6006)", t["evidence_missing"])

    def test_restart_inferred_from_gap(self):
        e = boot("2026-01-01T08:00:00Z") + [ev("2026-01-01T18:00:00Z", KG, 13), ev("2026-01-01T18:00:01Z", EL, 6006)] + \
            boot("2026-01-01T18:01:00Z")
        t = transitions(run(e))[1]
        self.assertEqual(t["type"], "restart")
        self.assertTrue(any("inferred" in f["text"] for f in t["flags"]))

    def test_fast_startup(self):
        e = boot("2026-01-01T08:00:00Z") + [ev("2026-01-01T18:00:00Z", "User32", 1074, param5="restart"),
                                            ev("2026-01-01T18:00:02Z", KG, 13), ev("2026-01-01T18:00:03Z", EL, 6006)] + \
            boot("2026-01-01T18:01:00Z", bt=1)
        t = transitions(run(e))[1]
        self.assertEqual(t["type"], "shutdown")
        self.assertIn("Fast Startup", t["subtype"])

    def test_41_subtypes(self):
        for fields, expect in [({"BugcheckCode": 239}, "Crash"), ({"PowerButtonTimestamp": 1}, "long-press"),
                               ({"SleepInProgress": 1}, "sleep"), ({}, "Power loss")]:
            base = {"BugcheckCode": 0, "PowerButtonTimestamp": 0, "SleepInProgress": 0}
            base.update(fields)
            e = boot("2026-01-01T08:00:00Z") + [ev("2026-01-01T10:00:00Z", "Service Control Manager", 7036)] + \
                boot("2026-01-01T10:05:00Z") + [ev("2026-01-01T10:05:20Z", KP, 41, **base)]
            t = transitions(run(e))[1]
            with self.subTest(expect):
                self.assertEqual(t["type"], "hard")
                self.assertIn(expect.lower(), t["subtype"].lower())

    def test_hang_during_shutdown(self):
        e = boot("2026-01-01T08:00:00Z") + [ev("2026-01-01T18:00:00Z", "User32", 1074, param5="power off")] + \
            boot("2026-01-01T18:20:00Z") + [ev("2026-01-01T18:20:20Z", KP, 41, BugcheckCode=0)]
        t = transitions(run(e))[1]
        self.assertEqual(t["type"], "hard")
        self.assertIn("did not complete", t["subtype"])

    def test_silent_end_inferred_low_confidence(self):
        e = boot("2026-01-01T08:00:00Z") + [ev("2026-01-01T10:00:00Z", "Service Control Manager", 7036)] + \
            boot("2026-01-01T10:30:00Z")
        t = transitions(run(e))[1]
        self.assertEqual(t["type"], "hard")
        self.assertLess(t["confidence"], 0.6)
        self.assertTrue(t["needs_review"])

    def test_sleep_rebuilt_from_pt1_only(self):
        e = boot("2026-01-01T08:00:00Z") + [ev("2026-01-01T13:00:12Z", "Microsoft-Windows-Power-Troubleshooter", 1,
                                               SleepTime="2026-01-01T12:00:00Z", WakeTime="2026-01-01T13:00:00Z", WakeSourceText="Lid")]
        sl = [x for x in run(e)["items"] if x["type"] == "sleep"]
        self.assertEqual(len(sl), 1)
        self.assertEqual(sl[0]["duration_s"], 3600)
        self.assertEqual(sl[0]["wake_source"], "Lid")

    def test_window_lists_informational_storport_events(self):
        t = transitions(run(hard_cycle([ev("2026-01-01T09:59:30Z", "Microsoft-Windows-StorPort", 505, chan=STP,
                                           Port=0, Opcode=42)])))[1]
        pre = t["drive"]["before"]
        self.assertEqual((pre["state"], pre["info_count"]), ("healthy", 1))
        self.assertEqual(pre["events"][0]["offset_s"], -30.0)
        self.assertIn("Opcode=42 (WRITE(10))", pre["events"][0]["fields"])
        self.assertEqual((t["drive"]["cause"], t["drive"]["cause_label"]), ("no_evidence", "No drive evidence"))

    def test_drive_reset_before_hard_shutdown_is_likely_cause(self):
        t = transitions(run(hard_cycle([ev("2026-01-01T09:59:40Z", "stornvme", 129, level=3)])))[1]
        self.assertEqual(t["drive"]["cause"], "likely")
        self.assertIn("Reset to device x1", t["drive"]["reasons"][0])

    def test_storage_bugcheck_and_drive_missing_after_boot(self):
        t = transitions(run(hard_cycle(after=[ev("2026-01-01T10:05:30Z", "disk", 157, level=3)], BugcheckCode=0x7A)))[1]
        self.assertEqual(t["drive"]["cause"], "likely")
        self.assertTrue(any("KERNEL_DATA_INPAGE_ERROR" in x for x in t["drive"]["reasons"]))
        self.assertEqual(t["drive"]["effect"], "missing")

    def test_platform_errors_alone_are_only_possible(self):
        t = transitions(run(hard_cycle([ev("2026-01-01T09:59:40Z", "Microsoft-Windows-WHEA-Logger", 18, level=2)])))[1]
        self.assertEqual(t["drive"]["cause"], "possible")

    def test_drive_errors_during_orderly_shutdown(self):
        e = boot("2026-01-01T08:00:00Z") + [
            ev("2026-01-01T17:59:50Z", "Microsoft-Windows-Ntfs", 140, level=2),
            ev("2026-01-01T18:00:00Z", "User32", 1074, param5="power off"),
            ev("2026-01-01T18:00:10Z", KG, 13), ev("2026-01-01T18:00:11Z", EL, 6006),
        ] + boot("2026-01-02T08:00:00Z")
        d = transitions(run(e))[1]["drive"]
        self.assertEqual((d["cause"], d["before"]["state"]), ("n/a", "error"))
        self.assertTrue(any("orderly" in x for x in d["reasons"]))

    def test_xml_parser_unnamed_and_userdata(self):
        xml = ('<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System><Provider Name="EventLog"/>'
               '<EventID Qualifiers="32768">6008</EventID><Level>2</Level><TimeCreated SystemTime="2026-01-01T10:00:00.1234567Z"/>'
               '<EventRecordID>7</EventRecordID><Channel>System</Channel><Computer>PC</Computer></System>'
               '<EventData><Data>10:00:00</Data><Data>01-01-2026</Data></EventData></Event>'
               '<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System><Provider Name="Microsoft-Windows-Eventlog"/>'
               '<EventID>104</EventID><Level>4</Level><TimeCreated SystemTime="2026-01-01T11:00:00Z"/><EventRecordID>8</EventRecordID>'
               '<Channel>System</Channel></System><UserData><LogFileCleared xmlns="x"><SubjectUserName>admin</SubjectUserName>'
               '<Channel>System</Channel></LogFileCleared></UserData></Event>')
        evs = parser.parse_xml_text(xml, "t.xml")
        self.assertEqual(evs[0].data["param1"], "10:00:00")
        self.assertEqual(evs[0].eid, 6008)
        self.assertEqual(evs[1].data["SubjectUserName"], "admin")


class WhichDrive(unittest.TestCase):
    """Tie storage events to a drive and highlight Samsung."""

    def drive(self, events, k=1):
        return transitions(run(events))[k]["drive"]

    def test_storport_event_naming_samsung(self):
        d = self.drive(hard_cycle([storport("2026-01-01T09:59:40Z", VendorId="NVMe", ProductId="Samsung SSD 980 PRO",
                                            SerialNumber="S69ENX0R000001")]))
        e = d["before"]["events"][0]
        self.assertEqual((e["hl"], e["vendor"], e["dev_basis"]), ("yes", "Samsung", "named in the event"))
        self.assertEqual((d["cause"], d["highlight"], d["highlight_label"]), ("possible", "yes", "Samsung drive"))
        self.assertIn("These drive problems are on the Samsung drive", d["reasons"])

    def test_samsung_part_number_without_the_name(self):
        e = self.drive(hard_cycle([storport("2026-01-01T09:59:40Z", ProductId="MZVL2512HCJQ-00B00")]))["before"]["events"][0]
        self.assertEqual((e["hl"], e["vendor"]), ("yes", "Samsung"))

    def test_other_vendor_is_not_highlighted(self):
        d = self.drive(hard_cycle([storport("2026-01-01T09:59:40Z", VendorId="NVMe", ProductId="WDC PC SN730 SDBQ")]))
        self.assertEqual((d["highlight"], d["before"]["events"][0]["vendor"]), ("no", "Western Digital"))
        self.assertIn("These drive problems are on another drive, not the Samsung drive", d["reasons"])

    def test_disk_number_through_the_inventory(self):
        e = hard_cycle([inv("2026-01-01T08:00:05Z", 0, SAMSUNG), inv("2026-01-01T08:00:05Z", 1, WD),
                        ev("2026-01-01T09:59:30Z", "disk", 153, level=3, param1="\\Device\\Harddisk1\\DR1"),
                        ev("2026-01-01T09:59:40Z", "disk", 7, level=2, param1="\\Device\\Harddisk0\\DR0"),
                        ev("2026-01-01T09:59:50Z", "stornvme", 129, level=3, param1="\\Device\\RaidPort0")])
        got = {x["eid"]: (x["hl"], x["dev_basis"]) for x in self.drive(e)["before"]["events"] if x["state"] != "info"}
        self.assertEqual(got[153], ("no", "Disk 1 in the Partition inventory"))
        self.assertEqual(got[7], ("yes", "Disk 0 in the Partition inventory"))
        self.assertEqual(got[129][0], "")    # two drives in this boot: an unnamed reset is not guessed

    def test_disk_numbers_follow_each_boot(self):
        # the two drives swap disk numbers between boots; the event uses the numbering of its own boot
        e = (boot("2026-01-01T08:00:00Z") + [inv("2026-01-01T08:00:05Z", 0, SAMSUNG), inv("2026-01-01T08:00:05Z", 1, WD)]
             + boot("2026-01-01T09:00:00Z") + [inv("2026-01-01T09:00:05Z", 0, WD), inv("2026-01-01T09:00:05Z", 1, SAMSUNG),
                                              ev("2026-01-01T09:59:40Z", "disk", 7, level=2, param1="\\Device\\Harddisk0\\DR0"),
                                              ev("2026-01-01T10:00:00Z", "Service Control Manager", 7036)]
             + boot("2026-01-01T10:05:00Z") + [ev("2026-01-01T10:05:20Z", KP, 41, BugcheckCode=0)])
        x = [x for x in transitions(run(e))[2]["drive"]["before"]["events"] if x["eid"] == 7][0]
        self.assertEqual((x["hl"], x["vendor"]), ("no", "Western Digital"))

    def test_unnamed_event_is_probably_the_only_drive(self):
        d = self.drive(hard_cycle([inv("2026-01-01T08:00:05Z", 0, SAMSUNG),
                                   ev("2026-01-01T09:59:50Z", "stornvme", 129, level=3, param1="\\Device\\RaidPort0")]))
        e = [x for x in d["before"]["events"] if x["eid"] == 129][0]
        self.assertEqual((e["hl"], e["dev_basis"]), ("probably", "only drive in this boot"))
        self.assertEqual((d["cause"], d["highlight"]), ("likely", "probably"))
        self.assertTrue(any("probably on the Samsung drive" in x for x in d["reasons"]))

    def test_without_inventory_only_disk_0_is_guessed(self):
        named = storport("2026-01-01T08:30:00Z", level=4, eid=505, ProductId="Samsung SSD 980")
        d = self.drive(hard_cycle([named, ev("2026-01-01T09:59:30Z", "disk", 153, level=3, param1="\\Device\\Harddisk1\\DR1"),
                                   ev("2026-01-01T09:59:40Z", "disk", 153, level=3, param1="\\Device\\Harddisk0\\DR0")]))
        got = [(x["dev_basis"].split(" - ")[0], x["hl"]) for x in d["before"]["events"]]
        self.assertEqual(got, [("not identified", ""), ("only drive in these logs", "probably")])

    def test_whea_names_a_pci_device_but_is_never_guessed(self):
        d = self.drive(hard_cycle([inv("2026-01-01T08:00:05Z", 0, SAMSUNG),
                                   ev("2026-01-01T09:59:30Z", "Microsoft-Windows-WHEA-Logger", 17, level=3,
                                      PrimaryDeviceName="PCI\\VEN_8086&DEV_A33C"),
                                   ev("2026-01-01T09:59:40Z", "Microsoft-Windows-WHEA-Logger", 17, level=3,
                                      PrimaryDeviceName="PCI\\VEN_8086&DEV_A33C",   # root port first, SSD behind it
                                      SecondaryDeviceName="PCI\\VEN_144D&DEV_A80A&SUBSYS_A801144D")]))
        got = [(x["hl"], x["dev_basis"]) for x in d["before"]["events"] if x["eid"] == 17]
        self.assertEqual(got, [("", "not identified"), ("yes", "PCI device VEN_144D in the event")])

    def test_serial_formats_of_one_drive_merge(self):
        r = run(hard_cycle([inv("2026-01-01T08:00:05Z", 0, SAMSUNG),
                            storport("2026-01-01T08:30:00Z", eid=505, level=4, VendorId="NVMe", ProductId="SAMSUNG MZVL2512",
                                     SerialNumber="0025_3881_0000_0001.")]))
        self.assertEqual([x["Model"] for x in r["disks"]], [SAMSUNG["Model"]])

    def test_highlight_vendor_is_configurable(self):
        cfg = catalog.load_config()
        cfg["highlight_vendor"] = "Western Digital"
        r = engine.analyze(hard_cycle([storport("2026-01-01T09:59:40Z", ProductId="WDC PC SN730")]), cfg)
        self.assertEqual((r["highlight_vendor"], transitions(r)[1]["drive"]["highlight"]), ("Western Digital", "yes"))


class SoftwareTrigger(unittest.TestCase):
    """What triggered a power cycle on the software side."""

    def sw(self, events, k=1):
        return transitions(run(events))[k]["software"]

    def test_reason_codes(self):
        self.assertEqual(engine._reason(0x80020010), ("update", "Operating System: Service pack (planned)", True))
        self.assertEqual(engine._reason(0x80040002)[0], "installer")
        self.assertEqual(engine._reason(0x10007)[:2], ("hardware", "Hardware: Disk (unplanned)"))
        self.assertEqual(engine._reason(0x500FF)[0], None)
        self.assertEqual(engine._reason(None), (None, "", False))

    def test_user_restart(self):
        s = self.sw(clean_cycle([req("2026-01-01T18:00:00Z", "C:\\Windows\\Explorer.EXE", "0x0")]))
        self.assertEqual((s["trigger"], s["strength"], s["confidence"]), ("user", "confirmed", 0.85))
        self.assertEqual(s["initiator"]["process"], "Explorer.EXE")

    def test_update_and_restart_from_start_menu(self):
        # the user's shell asks, but the reason code says servicing -> Windows Update
        s = self.sw(clean_cycle([req("2026-01-01T18:00:00Z", "C:\\Windows\\system32\\winlogon.exe", "0x80020010")]))
        self.assertEqual((s["trigger"], s["label"]), ("update", "Windows Update"))

    def test_vendor_tools(self):
        for proc in ("C:\\Program Files\\Dell\\CommandUpdate\\dcu-cli.exe", "C:\\Program Files\\Samsung\\Samsung Magician\\SamsungMagician.exe"):
            with self.subTest(proc):
                s = self.sw(clean_cycle([req("2026-01-01T18:00:00Z", proc, "0x80040001")]))
                self.assertEqual((s["trigger"], s["confidence"]), ("vendor", 0.85))

    def test_installer_backed_by_msi_events(self):
        s = self.sw(clean_cycle([app("2026-01-01T17:58:00Z", "MsiInstaller", 1038, level=4, param1="Demo App"),
                                 req("2026-01-01T18:00:00Z", "C:\\Windows\\System32\\msiexec.exe", "0x80040002")]))
        self.assertEqual((s["trigger"], s["confidence"]), ("installer", 1.0))
        self.assertTrue(any("Installer needs a restart" in x for x in s["reasons"]))

    def test_service_recovery_restart_without_1074(self):
        s = self.sw(clean_cycle([ev("2026-01-01T17:59:00Z", "Service Control Manager", 7031, level=1, param1="Demo Service",
                                    param2="1", param3="0", param4="2", param5="Restart the computer.")]))
        self.assertEqual((s["trigger"], s["strength"]), ("service", "likely"))

    def test_clean_stop_without_1074_is_not_logged(self):
        s = self.sw(clean_cycle())
        self.assertEqual((s["trigger"], s["strength"], s["confidence"]), ("not_logged", "unknown", None))

    def test_pending_update_makes_a_bare_restart_possible(self):
        s = self.sw(clean_cycle([ev("2026-01-01T12:00:00Z", "Microsoft-Windows-WindowsUpdateClient", 21, updateTitle="KB5000001")]))
        self.assertEqual((s["trigger"], s["strength"]), ("update", "possible"))

    def test_critical_process_crash_before_bugcheck(self):
        s = self.sw(hard_cycle([app("2026-01-01T09:59:50Z", "Application Error", 1000, param1="csrss.exe", param7="c0000005")],
                               BugcheckCode=0xEF))
        self.assertEqual((s["trigger"], s["strength"], s["confidence"]), ("critical", "likely", 0.7))

    def test_hang_with_drive_problems_is_a_possible_symptom(self):
        s = self.sw(hard_cycle([ev("2026-01-01T09:59:40Z", "stornvme", 129, level=3),
                                app("2026-01-01T09:59:45Z", "Application Hang", 1002, param1="explorer.exe")],
                               PowerButtonTimestamp=1))
        self.assertEqual((s["trigger"], s["strength"], s["confidence"]), ("hang", "possible", 0.2))
        self.assertTrue(any("symptom of the drive" in x for x in s["reasons"]))

    def test_update_still_installing_at_power_loss(self):
        start = ev("2026-01-01T09:50:00Z", "Microsoft-Windows-WindowsUpdateClient", 43, updateTitle="Update (KB5000002)")
        self.assertEqual(self.sw(hard_cycle([start]))["trigger"], "update_running")
        done = ev("2026-01-01T09:55:00Z", "Microsoft-Windows-WindowsUpdateClient", 19, updateTitle="Update (KB5000002)")
        self.assertEqual(self.sw(hard_cycle([start, done]))["trigger"], "none")

    def test_shutdown_requested_but_hung(self):
        e = boot("2026-01-01T08:00:00Z") + [req("2026-01-01T18:00:00Z", "C:\\Windows\\servicing\\TrustedInstaller.exe", "0x80020003"),
                                            ev("2026-01-01T18:00:30Z", "Service Control Manager", 7043, level=2, param1="Demo Service")] + \
            boot("2026-01-01T18:20:00Z") + [ev("2026-01-01T18:20:20Z", KP, 41, BugcheckCode=0)]
        t = transitions(run(e))[1]
        self.assertEqual((t["type"], t["software"]["trigger"], t["software"]["strength"]), ("hard", "update", "confirmed"))
        self.assertTrue(any("never finished" in x for x in t["software"]["reasons"]))
        self.assertIn("Held up by: Demo Service", t["software"]["reasons"])

    def test_quiet_app_log_and_battery_context(self):
        s = self.sw(hard_cycle([ev("2026-01-01T09:00:00Z", KP, 105, AcOnline="false"), app("2026-01-01T09:30:00Z", "Demo", 1, level=4)]))
        self.assertEqual((s["trigger"], s["strength"]), ("none", "none"))
        self.assertTrue(any("Running on battery" in x for x in s["reasons"]))

    def test_tagging_reads_named_and_unnamed_fields(self):
        r = run(hard_cycle([
            app("2026-01-01T09:00:00Z", "Application Error", 1000, AppName="demo.exe", ModuleName="demo.dll", ExceptionCode="c0000409"),
            app("2026-01-01T09:01:00Z", "Application Error", 1000, param1="old.exe", param4="ntdll.dll", param7="c0000005"),
            app("2026-01-01T09:02:00Z", ".NET Runtime", 1026, param1="Application: tool.exe\nException Info: System.IO.IOException"),
            app("2026-01-01T09:03:00Z", "Windows Error Reporting", 1001, level=4, param1="0", param2="5", param3="BlueScreen",
                param4="", param5="0", param6="7a"),
            ev("2026-01-01T09:04:00Z", "Service Control Manager", 7031, level=1, param1="Demo", param4="1", param5="Restart the service")]))
        got = [(e["kind"], e["subject"], e["detail"]) for e in r["software_events"]]
        self.assertEqual(got, [("crash", "demo.exe", "module demo.dll, exception c0000409"),
                               ("crash", "old.exe", "module ntdll.dll, exception c0000005"),
                               ("crash", "tool.exe", "System.IO.IOException"),
                               ("bluescreen", "bug check 7a", ""),
                               ("crash", "Demo", "recovery action: Restart the service")])


class Robustness(unittest.TestCase):
    def test_random_and_malformed_events_never_crash(self):
        import random
        rnd = random.Random(7)
        cfg = catalog.load_config()
        known = [(p, e) for pairs in cfg["signals"].values() for p, e in pairs]
        known += [(p, e) for p, e, *_ in cfg["software_events"]] + [(p, e) for p, e, *_ in cfg["storage_events"] if e != "*"]
        known += [("Microsoft-Windows-StorPort", 549), ("Microsoft-Windows-Partition", 1006), ("Random", 1)]
        values = ["", "0", "2", "0x0", "0x80020003", "garbage", "\\Device\\Harddisk3\\DR3", "PCI\\VEN_144D&DEV_1",
                  "Samsung SSD", "MZVL2512HCJQ", "2026-01-01T00:00:00Z", "not a time", "-1", "99999999999999999999", "Ω☃"]
        keys = ["param1", "param4", "param5", "param6", "DiskNumber", "Model", "ProductId", "SerialNumber", "BootType",
                "BugcheckCode", "SleepTime", "WakeTime", "TargetState", "AppName", "updateTitle", "AcOnline", "NewTime", "OldTime"]
        chans = ["System", "Application", STP, PART, "Setup", ""]
        for _ in range(30):
            evs = []
            for i in range(rnd.randint(0, 400)):
                prov, eid = rnd.choice(known)
                t = f"2026-01-{rnd.randint(1, 3):02d}T{rnd.randint(0, 23):02d}:{rnd.randint(0, 59):02d}:{rnd.randint(0, 59):02d}Z"
                data = {rnd.choice(keys): rnd.choice(values) for _ in range(rnd.randint(0, 5))}
                evs.append(Event(time=parse_time(t), channel=rnd.choice(chans), provider=prov, eid=int(eid),
                                 rid=rnd.choice([None, i, i * 2]), level=rnd.randint(0, 5), data=data))
            r = engine.analyze(evs, cfg)
            json.loads(report.to_json(r))
            report.to_html(r, 330), report.to_xlsx(r, -300), report.to_csv(r)


if __name__ == "__main__":
    unittest.main()
