# Memory protocol (plain-Markdown knowledge base)

Auto memory is off in both settings profiles, so there is one memory system: the knowledge base
(KB) at `{{KB_ROOT}}`, one folder per domain with a `HOT.md` summary, plus `_shared/HOT.md`. The
`save` skill (workbench-kb plugin) owns the exact commands.

## Conventions
- One note owns each fact; everything else points to it by its note path (`<domain>/<note>`).
- A changed fact keeps its history in the KB note: `SUPERSEDED (YYYY-MM-DD): was X -> now Y`, never
  deleted. Always-loaded files carry only the current value plus its date or owning note.
- Markers, defined here only: 🔒 a permanent rule the user stated (dated; change it only with a
  dated note) · 👤 an action or decision only the user can take · 🔴 blocking or overdue ·
  🟢 confirmed, in writing · ⚠️ caveat or known-wrong signal · 🚨 safety never-rule · ⇒ therefore.

## Write path: journal, don't edit shared state
- **After a significant response, journal one line** (status, what is open, the note that holds the
  detail): `{{PYTHON}} "{{WORKBENCH_HOME}}/kit/plugins/workbench-kb/scripts/save_driver.py" --inbox-add "<line>"`.
  Under 2 KB, no backticks, no credential values. Appends can't collide, so parallel sessions lose
  nothing.
- **In-flight state** (the KB's active-context file) is written only through the `save` skill,
  which merges under a lock. Tempted to edit it by hand? Journal instead and say why.
- **Permanent lessons don't go in in-flight state:** a permanent user rule goes in a rules file or
  USER.md; an incident lesson goes in a rules file with a pointer to the KB note that recorded it.
  Writing "always" or "never" into active-context means you're in the wrong file.
- **A save is due after:** a file edited outside the KB, a root cause found, a decision a future
  session needs, a tracked number changed, a new credential reference, a non-obvious routing call.
  A session-start "PRECOMPACT SAVE PENDING" notice means `/workbench-kb:save` before anything else.
- **KB state is machine-local:** the save lock, snapshots and metrics live in
  `<claude config dir>/workbench/kb-state/<key>/`, never in the KB folder.
- **The KB holds only data it is approved for:** never a credential value or another tenant's
  data. Keep `{{KB_ROOT}}` in a work-approved place: work OneDrive is fine (version history is the
  backup), but never a git repo inside any OneDrive folder. Push only to approved remotes.

## Read path: search before concluding silence
- Before acting on a domain, read its `HOT.md` and `_shared/HOT.md`; go deeper with
  `{{PYTHON}} "{{WORKBENCH_HOME}}/kit/plugins/workbench-kb/scripts/kb_search.py" "<terms>"`.
- **Before concluding something isn't known, search the KB.** A miss is not evidence of absence:
  search is keyword-based, so retry once with the note's own words (tool, ID, file name), then
  `find search --root kb` (meaning search over the KB).

## Size
- Always-loaded files are re-read on every call. A new rule costs a demotion elsewhere, not creep.
- **Over budget: demote, never compress in place.** Move the least-used section verbatim into a KB
  note, read it back, and leave a one-line pointer. Read before you overwrite; append for logs.
- Monthly, and on a size warning: the save skill's health check and `kb_eval.py`,
  then `brain-audit`.

## Compaction
Keep: files you modified, PR numbers and URLs, unresolved errors verbatim, the current phase and
next step, and any ID or credential *name* needed to resume.
