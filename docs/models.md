# Models at a glance

As of October 2026. The four current Claude models, what each is for, what to keep it away from, where to start on
effort, and what they cost. Every number comes from the vendor's published pages and is quoted in
`settings/model-evidence.json` (rows E31 to E35 and the `prices` key); the price table below is generated from that file
and a test keeps this page, `docs/token-diet.md` and `tools/token-split/token_split.py` equal to it. Prices and limits
change: re-read the vendor's pricing page before you plan spend, and see "Keeping it current" at the end.

Which persona and model to hand which kind of task is a separate question, answered with its evidence in
[Model routing](model-routing.md); this page does not repeat that table.

## The four models

| Model | API id | Context | Max output | Default effort | Latency |
|---|---|---|---|---|---|
| Claude Fable 5.1 | `claude-fable-5-1` | 1M tokens | 128K tokens | `high` | Slower |
| Claude Opus 5.5 | `claude-opus-5-5` | 1M tokens | 128K tokens | `medium` | Moderate |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | 1M tokens | 128K tokens | `high` | Fast |
| Claude Haiku 5.5 | `claude-haiku-5-5` | 1M tokens | 128K tokens | `medium` | Fastest |

Context and output are the synchronous Messages API limits; latency is the vendor's comparison across this lineup (E31).
The ids are fixed: no date suffix and no separate alias. Your provider may name them differently:

<!-- begin:ids -->
| Model | Claude API | Bedrock | Google Cloud | Foundry |
|---|---|---|---|---|
| `claude-opus-5-5` | `claude-opus-5-5` | `anthropic.claude-opus-5-5` | `claude-opus-5-5` | `claude-opus-5-5` |
| `claude-sonnet-5-5` | `claude-sonnet-5-5` | `anthropic.claude-sonnet-5-5` | `claude-sonnet-5-5` | `claude-sonnet-5-5` |
| `claude-haiku-5-5` | `claude-haiku-5-5` | `anthropic.claude-haiku-5-5` | `claude-haiku-5-5` | `claude-haiku-5-5` |
| `claude-fable-5-1` | `claude-fable-5-1` | `anthropic.claude-fable-5-1` | `claude-fable-5-1` | `claude-fable-5-1` |
<!-- end:ids -->

An unpinned alias such as `haiku` can resolve to an older generation on some providers, so pin the id.

## Prices

US dollars per million tokens, as the vendor lists them (E32). Cache write is the five-minute write.

<!-- begin:prices -->
| Model | Input | Output | Cache write (5 min) | Cache read |
|---|---|---|---|---|
| `claude-fable-5-1` | $10 | $50 | $12.50 | $0.25 |
| `claude-opus-5-5` | $4 | $20 | $5 | $0.20 |
| `claude-sonnet-5-5` | $2 | $10 | $2.50 | $0.10 |
| `claude-haiku-5-5`, prompt up to 100K tokens | $0.10 | $0.50 | $0.125 | $0.01 |
| `claude-haiku-5-5`, prompt over 100K tokens | $0.50 | $2.50 | $0.625 | $0.05 |
<!-- end:prices -->

- A one-hour cache write costs twice the input price. A cache read costs a tenth of the input price on Haiku 5.5, a twentieth on
  Opus 5.5 and Sonnet 5.5, and a fortieth on Fable 5.1.
- Haiku 5.5 is the only model with a long-prompt tier: a prompt over 100K tokens pays five times the base rate. The other three
  bill their whole window at one rate.
- The batch interface takes half off input and output.
- Models from Claude 4.7 on count about 30 percent more tokens for the same text than earlier ones, so recount before you
  compare cost with an older model. `docs/token-diet.md` section 6 works through when a cheaper model saves money, and
  `tools/token-split/token_split.py` shows where your own spend goes.

## Which model for what

Start from the vendor's rule: most workloads start with Opus 5.5, and tuning effort is often a better lever than switching
models (E34).

### Claude Fable 5.1
- **Best for:** demanding reasoning and long-horizon agentic work: sessions that run for hours, multistep deep research,
  analysis carried through to a finished document, spreadsheet or deck (E34).
- **Never for:** routine work Opus 5.5 handles. The vendor's order is to move up to Fable only when your own evals on Opus 5.5 at
  `xhigh` or `max` still fall short; it costs two and a half times Opus 5.5 per token and is the slowest (E34, E32, E31).
