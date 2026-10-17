#!/usr/bin/env python3
"""build_pdf.py: HTML or Markdown to a polished PDF through Edge headless, then a preflight check.

  python build_pdf.py <in.html|in.md> --out <x.pdf> [--page A4|Letter] [--title T] [--toc]
                      [--style report|memo|none] [--cover] [--author A] [--subject S] [--png DIR] [--json]

The core path needs only Edge and the Python standard library. Markdown input needs the Markdown package; --toc page
numbers, the preflight check and --png need pypdfium2 (and Pillow); setting Title/Author/Subject needs pypdf. A missing
optional package prints one NOTE line naming it and the build carries on. Nothing is ever downloaded or installed here.

Edge runs with a fresh temporary profile, no sandbox switch changed, no debugging port, and the page gets a CSP meta tag
(default-src 'none'): it cannot call out, and scripts do not run. Assets must be local files or data: URIs.
Markdown front matter (--- block): title, subtitle, author, date, classification, subject, lang, cover (yes).
--style: report (Markdown default) and memo add the kit stylesheets; none (HTML default) leaves your CSS alone.
--toc adds a contents list and fills in the page numbers by building twice (target-counter() does not work in Edge).
Exit: 0 built, 1 built but the preflight found a defect, 2 not built. --json prints the preflight report on stdout.
"""
import argparse
import contextlib
import html as htmllib
import json
import os
import pathlib
import re
import shutil
import string
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_pdf as chk  # noqa: E402

TEMPLATES = HERE.parent / "templates"
RENDER = HERE.parents[1] / "office-render" / "scripts" / "render.py"
PAGE_H = {"A4": "296mm", "Letter": "278mm"}   # page height minus 1-2 mm: a cover as tall as the page adds a blank page
CSP = "default-src 'none'; img-src data: file:; style-src 'unsafe-inline' file:; font-src data: file:; form-action 'none'"
FLAGS = ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--no-pdf-header-footer",
         "--generate-pdf-document-outline"]
NO_EDGE = ("Edge (msedge.exe) was not found. Nothing is downloaded. Open the HTML in a browser and print it by hand: "
           "Ctrl+P, destination Save as PDF, switch off Headers and footers.")
BY_HAND = "Meanwhile print by hand: open the HTML in Edge, Ctrl+P, destination Save as PDF, switch off Headers and footers."
NO_HEADLESS = ("Edge's policy HeadlessModeEnabled is off on this machine, so it cannot print without a window. The Day-1 "
               "headless-Edge check (D23) shows the same; ask through guide 03. " + BY_HAND)
TIMED_OUT = "Edge did not make the PDF in {t} s. If your organisation turned headless mode off, the Day-1 headless-Edge check (D23) shows it: ask through guide 03. " + BY_HAND


class BuildError(Exception):
    pass


def fwd(p):
    return str(p).replace("\\", "/")


def esc(s):
    return htmllib.escape(str(s), quote=True)


def css_str(s, limit=70):
    s = " ".join(str(s).split())
    s = s if len(s) <= limit else s[:limit - 1].rstrip() + "…"
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("<", "\\3c ")


# ----------------------------------------------------------------------------------------------------------------- Edge
def find_edge():
    if os.name != "nt":
        return shutil.which("microsoft-edge") or shutil.which("msedge")
    for var in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(var)
        p = pathlib.Path(base, "Microsoft", "Edge", "Application", "msedge.exe") if base else None
        if p and p.is_file():
            return str(p)
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe") as k:
                    p = winreg.QueryValueEx(k, "")[0]
                    if p and os.path.isfile(p):
                        return p
            except OSError:
                pass
    except ImportError:
        pass
    return None


def headless_blocked():
    """True when the Edge policy HeadlessModeEnabled is 0 for the machine or the user."""
    try:
        import winreg
    except ImportError:
        return False
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, r"SOFTWARE\Policies\Microsoft\Edge") as k:
                if winreg.QueryValueEx(k, "HeadlessModeEnabled")[0] == 0:
                    return True
        except OSError:
            pass
    return False


