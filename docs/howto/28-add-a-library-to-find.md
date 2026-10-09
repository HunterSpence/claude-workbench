# Add a library to find

Automates it: /workbench-core:find

## When to use
A folder of documents (a team share, a synced SharePoint or OneDrive library, a project folder) is missing from search
results, and you want it included. Index a scoped folder, not all of OneDrive. `<KIT>` is the kit folder (guide 01).

## Steps
1. See what is on the machine, read-only (it never downloads an online-only file):
   ```
   py -3 <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py discover
   ```
   Kinds: `onedrive-business`, `sharepoint-sync`, `documents`, plus `captured` and `howto`, which setup registers for you.
2. Keep the folder on the device. Only files that are on the device are read; in File Explorer, right-click the folder and
   choose "Always keep on this device". Never bulk-download a whole library: it can trip your organisation's data-loss controls.
3. Register it with a short label (letters, digits, `.`, `_`, `-`) and build the index:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py add-root "<folder>" --label docs
   py -3 <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py refresh --root docs
   ```
   `index "<folder>"` adds the root and indexes it in one step. Add `--max-minutes N` to let a big first run stop and resume.
4. Check it: `roots` lists what is registered and `status --json` shows the file counts per root.
5. To remove a library: `remove-root docs` (add `--purge` to delete its content from the index too).

## Verify
- `roots` lists the label, and `status --json` shows files under `ok` for that root.
- `search "<a phrase you know is in there>" --root docs` finds it.

## Common failures
- **Cloud-only count is high:** those files were catalogued by name but not read. Keep the folder on the device, then refresh.
- **Labelled files only appear by name:** the default; see guide 37.
- **Files skipped:** `status --json` names the reason: encrypted or rights-managed, scanned PDF without text, over 50 MB, or an Office file that unzips past 200 MB. Ask the owner for an accessible copy; never try to strip protection.
- **Install or download blocked:** reading file contents needs a few Python packages, and meaning-based search needs one small model download. Without the packages you still get the file catalogue (`files`); without the model, search stays keyword-only. Ask through guide 03.
- **The index lands in OneDrive:** it must not. The doctor (guide 13) fails on that.
