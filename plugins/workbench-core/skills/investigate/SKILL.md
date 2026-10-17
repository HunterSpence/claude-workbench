---
name: investigate
description: "Systematic debugging: no fix before a proven root cause. Use for \"debug this\", \"why is this broken\", \"investigate this error\", \"root cause\", a stack trace, a flaky test or unexpected behaviour. Hand a multi-file fix to cascade once the cause is known."
---

# /workbench-core:investigate

The rule: **no fix without a root cause you can demonstrate.** A report names a symptom. The fix
goes where the cause is, usually in a function every caller shares, not in the one path the report
mentions.

## 0. Search the known failures first
Starting from a symptom (an error line, a failing build or test)? Run the KB search from `rules/memory-protocol.md` as
`kb_search.py "<symptom words>" --domain _shared --limit 5`. A matching bug card gives the root cause, the fix and the
test that proves it; confirm it applies here before you use it, and say which card you used.

## 1. Pin the symptom
- Write the symptom down exactly: the command, input, expected output, actual output, and the
  first error line verbatim. "It fails" is not a symptom.
- Reproduce it. No repro yet: collect the evidence that exists (logs, timestamps, versions, recent
  changes from `git log --since`) and say the repro is missing.
- Scope lock: name the directory or module you believe holds the cause. Edits outside it need a
  stated reason.

## 2. Find the invariant
Ask what is constant across every failure and what differs from a working case.
- Works locally, fails in CI or a service: environment (env vars, cwd, user, PATH, network), not code.
- Dies exactly at a timeout with low CPU: blocked on I/O, a lock or a prompt.
- Started on a date: diff what changed then (`git log`, dependency lockfile, config, platform update).
- Only some inputs: shrink the input until the failure flips; the last removed piece is the clue.
- Use `git bisect` when a known-good commit exists.

## 3. Hypothesise, then test one thing at a time
- List up to three hypotheses, each with the observation that would refute it.
- Run the cheapest discriminating check first (a log grep, a print, one assertion, one test).
- Change one variable per experiment and revert experiments that did not confirm anything.
- A diagnostic that asserts a cause you did not measure misleads. Say what you measured.
- Three refuted hypotheses in a row: stop, re-read the code path end to end, and widen the scope
  out loud before guessing again.

## 4. Fix at the root
- Before editing, find every caller of the function you will touch (grep or the code graph). One
  check in the shared function beats a check in each caller.
- Smallest change that removes the cause. Remove debugging scaffolding before you finish.
- Add one regression test that fails without the fix. Watch it fail, then pass.

## 5. Verify and report
- Re-run the original repro and the surrounding tests. A green test is not evidence until you have
  seen it fail for the right reason.
- If the fix verifies but the symptom persists, the diagnosis was wrong: return to step 2 with the
  new evidence.
- Report in this shape:
  ```
  Symptom:      <exact>
  Root cause:   <mechanism, with file:line>
  Evidence:     <the observation that proves it>
  Ruled out:    <hypotheses refuted, and how>
  Fix:          <what changed, why there>
  Regression:   <test name; proven to fail without the fix>
  Status:       DONE | DONE_WITH_CONCERNS (<what>) | BLOCKED (<what is needed>)
  ```
