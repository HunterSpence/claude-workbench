---
title: Digest, orchestration and delegation
domain: _shared
status: active
---
# Orchestration and delegation: lessons that keep recurring

Read this before spawning agents, writing a worker prompt or running a build, attack and verify pass.

## Roles
- **Fix the role-to-model mapping** so findings stay attributable: a builder, an attacker on a different model, an
  independent alternative, and one final verifier that gates. The attacker never gates; the verifier closes the run.
- **A fallback silently changes who produced a verdict.** Gate personas open their reply with the model id they ran as.
- **Model diversity is the point of the attacker,** not a higher score. Say so when the same model reviews its own
  work.

## Writing the worker prompt
- **The worker has none of your context.** State the goal, the files it owns, the constraints it must obey, what is
  pre-authorised, the output shape and the stop conditions, in the prompt itself.
- **Write the priority order into the worker's prompt,** and say "every X, including ones added later" for class-wide
  rules.
- **Paste the constraints the worker needs.** Some built-in agents load none of your instruction files.
- **Disjoint ownership.** Give each worker its own files and its own worktree, and forbid editing its own tests or
  golden data.
- **Return contract:** conclusions not dumps, exact paths and commands run, and every claim labelled verified,
  plausible or assumed. Big output goes to a file.

## Running many agents
- **Past a handful of agents, messages get crossed.** List the agents and match the role before every send.
- **Run waves of three or four.** Many simultaneous model calls hit rate limits; poll the filesystem for silent
  completions instead of waiting on messages.
- **A usage-limit error means stop launching.** Every later spawn fails the same way.
- **Write results to disk,** because a background task or its waiter can be reaped without notice.
- **Cap heavy local jobs** (a few at once, sized to free memory, each under a memory cap) so a fan-out cannot freeze the machine.
- **Never two writers on one file.** Journal instead: append-only entries merged later.

## Migrations across many repositories
- **Freeze the hit list first.** Record an allowlist of path plus line pattern with its hash, lock it, and make the gate
  script fail on any hit outside it. An inline "historical" marker never exempts a line, and measured data is never
  relabelled.
- **The gate is a script, not a promise.** `tools/model-sweep` prints one `path:line` per unowned hit, takes the frozen
  allowlist, and fails the run when its own positive control is not found.
- **Search fresh clones of the remote,** and give each slice an owned file list from that search.
- **Change each code default together with its deploy value,** and keep the old model's price rows.
- **A "not sooner than" retirement date is a floor, not a deadline.** Read the deprecation page and split urgent work
  from hygiene.

## Gates
- **Never land worker output without a review gate.** Verify with exit codes, files and fresh runs, not the worker's
  own account of success.
- **Hard problems get best-of-N** with an independent judge; routine ones do not.
- **A stopped denial is a result.** When a worker hits a policy denial it stops and reports; it does not retry by
  another route.

## Cost
- **Lower effort on the same model before switching models.** A lead with cheaper workers pays only when the work is
  routine with a long cost tail, or the input is larger than one context window.
- **Step down the routing chain** on "model not allowed"; do not retry the same model.
- **Keep the plan in files,** and write a handoff or resume note before a session ends, so a fresh session can continue
  without the history.