def kill_run(marker):
    """Stop the Edge processes whose command line holds this run's own temp folder name, and no others."""
    if os.name != "nt":
        return
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $_.CommandLine -like ('*' + $env:WB_MARK + '*') } "
          "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env={**os.environ, "WB_MARK": marker},
                   capture_output=True, timeout=60)


def stable_pdf(path, last):
    """(done, size): the file is a whole PDF and its size did not change since the last poll."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(5)
            f.seek(max(0, size - 1024))
            tail = f.read()
    except OSError:
        return False, -1
    return size > 0 and size == last and head == b"%PDF-" and b"%%EOF" in tail, size


@contextlib.contextmanager
def work_dir():
    """A fresh temp folder per run (the page, the Edge profile, the output); removed afterwards, and only this run's own Edge
    processes are stopped if they still hold it."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="wb-pdf-"))
    try:
        yield work
    finally:
        for _ in range(3):
            shutil.rmtree(work, ignore_errors=True)
            if not work.exists():
                break
            kill_run(work.name)
            time.sleep(1)


def render_html(doc_html, timeout=60):
    """PDF bytes for one HTML string (used for stamps)."""
    with work_dir() as work:
        (work / "doc.html").write_text(inject_head(doc_html, f'<meta http-equiv="Content-Security-Policy" content="{esc(CSP)}">'), encoding="utf-8")
        return print_to_pdf(work / "doc.html", work, timeout).read_bytes()


def print_to_pdf(doc_path, work, timeout=60):
    """Render the HTML file with Edge into a new PDF under `work` and return its path. The launcher can return before the PDF exists,
    so poll for a whole, stable file."""
    edge = find_edge()
    if not edge:
        raise BuildError(NO_EDGE)
    if headless_blocked():
        raise BuildError(NO_HEADLESS)
    tag = time.time_ns()     # a fresh profile and output name per print: a profile still shutting down would take the next launch over
    out = pathlib.Path(work, f"out-{tag}.pdf")
    cmd = [edge, *FLAGS, f"--user-data-dir={fwd(pathlib.Path(work, f'profile-{tag}'))}", f"--print-to-pdf={fwd(out)}", pathlib.Path(doc_path).as_uri()]
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    end, last = time.time() + timeout, -1
    while time.time() < end:
        done, last = stable_pdf(out, last)
        if done:
            return out
        time.sleep(0.4)
    raise BuildError(TIMED_OUT.format(t=timeout))


