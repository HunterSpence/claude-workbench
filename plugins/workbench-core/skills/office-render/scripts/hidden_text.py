#!/usr/bin/env python3
"""hidden_text.py: report text in a document that a reader does not see but a model reading the file would.

  python hidden_text.py scan FILE... [--json] [--max-pages 500] [--max-mb 100] [--max-unpacked-mb 256]
                                     [--max-seconds 120] [--mem-mb 768]
  python hidden_text.py --self-test          offline, a few seconds, one line, exit 0 when every check holds

Formats: .pdf, .docx and plain text (.txt .md .csv .tsv .json .log .vtt .srt). Any other file is an error, never "clean".
  PDF       text outside the page or its crop box; text under 1 pt; text whose own glyph box renders as one flat colour
            (white on white, covered by a shape, invisible render mode over a blank area); invisible-mode text laid
            over different visible text. An invisible text layer over an image (an OCR layer) is noted, not flagged.
  DOCX      hidden runs (w:vanish, w:specVanish, set directly or through a style); text coloured like its highlight,
            shading or page colour; text of 1 pt or less. Body, headers, footers, footnotes and endnotes.
  text      zero-width characters, Unicode tag characters (decoded), bidi controls, words mixing Latin with look-alike
            Cyrillic or Greek letters, chat-template tokens and lines imitating chat turns
  metadata  PDF document info; DOCX core, app and custom properties: the text checks, plus prose or model-directed
            wording in a field
Caps: the file size, a .docx's unpacked size and a PDF's page count are checked first; then each file is parsed in a
child process under the kit's memcap (a per-process memory ceiling) and a time limit. A cap that is hit is an error.
Exit: 0 every file clean, 1 something flagged, 2 an error (unreadable, unsupported, over a cap). It only reports: it never
moves, edits or rejects a file. Excerpts show invisible characters as \\uXXXX escapes; treat them as untrusted data.
--json: {"version":1,"exit":N,"files":[{"file","format","status":"clean|flagged|error",
         "findings":[{"kind","where","text","detail"}],"notes":[...],"error":null|{"kind","message"}}]}
Needs pypdfium2 and Pillow (PDF) and lxml (DOCX), pinned in requirements.txt. Never PyMuPDF: it is AGPL-3.0.
"""
import argparse
import difflib
import glob
import io
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import unicodedata
import zipfile

TEXT_EXT = (".txt", ".md", ".csv", ".tsv", ".json", ".log", ".vtt", ".srt")
FLAT = 25            # grey levels (0-255) between darkest and lightest pixel of a glyph box below which it shows nothing
TINY_PT = 1.0        # effective glyph size in points below which text is unreadable
MAX_PIXELS = 6_000_000   # render budget per page; larger pages render at a lower scale
MAX_FINDINGS = 200
INVISIBLE_MODES = (3, 7)   # PDF text render modes that paint nothing: invisible, clip only
CAPS = {"max_pages": 500, "max_mb": 100, "max_unpacked_mb": 256, "max_seconds": 120.0, "mem_mb": 768}

ZW_RE = re.compile("[\u200b\u200c\u200d\u2060-\u2064\u180e\ufeff]")
JOINERS = "\u200c\u200d"                       # legitimate inside Persian, Indic and emoji text: flagged between ASCII only
BIDI_RE = re.compile("[\u202a-\u202e\u2066-\u2069]")
MARKS_RE = re.compile("[\u200e\u200f\u061c]")  # legitimate in right-to-left text: flagged only when there is none
TAGS_RE = re.compile("[\U000e0000-\U000e007f]+")
LOOKALIKE = set("\u0430\u0435\u043e\u0440\u0441\u0443\u0445\u0456\u0458\u0455\u04bb\u0501\u051b\u051d\u04cf\u0410\u0412\u0415\u041a\u041c\u041d\u041e\u0420\u0421\u0422\u0425\u0406\u0408\u0405" "\u03bf\u03b1\u03c1\u03c5\u03ba\u03bd\u03b9\u0391\u0392\u0395\u0396\u0397\u0399\u039a\u039c\u039d\u039f\u03a1\u03a4\u03a5\u03a7")
TEMPLATE = re.compile(r"<\|[a-z_]{2,20}\|>|\[/?INST\]|<</?SYS>>|<(?:start|end)_of_turn>"
                      r"|</?(?:system|assistant|system-reminder|untrusted[\w-]*)>", re.I)
