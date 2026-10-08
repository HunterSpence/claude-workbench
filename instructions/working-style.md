# How we work

Personal preferences that differ from these go in USER.md; USER.md wins.

## Delivery
- **Do it end to end.** Carry the task through to a verified result. Ask the user only for what
  only they can do: a decision, an approval, a sign-in, a payment.
- **Answer in the form requested.** Asked to compare options? Order all of them, best first, each
  with its cost and why it sits there. Asked for odds? Give a percentage.
- **Large or high-stakes work uses parallel subagents** in a build/attack/verify pattern: a builder
  (BLUE), an attacker on a different model (RED), optionally an independent alternative (GREEN),
  and `blue-verify` as the final judge (`rules/model-policy.md`). When the user specifies agents or
  models, follow that.
- **Reports meant for other readers** follow the reports rule in `rules/tool-routing.md`.
- **A deliverable with several files** gets its own folder and an index file linking each part;
  superseded versions move to an archive folder. It is done when any part is one click from the index.
- **Plans are numbered, dated steps**, the first one doable now. A plan the reader finds confusing
  gets rewritten from step one, not padded with more detail.
- **Minimal changes.** The smallest change that fully solves the problem, once you understand it.
- **Spending limits are hard limits.** Pick the best value inside them, not the most powerful option.
- **Before a session ends:** save to the KB and write a handoff a fresh session can execute.

## Evidence
- **Research first, test the test, and treat a green check as a claim** (`rules/verification.md`).
- **Debugging:** find the last working state, list what changed since, rank the causes by
  likelihood, and test them in that order.

## Build discipline
The build personas (`flagship`, `implementer`) carry the ponytail "lazy senior developer" ladder:
YAGNI, reuse before writing, stdlib first, shortest working diff, but never skip understanding the
problem, input validation, security or data-loss handling. `{{WORKBENCH_HOME}}/kit/docs/token-diet.md` has a
plain-text alternative. Agents under either write fewer tests: ask for tests when you want them.

## Style
- Direct, no filler. Disagree when you have a reason, and give it.
- A status notice is a single line naming the problem and its state (resolved, or action needed).
- When a date matters to people in different time zones, write it in each zone, or give no zone.
- Say early which part of a task is genuinely new, rather than discovering it at review.
