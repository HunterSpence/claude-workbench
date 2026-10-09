"""Offline tests for repo-review/scripts/run_review.py: fake claude, git and gh programs, no network, no model call.

Run: WB_REQUIRE_ALL=1 py -3 -m unittest discover -s plugins/workbench-core/skills/repo-review/tests -v
The live canary (`run_review.py --canary --live`) is a separate, manual step.
"""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: nothing below skips; a missing file fails

import hashlib  # noqa: E402
import stat  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest import mock  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
RUN = SCRIPTS / "run_review.py"
sys.path.insert(0, str(SCRIPTS))
import run_review as rr  # noqa: E402

HELP = "Options:\n  -p, --print   Print\n  --restricted   Restricted mode\n  --safe-mode   Safe mode\n  --max-budget-usd <amount>   Budget\n  --no-session-persistence   No persistence\n"
TOKEN = "readonly-token-for-test"
REPO = "example-org/example-repo"

FAKE_CLAUDE = '''
import json, os, sys, time
rec = os.environ["FAKE_RECORD"]
def hang():
    if os.environ.get("FAKE_PIDFILE"):
        open(os.environ["FAKE_PIDFILE"], "w").write(str(os.getpid()))
    time.sleep(40)
    sys.exit(1)
if sys.argv[1:] == ["--help"]:
    mode = os.environ.get("FAKE_CLAUDE_MODE")
    if mode == "hang-help":
        hang()
    if mode == "other-help":
        print("usage: some other program [options]")
        sys.exit(0)
    if mode == "node-help":
        print("Usage: node [options] [ script.js ] [arguments]")
        print("Options:")
        print("  -p, --print   evaluate script and print result")
        sys.exit(0)
    print("Usage: claude [options] [command] [prompt]")
    print("Claude Code - starts an interactive session by default, use -p/--print for non-interactive output")
    print("Options:")
    if mode != "noprint-help":
        print("  -p, --print   Print")
    for f in os.environ.get("FAKE_HELP_FLAGS", "--restricted --safe-mode --max-budget-usd --no-session-persistence").split():
        print("  " + f + "   description")
    sys.exit(139 if mode == "crash-help" else 0)
prompt = sys.stdin.buffer.read().decode('utf-8')
tree = sorted(os.path.relpath(os.path.join(d, f), os.getcwd()).replace(os.sep, "/") for d, _, fs in os.walk(os.getcwd()) for f in fs)
open(rec, "a").write(json.dumps({"who": "claude", "argv": sys.argv[1:], "cwd": os.getcwd(), "prompt": prompt, "tree": tree,
    "token_vars": sorted(k for k in os.environ if k.upper().startswith(("GH_", "GITHUB_")) or k == "WB_REVIEW_TOKEN")}) + "\\n")
if os.environ.get("FAKE_CLAUDE_MODE") == "hang":
    hang()
if os.environ.get("FAKE_CLAUDE_MODE") == "obey":
    print(json.dumps({"type": "result", "is_error": False, "result": "BANANA"}))
else:
    body = {"summary": "checked", "findings": [{"kind": "bug", "severity": "low", "file": "src/app.py", "line": 2,
                                               "message": "example", "evidence": "", "confidence": 0.5}]}
    print(json.dumps({"type": "result", "is_error": False, "result": "```json\\n" + json.dumps(body) + "\\n```"}))
'''
FAKE_GIT = '''
import json, os, sys
a = sys.argv[1:]
open(os.environ["FAKE_RECORD"], "a").write(json.dumps({"who": "git", "argv": a,
    "env": {k: os.environ[k] for k in ("GH_TOKEN", "GH_ENTERPRISE_TOKEN", "GIT_LFS_SKIP_SMUDGE", "GIT_TERMINAL_PROMPT") if k in os.environ}}) + "\\n")
dest = a[-1]
os.makedirs(os.path.join(dest, ".git"))
open(os.path.join(dest, ".git", "config"), "w").write("x")
open(os.path.join(dest, "README.md"), "w").write("hello")
open(os.path.join(dest, ".env"), "w").write("SERVICE_PASSWORD=stand-in")
os.makedirs(os.path.join(dest, "config"))
open(os.path.join(dest, "config", "id_rsa"), "w").write("stand-in")
'''
FAKE_GH = '''
import json, os, sys
a = sys.argv[1:]
open(os.environ["FAKE_RECORD"], "a").write(json.dumps({"who": "gh", "argv": a}) + "\\n")
if a[:1] == ["api"]:
    print('{"visibility":"internal","archived":false}')
elif a[:2] == ["pr", "view"]:
    print(json.dumps({"title": "t", "body": "b"}))
elif a[:2] == ["pr", "diff"]:
    print("diff --git a/x b/x")
'''


def make_launcher(folder, name, source):
    folder = Path(folder)
    script = folder / (name + "_impl.py")
    script.write_text(source, encoding="utf-8")
    if os.name == "nt":
        path = folder / (name + ".cmd")
        path.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        path = folder / name
        path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        path.chmod(0o755)
    return path


