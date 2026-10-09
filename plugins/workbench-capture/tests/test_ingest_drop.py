"""Ingest: the drop folder (transcripts become one meeting file each) and the InfoSec gate."""
import hashlib
import json
import os
import re
import sys
import unittest
from pathlib import Path

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import harness as H  # noqa: E402
import common  # noqa: E402
import drop  # noqa: E402

JOIN = "https://teams.example.com/l/meetup-join/19%3ameeting_abc123/0?context=secret"
STEM = "Quarterly Planning Sync-20261001_090000-Meeting Transcript"
CUES = H.CUES + [("00:00:30", "Bob Sample", f"The join link was {JOIN} for anyone late.")]
SIDE = {"title": H.MEETING, "start": "2026-10-01T09:00:00Z", "end": "2026-10-01T09:30:00Z", "organizer": "Alice Example <alice@example.com>",
        "attendees": ["alice@example.com", "bob@example.com"], "join_url": JOIN, "transcript_source": "teams-transcript"}


def front(path):
    fm, body = common.read_file(path)
    return list(fm), fm, body


class DropTests(unittest.TestCase):
    def setUp(self):
        self.e = H.Env()
        self.addCleanup(self.e.close)
        self.drop = self.e.P.drop
        self.drop.mkdir(parents=True)

    def put(self, name, data):
        (self.drop / name).write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))

    def meetings(self):
        return sorted(self.e.P.captured.glob("meetings/*/*.md"))

    def test_vtt_and_docx_of_one_meeting_make_one_file(self):
        self.put(f"{STEM}.vtt", H.vtt(CUES))
        H.docx(self.drop / f"{STEM}.docx", cues=CUES)
        self.put(f"{STEM}.meta.json", json.dumps(SIDE))
        code, out = self.e.run("meetings", "run", "--no-digest")
        self.assertEqual(code, 0, out)
        files = self.meetings()
        self.assertEqual(len(files), 1)
        keys, fm, body = front(files[0])
        self.assertEqual(keys, ["source", "url", "title", "author", "modified", "captured_at", "labels", "scope",
                                "meeting_id", "organizer", "attendees", "start", "end", "transcript_source"])
        mid = drop.meeting_id(H.MEETING, "2026-10-01T09:00:00Z", "Alice Example <alice@example.com>")
        self.assertRegex(fm["meeting_id"], r"^[0-9a-f]{64}$")
        self.assertEqual((fm["meeting_id"], fm["url"], fm["source"], fm["scope"]), (mid, f"teams-meeting:{mid}", "meetings", "meetings:alice-example"))
        self.assertEqual((fm["organizer"], fm["attendees"], fm["transcript_source"]), (SIDE["organizer"], SIDE["attendees"], "teams-transcript"))
        h8 = hashlib.sha1(fm["url"].encode()).hexdigest()[:8]
        self.assertEqual(files[0].as_posix(), (self.e.P.captured / "meetings" / "alice-example" / f"2026-10-01-quarterly-planning-sync-{h8}.md").as_posix())
        raw = files[0].read_text("utf-8")
        self.assertNotIn("meetup-join", raw)
        self.assertNotIn("context=secret", raw)
        self.assertIn("[link: teams.example.com]", raw)
        self.assertIn("[00:00:05] Alice Example: Welcome everyone", raw)
        done = list((self.e.P.drop_done).glob("*/*"))
        self.assertEqual(sorted(p.name for p in done), sorted([f"{STEM}.vtt", f"{STEM}.docx", f"{STEM}.meta.json"]))
        self.assertEqual([p.name for p in self.drop.iterdir()], [])

    def test_malformed_files_go_to_failed_with_a_report_line(self):
        self.put("broken.vtt", "this is not a transcript")
        self.put("broken-too.docx", b"not a zip at all")
        self.put("empty-cues.vtt", "WEBVTT\n\n")
        code, out = self.e.run("meetings", "run", "--no-digest")
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.name for p in (self.drop / "failed").iterdir()), ["broken-too.docx", "broken.vtt", "empty-cues.vtt"])
        self.assertEqual(self.meetings(), [])
        rep = self.e.reports()[-1]
        self.assertEqual(rep["counts"]["failed"], 3)
        self.assertEqual(sorted(s["item"] for s in rep["skipped"]), ["broken-too.docx", "broken.vtt", "empty-cues.vtt"])
        self.assertTrue(all(s["reason"].startswith("failed:") for s in rep["skipped"]))
        code, _ = self.e.run("meetings", "run", "--no-digest")  # failed/ is not picked up again
        self.assertEqual((code, len(self.e.reports()[-1]["skipped"])), (0, 0))

    def test_a_dtd_in_a_docx_is_refused(self):
        import zipfile
        with zipfile.ZipFile(self.drop / "bomb.docx", "w") as z:
            z.writestr("word/document.xml", '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaa">]><w:document xmlns:w="x"/>')
        self.e.run("meetings", "run", "--no-digest")
        self.assertTrue((self.drop / "failed" / "bomb.docx").exists())

    def test_labelled_docx_keeps_metadata_only_and_never_reaches_a_model(self):
        H.docx(self.drop / f"{STEM}.docx", cues=[("00:00:05", "Alice Example", "SECRETPHRASE the budget is final")], label="Confidential")
        code, out = self.e.run("meetings", "run")  # digest on: still no call
        self.assertEqual(code, 0, out)
        (f,) = self.meetings()
        _, fm, body = front(f)
        self.assertEqual(fm["labels"], ["Confidential"])
        self.assertNotIn("SECRETPHRASE", f.read_text("utf-8"))
        self.assertEqual(body, "")
        self.assertEqual(self.e.claude_calls(), [])
        self.assertEqual(self.e.reports()[-1]["counts"]["labelled"], 1)

    def test_rerun_with_the_same_files_writes_nothing_new(self):
        self.put(f"{STEM}.vtt", H.vtt(CUES))
        self.e.run("meetings", "run", "--no-digest")
        (f,) = self.meetings()
        before = f.stat().st_mtime_ns
        self.put(f"{STEM}.vtt", H.vtt(CUES))
        code, out = self.e.run("meetings", "run", "--no-digest")
        self.assertEqual(code, 0, out)
        self.assertEqual((f.stat().st_mtime_ns, self.e.reports()[-1]["counts"].get("unchanged")), (before, 1))
        self.assertEqual(len(self.meetings()), 1)

    def test_names_without_a_sidecar_fall_back_to_the_file_name_and_speakers(self):
        self.put(f"{STEM}.vtt", H.vtt())
        self.e.run("meetings", "run", "--no-digest")
        (f,) = self.meetings()
        _, fm, _ = front(f)
        self.assertEqual((fm["title"], fm["start"], fm["organizer"], fm["scope"], fm["transcript_source"]),
                         (H.MEETING, "2026-10-01T09:00:00Z", None, "meetings:unsorted", "teams-transcript"))
        self.assertEqual(fm["attendees"], ["Alice Example", "Bob Sample"])
        self.assertEqual(f.parent.name, "unsorted")

    def test_front_matter_round_trips_through_the_reader(self):
        item = {"url": "teams-meeting:abc?x=1#frag", "title": 'A "quoted"\ntitle', "body": "text", "labels": [], "scope": "s", "extra": {"meeting_id": "m"}}
        text = common.render(item, "meetings", "2026-10-08T00:00:00Z")
        p = self.e.P.captured / "x.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, "utf-8")
        fm, body = common.read_file(p)
        self.assertEqual((fm["url"], fm["title"], fm["meeting_id"], body), ("teams-meeting:abc", 'A "quoted" title', "m", "text\n"))
        self.assertNotIn("\r", text)

    def test_vtt_and_docx_parsers(self):
        cues = drop.parse_vtt(H.vtt() + "\n9\n00:01:00.000 --> 00:01:02.000\nplain line without a speaker\n")
        self.assertEqual(cues[0], ("00:00:05", "Alice Example", "Welcome everyone, let us start with the roadmap."))
        self.assertEqual(cues[-1], ("00:01:00", None, "plain line without a speaker"))
        self.assertEqual(drop.fmt_ts("1 minutes 5 seconds"), "00:01:05")
        self.assertEqual(drop.fmt_ts("2:03"), "00:02:03")


