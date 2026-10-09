# Runbooks

Procedures for the moments that are not day-to-day work: an incident, a re-imaged or replaced laptop, leaving a
project, and leaving the organisation. Each step uses commands that exist in this release; the guides named here
have the full syntax.

**Legal hold:** if a legal hold or preservation notice may cover your work, do not purge, uninstall, re-image or
delete anything (the knowledge base, captured copies, transcripts, journals, session transcripts) until the legal or
security team that issued it tells you in writing that you may.

## 1. Incident
Something sensitive went where it should not, a credential was exposed, a file or page tried to instruct Claude, the
laptop was lost, or an alert fired during a capture run.
1. Stop the session's work. Delete nothing: chats, captured copies, run reports and logs are the evidence.
2. Write down the time, what you saw, the files, tools and accounts involved, and what you already did. Leave every
   secret value out.
3. Report it to your organisation's security reporting channel now, never in a public issue or a chat thread.
4. Treat any credential that appeared in a prompt, file, commit, log or reply as exposed: its owner rotates it.
   Deleting it from a file or from git history does not un-expose it.
5. Contain only what is yours: stop unattended runs and scheduled tasks you started, and when the security team
   asks, sign out the kit's sign-ins (capture's and ingest's `logout`, guide `docs/howto/32-purge-indexed-or-captured-data.md`).
6. If IT asks for diagnostics: `py -3 <KIT>/bootstrap/setup.py doctor --bundle support.zip` (redacted: no notes, no
   tokens). Capture and ingest run reports in `<WB>/capture/runs/` list what was read.
7. Purge, uninstall or re-image only when the security team says so.
The short version for the first minutes is guide `docs/howto/40-incident-first-steps.md`.

## 2. Re-image or a new laptop
Before (on the old machine, if you still have it):
1. `py -3 <KIT>/bootstrap/setup.py backup` writes knowledge-base notes and curated configuration to `<DATA>/backup/`.
   When `<DATA>` is in the work OneDrive, the knowledge base and captured copies are already there.
2. Copies you kept local on purpose (`<WB>/capture/local/`) are not in the work cloud: move them to an approved place
   or let them go.
3. The search index, the embedding model and the capture browser profile are not backed up. The first two are
   rebuilt; the profile holds sign-in cookies and is never copied.
After (on the new machine):
1. Install as on day 1 (`IMPORT.md`), with the same `--data-root` if you chose one.
2. Inspect the backup first: `py -3 <KIT>/bootstrap/setup.py restore <zip> --to <empty folder>`. Then apply it:
   `py -3 <KIT>/bootstrap/setup.py restore <zip> --apply`. Settings files (whose hooks run code) are restored only
   with `--restore-settings`, after you have read them.
3. Let setup rebuild the index; sign in to capture again with its `login` if you use it.
4. `py -3 <KIT>/bootstrap/setup.py doctor` exits 0, and the guard test in `IMPORT.md` is blocked.

## 3. Leaving a project
1. Hand over what the project needs (decisions, open items, notes) through the project's own channels: its
   repository, wiki or tracker, as your organisation's policy says. The knowledge base is your working memory, not
   the project's record.
2. Remove the project's libraries from `find` (`remove-root <label> --purge`), its capture scope entries, and its
   captured copies and meeting or mail copies (guide `docs/howto/32-purge-indexed-or-captured-data.md`).
3. A separate profile for the project: `py -3 <KIT>/bootstrap/profile.py remove <name>`; add `--purge-kb` to delete
   its knowledge base once the handover is done.
4. Sign out of the project's hosts and tenants (`gh auth logout --hostname <host>` and the like), and tell the owners
   of any token issued for the project that it can be revoked.
5. Search your knowledge base for the project's name and move or delete notes that belong to it.

## 4. Leaving the organisation
1. Check for a legal hold first (top of this page). If one applies, stop here and ask.
2. Hand over work notes as your manager or the offboarding process asks. Work data stays with the organisation:
   never copy the knowledge base, captured copies or transcripts to personal storage, mail or devices.
3. Purge what the kit holds on the laptop (guide `docs/howto/32-purge-indexed-or-captured-data.md`): captured copies,
   meeting and mail copies, every `find` root, then sign out of capture and ingest.
4. Uninstall: `py -3 <KIT>/bootstrap/install.py --uninstall --apply` (`IMPORT.md`, "Removing
   everything"), sign out of Claude Code (`/logout`) and of every git host.
5. `<DATA>/` is left in place by the uninstall. Whether it is deleted or kept is the organisation's decision under its
   retention policy, not yours: leave it unless the offboarding process tells you otherwise.
6. You may keep personal working-style preferences only if they hold no work data at all.
