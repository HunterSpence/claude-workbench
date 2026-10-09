"""Tests for model_sweep.py: a fictional retiring id, throwaway folders and throwaway git repositories, no network."""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: nothing here skips; a missing git fails

import io  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest import mock  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import model_sweep as ms  # noqa: E402

PAT = r"claude-oldmodel-\d"
CONTROL = "model: claude-oldmodel-1"
HEADER = "repo\tpath_glob\tline_regex\treason\n"
SECRET = "SENTINEL-" + "k" * 12


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.addCleanup(self._t.cleanup)
        self.allow = self.tmp / "allow.tsv"
        self.allow.write_text(HEADER, encoding="utf-8")

    def repo(self, name, files):
        d = self.tmp / name
        d.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="")
        return d

    def sweep(self, repos, pattern=PAT, control=CONTROL):
        out, err = io.StringIO(), io.StringIO()
        rc = ms.sweep(pattern, control, self.allow, repos, out, err)
        return rc, out.getvalue().splitlines(), err.getvalue()

    def rows(self, *rows):
        self.allow.write_text(HEADER + "".join("\t".join(r) + "\n" for r in rows), encoding="utf-8")


class Gate(Base):
    def test_an_unowned_hit_exits_1_and_prints_only_path_and_line(self):
        r = self.repo("alpha", {"src/app.txt": f"one\ntwo\nuse claude-oldmodel-2 {SECRET}\n", "ok.txt": "clean\n"})
        rc, out, err = self.sweep([r])
        self.assertEqual((rc, out), (1, ["alpha/src/app.txt:3"]))
        self.assertNotIn(SECRET, "\n".join(out) + err)
        self.assertNotIn("oldmodel", "\n".join(out) + err)

    def test_a_clean_sweep_exits_0(self):
        self.assertEqual(self.sweep([self.repo("alpha", {"a.txt": "nothing here\n"})])[:2], (0, []))

    def test_a_covering_row_needs_repo_glob_and_regex_to_all_match(self):
        r = self.repo("alpha", {"docs/old.md": "history: claude-oldmodel-1 retired\n"})
        self.rows(("alpha", "docs/*", "history", "kept as history"))
        self.assertEqual(self.sweep([r])[:2], (0, []))
        for row in (("beta", "docs/*", "history", "x"), ("alpha", "src/*", "history", "x"), ("alpha", "docs/*", "present", "x")):
            self.rows(row)
            self.assertEqual(self.sweep([r])[:2], (1, ["alpha/docs/old.md:1"]), row)

    def test_a_row_covers_only_the_lines_its_regex_finds(self):
        r = self.repo("alpha", {"docs/old.md": "history: claude-oldmodel-1\nlive: claude-oldmodel-1\n"})
        self.rows(("alpha", "docs/*", "^history", "kept"))
        self.assertEqual(self.sweep([r])[:2], (1, ["alpha/docs/old.md:2"]))

    def test_several_repos_are_each_reported_under_their_own_name(self):
        a = self.repo("alpha", {"a.txt": "claude-oldmodel-1\n"})
        b = self.repo("beta", {"deep/b.txt": "x\nclaude-oldmodel-3\n"})
        self.assertEqual(self.sweep([a, b])[:2], (1, ["alpha/a.txt:1", "beta/deep/b.txt:2"]))

    def test_crlf_files_and_binary_files(self):
        r = self.repo("alpha", {"win.txt": "a\r\nb claude-oldmodel-1\r\n"})
        (r / "blob.bin").write_bytes(b"\0\0claude-oldmodel-1\0")
        self.assertEqual(self.sweep([r])[:2], (1, ["alpha/win.txt:2"]))

    def test_the_walk_skips_the_git_folder(self):
        r = self.repo("alpha", {"a.txt": "clean\n", ".git/config": "claude-oldmodel-1\n"})
        self.assertEqual(self.sweep([r])[:2], (0, []))


