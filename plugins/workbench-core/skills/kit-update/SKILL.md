---
name: kit-update
description: Update the workbench kit, then verify it. Use for "check the new stuff and go", "update the kit", "check for kit updates", a pending post-update verify, or fewer prompts (command approvals off, guard down). Not for updating Claude Code itself.
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
5. The script prints where the new release's own notes are (`<workbench home>/kit/IMPORT.md`, section "Updating"). Read that
   section: it belongs to the release just installed, so if it adds a step the script's table does not show, do that step too.
6. When it prints `Restart every Claude Code window, then type: go`, tell the user exactly that and nothing else: close every
   Claude Code window, start a new one from a fresh terminal, and type `go`.

An older kit without this skill does the same by hand: `IMPORT.md`, section "Updating".

## 2. After the restart: the verify
The first session after an update carries a line saying a post-update verify is pending. On the user's next message ("go" or
anything), before anything else:
1. Run `KIT_UPDATE verify` (explicit timeout 600000 ms; on exit 6, "Run the same command again", run the same command again). Show its
   table as printed (PASS, WARN, FAIL, NEEDS-IT per check, the IT asks once, the box FOR THE KIT AUTHOR). It also saves the scrubbed
   report to `<workbench home>/state/field-report.md` and clears the pending marker; if it says the marker stays (no session has started since the update), the user restarts first, then you run it again.
2. Do the live guard test, which no script can do for you. Make an empty scratch folder under the system temp folder, run
   `git init -b main` in it and `git remote add origin https://example.invalid/scratch.git` (that host never resolves). Then
   try, exactly: `git -C <scratch folder> push --force origin main`.
   - Blocked by the workbench guard (the message names a rule such as push-default-branch), or, at the minimal guard level, a
     prompt from the workbench guard naming force-push-main (tell the user to decline it) = PASS. Record it:
     `KIT_UPDATE record guard-live PASS "blocked by the workbench guard: <rule>"`.
   - The command ran, or failed with a network error instead of a guard message = FAIL:
     `KIT_UPDATE record guard-live FAIL "not blocked: <first line of the output>" --command "forced push of main in a scratch repo"` (never write the push command itself into that text: the guard reads it as a push).
   Then delete the scratch folder (one `Remove-Item -LiteralPath <folder> -Recurse` on its own), and add the guard-live row to the
   table you show.
3. Finish with the result line (counts), the NEEDS-IT list as the user's asks to send to IT (you never send them), and, when the
   box FOR THE KIT AUTHOR holds entries, tell the user to paste that box, as printed, to the kit author. Do not try to fix a kit
   defect by hand and do not change the box; names of people, computers and domains are already scrubbed.

## 3. Fewer prompts: command approvals and the guard level
Only when the user asks for it in their own message, run ONE call (explicit timeout 600000 ms) with what they asked for:
- "turn off the bash approvals" (no prompts before ordinary commands): `KIT_UPDATE set --approvals off`; back on: `--approvals ask`.
- "turn the guard down" or "minimal guard": `KIT_UPDATE set --guard minimal`; back: `--guard standard`.
- Both at once: `KIT_UPDATE set --approvals off --guard minimal`.
The guard asks the user once, because this re-runs the kit's installer. Show what it prints, including any `approvals off:` line (a
policy or the user's own setting keeps bypass mode off, so new windows start in acceptEdits instead), then tell the user to restart
every Claude Code window. At the minimal level the guard refuses nothing and asks only before irreversible steps, anything that
leaves the machine, credential files and changes to its own controls. Both choices are kept across updates. Never run this on your
own initiative, and never edit settings or the allowlist by hand to get the same effect.

## Never
- Leave a call to the default 2-minute Bash timeout, or give up on exit 6: the stages are short on purpose, call the same command again.
- Add `--force`, `--profile permissive` or opt-ins the user did not have: the update repeats the earlier choices.
- Put a skill name, user name, host or company name in a message that leaves the machine.
