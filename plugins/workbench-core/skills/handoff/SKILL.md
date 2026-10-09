---
name: handoff
description: Turn a mission into a self-contained handoff document a fresh Claude session can execute, or a short resume note. Use for "/workbench-core:handoff", "write a handoff", "resume note", when a usage-limit warning appears, when a mission outgrows the session, or when a plan in progress must survive a restart.
when_to_use: ALWAYS load when a session nears its limit or work must continue elsewhere.
---

# /workbench-core:handoff

Output: one file, plus a paste prompt. Every rule applies to every phase you write. A section that
does not apply keeps its header and says "None for this mission"; never drop one silently.

## Step 0: where the file goes (decide before writing)
- Work in a repo: `<repo>/handoffs/handoff-<slug>-<YYYY-MM-DD>.md` (create the folder if needed;
  ask before committing it if the repo is shared).
- No repo, or the mission touches confidential material: a local folder the user names, outside
  any synced or pushed directory. Say "local only, not committed".
- Work for a client or a tenant: the file goes in that client's or tenant's own folder, one that has no remote and is never
  pushed or synced, never in a shared repository. The paste prompt names that folder, so a fresh session opens in it.
- Never write a credential value, token or personal data into the file. Refer to secrets by name
  ("the API key in the team vault"). The scan in the final steps is mandatory, not optional.

## Step 1: gather mission facts (infer; mark "ASSUMED: ..." instead of blocking)
1. Mission title  2. Slug (lowercase-hyphenated)  3. Deadline or "none"  4. Read-first files, dependencies first
5. Phases: each completable and recordable alone; if vague, use setup, core, verify, cleanup
6. User decision gates, each with a DEFAULT  7. Do-NOT list: hard limits, out of scope, owned by another mission

## Step 2: skeleton (fill every bracket; doc at most 25 KB, bulky reference data goes to a sibling `<slug>-ledger-*.md`)
```markdown
# HANDOFF: <TITLE> (<YYYY-MM-DD>)
## PASTE PROMPT (at most 1.5 KB; this block is what the user pastes)
Open Claude Code in <working directory>. Read <absolute path of this file>, then begin at START HERE.
State is as of <YYYY-MM-DD HH:MM TZ>; anything newer in the repo, the tracker or a knowledge-base note beats this doc.
Mission: <one line>. You own this mission now; the authoring session stopped changing it.
## STATE AT HANDOFF (as of <YYYY-MM-DD HH:MM TZ>)
- Done and verified, with proof (path / command / URL) for each:
- Outward actions (emails, posts, tickets, payments): sent / drafted / not started, with proof:
- In-flight jobs: <job id> -> output path. Not written yet -> give the relaunch command. Never cite an output that does not exist.
- Repos: per repo `git -C <repo> status -sb | head -5`, branch, open PRs
- Temporary files moved to: <durable paths> (scratch folders die with the session)
- Wrong turns (do not retry):
## START HERE
1. <the exact first command>
> RUN WITHIN <deadline> <reason>. (delete this line if there is no deadline)
## What this is
<2-5 sentences: the problem, why it exists, why a fresh session needs it verbatim.>
## Read these FIRST, in order (before any edit)
1. `<file>`: <what it gives you>
## Non-negotiable rules for EVERYTHING in this mission
- **<ID>. <name>.** <rule>. Last bullet: "These rules apply to every phase above and any phase you add."
## Worker discipline
- Build phases: the `cascade` skill; prompts per the `spawn` skill; agent personas, never model ids.
  Workers NEVER touch: <orchestrator-only files>. Disjoint file ownership; review every diff before it lands.
---
## PHASE 0: <name> (~<time>, <why first>)
0.1 <step>
**VERIFY 0:** <exact command(s) and what pass looks like>. Record: <where the result is logged>.
---
<one PHASE block per phase; do not merge phases>
## Decision gates (defaults apply unless the user says otherwise)
- **D1: <name>:** DEFAULT: <choice>. Alt: <alternative>.   (none: "None for this mission")
## DO-NOT list
- Do NOT <hard limit>. Do NOT let workers edit <orchestrator-only files>.
## Definition of done
- [ ] <one line per phase verify>
## Priority if interrupted
<Ordered resume list with one-clause reasoning.>
## Known deferrals
- <out of scope now, worth a future mission>
*Authored by <agent persona>, <date>, for <requester>.*
```
Example: "handoff for moving the metrics service to the new cluster" gives slug
`metrics-service-migration`, no deadline, read the compose file and the runbook first, phases
backup, stand up, cut over, decommission, each with a VERIFY ("container healthy, curl 200 from the
new host"), D1 keep the old service 7 days (DEFAULT yes), Do-NOT: force-push, skipping the backup tag.

## Resume-note mode
Trigger: a usage-limit warning, or a request for a "resume note". Write ONLY PASTE PROMPT +
STATE AT HANDOFF + START HERE (at most 2 KB), same Step 0 routing, same final steps.

## Final steps (every time, in this order)
1. Journal first. If the workbench knowledge base is installed, journal one line with the `save` skill:
   "<TITLE>: HANDOFF READY at <absolute path>". A journal line is append-only, so it costs nothing and survives a session
   that ends right here.
2. Scan the finished file with the kit's credential scanner and fix every finding before you go on:
   `"${user_config.python}" "${CLAUDE_PLUGIN_ROOT}/scripts/secretscan.py" <file>`. Exit 0 and `CLEAN` is the only pass;
   exit 1 lists `file:line` with a masked match (never the value): replace the value with the credential's name and
   scan again; exit 2 means a file was not scanned, which is not a pass.
3. Save once. If the knowledge base is installed and the session is ending, run the `save` skill one time for the whole
   session, after the file is final, not once per edit of the handoff.
4. Verify the file exists and re-read the PASTE PROMPT once: it must make sense to a session that
   has seen nothing else.
5. Say where it lives, and only what you checked:
   - Committed: show `git log -1 --format=%h -- <file>` before saying "committed".
   - Pushed: show `git log origin/<branch> -1 -- <file>` and see a commit before saying "pushed". A local commit proves
     nothing about the remote.
   - Local only, including every client or tenant folder: say "local only, not committed".
6. Transfer ownership: the authoring session stops editing the mission. Report the path, where it
   lives (committed, pushed or local), the phase count, and the PASTE PROMPT block.