ROLE = re.compile(r"^[ \t>#*-]*(?:assistant|human)[ \t]*:", re.I | re.M)
ROLE_WEAK = re.compile(r"^[ \t>#*-]*(?:system|user|developer)[ \t]*:", re.I | re.M)   # only next to a ROLE or TEMPLATE hit
CUE = re.compile(r"\b(?:ignore|disregard|forget|override)\b.{0,40}?\b(?:instructions?|previous|prior|above|rules?)\b"
                 r"|\byou are (?:now )?(?:an?|the)\b|\bsystem prompt\b|\b(?:assistant|chatbot|language model|llm)\b"
                 r"|\bdo not (?:mention|reveal|tell|disclose)\b|\brespond (?:only )?with\b", re.I | re.S)


class Stop(Exception):
    """A file that is not scanned: kind is one of size-cap, unpacked-cap, page-cap, unsupported, parser."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


# ---- text checks (every format) ---------------------------------------------------------------------------------
def show(s, n=80):
    """An excerpt that is safe to print: whitespace runs as one space, invisible characters as escapes, n characters."""
    s = re.sub(r"[\t\r\n\f\v]+", " ", s)
    cut = s[:n]
    out = "".join(c if unicodedata.category(c)[0] != "C" and c not in "\u2028\u2029"
                  else (f"\\u{ord(c):04x}" if ord(c) < 0x10000 else f"\\U{ord(c):08x}") for c in cut)
    return out + ("..." if len(s) > n else "")


def finding(kind, where, text, detail):
    return {"kind": kind, "where": where, "text": show(text), "detail": detail}


def text_findings(text, where):
    """Findings from the characters themselves: what a model receives regardless of how the page looks."""
    out = []
    ctx = lambda i: text[max(0, i - 20):i + 40]   # noqa: E731
    for m in TAGS_RE.finditer(text):
        if text[:m.start()].endswith("\U0001f3f4"):      # a regional flag emoji uses tag characters legitimately
            continue
        spelled = "".join(chr(ord(c) - 0xE0000) for c in m.group() if 0xE0020 <= ord(c) <= 0xE007E)
        out.append(finding("unicode-tags", where, ctx(m.start()), "tag characters spell: " + show(spelled)))
    zw = [m.start() for m in ZW_RE.finditer(text)
          if not (m.group() == "\ufeff" and m.start() == 0)
          and not (m.group() in JOINERS and not (text[m.start() - 1:m.start()] or " ").isascii())
          and not (m.group() in JOINERS and not (text[m.start() + 1:m.start() + 2] or " ").isascii())]
    if zw:
        out.append(finding("zero-width", where, ctx(zw[0]), f"{len(zw)} zero-width character(s)"))
    bidi = [m.start() for m in BIDI_RE.finditer(text)]
    if MARKS_RE.search(text) and not any(unicodedata.bidirectional(c) in ("R", "AL") for c in text if not c.isascii()):
        bidi += [m.start() for m in MARKS_RE.finditer(text)]
    if bidi:
        out.append(finding("bidi-control", where, ctx(min(bidi)), f"{len(bidi)} bidirectional control character(s)"))
    words = 0
    for m in re.finditer(r"[^\W\d_]{2,}", text):
        w = m.group()
        if w.isascii() or not any(c in LOOKALIKE for c in w):
            continue
        if any(c.isascii() or unicodedata.name(c, "").startswith("LATIN") for c in w):
            words += 1
            if words <= 5:
                marked = "".join(f"\\u{ord(c):04x}" if c in LOOKALIKE else c for c in w)
                out.append(finding("homoglyph", where, ctx(m.start()), "word mixes Latin and look-alike letters: " + marked))
    if words > 5:
        out.append(finding("homoglyph", where, "", f"{words - 5} more mixed-script word(s)"))
    strong = [m for m in (TEMPLATE.search(text), ROLE.search(text)) if m]
    for m in strong:
        out.append(finding("role-token", where, ctx(m.start()), "chat-template token" if m.re is TEMPLATE else
                           "line imitating a chat turn"))
    if strong:
        for m in list(ROLE_WEAK.finditer(text))[:3]:
            out.append(finding("role-token", where, ctx(m.start()), "role line next to a forged chat turn"))
    return out


def meta_findings(fields):
    """Metadata is never on the page but many pipelines hand it to the model: text checks plus prose in a field."""
    out = []
    for name, value in fields.items():
        value = str(value or "").strip()
        if not value:
            continue
        where = "metadata:" + name
        out += text_findings(value, where)
        n = len(value.split())
        if CUE.search(value) or n >= 25:
            out.append(finding("metadata-prose", where, value,
                               "model-directed wording" if CUE.search(value) else f"{n} words of prose in a metadata field"))
    return out


def runs(items):
    """[(key, verdict, text)] in reading order -> [(verdict, [keys], text)] for consecutive equal verdicts (None ends a
    run; whitespace never starts or ends one)."""
    out, cur = [], None
    for key, verdict, ch in items:
        if ch.isspace():
            if cur:
                cur[2].append(ch)
            continue
        if cur and cur[0] == verdict:
            cur[1].append(key)
            cur[2].append(ch)
            continue
        cur = [verdict, [key], [ch]] if verdict else None
        if cur:
            out.append(cur)
    return [(v, keys, "".join(t).strip()) for v, keys, t in out]


# ---- PDF ----------------------------------------------------------------------------------------------------------
PDF_DETAIL = {"off-page": "text outside the page or its crop box", "tiny-text": "text smaller than 1 pt",
              "invisible-text": "glyph boxes render as one flat colour (same colour as the background, covered, or "
                                "invisible render mode on a blank area)"}


def scan_pdf(src, caps):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    doc = pdfium.PdfDocument(src)
    try:
        n = len(doc)
        if n > caps["max_pages"]:
            raise Stop("page-cap", f"{n} pages; the cap is {caps['max_pages']} (--max-pages)")
        findings, notes = meta_findings(doc.get_metadata_dict(skip_empty=True)), []
        for i in range(n):
            page = doc[i]
            try:
                f, nt = pdf_page(page, i + 1, raw)
            finally:
                page.close()
            findings += f
            notes += nt
        return findings, notes
    finally:
        doc.close()


def pdf_page(page, no, raw):
    tp = page.get_textpage()
    try:
        chars = []   # [index, char, loose box, render mode, effective size in pt]
        for i in range(tp.count_chars()):
            obj = raw.FPDFText_GetTextObject(tp.raw, i)
            if not obj:
                continue                     # characters the extractor generated (line breaks), not on the page
            m = raw.FS_MATRIX()
            raw.FPDFText_GetMatrix(tp.raw, i, m)
            size = raw.FPDFText_GetFontSize(tp.raw, i) * min(math.hypot(m.a, m.b), math.hypot(m.c, m.d))
            chars.append([i, chr(raw.FPDFText_GetUnicode(tp.raw, i)), tp.get_charbox(i, loose=True),
                          raw.FPDFTextObj_GetTextRenderMode(obj), size])
        where = f"page {no}"
        out, notes = text_findings(tp.get_text_range(), where), []
        if not chars:
            return out, notes
        c, m = page.get_cropbox(), page.get_mediabox()
        vis = (max(c[0], m[0]), max(c[1], m[1]), min(c[2], m[2]), min(c[3], m[3]))
        verdict = {}
        for i, ch, (l, b, r, t), mode, size in chars:
            if ch.isspace():
                continue
            cx, cy = (l + r) / 2, (b + t) / 2
            if not (vis[0] <= cx <= vis[2] and vis[1] <= cy <= vis[3]):
                verdict[i] = "off-page"
            elif size < TINY_PT:
                verdict[i] = "tiny-text"
        rest = [x for x in chars if x[0] not in verdict and not x[1].isspace()]
        flat = flat_glyphs(page, rest)
        verdict.update((i, "invisible-text") for i in flat)
        laid = [x for x in rest if x[3] in INVISIBLE_MODES and x[0] not in flat]   # invisible text over something drawn
        shown = [x for x in rest if x[3] not in INVISIBLE_MODES and x[0] not in flat]
        over, layer = invisible_over_visible(chars, laid, shown, lambda a, b: tp.get_text_range(a, b - a + 1))
        verdict.update((i, "invisible-over-text") for i in over)
        for v, keys, text in runs([(x[0], verdict.get(x[0]), x[1]) for x in chars]):
            if len(keys) < 2:
                continue                      # one stray glyph carries no message
            first, last = keys[0], keys[-1]
            full = tp.get_text_range(first, last - first + 1).strip() or text
            detail = next((over[k] for k in keys if over.get(k)), PDF_DETAIL.get(v, ""))
            out.append(finding(v, where, full, detail))
        if layer:
            notes.append(f"{where}: an invisible text layer over an image or drawing ({layer} characters, likely OCR); "
                         "not flagged")
        return out, notes
    finally:
        tp.close()


def flat_glyphs(page, chars):
    """Indices of glyphs whose loose box renders as one flat colour: the reader sees nothing there."""
    if not chars:
        return set()
    scale = min(2.0, math.sqrt(MAX_PIXELS / max(1.0, page.get_width() * page.get_height())))
    bitmap = page.render(scale=scale, grayscale=True)
    im, conv = bitmap.to_pil(), bitmap.get_posconv(page)
    flat = set()
    for i, _, (l, b, r, t), _, _ in chars:
        (xa, ya), (xb, yb) = conv.to_bitmap(l, t), conv.to_bitmap(r, b)
        box = (max(0, int(min(xa, xb))), max(0, int(min(ya, yb))),
               min(im.width, int(math.ceil(max(xa, xb)))), min(im.height, int(math.ceil(max(ya, yb)))))
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            continue                          # too small to judge at this scale
        lo, hi = im.crop(box).getextrema()
        if hi - lo < FLAT:
            flat.add(i)
    return flat


def _norm(s):
    return "".join(c for c in s.casefold() if c.isalnum())


def invisible_over_visible(chars, laid, shown, text_of):
    """Runs of invisible-mode text that sit on visible text. ({first index of a differing run: detail}, count of
    invisible characters over non-text, e.g. an OCR layer over a scan). A run that repeats the text under it is a text
    layer and is not flagged."""
    cell = 24.0
    grid = {}
    for x in shown:
        l, b, r, t = x[2]
        for gx in range(int(l // cell), int(r // cell) + 1):
            for gy in range(int(b // cell), int(t // cell) + 1):
                grid.setdefault((gx, gy), []).append(x)

    def under(x):
        l, b, r, t = x[2]
        area = max(1e-6, (r - l) * (t - b))
        hits = set()
        for gx in range(int(l // cell), int(r // cell) + 1):
            for gy in range(int(b // cell), int(t // cell) + 1):
                for y in grid.get((gx, gy), ()):
                    L, B, R, T = y[2]
                    w, h = min(r, R) - max(l, L), min(t, T) - max(b, B)
                    if w > 0 and h > 0 and w * h >= 0.3 * min(area, max(1e-6, (R - L) * (T - B))):
                        hits.add(y[0])
        return hits

    laid_ids = {x[0]: x for x in laid}
    differing, layer = {}, 0
    for _, keys, text in runs([(x[0], "laid" if x[0] in laid_ids else None, x[1]) for x in chars]):
        below = set().union(*(under(laid_ids[k]) for k in keys))
        if not below:
            layer += len(keys)
            continue
        seen = text_of(min(below), max(below))
        if difflib.SequenceMatcher(None, _norm(text), _norm(seen)).ratio() < 0.8:
            differing.update({k: "" for k in keys})
            differing[keys[0]] = "invisible text laid over different visible text: " + show(seen, 40)
    return differing, layer


# ---- DOCX ---------------------------------------------------------------------------------------------------------
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
BODY_PARTS = re.compile(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml")
HIGHLIGHT = {"black": "000000", "blue": "0000FF", "cyan": "00FFFF", "green": "00FF00", "magenta": "FF00FF",
             "red": "FF0000", "yellow": "FFFF00", "white": "FFFFFF", "darkBlue": "000080", "darkCyan": "008080",
             "darkGreen": "008000", "darkMagenta": "800080", "darkRed": "800000", "darkYellow": "808000",
             "darkGray": "808080", "lightGray": "C0C0C0"}
DOCX_DETAIL = {"hidden-run": "hidden text (w:vanish or w:specVanish)", "tiny-text": "text of 1 pt or less",
               "background-colour": "text coloured like its background"}


class Package:
    """A .docx whose declared unpacked size is checked before anything is decompressed. zipfile never returns more than
    a member's declared size (a member that lies fails its CRC check), so the declared total bounds every read."""

    def __init__(self, src, cap_mb):
        from lxml import etree
        self.etree = etree
        self.parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
        self.z = zipfile.ZipFile(io.BytesIO(src) if isinstance(src, bytes) else src)
        total = sum(i.file_size for i in self.z.infolist())
        if total > cap_mb << 20:
            raise Stop("unpacked-cap", f"unpacks to {total >> 20} MB; the cap is {cap_mb} MB (--max-unpacked-mb)")
        self.names = set(self.z.namelist())

    def xml(self, name):
        return self.etree.fromstring(self.z.read(name), self.parser) if name in self.names else None


