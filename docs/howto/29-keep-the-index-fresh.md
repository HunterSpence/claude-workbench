# Keep the index fresh

Automates it: /workbench-core:find

## When to use
Search shows old results, a new document is not found, or you want to know whether the index updates by itself. The
index is a local copy of what was on this machine at its last refresh. `<KIT>` is the kit folder (guide 01).

## Steps
1. See when it last ran:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py status
   ```
   The summary ends with `last refresh`; `status --json` adds the file counts per root.
2. Refresh by hand. It is resumable and safe to stop:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py refresh --all --max-minutes 10
   ```
   Use `--root <label>` for one root and `--detach` to run in the background. `--embed off` skips the vectors for a fast keyword-only pass.
   A refresh also drops files that no longer exist; `--rebuild` re-reads everything.
3. Know what refreshes for you. A `search` starts a background refresh (memory capped, ten minutes) when the last one is
   more than 24 hours old, and answers from the current index meanwhile. Set `WB_FIND_LAZY=0` to turn that off.
4. The nightly task. Setup creates a per-user scheduled task `\claude-workbench\knowledge-refresh` (memory capped,
   mains power only). It does up to four jobs in one run: refresh every root (the `kb` root, your notes, included); purge
   captured items older than your retention days, when the capture runtime is installed; make a backup when the newest is
   older than seven days (`py -3 <KIT>/bootstrap/setup.py backup --if-older-days 7`, guide 13); and, when `ctx` is installed,
   import new agent sessions (`ctx import --all`). With the corporate profile (a managed laptop) it is opt-in: `py -3 <KIT>/bootstrap/setup.py run --detach --with nightly`.
   Elsewhere it is on unless you pass `--no-nightly`. Run it now with `schtasks /Run /TN "\claude-workbench\knowledge-refresh"`.
5. After you capture or ingest new items (guides 30, 31, 41), refresh the `captured` root so they become searchable.

## Verify
- `status` shows a recent `last refresh`, and the file counts grew by what you added.
- `schtasks /Query /TN "\claude-workbench\knowledge-refresh"` exits 0 when the nightly task exists.
- The doctor's knowledge-index row is OK (guide 13), and `py -3 <KIT>/bootstrap/setup.py doctor --deep` shows its `knowledge: schedule`
  and `knowledge: backup` rows as OK (warnings are allowed; guide 13).

## Common failures
- **The nightly task is missing:** it is opt-in on the corporate profile, or your organisation blocks user tasks. Refresh by hand; do not look for another scheduler (guide 03).
- **A backup is older than a week although the task exists:** the task did not run, or its backup step failed. Run
  `py -3 <KIT>/bootstrap/setup.py backup` by hand and read its one-line result; the doctor's backup row shows the age (guide 13).
- **Overlapping heavy refreshes:** the laptop slows to a crawl. Run one, and let the cap do its job.
- **"No files found, refusing to prune":** a folder is offline or unmounted. Reconnect it; nothing was removed.
- **Items still found after you deleted them:** the index kept them until a refresh. Refresh, or purge (guide 32).
