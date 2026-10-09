# Purge indexed or captured data

Automates it: none (the commands are below)

## When to use
You want captured pages, meeting transcripts, mail copies or a library's search index deleted from this laptop: the project
ended, a scope was too wide, a retention period passed, or you handed the laptop in. `<KIT>` is the kit folder (guide 01).
Below, `CAP` means: run `capture.mjs` from the `<WB>/capture/app/` folder with node. `ING` means your knowledge Python
(`knowledge_python` in `<WB>/config.json`) running `ingest.py` from `<KIT>/plugins/workbench-capture/skills/ingest/scripts/`.

## Steps
1. Stop if this is part of an incident. A purge destroys evidence; ask your security team first (guide 40).
2. Captured pages and files: `CAP purge --source intranet --older-than 30`. With no flags it removes every copy from capture's own sources (intranet, shared files, Teams), including copies kept on this machine only.
3. Meeting and mail copies: `ING purge --source meetings` or `ING purge --source outlook` (add `--older-than <days>` to keep
   recent ones). The meeting purge also removes the originals saved in `<WB>/capture/drop-done/`. Clear the `failed` folder
   under `<DATA>/captured/_drop/meetings/` by hand.
4. Make the index forget them. A refresh drops files that no longer exist:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py refresh --root captured
   ```
   If the root is now empty, refresh refuses to prune; delete that root's content directly:
   `py -3 <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py --purge --root captured`.
5. A whole library: `remove-root <label> --purge`. Everything the index holds: `--purge` with no root. The index is one
   SQLite file in your local app-data folder and holds a full-text copy of what it read.
6. Remove saved sign-ins: `CAP logout` (the capture browser profile) and `ING logout` (the encrypted Graph token cache).

## Verify
- The source folders under `<DATA>/captured/` are empty or gone, `ING status --json` shows `meetings_files` and `outlook_files` at 0, and `doc_index.py status` shows the counts you expect.
- A search for a phrase you know was in the purged items returns nothing.

## Common failures
- **Search still finds purged items:** the index was not refreshed (step 4).
- **Copies are still in the work cloud:** if your data folder is in the work OneDrive, its retention and version history policies apply. That is policy, not a bug; ask your security team, do not work around it.
- **The originals are still where they were:** a purge removes only the kit's copies. Documents, mail and meetings stay at their source.
- **Uninstalling did not remove the data:** captured copies are your data, kept on purpose (guide 06). Purge them first.
- **Denied by a hook or policy:** stop and report it word for word (guide 39).
