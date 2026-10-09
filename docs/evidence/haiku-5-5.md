# Claude Haiku 5.5: what the public pages say

As of October 2026. Everything here comes from pages anyone can read, and every row can be traced to its source in
`settings/model-evidence.json`, the one home for evidence ids, prices and numbers. Read this before you route work to the
small model; for the other three models see [Models at a glance](../models.md), and for which persona gets which model see
[Model routing](../model-routing.md).

Each row carries one tag:

- **PUBLISHED:** the model maker's own page, system card or documentation.
- **3P-PUBLISHED:** a third party's page, such as an independent leaderboard or an editor vendor's model page.
- **RUMOUR:** a claim with no primary page behind it. No routing row uses one, and none is listed here.

Internal runs by the kit's authors never appear on this page. Every row so far is tier R0: one party measured it, so treat a
row as a starting point and run your own task pack before relying on it.

## What the vendor says it is for

- Built for high-volume, cost-sensitive work: summaries, compaction, database queries, classification, and subagent work next
  to the larger models; also speed-sensitive jobs such as live support and browser use (E12).
- The larger models remain the better choice for complex agentic coding (E12, E2).
- It is the first small model with adjustable effort (the launch post), so cost against quality is a setting you choose; E35 shows
  what each step buys.

## Price tiers

The table is generated from the `prices` key (Sonnet 5.5 is there for comparison). The vendor says the small model costs about
75 percent less to run than the previous small model on average, priced 90 percent lower up to 100K tokens and 50 percent lower
above it.

<!-- begin:haiku-prices -->
| Model | Input | Output | Cache write (5 min) | Cache read |
|---|---|---|---|---|
| `claude-sonnet-5-5` | $2 | $10 | $2.50 | $0.10 |
| `claude-haiku-5-5`, prompt up to 100K tokens | $0.10 | $0.50 | $0.125 | $0.01 |
| `claude-haiku-5-5`, prompt over 100K tokens | $0.50 | $2.50 | $0.625 | $0.05 |
<!-- end:haiku-prices -->

- A prompt over 100K tokens pays five times the base rate for input, output and cache; the saving over Sonnet 5.5 shrinks from
  twenty times to four times on long prompts (E11, E32).
- The same text counts as about 30 percent more tokens than on the previous small model, so recompute any token cap, budget or
  cost estimate you tuned on it.
- Its minimum cacheable prompt is 512 tokens, against 4,096 on the previous small model.

## Effort and thinking

- Start at `medium`, the default, including for agentic coding. Use `low` for chat and short tool tasks, and `high` for
  knowledge work, longer agent tasks and strict instruction following. Compare `xhigh` and `max` with Sonnet 5.5 before you pay
  for them (E13).
- At `low` in a long agent prompt it is more likely to skip a search, stop early or skip a check. At `xhigh` in a multi-turn
  chat it can end a turn with no visible text (E13).
- Thinking is on by default and counts toward `max_tokens`. Telling the model to answer directly did not stop it thinking in
  the vendor's testing; lower the effort instead (E13).
- The launch charts show what each step buys on four benchmarks (E35); on the knowledge exam max adds under two points over
  xhigh for more than three times the cost.

## Migrating a pinned request from the previous small model

From the vendor's migration guide and prompting guide:

- The id is fixed, `claude-haiku-5-5`, with no date suffix and no alias.
- A thinking token budget, any `top_k`, any `temperature` other than 1, any `top_p` other than 0.99, and an assistant prefill each
  return an error. Use adaptive thinking with an effort level, and end the messages with a user turn.
- A reply can open with thinking blocks even if the request set no `thinking`, and the thinking text is empty unless you ask for
  a summary. Select content blocks by type, not by position.
- A forced tool choice is accepted, but the reply starts with the tool call and has no thinking block.
- Thinking blocks work only in the account that produced them, and only while everything sent before them is unchanged: keep the
  history append-only.
- Safety classifiers can decline a request with `stop_reason` set to refusal, and there is no server-side fallback: handle the
  refusal in your client.
- Priority Tier is not supported. Computer use goes through the toolset on the Claude API and Google Cloud.
- With thinking off and a JSON output format, it may skip a tool call it needs. Use adaptive thinking for those requests.

## Evidence rows

<!-- begin:rows -->
### E12 · PUBLISHED

- **Source:** Anthropic: Haiku 5.5 launch post, positioning and limits (anthropic.com/claude-haiku-5-5)
- **Finding:** The vendor positions the small model for narrowly scoped, high-volume work such as summaries, compaction, classification and subagent tasks, and says the two larger models remain the better choice for complex agentic coding.

### E13 · PUBLISHED

