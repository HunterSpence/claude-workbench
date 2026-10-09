"""Tests for where the knowledge base keeps its state (locks, precompact flags, snapshots, metrics, journal windows):
on this machine under <workbench home>/kb-state/<key>/, never inside the (possibly synced) KB, plus the one-time COPY of an
earlier kit's <KB>/.state/. Run:
    python -m unittest discover -s plugins/workbench-kb/tests
Each test drives the scripts as subprocesses, the way the save skill does."""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
SCRIPTS = PLUGIN / "scripts"
REPO = PLUGIN.parent.parent
CORE_SCRIPTS = REPO / "plugins" / "workbench-core" / "scripts"
HAS_GIT = shutil.which("git") is not None
REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"


def load(name, folder):
    """A private copy of a script module, imported under a unique name."""
    spec = importlib.util.spec_from_file_location(f"{name}_state_test", folder / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(folder))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(folder))
    return mod


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-kbstate-"))
        self.root = self.tmp / "kb-root"
        shutil.copytree(REPO / "kb-template", self.root)
        self.claude = self.tmp / "claude"
        self.env = {**os.environ, "WORKBENCH_KB_ROOT": str(self.root), "CLAUDE_CONFIG_DIR": str(self.claude),
                    "CLAUDE_CODE_SESSION_ID": "sess-a", "SAVE_LOCK_TIMEOUT": "5", "PYTHONIOENCODING": "utf-8"}
        self.env.pop("KB_INDEX_DB", None)
        with mock.patch.dict(os.environ, self.env):
            self.state = load("kb_audit", SCRIPTS).state_dir(self.root)
        self.old = self.root / ".state"

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

    def put(self, folder, rel, text):
        p = folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def legacy(self, flag_for=("sess-old",)):
        """An earlier kit's <KB>/.state/: flags, snapshots, metrics and a lock file."""
        for sid in flag_for:
            self.put(self.old, f"precompact-{sid}.flag", f"precompact_fired: legacy {sid}\n")
        self.put(self.old, "snapshots/active-context-20200101-000000-1.md", "# AC\n- legacy snapshot\n")
        self.put(self.old, "snapshots/active-context-presave-legacy.md", "# AC\n- one\n")
        self.put(self.old, "save-metrics.jsonl", json.dumps({"ts": "2999-01-01T00:00Z", "key": "legacy-1", "mode": "inline",
                                                             "domains": ["ops"], "ac_hash": "x"}) + "\n")
        self.put(self.old, "locks/save.lock", "")

    def tree(self, folder):
        """{relative path: sha1 of the bytes} for every file under folder."""
        return {p.relative_to(folder).as_posix(): hashlib.sha1(p.read_bytes()).hexdigest()
                for p in sorted(folder.rglob("*")) if p.is_file()}

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


