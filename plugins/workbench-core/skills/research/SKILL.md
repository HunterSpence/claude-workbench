---
name: research
description: "Tiered web research: low (1 searcher), medium (3 searchers, researcher writes), high (5, plus red-team and blue-verify). Use for low/medium/high research or \"research X\"."
---

# /workbench-core:research: research tiers

The user names the tier; you pick the agents from this table. "Research" with no tier is MEDIUM. Every tier searches
the web; no tier answers from memory. The user's own counts, models or effort win.

| Tier | Search | Report | Check | For |
|---|---|---|---|---|
| LOW | 1 `searcher` | the searcher's answer, relayed in at most ten lines with links | re-open one cited source yourself | a quick sourced answer |
| MEDIUM | 3 `searcher`, one sub-question each | `researcher` (Opus 5.5 high) | re-fetch three claims yourself | most research; an answer that feeds a decision |
| HIGH | 5 `searcher` | `researcher` | `red-team` attacks the findings, then `blue-verify` gates | money, legal status, health, or anything hard to undo |

Persona names: the kit's personas spawn as `workbench-core:<name>`. The `searcher` is `workbench-core:searcher` when it
came with the plugin, or plain `searcher` when it sits in your own agents folder.

## Which model the searcher runs
- It ships on Sonnet 5.5 `xhigh` (the BREADTH row), which draws on plan limits on every seat. Its file has a marked
  switch to Fable 5.2 `low` for seats that include Fable; there, Fable scores higher on agentic search for less (KB
  note `_shared/digests/fable-5-2-routing.md`, item 1). Never flip it on a seat where Fable bills usage credits
  unless the user says yes.
- HIGH on a Fable searcher: spawn the searchers with `effort: "high"` (the user named the tier). On the Sonnet default
  pass no effort: `high` would lower it.
- The report writer stays `researcher` (Opus 5.5 high): the value point on research-report benchmarks, where Fable is
  never the cheaper way to a score (same note, item 2).

## Swaps (safety and rules, not cost)
- Security, biology or medical topics with a Fable searcher: run those lanes on `general-purpose` (Sonnet xhigh);
  Fable's safety filters block that work.
- Legal, tax, medical or other regulated questions: the report is written by `flagship` (Opus 5.5 xhigh) citing
  primary sources, then `blue-verify`, at every tier (the REGULATED row in `rules/model-policy.md`).
- A searcher reports a Fable limit or a safety refusal: rerun that lane on `general-purpose` and say so. A usage-limit
  error for the whole seat: stop launching, as `rules/model-policy.md` says.
- Headless runs (`claude -p`, scheduled jobs): keep the Sonnet searcher. A headless Fable request bills usage credits
  without asking.

## Run it
1. Split the question into the tier's number of sub-questions that do not overlap (for example: primary sources,
   prices and specs, recent changes, evidence against, local-language sources). Write them down before spawning.
2. Spawn every searcher in ONE message so they run in parallel. Each prompt follows the `spawn` skill's template: the
   sub-question, today's date, the return shape and the constraints it needs. WebSearch is one budget for the whole
   session, shared by every searcher; the optional search servers in `mcp/README.md` can back a lane.
3. Give the report writer the original question, every searcher's findings verbatim, and the shape the user asked
   for.
4. Run the tier's check, then deliver. MEDIUM and HIGH: a report, delivered as the reports rule in
   `rules/tool-routing.md` says. LOW: the answer inline, with links.

Many lanes, adversarial checking and a decision list at the end: use `deep-research` instead.
