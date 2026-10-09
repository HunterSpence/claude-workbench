"""Tests for knowledge-base retrieval: one hit per note, the two fused rankings, link resolution by file name, the plain-table
fallback, kb_eval's depth (hit@1, hit@5, MRR, latency percentiles, abstention, floors), kb_health's orphans / retrieval /
eval checks, the shipped template and its canned set. Run:
    python -m unittest discover -s plugins/workbench-kb/tests
Each test drives the scripts as subprocesses, the way the save skill does, on a throwaway copy of kb-template or on a
tiny KB built here. Every name and word below is invented."""
import functools
import importlib.util
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
SCRIPTS = PLUGIN / "scripts"
REPO = PLUGIN.parent.parent
CANNED = HERE / "kb_canned.json"
L, R = "[" * 2, "]" * 2          # KB link brackets, built so this file holds no literal link
REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
NO_FTS5 = {"KB_INDEX_NO_FTS5": "1"}


SIBLINGS = ("kb_audit", "kb_index", "kb_search", "kb_eval", "kb_health", "kb_demote", "save_driver", "savelock", "secretscan")


def load(name, env):
    """A private copy of a script module with `env` applied while it imports. The scripts bind the KB root at import, so
    their siblings are imported afresh too (and taken out of sys.modules again), never shared with another test."""
    saved = {m: sys.modules.pop(m) for m in SIBLINGS if m in sys.modules}
    spec = importlib.util.spec_from_file_location(f"{name}_retrieval_test", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    try:
        with mock.patch.dict(os.environ, env):
            spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(SCRIPTS))
        for m in SIBLINGS:
            sys.modules.pop(m, None)
        sys.modules.update(saved)
    return mod


def each_mode(fn):
    """Run a test body once on the FTS5 index and once on the plain-table fallback (fn gets the env that selects it)."""
    @functools.wraps(fn)
    def run(self):
        for label, env in (("fts5", {}), ("keyword fallback", NO_FTS5)):
            with self.subTest(mode=label):
                shutil.rmtree(self.tmp / "claude", ignore_errors=True)
                fn(self, env)
    return run