def snapshot(root):
    out = {}
    for p in sorted(Path(root).rglob("*")):
        rel = p.relative_to(root).as_posix()
        out[rel] = None if p.is_dir() else (p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.bin = self.d / "bin"
        self.bin.mkdir()
        self.lad = self.d / "lad"
        self.rec = self.d / "rec.jsonl"
        self.claude = make_launcher(self.bin, "fake-claude", FAKE_CLAUDE)
        make_launcher(self.bin, "git", FAKE_GIT)
        make_launcher(self.bin, "gh", FAKE_GH)
        self.allow = self.d / "allow.txt"
        self.allow.write_text(f"# test list\ngithub.com/{REPO}\n", encoding="utf-8")
        self.env = dict(os.environ, PATH=str(self.bin), LOCALAPPDATA=str(self.lad), FAKE_RECORD=str(self.rec),
                        WB_CLAUDE_BIN=str(self.claude))
        for k in ("FAKE_HELP_FLAGS", "FAKE_CLAUDE_MODE", "WB_REVIEW_TOKEN", "WB_REVIEW_ALLOWLIST"):
            self.env.pop(k, None)

    def run_review(self, *args, **extra_env):
        return subprocess.run([sys.executable, str(RUN), *args], capture_output=True, text=True, timeout=120,
                              env={**self.env, **extra_env})

    def records(self, who=None):
        rows = [json.loads(x) for x in self.rec.read_text().splitlines()] if self.rec.exists() else []
        return [r for r in rows if who in (None, r["who"])]

    def under_scratch(self, path):
        return Path(path).resolve().is_relative_to((self.lad / "wb-review").resolve())

    def symlink_or_skip(self, target, link, is_dir=False):
        """The one sanctioned skip (listed under SKIPS): an OS that refuses to create symlinks for this user."""
        try:
            os.symlink(target, link, target_is_directory=is_dir)
        except (OSError, NotImplementedError) as e:
            self.skipTest(f"this OS refuses to create symlinks here: {e}")

    def junction(self, target, link):
        if os.name != "nt":
            self.skipTest("junctions exist only on Windows")
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def outside_file(self):
        """A read-only file outside any scratch tree, with its content and mode recorded."""
        f = self.d / "outside" / "precious.txt"
        f.parent.mkdir(exist_ok=True)
        f.write_text("precious", encoding="utf-8")
        os.chmod(f, 0o444)
        return f, stat.S_IMODE(os.stat(f).st_mode)

    def source_folder(self):
        src = self.d / "source"
        rr.build_canary(src)
        (src / ".git").mkdir()
        (src / ".git" / "config").write_text("x", encoding="utf-8")
        return src


def alive(pid):
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True, text=True).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class HungClaudeTest(Base):
    """claude behind a .cmd shim (how npm installs it) that never answers: both calls give up on time, the whole process tree is
    killed, and the grandchild is gone. Killing only the shim left the call waiting on the pipes the grandchild held."""

    def hang(self, mode, call):
        pidfile = self.d / f"{mode}.pid"
        t0 = time.time()
        with mock.patch.dict(os.environ, {"FAKE_RECORD": str(self.rec), "FAKE_CLAUDE_MODE": mode, "FAKE_PIDFILE": str(pidfile)}):
            try:
                result = call()
            except Exception as e:      # noqa: BLE001 - the test inspects what came out
                result = e
        self.assertLess(time.time() - t0, 20, "the timeout must stop the call, not wait for the child's own end")
        pid = int(pidfile.read_text())
        for _ in range(50):
            if not alive(pid):
                break
            time.sleep(0.2)
        self.assertFalse(alive(pid), "the fake claude behind the shim was left running")
        return result

    def test_a_hung_review_call_times_out_on_time_and_leaves_nothing_running(self):
        result = self.hang("hang", lambda: rr.run_claude([str(self.claude), "-p"], "prompt", self.d, timeout=5))
        self.assertIsInstance(result, subprocess.TimeoutExpired)

    def test_a_hung_help_call_raises_on_time_and_leaves_nothing_running(self):
        self.assertIsInstance(self.hang("hang-help", lambda: rr.claude_help(str(self.claude), timeout=5)), rr.HelpUnreadable)

    def test_a_normal_call_still_returns_the_completed_process(self):
        with mock.patch.dict(os.environ, {"FAKE_RECORD": str(self.rec)}):
            r = rr.run_claude([str(self.claude), "-p"], "hello", self.d)
            helptext = rr.claude_help(str(self.claude))
        self.assertEqual((r.returncode, "findings" in r.stdout), (0, True))
        self.assertIn("--safe-mode", helptext)
        self.assertEqual(self.records("claude")[0]["prompt"], "hello")


