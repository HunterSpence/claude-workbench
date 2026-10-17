"""Tests for knowledge-base retrieval: one hit per note, the two fused rankings, link resolution by file name, the plain-table
fallback, kb_eval's depth (hit@1, hit@5, MRR, latency percentiles, abstention, floors), kb_health's orphans / retrieval /
eval checks, the shipped template and its canned set. Run:
    python -m unittest discover -s plugins/workbench-kb/tests
Each test drives the scripts as subprocesses, the way the save skill does, on a throwaway copy of kb-template or on a
tiny KB built here. Every name and word below is invented."""
import contextlib
import functools
import importlib.util
import io
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
        res = self.search("text")
        self.assertEqual((res["mode"], res["ranking"]), ("index", "fts5"))
        shutil.rmtree(self.tmp / "claude")
        res = self.search("text", env=NO_FTS5)
        self.assertEqual((res["mode"], res["ranking"]), ("index", "keyword fallback"))
        self.assertNotIn("warning", res)

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
        for old in ("1", "2"):      # 2 is the schema the previous kit built: the resolver changed since, so it is rebuilt too
            con = sqlite3.connect(db)
            con.execute("update meta set v = ? where k = 'schema'", (old,))
            con.commit()
            con.close()
            self.assertIn("older", self.search("text")["rebuilt"], old)
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


    def test_the_resolver_ignores_case_turns_spaces_into_hyphens_and_matches_titles(self):
        ki = load("kb_index", self.env)
        existing = {"ops/HOT.md", "ops/my-note.md", "ops/a.md", "infra/x.md", "infra/y.md", "_shared/Mixed-Case.md",
                    "t1/n1.md", "t2/n2.md", "d1/dup.md", "d2/DUP.md", "cc/N.md", "CC/n.md", "ops/b.md", "ops/B.md", "docs/00-Index.md"}
        titles = {"t1/n1.md": "Release Checklist", "t2/n2.md": "Release  checklist", "infra/y.md": "Rollback Plan", "ops/a.md": None}
        names = ki.stems_of(existing, titles)
        r = lambda t, src="ops/a.md": ki.resolve(t, src, existing, names)   # noqa: E731
        self.assertEqual(r("Ops/HOT"), "ops/HOT.md", "a folder-prefixed link ignores case")
        self.assertEqual(r("ops/hot"), "ops/HOT.md")
        self.assertEqual(r("OPS/HOT.md|alias#part"), "ops/HOT.md")
        self.assertEqual(r("My Note"), "ops/my-note.md", "spaces become hyphens, beside the source")
        self.assertEqual(r("My Note", "infra/x.md"), "ops/my-note.md", "...and anywhere in the KB when one note has that name")
        self.assertEqual(r("ops/My Note"), "ops/my-note.md")
        self.assertEqual(r("mixed case"), "_shared/Mixed-Case.md")
        self.assertEqual(r("Docs"), "docs/00-Index.md", "a folder link finds its index whatever the case")
        self.assertEqual(r("Rollback Plan"), "infra/y.md", "a unique front-matter title")
        self.assertIsNone(r("Release Checklist"), "two notes share the title: stays dead")
        self.assertIsNone(r("DUP"), "two notes share the name: stays dead")
        self.assertEqual(r("d1/DUP"), "d1/dup.md", "a full path is still unique")
        self.assertIsNone(r("Cc/n"), "two paths that differ only in case: stays dead")
        self.assertEqual(r("ops/b"), "ops/b.md", "an exact spelling wins over the case-blind match")
        self.assertEqual(r("ops/B"), "ops/B.md")
        self.assertIsNone(r("Ops/Missing Note"))
        self.assertIsNone(r("Rollout Plan"), "negative control: no note has that name or title")
        self.assertIsNone(ki.resolve("Rollback Plan", "ops/a.md", existing), "without titles there is no title rule")

    def test_template_stand_ins_and_commented_links_are_not_links(self):
        ki = load("kb_index", self.env)
        raw = "\n".join([
            f"see {L}...{R} and {L}<name>{R} and {L}ops/...{R} and {L}<ops/note>|alias{R} and {L}real-one{R}",
            f"`{L}x{R}` in code and {L}outside-code{R}",
            f"<!-- {L}hidden{R} --> then {L}after-comment{R} <!-- {L}also-hidden{R}",
            f"{L}still-hidden{R}",
            f"--> {L}back-in{R}",
            "```", f"{L}in-fence{R}", "```",
            f"<!-- a {L}one-line{R} comment --> {L}last{R}"])
        self.assertEqual([t for _n, t in ki.links_for(raw)], ["real-one", "outside-code", "after-comment", "back-in", "last"])
        self.assertEqual([n for n, _t in ki.links_for(raw)], [1, 2, 3, 5, 9])

    def test_a_comment_opener_inside_inline_code_hides_no_link(self):
        ki = load("kb_index", self.env)
        raw = f"write `<!--` to open a comment, see {L}after-code{R}\nand {L}next-line{R}\n<!-- {L}hidden{R} --> {L}visible{R}\n"
        self.assertEqual([(n, t) for n, t in ki.links_for(raw)], [(1, "after-code"), (2, "next-line"), (3, "visible")])

    def test_the_index_resolves_titles_and_keeps_stand_ins_out_of_the_dead_links(self):
        self.note("ops/release.md", "---\ntitle: Release Checklist\n---\n# Heading Only Words\nsteps\n")
        self.note("ops/b.md", f"---\ntitle: b\n---\n# B\nsee {L}Release Checklist{R} and {L}Ops/hot{R} and {L}...{R} {L}<x>{R}\n"
                  f"<!-- {L}gone-for-good{R} -->\n")
        rc, out, err = self.run_py("kb_search.py", "--related", "ops/b.md", "--json")
        self.assertEqual(rc, 0, err)
        self.assertEqual(sorted(r["path"] for r in json.loads(out)), ["ops/HOT.md", "ops/release.md"])
        rc, out, _ = self.run_py("kb_health.py", "--json")
        dead = next(r for r in json.loads(out)["results"] if r["check"] == "dead-links")
        self.assertEqual(dead["status"], "PASS", dead["detail"])
        self.note("ops/c.md", f"---\ntitle: c\n---\nsee {L}Heading Only Words{R} and {L}x{R}\n")    # a heading is not a title; x is a real miss
        rc, out, _ = self.run_py("kb_health.py", "--json")
        dead = next(r for r in json.loads(out)["results"] if r["check"] == "dead-links")
        self.assertEqual(dead["status"], "WARN")
        self.assertIn("Heading Only Words", dead["detail"])
        self.assertIn(f"{L}x{R}", dead["detail"])


