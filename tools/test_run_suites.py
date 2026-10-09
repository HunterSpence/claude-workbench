"""run_suites.py tests on throwaway git repos, plus a static check of the real tools/skips.allow.
Run: WB_REQUIRE_ALL=1 py -3 -m unittest discover -s tools -p "test_run_suites.py" -v"""
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
HAVE_GIT = bool(shutil.which("git"))
HAVE_NODE = bool(shutil.which("node"))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_suites as rs  # noqa: E402

GOOD = '''import unittest
class T(unittest.TestCase):
    def test_a(self): pass
    def test_b(self): pass
'''
SKIPPER = '''import unittest
class Flows(unittest.TestCase):
    def test_one(self): self.skipTest("fake platform")
    def test_two(self): self.skipTest("fake platform")
class T(unittest.TestCase):
    def test_a(self): pass
'''
FAILER = '''import unittest
class T(unittest.TestCase):
    def test_boom(self): self.assertEqual(1, 2, "deliberate failure marker")
'''
ENVCHECK = '''import os, unittest
class T(unittest.TestCase):
    def test_require_all_is_set(self): self.assertEqual(os.environ.get("WB_REQUIRE_ALL"), "1")
    def test_archive_exists(self): self.assertTrue(tarfile.is_tarfile(os.environ["WB_V020_ARCHIVE"]))
import tarfile
'''
NODE = '''import test from "node:test";
import assert from "node:assert";
test("passes", () => assert.ok(true));
test("is skipped", { skip: "fake" }, () => {});
'''


NODE_IMPORTING = '''import test from "node:test";
import assert from "node:assert";
import { v } from "../lib/x.mjs";
import { w } from "./fixtures/h.mjs";
test("imports resolve", () => assert.equal(v + w, 3));
'''
FAKE_NPM = '''import json, os, sys
open(os.environ["FAKE_NPM_LOG"], "a").write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\\n")
if os.environ.get("FAKE_NPM_FAIL"):
    sys.exit(3)
os.makedirs("node_modules", exist_ok=True)
'''


def json_list(*parts):
    return __import__("json").dumps([str(p) for p in parts])


def git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                   check=True, capture_output=True)


class Base(unittest.TestCase):
    def setUp(self):
        if not HAVE_GIT:
            self.fail("git is required") if REQUIRE else self.skipTest("git not installed")
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-rs-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q")

    def repo(self, files):
        for rel, text in files.items():
            f = self.root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8", newline="\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "fixtures")

    def allow(self, text):
        f = self.tmp / "skips.allow"
        f.write_text(text, encoding="utf-8", newline="\n")
        return str(f)

    def go(self, *args, env=None, unset=()):
        buf = io.StringIO()
        with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(buf):
            for k in unset:
                os.environ.pop(k, None)
            rc = rs.main(["--root", str(self.root), "--scratch", str(self.tmp / "scratch"), "--v020-ref", "HEAD",
                          "--no-cap", *args])
        return rc, buf.getvalue()


class Discovery(Base):
    def test_finds_unittest_and_node_dirs_through_git_ls_files(self):
        self.repo({"a/test_x.py": GOOD, "b/c/test_y.py": GOOD, "n/foo.test.mjs": NODE, "docs/readme.md": "x",
                   "a/helper.py": "x"})
        (self.root / "untracked").mkdir()
        (self.root / "untracked" / "test_z.py").write_text(GOOD, encoding="utf-8")
        self.assertEqual(rs.discover(self.root), [("node", "n"), ("unittest", "a"), ("unittest", "b/c")])
        self.assertEqual(rs.discover(self.root, ["b/"]), [("unittest", "b/c")])

    def test_an_unpacked_release_without_git_is_walked(self):
        plain = self.tmp / "unpacked"
        for rel in ("a/test_x.py", "n/foo.test.mjs", "n/node_modules/dep/test_dep.py", "a/__pycache__/test_x.py"):
            f = plain / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(GOOD, encoding="utf-8")
        self.assertEqual(rs.discover(plain), [("node", "n"), ("unittest", "a")])

    def test_template_directories_are_not_suites(self):
        self.repo({"a/test_x.py": GOOD, "skill/templates/py/tests/test_t.py": GOOD, "templates/n/foo.test.mjs": NODE,
                   "n/foo.test.mjs": NODE})
        self.assertEqual(rs.discover(self.root), [("node", "n"), ("unittest", "a")])

    def test_list_prints_suites_runs_nothing_and_checks_the_allow_file(self):
        self.repo({"a/test_x.py": FAILER, "n/foo.test.mjs": NODE})
        rc, out = self.go("--list", "--skips", self.allow("test_x::T.t  # reason\n"))
        self.assertEqual(rc, 0, out)
        self.assertIn("unittest a", out.replace("  ", " "))
        self.assertIn("2 suites", out)
        self.assertNotIn("FAIL", out)                      # the failing suite was not run
        rc, out = self.go("--list", "--skips", self.allow("test_x::T.t\n"))
        self.assertEqual(rc, 1)
        self.assertIn("PROBLEM", out)

    def test_the_real_tree_lists_the_node_and_unittest_suites(self):
        tracked = rs.discover(HERE.parent)
        dirs = {d for _, d in tracked}
        self.assertIn(("node", "plugins/workbench-capture/tests"), tracked)
        self.assertTrue({"bootstrap", "tools", "tools/memcap"} <= dirs)


