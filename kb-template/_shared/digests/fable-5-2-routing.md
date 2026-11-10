---
title: Digest, Fable 5.2 routing (where it wins, where it should not go, which effort)
domain: _shared
status: active
---
# Fable 5.2 routing: where it wins, where it should not go, and which effort

Read this before picking Claude Fable 5.2 for a task, a persona or the main session, before switching the `searcher`
persona to Fable, and when someone asks whether Fable saves money. Scores are Anthropic's published results unless
marked AA (Artificial Analysis). A ratio is Fable's published cost per task divided by the comparison's; some costs are
read off the published charts, so treat a ratio as about five percent either way. The kit's model rows are in
`docs/model-routing.md` in the kit copy; the general effort and token rules are in [[_shared/digests/models-and-tokens]].

## Bottom line
- Fable 5.2 is a quality upgrade for a few task shapes, not a way to cut a bill. Per token it costs twice Opus 5.5 for
  input, output and cache writes, the same for cache reads, and four times Sonnet 5.5 for input and output [S6].
- Where it wins, it wins at `low` or `medium` effort, often for a fraction of Opus's cost per task [S2] [S3].
- Whether it spends plan limits or usage credits depends on your plan and seat (section "Plans and seats").

## Where it wins (best first; the comparison is the kit's pin for that work)
1. **Hard questions answered with tools, wide data-collection search: Fable `low`.** WANDR 71.4 [S2]
   against 67.3 for Opus 5.5 `high` (the `researcher` pin) at 0.73×; HLE with tools 68.4 against 63.9 at 0.66× [S2]. Against Sonnet 5.5 `xhigh` (the
   BREADTH pin): +5.0 on WANDR at 0.82× and +6.4 on HLE with tools at 0.38× [S2]. These costs assume a perfect cache
   hit and leave out web-search fees [S2]. Fable at `high` adds 7.9 more on WANDR for 2.3× the cost of `low` [S2].
2. **Not for writing the research report.** On DRACO and DeepResearch Bench II, Fable is never the cheaper way to a
   score: 2.0 to 7.1× and 1.3 to 4.3× the cost [S2] [S3]. Opus 5.5 `high` is the value point there: DRACO 85.0 against
   Opus `xhigh` 86.7, a tie, at 2.5× the cost [S2].
3. **Hard closed-book reasoning (maths, science, technical): Fable `low` or `medium`.** HLE without tools: `low` scores
   +2.8 over Opus `xhigh` at 0.48× [S2]. HLE-Diamond: `medium` 66.3 against Opus `xhigh` 64.0 at 0.39× (AA) [S7]. CritPt:
   `low` ties Opus `high` at 0.81× (AA) [S7].
4. **Chart and figure reading: Fable `low`.** Chartography 64.2 [S2], level with Opus `max` 64.4 at
   0.06×, and 0.38× of Opus `xhigh`'s cost [S2].
5. **Escalation after an Opus `xhigh` build fails on hard, novel code: Fable `high`.** FrontierCode 2.0 [S2]: 45.3 against
   Opus `xhigh` 43.4, a tie, at 1.30× [S2]; AA has 49.1 against 43.8 at 1.48× [S7]. Fable `high` ties Opus `max` at
   0.52×; `xhigh` is the ceiling, at 2.7× [S2].
6. **Closed-book recall as a cross-check: Fable `low`.** AA-Omniscience 62.9 against Opus `xhigh` 43.1 at 0.93× (AA) [S7].
7. **Hardware and CAD design: any effort.** Cheaper than Opus at every level on BenchCAD [S2].
- Anthropic also reports a large gain on long unattended work [S2] (Remote Labor Index +20.0 at matched
  effort) with no cost data [S2], so it earns no routing row yet.

## Where it should not go
- **The main session at `xhigh`.** On the AA index, `xhigh` 62.2 ties `high` 61.8, and `high` costs 0.61× as much [S7].
  A context-heavy main session pays the doubled token price on every turn [S6]. Keep Opus 5.5 there; if you choose
  Fable for the main session, use `high`.
- **Product coding, terminal and ops, tool automation.** CursorBench: Opus `high` reaches the same score for less [S2].
  Terminal-Bench 4.0: Fable `high` costs 1.53× Opus `xhigh` for a tie (AA) [S7]. AutomationBench: Sonnet `xhigh`
  dominates and Fable `low` costs 3.0× (AA) [S7]. A SWE-bench Pro subset: 1.8 to 4.6× the cost [S3].