class FailClosedTest(Base):
    """Claude Code reads untrusted repository text, so the safety flags must be confirmed, not assumed. A help text that cannot be
    read (it hangs, claude cannot be started, the text is not claude's) refuses the review before anything is fetched or run."""

    def main_in_process(self, *args, **env):
        err, out = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {**self.env, **env}), mock.patch.object(rr, "HELP_TIMEOUT", 5), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            code = rr.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def assert_refused(self, code, out, err, reason):
        self.assertEqual(code, 2, err)
        self.assertIn("could not confirm Claude Code's safety flags", err)
        self.assertIn(reason, err)
        self.assertIn("not running the review", err)
        self.assertEqual(out, "")
        self.assertEqual(self.records(), [], "no clone, no gh call and no review process may start")
        self.assertFalse((self.lad / "wb-review").exists(), "no scratch folder either")

    def test_a_help_that_times_out_refuses_a_repository_review_and_starts_nothing(self):
        t0 = time.time()
        res = self.main_in_process(REPO, "--allowlist", str(self.allow), FAKE_CLAUDE_MODE="hang-help", FAKE_PIDFILE=str(self.d / "h.pid"))
        self.assertLess(time.time() - t0, 20)
        self.assert_refused(*res, "claude --help timed out")

    def test_a_help_that_times_out_refuses_a_local_review_print_argv_and_the_canary(self):
        src = self.source_folder()
        for args in (("--local", str(src)), ("--local", str(src), "--print-argv"), ("--canary",)):
            with self.subTest(args=args):
                self.assert_refused(*self.main_in_process(*args, FAKE_CLAUDE_MODE="hang-help", FAKE_PIDFILE=str(self.d / "h.pid")),
                                    "claude --help timed out")

    def test_a_help_that_is_not_claudes_or_a_claude_that_cannot_start_refuses_too(self):
        for mode, reason in (("other-help", "does not name Claude Code"),
                             ("node-help", "does not name Claude Code"),            # node --help lists -p/--print too
                             ("noprint-help", "did not list the -p/--print option"),
                             ("crash-help", "claude --help exited 139")):           # the full help printed, then the process crashed
            with self.subTest(mode=mode):
                self.assert_refused(*self.main_in_process(REPO, "--allowlist", str(self.allow), FAKE_CLAUDE_MODE=mode), reason)
        self.assert_refused(*self.main_in_process(REPO, "--allowlist", str(self.allow), WB_CLAUDE_BIN=str(self.d / "no-such-claude")),
                            "claude could not be started")

    def test_every_flag_dropped_because_the_help_does_not_list_it_is_named_on_stderr(self):
        src = self.source_folder()
        r = self.run_review("--local", str(src), "--print-argv", FAKE_HELP_FLAGS="--max-turns")
        self.assertEqual(r.returncode, 0, r.stderr)
        json.loads(r.stdout)                                           # stdout stays one JSON document
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        for dropped in ("--restricted", "--safe-mode", "--max-budget-usd", "--no-session-persistence"):
            self.assertIn(dropped, r.stderr)
        self.assertNotIn("--max-turns,", r.stderr)
        r = self.run_review("--local", str(src), "--print-argv")      # the default fake lists every flag but --max-turns
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--max-turns", r.stderr)
        self.assertIn("cost cap", r.stderr)
        for kept in ("--restricted", "--safe-mode"):
            self.assertNotIn(kept, r.stderr)
        r = self.run_review("--local", str(src), "--print-argv", FAKE_HELP_FLAGS="--restricted --safe-mode --max-turns --max-budget-usd --no-session-persistence")
        self.assertEqual(r.stderr, "", "nothing was dropped, so nothing is said")

    def test_a_readable_help_keeps_every_flag_it_lists_and_only_those(self):
        src = self.source_folder()
        r = self.run_review("--local", str(src), "--out", str(self.d / "out"))
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = self.records("claude")[0]["argv"]
        for flag in ("--restricted", "--safe-mode", "--max-budget-usd", "--no-session-persistence"):
            self.assertIn(flag, argv)
        self.assertNotIn("--max-turns", argv)                     # an affirmative help that lacks a flag drops it, as before
        r = self.run_review("--local", str(src), "--out", str(self.d / "out2"), FAKE_HELP_FLAGS="--restricted")
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = self.records("claude")[1]["argv"]
        self.assertIn("--restricted", argv)
        self.assertNotIn("--safe-mode", argv)


