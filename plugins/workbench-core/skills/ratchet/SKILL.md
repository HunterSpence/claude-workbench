---
name: ratchet
description: "Fix and re-audit a target in rounds until two consecutive rounds find nothing new, each fix locked behind a test proven to fail without it. Use for \"audit this in rounds\", \"until there are no new findings\", or when work was declared done too early."
---

# /workbench-core:ratchet: fix, re-hunt, repeat until dry

A ratchet only turns one way: each round locks in progress and never reopens covered ground. It
kills *stopping too early*: the fixes themselves open a new layer nobody re-hunts. The loop runs
until two consecutive rounds find nothing new, and the confirming round must look with different
eyes (see DECIDE).

## Invocation
`/workbench-core:ratchet <target>`, for example `/workbench-core:ratchet this repo's auth`.
Flags: `--rounds N` hard cap (default: until dry) · `--dry N` consecutive empty rounds to stop
(default 2) · `--agents N` auditors per round (default 3).

## Round 0: baseline (once, before any hunting)
1. **Ledger.** Create `RATCHET-LEDGER.md` next to the target:
   ```markdown
   # Ratchet ledger: <target>, started <date>
   Baseline: <start SHA> · suite: <N pass / M pre-existing fail (name them)>
   ## FIXED   (id | finding | fix | test that locks it | how the test was proven to fail)
   ## OPEN    (id | finding | why not fixed yet)
   ## WONTFIX (id | finding | reason, so it is never re-raised)
   ## FALSE POSITIVES (id | claim | why it was wrong)
   ```
2. **Baseline the tree.** Record the clean start SHA. Run the existing suite and write down what is
   *already red*: LOCK's proof means nothing if you can't tell your red from pre-existing red.
3. Pick round-1 lenses from the surface menu, one per auditor, all different.

The ledger is the loop's memory. Every auditor prompt gets FIXED + WONTFIX + FALSE POSITIVES pasted
in as "do not re-report". Dedup against all three, or a rejected claim is re-found every round and
the loop never converges.

## One round
Only step 1 is parallel. After it you work serially: **one writer, ever**. Auditors are read-only.
If you must delegate a write, nothing else touches the tree until it returns and `git status` is clean.

1. **HUNT.** Spawn N *fresh* agents in parallel (never forks), each with a different lens, the
   target paths and the ledger exclusions; from round 2 on, also `git diff <last-round-sha>..HEAD`.
   Always assign one auditor to the code changed last round (fixes are where regressions live) and
   one to a surface no round has covered yet. Write prompts with the `spawn` skill.
2. **TRIAGE.** A report is a lead, not a finding. Re-read the file against `git show HEAD:<path>`
   and reproduce it (state the input and the bad output). Can't reproduce: OPEN as "unreproduced",
   not counted as found. Drop anything already in the ledger.
3. **FIX.** The smallest change that removes the root cause, at the layer all callers route through.
   Prefer deleting over adding.
4. **LOCK.** Every non-trivial fix gets a test you have *watched fail*: break the implementation,
   confirm red, restore, confirm green, then `git status` clean. Record in the ledger how it was
   proven. If the harness cannot see the bug (a mock encodes your beliefs), say so in the test
   comment and the ledger: the check is the control; the test proves it fires.
5. **VERIFY at the real boundary.** Run the thing where it runs: build the container and probe it;
   match production constraints (`NODE_ENV=production`, no network where prod has none); confirm it
   fails closed on missing or blank secrets and config. Record the exact command and its output.
6. **COMMIT + APPEND.** One commit per round, naming what was found and how it was proven. Append
   everything to the ledger, including new FALSE POSITIVES.
7. **DECIDE.** Found anything: dry counter to 0, back to step 1. Nothing found and verification
   green: dry +1. **A dry round counts only if its lenses differ from the previous dry round's**:
   re-running the same auditors is correlated evidence, not confirmation. Counter reaches `--dry`: stop.

## Auditor prompt
The `spawn` skill's template, with these auditor-specific lines:

> Audit ONLY through this lens: **\<lens\>**. Target: \<paths\>. Read-only: change nothing.
> Start with this delta, then the code it touches: `git diff <sha>..HEAD` (round 1: the target
> itself). Already handled, do NOT re-report: \<FIXED + WONTFIX + FALSE POSITIVES\>.
> For each finding: file:line, the concrete input, the wrong behaviour, why it matters.
> If your lens turns up nothing, say "clean" and name exactly what you examined. "Nothing found"
> without a denominator is not a result.

## Stopping and the report
Stop when `--dry` distinct-lens rounds come back empty, the `--rounds` cap hits, or every remaining
OPEN item needs a call only the user can make; never because the session is long. Append the final
report to the ledger: rounds run · surfaces covered per round (the denominator) · each fix and how
it was *proven* · OPEN items and who unblocks each · WONTFIX and why · the one verification command
anyone can re-run.

## Surface menu (pick distinct lenses; not exhaustive)
Deploy/runtime boundary (containers, egress, missing config, cold start) · authentication and
default credentials · authorization at every layer (does the audit record match the actual
decision?) · untrusted input reaching a model or a query · resource limits and timeouts · supply
chain (lockfiles, transitive deps, reproducible builds) · observability (can anyone tell it broke?)
· the tests themselves (which claims have no test at all) · for regulated work, the documents a
reviewer will demand rather than the code.
