"""The post-update marker in the SessionStart hook: ONE short line while <workbench home>/state/post-update-verify.json exists, nothing
when it does not. Run: python -m unittest discover -s plugins/workbench-core/scripts/tests
The hook runs as a subprocess with a temp Claude home, workbench home and knowledge base; nothing of this PC is read."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
MARKER = "post-update-verify.json"


class PostUpdate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-postupd-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.kb, self.managed = self.tmp / "kb", self.tmp / "managed"
        for d in (self.kb, self.managed, self.tmp / "claude"):
            d.mkdir()
        (self.kb / "active-context.md").write_text("# active\n", encoding="utf-8")
        self.state = self.tmp / "claude" / "workbench" / "state"
        self.state.mkdir(parents=True)
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.tmp / "claude"), "WORKBENCH_KB_ROOT": str(self.kb),
                    "GUARDS_LOG_DIR": str(self.tmp / "logs"), "WORKBENCH_POLICY_DIRS": str(self.managed), "PYTHONIOENCODING": "utf-8"}

    def context(self, source="startup"):
        r = subprocess.run([sys.executable, "-S", str(SCRIPTS / "session_start.py")], capture_output=True, text=True, encoding="utf-8",
                           env=self.env, timeout=120, input=json.dumps({"session_id": "s1", "source": source}))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    def lines(self, ctx):
        return [x for x in ctx.splitlines() if "post-update verify" in x.lower()]

    def test_no_marker_no_line(self):
        self.assertEqual(self.lines(self.context()), [])

    def test_a_marker_adds_exactly_one_short_line_that_names_the_command(self):
        (self.state / MARKER).write_text(json.dumps({"version": "0.3.2", "time": "2026-10-09T08:00:00Z", "from_version": "0.3.1"}),
                                         encoding="utf-8")
        ctx = self.context()
        hit = self.lines(ctx)
        self.assertEqual(len(hit), 1, hit)
        line = hit[0]
        self.assertLessEqual(len(line), 420, "one short line")
        self.assertIn("kit 0.3.2", line)
        self.assertIn("on the user's next message", line)
        self.assertIn((Path(sys.executable).as_posix() + " "), line.replace("\\", "/"))
        self.assertIn("kit/bootstrap/kit_update.py verify", line)
        self.assertIn("live guard test", line)
        self.assertIn("timeout 600000", line)
        self.assertIn("on exit 6 run it again", line)
        self.assertEqual(ctx.count("kit_update.py"), 1, "named once")

    def test_it_comes_back_after_a_clear_or_a_compaction_until_the_verify_has_run_and_then_it_is_gone(self):
        (self.state / MARKER).write_text(json.dumps({"version": "0.3.2", "time": "2026-10-09T08:00:00Z"}), encoding="utf-8")
        for source in ("startup", "clear", "compact", "resume"):
            self.assertEqual(len(self.lines(self.context(source))), 1, source)
        (self.state / MARKER).unlink()                     # what `kit_update.py verify` does when it has run
        for source in ("startup", "clear"):
            self.assertEqual(self.lines(self.context(source)), [], source)

    def test_an_unreadable_or_empty_marker_never_breaks_the_hook(self):
        for body in ("{broken", "", "[]", "{}"):
            (self.state / MARKER).write_text(body, encoding="utf-8")
            self.assertEqual(self.lines(self.context()), [], body)

    def test_a_marker_without_a_version_still_gets_the_line(self):
        (self.state / MARKER).write_text(json.dumps({"time": "2026-10-09T08:00:00Z"}), encoding="utf-8")
        self.assertIn("kit unknown", self.lines(self.context())[0])


if __name__ == "__main__":
    unittest.main()
