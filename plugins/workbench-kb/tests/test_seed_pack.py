"""Tests for the knowledge seed pack: the digests every new and existing knowledge base receives under _shared/digests/,
the questions that prove they are findable, and the installer path that adds them to an existing knowledge base.

  Shape      the seed notes exist with digest frontmatter, and the marker lint passes: a body line holding a number of two
             or more digits carries an [S<n>] or [M<n>] marker, every [S<n>] resolves to a Sources row with a link and a
             fetch date, every [M<n>] to a Measurements row with n= and a tier. A negative control proves the lint
             fails. No subprocess and no index: the doctor's field list runs this class.
  Retrieval  every question in every seed_questions*.json finds its note in the KB search top 5 (throwaway template copy).
  Find       the same questions through find's keyword mode, top 3 (scratch index, no model download), and the explainer
             PDF beside its digest is indexed and found by a question only it answers.
  Install    bootstrap/install.py --apply into a knowledge base that predates the pack: the seed notes and the two PDFs
             are added and an edited digest stays byte for byte.
Run: python -m unittest plugins/workbench-kb/tests/test_seed_pack.py -v
"""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: a missing dependency fails, never skips

import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
TEMPLATE = REPO / "kb-template"
DIGESTS = TEMPLATE / "_shared" / "digests"
SCRIPTS = HERE.parent / "scripts"
FIND = REPO / "plugins" / "workbench-core" / "skills" / "find" / "scripts" / "doc_index.py"
SEED = ("models-and-tokens", "knowledge-layer", "retrieval-eval-method", "reports-and-pdfs", "internal-assistant",
        "enterprise-rag-architecture", "enterprise-rag-retrieval", "enterprise-rag-ingestion", "enterprise-rag-evaluation",
        "enterprise-rag-failure-modes", "ponytail-measurements", "workbench-explainer")
PDFS = ("workbench-explainer.pdf", "workbench-poster.pdf")   # shipped beside their digest; find indexes them, kb_search does not
FRONT = re.compile(r"\A---\ntitle: Digest, [^\n]+\ndomain: _shared\nstatus: active\n---\n")
NUMBER = re.compile(r"(?<![A-Za-z_\d])\d{2,}")          # the publish check's P5 rule (tools/test_docs.py)
LIST_ITEM = re.compile(r"^\s*\d+\.\s")                    # an ordered-list item number is structure, like a heading's
MARK = re.compile(r"\[([SM])(\d+)\]")
SOURCE_ROW = re.compile(r"^(?:- )?\[S(\d+)\] \S.* · https?://\S+ · fetched 20\d\d-\d\d-\d\d$")
MEASURE_ROW = re.compile(r"^(?:- )?\[M(\d+)\] \S.* · corpus \S.* · n=\S.* · tier R[012]$")
ROWS = {"Sources": ("S", SOURCE_ROW), "Measurements": ("M", MEASURE_ROW)}
# A figure from the authors' own runs is blurred ("about 0.9", "roughly a third"), never exact: an exact decimal or a
# decimal percentage on a Measurements row, or on a line citing only [M] markers, would fingerprint a private build.
EXACT = re.compile(r"\d+\.\d{3,}|\d+\.\d+\s*%|\d{2,}\.\d")


def lint(text):
    """[(line, problem)] for one seed note. Headings, the frontmatter and the rows of the Sources and Measurements
    sections are exempt from the number rule (they are the definitions the markers point at), and so is the number of
    an ordered-list item."""
    errs, rows, used, section = [], {"S": set(), "M": set()}, [], None
    front = FRONT.match(text)
    if not front:
        errs.append((1, "digest frontmatter"))
    skip = front.group(0).count("\n") if front else 0
    lines = text.split("\n")
    for n, line in enumerate(lines[skip:], skip + 1):
        if line.startswith("#"):
            section = line[3:].strip() if line.startswith("## ") else section
            continue
        if section in ROWS:
            if line.strip():
                kind, shape = ROWS[section]
                m = shape.match(line)
                if m:
                    rows[kind].add(int(m.group(1)))
                    if kind == "M" and EXACT.search(line):
                        errs.append((n, "an exact own-run figure on a Measurements row (blur it)"))
                else:
                    errs.append((n, f"a {section} row is not in the agreed shape"))
            continue
        marks = MARK.findall(line)
        used += [(n, k, int(i)) for k, i in marks]
        if marks and {k for k, _ in marks} == {"M"} and EXACT.search(line):
            errs.append((n, "an exact own-run figure on a line citing only [M] (blur it)"))
        if not marks and NUMBER.search(LIST_ITEM.sub("", line)):
            errs.append((n, "a number of two or more digits without an [S<n>] or [M<n>] marker"))
    errs += [(n, f"[{k}{i}] has no row") for n, k, i in used if i not in rows[k]]
    headings = [x for x in lines if x.startswith("## ")]
    if not headings or headings[-1] != "## Sources" or not rows["S"]:
        errs.append((len(lines), "the note must end with a '## Sources' section holding at least one row"))
    return errs


