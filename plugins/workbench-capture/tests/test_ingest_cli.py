"""Ingest: the command line as a process (exit codes), setup, purge, logout, status."""
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import harness as H  # noqa: E402
from fakes.fake_mailsource import FakeMailSource  # noqa: E402
import common  # noqa: E402

INGEST = str(H.SCRIPTS / "ingest.py")
NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)


def proc(e, *argv):
    r = subprocess.run([sys.executable, INGEST, *argv], capture_output=True, text=True, encoding="utf-8", env=e.env, timeout=120)
    return r.returncode, r.stdout + r.stderr


class CliTests(unittest.TestCase):
    def setUp(self):
        self.e = H.Env(ack=False)
        self.addCleanup(self.e.close)

    def test_exit_codes_of_the_real_process(self):
        self.assertEqual(proc(self.e, "meetings", "run")[0], 5)
        self.assertEqual(proc(self.e, "mail", "run", "--source", "com")[0], 5)
        self.assertEqual(proc(self.e, "ack-infosec")[0], 0)
        self.assertEqual(proc(self.e, "mail", "run", "--source", "com")[0], 4)  # no --experimental: refused before anything is opened
        self.e.P.drop.mkdir(parents=True)
        (self.e.P.drop / "Weekly Review-20261007_090000-Meeting Transcript.vtt").write_text(H.vtt(), "utf-8")
        code, out = proc(self.e, "meetings", "run", "--no-digest", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["counts"]["written"], 1)
        code, out = proc(self.e, "status", "--json")
        st = json.loads(out)
        self.assertEqual((code, st["meetings_files"], st["drop_waiting"], st["infosec_ack"]), (0, 1, 0, True))
        self.assertEqual(proc(self.e, "config", "get", "no_such_key")[0], 4)
        self.assertEqual(proc(self.e, "nonsense")[0], 2)

    def test_setup_prints_the_install_command_and_only_runs_it_with_apply(self):
        self.assertEqual(proc(self.e, "setup")[0], 4)  # no knowledge_python yet
        log = Path(self.e.tmp.name) / "setup.log"
        if os.name == "nt":
            py = self.e.bin / "fakepy.cmd"
            py.write_text(f'@echo off\r\necho %DO_NOT_TRACK% %PIP_DISABLE_PIP_VERSION_CHECK% %*> "{log}"\r\n', "utf-8")
        else:
            py = self.e.bin / "fakepy"
            py.write_text(f'#!/bin/sh\necho "$DO_NOT_TRACK $PIP_DISABLE_PIP_VERSION_CHECK $@" > "{log}"\n', "utf-8")
            py.chmod(0o755)
        cfg = json.loads((self.e.wb / "config.json").read_text("utf-8"))
        (self.e.wb / "config.json").write_text(json.dumps({**cfg, "knowledge_python": str(py)}), "utf-8")
        code, out = proc(self.e, "setup")
        self.assertEqual(code, 0)
        self.assertIn("would run", out)
        self.assertIn("requirements.txt", out)
        self.assertFalse(log.exists())
        code, out = proc(self.e, "setup", "--apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(log.read_text("utf-8").split()[:5], ["1", "1", "-m", "pip", "install"])

    def test_purge_logout_and_the_age_limit(self):
        e = H.Env()
        self.addCleanup(e.close)
        e.P.drop.mkdir(parents=True)
        for name, when in (("Old Review", NOW - timedelta(days=40)), ("New Review", NOW)):
            (e.P.drop / f"{name}.vtt").write_text(H.vtt(), "utf-8")
            (e.P.drop / f"{name}.meta.json").write_text(json.dumps({"title": name, "start": "2026-10-07T09:00:00Z"}), "utf-8")
            with mock.patch.object(common, "clock", lambda when=when: when):
                self.assertEqual(e.run("meetings", "run", "--no-digest")[0], 0)
        self.assertEqual(len(list(e.P.captured.glob("meetings/*/*.md"))), 2)
        with mock.patch.object(common, "clock", lambda: NOW):
            code, out = e.run("purge", "--source", "meetings", "--older-than", "30")
        self.assertEqual((code, json.loads(out)), (0, {"source": "meetings", "removed": 1, "kept": 1}))
        self.assertEqual([p.name for p in e.P.captured.glob("meetings/*/*.md")][0][11:21], "new-review")
        self.assertEqual(json.loads(e.run("purge", "--source", "meetings")[1])["removed"], 1)
        self.assertEqual((list(e.P.captured.glob("meetings/**/*.md")), list(e.P.drop_done.rglob("*.vtt"))), ([], []))
        # outlook: the files go and so does the checkpoint, so the next run reads the folder again
        src = FakeMailSource()
        src.add_store("s1", "Mailbox A")
        src.add("s1", "Inbox", "m1", "c1", "Hello", "2026-10-01T09:00:00Z", text="Hi there.")
        e.run("mail", "run", "--experimental", "--source", "com", "--no-digest", hooks={"source": src})
        self.assertTrue((e.P.state / "mail-checkpoint.json").exists())
        self.assertEqual(json.loads(e.run("status", "--json")[1])["outlook_files"], 1)
        self.assertEqual(json.loads(e.run("purge", "--source", "outlook")[1])["removed"], 1)
        self.assertFalse((e.P.state / "mail-checkpoint.json").exists())
        for n in ("graph-token.bin", "graph-meetings.json", "graph-mail-delta.json"):
            (e.P.state / n).write_bytes(b"x")
        self.assertEqual(e.run("logout")[0], 0)
        self.assertEqual([p.name for p in e.P.state.glob("graph-*")], [])


if __name__ == "__main__":
    unittest.main()
