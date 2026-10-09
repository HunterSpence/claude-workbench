# Labelled and confidential files

Automates it: none (the defaults protect you; this guide explains them)

## When to use
A document carries a sensitivity label such as Confidential, or you are not sure whether you may give a file to Claude,
index it, capture it or send it on. `<KIT>` is the kit folder (guide 01).

## Steps
1. Find out what label a file has. Office files show it in the title bar. To see what the kit sees:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py label <file> --json
   ```
   It prints the path and the label name, or `null` for none. Office files, PDFs and captured pages are all checked.
2. Know the defaults. Search lists a labelled file by name and label and does not read it. Capture skips labelled pages and
   files and names them in the run report. Ingest keeps only the headers of labelled or rights-managed mail, converts no attachments of
   such a message, and never makes an AI digest of a labelled item. The scrub in guide 36 keeps the label on the copy.
3. Opting in is a policy decision, not yours alone. `index "<folder>" --include-labelled` and `CAP run --source <name> --include-labelled`
   (guide 30) make a local plaintext copy. Do it only where your organisation's policy says so; ask your security team first.
4. Do not give Claude a labelled file you may not send to the model service. Whatever Claude reads in a session goes to that service (guide 38).
5. Do not copy text from a labelled or confidential document into another tool, chat or repository the label would not allow.
6. Encrypted or rights-managed files appear in the index status with a reason. Ask the owner for an accessible copy. Never try to remove protection.

Hard stop rule: any hook, permission, gateway or policy denial means stop and report it word for word; never retry another
way. `docs/admin-asks.md` has the ask for IT. The overall picture is in docs/security-overview.md.

## Verify
- `label <file> --json` returns the name you expect for a file you know is labelled.
- `doc_index.py status --json` lists them among the `coverage.skipped` counts, and a search by content does not find them.
- The capture and ingest run reports list skipped labelled items with the reason.

## Common failures
- **A page or site shows its label in an unusual way:** capture only detects common label markers. Put that area in the deny list (guide 30).
- **A file was indexed, then labelled:** labelling edits the file, so the next refresh sees the change and forgets its indexed text (guide 29). Purge old copies elsewhere if needed (guide 32).
- **Graph mail without label headers:** labelled mail can then only be told apart by content. Keep the Graph route for folders without labelled mail (guide 41).
- **Someone asks you to "just remove the label":** do not. Ask the label's owner.
