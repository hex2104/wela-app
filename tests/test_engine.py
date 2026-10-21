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
        self.assertEqual(self.r["disks"][0]["Model"], "DEMO NVMe SSD 1TB")

    def test_exports(self):
        html = report.to_html(self.r, 330)
        self.assertIn(b"WELA power-cycle report", html)
        self.assertIn(b"Drive around each power cycle", html)
        x = report.to_xlsx(self.r)
        with zipfile.ZipFile(__import__("io").BytesIO(x)) as z:
            self.assertIn("xl/worksheets/sheet2.xml", z.namelist())
            self.assertIn("Drive windows", z.read("xl/workbook.xml").decode())
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


if __name__ == "__main__":
    unittest.main()
