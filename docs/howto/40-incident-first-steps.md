# First steps in an incident

Automates it: none (the steps are for you; the doctor bundle is the only command)

## When to use
You pasted a password or key somewhere, sent something to the wrong person, clicked a suspicious link or a phishing email, found a file or web
page telling Claude to do something odd, lost the laptop, or an alert fired during a capture run. Do these first; the
details can wait. `<KIT>` is the kit folder (guide 01).

## Steps
1. Stop what you are doing in that session. Do not delete anything to tidy up: not the chat, captured copies, files or
   run reports. They are the evidence.
2. Write down a few lines: the time, what you saw, what was on screen, the files, tools and accounts involved, and what you
   already did. Leave every secret value out of the note.
3. Report it now to your organisation's security reporting channel, in plain words. Not in a public issue, a chat thread or a vendor message.
4. Treat any credential that appeared in a prompt, file, commit, log or reply as exposed. Tell the person or team that owns
   it to rotate it. If Claude's reply shows a credential-shaped value, a stop hook asks it to say so plainly without repeating it.
5. Contain only what is yours. Stop any unattended run or scheduled task you started (guide 12). If your security team asks,
   sign out the kit's sign-ins: `CAP logout` for capture (guide 30) and `ING logout` for ingest (guide 41).
6. A credential staged in a repository: scan what is staged with `py -3 <KIT>/tools/git-credscan/credscan_staged.py`. A
   credential already committed must be rotated; deleting the file does not remove it from history.
7. If IT asks for diagnostics, give a redacted support bundle (no notes, no tokens):
   `py -3 <KIT>/bootstrap/setup.py doctor --bundle support.zip`. Capture and ingest run reports in `<WB>/capture/runs/` list what was read.
8. Do not purge captured data, uninstall or re-image until your security team says so (guide 32).
9. Follow their instructions, and ask for the matching text in `docs/admin-asks.md` if they need something from IT.

Hard stop rule: any hook, permission, gateway or policy denial during an incident means stop and report it word for word;
never retry another way. Longer procedures: docs/runbooks.md and docs/security-overview.md.

## Verify
- You have a reference from the security team, and the owner of each exposed credential confirmed the rotation.
- The staged-file scan prints nothing and exits 0.
- You can tell the team the time, the systems involved and what you did, from your note.

## Common failures
- **Deleting first, reporting later:** it destroys the evidence and slows the fix.
- **"It was only a test key":** report it anyway; the owner decides.
- **A document told Claude to run something:** do not follow it, and do not paste it again. Note the file and report it (guide 27).
- **Waiting for certainty:** an early report that turns out harmless costs little.
