# How knowledge-base search is built and how to tell it still works

`kb_search.py` answers "where did we write that down" over the notes in your knowledge base. This page says what it
does, how `kb_eval.py` measures it, how to write a set of known questions for your own notes, and what the set the kit
ships does and does not prove.

## What the search does
- **Two rankings, fused.** The chunk ranking scores every paragraph of every note (heading words count three times the
  body words). The note ranking scores one row per note: its title, the words of its path, and all its headings. The two
  lists are merged by reciprocal rank (each list gives a note `1 / (60 + rank)`, the scores add), so a note both lists
  like beats a note only one list likes.
- **One hit per note.** The hit shows the note's best chunk. A long note can no longer fill the first page of results;
  `--all-chunks` gives the old listing, every matching chunk by its own score.
- **A fixed pool.** Each ranking is cut to its best 40 notes before they are merged, so `--limit` only trims the end of
  one ranked list and never reorders it.
- **All words, else any word.** The two rankings ask for every query word together. Only when neither finds a note with
  every word does the search fall back to any word, so a weak partial match in one ranking never outvotes a full match
  in the other.
- **Retired text is marked.** A hit whose chunk holds SUPERSEDED, OBSOLETE or CORRECTED is tagged `[SUPERSEDED]` (JSON:
  `"superseded": true`) and ranks lower; so do history notes.
- **Links.** A note link is the path in double square brackets. It resolves from the KB root, beside the note, as a
  folder's `00-index.md`, and then by file name when exactly one note has that name (so a link written as the bare file
  name `bug-cards` finds `_shared/bug-cards.md`). A name two notes share stays unresolved; `kb_health.py` reports it as a
  dead link.
- **No FTS5.** On a Python built without FTS5 the same two rankings run as substring matches ordered by how many query
  words match. The JSON says `"ranking": "keyword fallback"`.
- **Index state.** The JSON key `mode` says how the search ran: `index`, `stale-index`, or `grep` when the index could
  not be used (one WARNING line is printed and the search scans the notes directly).

A miss is not proof the note is absent. This is keyword search with stemming: retry once with the note's own words (the
tool, the error string, the name) before concluding there is nothing.

## What `kb_eval.py` measures
Run `kb_eval.py --set FILE` (add `--json` for the summary, `--per-query` for one row per case). A set is a JSON file.

An answerable case names the note that holds the answer:

    {"q": "how do we rotate the proxy cert", "expect": ["infra/proxy-cert.md"], "heading": "Rollover"}

`expect` lists the acceptable notes. `heading` is optional: part of the heading of the section that must be the hit
shown, for a note that answers many questions (a list of failure cards, a digest). `domain` is optional too.

An abstain case is a question the knowledge base cannot answer:

    {"q": "wibblefrot snarkle plonkity", "abstain": true}

| Measure | Meaning |
|---|---|
| `hit@1`, `hit@5` | Share of answerable cases whose expected note is the first hit, or among the first five |
| `mrr` | Mean of 1 / rank of the expected note (0 when it is not in the first ten) |
| `abstain` | Share of abstain cases for which the search returned nothing |
| `latency_ms` | p50, p95 and mean time of one search, over every case (nearest-rank percentiles) |

Everything except the times is deterministic: two runs on one knowledge base give the same numbers. The tests assert it.

**Abstention has a narrow meaning.** The search falls back to any query word, so a question that shares even one common
word with some note returns a weak hit and is not quiet. Write abstain cases with invented words that appear in no
note; they catch a search that invents a match, not one that is merely loose.

## Floors
A set may carry `"_floors": {"cases": N, "abstain_cases": M, "hit@1": x, "hit@5": y, "mrr": z, "abstain": a}`. A result
below any floor is listed under `below_floors` and `kb_eval.py` exits 1. `kb_health.py --eval FILE` runs the same set as
a health check (FAIL below the floors, INFO when the set has none), and `--json` gives it to a script. Because `cases`
is a floor too, deleting cases cannot lower the bar.

Rules the kit follows for its own set, and that you should follow for yours:
1. Write the cases from the questions you really ask, before you run anything.
2. Commit the set with no floors. Run it. Copy the exact result into `_floors`.
3. Never edit a case to fit a result, and never raise a floor silently; a change to either is its own commit with the
   reason.
4. After a change to the search, run the set before and after. A floor failing is the signal; do not retune the cases.

## The set the kit ships
`plugins/workbench-kb/tests/kb_canned.json` holds twelve answerable cases and two abstain cases. They name only the
failure cards, two digests (Claude Code mechanics and testing), the HOT files and the index, because those are the notes a
later edit to the other digests, the README or the facts file leaves alone. The unit tests run it on a throwaway copy of
`kb-template/` twice and require the same numbers, and they break one case on purpose to show the floors catch it.

What it proves and what it does not:
- It proves nothing regressed on these fourteen questions. The first run found all twelve at rank one and both abstain
  cases quiet, so every floor is 1.0: one case slipping to rank two fails it.
- It is **not** a benchmark. Fourteen cases written by the people who wrote the search is a smoke test of one party's
  own work, direction only. It cannot say the search is good on your notes; write a set from your own questions for that.
- The latency figures come from a synthetic knowledge base of two thousand notes. The tests require a p95 under 300 ms
  for the search itself and a median under 300 ms for the whole command, Python start-up included. Your disk and
  antivirus will move both.

## Measuring honestly
The shipped set catches regressions. To decide whether a change to search, chunking, embeddings or a prompt
actually helped, measure it the way the digest `_shared/digests/retrieval-eval-method.md` in your knowledge base
describes. In short:
- **Pre-register** the question source, the split, the metrics, the gates and the smallest difference the sample can
  resolve; commit it before any result and never edit it afterwards.
- **Use real questions** mined from what people typed, split into a dev half and a confirm half, plus near-miss
  unanswerables (the subject exists, the asked-for detail does not).
- **Label blind:** labellers find the answer with grep and reading, never with the search being tested, and a second
  labeller audits a random sample.
- **Plant controls for any model judge** (answers with known verdicts) and conclude nothing when it misses them.
- **Measure the noise floor** by re-reading the same questions with the same code; a difference inside it is not a
  result. Report rates with Wilson intervals and compare before and after on the same questions.
- **Count negative flips** (right before, wrong after) and cap them, and require a change to hold on more than one set.

## Health checks that use the same machinery
`kb_health.py` adds three checks:
- `orphans` (WARN): topic notes that no other note links to. Add a line to the domain's `HOT.md` or to `00-index.md`.
- `retrieval` (FAIL when a whole tier is unreachable): for a sample of notes from each tier that holds notes (HOT, topic,
  history), the note's own three rarest words must bring it back in the first ten hits. It fails when the index leaves
  a tier out or search cannot reach it.
- `eval` (only with `--eval FILE`): the floors above.

Meaning search is a different tool: `find search --root kb` finds a note by what it says rather than by its words, and is
the fallback when a keyword search misses.
