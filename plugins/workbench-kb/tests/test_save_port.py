"""Save-driver tests that go beyond test_kb.py: concurrency, history rollover by size, a full cycle in a sandbox, and the
credential gate end to end. They only TEST save_driver.py and kb_audit.py; neither is changed here. Run:
    python -m unittest discover -s plugins/workbench-kb/tests
Every test drives the scripts as subprocesses (the way the save skill does) against a throwaway copy of kb-template, with
CLAUDE_CONFIG_DIR and the home folder pointed at the same temporary folder. Credential-shaped values are built at run time.
"""
import functools
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
SCRIPTS = PLUGIN / "scripts"
REPO = PLUGIN.parent.parent
TEMPLATE = REPO / "kb-template"
HAS_GIT = shutil.which("git") is not None
REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
KEY = "AKIA" + "Z" * 16                       # built at run time: this file holds no credential shape
TOKEN = "".join(["abc123"] * 4)               # 24 characters with digits
PW = "Zq8!" + "vLm29xT"


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


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def put(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def tree_hash(root):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def entry(date, i, size):
    return f"## {date} 12:{i % 60:02d} - task {i}\n- **Outcome:** done\n- **Detail:** {'x' * size}\n\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-port-"))
        self.root = self.tmp / "kb-root"
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.claude = self.tmp / "claude"
        shutil.copytree(TEMPLATE, self.root)
        self.env = {**os.environ, "WORKBENCH_KB_ROOT": str(self.root), "CLAUDE_CONFIG_DIR": str(self.claude),
                    "HOME": str(self.home), "USERPROFILE": str(self.home), "SAVE_LOCK_TIMEOUT": "20",
                    "PYTHONIOENCODING": "utf-8", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        self.env.pop("KB_INDEX_DB", None)
        self.env.pop("CLAUDE_CODE_SESSION_ID", None)
        self.scripts = SCRIPTS                      # a subclass may run the driver from a copy of the plugin folder

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def popen(self, *args, sid="sess-a", env=None):
        e = {**self.env, "CLAUDE_CODE_SESSION_ID": sid, **(env or {})}
        return subprocess.Popen([sys.executable, str(self.scripts / "save_driver.py"), *map(str, args)], env=e,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")

    @staticmethod
    def finish(p):
        out, err = p.communicate(timeout=300)
        try:
            return p.returncode, json.loads(out)
        except ValueError:
            return p.returncode, {"unparsed": out[:300], "stderr": err[:300]}

    def drv(self, *args, sid="sess-a", env=None):
        rc, out = self.finish(self.popen(*args, sid=sid, env=env))
        self.assertNotIn("unparsed", out, out)
        return rc, out

    def many(self, jobs):
        """Start every job at once ((args, sid) pairs); [(rc, json)] in the same order."""
        procs = [self.popen(*a, sid=s) for a, s in jobs]
        return [self.finish(p) for p in procs]

    def pre(self, sid="sess-a"):
        rc, out = self.drv("--pre", sid=sid)
        self.assertEqual(rc, 0, out)
        return out

    def state(self):
        return Path(self.pre()["state_dir"])

    def note(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def ac_of(self, nbytes):
        """An active-context.md of exactly nbytes (ASCII, lines well under the line advisory, nothing credential-like)."""
        body, n = ["# Active context\n"], 17
        while n < nbytes:
            line = "- " + "a" * min(98, max(nbytes - n - 3, 0)) + "\n"
            body.append(line)
            n += len(line)
        text = "".join(body)
        self.assertEqual(len(text.encode()), nbytes)
        (self.root / "active-context.md").write_text(text, encoding="utf-8", newline="\n")

    def metrics(self):
        """The rows of the metrics file that parse (a torn line is skipped, as the driver does)."""
        f, rows = self.state() / "save-metrics.jsonl", []
        for x in (f.read_text(encoding="utf-8").splitlines() if f.exists() else []):
            try:
                rows.append(json.loads(x))
            except ValueError:
                continue
        return rows


class Concurrency(Base):
    def test_parallel_saves_lose_no_metric_row_and_no_daily_line(self):
        runs = self.many([(("--post", "--domains", "ops", "--note", f"parallel save {n}"), f"sess-{n}") for n in range(4)])
        self.assertEqual([r[0] for r in runs], [0] * 4, runs)
        rows = [r for r in self.metrics() if "parallel save" in r.get("note", "")]
        self.assertEqual(sorted(r["note"] for r in rows), [f"parallel save {n}" for n in range(4)])
        daily = "".join(p.read_text(encoding="utf-8") for p in (self.root / "daily").glob("*.md"))
        self.assertEqual(len(re.findall(r"parallel save \d", daily)), 4, daily)

    def test_parallel_pre_runs_keep_every_history_entry_exactly_once(self):
        self.note("ops/history.md", "# ops history\n\n" + "".join(entry(f"2001-01-{d:02d}", d, 3000) for d in range(1, 21)))
        runs = self.many([(("--pre",), f"sess-{n}") for n in range(3)])
        self.assertEqual([r[0] for r in runs], [0] * 3, runs)
        texts = [(self.root / "ops/history.md").read_text(encoding="utf-8")]
        texts += [p.read_text(encoding="utf-8") for p in (self.root / "ops/history").glob("*.md")]
        heads = re.findall(r"^## (2001-01-\d\d) ", "\n".join(texts), re.M)
        self.assertEqual(sorted(heads), [f"2001-01-{d:02d}" for d in range(1, 21)], "an entry was lost or archived twice")

    def test_journal_pruning_does_not_race_appends(self):
        """--pre rewrites the journal to prune old rows; appends landing at the same moment must survive."""
        old = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (self.root / "inbox.jsonl").write_text(
            "".join(json.dumps({"ts": old, "session": "old", "pid": 1, "text": f"ancient {i}"}) + "\n" for i in range(40)), encoding="utf-8")
        stop = threading.Event()
        pres = []

        def keep_pruning():
            while not stop.is_set():
                pres.append(self.drv("--pre", sid="sess-pre")[0])

        t = threading.Thread(target=keep_pruning)
        t.start()
        try:
            adders = [threading.Thread(target=lambda n=n: [self.drv("--inbox-add", f"fresh {n}-{i}", sid=f"sess-{n}") for i in range(6)])
                      for n in range(2)]
            for a in adders:
                a.start()
            for a in adders:
                a.join(timeout=300)
        finally:
            stop.set()
            t.join(timeout=300)
        self.assertTrue(pres and set(pres) == {0}, pres)
        self.drv("--pre", sid="sess-pre")                                                      # one more prune after the last append
        texts = [json.loads(x)["text"] for x in (self.root / "inbox.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sorted(t for t in texts if t.startswith("fresh")), sorted(f"fresh {n}-{i}" for n in range(2) for i in range(6)))
        self.assertEqual([t for t in texts if t.startswith("ancient")], [], "old rows were not pruned")

    def test_ac_write_reports_busy_and_leaves_the_file_alone(self):
        ac = self.root / "active-context.md"
        ac.write_text("# AC\n- keep me\n", encoding="utf-8")
        pre = self.pre()
        savelock = load("savelock_under_test", SCRIPTS / "savelock.py")
        draft = self.tmp / "draft.md"
        draft.write_text("# AC\n- draft\n", encoding="utf-8")
        with savelock.filelock(Path(pre["state_dir"]) / "save.lock", timeout=5):
            rc, out = self.drv("--ac-write", draft, "--base", pre["ac_base"], env={"SAVE_LOCK_TIMEOUT": "1"})
        self.assertEqual((rc, out["status"]), (1, "busy"), out)
        self.assertEqual(ac.read_text(encoding="utf-8"), "# AC\n- keep me\n")
        rc, out = self.drv("--ac-write", draft, "--base", pre["ac_base"])                    # the lock is free again
        self.assertEqual((rc, out["status"]), (0, "written"), out)

    def test_the_daily_log_is_written_only_under_the_save_lock(self):
        """A save that cannot get the lock must wait, not write: two unlocked read-modify-write runs lose a line."""
        pre = self.pre()
        savelock = load("savelock_under_test", SCRIPTS / "savelock.py")
        with savelock.filelock(Path(pre["state_dir"]) / "save.lock", timeout=5):
            p = self.popen("--post", "--domains", "ops", "--note", "waits for the lock", env={"SAVE_LOCK_TIMEOUT": "60"})
            time.sleep(4)
            self.assertIsNone(p.poll(), "--post finished while another save held the lock")
            self.assertEqual(list((self.root / "daily").glob("*.md")), [], "the daily log was written without the lock")
        rc, out = self.finish(p)
        self.assertEqual(rc, 0, out)
        self.assertIn("waits for the lock", "".join(f.read_text(encoding="utf-8") for f in (self.root / "daily").glob("*.md")))

    def test_journal_pruning_waits_for_the_journal_lock(self):
        """--pre rewrites the journal to prune it; appends use the same lock, so a held lock must stop the rewrite."""
        stamp = lambda days: (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")   # noqa: E731
        rows = [{"ts": stamp(30), "session": "old", "pid": 1, "text": f"ancient {i}"} for i in range(5)]
        rows.append({"ts": stamp(0), "session": "new", "pid": 2, "text": "fresh"})
        journal = self.root / "inbox.jsonl"
        journal.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        savelock = load("savelock_under_test", SCRIPTS / "savelock.py")
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.claude)}):
            lock = savelock.lock_for(journal)
        with savelock.filelock(lock, timeout=5):
            p = self.popen("--pre", env={"SAVE_LOCK_TIMEOUT": "60"})
            time.sleep(4)
            self.assertIsNone(p.poll(), "--pre finished while the journal lock was held")
            self.assertEqual(len(journal.read_text(encoding="utf-8").splitlines()), 6, "the journal was rewritten without its lock")
        rc, out = self.finish(p)
        self.assertEqual(rc, 0, out)
        texts = [json.loads(x)["text"] for x in journal.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(texts, ["fresh"])

    def test_a_precompact_flag_belongs_to_its_session(self):
        state = self.state()
        flag = state / "precompact-sess-a.flag"
        flag.write_text("compacted\n", encoding="utf-8")
        rc, out = self.drv("--pre", sid="sess-b")
        self.assertEqual((rc, out["resume_pending"]), (0, False))
        self.assertIn("precompact-sess-a.flag", out["other_sessions_pending"])
        rc, out = self.drv("--post", "--domains", "ops", "--note", "b saves inline", sid="sess-b")
        self.assertEqual((rc, out["mode"]), (0, "inline"))
        self.assertTrue(flag.exists(), "session b's save cleared session a's flag")
        rc, out = self.drv("--post", "--domains", "ops", "--note", "a resumes", sid="sess-a")
        self.assertEqual(out["mode"], "precompact-resume")
        self.assertFalse(flag.exists())

    def test_reaping_spares_this_sessions_own_stale_flag(self):
        state = self.state()
        mine, other = state / "precompact-sess-a.flag", state / "precompact-sess-z.flag"
        old = time.time() - 30 * 86400
        for f in (mine, other):
            f.write_text("compacted\n", encoding="utf-8")
            os.utime(f, (old, old))
        rc, out = self.drv("--pre", sid="sess-a")
        self.assertTrue(out["resume_pending"], "a dormant session lost its own pending resume")
        self.assertTrue(mine.exists())
        self.assertFalse(other.exists(), "another session's stale flag should be reaped")

    def test_a_torn_metrics_line_does_not_hide_the_rest(self):
        state = self.state()
        good = {"ts": "2001-01-01T00:00Z", "key": "old-save", "mode": "inline", "domains": ["ops"]}
        (state / "save-metrics.jsonl").write_text('{"ts": "20\n' + json.dumps(good) + "\n", encoding="utf-8")
        rc, out = self.drv("--post", "--domains", "ops", "--note", "after a torn line")
        self.assertEqual((rc, out["metrics"]), (0, "recorded"), out)
        self.assertIn("old-save", [r["key"] for r in self.metrics()])
        self.assertEqual(len(self.metrics()), 2)
        self.assertEqual(self.drv("--pre")[0], 0)

    def test_a_skip_is_recorded_once(self):
        rc, first = self.drv("--post", "--skip", "--note", "nothing happened")
        rc, second = self.drv("--post", "--skip", "--note", "nothing happened")
        self.assertEqual(first["result"], "skip recorded")
        self.assertEqual(second["result"], "skip already recorded")
        self.assertEqual(len([r for r in self.metrics() if r["mode"] == "skip"]), 1)


class ActiveContextCap(Base):
    def cap(self):
        return self.pre()["ac_cap"]

    def test_a_small_overage_completes_the_save_and_owes_the_trim(self):
        self.ac_of(self.cap() + 100)
        rc, out = self.drv("--post", "--domains", "ops", "--note", "near miss")
        self.assertEqual(rc, 0)
        self.assertEqual(out["ac_trim_owed"], 100)
        self.assertIn("daily_log", out, "a near miss must finish the save")
        self.assertIn("THIS SAVE COMPLETED", out["action_required"])

    def test_a_large_overage_stops_the_save(self):
        self.ac_of(self.cap() + 600)
        rc, out = self.drv("--post", "--domains", "ops", "--note", "far miss")
        self.assertEqual(rc, 0)
        self.assertNotIn("daily_log", out)
        self.assertIn("DID NOT COMPLETE", out["action_required"])
        self.assertEqual([r for r in self.metrics() if r.get("note") == "far miss"], [])

    def test_two_reasons_to_act_both_survive(self):
        self.ac_of(self.cap() + 600)
        rc, out = self.drv("--post", "--domains", "ops", "--note", "two reasons", "--files", self.tmp / "missing.md")
        self.assertIn("NOT scanned", out["action_required"])
        self.assertIn("DID NOT COMPLETE", out["action_required"])
        self.assertIn("ALSO", out["action_required"])


class RolloverBySize(Base):
    """kb_audit's history rollover, in-process on a throwaway KB: the ladder must end under the cap, lose nothing and keep
    the newest entries. The failure these tests catch is a strategy that reports success while moving nothing."""

    def setUp(self):
        super().setUp()
        with mock.patch.dict(os.environ, {"WORKBENCH_KB_ROOT": str(self.root), "CLAUDE_CONFIG_DIR": str(self.claude)}):
            self.audit = load("kb_audit_under_test", SCRIPTS / "kb_audit.py")
        self.hist = self.root / "ops" / "history.md"

    def write(self, dates, size=1400):
        self.hist.write_text("# History\n\n_Session records._\n\n---\n\n" + "".join(entry(d, i, size) for i, d in enumerate(dates)),
                             encoding="utf-8", newline="\n")

    def day(self, delta):
        return (datetime.now() - timedelta(days=delta)).strftime("%Y-%m-%d")

    def archived_text(self):
        return "".join(p.read_text(encoding="utf-8") for p in sorted((self.root / "ops" / "history").glob("*.md")))

    def test_a_flood_of_recent_entries_is_still_reduced(self):
        self.write([self.day(1)] * 17 + [self.day(0)] * 17)
        self.assertGreater(self.audit.lf_bytes(self.hist), self.audit.HIST_BYTES_CAP, "the fixture must start over the cap")
        res = self.audit.rollover_age_adaptive("ops")
        passes = res["passes"]
        self.assertTrue(all(p.get("result") == "nothing-older-than-cutoff" for p in passes if p["action"] == "rollover-age"), passes)
        size = [p for p in passes if p["action"] == "rollover-size"]
        self.assertTrue(size and size[0].get("moved", 0) > 0, "the size pass never ran or moved nothing")
        self.assertLessEqual(self.audit.lf_bytes(self.hist), self.audit.HIST_BYTES_CAP)

    def test_nothing_is_lost_and_the_newest_entries_stay(self):
        days = [self.day(1)] * 17 + [self.day(0)] * 17
        self.write(days)
        before = self.hist.read_text(encoding="utf-8")
        self.audit.rollover_age_adaptive("ops")
        after = self.hist.read_text(encoding="utf-8") + self.archived_text()
        heads = lambda t: sorted(re.findall(r"^## .*$", t, re.M))                         # noqa: E731
        self.assertEqual(heads(after), heads(before))
        for n in (33, 32, 31, 30, 29):                                                    # the newest MIN_KEEP entries
            self.assertIn(f"task {n}\n", self.hist.read_text(encoding="utf-8"))

    def test_the_floor_keeps_the_newest_entries_even_when_still_too_big(self):
        n = self.audit.MIN_KEEP_ENTRIES
        self.write([self.day(0)] * n, size=self.audit.HIST_BYTES_CAP)
        res = self.audit.rollover_size("ops")
        self.assertEqual(res["result"], "irreducible")
        self.assertEqual(len(re.findall(r"^## ", self.hist.read_text(encoding="utf-8"), re.M)), n)

    def test_a_file_under_the_cap_is_not_touched(self):
        self.write([self.day(0)] * 3)
        before = self.hist.read_bytes()
        self.audit.rollover_age_adaptive("ops")
        self.assertEqual(self.hist.read_bytes(), before)

    def test_old_entries_go_by_age_before_any_size_pass(self):
        self.write([self.day(60)] * 25 + [self.day(0)] * 3, size=1800)
        res = self.audit.rollover_age_adaptive("ops")
        self.assertEqual([p["action"] for p in res["passes"]], ["rollover-age"])
        self.assertEqual(len(re.findall(r"^## ", self.hist.read_text(encoding="utf-8"), re.M)), 3)

    def test_a_future_dated_entry_is_never_archived(self):
        """Headings can carry a clock a day ahead (another time zone); archiving one would file it under a month to come."""
        nxt = (datetime.now() + timedelta(days=45)).strftime("%Y-%m-%d")
        self.write([self.day(1)] * 30 + [nxt], size=1600)
        self.audit.rollover_size("ops")
        self.audit.rollover("ops")
        self.assertIn(f"## {nxt} ", self.hist.read_text(encoding="utf-8"))
        self.assertNotIn(f"## {nxt} ", self.archived_text())

    def test_the_monthly_rollover_moves_only_previous_months_and_keeps_order(self):
        cur = datetime.now().strftime("%Y-%m")
        days = ["2001-01-05", "2001-02-06", f"{cur}-01", f"{cur}-02"]
        self.write(days, size=50)
        keep_before = [m for m in re.findall(r"^## .*?\n(?:.*\n)*?\n", self.hist.read_text(encoding="utf-8"), re.M) if cur in m[:12]]
        self.audit.rollover("ops")
        now_text = self.hist.read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"^## (\d{4}-\d\d-\d\d)", now_text, re.M), days[2:])
        self.assertEqual([m for m in re.findall(r"^## .*?\n(?:.*\n)*?\n", now_text, re.M) if cur in m[:12]], keep_before)
        self.assertEqual(sorted(p.name for p in (self.root / "ops" / "history").glob("*.md")), ["2001-01.md", "2001-02.md"])


class CredentialGate(Base):
    def test_the_exit_3_report_masks_values_and_keeps_the_unscanned_reason(self):
        f = self.note("ops/leak.md", f"---\ntitle: x\n---\nfirst line\nrotated the key {KEY} today\n")
        rc, out = self.drv("--post", "--domains", "ops", "--note", "t", "--files", f, self.tmp / "missing.md")
        self.assertEqual(rc, 3)
        self.assertNotIn(KEY, json.dumps(out))
        found = out["cred_findings"][0]
        self.assertEqual(found["line"], 5)
        self.assertRegex(found["match"], r"^.{4}\.\.\.\(\d+ chars\)$")
        self.assertEqual(len(out["cred_unscanned"]), 1)
        self.assertIn("NOT scanned", out["action_required"])
        self.assertIn("Replace each finding", out["action_required"])
        self.assertEqual([r for r in self.metrics() if r.get("note") == "t"], [], "a blocked save must record nothing")

    def test_active_context_is_scanned_even_when_it_is_not_listed(self):
        (self.root / "active-context.md").write_text(f"# AC\n- the key is {KEY}\n", encoding="utf-8")
        rc, out = self.drv("--post", "--domains", "ops", "--note", "t")
        self.assertEqual(rc, 3)
        self.assertTrue(out["cred_findings"][0]["file"].endswith("active-context.md"))

    def test_a_correctly_redacted_line_does_not_block_the_next_save(self):
        f = self.note("ops/ok.md", "---\ntitle: ok\n---\nAdmin password: [REDACTED: refer to it by name]\nAPI_TOKEN=<YOUR_TOKEN>\n")
        rc, out = self.drv("--post", "--domains", "ops", "--note", "redacted", "--files", f)
        self.assertEqual((rc, out["cred_scan"]), (0, "CLEAN"), out)

    def test_every_listed_credential_is_found_not_just_the_first(self):
        f = self.note("ops/two.md", f"---\ntitle: x\n---\nONE {KEY}\nTWO API_TOKEN={TOKEN}\nTHREE Admin password: {PW}\n")
        rc, out = self.drv("--post", "--domains", "ops", "--note", "t", "--files", f)
        self.assertEqual(sorted(x["line"] for x in out["cred_findings"]), [4, 5, 6])
        self.assertNotIn(PW, json.dumps(out))

    def test_journal_masks_the_value_and_keeps_the_name(self):
        rc, out = self.drv("--inbox-add", f"set API_TOKEN={TOKEN} and the cloud key {KEY} for the build")
        self.assertEqual(rc, 0)
        self.assertIn("2 credential-shaped value(s) masked", out["warnings"][0])
        raw = (self.root / "inbox.jsonl").read_text(encoding="utf-8")
        self.assertIn("API_TOKEN=[REDACTED", raw, "the name must survive so the reader knows which credential it was")
        self.assertNotIn(TOKEN, raw)
        self.assertNotIn(KEY, raw)

    def test_a_masked_journal_line_does_not_trip_the_gate_later(self):
        self.drv("--inbox-add", f"set API_TOKEN={TOKEN} today")
        rc, out = self.drv("--post", "--domains", "ops", "--note", "after masking", "--files", self.root / "inbox.jsonl")
        self.assertEqual((rc, out["cred_scan"]), (0, "CLEAN"), out)


class Sandbox(Base):
    """One whole save cycle on a copy of the template: it must write nothing outside the temporary folder."""

    def git(self, *a, cwd=None):
        r = subprocess.run(["git", "-C", str(cwd or self.root), *a], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    @needs_git
    def test_full_cycle_leaves_the_template_and_the_home_folder_untouched(self):
        template_before = tree_hash(TEMPLATE)
        bare = self.tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, env=self.env)
        self.git("init", "-q")
        self.git("config", "user.email", "dev@example.com")
        self.git("config", "user.name", "Dev Example")
        self.git("remote", "add", "origin", str(bare))
        self.git("add", "-A")
        self.git("commit", "-qm", "seed")
        self.git("push", "-q", "-u", "origin", "HEAD")

        # 1. journal from two sessions, then --pre offers both
        self.drv("--inbox-add", "decided the quarterly cadence", sid="sess-a")
        self.drv("--inbox-add", "found the root cause of the slow index", sid="sess-b")
        pre = self.drv("--pre", sid="sess-a")[1]
        self.assertEqual(pre["inbox_pending"], 2)
        self.assertFalse((self.root / ".state").exists(), "state must live outside the KB")

        # 2. clean write, then a write over another session's change (3-way), then a conflict
        ac = self.root / "active-context.md"
        draft = self.tmp / "draft.md"
        draft.write_text("# AC\n- one\n- two\n- three\n", encoding="utf-8")
        rc, out = self.drv("--ac-write", draft, "--base", pre["ac_base"])
        self.assertEqual((rc, out["merge"]), (0, "direct"))
        base = out["ac_base"]
        ac.write_text("# AC\n- one\n- two (session b)\n- three\n", encoding="utf-8")
        draft.write_text("# AC\n- one\n- two\n- three\n- four (session a)\n", encoding="utf-8")
        rc, out = self.drv("--ac-write", draft, "--base", base)
        self.assertEqual((rc, out["status"]), (0, "written"), out)
        text = ac.read_text(encoding="utf-8")
        self.assertIn("two (session b)", text)
        self.assertIn("four (session a)", text)
        base = out["ac_base"]
        ac.write_text(text.replace("- one", "- one (b)"), encoding="utf-8")
        draft.write_text(text.replace("- one", "- one (a)"), encoding="utf-8")
        rc, out = self.drv("--ac-write", draft, "--base", base)
        self.assertEqual((rc, out["status"]), (1, "conflict"))
        self.assertIn("one (b)", ac.read_text(encoding="utf-8"), "a conflict must leave the live file alone")

        # 3. the credential gate stops the save and writes nothing
        leak = self.note("ops/leak.md", f"---\ntitle: leak\n---\nkey {KEY}\n")
        rc, out = self.drv("--post", "--domains", "ops", "--note", "gated", "--files", leak)
        self.assertEqual(rc, 3)
        leak.unlink()

        # 4. the hard cap on a touched domain stops it too; an untouched domain does not
        hot = self.root / "ops" / "HOT.md"
        small = hot.read_text(encoding="utf-8")
        hot.write_text(small + "x" * 30_000, encoding="utf-8")
        rc, out = self.drv("--post", "--domains", "ops", "--note", "over cap")
        self.assertEqual(rc, 4)
        hot.write_text(small, encoding="utf-8")

        # 5. a real save commits locally, pushes only when asked, and is idempotent
        rc, out = self.drv("--post", "--domains", "ops", "--note", "cycle save")
        self.assertEqual((rc, out["cred_scan"], out["git_commit"], out["git_push"]), (0, "CLEAN", "ok", "skipped (no --push)"), out)
        self.note("ops/more.md", "---\ntitle: more\n---\nbody\n")
        rc, out = self.drv("--post", "--domains", "ops", "--note", "cycle push", "--push")
        self.assertEqual(out["git_push"], "ok", out)
        local, remote = (self.git("rev-parse", "HEAD").strip(), self.git("--git-dir", str(bare), "rev-parse", "HEAD", cwd=self.tmp).strip())
        self.assertEqual(local, remote)
        rc, again = self.drv("--post", "--domains", "ops", "--note", "cycle push")
        self.assertEqual(again["metrics"], "already recorded")

        # 6. a compaction flag is raised and then cleared by this session's save
        flag = Path(pre["state_dir"]) / "precompact-sess-a.flag"
        flag.write_text("compacted\n", encoding="utf-8")
        self.assertTrue(self.drv("--pre", sid="sess-a")[1]["resume_pending"])
        rc, out = self.drv("--post", "--domains", "ops", "--note", "resume", sid="sess-a")
        self.assertEqual((out["mode"], flag.exists()), ("precompact-resume", False))

        # 7. a history file over its cap is rolled over by the next --pre
        self.note("ops/history.md", "# history\n\n" + "".join(entry(f"2001-02-{d:02d}", d, 3000) for d in range(1, 21)))
        pre = self.drv("--pre", sid="sess-a")[1]
        self.assertTrue(pre["rollovers_run"])
        self.assertTrue((self.root / "ops" / "history" / "2001-02.md").exists())

        # nothing leaked out of the sandbox
        self.assertEqual(tree_hash(TEMPLATE), template_before, "the template was modified")
        self.assertEqual(list(self.home.rglob("*")), [], "something was written to the home folder")
        self.assertFalse((self.root / ".state").exists())


class KitCopy(Base):
    """The driver run from a COPY of the plugin folder, so the tools it calls beside it (workbench-core) can be faked or
    left out, and the workbench home sits in a folder whose name holds a space."""

    def setUp(self):
        super().setUp()
        self.claude = self.tmp / "claude home"
        self.env["CLAUDE_CONFIG_DIR"] = str(self.claude)
        self.wb = self.claude / "workbench"
        self.kit = self.tmp / "kit"
        shutil.copytree(PLUGIN, self.kit / "workbench-kb", ignore=shutil.ignore_patterns("__pycache__"))
        self.scripts = self.kit / "workbench-kb" / "scripts"

    def core(self, skill, script, body):
        return put(self.kit / "workbench-core" / "skills" / skill / "scripts" / script, body)

    def saved(self, note, **env):
        rc, out = self.drv("--post", "--domains", "ops", "--note", note, env=env)
        self.assertEqual((rc, out["metrics"]), (0, "recorded"), out)
        return out

    def age_stamp(self, name, **ago):
        when = (datetime.now(timezone.utc) - timedelta(**ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        put(self.state() / name, when + "\n")


class SessionIdFallback(Base):
    """The hooks name a precompact flag by the id in the event; a Bash tool that does not export CLAUDE_CODE_SESSION_ID
    leaves the driver without it."""
    NOSID = {"CLAUDE_CODE_SESSION_ID": ""}

    def flag(self, name, age=0):
        f = self.state() / f"precompact-{name}.flag"
        f.write_text("compacted\n", encoding="utf-8")
        os.utime(f, (time.time() - age, time.time() - age))
        return f

    def test_the_one_fresh_flag_is_claimed_and_cleared(self):
        flag = self.flag("hook-session")
        rc, pre = self.drv("--pre", env=self.NOSID)
        self.assertEqual((rc, pre["resume_pending"], pre["flag_claimed_without_session_id"]), (0, True, True), pre)
        self.assertEqual(pre["mode_hint"], "precompact-resume")
        rc, post = self.drv("--post", "--domains", "ops", "--note", "no session id", env=self.NOSID)
        self.assertEqual((rc, post["mode"], post["flag_cleared"], post["flag_claimed_without_session_id"]),
                         (0, "precompact-resume", flag.name, True), post)
        self.assertFalse(flag.exists(), "the claimed flag must be gone, or the banner repeats forever")

    def test_with_several_flags_the_newest_is_claimed_and_the_others_stay(self):
        old, new = self.flag("old-session", age=3600), self.flag("new-session", age=60)
        rc, pre = self.drv("--pre", env=self.NOSID)
        self.assertEqual(pre["other_sessions_pending"], [old.name])
        rc, post = self.drv("--post", "--domains", "ops", "--note", "newest", env=self.NOSID)
        self.assertEqual(post["flag_cleared"], new.name)
        self.assertTrue(old.exists(), "another session's flag must survive")

    def test_a_stale_flag_is_nobodys_and_is_cleaned_up(self):
        stale = self.flag("dead-session", age=30 * 86400)
        rc, pre = self.drv("--pre", env=self.NOSID)
        self.assertEqual((rc, pre["resume_pending"]), (0, False), "a dead session's flag raised a spurious resume")
        self.assertNotIn("flag_claimed_without_session_id", pre)
        self.assertFalse(stale.exists(), "the stale flag should be removed by the usual cleanup")

    def test_a_stale_flag_never_beats_a_fresh_one(self):
        stale, fresh = self.flag("dead-session", age=30 * 86400), self.flag("live-session", age=60)
        rc, post = self.drv("--post", "--domains", "ops", "--note", "fresh wins", env=self.NOSID)
        self.assertEqual((rc, post["flag_cleared"]), (0, fresh.name))
        self.assertFalse(stale.exists())

    def test_without_any_flag_nothing_is_claimed(self):
        rc, pre = self.drv("--pre", env=self.NOSID)
        self.assertEqual((rc, pre["resume_pending"]), (0, False))
        self.assertNotIn("flag_claimed_without_session_id", pre)

    def test_a_known_session_id_never_claims_another_sessions_flag(self):
        flag = self.flag("hook-session")
        rc, pre = self.drv("--pre", sid="sess-b")
        self.assertEqual((pre["resume_pending"], pre.get("flag_claimed_without_session_id")), (False, None))
        self.assertTrue(flag.exists())


class PostReport(KitCopy):
    def test_post_lists_the_other_recent_saves_in_the_shape_pre_does(self):
        first = self.saved("first save")
        self.assertEqual(first["recent_other_saves"], [], "a save is not its own 'other'")
        second = self.drv("--post", "--domains", "infra", "--note", "second save", sid="sess-b")[1]
        others = second["recent_other_saves"]
        self.assertEqual((len(others), others[0]["domains"], set(others[0])), (1, ["ops"], {"ts", "domains"}))
        pre = self.pre()["recent_other_saves"]
        self.assertEqual((len(pre), set(pre[0])), (2, set(second["recent_other_saves"][0])))


class LegacyScanTimeout(KitCopy):
    def test_a_timed_out_scan_is_stamped_and_the_next_save_does_not_retry_it(self):
        mark = self.tmp / "scan-ran"
        self.core("cleanup", "scan_legacy.py", "import os, time\nopen(os.environ['SCAN_MARK'], 'a').write('x')\ntime.sleep(60)\n")
        env = {"SAVE_ADVISORY_TIMEOUT": "1", "SCAN_MARK": str(mark)}
        first = self.saved("slow scan one", **env)["advisories"]["legacy_scan"]
        self.assertEqual(first, "skipped: timed out after 1 s")
        self.assertTrue((self.state() / "legacy-scan.stamp").exists(), "a timeout must leave the stamp")
        self.assertRegex(self.saved("slow scan two", **env)["advisories"]["legacy_scan"], r"^not due \(ran 0 day")
        self.assertEqual(mark.read_text(), "x", "the scan was started again by the next save")

    def test_a_failing_scan_is_not_retried_until_the_tool_changes(self):
        mark = self.tmp / "scan-ran"
        env = {"SCAN_MARK": str(mark)}
        self.core("cleanup", "scan_legacy.py", "import os\nopen(os.environ['SCAN_MARK'], 'a').write('x')\nraise SystemExit(2)\n")
        self.assertEqual(self.saved("failing scan one", **env)["advisories"]["legacy_scan"], "skipped: no usable answer (exit 2)")
        self.assertRegex(self.saved("failing scan two", **env)["advisories"]["legacy_scan"], r"^not due \(ran 0 day\(s\) ago, and failed\)$")
        self.assertEqual(mark.read_text(), "x", "a failing scan was started again by the next save")
        self.core("cleanup", "scan_legacy.py", "import json\nprint(json.dumps({'candidates': []}))\n")      # the kit updated the tool
        self.assertEqual(self.saved("fixed scan", **env)["advisories"]["legacy_scan"],
                         "0 note(s) marked deprecated, obsolete or similar")


class Advisories(KitCopy):
    AUDIT = ("import json, os\nopen(os.environ['AUDIT_MARK'], 'a').write('x')\n"
             "print(json.dumps({'surface': {'bytes': 10, 'rules_over_cap': [], 'duplicates': [], 'dead_refs': [], "
             "'generated_drift': [], 'hidden_skills': []}}))\n")

    def setUp(self):
        super().setUp()
        self.mark = self.tmp / "audit-ran"
        self.core("brain-audit", "audit.py", self.AUDIT)

    def run_save(self, note, **env):
        return self.saved(note, AUDIT_MARK=str(self.mark), **env)["advisories"]

    def test_the_surface_audit_runs_at_most_once_a_day(self):
        self.assertEqual(self.run_save("day one")["surface"], "10 B always loaded, 0 finding(s)")
        self.assertRegex(self.run_save("day one again")["surface"], r"^not due \(ran 0 h ago; once a day\)$")
        self.assertEqual(self.mark.read_text(), "x", "ran twice inside a day")
        self.age_stamp("advisories.stamp", hours=25)
        self.assertEqual(self.run_save("day two")["surface"], "10 B always loaded, 0 finding(s)")
        self.assertEqual(self.mark.read_text(), "xx")

    def test_a_timed_out_audit_counts_as_the_days_run(self):
        self.core("brain-audit", "audit.py", "import time\ntime.sleep(60)\n")
        self.assertEqual(self.run_save("slow", SAVE_ADVISORY_TIMEOUT="1")["surface"], "skipped: timed out after 1 s")
        self.assertRegex(self.run_save("slow again", SAVE_ADVISORY_TIMEOUT="1")["surface"], r"^not due")

    BROKEN = "import os\nopen(os.environ['AUDIT_MARK'], 'a').write('b')\nraise SystemExit(2)\n"

    def test_an_audit_that_fails_at_once_is_not_retried_until_the_tool_changes(self):
        self.core("brain-audit", "audit.py", self.BROKEN)
        self.assertEqual(self.run_save("broken")["surface"], "skipped: no usable answer (exit 2)")
        self.assertRegex(self.run_save("broken again")["surface"], r"^not due \(ran 0 h ago, and failed; once a day\)$")
        self.assertEqual(self.mark.read_text(), "b", "a failing tool was started again by the next save")
        self.core("brain-audit", "audit.py", self.AUDIT)                  # the kit updated the tool: tried at once
        self.assertEqual(self.run_save("fixed")["surface"], "10 B always loaded, 0 finding(s)")
        self.assertEqual(self.mark.read_text(), "bx")

    def test_a_failed_audit_is_tried_again_a_day_later(self):
        self.core("brain-audit", "audit.py", self.BROKEN)
        self.run_save("broken")
        self.age_stamp("advisories.stamp", hours=25)
        self.assertEqual(self.run_save("a day later")["surface"], "skipped: no usable answer (exit 2)")
        self.assertEqual(self.mark.read_text(), "bb")

    def test_save_advisories_zero_runs_neither_tool(self):
        scan_mark = self.tmp / "scan-ran"
        self.core("cleanup", "scan_legacy.py", "import os\nopen(os.environ['SCAN_MARK'], 'a').write('x')\n")
        out = self.run_save("quiet", SAVE_ADVISORIES="0", SCAN_MARK=str(scan_mark))
        self.assertEqual(out, {"surface": "skipped: SAVE_ADVISORIES=0", "legacy_scan": "skipped: SAVE_ADVISORIES=0"})
        self.assertFalse(self.mark.exists() or scan_mark.exists(), "a tool ran although advisories were turned off")


class CoreLookup(KitCopy):
    """Where the driver finds the workbench-core tools: the installed kit, then the newest plugin-cache copy, then the
    folder beside the plugin. An installed plugin sits in `<claude>/plugins/cache/workbench/<plugin>/<version>/`."""

    def audit(self, base, n):
        body = "import json\nprint(json.dumps({'surface': {'bytes': %d, 'rules_over_cap': [], 'duplicates': [], 'dead_refs': [], " \
               "'generated_drift': [], 'hidden_skills': []}}))\n" % n
        return put(Path(base) / "skills" / "brain-audit" / "scripts" / "audit.py", body)

    def cached_driver(self):
        """Run the driver from the plugin-cache layout; returns the cache folder holding the core plugin's versions."""
        cache = self.claude / "plugins" / "cache" / "workbench"
        shutil.copytree(PLUGIN, cache / "workbench-kb" / "0.3.5", ignore=shutil.ignore_patterns("__pycache__"))
        self.scripts = cache / "workbench-kb" / "0.3.5" / "scripts"
        return cache / "workbench-core"

    def surface(self, **env):
        self.age_stamp("advisories.stamp", hours=25)          # the audit runs once a day: make it due again
        self.n = getattr(self, "n", 0) + 1
        return self.saved(f"lookup {self.n}", **env)["advisories"]["surface"]

    def test_the_plugin_cache_layout_finds_the_installed_kit_then_the_newest_cache_copy(self):
        cores = self.cached_driver()
        kit = self.wb / "kit" / "plugins" / "workbench-core"
        self.audit(cores / "0.3.9", 39)
        os.utime(cores / "0.3.9", (1_000_000_000, 1_000_000_000))          # older, though it sorts after 0.3.10
        self.audit(cores / "0.3.10", 310)
        self.audit(kit, 1)
        for label, remove, want in (("installed kit first", None, "1 B always loaded, 0 finding(s)"),
                                    ("then the newest cache copy", kit, "310 B always loaded, 0 finding(s)"),
                                    ("then the older one", cores / "0.3.10", "39 B always loaded, 0 finding(s)"),
                                    ("then nothing", cores, "skipped: not found")):
            with self.subTest(label):
                if remove is not None:
                    shutil.rmtree(remove)
                self.assertEqual(self.surface(), want)

    def test_the_folder_beside_the_plugin_is_the_last_resort_and_the_kit_beats_it(self):
        self.audit(self.kit / "workbench-core", 7)
        self.assertEqual(self.surface(), "7 B always loaded, 0 finding(s)")
        self.audit(self.wb / "kit" / "plugins" / "workbench-core", 1)
        self.assertEqual(self.surface(), "1 B always loaded, 0 finding(s)")

    def test_a_tool_found_in_the_cache_is_still_cut_off_at_the_timeout(self):
        self.cached_driver()
        put(self.claude / "plugins" / "cache" / "workbench" / "workbench-core" / "0.3.5" / "skills" / "brain-audit" / "scripts"
            / "audit.py", "import time\ntime.sleep(60)\n")
        self.assertEqual(self.surface(SAVE_ADVISORY_TIMEOUT="1"), "skipped: timed out after 1 s")


class FindRefresh(KitCopy):
    """The find index is refreshed by a detached child the stub stands in for: it writes a marker and exits, so no process
    outlives a test."""
    STUB = ("import json, os, sys\nopen(os.environ['FIND_MARK'], 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "print(json.dumps({'started': True}))\n")

    def setUp(self):
        super().setUp()
        self.mark = self.tmp / "find-calls"
        self.db = self.tmp / "know dir" / "index.sqlite"
        self.tool = put(self.wb / "kit" / "plugins" / "workbench-core" / "skills" / "find" / "scripts" / "doc_index.py", self.STUB)
        self.config(knowledge_python=sys.executable, knowledge_db=str(self.db))

    def config(self, **kw):
        put(self.wb / "config.json", json.dumps(kw))

    def go(self, note, **env):
        return self.saved(note, FIND_MARK=str(self.mark), **env)["find_refresh"]

    def calls(self):
        return [json.loads(x) for x in self.mark.read_text().splitlines()] if self.mark.exists() else []

    def test_started_once_then_debounced_then_started_again_after_30_minutes(self):
        self.assertEqual(self.go("one"), "started")
        argv = ["--db", str(self.db), "refresh", "--root", "kb", "--detach", "--json"]
        self.assertEqual((len(self.calls()), self.calls()[0]), (1, argv))
        self.assertRegex(self.go("two"), r"^skipped: a refresh was started \d+ min ago")
        self.assertEqual(len(self.calls()), 1, "the refresh was started again inside 30 minutes")
        self.age_stamp("find-refresh.stamp", minutes=31)
        self.assertEqual(self.go("three"), "started")
        self.assertEqual(len(self.calls()), 2)

    def test_skipped_without_config_without_the_script_or_when_turned_off(self):
        no_cfg = "skipped: config.json has no knowledge_python and knowledge_db"
        for label, setup, want in (
                ("no config file", lambda: (self.wb / "config.json").unlink(), no_cfg),
                ("no database", lambda: self.config(knowledge_python=sys.executable), no_cfg),
                ("no find script", lambda: (self.config(knowledge_python=sys.executable, knowledge_db=str(self.db)), self.tool.unlink()),
                 "skipped: the find script is not installed")):
            with self.subTest(label):
                setup()
                self.assertEqual(self.go(label), want)
        put(self.tool, self.STUB)
        self.config(knowledge_python=sys.executable, knowledge_db=str(self.db))
        self.assertEqual(self.go("off", SAVE_FIND_REFRESH="0"), "skipped: SAVE_FIND_REFRESH=0")
        self.assertEqual(self.calls(), [], "a refresh was started although it was skipped")

    def test_a_hung_or_failing_refresh_never_blocks_the_save_or_repeats(self):
        stamp = self.state() / "find-refresh.stamp"
        for label, body, env, want in (
                ("hangs", "import time\ntime.sleep(60)\n", {"SAVE_FIND_TIMEOUT": "1"}, "skipped: timed out after 1 s"),
                ("crashes", "raise SystemExit(1)\n", {}, "skipped: no usable answer (exit 1)"),
                ("already running", "import json\nprint(json.dumps({'started': False}))\n", {}, None)):
            with self.subTest(label):
                put(self.tool, body)
                stamp.unlink(missing_ok=True)
                out = self.go(label, **env)
                self.assertTrue(out.startswith("skipped: ") and (want is None or out == want), out)
                self.assertRegex(self.go(label + " again", **env), r"^skipped: a refresh was started", "the failure was retried")


class PluginAlone(Base):
    """The whole cycle from a copy of plugins/workbench-kb with no workbench-core folder beside it: the tools it calls
    after the save are absent, and nothing may fail because of that."""

    def test_pre_ac_write_post_without_workbench_core(self):
        solo = self.tmp / "solo kit"
        shutil.copytree(PLUGIN, solo / "workbench-kb", ignore=shutil.ignore_patterns("__pycache__"))
        self.scripts = solo / "workbench-kb" / "scripts"
        self.assertEqual([p.name for p in solo.iterdir()], ["workbench-kb"])
        pre = self.pre()
        draft = put(self.tmp / "draft.md", "# AC\n- solo item\n")
        rc, out = self.drv("--ac-write", draft, "--base", pre["ac_base"])
        self.assertEqual((rc, out["status"]), (0, "written"), out)
        note = self.note("ops/solo.md", "---\ntitle: solo\ndomain: ops\nstatus: active\nupdated: 2001-01-01\n---\nbody\n")
        rc, post = self.drv("--post", "--domains", "ops", "--note", "solo cycle", "--files", note)
        self.assertEqual((rc, post["cred_scan"], post["metrics"], post["stamped"]), (0, "CLEAN", "recorded", ["ops/solo.md"]), post)
        self.assertEqual(post["advisories"], {"surface": "skipped: not found", "legacy_scan": "skipped: not found"})
        self.assertTrue(post["find_refresh"].startswith("skipped: "), post["find_refresh"])
        self.assertNotIn("action_required", post)
        self.assertIn("solo item", (self.root / "active-context.md").read_text(encoding="utf-8"))
        self.assertTrue(list((self.root / "daily").glob("*.md")))


if __name__ == "__main__":
    unittest.main()
