"""Tests for the find skill (doc_index.py and find_mcp.py). Run from the repository root:
    WB_REQUIRE_ALL=1 python -m unittest discover -s plugins/workbench-core/skills/find/scripts/tests -v
WB_REQUIRE_ALL=1 turns a missing dependency into a failure instead of a skip; WB_LIVE=1 adds the network tests."""
import builtins
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import zipfile
import zlib
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)
import doc_index as di  # noqa: E402
import fixtures as F  # noqa: E402

L, R = "[" * 2, "]" * 2          # wiki-link brackets, built here so this file holds no literal double bracket
REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
LIVE = os.environ.get("WB_LIVE") == "1"
DI = os.path.join(SCRIPTS, "doc_index.py")
MCP = os.path.join(SCRIPTS, "find_mcp.py")
HAVE = {m: importlib.util.find_spec(m) is not None for m in ("markitdown", "docx", "pptx", "openpyxl", "numpy", "fastembed", "pdfminer")}


def need(tc, *mods):
    """A missing dependency fails the run under WB_REQUIRE_ALL=1 and skips it otherwise."""
    missing = [m for m in mods if not HAVE[m]]
    if missing:
        if REQUIRE:
            tc.fail("missing dependency: " + ", ".join(missing))
        tc.skipTest("needs " + ", ".join(missing))


