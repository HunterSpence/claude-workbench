# Make a report PDF

Automates it: /workbench-core:pdf-report

## When to use
You need a finished PDF: a report, memo or handout with a cover, a contents page, tables, a chart and "Page N of M" on every page. Or you
need to merge, split, stamp or fill PDFs. Edge on your laptop does the printing from HTML or Markdown, so nothing is uploaded and nothing is
downloaded. `<KIT>` is the kit folder (guide 01). Install the helpers once, the PDF ones and the page-image ones:
`py -3 -m pip install --user -r <KIT>/plugins/workbench-core/skills/pdf-report/requirements.txt -r <KIT>/plugins/workbench-core/skills/office-render/requirements.txt`
(if your organisation limits package installs, ask through guide 03). Without them an HTML file still builds, and each missing package is named in one `NOTE:` line.

## Steps
1. Write the content. Markdown is the quickest; a block between `---` lines at the top sets `title`, `subtitle`, `author`, `date`, `classification` and
   `cover: yes`. Put `{: .pb }` after a heading to start a new page, and give charts as inline SVG (the skill's `references/charts-svg.md` shows one).
2. Build it, A4 by default (`--page Letter` for Letter), with a contents page and a PNG of every page:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/pdf-report/scripts/build_pdf.py report.md --out out/report.pdf --toc --png out/png
   ```
   An HTML file works the same way; add `--style report` to put the kit stylesheet under your own CSS. The build runs twice when there is a contents
   page, so the page numbers are the real ones.
3. Read what it printed. Exit 0 means the preflight found nothing, 1 means the PDF was built with at least one defect (each is listed), 2 means it was not built.
4. Look at the pages. Open every PNG in `out/png`, not a sample, and write down what is wrong: a heading alone at the foot of a page, a table cut badly,
   a clipped column, a half-empty page, labels that collide. Fix the Markdown or HTML, never the PDF, then build again. Stop when a round finds nothing,
   after three rounds at most.
5. Run the check on its own whenever you like:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/pdf-report/scripts/check_pdf.py out/report.pdf --expect-pages 8 --json
   ```
6. Other PDF jobs use one tool, `pdf_tools.py`, with a command name: `info`, `text`, `merge`, `split`, `rotate`, `stamp`, `meta`, `scrub`, `fields`, `fill`.
   For example, a draft watermark on page 1, then a copy for sending:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/pdf-report/scripts/pdf_tools.py stamp out/report.pdf --out out/draft.pdf --text DRAFT --pages 1
   py -3 <KIT>/plugins/workbench-core/skills/pdf-report/scripts/pdf_tools.py scrub out/report.pdf --out out/send.pdf --json
   ```
7. A form: `fields form.pdf` lists the boxes, `fill form.pdf --out filled.pdf --set name=value` fills a copy. Read the copy, then sign it yourself. The tools
   never sign, never fill a signature box, refuse a signed or encrypted file and never edit the original.

## Verify
- The build prints `built <path> (N pages)` and no `DEFECT` line, and `check_pdf.py ... --json` has `"ok": true` with an empty `defects` list.
- In that JSON: `footer` has `"bad": []`; `tables` has `"split_rows": []` and `"header_missing_on": []`; `fonts` has `"not_embedded": []`; `outline` has entries
  and `"doubled_titles": []`; `toc` has `"wrong": []`; `metadata` has `"leaks": []`.
- The number of PNG files equals the page count, and you have looked at them.
- `pdf_tools.py info <file>` shows `tagged: True`, the language and no `Creator` or `Producer` property.

## Common failures
- **`BUILD FAILED: Markdown input needs the Markdown package`**: run the install line above, or give the builder HTML.
- **Edge did not make the PDF, or headless mode is off by policy**: the Day-1 headless-Edge check (D23, doctor row `knowledge: browser-cli`, guide 45) shows it. Ask through guide 03. Meanwhile
  open the HTML in Edge, press Ctrl+P, choose Save as PDF and switch off Headers and footers. Nothing is ever downloaded to get round it.
- **A blank page after the cover**: the cover is as tall as the page. Use the page height minus 1 mm (the stylesheet does) and `body { margin: 0 }`.
- **A bookmark title appears twice**: a heading at the very top of a page needs 1 pt of top margin. The check flags it.
- **The contents list has no numbers**: pypdfium2 is missing (the `NOTE:` line says so). Install it with the line above and build again.
- **A footer is missing on some pages**: your own HTML has no `@page` footer box. Add `@bottom-center { content: "Page " counter(page) " of " counter(pages) }`.
- **Results differ from the guide**: it was measured on Edge 155. State your Edge build when you report a difference.