class Degrade(Base):
    """A search that cannot bring the index up to date still answers, exit 0, with one warning line and no traceback."""

    def main_of(self, *argv, build=None):
        """(exit code, stdout, stderr) of kb_search.main() run in this process; `build` replaces kb_index.build."""
        ks = load("kb_search", self.env)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, self.env), mock.patch.object(sys, "argv", ["kb_search.py", *map(str, argv)]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(ks.kb_index, "build", build or ks.kb_index.build):
            rc = ks.main()
        return rc, out.getvalue(), err.getvalue()

    @staticmethod
    def fails(exc):
        def build(*_a, **_k):
            raise exc
        return build

    def db(self):
        return next((self.tmp / "claude" / "workbench" / "cache").glob("kb-*.db"))

    def test_a_failed_rebuild_answers_from_the_old_index_with_one_warning(self):
        self.note("ops/a.md", "---\ntitle: a\n---\n# A\nthe alpha procedure\n")
        self.search("alpha")                                                   # builds the index
        self.note("ops/b.md", "---\ntitle: b\n---\n# B\nthe bravo procedure\n")   # ...which is now stale
        rc, out, err = self.main_of("alpha", "--json", build=self.fails(PermissionError("held by a scanner")))
        self.assertEqual(rc, 0, err)
        res = json.loads(out)
        warning = "WARNING: index rebuild failed (PermissionError: held by a scanner): results may be stale"
        self.assertEqual((res["mode"], res["warning"], [h["path"] for h in res["hits"]]), ("stale-index", warning, ["ops/a.md"]))
        self.assertEqual(err.strip().splitlines(), [warning], "beside --json the warning is one stderr line")
        rc, out, err = self.main_of("bravo", "--json", build=self.fails(PermissionError("x")))
        self.assertEqual(json.loads(out)["hits"], [], "the old index does not know the new note: that is what stale means")
        rc, out, err = self.main_of("alpha", build=self.fails(OSError("disk full")))                # text mode: one WARNING line, then the hits
        self.assertEqual([ln for ln in out.splitlines() if ln.startswith("WARNING")], ["WARNING: index rebuild failed (OSError: disk full): results may be stale"])
        self.assertTrue(out.splitlines()[0].startswith("WARNING") and "ops/a.md" in out)
        rc, out, err = self.main_of("alpha", "--json")                                              # control: the rebuild works, no warning
        res = json.loads(out)
        self.assertEqual((res["mode"], "warning" in res, bool(res["rebuilt"])), ("index", False, True))

    def test_no_index_and_a_failing_build_falls_back_to_grep(self):
        self.note("ops/one.md", "---\ntitle: one\n---\n# One\nalpha alpha alpha and beta together\n")
        self.note("ops/two.md", "---\ntitle: two\n---\n# Two\nalpha with beta once\n")
        self.note("data/three.md", "---\ntitle: three\n---\n# Three\nonly alpha here\n")
        boom = self.fails(OSError("disk full"))
        rc, out, err = self.main_of("ALPHA beta", "--json", build=boom)
        self.assertEqual(rc, 0, err)
        res = json.loads(out)
        warning = "WARNING: index unavailable (OSError: disk full): grep fallback"
        self.assertEqual((res["mode"], res["ranking"], res["warning"]), ("grep", "grep", warning))
        self.assertEqual([(h["path"], h["score"]) for h in res["hits"]], [("ops/one.md", 4.0), ("ops/two.md", 2.0)],
                         "every word first, by how often they occur; the note with one of the words is not a hit while one has both")
        self.assertIn("alpha alpha alpha", res["hits"][0]["snippet"])
        self.assertEqual(err.strip().splitlines(), [warning])
        res = json.loads(self.main_of("alpha gamma", "--json", build=boom)[1])
        self.assertEqual([h["path"] for h in res["hits"]], ["ops/one.md", "data/three.md", "ops/two.md"], "no note has both: any word, by count, ties by path")
        res = json.loads(self.main_of("alpha", "--domain", "data", "--json", build=boom)[1])
        self.assertEqual([h["path"] for h in res["hits"]], ["data/three.md"])
        self.assertEqual(json.loads(self.main_of("zzzz", "--json", build=boom)[1])["hits"], [])
        rc, out, err = self.main_of("alpha", build=boom)
        self.assertEqual(out.splitlines()[0], warning)
        self.assertEqual(len([ln for ln in out.splitlines() if ln.startswith("WARNING")]), 1)
        self.assertFalse(list(self.tmp.rglob("kb-*.db*")), "no index file and no half-built copy")

    def test_a_corrupt_index_that_cannot_be_rebuilt_is_not_a_traceback(self):
        self.note("ops/a.md", "---\ntitle: a\n---\n# A\nthe alpha procedure\n")
        self.search("alpha")
        self.db().write_bytes(b"this is not a database" * 50)
        rc, out, err = self.main_of("alpha", "--json", build=self.fails(PermissionError("locked")))
        self.assertEqual(rc, 0, err)
        res = json.loads(out)
        self.assertEqual((res["mode"], [h["path"] for h in res["hits"]]), ("grep", ["ops/a.md"]))
        self.assertRegex(res["warning"], r"^WARNING: index unavailable \(.*\): grep fallback$")
        res = json.loads(self.main_of("alpha", "--json")[1])                                         # when the rebuild can run it replaces the file
        self.assertEqual((res["mode"], "warning" in res), ("index", False))

    def test_related_with_no_usable_index_says_so_and_exits_zero(self):
        self.note("ops/a.md", f"---\ntitle: a\n---\n# A\nsee {L}ops/HOT{R}\n")
        rc, out, err = self.main_of("--related", "ops/a.md", build=self.fails(OSError("disk full")))
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.splitlines()[0], "WARNING: index unavailable (OSError: disk full): grep fallback")
        self.assertIn("no links", out)
        self.run_py("kb_search.py", "--related", "ops/a.md", "--json")                                  # builds the index
        self.note("ops/c.md", "---\ntitle: c\n---\n# C\nnew\n")
        rc, out, err = self.main_of("--related", "ops/a.md", "--json", build=self.fails(OSError("disk full")))
        self.assertEqual([r["path"] for r in json.loads(out)], ["ops/HOT.md"], "the old index still has the link table")
        self.assertIn("index rebuild failed", err)

    def test_a_failed_replace_leaves_no_temporary_index(self):
        self.note("ops/a.md", "---\ntitle: a\n---\n# A\nalpha\n")
        ki = load("kb_index", self.env)
        with mock.patch.dict(os.environ, self.env), mock.patch.object(ki.os, "replace", side_effect=PermissionError("held")):
            with self.assertRaises(PermissionError):
                ki.build()
        self.assertEqual(list((self.tmp / "claude" / "workbench" / "cache").glob("*")), [])


