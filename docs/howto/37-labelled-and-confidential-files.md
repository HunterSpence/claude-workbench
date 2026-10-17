# Labelled and confidential files

Automates it: none (this guide explains the defaults)

## When to use
A document carries a sensitivity label such as Confidential, and you want to know how search, capture and ingest treat
it. `<KIT>` is the kit folder (guide 01).

## Steps
1. Find out what label a file has. Office files show it in the title bar. To see what the kit sees:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py label <file> --json
   ```
   It prints the path and the label name, or `null` for none. Office files, PDFs and captured pages are all checked.
2. Know the defaults. Search lists a labelled file by name and label and does not read it. Capture skips labelled pages and
   files and names them in the run report. Ingest keeps only the headers of labelled or rights-managed mail, converts no attachments of
   such a message, and never makes an AI digest of a labelled item. The scrub in guide 36 keeps the label on the copy.
3. Include labelled items: `index "<folder>" --include-labelled` and `CAP run --source <name> --include-labelled`
   (guide 30) make a local plaintext copy.
4. Encrypted or rights-managed files appear in the index status with a reason. Ask the owner for an accessible copy.

## Verify
- `label <file> --json` returns the name you expect for a file you know is labelled.
- `doc_index.py status --json` lists them among the `coverage.skipped` counts, and a search by content does not find them.
- The capture and ingest run reports list skipped labelled items with the reason.

## Common failures
- **A page or site shows its label in an unusual way:** capture only detects common label markers. Put that area in the deny list (guide 30).
- **A file was indexed, then labelled:** labelling edits the file, so the next refresh sees the change and forgets its indexed text (guide 29). Purge old copies elsewhere if needed (guide 32).
- **Graph mail without label headers:** labelled mail can then only be told apart by content. Keep the Graph route for folders without labelled mail (guide 41).