class FileNameTests(unittest.TestCase):
    def test_safe_name_cleans_outside_text(self):
        for raw, want in (("..\\..\\evil", "evil"), ("../../evil", "evil"), ("C:evil", "C evil"), ("a/b", "a b"), ("Plan\x00\x1f\x07 review\r\n", "Plan review"),
                          ("...", "Meeting"), ("", "Meeting"), (None, "Meeting"), ("CON", "Meeting"), ("nul.txt", "Meeting"), (" . ", "Meeting"), ("a\u200b\u202eb", "ab"),
                          ("Weekly review", "Weekly review"), ("x.y..z", "x.y.z")):
            self.assertEqual(common.safe_name(raw), want, raw)
        long = common.safe_name("T" * 300 + ". .")
        self.assertEqual(len(long), 60)
        self.assertEqual(common.safe_name("a" * 59 + " .. b"), "a" * 59)  # cut, then trailing space and dots go

    def test_safe_join_refuses_anything_that_leaves_the_folder(self):
        with H.tempfile.TemporaryDirectory() as t:
            ok = common.safe_join(t, "file.vtt")
            self.assertEqual(ok.parent, Path(t).resolve())
            for bad in ("../x.vtt", "..\\x.vtt", "sub/x.vtt", "C:x.vtt", str(Path(t).parent / "abs.vtt"), ".", ""):
                with self.assertRaises(ValueError, msg=bad):
                    common.safe_join(t, bad)


class GateTests(unittest.TestCase):
    def test_runs_exit_5_until_the_acknowledgement_is_recorded(self):
        e = H.Env(ack=False)
        self.addCleanup(e.close)
        for argv in (("meetings", "run"), ("mail", "run", "--experimental", "--source", "com"), ("digest", "--pending")):
            code, out = e.run(*argv)
            self.assertEqual(code, 5, argv)
            self.assertIn("ack-infosec", out)
        self.assertEqual(e.reports(), [])
        code, out = e.run("ack-infosec")
        self.assertEqual(code, 0)
        self.assertIn("security team", out)
        self.assertRegex(common.load_settings(e.P)["infosec_ack"], r"^\d{4}-\d\d-\d\dT")
        self.assertEqual(e.run("meetings", "run", "--no-digest")[0], 0)

    def test_config_and_status(self):
        e = H.Env()
        self.addCleanup(e.close)
        self.assertEqual(e.run("config", "set", "digest_max_per_day", "5")[0], 0)
        self.assertEqual(e.run("config", "get", "digest_max_per_day")[1].strip(), "5")
        self.assertEqual(e.run("config", "set", "digest_max_per_day", "zero")[0], 4)
        self.assertEqual(e.run("config", "set", "infosec_ack", "x")[0], 4)
        code, out = e.run("status", "--json")
        st = json.loads(out)
        self.assertEqual((code, st["infosec_ack"], st["digest_max_per_day"], st["meetings_files"]), (0, True, 5, 0))


if __name__ == "__main__":
    unittest.main()