class Location(Base):
    def test_state_dir_contract_between_the_two_plugins(self):
        kb_audit = load("kb_audit", SCRIPTS)
        wb = load("_wb", CORE_SCRIPTS)
        other = self.tmp / "second-kb"
        other.mkdir()
        seen = set()
        for cfg in (self.claude, self.tmp / "other-claude"):
            with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(cfg)}):
                for root in (self.root, other):
                    a, b = kb_audit.state_dir(root), wb.kb_state_dir(root)
                    self.assertEqual(a, b, "workbench-kb and workbench-core disagree on the state folder")
                    self.assertEqual(a.parent, cfg / "workbench" / "kb-state")
                    self.assertRegex(a.name, r"^[0-9a-f]{8}$")
                    seen.add(a)
        self.assertEqual(len(seen), 4, "two KBs and two config folders must never share a state folder")
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.claude)}):
            self.assertEqual(kb_audit.state_dir(str(self.root).upper()), kb_audit.state_dir(self.root), "the key ignores case")
            self.assertEqual(wb.legacy_kb_state_dir(self.root), self.root / ".state")

    def test_the_paths_the_scripts_use_sit_under_the_local_state_folder(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.claude), "WORKBENCH_KB_ROOT": str(self.root)}):
            os.environ.pop("KB_INDEX_DB", None)         # an override (doctor --deep D3 sets one) is not the default path
            ka = load("kb_audit", SCRIPTS)
            self.assertEqual(ka.ROOT, self.root)
            self.assertEqual(ka.STATE, ka.state_dir())
            self.assertEqual((ka.SAVE_LOCK, ka.SNAPSHOTS), (ka.STATE / "save.lock", ka.STATE / "snapshots"))
            self.assertEqual(ka.index_db(), self.claude / "workbench" / "cache" / f"kb-{ka.kb_key()}.db")
            self.assertEqual(ka.state_dir().name, ka.kb_key(), "the index and the state share one key")
            self.assertEqual(ka.OLD_SAVE_LOCK, self.root / ".state" / "locks" / "save.lock")
            for p in (ka.STATE, ka.SAVE_LOCK, ka.SNAPSHOTS, ka.index_db()):
                self.assertFalse(self.root in p.parents, f"{p} is inside the KB")

    def test_a_full_save_creates_nothing_under_the_kb_except_what_the_save_wrote(self):
        self.legacy()
        old_before = self.tree(self.old)
        before = set(self.tree(self.root))
        self.assertEqual(self.driver("--inbox-add", "state moved out of the KB")[0], 0)
        rc, pre = self.driver("--pre")
        self.assertEqual(rc, 0)
        draft = self.tmp / "draft.md"
        draft.write_text("# Active context\n- new\n", encoding="utf-8")
        self.assertEqual(self.driver("--ac-write", draft, "--base", pre["ac_base"])[0], 0)
        self.run_py("precompact.py", folder=CORE_SCRIPTS, stdin=json.dumps({"session_id": "sess-b", "trigger": "auto"}))
        self.assertEqual(self.driver("--post", "--domains", "ops", "--note", "t")[0], 0)
        new = set(self.tree(self.root)) - before
        self.assertEqual({n for n in new if not n.startswith("daily/")}, {"inbox.jsonl"}, f"unexpected new KB files: {sorted(new)}")
        self.assertEqual(self.tree(self.old), old_before, "the copy only READS the old folder")
        self.assertTrue((self.state / "snapshots").is_dir() and (self.state / "precompact-sess-b.flag").exists())
        self.assertTrue((self.state / "save-metrics.jsonl").exists())

    def test_fresh_kb_never_gets_a_state_folder(self):
        self.assertEqual(self.driver("--pre")[0], 0)
        self.assertFalse(self.old.exists())
        self.assertTrue((self.state / "snapshots").is_dir())
        self.assertFalse((self.state / "migrated-from-kb.json").exists(), "nothing to migrate, nothing recorded")