class Base(unittest.TestCase):
    template = False        # copy kb-template into the KB root

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-kbr-"))
        self.root = self.tmp / "kb-root"
        if self.template:
            shutil.copytree(REPO / "kb-template", self.root)
        else:
            (self.root / "ops").mkdir(parents=True)
            (self.root / "ops" / "HOT.md").write_text("---\ntitle: ops HOT\n---\n# ops\n", encoding="utf-8")
        self.env = {**os.environ, "WORKBENCH_KB_ROOT": str(self.root), "CLAUDE_CONFIG_DIR": str(self.tmp / "claude"),
                    "CLAUDE_CODE_SESSION_ID": "sess-a", "SAVE_LOCK_TIMEOUT": "5", "PYTHONIOENCODING": "utf-8"}
        self.env.pop("KB_INDEX_DB", None)
        self.env.pop("KB_INDEX_NO_FTS5", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_py(self, script, *args, env=None):
        r = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", env={**self.env, **(env or {})}, timeout=180)
        return r.returncode, r.stdout, r.stderr

    def search(self, q, *args, env=None):
        rc, out, err = self.run_py("kb_search.py", q, "--json", *args, env=env)
        self.assertEqual(rc, 0, out + err)
        return json.loads(out)

    def note(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p


class Ranking(Base):
    @each_mode
    def test_one_hit_per_note_and_a_long_note_cannot_fill_the_top_five(self, env):
        sections = "".join(f"## Part {i}\nthe orchid section {i} says orchid again and orchid once more\n\n" for i in range(30))
        self.note("ops/long.md", "---\ntitle: long\n---\n# Long\n" + sections)
        for i in range(6):
            self.note(f"ops/short{i}.md", f"---\ntitle: short {i}\n---\n# Short {i}\nan orchid is mentioned here once\n")
        hits = self.search("orchid", "--limit", "5", env=env)["hits"]
        paths = [h["path"] for h in hits]
        self.assertEqual(len(paths), len(set(paths)), "one hit per note")
        self.assertEqual(paths.count("ops/long.md"), 1)
        self.assertEqual(len(paths), 5)
        old = [h["path"] for h in self.search("orchid", "--limit", "5", "--all-chunks", env=env)["hits"]]
        self.assertGreater(old.count("ops/long.md"), 1, "--all-chunks is the old listing: a long note repeats")

    def test_the_python_api_is_one_hit_per_note_too(self):
        """kb_eval and other scripts call search() directly: its default must be the per-note list, not the chunk list."""
        self.note("ops/long.md", "---\ntitle: long\n---\n# Long\n" + "".join(f"## P{i}\nan orchid, an orchid\n\n" for i in range(12)))
        self.note("ops/short.md", "---\ntitle: short\n---\n# Short\nan orchid\n")
        ks = load("kb_search", self.env)
        with mock.patch.dict(os.environ, self.env):
            ks.ensure_index()
            paths = [h["path"] for h in ks.search("orchid")]
            self.assertEqual(sorted(paths), ["ops/long.md", "ops/short.md"])
            self.assertGreater(len(ks.search("orchid", all_chunks=True)), 2)

    @each_mode
    def test_limit_only_cuts_the_same_list(self, env):
        rng = random.Random(5)
        words = ["lumen", "harbor", "quartz", "meadow", "ferrite", "tundra", "vellum", "gantry"]
        for i in range(30):   # the words sit in titles and headings too, so both rankings have something to say
            self.note(f"ops/n{i}.md", f"---\ntitle: {rng.choice(words)} {rng.choice(words)} {i}\n---\n# {rng.choice(words)} {i}\n"
                      + "".join(f"## {rng.choice(words)}\n" + " ".join(rng.choice(words) for _ in range(30)) + "\n\n" for _ in range(3)))
        ks = load("kb_search", {**self.env, **env})
        with mock.patch.dict(os.environ, {**self.env, **env}):   # in-process: many searches, one index build
            ks.ensure_index()
            for q in ("lumen", "lumen harbor", "quartz meadow", "gantry tundra", "ferrite vellum lumen"):
                full = [(h["path"], h["line"], h["score"]) for h in ks.search(q, None, 30)]
                self.assertGreater(len(full), 10, q)
                for n in (1, 3, 7, 12):
                    cut = [(h["path"], h["line"], h["score"]) for h in ks.search(q, None, n)]
                    self.assertEqual(cut, full[:n], f"{q!r} --limit {n} must be a prefix of --limit 30")

    @each_mode
    def test_a_note_found_by_its_path_or_title_alone_is_returned(self, env):
        self.note("ops/zymurgy-ledger.md", "---\ntitle: Fermentation log\n---\n# Entries\nbarley and hops, written up weekly\n")
        hits = self.search("zymurgy", env=env)["hits"]
        self.assertEqual([h["path"] for h in hits], ["ops/zymurgy-ledger.md"], "the note arm finds a word that is only in the path")
        self.assertIn("barley", hits[0]["snippet"], "a section is shown even though no chunk matched")
        self.assertEqual([h["path"] for h in self.search("fermentation", env=env)["hits"]], ["ops/zymurgy-ledger.md"], "title")
        self.note("ops/ledger-misc.md", "---\ntitle: misc\n---\n# Misc\nnothing to do with it\n")
        self.assertEqual([h["path"] for h in self.search("zymurgy ledger", env=env)["hits"]], ["ops/zymurgy-ledger.md"],
                         "both words are asked for: a note with one of them in its path is not a match while one has both")

    @each_mode
    def test_a_partial_note_match_never_outvotes_an_all_terms_match(self, env):
        self.note("ops/zeta.md", "---\ntitle: zeta\n---\n# Zeta\nthe alpha beta gamma procedure, written out\n")
        self.note("ops/alpha-hub.md", "---\ntitle: alpha\n---\n# Alpha\nunrelated text about something else\n")
        self.assertEqual([h["path"] for h in self.search("alpha beta gamma", env=env)["hits"]], ["ops/zeta.md"],
                         "a note that has only one of the words in its title is not returned beside a note that has all three")
        self.assertEqual([h["path"] for h in self.search("alpha beta delta", env=env)["hits"]], ["ops/alpha-hub.md", "ops/zeta.md"],
                         "no note has every word: only then does any word do")

    @each_mode
    def test_a_note_found_by_both_arms_beats_one_found_by_the_chunk_arm_alone(self, env):
        self.note("ops/aaa.md", "---\ntitle: aaa\n---\n# Aaa\nquartz quartz quartz quartz\n")
        self.note("ops/quartz-guide.md", "---\ntitle: guide\n---\n# Guide\na single quartz mention among a good many other words to pad it out well\n")
        self.assertEqual(self.search("quartz", env=env)["hits"][0]["path"], "ops/quartz-guide.md")

    @each_mode
    def test_superseded_chunks_are_tagged_and_rank_lower(self, env):
        self.note("ops/old.md", "---\ntitle: old\n---\n# Old\nplover plover plover plover. SUPERSEDED earlier statement.\n")
        self.note("ops/new.md", "---\ntitle: new\n---\n# New\nplover. A later statement that still stands, with some filler words in it.\n")
        hits = self.search("plover", env=env)["hits"]
        self.assertEqual([(h["path"], h["superseded"]) for h in hits], [("ops/new.md", False), ("ops/old.md", True)])
        rc, out, _ = self.run_py("kb_search.py", "plover", env=env)
        self.assertRegex(out, r"ops/old\.md:\d+  \[Old\]  \[SUPERSEDED\] ")
        self.assertNotRegex(out, r"ops/new\.md:\d+  \[New\]  \[SUPERSEDED\]")

    def test_json_says_which_ranking_mode_ran(self):
        self.note("ops/a.md", "---\ntitle: a\n---\n# A\nsome text\n")
        self.assertEqual(self.search("text")["mode"], "fts5")
        shutil.rmtree(self.tmp / "claude")
        self.assertEqual(self.search("text", env=NO_FTS5)["mode"], "keyword fallback")

    def test_domain_filter_applies_to_both_arms(self):
        self.note("ops/zinnia-ledger.md", "---\ntitle: x\n---\n# X\nbody\n")
        self.note("data/HOT.md", "---\ntitle: data HOT\n---\n# data\n")
        self.note("data/zinnia.md", "---\ntitle: zinnia\n---\n# Z\nzinnia\n")
        self.assertEqual([h["path"] for h in self.search("zinnia", "--domain", "ops")["hits"]], ["ops/zinnia-ledger.md"])
        self.assertEqual([h["path"] for h in self.search("zinnia", "--domain", "data")["hits"]], ["data/zinnia.md"])

    def test_an_index_from_an_older_kit_is_rebuilt(self):
        self.note("ops/a.md", "---\ntitle: a\n---\n# A\nsome text\n")
        self.assertTrue(self.search("text")["rebuilt"])
        self.assertFalse(self.search("text")["rebuilt"])
        db = next((self.tmp / "claude" / "workbench" / "cache").glob("kb-*.db"))
        con = sqlite3.connect(db)
        con.execute("update meta set v = '1' where k = 'schema'")
        con.commit()
        con.close()
        self.assertIn("older", self.search("text")["rebuilt"])
        rc, out, err = self.run_py("kb_search.py", "text", "--no-rebuild", "--json")   # fine again after the rebuild
        self.assertEqual(rc, 0, err)


class Links(Base):
    def test_a_bare_file_name_resolves_when_exactly_one_note_has_it(self):
        ki = load("kb_index", self.env)
        existing = {"_shared/bug-cards.md", "ops/a.md", "x/dup.md", "y/dup.md", "x/n.md", "00-index.md"}
        r = lambda t, src="ops/a.md": ki.resolve(t, src, existing)   # noqa: E731
        self.assertEqual(r("bug-cards"), "_shared/bug-cards.md", "a unique file name resolves from anywhere")
        self.assertEqual(r("Bug-Cards|the cards"), "_shared/bug-cards.md", "case and alias are ignored")
        self.assertEqual(r("bug-cards#Fix"), "_shared/bug-cards.md")
        self.assertIsNone(r("dup"), "two notes share the name: guessing would link to the wrong one")
        self.assertEqual(r("dup", "x/n.md"), "x/dup.md", "a sibling still wins over the stem rule")
        self.assertIsNone(r("missing"))
        self.assertIsNone(r("sub/bug-cards"), "a path is exact: only a bare name falls back to the stem")
        self.assertEqual(r("00-index"), "00-index.md")

    def test_search_related_follows_a_stem_link(self):
        self.note("_shared/bug-cards.md", "---\ntitle: cards\n---\n# Cards\nbody\n")
        self.note("ops/a.md", f"---\ntitle: a\n---\n# A\nsee {L}bug-cards{R} and {L}HOT{R}\n")
        self.note("data/HOT.md", "---\ntitle: data HOT\n---\n# data\n")
        rc, out, err = self.run_py("kb_search.py", "--related", "ops/a.md", "--json")
        self.assertEqual(rc, 0, err)
        self.assertEqual(sorted(r["path"] for r in json.loads(out)), ["_shared/bug-cards.md", "ops/HOT.md"])   # HOT: beside the source
        rc, out, _ = self.run_py("kb_health.py", "--json")
        dead = next(r for r in json.loads(out)["results"] if r["check"] == "dead-links")
        self.assertEqual(dead["status"], "PASS", dead["detail"])


class Health(Base):
    def health(self, *args, env=None):
        rc, out, err = self.run_py("kb_health.py", "--json", *args, env=env)
        data = json.loads(out)
        self.assertEqual(data["exit"], rc)
        return rc, {r["check"]: r for r in data["results"]}

    def test_json_shape_and_nothing_else_on_stdout(self):
        rc, out, _ = self.run_py("kb_health.py", "--json")
        data = json.loads(out)
        self.assertEqual(set(data), {"kb_root", "results", "exit"})
        self.assertEqual(data["kb_root"], self.root.as_posix())
        self.assertTrue(all(set(r) == {"check", "status", "detail"} and r["status"] in ("PASS", "WARN", "FAIL", "INFO")
                            for r in data["results"]))
        self.assertEqual([r["check"] for r in data["results"]],
                         ["layout", "caps", "frontmatter", "index", "dead-links", "orphans", "retrieval", "secrets", "git"])

    def test_json_exit_is_one_on_a_failure(self):
        self.note("ops/leak.md", "---\ntitle: x\n---\nkey " + "AKIA" + "Z" * 16 + "\n")
        rc, res = self.health()
        self.assertEqual((rc, res["secrets"]["status"]), (1, "FAIL"))
        self.assertNotIn("AKIA" + "Z" * 16, json.dumps(res))

    def test_a_missing_kb_is_a_json_failure(self):
        shutil.rmtree(self.root)
        rc, res = self.health()
        self.assertEqual((rc, list(res)), (1, ["layout"]))

    def test_orphans_warn_until_something_links_to_the_note(self):
        self.note("ops/lonely.md", "---\ntitle: lonely\n---\n# Lonely\nnothing links here\n")
        self.note("ops/linked.md", "---\ntitle: linked\n---\n# Linked\nbody\n")
        self.note("ops/HOT.md", f"---\ntitle: ops HOT\n---\n# ops\nsee {L}ops/linked{R}\n")
        rc, res = self.health()
        self.assertEqual((rc, res["orphans"]["status"]), (0, "WARN"), "a warning never fails the run")
        self.assertIn("ops/lonely.md", res["orphans"]["detail"])
        self.assertNotIn("ops/linked.md", res["orphans"]["detail"])
        self.note("ops/linked.md", f"---\ntitle: linked\n---\n# Linked\nsee {L}ops/lonely{R} and itself {L}ops/linked{R}\n")
        self.assertEqual(self.health()[1]["orphans"]["status"], "PASS")
        self.note("ops/lonely.md", "---\ntitle: lonely\n---\n# Lonely\nnothing links here\n")
        self.note("ops/selfish.md", f"---\ntitle: selfish\n---\n# Selfish\nonly {L}ops/selfish{R}\n")   # a self-link is not an inbound link
        res = self.health()[1]["orphans"]
        self.assertEqual(res["status"], "WARN")
        self.assertIn("ops/selfish.md", res["detail"])

    def test_retrieval_samples_every_tier_that_holds_notes(self):
        self.note("ops/HOT.md", "---\ntitle: ops HOT\n---\n# ops\nwarehouse inventory tally rules\n")
        self.note("ops/topic.md", "---\ntitle: topic\n---\n# Topic\nhydrangea trellis notes\n")
        self.note("ops/history.md", "# ops history\n\n## 2001-01-01 10:00 - old task\n- Outcome: mulberry orchard survey\n")
        self.note("ops/history/2000-12.md", "# ops history\n\n## 2000-12-01 10:00 - older\n- Outcome: cardamom harvest tally\n")
        rc, res = self.health()
        self.assertEqual((res["retrieval"]["status"], rc), ("PASS", 0), res["retrieval"]["detail"])
        self.assertEqual(res["retrieval"]["detail"], "notes reached by search: hot 1/1, topic 1/1, history 2/2")

    def test_retrieval_fails_when_a_whole_tier_is_missing_from_the_index(self):
        self.note("ops/history.md", "# ops history\n\n## 2001-01-01 10:00 - old task\n- Outcome: mulberry orchard survey\n")
        self.note("ops/topic.md", "---\ntitle: topic\n---\n# Topic\nhydrangea trellis notes\n")
        env = {**self.env, "CLAUDE_CONFIG_DIR": str(self.tmp / "claude")}
        with mock.patch.dict(os.environ, env):
            kh = load("kb_health", env)
            real = kh.kb_index.build

            def build_without_history(*a, **k):
                out = real(*a, **k)
                con = sqlite3.connect(kh.kb_audit.index_db())
                for table in ("chunk", "notefts", "section"):
                    con.execute(f"delete from {table} where path like '%history%'")
                con.commit()
                con.close()
                return out
            with mock.patch.object(kh.kb_index, "build", build_without_history):
                kh.check_index_and_links()
                kh.check_retrieval()
        res = {n: (s, d) for n, s, d in kh.RESULTS}
        self.assertEqual(res["retrieval"][0], "FAIL")
        self.assertIn("history 0/1", res["retrieval"][1])
        self.assertIn("topic 1/1", res["retrieval"][1])

    def test_eval_check_gates_on_the_floors_of_the_set(self):
        self.note("ops/proxy.md", "---\ntitle: proxy\n---\n# Proxy\nrotate the inspection certificate every quarter\n")
        cases = [{"q": "rotate inspection certificate", "expect": ["ops/proxy.md"]},
                 {"q": "wibblefrot snarkle plonkity", "abstain": True}]
        good = self.tmp / "good.json"
        good.write_text(json.dumps({"cases": cases, "_floors": {"cases": 1, "hit@1": 1.0, "hit@5": 1.0, "mrr": 1.0,
                                                               "abstain_cases": 1, "abstain": 1.0}}), encoding="utf-8")
        rc, res = self.health("--eval", good)
        self.assertEqual((rc, res["eval"]["status"]), (0, "PASS"), res["eval"]["detail"])
        self.assertEqual(list(res)[-1], "eval")
        bad = self.tmp / "bad.json"
        bad.write_text(json.dumps({"cases": [{**cases[0], "expect": ["ops/elsewhere.md"]}, cases[1]],
                                   "_floors": json.loads(good.read_text())["_floors"]}), encoding="utf-8")
        rc, res = self.health("--eval", bad)
        self.assertEqual((rc, res["eval"]["status"]), (1, "FAIL"))
        self.assertIn("hit@1 0.0 < 1.0", res["eval"]["detail"])
        nofloor = self.tmp / "nofloor.json"
        nofloor.write_text(json.dumps({"cases": cases}), encoding="utf-8")
        self.assertEqual(self.health("--eval", nofloor)[1]["eval"]["status"], "INFO")
        rc, res = self.health("--eval", self.tmp / "missing.json")
        self.assertEqual((rc, res["eval"]["status"]), (1, "FAIL"))


class Eval(Base):
    def setUp(self):
        super().setUp()
        self.note("ops/proxy.md", "---\ntitle: proxy\n---\n# Proxy\n\n## Rollover\nrotate the inspection certificate every quarter\n\n"
                                  "## Renewal\nrenew the inspection certificate when the vendor console asks\n")
        self.note("ops/other.md", "---\ntitle: other\n---\n# Other\ninspection of the build\n")

    def ev(self, cases, *args, floors=None):
        f = self.tmp / "set.json"
        f.write_text(json.dumps({"cases": cases, **({"_floors": floors} if floors else {})}), encoding="utf-8")
        rc, out, err = self.run_py("kb_eval.py", "--set", f, *args)
        return rc, (json.loads(out) if out.lstrip().startswith("{") else out), err

    def test_metrics_latency_and_abstention(self):
        cases = [{"q": "rotate inspection certificate", "expect": ["ops/proxy.md"]},
                 {"q": "inspection", "expect": ["ops/other.md"]},
                 {"q": "zebra migration plan", "expect": ["ops/zebra.md"]},
                 {"q": "wibblefrot snarkle plonkity", "abstain": True},
                 {"q": "rotate inspection certificate", "abstain": True}]
        rc, r, err = self.ev(cases, "--json")
        self.assertEqual(rc, 0, err)
        self.assertEqual((r["cases"], r["abstain_cases"], r["abstain"]), (3, 2, 0.5))
        self.assertEqual(r["hit@5"], round(2 / 3, 3))
        self.assertLessEqual(r["hit@1"], r["hit@5"])
        self.assertGreaterEqual(r["mrr"], 0.5)
        self.assertEqual(set(r["latency_ms"]), {"p50", "p95", "mean"})
        self.assertLessEqual(r["latency_ms"]["p50"], r["latency_ms"]["p95"])
        self.assertEqual([m["q"] for m in r["misses"]], ["zebra migration plan"])
        self.assertEqual([m["q"] for m in r["false_hits"]], ["rotate inspection certificate"], "a query the KB answers is not quiet")
        self.assertNotIn("rows", r, "--json is the summary; --per-query adds the rows")
        rc, rows, _ = self.ev(cases, "--per-query")
        self.assertEqual([x["kind"] for x in rows["rows"]], ["answer"] * 3 + ["abstain"] * 2)
        self.assertIsNone(rows["rows"][2]["rank"])
        self.assertTrue(all("ms" in x and "top" in x for x in rows["rows"]))

    def test_percentiles(self):
        ke = load("kb_eval", self.env)
        self.assertEqual((ke.pct([], 95), ke.pct([7], 50), ke.pct([7], 95)), (0.0, 7, 7))
        xs = list(range(1, 101))
        self.assertEqual((ke.pct(xs, 50), ke.pct(xs, 95), ke.pct(xs, 100)), (50, 95, 100))
        self.assertEqual(ke.pct([3, 1, 2], 50), 2)

    def test_a_heading_picks_the_section_that_must_be_shown(self):
        q = "vendor console"        # only the Renewal section holds both words
        rc, r, _ = self.ev([{"q": q, "expect": ["ops/proxy.md"], "heading": "Renewal"}], "--per-query")
        self.assertEqual(r["rows"][0]["rank"], 1)
        for wrong in ("Rollover", "No such section"):
            rc, r, _ = self.ev([{"q": q, "expect": ["ops/proxy.md"], "heading": wrong}], "--per-query")
            self.assertIsNone(r["rows"][0]["rank"], wrong)
        rc, r, _ = self.ev([{"q": q, "expect": ["ops/proxy.md"]}], "--per-query")
        self.assertEqual(r["rows"][0]["rank"], 1, "no heading: the note alone counts")

    def test_two_runs_agree_on_everything_but_time(self):
        cases = [{"q": "rotate inspection certificate", "expect": ["ops/proxy.md"]}, {"q": "inspection", "expect": ["ops/other.md"]},
                 {"q": "wibblefrot snarkle plonkity", "abstain": True}]

        def strip(r):
            r.pop("latency_ms")
            for x in r["rows"]:
                x.pop("ms")
            return r
        a, b = (strip(self.ev(cases, "--per-query")[1]) for _ in range(2))
        self.assertEqual(a, b)

    def test_floors_set_the_exit_code(self):
        cases = [{"q": "rotate inspection certificate", "expect": ["ops/proxy.md"]},
                 {"q": "zebra migration plan", "expect": ["ops/zebra.md"]}]
        rc, r, _ = self.ev(cases, "--json", floors={"cases": 2, "hit@1": 0.5, "hit@5": 0.5})
        self.assertEqual((rc, r["below_floors"]), (0, []))
        rc, r, _ = self.ev(cases, "--json", floors={"hit@1": 0.51})
        self.assertEqual((rc, r["below_floors"]), (1, ["hit@1"]))
        rc, r, _ = self.ev(cases, "--json", floors={"cases": 3})
        self.assertEqual((rc, r["below_floors"]), (1, ["cases"]), "dropping cases cannot lower the bar")
        rc, r, _ = self.ev(cases, "--json", floors={"abstain_cases": 1, "abstain": 1.0})
        self.assertEqual((rc, r["below_floors"]), (1, ["abstain_cases", "abstain"]))
        rc, out, _ = self.ev(cases, floors={"mrr": 0.99})
        self.assertEqual(rc, 1)
        self.assertIn("BELOW FLOORS: mrr 0.5", out)

    def test_an_invalid_set_exits_two(self):
        f = self.tmp / "set.json"
        for body in ('{"cases": []}', '{"cases": [{"q": "x"}]}', '{"cases": [{"q": "<placeholder>", "expect": ["a.md"]}]}',
                     '{"cases": [{"q": "x", "expect": ["a.md"]}], "_floors": {"hit@1": "high"}}', "not json"):
            f.write_text(body, encoding="utf-8")
            self.assertEqual(self.run_py("kb_eval.py", "--set", f)[0], 2, body)
        self.assertEqual(self.run_py("kb_eval.py", "--set", self.tmp / "nope.json")[0], 2)

    def test_init_writes_a_starter_that_is_refused_until_edited(self):
        self.assertEqual(self.run_py("kb_eval.py", "--init")[0], 0)
        self.assertEqual(self.run_py("kb_eval.py")[0], 2)
        self.assertIn("left alone", self.run_py("kb_eval.py", "--init")[1])


class Template(Base):
    template = True

    def test_every_domain_links_back_to_the_index_and_the_graph_connects(self):
        for d in ("_shared", "platform", "infra", "data", "ai", "security", "ops", "projects"):
            self.assertIn(f"- part_of {L}00-index{R}", (self.root / d / "HOT.md").read_text(encoding="utf-8"), d)
        shared = (self.root / "_shared" / "HOT.md").read_text(encoding="utf-8")
        for target in ["_shared/bug-cards"] + [f"_shared/digests/{p.stem}" for p in sorted((self.root / "_shared" / "digests").glob("*.md"))]:
            self.assertIn(f"{L}{target}{R}", shared, "_shared lists the digests and the bug cards")
        rc, out, err = self.run_py("kb_search.py", "--related", "ops/HOT.md", "--depth", "2", "--json")
        self.assertEqual(rc, 0, err)
        reached = {r["path"]: r["depth"] for r in json.loads(out)}
        self.assertEqual(reached["00-index.md"], 1)
        self.assertEqual(reached["_shared/HOT.md"], 2)
        self.assertEqual(reached["_shared/bug-cards.md"], 2)

    def test_the_template_is_healthy_and_has_no_dead_link_or_orphan(self):
        rc, out, err = self.run_py("kb_health.py", "--json")
        self.assertEqual(rc, 0, out + err)
        res = {r["check"]: r for r in json.loads(out)["results"]}
        for check in ("layout", "caps", "frontmatter", "index", "dead-links", "orphans", "retrieval", "secrets"):
            self.assertEqual(res[check]["status"], "PASS", f"{check}: {res[check]['detail']}")
        self.assertGreaterEqual(len([d for d in self.root.iterdir() if (d / "HOT.md").exists()]), 8)

    def test_every_template_file_that_names_a_note_names_one(self):
        """No literal link in the kit's own scripts: the template alone ships wikilinks, each to a note it holds."""
        notes = {p.relative_to(self.root).as_posix()[:-3] for p in self.root.rglob("*.md")}
        for p in self.root.rglob("*.md"):
            for t in re.findall(r"\[\[([^\]\n]+)\]\]", p.read_text(encoding="utf-8")):
                self.assertIn(t.split("|")[0].split("#")[0], notes, f"{p.name} links to a note the template lacks")


class Canned(Base):
    """The shipped known-answer set, run on a sandbox copy of the template. The floors in the file are the first run's
    exact result, so one case that stops being found, or ranks lower, fails here."""
    template = True

    def run_set(self, path, *args):
        return self.run_py("kb_eval.py", "--set", path, *args)

    def strip(self, r):
        r.pop("latency_ms")
        for x in r["rows"]:
            x.pop("ms")
        return r

    def test_the_set_meets_its_floors_twice_with_identical_numbers(self):
        runs = []
        for _ in range(2):
            rc, out, err = self.run_set(CANNED, "--per-query")
            self.assertEqual(rc, 0, out + err)
            runs.append(self.strip(json.loads(out)))
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(runs[0]["below_floors"], [])

    def test_the_floors_are_the_first_runs_exact_counts(self):
        data = json.loads(CANNED.read_text(encoding="utf-8"))
        floors = data["_floors"]
        answers = [c for c in data["cases"] if not c.get("abstain")]
        self.assertEqual(floors["cases"], len(answers))
        self.assertEqual(floors["abstain_cases"], len(data["cases"]) - len(answers))
        rc, out, _ = self.run_set(CANNED, "--json")
        r = json.loads(out)
        for k in ("cases", "abstain_cases", "hit@1", "hit@5", "mrr", "abstain"):
            self.assertEqual(r[k], floors[k], f"{k}: the floor is the run, not below it")

    def test_the_set_only_names_content_that_later_edits_leave_alone(self):
        """Wave 3 edits other digests, the README and the facts file; these cases may name only the bug cards, two digests,
        the HOT files and the index."""
        allowed = re.compile(r"^(_shared/bug-cards\.md|_shared/digests/(claude-code-mechanics|testing)\.md|[a-z_]+/HOT\.md|00-index\.md)$")
        for c in json.loads(CANNED.read_text(encoding="utf-8"))["cases"]:
            for e in c.get("expect", []):
                self.assertRegex(e, allowed)
                self.assertTrue((self.root / e).is_file(), e)

    def test_one_broken_case_fails_the_floors_through_eval_and_health(self):
        data = json.loads(CANNED.read_text(encoding="utf-8"))
        rows = json.loads(self.run_set(CANNED, "--per-query")[1])["rows"]
        first = next(i for i, x in enumerate(rows) if x.get("rank") == 1)       # a case that is found at rank one today
        broken = json.loads(json.dumps(data))
        broken["cases"][first]["expect"] = ["ops/HOT.md"]                          # its answer "moved" to a note that is not it
        f = self.tmp / "broken.json"
        f.write_text(json.dumps(broken), encoding="utf-8")
        rc, out, _ = self.run_set(f, "--json")
        r = json.loads(out)
        self.assertEqual(rc, 1)
        self.assertIn("hit@1", r["below_floors"])
        rc, out, _ = self.run_py("kb_health.py", "--json", "--eval", f)
        self.assertEqual((rc, next(x for x in json.loads(out)["results"] if x["check"] == "eval")["status"]), (1, "FAIL"))
        rc, out, _ = self.run_py("kb_health.py", "--json", "--eval", CANNED)
        self.assertEqual((rc, next(x for x in json.loads(out)["results"] if x["check"] == "eval")["status"]), (0, "PASS"))
        quiet = json.loads(json.dumps(data))
        quiet["cases"][-1] = {"q": "unpinned npx uvx newest", "abstain": True}   # an abstain case the KB answers
        f.write_text(json.dumps(quiet), encoding="utf-8")
        rc, out, _ = self.run_set(f, "--json")
        self.assertEqual((rc, json.loads(out)["below_floors"]), (1, ["abstain"]))


class Latency(unittest.TestCase):
    """A 2,000-note synthetic KB: search stays well inside 300 ms at p95 (the budget), and the CLI answers inside it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wb-kblat-"))
        cls.root = cls.tmp / "kb"
        rng = random.Random(7)
        syl = ["ba", "ke", "lo", "mi", "nu", "ra", "so", "ti", "vu", "xe", "da", "fi", "go", "hu", "jo", "la", "me", "ni", "po", "qui"]
        vocab = ["".join(rng.choice(syl) for _ in range(rng.randint(2, 4))) for _ in range(4000)]
        domains = ["_shared", "platform", "infra", "data", "ai", "security", "ops", "projects"]
        for d in domains:
            (cls.root / d).mkdir(parents=True)
            (cls.root / d / "HOT.md").write_text(f"---\ntitle: {d} HOT\n---\n# {d}\n", encoding="utf-8")
        cls.texts = []
        for i in range(2000):
            secs = "\n".join(f"## {' '.join(rng.sample(vocab, 3))}\n" + " ".join(rng.choice(vocab) for _ in range(rng.randint(60, 160))) + "\n"
                             for _ in range(rng.randint(2, 5)))
            text = f"---\ntitle: {' '.join(rng.sample(vocab, 3))}\n---\n# {' '.join(rng.sample(vocab, 2))}\n{secs}"
            (cls.root / domains[i % 8] / f"note-{i}.md").write_text(text, encoding="utf-8")
            cls.texts.append(text)
        cls.env = {"WORKBENCH_KB_ROOT": str(cls.root), "CLAUDE_CONFIG_DIR": str(cls.tmp / "claude")}
        cls.queries = []
        for _ in range(60):   # three words of one note: all-terms match
            cls.queries.append(" ".join(rng.sample(re.findall(r"[a-z]{4,}", rng.choice(cls.texts)), 3)))
        for _ in range(20):   # words of three notes: nothing matches all, so the any-term fallback runs
            cls.queries.append(" ".join(rng.choice(re.findall(r"[a-z]{4,}", rng.choice(cls.texts))) for _ in range(3)))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_search_p95_is_under_the_budget(self):
        ks = load("kb_search", self.env)
        with mock.patch.dict(os.environ, self.env):
            self.assertTrue(ks.kb_index.build().startswith("ok (2008 notes"))
            ks.search(self.queries[0])
            ms = []
            for q in self.queries:
                t0 = time.perf_counter()
                hits = ks.search(q, None, 10)
                ms.append((time.perf_counter() - t0) * 1000)
                self.assertLessEqual(len(hits), 10)
        ms.sort()
        p95 = ms[int(len(ms) * 0.95) - 1]
        self.assertLess(p95, 300, f"search p95 {p95:.0f} ms over {len(ms)} queries on 2,000 notes")

    def test_the_command_line_answers_inside_the_budget(self):
        env = {**os.environ, **self.env, "PYTHONIOENCODING": "utf-8"}
        ms = []
        for q in self.queries[:12]:
            t0 = time.perf_counter()
            r = subprocess.run([sys.executable, str(SCRIPTS / "kb_search.py"), q, "--json"], capture_output=True, text=True,
                               encoding="utf-8", env=env, timeout=120)
            ms.append((time.perf_counter() - t0) * 1000)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(sorted(ms)[len(ms) // 2], 300, "median of a whole command, Python start-up included")


if __name__ == "__main__":
    unittest.main()
