# Quality bar for a PDF report

The checklist the build and `check_pdf.py` enforce, and the one a reviewer reads against. T marks a point that was tested on a real Edge
build (see `edge-notes.md`); U marks one that was not, so treat it as advice.

## Page and typography
- Geometry from CSS, never from a printer default: `@page { size: A4 | Letter; margin: 22mm 18mm 24mm }`. T: the size is honoured (A4 is
  595 by 842 points, Letter 612 by 792).
- Running header (document title or classification) and the footer `Page N of M` in margin boxes. T: `counter(page)` and
  `counter(pages)` work in `@page` boxes. Custom properties do not reach margin boxes, so colours there are literals.
- Cover on a named page: `page: cover; @page cover { margin: 0 }`, height the page height minus 1 mm (A4 296 mm, Letter 278 mm) and
  `body { margin: 0 }`. T: a cover exactly as tall as the page leaves a near-blank page behind it. The check calls that a blank page.
  Write the `@page cover` rule after the plain `@page` rules and set its top and bottom boxes to `content: none`, or the running header lands in the cover's text layer.
- Body 10 to 11 pt, line height 1.4 to 1.55, 65 to 90 characters per line. Humanist sans or serif from what Windows and Office install:
  Segoe UI, Calibri, Cambria, Georgia, Consolas, always with a fallback stack. Headings in a sans on a 1.25 scale.
  `font-variant-numeric: tabular-nums` in tables, `orphans: 3; widows: 3`. Ligatures and hyphenation off, so every word stays whole for search and
  copy-paste (T: PDFium reads a hyphen at a line end as a special character, which splits the word for a search). U: `text-wrap: balance` on headings.
- Fonts embed themselves as subsets. T: Type0 subsets with a `FontFile2`, so the check walks `DescendantFonts`. A custom font needs a
  local file whose licence allows embedding; a web font never loads (U for the local file).

## Page breaks
- `h1, h2, h3 { break-after: avoid }`; `figure, blockquote, pre, .callout { break-inside: avoid }`; a new page before a chapter only where
  one should start (`h1.pb`).
- `tr { break-inside: avoid }` keeps rows whole and `thead { display: table-header-group }` repeats the header. T for both. An element
  taller than a page ignores `break-inside`; the verify loop finds it.
- A heading that sits at the very top of a page keeps at least 1 pt of top margin. T: with 0 (or less than 1 pt) Edge writes the bookmark
  title twice ("SummarySummary"). The check flags a doubled title.

## Tables
- Numbers right-aligned, a short header row, at most 7 columns in portrait; wider means a landscape named page (U) or a second table.
- Markdown tables get `class="fixed"` and a `<colgroup>` sized by the longest text in each column, so short columns never wrap their words. For HTML, do the
  same by hand (`report.css` then lets long identifiers wrap with `overflow-wrap: anywhere`); `table-layout: auto` is the default for a table with no class. T: `overflow-wrap: anywhere` in an auto table shrinks narrow columns to one character ("Own/er"), so do not set it there.

## Charts, images, links
- Charts are inline SVG (see `charts-svg.md`). T: vector, and the labels stay selectable text. No canvas or bitmap charts.
- Images downscaled to about 150 to 200 dpi; the file stays under 5 MB if it will be emailed.
- Internal links and the contents list point at real pages; the contents numbers come from a second build, never typed by hand.

## Contents page
Two builds: the first with fixed-width placeholders, the second with the numbers read from the bookmarks of the first. The numbers sit in
right-aligned cells of fixed width, so writing them in cannot move a page break. `check_pdf.py` then reads each contents line and compares its number with
the page its link really points to. T: `target-counter()` and `leader()` are not supported, so they are never used.

## Accessibility and metadata
- `<html lang>`, real headings in order, alt text or a text alternative for every image and chart. T: the PDF is tagged, carries the
  language and uses `<title>` as its Title. U: PDF/UA validation: say so, and ask a person to review anything that must be accessible.
- Title, Author and Subject set; the browser's name removed from Creator and Producer (T: it leaks otherwise).
- Edge adds no organisational sensitivity label. The footer text states the classification the policy requires, and the user applies the label.

## Before it leaves
Scrub a copy (`pdf_tools.py scrub`), run `check_pdf.py` on the copy, read every page once more as a reader would, and send the copy only.
