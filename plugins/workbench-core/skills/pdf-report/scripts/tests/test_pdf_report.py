"""Tests for the pdf-report skill: the build (real Edge), the preflight check with one negative fixture per check, the PDF tools and
their safety rails, the stdlib-only path and the licences. Run (Edge is needed; a skip is a failure under WB_REQUIRE_ALL=1):
    WB_REQUIRE_ALL=1 py -3 -m unittest discover -s plugins/workbench-core/skills/pdf-report/scripts/tests -v
Edge runs one at a time, on small documents. Nothing here reads the real config folder or any document of yours."""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: a missing dependency FAILS under it, it never skips

import ast  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from importlib import metadata  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest import mock  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
SKILL = SCRIPTS.parent
KIT = SKILL.parents[3]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))
import build_pdf as bp  # noqa: E402
import check_pdf as ck  # noqa: E402
import pdfgen  # noqa: E402
import sample  # noqa: E402

BUILD, CHECK, TOOLS = (str(SCRIPTS / n) for n in ("build_pdf.py", "check_pdf.py", "pdf_tools.py"))
RENDER = KIT / "plugins" / "workbench-core" / "skills" / "office-render" / "scripts" / "render.py"
EDGE = bp.find_edge()
BANNED_WORD = "gu" + "ard"     # rule: this word never appears in a file of this skill, this file included
ENV = {**os.environ, "CLAUDE_CONFIG_DIR": os.path.join(tempfile.gettempdir(), "wb-pdft-no-config"), "PYTHONUTF8": "1"}   # no real config: no re-exec
_SAMPLE = []


