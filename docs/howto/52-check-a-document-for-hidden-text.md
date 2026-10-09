# Check a document for hidden text

Automates it: /workbench-core:office-render

## When to use
A PDF, a Word file or a text export came from outside your organisation, and you are about to have Claude read,
summarise or index it. Text a person cannot see still reaches the model: white or covered text, text pushed off the
page, 1 pt text, hidden Word runs, zero-width and other invisible characters, lines that imitate a chat turn, and
instructions tucked into the document properties. A measurement study of about 200,000 real documents sent to an
AI screening system found that more than 90% of the hidden injected prompts used no explicit instructions
(arXiv 2605.28999). So the check looks for concealment, not for wording.
`<KIT>` is the kit folder (guide 01). Install the helpers once:
`py -3 -m pip install --user -r <KIT>/plugins/workbench-core/skills/office-render/requirements.txt`
(if your organisation limits package installs, ask through guide 03).

## Steps
1. Scan before anything reads the file:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/office-render/scripts/hidden_text.py scan <file> [<file> ...]
   ```
   Add `--json` when a script reads the result.
2. Read the exit code. 0: nothing found. 1: at least one finding. 2: the file was not scanned (an unsupported type,
   unreadable or encrypted, or over a cap). Exit 2 means unchecked, not clean.
3. For each finding, read the kind, where it is and the excerpt. PDF: `invisible-text` (the glyphs render as one flat
   colour), `invisible-over-text`, `off-page`, `tiny-text`. Word: `hidden-run`, `background-colour`, `tiny-text`. Any
   text, metadata included: `zero-width`, `unicode-tags` (with the text they spell), `bidi-control`, `homoglyph`,
   `role-token`. Properties: `metadata-prose`. Invisible characters in an excerpt are shown as escapes.
4. Decide, as a person: delete the file, ask the sender for a clean copy, or go ahead knowing what it carries. The
   scanner never moves, edits or rejects anything. Keep a flagged file out of every folder that is ingested or indexed
   until you decide; the ingest skill's quarantine note describes the review folder.
5. A `.pptx` or `.xlsx` is not scanned: render every page and read it instead (guide 36).

## Verify
- `py -3 <KIT>/plugins/workbench-core/skills/office-render/scripts/hidden_text.py --self-test` prints one line starting
  `hidden_text self-test: ok` and exits 0. It builds its own small test files in memory, offline.
- A file you know is clean scans as `CLEAN` with exit 0; the same file saved again with one white sentence added scans
  as `FLAGGED` with exit 1.

## Common failures
- **`no-memcap`**: each file is parsed in a child process under the kit's memory cap, `tools/memcap/memcap.py`. The
  scanner looks for it next to the skill in a kit folder and in the installed kit copy. Without it nothing is parsed.
- **`size-cap`, `page-cap`, `unpacked-cap`, `time-cap`**: the file is over a default cap (100 MB, 500 pages, 256 MB
  unpacked, 120 s). Raise only the one named, with `--max-mb`, `--max-pages`, `--max-unpacked-mb` or `--max-seconds`,
  and only for a file you trust.
- **`parser` or `parser-stopped`**: the file is damaged or encrypted, or it needed more memory than the cap (`--mem-mb`,
  768 by default). A decompression bomb stops here, by design.
- **A note about an invisible text layer**: a scanned PDF usually carries recognised (OCR) text, drawn invisibly over
  the page image. It is noted and not flagged, because the scanner cannot read the image to check that the two match.
- **A faint watermark is flagged**: near-white text on white is reported as `invisible-text`. Look at the page and
  carry on if it is only a watermark.
- **What it does not catch**: text under a picture, a patterned or gradient graphic, or other text; an OCR layer that
  says something other than its image; PDF annotations, form fields, attachments and XMP metadata; Word text boxes
  placed off the page, squeezed character spacing, fills that come from a table style (noted), comments, field codes and
  embedded objects; look-alike letters other than Cyrillic and Greek ones mixed into Latin words; `.pptx`, `.xlsx`,
  HTML and mail files. It does not judge what visible text says: a visible instruction passes.
