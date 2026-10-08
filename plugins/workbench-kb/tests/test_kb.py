"""Tests for the workbench-kb tools, run against a throwaway copy of kb-template. Run:
    python -m unittest discover -s plugins/workbench-kb/tests
Each test drives the scripts as subprocesses, the way the save skill does."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
SCRIPTS = PLUGIN / "scripts"
REPO = PLUGIN.parent.parent
L, R = "[" * 2, "]" * 2          # KB link brackets, built so this file holds no literal link
CORE_SCRIPTS = REPO / "plugins" / "workbench-core" / "scripts"
HAS_GIT = shutil.which("git") is not None
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

    # ── the driver ──
    def test_pre_on_fresh_kb(self):
        rc, out = self.driver("--pre")
        self.assertEqual(rc, 0)
        self.assertTrue(Path(out["ac_base"]).exists())
        self.assertEqual(out["mode_hint"], "inline")
        self.assertIn("ops", out["domains"])
        self.assertGreater(out["ac_bytes_left"], 0)

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

    @unittest.skipUnless(HAS_GIT, "git not installed")
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

    @unittest.skipUnless(HAS_GIT, "git not installed")
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
        self.assertIn({"path": "infra/HOT.md", "via": "links to"}, json.loads(out))
        self.note("ops/later.md", "---\ntitle: later\n---\nzebracrossing appears only here\n")
        rc, out, _ = self.run_py("kb_search.py", "zebracrossing", "--json")
        res = json.loads(out)
        self.assertTrue(res["rebuilt"])
        self.assertEqual(res["hits"][0]["path"], "ops/later.md")

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


class Shared(unittest.TestCase):
    def test_secretscan_copies_are_identical(self):
        self.assertEqual((SCRIPTS / "secretscan.py").read_bytes(), (CORE_SCRIPTS / "secretscan.py").read_bytes(),
                         "edit both copies of secretscan.py together")

    def test_secretscan_shapes(self):
        sys.path.insert(0, str(SCRIPTS))
        import secretscan
        pos = [KEY, "gh" + "p_" + "A" * 36, "-----BEGIN " + "RSA PRIVATE KEY-----", "API_TOKEN=" + "abc123" * 4,
               "postgres://app:" + "s3cretpw9" + "@db.example.com/x", "xox" + "b-" + "1" * 24]
        neg = ["API_TOKEN=<YOUR_TOKEN>", "password: ${DB_PASSWORD}", "sk-agent-notes-for-the-team-2026",
               "token = process.env.API_TOKEN", "AKIA is the prefix of AWS key ids"]
        for s in pos:
            self.assertTrue(secretscan.scan_text(s), f"missed: {s[:12]}...")
        for s in neg:
            self.assertFalse(secretscan.scan_text(s), f"false positive: {s}")
        self.assertNotIn(KEY, json.dumps(secretscan.findings(f"x {KEY}")))


if __name__ == "__main__":
    unittest.main()
