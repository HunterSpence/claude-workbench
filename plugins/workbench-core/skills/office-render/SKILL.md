---
name: office-render
description: Render a .pptx, .docx, .xlsx or .pdf to one PNG per slide or page so Claude can look at it - through real PowerPoint/Word/Excel on Windows, or LibreOffice headless, then pypdfium2. Use for visual QA of any generated Office file ("does the deck look right", "check the layout", "render this document"), and as the last step of office-pptx and office-xlsx.
---

# office-render

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it
> appears unreplaced (the skill was copied in without the plugin), use `py -3` on Windows and
> `python3` on Linux, macOS and WSL, never the Microsoft Store `python` stub.

```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/render.py" <file> --out <dir> [--engine auto|office|libreoffice] [--dpi 110] [--first N]
```
Setup once: `"${user_config.python}" -m pip install --user -r "${CLAUDE_SKILL_DIR}/requirements.txt"`.

- **office** (Windows): forces macros off (`AutomationSecurity = 3`) before anything opens, opens
  the file read-only in PowerPoint, Word or Excel through COM, exports a PDF, closes it. This is what your readers will see, so use it for sign-off. If the user already
  has that app open, the script works inside their instance but only touches its own document and
  never hides or quits the app. Some organisations block Office automation by policy; if it fails,
  say so and use the other engine. Do not try to get around the block.
- **libreoffice**: `soffice --headless` with a throwaway profile. Works on Linux and WSL. Fonts are
  substituted when the document's fonts are not installed, so line breaks can differ from Office.
- **auto** (default): office on Windows if it works, else LibreOffice.
- A `.pdf` input skips straight to rasterising.
- **Refused:** macro-enabled and legacy formats (`.xlsm .xltm .docm .dotm .pptm .potm .doc .xls
  .ppt .rtf`). Ask the user to save a trusted copy as `.pptx`/`.docx`/`.xlsx` in Office (which
  drops macros) and render that.

The script prints the PNG paths, one per line, and deletes older PNGs for the same file first so a
stale render is never reviewed by mistake.

## The QA loop
1. Render.
2. Read **every** PNG, not a sample. Large decks: `--first N` for a quick pass, then all of them.
3. For each page, write down concrete defects: text overflowing or clipped, overlapping shapes,
   text too small to read, misaligned edges, inconsistent fonts or colours, empty placeholders,
   charts without labels, tables split badly, cut-off columns (spreadsheets), widows and orphans,
   images stretched or blurry.
4. Fix the source (the outline or the generating script), not the rendered output. Regenerate,
   re-render, re-read the changed pages.
5. Stop when a round finds nothing, at most three rounds, and report what was checked and what
   remains.

A fresh pair of eyes helps: for an important document, have a subagent review the PNGs against
the checklist without seeing your build notes.

## Notes
- Excel renders follow each sheet's print area and page setup; wide sheets split across pages.
  Set a print area or fit-to-width in the workbook if the render is unreadable.
- Higher `--dpi` costs more image tokens; 110 is enough to read 10 pt text. Use 150+ only to
  inspect a detail.
- PyMuPDF is deliberately not used (AGPL-3.0).