def _on(e):
    return e is not None and e.get(W + "val", "true").lower() not in ("0", "false", "off", "none")


def _shd(e):
    if e is None or e.get(W + "val") == "nil":
        return None
    color, fill = e.get(W + "color", "auto"), e.get(W + "fill", "auto")
    if e.get(W + "val") == "solid" and color.lower() != "auto":
        return color
    return fill if fill.lower() != "auto" else None


def run_props(rpr):
    """The run properties an rPr sets: vanish (bool), color, sz (half-points), bg (highlight or shading)."""
    d = {}
    if rpr is None:
        return d
    for tag in ("vanish", "specVanish"):
        e = rpr.find(W + tag)
        if e is not None:
            d["vanish" if tag == "vanish" else "spec"] = _on(e)
    e = rpr.find(W + "color")
    if e is not None and e.get(W + "val", "auto").lower() != "auto":
        d["color"] = e.get(W + "val")
    e = rpr.find(W + "sz")
    if e is not None and (e.get(W + "val") or "").isdigit():
        d["sz"] = int(e.get(W + "val"))
    e = rpr.find(W + "highlight")
    bg = HIGHLIGHT.get(e.get(W + "val")) if e is not None else None
    bg = bg or _shd(rpr.find(W + "shd"))
    if bg:
        d["bg"] = bg
    return d


