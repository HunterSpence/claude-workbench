# Model policy

## Pins live in settings, not here
- `model`, `fallbackModel`, `modelSettings` (and, in the permissive profile, the model alias and
  subagent-model variables) live in user settings:
  `{{WORKBENCH_HOME}}/kit/settings/SETTINGS.md` explains each. A persona's model and effort live in
  its frontmatter. Trust the live values over prose.
- **Organisation limits win** (managed `availableModels`, `maxEffortLevel`, effort caps), then the
  user's explicit pick. Don't "correct" either. Model ids, context sizes and prices: the bundled
  `claude-api` skill, never memory.
- **Effort resolves** from the agent's `effort:` frontmatter, else the model's `modelSettings`
  entry, else top-level `effortLevel` (in user settings, only models older than Opus 5.5).
  `--effort` and `CLAUDE_CODE_EFFORT_LEVEL` outrank all of it: never set either. To steer a
  subagent's effort, pick the persona that carries it.
- **A fallback silently changes who produced a verdict.** `red-team`, `green-team` and `blue-verify`
  open every verdict with `Model: <the id you are running as>`.
- A usage-limit error in a fan-out means STOP launching: every later spawn fails the same way.

## Roles and routing (quality first; Opus and Sonnet at high or xhigh only)
BLUE = `flagship`, `blue-verify`, `security-auditor` · GREEN = `green-team` · RED = `red-team`
(attacks, never gates) · workers = general-purpose, `implementer`, `researcher`, `ops-runner` ·
override-only = `sonnet-max`. The plugin names them `workbench-core:<name>`. Roles stay fixed so
findings stay attributable.

| stakes | work | spawn | model · effort |
|---|---|---|---|
| routine | search, collect, extract, format, run | general-purpose | Sonnet 5.5 · high |
| standard | research, ops, security review | `researcher` · `ops-runner` · `security-auditor` | Opus 5.5 · high |
| high | hard or irreversible build (BLUE) | `flagship` | Opus 5.5 · xhigh |
| high | independent alternative (GREEN) | `green-team` | Sonnet 5.5 · xhigh |
| high | attack, on a different model from BLUE (RED) | `red-team` | Sonnet 5.5 · xhigh |
| high | final verify, tie-break, gate | `blue-verify` | Opus 5.5 · xhigh |

- Unsure? Go one row up. `sonnet-max` runs only when the user asks for it. The final pass of any
  build/attack/verify run is `blue-verify`. The user naming a model, count or effort overrides.
- A workflow script's `agent()` call takes a model and effort per call: use the same pairs. Opus
  and Sonnet run at `high` or `xhigh` only: never `medium`, `low` or `max` (`max` only through
  `sonnet-max`, on the user's ask).
- Think-then-build tasks (fix, build, refactor, migrate) go through the `cascade` skill unasked;
  genuinely hard ones use its best-of-N mode. Non-interactive review, judging or bulk passes go
  through `batch-review` (Batch API: about half price, minutes to hours, needs an API key your
  organisation provides).
- Record a non-obvious routing pick in the KB's `ops/model-routing-ledger.md`, same session.

## Delegating
The worker-prompt template is the `spawn` skill's. Why each line exists, per-model failure modes
and the task-shape table: `model-profiles.md` (read on demand). In short:
keep the plan in files, say "every X, including later ones", write the priority order into the
worker's own prompt, say what is pre-authorised, and never land worker output without a review gate.
