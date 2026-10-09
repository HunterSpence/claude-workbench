# Model policy

## Pins live in settings, not here
- `model`, `fallbackModel` and `modelSettings` (in the permissive profile also the alias and
  subagent-model variables) are user settings, each explained in
  `{{WORKBENCH_HOME}}/kit/settings/SETTINGS.md`; a persona's model and effort are in its
  frontmatter. Trust the live values over prose.
- **Organisation limits win** (managed `availableModels`, `maxEffortLevel`), then the user's
  explicit pick: don't "correct" either. Model ids, context sizes and prices: the bundled
  `claude-api` skill, never memory. Dated overview: `{{WORKBENCH_HOME}}/kit/docs/models.md`, on demand.
- **Effort resolves** from the agent's `effort:` frontmatter, else the model's `modelSettings`
  entry, else top-level `effortLevel`. `--effort` and `CLAUDE_CODE_EFFORT_LEVEL` outrank all of
  it: never set either. Steer effort by picking the persona; pass the Agent tool's `effort`
  parameter only when the user names a level.
- **A fallback silently changes who produced a verdict.** `red-team`, `green-team` and `blue-verify`
  open every verdict with `Model: <the id you are running as>`.
- A usage-limit error in a fan-out means STOP launching: every later spawn fails the same way.

## Roles and routing
BLUE = `flagship`, `blue-verify`, `security-auditor` · GREEN = `green-team` · RED = `red-team`
(attacks, never gates) · workers = general-purpose, `implementer`, `researcher`, `ops-runner`,
`scout` (small-model reader of text handed to it) · override-only = `sonnet-max`. The plugin
names them `workbench-core:<name>`. Roles stay fixed so findings stay attributable.
- **Route by task type:** `{{WORKBENCH_HOME}}/kit/docs/model-routing.md` (on demand) gives each
  type (CODE, BREADTH, READ, BUILD, GATE, RESEARCH, OPS, ...) its persona, model chain and
  evidence; SessionStart shows the first five rows. Unsure? Go one step up in stakes.
- **On "model not allowed", step down that row's chain.** Never retry the same model or route
  around the restriction.
- Use the effort each row names (`high` or `xhigh` for Opus and Sonnet, `high` for Haiku);
  `sonnet-max` only on the user's explicit ask. A workflow `agent()` call takes the same pairs. An
  explicit user choice of model, agent count or effort wins. The final pass of any
  build/attack/verify run is `blue-verify`.
- Think-then-build tasks (fix, build, refactor, migrate) go through the `cascade` skill unasked;
  hard ones use its best-of-N mode. Non-interactive review, judging or bulk passes can use the Batch API
  (about half price, minutes to hours, needs an organisation API key): suggest the user run `/workbench-core:batch-review`.
- Record a non-obvious routing pick in the KB's `ops/model-routing-ledger.md`, same session.

## Delegating
The worker-prompt template is the `spawn` skill's; why each line exists and per-model failure
modes: `model-profiles.md` (on demand). In short: keep the plan in files, say "every X, including
later ones", write the priority order into the worker's own prompt, say what is pre-authorised,
and never land worker output without a review gate.
