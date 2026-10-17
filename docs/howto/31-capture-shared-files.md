# Capture shared files

Automates it: /workbench-capture:capture

## When to use
Colleagues shared folders and files with you in SharePoint or OneDrive, and you want read-only Markdown copies of the
ones you pick, searchable with the rest of your documents. There is no browser in this route: capture reads the files
from your synced OneDrive folder. If you only need search, indexing the synced folder (guide 28) is simpler.
`<KIT>` is the kit folder (guide 01). Below, `CAP` means: run `capture.mjs` from the `<WB>/capture/app/` folder with node.

## Steps
1. Have the capture add-on (`py -3 <KIT>/bootstrap/setup.py run --detach --with capture`). The Edge policy is not needed
   here, because no browser starts.
2. In the OneDrive web app open "Shared with me" and use "Add shortcut to My files" yourself, once per folder or file.
   Capture never clicks it. Wait until OneDrive syncs the shortcut to this PC.
3. Point capture at your sync folder, then list only what you want, relative to that folder:
   ```
   CAP scope set sync_root "<your OneDrive folder>"
   CAP scope add --source shared-files "Shared/Planning"
   CAP scope add --deny --source shared-files Confidential
   ```
   A folder entry means every readable file inside it, so list a folder only when you want all of it. A deny entry blocks any path containing it.
4. `CAP run --source shared-files --dry-run`, then `CAP run --source shared-files`. Each file is read once at a paced rate and
   converted; `docx`, `pptx`, `xlsx`, `pdf`, `html`, `md` and `txt` are read, up to 100 files a run.
5. Copies go to `<DATA>/captured/shared-files/`. To keep this source on this machine only, run
   `CAP scope set placement.shared-files local` (copies then sit under `<WB>/capture/local/shared-files/`; register that
   folder yourself with `add-root`, guide 28). Copies in the work cloud fall under your organisation's retention and DLP rules.
6. Refresh the index (guide 29).

Hard stop rule: exit code 3 means capture stopped on purpose. Report `stop.kind`, `stop.reason` and `stop.ask` word for
word. `docs/admin-asks.md` has the ask for IT.

The Teams and Outlook-on-the-web capture sources are deferred in this release (those web apps read data with POST requests, which capture blocks).

## Verify
- The run report in `<WB>/capture/runs/` counts files written and skipped, with a reason for each skip.
- A search with `--source shared-files` finds a phrase from one of the files.

## Common failures
- **A file is skipped as labelled:** by design (guide 37). `--include-labelled` only where policy allows a local plaintext copy.
- **Entry outside the sync folder refused:** entries must resolve inside `sync_root`.
- **File is online-only:** it is read through one paced download, so keep the list short; never list a whole library.
- **Nothing written:** the shortcut has not synced yet, or the scope entry is misspelled; `CAP scope list` shows what is set.
