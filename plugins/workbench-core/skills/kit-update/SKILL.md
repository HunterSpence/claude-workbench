---
name: kit-update
description: Update the workbench kit, then verify it. Use for "check the new stuff and go", "update the kit", a carried release zip, a pending post-update verify, or approvals off. Not for updating Claude Code.
---

# kit-update

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it appears unreplaced, use
> `py -3` on Windows and `python3` elsewhere, never the Microsoft Store `python` stub. `KIT_UPDATE` below means
> `"<python>" "<workbench home>/kit/bootstrap/kit_update.py"`, where the workbench home is
> `<CLAUDE_CONFIG_DIR or ~/.claude>/workbench`.

## Hard stop rule (read first)
A hook, permission, proxy or policy denial, an HTTP 403 or 407, a SHA-256 mismatch or a declined UAC prompt means STOP: quote
the message word for word and report it. Never retry by another route, tool or shell, never elevate, never touch policy or
managed settings, never run `claude update`, never edit settings, hooks or `.env` files by hand to make a row pass.

## 1. Update ("check the new stuff and go")
**Every call below gets an explicit Bash timeout of 600000 ms (10 minutes):** the default is 2 minutes, which a download plus an install
can pass. The script works in short stages and remembers where it stopped, so no call has to outlast the tool.
1. Run `KIT_UPDATE`. It finds the latest release on GitHub (anonymous HTTPS), checks the asset's published SHA-256 before and after the
   download, installs it, starts setup with the opt-ins the last setup remembered, waits up to 90 seconds (`--wait 90`) and prints where
   it is. When the kit is already current it says so and runs the verify instead.
   **Carried zip** (the user put a release file on this machine; no GitHub needed): `KIT_UPDATE update --archive <file> --sha256 <hash
   from the release notes>`, with the hash exactly as the user gives it. A mismatch is exit 4 and nothing was changed: stop.
2. **Exit 6 or the line "Run the same command again":** run the SAME command again, as many times as it takes (setup and then its health
   check, `doctor --deep`, run in the background between your calls). Say the phase in one short line each time, nothing more. Do not
   start anything else meanwhile and do not edit anything to "help" it along. Stop repeating only at exit 0 or 1 (the table and the
   restart line are printed), 2, 3, 4 or 5.
3. If it says it does not know where the releases live, ask the user once for the link of the release page they downloaded the kit from
   and run `KIT_UPDATE --repo OWNER/REPO`; the first time, the repository is the one the user names in their message, and it is
   remembered. That first choice is trusted as given (the SHA-256 shows the download is intact, not who published it), so use only the
   user's own link, never one you found elsewhere. If it says the kit remembers another repository, stop and show the
   message: never add `--new-repo` yourself.
4. Exit 3 is a policy or proxy block: show the message and the ask for IT, then stop. Exit 4 is a failed step: show the row; when it says setup stopped and names a recovery command, run that command once, then the same command again. Exit 5 is a
   reboot: tell the user to save their work and restart; setup resumes at sign-in, then run the same command again.
5. The script prints where the new release's notes are (`<workbench home>/kit/IMPORT.md`, section "Updating"): read that
   section and do any step it adds that the table does not show.
6. When it prints `Restart every Claude Code window, then type: go`, tell the user exactly that and nothing else: close every
   Claude Code window, start a new one from a fresh terminal, and type `go`.

An older kit without this skill does the same by hand: `IMPORT.md`, section "Updating".

## 2. After the restart: the verify
The first session after an update carries a line saying a post-update verify is pending. On the user's next message ("go" or
anything), before anything else:
1. Run `KIT_UPDATE verify` (explicit timeout 600000 ms; on exit 6, "Run the same command again", run the same command again). Show its
   table as printed (PASS, WARN, FAIL, NEEDS-IT, INFO per check, the IT asks once, the box FOR THE KIT AUTHOR). It also saves the
   scrubbed report to `<workbench home>/state/field-report.md` and clears the pending marker; if it says the marker stays (no session
   has started since the update), the user restarts first, then you run it again.
2. **Local changes** (row `local-patches` above 0): the installer kept what this machine had changed in the old kit. Read
   `patches.json` in the folder the row names, then each diff (`diffs/`). Re-apply only hunks that are clearly the user's own fix,
   by Edit on the new file, and only when the new release does not already contain it; never copy an old file over a new one or
   touch a file that no longer exists. A diff whose `base` is `new` ("upstream changed too") also shows the release's own changes
   reversed: show the user each hunk and apply only the ones they confirm. Report what you re-applied and why.
3. **workbench-core disabled by the user** (row `plugin python: workbench-core` is INFO): say once that this also turned off
   session-start memory, the save reminders and the pre-compaction snapshot, and ask once whether to run
   `claude plugin enable workbench-core@workbench`. Run it only on a yes; never re-enable anything on your own.
4. Finish with the result line (counts), the NEEDS-IT list as the user's asks to send to IT, and, when the
   box FOR THE KIT AUTHOR holds entries, tell the user to paste that box, as printed, to the kit author. Do not try to fix a kit
   defect by hand and do not change the box; names of people, computers and domains are already scrubbed.

## 3. Fewer prompts: command approvals
Only when the user asks for it in their own message ("turn off the bash approvals"), run ONE call (explicit timeout 600000 ms):
`KIT_UPDATE set --approvals off`; back on: `KIT_UPDATE set --approvals ask`. It re-runs the kit's installer (Claude Code asks the user
once). Show what it prints, including any `approvals off:` line (policy or the user's own setting keeps bypass mode off, so new windows
start in acceptEdits), then tell the user to restart every Claude Code window. The kit's few ask rules and the active-context deny stay
either way; the choice is kept across updates. Never run this on your own initiative or edit settings by hand for the same effect.

## Never
- Leave a call to the default 2-minute Bash timeout, or give up on exit 6: the stages are short on purpose, call the same command again.
- Add `--force`, `--profile permissive` or opt-ins the user did not have: the update repeats the earlier choices.