def seed_questions():
    """[(file name, question, expected note)] from every seed_questions*.json (each file is one slice's set)."""
    out = []
    for f in sorted(HERE.glob("seed_questions*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data.get("version") == 1, f.name
        out += [(f.name, q["q"], q["expect"]) for q in data["questions"]]
    return out


GOOD = """---
title: Digest, sample
domain: _shared
status: active
---
# Sample
- Batches cost 50% of the standard price [S1].
- One run measured it at 0.85 [M1].
- Nothing numeric here.
10. A tenth list item with no other number.

## Measurements
- [M1] A gate · corpus one invented set · n=tens of questions · tier R0

## Sources
- [S1] A vendor page · https://example.com/page · fetched 2026-01-02
"""


class Shape(unittest.TestCase):
    def test_the_seed_notes_and_pdfs_exist_with_digest_frontmatter_and_body(self):
        for name in SEED:
            with self.subTest(note=name):
                p = DIGESTS / f"{name}.md"
                self.assertTrue(p.is_file(), f"{p} is missing")
                text = p.read_text(encoding="utf-8")
                self.assertRegex(text, FRONT)
                self.assertGreater(len(text), 1500, "a seed note carries real content")
        for name in PDFS:
            with self.subTest(pdf=name):
                p = DIGESTS / name
                self.assertTrue(p.is_file(), f"{p} is missing")
                self.assertTrue(p.read_bytes().startswith(b"%PDF-"), name)

    def test_every_number_carries_a_marker_and_every_marker_resolves(self):
        for name in SEED:
            with self.subTest(note=name):
                p = DIGESTS / f"{name}.md"
                self.assertTrue(p.is_file(), f"{p} is missing")
                self.assertEqual(lint(p.read_text(encoding="utf-8")), [])

    def test_the_lint_passes_a_good_note_and_fails_each_bad_one(self):
        self.assertEqual(lint(GOOD), [])
        bad = {
            "unmarked number": GOOD.replace("0.85 [M1]", "0.85"),
            "unmarked number after a list item": GOOD.replace("- Nothing numeric here.", "12. waited 30 seconds"),
            "marker with no row": GOOD.replace("[S1].\n", "[S2].\n"),
            "source row without a fetch date": GOOD.replace(" · fetched 2026-01-02", ""),
            "source row without a link": GOOD.replace("https://example.com/page", "example.com/page"),
            "measurement row without n=": GOOD.replace("n=tens of questions", "tens of questions"),
            "measurement row without a tier": GOOD.replace(" · tier R0", ""),
            "no frontmatter": GOOD.split("---\n", 2)[2],
            "sources not last": GOOD + "\n## Later\nmore text\n",
            "exact own-run figure": GOOD.replace("0.85 [M1]", "0.853 [M1]"),
        }
        for why, text in bad.items():
            with self.subTest(case=why):
                self.assertNotEqual(lint(text), [], why)

    def test_the_question_files_name_seed_notes_two_per_note_at_least(self):
        qs = seed_questions()
        self.assertTrue(qs, "no seed_questions*.json file")
        expected = [e for _, _, e in qs]
        self.assertEqual([e for e in expected if e not in {f"_shared/digests/{n}.md" for n in SEED}], [])
        mine = json.loads((HERE / "seed_questions.json").read_text(encoding="utf-8"))["questions"]
        self.assertEqual(len(mine), 10)
        for name in SEED[:5]:
            self.assertEqual(sum(1 for q in mine if q["expect"] == f"_shared/digests/{name}.md"), 2, name)


class TemplateCopy(unittest.TestCase):
    """A throwaway copy of kb-template and a private Claude configuration folder."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wb-seed-"))
        cls.kb = cls.tmp / "kb"
        shutil.copytree(TEMPLATE, cls.kb)
        cls.env = {**os.environ, "WORKBENCH_KB_ROOT": str(cls.kb), "CLAUDE_CONFIG_DIR": str(cls.tmp / "claude"),
                   "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        for k in ("KB_INDEX_DB", "KB_INDEX_NO_FTS5"):
            cls.env.pop(k, None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class Retrieval(TemplateCopy):
    def test_every_seed_question_finds_its_note_in_the_kb_search_top_5(self):
        for src, q, expect in seed_questions():
            with self.subTest(file=src, question=q[:60]):
                self.assertTrue((self.kb / expect).is_file(), f"{expect} is not in kb-template")
                r = subprocess.run([sys.executable, str(SCRIPTS / "kb_search.py"), q, "--json", "--limit", "5"],
                                   capture_output=True, text=True, encoding="utf-8", env=self.env, timeout=180)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                top = [h["path"] for h in json.loads(r.stdout)["hits"]]
                self.assertIn(expect, top)


class Find(TemplateCopy):
    def test_every_seed_question_finds_its_note_in_find_keyword_top_3(self):
        env = dict(self.env, WB_FIND_LAZY="0", WB_KNOWLEDGE_REEXEC="1", HF_HUB_OFFLINE="1")
        db = self.tmp / "find.sqlite"

        def cli(*a):
            return subprocess.run([sys.executable, str(FIND), "--db", str(db), *a], env=env, capture_output=True,
                                  text=True, encoding="utf-8", timeout=600)
        for step in (["add-root", str(self.kb), "--label", "kb"], ["refresh", "--root", "kb", "--embed", "off"]):
            r = cli(*step)
            if r.returncode and not REQUIRE and "No module named" in r.stderr:
                self.skipTest("knowledge packages missing: " + r.stderr.strip().splitlines()[-1])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for src, q, expect in seed_questions():
            with self.subTest(file=src, question=q[:60]):
                r = cli("search", q, "--mode", "keyword", "--limit", "3", "--root", "kb", "--json")
                self.assertEqual(r.returncode, 0, r.stderr)
                top = [Path(h["path"]).as_posix() for h in json.loads(r.stdout)["hits"]]
                self.assertIn(expect, top)

    def test_the_explainer_pdf_is_indexed_and_answers_a_question_only_it_covers(self):
        # PDF text needs the knowledge venv (pdfminer), as in the find suite: run_suites passes WB_KNOWLEDGE_PYTHON
        py = os.environ.get("WB_KNOWLEDGE_PYTHON") or sys.executable
        env = dict(self.env, WB_FIND_LAZY="0", WB_KNOWLEDGE_REEXEC="1", HF_HUB_OFFLINE="1")
        db = self.tmp / "find-pdf.sqlite"

        def cli(*a):
            r = subprocess.run([py, str(FIND), "--db", str(db), *a], env=env, capture_output=True, text=True,
                               encoding="utf-8", timeout=600)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return json.loads(r.stdout) if "--json" in a else r
        cli("add-root", str(self.kb), "--label", "kb")
        cli("refresh", "--root", "kb", "--embed", "off")
        problems = [p for p in cli("report", "--json").get("problems") or [] if p.get("ref", "").endswith(".pdf")]
        if problems and not REQUIRE and all("not installed" in p.get("error", "") for p in problems):
            self.skipTest("PDF text needs the knowledge venv: set WB_KNOWLEDGE_PYTHON")
        self.assertEqual(problems, [])
        hits = cli("search", "why is memory Markdown and not a vector store", "--mode", "keyword", "--limit", "3",
                   "--root", "kb", "--json")["hits"]
        self.assertIn("_shared/digests/workbench-explainer.pdf", [Path(h["path"]).as_posix() for h in hits])


class Install(unittest.TestCase):
    """An existing knowledge base made from an earlier template (no seed notes, testing.md edited by its owner)."""

    def test_install_adds_the_seed_notes_and_keeps_an_edited_digest(self):
        t = Path(tempfile.mkdtemp(prefix="wb-seedinst-"))
        self.addCleanup(shutil.rmtree, t, True)
        kb, home = t / "kb", t / "home"
        shutil.copytree(TEMPLATE, kb)
        for name in [f"{n}.md" for n in SEED] + list(PDFS):
            (kb / "_shared" / "digests" / name).unlink()
        edited = kb / "_shared" / "digests" / "testing.md"
        edited.write_bytes(edited.read_bytes() + b"\n- A line the owner added.\n")
        before = edited.read_bytes()
        (home / ".claude").mkdir(parents=True)
        (t / "reg.json").write_text("{}", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("OneDrive", "WORKBENCH_", "WB_"))}
        env.update(USERPROFILE=str(home), HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"),
                   LOCALAPPDATA=str(t / "lad"), WORKBENCH_FAKE_REGISTRY=str(t / "reg.json"),
                   WORKBENCH_FAKE_BIN=str(t / "nobin"), PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, str(REPO / "bootstrap" / "install.py"), "--apply", "--no-cli", "--profile",
                            "corporate", "--kb-root", str(kb)], capture_output=True, text=True, encoding="utf-8",
                           env=env, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-1000:])
        for name in [f"{n}.md" for n in SEED] + list(PDFS):
            with self.subTest(note=name):
                got = kb / "_shared" / "digests" / name
                self.assertTrue(got.is_file(), f"{name} was not added")
                self.assertEqual(got.read_bytes(), (DIGESTS / name).read_bytes())
        self.assertEqual(edited.read_bytes(), before, "an edited digest is never overwritten")


if __name__ == "__main__":
    unittest.main()
