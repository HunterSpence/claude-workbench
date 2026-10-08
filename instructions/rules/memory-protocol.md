# Memory protocol (plain-Markdown knowledge base)

Auto memory is off in both settings profiles, so there is one memory system: the knowledge base
(KB) at `{{KB_ROOT}}`, one folder per domain with a `HOT.md` summary, plus `_shared/HOT.md`. The
`save` skill (workbench-kb plugin) owns the exact commands.

## Conventions
- One note owns each fact; everything else points to it by relative path.
- A changed fact keeps its history in the KB note: `SUPERSEDED (YYYY-MM-DD): was X -> now Y`, never
  deleted. Always-loaded files carry only the current value plus its date or owning note.
- Rules the user states as permanent are marked **NEVER** or **ALWAYS**, with the date.

## Write path: journal, don't edit shared state
- **After significant work, journal it** with the `save` skill (status, open items, the note it
  touches). Appends can't collide, so parallel sessions lose nothing.
- **In-flight state** (the KB's active-context file) is written only through the `save` skill,
  which merges under a lock. Tempted to edit it by hand? Journal instead and say why.
- **Permanent lessons don't go in in-flight state:** a permanent user rule goes in a rules file or
  USER.md; an incident lesson goes in a rules file with a pointer to the KB note that recorded it.
- **A save is due after:** a file edited outside the KB, a root cause found, a decision a future
  session needs, a tracked number changed, a non-obvious routing call.
- **Never put a credential value, another tenant's data, or data the KB isn't approved for in the
  KB.** Keep `{{KB_ROOT}}` in a work-approved location. If it is a git repo, keep it out of
  OneDrive-synced folders and push it only to an approved work remote, if at all. Nothing in the kit
  pushes it by default.

## Read path: search before concluding silence
- Before acting on a domain, read its `HOT.md` and `_shared/HOT.md`; go deeper with the `save`
  skill's search.
- **A miss is not evidence of absence.** Search is keyword-based: retry once with the note's own
  words (tool, ID, file name) before concluding nothing is recorded.

## Size
- Always-loaded files are re-read on every call. A new rule costs a demotion elsewhere, not creep.
- **Over budget: demote, never compress in place.** Move the least-used section verbatim into a KB
  note, read it back, and leave a one-line pointer. Read before you overwrite; append for logs.

## Compaction
Keep: files you modified, PR numbers and URLs, unresolved errors verbatim, the current phase and
next step, and any ID or credential *name* needed to resume.
