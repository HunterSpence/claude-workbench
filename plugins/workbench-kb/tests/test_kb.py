"""Tests for the workbench-kb tools, run against a throwaway copy of kb-template. Run:
    python -m unittest discover -s plugins/workbench-kb/tests
Each test drives the scripts as subprocesses, the way the save skill does."""
import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
SCRIPTS = PLUGIN / "scripts"
REPO = PLUGIN.parent.parent
L, R = "[" * 2, "]" * 2          # KB link brackets, built so this file holds no literal link
CORE_SCRIPTS = REPO / "plugins" / "workbench-core" / "scripts"
HAS_GIT = shutil.which("git") is not None
REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"


def needs_git(fn):
    """Skip without git, but fail instead under WB_REQUIRE_ALL=1 (a skipped test proves nothing)."""
    @functools.wraps(fn)
    def run(self, *a, **k):
        if not HAS_GIT:
            if REQUIRE:
                self.fail("git is not installed")
            self.skipTest("git not installed")
        return fn(self, *a, **k)
    return run
KEY = "AKIA" + "Z" * 16          # built at runtime: this file holds no credential shape


class KB(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-kb-"))
        self.root = self.tmp / "kb-root"
        shutil.copytree(REPO / "kb-template", self.root)
        self.env = {**os.environ, "WORKBENCH_KB_ROOT": str(self.root), "CLAUDE_CONFIG_DIR": str(self.tmp / "claude"),
                    "CLAUDE_CODE_SESSION_ID": "sess-a", "SAVE_LOCK_TIMEOUT": "5", "PYTHONIOENCODING": "utf-8"}
        self.env.pop("KB_INDEX_DB", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_py(self, script, *args, env=None, folder=SCRIPTS, stdin=None):
        r = subprocess.run([sys.executable, str(folder / script), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", env={**self.env, **(env or {})}, timeout=120, input=stdin)
        return r.returncode, r.stdout, r.stderr

    def driver(self, *args, env=None):
        rc, out, err = self.run_py("save_driver.py", *args, env=env)
        try:
            return rc, json.loads(out)
        except ValueError:
            self.fail(f"save_driver printed no JSON (rc={rc}): {out[:300]} {err[:300]}")

    def note(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def hold(self, lock):
        """A child process holding `lock` until its stdin closes; returns it once the lock is taken."""
        code = ("import sys\nsys.path.insert(0, sys.argv[1])\nimport savelock\n"
                "with savelock.filelock(sys.argv[2], timeout=20):\n    print('locked', flush=True)\n    sys.stdin.readline()\n")
        p = subprocess.Popen([sys.executable, "-c", code, str(SCRIPTS), str(lock)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
        self.assertEqual(p.stdout.readline().strip(), "locked")
        self.addCleanup(self.release, p)
        return p

    @staticmethod
    def release(p):
        if p.poll() is None:
            p.stdin.close()
            p.wait(timeout=30)
        p.stdout.close()

    # ── the driver ──
    def test_pre_on_fresh_kb(self):
        rc, out = self.driver("--pre")
        self.assertEqual(rc, 0)
        self.assertTrue(Path(out["ac_base"]).exists())
        self.assertEqual(out["mode_hint"], "inline")
        self.assertIn("ops", out["domains"])
        self.assertGreater(out["ac_bytes_left"], 0)
        self.assertIsNone(out["last_save_minutes_ago"], "no save yet")

    def test_inbox_add_masks_credentials_and_surfaces_in_window(self):
        rc, out = self.driver("--inbox-add", f"rotated the deploy key {KEY} today")
        self.assertEqual(rc, 0)
        self.assertIn("warnings", out)
        raw = (self.root / "inbox.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(KEY, raw)
        self.assertIn("REDACTED", raw)
        rc, pre = self.driver("--pre")
        self.assertEqual(pre["inbox_pending"], 1)
        self.assertIn("rotated the deploy key", Path(pre["inbox_file"]).read_text(encoding="utf-8"))

    def test_concurrent_journal_appends_lose_nothing(self):
        code = ("import sys, subprocess\n"
                "for i in range(10): subprocess.run([sys.executable, sys.argv[1], '--inbox-add', f'p{sys.argv[2]} n{i}'],"
                " capture_output=True)\n")
        procs = [subprocess.Popen([sys.executable, "-c", code, str(SCRIPTS / "save_driver.py"), str(n)], env=self.env)
                 for n in range(2)]
        for p in procs:
            p.wait(timeout=300)
        rows = [json.loads(ln) for ln in (self.root / "inbox.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 20)

    def test_ac_write_needs_a_base(self):
        draft = self.tmp / "draft.md"
        draft.write_text("# Active context\n- new\n", encoding="utf-8")
        rc, out = self.driver("--ac-write", draft)
        self.assertEqual(rc, 2)
        rc, pre = self.driver("--pre")
        rc, out = self.driver("--ac-write", draft, "--base", pre["ac_base"])
        self.assertEqual((rc, out["status"], out["merge"]), (0, "written", "direct"))
        self.assertEqual((self.root / "active-context.md").read_text(encoding="utf-8"), "# Active context\n- new\n")

    @needs_git
    def test_ac_write_merges_another_sessions_lines(self):
        ac = self.root / "active-context.md"
        ac.write_text("# AC\n- one\n- two\n- three\n", encoding="utf-8")
        rc, pre = self.driver("--pre")
        ac.write_text("# AC\n- one\n- two (other session)\n- three\n", encoding="utf-8")   # a parallel save landed
        draft = self.tmp / "draft.md"
        draft.write_text("# AC\n- one\n- two\n- three\n- four (mine)\n", encoding="utf-8")
        rc, out = self.driver("--ac-write", draft, "--base", pre["ac_base"])
        self.assertEqual((rc, out["status"]), (0, "written"))
        text = ac.read_text(encoding="utf-8")
        self.assertIn("two (other session)", text)
        self.assertIn("four (mine)", text)
        # the same line changed on both sides is a conflict file, and the live file is untouched
        rc, pre = self.driver("--pre")
        ac.write_text(text.replace("- one", "- one (theirs)"), encoding="utf-8")
        draft.write_text(text.replace("- one", "- one (mine)"), encoding="utf-8")
        rc, out = self.driver("--ac-write", draft, "--base", pre["ac_base"])
        self.assertEqual((rc, out["status"]), (1, "conflict"))
        self.assertIn("<<<<<<<", Path(out["conflict_file"]).read_text(encoding="utf-8"))
        self.assertIn("one (theirs)", ac.read_text(encoding="utf-8"))

    def test_post_credential_gate(self):
        f = self.note("ops/leak.md", f"---\ntitle: x\n---\naws key {KEY}\n")
        rc, out = self.driver("--post", "--domains", "ops", "--note", "t", "--files", f)
        self.assertEqual(rc, 3)
        self.assertNotIn(KEY, json.dumps(out))
        rc, out = self.driver("--post", "--domains", "ops", "--note", "t", "--files", self.tmp / "missing.md")
        self.assertIn("cred_unscanned", out)

    def test_post_hot_cap_gate(self):
        self.note("ops/HOT.md", "x" * 30_000)
        rc, out = self.driver("--post", "--domains", "ops", "--note", "t")
        self.assertEqual(rc, 4)
        rc, out = self.driver("--post", "--domains", "infra", "--note", "t")   # an untouched domain does not block
        self.assertEqual(rc, 0)

    def test_post_success_is_idempotent_and_never_pushes_by_default(self):
        rc, out = self.driver("--post", "--domains", "ops", "--note", "first save")
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["cred_scan"], "CLEAN")
        self.assertTrue(out["reindex"].startswith("ok"), out["reindex"])
        self.assertTrue(out["git_commit"].startswith("skipped"))
        self.assertEqual(out["metrics"], "recorded")
        self.assertTrue(Path(out["daily_log"]).exists())
        rc, out = self.driver("--post", "--domains", "ops", "--note", "first save")
        self.assertEqual(out["metrics"], "already recorded")
        rc, pre = self.driver("--pre")
        self.assertIsNotNone(pre["last_save_minutes_ago"])
        self.assertLess(pre["last_save_minutes_ago"], 30, "a save just happened: the skip gate can use this")

    @needs_git
    def test_git_commit_local_and_push_only_on_request(self):
        g = lambda *a, cwd=self.root: subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True)  # noqa: E731
        g("init", "-q")
        g("config", "user.email", "dev@example.com")
        g("config", "user.name", "Dev Example")
        rc, out = self.driver("--post", "--domains", "ops", "--note", "s1")
        self.assertEqual((out["git_commit"], out["git_push"]), ("ok", "skipped (no --push)"))
        self.note("ops/n.md", "---\ntitle: n\n---\nbody\n")
        rc, out = self.driver("--post", "--domains", "ops", "--note", "s2", "--push")
        self.assertEqual(out["git_push"], "skipped (--push given but no remote is configured)")
        bare = self.tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        g("remote", "add", "origin", str(bare))
        g("push", "-q", "-u", "origin", "HEAD")
        self.note("ops/m.md", "---\ntitle: m\n---\nbody\n")
        rc, out = self.driver("--post", "--domains", "ops", "--note", "s3", "--push")
        self.assertEqual(out["git_push"], "ok", out)

    def test_precompact_contract_with_core_hook(self):
        (self.root / "active-context.md").write_text("# AC\n- in flight\n", encoding="utf-8")
        rc, _, _ = self.run_py("precompact.py", folder=CORE_SCRIPTS,
                               stdin=json.dumps({"session_id": "sess-a", "trigger": "auto"}))
        self.assertEqual(rc, 0)
        rc, pre = self.driver("--pre")
        self.assertTrue(pre["resume_pending"])
        self.assertTrue(any("compacted" in n for n in pre["next"]))
        rc, post = self.driver("--post", "--domains", "ops", "--note", "resume")
        self.assertEqual(post["mode"], "precompact-resume")
        self.assertIn("flag_cleared", post)
        rc, pre = self.driver("--pre")
        self.assertFalse(pre["resume_pending"])

    def test_history_rollover(self):
        old = "".join(f"## 2001-01-{d:02d} 10:00 - old task {d}\n- **Outcome:** {'x' * 3000}\n\n" for d in range(1, 21))
        self.note("ops/history.md", "# ops history\n\n" + old)
        rc, pre = self.driver("--pre")
        self.assertTrue(pre["rollovers_run"])
        self.assertTrue((self.root / "ops/history/2001-01.md").exists())
        self.assertNotIn("ops", pre["history_still_over_cap"])

    # ── search, health, demote ──
    def test_kb_eval(self):
        rc, out, err = self.run_py("kb_eval.py")
        self.assertEqual(rc, 2, "no set yet")
        rc, out, err = self.run_py("kb_eval.py", "--init")
        self.assertIn("wrote", out)
        self.assertEqual(self.run_py("kb_eval.py")[0], 2, "the placeholder set is refused")
        self.note("infra/proxy-cert.md", "---\ntitle: proxy cert\n---\n# Proxy cert\nRotate the inspection proxy "
                                         "certificate with the vendor console every quarter.\n")
        (self.root / "kb_eval_set.json").write_text(json.dumps({"cases": [
            {"q": "rotate inspection proxy certificate", "expect": ["infra/proxy-cert.md"]},
            {"q": "zebra migration plan", "expect": ["ops/zebra.md"]}]}), encoding="utf-8")
        rc, out, err = self.run_py("kb_eval.py", "--json")
        self.assertEqual(rc, 0, err)
        r = json.loads(out)
        self.assertEqual((r["cases"], r["hit@1"], r["hit@5"]), (2, 0.5, 0.5))
        self.assertEqual([m["q"] for m in r["misses"]], ["zebra migration plan"])

    def test_search(self):
        self.note("infra/proxy-certs.md", "---\ntitle: Proxy certificates\n---\n# Proxy certificates\n\n"
                  "## Fix\nPoint pip at the corporate CA bundle with pip config set global.cert.\n"
                  f"See {L}infra/HOT{R}.\n")
        rc, out, err = self.run_py("kb_search.py", "corporate CA bundle", "--json")
        hits = json.loads(out)["hits"]
        self.assertTrue(hits and hits[0]["path"] == "infra/proxy-certs.md", out + err)
        rc, out, _ = self.run_py("kb_search.py", "certificates", "--domain", "ops", "--json")
        self.assertEqual(json.loads(out)["hits"], [])
        rc, out, _ = self.run_py("kb_search.py", "--related", "infra/proxy-certs.md", "--json")
        self.assertIn({"path": "infra/HOT.md", "via": "links to", "depth": 1}, json.loads(out))
        self.note("ops/later.md", "---\ntitle: later\n---\nzebracrossing appears only here\n")
        rc, out, _ = self.run_py("kb_search.py", "zebracrossing", "--json")
        res = json.loads(out)
        self.assertTrue(res["rebuilt"])
        self.assertEqual(res["hits"][0]["path"], "ops/later.md")

    def chain(self):
        """a links to b, b links to c, c links to nothing; returns the three KB-relative paths."""
        self.note("ops/a.md", f"---\ntitle: a\n---\n# A\nsee {L}ops/b{R}\n")
        self.note("ops/b.md", f"---\ntitle: b\n---\n# B\nsee {L}ops/c{R}\n")
        self.note("ops/c.md", "---\ntitle: c\n---\n# C\nend of the chain\n")
        return "ops/a.md", "ops/b.md", "ops/c.md"

    def test_related_walks_two_hops(self):
        a, b, c = self.chain()
        rc, out, err = self.run_py("kb_search.py", "--related", a, "--json")
        self.assertEqual([(r["path"], r["depth"]) for r in json.loads(out)], [(b, 1)])
        rc, out, err = self.run_py("kb_search.py", "--related", a, "--depth", "2", "--json")
        self.assertEqual([(r["path"], r["via"], r["depth"]) for r in json.loads(out)], [(b, "links to", 1), (c, "links to", 2)])
        rc, out, err = self.run_py("kb_search.py", "--related", c, "--depth", "2", "--json")          # backlinks walk too
        self.assertEqual([(r["path"], r["via"]) for r in json.loads(out)], [(b, "linked from"), (a, "linked from")])
        self.assertNotIn("index stale", err)

    def test_related_drops_dead_links_and_says_the_index_is_stale(self):
        a, b, c = self.chain()
        self.run_py("kb_search.py", "--related", a, "--depth", "2", "--json")                      # builds the index
        self.note(b, "---\ntitle: b\n---\n# B\nthe link to c was deleted\n")                     # b no longer links to c
        rc, out, err = self.run_py("kb_search.py", "--related", a, "--depth", "2", "--no-rebuild", "--json")
        self.assertEqual([r["path"] for r in json.loads(out)], [b])
        self.assertIn("index stale", err)
        (self.root / c).unlink()                                                                    # and now the note itself is gone
        self.note(b, f"---\ntitle: b\n---\n# B\nsee {L}ops/c{R}\n")
        rc, out, err = self.run_py("kb_search.py", "--related", a, "--depth", "2", "--no-rebuild")
        self.assertIn("index stale", out)
        self.assertNotIn(c, out)
        rc, out, err = self.run_py("kb_search.py", "--related", a, "--depth", "2", "--json")        # a normal run rebuilds first
        self.assertEqual([r["path"] for r in json.loads(out)], [b])
        self.assertNotIn("index stale", err)

    def test_scope_all_finds_a_journal_line(self):
        rc, out = self.driver("--inbox-add", "decided the quokkaledger moves to a quarterly cadence")
        self.assertEqual(rc, 0)
        rc, out, _ = self.run_py("kb_search.py", "quokkaledger", "--json")
        self.assertEqual(json.loads(out)["hits"], [])
        rc, out, _ = self.run_py("kb_search.py", "quokkaledger", "--scope", "all", "--json")
        hits = json.loads(out)["hits"]
        self.assertEqual([(h["path"], h["line"]) for h in hits], [("inbox.jsonl", 1)])
        self.assertIn("quokkaledger", hits[0]["snippet"])

    def test_lock_files_live_under_the_workbench_state_folder(self):
        sys.path.insert(0, str(SCRIPTS))
        import savelock
        a, b = self.root / "inbox.jsonl", self.root / "ops" / "metrics.jsonl"
        before = sorted(p.name for p in self.root.rglob("*"))
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.tmp / "claude")}):
            la, lb = savelock.lock_for(a), savelock.lock_for(b)
            self.assertEqual(savelock.lock_for(a), la)
            self.assertEqual(savelock.lock_for(self.root / "ops" / ".." / "inbox.jsonl"), la)         # the resolved path is hashed
        self.assertNotEqual(la, lb)
        locks = self.tmp / "claude" / "workbench" / "state" / "locks"
        self.assertTrue(la.parent == lb.parent == locks and locks.is_dir())
        self.assertRegex(la.name, r"^[0-9a-f]{16}\.lock$")
        self.assertEqual(sorted(p.name for p in self.root.rglob("*")), before, "nothing is created next to the data")
        rc, out = self.driver("--inbox-add", "one journal line")                                     # the real writer uses it too
        self.assertEqual(rc, 0)
        self.assertFalse(list(self.root.rglob("*.lock")) and [p for p in self.root.rglob("*.lock") if p.name != "save.lock"])
        self.assertTrue(any(re.fullmatch(r"[0-9a-f]{16}\.lock", p.name) for p in locks.iterdir()))

    def test_health(self):
        rc, out, err = self.run_py("kb_health.py")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS  index", out)
        self.note("ops/bad.md", f"---\ntitle: bad\n---\nkey {KEY}\nsee {L}ops/nowhere{R}\n")
        rc, out, _ = self.run_py("kb_health.py")
        self.assertEqual(rc, 1)
        self.assertIn("FAIL  secrets", out)
        self.assertNotIn(KEY, out)
        self.assertIn("WARN  dead-links", out)

    def test_demote(self):
        hot = self.root / "ops/HOT.md"
        hot.write_text(hot.read_text(encoding="utf-8") + "- old fact about the build flag, error E123\n", encoding="utf-8")
        rc, out, err = self.run_py("kb_demote.py", "--domain", "ops", "--match", "build flag")
        res = json.loads(out)
        self.assertTrue(res.get("verified"), out + err)
        self.assertNotIn("error E123", hot.read_text(encoding="utf-8"))
        self.assertIn("error E123", (self.root / "ops/history.md").read_text(encoding="utf-8"))
        rc, out, _ = self.run_py("kb_demote.py", "--domain", "ops", "--match", " ")
        self.assertIn("error", json.loads(out))

    def demote_fixture(self):
        hot = self.root / "ops/HOT.md"
        hot.write_text(hot.read_text(encoding="utf-8") + "- old fact about the build flag, error E123\n", encoding="utf-8")
        return hot, hot.read_bytes()

    def demote(self, env=None):
        rc, out, err = self.run_py("kb_demote.py", "--domain", "ops", "--match", "build flag", env=env)
        return rc, json.loads(out), err

    def test_demote_waits_for_a_session_still_on_the_earlier_kits_lock(self):
        """An earlier kit kept save.lock inside the KB (<KB>/.state/locks/); save_driver still takes it while it exists,
        and so must kb_demote: a save and a demote of the same HOT.md may not interleave."""
        hot, before = self.demote_fixture()
        p = self.hold(self.root / ".state" / "locks" / "save.lock")
        rc, res, _ = self.demote(env={"SAVE_LOCK_TIMEOUT": "1"})
        self.assertEqual(rc, 1)
        self.assertIn("save lock", res["error"])
        self.assertEqual(hot.read_bytes(), before, "nothing moved while the lock was held")
        self.assertFalse((self.root / "ops/history.md").exists())
        self.release(p)
        rc, res, err = self.demote()
        self.assertEqual((rc, res.get("verified")), (0, True), err)

    def test_demote_waits_for_the_local_lock_too(self):
        hot, before = self.demote_fixture()
        key = hashlib.sha256(self.root.resolve().as_posix().lower().encode()).hexdigest()[:8]   # kb_audit.kb_key
        p = self.hold(self.tmp / "claude" / "workbench" / "kb-state" / key / "save.lock")
        rc, res, _ = self.demote(env={"SAVE_LOCK_TIMEOUT": "1"})
        self.assertEqual((rc, hot.read_bytes() == before), (1, True))
        self.assertIn("save lock", res["error"])
        self.release(p)
        self.assertEqual(self.demote()[0], 0)

    def test_demote_without_an_earlier_kits_lock_file_creates_none_in_the_kb(self):
        self.demote_fixture()
        self.assertEqual(self.demote()[0], 0)
        self.assertFalse((self.root / ".state").exists(), "the lock is local; nothing is written under the KB for it")


class Junctions(unittest.TestCase):
    """A junction inside the KB is never entered: its notes belong to the folder it points at (listed there once), and a
    junction to a folder outside the KB must not pull foreign notes in."""

    def test_kb_index_skips_a_junction(self):
        if os.name != "nt":
            self.skipTest("junctions exist only on Windows")
        tmp = Path(tempfile.mkdtemp(prefix="wb-kbj-"))
        kb, link = tmp / "kb", tmp / "kb" / "ops" / "mirror"
        try:
            (kb / "infra").mkdir(parents=True)
            (kb / "ops").mkdir()
            (kb / "infra" / "n.md").write_text("---\ntitle: n\n---\n# N\nthe quillfeather rotation note\n", encoding="utf-8")
            (tmp / "outside").mkdir()
            (tmp / "outside" / "foreign.md").write_text("---\ntitle: f\n---\n# F\nquillfeather outside the KB\n", encoding="utf-8")
            for target, name in ((kb / "infra", "mirror"), (tmp / "outside", "away")):
                r = subprocess.run(["cmd", "/c", "mklink", "/J", str(kb / "ops" / name), str(target)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, "the junction must be created: " + r.stdout + r.stderr)
            self.assertTrue((kb / "ops" / "mirror" / "n.md").is_file(), "the junction really shows the note a second time")
            env = {**os.environ, "WORKBENCH_KB_ROOT": str(kb), "CLAUDE_CONFIG_DIR": str(tmp / "claude"), "PYTHONIOENCODING": "utf-8"}
            r = subprocess.run([sys.executable, str(SCRIPTS / "kb_index.py"), "build"], capture_output=True, text=True, encoding="utf-8", env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(json.loads(r.stdout)["result"].startswith("ok (1 notes,"), r.stdout)
            r = subprocess.run([sys.executable, str(SCRIPTS / "kb_search.py"), "quillfeather", "--all-chunks", "--json"],
                               capture_output=True, text=True, encoding="utf-8", env=env)
            self.assertEqual([h["path"] for h in json.loads(r.stdout)["hits"]], ["infra/n.md"], r.stdout)
            # a KB root that is itself reached through a junction (a redirected folder) is still read: only the entries inside are skipped
            root_link = tmp / "kb-link"
            r = subprocess.run(["cmd", "/c", "mklink", "/J", str(root_link), str(kb)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = subprocess.run([sys.executable, str(SCRIPTS / "kb_index.py"), "build"], capture_output=True, text=True, encoding="utf-8",
                               env={**env, "WORKBENCH_KB_ROOT": str(root_link)})
            self.assertTrue(json.loads(r.stdout)["result"].startswith("ok (1 notes,"), r.stdout + r.stderr)
        finally:
            for link_path in (tmp / "kb-link", kb / "ops" / "mirror", kb / "ops" / "away"):
                if link_path.exists():
                    os.rmdir(link_path)      # the junction itself, never its target
            shutil.rmtree(tmp, ignore_errors=True)

    def test_only_a_mount_point_reparse_tag_counts_as_a_junction(self):
        """Python 3.10 and 3.11 have no DirEntry.is_junction: the fallback reads the reparse tag, so a OneDrive placeholder
        folder (a reparse point under another tag) is still walked."""
        sys.path.insert(0, str(SCRIPTS))
        import kb_index

        class Entry:   # no is_junction attribute, like a DirEntry before 3.12
            def __init__(self, attrs, **more):
                self.st = types.SimpleNamespace(st_file_attributes=attrs, **more)

            def stat(self, follow_symlinks=True):
                return self.st
        mount, cloud = 0xA0000003, 0x9000601A
        self.assertTrue(kb_index.is_junction(Entry(0x410, st_reparse_tag=mount)))
        self.assertFalse(kb_index.is_junction(Entry(0x410, st_reparse_tag=cloud)), "a cloud placeholder holds real notes")
        self.assertFalse(kb_index.is_junction(Entry(0x10, st_reparse_tag=0)))
        self.assertFalse(kb_index.is_junction(types.SimpleNamespace(stat=lambda follow_symlinks=True: types.SimpleNamespace())), "no attributes (not Windows)")
        self.assertTrue(kb_index.is_junction(Entry(0x410)), "a reparse point with no tag to read is skipped, not followed")


class Shared(unittest.TestCase):
    def test_secretscan_copies_are_identical(self):
        self.assertEqual((SCRIPTS / "secretscan.py").read_bytes(), (CORE_SCRIPTS / "secretscan.py").read_bytes(),
                         "edit both copies of secretscan.py together")

    def test_secretscan_shapes(self):
        sys.path.insert(0, str(SCRIPTS))
        import secretscan
        pos = [KEY, "gh" + "p_" + "A" * 36, "-----BEGIN " + "RSA PRIVATE KEY-----", "API_TOKEN=" + "abc123" * 4,
               "postgres://app:" + "s3cretpw9" + "@db.example.com/x", "xox" + "b-" + "1" * 24,
               "API_TOKEN=" + "vault" + "9f8a7b6c5d4e3f2a1b", "Authorization: Bearer " + "see-" + "A1b2C3d4" * 4,   # no prefix exempts a value
               "API_TOKEN=" + "env-9f8a7b6c5d4e3f2a1b", "sk-" + "or-v1-" + "9f" * 32, '{"key": "sk-' + "or-v1-" + "9f" * 32 + '"}',
               "Bearer " + "sess-live-" + "a9b8c7d6e5f4a3b2c1d0e9f8", "https://mcp.example.com/sse?api_key=" + "a1b2c3d4" * 4,
               "DB_PASSWORD=" + "Hq7rT2.Kx9mP4vZ8wQ1"]
        neg = ["API_TOKEN=<YOUR_TOKEN>", "password: ${DB_PASSWORD}", "sk-team-notes-for-the-wiki-2026",
               "token = process.env.API_TOKEN", "AKIA is the prefix of AWS key ids", "API_TOKEN=env:API_TOKEN_2",
               "token = self.cfg.token_v2"]
        for s in pos:
            self.assertTrue(secretscan.scan_text(s), f"missed: {s[:12]}...")
        for s in neg:
            self.assertFalse(secretscan.scan_text(s), f"false positive: {s}")
        self.assertNotIn(KEY, json.dumps(secretscan.findings(f"x {KEY}")))


if __name__ == "__main__":
    unittest.main()