# ------------------------------------------------------------------------------------------------------------ html parts
def front_matter(text):
    m = re.match(r"﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep and re.fullmatch(r"[a-z_]+", k.strip().lower()):
            meta[k.strip().lower()] = v.strip().strip("\"'")
    return meta, text[m.end():]


def md_to_html(text):
    try:
        import markdown
    except ImportError:
        raise BuildError("Markdown input needs the Markdown package: run setup, or give HTML")
    return balance_tables(markdown.markdown(text, extensions=["tables", "fenced_code", "footnotes", "attr_list", "sane_lists"], output_format="html"))


def inject_head(doc, snippet):
    """Insert snippet as the first thing inside <head> (so the page's own styles, which come later, win)."""
    m = re.search(r"<head\b[^>]*>", doc, re.I)
    if m:
        return doc[:m.end()] + "\n" + snippet + doc[m.end():]
    m = re.search(r"<html\b[^>]*>", doc, re.I)
    if m:
        return doc[:m.end()] + "\n<head>" + snippet + "</head>" + doc[m.end():]
    return "<!doctype html><html><head><meta charset=\"utf-8\">" + snippet + "</head><body>" + doc + "</body></html>"


REL_ATTR = re.compile(r"""(\b(?:src|href|poster)\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
REL_CSS = re.compile(r"""url\(\s*(["']?)([^)"']+)\1\s*\)""", re.I)
ABSOLUTE = re.compile(r"(?:#|[a-z][a-z0-9+.-]*:)", re.I)


def absolutize(doc, base):
    """Make relative src/href/url() values absolute against the source folder. Not <base href>: with it, "#section" links
    stop being in-page links, so the contents entries and the bookmarks would point at a file instead of a page."""
    from urllib.parse import urljoin
    fix_attr = lambda m: m.group(0) if not m.group(3).strip() or ABSOLUTE.match(m.group(3).strip()) \
        else f"{m.group(1)}{m.group(2)}{urljoin(base, m.group(3).strip())}{m.group(2)}"   # noqa: E731
    fix_css = lambda m: m.group(0) if ABSOLUTE.match(m.group(2).strip()) \
        else f"url({m.group(1)}{urljoin(base, m.group(2).strip())}{m.group(1)})"          # noqa: E731
    return REL_CSS.sub(fix_css, REL_ATTR.sub(fix_attr, doc))


TABLE = re.compile(r"<table\b([^>]*)>(.*?)</table>", re.S | re.I)
ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", re.S | re.I)


def column_widths(lengths, cap=60, floor=6.0):
    """Percent width per column from the text in it. lengths[r][c] = characters in that cell (header row included). A column's measure
    is its longest text, capped at `cap` characters, plus a padding allowance; widths follow the measures, so a long-text column takes
    the slack and a short or numeric one stays narrow. No column goes below `floor` percent; the others give up the difference."""
    n = max(len(r) for r in lengths)
    w = [min(max((r[i] for r in lengths if i < len(r)), default=1), cap) + 3 for i in range(n)]
    pct, floor = [100.0 * x / sum(w) for x in w], min(floor, 100.0 / n)
    for _ in range(n):
        small = {i for i, v in enumerate(pct) if v < floor}
        big = [i for i in range(n) if i not in small]
        if not small or not big:
            break
        scale = (100.0 - floor * len(small)) / sum(pct[i] for i in big)
        pct = [floor if i in small else v * scale for i, v in enumerate(pct)]
    return pct


def balance_tables(doc):
    """Give every table without a <colgroup> fixed layout and content-aware column widths (see column_widths), so a short column keeps
    its words on one line and the long-text column takes the slack. Auto layout shrinks every column when the table is over-wide, which
    wraps "Team B" into two lines; equal widths wrap the long column to many lines while the others sit empty."""
    def fix(m):
        attrs, inner = m.group(1), m.group(2)
        rows = [[len(plain(c)) for c in CELL.findall(r)] for r in ROW.findall(inner)]
        if max((len(r) for r in rows), default=0) < 2 or "<colgroup" in inner.lower():
            return m.group(0)
        cols = "<colgroup>" + "".join(f'<col style="width:{x:.1f}%">' for x in column_widths(rows)) + "</colgroup>"
        attrs = re.sub(r"""\bclass=(["'])""", r"class=\1fixed ", attrs, count=1) if re.search(r"\bclass=", attrs) else attrs + ' class="fixed"'
        return f"<table{attrs}>{cols}{inner}</table>"
    return TABLE.sub(fix, doc)


def doc_title(doc):
    m = re.search(r"<title[^>]*>(.*?)</title>", doc, re.I | re.S)
    return " ".join(htmllib.unescape(m.group(1)).split()) if m else ""


def set_title(doc, title):
    if re.search(r"<title[^>]*>.*?</title>", doc, re.I | re.S):
        return re.sub(r"<title[^>]*>.*?</title>", lambda _: f"<title>{esc(title)}</title>", doc, count=1, flags=re.I | re.S)
    return inject_head(doc, f"<title>{esc(title)}</title>")


def plain(s):
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", "", s)).split())


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


HEAD = re.compile(r"<h([1-6])\b([^>]*)>(.*?)</h\1>", re.S | re.I)
COVER = re.compile(r"<section\b[^>]*\bclass=[\"'][^\"']*\bcover\b[^\"']*[\"'][^>]*>.*?</section>", re.S | re.I)


def prep_headings(doc, depth=2):
    """(doc, entries): every heading up to `depth` outside the cover gets an id; entries = [(level, id, text)]."""
    spans = [(m.start(), m.end()) for m in COVER.finditer(doc)]
    used = set(re.findall(r"""\bid=["']?([^\s"'>]+)""", doc))
    entries = []

    def fix(m):
        lvl, attrs, inner = int(m.group(1)), m.group(2), m.group(3)
        if lvl > depth or "no-toc" in attrs or any(a <= m.start() < b for a, b in spans):
            return m.group(0)
        idm = re.search(r"""\bid=["']?([^\s"'>]+)""", attrs)
        if idm:
            hid = idm.group(1)
        else:
            base = slug(plain(inner)) or "section"
            hid, k = base, 2
            while hid in used:
                hid, k = f"{base}-{k}", k + 1
            used.add(hid)
            attrs = f' id="{hid}"' + attrs
        entries.append((lvl, hid, plain(inner)))
        return f"<h{lvl}{attrs}>{inner}</h{lvl}>"
    return HEAD.sub(fix, doc), entries


TOC_CSS = ("nav.toc ol{list-style:none;margin:0;padding:0}nav.toc li{margin:0;padding:3pt 0}nav.toc li.l2{padding-left:14pt}"
           "nav.toc a{display:flex;align-items:baseline;color:inherit;text-decoration:none}nav.toc .t{flex:0 1 auto}"
           "nav.toc .dots{flex:1 1 auto;margin:0 4pt;border-bottom:1pt dotted #888}"
           "nav.toc .n{flex:0 0 2.4em;text-align:right;font-variant-numeric:tabular-nums}nav.toc.nonum .n,nav.toc.nonum .dots{display:none}")


def place_toc(doc, entries, numbers=None, nonum=False):
    """Insert the contents list at <!-- toc -->, else after the cover, else at the top of <body>. Numbers are fixed-width cells."""
    rows = "".join(
        f'<li class="l{lvl}"><a href="#{esc(hid)}"><span class="t">{esc(text)}</span><span class="dots"></span>'
        f'<span class="n">{(numbers or {}).get(hid, "00")}</span></a></li>' for lvl, hid, text in entries)
    nav = f'<nav class="toc{" nonum" if nonum else ""}" aria-label="Contents"><h2 class="no-toc">Contents</h2><ol>{rows}</ol></nav>'
    if "nav.toc .n" not in doc:      # no kit stylesheet in the page: bring the few rules the list needs (flex rows, no "1." markers, no run-on numbers)
        nav = f"<style>{TOC_CSS}</style>" + nav
    if "<!-- toc -->" in doc:
        return doc.replace("<!-- toc -->", nav, 1)
    m = COVER.search(doc)
    if m:
        return doc[:m.end()] + "\n" + nav + doc[m.end():]
    m = re.search(r"<body\b[^>]*>", doc, re.I)
    return doc[:m.end()] + "\n" + nav + doc[m.end():] if m else nav + doc


def outline_pages(pdf):
    """[(title, page)] from the PDF bookmarks, through pypdfium2."""
    import pypdfium2 as pdfium
    d = pdfium.PdfDocument(str(pdf))
    try:
        out = []
        for b in d.get_toc():
            dest = b.get_dest()
            out.append((" ".join(b.get_title().split()), dest.get_index() + 1 if dest else None))
        return out
    finally:
        d.close()


def numbers_for(entries, outline):
    nums, cur = {}, 0
    for _, hid, text in entries:
        for j in range(cur, len(outline)):
            if outline[j][0].casefold() in (text.casefold(), (text + text).casefold()) and outline[j][1]:   # Edge can double a title
                nums[hid], cur = outline[j][1], j + 1
                break
        else:
            raise BuildError(f"heading {text!r} is not in the PDF bookmarks, so its page number is unknown")
    return nums


# ------------------------------------------------------------------------------------------------------------- metadata
INFO_STR = re.compile(rb"(/(?:Creator|Producer)\s*\()((?:\\.|[^\\)])*)(\))")


def undouble_outline(w, heads):
    """Edge writes the bookmark title twice for a heading that starts a page ("SummarySummary"): give each its single title back."""
    from pypdf.generic import NameObject, TextStringObject
    twice = {h + h: h for h in heads if h}

    def walk(ref):
        while ref is not None:
            node = ref.get_object()
            t = " ".join(str(node.get("/Title", "")).split())
            if t in twice:
                node[NameObject("/Title")] = TextStringObject(twice[t])
            if node.get("/First") is not None:
                walk(node["/First"])
            ref = node.get("/Next")
    top = w._root_object.get("/Outlines")
    if top is not None:
        walk(top.get_object().get("/First"))


def finish_metadata(pdf, title, author, subject, notes, heads=()):
    """Set Title/Author/Subject, drop Creator and Producer (they carry the browser's name) and repair doubled bookmark titles. pypdf
    when installed; else the two strings are blanked in place at the same length, so the file's offsets stay valid."""
    if chk.have("pypdf"):
        from pypdf import PdfWriter
        w = PdfWriter(clone_from=str(pdf))
        undouble_outline(w, heads)
        meta = {"/Title": title}
        if author:
            meta["/Author"] = author
        if subject:
            meta["/Subject"] = subject
        w.metadata = meta
        tmp = str(pdf) + ".tmp"
        with open(tmp, "wb") as f:
            w.write(f)
        os.replace(tmp, pdf)
        return
    b = pathlib.Path(pdf).read_bytes()
    pathlib.Path(pdf).write_bytes(INFO_STR.sub(lambda m: m.group(1) + b" " * len(m.group(2)) + m.group(3), b))
    notes.append("pypdf is not installed: Creator and Producer were blanked in place, Author and Subject were not set and the "
                 "preflight check was skipped. " + chk.SETUP)


# --------------------------------------------------------------------------------------------------------------- the build
def compose(src, a, notes):
    """(html for Edge, title, author, subject) for the input file."""
    text = pathlib.Path(src).read_text(encoding="utf-8-sig")
    ext = pathlib.Path(src).suffix.lower()
    style = a.style
    if ext in (".md", ".markdown"):
        meta, body = front_matter(text)
        style = style or "report"
        first = re.search(r"^# +(.+?)\s*#*\s*$", body, re.M)
        title = a.title or meta.get("title") or (first.group(1).strip() if first else pathlib.Path(src).stem)
        cover = a.cover or meta.get("cover", "").lower() in ("yes", "true", "1")
        if cover and first and not (a.title or meta.get("title")):
            body = body[:first.start()] + body[first.end():]      # the cover carries the title: do not repeat it as the first heading
        author = a.author or meta.get("author", "")
        css = "" if style == "none" else (TEMPLATES / "report.css").read_text(encoding="utf-8")
        if style == "memo":
            css += "\n" + (TEMPLATES / "memo.css").read_text(encoding="utf-8")
        rest = ""
        if meta.get("subtitle"):
            rest += f'<p class="subtitle">{esc(meta["subtitle"])}</p>\n'
        line = " | ".join(x for x in (author, meta.get("date", "")) if x)
        if line:
            rest += f'<p class="meta">{esc(line)}</p>\n'
        if meta.get("classification"):
            rest += f'<p class="tag">{esc(meta["classification"])}</p>\n'
        tpl = (TEMPLATES / "report.html").read_text(encoding="utf-8")
        if not cover:
            tpl = re.sub(r"<!-- cover:start -->.*?<!-- cover:end -->\n?", "", tpl, flags=re.S)
        doc = string.Template(tpl).substitute(
            lang=esc(meta.get("lang", "en")), title=esc(title), author=esc(author), css=css, page=a.page, page_h=PAGE_H[a.page],
            run_left=css_str(title), run_right=css_str(meta.get("classification", "")), cover_rest=rest, body=md_to_html(body))
        subject = a.subject or meta.get("subject", "")
        return doc, title, author, subject
    if ext not in (".html", ".htm"):
        raise BuildError(f"{pathlib.Path(src).name}: give an .html or .md file")
    doc = text
    if a.title:
        doc = set_title(doc, a.title)
    if style in ("report", "memo"):
        css = (TEMPLATES / "report.css").read_text(encoding="utf-8")
        if style == "memo":
            css += "\n" + (TEMPLATES / "memo.css").read_text(encoding="utf-8")
        doc = inject_head(doc, f"<style>\n{css}\n</style>\n<style>:root {{ --page-h: {PAGE_H[a.page]}; }} @page {{ size: {a.page}; }}</style>")
    elif not re.search(r"@page[^{]*\{[^}]*\bsize\s*:", doc):
        doc = inject_head(doc, f"<style>@page {{ size: {a.page}; }}</style>")
    am = re.search(r"""<meta\s+name=["']author["']\s+content=["']([^"']*)["']""", doc, re.I)
    author = a.author or (htmllib.unescape(am.group(1)) if am else "")
    return doc, doc_title(doc) or pathlib.Path(src).stem, author, a.subject or ""


def build(a, notes):
    src = pathlib.Path(a.input).resolve()
    if not src.is_file():
        raise BuildError(f"no such file: {src}")
    doc, title, author, subject = compose(src, a, notes)
    doc = absolutize(doc, src.parent.as_uri().rstrip("/") + "/")
    doc = inject_head(doc, f'<meta http-equiv="Content-Security-Policy" content="{esc(CSP)}">')
    entries, numbers = [], None
    if a.toc:
        doc, entries = prep_headings(doc, a.toc_depth)
        if not entries:
            notes.append("--toc: the document has no headings, so no contents list was added")
    can_number = chk.have("pypdfium2")
    if entries and not can_number:
        notes.append("pypdfium2 is not installed: the contents list has no page numbers. " + chk.SETUP)
    out = pathlib.Path(a.out).resolve()
    with work_dir() as work:
        pdf = None
        for attempt in range(4 if entries and can_number else 1):
            html = place_toc(doc, entries, numbers, nonum=bool(entries) and not can_number) if entries else doc
            page_file = work / "doc.html"
            page_file.write_text(html, encoding="utf-8")
            pdf = print_to_pdf(page_file, work)
            if not (entries and can_number):
                break
            nums = numbers_for(entries, outline_pages(pdf))
            if nums == numbers:
                break
            numbers = nums
        else:
            raise BuildError("the contents page numbers did not settle after 4 builds; shorten the longest heading or add a page break")
        finish_metadata(pdf, title, author, subject, notes, [plain(m.group(3)) for m in HEAD.finditer(html)])
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf, out)
    return out, html


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--page", choices=("A4", "Letter"), default="A4")
    ap.add_argument("--title")
    ap.add_argument("--toc", action="store_true")
    ap.add_argument("--toc-depth", type=int, choices=(1, 2, 3), default=2)
    ap.add_argument("--style", choices=("report", "memo", "none"))
    ap.add_argument("--cover", action="store_true", help="Markdown: a full-bleed cover page")
    ap.add_argument("--author")
    ap.add_argument("--subject")
    ap.add_argument("--png", metavar="DIR", help="also render every page to PNG here (office-render/scripts/render.py)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    chk.reexec_under_knowledge_python(["pypdf", "pypdfium2", "PIL"] + (["markdown"] if a.input.lower().endswith((".md", ".markdown")) else []))
    notes = []
    try:
        out, html = build(a, notes)
    except BuildError as e:
        print(f"BUILD FAILED: {e}", file=sys.stderr)
        return 2
    for n in notes:
        print(f"NOTE: {n}", file=sys.stderr)
    report, pngs = None, []
    if chk.have("pypdf"):
        try:
            has_toc = 'class="toc"' in html
            report = chk.check(out, footer="required" if "counter(pages)" in html else "none",
                               toc="yes" if has_toc and 'class="toc nonum"' not in html else "auto", html=html)
        except chk.NotChecked as e:
            print(f"NOTE: preflight skipped: {e}", file=sys.stderr)
    if a.png:
        if not chk.have("pypdfium2", "PIL"):
            print("NOTE: --png needs pypdfium2 and Pillow: " + chk.SETUP, file=sys.stderr)
        else:
            r = subprocess.run([sys.executable, str(RENDER), str(out), "--out", a.png], capture_output=True, text=True)
            pngs = [x for x in r.stdout.splitlines() if x and not x.startswith("#")]
            if r.returncode:
                print(f"NOTE: PNG render failed: {r.stderr.strip()[:200]}", file=sys.stderr)
    if a.json:
        print(json.dumps({"pdf": str(out), "png": pngs, "notes": notes, "check": report}, indent=1, ensure_ascii=False))
    else:
        print(f"built {out} ({report['pages'] if report else '?'} pages)")
        for d in (report or {}).get("defects", []):
            print(f"DEFECT {d}")
        print("\n".join(pngs))
    return 1 if report and not report["ok"] else 0


if __name__ == "__main__":
    sys.exit(main())
