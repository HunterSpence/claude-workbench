# Scrub a document before sending it

Automates it: /workbench-core:office-render

## When to use
You want a copy of a Word, PowerPoint or Excel file without the author names, comments, tracked changes, hidden slides and
similar leftovers, for example before you send it to a customer or vendor.
`<KIT>` is the kit folder (guide 01). Install the helpers once: `py -3 -m pip install --user -r <KIT>/plugins/workbench-core/skills/office-render/requirements.txt`
(if your organisation limits package installs, ask through guide 03).

## Steps
1. Look at it as a reader will. Render every page to images and read all of them, not a sample:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/office-render/scripts/render.py <file> --out <folder>
   ```
   On Windows it uses PowerPoint, Word or Excel read-only with macros off, else LibreOffice. If Office automation is blocked by policy, ask through guide 03.
2. Fix what you see in the source file, not in the images. Render again.
3. Scrub a copy, never the original:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/office-render/scripts/scrub.py <file> --out <send-copy> --strip-notes --json
   ```
   It clears author, last modifier, company, manager and the Comments property; removes comments and their author lists, the
   preview image and a workbook's saved path; accepts every tracked change; removes hidden slides and, with `--strip-notes`,
   all speaker notes; and puts an apostrophe in front of text cells that start with `=`, `+`, `-` or `@` so no program reads them as formulas.
4. Read the JSON. `ok` must be true and `changes` lists what went. Read `warnings`: embedded files, links to other workbooks and
   custom XML are listed but not touched. Check them by hand.
5. The scrub removes known metadata, not wording in the body.
   A PDF has its own scrub: `py -3 <KIT>/plugins/workbench-core/skills/pdf-report/scripts/pdf_tools.py scrub <file.pdf> --out <send-copy.pdf> --json` removes author, creator, producer and XMP, and lists (never removes) scripts, attachments and comments (guide 57).
6. Use the copy. The sensitivity label stays on it (guide 37).

## Verify
- The JSON says `"ok": true` and the exit code is 0. The original file is unchanged and the copy has a new name.
- Open the copy: File, Info shows no author, Review shows no comments or tracked changes, and no hidden slides remain.
- `render.py <file> --lint` (Word and PowerPoint) lists pictures without alt text and slides without a title.

## Common failures
- **Refused:** macro-enabled, legacy (`.doc`, `.xls`, `.ppt`, `.rtf`), encrypted and rights-protected files are refused. Save a trusted `.docx`, `.pptx` or `.xlsx` copy in Office first.
- **A cell now starts with an apostrophe:** that is formula protection, so no program reads the cell as a formula (for example `-5`). Tell the recipient or retype it.
- **Page breaks moved:** accepting tracked changes can do that. Render the copy again.
