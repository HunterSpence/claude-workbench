---
name: doc-index
description: Local full-text search over a folder of Word, PowerPoint, Excel, PDF, HTML and Markdown files (for example a synced document library), then a cited answer from the originals. Use for "search our docs for X", "what do the documents say about Y", "index this folder", "find the paragraph that mentions Z". Runs on the machine; no vectors, no network at query time.
---

# doc-index

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it
> appears unreplaced (the skill was copied in without the plugin), use `py -3` on Windows and
> `python3` on Linux, macOS and WSL, never the Microsoft Store `python` stub.

`scripts/doc_index.py` converts documents to Markdown with MarkItDown, stores one row per paragraph
in a local SQLite FTS5 index, and returns ranked passages as `file#pN` references.

## Setup (once)
```bash
"${user_config.python}" -m pip install --user -r "${CLAUDE_SKILL_DIR}/requirements.txt"   # or your package mirror / uv
```
Search alone needs only the standard library;
MarkItDown is needed to convert Office, PDF and HTML files. Ask before installing anything on a
managed machine.

## Which folder
SharePoint and Teams document libraries you "Sync" (or "Add shortcut to My files") appear in File
Explorer under your organisation's OneDrive folders in `%USERPROFILE%`. Index the library folder,
not all of OneDrive. Only files actually on this device are indexed; right-click a folder and choose
"Always keep on this device" to include it. Access stays what SharePoint grants you: the index never
widens it. From WSL, Windows folders are under `/mnt/c/...` (slow for large libraries: prefer
running the indexer with Windows Python).

## Index
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/doc_index.py" index "<folder>"            # add/update changed files
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/doc_index.py" index "<folder>" --rebuild  # also drop files that are gone
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/doc_index.py" report --folder "<folder>"  # what could not be indexed, and why
```
- Incremental: unchanged size and mtime are skipped; a changed file is re-hashed and re-converted
  only if its content changed. A plain `index` never deletes; `--rebuild` prunes rows for files no
  longer present (and refuses if the folder looks empty or offline). Schedule `--rebuild` nightly if
  you want, with your own scheduler.
- **Never triggers downloads**: on Windows, OneDrive "online-only" placeholders are recognised by
  their file attributes and skipped (reported as `cloud-only`). Make a folder "Always keep on this
  device" to include it.
- **Failures are reported, not hidden**: password-protected, encrypted or rights-managed Office
  files (OLE containers), unreadable PDFs, files over `--max-mb` on disk (default 50), and Office files whose parts would
  expand past `--max-unzipped-mb` (default 200) or list more than 10,000 parts appear in `report`;
  the expanded size is read from the zip directory, so nothing is decompressed to check it.
  Do not try to remove protection; ask the user for an accessible copy if the content matters.
- **Labelled files are skipped by default.** Office files carrying a sensitivity label are listed
  in `report` as `labelled` and not converted or indexed. Both places Office stores a label are
  read: the classic custom document properties and the `LabelInfo` part used when co-authoring of
  labelled files is on; an unreadable `LabelInfo` part counts as labelled. Pass
  `--include-labelled` only where your organisation's policy allows a local plaintext copy of that
  content; the label name is then shown with each result. Labels inside PDFs are not detected.
- **Where the plaintext lives:** `%LOCALAPPDATA%\doc-index\<id>\index.sqlite` plus
  `%LOCALAPPDATA%\doc-index\<id>\cache\*.md` on Windows (`~/.cache/doc-index/<id>/` elsewhere),
  where `<id>` is derived from the folder path; `status` prints the exact path. Never inside the
  indexed folder, so a synced library does not sync its index. It is a full-text copy of the
  documents: treat it like them, keep it off shared drives, and delete it when done:
  ```bash
  "${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/doc_index.py" --purge --folder "<folder>"
  ```

## Answer a question
1. Search with the user's distinctive words (keyword search, not semantic: try synonyms,
   product names, acronyms; all words must match, else any word):
   ```bash
   "${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/doc_index.py" search "<words>" --folder "<folder>" --limit 10
   ```
   Add `--path <text>` to restrict to a subfolder or file type, `--json` for structured output.
2. Read the hits in context before relying on them:
   ```bash
   "${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/doc_index.py" show "<file>#p<N>" --folder "<folder>" --context 3
   ```
   For a decision-grade answer, open the original file (the `source:` line) and check the passage
   there too: conversion can drop tables, comments or slide notes.
3. Write a short synthesis where every claim cites `file#pN`. Say which documents disagree, which
   are newest (check modified dates), and what the index could not cover (`report`). If nothing
   relevant is found, say so; never fill in missing facts from general knowledge without labelling them.
4. Respect labels and access: do not copy text from a labelled or confidential document into
   another tool, chat or repository the label would not allow.

## Limits
Keyword ranking (BM25) misses paraphrases; scanned PDFs without a text layer produce nothing
(OCR is out of scope); very large spreadsheets become long tables. The index only knows files
present on this machine at the last run.