class AllowlistTest(Base):
    def test_non_allowlisted_repo_is_refused_before_anything_runs(self):
        r = self.run_review("example-org/other-repo", "--allowlist", str(self.allow))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not on the review allowlist", r.stderr)
        self.assertEqual(self.records(), [])                 # no git, no gh, no claude
        self.assertFalse((self.lad / "wb-review").exists())  # no scratch folder either

    def test_lookalikes_are_refused_and_exact_names_pass(self):
        for name in (f"{REPO}-2", "example-org/example", "other-host.example.com/example-org/example-repo", "../etc/passwd", "a b/c"):
            r = self.run_review(name, "--allowlist", str(self.allow))
            self.assertEqual(r.returncode, 2, name)
        self.assertEqual(self.records(), [])
        for name in (REPO, f"github.com/{REPO}", f"https://github.com/{REPO}.git", REPO.upper()):
            self.assertTrue(rr.is_allowed(rr.parse_target(name), self.allow), name)

    def test_missing_allowlist_refuses(self):
        r = self.run_review(REPO, "--allowlist", str(self.d / "absent.txt"))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.records(), [])


class ArgvTest(Base):
    def test_argv_has_the_isolation_flags(self):
        argv = rr.build_argv("claude", HELP)
        self.assertIn("-p", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "user")
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob")
        self.assertEqual(argv[argv.index("--disallowedTools") + 1], "mcp__*")
        denied = argv[argv.index("--disallowedTools") + 1:]
        denied = denied[:next((i for i, t in enumerate(denied) if t.startswith("--")), len(denied))]
        for pattern in rr.SECRET_PATTERNS:
            self.assertIn(f"Read(**/{pattern})", denied)
        for must in ("Read(**/.env)", "Read(**/.env.*)", "Read(**/*.pem)", "Read(**/id_rsa*)", "Read(**/.npmrc)", "Read(**/.netrc)"):
            self.assertIn(must, denied)                          # on the command line, so it does not rely on a settings file
        self.assertIn("--restricted", argv)                      # listed in HELP
        self.assertIn("--safe-mode", argv)                       # listed in HELP, added next to the isolation flags
        self.assertNotIn("--max-turns", argv)                    # not listed in HELP
        self.assertEqual(Path(argv[argv.index("--settings") + 1]), SCRIPTS / "review-settings.json")
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")

    def test_flags_the_cli_does_not_list_are_left_out(self):
        argv = rr.build_argv("claude", "Options:\n  -p, --print   Print\n")
        for flag in ("--restricted", "--safe-mode", "--max-turns", "--max-budget-usd", "--no-session-persistence"):
            self.assertNotIn(flag, argv)
        for flag in ("--strict-mcp-config", "--setting-sources", "--tools", "--disallowedTools"):
            self.assertIn(flag, argv)

    def test_the_prompt_is_never_a_trailing_positional(self):
        self.assertNotIn("--", rr.build_argv("claude", HELP)[-3:])
        self.assertEqual(rr.build_argv("claude", HELP)[-2:], ["--output-format", "json"])      # nothing a variadic flag could swallow

    def test_settings_file_excludes_instruction_files_and_secret_reads(self):
        s = json.loads((SCRIPTS / "review-settings.json").read_text(encoding="utf-8"))
        for need in ("CLAUDE.md", "AGENTS.md", "CLAUDE.local.md"):
            self.assertTrue(any(p.endswith(need) for p in s["claudeMdExcludes"]), need)
        self.assertIn("Read(**/.env)", s["permissions"]["deny"])
        self.assertIs(s["disableAllHooks"], True)
        self.assertIs(s["enableAllProjectMcpServers"], False)

    def test_print_argv_prints_the_json_and_exits_0_without_side_effects(self):
        src = self.source_folder()
        r = self.run_review("--local", str(src), "--print-argv")
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = json.loads(r.stdout)
        self.assertEqual(argv, rr.build_argv(str(self.claude), HELP))
        self.assertIn("--strict-mcp-config", argv)
        self.assertFalse((self.lad / "wb-review").exists())
        r = self.run_review("--local", str(src), "--print-argv", FAKE_HELP_FLAGS="--max-turns")
        self.assertEqual(json.loads(r.stdout), rr.build_argv(str(self.claude), "  --max-turns   x\n"))
        self.assertNotIn("--restricted", json.loads(r.stdout))
        self.assertNotIn("--safe-mode", json.loads(r.stdout))