class Migration(Base):
    def test_pre_copies_the_old_state_and_keeps_the_old_folder(self):
        self.legacy()
        old_before = self.tree(self.old)
        rc, pre = self.driver("--pre")
        self.assertEqual(rc, 0)
        self.assertRegex(pre["state_migration"], r"^copied 4 file\(s\)")
        new = self.tree(self.state)
        for rel in ("precompact-sess-old.flag", "snapshots/active-context-20200101-000000-1.md",
                    "snapshots/active-context-presave-legacy.md", "save-metrics.jsonl"):
            self.assertEqual(new[rel], old_before[rel], rel)
        self.assertNotIn("locks/save.lock", new, "a lock file is not state")
        self.assertTrue((self.state / "migrated-from-kb.json").exists())
        self.assertEqual(self.tree(self.old), old_before, "COPY, not move: the old folder is readable for one release")
        rc, pre = self.driver("--pre")
        self.assertNotIn("state_migration", pre, "the copy runs once")
        self.assertIn("precompact-sess-old.flag", pre["other_sessions_pending"])

    def test_a_file_already_in_the_new_folder_wins(self):
        self.legacy()
        self.put(self.state, "snapshots/active-context-presave-legacy.md", "# AC\n- newer, written by this kit\n")
        self.driver("--pre")
        self.assertIn("newer", (self.state / "snapshots" / "active-context-presave-legacy.md").read_text(encoding="utf-8"))

    def test_readers_fall_back_to_the_old_folder(self):
        self.legacy(flag_for=("sess-a",))
        self.put(self.state, "migrated-from-kb.json", "{}")          # skip the copy: only the readers are under test
        rc, pre = self.driver("--pre")
        self.assertTrue(pre["resume_pending"], "this session's flag was raised by the earlier kit")
        self.assertIsNotNone(pre["last_save_minutes_ago"], "a save recorded in the old metrics file counts")
        rc, post = self.driver("--post", "--domains", "ops", "--note", "resume")
        self.assertEqual(post["mode"], "precompact-resume")
        self.assertFalse((self.old / "precompact-sess-a.flag").exists(), "post clears the legacy flag too, or it would return")

    def test_post_clears_both_copies_of_the_flag(self):
        self.legacy(flag_for=("sess-a",))
        self.driver("--pre")
        self.assertTrue((self.state / "precompact-sess-a.flag").exists() and (self.old / "precompact-sess-a.flag").exists())
        rc, post = self.driver("--post", "--domains", "ops", "--note", "resume")
        self.assertEqual(rc, 0)
        self.assertFalse((self.state / "precompact-sess-a.flag").exists() or (self.old / "precompact-sess-a.flag").exists())
        self.assertFalse(self.driver("--pre")[1]["resume_pending"])

    def test_a_process_holding_the_old_lock_blocks_the_migration(self):
        self.legacy()
        p = self.hold(self.old / "locks" / "save.lock")
        rc, pre = self.driver("--pre", env={"SAVE_LOCK_TIMEOUT": "1"})
        self.assertEqual(rc, 0, "the save still starts; only the copy waits")
        self.assertRegex(pre["state_migration"], r"^skipped: another session holds the save lock")
        self.assertFalse((self.state / "migrated-from-kb.json").exists())
        self.assertFalse((self.state / "precompact-sess-old.flag").exists(), "nothing is copied while the old lock is held")
        self.release(p)
        rc, pre = self.driver("--pre")
        self.assertRegex(pre["state_migration"], r"^copied ")

    def test_a_process_holding_the_new_lock_blocks_the_migration_too(self):
        self.legacy()
        p = self.hold(self.state / "save.lock")
        rc, pre = self.driver("--pre", env={"SAVE_LOCK_TIMEOUT": "1"})
        self.assertRegex(pre["state_migration"], r"^skipped: another session holds the save lock")
        self.assertFalse((self.state / "migrated-from-kb.json").exists())
        self.release(p)
        self.assertRegex(self.driver("--pre")[1]["state_migration"], r"^copied ")

    def test_ac_write_waits_for_a_session_on_the_old_lock(self):
        self.legacy()
        rc, pre = self.driver("--pre")
        draft = self.tmp / "draft.md"
        draft.write_text("# Active context\n- mine\n", encoding="utf-8")
        p = self.hold(self.old / "locks" / "save.lock")
        rc, out = self.driver("--ac-write", draft, "--base", pre["ac_base"], env={"SAVE_LOCK_TIMEOUT": "1"})
        self.assertEqual((rc, out["status"]), (1, "busy"), "an earlier kit's session holds the save lock: no interleaved write")
        self.release(p)
        self.assertEqual(self.driver("--ac-write", draft, "--base", pre["ac_base"])[1]["status"], "written")

    def test_an_old_base_ac_write_still_works(self):
        """A save started on the earlier kit printed a <KB>/.state/snapshots path as ac_base; --ac-write must accept it,
        also after that folder is gone (the copy in the new snapshots folder answers to the same file name)."""
        self.legacy()
        base = self.old / "snapshots" / "active-context-presave-legacy.md"
        ac = self.root / "active-context.md"
        ac.write_text(base.read_text(encoding="utf-8"), encoding="utf-8")
        draft = self.tmp / "draft.md"
        draft.write_text("# AC\n- one\n- two (mine)\n", encoding="utf-8")
        rc, out = self.driver("--ac-write", draft, "--base", base)
        self.assertEqual((rc, out["status"], out["merge"]), (0, "written", "direct"))
        self.assertIn("two (mine)", ac.read_text(encoding="utf-8"))
        self.driver("--pre")                                              # copies the old snapshots across
        ac.write_text("# AC\n- one\n", encoding="utf-8")
        shutil.rmtree(self.old)                                           # one release later the folder is deleted
        rc, out = self.driver("--ac-write", draft, "--base", base)
        self.assertEqual((rc, out["status"]), (0, "written"), out)
        rc, out = self.driver("--ac-write", draft, "--base", self.old / "snapshots" / "never-existed.md")
        self.assertEqual(rc, 2, "a base that exists nowhere is still refused")

    @unittest.skipUnless(HAS_GIT, "needs git for the 3-way merge")
    def test_an_old_base_three_way_merge_keeps_the_other_sessions_lines(self):
        self.legacy()
        base = self.old / "snapshots" / "active-context-presave-legacy.md"
        base.write_text("# AC\n- one\n- two\n- three\n", encoding="utf-8")
        (self.root / "active-context.md").write_text("# AC\n- one\n- two (other session)\n- three\n", encoding="utf-8")
        draft = self.tmp / "draft.md"
        draft.write_text("# AC\n- one\n- two\n- three\n- four (mine)\n", encoding="utf-8")
        rc, out = self.driver("--ac-write", draft, "--base", base)
        self.assertEqual((rc, out["status"]), (0, "written"), out)
        text = (self.root / "active-context.md").read_text(encoding="utf-8")
        self.assertIn("two (other session)", text)
        self.assertIn("four (mine)", text)


