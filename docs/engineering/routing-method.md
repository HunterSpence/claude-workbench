# How the routing table is built, and how to rebuild it

The table in [Model routing](../model-routing.md) says which model, at which effort, a task shape gets. It is not opinion: it is
generated from two files, and this page is the method behind them, so a team can redo it when a model, a price or an effort
level changes instead of trusting the shipped table for ever. The facts about each model are on [Models at a glance](../models.md).

| File | Holds |
|---|---|
| `settings/model-routing.json` | The rows: task shape, persona, preference order of model and effort, what never to use, and the evidence ids each row cites |
| `settings/model-evidence.json` | The evidence rows (source page, date, kind, tier, a finding in words, the numbers) and the `prices` table |
| `docs/model-routing.md` | Generated from the two by `py -3 tools/test_docs.py --render-routing`; edit the JSON, never the page |

## The rules

1. **Published data only.** A routing pick rests on evidence rows of kind `vendor` (the model maker's own page, card or
   documentation) or `independent` (a third party's page), each with a source and the date it was read. Nothing else may rank a
   pick: not a hunch, not a blog summary, not a number you cannot point to on a page.
2. **Your own runs show direction only.** A small run by your own team goes in as an `internal-run` row with a direction, a count
   and a month, no value, no cost and no score. It may confirm or question a pick; it never makes one. The checker enforces this.
3. **Say how many parties measured it.** Tier R0 means one party measured it, R1 one independent replication, R2 two or more.
   A row that only has R0 evidence is a starting point: run your own task pack on it before you rely on it.
4. **Match the benchmark to the task.** Pick evidence that looks like the task shape: agentic coding results for a coding row,
   long-context reading for a reading row, tool-loop automation for a collecting row. A good score on a different kind of work
   is not evidence for this one.
5. **Cost per task next to score.** An effort level that adds a point for three times the cost is not a better pick. The vendors'
   own effort pages say the top levels earn their cost only where your evals show a gain.
6. **Do not rank inside the noise.** If two settings are within a point or two on one benchmark, report them as a tier and
   let cost or latency decide.
7. **Keep numbers out of the rows.** Routing rows carry words and ids; the digits live in the evidence rows. The checker fails a
   routing row with a digit outside a model id.
8. **Prefer a persona over a model name.** A row names the persona that does the work. The persona file carries the first choice
   of its row in `plugins/workbench-core/agents/`, and a test keeps the two equal.

## Rebuilding the table

1. **List the task shapes.** One row per kind of work you hand to a worker: reading, collecting, coding a planned slice, a hard
   build, a final check, an attack, an alternative. Name the persona for each.
2. **Collect the evidence rows.** For each candidate model and effort, read the vendor's launch and model pages and the
   independent leaderboards for the same period. Record each as an evidence row: source page, date read, kind, tier, a finding in
   plain words, and the numbers with their cost per task. Read the actual page; a chart image is not a source until you have read
   the values.
3. **Draft the table from the rows.** For each task shape write the first choice, one fallback, and a `never` line for any model
   a published page argues against, each citing evidence ids.
4. **Attack it.** Give the draft and the evidence rows, and nothing else, to `red-team`. Ask for the strongest published evidence
   against each row's first choice: a cheaper setting that matches it, a dearer one that clearly beats it, a benchmark that does not
   look like the task. Every claim must name a row id.
5. **Ask for an alternative.** Give `green-team` the evidence rows and the task shapes, without the draft, and have it build its own
   table. Where the two tables disagree, the disagreement is the finding.
6. **Judge.** `blue-verify` gets the draft, the attack and the alternative. For each row it decides keep or change, names the
   evidence id behind the decision, explains ties, and lists every claim that has no row id as unsupported. Cut the unsupported
   claims.
7. **Write the JSON and render.** Update both files, then run `py -3 tools/test_docs.py --render-routing`,
   `py -3 tools/test_docs.py --deny docs settings`, and the kit's suites. The routing snapshot in `tools/test_models_doc.py` is
   frozen on purpose: change it in the same commit as an intended routing change, never to make a failure go away.
8. **Check on your own work.** Run a small task pack with `tools/skill-bench` on the new first choices, and record the direction as
   an `internal-run` row.

Prompt skeletons that have held up (shorten, never widen):

```text
RED: You attack a draft routing table. Use only the evidence rows given. For each routing row, find the strongest evidence
against its first choice and quote the row id. Do not propose new rows.
GREEN: Using only the evidence rows given, build a routing table for these task shapes. You have not seen any draft.
BLUE: You get a draft, an attack and an alternative. For each row decide keep or change, cite the evidence id, explain ties, and
list every claim with no row id as unsupported.
```

## When to redo it

A new model id, a price change, a retirement notice, a recalibrated effort scale, or a vendor page that contradicts a row. A
price change alone is a one-file edit to the `prices` key (see "Keeping it current" on [Models at a glance](../models.md)); the
rows only need rework when what a model can do, not what it costs, has changed.
