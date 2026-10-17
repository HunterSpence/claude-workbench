---
title: Digest, retrieval evaluation method
domain: _shared
status: active
---
# Retrieval evaluation: measuring a search or RAG change honestly

Read this before claiming that a search, ranking, chunking, embedding or prompt change helped, and before building one
on the strength of a demo. The mechanics of the kit's own known-answer set and its floors are in
`docs/engineering/retrieval-eval.md`; the general test-the-test checklist is `instructions/rules/test-validity.md`.
This page is method only.

## Before measuring
- **Pre-register.** Write down the question source, the split, every metric, every gate and the smallest difference
  the sample can resolve, commit it, and never edit it after a result. An amendment is allowed only before the data it
  touches exists, dated, with its reason.
- **Real questions, not authored ones.** Mine what people actually typed (search logs, chat transcripts), remove
  duplicates and malformed entries, draw a sample with a fixed seed and split it into a dev half and a confirm half.
  Questions you write yourself test your own vocabulary, and a search tuned on them looks better than it is.
- **Near-miss unanswerables.** Add questions whose subject exists but whose asked-for detail does not, with the
  absence proven by grep. Invented-word questions only catch a search that makes up matches.
- **Power.** From a small pilot's paired spread, state the smallest difference the run can resolve. A result inside it
  is UNRESOLVED, never a pass or a fail.

## Labels
- **Blind labels.** Labellers find the gold note with grep and reading, never with the system under test.
- **Record per question:** the information need, answerable or not, the gold notes, the current answer with its
  evidence line, hops (one note or several), and whether an older value of the same fact also exists.
- **Audit the labels.** A second labeller re-labels a random fifth without seeing the first labels. Disagreement means
  re-labelling the disputed cases and auditing once more. Auditors also take an unmarked stale value for the live one,
  so the labelling brief needs a "search for a later statement" step.

## Judging answers
- **A judge on a different model** from the one that answered, with a fixed verdict set: correct, partial, stale, wrong,
  abstained correctly, missed, invented.
- **Diagnose stale verdicts before tuning ranking.** A stale answer often means two sources state different values
  with neither marked as the older one; no ranking change fixes that, so look for the unmarked pair first.
- **Planted controls.** Mix answers with known verdicts (each checked against the source before use) into the judge's
  batch under opaque ids. If the judge gets more than one in ten wrong, conclude nothing from that run.
- **Deterministic measures first.** Hit@k, mean reciprocal rank and required-string checks are primary; answer-level
  verdicts come second, because they are the noisy layer. Published comparisons report evaluation biases next to
  failure modes for this reason [S1].
- **Fix the depth you measure at.** A retrieval failure is "the right chunk is not in the first k"; the vendor study of
  contextual retrieval reports its gains as a top-20 failure rate [S2]. Pick k to match what the reader really sees.

## Noise floor and statistics
- **Measure the noise floor.** Re-read the same questions with the same code and count the verdicts that flip. A
  single-run difference smaller than that floor is not a result.
- **Intervals, not points.** Report every rate with a Wilson interval; percentile bootstraps under-cover at small or
  sparse samples.
- **Paired comparison.** Compare before and after on the same questions, and count negative flips (right before, wrong
  after). Cap them in the gate, so an average gain cannot hide new failures.
- **Several sets.** A ranking change that helps one set can hurt another. Keep a dev set, a confirm set and a held-out
  set, and require a change to hold on all of them before it ships.

## Gates that work
- **Every gate names its action in advance:** "build X if metric M on the confirm half is below T", and what happens if
  it fails. A gate that can only pass is not a gate.
- **A validity gate comes first:** the harness reproduces the committed baseline, the judge passes its planted controls
  and the label audit passes. If any fails, nothing else is concluded.
- **A new warning or flag ships only with measured precision.** A warning that misfires trains readers to skip it,
  including the times it is right.
- **A build ships only if** the target metric improves beyond the noise floor on the confirm half, negative flips stay
  within the cap, the held-out floors still pass and latency stays within its budget on a quiet machine.

## Sources
- [S1] RAG vs. GraphRAG: A Systematic Evaluation and Key Insights · https://arxiv.org/abs/2502.11371 · fetched 2026-10-17
- [S2] Anthropic, Contextual Retrieval in AI Systems · https://www.anthropic.com/news/contextual-retrieval · fetched 2026-10-17
