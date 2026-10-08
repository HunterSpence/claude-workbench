#!/usr/bin/env python3
"""xlsx_kit.py: spreadsheet conventions and checks on top of openpyxl.

  python xlsx_kit.py style <book.xlsx> [--out <new.xlsx>] [--header-row 1]
      named styles: Input (blue), Formula (black), Link (green, cross-sheet), Header, Total;
      freeze panes under the header; approximate column widths. Every sheet.
  python xlsx_kit.py check <book.xlsx> [--recalc auto|excel|libreoffice|none] [--json]
      optional recalculation, then: formula errors (#DIV/0!, #REF!, ...), formulas with no
      calculated value, and numbers typed into a column of formulas. Exit 1 if anything is wrong.

As a library: from xlsx_kit import style_workbook, add_list_validation, check
"""
import argparse, json, os, pathlib, shutil, subprocess, sys, tempfile

from openpyxl import load_workbook
from openpyxl.styles import Border, Font, NamedStyle, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ERRORS = {"#DIV/0!", "#REF!", "#NAME?", "#VALUE!", "#N/A", "#NUM!", "#NULL!", "#SPILL!", "#CALC!", "#GETTING_DATA"}
THIN = Side(style="thin", color="808080")


def _styles():
    s = {
        "Input": NamedStyle("Input", font=Font(color="0000FF")),
        "Formula": NamedStyle("Formula", font=Font(color="000000")),
        "Link": NamedStyle("Link", font=Font(color="008000")),
        "Header": NamedStyle("Header", font=Font(bold=True), fill=PatternFill("solid", fgColor="D9E1F2"),
                             border=Border(bottom=THIN)),
        "Total": NamedStyle("Total", font=Font(bold=True), border=Border(top=THIN)),
    }
    return s


def register_styles(wb):
    have = set(wb.named_styles)
    for name, st in _styles().items():
        if name not in have:
            wb.add_named_style(st)


def kind(cell):
    v = cell.value
    if isinstance(v, str) and v.startswith("="):
        return "Link" if "!" in v else "Formula"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return "Input"
    return None


def style_workbook(wb, header_row=1, freeze=True, widths=True):
    """Apply the colour convention by cell content. Number formats and fills you set stay;
    only the font colour and header/total styling come from here."""
    register_styles(wb)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.row == header_row and c.value is not None:
                    c.style = "Header"
                    continue
                k = kind(c)
                if k:
                    fmt = c.number_format
                    c.style = k
                    c.number_format = fmt
                    if isinstance(c.value, str) and c.value.upper().startswith(("=SUM(", "=SUBTOTAL(")) and \
                            str(ws.cell(c.row, 1).value or "").strip().lower().startswith("total"):
                        c.style, c.number_format = "Total", fmt
        if freeze and ws.max_row > header_row:
            ws.freeze_panes = ws.cell(header_row + 1, 1).coordinate
        if widths:
            for col in ws.iter_cols():
                longest = max((len(str(c.value)) for c in col if c.value is not None and not str(c.value).startswith("=")), default=8)
                ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(10, longest + 2), 60)
    return wb


def add_list_validation(ws, cell_range, options, prompt=None):
    """Dropdown restricted to `options` (inline list; keep under 255 characters in total)."""
    dv = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=True,
                        showErrorMessage=True, errorTitle="Not allowed", error="Pick a value from the list.")
    if prompt:
        dv.promptTitle, dv.prompt, dv.showInputMessage = "Input", prompt, True
    ws.add_data_validation(dv)
    dv.add(cell_range)
    return dv


# Macro-enabled and legacy binary formats are refused: they can carry code. Convert a trusted copy first.
REFUSED = {".xlsm", ".xltm", ".docm", ".dotm", ".pptm", ".potm", ".doc", ".xls", ".ppt", ".rtf"}


def refuse_risky(path):
    ext = pathlib.Path(path).suffix.lower()
    if ext in REFUSED:
        raise ValueError(f"refusing {ext}: macro-enabled or legacy format. Open a trusted copy in Excel, save it as "
                         f".xlsx (macros are dropped), and work on that.")


# Recalculation through Excel. Paths travel in environment variables. Macros are force-disabled
# (AutomationSecurity = 3) before the workbook opens, and it opens READ-ONLY; the recalculated copy
# is saved to a new file that replaces the original only after Excel succeeds. If the user already has
# Excel open, COM attaches to their instance: we restore AutomationSecurity, touch only our
# workbook, and never hide or quit their Excel.
PS_RECALC = ("$a = New-Object -ComObject Excel.Application; $own = $a.Workbooks.Count -eq 0; "
             "$prev = $a.AutomationSecurity; $a.AutomationSecurity = 3; "
             "if ($own) { $a.Visible = $false; $a.DisplayAlerts = $false }; try { "
             "$d = $a.Workbooks.Open($env:XLSX_IN, 0, $true); $a.CalculateFull(); $d.SaveAs($env:XLSX_OUT, 51); $d.Close($false) } "
             "finally { $a.AutomationSecurity = $prev; if ($own) { $a.Quit() }; "
             "[void][Runtime.InteropServices.Marshal]::ReleaseComObject($a) }")


