# Runbooks

Procedures for the moments that are not day-to-day work: a re-imaged or replaced laptop, leaving a project, and
leaving the organisation. Each step uses commands that exist in this release; the guides named here
have the full syntax.

**Legal hold:** if a legal hold or preservation notice may cover your work, do not purge, uninstall, re-image or
delete anything (the knowledge base, captured copies, transcripts, journals, session transcripts) until the team that
issued it tells you in writing that you may.

Diagnostics for IT: `py -3 <KIT>/bootstrap/setup.py doctor --bundle support.zip` (redacted: no notes, no tokens).

## 1. Re-image or a new laptop
Before (on the old machine, if you still have it):
1. `py -3 <KIT>/bootstrap/setup.py backup` writes knowledge-base notes and curated configuration to `<DATA>/backup/`.
   When `<DATA>` is in the work OneDrive, the knowledge base and captured copies are already there.
2. Copies you kept local on purpose (`<WB>/capture/local/`) are not in the work cloud: move them or let them go.
3. The search index, the embedding model and the capture browser profile are not backed up. The first two are
   rebuilt; the profile holds sign-in cookies and is never copied.
After (on the new machine):
1. Install as on day 1 (`IMPORT.md`), with the same `--data-root` if you chose one.
2. Inspect the backup first: `py -3 <KIT>/bootstrap/setup.py restore <zip> --to <empty folder>`. Then apply it:
   `py -3 <KIT>/bootstrap/setup.py restore <zip> --apply`. Settings files (whose hooks run code) are restored only
   with `--restore-settings`, after you have read them.
3. Let setup rebuild the index; sign in to capture again with its `login` if you use it.
4. `py -3 <KIT>/bootstrap/setup.py doctor` exits 0, and `/hooks` lists the workbench hooks.

## 2. Leaving a project
1. Hand over what the project needs (decisions, open items, notes) through the project's own channels: its
   repository, wiki or tracker. The knowledge base is your working memory, not the project's record.
2. Remove the project's libraries from `find` (`remove-root <label> --purge`), its capture scope entries, and its
   captured copies and meeting or mail copies (guide `docs/howto/32-purge-indexed-or-captured-data.md`).
3. A separate profile for the project: `py -3 <KIT>/bootstrap/profile.py remove <name>`; add `--purge-kb` to delete
   its knowledge base once the handover is done.
4. Sign out of the project's hosts (`gh auth logout --hostname <host>` and the like).
5. Search your knowledge base for the project's name and move or delete notes that belong to it.

## 3. Leaving the organisation
1. Check for a legal hold first (top of this page). If one applies, stop here and ask.
2. Hand over work notes as your manager or the offboarding process asks.
3. Purge what the kit holds on the laptop (guide `docs/howto/32-purge-indexed-or-captured-data.md`): captured copies,
   meeting and mail copies, every `find` root, then sign out of capture and ingest.
4. Uninstall: `py -3 <KIT>/bootstrap/install.py --uninstall --apply` (`IMPORT.md`, "Removing
   everything"), sign out of Claude Code (`/logout`) and of every git host.
5. `<DATA>/` is left in place by the uninstall; delete it or leave it as the offboarding process says.
