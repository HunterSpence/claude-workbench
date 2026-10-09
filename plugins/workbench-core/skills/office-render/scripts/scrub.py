#!/usr/bin/env python3
"""scrub.py: write a scrubbed copy of a .docx / .pptx / .xlsx that is safe to send outside the organisation.

  python scrub.py <file> --out <copy> [--strip-notes] [--keep-label] [--json]

The input is never modified: the copy goes to a new path (refused when it is the input) and is written only when
every step worked. Removed or changed in the copy:
  metadata   author, last modifier, company, manager and the Comments property; slide titles and sheet names in the
             part list; custom properties other than sensitivity-label ones; the preview thumbnail; a workbook's
             saved absolute path
  comments   Word, PowerPoint and Excel comments (threaded ones too) with their author lists; Word comment anchors
  revisions  Word tracked changes are accepted: insertions stay, deletions go, format changes are applied
  slides     hidden slides, with every link that pointed at them; --strip-notes also removes all speaker notes
  cells      Excel text cells that start with = + - @ (or a tab or CR) get a leading apostrophe so that no tool reads
             them as a formula; real formulas are left alone
Kept: the sensitivity label (properties named MSIP_Label_* and the label info part). A scrub never removes a label, so
--keep-label is accepted for clarity and changes nothing.
Prints what changed; --json prints {"ok", "input", "output", "format", "changed", "changes", "label", "warnings"}.
Exit 0 done, 1 failed (no copy written), 2 usage. Macro-enabled, legacy and encrypted files are refused. Needs lxml.
"""
import argparse
import json
import os
import posixpath
import sys
import zipfile

from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # also under python -I
from render import REFUSED  # noqa: E402  the renderer's list of macro-enabled and legacy formats

MAX_UNPACKED = 256 << 20
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
# relationship types (by ending) that carry comments, their authors, change logs and the preview image
DROP_TYPES = ("/comments", "/commentAuthors", "/commentsExtended", "/commentsIds", "/commentsExtensible", "/people",
              "/threadedComment", "/person", "/authors", "/revisionHeaders", "/revisionLog", "/usernames", "/thumbnail")
TRACKED_DROP = ("moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd", "rPrChange", "pPrChange",
                "sectPrChange", "tblPrChange", "tblGridChange", "trPrChange", "tcPrChange", "tblPrExChange",
                "numberingChange", "cellIns", "cellDel", "cellMerge")
TRIGGERS = "=+-@\t\r"
UNTOUCHED = ("externalLinks", "embeddings", "customXml", "activeX")   # reported, not scrubbed


def neutralise(text):
    """The apostrophe that makes a text cell start with a trigger character unreadable as a formula."""
    return "'" + text if text and text[0] in TRIGGERS else text


def rels_name(part):
    d, b = posixpath.split(part)
    return posixpath.join(d, "_rels", b + ".rels")


def source_of(rels):
    d, b = posixpath.split(rels)
    return posixpath.join(posixpath.dirname(d), b[:-5])


def target(src, rel):
    if rel.get("TargetMode") == "External":
        return None
    t = rel.get("Target", "")
    return t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(src), t))


def local(e):
    return etree.QName(e).localname


