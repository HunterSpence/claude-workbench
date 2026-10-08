---
name: save
description: "Save this session's knowledge to the Markdown knowledge base (<domain>/ notes, active-context.md, a daily log line), then reindex. Use before /compact, when the user wraps up, when a session-start notice says a precompact save is pending, or any time work worth keeping happened. A driver does the mechanics (journal folding, caps, credential scan, locked merge, reindex, optional local git commit); you do the judgment writes. Never pushes anywhere unless the user configured a remote and asks for --push."
---

# save

The driver is `${CLAUDE_PLUGIN_ROOT}/scripts/save_driver.py`; run it with `${user_config.python}`.
Below, `DRIVER` means `"${user_config.python}" "${CLAUDE_PLUGIN_ROOT}/scripts/save_driver.py"`.
The knowledge base root is `WORKBENCH_KB_ROOT` (set by the bootstrap); the driver prints it as `kb_root`.

Mid-session, never edit `active-context.md`. Journal one line instead (appends never collide):
```bash
DRIVER --inbox-add "<status + what is open + which note holds the detail>"
```
Under 2 KB, no backticks, no credential values (the driver masks credential shapes, but refer to secrets by name).

## Step 1: pre-flight (one call)
```bash
DRIVER --pre
```
Do each item in its `next` list, in order. Keep `ac_base` for step 3.
- **Skip gate:** if nothing worth keeping happened (no decision, root cause, changed fact, new runbook or open
  item) and `ac_hash_already_saved` is true, run `DRIVER --post --skip --note "<why>"` and stop.
- **Journal window:** the file named by `inbox_file` holds one JSON entry per line. Fold every entry without
  `"folded": true` into your active-context draft. `"mine": false` entries came from other sessions. Entries with
  `"folded": true` were offered to an earlier save: re-add one only if active-context lost it.

## Step 2: knowledge-base writes (your judgment)
Domains are the KB root's folders that hold a `HOT.md` (the `domains` field of `--pre`). Route by topic, usually one or two domains.
1. **`<domain>/HOT.md`**: only if live state changed. Sections: `## Current state`, `## Decision heuristics`,
   `## Error blacklist` (symptom -> root cause -> fix). Respect `warn_hot` / `over_cap_hot`; over the cap, run
   `kb_demote.py --domain <d> --match "<text>"` (in the same `scripts/` folder). Never shorten text in place.
   - One fact, one home: link to the note that owns a fact instead of repeating it.
   - Changing a fact: keep the old line, marked `SUPERSEDED (YYYY-MM-DD): was X, now Y.`
2. **Topic notes** for reusable knowledge (runbooks, configs, patterns): `<domain>/<topic-slug>.md` with
   frontmatter (`title`, `domain`, `tags`, `status`, `updated`), then `## Observations` and `## Relations`.
3. **`<domain>/history.md`**: append one record; skip it if the same heading exists:
   ```markdown
   ## YYYY-MM-DD HH:MM - <task>
   - **Outcome:** Success / Partial / Blocked, one sentence
   - **Key learnings:** the non-obvious gotcha or root cause
   - **Files/notes changed:** paths
   ```
   Use the `stamp` from `--pre` for the heading time.
4. **Subagent `## DISCOVERIES` blocks**: route each to its `domain:` and `note:`.

Work facts stay inside the knowledge base your organisation allows. Never write a credential value anywhere.

## Step 3: active-context.md (through the driver only)
Write your full new version to a scratch file (stay within `ac_bytes_left` bytes; in-flight items only, no rules),
then:
```bash
DRIVER --ac-write <draft-file> --base <ac_base>
```
- `status: written` prints a fresh `ac_base`. Any further `--ac-write` in this save passes THAT one.
- `status: conflict`: another session changed the same lines. Edit the `conflict_file` it names (keep both
  sessions' facts, remove the markers), then re-run `--ac-write <conflict_file> --base <the base it printed>`.

## Step 4: post (one call)
```bash
DRIVER --post --domains ops,infra --note "<one-line summary>" --files <file1> <file2>
```
`--files`: every KB file you wrote, as separate arguments. Add `--push` only when the user asked for it and the
KB folder has a remote they configured.

| Result | Meaning, and what to do |
|---|---|
| exit 3 | credential-shaped values found: replace each with `[REDACTED]`, refer to it by name, re-run |
| exit 4 | a touched HOT.md is over the hard cap: `kb_demote.py`, re-run |
| exit 0 + `action_required` | read it; several reasons are joined by `ALSO:` |
| `THIS SAVE DID NOT COMPLETE` | active-context is past its cap and grace band: trim through `--ac-write`, re-run |
| `cred_unscanned` | a `--files` path does not exist, so it was not scanned: fix the path, re-run |
| `git_commit` / `git_push` | `skipped` unless the KB is a git repository / you passed `--push` with a remote |

## Step 5: report (at most 5 lines)
```
save complete: domains [..], notes written N, mode inline|precompact-resume
caps OK (warn: ..) | credential scan CLEAN | reindex ok | git: commit ok / skipped
```

## After compaction
When session start says a precompact save is pending (or `--pre` reports `resume_pending`), read the snapshot `--pre`
names, write what it knew (steps 2 to 4). The completed `--post` clears this session's flag.

## Search and health
- Search: `"${user_config.python}" "${CLAUDE_PLUGIN_ROOT}/scripts/kb_search.py" "<terms>" [--domain d]`.
  A miss is not proof of absence: retry once with the note's own words.
- Health: `"${user_config.python}" "${CLAUDE_PLUGIN_ROOT}/scripts/kb_health.py"`.