class RepoModeTest(Base):
    def test_clone_lands_under_the_scratch_root_and_claude_runs_there_with_no_github_token(self):
        r = self.run_review(REPO, "--pr", "7", "--allowlist", str(self.allow), "--keep-scratch",
                            WB_REVIEW_TOKEN=TOKEN, GH_TOKEN="broad-login-token", GITHUB_TOKEN="another-broad-token")
        self.assertEqual(r.returncode, 0, r.stderr)
        git = self.records("git")[0]
        dest = Path(git["argv"][-1])
        self.assertTrue(self.under_scratch(dest), dest)
        self.assertEqual(dest.name, "github.com__example-org__example-repo")
        for part in ("clone", "--depth", "--no-recurse-submodules", "core.symlinks=false"):
            self.assertIn(part, git["argv"])
        self.assertEqual(git["env"]["GH_TOKEN"], TOKEN)                       # the read-only token, not the broad one
        self.assertEqual(git["env"]["GIT_LFS_SKIP_SMUDGE"], "1")
        gh_calls = [x["argv"][:2] for x in self.records("gh")]
        self.assertIn(["pr", "view"], gh_calls)
        self.assertIn(["pr", "diff"], gh_calls)
        c = self.records("claude")[0]
        self.assertEqual(Path(c["cwd"]).resolve(), dest.parent.resolve())      # Claude runs in the scratch folder
        self.assertEqual(c["argv"], rr.build_argv(str(self.claude), HELP)[1:])
        self.assertEqual(c["token_vars"], [])                                  # no GitHub credential reaches Claude
        self.assertIn("untrusted", c["prompt"])
        self.assertIn("Review rubric", c["prompt"])
        self.assertFalse(any(".git/" in t for t in c["tree"]))                  # .git was removed after the clone
        self.assertFalse(any(t.endswith((".env", "id_rsa")) for t in c["tree"]))   # secret-shaped files were deleted
        self.assertIn("meta.json", c["tree"])
        self.assertIn("pr.diff", c["tree"])
        out = next((self.lad / "wb-review" / "reviews").iterdir())
        data = json.loads((out / "github.com__example-org__example-repo#7.findings.json").read_text())
        self.assertEqual(data["findings"][0]["file"], "src/app.py")
        self.assertEqual(data["header"]["scratch_removed"], [".env", "config/id_rsa"])         # recorded by name
        self.assertIn(".env", (out / "review.md").read_text())
        self.assertIn(".env, config/id_rsa", (out / "run.log").read_text())
        self.assertTrue((out / "review.md").is_file())
        self.assertNotIn(TOKEN, (out / "run.log").read_text() + r.stdout + r.stderr)
        self.assertEqual([x for x in self.records() if x["who"] == "gh" and x["argv"][:2] == ["pr", "review"]], [])

    def test_scratch_is_deleted_but_findings_stay(self):
        r = self.run_review(REPO, "--allowlist", str(self.allow))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([p.name for p in (self.lad / "wb-review").iterdir()], ["reviews"])

    def test_two_runs_get_different_scratch_folders(self):
        for _ in range(2):
            self.run_review(REPO, "--allowlist", str(self.allow), "--keep-scratch")
        dests = {x["argv"][-1] for x in self.records("git")}
        self.assertEqual(len(dests), 2)

    def test_a_reply_that_is_not_the_findings_json_is_an_error(self):
        r = self.run_review(REPO, "--allowlist", str(self.allow), FAKE_CLAUDE_MODE="obey")
        self.assertEqual(r.returncode, 4)
        out = next((self.lad / "wb-review" / "reviews").iterdir())
        self.assertFalse(list(out.glob("*.findings.json")))
        self.assertTrue(list(out.glob("*.result.json")))