class Styles:
    """Run properties and paragraph shading from styles.xml, following basedOn. ponytail: toggle properties use the
    last setting in the hierarchy, not the standard's XOR; exact toggles only matter for styles that switch vanish twice."""

    def __init__(self, root):
        self.default, self.table = {}, {}
        if root is None:
            return
        self.default = run_props(root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr"))
        for s in root.iter(W + "style"):
            base = s.find(W + "basedOn")
            self.table[s.get(W + "styleId")] = (base.get(W + "val") if base is not None else None,
                                                run_props(s.find(W + "rPr")), _shd(s.find(f"{W}pPr/{W}shd")))

    def chain(self, sid):
        props, shd, seen = {}, None, set()
        order = []
        while sid in self.table and sid not in seen and len(seen) < 32:
            seen.add(sid)
            order.append(self.table[sid])
            sid = self.table[sid][0]
        for _, p, s in reversed(order):
            props.update(p)
            shd = s or shd
        return props, shd


def _close(a, b):
    try:
        x, y = int(a, 16), int(b, 16)
    except (TypeError, ValueError):
        return False
    return max(abs((x >> k & 255) - (y >> k & 255)) for k in (0, 8, 16)) < FLAT


def scan_docx(src, caps):
    pkg = Package(src, caps["max_unpacked_mb"])
    styles = Styles(pkg.xml("word/styles.xml"))
    findings, notes = [], []
    for name in sorted(n for n in pkg.names if BODY_PARTS.fullmatch(n)):
        root = pkg.xml(name)
        if root is None:
            continue
        page = root.find(W + "background")
        page_bg = page.get(W + "color") if page is not None and page.get(W + "color", "auto") != "auto" else "FFFFFF"
        items, unchecked = [], 0
        for p in root.iter(W + "p"):
            ppr = p.find(W + "pPr")
            pstyle = ppr.find(W + "pStyle") if ppr is not None else None
            pprops, pshd = styles.chain(pstyle.get(W + "val") if pstyle is not None else None)
            pshd = _shd(ppr.find(W + "shd")) if ppr is not None and ppr.find(W + "shd") is not None else pshd
            cell = next(p.iterancestors(W + "tc"), None)
            cshd = _shd(cell.find(f"{W}tcPr/{W}shd")) if cell is not None else None
            table = next(p.iterancestors(W + "tbl"), None)
            styled = cshd is None and table is not None and table.find(f"{W}tblPr/{W}tblStyle") is not None
            for r in p.findall(f".//{W}r"):
                if next(r.iterancestors(W + "p")) is not p or any(a.tag == MC_FALLBACK for a in r.iterancestors()):
                    continue                  # a nested text box has its own paragraph; fallback copies duplicate content
                text = "".join(t.text or "" for t in r.findall(W + "t"))
                if not text:
                    continue
                rpr = r.find(W + "rPr")
                rs = rpr.find(W + "rStyle") if rpr is not None else None
                props = dict(styles.default)
                props.update(pprops)
                props.update(styles.chain(rs.get(W + "val") if rs is not None else None)[0])
                props.update(run_props(rpr))
                bg = props.get("bg") or pshd or cshd
                same = bool(props.get("color")) and _close(props["color"], bg or page_bg)
                if same and not bg and styled:
                    unchecked += 1            # the cell's fill comes from a table style, which is not resolved
                    same = False
                kind = ("hidden-run" if props.get("vanish") or props.get("spec") else
                        "tiny-text" if props.get("sz", 99) <= 2 else "background-colour" if same else None)
                items.append((0, kind, text))
            items.append((0, None, "\n"))
        findings += [finding(v, name, text, DOCX_DETAIL[v]) for v, _, text in runs(items) if text]
        if unchecked:
            notes.append(f"{name}: {unchecked} run(s) coloured like the page inside table cells filled by a table "
                         "style; not checked")
        body = "\n".join("".join(t.text or "" for t in p.iter(W + "t")) for p in root.iter(W + "p"))
        findings += text_findings(body, name)
    fields = {}
    for part in ("docProps/core.xml", "docProps/app.xml"):
        root = pkg.xml(part)
        for e in (root if root is not None else ()):
            if len(e) == 0 and (e.text or "").strip():
                fields[pkg.etree.QName(e).localname] = e.text
    root = pkg.xml("docProps/custom.xml")
    for prop in (root if root is not None else ()):
        fields["custom:" + (prop.get("name") or "?")] = " ".join(t.strip() for t in prop.itertext())
    return findings + meta_findings(fields), notes


# ---- plain text, dispatch -----------------------------------------------------------------------------------------
def scan_text(src, caps):
    data = src if isinstance(src, bytes) else open(src, "rb").read((caps["max_mb"] << 20) + 1)
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data.decode("utf-16", "replace")
    else:
        text = data.decode("utf-8-sig", "replace")
    return text_findings(text, "text"), []


def kind_of(name):
    ext = os.path.splitext(name)[1].lower()
    return "pdf" if ext == ".pdf" else "docx" if ext == ".docx" else "text" if ext in TEXT_EXT else None


def analyse(src, fmt, caps=CAPS):
    """(findings, notes) for one document given as a path or bytes. Raises Stop when it is not scanned."""
    if fmt is None:
        raise Stop("unsupported", "not scanned: only .pdf, .docx and plain text (" + " ".join(TEXT_EXT) + ")")
    f, notes = {"pdf": scan_pdf, "docx": scan_docx, "text": scan_text}[fmt](src, caps)
    return f[:MAX_FINDINGS], notes + ([f"{len(f) - MAX_FINDINGS} more finding(s) not listed"] if len(f) > MAX_FINDINGS else [])


def child(path, caps):
    """Runs inside the capped child: one JSON object on stdout, exit 0 whatever the verdict."""
    out = {"format": kind_of(path), "findings": [], "notes": [], "error": None}
    try:
        out["findings"], out["notes"] = analyse(path, out["format"], caps)
    except Stop as e:
        out["error"] = {"kind": e.kind, "message": str(e)}
    except MemoryError:
        out["error"] = {"kind": "memory-cap", "message": f"over the {caps['mem_mb']} MB memory cap (--mem-mb)"}
    except Exception as e:   # a parser failure on a hostile or broken file is a result, not a crash
        hint = (f" (a file that needs more than the {caps['mem_mb']} MB memory cap stops this way: the native parser "
                "reports a failed allocation as an OSError)") if isinstance(e, OSError) else ""
        out["error"] = {"kind": "parser", "message": f"{type(e).__name__}: {str(e)[:300]}{hint}"}
    sys.stdout.write(json.dumps(out))
    return 0


# ---- the parent: caps, memcap child, report -----------------------------------------------------------------------
def find_memcap():
    """The kit's tools/memcap/memcap.py: next to a checkout, or the installed kit copy (same lookup as find)."""
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, *[".."] * n, "tools", "memcap", "memcap.py") for n in range(4, 8)]
    cands.append(os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"),
                              "workbench", "kit", "tools", "memcap", "memcap.py"))
    return next((os.path.normpath(c) for c in cands if os.path.isfile(c)), None)