def get_sample():
    """(ready, pdf path, build process, parsed --json): the sample report is built once per run with real Edge (two passes) and shared."""
    if not _SAMPLE:
        if not (EDGE and ck.have("pypdf", "pypdfium2", "PIL", "markdown")):
            _SAMPLE.append((False, None, None, None))
        else:
            d = Path(tempfile.mkdtemp(prefix="wb-pdfs-"))
            unittest.addModuleCleanup(shutil.rmtree, d, True)
            out = d / "out" / "sample.pdf"
            r = subprocess.run([sys.executable, BUILD, str(sample.write_sample(d)), "--out", str(out), "--toc", "--png", str(d / "png"), "--json"],
                               capture_output=True, text=True, encoding="utf-8", env=ENV, timeout=300)
            try:
                _SAMPLE.append((True, out, r, json.loads(r.stdout)))
            except ValueError:
                _SAMPLE.append((True, out, r, None))
    return _SAMPLE[0]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def column_edges(pdf, words=("T-001", "Task001item", "TeamB")):
    """(page, left edge in points of the first body cell of each column named by `words`, right edge of the table) read from the PDF
    text layer: the table's own layout as printed, not the stylesheet's intent. Words are matched with the white space left out,
    because a narrow cell can come out of the text layer one letter to a line."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    try:
        for i in range(len(doc)):
            tp = doc[i].get_textpage()
            flat = [(c, k) for k, c in enumerate(tp.get_text_range()) if not c.isspace()]
            text, at, edges = "".join(c for c, _ in flat), 0, []
            for w in words:
                j = text.find(w, at)
                if j < 0:
                    break
                edges.append(tp.get_charbox(flat[j][1])[0])
                at = j + len(w)
            if len(edges) == len(words):
                return i + 1, edges, doc[i].get_size()[0] - 18 / 25.4 * 72      # the page margin of report.css
    finally:
        doc.close()
    raise AssertionError(f"{words} not found in {pdf}")


def long_column_is_wider(pdf):
    """True when the long-text column (second) is wider than the id column and than all the short columns after it together."""
    page, (idl, taskl, ownerl), right = column_edges(pdf)
    task, ident, short = ownerl - taskl, taskl - idl, right - ownerl
    return task > 2.5 * ident and task > short and task > 0.45 * (right - idl)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wb-pdft-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.env = ENV

    def need(self, ok, what):
        if not ok:
            self.fail(f"missing: {what}") if REQUIRE else self.skipTest(what)

    def need_edge(self):
        self.need(EDGE, "Microsoft Edge (msedge.exe)")

    def need_libs(self):
        self.need(ck.have("pypdf", "pypdfium2", "PIL", "markdown"), "pypdf, pypdfium2, Pillow and Markdown (run the workbench setup)")

    @classmethod
    def run_py(cls, *args, env=None, timeout=300):
        return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, encoding="utf-8", env=env or cls.env, timeout=timeout)

    @classmethod
    def build(cls, src, out, *flags, env=None):
        """(process, parsed --json output or None)"""
        r = cls.run_py(BUILD, src, "--out", out, *flags, "--json", env=env)
        try:
            return r, json.loads(r.stdout)
        except ValueError:
            return r, None

    @classmethod
    def html(cls, name, text):
        p = cls.tmp / name
        p.write_text(text, encoding="utf-8")
        return p

    @classmethod
    def check(cls, pdf, *flags):
        r = cls.run_py(CHECK, pdf, *flags, "--json")
        return r.returncode, json.loads(r.stdout)

    def page_texts(self, pdf):
        return [p["text"] for p in ck.scan_pages(pdf, ink=False)]


# ================================================================================================ the positive sample
class Sample(Base):
    """cover + contents + a table over several pages + an SVG chart, built from Markdown with real Edge."""

    def setUp(self):
        self.need_edge()
        self.need_libs()
        ready, self.out, self.proc, self.res = get_sample()
        self.assertIsNotNone(self.res, self.proc.stderr)
        self.c = self.res["check"]["checks"]

    def test_the_build_is_clean_and_every_defect_list_is_empty(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertEqual(self.res["check"]["defects"], [])
        self.assertEqual(self.res["check"]["skipped"], [])
        self.assertEqual(self.res["notes"], [])

    def test_page_n_of_m_on_every_numbered_page(self):
        n = self.res["check"]["pages"]
        self.assertGreaterEqual(n, 6)
        self.assertEqual((self.c["footer"]["ok"], self.c["footer"]["mode"], self.c["footer"]["bad"]), (True, "required", []))
        self.assertEqual(self.c["footer"]["numbered"], n - 1, "every page but the cover reads Page N of M")

    def test_the_table_header_repeats_and_no_row_is_split(self):
        t = self.c["tables"]
        self.assertTrue(t["ok"])
        self.assertGreaterEqual(len(t["continuation_pages"]), 2, "the table runs over at least three pages")
        self.assertEqual(t["header_missing_on"], [])
        self.assertEqual(t["rows_checked"], 70, "all 70 rows were located")
        self.assertEqual((t["rows_unmatched"], t["split_rows"]), (0, []))

    def test_the_long_text_column_is_wider_than_the_short_columns(self):
        page, (idl, taskl, ownerl), right = column_edges(self.out)
        self.assertGreater(ownerl - taskl, 200, "the Task column has room for its text")
        self.assertLess(taskl - idl, 60, "the ID column is as wide as its text needs")
        self.assertLess(right - ownerl, ownerl - taskl, "Owner, Status and Hours together are narrower than Task")
        self.assertTrue(long_column_is_wider(self.out))

    def test_every_font_is_embedded(self):
        f = self.c["fonts"]
        self.assertTrue(f["ok"])
        self.assertGreaterEqual(f["total"], 1)
        self.assertEqual(f["not_embedded"], [])

    def test_bookmarks_exist_and_none_is_doubled(self):
        o = self.c["outline"]
        self.assertTrue(o["ok"] and o["expected"])
        self.assertGreaterEqual(o["entries"], 8)
        self.assertEqual((o["missing_titles"], o["doubled_titles"]), ([], []))

    def test_creator_and_producer_are_scrubbed(self):
        m = self.c["metadata"]
        self.assertTrue(m["ok"])
        self.assertEqual((m["leaks"], m["creator"], m["producer"]), ([], "", ""))
        self.assertEqual(m["title"], "Acme quarterly status")
        raw = self.out.read_bytes()
        self.assertNotIn(b"HeadlessChrome", raw)
        self.assertNotIn(b"Skia/PDF", raw)

    def test_the_contents_numbers_equal_the_real_pages_by_two_independent_routes(self):
        self.assertTrue(self.c["toc"]["ok"])
        self.assertEqual((self.c["toc"]["entries"], self.c["toc"]["wrong"]), (6, []))
        texts = self.page_texts(self.out)           # the second route: read the numbers and the headings from the page text
        toc = {m.group(1): int(m.group(2)) for m in re.finditer(r"^(.+?) (\d+)$", texts[1], re.M) if not m.group(1).startswith("Page ")}
        self.assertEqual(sorted(toc), ["Delivery", "Next steps", "Quality", "Results", "Summary", "Task log"])
        for title, printed in toc.items():
            real = next(i + 1 for i, t in enumerate(texts) if i >= 2 and re.search(rf"^{re.escape(title)}$", t, re.M))
            self.assertEqual(printed, real, title)

    def test_no_blank_page_no_remnant_links_resolve(self):
        self.assertEqual(self.c["blank_pages"]["pages"], [])
        self.assertEqual(self.c["remnants"]["pages"], [])
        self.assertEqual(self.c["links"]["broken"], [])
        self.assertGreaterEqual(self.c["links"]["internal"], 6)

    def test_the_cover_has_no_running_header_in_its_text_layer_and_the_body_pages_do(self):
        texts = self.page_texts(self.out)
        self.assertEqual(texts[0].count("Acme quarterly status"), 1, "the cover's own title only: no header text hidden in a margin box")
        self.assertNotIn("Acme quarterly status Internal", texts[0])
        self.assertTrue(texts[1].startswith("Acme quarterly status Internal"), "a body page keeps its running header")

    def test_the_chart_is_vector_text_in_the_page(self):
        texts = self.page_texts(self.out)
        self.assertTrue(any("Q1" in t and "Q4" in t for t in texts), "SVG labels stay selectable text")

    def test_the_cli_check_agrees_and_exits_zero(self):
        code, r = self.check(self.out)
        self.assertEqual((code, r["ok"], r["defects"]), (0, True, []))
        self.assertEqual(r["pages"], self.res["check"]["pages"])

    def test_build_png_flag_and_render_py_give_one_png_per_page(self):
        n = self.res["check"]["pages"]
        self.assertEqual(len(self.res["png"]), n)
        self.assertTrue(all(Path(p).is_file() for p in self.res["png"]))
        out = self.tmp / "png2"
        r = self.run_py(RENDER, self.out, "--out", out, "--dpi", "60")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(list(out.glob("sample-*.png"))), n)

    def test_the_letter_page_size_is_honoured(self):
        out = self.tmp / "letter.pdf"
        r, res = self.build(sample.write_sample(self.tmp), out, "--page", "Letter")
        self.assertIn(r.returncode, (0, 1), r.stderr)
        from pypdf import PdfReader
        w, h = (float(x) for x in PdfReader(str(out)).pages[0].mediabox[2:])
        self.assertEqual((round(w), round(h)), (612, 792))
        self.assertEqual(res["check"]["checks"]["blank_pages"]["pages"], [], "the Letter cover is shorter than the A4 one")


# ================================================================================================ one negative per check
COVER_297 = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Cover test</title><style>
@page { size: A4; margin: 20mm; } @page cover { margin: 0; } body { margin: 0; font-family: "Segoe UI", sans-serif; }
.cover { page: cover; height: 297mm; background: #0a3566; color: #ffffff; break-after: page; }
</style></head><body><section class="cover"><h1>Cover</h1></section><p>Body text on the second page.</p>
<p>Unfilled: {{ customer_name }}</p></body></html>"""

NO_FOOTER = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>No footer</title><style>
@page { size: A4; margin: 20mm; } h1 { break-before: page; } h1:first-child { break-before: auto; }
</style></head><body><h1>One</h1><p>First.</p><h1>Two</h1><p>Second.</p><h1>Three</h1><p>Third.</p></body></html>"""

WRONG_TOC = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Wrong contents</title><style>
@page { size: A4; margin: 20mm; } h1 { break-before: page; margin-top: 1pt; } body { font-family: "Segoe UI", sans-serif; }
</style></head><body><h2>Contents</h2><p><a href="#a">Alpha 9</a></p><p><a href="#b">Beta 9</a></p>
<h1 id="a">Alpha</h1><p>Text.</p><h1 id="b">Beta</h1><p>Text.</p></body></html>"""


def table_defect_html():
    rows = "".join(f"<tr><td>R{i:02d}</td><td>Row {i:02d} " + " ".join(f"w{i:02d}x{j:03d}" for j in range(110)) + "</td></tr>" for i in range(1, 15))
    return ("""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Table defects</title><style>
@page { size: A4; margin: 15mm; } body { font: 10pt "Segoe UI", sans-serif; } table { width: 100%; border-collapse: collapse; }
thead { display: table-row-group; } tr { break-inside: auto; } td, th { padding: 3pt; vertical-align: top; text-align: left; }
td:first-child { width: 14mm; }</style></head><body><table><thead><tr><th>Ref</th><th>Detail</th></tr></thead><tbody>"""
            + rows + "</tbody></table></body></html>")