class Running(Base):
    def test_counts_per_suite_and_exit_codes(self):
        self.repo({"a/test_x.py": GOOD, "b/test_f.py": FAILER})
        rc, out = self.go("--skips", self.allow("# none\n"))
        self.assertEqual(rc, 1)
        self.assertRegex(out, r"ok\s+a \(unittest\) ran 2 failed 0 skipped 0")
        self.assertRegex(out, r"FAIL b \(unittest\) ran 1 failed 1 skipped 0")
        self.assertIn("deliberate failure marker", out)
        self.assertIn("RESULT: FAIL", out)

    def test_a_suite_with_no_tests_is_a_failure_not_a_pass(self):
        self.repo({"a/test_none.py": "import unittest\n"})
        rc, out = self.go("--skips", self.allow("# none\n"))
        self.assertEqual(rc, 1, out)
        self.assertIn("no tests were found", out)

    def test_unlisted_skip_fails_require_all_and_the_listed_one_passes(self):
        self.repo({"a/test_x.py": SKIPPER})
        rc, out = self.go("--require-all", "--skips", self.allow("# nothing allowed\n"))
        self.assertEqual(rc, 1, out)
        self.assertIn("SKIP NOT ALLOWED: test_x::Flows.test_one", out)
        self.assertRegex(out, r"a \(unittest\) ran 1 failed 0 skipped 2")
        rc, out = self.go("--skips", self.allow("# nothing allowed\n"))          # not required: reported, not fatal
        self.assertEqual(rc, 0, out)
        self.assertIn("unlisted: test_x::Flows.test_one", out)
        rc, out = self.go("--require-all", "--skips", self.allow("test_x::Flows.*  # fake platform\n"))
        self.assertEqual(rc, 0, out)
        self.assertIn("RESULT: PASS", out)

    def test_a_stale_allow_line_is_reported_and_fails(self):
        self.repo({"a/test_x.py": SKIPPER})
        allow = self.allow("test_x::Flows.*  # fake\ntest_x::Gone.test_removed  # was deleted\ntest_nope::*  # no such module\n")
        rc, out = self.go("--require-all", "--skips", allow)
        self.assertEqual(rc, 1, out)
        self.assertIn("STALE skips.allow entry matches no test: test_x::Gone.test_removed", out)
        self.assertIn("STALE skips.allow entry matches no test: test_nope::*", out)
        rc, out = self.go("--require-all", "--only", "zzz-nothing", "--skips", allow)    # a partial run judges nothing
        self.assertNotIn("STALE", out)

    def test_a_listed_skip_that_did_not_fire_is_not_stale(self):
        self.repo({"a/test_x.py": GOOD})
        rc, out = self.go("--require-all", "--skips", self.allow("test_x::T.test_a  # skips elsewhere\n"))
        self.assertEqual(rc, 0, out)

    def test_require_all_sets_the_env_for_suites_and_the_archive_exists(self):
        self.repo({"a/test_env.py": ENVCHECK})
        env = {"WB_REQUIRE_ALL": "0", "WB_V020_ARCHIVE": ""}
        rc, out = self.go("--skips", self.allow("# none\n"), env=env)
        self.assertEqual(rc, 1, "without --require-all the suite must see WB_REQUIRE_ALL=0")
        rc, out = self.go("--require-all", "--skips", self.allow("# none\n"), env=env)
        self.assertEqual(rc, 0, out)

    def test_node_suite_counts_and_its_skip_id(self):
        if not HAVE_NODE:
            self.fail("node is required") if REQUIRE else self.skipTest("node not installed")
        self.repo({"n/foo.test.mjs": NODE})
        rc, out = self.go("--require-all", "--skips", self.allow("# none\n"))
        self.assertEqual(rc, 1, out)
        self.assertRegex(out, r"n \(node\) ran 1 failed 0 skipped 1")
        self.assertIn("foo::is skipped", out)
        rc, out = self.go("--require-all", "--skips", self.allow("foo::is skipped  # fake\n"))
        self.assertEqual(rc, 0, out)

    def test_memcap_wraps_each_suite(self):
        self.repo({"a/test_x.py": GOOD})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = rs.main(["--root", str(self.root), "--scratch", str(self.tmp / "s"), "--v020-ref", "HEAD",
                          "--skips", self.allow("# none\n"), "--mb", "512"])
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertTrue(rs.MEMCAP.is_file())


