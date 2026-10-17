---
name: save
description: "Save this session's knowledge to the Markdown knowledge base (domain notes, active-context.md, a daily log line), then reindex. Use before /compact, when the user wraps up, when a precompact save is pending, or when work worth keeping happened."
---

# save

The driver is `${CLAUDE_PLUGIN_ROOT}/scripts/save_driver.py`; run it with `${user_config.python}`.
Below, `DRIVER` means `"${user_config.python}" "${CLAUDE_PLUGIN_ROOT}/scripts/save_driver.py"`.
The knowledge base root is `WORKBENCH_KB_ROOT` (set by the bootstrap); the driver prints it as `kb_root`.
Bare `/save` starts this skill too, the same as `/workbench-kb:save`.

Mid-session, never edit `active-context.md`. Journal one line instead (appends never collide):
```bash
DRIVER --inbox-add "<status + what is open + which note holds the detail>"
```
Under 2 KB, no backticks, no credential values (the driver masks credential shapes, but refer to secrets by name).

## Step 1: pre-flight (one call, Bash timeout 300000 ms)
```bash
DRIVER --pre
```
Do each item in its `next` list, in order. Keep `ac_base` for step 3.
- **Skip gate** (never when a precompact save is pending): count the save markers that fired this session (the
  "A save is due after" list in `rules/memory-protocol.md`). If fewer than 2 fired AND `last_save_minutes_ago` is
  under 30, or nothing worth keeping happened and `ac_hash_already_saved` is true, run
  `DRIVER --post --skip --note "<why>"` and stop. The user saying "save anyway" or `/workbench-kb:save force` bypasses it.
- **Journal window:** the file named by `inbox_file` holds one JSON entry per line. Fold every entry without
  `"folded": true` into your active-context draft. `"mine": false` entries came from other sessions. Entries with
  `"folded": true` were offered to an earlier save: re-add one only if active-context lost it.

## Step 2: knowledge-base writes (your judgment)
Domains are the KB root's folders that hold a `HOT.md` (the `domains` field of `--pre`). Route by topic, usually one or two domains:
- `platform`: the applications you build: architecture, UI, testing, code review.
- `infra`: servers, containers, CI/CD, networking, DNS, certificates, monitoring.
- `data`: databases, pipelines, schemas, data quality.
- `ai`: models, agents, prompts, retrieval, evaluation, the assistant itself.
- `ops`: how work runs: this knowledge base, docs, cost, research, debugging.
- `projects`: multi-session efforts, one folder each with a `00-index.md`.
- `security`: secrets handling, hardening, findings, compliance.
- `_shared`: facts every task needs: conventions, environment, tools, contacts by role.
1. **`<domain>/HOT.md`**: only if live state changed. Sections: `## Current state`, `## Decision heuristics`,
   `## Error blacklist` (symptom -> root cause -> fix). Respect `warn_hot` / `over_cap_hot`; over the cap, run
   `kb_demote.py --domain <d> --match "<text>"` (in the same `scripts/` folder). Never shorten text in place.
   - One fact, one home: link to the note that owns a fact instead of repeating it.
   - Changing a fact: keep the old line, marked `SUPERSEDED (YYYY-MM-DD): was X, now Y.`
   - **Error blacklist demotion:** an entry whose fix is deployed and verified AND is more than two weeks old is,
     on the next save that touches that domain, collapsed to one line (`symptom -> root cause -> fix (date)`); its
     narrative moves to `history.md`.
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

Never write a credential value anywhere.
- **No re-reads.** Do not read a file back after Edit or Write to check it: an edit applies only when its checks pass, so a call that succeeded has changed the file.
- **The driver writes the daily log** (`daily/`, one line per save) and stamps `updated:` in front matter. Do not write
  either by hand. A fact registered in `_shared/facts.json` has one owner note: change it there, and run
  `kb_health.py facts` (same `scripts/` folder) if you moved a value.