WRONG_FOOTER = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Wrong footer</title><style>
@page { size: A4; margin: 20mm; @bottom-center { content: "Page " counter(page) " of 9"; } } h1 { break-before: page; } h1:first-child { break-before: auto; }
</style></head><body><h1>One</h1><p>First.</p><h1>Two</h1><p>Second.</p><h1>Three</h1><p>Third.</p></body></html>"""


class Negative(Base):
    """Each defect the preflight promises to catch, from a fixture that really has it."""

    def setUp(self):
        self.need_libs()

    def defect(self, pdf, name, *flags):
        code, r = self.check(pdf, *flags)
        self.assertEqual(code, 1, r)
        self.assertFalse(r["checks"][name]["ok"], r["checks"][name])
        self.assertTrue(any(d.startswith(name + ":") for d in r["defects"]), r["defects"])
        return r["checks"][name]

    def built(self, name, html, *flags):
        self.need_edge()
        out = self.tmp / f"{name}.pdf"
        r, res = self.build(self.html(f"{name}.html", html), out, *flags)
        self.assertIsNotNone(res, r.stderr)
        return out, res

    def test_a_cover_as_tall_as_the_page_leaves_a_blank_page(self):
        pdf, res = self.built("cover297", COVER_297)
        c = self.defect(pdf, "blank_pages", "--footer", "none")
        self.assertTrue(c["pages"], "the 297 mm cover pushed a sliver onto a page of its own")
        self.assertIn("remnants", {d.split(":")[0] for d in res["check"]["defects"]}, "the {{ }} text is a template remnant")

    def test_a_missing_footer_is_caught_when_one_is_required(self):
        pdf, _ = self.built("nofooter", NO_FOOTER)
        c = self.defect(pdf, "footer", "--footer", "required")
        self.assertEqual([b["page"] for b in c["bad"]], [2, 3])
        code, r = self.check(pdf)      # auto: no page has a footer, so none is demanded
        self.assertEqual((code, r["checks"]["footer"]["mode"]), (0, "none"))

    def test_a_footer_with_the_wrong_total_is_caught_and_says_what_it_reads(self):
        pdf, _ = self.built("wrongfooter", WRONG_FOOTER)
        c = self.defect(pdf, "footer")        # auto: footers are present, so they are required and must be true
        self.assertEqual([(b["page"], b["reads"], b["should"]) for b in c["bad"]],
                         [(1, "Page 1 of 9", "Page 1 of 3"), (2, "Page 2 of 9", "Page 2 of 3"), (3, "Page 3 of 9", "Page 3 of 3")])

    def test_an_internal_link_to_nowhere_is_caught(self):
        f = self.tmp / "dead-link.pdf"
        f.write_bytes(pdfgen.link_pdf())
        c = self.defect(f, "links", "--footer", "none")
        self.assertEqual((c["internal"], c["broken"]), (1, [{"page": 1}]))

    def test_a_pdf_with_no_text_layer_is_caught(self):
        f = self.tmp / "no-text.pdf"
        f.write_bytes(pdfgen.plain_pdf(content=b"0 0 200 200 re f"))
        self.assertEqual(self.defect(f, "text_layer", "--footer", "none")["pages_without_text"], [1])

    def test_a_heading_missing_from_the_bookmarks_is_caught(self):
        from pypdf import PdfWriter
        import io
        w = PdfWriter(clone_from=io.BytesIO(pdfgen.plain_pdf()))
        w.add_outline_item("Summary", 0)
        f = self.tmp / "one-bookmark.pdf"
        with open(f, "wb") as fh:
            w.write(fh)
        src = self.html("two-heads.html", "<html><head><title>T</title></head><body><h1>Summary</h1><h1>Results</h1></body></html>")
        self.assertEqual(self.defect(f, "outline", "--html", src, "--footer", "none")["missing_titles"], ["Results"])

    def test_a_wrong_contents_number_is_caught(self):
        pdf, _ = self.built("wrongtoc", WRONG_TOC)
        c = self.defect(pdf, "toc", "--footer", "none")
        self.assertEqual([(w["printed"], w["real"]) for w in c["wrong"]], [(9, 2), (9, 3)])

    def test_a_table_without_a_repeating_header_and_with_split_rows_is_caught(self):
        pdf, _ = self.built("tabledefects", table_defect_html())
        code, r = self.check(pdf, "--html", self.tmp / "tabledefects.html", "--footer", "none")
        t = r["checks"]["tables"]
        self.assertEqual(code, 1, r["defects"])
        self.assertFalse(t["ok"])
        self.assertTrue(t["header_missing_on"], "the header does not repeat")
        self.assertTrue(t["split_rows"], "a row runs across a page boundary")

    def test_a_font_that_is_not_embedded_is_caught(self):
        f = self.tmp / "helvetica.pdf"
        f.write_bytes(pdfgen.plain_pdf())
        c = self.defect(f, "fonts", "--footer", "none")
        self.assertEqual(c["not_embedded"], ["/Helvetica"])

    def test_an_empty_outline_is_caught_and_so_is_a_doubled_title(self):
        sample_pdf = get_sample()[1]
        self.need(sample_pdf, "the sample build (Edge and the packages)")
        from pypdf import PdfWriter
        w = PdfWriter(clone_from=str(sample_pdf))
        del w._root_object["/Outlines"]
        bare = self.tmp / "no-outline.pdf"
        with open(bare, "wb") as f:
            w.write(f)
        c = self.defect(bare, "outline")
        self.assertEqual((c["entries"], c["expected"]), (0, True))
        w = PdfWriter(clone_from=str(sample_pdf))
        w.add_outline_item("SummarySummary", 2)
        twice = self.tmp / "doubled.pdf"
        with open(twice, "wb") as f:
            w.write(f)
        self.assertEqual(self.defect(twice, "outline")["doubled_titles"], ["SummarySummary"])

    def test_equal_column_widths_fail_the_wide_column_check(self):
        """The positive control for the width test: a table of the same text with equal columns is what the check must reject."""
        rows = "".join(f"<tr><td>T-{i:03d}</td><td>Task {i:03d} item {sample.LONG}</td><td>Team B</td><td>Done</td><td>1.5</td></tr>" for i in (1, 2, 3))
        pdf, _ = self.built("equalcols", """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Equal columns</title><style>
