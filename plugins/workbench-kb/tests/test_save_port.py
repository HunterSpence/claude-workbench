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

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def popen(self, *args, sid="sess-a", env=None):
        e = {**self.env, "CLAUDE_CODE_SESSION_ID": sid, **(env or {})}
        return subprocess.Popen([sys.executable, str(SCRIPTS / "save_driver.py"), *map(str, args)], env=e,
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
    the newest entries. The failure these guard against is a strategy that reports success while moving nothing."""

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


if __name__ == "__main__":
    unittest.main()
