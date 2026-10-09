---
name: office-xlsx
description: "Build or edit Excel workbooks (.xlsx) with openpyxl like a careful analyst: live formulas, input colour convention, named styles; recalculate and check for formula errors. Use for \"make a spreadsheet\", \"build a model\", \"add a summary sheet\", \"fix this workbook\"."
when_to_use: "ALWAYS load before creating or editing an Excel workbook, even a small one."
---

# office-xlsx

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it
> appears unreplaced (the skill was copied in without the plugin), use `py -3` on Windows and
> `python3` on Linux, macOS and WSL, never the Microsoft Store `python` stub.

Library and CLI: `scripts/xlsx_kit.py`. Setup once:
`"${user_config.python}" -m pip install --user -r "${CLAUDE_SKILL_DIR}/requirements.txt"`.

## Rules for a workbook people can trust
1. **Keep it live.** Whatever Python works out, the workbook should be able to work out again:
   put the calculation in the cell as an expression over the cells it depends on, so a reader who
   changes one assumption sees every dependent number move. A sheet of pasted numbers is a
   snapshot, not a model.
2. **Inputs separate from calculations.** Put assumptions in clearly labelled input cells (or an
   `Inputs` sheet) and reference them; no magic numbers inside formulas.
3. **Make each cell's role visible.** `style` gives typed numbers the `Input` style, calculations
   the `Formula` style and references to other sheets the `Link` style, each with its own font
   colour, and marks the header row and total rows. A reviewer can then tell at a glance which
   cells are meant to be edited and which are derived. Use the organisation's own template styles
   instead when it has them.
4. **Readable structure:** one header row, frozen panes below it, sensible column widths, number
   formats set per column (`#,##0`, `0.0%`, dates as dates), no merged cells inside data.
5. **Constrain inputs:** dropdowns for categorical inputs (`add_list_validation`).
6. **Portable functions:** prefer functions every engine has (INDEX/MATCH over newer dynamic-array
   functions) unless the user's Excel version is known to support them. Functions newer than Excel
   2007 (XLOOKUP, IFS, TEXTJOIN, FILTER, SORT, STDEV.S and so on) must be stored with a prefix
   (`_xlfn.XLOOKUP`, `_xlfn._xlws.FILTER`), or Excel shows `#NAME?` until someone re-enters the cell.
   `prefix_new_functions(wb)` (and the `style` command) adds it; `check` flags any left bare. LET and
   LAMBDA also need `_xlpm.` on their parameter names, so they are reported, not rewritten: enter
   them in Excel or use helper cells. A spilling formula written this way may open with an implicit
   `@`: prefer non-spilling forms, or set it in Excel.
7. **Editing an existing workbook:** first run
   `"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/xlsx_kit.py" risk book.xlsx`. It saves a
   throwaway copy with openpyxl and compares the parts (drawings, shapes, pictures, charts, comments,
   threaded comments, pivot tables and caches, slicers, timelines, form controls, sparklines). If
   anything would be lost it says so loudly and exits 3; `style` refuses in that case unless you pass
   `--accept-loss --out <new file>`. Load it normally (never save a workbook opened with
   `data_only=True`: that replaces formulas with values), change only what was asked, and save to a
   new file name unless told otherwise.
8. **Macro-enabled and legacy files are refused** (`.xlsm`, `.xltm`, `.xls` and their Word and
   PowerPoint equivalents): they can carry code. Ask the user to save a trusted copy as `.xlsx` in
   Excel (which drops the macros) and work on that.

## Build
Write a short Python script with openpyxl for the content, then apply the conventions:
```python
import sys; sys.path.insert(0, r"${CLAUDE_SKILL_DIR}/scripts")
from openpyxl import Workbook
from xlsx_kit import style_workbook, add_list_validation, prefix_new_functions
wb = Workbook(); ws = wb.active; ws.title = "Model"
ws.append(["Item", "Units", "Price", "Revenue"])
ws.append(["Widgets", 120, 4.5, "=B2*C2"])
ws.append(["Total", "=SUM(B2:B2)", None, "=SUM(D2:D2)"])
add_list_validation(ws, "E2:E50", ["Low", "Medium", "High"], prompt="Risk level")
style_workbook(wb)        # colours, header, totals, freeze panes, widths
for cell, note in prefix_new_functions(wb):   # _xlfn. prefixes; notes for LET/LAMBDA
    print(cell, note)
wb.save("model.xlsx")
```
Or style an existing file: `"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/xlsx_kit.py" style in.xlsx --out out.xlsx`.