@page { size: A4; margin: 18mm; } body { font: 10pt "Segoe UI", sans-serif; } table { width: 100%; table-layout: fixed; border-collapse: collapse; }
td, th { padding: 3pt 6pt; text-align: left; vertical-align: top; }</style></head><body><table><thead><tr><th>ID</th><th>Task</th><th>Owner</th>
<th>Status</th><th>Hours</th></tr></thead><tbody>""" + rows + "</tbody></table></body></html>")
        page, (idl, taskl, ownerl), right = column_edges(pdf)
        self.assertAlmostEqual(taskl - idl, ownerl - taskl, delta=1.5, msg="the fixture really has equal columns")
        self.assertFalse(long_column_is_wider(pdf))

    def test_the_page_count_must_match_when_asked(self):
        f = self.tmp / "one-page.pdf"
        f.write_bytes(pdfgen.plain_pdf())
        self.assertFalse(self.check(f, "--expect-pages", "3", "--footer", "none")[1]["checks"]["pages"]["ok"])
        self.assertEqual(self.check(f, "--expect-pages", "1", "--footer", "none")[1]["checks"]["pages"]["ok"], True)

    def test_a_browser_fingerprint_in_creator_or_producer_is_caught(self):
        f = self.tmp / "fingerprint.pdf"
        f.write_bytes(pdfgen.plain_pdf(b"<< /Title (T) /Creator (HeadlessChrome) /Producer (Skia/PDF m1) >>"))
        c = self.defect(f, "metadata", "--footer", "none")
        self.assertEqual(len(c["leaks"]), 2)

    def test_unreadable_encrypted_and_missing_files_exit_two(self):
        junk = self.tmp / "junk.pdf"
        junk.write_bytes(b"not a pdf")
        enc = self.tmp / "enc.pdf"
        enc.write_bytes(pdfgen.encrypted_pdf())
        for f in (junk, enc, self.tmp / "absent.pdf"):
            self.assertEqual(self.check(f)[0], 2, f)


# ================================================================================================ pdf_tools and its rails
class Tools(Base):
    def setUp(self):
        self.need_libs()

    def tool(self, *args):
        return self.run_py(TOOLS, *args)

    def fixtures(self):
        d = self.tmp / "fx"
        d.mkdir(exist_ok=True)
        for n, data in (("form", pdfgen.form_pdf()), ("signed", pdfgen.form_pdf(signature=True)), ("enc", pdfgen.encrypted_pdf()),
                        ("plain", pdfgen.plain_pdf()),
                        ("label", pdfgen.plain_pdf(b"<< /Title (T) /Author (Pat Example) /MSIP_Label_x_Enabled (true) /Producer (Tool) >>"))):
            (d / f"{n}.pdf").write_bytes(data)
        return d

    def sample_pdf(self):
        self.need_edge()
        ready, out, proc, res = get_sample()
        self.assertTrue(ready and res, "the sample build")
        return out

    def test_info_and_text_and_fields_read_the_files(self):
        d, s = self.fixtures(), self.sample_pdf()
        i = json.loads(self.tool("info", s, "--json").stdout)
        self.assertEqual((i["encrypted"], i["signed"], i["tagged"], i["language"]), (False, False, True, "en"))
        self.assertGreaterEqual(i["outline_entries"], 8)
        self.assertEqual(i["page_size_mm"], [210, 297])
        t = json.loads(self.tool("text", s, "--pages", "2", "--json").stdout)
        self.assertEqual([p["page"] for p in t["pages"]], [2])
        self.assertIn("Contents", t["pages"][0]["text"])
        f = json.loads(self.tool("fields", d / "form.pdf", "--json").stdout)["fields"]
        self.assertEqual([(x["name"], x["type"]) for x in f], [("full_name", "text"), ("agree", "checkbox"), ("sign_here", "signature")])
        self.assertIn("/Yes", f[1]["states"])
        self.assertEqual(json.loads(self.tool("info", d / "enc.pdf", "--json").stdout), {"file": str(d / "enc.pdf"), "encrypted": True})

    def test_merge_split_rotate_meta_leave_the_input_alone(self):
        d, s = self.fixtures(), self.sample_pdf()
        before = sha(s)
        from pypdf import PdfReader
        n = len(PdfReader(str(s)).pages)
        m = self.tmp / "merged.pdf"
        self.assertEqual(self.tool("merge", s, d / "plain.pdf", "--out", m).returncode, 0)
        self.assertEqual(len(PdfReader(str(m)).pages), n + 1)
        parts = self.tmp / "parts"
        r = self.tool("split", s, "--out", parts, "--ranges", "1-2,3")
        self.assertEqual(sorted(p.name for p in parts.glob("*.pdf")), ["sample-1-2.pdf", "sample-3.pdf"], r.stderr)
        self.assertEqual(len(PdfReader(str(parts / "sample-1-2.pdf")).pages), 2)
        rot = self.tmp / "rot.pdf"
        self.assertEqual(self.tool("rotate", s, "--out", rot, "--degrees", "90", "--pages", "1").returncode, 0)
        self.assertEqual([p.get("/Rotate", 0) for p in PdfReader(str(rot)).pages][:2], [90, 0])
        meta = self.tmp / "meta.pdf"
        self.assertEqual(self.tool("meta", s, "--out", meta, "--title", "T2", "--author", "Acme").returncode, 0)
        self.assertEqual(dict(PdfReader(str(meta)).metadata)["/Title"], "T2")
        self.assertEqual(sha(s), before, "the input is never edited")
        self.assertEqual(self.tool("rotate", s, "--out", s, "--degrees", "90").returncode, 2, "--out must differ from the input")

    def test_scrub_removes_properties_keeps_the_label_and_lists_what_it_keeps(self):
        d = self.fixtures()
        out = self.tmp / "scrubbed.pdf"
        r = self.tool("scrub", d / "label.pdf", "--out", out, "--json")
        j = json.loads(r.stdout)
        self.assertEqual((r.returncode, j["ok"]), (0, True), r.stderr)
        self.assertEqual(sorted(j["removed"]), ["Author", "Producer"])
        self.assertIn("MSIP_Label_x_Enabled", j["kept"])
        self.assertEqual(j["left_over"], [])
        s = self.sample_pdf()
        res = json.loads(self.tool("scrub", s, "--out", self.tmp / "s2.pdf", "--json").stdout)
        self.assertEqual(res["warnings"], [], "a report's own links are not a warning")
        self.assertFalse(Path(self.tmp / "s2.pdf").read_bytes().count(b"HeadlessChrome"))

    def test_fill_writes_a_copy_with_the_values_and_never_a_signature(self):
        d = self.fixtures()
        src, out = d / "form.pdf", self.tmp / "filled.pdf"
        before = sha(src)
        r = self.tool("fill", src, "--out", out, "--set", "full_name=Pat Example", "--set", "agree=yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("never signs", r.stdout)
        self.assertEqual(sha(src), before)
        from pypdf import PdfReader
        got = {k: str(v.get("/V")) for k, v in PdfReader(str(out)).get_fields().items()}
        self.assertEqual((got["full_name"], got["agree"], got["sign_here"]), ("Pat Example", "/Yes", "None"))
        self.assertTrue(PdfReader(str(out)).trailer["/Root"]["/AcroForm"].get("/NeedAppearances"))
        for bad, why in (("sign_here=Pat", "signature"), ("nope=1", "no such field")):
            r = self.tool("fill", src, "--out", self.tmp / "x.pdf", "--set", bad)
            self.assertEqual(r.returncode, 2, bad)
            self.assertIn(why, r.stderr)
        self.assertFalse((self.tmp / "x.pdf").exists())
        self.assertEqual(self.tool("fill", src, "--out", src, "--set", "full_name=A").returncode, 2)

    def test_the_filled_value_shows_when_the_page_is_rendered_with_forms(self):
        import pypdfium2 as pdfium
        d = self.fixtures()
        out = self.tmp / "filled2.pdf"
        self.assertEqual(self.tool("fill", d / "form.pdf", "--out", out, "--set", "full_name=Pat Example", "--set", "agree=yes").returncode, 0)

        def ink(path):
            doc = pdfium.PdfDocument(str(path))
            doc.init_forms()
            img = doc[0].render(scale=1, may_draw_forms=True).to_pil().convert("L")
            doc.close()
            return sum(img.histogram()[:200])
        self.assertGreater(ink(out), ink(d / "form.pdf"), "the copy shows what was typed in")

    def test_signed_and_encrypted_files_are_refused_by_every_command_that_writes(self):
        d = self.fixtures()
        for name, why in (("signed", "signature"), ("enc", "encrypted")):
            src = d / f"{name}.pdf"
            for i, args in enumerate((("rotate", src, "--out", None, "--degrees", "90"), ("split", src, "--out", None),
                                      ("meta", src, "--out", None, "--title", "T"), ("scrub", src, "--out", None),
                                      ("fill", src, "--out", None, "--set", "full_name=A"), ("stamp", src, "--out", None, "--text", "X"),
                                      ("merge", src, d / "plain.pdf", "--out", None))):
                out = self.tmp / f"refused-{name}-{i}.pdf"
                r = self.tool(*[out if a is None else a for a in args])
                self.assertEqual(r.returncode, 2, (name, args[0], r.stderr))
                self.assertIn(why, r.stderr)
                self.assertFalse(out.exists(), f"{args[0]} must write nothing for a {name} file")
        self.assertEqual(json.loads(self.tool("info", d / "signed.pdf", "--json").stdout)["signed"], True)
        self.assertEqual(self.tool("fields", d / "enc.pdf").returncode, 2)

    def test_stamp_draws_text_with_edge_and_keeps_every_font_embedded(self):
        s = self.sample_pdf()
        out = self.tmp / "stamped.pdf"
        r = self.tool("stamp", s, "--out", out, "--text", "DRAFT", "--pages", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        texts = self.page_texts(out)
        self.assertIn("DRAFT", texts[2])
        self.assertNotIn("DRAFT", texts[3])
        code, rep = self.check(out, "--footer", "none")
        self.assertTrue(rep["checks"]["fonts"]["ok"], rep["checks"]["fonts"])


# ================================================================================================ styles and the interpreter hand-over
HTML_PLAIN = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Plain page</title></head><body>
<h1>Alpha</h1><p>First section text.</p><h2>Detail</h2><p>More.</p><h1>Beta</h1><p>Second section text.</p>
<table><thead><tr><th>Key</th><th>Value</th></tr></thead><tbody><tr><td>One</td><td>1</td></tr><tr><td>Two</td><td>2</td></tr></tbody></table></body></html>"""
MEMO_MD = "---\ntitle: Status memo\nauthor: Acme Operations\n---\n# Status memo\n\n| To | Team |\n|---|---|\n| From | Operations |\n\nThe work is on track.\n"


