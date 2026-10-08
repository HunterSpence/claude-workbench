# How we work

Personal preferences that differ from these go in USER.md; USER.md wins.

## Delivery
- **Do it end to end.** Carry the task through to a verified result. Ask the user only for what
  only they can do: a decision, an approval, a sign-in, a payment.
- **Match the requested format.** When the user asks for a ranking, rank every option and give each
  its cost and the reason for its place. When they ask how likely something is, give a number.
- **Large or high-stakes work uses parallel subagents** in a build/attack/verify pattern: a builder
  (BLUE), an attacker on a different model (RED), optionally an independent alternative (GREEN),
  and `blue-verify` as the final judge (`rules/model-policy.md`). When the user specifies agents or
  models, follow that.
- **Reports meant for other readers** follow the reports rule in `rules/tool-routing.md`.
- **Plans are numbered steps with dates or deadlines**, starting with what to do first. If a plan
  confuses the reader, rewrite it from the first step instead of adding detail.
- **Minimal changes.** The smallest change that fully solves the problem, once you understand it.
- **Respect budgets.** Stay within any stated limit, and prefer the best value over the most
  capable option.
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
- Say early which part of a task is genuinely new, rather than discovering it at review.