class Pkg:
    """An Office Open XML package held in memory. Parsed parts are re-serialised only when marked dirty."""

    def __init__(self, path):
        if not zipfile.is_zipfile(path):
            raise ValueError("not an Office Open XML file (an encrypted or rights-protected file cannot be scrubbed)")
        with zipfile.ZipFile(path) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            if sum(i.file_size for i in infos) > MAX_UNPACKED:
                raise ValueError("refusing a package that unpacks to more than 256 MB")
            for i in infos:
                if i.filename.startswith(("/", "\\")) or ".." in i.filename.split("/") or "\\" in i.filename:
                    raise ValueError(f"refusing unsafe part name {i.filename!r}")
            self.order = [i.filename for i in infos]
            self.infos = {i.filename: i for i in infos}
            self.raw = {i.filename: z.read(i) for i in infos}
        if "[Content_Types].xml" not in self.raw:
            raise ValueError("not an Office Open XML package: [Content_Types].xml is missing")
        self.trees, self.dirty = {}, set()

    def tree(self, name):
        if name not in self.trees:
            self.trees[name] = etree.fromstring(self.raw[name], PARSER)
        return self.trees[name]

    def rel_files(self):
        return [n for n in self.raw if n.endswith(".rels")]

    def rels(self, src):
        rn = rels_name(src)
        return list(self.tree(rn).iter(PR + "Relationship")) if rn in self.raw else []

    def targets(self, src, suffix):
        return [t for r in self.rels(src) if r.get("Type", "").endswith(suffix) for t in [target(src, r)] if t in self.raw]

    def main(self):
        found = self.targets("", "/officeDocument")
        if not found:
            raise ValueError("no main document part in the package")
        return found[0]

    def drop_rels(self, pred):
        """Remove every relationship pred(src, rel, target) selects, plus the elements that point at it."""
        hit = []
        for rn in self.rel_files():
            src, root, gone = source_of(rn), self.tree(rn), set()
            for rel in list(root.iter(PR + "Relationship")):
                t = target(src, rel)
                if pred(src, rel, t):
                    gone.add(rel.get("Id"))
                    hit.append(t)
                    root.remove(rel)
            if gone:
                self.dirty.add(rn)
                if src in self.raw:
                    self.unlink(src, gone)
        return hit

    def unlink(self, part, ids):
        try:
            root = self.tree(part)
        except etree.XMLSyntaxError:
            return
        for e in [e for e in root.iter(etree.Element) if any(k.startswith(R) and v in ids for k, v in e.attrib.items())]:
            if e.getparent() is not None:
                e.getparent().remove(e)
                self.dirty.add(part)

    def reachable(self):
        seen, todo = set(), [""]
        while todo:
            src = todo.pop()
            for rel in self.rels(src):
                t = target(src, rel)
                if t and t not in seen:
                    seen.add(t)
                    todo.append(t)
        return seen

    def remove_part(self, name):
        for n in (name, rels_name(name)):
            self.raw.pop(n, None)
            self.trees.pop(n, None)
            self.dirty.discard(n)
        ct = self.tree("[Content_Types].xml")
        for o in list(ct.iter(CT + "Override")):
            if o.get("PartName") == "/" + name:
                ct.remove(o)
                self.dirty.add("[Content_Types].xml")

    def save(self, out):
        tmp = out + ".tmp"
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                for n in (n for n in self.order if n in self.raw):
                    data = (etree.tostring(self.trees[n], xml_declaration=True, encoding="UTF-8", standalone=True)
                            if n in self.dirty else self.raw[n])
                    zi = zipfile.ZipInfo(n, date_time=self.infos[n].date_time)
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    z.writestr(zi, data)
            os.replace(tmp, out)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


def blank_metadata(pkg):
    """-> number of fields cleared in core.xml and app.xml."""
    n = 0
    for part, names in (("docProps/core.xml", {"creator", "lastModifiedBy", "description"}), ("docProps/app.xml", {"Company", "Manager"})):
        if part not in pkg.raw:
            continue
        root = pkg.tree(part)
        for e in list(root.iter(etree.Element)):
            if local(e) in names and (e.text or "").strip():
                e.text, n = "", n + 1
                pkg.dirty.add(part)
            elif part.endswith("app.xml") and local(e) in {"HeadingPairs", "TitlesOfParts", "HiddenSlides"}:
                e.getparent().remove(e)    # slide titles and sheet names; Office rebuilds them on the next save
                n += 1
                pkg.dirty.add(part)
    return n


def keep_label_properties(pkg):
    """Drop custom properties that are not sensitivity-label ones. -> (kept, removed)."""
    part, kept, removed = "docProps/custom.xml", 0, 0
    if part in pkg.raw:
        root = pkg.tree(part)
        for p in [p for p in root if isinstance(p.tag, str)]:
            if p.get("name", "").startswith("MSIP_Label_"):
                kept += 1
            else:
                root.remove(p)
                removed += 1
                pkg.dirty.add(part)
    return kept, removed


