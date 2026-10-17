---
title: Digest, reports and PDFs
domain: _shared
status: active
---
# Reports and PDFs: which route, and the bar a finished PDF must clear

Read this before writing a report, memo, one-pager or any PDF another person will read or a reviewer will sign off.

## Where the know-how lives
- **The skill:** `/workbench-core:pdf-report` builds a PDF from HTML or Markdown with the Edge browser already on the
  machine, runs a deterministic check, renders every page to an image for a visual pass, and scrubs the metadata. Its
  `SKILL.md` holds the loop, the templates and the browser gotchas; ask for it by name or say "make this a PDF report".
- **The guide:** "Make a report PDF" in `docs/howto/` walks the same loop step by step, with the checks and the common
  failures.
- **Neighbours:** `/workbench-core:office-render` (page images and the hidden-text scan), `/workbench-core:office-docx`
  (Word files), the diagram skill (offline SVG figures) and the scrub step that runs before anything leaves.

## Word or HTML?
- **Word route** (`office-docx`): the reader must edit the file, or a corporate Word template is mandatory. Export to PDF
  through Office, then run the same PDF check.
- **HTML route** (`pdf-report`): typography, charts, long tables, page numbers and a table of contents matter, and the
  reader does not need to edit it.
- **Either way** the PDF goes through the same check and the same page-by-page visual pass. Only permissive libraries
  are used: the PyMuPDF family is AGPL or commercial [S1], so it never enters the pipeline.

## The quality bar (eight lines)
1. **Pages:** A4 or Letter set in `@page`, margins wide enough for a running header and a "Page N of M" footer; the cover
   sits on its own named page with no footer, sized a hair under the sheet so it cannot spill onto a blank page.
2. **Type:** fonts that Windows and Office already install (so they embed and print the same everywhere), a comfortable
   reading size with generous line spacing, lines short enough to read, tabular figures in number columns.
3. **Breaks:** no heading stranded at the foot of a page, no table row split across pages, table headers repeated on
   each page, figures and callouts kept whole; a new chapter starts a page only where it should.
4. **Tables:** fixed column widths, numbers right-aligned, long identifiers allowed to wrap; a table with too many
   columns goes on a landscape page instead of shrinking the font.
5. **Charts:** inline SVG (sharp at any zoom, text selectable), labelled directly, readable in greyscale and by
   colour-blind readers, each with a title and alternative text.
6. **Navigation:** real headings that become PDF bookmarks, a table of contents whose page numbers are checked against
   the rendered pages (browsers cannot fill them in one pass), and internal links that resolve.
7. **Machine checks pass:** every font embedded, no blank or near-blank page, the expected page count, an extractable
   text layer in reading order, no template remnants, and a file small enough to email.
8. **Before it leaves:** read every rendered page image, fix the source (never the PDF), scrub author, creator and
   producer metadata (a headless browser stamps its own name), and put the classification your policy requires in
   the footer.

## Sources
- [S1] pymupdf4llm on PyPI (licence field) · https://pypi.org/project/pymupdf4llm/ · fetched 2026-10-17