- **Effort:** start at `high`, the default. Go to `xhigh` or `max` for the most capability-sensitive work, and down to `medium`
  or `low` for routine or latency-sensitive work once your evals show quality holds (E33).

### Claude Opus 5.5
- **Best for:** long-running agentic coding and knowledge work, large refactors, complex systems work, vision-heavy workflows
  and computer use; the vendor's starting point for most workloads (E34).
- **Never for:** high-volume, latency-sensitive jobs such as classification, extraction and routing, where the vendor points to
  Haiku 5.5 for the lowest latency and price (E34); and code that turns thinking off, which the model rejects at every effort
  level (E33).
- **Effort:** `medium` is the default, one level below the previous Opus, so a request that sets no effort runs lower than it
  used to. Run your own sweep rather than carrying settings over, and give high levels a large `max_tokens` (E33).

### Claude Sonnet 5.5
- **Best for:** speed and capability for everyday coding, agent and enterprise work: code generation, data analysis, content
  creation, visual understanding and agentic tool use (E34).
- **Never for:** the vendor's pages rule out no task type. The one hard limit is that `thinking` set to disabled is rejected at
  every effort level; send `between_tools` instead, at `high` or below (E33).
- **Effort:** `high` is the default. For agentic coding and multistep tool use start at `medium` for well-specified tasks and
  `high` for harder or longer ones; use `medium` or `low` for chat and latency-sensitive work; try `xhigh` or `max` only where
  your evals show a gain. The levels are recalibrated from the previous Sonnet, so re-run your sweep (E33).

### Claude Haiku 5.5
- **Best for:** high-volume, latency-sensitive tasks: classification, extraction, routing, summaries, compaction, database
  queries, and subagent work next to Opus 5.5 or Sonnet 5.5 (E31, E12).
- **Never for:** complex agentic coding, where the vendor says the two larger models remain the better choice (E12); long agent
  prompts at `low` effort, where it is more likely to skip a search, stop early or skip a check (E13); and long prompts when price
  is the reason to use it, since over 100K tokens it costs five times the base rate (E32).
- **Effort:** start at `medium`, the default, for most work including agentic coding. `low` suits chat, short tool tasks and
  simple high-volume requests; `high` suits knowledge work, longer agent tasks and strict instruction following; use `xhigh` or
  `max` only where your evals show a gain, and compare them with Sonnet 5.5. To get less thinking, lower the effort: the vendor
  found that telling the model to answer directly did not stop it thinking (E13).

## Effort levels in one table

The levels and the vendor's description of each (E33). Effort is a signal, not a token budget, and it applies to tool calls and
text as well as thinking.

| Level | Meaning |
|---|---|
| `low` | The most efficient: big token savings for some loss of capability. Suits simple tasks, such as subagents. |
| `medium` | Balanced speed, cost and performance. The default on Opus 5.5 and Haiku 5.5. |
| `high` | Complex reasoning and difficult coding. The default on Fable 5.1 and Sonnet 5.5. |
| `xhigh` | Long-running agentic and coding work with large token budgets. Not every model has it. |
| `max` | No limit on token spend, for the deepest reasoning. Measure before you pay for it. |

Changing the top-level effort between requests restarts the prompt cache. Pick the level at the start of a task, or use the
vendor's per-message effort change where it is offered (`docs/token-diet.md` section 2).

## Request settings that return an error

| Model | Setting the model rejects |
|---|---|
| Fable 5.1 | `thinking` set to disabled: thinking is always on (E33) |
| Opus 5.5 | `thinking` set to disabled, at every effort level (E33) |
| Sonnet 5.5 | `thinking` set to disabled, at every effort level (E33) |
| Haiku 5.5 | `temperature` or `top_p` other than the defaults, any `top_k`, a thinking token budget, an assistant prefill, and disabled thinking at `xhigh` or `max` (E33; the rest in `docs/evidence/haiku-5-5.md`) |

The vendor's migration guide for each model lists the rest; read it before moving a pinned request to a new id.

## Keeping it current

1. Read the vendor's models, pricing and effort pages.
2. Update the `prices` key and rows E31 to E35 in `settings/model-evidence.json`, each with its page and the date you read it.
3. Run `py -3 tools/test_docs.py --render-routing` and `py -3 tools/test_models_doc.py --render`.
4. Run the kit's test suites. A price that differs between this page, `docs/token-diet.md` and the JSON fails the build.

How the routing table itself is rebuilt when a model changes: `docs/engineering/routing-method.md`.
