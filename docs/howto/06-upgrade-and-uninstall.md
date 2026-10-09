# Upgrade the kit, or remove it completely

Automates it: `py -3 <KIT>/bootstrap/setup.py undo-config`

## When to use
A newer tagged release is out, or you want the kit gone from this laptop. `<KIT>` is the kit folder (guide 01).

## Steps
**Upgrade**
1. Back up first: `py -3 <KIT>/bootstrap/setup.py backup` (the zip goes to `<DATA>/backup/`).
2. Download the newer tag, verify its SHA-256, unpack it somewhere new (`IMPORT.md`).
3. From the new folder run the installer the same way: dry run, read the plan, then `--apply`. Keep the same
   `--git-hosts` and `--with` choices. It keeps your earlier knowledge-base and data folders and backs up every file it changes.
4. Run `/workbench-core:setup` again so new packages and checks are applied.

**Remove**
1. Dry run: `py -3 bootstrap/install.py --uninstall`. It lists every file it would restore or remove.
2. Apply: `py -3 bootstrap/install.py --uninstall --apply`. It also undoes machine changes setup recorded (scheduled
   task, resume value, user variables, git setting). To do only that part: `py -3 <KIT>/bootstrap/setup.py undo-config --apply`.
3. Add `--purge-backups` to the uninstall once you are sure; it deletes the `backups` folder in the workbench folder.
4. Your own data is kept on purpose: the knowledge base `<KB>/`, `<DATA>/backup/`, client profiles in `<HOME>/.claude-profiles/`
   and capture settings. `bootstrap/layout.json` lists each path and whether uninstall removes it. Delete what you no longer want yourself.

## Verify
- After an upgrade, `py -3 <KIT>/bootstrap/setup.py doctor` exits 0 or 1 and `/plugin` lists the new version.
- After an uninstall, `/plugin` no longer lists the workbench plugins and the scheduled task
  `\claude-workbench\knowledge-refresh` is gone (`schtasks /Query /TN "\claude-workbench\knowledge-refresh"` fails).

## Common failures
- **A file you edited is not restored:** the uninstall keeps a copy of anything you changed after the install in its own backup folder.
- **Uninstall cannot find a manifest:** the workbench folder was moved or deleted; the dry run says so. Remove the
  leftovers named in `bootstrap/layout.json` by hand.
- **The `claude` command is missing:** run uninstall with `--no-cli`; it prints the plugin commands to run yourself.
- **WSL still has the kit:** it has its own configuration; run the same uninstall inside the distribution.