def recalc_excel(path, timeout=240):
    if os.name != "nt":
        raise RuntimeError("Excel COM needs Windows")
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "recalc.xlsx")
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_RECALC],
                           env=dict(os.environ, XLSX_IN=os.path.abspath(path), XLSX_OUT=out),
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0 or not os.path.exists(out):
            raise RuntimeError("Excel recalculation failed: " + (r.stderr or r.stdout).strip()[:300])
        shutil.copyfile(out, path)


def recalc_libreoffice(path, timeout=240):
    exe = shutil.which("soffice") or shutil.which("libreoffice") or \
        next((p for p in (r"C:\Program Files\LibreOffice\program\soffice.exe",) if os.path.exists(p)), None)
    if not exe:
        raise RuntimeError("LibreOffice (soffice) not found")
    with tempfile.TemporaryDirectory() as profile, tempfile.TemporaryDirectory() as out:
        subprocess.run([exe, "-env:UserInstallation=" + pathlib.Path(profile).as_uri(), "--headless",
                        "--convert-to", "xlsx", "--outdir", out, os.path.abspath(path)],
                       capture_output=True, text=True, timeout=timeout)
        made = os.path.join(out, pathlib.Path(path).stem + ".xlsx")
        if not os.path.exists(made):
            raise RuntimeError("LibreOffice did not produce a workbook")
        shutil.copy2(made, path)


def recalc(path, engine="auto"):
    refuse_risky(path)
    if engine == "none":
        return "none"
    order = {"auto": ("excel", "libreoffice"), "excel": ("excel",), "libreoffice": ("libreoffice",)}[engine]
    errs = []
    for name in order:
        try:
            (recalc_excel if name == "excel" else recalc_libreoffice)(path)
            return name
        except Exception as e:
            errs.append(f"{name}: {e}")
    raise RuntimeError("; ".join(errs))


def check(path):
    """Problems as dicts: kind (error|uncalculated|hardcoded), sheet, cell, detail."""
    wf = load_workbook(path)                    # formulas
    wv = load_workbook(path, data_only=True)    # cached values written by the last calculation
    out = []
    for ws in wf.worksheets:
        vs = wv[ws.title]
        cols = {}
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                cached = vs[c.coordinate].value
                is_formula = isinstance(v, str) and v.startswith("=")
                if isinstance(cached, str) and cached in ERRORS:
                    out.append({"kind": "error", "sheet": ws.title, "cell": c.coordinate,
                                "detail": f"{cached}" + (f" from {v}" if is_formula else "")})
                elif is_formula and cached is None:
                    out.append({"kind": "uncalculated", "sheet": ws.title, "cell": c.coordinate, "detail": v})
                if is_formula or (isinstance(v, (int, float)) and not isinstance(v, bool)):
                    cols.setdefault(c.column, []).append((c.row, is_formula, c.coordinate))
        for cells in cols.values():   # a typed number sitting between formulas in the same column
            frows = [r for r, f, _ in cells if f]
            if len(frows) >= 3:
                for r, f, coord in cells:
                    if not f and frows[0] < r < frows[-1]:
                        out.append({"kind": "hardcoded", "sheet": ws.title, "cell": coord,
                                    "detail": "number typed into a column of formulas; should it be a formula?"})
    return out


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("style")
    p.add_argument("book")
    p.add_argument("--out")
    p.add_argument("--header-row", type=int, default=1)
    p = sub.add_parser("check")
    p.add_argument("book")
    p.add_argument("--recalc", choices=("auto", "excel", "libreoffice", "none"), default="none")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        refuse_risky(a.book)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    if a.cmd == "style":
        wb = load_workbook(a.book)
        style_workbook(wb, a.header_row)
        wb.save(a.out or a.book)
        print(f"styled {a.out or a.book}")
        return 0
    used = "none"
    if a.recalc != "none":
        try:
            used = recalc(a.book, a.recalc)
        except RuntimeError as e:
            print(f"RECALC FAILED ({e}); checking cached values as they are", file=sys.stderr)
    problems = check(a.book)
    if a.json:
        print(json.dumps({"recalculated_by": used, "problems": problems}, indent=1))
    else:
        print(f"recalculated by: {used}")
        for p in problems:
            print(f"{p['kind']:<13}{p['sheet']}!{p['cell']}  {p['detail']}")
        n = {k: sum(1 for p in problems if p["kind"] == k) for k in ("error", "uncalculated", "hardcoded")}
        print(f"{n['error']} error(s), {n['uncalculated']} uncalculated, {n['hardcoded']} possible hard-coded value(s)")
        if n["uncalculated"]:
            print("Uncalculated formulas show as empty to pandas, previews and some viewers: recalc with Excel or LibreOffice.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