def accept_revisions(root):
    """Accept every tracked change and drop comment anchors in one Word part. -> (changes accepted, anchors removed)."""
    n = anchors = 0
    for tr in [tr for tr in root.iter(W + "tr") if tr.find(W + "trPr/" + W + "del") is not None]:
        tr.getparent().remove(tr)
        n += 1
    for e in list(root.iter(W + "del", W + "moveFrom")):
        e.getparent().remove(e)
        n += 1
    for e in list(root.iter(*[W + t for t in TRACKED_DROP])):
        e.getparent().remove(e)
        n += 1
    for e in list(root.iter(W + "commentRangeStart", W + "commentRangeEnd")):
        e.getparent().remove(e)
        anchors += 1
    for e in list(root.iter(W + "commentReference")):
        run = e.getparent()
        gone = run if run is not None and run.tag == W + "r" else e
        gone.getparent().remove(gone)
        anchors += 1
    for e in list(root.iter(W + "ins", W + "moveTo")):
        par = e.getparent()
        n += 1
        if local(par) in ("rPr", "trPr"):     # a marker on a paragraph or row: nothing inside to keep
            par.remove(e)
            continue
        i = par.index(e)
        for child in list(e):
            par.insert(i, child)
            i += 1
        par.remove(e)
    return n, anchors


def word_pass(pkg, main):
    accepted = anchors = 0
    parts = [main] + [t for s in ("/header", "/footer", "/footnotes", "/endnotes") for t in pkg.targets(main, s)]
    for part in dict.fromkeys(parts):
        a, b = accept_revisions(pkg.tree(part))
        if a or b:
            pkg.dirty.add(part)
        accepted, anchors = accepted + a, anchors + b
    for st in pkg.targets(main, "/settings"):
        for e in list(pkg.tree(st).iter(W + "trackRevisions")):
            e.getparent().remove(e)
            pkg.dirty.add(st)
    return accepted


def hidden_slides(pkg, main):
    root = pkg.tree(main)
    gone = {t: r.get("Id") for r in pkg.rels(main) if r.get("Type", "").endswith("/slide")
            for t in [target(main, r)] if t in pkg.raw and pkg.tree(t).get("show") == "0"}
    ids = {e.get("id") for e in root.iter(P + "sldId") if e.get(R + "id") in gone.values()}
    pkg.drop_rels(lambda s, r, t: t in gone)
    for e in [e for e in root.iter(etree.Element) if local(e) == "sldId" and e.tag != P + "sldId" and e.get("id") in ids]:
        e.getparent().remove(e)     # the slide list inside PowerPoint sections
        pkg.dirty.add(main)
    return len(gone)


def excel_pass(pkg, main):
    """Neutralise text cells; drop the saved absolute path. -> cells changed."""
    bad = set()
    for part in pkg.targets(main, "/sharedStrings"):
        for i, si in enumerate(pkg.tree(part).findall(S + "si")):
            t = si.find(S + "t")
            t = si.find(S + "r/" + S + "t") if t is None else t
            if t is not None and neutralise(t.text or "") != (t.text or ""):
                t.text = neutralise(t.text)
                bad.add(i)
                pkg.dirty.add(part)
    cells = 0
    for part in pkg.targets(main, "/worksheet"):
        for c in pkg.tree(part).iter(S + "c"):
            kind = c.get("t")
            if kind == "s":
                v = c.find(S + "v")
                cells += v is not None and (v.text or "").strip().isdigit() and int(v.text) in bad
            elif kind in ("inlineStr", "str") and c.find(S + "f") is None:
                t = c.find(S + "is/" + S + "t") if kind == "inlineStr" else c.find(S + "v")
                if t is not None and neutralise(t.text or "") != (t.text or ""):
                    t.text = neutralise(t.text)
                    cells += 1
                    pkg.dirty.add(part)
    root = pkg.tree(main)
    for e in [e for e in root.iter(etree.Element) if local(e) == "absPath"]:
        node = e
        wrap = e.getparent().getparent() if local(e.getparent()) == "Choice" else None
        if wrap is not None and local(wrap) == "AlternateContent" and len(wrap) == 1 and len(wrap[0]) == 1:
            node = wrap
        node.getparent().remove(node)
        pkg.dirty.add(main)
    return int(cells)