class AnswerLine(Base):
    PAD = "the deploy step %d runs nightly and the deploy log is kept for a while after it"

    def snip(self, q, body, env=None):
        self.note("ops/guide.md", "---\ntitle: guide\n---\n# Guide\n" + body)
        return self.search(q, env=env)["hits"][0]["snippet"]

    @each_mode
    def test_the_snippet_is_the_line_with_the_rare_word(self, env):
        pad = "\n".join(self.PAD % i for i in range(5))
        snip = self.snip("deploy quillfeather", f"## Steps\n{pad}\nrotate the quillfeather credentials after every deploy\n", env)
        self.assertTrue(snip.startswith("rotate the quillfeather credentials"), snip)

    def test_a_query_number_outweighs_a_line_with_more_common_words(self):
        body = "\n\n".join(["the cache limit is documented here", "port 4096 is reserved", "the cache holds data", "the cache is warm",
                           "the limit applies per host", "the limit is soft"]) + "\n"
        ks = load("kb_search", self.env)
        terms = ks.terms_of("cache limit 4096")
        self.assertTrue(ks._snippet(body, terms).startswith("port 4096 is reserved"))
        with mock.patch.object(ks, "NUM_BONUS", 0.0):
            self.assertTrue(ks._snippet(body, terms).startswith("the cache limit is documented"), "without the bonus the line with more words wins")

    def test_a_hard_wrapped_line_is_joined_and_front_matter_is_never_the_answer(self):
        ks = load("kb_search", self.env)
        pad = "\n".join(self.PAD % i for i in range(3))
        body = f"{pad}\nThe audit export runs every Sunday and lands in the shared\nfolder named quokka-archive for the compliance team\n- a bullet\n"
        snip = ks._snippet(body, ks.terms_of("audit quokka"))
        self.assertTrue(snip.startswith("The audit export runs every Sunday and lands in the shared folder named quokka-archive"), snip)
        self.assertNotIn("a bullet", snip, "a new bullet is not a continuation")
        front = "---\ntitle: Quillfeather guide\ntags: quillfeather\n---\n# Guide\nRotate the quillfeather credentials monthly\n"
        self.assertTrue(ks._snippet(front, ["quillfeather"]).startswith("Rotate the quillfeather"))

    def test_no_line_holds_a_query_word_falls_back_to_the_window(self):
        ks = load("kb_search", self.env)
        body = "## Rollouts\nwe deploy the service on Friday\nand the team knows why\n"
        self.assertEqual(ks._snippet(body, ["deployed"]), "## Rollouts we deploy the service on Friday and the team knows why", "a stem-only match: the window")
        self.assertTrue(ks._snippet(body, ["deploy"]).startswith("we deploy the service on Friday"), "control: the word is there")
        self.assertEqual(ks._snippet("only prose here", ["zebra"]), "only prose here")
        self.assertEqual(ks._snippet("", ["zebra"]), "")


