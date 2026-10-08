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
  build/attack/verify run is `blue-verify`.
- Think-then-build tasks (fix, build, refactor, migrate) go through the `cascade` skill.
- Record a non-obvious routing pick in the KB (one append-only ledger note), same session.

## Delegating
The worker-prompt template is the `spawn` skill's. Why it has each line: lower tiers drift on long
work (keep the plan in files, cap missions at 30-60 minutes), apply a rule to the instance rather
than the class (say "every X, including later ones"), drop constraints when two collide (write the
priority order into their prompt), ask permission for authorised work (say it is pre-authorised),
and produce plausible-wrong output at volume (never land it without a review gate). Opus accepts
its own good-looking answer: ask it to refute its top 3 conclusions. Novel problems: decompose,
best-of-N plus a judge, and say early what is novel. Workflow schemas: optional fields for what an
agent may omit, exhaustive enums, a literal example object in the prompt.
