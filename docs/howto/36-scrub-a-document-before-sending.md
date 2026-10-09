# Scrub a document before sending it

Automates it: /workbench-core:office-render

## When to use
You are about to email, upload or share a Word, PowerPoint or Excel file outside your organisation (a customer, a vendor,
a public site), and you want the author names, comments, tracked changes, hidden slides and similar leftovers gone first.
`<KIT>` is the kit folder (guide 01). Install the helpers once: `py -3 -m pip install --user -r <KIT>/plugins/workbench-core/skills/office-render/requirements.txt`
(if your organisation limits package installs, ask through guide 03).

## Steps
1. Look at it as a reader will. Render every page to images and read all of them, not a sample:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/office-render/scripts/render.py <file> --out <folder>
   ```
   On Windows it uses PowerPoint, Word or Excel read-only with macros off, else LibreOffice. If Office automation is blocked by policy, that is the answer; do not try to get round it.
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
5. Read the text once more yourself. The scrub removes known metadata, not sensitive wording in the body.
6. Send the copy only. The sensitivity label stays on it: if the label does not allow the file to leave, it does not leave (guide 37).

## Verify
- The JSON says `"ok": true` and the exit code is 0. The original file is unchanged and the copy has a new name.
- Open the copy: File, Info shows no author, Review shows no comments or tracked changes, and no hidden slides remain.
- `render.py <file> --lint` (Word and PowerPoint) lists pictures without alt text and slides without a title.

## Common failures
- **Refused:** macro-enabled, legacy (`.doc`, `.xls`, `.ppt`, `.rtf`), encrypted and rights-protected files are refused. Save a trusted `.docx`, `.pptx` or `.xlsx` copy in Office first.
- **A cell now starts with an apostrophe:** that is the formula guard (for example `-5`). Tell the recipient or retype it.
- **Page breaks moved:** accepting tracked changes can do that. Render the copy again.