class GitRepos(Base):
    def git(self, d, *args):
        subprocess.run(["git", "-C", str(d), *args], check=True, capture_output=True)

    def test_only_tracked_files_count_in_a_work_tree(self):
        r = self.repo("alpha", {"tracked.txt": "claude-oldmodel-1\n", "untracked.txt": "claude-oldmodel-1\n"})
        self.git(r, "init", "-q")
        self.git(r, "add", "tracked.txt")
        self.assertEqual(self.sweep([r])[:2], (1, ["alpha/tracked.txt:1"]))

    def test_a_subfolder_of_a_repository_is_walked_not_listed(self):
        r = self.repo("alpha", {"sub/in.txt": "claude-oldmodel-1\n", "top.txt": "claude-oldmodel-1\n"})
        self.git(r, "init", "-q")
        self.assertEqual(self.sweep([r / "sub"])[:2], (1, ["sub/in.txt:1"]))


class Template(unittest.TestCase):
    def test_the_shipped_allowlist_template_is_valid_and_excuses_nothing(self):
        self.assertEqual(ms.load_allowlist(HERE / "allowlist.template.tsv"), [])


class Unusable(Base):
    def test_every_gate_failure_is_exit_2(self):
        r = self.repo("alpha", {"a.txt": "claude-oldmodel-1\n"})
        self.assertEqual(self.sweep([r], pattern="(")[0], 2)
        self.assertEqual(self.sweep([r], control="nothing to see")[0], 2)
        self.assertEqual(self.sweep([r], control=CONTROL + "\nsecond line")[0], 2)
        self.assertEqual(self.sweep([self.tmp / "missing"])[0], 2)
        self.assertEqual(self.sweep([r, self.tmp / "missing"])[0], 2, "one missing folder fails the whole run")
        self.assertEqual(self.sweep([self.repo("empty", {})])[0], 2)

    def test_a_malformed_allowlist_is_exit_2(self):
        r = self.repo("alpha", {"a.txt": "clean\n"})
        for text in ("alpha\ta\tb\tc\n", HEADER + "alpha\tdocs/*\tx\t\n", HEADER + "alpha\tdocs/*\t(\treason\n",
                     HEADER + "alpha\tdocs/*\tx\n", ""):
            self.allow.write_text(text, encoding="utf-8")
            self.assertEqual(self.sweep([r])[0], 2, repr(text))
        self.allow.unlink()
        self.assertEqual(self.sweep([r])[0], 2)

    def test_the_positive_control_fails_the_run_when_the_scan_cannot_see_it(self):
        r = self.repo("alpha", {"a.txt": "clean\n"})
        with mock.patch.object(ms, "scan", return_value=(0, [], 1)):
            self.assertEqual(self.sweep([r])[0], 2)
        with mock.patch.object(ms, "scan", return_value=(2, ["control/control.txt:1", "control/control.txt:2"], 1)):
            self.assertEqual(self.sweep([r])[0], 2)


class Cli(Base):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(HERE / "model_sweep.py"), *args], capture_output=True, text=True)

    def test_exit_codes_and_streams_through_the_command_line(self):
        r = self.repo("alpha", {"a.txt": f"x claude-oldmodel-1 {SECRET}\n"})
        args = ("--pattern", PAT, "--control", CONTROL, "--allowlist", str(self.allow), "--repos", str(r))
        p = self.run_cli(*args)
        self.assertEqual((p.returncode, p.stdout.strip()), (1, "alpha/a.txt:1"))
        self.assertIn("1 not allowlisted", p.stderr)
        self.assertNotIn(SECRET, p.stdout + p.stderr)
        self.rows(("alpha", "a.txt", "x claude", "known"))
        p = self.run_cli(*args)
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_missing_arguments_are_a_usage_error(self):
        self.assertEqual(self.run_cli("--pattern", PAT).returncode, 2)

    def test_self_test_is_one_offline_line(self):
        p = self.run_cli("--self-test")
        self.assertEqual((p.returncode, len(p.stdout.strip().splitlines())), (0, 1), p.stderr)


if __name__ == "__main__":
    if shutil.which("git") is None:
        raise SystemExit("git is required for these tests")
    unittest.main()