def _kill(p):
    if os.name == "nt":
        p.kill()                              # memcap dies, its job object closes, every process in it is killed
    else:
        os.killpg(p.pid, signal.SIGKILL)


def scan_file(path, caps):
    res = {"file": path, "format": kind_of(path), "status": "error", "findings": [], "notes": [], "error": None}

    def err(kind, message):
        res["error"] = {"kind": kind, "message": message}
        return res
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return err("unreadable", str(e))
    if size > caps["max_mb"] << 20:
        return err("size-cap", f"{size >> 20} MB; the cap is {caps['max_mb']} MB (--max-mb)")
    if res["format"] is None:
        return err("unsupported", "not scanned: only .pdf, .docx and plain text (" + " ".join(TEXT_EXT) + ")")
    memcap = find_memcap()
    if not memcap:
        return err("no-memcap", "tools/memcap/memcap.py from the kit was not found, so the file was not parsed")
    py = [sys.executable] + (["-I"] if sys.flags.isolated else [])
    cmd = [sys.executable, memcap, "--mb", str(caps["mem_mb"]), "--", *py, os.path.abspath(__file__), "_child", path,
           *[a for k in ("max_pages", "max_mb", "max_unpacked_mb", "mem_mb") for a in ("--" + k.replace("_", "-"), str(caps[k]))]]
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         **({} if os.name == "nt" else {"start_new_session": True}))
    try:
        out, _ = p.communicate(timeout=caps["max_seconds"])
    except subprocess.TimeoutExpired:
        _kill(p)
        p.communicate()
        return err("time-cap", f"stopped after {caps['max_seconds']:g} s (--max-seconds)")
    try:
        data = json.loads(out.decode("utf-8"))
        assert isinstance(data, dict) and isinstance(data.get("findings"), list)
    except (ValueError, AssertionError):
        data = None
    if p.returncode != 0 or data is None:
        return err("parser-stopped", f"the parser stopped without a result (exit {p.returncode}): it reached the "
                                     f"{caps['mem_mb']} MB memory cap (--mem-mb) or the file broke it")
    res.update(findings=data["findings"], notes=data.get("notes") or [])
    if data.get("error"):
        return err(data["error"]["kind"], data["error"]["message"])
    res["status"] = "flagged" if res["findings"] else "clean"
    return res


