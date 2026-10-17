#!/usr/bin/env python3
"""check_pdf.py: preflight a finished PDF report. Reports defects; never edits the file.

  python check_pdf.py <x.pdf> [--expect-pages N] [--footer auto|required|none] [--outline auto|yes|no]
                      [--toc auto|yes|no] [--html SRC.html] [--max-mb 5] [--json]

Checks (each one has a negative fixture in scripts/tests):
  pages        page count equals --expect-pages
  blank_pages  a page with no ink in its content area (the full-height cover bug adds one)
  fonts        every font embedded (Type0 fonts are walked through DescendantFonts)
  outline      bookmarks exist when the document has headings (tagged-PDF headings, or --outline yes), none is written twice
               (an Edge quirk), and with --html every h1-h3 of the source is a bookmark
  footer       "Page N of M" reads the true N and M on every page after the first (--footer none: no footer is required, but one
               that is there must still be right)
  toc          the number printed on each contents line equals the page its link really points to
  links        every internal link resolves to a page
  metadata     Creator and Producer carry no browser fingerprint; Title is set; with --html it equals <title>
  remnants     no {{ }}, undefined, [object or ${ in the page text
  tables       with --html: a continuation page repeats the header row; no row is cut across a page boundary
Text-based checks need pypdfium2, blank pages also Pillow: without them the check is listed under "skipped", never passed.
Exit: 0 no defect, 1 at least one defect, 2 not checked (missing file, not a PDF, encrypted, pypdf missing).
--json: {"version","file","ok","pages","defects":[...],"notes":[...],"skipped":[{"check","reason"}],"checks":{name:{"ok",...}}}
Never PyMuPDF (AGPL-3.0). Only the standard library is imported at the top; the packages load when a check needs them.
"""
import argparse
import bisect
import importlib.util
import json
import os
import re
import subprocess
import sys
from html.parser import HTMLParser

SETUP = "run the workbench setup (it installs the pdf-report packages)"
BAD_CREATOR = re.compile(r"headless|chrome|edg/|skia|mozilla", re.I)
FOOT = re.compile(r"Page\s*(\d+)\s*of\s*(\d+)", re.I)
REMNANT = re.compile(r"\{\{|\}\}|\[object |\bundefined\b|\bNaN\b|\$\{")
TOC_TITLE = re.compile(r"^\s*(?:contents|table of contents)\s*$", re.I | re.M)
TOC_LINE = re.compile(r"^(.*\S)\s+(\d{1,4})$|^(.*[^\d\s])(\d{1,4})$")   # "Title 3", or "Title3" when the text layer drops the gap
INK_LEVEL = 235          # grey level below which a pixel counts as ink
BLANK_INK = 0.0005       # content-area ink fraction below which a page is blank


class NotChecked(Exception):
    """The file cannot be checked at all (exit 2)."""


_HAVE = {}


def have(*mods):
    """True when every module really imports (not just when a file with its name exists)."""
    for m in mods:
        if m not in _HAVE:
            try:
                importlib.import_module(m)
                _HAVE[m] = True
            except Exception:  # noqa: BLE001 - missing, broken or blocked: all mean "not usable here"
                _HAVE[m] = False
    return all(_HAVE[m] for m in mods)


def reexec_under_knowledge_python(modules):
    """A needed module is missing here and the workbench config names a knowledge_python: run the same command under it."""
    if os.environ.get("WB_PDF_REEXEC") == "1" or have(*modules):
        return
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    try:
        with open(os.path.join(home, "workbench", "config.json"), encoding="utf-8-sig") as f:
            py = json.load(f).get("knowledge_python")
    except (OSError, ValueError, AttributeError):
        return
    if py and os.path.isfile(py) and os.path.normcase(os.path.abspath(py)) != os.path.normcase(os.path.abspath(sys.executable)):
        sys.exit(subprocess.call([py, *sys.argv], env={**os.environ, "WB_PDF_REEXEC": "1"}))


def norm(s):
    return " ".join(str(s).split())


