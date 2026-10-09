# Fix a bug with the bug playbook

Automates it: /workbench-core:investigate, /workbench-core:repo-fix

## When to use
You have an error, a failing test or odd behaviour. Recurring failures (swallowed exit codes, console code pages, proxy
certificates, line endings, long paths) already have a card with a fix; check the cards before you debug from scratch.
`<KIT>` is the kit folder (guide 01).

## Steps
1. Search the cards by symptom words from the error:
   `py -3 <KIT>/plugins/workbench-kb/scripts/kb_search.py "<symptom words>" --domain _shared --limit 5`
   Or read `kb-template/_shared/bug-cards.md`. Each card has Symptom, Root cause, Fix, Verifying test and Spot it fast. Run its
   "Spot it fast" check to confirm it is your case.
2. After a failed tool call, a hook may already have named the best matching card in one line. Open that card.
3. No card fits: run `/workbench-core:investigate`. Write the symptom down exactly, reproduce it, find what is constant across failures,
   test one hypothesis at a time, and report with the symptom, root cause, evidence, what you ruled out, the fix and the regression test.
4. A whole repository to review and fix: `/workbench-core:repo-fix`. It clones into a scratch folder, records a baseline of tests
   and linters, reviews, then fixes one finding at a time on a branch, with a failing test first.
5. Fix at the root: find every caller of the function you are changing, make the smallest change in the shared place, then
   run the new test and the whole suite and compare with the baseline.
6. If the class will come back, add a card to your `_shared/bug-cards.md`: the next number, all five fields, the class and
   not the incident. Add a detector only when the error text is specific.

## Verify
- The regression test fails without your fix and passes with it (watch it fail first).
- The original repro now passes and nothing that passed in the baseline fails.
- For a new function, break the fix in a copy and watch a named test fail for that reason; an import error on the old
  commit proves nothing.
- For a live service, find the log line of the fixed path (the call, then a normal finish) in one session; a field
  printed on every reply proves nothing.

## Common failures
- **The fix passes but the symptom remains:** the diagnosis was wrong. Go back to step 3 with the new evidence.
- **Three hypotheses refuted:** stop guessing, re-read the code path end to end, and widen the scope out loud.
- **Fixing only the path in the ticket:** other callers stay broken. Grep every caller first.
- **A search finds nothing:** it is keyword search; retry once with the error's own words.
- **Weakening a test to get green:** never. Fix the cause or report the blocker.
