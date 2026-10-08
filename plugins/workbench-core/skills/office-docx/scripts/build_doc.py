#!/usr/bin/env python3
"""build_doc.py: build a Word .docx with python-docx from a JSON outline or Markdown, optionally on a
template, and read a .docx back as Markdown.

  python build_doc.py build <outline.json> <out.docx> [--allow-outside]          outline -> docx, then lint
  python build_doc.py md <in.md> <out.docx> [--template t.docx] [--allow-outside] Markdown -> docx
  python build_doc.py styles <template.docx>                   list paragraph, list and table styles
  python build_doc.py to-md <in.docx> [out.md]                 docx -> Markdown (markitdown)

Outline (JSON):
{
  "template": "brand.docx",            optional; its body is cleared unless "keep_template_content": true
  "header": "Team memo", "footer": "Internal", "page_numbers": true,
  "blocks": [
    {"title": "Release plan"},  {"subtitle": "Q3"},
    {"heading": "Summary", "level": 1},
    {"paragraph": "Text with **bold**, *italic*, `code` and [a link](https://example.com).", "style": "Body Text"},
    {"bullets": ["Point", ["sub-point", "sub-point"], "Point"]},
    {"numbered": ["First", "Second"]},                 each numbered list restarts at 1
    {"table": {"columns": ["Item", "Owner"], "rows": [ ["Build", "<name>"] ], "style": "Table Grid"}},
    {"image": "diagram.png", "width_in": 6, "caption": "Figure 1: the flow"},
    {"quote": "A quoted passage."},
    {"page_break": true}
  ]
}
Relative paths resolve against the outline's folder. Image and template paths must stay inside that
folder: `..` escapes, absolute paths elsewhere, network paths (\\\\server\\share or //server/share) and URLs
(http:, file:, ...) are refused unless you pass --allow-outside. Styles missing from a template fall
back to Normal with a LINT line. Macro-enabled and legacy formats are refused.
"""
import json, os, re, sys

from docx import Document
from docx.enum.text import WD_BREAK
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Inches

REFUSED = {".docm", ".dotm", ".doc", ".dot", ".rtf", ".xlsm", ".pptm"}
LINT = {"heading_chars": 90, "paragraph_words": 180, "table_cols": 8, "table_rows": 40}
INLINE = re.compile(r"(\*\*(?P<b>.+?)\*\*|__(?P<b2>.+?)__|`(?P<c>[^`]+)`|\[(?P<lt>[^\]]+)\]\((?P<lu>[^)\s]+)\)"
                    r"|(?<![\w*])\*(?P<i>[^*\s][^*]*?)\*(?![\w*])|(?<![\w_])_(?P<i2>[^_\s][^_]*?)_(?![\w_]))")


URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")      # two letters or more, so C:\ is a drive, not a scheme


def inside(base, path, what, allow_outside=False):
    """The full path of `path` (relative to `base`) if it stays inside `base`. Network paths and URLs are
    refused because opening them reaches another machine (a UNC path sends Windows credentials to it)."""
    raw = str(path)
    if not allow_outside:
        if raw.startswith(("\\\\", "//")):
            raise SystemExit(f"refusing {what} {raw}: a network path. Copy the file next to the outline, "
                             "or pass --allow-outside if you trust that server.")
        if URL_SCHEME.match(raw):
            raise SystemExit(f"refusing {what} {raw}: a URL. Download it next to the outline first.")
    full = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(base, raw))
    root = os.path.realpath(base)
    if not allow_outside:
        try:
            ok = os.path.commonpath([os.path.normcase(full), os.path.normcase(root)]) == os.path.normcase(root)
        except ValueError:          # another drive
            ok = False
        if not ok:
            raise SystemExit(f"refusing {what} {raw}: it is outside {root}. Copy it into that folder, "
                             "or pass --allow-outside.")
    return full


def refuse_risky(path, what="file"):
    ext = os.path.splitext(str(path))[1].lower()
    if ext in REFUSED:
        raise SystemExit(f"refusing {what} {ext}: macro-enabled or legacy format. Open a trusted copy in Word, "
                         "save it as .docx (macros are dropped), and use that.")
    if what == "template" and ext == ".dotx":
        raise SystemExit("python-docx cannot open .dotx: open it in Word and save a copy as .docx, then use that.")


