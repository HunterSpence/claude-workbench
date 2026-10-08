import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "onboard.py"
KEY = "AKIA" + "T" * 16          # built at runtime: this file holds no credential shape
ANSWERS = {"name": "Sam", "role_team": "backend engineer, payments team", "timezone_hours": "UTC+1, 09:00-17:30",
           "git_hosts": "git.example.com", "secret_store": "the organisation vault", "sign_off": "Sam",
           "tone": "short and direct", "repos": ["acme/payments-api"], "tools": ["VS Code", "Jira"],
           "review_norms": ["two approvals", "squash merge"], "never": ["push to main"], "work_prefs": [""]}


class Onboard(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="onboard-"))
        self.claude, self.kb = self.d / "claude", self.d / "kb"
        (self.claude / "workbench").mkdir(parents=True)
        (self.kb / "_shared").mkdir(parents=True)
        (self.kb / "_shared" / "HOT.md").write_text("# _shared\n\n## Current state\n\n## Decision heuristics\n")
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.claude), "WORKBENCH_KB_ROOT": str(self.kb)}

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def run_it(self, answers, *extra):
        p = self.d / "answers.json"
        p.write_text(json.dumps(answers))
        return subprocess.run([sys.executable, str(SCRIPT), "--answers", str(p), *extra], capture_output=True,
                              text=True, env=self.env)

    def test_writes_user_md_and_seeds_hot_idempotently(self):
        user = self.claude / "workbench" / "USER.md"
        user.write_text("# About me\n- **Name I go by:** <first name>\n")
        r = self.run_it(ANSWERS)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = user.read_text()
        self.assertIn("- **Name I go by:** Sam", text)
        self.assertIn("- two approvals", text)
        self.assertNotIn("<first name>", text)
        self.assertNotIn("<e.g.", text)
        self.assertNotIn("## How I like to work\n- \n", text, "empty answers are left out")
        self.assertTrue(list((self.claude / "workbench" / "backups").glob("onboard-*/USER.md")), "old USER.md kept")
        hot = (self.kb / "_shared" / "HOT.md").read_text()
        self.assertIn("- Repos: acme/payments-api", hot)
        self.assertLess(hot.index("## Current state"), hot.index("<!-- onboard:start -->"))
        self.assertLess(hot.index("<!-- onboard:end -->"), hot.index("## Decision heuristics"))
        self.run_it(dict(ANSWERS, repos=["acme/ledger"]))
        hot = (self.kb / "_shared" / "HOT.md").read_text()
        self.assertEqual(hot.count("<!-- onboard:start -->"), 1, "re-run replaces the block")
        self.assertIn("acme/ledger", hot)
        self.assertNotIn("acme/payments-api", hot)

    def test_refuses_credentials(self):
        r = self.run_it(dict(ANSWERS, secret_store=f"key is {KEY}"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("secret_store", r.stderr)
        self.assertNotIn(KEY, r.stdout + r.stderr)
        self.assertFalse((self.claude / "workbench" / "USER.md").exists())

    def test_dry_run_writes_nothing(self):
        r = self.run_it(ANSWERS, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Name I go by:** Sam", r.stdout)
        self.assertFalse((self.claude / "workbench" / "USER.md").exists())


if __name__ == "__main__":
    unittest.main()
