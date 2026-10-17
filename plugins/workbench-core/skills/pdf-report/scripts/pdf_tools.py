#!/usr/bin/env python3
"""pdf_tools.py: read, merge, split, rotate, stamp, relabel, scrub and fill PDFs. Every command that writes makes a NEW file.

  python pdf_tools.py info   <in.pdf> [--json]
  python pdf_tools.py text   <in.pdf> [--pages 1-3,5] [--json]
  python pdf_tools.py merge  <a.pdf> <b.pdf> ... --out <x.pdf>
  python pdf_tools.py split  <in.pdf> --out <folder> [--ranges 1-3,4,5-9]        (default: one file per page)
  python pdf_tools.py rotate <in.pdf> --out <x.pdf> --degrees 90|180|270 [--pages 2,4-5]
  python pdf_tools.py stamp  <in.pdf> --out <x.pdf> --text DRAFT [--where center|top|bottom] [--pages 1-2]   (Edge draws it)
  python pdf_tools.py meta   <in.pdf> [--out <x.pdf> --title T --author A --subject S --keywords K]            (no flag: show)
  python pdf_tools.py scrub  <in.pdf> --out <x.pdf> [--json]
  python pdf_tools.py fields <in.pdf> [--json]
  python pdf_tools.py fill   <in.pdf> --out <x.pdf> --set name=value [--set ...] [--values file.json] [--png <folder>]

Safety rails: encrypted PDFs are refused (ask the owner for an unprotected copy); a PDF with a digital signature is refused by
every command that writes (any change breaks the signature); the input is never edited and --out must be a different file;
fill and stamp never draw a signature, and a form that needs signing is handed back for the user to sign. scrub removes the
document properties and XMP (except a sensitivity label) and LISTS embedded files, JavaScript and annotations: it never removes them.
Needs pypdf (BSD-3-Clause); text, stamp and page checks also need pypdfium2; stamp needs Edge. Never PyMuPDF (AGPL-3.0).
Exit: 0 done, 2 refused or failed (one line on stderr).
"""
import argparse
import html
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_pdf as chk  # noqa: E402

INFO_DROP = ("/Author", "/Creator", "/Producer", "/Subject", "/Keywords", "/CreationDate", "/ModDate", "/Trapped")


class ToolError(Exception):
    pass


def need(*mods):
    missing = [m for m in mods if not chk.have(m)]
    if missing:
        raise ToolError(f"{' and '.join({'PIL': 'Pillow'}.get(m, m) for m in missing)} {'are' if len(missing) > 1 else 'is'} not installed: {chk.SETUP}")


def res(x):
    return x.get_object() if hasattr(x, "get_object") else x


def is_signed(reader):
    if "/Perms" in reader.trailer["/Root"]:
        return True
    return any(f.get("/FT") == "/Sig" and f.get("/V") for f in (reader.get_fields() or {}).values())


def open_reader(path, writing=False):
    """A PdfReader; encrypted files are always refused, signed ones when the command writes."""
    need("pypdf")
    from pypdf import PdfReader
    if not os.path.isfile(path):
        raise ToolError(f"no such file: {path}")
    try:
        r = PdfReader(path)
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"{path}: not a readable PDF ({type(e).__name__})")
    if r.is_encrypted:
        raise ToolError(f"{path} is encrypted: ask the owner for an unprotected copy (this tool never guesses or asks for a password)")
    if writing and is_signed(r):
        raise ToolError(f"{path} carries a digital signature: any change breaks it, so nothing was written. Work on an unsigned copy")
    return r


def out_path(a, src):
    out = pathlib.Path(a.out).resolve()
    if out == pathlib.Path(src).resolve():
        raise ToolError("--out must be a different file: the input is never edited")
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def parse_pages(spec, n):
    """'1-3,5' -> [0, 1, 2, 4] (zero-based); every page when spec is empty."""
    if not spec:
        return list(range(n))
    idx = []
    for part in spec.split(","):
        m = re.fullmatch(r"\s*(\d+)(?:\s*-\s*(\d+))?\s*", part)
        if not m:
            raise ToolError(f"bad page list {spec!r}: use 1-3,5")
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        if not 1 <= lo <= hi <= n:
            raise ToolError(f"pages {part.strip()} are outside 1-{n}")
        idx += range(lo - 1, hi)
    return idx