class Builder:
    def __init__(self, template=None, keep=False, base_dir=".", allow_outside=False):
        self.allow_outside = allow_outside
        if template:
            template = inside(base_dir, template, "template", allow_outside)
            refuse_risky(template, "template")
        self.doc = Document(template) if template else Document()
        self.base = base_dir
        self.lint = []
        self.last_level = 0
        if template and not keep:
            body = self.doc.element.body
            for el in list(body):
                if el.tag != qn("w:sectPr"):
                    body.remove(el)

    # -- helpers -----------------------------------------------------------------------------------
    def style(self, name, fallback="Normal"):
        try:
            return self.doc.styles[name]
        except KeyError:
            self.lint.append(f"LINT style '{name}' not in template; used {fallback}")
            return self.doc.styles[fallback]

    def has_style(self, name):
        try:
            self.doc.styles[name]
            return True
        except KeyError:
            return False

    def usable_width(self):
        s = self.doc.sections[-1]
        return Emu(s.page_width - s.left_margin - s.right_margin)

    def hyperlink(self, para, text, url):
        r_id = para.part.relate_to(url, RT.HYPERLINK, is_external=True)
        h = OxmlElement("w:hyperlink")
        h.set(qn("r:id"), r_id)
        run = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        if self.has_style("Hyperlink"):
            rs = OxmlElement("w:rStyle")
            rs.set(qn("w:val"), self.doc.styles["Hyperlink"].style_id)
            rpr.append(rs)
        else:
            col, u = OxmlElement("w:color"), OxmlElement("w:u")
            col.set(qn("w:val"), "0563C1")
            u.set(qn("w:val"), "single")
            rpr.extend([col, u])
        run.append(rpr)
        t = OxmlElement("w:t")
        t.text = text
        t.set(qn("xml:space"), "preserve")
        run.append(t)
        h.append(run)
        para._p.append(h)

    def inline(self, para, text):
        pos = 0
        for m in INLINE.finditer(text):
            if m.start() > pos:
                para.add_run(text[pos:m.start()])
            if m.group("b") or m.group("b2"):
                para.add_run(m.group("b") or m.group("b2")).bold = True
            elif m.group("c"):
                r = para.add_run(m.group("c"))
                r.font.name = "Consolas"
            elif m.group("lt"):
                self.hyperlink(para, m.group("lt"), m.group("lu"))
            else:
                para.add_run(m.group("i") or m.group("i2")).italic = True
            pos = m.end()
        if pos < len(text):
            para.add_run(text[pos:])
        return para

    def restart_numbering(self, style):
        """A new w:num on the style's abstract list with startOverride=1, so each list restarts at 1."""
        ppr = style.element.pPr
        if ppr is None or ppr.numPr is None or ppr.numPr.numId is None:
            return None
        numbering = self.doc.part.numbering_part.element
        old = numbering.num_having_numId(ppr.numPr.numId.val)
        num = numbering.add_num(old.abstractNumId.val)
        for lvl in range(3):
            num.add_lvlOverride(ilvl=lvl).add_startOverride(1)
        return num.numId

    # -- blocks ------------------------------------------------------------------------------------
    def heading(self, text, level):
        level = max(1, min(int(level), 9))
        if self.last_level and level > self.last_level + 1:
            self.lint.append(f"LINT heading '{text[:40]}' jumps from level {self.last_level} to {level}")
        if len(text) > LINT["heading_chars"]:
            self.lint.append(f"LINT heading longer than {LINT['heading_chars']} chars: '{text[:40]}...'")
        self.last_level = level
        p = self.doc.add_paragraph(style=self.style(f"Heading {level}"))
        return self.inline(p, text)

    def paragraph(self, text, style="Normal"):
        if len(text.split()) > LINT["paragraph_words"]:
            self.lint.append(f"LINT paragraph over {LINT['paragraph_words']} words: '{text[:40]}...'")
        return self.inline(self.doc.add_paragraph(style=self.style(style)), text)

    def items(self, items, kind, depth=0, num_id=None):
        base = "List Bullet" if kind == "bullets" else "List Number"
        if kind == "numbered" and depth == 0 and num_id is None:
            num_id = self.restart_numbering(self.style(base))
        for it in items:
            if isinstance(it, list):
                self.items(it, kind, depth + 1, num_id)
                continue
            name = base if depth == 0 else f"{base} {min(depth + 1, 3)}"
            p = self.inline(self.doc.add_paragraph(style=self.style(name, base if self.has_style(base) else "Normal")),
                            str(it))
            if num_id is not None and depth == 0:
                numpr = p._p.get_or_add_pPr().get_or_add_numPr()
                numpr.get_or_add_ilvl().val = 0
                numpr.get_or_add_numId().val = num_id

    def table(self, spec):
        cols, rows = spec.get("columns") or [], spec.get("rows") or []
        if len(cols) > LINT["table_cols"]:
            self.lint.append(f"LINT table has {len(cols)} columns; consider landscape or splitting it")
        if len(rows) > LINT["table_rows"]:
            self.lint.append(f"LINT table has {len(rows)} rows; consider an appendix or a spreadsheet")
        width = len(cols) or max((len(r) for r in rows), default=1)
        t = self.doc.add_table(rows=0, cols=width)
        t.style = self.style(spec.get("style", "Table Grid"), "Normal Table")
        if cols:
            cells = t.add_row().cells
            for c, v in zip(cells, cols):
                c.paragraphs[0].add_run(str(v)).bold = True
            trpr = t.rows[0]._tr.get_or_add_trPr()
            hdr = OxmlElement("w:tblHeader")   # repeat the header row on every page
            hdr.set(qn("w:val"), "true")
            trpr.append(hdr)
        for r in rows:
            cells = t.add_row().cells
            for c, v in zip(cells, list(r) + [""] * (width - len(r))):
                self.inline(c.paragraphs[0], "" if v is None else str(v))
        self.doc.add_paragraph()   # keeps the next block from fusing with the table
        return t

    def image(self, path, width_in=None, caption=None):
        p = inside(self.base, path, "image", self.allow_outside)
        if not os.path.exists(p):
            self.lint.append(f"LINT image not found: {path}")
            return None
        full = self.usable_width()
        want = Inches(width_in) if width_in else None
        if want is None or want > full:
            want = full if want is not None else None
        pic = self.doc.add_picture(p, width=want) if want else self.doc.add_picture(p)
        if pic.width > full:            # scale down, keep the aspect ratio
            ratio = full / pic.width
            pic.width, pic.height = Emu(int(full)), Emu(int(pic.height * ratio))
        if caption:
            self.inline(self.doc.add_paragraph(style=self.style("Caption")), caption)
        return pic

    def header_footer(self, header=None, footer=None, page_numbers=False):
        for s in self.doc.sections:
            if header:
                s.header.paragraphs[0].text = header
            if footer or page_numbers:
                p = s.footer.paragraphs[0]
                p.text = (footer or "") + ("    Page " if page_numbers else "")
                if page_numbers:
                    fld = OxmlElement("w:fldSimple")
                    fld.set(qn("w:instr"), "PAGE")
                    r = OxmlElement("w:r")
                    t = OxmlElement("w:t")
                    t.text = "1"
                    r.append(t)
                    fld.append(r)
                    p._p.append(fld)

    def block(self, b):
        if "heading" in b:
            self.heading(b["heading"], b.get("level", 1))
        elif "title" in b:
            self.inline(self.doc.add_paragraph(style=self.style("Title")), b["title"])
        elif "subtitle" in b:
            self.inline(self.doc.add_paragraph(style=self.style("Subtitle")), b["subtitle"])
        elif "paragraph" in b:
            self.paragraph(b["paragraph"], b.get("style", "Normal"))
        elif "bullets" in b:
            self.items(b["bullets"], "bullets")
        elif "numbered" in b:
            self.items(b["numbered"], "numbered")
        elif "table" in b:
            self.table(b["table"])
        elif "image" in b:
            self.image(b["image"], b.get("width_in"), b.get("caption"))
        elif "quote" in b:
            self.inline(self.doc.add_paragraph(style=self.style("Quote")), b["quote"])
        elif "code" in b:
            for line in str(b["code"]).splitlines() or [""]:
                r = self.doc.add_paragraph(style=self.style("No Spacing")).add_run(line)
                r.font.name = "Consolas"
        elif b.get("page_break"):
            self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        else:
            self.lint.append(f"LINT unknown block skipped: {sorted(b)}")

    def save(self, out):
        refuse_risky(out, "output")
        if not out.lower().endswith(".docx"):
            raise SystemExit("output must be a .docx file")
        self.doc.save(out)