def exit_code(results):
    st = {r["status"] for r in results}
    return 2 if "error" in st else 1 if "flagged" in st else 0


def report(results):
    for r in results:
        if r["status"] == "error":
            print(f"ERROR    {r['file']}  {r['error']['kind']}: {r['error']['message']}")
            continue
        print(f"{r['status'].upper():8} {r['file']}" + (f"  ({len(r['findings'])} finding(s))" if r["findings"] else ""))
        for f in r["findings"]:
            print(f"  {f['kind']:<19} {f['where']}  \"{f['text']}\"  [{f['detail']}]")
        for n in r["notes"]:
            print(f"  note: {n}")
    n = {s: sum(r["status"] == s for r in results) for s in ("flagged", "clean", "error")}
    print(f"# {len(results)} file(s): {n['flagged']} flagged, {n['clean']} clean, {n['error']} error(s). "
          "Findings are for a person to review; nothing was moved, changed or rejected.")


# ---- fixtures for the self-test (the tests reuse them) -------------------------------------------------------------
def make_pdf(content, pages=1, resources="", extra=(), info=None, crop=None, media=(0, 0, 612, 792)):
    """A PDF (bytes) whose pages all draw `content`, with Helvetica as /F1. `extra` objects are numbered from 4 + 2*pages."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    data = content.encode("latin-1")
    cb = f" /CropBox [{' '.join(map(str, crop))}]" if crop else ""
    for i in range(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [{' '.join(map(str, media))}]{cb} "
                    f"/Resources << /Font << /F1 3 0 R >> {resources} >> /Contents {len(objs) + 2} 0 R >>")
        objs.append(f"<< /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream")
    objs[1] = (f"<< /Type /Pages /Kids [{' '.join(f'{4 + 2 * i} 0 R' for i in range(pages))}] /Count {pages} >>")
    objs += list(extra)
    if info:
        objs.append("<< " + " ".join(f"/{k} ({v})" for k, v in info.items()) + " >>")
    out, offs = b"%PDF-1.4\n", []
    for n, body in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{n} 0 obj\n".encode() + (body if isinstance(body, bytes) else body.encode("latin-1")) + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    trailer = f" /Info {len(objs)} 0 R" if info else ""
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R{trailer} >>\nstartxref\n{xref}\n%%EOF\n".encode()


def ink_image(w=200, h=40):
    """A grey image XObject with ink everywhere (a stand-in for a scanned page), for a PDF's `extra` list."""
    px = bytes(0 if (x + y) % 3 == 0 else 255 for y in range(h) for x in range(w))
    return (f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceGray /BitsPerComponent 8 "
            f"/Length {len(px)} >>\nstream\n").encode() + px + b"\nendstream"