def emit(a, obj, lines):
    print(json.dumps(obj, indent=1, ensure_ascii=False) if getattr(a, "json", False) else "\n".join(lines))


def write(w, out):
    with open(out, "wb") as f:
        w.write(f)


# ------------------------------------------------------------------------------------------------------------ reading
def fields_of(r):
    rows = []
    for name, f in (r.get_fields() or {}).items():
        ft, flags = str(f.get("/FT") or ""), int(f.get("/Ff") or 0)
        kind = {"/Tx": "text", "/Ch": "choice", "/Sig": "signature"}.get(ft, ft)
        if ft == "/Btn":
            kind = "pushbutton" if flags & (1 << 16) else "radio" if flags & (1 << 15) else "checkbox"
        v = f.get("/V")
        row = {"name": name, "type": kind, "value": None if v is None else str(v), "readonly": bool(flags & 1)}
        if kind in ("checkbox", "radio"):
            row["states"] = [str(s) for s in f.get("/_States_", [])]
        if kind == "choice":
            row["options"] = [str(o) for o in f.get("/Opt", [])]
        rows.append(row)
    return rows


def survey(r):
    """What a reader of the file should know before it leaves: scripts, attachments, annotations, labels, XMP."""
    root = r.trailer["/Root"]
    js = 0
    if "/OpenAction" in root and "/JS" in str(res(root["/OpenAction"])):
        js += 1
    js += sum(1 for p in r.pages for a in (p.get("/Annots") or []) if "/JS" in str(res(res(a).get("/A", ""))))
    names = res(root.get("/Names")) or {}
    if "/JavaScript" in names:
        js += 1
    emb = 0
    if "/EmbeddedFiles" in names:
        emb = len(res(names["/EmbeddedFiles"]).get("/Names", [])) // 2
    emb += sum(1 for p in r.pages for a in (p.get("/Annots") or []) if res(a).get("/Subtype") == "/FileAttachment")
    annots = {}
    for p in r.pages:
        for a in p.get("/Annots") or []:
            st = str(res(a).get("/Subtype", "?")).lstrip("/")
            annots[st] = annots.get(st, 0) + 1
    xmp = res(root.get("/Metadata"))
    xmp_bytes = xmp.get_data() if xmp is not None else b""
    meta = {str(k).lstrip("/"): str(v) for k, v in (r.metadata or {}).items()}
    labels = sorted(k for k in meta if k.startswith("MSIP_Label_")) + (["xmp:MSIP_Label_"] if b"MSIP_Label_" in xmp_bytes else [])
    return {"javascript": js, "embedded_files": emb, "annotations": annots, "has_xmp": bool(xmp_bytes), "label_keys": labels, "metadata": meta}


def cmd_info(a):
    need("pypdf")
    from pypdf import PdfReader
    r = PdfReader(a.pdf)
    if r.is_encrypted:
        return emit(a, {"file": a.pdf, "encrypted": True}, [f"{a.pdf}: encrypted (not opened)"])
    box = r.pages[0].mediabox
    w, h = float(box.width), float(box.height)
    s = survey(r)
    info = {"file": a.pdf, "pages": len(r.pages), "page_size_pt": [round(w, 1), round(h, 1)],
            "page_size_mm": [round(w / 72 * 25.4), round(h / 72 * 25.4)], "encrypted": False, "signed": is_signed(r),
            "tagged": bool((res(r.trailer["/Root"].get("/MarkInfo")) or {}).get("/Marked")), "language": str(r.trailer["/Root"].get("/Lang", "")),
            "form_fields": len(r.get_fields() or {}), "outline_entries": len(chk.outline_titles(r.outline)), **s}
    emit(a, info, [f"{k}: {v}" for k, v in info.items()])