class Retired(Base):
    FACTS = {"facts": [{"id": "cache-host", "owner": "infra/cache", "canonical": "the cache runs on host alpha-9",
                        "forbidden": ["host beta-3"]}]}

    def setUp(self):
        super().setUp()
        self.note("infra/cache.md", "---\ntitle: cache\n---\n# Cache\n## Where\nthe cache runs on host alpha-9 for every region\n"
                  "it used to run on host beta-3\n")
        self.note("ops/runbook.md", "---\ntitle: runbook\n---\n# Runbook\nrestart the cache on host beta-3 first\n")
        self.note("ops/old.md", "---\ntitle: old\n---\n# Old\nSUPERSEDED: the cache used host beta-3 until spring\n")
        self.note("ops/other.md", "---\ntitle: other\n---\n# Other\nthe cache notes with nothing stale\n")

    def facts(self, data=None):
        self.note("_shared/facts.json", json.dumps(self.FACTS if data is None else data))

    def paths(self, q, *args):
        return [h["path"] for h in self.search(q, *args)["hits"]]

    def test_a_stale_value_is_flagged_and_its_owner_pinned_above_it(self):
        self.facts()
        res = self.search("restart cache beta-3")
        self.assertEqual([h["path"] for h in res["hits"]], ["infra/cache.md", "ops/runbook.md"], "the owner is not in the hits: it is inserted above")
        owner, stale = res["hits"]
        self.assertEqual(stale["retired"], {"fact": "cache-host", "owner": "infra/cache.md"})
        self.assertNotIn("retired", owner)
        self.assertEqual((owner["pinned_for"], owner["line"], owner["heading"]), ("cache-host", 6, "Where"))
        self.assertIn("alpha-9", owner["snippet"])
        rc, out, _ = self.run_py("kb_search.py", "restart cache beta-3")
        self.assertRegex(out, r"ops/runbook\.md:\d+  \[Runbook\]  \[retired - live value in infra/cache\.md\] ")
        self.assertRegex(out, r"infra/cache\.md:6  \[Where\]  \[live value of cache-host\] ")
        self.assertEqual(len(self.search("restart cache beta-3", "--limit", "1")["hits"]), 1, "the list is still cut to --limit")

    def test_negative_controls_nothing_is_flagged_that_should_not_be(self):
        self.facts()
        hits = self.search("used host beta-3")["hits"]
        self.assertIn("ops/old.md", [h["path"] for h in hits])
        self.assertTrue(all("retired" not in h for h in hits), "a line marked SUPERSEDED is the marked old value")
        hits = self.search("cache host", "--all-chunks")["hits"]
        owner = [h for h in hits if h["path"] == "infra/cache.md"]
        self.assertTrue(owner and all("retired" not in h for h in owner), "the owner note may name the value that misleads")
        res = self.search("cache host")["hits"]                          # the owner is already a hit: no second copy, no pin
        self.assertEqual(len({h["path"] for h in res}), len(res))
        self.assertTrue(all("pinned_for" not in h for h in res))
        self.assertEqual([h["path"] for h in res if "retired" in h], ["ops/runbook.md"])
        self.assertIn("infra/cache.md", [h["path"] for h in res])

    def test_without_a_usable_registry_search_is_unchanged(self):
        base = self.search("restart cache beta-3")["hits"]
        self.assertEqual([h["path"] for h in base], ["ops/runbook.md"])
        for data in ({"facts": []}, {"facts": [{"id": "x", "owner": "infra/cache", "canonical": "c"}]}):   # empty / no forbidden text
            self.facts(data)
            self.assertEqual(self.search("restart cache beta-3")["hits"], base)
        self.note("_shared/facts.json", "{ not json")
        rc, out, err = self.run_py("kb_search.py", "restart cache beta-3", "--json")
        self.assertEqual((rc, json.loads(out)["hits"]), (0, base))
        self.facts()
        self.assertEqual(self.paths("restart cache beta-3"), ["infra/cache.md", "ops/runbook.md"], "control: the registry is what changes the list")

    def test_a_registry_that_stays_locked_does_not_stop_the_search(self):
        """savelock retries a held file for about a second, then raises OSError: search must answer without retired flags."""
        self.facts()
        sys.path.insert(0, str(SCRIPTS))
        import kb_facts
        ks = load("kb_search", self.env)
        with mock.patch.dict(os.environ, self.env), mock.patch.object(kb_facts, "load", side_effect=PermissionError("held by a scanner")):
            ks.ensure_index()
            for hits in (ks.search("restart cache beta-3"), ks.grep_search("restart cache beta-3")):
                self.assertEqual([h["path"] for h in hits], ["ops/runbook.md"])
                self.assertTrue(all("retired" not in h and "pinned_for" not in h for h in hits))
        rc, out, err = self.run_py("kb_search.py", "restart cache beta-3", "--json")                        # control: the registry is readable
        self.assertEqual([h["path"] for h in json.loads(out)["hits"]], ["infra/cache.md", "ops/runbook.md"])

    def test_the_grep_fallback_flags_a_stale_value_too(self):
        self.facts()
        ks = load("kb_search", self.env)
        with mock.patch.dict(os.environ, self.env):
            hits = ks.grep_search("restart cache beta-3")
        self.assertEqual([(h["path"], "retired" in h) for h in hits], [("infra/cache.md", False), ("ops/runbook.md", True)])


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
        if os.environ.get("WB_FIELD_CHECK") == "1":
            return   # the doctor's D3 checks correctness; on a busy laptop with scanning a wall-clock budget measures the machine
        self.assertLess(sorted(ms)[len(ms) // 2], 300, "median of a whole command, Python start-up included")


if __name__ == "__main__":
    unittest.main()