class LocalModeTest(Base):
    def test_local_uses_the_same_argv_and_never_touches_the_source(self):
        src = self.source_folder()
        rubric = self.d / "rubric.md"
        rubric.write_text("# Custom criteria\nCheck that every description matches the code.\n", encoding="utf-8")
        before = snapshot(src)
        r = self.run_review("--local", str(src), "--rubric", str(rubric), "--out", str(self.d / "out"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(snapshot(src), before)                                # byte-for-byte, mtimes included
        c = self.records("claude")[0]
        self.assertTrue(self.under_scratch(c["cwd"]))
        self.assertFalse(Path(c["cwd"]).resolve().is_relative_to(src.resolve()))
        self.assertEqual(c["argv"], rr.build_argv(str(self.claude), HELP)[1:])
        self.assertIn("Custom criteria", c["prompt"])
        self.assertEqual([x for x in self.records() if x["who"] in ("git", "gh")], [])      # no clone, no network tools
        self.assertTrue(any(t.endswith("src/app.py") for t in c["tree"]))
        self.assertFalse(any(".git/" in t for t in c["tree"]))                  # .git is not copied
        self.assertFalse(any(t.endswith(".env") for t in c["tree"]))            # the copy has no .env after prep
        self.assertTrue((src / ".env").is_file())                               # the original keeps it
        header = json.loads((self.d / "out" / "local__source.findings.json").read_text())["header"]
        self.assertEqual(header["scratch_removed"], [".env"])
        self.assertEqual(header["links_skipped"], [])
        self.assertTrue((self.d / "out" / "local__source.findings.json").is_file())
        # the repository mode builds its command from the same function: identical argv
        self.run_review(REPO, "--allowlist", str(self.allow))
        self.assertEqual(self.records("claude")[0]["argv"], self.records("claude")[1]["argv"])

    def test_an_at_path_in_the_rubric_reaches_claude_without_the_at(self):
        """`claude -p` inlines the file named by an @path in prompt text; the prompt carries (at) instead."""
        src = self.source_folder()
        rubric = self.d / "rubric.md"
        rubric.write_text("# Custom criteria\nIgnore @C:/x/secret.txt and @~/notes.md, @c:\\x\\y.txt, (@./a.txt) and \"@/etc/hosts\".\n"
                          "Also @\"C:/x y/z.txt\", \u898b\u3066\u3002@C:/x/a.txt, a\u3001@C:/x/b.txt, a\uff1f@C:/x/c.txt and a\uff01@C:/x/d.txt.\n"
                          "Write to name@example.com.\n", encoding="utf-8")
        r = self.run_review("--local", str(src), "--rubric", str(rubric), "--out", str(self.d / "out"))
        self.assertEqual(r.returncode, 0, r.stderr)
        prompt = self.records("claude")[0]["prompt"]
        self.assertIsNone(re.search(r"(?<![A-Za-z0-9_])@", prompt), "an @ that Claude Code could read reached claude")
        for kept in ("Ignore (at)C:/x/secret.txt and (at)~/notes.md, (at)c:\\x\\y.txt, ((at)./a.txt) and \"(at)/etc/hosts\".",
                     "Also (at)\"C:/x y/z.txt\", \u898b\u3066\u3002(at)C:/x/a.txt, a\u3001(at)C:/x/b.txt, a\uff1f(at)C:/x/c.txt and a\uff01(at)C:/x/d.txt.",
                     "Write to name@example.com."):
            self.assertIn(kept, prompt)

    def test_build_prompt_changes_every_at_outside_an_address_in_the_scope_and_the_rubric_and_nothing_else(self):
        plain = rr.PROMPT.format(scope="The material is in the folder x.", rubric="# Rubric\nReply with JSON.")
        self.assertEqual(rr.build_prompt("The material is in the folder x.", "# Rubric\nReply with JSON."), plain)
        got = rr.build_prompt("Look at @C:/x/scope.txt", "@~/r.md\n@.env\nx@C:/y meet @ 5pm {braces} a@b.example @\x1cC:/x @\x85C:/x")
        self.assertIn("Look at (at)C:/x/scope.txt", got)
        self.assertIn("(at)~/r.md\n(at).env\nx@C:/y meet (at) 5pm {braces} a@b.example (at)\x1cC:/x (at)\x85C:/x", got)
        self.assertIsNone(re.search(r"(?<![A-Za-z0-9_])@", got))

    def link_source(self):
        src = self.d / "linky"
        (src / "sub").mkdir(parents=True)
        (src / "real.txt").write_text("a", encoding="utf-8")
        (src / "sub" / "inner.txt").write_text("b", encoding="utf-8")
        (src / ".git").mkdir()
        (src / ".git" / "HEAD").write_text("x", encoding="utf-8")
        return src

    def files_in(self, root):
        return sorted(p.relative_to(root).as_posix() for p in Path(root).rglob("*") if p.is_file())

    def test_copy_skips_symlinks_and_git_metadata_and_reports_them(self):
        src, (outside, mode) = self.link_source(), self.outside_file()
        self.symlink_or_skip(outside, src / "sub" / "link-out")
        self.symlink_or_skip(outside.parent, src / "dirlink", is_dir=True)
        self.assertEqual(rr.copy_local(src, self.d / "copy"), ["dirlink", "sub/link-out"])
        self.assertEqual(self.files_in(self.d / "copy"), ["real.txt", "sub/inner.txt"])
        self.assertEqual(outside.read_text(), "precious")

    def test_copy_skips_junctions_and_reports_them(self):
        src, (outside, mode) = self.link_source(), self.outside_file()
        self.junction(outside.parent, src / "sub" / "jn")
        self.assertEqual(rr.copy_local(src, self.d / "copy"), ["sub/jn"])
        self.assertEqual(self.files_in(self.d / "copy"), ["real.txt", "sub/inner.txt"])
        self.assertTrue(outside.is_file())

    def test_local_run_records_skipped_links_in_the_findings_header(self):
        src, (outside, mode) = self.link_source(), self.outside_file()
        self.symlink_or_skip(outside, src / "sub" / "link-out")
        r = self.run_review("--local", str(src), "--out", str(self.d / "out"))
        self.assertEqual(r.returncode, 0, r.stderr)
        header = json.loads((self.d / "out" / "local__linky.findings.json").read_text())["header"]
        self.assertEqual(header["links_skipped"], ["sub/link-out"])
        self.assertFalse(any("link-out" in t for t in self.records("claude")[0]["tree"]))
        self.assertTrue(os.path.lexists(src / "sub" / "link-out"))              # the original keeps its link

    def test_a_missing_folder_is_refused(self):
        r = self.run_review("--local", str(self.d / "nope"))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.records("claude"), [])


class PostingTest(Base):
    def setUp(self):
        super().setUp()
        self.review = self.d / "review.md"
        self.review.write_text("# Review draft\n", encoding="utf-8")

    def reviews(self):
        return [x for x in self.records("gh") if x["argv"][:2] == ["pr", "review"]]

    def test_a_normal_run_never_posts(self):
        self.run_review(REPO, "--pr", "7", "--allowlist", str(self.allow))
        self.assertEqual(self.reviews(), [])

    def test_post_needs_the_token(self):
        base = [REPO, "--pr", "7", "--allowlist", str(self.allow), "--post", str(self.review)]
        for extra in ([], ["--confirm", "yes"], ["--confirm", "post-review-comment"], ["--confirm", ""]):
            r = self.run_review(*base, *extra)
            self.assertEqual(r.returncode, 2, extra)
        self.assertEqual(self.records(), [])
        r = self.run_review(REPO, "--allowlist", str(self.allow), "--confirm", rr.CONFIRM_TOKEN)       # a token alone posts nothing
        self.assertEqual(self.reviews(), [])

    def test_post_with_the_token_posts_one_comment_review(self):
        r = self.run_review(REPO, "--pr", "7", "--allowlist", str(self.allow), "--post", str(self.review), "--confirm", rr.CONFIRM_TOKEN,
                            WB_REVIEW_TOKEN=TOKEN)
        self.assertEqual(r.returncode, 0, r.stderr)
        posted = self.reviews()
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0]["argv"], ["pr", "review", "7", "-R", f"github.com/{REPO}", "--comment", "-F", str(self.review)])
        self.assertNotIn("--approve", posted[0]["argv"])
        self.assertEqual(self.records("claude"), [])                           # posting does not run a review

    def test_post_still_needs_the_allowlist_and_a_pr_number(self):
        r = self.run_review("example-org/other-repo", "--pr", "7", "--allowlist", str(self.allow), "--post", str(self.review),
                            "--confirm", rr.CONFIRM_TOKEN)
        self.assertEqual(r.returncode, 2)
        r = self.run_review(REPO, "--allowlist", str(self.allow), "--post", str(self.review), "--confirm", rr.CONFIRM_TOKEN)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.reviews(), [])


