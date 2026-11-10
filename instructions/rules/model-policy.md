# Model policy

## Pins live in settings, not here
- `model`, `fallbackModel`, `modelSettings` and the subagent-model variable are user settings
  (`{{WORKBENCH_HOME}}/kit/settings/SETTINGS.md`); a persona's model and effort are in its
  frontmatter. Trust live values over prose.
- **Organisation limits win** (managed `availableModels`, `maxEffortLevel`), then the user's
  explicit pick: don't "correct" either. Ids, context sizes, prices: the bundled `claude-api`
  skill, never memory. Dated overview: `{{WORKBENCH_HOME}}/kit/docs/models.md`, on demand.
- **Effort resolves** from the agent's `effort:` frontmatter, else the model's `modelSettings`
  entry, else top-level `effortLevel`. `--effort` and `CLAUDE_CODE_EFFORT_LEVEL` outrank all of
  it: never set either. Steer effort by persona; pass the Agent tool's `effort` only when the
  user names a level.
- **A fallback silently changes who produced a verdict.** `red-team`, `green-team` and
  `blue-verify` open every verdict with `Model: <the id you are running as>`.
- A usage-limit error in a fan-out means STOP launching: every later spawn fails the same way.

## Roles and routing
BLUE = `flagship`, `blue-verify`, `security-auditor`; GREEN = `green-team`; RED = `red-team`
(attacks, never gates); workers = general-purpose, `implementer`, `researcher`, `ops-runner`,
`scout`; override-only = `sonnet-max`. Plugin names: `workbench-core:<name>`. Roles stay fixed.

| Type: shape | Persona | Model, effort |
|---|---|---|
| CODE: planned slice plus its test | implementer | Sonnet xhigh |
| BREADTH: search fan-outs, tool loops | general-purpose | Sonnet xhigh |
| READ: digest text handed over | scout | Haiku high |
| BUILD: unshaped or irreversible change | flagship | Opus xhigh |
| GATE: final pass, verify, judge | blue-verify | Opus xhigh |
| RESEARCH: multi-source synthesis | researcher | Opus high |
| OPS: run on a machine | ops-runner | Opus high |
| DELIVERABLE: final doc for others | flagship | Opus xhigh |
| SECURITY: vulnerability review | security-auditor | Opus high |
| REGULATED: legal, tax, medical; cite sources | flagship | Opus xhigh |
| RED: attack the builder's work | red-team | Sonnet xhigh |
| GREEN: independent alternative | green-team | Sonnet xhigh |

- Unsure? One row up. On "model not allowed", step down that row's chain in
  `{{WORKBENCH_HOME}}/kit/docs/model-routing.md`; never retry or route around.
- Web research by tier (low, medium, high): the `research` skill; its `searcher` worker runs Sonnet xhigh, Fable 5.2
  low only on a seat that includes Fable (KB note `_shared/digests/fable-5-2-routing`).
- Fable 5.2 lanes (Agent `model: fable` with that `effort`), only on a seat that includes Fable (`/model` shows its
  row without "Requires usage credits", or an admin confirms): medium for hard closed-book questions, 3+ per spawn;
  low for chart or figure reading and fact cross-checks; high for `flagship` after an Opus build failed. These levels count as user-named. Never
  security, biology, medical, legal or tax: those stay on Opus xhigh citing primary sources.
- Never start a headless `claude -p` or SDK run on a Fable model without the user's go for that run: where Fable would
  bill usage credits (a seat without Fable, or past its Fable cap), a headless run bills them without asking.
- Fable 5.1 only when the user names it; for regulated work offer it, never route to it.
- `sonnet-max` only on explicit ask. A workflow `agent()` takes the same pairs. The user's
  explicit model, count or effort wins. The final pass of a build/attack/verify run is `blue-verify`.
- Fix, build, refactor, migrate: the `cascade` skill, unasked; hard ones best-of-N. Bulk passes
  may use the Batch API (half price, hours; org API key): suggest `/workbench-core:batch-review`.
- Token and cost habits: `{{WORKBENCH_HOME}}/kit/docs/token-diet.md`; KB note
  `_shared/digests/models-and-tokens`.
- Record a non-obvious routing pick in the KB's `ops/model-routing-ledger.md`, same session.

## Delegating
Prompt template: the `spawn` skill's; why each line exists: `model-profiles.md` (on demand). Keep
the plan in files, say "every X, including later ones", put the priority order in the worker's
prompt, say what is pre-authorised, never land worker output without a review gate.