## Check before handing over
openpyxl writes formulas without calculating them, so the file has no values until a spreadsheet
engine recalculates it (pandas, previews and some viewers then show blanks).
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/xlsx_kit.py" check model.xlsx --recalc auto
```
- `--recalc excel` (Windows) opens the workbook **read-only** in Excel through COM with macros
  force-disabled, runs a full calculation, saves the result to a temporary copy and then replaces
  the original, so cached values are real Excel results. If the user has Excel open, the script
  works inside their instance without hiding or closing it. `libreoffice` converts through
  `soffice --headless` (values may differ for functions LibreOffice lacks). `auto` tries Excel,
  then LibreOffice. If automation is blocked by policy, say so; do not work around it.
- It reports formula errors (`#DIV/0!`, `#REF!`, `#NAME?`, ...), formulas that still have no value,
  numbers typed into a column of formulas, and newer functions missing their `_xlfn.` prefix. Exit code 1 if anything is found.
- Zero errors means the formulas evaluate, not that they are right: spot-check a few results by
  hand and say which you checked.

Then render it for a visual pass (column widths, cut-off text, print layout):
`"${user_config.python}" "${CLAUDE_SKILL_DIR}/../office-render/scripts/render.py" model.xlsx --out render/`
and read every page.

## Workbooks with shapes, pivots or slicers
openpyxl cannot carry everything (`risk` shows what). Make those edits in Excel itself, through COM
with the same safety pattern the recalc step uses: macros force-disabled before the file opens, the
original opened read-only, the result saved under a new name, and the user's own Excel never hidden
or closed.
```powershell
$a = New-Object -ComObject Excel.Application; $own = $a.Workbooks.Count -eq 0; $prev = $a.AutomationSecurity
$a.AutomationSecurity = 3; if ($own) { $a.Visible = $false; $a.DisplayAlerts = $false }
try { $wb = $a.Workbooks.Open($env:XLSX_IN, 0, $true)
      $wb.Worksheets.Item("Model").Range("B2").Formula2 = "=XLOOKUP(A2,Inputs!A:A,Inputs!B:B)"
      $wb.SaveAs($env:XLSX_OUT, 51); $wb.Close($false) }
finally { $a.AutomationSecurity = $prev; if ($own) { $a.Quit() }; [void][Runtime.InteropServices.Marshal]::ReleaseComObject($a) }
```
Pass the paths in `XLSX_IN` and `XLSX_OUT`, never inside the script text. `Formula2` writes a
formula the way a user would type it, so newer functions and spills work. Pivot tables refresh with
`$wb.RefreshAll()`. If COM automation is blocked by policy, ask the user to make the change in Excel
(or the Claude for Excel add-in, if the tenant allows it); don't work around it.

## Before it leaves the organisation
Render check first (section above), then scrub a copy and send only the copy:
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/../office-render/scripts/scrub.py" book.xlsx --out book-send.xlsx --json
```
It removes comments (threaded ones too), author and company names, the saved file path and the preview image. Text cells that start with `=`, `+`, `-` or `@` get a leading apostrophe so nothing reads them as formulas; real formulas stay. The sensitivity label stays. Details and limits: the office-render skill.

## Starter workbooks
`${CLAUDE_SKILL_DIR}/templates/traceability-matrix.json` and `${CLAUDE_SKILL_DIR}/templates/raid-log.json` are specs for
`"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/xlsx_kit.py" from-spec <spec.json> <new.xlsx>` (sheets, dropdowns, live summary formulas,
`style` applied). Formulas show values once the workbook is opened in Excel. Fill the `<placeholders>` and edit the rows.

## Alternatives
The Claude for Excel add-in (if your tenant allows it) works inside Excel directly; Anthropic's
`document-skills` plugin is an optionally installed, separately licensed alternative. See
`THIRD-PARTY.md`.