## Step 3: active-context.md (through the driver only)
A settings deny rule refuses a direct edit of `active-context.md`: draft in the temp folder and use `--ac-write`.
Write your full new version to a scratch file in the system temp folder (stay within `ac_bytes_left` bytes; in-flight items only, no rules).
Adding more than the budget allows means removing the difference in this same rewrite: cut finished work whose
detail already lives in a KB note (the link is the entry once the work is done). Never cut a rule pointer or an
open item that waits on the user. Keep dated items in ISO form (`YYYY-MM-DD`) so session start can surface them.
Then:
```bash
DRIVER --ac-write <draft-file> --base <ac_base>
```
- `status: written` prints a fresh `ac_base`. Any further `--ac-write` in this save passes THAT one.
- `status: conflict`: another session changed the same lines. Edit the `conflict_file` it names (keep both
  sessions' facts, remove the markers), then re-run `--ac-write <conflict_file> --base <the base it printed>`.

## Step 4: post (one call, Bash timeout 300000 ms)
```bash
DRIVER --post --domains ops,infra --note "<one-line summary>" --files <file1> <file2>
```
`--files`: every KB file you wrote, as separate arguments. Add `--push` only when the user asked for it and the
KB folder has a remote they configured. A scheduled backup of the knowledge base must never commit to the repository
this driver commits to: give it its own repository or folder.

| Result | Meaning, and what to do |
|---|---|
| exit 3 | credential-shaped values found: replace each with `[REDACTED]`, refer to it by name, re-run |
| exit 4 | a touched HOT.md is over the hard cap: `kb_demote.py`, re-run |
| exit 0 + `action_required` | read it; several reasons are joined by `ALSO:` |
| `THIS SAVE DID NOT COMPLETE` | active-context is past its cap and grace band: trim through `--ac-write`, re-run |
| `cred_unscanned` | a `--files` path does not exist, so it was not scanned: fix the path, re-run |
| `stamped` / `stamp_skipped` | notes given a fresh `updated:` (only those named in `--files` whose content changed since `--pre`); a skipped one says why (no front matter, over its cap): no action unless you expected a stamp |
| `advisories` | one line each: the size of the always-loaded instructions (at most once a day), and weekly the notes marked deprecated. Information only. `not due (...)` means it ran recently; `skipped: ...` means that tool is missing, failed or is turned off (`SAVE_ADVISORIES=0`); the save is unaffected |
| `find_refresh` | `started`: a detached refresh of the find index was launched (at most one per 30 min). `skipped: ...` says why (no find setup, too soon, `SAVE_FIND_REFRESH=0`). No action either way |
| `recent_other_saves` | not empty: another session saved in the last 15 minutes, so mention it; the merge already kept its lines |
| `git_commit` / `git_push` | `skipped` unless the KB is a git repository / you passed `--push` with a remote |

## Step 5: report (at most 5 lines)
```
save complete: domains [..], notes written N, mode inline|precompact-resume
caps OK (warn: ..) | credential scan CLEAN | reindex ok | git: commit ok / skipped
```

## After compaction
When session start says a precompact save is pending (or `--pre` reports `resume_pending`), read the snapshot `--pre`
names and write what it knew (steps 2 to 4). Use the snapshot, not the live `active-context.md`, when a parallel session
rewrote that file since: the live file may no longer hold what this session knew. If the snapshot is skeletal (a few
lines, nothing of the session), write a minimal history entry with what you do know and still run `--post`, so the flag
clears and the banner stops. The completed `--post` clears this session's flag; without a session id in the environment
it clears the one flag it claimed (`flag_claimed_without_session_id: true`).

## Search and health
- Search: `"${user_config.python}" "${CLAUDE_PLUGIN_ROOT}/scripts/kb_search.py" "<terms>" [--domain d]`.
  A miss is not proof of absence: retry once with the note's own words.
- Health: `"${user_config.python}" "${CLAUDE_PLUGIN_ROOT}/scripts/kb_health.py"`.
- Retrieval check: `"${user_config.python}" "${CLAUDE_PLUGIN_ROOT}/scripts/kb_eval.py"` runs your own known-answer
  set (`--init` writes a starter `kb_eval_set.json` in the KB root). Run it monthly and after big KB reorganisations;
  a falling hit@5 means notes need clearer titles or the answer moved.
