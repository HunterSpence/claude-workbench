---
name: cascade
description: "Use for any non-trivial fix, build, refactor, migrate or harden task (fix or debug X, it is broken, add a feature): diagnose, plan, implement, verify across personas, with parallel-slice and best-of-N modes. Skip one-line fixes and pure research or decisions."
---

# Cascade: route each phase to the persona that owns it

Each persona's model and effort live in its own agent file (`agents/*.md` frontmatter). Pick the
persona, never a `model:` override. Worker prompts follow the `spawn` skill, section 4. A user who
names personas, models, counts or effort overrides this file.

## Phases: each hands a WRITTEN artifact to the next
| # | phase | persona | output |
|---|---|---|---|
| 1 | DIAGNOSE (M/L: two lanes) | `flagship` + `red-team` briefed "diagnose, do not attack" | ranked root causes with evidence (file:line, log line, repro) and what was ruled out |
| 2 | PLAN | `flagship` | slices with disjoint owned files, an acceptance test per slice, risks, rollback |
| 2b | PRE-MORTEM (L) | `red-team` | attacks on the plan; the planner revises once |
| 3 | IMPLEMENT | S: `flagship`; 2+ disjoint slices: one `implementer` each (infra slices: `ops-runner`) | diff plus the slice's test output |
| 4 | VERIFY | `blue-verify` | pass/fail per acceptance test, plan-vs-diff gaps |
| 4b | RED ON THE DIFF (L) | `red-team` | concrete breakages |

## Size first (one line: "Size: S, because ...")
- **S (default)**: cause known, or at most 2 files. One `flagship` diagnoses, plans and builds; `blue-verify` gates.
- **M**: cause still unknown after one pass, or 2+ disjoint slices: phases 1-4, workers per *Parallel slices*.
- **L**: production, money, irreversible, or more than 5 files: M plus 2b and 4b. A hard-to-reverse architecture call: *Best-of-N*.

## Rules
- Merge the two diagnoses yourself. If they disagree on the root cause, settle it with the cheapest
  discriminating check (a log grep, a repro, one test) before planning. If none exists,
  `blue-verify` adjudicates on the evidence.
- Escalate, don't retry the same way. A slice that fails VERIFY twice goes to `flagship` (a failed
  S run sizes up to M). A fix that verifies while the symptom persists means the diagnosis was
  wrong: back to phase 1 with the new evidence.
- VERIFY tests the test first. Every acceptance test, benchmark or gate result is checked before it
  counts: a positive control exists, the change was proven applied, the workload matched, exit codes
  were read directly, and nothing was silently skipped or defaulted.
- Filter to text files before any bulk replace: a regex over a backup or data tree rewrites binary files (databases,
  archives) it should never touch. A container restart keeps its old environment: after an env change, recreate
  the container (`compose up -d`) before you call it verified.
- Your organisation's rules and the repo's own instructions hold in every phase. Anything that a
  third party sees, or that spends money, stops for the user's confirmation.
- Report one line per phase (diagnosis, plan, slices, verify verdict, escalations), naming the
  persona behind each.

## Parallel slices (2+ disjoint slices)
- One worktree per worker (`isolation: "worktree"` or `git worktree add`). Never share a working
  tree, even with disjoint files. A slice that runs scripts or remote commands gets its own
  `git worktree add` path written into its prompt.
- Before removing a worktree, list its junctions (`dir /AL` in cmd) and remove each with `rmdir`, never `rm -rf` or
  `git worktree remove --force`: a delete that walks through a junction deletes the real files it points to.
- Worker prompts forbid `git stash`: the stash stack is shared by every worktree of a repo, so two
  workers stashing at once pop each other's work. Set work aside with a WIP commit or
  `git diff > x.patch`.
- Each prompt states its OWNED and FORBIDDEN files inside the prompt itself, not only in the plan.
  A worker that needs a forbidden file stops and reports. Launch all workers in one message.
- Tag the start (`git tag pre-<mission>-<date>`) and keep the tag after the merge as the rollback point.
- Write the gate criteria BEFORE launch, blind to any output. Never add or soften one after seeing a diff.
- The orchestrator reads every diff and never merges on a worker's self-report.
- `blue-verify` scores each criterion on its own. A failure goes back to that worker; it is not
  patched inline (a one-line typo excepted).

## Best-of-N (L size, hard-to-reverse architecture calls)
Write the criteria first (right problem, constraints honoured, nothing forbidden crossed, evidence
attached). Run 2-3 independent candidates (`flagship` + `green-team`; angles: smallest change, what
breaks in production, easiest to maintain), none seeing another. `red-team` refutes each candidate
from the solution alone, never from its author's justification. `blue-verify` judges against the
pre-written criteria, may graft one named idea from a runner-up, and labels each claim VERIFIED,
PLAUSIBLE or ASSUMED.