- **Source:** Anthropic: API docs, effort and the prompting guide for Haiku 5.5 (platform.claude.com/docs/en/build-with-claude/effort)
- **Finding:** Vendor effort guidance for the small model: start at medium; use high for knowledge work, longer agent tasks and strict instruction following; at low effort in long agent prompts it is more likely to skip a search, stop early or skip a check; at xhigh in multi-turn chat it can end a turn with no visible text; use xhigh or max only where your own evaluation shows a gain. In Anthropic's testing, telling the model to answer directly did not stop it thinking; lower the effort instead.

### E11 · PUBLISHED

- **Source:** Anthropic: Haiku 5.5 launch post and API pricing page (anthropic.com/claude-haiku-5-5, platform.claude.com/docs/en/about-claude/pricing)
- **Finding:** The small model is the only current model with a long-prompt price tier: prompts over the threshold cost five times the base input and output rates, so its saving over the mid-tier shrinks on long agent prompts.
- **Numbers:** Haiku 5.5 per million tokens: input $0.10 (prompts up to 100K tokens) or $0.50 (over 100K); output $0.50 or $2.50; cache read $0.01 or $0.05. Sonnet 5.5: input $2.00, output $10.00, cache read $0.10

### E35 · PUBLISHED

- **Source:** Anthropic: Haiku 5.5 launch post, effort charts for the small model (anthropic.com/claude-haiku-5-5)
- **Finding:** On the vendor's launch charts the small model improves at every effort step on all four benchmarks shown; the last step to max costs more than twice as much as xhigh on three of them, and on the knowledge exam it adds under two points for more than three times the cost.
- **Numbers:** Haiku 5.5, score and cost per attempt in USD at low, medium, high, xhigh, max. OSWorld 2.1 offline subset: 42.0% ($0.0695), 53.3% ($0.1257), 61.3% ($0.1827), 67.6% ($0.2792), 72.4% ($0.6111). GDPval-AA v2.1 (Elo): 1125 ($0.01167), 1277 ($0.03042), 1420 ($0.08938), 1513 ($0.26725), 1620 ($0.86593). Humanity's Last Exam, no tools: 30.9% ($0.00334), 35.5% ($0.00693), 39.7% ($0.02043), 44.1% ($0.06452), 45.9% ($0.21367). Terminal-Bench 4.0: 12.7% ($0.424), 20.3% ($0.6798), 24.8% ($1.0372), 31.5% ($1.7545), 39.2% ($2.6433).

### E2 · PUBLISHED

- **Source:** Anthropic: Terminal-Bench 4.0 launch charts, Claude Code harness (anthropic.com/claude-haiku-5-5, anthropic.com/claude-opus-5-5)
- **Finding:** On the vendor's own harness the top tier at high scores a few points above the mid-tier at xhigh for slightly less per attempt, the mid-tier at max posts the highest score but at more than twice its xhigh cost, and the top tier's max scores below its xhigh.
- **Numbers:** Terminal-Bench 4.0 (Claude Code): Opus 5.5 high 64.2% ($3.88 per attempt), xhigh 66.4% ($7.35), max 64.8% ($11.24); Sonnet 5.5 high 43.0% ($1.46), xhigh 61.5% ($4.34), max 70.6% ($10.44); Haiku 5.5 max 39.2% ($2.64)

### E8 · PUBLISHED

- **Source:** Anthropic: OSWorld 2.1 offline subset, Haiku 5.5 launch charts (anthropic.com/claude-haiku-5-5)
- **Finding:** On computer-use loops the mid-tier at xhigh is within three points of its max at under half the cost; the small model's xhigh matches the mid-tier's medium at under a third of the cost, but its max stays below the mid-tier's xhigh.
- **Numbers:** OSWorld 2.1 offline subset, partial credit: Sonnet 5.5 medium 66.0% ($0.93 per attempt), high 73.2% ($1.38), xhigh 81.1% ($2.22), max 83.9% ($5.73); Haiku 5.5 xhigh 67.6% ($0.28), max 72.4% ($0.61)

### E29 · PUBLISHED

- **Source:** Anthropic: Haiku 5.5 system card, ProgramBench long-context coding results (anthropic.com/claude-haiku-5-5-system-card)
- **Finding:** On the vendor's long-context agentic coding benchmark, where the agent rebuilds a program from its compiled binary and documentation with inputs up to about a million tokens, the small model scores slightly above the mid-tier and well below the top tier; the card runs the small model at max effort and does not state the others' effort.
- **Numbers:** ProgramBench (166 tasks after the card dropped 34 flaky ones; inputs up to the 1M-token window): Opus 5.5 91.2%, Haiku 5.5 82.0%, Sonnet 5.5 79.7%; the card's standard configuration runs Haiku 5.5 at max effort and does not state the effort of the other two on this benchmark

### E14 · PUBLISHED

