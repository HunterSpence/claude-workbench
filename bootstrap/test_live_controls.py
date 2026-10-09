"""live_controls.py checks. Unit tests always run; the Live class (WB_LIVE=1, Windows) re-reads the ledger the live run
wrote and checks independently that no task, no RunOnce value and no package is left behind.
Run: WB_LIVE=1 python -m unittest bootstrap/test_live_controls.py -v   (after: live_controls.py run --apply --json)"""
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
LIVE = os.environ.get("WB_LIVE") == "1" and os.name == "nt"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import install as I  # noqa: E402
import live_controls as L  # noqa: E402
import setup as S  # noqa: E402


class Units(unittest.TestCase):
    def test_runonce_command_is_exactly_260(self):
        for home in (Path.home(), Path(tempfile.gettempdir()), Path(tempfile.gettempdir()) / ("x" * 90)):
            cmd = L.runonce_260(sys.executable, home)
            self.assertEqual(len(cmd), 260, home)
            self.assertTrue(cmd.endswith(" resume") and str(home) in cmd)

    def test_neutralise(self):
        four = lambda *n: ".".join(map(str, n))           # noqa: E731  (four-part versions are built, never written)
        raw = (f"WSL version: {four(2, 6, 1, 0)}\r\nKernel version: {four(6, 6, 87, 2)}-1\r\n"
               "* MyBox     Running  2\r\n  Ubuntu-24.04  Stopped  2\r\n")
        out = L.neutralise(raw, ["MyBox", "Ubuntu-24.04"])
        self.assertNotIn("MyBox", out)
        self.assertIn("Distro", out)
        self.assertIn("Ubuntu-24.04".replace("24.04", "9.9.9"), out)     # digits never survive, names stay readable
        self.assertFalse(re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", out), "no four-part version can remain")
        self.assertFalse(re.search(r"[0-8]", out))

    def test_apply_is_refused_without_wb_live(self):
        env = {k: v for k, v in os.environ.items() if k != "WB_LIVE"}
        r = subprocess.run([sys.executable, str(HERE / "live_controls.py"), "run", "--apply"], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2, r.stdout)
        r = subprocess.run([sys.executable, str(HERE / "live_controls.py"), "run"], env=env, capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertIn("schtasks", r.stdout)


@unittest.skipUnless(LIVE, "live controls run only with WB_LIVE=1 on Windows")
class Live(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = Path(os.environ.get("WB_LIVE_OUT") or Path(tempfile.gettempdir()) / "wb-live")
        cls.ledger = json.loads((out / "live-ledger.json").read_text(encoding="utf-8"))
        cls.steps = {s["step"]: s for s in cls.ledger["steps"]}
        cls.out = out

    def test_ledger_is_recent_and_complete(self):
        made = datetime.datetime.strptime(self.ledger["generated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        self.assertLess((datetime.datetime.now(datetime.timezone.utc) - made).total_seconds(), 6 * 3600)
        self.assertEqual(set(self.steps), {"schtasks", "runonce", "winget", "wsl"})
        self.assertTrue(self.ledger["ok"])
        for name, s in self.steps.items():
            self.assertTrue(s["ok"], (name, s["detail"]))
            self.assertEqual(s["cleanup"], "n/a" if name == "wsl" else "verified", name)

    def test_no_task_left(self):
        name = f"\\{L.FOLDER}\\live-{self.ledger['rand']}"
        self.assertNotEqual(subprocess.run(["schtasks", "/Query", "/TN", name], capture_output=True).returncode, 0)
        self.assertTrue(self.steps["schtasks"]["detail"]["test_folder_removed"])
        self.assertTrue(self.steps["schtasks"]["detail"]["battery_settings"], "Task Scheduler kept our settings")

    def test_no_runonce_value_left(self):
        self.assertIsNone(os.environ.get("WORKBENCH_FAKE_REGISTRY"))
        vals = I.reg_values(S.RUNONCE_KEY) or {}
        self.assertFalse([n for n in vals if n.lower().startswith("wb-live-")])
        self.assertEqual(self.steps["runonce"]["detail"]["length"], 260)

    def test_no_package_left(self):
        d = self.steps["winget"]["detail"]
        wid = d["package"]
        rc = subprocess.run(["winget", "list", "-e", "--id", wid, "--accept-source-agreements", "--disable-interactivity"],
                            capture_output=True).returncode & 0xFFFFFFFF
        self.assertEqual(rc, S.NOT_FOUND)
        cmd = dict(L.CANDIDATES)[wid]
        self.assertFalse((I.lad() / "Microsoft" / "WinGet" / "Links" / f"{cmd}.exe").exists())
        self.assertTrue(d["user_path_unchanged"] and d["resolved"] and d["version"])
        self.assertTrue(d.get("test_folder_removed", True))

    def test_wsl_bytes_written_neutralised(self):
        t = (self.out / "wsl-bytes.txt").read_text(encoding="utf-8")
        self.assertFalse(re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", t))
        self.assertTrue(self.steps["wsl"]["detail"]["clean_decode"])


if __name__ == "__main__":
    unittest.main()