# -- Markdown -> blocks -----------------------------------------------------------------------------
def md_blocks(text):
    """A small Markdown reader: headings, paragraphs, nested - * + and 1. lists, pipe tables, images,
    > quotes, fenced code, --- page breaks are ignored (rules are not page breaks)."""
    blocks, lines, i = [], text.replace("\r\n", "\n").split("\n"), 0
    para = []

    def flush():
        if para:
            blocks.append({"paragraph": " ".join(s.strip() for s in para)})
            para.clear()

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if s.startswith("```"):
            flush()
            code, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            blocks.append({"code": "\n".join(code)})
        elif not s or re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            flush()
        elif m := re.match(r"(#{1,6})\s+(.*?)\s*#*$", s):
            flush()
            blocks.append({"heading": m.group(2), "level": len(m.group(1))})
        elif m := re.fullmatch(r"!\[([^\]]*)\]\(([^)\s]+)\)", s):
            flush()
            blocks.append({"image": m.group(2), "caption": m.group(1) or None})
        elif s.startswith(">"):
            flush()
            q = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                q.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append({"quote": " ".join(q)})
            continue
        elif s.startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\|?\s*:?-{2,}.*", lines[i + 1].strip()):
            flush()
            row = lambda r: [c.strip() for c in r.strip().strip("|").split("|")]
            cols, rows, i = row(s), [], i + 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(row(lines[i]))
                i += 1
            blocks.append({"table": {"columns": cols, "rows": rows}})
            continue
        elif re.match(r"\s*([-*+]|\d+[.)])\s+", ln):
            flush()
            kind = "numbered" if re.match(r"\s*\d+[.)]\s+", ln) else "bullets"
            flat = []
            while i < len(lines) and (m := re.match(r"(\s*)([-*+]|\d+[.)])\s+(.*)", lines[i])):
                flat.append((len(m.group(1).expandtabs(4)) // 2, m.group(3)))
                i += 1
            blocks.append({kind: nest(flat)})
            continue
        else:
            para.append(ln)
        i += 1
    flush()
    return blocks


def nest(flat):
    """[(indent, text)] -> ["a", ["a.1", "a.2"], "b"]; indents of any width, at most one level deeper per item."""
    levels = sorted({d for d, _ in flat})
    root = []
    stack = [root]                       # stack[k] is the list holding depth-k items
    for d, t in flat:
        depth = min(levels.index(d), len(stack))
        if depth == len(stack):          # one level deeper: a sub-list after the previous item
            sub = []
            stack[-1].append(sub)
            stack.append(sub)
        del stack[depth + 1:]
        stack[depth].append(t)
    return root


def to_markdown(path):
    refuse_risky(path)
    try:
        from markitdown import MarkItDown
    except ImportError:
        raise SystemExit("to-md needs markitdown: pip install --user -r requirements.txt")
    return MarkItDown().convert(path).text_content


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    allow = "--allow-outside" in a
    a = [x for x in a if x != "--allow-outside"]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = a[0]
    if cmd == "build" and len(a) == 3:
        with open(a[1], encoding="utf-8") as f:
            o = json.load(f)
        base = os.path.dirname(os.path.abspath(a[1]))
        tpl = o.get("template")
        b = Builder(tpl, o.get("keep_template_content"), base, allow)
        for blk in o.get("blocks", []):
            b.block(blk)
        b.header_footer(o.get("header"), o.get("footer"), o.get("page_numbers"))
    elif cmd == "md" and len(a) in (3, 5):
        tpl = a[a.index("--template") + 1] if "--template" in a else None
        with open(a[1], encoding="utf-8") as f:
            blocks = md_blocks(f.read())
        b = Builder(tpl, False, os.path.dirname(os.path.abspath(a[1])), allow)
        for blk in blocks:
            b.block(blk)
    elif cmd == "styles" and len(a) == 2:
        refuse_risky(a[1], "template")
        d = Document(a[1])
        for kind, label in ((1, "paragraph"), (3, "table")):
            print(f"{label} styles: " + ", ".join(sorted(s.name for s in d.styles if s.type == kind)))
        return 0
    elif cmd == "to-md" and len(a) in (2, 3):
        md = to_markdown(a[1])
        if len(a) == 3:
            with open(a[2], "w", encoding="utf-8") as f:
                f.write(md)
            print(a[2])
        else:
            sys.stdout.write(md)
        return 0
    else:
        print(__doc__)
        return 2
    out = a[2]
    b.save(out)
    print(out)
    for line in b.lint:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