- **Source:** Anthropic: Haiku 5.5 system card and prompting guide, safeguards and behavioural audit (anthropic.com/claude-haiku-5-5-system-card)
- **Finding:** The small model's cyber safeguards trigger on significantly less activity than other recent releases and it has no server-side fallback after a refusal; in the vendor's behavioural audit it over-refused more than any other model tested and sometimes used a leaked answer without telling the user.

### E1 · 3P-PUBLISHED

- **Source:** Artificial Analysis: Terminal-Bench 4.0 on the per-effort model pages (artificialanalysis.ai/models/claude-opus-5-5-high and sibling pages)
- **Finding:** On a terminal-task benchmark the mid-tier at xhigh and the top tier at high are within a point of each other at similar cost, the top tier scores no higher at max than at xhigh, and the small model's best setting stays below the mid-tier's high setting.
- **Numbers:** Terminal-Bench 4.0: Sonnet 5.5 high 43.9% ($2.19 per task), xhigh 57.1% ($6.08), max 63.6% ($12.65); Opus 5.5 medium 52.5% ($4.04), high 56.6% ($5.12), xhigh 59.6% ($8.78), max 59.6% ($13.11); Haiku 5.5 xhigh 29.3% ($0.46), max 32.8% ($0.65)

### E7 · 3P-PUBLISHED

- **Source:** Artificial Analysis: AutomationBench-AA on the per-effort model pages (artificialanalysis.ai/models/claude-sonnet-5-5-xhigh and sibling pages)
- **Finding:** On a multi-step tool-automation benchmark the mid-tier at xhigh matches the top tier at xhigh for about half the cost and gains about six points over its own high; the small model's best setting scores below the mid-tier's low setting.
- **Numbers:** AutomationBench-AA: Sonnet 5.5 low 49.4% ($0.241 per task), high 59.4% ($0.313), xhigh 65.5% ($0.422), max 71.8% ($1.03); Opus 5.5 high 63.2% ($0.699), xhigh 65.0% ($0.878), max 69.5% ($1.43); Haiku 5.5 xhigh 36.0% ($0.028), max 35.4% ($0.042)

### E10 · 3P-PUBLISHED

- **Source:** Artificial Analysis: AA-LCR v1.1 long-context reasoning on the per-effort model pages (artificialanalysis.ai/models/claude-haiku-5-5-high and sibling pages)
- **Finding:** On answering questions over long documents the small model ties the mid-tier at medium effort and again at max for a small fraction of the cost; the cost shown matches the vendor's base price tier, so the real saving is smaller on long prompts.
- **Numbers:** AA-LCR v1.1: Haiku 5.5 medium 77.3% ($0.015 per task), xhigh 78.3%, max 82.7% ($0.019); Sonnet 5.5 medium 76.3% ($0.292), high 78.0% ($0.294), max 82.7% ($0.339); Opus 5.5 medium 84.3% ($0.590), max 84.7% ($0.677)

### E3 · 3P-PUBLISHED

- **Source:** Cursor: CursorBench 4.0 leaderboard (cursor.com/cursorbench)
- **Finding:** On an editor-agent coding benchmark the top tier at high matches its own xhigh and sits under two points below its max at under a third of the cost; the mid-tier at xhigh reaches most of that score for less; the small model's best setting only matches the mid-tier at high.
- **Numbers:** CursorBench 4.0: Opus 5.5 high 56.0% ($3.97 per task), xhigh 56.0% ($6.98), max 57.8% ($13.43); Sonnet 5.5 high 47.8% ($1.20), xhigh 53.1% ($2.81), max 55.5% ($7.05); Haiku 5.5 max 48.4% ($1.12)

### E30 · 3P-PUBLISHED

- **Source:** Cursor: Claude Haiku 5.5 model page, CursorBench with thinking on and off (cursor.com/docs/models/claude-haiku-5-5)
- **Finding:** On an editor-agent coding benchmark the small model with thinking off scores well below its thinking-on result at the same effort levels.
- **Numbers:** CursorBench: thinking off 22.1% to 26.2%, thinking on 30.9% to 42.3% at the same effort levels (the page does not list the levels); thinking on reaches 48.4% at max
<!-- end:rows -->

## Reading the rows

- The independent leaderboard labels its Opus 5.5 and Sonnet 5.5 entries "with fallback" (a refused request is re-run on another
  model) and its Haiku 5.5 entries without. The vendor says the small model has no server-side fallback (E14). Compare entries
  with that label difference in mind (E1, E7, E10).
- The same benchmark gives different numbers under different harnesses: terminal tasks at max effort read higher in the vendor's own
  harness (E2) than on the independent leaderboard (E1). Compare rows within one source.
- The launch charts and the system card are the vendor's own runs; the editor vendor's page and the leaderboards are third-party
  runs.
- Chart values the page does not print as text, and numbers that sit only in a sibling model's card, are left out rather than
  guessed.
- A model page can change after this was written. Re-read it before a decision that costs money.