def cmd_text(a):
    need("pypdf", "pypdfium2")
    n = len(open_reader(a.pdf).pages)
    want = parse_pages(a.pages, n)
    pages = chk.scan_pages(a.pdf, ink=False)
    rows = [{"page": i + 1, "text": pages[i]["text"]} for i in want]
    none = [r["page"] for r in rows if not r["text"].strip()]
    lines = [f"--- page {r['page']} ---\n{r['text']}" for r in rows]
    if none:
        lines.append(f"# no text layer on page(s) {none}: scanned or image-only. Reading them needs OCR (RapidOCR, optional).")
    emit(a, {"pages": rows, "no_text": none}, lines)


def cmd_fields(a):
    rows = fields_of(open_reader(a.pdf))
    emit(a, {"file": a.pdf, "fields": rows}, [f"{len(rows)} field(s)"] + [
        f"{r['name']}  [{r['type']}]  value={r['value']!r}" + (f"  on-state(s)={r['states']}" if r.get("states") else "")
        + (f"  options={r['options']}" if r.get("options") else "") + ("  (read-only)" if r["readonly"] else "") for r in rows])


# ------------------------------------------------------------------------------------------------------------ writing
def cmd_merge(a):
    from pypdf import PdfWriter
    if len(a.inputs) < 2:
        raise ToolError("merge needs at least two PDFs")
    out = out_path(a, a.inputs[0])
    w = PdfWriter()
    for f in a.inputs:
        if pathlib.Path(f).resolve() == out:
            raise ToolError("--out must differ from every input")
        w.append(open_reader(f, writing=True), import_outline=True)
    write(w, out)
    print(f"merged {len(a.inputs)} files, {len(w.pages)} pages -> {out}")


def cmd_split(a):
    from pypdf import PdfWriter
    r = open_reader(a.pdf, writing=True)
    n = len(r.pages)
    spec = a.ranges or ",".join(str(i) for i in range(1, n + 1))
    folder = pathlib.Path(a.out).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    made = []
    for part in spec.split(","):
        idx = parse_pages(part, n)
        w = PdfWriter()
        for i in idx:
            w.add_page(r.pages[i])
        f = folder / f"{pathlib.Path(a.pdf).stem}-{part.strip().replace(' ', '')}.pdf"
        write(w, f)
        made.append(str(f))
    print("\n".join(made))


def cmd_rotate(a):
    from pypdf import PdfWriter
    if a.degrees % 90:
        raise ToolError("--degrees must be 90, 180 or 270")
    r = open_reader(a.pdf, writing=True)
    out = out_path(a, a.pdf)
    w = PdfWriter(clone_from=r)
    for i in parse_pages(a.pages, len(w.pages)):
        w.pages[i].rotate(a.degrees)
    write(w, out)
    print(f"rotated {len(parse_pages(a.pages, len(w.pages)))} page(s) by {a.degrees} -> {out}")


STAMP_CSS = {
    "center": "position:fixed;inset:0;display:flex;align-items:center;justify-content:center;font-size:96pt;letter-spacing:.05em;"
              "color:rgba(90,102,114,.28);transform:rotate(-35deg);white-space:nowrap;",
    "top": "position:fixed;top:8mm;left:0;right:0;text-align:center;font-size:10pt;letter-spacing:.08em;color:#5a6672;",
    "bottom": "position:fixed;bottom:8mm;left:0;right:0;text-align:center;font-size:10pt;letter-spacing:.08em;color:#5a6672;",
}


