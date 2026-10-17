# Model profiles: what degrades at each tier, and what buys it back (read on demand)

Read this when you route a task or write a prompt for a worker. Routing (task type, persona, model,
effort) is owned by `{{WORKBENCH_HOME}}/kit/docs/model-routing.md` and the rules in `rules/model-policy.md`; the
worker-prompt template is the `spawn` skill's.
This file is observed tendencies, not a benchmark: where your own A/B tests disagree, the tests win.

## The gap, and the structure that recovers it
| Dimension | Top tier (Opus, xhigh) | Workhorse (Sonnet) | What recovers it |
|---|---|---|---|
| Holding a goal over hours and hundreds of tool calls | good; drifts on very long arcs | drifts; needs the goal re-fed | The mission lives in files: phase files, a check per phase, a definition-of-done checklist. Re-read them after compaction. |
| Applying a rule said once to every case | mostly | literal: applies it to the instance, not the class | Say "every X, including ones added later"; repeat the constraint in each worker prompt; zero-exception rules belong in hooks. |
| Resolving ambiguity | good | asks, or guesses literally | Write defaults down; an underspecified task gets one line stating the assumption, then proceeds. |
| Juggling conflicting constraints | good if priorities are stated | drops one silently | Write the priority order into the prompt. Fewer live rules; never fix a miss by adding emphasis. |
| Noticing it is wrong mid-stream | moderate: ask for it | weak: ships plausible-wrong output confidently | Review gates, adversarial verify passes, evidence before "done". Never trust one pass at this tier. |
| Novel problems with no pattern to match | moderate | weak | The least recoverable. Decompose until the pieces look familiar; best-of-N plus a judge; say early what is novel. |
| Degrading as context fills | moderate | faster | Delegate with short return contracts; `/clear` between tasks; small always-loaded files. |
| Tool economy (right tool first, batching, no re-reads) | good | explores redundantly | Low-freedom skills with exact commands; routing tables; "check X first" lookups. |
| Calibration | moderate | overconfident | VERIFIED / PLAUSIBLE / ASSUMED labels; numbers need a measurement or a dated source. |
| How many rules it honours at once | high | lower, and it falls off sharply | Fewer, better rules; detail in on-demand files and skills; hooks carry the hard limits. |

The principle: what one strong pass does, the fleet does as a system (generate, verify, judge),
with state in files and hard limits in hooks.

## Opus (BLUE, flagship)
- Trust with: standard development, orchestration, code review, incident response, final gates, hard
  problems when given structure (a phase plan and a definition of done).
- Watch for: accepting its own good-looking answer; doing 200-tool-call work inline instead of
  delegating; drift on missions past two or three hours; "should" in completion claims.
- Prompt it with: the definition of done as a literal checklist; "re-read the mission file after any
  compaction"; "before presenting, try to refute your top 3 conclusions". xhigh for ambiguous or
  long work, high for routine work. A faster output mode is fine for mechanical passes, not for
  judgment-heavy writing.

## Sonnet (workers, GREEN, RED)
- Trust with: explicit specs, domain work with a pointer to the KB, drafts that will be reviewed,
  parallel worker swarms, anything with a template and a return contract.
- Watch for:
  - **Literalness.** Say "every file in the list, including ones added later", not "the files".
  - **Over-asking.** It stops to ask about already-authorised work. Write "Y is pre-authorised; do
    not stop to ask."
  - **Plausible-wrong at volume.** Never land its output without a review gate.
  - **Dropping a constraint when two collide.** Put the priority order in its own prompt, not only
    in a file it might not open.
  - **Goal drift.** Cap a worker mission at about 30-60 minutes of work; split bigger work into waves.
- Paste the spec, owned and forbidden files, the acceptance test and the facts it needs into the
  prompt itself: a constraint it was only pointed at may not exist for it.

## Haiku (extraction)
Extraction, formatting, classification, log summaries. Force an output schema. Never judgment,
never prose for the user, never routing decisions. A Haiku task that needs a second attempt was
misrouted: move it up a tier. What the public pages say about Haiku 5.5 (prices, effort, limits,
never-list): `{{WORKBENCH_HOME}}/kit/docs/evidence/haiku-5-5.md`, on demand.

## Workflow schemas (orchestrator side)
- Make fields an agent may legitimately omit optional or nullable, and make enums exhaustive,
  before launching: each omission otherwise costs a retry per agent.
- Paste a literal example object into the agent prompt. The most common schema failure is nesting
  the whole payload under its first key.

## What structure does not recover
1. Single-shot insight on genuinely novel problems. Mitigate: decompose, best-of-N with diverse
   angles, and flag "this is novel" to the user early.
2. Taste on open-ended design. Mitigate: best-of-N candidates, then human eyes on anything
   irreversible.
3. Cross-domain connections. Mitigate: end every big mission with the literal checklist step
   "what else does this touch?"

## Task shape to structure
| Task shape | Route | Structure it needs |
|---|---|---|
| Extraction, formatting, digesting handed-over text | `scout` (Haiku) | an output schema and locators |
| Mechanical edit sweep, templated rewrite | Sonnet worker(s) | template, file-ownership map, return contract, orchestrator diff review |
| Domain task with good KB context | Sonnet worker | a pointer to the domain's `HOT.md` and the KB search, not a pasted copy |
| Standard development, debugging, incidents | main session or `flagship` | judgment procedures, definition of done, evidence before done |
| Attack, refute, pre-mortem | `red-team` | read-only; every finding carries evidence and the guarantee a fix must give |
| High-stakes one-shot (architecture, final review, hard bug) | best-of-N plus a `blue-verify` judge (`cascade`) | gate criteria written before generation |
| Novel and irreversible | Opus xhigh, `cascade` best-of-N, the user told early | decompose first; say what is novel |
| "Wrong means a production incident" | any tier plus an independent verify pass | evidence on every claim |
