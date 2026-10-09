# Hand work to subagents and pick the model

Automates it: /workbench-core:spawn

## When to use
A task has parts that can run side by side, needs an independent check, or is large enough that exploring it would
fill your context. For a fix or a build with several steps, `/workbench-core:cascade` runs the phases for you. `<KIT>`
is the kit folder (guide 01).

## Steps
1. Pick the persona for the kind of work, not a model. `/agents` lists them: `flagship` (hard build), `implementer` (one
   planned slice), `researcher`, `ops-runner`, `security-auditor`, `scout` (read and extract text you hand it),
   `red-team` (attacks, never decides), `green-team` (independent alternative), `blue-verify` (final check) and the
   built-in `general-purpose`. Never use the built-in `Explore` or `Plan` for work that touches hosts, money or policy: they do not load your rules.
2. Look up the row in `docs/model-routing.md`: the task shape, the persona, the preference order of model and effort,
   what never to use, and the evidence. Setup keeps only models your organisation allows and writes the result to
   `<WB>/state/routing.effective.json` (rebuild it with `py -3 <KIT>/bootstrap/setup.py routing`). `docs/models.md` has the
   other half: what each model is for, what to keep it away from, its price and where to start on effort.
3. Write the prompt the worker will run without your context. Use `/workbench-core:spawn`, whose template holds the
   goal, the files it may touch and those it may not, constraints, what is pre-authorised, the output shape and when to stop.
4. Run parallel workers in their own worktrees (`git worktree add`) with disjoint files, three or four at a time.
5. Read each result as a claim, not a fact: ask for evidence per claim, then run a `blue-verify` pass on anything
   irreversible before it lands.

## Verify
- `blue-verify`, `green-team` and `red-team` open each verdict with the model they ran as; compare it with the row's first choice.
- A trial: `claude -p --agent red-team "print your rules"` shows the persona's model line and tool limits.

## Common failures
- **"Model not allowed":** step down the row's preference order. Never retry the same model or route around the restriction.
- **A worker did not know a fact:** a smaller model does not reliably open a file it was only pointed at. Paste the
  constraint into its prompt.
- **A usage-limit error in a fan-out:** stop launching; every later spawn fails the same way.
- **Two workers overwrote each other:** they shared a working tree. One worktree each.
- **`scout` runs an older small model than you expect:** your provider's `haiku` alias may still point at it, so pin the
  provider's id (`docs/known-limits.md`). The capability report (guide 02) also says when your Claude Code is below the
  version the vendor recommends for Haiku 5.5; `claude update` brings it up to date.
