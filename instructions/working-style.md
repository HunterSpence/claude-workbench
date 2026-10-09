# How we work

Personal preferences go in USER.md; USER.md wins over this file.

## Kit workflows
- **High-stakes work can use parallel subagents** in a build/attack/verify pattern: a builder
  (BLUE), an attacker on a different model (RED), optionally an independent alternative (GREEN),
  and `blue-verify` as the final judge (`rules/model-policy.md`). When the user specifies agents or
  models, follow that.
- **Reports meant for other readers** follow the reports rule in `rules/tool-routing.md`.
- **Session wrap-up:** the `save` skill and a handoff note (`rules/memory-protocol.md`).

## Evidence
- **Research first, test the test, and treat a green check as a claim** (`rules/verification.md`).

## Build discipline
The build personas (`flagship`, `implementer`) carry the ponytail ladder: YAGNI, reuse, stdlib
first, shortest working diff, never skipping understanding, validation, security or data-loss
handling. They write fewer tests: ask for tests when you want them.

## Style
- Direct, no filler. Disagree when you have a reason, and give it.
