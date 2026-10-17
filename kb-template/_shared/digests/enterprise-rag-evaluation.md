---
title: Digest, enterprise RAG evaluation and leak testing
domain: _shared
status: active
---
# Enterprise RAG evaluation: leak testing, scoring traps and measured results

How a permission-aware retrieval system can be measured, what breaks the measurements, and what honest numbers
look like. Read before claiming that a permissioned assistant is accurate or that it never leaks. General method
(pre-registration, noise floors, blind labels) is in `retrieval-eval-method`; this note adds the permission-specific
parts.

## Two axes, never one score
- **Report utility and safety separately.** Utility: recall@k, MRR, nDCG, answer correctness, abstention accuracy
  and over-refusal, computed inside each persona's visible set. Safety: leaks, non-interference differences,
  mutants detected. A composite hides the axis that failed.
- **Judge-free metrics first.** Deterministic checks (recall, exact values, citation-id match, abstention flags,
  leak oracle) carry the gate; an LLM judge stays off until it is calibrated against human labels.

## Non-interference is the release gate
- **Twin test:** for each persona build a second store holding only that persona's visible items, on the same
  backend, under the same tenant so ids match. Every query and strategy must return byte-identical output: ids,
  ranks, scores to many decimals, text, citations, entities, paths, summaries and counts.
- **It catches what id checks cannot.** Corpus statistics (BM25 document frequency over hidden rows), tie order
  following hidden creation order, and counts that include hidden items all change a visible output without
  returning a forbidden id.
- **Run the twins on production adapters,** not only the in-memory reference: engine shard statistics leak only there.
- **Sample non-interference at scale** on a generated enterprise with skewed ACLs and nested groups. Real leaks tend
  to come from shapes a planted suite never contains, such as entity names pooled across ACL keys for linking, or
  group clipping that unmasks deny rules.
- **Give the twin its own database cluster.** Shared connection pools run out, mutants error, and a combiner can
  report them as undetected. An errored mutant is an invalid run, never a pass or a fail.

## Mutation-test the leak suite
- **One mutant per enforcement call site** (no ACL predicate on the vector query, post-filter after top-k, reranker
  fed unfiltered candidates, cache key without identity, deny ignored, group lookup failing open, saved answers
  surviving purge). The suite must detect every one, over every strategy [M1].
- **Run every strategy.** Some mutants are reachable only through the graph and global routes and survive a run
  limited to hybrid search.
- **Avoid equivalent mutants.** On mapped data every edge endpoint usually has its own mention, so an "entity visible
  through an edge" mutant changes nothing; plant the condition directly (an edge whose hidden end has no own fact).
- **Patch every binding:** a module-level patch misses a function imported by name elsewhere. An opt-in feature's
  mutant must be inert at the default setting, not merely undetected.
- **Instrument every boundary:** retrieval candidates, each graph hop, reranker input, prompt or evidence pack,
  citations, answer text, logs and caches, saved answers, status endpoints. In generate mode record every prompt and
  check it for sentences that only forbidden documents contain.

## Zero leaks is a bound, not a fact
- **Zero events in n independent cells bounds the leak rate at about three divided by n** at the usual confidence
  level. Count distinct persona and query cells that exercise the enforcement code, not repeated runs.
- **Hidden and nonexistent must look the same.** Hidden and fabricated citation ids must return byte-identical errors
  on every surface; probe thousands of pairs and expect none distinguishable [M8].

## Scoring traps that inflated results
- **Bare numbers match digits inside ids.** A count nearly three times the gold value can pass [M2] when an entity
  id contains the gold digits; match numbers only in answer text and bound counts, and exclude keys the question names.
- **Substring credit:** a short number matched inside a longer one (six days inside sixteen days); compare whole tokens.
- **Answer correctness that credits facts sitting in retrieved passages** cannot tell a good answer from an abstention
  over good evidence; score the answer text alone.
- **A report-level pass flag that ignores the baseline** prints "passed" for a run with leaks; read the exit code.

## Splits, power and nulls
- **Dev for tuning, test for gates,** thresholds written before results and never re-tuned on test. A golden set edited
  by the system under test, or after anyone saw results, is invalid: freeze it and keep a held-out half.
- **Synthetic corpora and gold from one generator are circular;** add an independently authored question set.
- **Small sets cannot pass a strict gate:** with about ten unanswerable questions, even a perfect score has a Wilson
  lower bound under a 0.8 bar [M6].
- **Use paired, question-clustered intervals** and plan the sample size before running [S2]; report pass^k across
  repeated runs for reliability [S1].
- **Two identical runs of a deterministic pipeline always agree,** so they make a useless null. Shuffle signs or
  split the per-question paired differences instead, and fix the interpreter's hash seed, which can move lexical scores.
- **Reproduce a published baseline first** (a positive control) so the harness itself is trusted [M9].

## Measured results
- **Graph routing:** a large, significant recall gain on relationship and trace questions in a domain with explicit
  structure, and no demonstrable gain in a domain without it [M3].
- **Abstention:** offline lexical abstention handles near-miss unanswerable questions poorly; a small local
  open-weight model in generate mode refused every unanswerable test question, at the cost of some over-refusal [M4].
- **A real model changes the verifier:** list numbers read as claims, numbers checked against one sentence only and
  typed results missing from the prompt tend to surface on the first live run; fixing them raises claim support [M5].
- **Injection envelopes help weak hosts only:** labelled envelopes and datamarking cut attack success on a small local
  host, while a frontier host ignored every plant, so the test has no power there [M7].

## Measurements
- [M1] Leak suite: no leaks, no non-interference differences, no errors, every per-call-site mutant detected over every strategy, also on three production backends · corpus a synthetic multi-department document set · n=all strategies and mutants, several personas · tier R0
- [M2] Scorer defect: digits inside ids credited as answers; results scored before the fix are invalid · corpus a synthetic multi-department document set · n=3 confirmed questions · tier R0
- [M3] Recall lift about +0.5 with an interval excluding zero vs about +0.2 with an interval including zero · corpus a synthetic multi-department document set · n=about a dozen questions per arm · tier R0
- [M4] Every unanswerable question refused in both domains; roughly a tenth to a fifth of answerable questions over-refused; claim support above 0.9 · corpus a synthetic multi-department document set · n=a few dozen test questions per domain · tier R0
- [M5] First live run vs after the verifier fixes: text correctness up by about 0.2, claim support from under 0.8 to near 1 · corpus a synthetic multi-department document set · n=a few dozen test questions · tier R0
- [M6] Wilson lower bounds for perfect scores on small question sets · corpus unanswerable test questions · n=about ten per set · tier R0
- [M7] Attack success roughly a third naive, under a fifth with a labelled envelope and lower again datamarked, on a small local host; none on a frontier host · corpus planted payload trials · n=over a hundred trials per arm · tier R0
- [M8] Hidden vs fabricated citation ids over three API surfaces, no distinguishable pair · corpus a synthetic multi-department document set · n=tens of thousands of probes · tier R0
- [M9] Positive controls: SciFact BM25 and a small dense embedder each within about a point of the published score · corpus SciFact · n=public test queries · tier R1

## Sources
- [S1] tau-bench, the pass^k reliability metric · https://arxiv.org/abs/2406.12045 · fetched 2026-10-17
- [S2] Adding Error Bars to Evals · https://arxiv.org/abs/2411.00640 · fetched 2026-10-17