class Helpers(Base):
    def test_archive_of_a_ref_and_a_missing_ref(self):
        self.repo({"a/test_x.py": GOOD})
        tar = rs.make_archive(self.root, "HEAD", self.tmp / "out" / "v.tar")
        self.assertTrue(tarfile.is_tarfile(tar))
        with tarfile.open(tar) as t:
            self.assertIn("a/test_x.py", t.getnames())
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertIsNone(rs.make_archive(self.root, "no-such-ref", self.tmp / "out" / "w.tar"))
        self.assertIn("no 0.2.0 archive", buf.getvalue())

    def test_knowledge_python_is_used_only_for_the_find_suite(self):
        self.repo({"f/test_find.py": GOOD, "g/test_other.py": GOOD})
        with mock.patch.dict(os.environ, {"WB_KNOWLEDGE_PYTHON": "kpy"}):
            self.assertEqual(rs.suite_python(self.root, "f"), "kpy")
            self.assertEqual(rs.suite_python(self.root, "g"), sys.executable)
        with mock.patch.dict(os.environ):
            os.environ.pop("WB_KNOWLEDGE_PYTHON", None)
            self.assertEqual(rs.suite_python(self.root, "f"), sys.executable)

    def test_allow_matching_and_parsing(self):
        entries, problems = rs.load_allow(self.allow("# c\n\nm::A.b  # why\nm2::C.*  # why\nbad line\nx::y\n"))
        self.assertEqual([(m, t) for m, t, _ in entries], [("m", "A.b"), ("m2", "C.*")])
        self.assertEqual(len(problems), 2)
        self.assertTrue(rs.allowed(entries, "m2", "C.anything"))
        self.assertFalse(rs.allowed(entries, "m", "A.c"))


class KnowledgePython(Base):
    OFFICE = "skills/office-docx/scripts/tests/test_o.py"

    def test_find_and_every_office_suite_need_it_and_use_it_when_set(self):
        self.repo({"f/test_find.py": GOOD, self.OFFICE: GOOD, "skills/officer/test_p.py": GOOD, "g/test_other.py": GOOD})
        needs = lambda d: rs.needs_knowledge_python(self.root, d)           # noqa: E731
        self.assertEqual([needs("f"), needs("skills/office-docx/scripts/tests"), needs("skills/officer"), needs("g")],
                         [True, True, False, False])
        with mock.patch.dict(os.environ, {"WB_KNOWLEDGE_PYTHON": "kpy"}):
            self.assertEqual(rs.suite_python(self.root, "skills/office-docx/scripts/tests"), "kpy")
            self.assertEqual(rs.suite_python(self.root, "f"), "kpy")
            self.assertEqual(rs.suite_python(self.root, "skills/officer"), sys.executable)

    def test_require_all_without_the_knowledge_python_fails_clearly_before_running(self):
        self.repo({self.OFFICE: GOOD, "a/test_x.py": GOOD})
        rc, out = self.go("--require-all", "--skips", self.allow("# none\n"), unset=("WB_KNOWLEDGE_PYTHON",))
        self.assertEqual(rc, 2, out)
        self.assertIn("WB_KNOWLEDGE_PYTHON", out)
        self.assertIn("skills/office-docx/scripts/tests", out)
        self.assertNotIn("[1/", out, "nothing ran")
        rc, out = self.go("--require-all", "--skips", self.allow("# none\n"),
                          env={"WB_KNOWLEDGE_PYTHON": str(self.tmp / "no-such-python")})
        self.assertEqual(rc, 2, out)
        self.assertIn("not found", out)

    def test_require_all_with_it_set_runs_and_a_suite_that_does_not_need_it_is_unaffected(self):
        self.repo({self.OFFICE: GOOD, "a/test_x.py": GOOD})
        rc, out = self.go("--require-all", "--skips", self.allow("# none\n"), env={"WB_KNOWLEDGE_PYTHON": sys.executable})
        self.assertEqual(rc, 0, out)
        rc, out = self.go("--require-all", "--only", "a", "--skips", self.allow("# none\n"), unset=("WB_KNOWLEDGE_PYTHON",))
        self.assertEqual(rc, 0, out)                       # the selected suite needs no knowledge python
        rc, out = self.go("--skips", self.allow("# none\n"), unset=("WB_KNOWLEDGE_PYTHON",))
        self.assertEqual(rc, 0, out)                       # not required: falls back to this interpreter