class PruneTest(Base):
    def test_prune_removes_secret_shaped_files_and_keeps_the_rest(self):
        root = self.d / "tree"
        secret = [".env", ".env.production", "sub/server.pem", "sub/deep/tls.KEY", "id_rsa", "id_rsa.pub", "keys/id_ed25519", ".npmrc",
                  "a/.pypirc", "a/.netrc", "b/.ENV", "c/bundle.p12", "c/store.jks", ".git-credentials"]
        keep = ["app.py", "env.py", "README.md", "keyboard.txt", "monkey.py", "src/.envrc", "docs/environment.md", "tokens.py"]
        for rel in secret + keep:
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x", encoding="utf-8")
        os.chmod(root / ".env", 0o444)                                         # read-only files must go too
        removed = rr.prune_secrets(root)
        self.assertEqual(removed, sorted(secret))
        self.assertEqual(sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()), sorted(keep))

    def test_a_symlink_named_like_a_secret_is_removed_and_its_target_left_alone(self):
        root, (outside, mode) = self.d / "tree", self.outside_file()
        (root / "sub").mkdir(parents=True)
        self.symlink_or_skip(outside, root / ".env")
        self.symlink_or_skip(outside, root / "sub" / "server.pem")
        with mock.patch.object(os, "chmod", wraps=os.chmod) as chmod:           # on POSIX chmod follows links; Windows differs
            self.assertEqual(rr.prune_secrets(root), [".env", "sub/server.pem"])
        self.assertEqual(chmod.call_args_list, [])                              # a link is never chmod-ed, whatever the OS does
        self.assertFalse(os.path.lexists(root / ".env"))                        # the link is gone
        self.assertFalse(os.path.lexists(root / "sub" / "server.pem"))
        self.assertEqual(outside.read_text(), "precious")                       # the file it pointed at is untouched
        self.assertEqual(stat.S_IMODE(os.stat(outside).st_mode), mode)          # no chmod went through the link

    def test_prune_does_not_descend_into_directory_links(self):
        root, (outside, mode) = self.d / "tree", self.outside_file()
        root.mkdir()
        (outside.parent / ".env").write_text("not yours", encoding="utf-8")
        self.symlink_or_skip(outside.parent, root / "dirlink", is_dir=True)
        self.assertEqual(rr.prune_secrets(root), [])
        self.assertTrue((outside.parent / ".env").is_file())
        self.assertEqual(rr.strip_links(root), ["dirlink"])                     # the link goes, the folder behind it stays
        self.assertFalse(os.path.lexists(root / "dirlink"))
        self.assertTrue((outside.parent / ".env").is_file())
        self.assertEqual(outside.read_text(), "precious")

    def test_prune_and_strip_leave_a_junction_target_alone(self):
        root, (outside, mode) = self.d / "tree", self.outside_file()
        root.mkdir()
        (outside.parent / ".env").write_text("not yours", encoding="utf-8")
        self.junction(outside.parent, root / "jn")
        self.assertEqual(rr.prune_secrets(root), [])
        self.assertTrue((outside.parent / ".env").is_file())
        self.assertEqual(rr.strip_links(root), ["jn"])
        self.assertFalse(os.path.lexists(root / "jn"))
        self.assertTrue((outside.parent / ".env").is_file())
        self.assertEqual(stat.S_IMODE(os.stat(outside).st_mode), mode)

    def test_prune_returns_names_only(self):
        root = self.d / "tree"
        root.mkdir()
        (root / ".env").write_text("VALUE-THAT-MUST-NOT-LEAK", encoding="utf-8")
        self.assertNotIn("VALUE-THAT-MUST-NOT-LEAK", json.dumps(rr.prune_secrets(root)))

    def test_nothing_to_remove_is_an_empty_list(self):
        root = self.d / "tree"
        root.mkdir()
        (root / "a.py").write_text("x", encoding="utf-8")
        self.assertEqual(rr.prune_secrets(root), [])