- **Final documents and other knowledge-work deliverables.** GDPval: Fable `xhigh` is 84 Elo below Opus `xhigh` (AA) [S7].
  AA-Briefcase: Opus `xhigh` 1760 against Fable `xhigh` 1738, with Fable at 2.3× the cost (AA) [S7].
- **Large codebases in one long context.** ProgramBench: 5.6 points lower, out of context on 68% of tasks [S2]; with a
  context-remaining counter it ties, 91.6 against 91.1 [S2].
- **Security and biology.** Safety classifiers block most cybersecurity and much biology work and fall back to Opus 4.8
  or Opus 5 [S1] [S8]. The `security-auditor` stays on Opus, and a Fable `searcher` never takes those topics.
- **Medical, legal, tax.** No published Fable 5.2 advantage on the health or legal benchmarks so far; the kit's
  REGULATED row (Opus 5.5 `xhigh` plus `blue-verify`) stands.
- **The Sonnet rows** (`implementer`, general-purpose, `red-team`, `green-team`): four times the price for input and output, twice for cache reads
  for no published gain on those task shapes [S6].
- **An orchestrator in Opus's place:** +0.2 F1 for 19% more cost in Anthropic's own run [S3].

## Effort: the lowest Fable 5.2 level that matches
| Work | Kit pin | Fable level that matches the pin (cost ratio) | Fable against the best other model |
|---|---|---|---|
| Search, questions with tools [S2] | Opus `high` | `low`, +4.1 and +4.5 (0.73× and 0.66×) | `low` ties Opus `max` (0.33× and 0.09×) |
| Closed-book reasoning [S2] [S7] | Opus `xhigh` | `low` +2.8 (0.48×); AA HLE-Diamond `medium` +2.3 (0.39×) | `low` ties Opus `max` (0.16×) |
| Charts [S2] | Opus `xhigh` | `low` (0.38×) | `low` ties Opus `max` (0.06×) |
| Recall, AA [S7] | Opus `xhigh` | `low` +19.8 (0.93×) | `low` beats Opus `max` by 14.8 (0.07×) |
| Hard novel coding [S2] [S7] | Opus `xhigh` | `high`, a tie (1.30×); AA +5.4 (1.48×) | `high` ties Opus `max` (0.52×) |
| Product coding, CursorBench [S2] | Sonnet or Opus `xhigh` | none: Opus `high` is cheaper | `high` ties Opus `max` (0.72×) |
| Terminal and ops, AA [S7] | Opus `high` | `medium`, a tie (1.03×) | none cheaper; Sonnet `max` scores best |
| Research reports [S2] | Opus `high` | `high`, a tie (2.39×) | never cheaper |
| Main session, AA index [S7] | Opus `xhigh` | `medium` ties (0.63×) but trails Fable `high` by 127 GDPval Elo; `high` +4.4 (1.50×) | `high` beats Opus `max` (0.90×) |

- **Effort steps on Fable 5.2** (the median of ten published curves): `medium` to `high` costs 2.20× for +3.7 points [S2] [S3],
  `high` to `xhigh` 1.89× for +1.8, `xhigh` to `max` 2.28× for +2.2 [S2] [S3]. `low` costs about 0.42× and `medium`
  about 0.46× of `high` [S2] [S3].
- **Kit picks:** `low` for search, charts and recall; `medium` for closed-book questions (on AA HLE-Diamond, `low` trails
  Opus `xhigh` by 3.2) [S7]; `high` for a coding escalation and for the main session. Avoid `max`.
- **Defaults:** Claude Code runs Fable 5.2 at `medium` unless a level is set; the API default is `high` [S4] [S8]. A
  persona's `effort:` line overrides both (see [[_shared/digests/models-and-tokens]]).
- **Early stopping:** at `low` and `medium` a turn more often ends before the work is done [S5]. Anthropic's
  prompting guide gives a finish-the-whole-task instruction; the `searcher` persona carries one [S5].
- **Output tokens per task (AA):** Fable `medium` 43k against Opus `xhigh` 103k; Fable `low` 36k against Opus `high` 60k [S7];
  Fable `high` 98k against Opus `xhigh` 103k [S7]. Fewer tokens, each at twice the price [S6].