def cmd_stamp(a):
    need("pypdf")
    import build_pdf
    from pypdf import PdfReader, PdfWriter
    import io
    r = open_reader(a.pdf, writing=True)
    out = out_path(a, a.pdf)
    w = PdfWriter(clone_from=r)
    overlays = {}
    todo = parse_pages(a.pages, len(w.pages))
    for i in todo:
        box = w.pages[i].mediabox
        size = (round(float(box.width), 1), round(float(box.height), 1))
        if size not in overlays:
            doc = (f'<!doctype html><html><head><meta charset="utf-8"><style>@page {{ size: {size[0]}pt {size[1]}pt; margin: 0; }}'
                   f'html,body {{ margin: 0; background: none; font-family: "Segoe UI", Arial, sans-serif; -webkit-print-color-adjust: exact; '
                   f'print-color-adjust: exact; }} div {{ {STAMP_CSS[a.where]} }}</style></head><body><div>{html.escape(a.text)}</div></body></html>')
            overlays[size] = PdfReader(io.BytesIO(build_pdf.render_html(doc))).pages[0]
        w.pages[i].merge_page(overlays[size])
    write(w, out)
    print(f"stamped {len(todo)} page(s) with {a.text!r} -> {out}")


def cmd_meta(a):
    from pypdf import PdfWriter
    r = open_reader(a.pdf, writing=bool(a.out))
    sets = {f"/{k.title()}": getattr(a, k) for k in ("title", "author", "subject", "keywords") if getattr(a, k)}
    if not sets:
        return emit(a, {"metadata": {str(k).lstrip("/"): str(v) for k, v in (r.metadata or {}).items()}},
                    [f"{str(k).lstrip('/')}: {v}" for k, v in (r.metadata or {}).items()] or ["# no document properties"])
    if not a.out:
        raise ToolError("--out is required to change properties (a new file is written)")
    out = out_path(a, a.pdf)
    w = PdfWriter(clone_from=r)
    w.add_metadata(sets)
    write(w, out)
    print(f"set {', '.join(k.lstrip('/') for k in sets)} -> {out}")


def cmd_scrub(a):
    from pypdf import PdfWriter
    from pypdf.generic import NameObject
    r = open_reader(a.pdf, writing=True)
    out = out_path(a, a.pdf)
    s = survey(r)
    meta = {str(k): str(v) for k, v in (r.metadata or {}).items()}
    keep = {k: v for k, v in meta.items() if k in ("/Title",) or k.lstrip("/").startswith("MSIP_Label_")}
    removed = sorted(k.lstrip("/") for k in meta if k not in keep)
    warnings = []
    w = PdfWriter(clone_from=r)
    w.metadata = keep
    root = w._root_object
    if "/Metadata" in root:
        if any("MSIP_Label_" in x for x in s["label_keys"] if x.startswith("xmp:")):
            warnings.append("the XMP packet carries a sensitivity label, so it was kept: it may also name an author (read it)")
        else:
            del root[NameObject("/Metadata")]
            removed.append("XMP")
    for what, n in (("JavaScript", s["javascript"]), ("embedded file(s)", s["embedded_files"])):
        if n:
            warnings.append(f"{n} {what} found and NOT removed: look at them before sending")
    loose = {k: n for k, n in s["annotations"].items() if k not in ("Link", "Widget")}      # links and form widgets are the document itself
    if loose:
        warnings.append(f"annotations present and NOT removed: {loose}")
    write(w, out)
    after = open_reader(str(out))
    left = [k for k in (after.metadata or {}) if k in INFO_DROP]
    raw = pathlib.Path(out).read_bytes()
    left += [m for m in ("HeadlessChrome", "Skia/PDF") if m.encode() in raw]
    res = {"ok": not left, "out": str(out), "removed": removed, "kept": sorted(k.lstrip("/") for k in keep), "warnings": warnings,
           "javascript": s["javascript"], "embedded_files": s["embedded_files"], "annotations": s["annotations"], "left_over": left}
    emit(a, res, [f"{'ok' if res['ok'] else 'NOT CLEAN'}: removed {removed or 'nothing'}; kept {res['kept'] or 'nothing'} -> {out}"]
         + [f"warning: {x}" for x in warnings] + ([f"left over: {left}"] if left else []))
    if left:
        raise SystemExit(1)


def on_state(row):
    return next((s for s in row.get("states", []) if s != "/Off"), "/Yes")


