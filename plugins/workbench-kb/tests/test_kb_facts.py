"""Tests for the fact registry (kb_facts.py, `kb_health.py facts`), the `updated:` stamper (frontmatter.py and
save_driver.py --post), the non-fatal --post advisories, and the metrics row that follows a torn last line. Run:
    python -m unittest discover -s plugins/workbench-kb/tests
The scripts run as subprocesses against a throwaway copy of kb-template (the way the save skill runs them); the pure
helpers are loaded in-process. Every name, region and value below is fictional.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
CORE_TOOLS = REPO / "plugins" / "workbench-core" / "skills"
REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"


def load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_facts_test", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(SCRIPTS))
    return mod


def put(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    return path


def today_choices():
    """Today's date as the stamper writes it; the day before and after are accepted so a test spanning midnight passes."""
    now = datetime.now()
    return {(now + timedelta(days=d)).strftime("%Y-%m-%d") for d in (-1, 0, 1)}


class FrontmatterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fm = load("frontmatter")

    def test_the_value_is_replaced_in_place_and_every_other_byte_stays(self):
        for eol in ("\n", "\r\n"):
            for bom in ("", "﻿"):
                with self.subTest(eol=repr(eol), bom=bool(bom)):
                    head = [f"{bom}---", "title: a note", "tags: [x, y]", "updated: 2001-01-01", "status:   active", "---"]
                    text = eol.join(head) + eol + "# Body" + eol + "updated: not this one" + eol
                    got = self.fm.set_key(text, "updated", "2002-02-02")
                    self.assertEqual(got, text.replace("updated: 2001-01-01", "updated: 2002-02-02"))

    def test_a_missing_key_is_added_just_before_the_closing_line_with_the_files_line_endings(self):
        self.assertEqual(self.fm.set_key("---\ntitle: a\n---\nbody\n", "updated", "D"), "---\ntitle: a\nupdated: D\n---\nbody\n")
        self.assertEqual(self.fm.set_key("---\r\ntitle: a\r\n---\r\nbody\r\n", "updated", "D"),
                         "---\r\ntitle: a\r\nupdated: D\r\n---\r\nbody\r\n")
        self.assertEqual(self.fm.set_key("---\n---\nbody\n", "updated", "D"), "---\nupdated: D\n---\nbody\n")

    def test_a_note_without_a_front_matter_block_is_never_given_one(self):
        for text in ("# Just a body\nupdated: x\n", "", "text\n---\ntitle: a\n---\n", "---\ntitle: never closed\nupdated: x\n"):
            with self.subTest(text=text):
                self.assertIsNone(self.fm.set_key(text, "updated", "D"))
                self.assertIsNone(self.fm.get(text, "updated"))

    def test_only_a_top_level_key_counts(self):
        text = "---\ntitle: a\nmeta:\n  updated: nested\n---\nbody\n"
        self.assertIsNone(self.fm.get(text, "updated"))
        self.assertEqual(self.fm.set_key(text, "updated", "D"), "---\ntitle: a\nmeta:\n  updated: nested\nupdated: D\n---\nbody\n")

    def test_get_strips_quotes_and_spacing(self):
        self.assertEqual(self.fm.get('---\nupdated : "2001-01-01"  \n---\n', "updated"), "2001-01-01")
        self.assertEqual(self.fm.get("---\nupdated:\n---\n", "updated"), "")

    def test_the_same_value_gives_back_the_same_text(self):
        text = "---\ntitle: a\nupdated: D\n---\nbody\n"
        self.assertEqual(self.fm.set_key(text, "updated", "D"), text)


