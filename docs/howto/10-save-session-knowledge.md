# Save what a session learned

Automates it: `/save` or `/workbench-kb:save`

## When to use
Before `/compact`, when you wrap up, or after a root cause, a decision a later session needs, a number that changed, or
a file edited outside the knowledge base (KB). `<KIT>` is the kit folder (guide 01).

## Steps
1. During the session, journal in one line instead of editing shared state (appends never collide):
   `py -3 <KIT>/plugins/workbench-kb/scripts/save_driver.py --inbox-add "status, what is open, which note holds detail"`
   Keep it under 2 KB and write no backticks: a shell runs what sits between two of them before the driver sees the text, and
   the driver warns when it finds one. Refer to a secret by name, never its value.
2. To save, run `/save` (or `/workbench-kb:save`; both start the same skill). It runs `--pre`, then you (or Claude) write
   the notes it asks for, then `--post`.
   By hand: `py -3 <KIT>/plugins/workbench-kb/scripts/save_driver.py --pre`
3. Notes go in the KB root (`<KB>/`) under a domain folder that has a `HOT.md`. One fact has one home; change a fact by
   keeping the old line marked `SUPERSEDED` and adding the new one.
4. Finish with `--post --domains <list> --note "<one line>" --files <each file you wrote>`. It scans for credential-shaped
   text, checks the size caps and rebuilds the search index.
5. Find it later: `py -3 <KIT>/plugins/workbench-kb/scripts/kb_search.py "<words>" --domain <domain>`. When the words you
   remember are not the note's words, ask `find` over the KB (guide 27).
6. Know where the state lives. The save lock, the pre-compact flags, the active-context snapshots, the save metrics and the
   journal windows sit on this machine, in `<WB>/kb-state/<key>/` (`<WB>` is the workbench folder inside your Claude config
   folder; `<key>` is eight hex digits of the KB path, so two knowledge bases never share a folder). The KB folder holds only
   notes, so a synced KB folder never carries a lock. An earlier kit kept this in `<KB>/.state/`: the first `--pre` copies it
   across once, never moves or deletes it, and the old folder stays readable for one release. Delete it by hand after that.

## Verify
- The `--post` result says the credential scan is clean and the reindex succeeded.
- `kb_search.py` returns your note for a word from its title. A miss is not proof of absence: retry once with the note's own words.
- `py -3 <KIT>/plugins/workbench-kb/scripts/kb_health.py` reports no cap breach (add `--json` for a script).
- After a `--pre`, `<WB>/kb-state/` holds a folder for this KB, and no new lock or snapshot appears under `<KB>/`.

## Common failures
- **Exit 3:** credential-shaped values were found. Replace each with `[REDACTED]`, name the credential instead, run again.
- **Exit 4:** a `HOT.md` is over its cap. Move older entries out with `py -3 <KIT>/plugins/workbench-kb/scripts/kb_demote.py --domain <d> --match "<text>"`; never shorten in place.
- **`--pre` says another session holds the save lock:** a save in another window is running. Wait and run it again; the lock is
  released when that save ends, so never delete the file while it runs. Journaling with `--inbox-add` does not take the save lock.
- **Session start says a pre-compact save is pending:** run the save first, before new work.
- **KB inside a git repository in OneDrive:** not allowed; the doctor fails it (guide 13).
