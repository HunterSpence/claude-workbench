# Update the tools setup installed

Automates it: `py -3 <KIT>/bootstrap/setup.py update`

## When to use
The doctor's `updates` row warns, a new kit release moved the tested versions, or you want to see what would change
before anything does. `<KIT>` is the kit folder (guide 01); `<WB>` is the workbench folder inside your Claude config folder.

## Steps
1. Look first. This changes nothing and writes the result to `<WB>/state/update.json` and `update.md`:
   `py -3 <KIT>/bootstrap/setup.py update --check`
   Each row has an action:
   - **current**: at or above the version tested for this kit release (`pin` in `bootstrap/packages.json`).
   - **it-managed**: installed by IT or by hand, not by setup. It is listed and never changed.
   - **deferred**: not done now. The `command` column is the one command to run yourself (`update.md` prints it).
   - **skipped-policy**, **denied**: a policy blocks winget or the install. The ask-IT text is in `setup.py status`.
   - **upgraded**, **failed**: the result of a real update.
2. Update what setup installed. Only those tools move, and only to the tested version:
   `py -3 <KIT>/bootstrap/setup.py update`
   A tool counts as upgraded only when its own version call reports the target afterwards; an installer that exits 0
   and leaves the old version is reported as failed.
3. Programs in use are never replaced while you work. Git, PowerShell, Node.js and Claude Code show as deferred with
   their command. Close every window that runs them, then run that command from a plain terminal.
4. Want the newest instead of the tested version? `py -3 <KIT>/bootstrap/setup.py update --with update-latest`. It applies
   to this run only; a later plain run goes back to the tested versions.
5. A setup run does the same update after its verify step. Leave it out with `--no-update` (the installer passes the flag on).
6. The knowledge environment's Python packages are put back on the versions in `requirements.txt`. Newer releases of those
   packages are listed, not installed.
7. `claude update` is your choice and setup never runs it. `--with claude-winget` installs Claude Code from winget, and
   `--with claude-autoupdate` sets `CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE=1` so that install can upgrade itself.

## Verify
- `update --check` exits 0 and `update.md` lists every installed tool with one of the actions above.
- After `update`, each upgraded row shows an `after` version equal to its `target`.
- `py -3 <KIT>/bootstrap/setup.py doctor` shows an `updates` row: OK, or WARN naming the deferred or failed tools.

## Common failures
- **A tool setup installed shows as it-managed:** it was installed before the kit recorded installs, so there is no record
  that setup put it there. Setup leaves it alone; update it yourself, or remove it and run setup again.
- **deferred with exit 0x8A150101:** winget says the program is running (return code `INSTALL_PACKAGE_IN_USE`). Close it and
  run the command.
- **failed, "but reports 2.x, not 2.y":** the installer said it succeeded and the version did not change. Run the printed
  command in a terminal to see the installer's own message, or ask IT whether the version is pinned.
- **denied:** a policy refused it. Setup does not try another route; send the ask-IT text to IT.
- **A machine-wide tool shows as deferred with "never elevates":** it needs an administrator. Setup does not raise its own
  rights; ask IT or run the command in an administrator shell yourself.
