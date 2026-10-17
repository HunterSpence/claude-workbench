# Upgrade the kit, or remove it completely

Automates it: `py -3 <KIT>/bootstrap/setup.py undo-config`

## When to use
A newer tagged release is out, or you want the kit gone from this laptop. `<KIT>` is the kit folder (guide 01).

## Steps
**Upgrade**
1. Back up first: `py -3 <KIT>/bootstrap/setup.py backup` (the zip goes to `<DATA>/backup/`).
2. Tell Claude Code: **"check the new stuff and go"** (the `kit-update` skill; "update the kit" works too). It finds the latest
   release, checks its SHA-256, installs it, runs setup with the same `--with` choices and profile as last time, runs
   `setup.py doctor --deep` and ends with one line: close every Claude Code window, start a new one, type `go`.
3. After the restart, your first message starts the verify: one table of PASS, WARN, FAIL and NEEDS-IT rows, the asks for your IT
   team listed once, and a box FOR THE KIT AUTHOR to paste to the author (names and hosts are scrubbed; it is also saved as
   `<WB>/state/field-report.md`). Nothing else needs you except real approvals and the restart. A `local-patches` row above 0
   means the installer kept files you had changed in the old kit (with diffs, in `<WB>/state/local-patches/`); Claude re-applies
   one only when the new release does not already fix the same thing.
4. No GitHub on this machine: copy the release zip here and say "update the kit from `<file>`, SHA-256 `<hash>`" (the hash from
   the release notes). That runs `py -3 <KIT>/bootstrap/kit_update.py update --archive <file> --sha256 <hash>`, which checks the
   hash before it changes anything. A 0.3.4 kit has no `--archive`: use the paste prompt in `IMPORT.md`, section "Updating".
5. Without the skill (0.3.1 or older), or without Claude Code: the by-hand steps are in `IMPORT.md`, section "Updating":
   verify the zip's SHA-256, unpack it, run `install.py --apply --profile <profile>` with the same `--with` choices (it keeps
   your earlier knowledge-base and data folders and backs up every file it changes), then `setup.py run --detach` and
   `setup.py doctor --deep`.

**Remove**
1. Dry run: `py -3 bootstrap/install.py --uninstall`. It lists every file it would restore or remove.
2. Apply: `py -3 bootstrap/install.py --uninstall --apply`. It also undoes machine changes setup recorded (scheduled
   task, resume value, user variables, git setting). To do only that part: `py -3 <KIT>/bootstrap/setup.py undo-config --apply`.
3. Add `--purge-backups` to the uninstall once you are sure; it deletes the `backups` folder in the workbench folder.
4. Your own data is kept on purpose: the knowledge base `<KB>/`, `<DATA>/backup/`, client profiles in `<HOME>/.claude-profiles/`
   and capture settings. `bootstrap/layout.json` lists each path and whether uninstall removes it. Delete what you no longer want yourself.

## Verify
- After an upgrade, `py -3 <KIT>/bootstrap/kit_update.py verify` shows no FAIL row (NEEDS-IT rows are asks for IT, not failures),
  `py -3 <KIT>/bootstrap/setup.py doctor` exits 0 or 1 and `/plugin` lists the new version.
- After an uninstall, `/plugin` no longer lists the workbench plugins and the scheduled task
  `\claude-workbench\knowledge-refresh` is gone (`schtasks /Query /TN "\claude-workbench\knowledge-refresh"` fails).

## Common failures
- **"does not know where its releases live":** run `py -3 <KIT>/bootstrap/kit_update.py --repo OWNER/REPO` once, with the repository of the
  release page you downloaded the kit from; it is remembered.
- **A hash mismatch:** nothing was installed (a download is deleted; a carried zip is left as it is). Download the release
  again from its release page.
- **A plugin you turned off:** the update keeps it off and the verify shows it as INFO. Turning `workbench-core` off also turns off
  session memory and the save reminders: `claude plugin enable workbench-core@workbench` brings it back.
- **"Run the same command again" (exit 6):** the update is a chain of short steps; run the same command again, as often as it says so
  (each call waits about 90 seconds; Claude gives every call a 10-minute timeout).
- **"this kit remembers ... as the repository":** the kit only takes releases from the repository it remembered. If the project really
  moved, run it once with `--repo OWNER/REPO --new-repo`.
- **A file you edited is not restored:** the uninstall keeps a copy of anything you changed after the install in its own backup folder.
- **Uninstall cannot find a manifest:** the workbench folder was moved or deleted; the dry run says so. Remove the
  leftovers named in `bootstrap/layout.json` by hand.
- **The `claude` command is missing:** run uninstall with `--no-cli`; it prints the plugin commands to run yourself.
- **WSL still has the kit:** it has its own configuration; run the same uninstall inside the distribution.