class Registry(unittest.TestCase):
    """kb_facts.check in-process on a temporary KB, config dir and project folder."""

    @classmethod
    def setUpClass(cls):
        cls.kf = load("kb_facts")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-facts-"))
        self.kb, self.home, self.proj = self.tmp / "kb", self.tmp / "claude", self.tmp / "proj"
        for d in (self.kb, self.home, self.proj):
            d.mkdir()
        patch = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        put(self.kb / "infra" / "builder.md", "---\ntitle: builder\n---\n# Builder\nThe build server runs in region east-a.\n")
        self.register({"id": "builder-region", "owner": "infra/builder", "canonical": "region east-a",
                       "forbidden": ["region west-b"]})

    def register(self, *facts, raw=None):
        put(self.kb / "_shared" / "facts.json", raw if raw is not None else json.dumps({"facts": list(facts)}))

    def check(self):
        return self.kf.check(self.kb, project=self.proj)

    def kinds(self):
        return [(f["kind"], f["file"].rsplit("/", 1)[-1], f["line"]) for f in self.check()["findings"]]

    def test_a_consistent_registry_passes(self):
        res = self.check()
        self.assertEqual((res["registered"], res["facts"], res["findings"]), (True, 1, []))
        self.assertEqual(self.kf.summary(res)[0], "PASS")

    def test_a_forbidden_alternate_in_a_kb_note_is_flagged_with_its_line(self):
        put(self.kb / "ops" / "other.md", "# Other\n\nWe deploy to region west-b on Fridays.\n")
        self.assertEqual(self.kinds(), [("forbidden", "other.md", 3)])
        status, detail = self.kf.summary(self.check())
        self.assertEqual(status, "FAIL")
        self.assertIn("ops/other.md:3", detail)

    def test_a_forbidden_alternate_in_an_always_loaded_file_is_flagged(self):
        put(self.home / "CLAUDE.md", "# Rules\n@rules/env.md\n")
        put(self.home / "rules" / "env.md", "Builds run in Region West-B.\n")          # an imported file, other case
        put(self.home / "rules" / "direct.md", "Also region west-b here.\n")           # an unconditional rule
        put(self.proj / "CLAUDE.md", "Project note: region\nwest-b is the default.\n")  # a phrase wrapped over two lines
        self.assertEqual(sorted(self.kinds()), [("forbidden", "CLAUDE.md", 1), ("forbidden", "direct.md", 1), ("forbidden", "env.md", 1)])

    def test_a_path_scoped_rule_is_not_always_loaded(self):
        put(self.home / "rules" / "scoped.md", "---\npaths: src/**\n---\nregion west-b\n")
        self.assertEqual(self.kinds(), [])

    def test_the_owner_dropping_its_canonical_text_is_flagged(self):
        put(self.kb / "infra" / "builder.md", "---\ntitle: builder\n---\n# Builder\nThe build server moved.\n")
        self.assertEqual(self.kinds(), [("canonical", "builder.md", 0)])
        self.assertEqual(self.kf.summary(self.check())[0], "FAIL")

    def test_a_longer_word_does_not_state_the_canonical(self):
        put(self.kb / "infra" / "builder.md", "The build server runs in region east-a2.\n")
        self.assertEqual([k[0] for k in self.kinds()], ["canonical"])

    def test_a_missing_owner_note_is_flagged(self):
        (self.kb / "infra" / "builder.md").unlink()
        self.assertEqual([k[0] for k in self.kinds()], ["owner"])

    def test_superseded_lines_history_and_archives_are_exempt(self):
        put(self.kb / "ops" / "moved.md", "SUPERSEDED (a date): was region west-b, now region east-a.\n")
        put(self.kb / "infra" / "history.md", "## entry\nWe ran region west-b then.\n")
        put(self.kb / "infra" / "history" / "old.md", "region west-b\n")
        put(self.kb / "daily" / "day.md", "- region west-b\n")
        put(self.kb / ".hidden" / "x.md", "region west-b\n")
        self.assertEqual(self.kinds(), [])

    def test_the_owner_may_name_the_misleading_value_and_a_readme_is_not_a_note(self):
        put(self.kb / "infra" / "builder.md", "The build server runs in region east-a.\nThe console still says region west-b.\n")
        put(self.kb / "ops" / "README.md", "About this folder: region west-b is the old value.\n")
        self.assertEqual(self.kinds(), [])

    def test_an_unusable_registry_is_a_failure_not_a_pass(self):
        for raw in ("{not json", json.dumps({"facts": "nope"}), json.dumps({"facts": [{"id": "x"}]}),
                    json.dumps({"facts": [{"id": "x", "owner": "o", "canonical": "c", "forbidden": [3]}]})):
            with self.subTest(raw=raw):
                self.register(raw=raw)
                res = self.check()
                self.assertEqual([f["kind"] for f in res["findings"]], ["registry"], res)
                self.assertEqual(self.kf.summary(res)[0], "FAIL")

    def test_a_registry_that_contradicts_itself_is_reported(self):
        self.register({"id": "a", "owner": "infra/builder", "canonical": "region east-a", "forbidden": ["east-a"]},
                      {"id": "b", "owner": "infra/builder", "canonical": "region east-a"},
                      {"id": "b", "owner": "infra/builder", "canonical": "region east-a"})
        msgs = [f["text"] for f in self.check()["findings"]]
        self.assertEqual(len(msgs), 2, msgs)
        self.assertTrue(any("inside the canonical" in m for m in msgs) and any("used twice" in m for m in msgs), msgs)

    def test_no_registry_and_an_empty_one_are_information_only(self):
        self.register()
        self.assertEqual(self.kf.summary(self.check())[0], "INFO")
        (self.kb / "_shared" / "facts.json").unlink()
        res = self.check()
        self.assertEqual((res["registered"], res["findings"], self.kf.summary(res)[0]), (False, [], "INFO"))

    def test_the_shipped_template_registry_is_empty_and_valid(self):
        data = json.loads((TEMPLATE / "_shared" / "facts.json").read_text(encoding="utf-8"))
        self.assertEqual(data["facts"], [])
        self.assertEqual(self.kf.load(TEMPLATE), ([], []))

    def test_self_test_is_one_line_exit_zero_and_quick(self):
        t0 = time.time()
        r = subprocess.run([sys.executable, str(SCRIPTS / "kb_facts.py"), "--self-test"], capture_output=True, text=True, timeout=60)
        self.assertEqual((r.returncode, r.stdout.strip().count("\n"), r.stderr), (0, 0, ""), r.stdout)
        self.assertTrue(r.stdout.strip().startswith("kb_facts self-test"), r.stdout)
        self.assertLess(time.time() - t0, 10)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-kbi-"))
        self.root, self.claude, self.home = self.tmp / "kb", self.tmp / "claude", self.tmp / "home"
        self.home.mkdir()
        shutil.copytree(TEMPLATE, self.root)
        self.env = {**os.environ, "WORKBENCH_KB_ROOT": str(self.root), "CLAUDE_CONFIG_DIR": str(self.claude), "HOME": str(self.home),
                    "USERPROFILE": str(self.home), "SAVE_LOCK_TIMEOUT": "20", "PYTHONIOENCODING": "utf-8",
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "CLAUDE_CODE_SESSION_ID": "sess-a"}
        self.env.pop("KB_INDEX_DB", None)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_py(self, script, *args, env=None, folder=SCRIPTS, timeout=120):
        r = subprocess.run([sys.executable, str(Path(folder) / script), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", env={**self.env, **(env or {})}, timeout=timeout)
        return r.returncode, r.stdout, r.stderr

    def drv(self, *args, env=None, folder=SCRIPTS):
        rc, out, err = self.run_py("save_driver.py", *args, env=env, folder=folder)
        try:
            return rc, json.loads(out)
        except ValueError:
            self.fail(f"save_driver printed no JSON (rc={rc}): {out[:300]} {err[:400]}")

    def pre(self):
        rc, out = self.drv("--pre")
        self.assertEqual(rc, 0, out)
        return out

    def post(self, *files, note="a save", env=None, folder=SCRIPTS):
        return self.drv("--post", "--domains", "ops", "--note", note, "--files", *files, env=env, folder=folder) if files else \
            self.drv("--post", "--domains", "ops", "--note", note, env=env, folder=folder)

    def metrics(self):
        f = Path(self.pre()["state_dir"]) / "save-metrics.jsonl"
        rows = []
        for x in (f.read_text(encoding="utf-8").splitlines() if f.exists() else []):
            try:
                rows.append(json.loads(x))
            except ValueError:
                continue
        return rows


class Health(Base):
    def health(self, *args):
        rc, out, err = self.run_py("kb_health.py", "--json", *args)
        data = json.loads(out)
        self.assertEqual(data["exit"], rc, err)
        return rc, {r["check"]: r for r in data["results"]}

    def register(self, *facts):
        put(self.root / "_shared" / "facts.json", json.dumps({"facts": list(facts)}))

    FACT = {"id": "builder-region", "owner": "infra/builder", "canonical": "region east-a", "forbidden": ["region west-b"]}

    def test_a_full_run_is_unchanged_until_the_registry_holds_a_fact(self):
        rc, res = self.health()
        self.assertNotIn("facts", res)
        self.register(self.FACT)
        put(self.root / "infra" / "builder.md", "---\ntitle: builder\n---\nThe build server runs in region east-a.\n")
        rc, res = self.health()
        self.assertEqual((rc, res["facts"]["status"]), (0, "PASS"), res["facts"])
        self.assertLess(list(res).index("secrets"), list(res).index("facts"))

    def test_facts_alone_runs_only_the_layout_and_registry_checks(self):
        rc, res = self.health("facts")
        self.assertEqual((rc, list(res), res["facts"]["status"]), (0, ["layout", "facts"], "INFO"))

    def test_a_forbidden_alternate_fails_the_run_and_names_where(self):
        self.register(self.FACT)
        put(self.root / "infra" / "builder.md", "---\ntitle: builder\n---\nThe build server runs in region east-a.\n")
        put(self.root / "ops" / "plan.md", "---\ntitle: plan\n---\nShip to region west-b.\n")
        for args in ((), ("facts",)):
            rc, res = self.health(*args)
            self.assertEqual((rc, res["facts"]["status"]), (1, "FAIL"))
            self.assertIn("ops/plan.md:4", res["facts"]["detail"])

    def test_the_owner_dropping_the_canonical_fails_the_run(self):
        self.register(self.FACT)
        put(self.root / "infra" / "builder.md", "---\ntitle: builder\n---\nThe build server moved.\n")
        rc, res = self.health("facts")
        self.assertEqual((rc, res["facts"]["status"]), (1, "FAIL"))
        self.assertIn("no longer states", res["facts"]["detail"])

    def test_the_text_mode_prints_the_facts_line(self):
        self.register(self.FACT)
        rc, out, _ = self.run_py("kb_health.py", "facts")
        self.assertEqual(rc, 1)
        self.assertRegex(out, r"(?m)^FAIL\s+facts\s")


class Stamp(Base):
    """`updated:` is stamped by --post on the notes it was named AND whose bytes changed since --pre."""

    NOTE = "---\ntitle: a note\ntags: [x, y]\nstatus:   active\nupdated: 2001-01-01\n---\n# A\nbody\n"

    def stamped(self, out):
        return out.get("stamped"), out.get("stamp_skipped", {})

    def test_a_changed_named_note_is_stamped_and_nothing_else_moves(self):
        a = put(self.root / "ops" / "a.md", self.NOTE)
        self.pre()
        a.write_bytes(self.NOTE.replace("body", "body, edited").encode())
        rc, out = self.post(a)
        self.assertEqual((rc, self.stamped(out)), (0, (["ops/a.md"], {})), out)
        got = a.read_bytes().decode("utf-8")                    # bytes, not read_text: a CRLF rewrite must show
        self.assertNotIn("\r", got)
        self.assertRegex(got, r"(?m)^updated: \d{4}-\d\d-\d\d$")
        self.assertIn(re.search(r"updated: (\S+)", got).group(1), today_choices())
        self.assertEqual(re.sub(r"updated: \S+", "updated: 2001-01-01", got), self.NOTE.replace("body", "body, edited"))

    def test_crlf_and_a_byte_order_mark_survive(self):
        text = "﻿---\r\ntitle: a\r\n---\r\nbody\r\n"
        a = put(self.root / "ops" / "a.md", text)
        self.pre()
        a.write_bytes(text.replace("body", "body2").encode("utf-8"))
        self.assertEqual(self.stamped(self.post(a)[1])[0], ["ops/a.md"])
        raw = a.read_bytes().decode("utf-8")
        self.assertRegex(raw, r"^﻿---\r\ntitle: a\r\nupdated: \d{4}-\d\d-\d\d\r\n---\r\nbody2\r\n$")

    def test_a_named_note_whose_bytes_did_not_change_is_not_touched(self):
        a = put(self.root / "ops" / "a.md", self.NOTE)
        self.pre()
        before = a.read_bytes()
        rc, out = self.post(a)
        self.assertEqual((self.stamped(out), a.read_bytes()), (([], {}), before))
        a.write_bytes(before)                                  # written again with the same bytes: still unchanged
        rc, out = self.post(a, note="again")
        self.assertEqual((self.stamped(out), a.read_bytes()), (([], {}), before))

    def test_a_changed_note_that_was_not_named_is_not_touched(self):
        a = put(self.root / "ops" / "a.md", self.NOTE)
        b = put(self.root / "ops" / "b.md", self.NOTE)
        self.pre()
        a.write_bytes(self.NOTE.replace("body", "x").encode())
        b.write_bytes(self.NOTE.replace("body", "y").encode())
        rc, out = self.post(b)
        self.assertEqual(self.stamped(out)[0], ["ops/b.md"])
        self.assertEqual(a.read_bytes(), self.NOTE.replace("body", "x").encode())

    def test_a_note_past_its_size_cap_is_never_stamped(self):
        caps = json.loads(self.run_py("kb_audit.py", "--caps-json")[1])
        head = "---\ntitle: ops HOT\ndomain: ops\n---\n"

        def hot(total):
            return head + "a" * (total - len(head) - 1) + "\n"
        h = self.root / "ops" / "HOT.md"
        h.write_bytes(hot(1000).encode())
        self.pre()
        for label, total, expect in (("over the cap", caps["hot_warn"] + 500, "over its size cap"),
                                     ("the stamp would cross it", caps["hot_warn"] - 5, "over its size cap"),
                                     ("well under it", 2000, None)):
            with self.subTest(label):
                h.write_bytes(hot(total).encode())
                before = h.read_bytes()
                rc, out = self.post(h, note=label)
                self.assertEqual(rc, 0, out)
                if expect:
                    self.assertEqual((self.stamped(out), h.read_bytes()), (([], {"ops/HOT.md": expect}), before))
                else:
                    self.assertEqual(self.stamped(out)[0], ["ops/HOT.md"])
                    self.assertIn("updated: ", h.read_text(encoding="utf-8"))

    def test_a_note_without_front_matter_is_left_alone_and_reported(self):
        a = put(self.root / "ops" / "a.md", "# plain\nbody\n")
        self.pre()
        a.write_bytes(b"# plain\nbody changed\n")
        rc, out = self.post(a)
        self.assertEqual((self.stamped(out), a.read_bytes()), (([], {"ops/a.md": "no front matter"}), b"# plain\nbody changed\n"))

    def test_a_note_written_after_pre_is_stamped_with_the_key_added(self):
        self.pre()
        a = put(self.root / "ops" / "new.md", "---\ntitle: new\n---\nfresh\n")
        rc, out = self.post(a)
        self.assertEqual(self.stamped(out)[0], ["ops/new.md"])
        self.assertRegex(a.read_text(encoding="utf-8"), r"^---\ntitle: new\nupdated: \d{4}-\d\d-\d\d\n---\nfresh\n$")

    def test_records_and_active_context_are_never_stamped(self):
        hist = put(self.root / "ops" / "history.md", "---\ntitle: h\n---\n## 2001-01-01 10:00 - t\n")
        ac = self.root / "active-context.md"
        ac.write_bytes(b"---\ntitle: ac\n---\nnow\n")
        self.pre()
        hist.write_bytes(hist.read_bytes() + b"more\n")
        ac.write_bytes(ac.read_bytes() + b"more\n")
        rc, out = self.post(hist, ac)
        self.assertEqual(self.stamped(out), ([], {}))
        self.assertNotIn(b"updated", hist.read_bytes() + ac.read_bytes())

    def test_a_file_outside_the_kb_is_ignored(self):
        outside = put(self.tmp / "elsewhere.md", "---\ntitle: x\n---\nbody\n")
        self.pre()
        outside.write_bytes(b"---\ntitle: x\n---\nbody2\n")
        rc, out = self.post(outside)
        self.assertEqual((rc, self.stamped(out), outside.read_bytes()), (0, ([], {}), b"---\ntitle: x\n---\nbody2\n"))

    def test_without_a_pre_baseline_nothing_is_stamped_and_the_report_says_why(self):
        a = put(self.root / "ops" / "a.md", self.NOTE)
        rc, out = self.post(a)
        self.assertEqual((rc, out["stamped"], a.read_bytes()), (0, [], self.NOTE.encode()))
        self.assertIn("--pre", out["stamp_skipped"]["*"])

    def test_a_blocked_save_stamps_nothing(self):
        a = put(self.root / "ops" / "a.md", self.NOTE)
        self.pre()
        key = "AKIA" + "Z" * 16
        a.write_bytes(self.NOTE.replace("body", f"key {key}").encode())
        rc, out = self.post(a)
        self.assertEqual(rc, 3)
        self.assertNotIn("stamped", out)
        self.assertIn(b"updated: 2001-01-01", a.read_bytes())


class Plugins(Base):
    """A copy of the kit's plugin folders, so the advisory tools beside save_driver.py can be faked, hidden or broken."""

    def setUp(self):
        super().setUp()
        self.kit = self.tmp / "kit" / "plugins"
        shutil.copytree(SCRIPTS, self.kit / "workbench-kb" / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        self.scripts = self.kit / "workbench-kb" / "scripts"
        self.env["SCAN_MARK"] = str(self.tmp / "scan-ran")

    def fake(self, skill, script, body):
        return put(self.kit / "workbench-core" / "skills" / skill / "scripts" / script, body)

    def fake_audit(self, body):
        return self.fake("brain-audit", "audit.py", body)

    def fake_scan(self, body):
        return self.fake("cleanup", "scan_legacy.py", body)

    def saved(self, *files, **kw):
        return self.post(*files, folder=self.scripts, **kw)

    SURFACE = {"surface": {"bytes": 1234, "core_lines": 9, "rules_over_cap": [], "paths_rules": [], "duplicates": [{"x": 1}, {"x": 2}],
                           "dead_refs": [], "generated_drift": [], "hidden_skills": []}, "exit": 1}

    def test_absent_tools_read_skipped_not_found_and_the_save_still_completes(self):
        rc, out = self.saved()
        self.assertEqual(rc, 0)
        self.assertEqual(out["advisories"], {"surface": "skipped: not found", "legacy_scan": "skipped: not found"})
        self.assertNotIn("action_required", out)
        self.assertEqual(out["metrics"], "recorded")

    def test_the_surface_audit_is_one_line_even_when_it_exits_one(self):
        self.fake_audit("import json, sys\nassert sys.argv[1:] == ['--surface', '--json'], sys.argv\n"
                        f"print(json.dumps({self.SURFACE!r}))\nsys.exit(1)\n")
        rc, out = self.saved()
        self.assertEqual(rc, 0)
        self.assertEqual(out["advisories"]["surface"], "1234 B always loaded, 2 finding(s); the brain-audit skill lists them")
        self.assertNotIn("action_required", out)

    def test_a_crashing_or_garbled_surface_tool_cannot_fail_the_save(self):
        for label, body in (("crash", "raise RuntimeError('boom')\n"), ("garbage", "print('not json at all')\n"),
                            ("empty", "pass\n"), ("wrong shape", "print('[1, 2]')\n"), ("no keys", "print('{}')\n")):
            with self.subTest(label):
                self.fake_audit(body)
                rc, out = self.saved(note=label)
                self.assertEqual(rc, 0, out)
                self.assertTrue(out["advisories"]["surface"].startswith("skipped: "), out["advisories"])
                self.assertEqual(out["metrics"], "recorded")
                self.assertNotIn("action_required", out)

    def test_a_garbled_answer_reads_no_usable_answer(self):
        self.fake_audit("print('garbage')\nraise SystemExit(3)\n")
        self.assertEqual(self.saved()[1]["advisories"]["surface"], "skipped: no usable answer (exit 3)")

    def test_a_tool_that_hangs_is_cut_off_at_the_timeout(self):
        self.fake_audit("import time\ntime.sleep(60)\n")
        t0 = time.time()
        rc, out = self.saved(env={"SAVE_ADVISORY_TIMEOUT": "1"})
        self.assertEqual((rc, out["advisories"]["surface"]), (0, "skipped: timed out after 1 s"), out)
        self.assertEqual(out["metrics"], "recorded")
        self.assertLess(time.time() - t0, 30)

    def test_an_advisory_that_raises_is_caught_per_advisory(self):
        code = ("import sys, json\nsys.path.insert(0, sys.argv[1])\nimport save_driver as sd\n"
                "def boom():\n    raise RuntimeError('x')\n"
                "sd._advise_surface = boom\nsd._advise_legacy = lambda: 'fine'\nprint(json.dumps(sd._advisories()))\n")
        r = subprocess.run([sys.executable, "-c", code, str(self.scripts)], capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"surface": "skipped: RuntimeError", "legacy_scan": "fine"})

    def stamp_age(self, days):
        state = Path(self.pre()["state_dir"])
        when = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        put(state / "legacy-scan.stamp", when + "\n")

    SCAN = ("import json, os, sys\nassert sys.argv[1] == '--root' and '--json' in sys.argv, sys.argv\n"
            "open(os.environ['SCAN_MARK'], 'a').write('x')\n"
            "print(json.dumps({'candidates': [{'path': 'a.md', 'reason': 'front matter status: archived', 'last_commit_days': None},\n"
            "  {'path': 'b.md', 'reason': 'front matter status: deprecated', 'last_commit_days': None}]}))\n")

    def test_the_legacy_scan_runs_at_most_weekly_and_ignores_archived_notes(self):
        self.fake_scan(self.SCAN)
        ran = self.tmp / "scan-ran"
        first = self.saved(note="one")[1]["advisories"]["legacy_scan"]
        self.assertEqual(first, "1 note(s) marked deprecated, obsolete or similar; the cleanup skill reviews them (report only)")
        self.assertEqual(ran.read_text(), "x")
        self.assertRegex(self.saved(note="two")[1]["advisories"]["legacy_scan"], r"^not due \(ran 0 day\(s\) ago\)$")
        self.stamp_age(3)
        self.assertRegex(self.saved(note="three")[1]["advisories"]["legacy_scan"], r"^not due \(ran 3 day")
        self.assertEqual(ran.read_text(), "x", "ran again inside the week")
        self.stamp_age(8)
        self.assertTrue(self.saved(note="four")[1]["advisories"]["legacy_scan"].startswith("1 note(s)"))
        self.assertEqual(ran.read_text(), "xx")

    def test_a_failed_legacy_scan_is_retried_by_the_next_save(self):
        self.fake_scan("raise SystemExit(2)\n")
        self.assertEqual(self.saved(note="one")[1]["advisories"]["legacy_scan"], "skipped: no usable answer (exit 2)")
        self.fake_scan(self.SCAN)
        self.assertTrue(self.saved(note="two")[1]["advisories"]["legacy_scan"].startswith("1 note(s)"))

    def test_a_skipped_save_runs_no_advisory(self):
        self.fake_audit("raise SystemExit(9)\n")
        rc, out = self.drv("--post", "--skip", "--note", "nothing happened", folder=self.scripts)
        self.assertNotIn("advisories", out)

    def test_the_real_tools_answer_in_the_kits_own_layout(self):
        for rel in ("brain-audit/scripts/audit.py", "cleanup/scripts/scan_legacy.py"):
            if not (CORE_TOOLS / rel).is_file():
                if REQUIRE:
                    self.fail(f"{rel} is missing")
                self.skipTest(f"{rel} is not in this checkout")
        put(self.root / "ops" / "gone.md", "---\ntitle: gone\nstatus: deprecated\n---\nold\n")
        put(self.root / "ops" / "kept.md", "---\ntitle: kept\nstatus: archived\n---\nretired on purpose\n")
        rc, out = self.post()
        self.assertEqual(rc, 0, out)
        self.assertRegex(out["advisories"]["surface"], r"^\d+ B always loaded, \d+ finding\(s\)")
        self.assertTrue(out["advisories"]["legacy_scan"].startswith("1 note(s) marked deprecated"), out["advisories"])


class TornMetrics(Base):
    def test_a_cut_off_last_line_does_not_swallow_the_next_row(self):
        state = Path(self.pre()["state_dir"])
        good = {"ts": "2001-01-01T00:00Z", "key": "old-save", "mode": "inline", "domains": ["ops"]}
        (state / "save-metrics.jsonl").write_text(json.dumps(good) + "\n" + '{"ts": "20', encoding="utf-8")   # no newline at the end
        rc, out = self.drv("--post", "--domains", "ops", "--note", "after a torn tail")
        self.assertEqual((rc, out["metrics"]), (0, "recorded"), out)
        self.assertIn("old-save", [r["key"] for r in self.metrics()])
        self.assertEqual([r["note"] for r in self.metrics() if "note" in r], ["after a torn tail"])
        rc, again = self.drv("--post", "--domains", "ops", "--note", "after a torn tail")
        self.assertEqual(again["metrics"], "already recorded", "the row was lost, so the next save recorded it twice")
        self.assertEqual(len([r for r in self.metrics() if r.get("note") == "after a torn tail"]), 1)

    def test_a_clean_file_gets_no_blank_line(self):
        self.drv("--post", "--domains", "ops", "--note", "first")
        self.drv("--post", "--domains", "ops", "--note", "second")
        text = (Path(self.pre()["state_dir"]) / "save-metrics.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("\n\n", text)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(len(text.splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
