"""Tests for checkpoint.py, the post-edit hook: the journal reminder names a command that exists and runs, and an edit to a
hook script is only compiled (no other process starts). Run:
    python -m unittest plugins/workbench-core/scripts/tests/test_checkpoint.py -v
Each case runs a COPY of the hook as a subprocess, under a throwaway Claude config folder and kit folder whose names hold a
space (the quoting case), so nothing of the real install is read or written."""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # acceptance runs: a missing dependency fails, never skips
SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[2]
KB_SCRIPTS = REPO / "plugins" / "workbench-kb" / "scripts"
WORD = "gu" + "ard"          # the removed feature's name, built at runtime: the hook source must not mention it
# The reminder as it read before the full command was embedded (no path, no python): the positive control.
OLD_REMINDER = ("JOURNAL CHECKPOINT (25 edits). Before your next tool call, journal one line with the save "
                "skill's journal command: save_driver.py --inbox-add \"<what changed + what is open>\" (under 2 KB, no "
                "backticks). Do not edit active-context.md directly. Then continue the user's task.")
COMMAND = re.compile(r'("[^"]+" "[^"]+save_driver\.py" --inbox-add) "<what changed \+ what is open>"')


def runnable(text):
    """(python, driver) when the text tells Claude to run `"<python>" "<driver>" --inbox-add`, both absolute paths of
    files that exist; else None. THE check the reminder must pass."""
    m = re.search(r'"([^"]+)" "([^"]+save_driver\.py)" --inbox-add', text)
    ok = m and all(os.path.isabs(x) and os.path.isfile(x) for x in m.groups())
    return m.groups() if ok else None


class Checkpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb ckpt "))
        self.claude = self.tmp / "claude home"
        self.wb = self.claude / "workbench"
        self.kb = self.tmp / "kb root"
        self.scripts = self.tmp / "my kit" / "plugins" / "workbench-core" / "scripts"   # the hook under test lives here
        self.scripts.mkdir(parents=True)
        for name in ("checkpoint.py", "_wb.py"):
            shutil.copy2(SCRIPTS / name, self.scripts / name)
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.claude), "WORKBENCH_KB_ROOT": str(self.kb),
                    "PYTHONIOENCODING": "utf-8"}
        self.env.pop("CLAUDE_CODE_SESSION_ID", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def need(self, path):
        if not Path(path).exists():
            if REQUIRE:
                self.fail(f"{path} is missing")
            self.skipTest(f"{path} is not in this checkout")

    def config(self, **kw):
        self.wb.mkdir(parents=True, exist_ok=True)
        (self.wb / "config.json").write_text(json.dumps(kw), encoding="utf-8")

    def driver(self, where):
        """A copy of the kit's driver scripts at `where`/workbench-kb/scripts; returns the save_driver.py path."""
        self.need(KB_SCRIPTS / "save_driver.py")
        dst = Path(where) / "workbench-kb" / "scripts"
        shutil.copytree(KB_SCRIPTS, dst, ignore=shutil.ignore_patterns("__pycache__"))
        return dst / "save_driver.py"

    def hook(self, event):
        r = subprocess.run([sys.executable, "-S", str(self.scripts / "checkpoint.py")], input=json.dumps(event),
                           capture_output=True, text=True, encoding="utf-8", env=self.env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else None

    def fire(self, sid="c1", agent=None):
        """One edit event with the counter one short of the threshold, so this edit fires the reminder."""
        state = self.wb / "state"
        state.mkdir(parents=True, exist_ok=True)
        (state / f"checkpoint.{sid}.json").write_text(json.dumps({"count": 24, "last_fired": None}), encoding="utf-8")
        return self.hook({"session_id": sid, "tool_name": "Edit", "tool_input": {"file_path": str(self.tmp / "x.txt")},
                          **({"agent_id": agent} if agent else {})})

    def test_the_reminder_names_a_command_that_exists_and_runs(self):
        drv = self.driver(self.wb / "kit" / "plugins")
        self.config(python=sys.executable)
        text = self.fire()
        self.assertTrue(text.startswith("JOURNAL CHECKPOINT"), text)
        self.assertIn("--inbox-add", text)
        self.assertIn("Bash tool", text)
        self.assertEqual(runnable(text), (Path(sys.executable).as_posix(), drv.as_posix()), text)
        self.assertIn(" ", drv.as_posix(), "the fixture must hold a path with a space")
        m = COMMAND.search(text)
        self.assertIsNotNone(m, text)
        r = subprocess.run([*shlex.split(m.group(1)), "journalled from the reminder"], capture_output=True, text=True,
                           encoding="utf-8", env=self.env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("journalled from the reminder", (self.kb / "inbox.jsonl").read_text(encoding="utf-8"))

    @unittest.skipUnless(os.name == "nt", "PowerShell is the Windows shell; Git Bash needs no prefix")
    def test_the_command_runs_in_powershell_once_it_has_the_ampersand(self):
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if not ps:
            if REQUIRE:
                self.fail("PowerShell is not installed")
            self.skipTest("PowerShell is not installed")
        self.driver(self.wb / "kit" / "plugins")
        self.config(python=sys.executable)
        text = self.fire()
        self.assertIn("in PowerShell put & and a space in front", text)
        cmd = COMMAND.search(text).group(1)
        run = lambda line: subprocess.run([ps, "-NoProfile", "-Command", line], capture_output=True, text=True,   # noqa: E731
                                          encoding="utf-8", env=self.env, timeout=120)
        self.assertNotEqual(run(f"{cmd} 'bare'").returncode, 0, "without the ampersand PowerShell must reject it (the premise)")
        r = run(f"& {cmd} 'journalled from powershell'")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("journalled from powershell", (self.kb / "inbox.jsonl").read_text(encoding="utf-8"))

    def test_the_old_text_fails_the_check(self):
        """Positive control: the check rejects the reminder as it read before, and a path that is not there."""
        self.assertIsNone(runnable(OLD_REMINDER))
        self.assertIsNone(runnable(f'"{sys.executable}" "{self.tmp}/none/save_driver.py" --inbox-add'.replace("\\", "/")))

    def test_driver_lookup_order(self):
        self.config(python=sys.executable)
        kit = self.wb / "kit" / "plugins" / "workbench-kb" / "scripts" / "save_driver.py"
        cache = self.claude / "plugins" / "cache" / "workbench" / "workbench-kb"
        repo = self.scripts.parents[1] / "workbench-kb" / "scripts" / "save_driver.py"
        for p in (kit, cache / "0.3.9" / "scripts" / "save_driver.py", cache / "0.3.10" / "scripts" / "save_driver.py", repo):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# stub\n", encoding="utf-8")
        os.utime(cache / "0.3.9" / "scripts" / "save_driver.py", (1_000_000_000, 1_000_000_000))
        for label, want, remove in (("installed kit first", kit, None),
                                    ("then the newest plugin-cache copy", cache / "0.3.10" / "scripts" / "save_driver.py", kit),
                                    ("then this repo's layout", repo, cache),
                                    ("then no path at all", None, repo)):
            with self.subTest(label):
                if remove is not None:
                    shutil.rmtree(remove) if remove.is_dir() else remove.unlink()
                text = self.fire()
                self.assertTrue(text.startswith("JOURNAL CHECKPOINT") and "--inbox-add" in text, text)
                got = runnable(text)
                self.assertEqual(got and got[1], want and want.as_posix(), text)

    def test_python_is_the_console_one(self):
        py_dir = self.tmp / "py dir"
        py_dir.mkdir()
        for name in ("pythonw.exe", "python.exe"):
            (py_dir / name).write_text("", encoding="utf-8")
        drv = self.driver(self.wb / "kit" / "plugins")
        for label, cfg, want in (("pythonw becomes python", {"python": str(py_dir / "pythonw.exe")}, (py_dir / "python.exe").as_posix()),
                                 ("a missing config python falls back", {"python": str(self.tmp / "gone" / "python.exe")}, Path(sys.executable).as_posix()),
                                 ("no config falls back", {}, Path(sys.executable).as_posix())):
            with self.subTest(label):
                self.config(**cfg)
                self.assertEqual(runnable(self.fire()), (want, drv.as_posix()))
        with self.subTest("a bare pythonw is looked up on PATH first"):
            bare, sfx = self.tmp / "bare dir", ".exe" if os.name == "nt" else ""
            bare.mkdir()
            for name in ("pythonw", "python"):
                (bare / (name + sfx)).write_text("", encoding="utf-8")
                (bare / (name + sfx)).chmod(0o755)
            self.env["PATH"] = str(bare) + os.pathsep + self.env.get("PATH", "")
            self.config(python="pythonw")
            got = runnable(self.fire())
            self.assertEqual(got and (os.path.normcase(got[0]), got[1]), (os.path.normcase((bare / ("python" + sfx)).as_posix()), drv.as_posix()))

    def test_an_edit_to_a_hook_script_is_only_compiled(self):
        bad, good = self.scripts / "broken.py", self.scripts / "fine.py"
        bad.write_text("def f(:\n", encoding="utf-8")
        good.write_text("x = 1\n", encoding="utf-8")
        edit = lambda f, **kw: {"session_id": "e1", "tool_name": "Edit", "tool_input": {"file_path": str(f)}, **kw}   # noqa: E731
        msg = self.hook(edit(bad))
        self.assertTrue(msg.startswith("HOOK EDIT:") and "broken.py" in msg, msg)
        self.assertTrue(self.hook(edit(bad, agent_id="a1")).startswith("HOOK EDIT:"), "a subagent's hook edit is reported too")
        self.assertIsNone(self.hook(edit(good)), "a hook script that compiles raises no alarm")
        self.assertIsNone(self.hook(edit(good, agent_id="a1")))

    def test_the_hook_starts_no_process_and_names_no_removed_feature(self):
        src = (SCRIPTS / "checkpoint.py").read_text(encoding="utf-8").lower()
        for word in ("subprocess", "pretooluse", WORD):
            self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()