class Styles(Base):
    def setUp(self):
        self.need_edge()
        self.need_libs()

    def test_html_gets_the_kit_stylesheet_and_a_contents_page_on_request(self):
        out = self.tmp / "styled.pdf"
        r, res = self.build(self.html("styled.html", HTML_PLAIN), out, "--style", "report", "--toc")
        self.assertEqual(r.returncode, 0, r.stderr + str(res and res["check"]["defects"]))
        c = res["check"]["checks"]
        self.assertEqual((c["footer"]["mode"], c["footer"]["bad"]), ("required", []), "the kit CSS carries the Page N of M box")
        self.assertEqual((c["toc"]["entries"], c["toc"]["wrong"]), (3, []))
        self.assertEqual(c["tables"]["rows_checked"], 2)

    def test_html_with_a_contents_list_but_no_style_still_reads_and_checks_right(self):
        paged = HTML_PLAIN.replace("</head>", "<style>h1 { break-before: page; }</style></head>")
        for name, html in (("one-page", HTML_PLAIN), ("paged", paged)):
            r, res = self.build(self.html(f"toc-{name}.html", html), self.tmp / f"toc-{name}.pdf", "--toc")
            self.assertEqual(r.returncode, 0, name + r.stderr + str(res and res["check"]["defects"]))
            toc = res["check"]["checks"]["toc"]
            self.assertEqual((toc["ok"], toc["entries"], toc["wrong"]), (True, 3, []), name)
            first = self.page_texts(self.tmp / f"toc-{name}.pdf")[0]
            self.assertIn("Contents", first)
            self.assertNotRegex(first, r"[A-Za-z]\d", f"{name}: the page numbers do not run into the titles")
            self.assertNotRegex(first, r"(?m)^\d\. ", f"{name}: no list markers in front of the entries")
            nums = [int(n) for n in re.findall(r"(?m)^(\d+)$", first.split("Contents", 1)[1].split("First section")[0])]
            self.assertEqual(len(nums), 3, name)
            if name == "paged":
                self.assertEqual(nums[-1], res["check"]["pages"], "Beta is on the last page")

    def test_html_without_a_style_is_left_alone_and_a_memo_has_no_cover(self):
        out = self.tmp / "plain.pdf"
        r, res = self.build(self.html("plain-page.html", HTML_PLAIN), out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((res["check"]["checks"]["footer"]["mode"], res["check"]["checks"]["footer"]["numbered"]), ("none", 0),
                         "no footer is invented for a page that did not ask for one")
        memo = self.tmp / "memo.pdf"
        r, res = self.build(self.html("memo.md", MEMO_MD), memo, "--style", "memo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(res["check"]["pages"], 1)
        self.assertEqual(res["check"]["checks"]["footer"]["numbered"], 1, "Page 1 of 1: a memo has no cover to skip")


class Handover(Base):
    def test_a_missing_package_hands_the_command_to_the_knowledge_python_once(self):
        cfg = self.tmp / "cfg-handover"
        (cfg / "workbench").mkdir(parents=True)
        fake = self.tmp / ("fake-python.cmd" if os.name == "nt" else "fake-python.sh")
        log = self.tmp / "handover.log"
        fake.write_text((f'@echo off\r\necho %WB_PDF_REEXEC% %* > "{log}"\r\nexit /b 7\r\n') if os.name == "nt"
                        else f'#!/bin/sh\necho "$WB_PDF_REEXEC $@" > "{log}"\nexit 7\n', encoding="utf-8")
        fake.chmod(0o755)
        (cfg / "workbench" / "config.json").write_text(json.dumps({"knowledge_python": str(fake)}), encoding="utf-8")
        stubs = self.tmp / "stubs-handover"
        (stubs / "pypdf").mkdir(parents=True, exist_ok=True)
        (stubs / "pypdf" / "__init__.py").write_text(STUB, encoding="utf-8")
        env = {**self.env, "CLAUDE_CONFIG_DIR": str(cfg), "PYTHONPATH": str(stubs)}
        r = self.run_py(CHECK, self.tmp / "none.pdf", env=env)
        self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
        self.assertTrue(log.read_text(encoding="utf-8").startswith("1 "), "the child is told it is the hand-over, so it cannot loop")
        self.assertIn("check_pdf.py", log.read_text(encoding="utf-8"))
        env["WB_PDF_REEXEC"] = "1"
        self.assertEqual(self.run_py(CHECK, self.tmp / "none.pdf", env=env).returncode, 2, "already handed over: no second hop")


class NoPypdf(Base):
    """A python with no pypdf at all (a fresh empty venv, run with -I): every command ends in one REFUSED line, never a traceback."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        venv = cls.tmp / "empty-venv"
        r = subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        cls.py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        cls.pdf = cls.tmp / "np-plain.pdf"
        cls.pdf.write_bytes(pdfgen.plain_pdf())
        cls.out = cls.tmp / "np-out"

    def test_the_empty_python_really_lacks_pypdf(self):
        r = subprocess.run([str(self.py), "-I", "-c", "import pypdf"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)

    def test_every_pdf_tools_command_names_the_missing_package_in_one_line(self):
        cmds = {"info": ["info", self.pdf], "text": ["text", self.pdf], "fields": ["fields", self.pdf],
                "merge": ["merge", self.pdf, self.pdf, "--out", self.out / "m.pdf"], "split": ["split", self.pdf, "--out", self.out / "parts"],
                "rotate": ["rotate", self.pdf, "--out", self.out / "r.pdf", "--degrees", "90"],
                "stamp": ["stamp", self.pdf, "--out", self.out / "s.pdf", "--text", "X"],
                "meta": ["meta", self.pdf, "--out", self.out / "t.pdf", "--title", "T"],
                "scrub": ["scrub", self.pdf, "--out", self.out / "c.pdf"],
                "fill": ["fill", self.pdf, "--out", self.out / "f.pdf", "--set", "a=b"]}
        self.assertEqual(sorted(cmds), sorted(["info", "text", "fields", "merge", "split", "rotate", "stamp", "meta", "scrub", "fill"]))
        for name, args in cmds.items():
            r = subprocess.run([str(self.py), "-I", TOOLS, *map(str, args)], capture_output=True, text=True, encoding="utf-8", env=ENV)
            self.assertEqual(r.returncode, 2, (name, r.stderr))
            self.assertRegex(r.stderr, r"^REFUSED: pypdf (?:and pypdfium2 are|is) not installed: ", (name, r.stderr))
            self.assertEqual(len(r.stderr.strip().splitlines()), 1, (name, r.stderr))
            self.assertNotIn("Traceback", r.stderr)
        self.assertFalse(self.out.exists(), "nothing was written")

    def test_check_pdf_and_build_pdf_name_it_too(self):
        r = subprocess.run([str(self.py), "-I", CHECK, str(self.pdf)], capture_output=True, text=True, encoding="utf-8", env=ENV)
        self.assertEqual((r.returncode, "pypdf is not installed" in r.stdout, "Traceback" in r.stderr), (2, True, False))
        r = subprocess.run([str(self.py), "-I", BUILD, str(self.tmp / "np.md"), "--out", str(self.tmp / "np.pdf")], capture_output=True, text=True,
                           encoding="utf-8", env=ENV)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)


# ================================================================================================ stdlib-only path
STUB = 'raise ImportError("blocked for the stdlib-path test", name=__name__)\n'
HTML_TOC = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Plain build</title><meta name="author" content="Acme"></head>
<body><h1>One</h1><p>Text.</p><h1>Two</h1><p>More text.</p></body></html>"""


class StdlibPath(Base):
    """A python without pypdf, Markdown, pypdfium2 and Pillow still turns HTML into a PDF and says what it skipped."""

    def stub_env(self):
        stubs = self.tmp / "stubs"
        for m in ("pypdf", "markdown", "pypdfium2", "PIL"):
            (stubs / m).mkdir(parents=True, exist_ok=True)
            (stubs / m / "__init__.py").write_text(STUB, encoding="utf-8")
        return {**self.env, "PYTHONPATH": str(stubs)}

    def test_html_builds_with_the_one_line_notices(self):
        self.need_edge()
        out = self.tmp / "plain.pdf"
        r = self.run_py("-S", BUILD, self.html("plain.html", HTML_TOC), "--out", out, "--toc", env=self.stub_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        raw = out.read_bytes()
        self.assertTrue(raw.startswith(b"%PDF-") and b"%%EOF" in raw[-1024:])
        notes = [x for x in r.stderr.splitlines() if x.startswith("NOTE:")]
        self.assertEqual(len(notes), 2, r.stderr)
        self.assertTrue(any("pypdfium2" in n and "page numbers" in n for n in notes), notes)
        self.assertTrue(any("pypdf" in n and "blanked in place" in n for n in notes), notes)
        self.assertNotIn("Traceback", r.stderr)
        self.assertNotIn(b"HeadlessChrome", raw)
        self.assertNotIn(b"Skia/PDF", raw)

    def test_markdown_without_the_package_is_one_clear_line_not_a_traceback(self):
        src = self.html("doc.md", "# Title\n\nText.\n")
        r = self.run_py(BUILD, src, "--out", self.tmp / "m.pdf", env=self.stub_env())
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stderr.strip(), "BUILD FAILED: Markdown input needs the Markdown package: run setup, or give HTML")

    def test_the_other_scripts_name_the_missing_package(self):
        env = self.stub_env()
        r = self.run_py(CHECK, self.html("a.pdf", "%PDF-1.4\n"), env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("pypdf is not installed", r.stdout)
        r = self.run_py(TOOLS, "info", self.html("b.pdf", "%PDF-1.4\n"), env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("pypdf is not installed", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


# ================================================================================================ build pieces, no Edge
class Pieces(Base):
    def test_the_edge_flags_are_the_tested_set_and_never_weaken_the_sandbox(self):
        flags = " ".join(bp.FLAGS)
        for want in ("--headless=new", "--no-pdf-header-footer", "--generate-pdf-document-outline", "--disable-gpu"):
            self.assertIn(want, flags)
        for never in ("--no-sandbox", "--remote-debugging", "--allow-file-access", "--disable-web-security"):
            self.assertNotIn(never, flags)
        self.assertNotIn("--no-sandbox", Path(BUILD).read_text(encoding="utf-8"))

    def test_the_page_may_not_call_out(self):
        self.assertIn("default-src 'none'", bp.CSP)
        self.assertNotIn("http", bp.CSP)
        doc = bp.inject_head("<html><head><title>T</title></head><body></body></html>", "<meta csp>")
        self.assertLess(doc.index("<meta csp>"), doc.index("<title>"), "the policy comes first in <head>")

    def test_missing_edge_and_a_blocked_headless_policy_give_the_fallback_not_a_download(self):
        with mock.patch.object(bp, "find_edge", return_value=None):
            with self.assertRaises(bp.BuildError) as e:
                bp.print_to_pdf(self.tmp / "x.html", self.tmp)
        self.assertIn("Ctrl+P", str(e.exception))
        self.assertIn("Nothing is downloaded", str(e.exception))
        with mock.patch.object(bp, "find_edge", return_value="msedge.exe"), mock.patch.object(bp, "headless_blocked", return_value=True):
            with self.assertRaises(bp.BuildError) as e:
                bp.print_to_pdf(self.tmp / "x.html", self.tmp)
        self.assertIn("D23", str(e.exception))
        self.assertIn("Ctrl+P", str(e.exception))

    def test_front_matter_headings_ids_and_contents_markup(self):
        meta, body = bp.front_matter("---\ntitle: \"A: b\"\ncover: yes\n---\n# H\n")
        self.assertEqual((meta, body), ({"title": "A: b", "cover": "yes"}, "# H\n"))
        doc, entries = bp.prep_headings('<section class="cover"><h1>Cover</h1></section><h1>One</h1><h2 id="x">Two</h2><h3>Three</h3><h1>One</h1>')
        self.assertEqual([(l, i, t) for l, i, t in entries], [(1, "one", "One"), (2, "x", "Two"), (1, "one-2", "One")])
        nav = bp.place_toc(doc, entries, {"one": 3, "x": 4, "one-2": 10})
        self.assertIn('<a href="#x">', nav)
        self.assertEqual(re.findall(r'class="n">(\d+)<', nav), ["3", "4", "10"])
        self.assertIn("00", bp.place_toc(doc, entries).split("</nav>")[0], "pass one uses fixed-width placeholders")
        self.assertLess(nav.index("</section>"), nav.index("<nav"), "the contents list follows the cover")

    def test_column_widths_follow_the_text_with_a_floor_and_a_cap(self):
        rows = [[2, 4, 5, 6, 5], [5, 13, 6, 4, 3], [5, 93, 6, 4, 3]]       # ID, Task (long), Owner, Status, Hours
        w = bp.column_widths(rows)
        self.assertAlmostEqual(sum(w), 100.0)
        self.assertGreater(w[1], 3 * max(w[0], w[2], w[3], w[4]), "the long-text column takes the slack")
        self.assertGreater(w[3], w[0], "a header or value longer than another column's gets more room")
        self.assertEqual(bp.column_widths([[10, 10], [10, 10]]), [50.0, 50.0], "equal text, equal columns")
        many = bp.column_widths([[1] * 11 + [60]])
        self.assertTrue(all(abs(x - 6.0) < 1e-9 for x in many[:11]) and abs(sum(many) - 100.0) < 1e-9, "no column below the floor")
        huge, lopsided = [[200] * 2], [[200] + [10]]
        self.assertEqual(bp.column_widths(huge), [50.0, 50.0], "the cap stops one huge cell from starving its neighbour")
        self.assertGreater(bp.column_widths(lopsided)[0], bp.column_widths(lopsided)[1])
        out = bp.balance_tables("<table><thead><tr><th>A</th><th>B</th></tr></thead><tr><td>x</td><td>" + "y" * 40 + "</td></tr></table>")
        self.assertIn('class="fixed"', out)
        self.assertEqual(len(re.findall(r"<col ", out)), 2)
        self.assertEqual(bp.balance_tables(out), out, "a table that already has a colgroup is left alone")

    def test_numbers_come_from_the_bookmarks_even_when_edge_doubles_a_title(self):
        entries = [(1, "a", "Summary"), (1, "b", "Results"), (1, "c", "Results")]
        outline = [("SummarySummary", 3), ("Results", 3), ("Other", 4), ("Results", 6)]
        self.assertEqual(bp.numbers_for(entries, outline), {"a": 3, "b": 3, "c": 6})
        with self.assertRaises(bp.BuildError):
            bp.numbers_for([(1, "z", "Missing")], outline)

    def test_a_doubled_bookmark_title_is_given_its_single_title_back(self):
        self.need(ck.have("pypdf"), "pypdf")
        import io
        from pypdf import PdfReader, PdfWriter
        w = PdfWriter(clone_from=io.BytesIO(pdfgen.plain_pdf()))
        w.add_outline_item("SummarySummary", 0)
        w.add_outline_item("Results", 0)
        bp.undouble_outline(w, ["Summary", "Results", "Task log"])
        buf = io.BytesIO()
        w.write(buf)
        self.assertEqual(ck.outline_titles(PdfReader(io.BytesIO(buf.getvalue())).outline), ["Summary", "Results"])

    def test_relative_assets_are_made_absolute_but_in_page_links_stay(self):
        out = bp.absolutize('<a href="#top">t</a><img src="img/a.png"><link href="s.css"><p style="background:url(bg.png)"></p>'
                            '<img src="data:image/png;base64,AAAA"><a href="https://example.com/x">x</a>', "file:///proj/")
        for want in ('href="#top"', 'src="file:///proj/img/a.png"', 'href="file:///proj/s.css"', "url(file:///proj/bg.png)",
                     'src="data:image/png;base64,AAAA"', 'href="https://example.com/x"'):
            self.assertIn(want, out)

    def test_css_strings_are_escaped_and_long_titles_are_cut(self):
        self.assertEqual(bp.css_str('a"b\\c<d'), 'a\\"b\\\\c\\3c d')
        self.assertTrue(bp.css_str("x" * 200).endswith("…") and len(bp.css_str("x" * 200)) == 70)

    def test_blanking_creator_and_producer_in_place_keeps_every_offset(self):
        raw = pdfgen.plain_pdf(b"<< /Title (T) /Creator (Mozilla\\(x\\) HeadlessChrome) /Producer (Skia/PDF m1) >>")
        out = bp.INFO_STR.sub(lambda m: m.group(1) + b" " * len(m.group(2)) + m.group(3), raw)
        self.assertEqual(len(out), len(raw))
        self.assertNotIn(b"HeadlessChrome", out)
        self.assertIn(b"/Title (T)", out)

    def test_markdown_becomes_the_report_template_with_a_cover_only_when_asked(self):
        self.need(ck.have("markdown"), "the Markdown package")
        import argparse
        a = argparse.Namespace(page="Letter", title=None, style=None, cover=False, author=None, subject=None)
        src = self.html("t.md", "---\nsubtitle: Sub\nclassification: Internal\n---\n# Title\n\nBody.\n")
        doc, title, author, subject = bp.compose(src, a, [])
        self.assertEqual(title, "Title")
        self.assertNotIn('class="cover"', doc)
        self.assertIn("size: Letter", doc)
        self.assertIn("--page-h: 278mm", doc)
        a.cover = True
        doc, *_ = bp.compose(src, a, [])
        self.assertIn('class="cover"', doc)
        self.assertEqual(doc.count("<h1>Title</h1>"), 1, "the cover carries the title; it is not repeated as the first heading")
        self.assertNotRegex(doc, r"\$(?:lang|title|author|css|page|page_h|run_left|run_right|cover_rest|body)\b")


# ================================================================================================ licences and layout
BANNED_IMPORTS = {"fitz", "pymupdf", "pymupdf4llm", "jinja2", "fpdf", "pikepdf", "weasyprint"}
LICENCE_OK = {"pypdf": "BSD-3-Clause", "markdown": "BSD-3-Clause"}
INSTALLED_LICENCE = {"pypdf": ("BSD-3-Clause",), "Markdown": ("BSD-3-Clause",), "pypdfium2": ("BSD-3-Clause", "Apache-2.0"), "pillow": ("MIT-CMU", "HPND", "MIT")}


class Licence(Base):
    def test_requirements_name_only_allowlisted_permissive_packages_with_exact_pins(self):
        lines = [x.strip() for x in (SKILL / "requirements.txt").read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")]
        names = {re.fullmatch(r"([A-Za-z0-9_.-]+)==(\d+\.\d+(?:\.\d+)?)", x).group(1).lower() for x in lines}
        self.assertEqual(names, set(LICENCE_OK))
        self.assertEqual(len(lines), 2)

    def test_installed_metadata_licences_match(self):
        for pkg, ok in INSTALLED_LICENCE.items():
            try:
                md = metadata.metadata(pkg)
            except metadata.PackageNotFoundError:
                self.need(False, f"installed package {pkg}")
            text = " ".join(filter(None, [md.get("License-Expression"), md.get("License"), *(md.get_all("Classifier") or [])]))
            self.assertTrue(any(o.lower() in text.lower() for o in ok), f"{pkg}: {text[:80]!r} names none of {ok}")
        for pkg, lic in LICENCE_OK.items():
            self.assertEqual(metadata.metadata(pkg).get("License-Expression"), lic)

    def test_no_source_file_imports_an_avoided_library(self):
        seen = 0
        for f in SKILL.rglob("*.py"):
            seen += 1
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                for m in mods:
                    self.assertNotIn(m.split(".")[0].lower(), BANNED_IMPORTS, f"{f.name} imports {m}")
        self.assertGreaterEqual(seen, 5)

    def test_third_party_lists_the_new_packages(self):
        text = (KIT / "THIRD-PARTY.md").read_text(encoding="utf-8")
        for name in ("pypdf", "Markdown"):
            self.assertRegex(text, rf"\| {name} .*pdf-report.*BSD-3-Clause")


class Layout(Base):
    def test_the_skill_ships_its_files_and_stays_inside_the_description_budget(self):
        for rel in ("SKILL.md", "requirements.txt", "templates/report.html", "templates/report.css", "templates/memo.css",
                    "references/quality-bar.md", "references/edge-notes.md", "references/charts-svg.md", "references/forms.md"):
            self.assertTrue((SKILL / rel).is_file(), rel)
        head = (SKILL / "SKILL.md").read_text(encoding="utf-8").split("---")[1]
        desc = json.loads(re.search(r"^description: (\".*\")$", head, re.M).group(1))
        when = re.search(r"^when_to_use: \"(.*)\"$", head, re.M)
        when = when.group(1) if when else ""
        self.assertEqual(re.search(r"^name: (.+)$", head, re.M).group(1), "pdf-report")
        self.assertLessEqual(len(desc) + len(when), 220)
        self.assertLessEqual(len(when), 90)

    def test_the_forbidden_word_is_in_no_file_of_the_skill_or_its_guide(self):
        files = [f for f in SKILL.rglob("*") if f.is_file() and f.suffix in (".py", ".md", ".css", ".html", ".txt")]
        files.append(KIT / "docs" / "howto" / "57-make-a-report-pdf.md")
        for f in files:
            self.assertNotIn(BANNED_WORD, f.read_text(encoding="utf-8").lower(), str(f))

    def test_no_edge_build_number_or_dotted_quad_in_the_skill_files(self):
        for f in SKILL.rglob("*"):
            if f.is_file() and f.suffix in (".py", ".md", ".css", ".html", ".txt"):
                self.assertIsNone(re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", f.read_text(encoding="utf-8")), str(f))


if __name__ == "__main__":
    unittest.main()
