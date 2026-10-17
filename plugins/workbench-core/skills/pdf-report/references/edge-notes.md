# Edge headless: what was measured, what to expect

Measured on one machine with Edge 155 (the version shows in `edge://version`; do not start `msedge.exe --version` while the user's own Edge is
open, it joins that session). Small documents only. Behaviour on an older or newer Edge can differ: when a result looks wrong, say which build.

## The command (build_pdf.py does all of this)
```
msedge.exe --headless=new --disable-gpu --no-first-run --no-default-browser-check --user-data-dir=<fresh folder>
           --no-pdf-header-footer --generate-pdf-document-outline --print-to-pdf=<C:/...pdf> file:///C:/.../doc.html
```
- Every path in a flag is a `C:/...` Windows path. Git Bash `/c/...` paths are passed through unconverted and Edge writes nothing.
- A fresh `--user-data-dir` per print. Edge hands off to a running instance that shares the profile, exits within a fraction of a second
  and produces nothing, and the earlier instance may finish its job later, so files appear out of order.
- The launcher returns before the PDF exists. Poll for a whole file (`%PDF-` at the start, `%%EOF` near the end) whose size stopped changing.
- Never `--no-sandbox`, a remote-debugging port or `--allow-file-access-from-files`. Nothing here needs them.
- Stray processes: only those whose command line holds this run's own temp folder are stopped. Other Edge windows are never touched.

## The page cannot call out
`build_pdf.py` inserts `Content-Security-Policy: default-src 'none'; img-src data: file:; style-src 'unsafe-inline' file:; font-src data: file:` as the
first thing in `<head>`. No script runs and nothing leaves the machine; a template cannot phone home and the document stays private.
Assets are local files or `data:` URIs. Relative `src`, `href` and `url()` values are made absolute against the source folder. A `<base href>` is not used: with it,
`#section` links stop being in-page links and the contents list and bookmarks would point at a file instead of a page.

## Behaviour found
| Feature | Result |
|---|---|
| `@page` margin boxes with `counter(page)` and `counter(pages)` | works |
| Named page (`page: cover`, `@page cover { margin: 0 }`, boxes `content: none`) | works, if the `@page cover` rule comes AFTER every plain `@page` rule that sets header or footer text: a later plain rule puts its text on the cover too (clipped, so invisible, but present in the text layer) |
| `thead { display: table-header-group }` repeats; `tr { break-inside: avoid }` keeps rows whole | works |
| Inline SVG | works, vector, text selectable |
| System fonts (Segoe UI, Georgia) | embedded as subsets; web fonts never load |
| Tagged PDF, `/Lang`, Title from `<title>`, internal links | present; bookmarks need `--generate-pdf-document-outline` |
| `target-counter()` and `leader()` in a contents list | do NOT work: numbers are missing, hence the two-pass build |
| Cover as tall as the page | adds a near-blank page: use the page height minus 1 mm and `body { margin: 0 }` |
| Heading at the very top of a page with a top margin under 1 pt | its bookmark title is written twice |
| Creator and Producer | the browser's name: removed after the build |
| Edge's page background | transparent, so a stamp page can be merged over another page |

## Not tested (labelled so in the skill)
`text-wrap: balance`, a landscape named page in a portrait document, local `@font-face` files (a `data:` URI font is the safe route),
`--virtual-time-budget` for JavaScript charts, numbering that skips the cover, `playwright-cli pdf` parity, PDF/UA validation, and the
effect of managed Edge policies other than the one below.

## Edge refuses or is missing
- Not installed: the build says so and tells the user to print by hand (Ctrl+P, Save as PDF, Headers and footers off). It never downloads a browser.
- Policy `HeadlessModeEnabled` is off: Edge opens a window instead of printing. The build reads the policy first and stops at once with the same
  advice. The Day-1 headless-Edge check (D23, doctor row `knowledge: browser-cli`; guide 45) shows the same fact; the request to IT goes through guide 03.
- Other managed Edge policies (one that blocks local files, for instance) were not tested. The poll gives up after 60 s and says so.
