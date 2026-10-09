"""Tests for scan_legacy.py, the report-only scanner behind the cleanup skill. Run:
    python -m unittest discover -s plugins/workbench-core/skills/cleanup/scripts
Every fixture is a fictional repository built in a temporary folder."""
import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scan_legacy  # noqa: E402

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: a missing dependency fails instead of skipping
HAS_GIT = shutil.which("git") is not None
SCRIPT = HERE / "scan_legacy.py"


def needs_git(fn):
    @functools.wraps(fn)
    def run(self, *a, **k):
        if not HAS_GIT:
            if REQUIRE:
                self.fail("git is not installed")
            self.skipTest("git not installed")
        return fn(self, *a, **k)
    return run


def snapshot(root):
    return sorted((p.relative_to(root).as_posix(), p.read_bytes()) for p in Path(root).rglob("*") if p.is_file() and ".git" not in p.parts)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def put(self, rel, text="x\n", age_days=0):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        if age_days:
            t = time.time() - age_days * 86400
            os.utime(p, (t, t))
        return p

    def paths(self, **kw):
        kw.setdefault("stale_days", 0)
        return [c["path"] for c in scan_legacy.scan(self.root, **kw)["candidates"]]


class Scan(Base):
    def test_docs_marked_dead_in_front_matter_are_listed(self):
        for st in ("deprecated", "obsolete", "superseded", "archived", "dead", "legacy", "retired"):
            self.put(f"docs/{st}.md", f"---\ntitle: t\nstatus: {st}\n---\nbody\n")
        self.put("docs/live.md", "---\nstatus: active\n---\nbody\n")
        self.put("docs/draft.md", "---\nstatus: draft\n---\nbody\n")
        self.put("docs/body.md", "no front matter\nstatus: deprecated\n")
        self.put("docs/after.md", "---\ntitle: t\n---\nstatus: deprecated\n")
        got = self.paths()
        self.assertEqual(got, sorted(f"docs/{s}.md" for s in ("deprecated", "obsolete", "superseded", "archived", "dead", "legacy", "retired")))

    def test_a_dead_doc_is_listed_however_recent(self):
        self.put("docs/old.md", "---\nstatus: deprecated\n---\n")
        self.assertEqual(self.paths(stale_days=365), ["docs/old.md"])

    def test_a_script_named_nowhere_else_is_listed(self):
        self.put("scripts/orphan.sh")
        self.put("scripts/used.sh")
        self.put("README.md", "Run scripts/used.sh daily.\n")
        self.assertEqual(self.paths(), ["scripts/orphan.sh"])

    def test_any_mention_keeps_a_script_off_the_list_even_a_comment(self):
        self.put("scripts/a.ps1")
        self.put("tools/b.sh")
        self.put("bin/c.cmd")
        self.put("ci/pipeline.yml", "# nothing calls a.ps1 any more\nstep: tools/b.sh\n- bin/c.cmd\n")
        self.assertEqual(self.paths(), [])

    def test_a_script_mentioning_only_itself_is_still_listed(self):
        self.put("scripts/loop.sh", "# usage: loop.sh\n")
        self.assertEqual(self.paths(), ["scripts/loop.sh"])

    def test_python_and_javascript_modules_count_as_mentioned_by_bare_name(self):
        self.put("scripts/lib_util.py")
        self.put("scripts/helper.mjs")
        self.put("scripts/runner.py", "import lib_util\n")
        self.put("scripts/app.mjs", "import './helper'\n")
        self.put("README.md", "Run scripts/runner.py and scripts/app.mjs.\n")
        self.assertEqual(self.paths(), [])
        self.put("scripts/lonely.sh")
        self.put("notes.txt", "the word lonely appears here\n")
        self.assertEqual(self.paths(), ["scripts/lonely.sh"], "a bare name only protects a module, never a shell script")

    def test_known_entry_points_and_tests_are_not_listed(self):
        for n in ("__init__.py", "conftest.py", "main.py", "setup.py", "test_x.py", "x_test.py", "a.test.js"):
            self.put(f"scripts/{n}")
        self.put("scripts/custom_entry.py")
        self.assertEqual(self.paths(keep=("custom_entry.py",)), [])
        self.assertEqual(self.paths(), ["scripts/custom_entry.py"])
        self.assertEqual(self.paths(keep=("scripts/custom_*",)), [])

    def test_only_the_script_folders_are_checked(self):
        self.put("src/orphan.py")
        self.put("scripts/orphan.py")
        self.assertEqual(self.paths(), ["scripts/orphan.py"])
        self.assertEqual(self.paths(script_dirs=("src",)), ["src/orphan.py"])

    def test_archived_and_vendored_folders_are_ignored_both_ways(self):
        self.put("scripts/orphan.sh")
        self.put("_archive/2020/note.md", "orphan.sh was kept here\n")
        self.put("node_modules/pkg/readme.md", "orphan.sh\n")
        self.put("_archive/old.md", "---\nstatus: deprecated\n---\n")
        self.assertEqual(self.paths(), ["scripts/orphan.sh"], "a mention inside an archive does not keep a script alive")

    def test_a_script_must_be_unchanged_for_the_stale_days(self):
        self.put("scripts/fresh.sh", age_days=2)
        self.put("scripts/stale.sh", age_days=40)
        self.assertEqual(self.paths(stale_days=30), ["scripts/stale.sh"])
        self.assertEqual(self.paths(stale_days=1), ["scripts/fresh.sh", "scripts/stale.sh"])
        got = {c["path"]: c for c in scan_legacy.scan(self.root, stale_days=30)["candidates"]}
        self.assertIsNone(got["scripts/stale.sh"]["last_commit_days"], "no git: the age comes from the file, the field says so")
        self.assertIn("40 days", got["scripts/stale.sh"]["reason"])

    def test_the_scan_never_moves_or_deletes_anything(self):
        self.put("scripts/orphan.sh", "echo 1\n", age_days=90)
        self.put("docs/old.md", "---\nstatus: deprecated\n---\nbody\n")
        self.put("README.md", "hello\n")
        before = snapshot(self.root)
        self.assertEqual(len(scan_legacy.scan(self.root, stale_days=0)["candidates"]), 2)
        for args in (["--root", str(self.root)], ["--root", str(self.root), "--json", "--stale-days", "0"]):
            r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(snapshot(self.root), before, "the scanner changed the tree")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["README.md", "docs", "scripts"], "no new file or folder")

    def test_the_json_shape_and_the_exit_codes(self):
        self.put("scripts/orphan.sh", age_days=60)
        r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "--json"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(list(out), ["candidates"])
        self.assertEqual(set(out["candidates"][0]), {"path", "reason", "last_commit_days"})
        r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root / "nope")], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2)
        r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2)

    def test_the_human_output_says_it_is_report_only(self):
        self.put("docs/old.md", "---\nstatus: retired\n---\n")
        r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root)], capture_output=True, text=True, encoding="utf-8")
        self.assertIn("docs/old.md", r.stdout)
        self.assertIn("nothing was moved or deleted", r.stdout)

    def test_self_test_is_one_line_offline_and_quick(self):
        t = time.monotonic()
        r = subprocess.run([sys.executable, str(SCRIPT), "--self-test"], capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertLess(time.monotonic() - t, 10)


class WithGit(Base):
    def git(self, *a):
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        r = subprocess.run(["git", "-C", str(self.root), *a], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)

    @needs_git
    def test_the_age_comes_from_the_last_commit_and_ignored_files_are_skipped(self):
        self.put("scripts/orphan.sh")
        self.put("scripts/ignored.sh")
        self.put(".gitignore", "scripts/ignored.sh\n")
        for a in (["init", "-q"], ["config", "user.email", "dev@example.com"], ["config", "user.name", "Dev Example"],
                  ["add", "scripts/orphan.sh", ".gitignore"], ["commit", "-qm", "seed"]):
            self.git(*a)
        self.put("scripts/untracked.sh", age_days=40)           # on disk, not committed, not ignored: still scanned
        got = {c["path"]: c for c in scan_legacy.scan(self.root, stale_days=0)["candidates"]}
        self.assertEqual(sorted(got), ["scripts/orphan.sh", "scripts/untracked.sh"])
        self.assertEqual(got["scripts/orphan.sh"]["last_commit_days"], 0)
        self.assertIsNone(got["scripts/untracked.sh"]["last_commit_days"])
        self.assertEqual(self.paths(stale_days=30), ["scripts/untracked.sh"], "the committed script is a minute old; the other has no history, so its file age counts")


if __name__ == "__main__":
    unittest.main()