def cmd_fill(a):
    from pypdf import PdfWriter
    r = open_reader(a.pdf, writing=True)
    out = out_path(a, a.pdf)
    rows = {x["name"]: x for x in fields_of(r)}
    if not rows:
        raise ToolError("no form fields: this is a flat form and cannot be filled by name (see references/forms.md)")
    values = {}
    for kv in a.set or []:
        k, sep, v = kv.partition("=")
        if not sep:
            raise ToolError(f"--set wants name=value, got {kv!r}")
        values[k] = v
    if a.values:
        values.update(json.loads(pathlib.Path(a.values).read_text(encoding="utf-8")))
    if not values:
        raise ToolError("nothing to fill: give --set name=value or --values file.json")
    unknown = [k for k in values if k not in rows]
    if unknown:
        raise ToolError(f"no such field: {unknown}; the form has {sorted(rows)}")
    sig = [k for k in values if rows[k]["type"] == "signature"]
    if sig:
        raise ToolError(f"{sig}: a signature field is never filled by this tool: the person who signs does it")
    for k, v in list(values.items()):
        if rows[k]["type"] in ("checkbox", "radio"):
            values[k] = on_state(rows[k]) if str(v).lower() in ("yes", "true", "on", "1", "x", "checked") else (
                "/Off" if str(v).lower() in ("no", "false", "off", "0", "") else (v if str(v).startswith("/") else "/" + str(v)))
    w = PdfWriter(clone_from=r)
    for page in w.pages:
        w.update_page_form_field_values(page, values, auto_regenerate=False)
    w.set_need_appearances_writer(True)
    write(w, out)
    print(f"filled {len(values)} field(s) in a copy -> {out}")
    if a.png:       # office-render's render.py draws no form fields, so the copy is rendered here with form support on
        need("pypdfium2")
        import pypdfium2 as pdfium
        folder = pathlib.Path(a.png)
        folder.mkdir(parents=True, exist_ok=True)
        doc = pdfium.PdfDocument(str(out))
        doc.init_forms()
        for i in range(len(doc)):
            png = folder / f"{out.stem}-{i + 1:02d}.png"
            doc[i].render(scale=110 / 72, may_draw_forms=True).to_pil().save(png)
            print(png)
        doc.close()
    print("Check the copy page by page. A form that has to be signed is for you to sign: this tool never signs or stamps a signature.")


# ------------------------------------------------------------------------------------------------------------- command line
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *args, out=False, **flags):
        p = sub.add_parser(name)
        for x in args:
            p.add_argument(x)
        if out:
            p.add_argument("--out", required=True if out is True else False)
        for f, kw in flags.items():
            p.add_argument("--" + f.replace("_", "-"), **kw)
        p.set_defaults(fn=fn)
        return p
    J = {"action": "store_true"}
    add("info", cmd_info, "pdf", json=J)
    add("text", cmd_text, "pdf", pages={}, json=J)
    add("fields", cmd_fields, "pdf", json=J)
    p = add("merge", cmd_merge, out=True)
    p.add_argument("inputs", nargs="+")
    add("split", cmd_split, "pdf", out=True, ranges={})
    add("rotate", cmd_rotate, "pdf", out=True, degrees={"type": int, "required": True}, pages={})
    add("stamp", cmd_stamp, "pdf", out=True, text={"required": True}, where={"choices": ("center", "top", "bottom"), "default": "center"}, pages={})
    add("meta", cmd_meta, "pdf", out="optional", title={}, author={}, subject={}, keywords={}, json=J)
    add("scrub", cmd_scrub, "pdf", out=True, json=J)
    add("fill", cmd_fill, "pdf", out=True, set={"action": "append"}, values={}, png={})
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    chk.reexec_under_knowledge_python(["pypdf", "pypdfium2"] if a.cmd == "text" else ["pypdf"])
    try:
        a.fn(a)
    except ToolError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    except ImportError as e:      # a package imported inside a command: one line naming it, never a traceback
        print(f"REFUSED: {({'PIL': 'Pillow'}).get(e.name, e.name) or e} is not installed: {chk.SETUP}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError) as e:
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