## Plans and seats: plan limits or usage credits
- Max and Ultra plans and premium seats on Team and seat-based Enterprise plans include Fable up to half of the weekly
  usage limit, and Anthropic says Fable uses those limits faster than other models. Past that, you continue on usage
  credits or switch models. Pro plans and standard seats run Fable on usage credits from the start (a launch-week promotion also included Fable for Pro and Team standard seats; check `/model` again after it ends); usage-based
  Enterprise plans pay API rates; on Enterprise, Fable 5.2 stays off until an admin enables it; a week after launch it joins every role that already has a Fable model unless an admin opts out. Source: Claude Help Center,
  "Claude Fable models on your plan".
- **Check your own seat:** in `/model`, a Fable row marked "Requires usage credits" means Fable bills usage credits,
  not your plan's limits [S8]. `/usage` shows what you have used. How fast Fable drains a seat's limit is not published
  as a number: measure it on your own plan before routing routine work to Fable.
- **Headless runs never ask:** with `claude -p`, or an SDK application that shows no prompt, a Fable request that would
  bill usage credits is billed without asking [S8]. Keep headless and scheduled work off Fable unless the seat includes
  it.
- **Name the model id.** The kit's permissive settings profile pins the `fable` alias to Fable 5.1 through
  `ANTHROPIC_DEFAULT_FABLE_MODEL`; use `claude-fable-5-2`, which needs Claude Code 2.1.321 or later [S8]. An
  organisation's model allow-list can exclude it.

## How the kit uses this
- **The `research` skill** runs web research in three tiers. Its `searcher` persona ships on Sonnet 5.5 `xhigh` (the
  BREADTH pin, from plan limits on every seat) and has a marked switch to Fable 5.2 `low` for seats that include Fable,
  where it scores higher for less (item 1 above). The report writer stays `researcher` (Opus 5.5 `high`, item 2).
- **Everything else keeps its row.** Fable is the user's pick, never a default; offer it for the winning shapes above.

## Ponytail on Fable 5.2 (our runs, one party)
- The same one-line tickets as [[_shared/digests/ponytail-measurements]], Fable 5.2 at `high`, session cost as a share
  of the no-rules cost, with 90% intervals [M1]:
  - rules present from the start plus a codebase map, as the build personas carry them: 0.50 [0.37, 0.65] [M1];
  - a hook that adds the rules and the map on the first read or write of a code file: 0.66 [0.54, 0.77] [M1].
- The saving comes from fewer turns (about 0.55 and 0.81 of the no-rules count) and about half the output tokens [M1].
- Completeness held: about 2.9 of 3 in every arm, no session below 2.5, a paired drop under a tenth of a point, two
  blind judges [M1]. No ponytail setting needs to change for Fable; effort, not ponytail, sets how much it thinks.

## Measurements
- [M1] Ponytail delivery arms against no rules on Fable 5.2 at high effort, cost from usage, two blind judges for completeness · corpus the twelve one-line tickets on a public full-stack web app template · n=about a dozen sessions per arm, one repetition per ticket · tier R0

## Sources
- [S1] Anthropic, Claude Fable 5.2 and Claude Mythos 5.2 announcement · https://www.anthropic.com/claude-fable-and-mythos-5-2 · fetched 2026-11-10
- [S2] Anthropic, Claude Fable 5.2 and Claude Mythos 5.2 system card · https://www.anthropic.com/document/claude-fable-5-2-mythos-5-2-system-card · fetched 2026-11-10
- [S3] Claude API docs, Optimizing for cost and intelligence · https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence · fetched 2026-11-10
- [S4] Claude API docs, Effort · https://platform.claude.com/docs/en/build-with-claude/effort · fetched 2026-11-10
- [S5] Claude API docs, Prompting Claude Fable 5.2 · https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5-2 · fetched 2026-11-10
- [S6] Claude API docs, model prices · https://platform.claude.com/docs/en/about-claude/pricing · fetched 2026-11-10
- [S7] Artificial Analysis, Claude Fable 5.2 model page · https://artificialanalysis.ai/models/claude-fable-5-2 · fetched 2026-11-10
- [S8] Claude Code docs, Model configuration · https://code.claude.com/docs/en/model-config · fetched 2026-11-10