# ---------------------------------------------------------------------------------------------------------------- text
def scan_pages(path, ink=True):
    """[{"text", "ink"}] per page through pypdfium2 (ink needs Pillow). ink = fraction of dark pixels in the content area."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(path))
    out = []
    try:
        for i in range(len(doc)):
            page = doc[i]
            tp = page.get_textpage()
            row = {"text": tp.get_text_range().replace("\r\n", "\n"), "ink": None}
            tp.close()
            if ink:
                img = page.render(scale=0.4).to_pil().convert("L")
                w, h = img.size
                band = img.crop((0, int(h * 0.08), w, int(h * 0.9)))      # the header and footer bands do not count as content
                row["ink"] = sum(band.histogram()[:INK_LEVEL]) / float(band.size[0] * band.size[1])
            page.close()
            out.append(row)
    finally:
        doc.close()
    return out


def rect_texts(path, wanted):
    """{(page_index, rect): text} for link rectangles, read from the page text layer."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(path))
    out = {}
    try:
        for pi in sorted({p for p, _ in wanted}):
            page = doc[pi]
            tp = page.get_textpage()
            for p, rect in wanted:
                if p == pi:
                    x0, y0, x1, y1 = rect
                    out[(p, rect)] = norm(tp.get_text_bounded(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
            tp.close()
            page.close()
    finally:
        doc.close()
    return out


# ---------------------------------------------------------------------------------------------------------- pdf objects
def outline_titles(items, out=None):
    out = [] if out is None else out
    for it in items:
        if isinstance(it, list):
            outline_titles(it, out)
        else:
            out.append(norm(it.title))
    return out


def struct_headings(reader, cap=30000):
    """How many H1-H3 (or generic H) elements the tagged-PDF structure tree holds."""
    from pypdf.generic import IndirectObject
    try:
        root = reader.trailer["/Root"].get("/StructTreeRoot")
        stack, seen, n = [root.get_object().get("/K")] if root is not None else [], set(), 0
    except Exception:  # noqa: BLE001
        return 0
    while stack and cap > 0:
        cap -= 1
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
            continue
        if isinstance(node, IndirectObject):
            if node.idnum in seen:
                continue
            seen.add(node.idnum)
            node = node.get_object()
        if isinstance(node, dict):
            if node.get("/S") in ("/H", "/H1", "/H2", "/H3"):
                n += 1
            stack.append(node.get("/K"))
    return n


def font_report(reader):
    """[{"name","subtype","embedded"}] for every distinct font used by a page or a form XObject."""
    from pypdf.generic import IndirectObject
    seen, fonts, forms = set(), [], set()

    def descriptor(f):
        if f.get("/Subtype") == "/Type0":
            kids = f.get("/DescendantFonts")
            f = kids.get_object()[0].get_object() if kids else {}
        d = f.get("/FontDescriptor")
        return d.get_object() if d is not None else None

    def walk(res, depth):
        res = res.get_object() if res is not None else None
        if not res or depth > 4:
            return
        fd = res.get("/Font")
        for ref in (fd.get_object().values() if fd is not None else []):
            key = ref.idnum if isinstance(ref, IndirectObject) else id(ref)
            if key in seen:
                continue
            seen.add(key)
            f = ref.get_object()
            d = descriptor(f)
            embedded = f.get("/Subtype") == "/Type3" or (d is not None and any(k in d for k in ("/FontFile", "/FontFile2", "/FontFile3")))
            fonts.append({"name": str(f.get("/BaseFont", "?")), "subtype": str(f.get("/Subtype")), "embedded": bool(embedded)})
        xo = res.get("/XObject")
        for ref in (xo.get_object().values() if xo is not None else []):
            o = ref.get_object()
            key = ref.idnum if isinstance(ref, IndirectObject) else id(ref)
            if o.get("/Subtype") == "/Form" and key not in forms:
                forms.add(key)
                walk(o.get("/Resources"), depth + 1)

    for page in reader.pages:
        walk(page.get("/Resources"), 0)
    return fonts


def page_links(reader):
    """[(page_index, rect, dest_page|None|'external')] for every Link annotation."""
    ids = {p.indirect_reference.idnum: i for i, p in enumerate(reader.pages)}
    named = reader.named_destinations
    out = []

    def page_of(ref):
        ref = getattr(ref, "idnum", None)
        return ids.get(ref)

    for i, page in enumerate(reader.pages):
        for a in page.get("/Annots") or []:
            a = a.get_object()
            if a.get("/Subtype") != "/Link":
                continue
            d = a.get("/Dest")
            if d is None:
                act = a.get("/A")
                act = act.get_object() if act is not None else {}
                if act.get("/S") != "/GoTo":
                    out.append((i, None, "external"))
                    continue
                d = act.get("/D")
            d = d.get_object() if hasattr(d, "get_object") else d
            if isinstance(d, list):
                dest = page_of(d[0]) if d else None
            else:
                key = str(d)
                dd = named.get(key) or named.get(key if key.startswith("/") else "/" + key)
                dest = page_of(dd.page) if dd is not None else None
            rect = tuple(round(float(x), 2) for x in a.get("/Rect", []))
            out.append((i, rect or None, dest))
    return out


# --------------------------------------------------------------------------------------------------------- source html
class SourceHtml(HTMLParser):
    """Tables (header cells, body rows), headings and <title> of the source HTML, for the structure checks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.heads, self.title = [], [], ""
        self._t = None
        self._row = None
        self._cell = None
        self._head = None
        self._in_thead = False
        self._in_title = False
        self._title_seen = False

    def handle_starttag(self, tag, attrs):
        if tag == "title" and not self._title_seen:      # the first <title> only: an SVG <title> is not the document's
            self._in_title = self._title_seen = True
        elif tag in ("h1", "h2", "h3"):
            self._head = []
        elif tag == "table":
            self._t = {"head": [], "rows": []}
            self.tables.append(self._t)
        elif self._t is not None:
            if tag == "thead":
                self._in_thead = True
            elif tag == "tr":
                self._row = []
            elif tag in ("td", "th"):
                self._cell = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2", "h3") and self._head is not None:
            self.heads.append(norm("".join(self._head)))
            self._head = None
        elif tag == "table":
            self._t = None
        elif self._t is not None:
            if tag == "thead":
                self._in_thead = False
            elif tag in ("td", "th") and self._cell is not None and self._row is not None:
                self._row.append(norm("".join(self._cell)))
                self._cell = None
            elif tag == "tr" and self._row is not None:
                (self._t["head"] if self._in_thead else self._t["rows"]).append(self._row)
                self._row = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._head is not None:
            self._head.append(data)
        if self._cell is not None:
            self._cell.append(data)


def locate(texts):
    """(stream, starts): all page text as one normalised string and the offset where each page begins."""
    stream, starts = "", []
    for t in texts:
        starts.append(len(stream))
        stream += norm(t) + " \f "
    return stream, starts


def table_report(tables, texts):
    stream, starts = locate(texts)
    page_at = lambda pos: bisect.bisect_right(starts, pos) - 1   # noqa: E731
    res = {"found": len(tables), "rows_checked": 0, "rows_unmatched": 0, "continuation_pages": [], "header_missing_on": [], "split_rows": []}
    cursor = 0
    for ti, t in enumerate(tables):
        head = [c for c in (t["head"][0] if t["head"] else []) if c]
        pages = set()
        for ri, row in enumerate(t["rows"]):
            cells, pos, pgs, ok = [c for c in row if c], cursor, set(), True
            last = cursor
            for c in cells:      # a cell is found by its first and last words, so a cell cut by a page break is still seen
                p = stream.find(c[:24], pos)
                q = stream.find(c[-24:], p) if p >= 0 else -1
                if p < 0 or q < 0 or (pgs and p - last > 600):
                    ok = False
                    break
                pgs.update((page_at(p), page_at(q)))
                pos = last = q + len(c[-24:])
            if not ok or not cells:
                res["rows_unmatched"] += 1
                continue
            res["rows_checked"] += 1
            cursor = pos
            pages |= pgs
            if len(pgs) > 1:
                res["split_rows"].append({"table": ti, "row": ri, "pages": sorted(p + 1 for p in pgs), "text": " | ".join(cells)[:80]})
        if head and pages:
            for pg in sorted(pages)[1:]:
                res["continuation_pages"].append(pg + 1)
                chunk, at = norm(texts[pg]), 0
                for h in head:
                    at = chunk.find(h, at)
                    if at < 0:
                        res["header_missing_on"].append(pg + 1)
                        break
                    at += len(h)
    return res


# ------------------------------------------------------------------------------------------------------------- the check
def check(path, expect_pages=None, footer="auto", outline="auto", toc="auto", html=None, max_mb=5.0):
    """Run every check; returns the report dict (see the module docstring)."""
    if not have("pypdf"):
        raise NotChecked("pypdf is not installed, so the PDF cannot be checked: " + SETUP)
    from pypdf import PdfReader
    path = str(path)
    if not os.path.isfile(path):
        raise NotChecked(f"no such file: {path}")
    with open(path, "rb") as f:
        if f.read(5) != b"%PDF-":
            raise NotChecked("not a PDF (no %PDF- header)")
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise NotChecked("encrypted: not checked (ask the owner for an unprotected copy)")
        n = len(reader.pages)
    except NotChecked:
        raise
    except Exception as e:  # noqa: BLE001
        raise NotChecked(f"unreadable PDF ({type(e).__name__}: {e})")
    r = {"version": 1, "file": path, "ok": True, "pages": n, "size_kb": round(os.path.getsize(path) / 1024), "defects": [],
         "notes": [], "skipped": [], "checks": {}}
    src = SourceHtml()
    if html:
        src.feed(html)

    def done(name, ok, msg="", **info):
        r["checks"][name] = {"ok": bool(ok), **info}
        if not ok:
            r["defects"].append(f"{name}: {msg}")

    def run(name, fn):
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - a crashing check is a defect, never a pass
            done(name, False, f"could not run ({type(e).__name__}: {e})")

    def skip(name, reason):
        r["skipped"].append({"check": name, "reason": reason})

    pdfium = have("pypdfium2")
    pages = None
    if pdfium:
        try:
            pages = scan_pages(path, ink=have("PIL"))
        except Exception as e:  # noqa: BLE001
            raise NotChecked(f"pypdfium2 could not read the PDF ({type(e).__name__}: {e})")
    texts = [p["text"] for p in pages] if pages else None

    # pages
    if expect_pages is None:
        done("pages", True, count=n)
    else:
        done("pages", n == expect_pages, f"{n} pages, expected {expect_pages}", count=n, expected=expect_pages)

    # blank pages
    if pages and have("PIL"):
        blank = [i + 1 for i, p in enumerate(pages) if p["ink"] < BLANK_INK]
        done("blank_pages", not blank, f"blank page(s) {blank}: a cover as tall as the page, or a break after the last block", pages=blank)
    else:
        skip("blank_pages", "needs pypdfium2 and Pillow: " + SETUP)

    # fonts
    def c_fonts():
        fonts = font_report(reader)
        bad = sorted({f["name"] for f in fonts if not f["embedded"]})
        done("fonts", not bad, f"not embedded: {', '.join(bad)}", total=len(fonts), not_embedded=bad)
    run("fonts", c_fonts)

    # outline
    def c_outline():
        titles = outline_titles(reader.outline)
        heads = struct_headings(reader)
        want = outline == "yes" or (outline == "auto" and heads > 0 and n > 1)
        missing = [h for h in src.heads if norm(h).casefold() not in {t.casefold() for t in titles}] if html and outline != "no" else []
        doubled = [x for x in titles if len(x) >= 4 and len(x) % 2 == 0 and x[:len(x) // 2] == x[len(x) // 2:]]
        ok = (not want or bool(titles)) and not missing and not doubled
        msg = ("no bookmarks although the document has headings" if want and not titles else
               f"bookmark titles written twice {doubled[:3]}: a heading at the top of a page needs at least 1pt of top margin" if doubled else
               f"headings missing from the bookmarks: {missing[:5]}")
        done("outline", ok, msg, entries=len(titles), expected=bool(want), headings=heads, missing_titles=missing, doubled_titles=doubled)
    if outline != "no":
        run("outline", c_outline)

    # footer
    if texts is not None:
        def c_footer():
            found = {i: FOOT.findall(t)[-1] for i, t in enumerate(texts, 1) if FOOT.search(t)}
            mode = footer if footer != "auto" else ("required" if found else "none")
            bad = []
            for i in range(1, n + 1):
                if i in found:
                    a, b = int(found[i][0]), int(found[i][1])
                    if (a, b) != (i, n):
                        bad.append({"page": i, "reads": f"Page {a} of {b}", "should": f"Page {i} of {n}"})
                elif i >= 2 and mode == "required":
                    bad.append({"page": i, "reads": None, "should": f"Page {i} of {n}"})
            done("footer", not bad, f"wrong or missing 'Page N of M' on page(s) {[b['page'] for b in bad]}",
                 mode=mode, numbered=len(found), bad=bad)
        run("footer", c_footer)
    elif footer != "none":
        skip("footer", "needs pypdfium2: " + SETUP)

    # links and contents
    def c_links():
        links = page_links(reader)
        internal = [x for x in links if x[2] != "external"]
        broken = [{"page": p + 1} for p, _, d in internal if d is None]
        done("links", not broken, f"{len(broken)} internal link(s) point nowhere (page(s) {sorted({b['page'] for b in broken})})",
             internal=len(internal), external=len(links) - len(internal), broken=broken)
        if toc == "no":
            return
        if texts is None:
            skip("toc", "needs pypdfium2: " + SETUP)
            return
        tpage = next((i for i, t in enumerate(texts[:4]) if TOC_TITLE.search(t)), None)
        entries, wrong = [], []
        if tpage is not None:
            cand = [(p, rect, d) for p, rect, d in internal if p == tpage and isinstance(d, int) and rect]
            first = min((d for _, _, d in cand), default=None)
            last = None if first is None else max(tpage, first - 1)       # the contents run from its title to the page before its first target
            span = [x for x in internal if last is not None and tpage <= x[0] <= last and isinstance(x[2], int) and x[1]]
            got = rect_texts(path, [(p, rect) for p, rect, _ in span])
            for p, rect, d in span:
                m = TOC_LINE.match(got.get((p, rect), ""))
                if m:
                    title, printed = m.group(1) or m.group(3), int(m.group(2) or m.group(4))
                    entries.append(title)
                    if printed != d + 1:
                        wrong.append({"entry": title[:60], "printed": printed, "real": d + 1})
        if toc == "yes" and not entries:
            done("toc", False, "no contents page with numbered links was found", entries=0, wrong=[])
        elif entries or tpage is not None:
            done("toc", not wrong, f"contents number(s) differ from the real page: {wrong[:3]}", entries=len(entries), wrong=wrong)
    run("links", c_links)

    # metadata
    def c_meta():
        meta = {str(k): str(v) for k, v in (reader.metadata or {}).items()}
        leaks = [f"{k.lstrip('/')}: {v[:40]}" for k, v in meta.items() if k in ("/Creator", "/Producer", "/Author") and BAD_CREATOR.search(v)]
        title = meta.get("/Title", "")
        want = norm(src.title) if html and src.title.strip() else None
        ok = not leaks and bool(title.strip()) and (want is None or norm(title) == want)
        msg = f"browser fingerprint in {leaks}" if leaks else (f"Title {title!r} does not equal <title> {want!r}" if title.strip() else "no Title")
        done("metadata", ok, msg, title=title, creator=meta.get("/Creator", ""), producer=meta.get("/Producer", ""), leaks=leaks)
    run("metadata", c_meta)

    # text layer and remnants
    if texts is not None:
        def c_text():
            empty = [i + 1 for i, t in enumerate(texts) if not t.strip()]
            if len(empty) == len(texts):
                done("text_layer", False, "no page has a text layer (a scan or an image): text cannot be searched or read aloud", pages_without_text=empty)
            else:
                done("text_layer", True, pages_without_text=empty)
            hit = [i + 1 for i, t in enumerate(texts) if REMNANT.search(t)]
            done("remnants", not hit, f"template remnants ({{{{, undefined, [object) on page(s) {hit}", pages=hit)
        run("text_layer", c_text)
    else:
        skip("text_layer", "needs pypdfium2: " + SETUP)

    # tables against the source html
    if html and src.tables:
        if texts is None:
            skip("tables", "needs pypdfium2: " + SETUP)
        else:
            def c_tables():
                t = table_report(src.tables, texts)
                bad = t["split_rows"] or t["header_missing_on"]
                done("tables", not bad, f"split row(s) {[s['pages'] for s in t['split_rows']]}; header missing on page(s) {t['header_missing_on']}", **t)
            run("tables", c_tables)

    if r["size_kb"] > max_mb * 1024:
        r["notes"].append(f"{r['size_kb']} KB is over {max_mb:g} MB: downscale images before emailing")
    r["ok"] = not r["defects"]
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--expect-pages", type=int)
    ap.add_argument("--footer", choices=("auto", "required", "none"), default="auto")
    ap.add_argument("--outline", choices=("auto", "yes", "no"), default="auto")
    ap.add_argument("--toc", choices=("auto", "yes", "no"), default="auto")
    ap.add_argument("--html", help="the source HTML: adds the table, heading and <title> checks")
    ap.add_argument("--max-mb", type=float, default=5.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    reexec_under_knowledge_python(["pypdf", "pypdfium2", "PIL"])
    try:
        html = open(a.html, encoding="utf-8", errors="replace").read() if a.html else None
        r = check(a.pdf, a.expect_pages, a.footer, a.outline, a.toc, html, a.max_mb)
    except (NotChecked, OSError) as e:
        print(json.dumps({"version": 1, "file": a.pdf, "ok": False, "error": str(e)}) if a.json else f"NOT CHECKED: {e}")
        return 2
    if a.json:
        print(json.dumps(r, indent=1, ensure_ascii=False))
    else:
        for name, c in r["checks"].items():
            print(f"{'ok    ' if c['ok'] else 'DEFECT'} {name}")
        print("\n".join(f"DEFECT {d}" for d in r["defects"]))
        print("\n".join(f"skipped {s['check']}: {s['reason']}" for s in r["skipped"]))
        print("\n".join(f"note: {x}" for x in r["notes"]))
        print(f"# {r['pages']} page(s), {r['size_kb']} KB: {'clean' if r['ok'] else str(len(r['defects'])) + ' defect(s)'}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