def quiet(*_):
    pass


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wb-find-")
        self.saved = dict(os.environ)
        home = os.path.join(self.tmp, "home")
        os.makedirs(home)
        os.environ.update(LOCALAPPDATA=os.path.join(self.tmp, "lad"), HOME=home, USERPROFILE=home,
                          CLAUDE_CONFIG_DIR=os.path.join(self.tmp, "claude"), WB_FIND_LAZY="0", HF_HUB_OFFLINE="1",
                          WB_DISCOVER_REGISTRY="0", PYTHONIOENCODING="utf-8")
        for k in ("WORKBENCH_KNOWLEDGE_DB", "WB_KNOWLEDGE_REEXEC", "OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
            os.environ.pop(k, None)
        di._EMB.clear()
        self.root = os.path.join(self.tmp, "library")
        os.makedirs(os.path.join(self.root, "sub"))
        self.db = os.path.join(self.tmp, "idx", "index.sqlite")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def w(self, rel, text, root=None):
        p = os.path.join(root or self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def con(self):
        return di.connect(self.db)

    def index(self, root=None, label=None, **kw):
        con = self.con()
        try:
            lab = di.add_root(con, root or self.root, label)
            r = con.execute("select id, label, path from roots where label=?", (lab,)).fetchone()
            return di.index_root(con, r, log=quiet, **kw)
        finally:
            con.close()

    def search(self, q, **kw):
        con = self.con()
        kw.setdefault("lazy", False)
        try:
            return di.search(con, self.db, q, **kw)
        finally:
            con.close()

    def refs(self, q, **kw):
        return [h["ref"] for h in self.search(q, **kw)["hits"]]

    def q(self, sql, *args):
        con = self.con()
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    def cli(self, *args, env=None, python=None):
        r = subprocess.run([*(python or [sys.executable]), DI, "--db", self.db, *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", env={**os.environ, **(env or {})}, timeout=300)
        return r.returncode, r.stdout, r.stderr

    def cli_json(self, *args, **kw):
        rc, out, err = self.cli(*args, **kw)
        self.assertEqual(rc, 0, err)
        return json.loads(out)


class Catalog(Env):
    def setUp(self):
        super().setUp()
        self.w("notes.md", "# Onboarding\n\nThe quarterly rollout plan covers three regions.\n\nSecond paragraph about budgets.\n")
        self.w("sub/readme.txt", "Plain text mentioning the escalation matrix.\n")
        with open(os.path.join(self.root, "locked.docx"), "wb") as f:
            f.write(di.OLE_MAGIC + b"\0" * 100)
        with open(os.path.join(self.root, "~$notes.docx"), "wb") as f:
            f.write(b"owner lock file")

    def test_index_search_incremental_rebuild(self):
        s = self.index()
        self.assertEqual((s["new"], s["failed"], s["catalogued"]), (2, 1, 3))
        res = self.search("rollout regions")
        self.assertEqual(res["hits"][0]["ref"], "library/notes.md#p2")
        self.assertEqual((res["hits"][0]["heading"], res["hits"][0]["title"]), ("Onboarding", "Onboarding"))
        self.assertIn("[rollout]", res["hits"][0]["snippet"])
        self.assertEqual(self.refs("escalation"), ["library/sub/readme.txt#p1"])
        self.assertEqual(self.refs("rollout zebra")[0], "library/notes.md#p2")   # any-word fallback
        con = self.con()
        self.assertIn(">> library/notes.md#p2", di.show(con, "library/notes.md#p2", 1))
        row = con.execute("select status, reason, error from files where name='locked.docx'").fetchone()
        self.assertEqual(row[:2], ("failed", "encrypted"))
        self.assertIn("encrypted", row[2])
        self.assertFalse(con.execute("select 1 from files where name like '~$%'").fetchone())
        con.close()
        s = self.index()                       # nothing changed
        self.assertEqual((s["new"], s["updated"], s["unchanged"]), (0, 0, 3))
        time.sleep(0.05)
        self.w("notes.md", "# Onboarding\n\nThe plan was replaced by a pilot.\n")
        self.assertEqual(self.index()["updated"], 1)
        self.assertEqual(self.refs("rollout"), [])
        self.assertEqual(self.refs("pilot"), ["library/notes.md#p2"])
        os.remove(os.path.join(self.root, "sub", "readme.txt"))
        self.assertEqual(self.index()["removed"], 0)                   # an incremental run never deletes
        self.assertTrue(self.refs("escalation"))
        self.assertEqual(self.index(rebuild=True)["removed"], 1)
        self.assertEqual(self.refs("escalation"), [])

    def test_rebuild_refuses_to_prune_an_empty_folder(self):
        self.index()
        for name in os.listdir(self.root):
            p = os.path.join(self.root, name)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        self.assertEqual(self.index(rebuild=True)["removed"], 0)
        self.assertTrue(self.refs("rollout"))

    def test_catalog_has_a_row_for_every_file(self):
        for rel in ("data.bin", "sub/pic.png", "sub/Q3 forecast.csv"):
            self.w(rel, "x")
        self.index()
        con = self.con()
        rows = di.files_search(con, "forecast")
        self.assertEqual([(r["ref"], r["status"]) for r in rows], [("library/sub/Q3 forecast.csv", "catalogued")])
        self.assertTrue(rows[0]["size"] == 1 and rows[0]["mtime"] and rows[0]["title"] == "Q3 forecast")
        self.assertEqual(di.coverage(con)["skipped"]["unsupported-type"], 3)
        self.assertEqual(con.execute("select count(*) from files").fetchone()[0], 6)
        self.assertEqual([r["name"] for r in di.files_search(con, "notes")][0], "notes.md")   # name matches first
        con.close()
        out = self.cli_json("files", "pic", "--json")
        self.assertEqual(out["files"][0]["ref"], "library/sub/pic.png")

    def test_files_ranks_by_name_then_recency(self):
        self.w("alpha/report-final.md", "x")
        self.w("report-notes/summary.md", "x")
        self.index()
        con = self.con()
        self.assertEqual(di.files_search(con, "report")[0]["ref"], "library/alpha/report-final.md")
        self.assertEqual(di.files_search(con, "report summary")[0]["ref"], "library/report-notes/summary.md")
        self.assertEqual(di.files_search(con, "nosuchthing"), [])
        con.close()

    def test_cloud_only_placeholder_is_catalogued_and_never_opened(self):
        self.w("online-only.md", "x" * 7777)
        opened = []
        real = (di.sha256, di.convert_doc, di.file_label)
        with mock.patch.object(di, "is_cloud_only", lambda st: st.st_size == 7777), \
                mock.patch.object(di, "sha256", lambda p: opened.append(p) or real[0](p)), \
                mock.patch.object(di, "convert_doc", lambda p, *a, **k: opened.append(p) or real[1](p, *a, **k)), \
                mock.patch.object(di, "file_label", lambda p: opened.append(p) or real[2](p)):
            s = self.index()
            self.index()                        # a second run keeps it skipped
        self.assertEqual(s["cloud_only"], 1)
        self.assertFalse([p for p in opened if p.endswith("online-only.md")])
        con = self.con()
        row = di.files_search(con, "online-only")[0]
        self.assertEqual((row["status"], row["cloud_only"]), ("cloud-only", True))
        self.assertEqual(di.coverage(con)["skipped"]["cloud-only"], 1)
        con.close()

    def test_zip_bomb_office_file_is_skipped_before_conversion(self):
        p = os.path.join(self.root, "bomb.docx")
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as f:
            f.writestr("word/document.xml", " " * (3 * 1024 * 1024))   # 3 MB that deflates to a few KB
        converted = []
        orig = di.convert_doc
        with mock.patch.object(di, "convert_doc", lambda path, *a, **k: converted.append(path) or orig(path, *a, **k)):
            self.index(max_unzipped_mb=2)
        self.assertFalse([c for c in converted if c.endswith("bomb.docx")])
        row = self.q("select status, reason, error from files where name='bomb.docx'")[0]
        self.assertEqual(row[:2], ("skipped", "too-large-unzipped"))
        self.assertIn("too large when uncompressed", row[2])

    def test_paragraphs_headings_and_long_lines(self):
        segs = [("# Top\n\nintro\n\n## Sub\n\nbody line one\nbody line two\n\n" + "word " * 1500, "page 2", None)]
        got = di.paragraphs(segs)
        self.assertEqual([g[0] for g in got[:4]], ["Top", "Top", "Top > Sub", "Top > Sub"])
        self.assertTrue(all(g[2] == "page 2" for g in got))
        self.assertGreater(len(got), 5)                         # the long line was cut
        self.assertTrue(all(len(g[1]) <= 2 * di.MAX_PARA for g in got))

    def test_front_matter_parser_is_lenient(self):
        fm, body = di.parse_front_matter('---\nsource: "intranet"\nlabels: ["A", "B"]\ntitle: My plain title\ntags:\n  - x\nn: 5\nbad: {oops\n---\nbody\n')
        self.assertEqual((fm["source"], fm["labels"], fm["title"], fm["n"], fm["bad"]), ("intranet", ["A", "B"], "My plain title", 5, "{oops"))
        self.assertEqual(fm["tags"], "")
        self.assertEqual(body.strip(), "body")
        self.assertEqual(di.parse_front_matter("no front matter\n")[0], None)
        self.assertEqual(di.parse_front_matter("---\nunterminated: 1\n")[0], None)
        self.assertFalse(di.is_captured({"source": "x"}))
        self.assertTrue(di.is_captured({"source": "x", "captured_at": "y"}))

    def test_html_hides_invisible_elements(self):
        html = ('<h1>Title</h1><p>Seen</p><div style="display:none">gone1<span>gone2</span></div><p>Also seen</p>'
                '<p hidden>gone3</p><span style="font-size:0">gone4</span><!-- gone5 --><style>.x{}</style><ul><li>item</li></ul>')
        text = di._Visible().text(html)
        for gone in ("gone1", "gone2", "gone3", "gone4", "gone5", ".x"):
            self.assertNotIn(gone, text)
        for seen in ("# Title", "Seen", "Also seen", "item"):
            self.assertIn(seen, text)


class Labels(Env):
    PAGE = ["Quarterly summary"]
    LABELLED_PAGES = [ ["Labelled pdf paragraph about the succession plan."] ]   # one page of one line

    def z(self, name, parts):
        p = os.path.join(self.tmp, name)
        with zipfile.ZipFile(p, "w") as f:
            for k, v in parts.items():
                f.writestr(k, v)
        return p

    def test_label_reader_both_locations(self):
        z, G = self.z, F.GUID
        self.assertEqual(di.sensitivity_label(z("a.docx", {"docMetadata/LabelInfo.xml": F.label_info()})), f"label {{{G}}}")
        self.assertIsNone(di.sensitivity_label(z("b.docx", {"docMetadata/LabelInfo.xml": F.label_info(removed="1")})))
        self.assertIsNone(di.sensitivity_label(z("c.docx", {"docMetadata/LabelInfo.xml": F.label_info(enabled="0")})))
        self.assertEqual(di.sensitivity_label(z("d.docx", {"docProps/custom.xml": F.LABEL_XML})), "Internal")
        self.assertEqual(di.sensitivity_label(z("e.docx", {"docProps/custom.xml": F.LABEL_XML, "docMetadata/LabelInfo.xml": F.label_info()})), "Internal")
        self.assertIsNone(di.sensitivity_label(z("f.docx", {"word/document.xml": "<w/>"})))
        self.assertTrue(di.sensitivity_label(z("g.docx", {"docMetadata/LabelInfo.xml": "<not xml"})))       # fails closed
        self.assertTrue(di.sensitivity_label(z("h.docx", {"DOCMETADATA/labelinfo.XML": F.label_info()})))   # case-insensitive
        self.assertIsNone(di.sensitivity_label(z("i.docx", {"other/LabelInfo.xml": F.label_info()})))       # exact path only
        self.assertTrue(di.sensitivity_label(z("j.docx", {"docMetadata/LabelInfo.xml": "<!DOCTYPE x [<!ENTITY a 'b'>]><x/>"})))   # DTD refused: fails closed

    def test_oversized_label_parts_fail_closed_without_being_read(self):
        big = " " * (di.LABEL_PART_CAP + 10)          # compresses to almost nothing: a tiny zip bomb
        opened = []
        real_open = zipfile.ZipFile.open

        def spy(zf, member, *a, **k):
            opened.append(member.filename if isinstance(member, zipfile.ZipInfo) else member)
            return real_open(zf, member, *a, **k)
        for part in ("docMetadata/LabelInfo.xml", "docProps/custom.xml"):
            p = os.path.join(self.tmp, "big.docx")
            with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as f:
                f.writestr(part, big)
            self.assertLess(os.path.getsize(p), 20000)
            with mock.patch.object(zipfile.ZipFile, "open", spy):
                label = di.sensitivity_label(p)
            self.assertTrue(label and "oversized" in label, part)
            self.assertNotIn(part, opened, f"{part} was read despite its size")

    def test_pdf_label_plain_and_compressed(self):
        info_key = f"MSIP_Label_{F.GUID}_Name"
        p = os.path.join(self.tmp, "a.pdf")
        with open(p, "wb") as f:
            f.write(F.pdf_bytes([self.PAGE], {info_key: "Confidential"}))
        self.assertEqual(di.pdf_label(p), "Confidential")
        q = os.path.join(self.tmp, "b.pdf")
        body = zlib.compress(f"<< /{info_key} (Highly Restricted) >>".encode())
        with open(q, "wb") as f:
            f.write(b"%PDF-1.5\n1 0 obj\n<< /Filter /FlateDecode /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream\nendobj\n%%EOF\n")
        self.assertEqual(di.pdf_label(q), "Highly Restricted")
        r = os.path.join(self.tmp, "c.pdf")
        with open(r, "wb") as f:
            f.write(F.pdf_bytes([self.PAGE], {"Title": "plain"}))
        self.assertIsNone(di.pdf_label(r))

    def test_labelled_content_is_catalogued_but_not_indexed(self):
        need(self, "markitdown", "docx", "pdfminer")
        F.make_docx(os.path.join(self.root, "board.docx"), text="Labelled paragraph about the succession plan.", label=True)
        with open(os.path.join(self.root, "board.pdf"), "wb") as f:
            f.write(F.pdf_bytes(self.LABELLED_PAGES, {f"MSIP_Label_{F.GUID}_Name": "Confidential"}))
        F.captured_md(os.path.join(self.root, "intranet", "page.md"), labels=["Confidential"], body="Labelled captured paragraph about the succession plan.")
        self.w("open.md", "An unlabelled paragraph about the holiday calendar.")
        s = self.index()
        self.assertEqual(s["labelled"], 3)
        self.assertEqual(self.refs("succession plan"), [])                # nothing labelled reached the index
        self.assertEqual(self.refs("holiday calendar"), ["library/open.md#p1"])
        con = self.con()
        rows = {r["name"]: r for r in di.files_search(con, "board")} | {r["name"]: r for r in di.files_search(con, "page")}
        self.assertEqual((rows["board.docx"]["label"], rows["board.pdf"]["label"], rows["page.md"]["label"]), ("Internal", "Confidential", "Confidential"))
        self.assertEqual(con.execute("select count(*) from paras where body like '%succession plan%'").fetchone()[0], 0)
        con.close()
        self.assertEqual(self.index()["labelled"], 0)                    # stays skipped, cheaply
        self.assertEqual(self.cli_json("label", os.path.join(self.root, "board.docx"), "--json")["label"], "Internal")
        self.assertEqual(self.cli_json("label", os.path.join(self.root, "board.pdf"), "--json")["label"], "Confidential")
        self.assertEqual(self.cli_json("label", os.path.join(self.root, "intranet", "page.md"), "--json")["label"], "Confidential")
        self.assertIsNone(self.cli_json("label", os.path.join(self.root, "open.md"), "--json")["label"])
        self.index(include_labelled=True)                                   # explicit opt-in
        hits = self.search("succession plan")["hits"]
        self.assertEqual(len(hits), 3)
        self.assertEqual({h["label"] for h in hits}, {"Internal", "Confidential"})
        self.index()                                                       # opting back out removes the content again
        self.assertEqual(self.refs("succession plan"), [])

    def test_labelinfo_only_docx_is_skipped_unless_opted_in(self):
        need(self, "markitdown", "docx")
        p = F.make_docx(os.path.join(self.root, "coauthored.docx"), text="Coauthoring budget forecast for the northern programme.")
        F.add_part(p, "docMetadata/LabelInfo.xml", F.label_info())
        self.assertEqual(self.index()["labelled"], 1)
        self.assertEqual(self.refs("coauthoring forecast"), [])
        self.index(include_labelled=True)
        hit = self.search("coauthoring forecast")["hits"][0]
        self.assertEqual(hit["label"], f"label {{{F.GUID}}}")


class Purge(Env):
    def test_purge_covers_index_vectors_edges_keys_and_legacy_cache(self):
        self.w("a.md", f"# Alpha\n\nSee {L}b{R} about ticket ABC-123 and the plan.\n")
        self.w("b.md", "# Beta\n\nTicket ABC-123 is the same work.\n")
        self.index()
        con = self.con()
        con.execute("insert into vec select id, ?, 384, zeroblob(1536) from paras", (di.MODEL,))
        con.commit()
        for t in ("paras", "fts", "vec", "keys", "edges", "linkraw", "files"):
            self.assertGreater(con.execute(f"select count(*) from {t}").fetchone()[0], 0, t)
        di.purge_root(con, "library")
        for t in ("paras", "fts", "vec", "keys", "edges", "linkraw", "files"):
            self.assertEqual(con.execute(f"select count(*) from {t}").fetchone()[0], 0, t)
        self.assertEqual(con.execute("select count(*) from roots").fetchone()[0], 1)   # still registered
        con.close()
        cache = os.path.join(os.path.dirname(self.db), "cache")
        os.makedirs(cache)
        open(os.path.join(cache, "x.md"), "w").close()
        self.assertEqual(self.cli("--purge")[0], 0)
        self.assertFalse(os.path.exists(self.db) or os.path.exists(cache) or os.path.exists(self.db + "-wal"))
        self.assertTrue(os.path.exists(os.path.join(self.root, "a.md")))               # originals untouched

    def test_remove_root_purges_its_rows(self):
        self.w("a.md", "plain words here")
        self.index()
        self.assertEqual(self.cli("remove-root", "library")[0], 0)
        self.assertEqual(self.q("select count(*) from paras")[0][0], 0)
        self.assertEqual(self.q("select count(*) from roots")[0][0], 0)


class Graph(Env):
    def test_versions_tickets_links_and_newest(self):
        self.w("docs/plan v1.md", "# Plan\n\nWork tracked in ABC-123.\n")
        self.w("docs/plan v2.md", "# Plan\n\nWork tracked in ABC-123, revised.\n")
        self.w("other/notes.md", "# Notes\n\nDiscussion of ABC-123.\n")
        self.w("lonely/solo.md", "# Solo\n\nNothing shared.\n")
        for n in (1, 2, 3):
            self.w(f"rep/rep_v{n}.md", f"# Rep\n\nVersion {n}.\n")
        self.w("min/minutes 2026-01-05.md", "# Minutes\n\nfirst\n")
        self.w("min/minutes 2026-02-02.md", "# Minutes\n\nsecond\n")
        self.w("spec/spec.md", "# Spec\n\nbase\n")
        self.w("spec/spec v2.md", "# Spec\n\nnext\n")
        self.w("links/a.md", f"# A\n\n[see b](b.md) and {L}c{R} and [out](https://example.com/x)\n")
        self.w("links/b.md", "# B\n\nplain\n")
        self.w("links/c.md", "# C\n\nplain\n")
        self.index()
        con = self.con()
        rel = {r["ref"]: r["via"] for r in di.related(con, "library/docs/plan v1.md", 1)["related"]}
        self.assertIn("supersedes", rel["library/docs/plan v2.md"])
        self.assertIn("ticket", rel["library/other/notes.md"])
        self.assertNotIn("library/lonely/solo.md", rel)
        self.assertEqual(di.newest(con, "library/docs/plan v1.md")["newest"]["ref"], "library/docs/plan v2.md")
        self.assertEqual(di.newest(con, "plan")["newest"]["ref"], "library/docs/plan v2.md")        # words
        self.assertEqual(di.newest(con, "library/rep/rep_v1.md")["newest"]["ref"], "library/rep/rep_v3.md")
        self.assertEqual(di.newest(con, os.path.join(self.root, "min", "minutes 2026-01-05.md"))["newest"]["ref"], "library/min/minutes 2026-02-02.md")
        self.assertEqual(di.newest(con, "library/spec/spec.md")["newest"]["ref"], "library/spec/spec v2.md")   # unmarked = first version
        self.assertEqual(di.newest(con, "library/lonely/solo.md")["newest"]["ref"], "library/lonely/solo.md")
        rel = {r["ref"]: r["via"] for r in di.related(con, "library/links/a.md", 1)["related"]}
        self.assertIn("hyperlink", rel["library/links/b.md"])
        self.assertIn("wiki", rel["library/links/c.md"])
        deep = {r["ref"]: r["depth"] for r in di.related(con, "library/rep/rep_v1.md", 2)["related"]}
        self.assertEqual((deep["library/rep/rep_v3.md"], deep["library/rep/rep_v2.md"]), (1, 1))   # via the newest, and the folder
        con.close()
        out = self.cli_json("related", "library/docs/plan v1.md", "--json")
        self.assertEqual(out["start"], "library/docs/plan v1.md")
        self.assertIn("library/docs/plan v2.md", [r["ref"] for r in out["related"]])
        self.assertEqual(self.cli_json("newest", "library/docs/plan v1.md", "--json")["superseded"], ["library/docs/plan v1.md"])

    def test_fanout_cap_stops_co_mention_edges(self):
        for i in range(di.FANOUT_CAP + 1):
            self.w(f"d{i}/f.md", f"# Doc {i}\n\nMentions ticket TKT-77 and the Service Level Objective (SLO).\n")
        self.index()
        con = self.con()
        self.assertEqual(con.execute("select count(*) from keys where key='ticket:TKT-77'").fetchone()[0], di.FANOUT_CAP + 1)
        self.assertEqual(con.execute("select count(*) from keys where key='acronym:SLO'").fetchone()[0], di.FANOUT_CAP + 1)
        self.assertEqual(di.related(con, "library/d0/f.md", 1, 500)["related"], [], "a key in more than the cap makes no edges")
        con.close()

    def test_fanout_at_the_cap_still_links(self):
        for i in range(di.FANOUT_CAP):
            self.w(f"d{i}/f.md", f"# Doc {i}\n\nMentions ticket TKT-88.\n")
        self.index()
        con = self.con()
        r = di.related(con, "library/d0/f.md", 1, 500)["related"]
        self.assertEqual(len(r), di.FANOUT_CAP - 1)
        self.assertTrue(all("ticket" in x["via"] for x in r))
        con.close()
        self.w("d99/f.md", "# Doc\n\nMentions ticket TKT-88.\n")      # one more file crosses the cap
        self.index()
        con = self.con()
        self.assertEqual(di.related(con, "library/d0/f.md", 1, 500)["related"], [])
        con.close()


class Captured(Env):
    def setUp(self):
        super().setUp()
        self.cap = os.path.join(self.tmp, "captured")
        os.makedirs(self.cap)

    def index_cap(self):
        return self.index(root=self.cap, label="captured")

    def test_captured_front_matter_surfaces_url_and_source(self):
        F.captured_md(os.path.join(self.cap, "intranet", "docs", "2026-01-03-handbook-a1b2c3d4.md"), title="Leave handbook",
                      body="The carry-over rule for unused holiday is described here.", extra={"zz_unknown": {"a": 1}, "tags": [1, 2]})
        F.captured_md(os.path.join(self.cap, "shared-files", "x", "2026-01-03-other-11223344.md"), source="shared-files",
                      url="https://files.example.com/a", title="Other", body="Different carry-over wording.")
        self.w("captured/loose.md", "---\nsource: \"intranet\"\n---\n\nNot captured: no captured_at key, carry-over text.\n", root=self.tmp)
        self.index_cap()
        hits = {h["path"]: h for h in self.search("carry-over")["hits"]}
        h = hits["intranet/docs/2026-01-03-handbook-a1b2c3d4.md"]
        self.assertEqual((h["url"], h["source"], h["title"]), ("https://intranet.example.com/page", "intranet", "Leave handbook"))
        self.assertIsNone(hits["loose.md"]["url"])                                    # source alone does not make a file captured
        self.assertEqual([x["source"] for x in self.search("carry-over", source="shared-files")["hits"]], ["shared-files"])
        self.assertEqual(self.search("carry-over", source="nothing")["hits"], [])
        self.assertEqual(self.search("carry-over", root="nothing")["hits"], [])
        self.assertEqual(self.q("select kind from roots where label='captured'")[0][0], "captured")
        con = self.con()
        self.assertIn("url: https://intranet.example.com/page", di.show(con, h["ref"]))
        con.close()

    def test_mail_and_meeting_keys_become_edges(self):
        base = os.path.join(self.cap, "outlook", "inbox")
        F.captured_md(os.path.join(base, "m1.md"), source="outlook", title="Rollout schedule", url="https://mail.example.com/1",
                      extra={"thread_id": "T-100", "message_ids": ["<1@example.com>"], "from": "Alice@Example.com",
                             "to": ["bob@example.com", "carol@example.com"], "cc": [], "received": "2026-01-03T10:00:00Z", "x_custom": "ignored"},
                      body="Please confirm the schedule.")
        F.captured_md(os.path.join(base, "m2.md"), source="outlook", title="Re: Rollout schedule", url="https://mail.example.com/2",
                      extra={"thread_id": "T-100", "from": "bob@example.com", "to": ["alice@example.com"]}, body="Confirmed.")
        F.captured_md(os.path.join(base, "m3.md"), source="outlook", title="Lunch", url="https://mail.example.com/3",
                      extra={"thread_id": "T-200", "from": "dave@example.com", "to": ["erin@example.com"]}, body="Noon works.")
        F.captured_md(os.path.join(self.cap, "teams", "mt1.md"), source="teams", title="Weekly sync", url="https://meet.example.com/1",
                      extra={"meeting_id": "m-" + "ab" * 8, "organizer": "Alice Example <alice@example.com>", "attendees": ["bob@example.com", "Frank Name"],
                             "start": "2026-01-04T09:00:00Z", "end": "2026-01-04T09:30:00Z", "transcript_source": "teams"}, body="Notes of the sync.")
        F.captured_md(os.path.join(self.cap, "teams", "mt2.md"), source="teams", title="Weekly sync transcript", url="https://meet.example.com/2",
                      extra={"meeting_id": "m-" + "ab" * 8, "organizer": "alice@example.com"}, body="Transcript of the sync.")
        self.index_cap()
        con = self.con()
        rel = {r["ref"]: r["via"] for r in di.related(con, "captured/outlook/inbox/m1.md", 1, 50)["related"]}
        self.assertIn("thread", rel["captured/outlook/inbox/m2.md"])
        self.assertIn("person", rel["captured/outlook/inbox/m2.md"])
        self.assertIn("person", rel["captured/teams/mt1.md"])                           # alice, lower-cased, appears in both
        self.assertNotIn("captured/outlook/inbox/m3.md", {r for r, v in rel.items() if "thread" in v or "person" in v})
        rel = {r["ref"]: r["via"] for r in di.related(con, "captured/teams/mt1.md", 1, 50)["related"]}
        self.assertIn("meeting", rel["captured/teams/mt2.md"])
        self.assertIn("person", rel["captured/outlook/inbox/m2.md"])                   # bob
        keys = {k for (k,) in con.execute("select key from keys where path='captured/outlook/inbox/m1.md'")}
        self.assertTrue({"thread:t-100", "person:alice@example.com", "person:carol@example.com"} <= keys)
        self.assertFalse([k for k in keys if "custom" in k or "message" in k])        # unknown and unused keys add nothing
        con.close()

    def test_person_fanout_cap(self):
        for i in range(di.FANOUT_CAP + 1):
            F.captured_md(os.path.join(self.cap, "outlook", f"b{i}.md"), source="outlook", title=f"Bulk {i}", url=f"https://mail.example.com/b{i}",
                          extra={"from": "bulk@example.com", "thread_id": f"solo-{i}"}, body="Newsletter.")
        self.index_cap()
        con = self.con()
        self.assertEqual([r for r in di.related(con, "captured/outlook/b0.md", 1, 500)["related"] if "person" in r["via"]], [])
        con.close()

    def test_archived_items_are_found_but_rank_below_active(self):
        F.captured_md(os.path.join(self.cap, "intranet", "old.md"), title="Old", url="https://intranet.example.com/old", status="archived",
                      body="budget forecast budget forecast budget forecast budget forecast")
        F.captured_md(os.path.join(self.cap, "intranet", "new.md"), title="New", url="https://intranet.example.com/new",
                      body="The budget forecast is on the next page.")
        self.index_cap()
        paths = [h["path"] for h in self.search("budget forecast")["hits"]]
        self.assertEqual(paths, ["intranet/new.md", "intranet/old.md"])

    def test_underscore_folders_in_a_captured_root_are_not_indexed(self):
        self.w("intranet/ok.md", "# Ok\n\nA normal page about parking.\n", root=self.cap)
        F.captured_md(os.path.join(self.cap, "intranet", "ok2.md"), body="Another page about parking.")
        self.w("_drop/meetings/raw-transcript.md", "# Raw\n\ntranscriptsecret waits for processing.\n", root=self.cap)
        self.w("intranet/_staging/deep/raw2.md", "# Raw2\n\ntranscriptsecret again.\n", root=self.cap)
        self.index_cap()
        con = self.con()
        self.assertEqual(di.files_search(con, "raw-transcript"), [])
        self.assertEqual(di.files_search(con, "raw2"), [])
        self.assertEqual(con.execute("select count(*) from files").fetchone()[0], 2)
        con.close()
        self.assertEqual(self.search("transcriptsecret")["hits"], [])
        plain = os.path.join(self.tmp, "plainlib")                 # the rule is for captured roots only
        self.w("_notes/a.md", "# A\n\nunderscorefolder content.\n", root=plain)
        self.index(root=plain, label="plainlib")
        self.assertEqual(self.refs("underscorefolder"), ["plainlib/_notes/a.md#p2"])

    @unittest.skipUnless(os.name == "nt", "long-path prefix is a Windows feature")
    def test_long_path_captured_file(self):
        deep = os.path.join(self.cap, "intranet", *[f"scope-{i:02d}-" + "x" * 20 for i in range(10)])
        self.assertGreater(len(deep), 260)
        os.makedirs(di.lp(deep))
        with open(di.lp(os.path.join(deep, "2026-01-03-deep-page-a1b2c3d4.md")), "w", encoding="utf-8") as f:
            f.write('---\nsource: "intranet"\nurl: "https://intranet.example.com/deep"\ncaptured_at: "2026-01-03T00:00:00Z"\n---\n\nDeep tree paragraph about gardens.\n')
        self.index_cap()
        hits = self.search("gardens")["hits"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["url"], "https://intranet.example.com/deep")
        con = self.con()
        self.assertIn("Deep tree paragraph", di.show(con, hits[0]["ref"]))
        con.close()


class Hidden(Env):
    TOKENS = ("hiddencomment", "hiddendeletion", "hiddennote", "hiddenslide", "hiddenpptxcomment", "hiddensheet", "hiddenxlsxcomment")

    def setUp(self):
        super().setUp()
        need(self, "markitdown", "docx", "pptx", "openpyxl", "pdfminer")
        self.files = F.make_poisoned(self.root)

    def test_convert_counts_each_hidden_kind(self):
        c = {n: di.convert_doc(p) for n, p in self.files.items()}
        self.assertTrue(all(d["error"] is None for d in c.values()), {n: d["error"] for n, d in c.items()})
        hc = {n: {k: v for k, v in d["hidden_content"].items() if v} for n, d in c.items()}
        self.assertEqual(hc["poison.docx"], {"comments": 1, "tracked_changes": 2})
        self.assertEqual(hc["poison.pptx"], {"comments": 1, "speaker_notes": 1, "hidden_slides": 1})
        self.assertEqual(hc["poison.xlsx"], {"comments": 1, "hidden_sheets": 1})
        self.assertEqual((hc["poison.pdf"], hc["poison.html"]), ({}, {}))
        out = self.cli_json("convert", self.files["poison.pptx"], "--json")
        self.assertEqual(out["hidden_content"], {"comments": 1, "tracked_changes": 0, "speaker_notes": 1, "hidden_sheets": 0, "hidden_slides": 1})
        self.assertIn("[hidden: speaker_notes]", out["markdown"])
        self.assertIsNone(out["error"])

    def test_hidden_paragraphs_carry_the_flag_and_visible_ones_do_not(self):
        self.index()
        for tok in self.TOKENS:
            hits = self.search(tok)["hits"]
            self.assertTrue(hits, tok)
            self.assertTrue(all(h["flags"] == ["hidden-content"] for h in hits), (tok, hits))
        vis = self.search("visibleinsertion")["hits"]
        self.assertTrue(vis and vis[0]["flags"] == [])
        for tok in ("telemetry", "loading dock", "garden project", "throughput"):
            self.assertTrue(all(h["flags"] == [] for h in self.search(tok)["hits"]), tok)
        con = self.con()
        txt = di.show(con, self.search("hiddennote")["hits"][0]["ref"], 0)
        self.assertIn("[hidden-content: speaker_notes]", txt)
        con.close()

    def test_pdf_metadata_and_html_hidden_blocks_never_reach_the_index(self):
        self.index()
        for tok in ("pdfmetadata", "pdfsubject", "pdfkeywords", "htmlhidden", "htmlattr", "htmlvisibility", "htmlcomment", "htmlscript"):
            self.assertEqual(self.search(tok)["hits"], [], tok)
            self.assertEqual(self.q("select count(*) from fts where fts match ?", tok)[0][0], 0, tok)
        self.assertEqual(self.q("select count(*) from files where title like '%IGNORE%'")[0][0], 0)

    def test_locators_for_pdf_pptx_xlsx(self):
        self.index()
        loc = lambda q: self.search(q)["hits"][0]["locator"]   # noqa: E731
        self.assertEqual(loc("loading dock"), "page 1")
        self.assertEqual(loc("courier schedule"), "page 2")
        self.assertEqual(loc("telemetry"), "slide 1")
        self.assertEqual(loc("throughput"), "sheet Budget")
        self.assertEqual(self.search("hiddensheet")["hits"][0]["locator"], "sheet Archive")


class Schema(Env):
    def test_schema_mismatch_rebuilds_and_keeps_roots(self):
        self.w("a.md", "# A\n\nrebuildable text\n")
        self.index()
        con = self.con()
        self.assertGreater(con.execute("select count(*) from files").fetchone()[0], 0)
        con.execute("pragma user_version=1")
        con.execute("create table junk(x)")
        con.commit()
        con.close()
        con = self.con()                                              # reopened with the wrong version
        self.assertEqual(con.execute("pragma user_version").fetchone()[0], di.SCHEMA_VERSION)
        self.assertEqual(con.execute("select count(*) from files").fetchone()[0], 0)
        self.assertFalse(con.execute("select 1 from sqlite_master where name='junk'").fetchone())
        self.assertEqual(con.execute("select label from roots").fetchall(), [("library",)])
        con.close()
        self.assertEqual(self.index()["new"], 1)                         # refilled from the registered root
        con = self.con()                                              # a current database is left alone
        self.assertEqual(con.execute("select count(*) from files").fetchone()[0], 1)
        con.close()

    def test_zero_version_database_from_an_old_layout_is_rebuilt(self):
        os.makedirs(os.path.dirname(self.db))
        o = sqlite3.connect(self.db)
        o.executescript("create table meta(k text primary key, v text); create table files(path text primary key, size int);"
                        "create virtual table para using fts5(path unindexed, body); insert into meta values('root','x');")
        o.commit()
        o.close()
        con = self.con()
        self.assertEqual(con.execute("pragma user_version").fetchone()[0], di.SCHEMA_VERSION)
        self.assertFalse(con.execute("select 1 from sqlite_master where name='para'").fetchone())
        con.close()

    def test_legacy_database_is_migrated_and_left_in_place(self):
        lib = os.path.join(self.tmp, "legacy-lib")
        self.w("a.md", "# Legacy\n\nThe archived rollout memo.\n", root=lib)
        old_dir = os.path.join(os.environ["LOCALAPPDATA"], "doc-index", "0123456789ab")
        os.makedirs(old_dir)
        old = os.path.join(old_dir, "index.sqlite")
        o = sqlite3.connect(old)
        o.executescript("create table meta(k text primary key, v text);"
                        "create table files(path text primary key, size int, mtime real, sha256 text, status text, error text, label text, paragraphs int, indexed_at text);"
                        "create virtual table para using fts5(path unindexed, pid unindexed, heading, body);")
        o.execute("insert into meta values('root', ?)", (lib,))
        o.execute("insert into para(path, pid, heading, body) values ('a.md','p1','','old body')")
        o.commit()
        o.close()
        before = (open(old, "rb").read(), os.path.getmtime(old))
        shared = di.shared_db()
        con = di.connect(shared)                                      # the first open of the shared database
        self.assertEqual(con.execute("select label, path from roots").fetchall(), [("legacy-lib", os.path.abspath(lib))])
        out = di.refresh(con, shared, embed="off", log=quiet)
        self.assertEqual(out["roots"]["legacy-lib"]["new"], 1)
        hits = di.search(con, shared, "archived rollout", lazy=False)["hits"]
        self.assertEqual(hits[0]["ref"], "legacy-lib/a.md#p2")
        st = di.status(con, shared)
        self.assertEqual(st["migrated_from"], [old])
        self.assertEqual(st["schema_version"], di.SCHEMA_VERSION)
        con.close()
        self.assertEqual((open(old, "rb").read(), os.path.getmtime(old)), before)    # the old file is untouched
        self.assertIn("--purge", subprocess.run([sys.executable, DI, "status"], capture_output=True, text=True, encoding="utf-8").stdout)
        self.assertEqual(subprocess.run([sys.executable, DI, "--db", old, "--purge"], capture_output=True).returncode, 0)
        self.assertFalse(os.path.exists(old))

    def test_two_writers_with_busy_timeout_do_not_fail(self):
        di.connect(self.db).close()
        errors, done = [], threading.Event()
        c1 = di.connect(self.db)
        self.assertGreaterEqual(c1.execute("pragma busy_timeout").fetchone()[0], 30000)

        def second():
            try:
                c2 = di.connect(self.db)
                c2.execute("insert or replace into meta values('b','2')")
                c2.commit()
                c2.close()
            except Exception as e:   # noqa: BLE001
                errors.append(e)
            done.set()
        c1.execute("begin immediate")
        c1.execute("insert or replace into meta values('a','1')")
        t = threading.Thread(target=second)
        t.start()
        time.sleep(1.5)                       # the second writer is now waiting on the lock
        self.assertFalse(done.is_set())
        c1.commit()
        t.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(dict(c1.execute("select k, v from meta where k in ('a','b')")), {"a": "1", "b": "2"})
        c1.close()


class Resolution(Env):
    def test_database_resolution_order(self):
        shared = di.shared_db()
        self.assertEqual(di.resolve_db(), os.path.abspath(shared))
        cfg = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "workbench")
        os.makedirs(cfg)
        with open(os.path.join(cfg, "config.json"), "w") as f:
            json.dump({"knowledge_db": os.path.join(self.tmp, "from-config.sqlite")}, f)
        self.assertEqual(di.resolve_db(), os.path.join(self.tmp, "from-config.sqlite"))
        os.environ["WORKBENCH_KNOWLEDGE_DB"] = os.path.join(self.tmp, "from-env.sqlite")
        self.assertEqual(di.resolve_db(), os.path.join(self.tmp, "from-env.sqlite"))
        folder = di.resolve_db(None, self.root)
        self.assertRegex(folder.replace("\\", "/"), r"doc-index/[0-9a-f]{12}/knowledge\.sqlite$")
        self.assertEqual(di.resolve_db(os.path.join(self.tmp, "x.sqlite"), self.root), os.path.join(self.tmp, "x.sqlite"))

    def test_cli_contract_and_exit_codes(self):
        d = os.path.join(self.tmp, "docs")
        self.w("a.md", "hello world", root=d)
        r = self.cli_json("add-root", d, "--label", "docs", "--json")
        self.assertEqual(r, {"root": "docs", "path": os.path.abspath(d)})
        self.assertEqual(self.cli_json("add-root", d, "--json"), r)                      # idempotent
        self.assertEqual(self.cli("add-root", self.root, "--label", "docs")[0], 1)         # a label names one folder
        self.assertEqual(self.cli("index", d)[0], 0)
        roots = self.cli_json("roots", "--json")["roots"]
        self.assertEqual([(x["label"], x["files"]) for x in roots], [("docs", 1)])
        st = self.cli_json("status", "--json")
        for k in ("db", "schema_version", "migrated_from", "roots", "coverage", "paragraphs", "vectors", "model", "mode", "last_refresh"):
            self.assertIn(k, st)
        self.assertEqual((st["mode"], st["vectors"], st["paragraphs"], st["roots"][0]["files"]), ("keyword", 0, 1, {"ok": 1}))
        self.assertEqual(self.cli("status")[0], 0)
        self.assertEqual(self.cli("report")[0], 0)
        self.assertEqual(self.cli("bogus")[0], 2)
        self.assertEqual(self.cli()[0], 2)
        self.assertEqual(self.cli("show", "docs/missing.md")[0], 1)
        res = self.cli_json("search", "hello", "--json", "--limit", "5")
        self.assertEqual((res["mode"], res["refresh_started"], res["hits"][0]["ref"]), ("keyword", False, "docs/a.md#p1"))
        self.assertEqual(set(res["hits"][0]), {"ref", "root", "path", "heading", "title", "snippet", "score", "arms", "label", "url", "source", "mtime", "locator", "flags"})

    def test_catalog_commands_import_nothing_heavy(self):
        self.w("a.md", "hello")
        self.index()
        code = ("import sys, json; sys.path.insert(0, %r); import doc_index as di\n"
                "for a in (['files','hello'],['roots'],['status'],['label',%r],['discover'],['related','library/a.md'],['newest','library/a.md'],['show','library/a.md#p1']):\n"
                "    di.main(['--db', %r] + a)\n"
                "print('HEAVY=' + json.dumps([m for m in ('markitdown','numpy','fastembed','pdfminer','pptx','openpyxl','docx','onnxruntime') if m in sys.modules]))\n"
                % (SCRIPTS, os.path.join(self.root, "a.md"), self.db))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", env=os.environ, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "HEAVY=[]")

    def test_discover_lists_libraries_without_opening_files(self):
        home = os.environ["USERPROFILE"]
        self.w("OneDrive - Example Org/Team/a.md", "alpha", root=home)
        self.w("OneDrive - Example Org/Team/online.md", "x" * 7, root=home)
        self.w("Documents/b.md", "beta", root=home)
        cap = os.path.join(self.tmp, "cap")
        self.w("x.md", "captured", root=cap)
        con = self.con()
        di.add_root(con, cap, "captured")
        opened = []
        real_open = builtins.open

        def spy(f, *a, **k):
            opened.append(str(f))
            return real_open(f, *a, **k)
        with mock.patch.object(di, "is_cloud_only", lambda st: st.st_size == 7), mock.patch("builtins.open", spy):
            libs = di.discover(con)["libraries"]
        con.close()
        self.assertEqual([p for p in opened if home in p or cap in p], [])
        by = {L["kind"]: L for L in libs}
        self.assertEqual(set(by), {"onedrive-business", "documents", "captured"})
        self.assertEqual((by["onedrive-business"]["on_device_files"], by["onedrive-business"]["cloud_only_files"], by["onedrive-business"]["sampled"]), (1, 1, False))
        self.assertEqual(by["captured"]["label"], "captured")
        out = self.cli_json("discover", "--json")
        self.assertIn("libraries", out)

    def test_cli_reexecs_under_the_knowledge_python(self):
        need(self, "markitdown", "docx")
        py = os.path.join(sys.base_prefix, "python.exe") if os.name == "nt" else os.path.join(sys.base_prefix, "bin", "python3")
        self.assertNotEqual(os.path.normcase(py), os.path.normcase(sys.executable), "this test needs a virtual environment")
        base = [py, "-S"]   # -S: no site-packages, so no markitdown
        probe = subprocess.run([*base, "-c", "import importlib.util as u; print(u.find_spec('markitdown') is None)"], capture_output=True, text=True)
        self.assertEqual(probe.stdout.strip(), "True", probe.stderr)
        cfg = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "workbench")
        os.makedirs(cfg)
        with open(os.path.join(cfg, "config.json"), "w") as f:
            json.dump({"knowledge_python": sys.executable}, f)
        docx = F.make_docx(os.path.join(self.tmp, "x.docx"), text="Hello from a word document.")
        rc, out, err = self.cli("convert", docx, "--json", python=base)
        self.assertEqual(rc, 0, err)
        self.assertIn("Hello from a word document", json.loads(out)["markdown"], out)
        rc, out, err = self.cli("convert", docx, "--json", python=base, env={"WB_KNOWLEDGE_REEXEC": "1"})   # the re-exec loop stop
        self.assertIn("markitdown is not installed", json.loads(out)["error"])


class Vectors(Env):
    """Hybrid search with a stand-in embedder: no model and no network."""
    SYN = {"car": "vehicle", "automobile": "vehicle", "pass": "permit", "badge": "permit"}

    class Fake:
        def __init__(self):
            self.calls = []

        @staticmethod
        def vec(text):
            import numpy as np
            v = np.zeros(64, dtype=np.float32)
            for t in re.findall(r"\w+", text.lower()):
                v[zlib.crc32(Vectors.SYN.get(t, t).encode()) % 64] += 1
            return v

        def embed(self, texts, batch_size=32):
            self.calls.append(len(texts))
            return iter([self.vec(t) for t in texts])

        def query_embed(self, q):
            return iter([self.vec(q)])

    def setUp(self):
        super().setUp()
        need(self, "numpy")
        self.fake = self.Fake()
        self.real_get_embedder = di.get_embedder
        p = mock.patch.object(di, "get_embedder", lambda download=False: self.fake)
        p.start()
        self.addCleanup(p.stop)

    def test_rrf_fuses_both_arms_and_dense_only_hits_appear(self):
        self.w("a/parking.md", "# Parking\n\nStaff renew the vehicle permit yearly.\n")
        self.w("b/lunch.md", "# Lunch\n\nThe cafeteria opens at noon.\n")
        self.index()
        con = self.con()
        out = di.embed_cmd(con)
        con.close()
        self.assertEqual((out["embedded"], out["reused"], out["pending"]), (4, 0, False))
        both = self.search("vehicle permit")
        self.assertEqual(both["mode"], "hybrid")
        self.assertIsNone(both["mode_reason"])
        h = both["hits"][0]
        self.assertEqual((h["ref"], h["arms"]), ("library/a/parking.md#p2", {"bm25": 1, "dense": 1}))
        self.assertEqual(h["score"], round(2 / (di.RRF_K + 1), 5))
        dense_only = self.search("car pass")["hits"][0]
        self.assertEqual((dense_only["path"], dense_only["arms"]["bm25"]), ("a/parking.md", None))
        self.assertEqual(dense_only["arms"]["dense"], 1)
        kw = self.search("car pass", mode="keyword")
        self.assertEqual((kw["mode"], kw["mode_reason"], kw["hits"]), ("keyword", "keyword mode requested", []))
        self.assertEqual(self.search("vehicle permit", mode="keyword")["hits"][0]["arms"]["dense"], None)

    def test_identical_paragraphs_embed_once(self):
        for d in ("x", "y"):
            self.w(f"{d}/memo.md", "# Memo\n\nSame words in two folders.\n")
        self.index()
        con = self.con()
        out = di.embed_cmd(con)
        self.assertEqual((out["embedded"], out["reused"]), (2, 2))
        self.assertEqual(sum(self.fake.calls), 2)
        self.assertEqual(di.embed_cmd(con)["embedded"], 0)                  # nothing left to do
        con.close()

    def test_search_filters_apply_to_both_arms(self):
        self.w("a/one.md", "# One\n\nvehicle permit renewal\n")
        self.w("b/two.md", "# Two\n\nvehicle permit renewal\n")
        self.index()
        con = self.con()
        di.embed_cmd(con)
        con.close()
        self.assertEqual({h["path"] for h in self.search("car pass", path="b/two")["hits"]}, {"b/two.md"})

    def test_wrong_model_hash_falls_back_to_keyword_and_deletes_the_file(self):
        self.w("a.md", "# A\n\nvehicle permit renewal\n")
        self.index()
        con = self.con()
        con.execute("insert into vec select id, ?, 384, zeroblob(1536) from paras", (di.MODEL,))
        con.commit()
        con.close()
        bad = os.path.join(di.models_dir(), "models--Qdrant--bge-small-en-v1.5-onnx-Q", "snapshots", "abc", di.MODEL_FILE)
        os.makedirs(os.path.dirname(bad))
        with open(bad, "wb") as f:
            f.write(b"this is not the pinned model")
        with mock.patch.object(di, "get_embedder", self.real_get_embedder):   # the real check, not the stand-in
            res = self.search("vehicle permit")
        self.assertEqual(res["mode"], "keyword")
        self.assertIn("SHA-256", res["mode_reason"])
        self.assertTrue(res["hits"])
        self.assertFalse(os.path.exists(bad))
        self.assertFalse(os.path.exists(os.path.join(di.models_dir(), "models--Qdrant--bge-small-en-v1.5-onnx-Q")))
        con = self.con()
        self.assertTrue([n for n in di.status(con, self.db)["notes"] if "SHA-256" in n])
        con.close()

    def test_rerank_without_a_local_model_keeps_the_hits(self):
        need(self, "fastembed")
        self.w("a.md", "# A\n\nvehicle permit renewal\n")
        self.index()
        res = self.search("vehicle permit", mode="keyword", rerank=True)
        self.assertTrue(res["hits"])
        self.assertIn("rerank unavailable", res["mode_reason"])


class Offline(Env):
    def test_search_falls_back_to_keyword_with_exit_zero(self):
        self.w("a.md", "# A\n\nThe quarterly rollout plan.\n")
        self.assertEqual(self.cli("index", self.root)[0], 0)
        self.assertFalse(os.path.exists(di.models_dir()))                     # an empty model dir
        res = self.cli_json("search", "rollout plan", "--mode", "auto", "--json", env={"HF_HUB_OFFLINE": "1"})
        self.assertEqual((res["mode"], res["hits"][0]["ref"]), ("keyword", "library/a.md#p2"))
        self.assertTrue(res["mode_reason"])
        con = self.con()
        con.execute("insert into vec select id, ?, 384, zeroblob(1536) from paras", (di.MODEL,))   # vectors exist, the model does not
        con.commit()
        con.close()
        res = self.cli_json("search", "rollout plan", "--mode", "hybrid", "--json", env={"HF_HUB_OFFLINE": "1"})
        self.assertEqual((res["mode"], bool(res["hits"])), ("keyword", True))
        self.assertIn("not downloaded", res["mode_reason"])
        self.assertEqual(self.cli_json("status", "--json")["mode"], "keyword")

    def test_embed_offline_reports_and_does_not_raise(self):
        self.w("a.md", "# A\n\ntext\n")
        self.index()
        res = self.cli_json("embed", "--json", env={"HF_HUB_OFFLINE": "1"})
        self.assertEqual((res["embedded"], res["model"]), (0, None))
        self.assertIn("offline", res["mode_reason"])


class Junctions(Env):
    """A junction inside an indexed folder is never entered: its files belong to the folder it points at."""

    def test_walk_skips_a_junction(self):
        if os.name != "nt":
            self.skipTest("junctions exist only on Windows")
        self.w("sub/own.md", "# Own\n\nthe quillfeather rotation\n")
        real = os.path.join(self.tmp, "elsewhere")
        self.w("other.md", "# Other\n\nquillfeather again\n", root=real)
        link = os.path.join(self.root, "sub", "mirror")
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, real], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, "the junction must be created: " + r.stdout + r.stderr)
        try:
            self.assertTrue(os.path.isfile(os.path.join(link, "other.md")), "the junction really shows the file a second time")
            self.assertEqual(sorted(rel for rel, _st in di.walk(self.root)), ["sub/own.md"])
            self.index()
            self.assertEqual(self.q("select rel from files order by rel"), [("sub/own.md",)])
            root_link = os.path.join(self.tmp, "library-link")        # a root reached through a junction (a redirected folder) is still walked
            r = subprocess.run(["cmd", "/c", "mklink", "/J", root_link, self.root], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            try:
                self.assertEqual(sorted(rel for rel, _st in di.walk(root_link)), ["sub/own.md"])
            finally:
                os.rmdir(root_link)
        finally:
            os.rmdir(link)       # the junction itself, never its target

    def test_only_a_mount_point_reparse_tag_counts_as_a_junction(self):
        """Python 3.10 and 3.11 have no DirEntry.is_junction: the fallback reads the reparse tag, so a OneDrive placeholder
        folder (a reparse point under another tag) is still walked."""
        class Entry:   # no is_junction attribute, like a DirEntry before 3.12
            def __init__(self, attrs, **more):
                self.st = types.SimpleNamespace(st_file_attributes=attrs, **more)

            def stat(self, follow_symlinks=True):
                return self.st
        self.assertTrue(di.is_junction(Entry(0x410, st_reparse_tag=di.MOUNT_POINT)))
        self.assertFalse(di.is_junction(Entry(0x410, st_reparse_tag=0x9000601A)), "a cloud placeholder holds real files")
        self.assertFalse(di.is_junction(Entry(0x10, st_reparse_tag=0)))
        self.assertFalse(di.is_junction(types.SimpleNamespace(stat=lambda follow_symlinks=True: types.SimpleNamespace())), "no attributes (not Windows)")
        self.assertTrue(di.is_junction(Entry(0x410)), "a reparse point with no tag to read is skipped, not followed")


class Sideload(Env):
    """`model import` / `model export`: the pinned model reaches a machine that cannot reach the hub. The pins (the model and its
    four JSON files) are replaced by the hashes of stand-in files, so no real model is needed; the mismatch tests use the real pin."""
    REV = "0123abcd"
    FILES = {"model_optimized.onnx": b"stand-in for the onnx model " * 200, "config.json": b"{}", "tokenizer.json": b"{\"t\": 1}",
             "tokenizer_config.json": b"{\"c\": 2}", "special_tokens_map.json": b"{\"s\": 3}"}

    def setUp(self):
        super().setUp()
        self.pkg = os.path.join(self.tmp, "pkg")
        self.model_dir = self.package(self.pkg)
        sha = lambda n: hashlib.sha256(self.FILES[n]).hexdigest()   # noqa: E731
        for pin in (mock.patch.object(di, "MODEL_SHA256", sha("model_optimized.onnx")),
                    mock.patch.object(di, "MODEL_SIDECARS", {n: sha(n) for n in self.FILES if n.endswith(".json")})):
            pin.start()
            self.addCleanup(pin.stop)

    def package(self, where, drop=(), extra=None, rev=None):
        top = os.path.join(where, di.MODEL_CACHE_DIR)
        rev = rev or self.REV
        for n, data in {**self.FILES, **(extra or {})}.items():
            if n not in drop:
                os.makedirs(os.path.join(top, "snapshots", rev), exist_ok=True)
                with open(os.path.join(top, "snapshots", rev, n), "wb") as f:
                    f.write(data)
        os.makedirs(os.path.join(top, "refs"), exist_ok=True)
        with open(os.path.join(top, "refs", "main"), "w") as f:
            f.write(rev)
        os.makedirs(os.path.join(top, "blobs"), exist_ok=True)
        with open(os.path.join(top, "blobs", "ab12"), "wb") as f:
            f.write(b"the hub's duplicate copy")
        return top

    def zip_of(self, name, entries):
        out = os.path.join(self.tmp, name)
        with zipfile.ZipFile(out, "w") as zf:
            for arc, data in entries.items():
                zf.writestr(arc, data)
        return out

    def run_main(self, *args):
        """(exit code, stdout, stderr) of main() in this process."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = di.main(["--db", self.db, *map(str, args)])
        return rc, out.getvalue(), err.getvalue()

    def cached(self):
        return os.path.join(di.models_dir(), di.MODEL_CACHE_DIR)

    def test_import_from_a_folder_puts_the_model_where_the_search_finds_it(self):
        self.assertIsNone(di.find_model_file())
        with mock.patch("socket.socket", side_effect=AssertionError("no network")):
            rc, out, err = self.run_main("model", "import", self.pkg, "--json")
        self.assertEqual(rc, 0, err)
        res = json.loads(out)
        self.assertEqual((res["dir"], res["files"]), (self.cached(), 6))                  # five snapshot files and refs/main
        found = di.find_model_file()
        self.assertEqual(found, os.path.join(self.cached(), "snapshots", self.REV, di.MODEL_FILE))
        self.assertEqual(di.verified_model_file(), found, "the pinned hash matches the imported file")
        with open(os.path.join(self.cached(), "refs", "main")) as f:
            self.assertEqual(f.read(), self.REV, "the hub's offline lookup resolves the revision through refs/main")
        self.assertFalse(os.path.exists(os.path.join(self.cached(), "blobs")), "the hub's duplicate copy is not needed")
        self.assertEqual([n for n in os.listdir(di.models_dir()) if n.startswith(".")], [], "no staging folder left behind")
        rc, out, err = self.run_main("model", "import", self.pkg)
        self.assertEqual(rc, 0)
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertIn("doc_index.py embed", out)

    def test_import_from_a_zip_and_from_a_folder_that_holds_the_cache_folder(self):
        entries = {f"{di.MODEL_CACHE_DIR}/snapshots/{self.REV}/{n}": d for n, d in self.FILES.items()}
        entries[f"{di.MODEL_CACHE_DIR}/blobs/ab12"] = b"x"
        entries["readme.txt"] = b"not part of the model"
        for name, wrap in (("plain.zip", ""), ("wrapped.zip", "models/")):
            shutil.rmtree(di.models_dir(), ignore_errors=True)
            z = self.zip_of(name, {wrap + k: v for k, v in entries.items()})
            rc, out, err = self.run_main("model", "import", z)
            self.assertEqual(rc, 0, f"{name}: {err}")
            self.assertEqual(sorted(os.listdir(os.path.join(self.cached(), "snapshots", self.REV))), sorted(self.FILES), name)
            self.assertEqual(os.listdir(self.cached()).count("blobs"), 0, name)
            self.assertFalse(os.path.exists(os.path.join(di.models_dir(), "readme.txt")))
        shutil.rmtree(di.models_dir(), ignore_errors=True)
        shutil.copytree(self.pkg, os.path.join(self.tmp, "wrapper", "models"))                 # the folder one level up works too
        self.assertEqual(self.run_main("model", "import", os.path.join(self.tmp, "wrapper"))[0], 0)
        self.assertTrue(di.find_model_file())

    def test_a_model_file_that_does_not_match_the_pin_is_refused_before_anything_is_copied(self):
        with mock.patch.object(di, "MODEL_SHA256", "0" * 64):
            rc, out, err = self.run_main("model", "import", self.pkg)
        self.assertEqual((rc, out), (1, ""))
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertIn("does not match the pinned SHA-256", err)
        self.assertFalse(os.path.exists(di.models_dir()), "nothing was created, not even the staging folder")
        rc, out, err = self.cli("model", "import", self.pkg)                                    # the real pin, from the command line
        self.assertEqual((rc, out), (1, ""))
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertFalse(os.path.exists(di.models_dir()))

    def test_missing_files_and_wrong_paths_are_one_clear_line(self):
        cases = {"no model file": self.package(os.path.join(self.tmp, "p1"), drop=("model_optimized.onnx",)),
                 "no tokenizer": self.package(os.path.join(self.tmp, "p2"), drop=("tokenizer.json",)),
                 "no config": self.package(os.path.join(self.tmp, "p3"), drop=("config.json",)),
                 "no tokenizer config": self.package(os.path.join(self.tmp, "p4"), drop=("tokenizer_config.json",)),
                 "no special tokens": self.package(os.path.join(self.tmp, "p5"), drop=("special_tokens_map.json",))}
        want = {"no model file": "is missing from", "no tokenizer": "tokenizer.json missing beside", "no config": "config.json missing beside",
                "no tokenizer config": "tokenizer_config.json missing beside", "no special tokens": "special_tokens_map.json missing beside"}
        for label, top in cases.items():
            rc, out, err = self.run_main("model", "import", os.path.dirname(top))
            self.assertEqual((rc, out), (1, ""), label)
            self.assertEqual(len(err.strip().splitlines()), 1, err)
            self.assertIn(want[label], err, label)
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        text = os.path.join(self.tmp, "notes.txt")
        with open(text, "w") as f:
            f.write("x")
        for bad in (empty, text, os.path.join(self.tmp, "absent.zip")):
            rc, out, err = self.run_main("model", "import", bad)
            self.assertEqual((rc, len(err.strip().splitlines())), (1, 1), bad)
        self.assertEqual(self.run_main("model", "bogus", self.pkg)[0], 2)
        self.assertFalse(os.path.exists(di.models_dir()))

    def test_a_zip_entry_that_leaves_its_folder_is_refused(self):
        base = {f"{di.MODEL_CACHE_DIR}/snapshots/{self.REV}/{n}": d for n, d in self.FILES.items()}
        for evil in (f"{di.MODEL_CACHE_DIR}/snapshots/{self.REV}/../../../../escaped.txt", "/abs/escaped.txt", "C:/escaped.txt"):
            z = self.zip_of("evil.zip", {**base, evil: b"x"})
            rc, out, err = self.run_main("model", "import", z)
            self.assertEqual((rc, len(err.strip().splitlines())), (1, 1), evil)
            self.assertIn("unsafe path", err)
        self.assertFalse(os.path.exists(di.models_dir()))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escaped.txt")))

    def snapshot(self):
        """{relative path: bytes} of everything under the cached model folder, to prove a failed import changed nothing."""
        out = {}
        for d, _dirs, names in os.walk(di.models_dir()):
            for n in names:
                full = os.path.join(d, n)
                with open(full, "rb") as f:
                    out[os.path.relpath(full, di.models_dir())] = f.read()
        return out

    def test_a_second_import_replaces_the_cache_folder_whole(self):
        self.assertEqual(self.run_main("model", "import", self.pkg)[0], 0)
        stale = os.path.join(self.cached(), "snapshots", self.REV, "stale.txt")
        with open(stale, "w") as f:
            f.write("left over from the first import")
        other = self.package(os.path.join(self.tmp, "second"), rev="fedcba98")
        self.assertEqual(self.run_main("model", "import", os.path.dirname(other))[0], 0)
        self.assertEqual(os.listdir(os.path.join(self.cached(), "snapshots")), ["fedcba98"], "the old revision is gone: replaced, not merged")
        with open(os.path.join(self.cached(), "refs", "main")) as f:
            self.assertEqual(f.read(), "fedcba98")
        self.assertEqual(self.run_main("model", "import", self.pkg)[0], 0)
        self.assertFalse(os.path.exists(stale))
        junk = self.package(os.path.join(self.tmp, "junk"), extra={"notes.txt": b"x", "extra.json": b"not json"})
        self.assertEqual(self.run_main("model", "import", os.path.dirname(junk))[0], 0)
        self.assertEqual(sorted(os.listdir(os.path.join(self.cached(), "snapshots", self.REV))), sorted(self.FILES),
                         "only the pinned files are taken, whatever else the package holds")

    def test_a_refused_import_leaves_the_working_model_byte_identical(self):
        self.assertEqual(self.run_main("model", "import", self.pkg)[0], 0)
        before = self.snapshot()
        bad_model = self.package(os.path.join(self.tmp, "bad1"), extra={"model_optimized.onnx": b"tampered"})
        bad_tokenizer = self.package(os.path.join(self.tmp, "bad2"), extra={"tokenizer.json": b"{\"t\": 2}"})     # valid JSON, not the pinned file
        broken_json = self.package(os.path.join(self.tmp, "bad3"), extra={"config.json": b"{ not json"})
        for top, name in ((bad_model, di.MODEL_FILE), (bad_tokenizer, "tokenizer.json"), (broken_json, "config.json")):
            rc, out, err = self.run_main("model", "import", os.path.dirname(top))
            self.assertEqual((rc, len(err.strip().splitlines())), (1, 1), name)
            self.assertIn("does not match", err, name)
            self.assertEqual(self.snapshot(), before, f"a refused {name} must not touch the model that works")
        # the file changes between the check and the copy: caught on the copy, before the old folder is moved
        pre_check = [di.MODEL_SHA256, *di.MODEL_SIDECARS.values()]          # what the check "saw": every file as pinned
        with mock.patch.object(di, "_sha_of", side_effect=pre_check):
            rc, out, err = self.run_main("model", "import", os.path.dirname(bad_tokenizer))
        self.assertEqual((rc, len(err.strip().splitlines())), (1, 1))
        self.assertIn("changed while it was being copied", err)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(di.verified_model_file(), di.find_model_file())

    def test_a_symbolic_link_in_a_zip_is_refused_and_the_working_model_stays(self):
        self.assertEqual(self.run_main("model", "import", self.pkg)[0], 0)
        before = self.snapshot()
        base = f"{di.MODEL_CACHE_DIR}/snapshots/{self.REV}/"
        out = os.path.join(self.tmp, "link.zip")
        with zipfile.ZipFile(out, "w") as zf:
            for n, data in self.FILES.items():
                if n == "tokenizer.json":
                    info = zipfile.ZipInfo(base + n)
                    info.external_attr = (0o120777 << 16)          # a symbolic link entry: its content is the target path
                    zf.writestr(info, "../../elsewhere/tokenizer.json")
                else:
                    zf.writestr(base + n, data)
        rc, o, err = self.run_main("model", "import", out)
        self.assertEqual((rc, o, len(err.strip().splitlines())), (1, "", 1), err)
        self.assertIn("symbolic link", err)
        self.assertEqual(self.snapshot(), before, "the working model is untouched")

    def test_a_damaged_zip_is_one_clear_line(self):
        self.assertEqual(self.run_main("model", "import", self.pkg)[0], 0)
        before = self.snapshot()
        base = f"{di.MODEL_CACHE_DIR}/snapshots/{self.REV}/"
        for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            out = os.path.join(self.tmp, f"damaged{method}.zip")
            with zipfile.ZipFile(out, "w", method) as zf:
                for n, data in self.FILES.items():
                    zf.writestr(base + n, data)
                head = zf.getinfo(base + "model_optimized.onnx")
            raw = bytearray(open(out, "rb").read())
            start = head.header_offset + 30 + len(head.filename.encode()) + 4        # inside the member's data
            raw[start:start + 24] = b"\xff" * 24
            with open(out, "wb") as f:
                f.write(raw)
            rc, o, err = self.run_main("model", "import", out)
            self.assertEqual((rc, o, len(err.strip().splitlines())), (1, "", 1), f"method {method}: {err}")
            self.assertIn("is damaged", err)
            self.assertEqual(self.snapshot(), before)
        with mock.patch.object(di, "_sha_of", side_effect=zlib.error("incomplete or truncated stream")):
            rc, o, err = self.run_main("model", "import", self.pkg)
        self.assertEqual((rc, len(err.strip().splitlines())), (1, 1), "a zlib error is mapped too")
        self.assertIn("is damaged", err)

    def test_export_packs_the_verified_model_and_import_takes_it_back(self):
        rc, out, err = self.run_main("model", "export", os.path.join(self.tmp, "none.zip"))
        self.assertEqual((rc, len(err.strip().splitlines())), (1, 1), "nothing cached yet")
        self.assertIn("no cached embedding model", err)
        self.assertEqual(self.run_main("model", "import", self.pkg)[0], 0)
        out_zip = os.path.join(self.tmp, "out", "model.zip")
        rc, out, err = self.run_main("model", "export", out_zip, "--json")
        self.assertEqual(rc, 0, err)
        with zipfile.ZipFile(out_zip) as zf:
            names = sorted(zf.namelist())
        self.assertEqual(names, sorted([f"{di.MODEL_CACHE_DIR}/refs/main", *(f"{di.MODEL_CACHE_DIR}/snapshots/{self.REV}/{n}" for n in self.FILES)]))
        self.assertFalse(os.path.exists(out_zip + ".tmp"))
        before = {n: open(os.path.join(self.cached(), "snapshots", self.REV, n), "rb").read() for n in self.FILES}
        shutil.rmtree(di.models_dir())
        self.assertEqual(self.run_main("model", "import", out_zip)[0], 0)
        self.assertEqual({n: open(os.path.join(self.cached(), "snapshots", self.REV, n), "rb").read() for n in self.FILES}, before)
        self.assertEqual(di.verified_model_file(), di.find_model_file())
        bad = os.path.join(self.cached(), "snapshots", self.REV, di.MODEL_FILE)           # a cache that no longer matches the pin
        with open(bad, "wb") as f:
            f.write(b"corrupt")
        rc, out, err = self.run_main("model", "export", os.path.join(self.tmp, "second.zip"))
        self.assertEqual((rc, len(err.strip().splitlines())), (1, 1))
        self.assertIn("does not match the pinned SHA-256", err)
        self.assertTrue(os.path.exists(bad), "export reports a bad cache, it does not delete it")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "second.zip")))
        self.assertEqual(self.run_main("model", "export", self.tmp)[0], 1, "a folder is not a zip name")

    def test_status_says_why_search_is_keyword_only_and_names_the_import(self):
        self.w("a.md", "# A\n\nrollout plan\n")
        self.assertEqual(self.cli("index", self.root)[0], 0)
        st = self.cli_json("status", "--json")
        self.assertEqual(st["mode"], "keyword")
        self.assertIn("offline (HF_HUB_OFFLINE is set)", st["keyword_reason"])
        self.assertTrue(st["model_import"].startswith("doc_index.py model import"))
        st = self.cli_json("status", "--json", env={"HF_HUB_OFFLINE": "0"})
        self.assertRegex(st["keyword_reason"], r"the embedding model is not downloaded")
        rc, out, err = self.cli("status", env={"HF_HUB_OFFLINE": "0"})
        self.assertEqual(rc, 0, err)
        self.assertIn("search is keyword-only: ", out)
        self.assertIn("doc_index.py model import", out)
        self.assertIn("doc_index.py model export", out)
        con = self.con()
        con.execute("insert or replace into meta values('model_fail', ?)",
                    (json.dumps({"at": di.now_iso(), "host": di.hub_host(), "error": "HfHubHTTPError, HTTP 403"}),))
        con.commit()
        with mock.patch.dict(os.environ, {"HF_HUB_OFFLINE": "0"}):
            self.assertIn("download from huggingface.co failed: HfHubHTTPError, HTTP 403", di.status(con, self.db)["keyword_reason"])
            have = lambda missing: (lambda m: None if m in missing else object())   # noqa: E731
            with mock.patch.object(di.importlib.util, "find_spec", have(("fastembed",))):
                self.assertIn("fastembed not installed in this Python", di.keyword_reason(con, 3, "model.onnx"))
                self.assertIn("fastembed not installed", di.keyword_reason(con, 0, None))
            with mock.patch.object(di.importlib.util, "find_spec", have(())):
                self.assertIsNone(di.keyword_reason(con, 3, "model.onnx"), "package, model and vectors: hybrid")
                self.assertEqual(di.keyword_reason(con, 0, "model.onnx"), "no vectors yet: run `embed` (or `refresh`)")
        self.assertEqual(self.run_main("model", "import", self.pkg)[0], 0)
        st = di.status(con, self.db)
        self.assertIsNone(st["model_import"], "the model is in place: no import to suggest")
        self.assertEqual(st["model"], di.MODEL)
        con.close()


class Download(Env):
    def test_tls_failure_retries_once_over_plain_https_without_xet(self):
        need(self, "numpy", "fastembed")
        import huggingface_hub.constants as hc
        os.environ["HF_HUB_OFFLINE"] = "0"
        os.environ.pop("HF_HUB_DISABLE_XET", None)
        calls = []

        def fake_embedding(*a, **k):
            calls.append(os.environ.get("HF_HUB_DISABLE_XET"))
            if len(calls) == 1:
                raise RuntimeError("SSL: CERTIFICATE_VERIFY_FAILED")
            return object()
        with mock.patch("fastembed.TextEmbedding", fake_embedding), mock.patch.object(hc, "HF_HUB_DISABLE_XET", False), \
                mock.patch.object(di, "verified_model_file", lambda: "model.onnx" if calls else None):
            di.get_embedder(download=True)
            self.assertTrue(hc.HF_HUB_DISABLE_XET)
        self.assertEqual(calls, [None, "1"])
        self.assertEqual(os.environ["HF_HUB_DISABLE_TELEMETRY"], "1")

    def test_other_download_errors_do_not_retry_and_fall_back_to_keyword(self):
        need(self, "numpy", "fastembed")
        os.environ["HF_HUB_OFFLINE"] = "0"
        calls = []

        def fake_embedding(*a, **k):
            calls.append(1)
            raise RuntimeError("connection reset")
        with mock.patch("fastembed.TextEmbedding", fake_embedding):
            with self.assertRaises(di.ModelUnavailable) as cm:
                di.get_embedder(download=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual((cm.exception.host, cm.exception.error), ("huggingface.co", "RuntimeError"))   # host and class, not the library's wording
        self.assertNotIn("connection reset", str(cm.exception))


class Lazy(Env):
    def wait_idle(self, db, seconds=180):
        """Wait for a detached refresh to finish: its lock is free and last_refresh is set."""
        end = time.time() + seconds
        while time.time() < end:
            h = di.try_lock(di.lock_path(db))
            if h is not None:
                h.close()
                con = di.connect(db)
                last = di.get_meta(con, "last_refresh")
                con.close()
                if last:
                    return last
            time.sleep(0.5)
        self.fail("the detached refresh did not finish")

    def test_stale_refresh_is_started_once_and_hits_still_return(self):
        self.assertTrue(di.find_memcap(), "tools/memcap/memcap.py must be reachable from the skill")
        self.w("a.md", "# A\n\nThe quarterly rollout plan covers three regions.\n")
        self.index()
        del os.environ["WB_FIND_LAZY"]
        try:
            res = self.search("rollout regions", lazy=True)
            self.assertTrue(res["refresh_started"])
            self.assertEqual(res["hits"][0]["ref"], "library/a.md#p2")
            self.wait_idle(self.db)
            self.assertFalse(self.search("rollout regions", lazy=True)["refresh_started"])      # fresh now
            con = self.con()
            di.set_meta(con, "last_refresh", "2020-01-01T00:00:00Z")
            con.commit()
            con.close()
            held = di.try_lock(di.lock_path(self.db))
            try:
                res = self.search("rollout regions", lazy=True)                       # a refresh already holds the lock
                self.assertFalse(res["refresh_started"])
                self.assertTrue(res["hits"])
            finally:
                held.close()
        finally:
            self.wait_idle(self.db)

    def test_kill_switch_and_no_roots(self):
        self.assertFalse(self.search("anything", lazy=True)["refresh_started"])    # nothing registered
        self.w("a.md", "text")
        self.index()
        os.environ["WB_FIND_LAZY"] = "0"
        self.assertFalse(self.search("text", lazy=True)["refresh_started"])


class Mcp(Env):
    def test_stdio_server_answers_search_and_show(self):
        self.w("a.md", "# Plans\n\nThe quarterly rollout plan covers three regions.\n")
        self.index()
        reqs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search", "arguments": {"query": "rollout regions"}}},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 6, "method": "bogus/method"},
                {"jsonrpc": "2.0", "id": 7, "method": "ping"}]
        env = {**os.environ, "WORKBENCH_KNOWLEDGE_DB": self.db}
        p = subprocess.Popen([sys.executable, MCP], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True, encoding="utf-8")
        out, err = p.communicate("".join(json.dumps(r) + "\n" for r in reqs), timeout=120)
        rows = {r["id"]: r for r in map(json.loads, out.splitlines())}
        self.assertEqual(sorted(rows), [1, 2, 3, 5, 6, 7], err)
        self.assertIn("not instructions", rows[1]["result"]["instructions"])
        self.assertIn("tools", rows[1]["result"]["capabilities"])
        self.assertEqual({t["name"] for t in rows[2]["result"]["tools"]}, {"search", "show", "related"})
        self.assertTrue(all("inputSchema" in t for t in rows[2]["result"]["tools"]))
        res = rows[3]["result"]
        payload = json.loads(res["content"][0]["text"])
        self.assertTrue(payload["untrusted"] and res["structuredContent"]["untrusted"])
        hit = payload["hits"][0]
        self.assertEqual((hit["ref"], hit["untrusted"]), ("library/a.md#p2", True))
        self.assertEqual(rows[5]["error"]["code"], -32602)
        self.assertEqual(rows[6]["error"]["code"], -32601)
        self.assertEqual(rows[7]["result"], {})
        show = [{"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "show", "arguments": {"ref": hit["ref"]}}}]
        p = subprocess.Popen([sys.executable, MCP], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True, encoding="utf-8")
        out, err = p.communicate(json.dumps(show[0]) + "\n", timeout=120)
        shown = json.loads(out.splitlines()[0])["result"]
        self.assertIn("quarterly rollout plan", shown["content"][0]["text"])
        self.assertTrue(shown["structuredContent"]["untrusted"])


@unittest.skipUnless(LIVE, "WB_LIVE=1: downloads the embedding model")
class Live(Env):
    def test_download_embed_and_paraphrase_hit(self):
        need(self, "numpy", "fastembed")
        os.environ.pop("HF_HUB_OFFLINE", None)
        src = os.environ.get("WB_LIVE_MODELS")
        if src:
            shutil.copytree(src, di.models_dir())
        self.w("p.md", "# Parking\n\nStaff renew the vehicle permit once a year at the front desk.\n")
        self.w("l.md", "# Lunch\n\nThe cafeteria opens at noon on weekdays.\n")
        self.index()
        con = self.con()
        out = di.embed_cmd(con)
        con.close()
        self.assertGreater(out["embedded"], 0, out)
        res = self.search("how do I keep my car pass valid")
        self.assertEqual(res["mode"], "hybrid", res["mode_reason"])
        self.assertIsNotNone(res["hits"][0]["arms"]["dense"])


if __name__ == "__main__":
    unittest.main()
