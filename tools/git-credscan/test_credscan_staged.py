import os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "credscan_staged.py"
KEY = "AKIA" + "Q" * 16          # built at runtime: this file holds no credential shape


@unittest.skipUnless(shutil.which("git"), "needs git")
class CredscanStaged(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="credscan-"))
        self.git("init", "-q")
        self.git("config", "user.email", "dev@example.com")
        self.git("config", "user.name", "Dev Example")
        (self.d / "old.txt").write_text("seed\n")
        self.git("add", ".")
        self.git("commit", "-qm", "seed")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def git(self, *a):
        return subprocess.run(["git", "-C", str(self.d), *a], capture_output=True, text=True, encoding="utf-8", errors="replace")

    def run_scan(self, *a):
        return subprocess.run([sys.executable, str(SCRIPT), *a], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=self.d)

    def test_blocks_staged_credential_masked(self):
        (self.d / "conf.py").write_text(f"x = 1\nkey = '{KEY}'\n")
        self.git("add", "conf.py")
        r = self.run_scan()
        self.assertEqual(r.returncode, 1)
        self.assertIn("conf.py:2 AKIA", r.stdout)
        self.assertNotIn(KEY, r.stdout + r.stderr, "the value is never printed")

    def test_clean_and_unstaged_pass(self):
        (self.d / "a.py").write_text("print('hello')\n")
        self.git("add", "a.py")
        (self.d / "b.py").write_text(f"k = '{KEY}'\n")          # not staged: not this commit's business
        r = self.run_scan()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_only_added_lines(self):
        (self.d / "c.py").write_text(f"k = '{KEY}'\n")
        self.git("add", "c.py")
        self.git("commit", "-qm", "already in history")   # no hook installed in this test
        (self.d / "c.py").write_text(f"k = '{KEY}'\nok = 2\n")
        self.git("add", "c.py")
        self.assertEqual(self.run_scan().returncode, 0)

    def test_install_hook_blocks_commit_and_never_overwrites(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--install", str(self.d)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (self.d / "conf.py").write_text(f"key = '{KEY}'\n")
        self.git("add", "conf.py")
        c = self.git("commit", "-qm", "should fail")
        self.assertNotEqual(c.returncode, 0, "the installed hook blocks the commit")
        r = subprocess.run([sys.executable, str(SCRIPT), "--install", str(self.d)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 2)
        self.assertIn("already exists", r.stdout)

    def test_quoted_path(self):
        (self.d / 'we"ird.py').write_text(f"k = '{KEY}'\n") if os.name != "nt" else (self.d / "caf\u00e9.py").write_text(f"k = '{KEY}'\n")
        self.git("add", ".")
        r = self.run_scan()
        self.assertEqual(r.returncode, 1)
        self.assertTrue('we"ird.py:1' in r.stdout or "caf\u00e9.py:1" in r.stdout, r.stdout)

    def test_fails_closed_outside_a_repo(self):
        out = Path(tempfile.mkdtemp(prefix="norepo-"))
        try:
            r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=out,
                               env={**os.environ, "GIT_CEILING_DIRECTORIES": str(out.parent)})
            self.assertEqual(r.returncode, 2)
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