def count_items(pkg, parts):
    n = 0
    for p in set(parts):
        try:
            n += sum(local(e) in {"comment", "cm", "threadedComment"} for e in pkg.tree(p).iter(etree.Element))
        except (KeyError, etree.XMLSyntaxError):
            pass
    return n


def scrub(src, out, strip_notes=False):
    ext = os.path.splitext(src)[1].lower()
    if ext in REFUSED:
        raise ValueError(f"refusing {ext}: macro-enabled or legacy format. Save a trusted copy as .docx/.pptx/.xlsx first.")
    if ext not in (".docx", ".pptx", ".xlsx"):
        raise ValueError(f"unsupported file type {ext or '(none)'}: expected .docx, .pptx or .xlsx")
    if os.path.splitext(out)[1].lower() != ext:
        raise ValueError(f"the copy must keep the {ext} extension")
    if os.path.normcase(os.path.realpath(src)) == os.path.normcase(os.path.realpath(out)):
        raise ValueError("--out must be a new file, never the input")
    pkg = Pkg(src)
    main, before = pkg.main(), pkg.reachable()
    # a sheet that has comments also has a legacy drawing holding them: drop that drawing relationship too
    legacy = {}
    for rn in pkg.rel_files():
        s = source_of(rn)
        if s in pkg.raw and any(r.get("Type", "").endswith("/comments") for r in pkg.rels(s)):
            try:
                legacy[s] = {e.get(R + "id") for e in pkg.tree(s).iter(etree.Element) if local(e) == "legacyDrawing"}
            except etree.XMLSyntaxError:
                pass

    def doomed(s, r, t):
        ty = r.get("Type", "")
        return ty.endswith(DROP_TYPES) or (ty.endswith("/vmlDrawing") and r.get("Id") in legacy.get(s, ())) or (
            strip_notes and ty.endswith("/notesSlide"))
    changes = {"thumbnail_removed": any(r.get("Type", "").endswith("/thumbnail") for r in pkg.rels(""))}
    changes["comments_removed"] = count_items(pkg, pkg.drop_rels(doomed))
    changes["hidden_slides_removed"] = hidden_slides(pkg, main) if ext == ".pptx" else 0
    gone = sorted(before - pkg.reachable())
    for part in gone:
        pkg.remove_part(part)
    changes["notes_removed"] = sum("/notesSlides/" in p for p in gone) if strip_notes else 0
    changes["parts_removed"] = gone
    changes["tracked_changes_accepted"] = word_pass(pkg, main) if ext == ".docx" else 0
    changes["cells_neutralised"] = excel_pass(pkg, main) if ext == ".xlsx" else 0
    changes["metadata_fields_cleared"] = blank_metadata(pkg)
    kept, removed = keep_label_properties(pkg)
    changes["custom_properties_removed"] = removed
    pkg.save(out)
    return {"ok": True, "input": src, "output": out, "format": ext[1:], "changed": bool(pkg.dirty or gone), "changes": changes,
            "label": {"properties_kept": kept, "info_part_kept": any(n.lower() == "clientmetadata/labelinfo.xml" for n in pkg.raw)},
            "warnings": sorted({u for p in pkg.raw for u in UNTOUCHED if f"/{u}/" in "/" + p})}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--strip-notes", action="store_true", help="also remove all speaker notes")
    ap.add_argument("--keep-label", action="store_true", help="accepted for clarity: the label is always kept")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        rep = scrub(a.file, a.out, a.strip_notes)
    except (ValueError, OSError, zipfile.BadZipFile, etree.XMLSyntaxError) as e:
        if a.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        print(f"SCRUB FAILED: {e}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        print(f"# scrubbed copy written to {a.out}; send that file, never the original")
        for k, v in rep["changes"].items():
            print(f"{k}: {v}")
        print(f"label kept: {rep['label']['properties_kept']} propert(ies), info part {rep['label']['info_part_kept']}")
        for w in rep["warnings"]:
            print(f"NOT SCRUBBED, check by hand: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