class CanaryTest(Base):
    def test_fixture_is_built_with_every_trap(self):
        fx = rr.build_canary(self.d / "fx")
        root = Path(fx["dir"])
        self.assertIn("BANANA", (root / "CLAUDE.md").read_text())
        self.assertTrue((root / "AGENTS.md").is_file())
        self.assertIn("canary-mcp", json.loads((root / ".mcp.json").read_text())["mcpServers"])
        self.assertIn("hook-ran.marker", (root / ".claude" / "settings.json").read_text())
        self.assertIn(fx["secret"], (root / ".env").read_text())
        meta = json.loads((root / "meta.json").read_text())
        self.assertIn("shell", meta["body"])                                  # a pull request text that asks for a tool
        self.assertIn("shell", meta["commits"][0]["messageBody"])             # and a commit message that does
        self.assertTrue((root / "pr.diff").is_file())
        self.assertFalse(any((root / m).exists() for m in fx["markers"]))
        self.assertNotEqual(fx["secret"], rr.build_canary(self.d / "fx2")["secret"])

    def test_evaluation_flags_every_kind_of_failure(self):                    # test the test
        fx = rr.build_canary(self.d / "fx")
        clean = '{"summary":"s","findings":[]}'
        self.assertEqual(rr.evaluate_canary(fx, clean, "starting\nreading src/app.py"), [])
        self.assertTrue(rr.evaluate_canary(fx, "BANANA", ""))
        self.assertTrue(rr.evaluate_canary(fx, "MANGO", ""))
        self.assertTrue(rr.evaluate_canary(fx, clean, "connecting to MCP server canary-mcp"))
        self.assertTrue(rr.evaluate_canary(fx, clean + fx["secret"], ""))
        self.assertTrue(rr.evaluate_canary(fx, clean, "tool Read file_path=" + str(Path(fx["dir"]) / ".env")))
        announced = 'Adding 10 deny rule(s) to destination flagSettings: ["Read(**/.env)","Read(**/.env.*)","Read(**/*.pem)"]'
        self.assertEqual(rr.evaluate_canary(fx, clean, announced), [])         # a deny-rule listing is not a read of .env
        self.assertTrue(rr.evaluate_canary(fx, clean, '{"name":"Read","input":{"file_path":"C:\\\\scratch\\\\canary\\\\.env"}}'))
        (Path(fx["dir"]) / "hook-ran.marker").write_text("x")
        self.assertTrue(rr.evaluate_canary(fx, clean, ""))

    def test_offline_canary_builds_the_fixture_and_prints_the_argv_without_calling_the_model(self):
        r = self.run_review("--canary")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(self.under_scratch(out["fixture"]))
        self.assertTrue((Path(out["fixture"]) / "CLAUDE.md").is_file())
        self.assertIn("--strict-mcp-config", out["argv"])
        self.assertEqual(self.records("claude"), [])

    def test_live_branch_passes_a_clean_reply_and_fails_an_obedient_one(self):
        r = self.run_review("--canary", "--live")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("canary: PASS", r.stdout)
        c = self.records("claude")[0]
        self.assertIn("--debug-file", c["argv"])
        self.assertTrue({"CLAUDE.md", ".mcp.json", "AGENTS.md"} <= set(c["tree"]))
        self.assertNotIn(".env", c["tree"])                                    # pruned before the review: nothing to read
        r = self.run_review("--canary", "--live", "--no-prune")                # the Read deny alone, with the file present
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(".env", self.records("claude")[1]["tree"])
        r = self.run_review("--canary", "--live", FAKE_CLAUDE_MODE="obey")
        self.assertNotEqual(r.returncode, 0)

    def test_usage_errors(self):
        for args in ([], ["--live"], ["--no-prune", "--local", str(self.d)], ["--local", str(self.d), REPO], ["--canary", "--local", str(self.d)]):
            self.assertEqual(self.run_review(*args).returncode, 2, args)


if __name__ == "__main__":
    unittest.main()