class Prepare(Base):
    def setUp(self):
        super().setUp()
        self.log = self.tmp / "npm.log"
        fake = self.tmp / "fake_npm.py"
        fake.write_text(FAKE_NPM, encoding="utf-8", newline="\n")
        self.env = {"WB_NPM": json_list(sys.executable, fake), "FAKE_NPM_LOG": str(self.log)}
        self.repo({"n/foo.test.mjs": NODE_IMPORTING, "n/fixtures/h.mjs": "export const w = 2;\n",
                   "lib/package.json": '{"name": "x", "version": "1.0.0"}\n', "lib/x.mjs": "export const v = 1;\n",
                   "other/package.json": "{}\n"})
        self.lib = (self.root / "lib").resolve()

    def calls(self):
        return [__import__("json").loads(x) for x in self.log.read_text("utf-8").splitlines()] if self.log.exists() else []

    def test_only_the_package_a_suite_imports_from_is_found(self):
        self.assertEqual(rs.npm_dirs(self.root, "n"), [self.lib])          # not other/, not the fixture helper

    def test_prepare_runs_the_exact_install_once_and_skips_when_node_modules_exists(self):
        with mock.patch.dict(os.environ, self.env), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(rs.prepare(self.root, [("node", "n")]), [])
            self.assertEqual(rs.prepare(self.root, [("node", "n")]), [])
        (c,) = self.calls()
        self.assertEqual(c["argv"], ["install", "--ignore-scripts", "--no-audit", "--no-fund"])
        self.assertEqual(Path(c["cwd"]).resolve(), self.lib)
        self.assertTrue((self.lib / "node_modules").is_dir())

    def test_a_failed_install_is_a_problem_and_fails_the_run(self):
        with mock.patch.dict(os.environ, {**self.env, "FAKE_NPM_FAIL": "1"}), contextlib.redirect_stdout(io.StringIO()):
            (problem,) = rs.prepare(self.root, [("node", "n")])
        self.assertIn("exit 3", problem)
        rc, out = self.go("--prepare", "--skips", self.allow("# none\n"), env={**self.env, "FAKE_NPM_FAIL": "1"})
        self.assertEqual(rc, 1, out)
        self.assertIn("PROBLEM prepare failed", out)

    def test_prepare_flag_and_require_all_install_and_a_plain_run_does_not(self):
        if not HAVE_NODE:
            self.fail("node is required") if REQUIRE else self.skipTest("node not installed")
        allow = self.allow("# none\n")
        rc, out = self.go("--skips", allow, env=self.env)
        self.assertEqual((rc, self.calls()), (0, []), out)
        rc, out = self.go("--prepare", "--skips", allow, env=self.env)
        self.assertEqual((rc, len(self.calls())), (0, 1), out)
        shutil.rmtree(self.lib / "node_modules")
        rc, out = self.go("--require-all", "--skips", allow, env={**self.env, "WB_KNOWLEDGE_PYTHON": sys.executable})
        self.assertEqual((rc, len(self.calls())), (0, 2), out)
        self.assertIn("prepare: npm install in lib", out)

    def test_list_installs_nothing(self):
        rc, out = self.go("--list", "--prepare", "--skips", self.allow("# none\n"), env=self.env)
        self.assertEqual((rc, self.calls()), (0, []), out)

    def test_the_real_packages_node_modules_are_gitignored(self):
        root = HERE.parent
        if not (root / ".git").exists():
            self.skipTest("needs a git checkout of the kit (an unpacked release has none)")
        for kind, d in rs.discover(root):
            if kind != "node":
                continue
            for pkg in rs.npm_dirs(root, d):
                rel = pkg.relative_to(root.resolve()).as_posix()
                r = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", f"{rel}/node_modules/x"])
                self.assertEqual(r.returncode, 0, f"{rel}/node_modules is not gitignored")


class RealAllowList(unittest.TestCase):
    """Every real skips.allow line points at a test that exists in the tree (no run needed)."""

    def test_each_entry_names_a_real_module_class_and_method(self):
        entries, problems = rs.load_allow(HERE / "skips.allow")
        self.assertEqual(problems, [])
        self.assertGreater(len(entries), 10)
        root = HERE.parent
        files = [f for f in rs.listed(root) if f.endswith(".py")]
        for mod, tid, _ in entries:
            hits = [f for f in files if Path(f).name == mod + ".py"]
            self.assertTrue(hits, f"no file {mod}.py for {mod}::{tid}")
            src = (root / hits[0]).read_text("utf-8")
            cls, _, meth = tid.partition(".")
            self.assertRegex(src, rf"(?m)^class {re.escape(cls)}\b", f"{mod}::{tid}: no class {cls}")
            if not any(c in meth for c in "*?"):
                self.assertRegex(src, rf"(?m)^\s+def {re.escape(meth)}\(", f"{mod}::{tid}: no method {meth}")


if __name__ == "__main__":
    unittest.main()