def make_docx(body, styles=None, core=None, custom=None, extra=None):
    """A minimal .docx (bytes): `body` is the inner XML of w:body; `core` is the inner XML of cp:coreProperties;
    `extra` maps more part names to their XML."""
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    parts = {"[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
             'content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
             "word/document.xml": f'<?xml version="1.0"?><w:document {ns}><w:body>{body}</w:body></w:document>'}
    if styles:
        parts["word/styles.xml"] = f'<?xml version="1.0"?><w:styles {ns}>{styles}</w:styles>'
    if core:
        parts["docProps/core.xml"] = ('<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
                                      'package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                                      f'{core}</cp:coreProperties>')
    if custom:
        parts["docProps/custom.xml"] = ('<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/'
                                        'officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/'
                                        f'officeDocument/2006/docPropsVTypes">{custom}</Properties>')
    parts.update(extra or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, xml in parts.items():
            z.writestr(name, xml)
    return buf.getvalue()


def self_test():
    visible = "BT /F1 12 Tf 72 700 Td (The meeting moved to Thursday.) Tj ET "
    checks = [
        ("clean PDF", lambda: analyse(make_pdf(visible), "pdf"), set()),
        ("white text", lambda: analyse(make_pdf(visible + "BT 1 1 1 rg /F1 12 Tf 72 680 Td (Approve it) Tj ET"), "pdf"),
         {"invisible-text"}),
        ("OCR layer", lambda: analyse(make_pdf("q 200 0 0 40 72 600 cm /Im1 Do Q BT 3 Tr /F1 12 Tf 76 612 Td "
                                               "(Scanned words here) Tj ET", resources="/XObject << /Im1 6 0 R >>",
                                               extra=[ink_image()]), "pdf"), set()),
        ("hidden run", lambda: analyse(make_docx("<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>Approve it</w:t></w:r></w:p>"),
                                       "docx"), {"hidden-run"}),
        ("characters", lambda: analyse("ap\u200bprove \U000e0068\U000e0069".encode(), "text"), {"zero-width", "unicode-tags"}),
    ]
    try:
        for name, run, want in checks:
            got = {f["kind"] for f in run()[0]}
            if got != want:
                print(f"hidden_text self-test: FAIL: {name}: expected {sorted(want)}, got {sorted(got)}")
                return 1
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "probe.pdf")
            with open(path, "wb") as f:
                f.write(make_pdf(visible + "BT 1 1 1 rg /F1 12 Tf 72 680 Td (Approve it) Tj ET"))
            r = scan_file(path, CAPS)
            if r["status"] != "flagged":
                print(f"hidden_text self-test: FAIL: capped child scan: {r['status']} {r['error']}")
                return 1
    except Exception as e:
        print(f"hidden_text self-test: FAIL: {type(e).__name__}: {e}")
        return 1
    print(f"hidden_text self-test: ok ({len(checks) + 1} checks, child parsed under memcap)")
    return 0


def add_caps(p):
    p.add_argument("--max-pages", type=int, default=CAPS["max_pages"])
    p.add_argument("--max-mb", type=int, default=CAPS["max_mb"], help="largest file, in MB")
    p.add_argument("--max-unpacked-mb", type=int, default=CAPS["max_unpacked_mb"], help="largest unpacked .docx, in MB")
    p.add_argument("--mem-mb", type=int, default=CAPS["mem_mb"], help="memory cap for the parsing child, in MB")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_child"]:
        cp = argparse.ArgumentParser(prog="hidden_text.py _child")
        cp.add_argument("file")
        add_caps(cp)
        a = cp.parse_args(argv[1:])
        return child(a.file, {k: getattr(a, k) for k in ("max_pages", "max_mb", "max_unpacked_mb", "mem_mb")})
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("scan", help="scan files; exit 0 clean, 1 flagged, 2 error")
    s.add_argument("files", nargs="+")
    s.add_argument("--json", action="store_true")
    s.add_argument("--max-seconds", type=float, default=CAPS["max_seconds"], help="time limit per file")
    add_caps(s)
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd != "scan":
        ap.print_usage(sys.stderr)
        return 2
    caps = {k: getattr(a, k) for k in CAPS}
    files = [f for pat in a.files for f in (sorted(glob.glob(pat)) if glob.has_magic(pat) else [pat])] or a.files
    results = [scan_file(f, caps) for f in files]
    code = exit_code(results)
    if a.json:
        print(json.dumps({"version": 1, "exit": code, "files": results}, indent=1))
    else:
        report(results)
    return code


if __name__ == "__main__":
    sys.exit(main())