class Window(Base):
    def test_window_falls_back_to_a_name_with_the_pid_when_the_usual_one_is_unwritable(self):
        self.assertEqual(self.driver("--inbox-add", "journal line for the window")[0], 0)
        rc, pre = self.driver("--pre")
        self.assertEqual(Path(pre["inbox_file"]).name, "inbox-window.sess-a.jsonl")
        (self.state / "inbox-window.sess-a.jsonl").unlink()
        (self.state / "inbox-window.sess-a.jsonl").mkdir()                # held: a directory cannot be replaced by a file
        rc, pre = self.driver("--pre")
        self.assertEqual(rc, 0, pre)
        self.assertRegex(Path(pre["inbox_file"]).name, r"^inbox-window\.sess-a\.\d+\.jsonl$")
        self.assertIn("journal line for the window", Path(pre["inbox_file"]).read_text(encoding="utf-8"))
        self.assertEqual(pre["inbox_pending"], 1)


class Advisories(Base):
    def test_backtick_in_a_journal_entry_warns(self):
        rc, out = self.driver("--inbox-add", "the `deploy` step was skipped")
        self.assertEqual(rc, 0)
        self.assertTrue(any("backtick" in w for w in out["warnings"]), out)
        self.assertIn("`deploy`", (self.root / "inbox.jsonl").read_text(encoding="utf-8"), "warn, never rewrite or refuse")
        rc, out = self.driver("--inbox-add", "no special characters here")
        self.assertNotIn("warnings", out)

    def test_open_user_decisions_advisory_above_ten(self):
        kb_audit = load("kb_audit", SCRIPTS)
        def ac(n, extra=""):
            return ("# Active context\n\n## Open\n" + "".join(f"- open item {i}\n" for i in range(30)) +
                    "\n## Waiting on you\nActions or decisions only the user can take.\n" +
                    "".join(f"- decision {i}\n" for i in range(n)) + extra + "\n## Notes\n- decision-like line\n")
        self.assertEqual(kb_audit.open_decisions(ac(10)), 10, "only the Waiting on you section counts")
        self.assertNotIn("decisions", kb_audit.ac_report(ac(10))["advisories"], "ten is the limit, not over it")
        rep = kb_audit.ac_report(ac(11))
        self.assertIn("open user decisions: 11", rep["advisories"]["decisions"])
        self.assertEqual(rep["decisions"], 11)
        closed = kb_audit.ac_report(ac(11, "- ~~settled item~~\n- [x] ticked item\n1. numbered open item\n"))
        self.assertEqual(closed["decisions"], 12, "struck-through and ticked items are closed; a numbered one is open")

    def test_post_reports_the_decisions_advisory(self):
        body = "# Active context\n\n## Waiting on you\n" + "".join(f"- decision {i}\n" for i in range(11))
        (self.root / "active-context.md").write_text(body, encoding="utf-8")
        rc, post = self.driver("--post", "--domains", "ops", "--note", "t")
        self.assertEqual(rc, 0)
        self.assertIn("open user decisions: 11", post["action_required"])


if __name__ == "__main__":
    unittest.main()
