---
name: pdf-report
description: "Build a polished PDF report, memo or handout from HTML or Markdown with Edge, check it, then merge, split, stamp or fill PDFs. Use for \"make a PDF report\", \"merge PDFs\"."
when_to_use: "ALWAYS load before making or changing a PDF."
---

# pdf-report

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it
> appears unreplaced (the skill was copied in without the plugin), use `py -3` on Windows and
> `python3` on Linux, macOS and WSL, never the Microsoft Store `python` stub. When a package below is missing
> and the workbench `config.json` names a `knowledge_python`, each script re-runs itself under that interpreter.

The engine is Microsoft Edge, already on the laptop: HTML and CSS go in, a PDF with real text, embedded fonts, bookmarks
and "Page N of M" comes out. Nothing is downloaded, and the page cannot reach the network.
Setup once: `"${user_config.python}" -m pip install --user -r "${CLAUDE_SKILL_DIR}/requirements.txt"` (pypdf and Markdown; ask before
installing on a managed machine). Without them HTML still builds; each missing package prints one `NOTE:` line naming it.

## Word or HTML?
| The reader needs | Route |
|---|---|
| to edit it, or your organisation's Word template | office-docx, then `render.py --engine office` for the PDF |
| typography, charts, a cover, a contents page, exact page control | this skill (HTML route) |
| a slide handout or a spreadsheet print | export from real Office, then run `check_pdf.py` on it |
Either route ends in the same check.

## 1. Plan before you build
- Lead with the answer on page 1; one idea per section; headings that say the point.
- Decide the page (`A4` or `Letter`), whether it needs a cover and a contents page, and the classification text the footer must show:
  Edge writes no organisational label, so the text has to say it and the user applies the label where the policy asks.
- Colours and fonts: if a `BRAND_SPEC.md` exists, copy its tokens into the `:root` block of `templates/report.css`. If there is none and
  the look matters, tell the user they can run /workbench-core:brand-spec.
- Charts are inline SVG only (see `references/charts-svg.md`; the `diagram` skill's SVG can be embedded). Images are local files or
  `data:` URIs, about 150 to 200 dpi.

## 2. Build
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/build_pdf.py" <in.html|in.md> --out <dir>/<name>.pdf [--page A4|Letter] [--title T] [--toc]
      [--style report|memo|none] [--cover] [--author A] [--subject S] [--png <dir>] [--json]
```
- **Markdown** (needs the Markdown package) is poured into `templates/report.html` with `report.css` (or `memo.css` after it).
  A `---` block at the top may set `title, subtitle, author, date, classification, subject, lang, cover: yes`. `{: .pb }` after a
  heading starts a new page; a `>` quote is a callout (`{: .callout }` after a plain paragraph makes one too); tables, footnotes and fenced code work.
- **HTML** is used as written. `--style report` adds the kit stylesheet underneath your own CSS, which wins. Add
  `@page { margin: 22mm 18mm 24mm; @bottom-center { content: "Page " counter(page) " of " counter(pages) } }` for the footer.
- `--toc` builds twice and writes the page numbers into fixed-width cells (`target-counter()` does not work in Edge).
- It prints the result and the preflight defects; exit 0 clean, 1 built with a defect, 2 not built. `--json` prints the report.
- Old PDFs and PNGs of the same name are replaced, never mixed in. Edge runs with a fresh profile and is never started with
  its sandbox off; stray processes are only those of this run.
- Edge refused or missing: the message says so. If headless mode is off by policy, the Day-1 headless-Edge check (D23, row `knowledge: browser-cli`; guide 45) shows it, so ask
  through guide 03. Meanwhile tell the user to print by hand: Edge, Ctrl+P, destination Save as PDF, Headers and footers off. Never download a browser.

## 3. Verify (the loop)
1. Build; read the printed defects. For any build: `check_pdf.py <pdf> [--expect-pages N] [--html <source.html>] --json` (exit 1 on a defect).
   It checks page count, blank pages, fonts embedded, bookmarks (none doubled), "Page N of M", contents numbers, links, creator and
   producer, template leftovers, and with `--html` a repeated table header and no row cut by a page break.
2. Render every page: `"${user_config.python}" "${CLAUDE_SKILL_DIR}/../office-render/scripts/render.py" <pdf> --out <dir> --dpi 110`
   (or build with `--png <dir>`). Read **every** PNG: a 6-up contact sheet first, then full pages for tables and charts.
3. Write concrete defects (orphaned heading at a page foot, split table, clipped column, half-empty page, colliding labels,
   footer touching text, low contrast). Fix the HTML, CSS or Markdown, never the PDF. Rebuild, re-read the changed pages.
   Stop when a round finds nothing, at most three rounds. For an important document a fresh subagent reviews the PNGs against
   `references/quality-bar.md` without your build notes.
4. Extraction check: `pdf_tools.py text <pdf> --pages 3` and look for three phrases per section, in reading order.
5. Scrub a copy: `pdf_tools.py scrub <pdf> --out <send-copy> --json`, then `check_pdf.py` on the copy. Say what was and was not checked.

## 4. Other PDFs (`scripts/pdf_tools.py`)
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/pdf_tools.py" info|text|merge|split|rotate|stamp|meta|scrub|fields|fill <pdf> ...
```
- Read: `info` (pages, size, tagged, signed, scripts, attachments, label keys), `text` (per page; names pages with no text layer, which
  need OCR: RapidOCR, optional). A PDF from outside goes through office-render's `hidden_text.py scan` first.
- `merge a b --out x`, `split a --out dir [--ranges 1-3,4]`, `rotate a --out x --degrees 90 [--pages 2]`, `meta a --out x --title T`,
  `stamp a --out x --text DRAFT [--where center|top|bottom]` (Edge draws it). For one page-number series across a pack, build one HTML instead.
- Forms: `fields a` lists names, types and the on-state of each checkbox; `fill a --out x --set name=value` writes a copy
  (`--set agree=yes` ticks a box). Flat forms and signing: `references/forms.md`.
- **Rails, not options:** encrypted files are refused (ask for an unprotected copy); a signed file is refused by every command that writes;
  the input is never edited and `--out` must be another file; nothing here ever draws or applies a signature. For a legal, financial or
  government form: fill a copy, show it to the user, stop, and the user signs it.

## Quality bar (details and the reasons: `references/quality-bar.md`)
Geometry from `@page`; running header and "Page N of M"; cover on a named page at page height minus 1 mm; body 10 to 11 pt, line height
1.4 to 1.55; headings never stranded (`break-after: avoid`); table rows whole (`tr { break-inside: avoid }`) with `thead { display: table-header-group }`;
at most 7 table columns portrait; charts as labelled SVG with a text alternative; `<html lang>`, a real `<title>`, alt text; Segoe UI, Calibri
or Georgia with a fallback stack (web fonts never load); file under 5 MB for email.

## Limits (say them when they matter)
- Tested on one Edge version and small documents. UNTESTED: `text-wrap: balance`, a landscape page inside a portrait document, local `@font-face`
  files, JavaScript charts, stamp numbering, PDF/UA validation. A pack that must be accessible needs a person's review.
- A heading at the very top of a page needs 1 pt of top margin or its bookmark title doubles (the check flags it). More in `references/edge-notes.md`.
- `check_pdf.py` does not look for text hidden outside the page; scan inbound files with `hidden_text.py`.
- Never PyMuPDF (AGPL-3.0), Jinja2, WeasyPrint, pandoc or Poppler here.
