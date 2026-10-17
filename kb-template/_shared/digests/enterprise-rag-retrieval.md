---
title: Digest, enterprise RAG retrieval patterns
domain: _shared
status: active
---
# Enterprise RAG retrieval: hybrid search, fusion, rerank and permission filters

Patterns measured on synthetic document sets and on public retrieval benchmarks. Read before
choosing how keyword search, embeddings, reranking and a graph combine when every user sees a different slice of the
corpus. The permission model itself is in `enterprise-rag-architecture`.

## Route by question class first
- **A cheap router beats any single strategy.** Classes that held up: identifier lookup (exact business-key fast path
  plus hybrid), single fact (hybrid), relationship (entity linking, then typed reach over schema relations; hubs are
  reached but never expanded), trace (deterministic walks over known chains), aggregate (typed counts that bind every
  predicate or refuse), global (map-reduce over a text-free partition of readable evidence). As-of is orthogonal.
- **Typed results rank ahead of graph-expansion results.** Ranking expansion entities first drags relationship
  recall below plain hybrid; putting typed walks and counts first recovers it [M4].
- **Evaluate the router separately from answers;** a correct class with a wrong walk still fails the user.

## Hybrid search and fusion
- **Run BM25 and dense retrieval in parallel and fuse by weighted reciprocal rank fusion.** The common rank constant
  is 60, the documented default of OpenSearch's RRF processor [S1]. Start with the vector list weighted highest, BM25
  next, graph lowest, and tune per class on a dev split, never on the test split.
- **RRF is the zero-training default, not the optimum.** A fusion study found RRF sensitive to its constant and a
  tuned convex combination better in and out of domain once a few labelled queries exist [S2].
- **Deduplicate on document and span, then diversify (MMR) before the context packer.** Watch MMR placement: a plain
  hybrid plus cross-encoder beat a fuller pipeline by a few points of nDCG, and MMR after the reranker is the likely
  cause [M5].

## Rerank
- **Rerank only after the permission filter.** A reranker is a model input; it must never see text the caller cannot read.
- **The reranker's value depends on the first stage.** With a weak hashing embedder a small cross-encoder adds a
  lot; with a real embedder it added about a point of nDCG@10 on a public finance-QA set [M5]. Measure before paying latency.
- **Multi-hop needs more than a better reranker.** A chained retrieval step plus a multilingual cross-encoder raised
  held-out recall@5 by more than ten points on 2WikiMultiHopQA and a few points on MuSiQue [M6]. A small cross-encoder
  closed a multi-hop shortfall of up to about six nDCG@10 points [M6], at about half again the p95 latency.
- **Embedder upgrades are measurable:** Qwen3-Embedding-0.6B beat bge-small-en-v1.5 by several points of nDCG@10 on FiQA [M7];
  dropping the documented query prefix cost about two points on SciFact, close to the published effect [M7].

## Lexical scoring under permissions
- **BM25 statistics must come from rows the caller can read.** Corpus-wide document frequency, document count and
  average length let hidden documents change a visible score, a channel id-level leak checks cannot see.
- **Engine document-level security does not fix it.** Elastic documents that document-level security does not affect
  the global index statistics used for scoring [S5]; shard-level statistics in OpenSearch behave the same way, and a
  production-adapter twin shows thousands of non-interference differences until scoring uses visible rows only [M2].
- **The fix:** choose candidates under the ACL filter with a statistics-free proxy score, fetch visible N, length and
  document frequency in one filtered request, then re-score with BM25. Trade-off: recall is capped at the proxy's
  candidate pool. Postgres `ts_rank_cd` is document-local and safe but weak.
- **Visible-only BM25 is not a quality tax.** It was non-inferior to index-wide statistics (a difference
  indistinguishable from zero, its interval within a fraction of a point) [M1], reproduced the published SciFact BM25
  score, and beat `ts_rank_cd` by more than ten points of nDCG@10 on FiQA [M1].
- **Tokenise identifiers yourself.** The stock Postgres parser emits a hyphenated identifier's numeric tail as a
  signed integer token [S8], so a ticket key splits apart; store a tsvector built from the application tokenizer and
  keep an exact identifier lookup leg.

## Filtered vector search
- **Put the filter inside the vector query:** `acl_key = ANY($1)` in the same Postgres statement, a terms filter
  inside the OpenSearch k-NN filter, never a post-filter.
- **Approximate indexes filter after the scan.** pgvector's README: HNSW at the default `ef_search` of 40 [S3] with
  a filter matching 10% of rows returns about 4 rows; iterative index scans (from version 0.8.0) scan further [S3].
- **Let the number of rows the caller can see choose the method:** brute-force exact search for a small visible set,
  an iterative or filter-aware index scan for a medium one, a plain index scan when almost everything is visible. A
  filtered-search study saw the Postgres planner pick the index even when a sequential exact scan was as fast and
  returned every true neighbour [S4].
- **Measure recall by selectivity bucket.** On a large generated corpus, exact fallback gave perfect recall when a
  caller could see about one percent of it or less, while approximate recall was near one half when a tenth or more
  was visible, on an old pgvector without iterative scan [M3].
- **Record each arm's query plan before declaring "no effect".** Index-tuning arms that give identical recall may
  never use the index at all.
- **Large allowed sets hit engine limits:** OpenSearch's terms query defaults to 65,536 terms [S6]; split the list
  or filter on the complement, and test past the limit [M8].

## Graph expansion
- **Use personalised PageRank on the authorised and trusted subgraph only:** asserted facts valid at the as-of
  time, proposed LLM edges excluded, a hub penalty on degree. Untrusted structural writes can reroute PageRank mass
  while every cited record stays authentic; the published fix recomputes selection on the trusted subgraph [S7].
- **Typed traversal first when the path is known;** PageRank is the fallback for unknown paths.

## Abstention and answering
- **Let structure decide when to answer.** Answer from the pack directly when it holds a typed path or a count tied
  to the question. An identifier match is not enough unless the other words of the question are covered too, and when
  the walk the question asked for comes back empty, decline, even if expansion surfaced paths about something else.
- **Otherwise use a coverage threshold calibrated on dev,** and expect it to fail on near-miss unanswerables (the
  topic exists, the fact does not); a model's own insufficiency signal in generate mode covers them better.
- **No model call in evidence-pack mode.** A global route that quietly calls the LLM (for example on any query
  containing "across") also escapes billing; route, bill and claim-check every call.

## Measurements
- [M1] Visible-only BM25 vs index-wide statistics and vs ts_rank_cd · corpus SciFact, FiQA, NFCorpus plus a synthetic multi-department document set · n=public test query sets of hundreds of queries · tier R0
- [M2] Non-interference differences from engine shard statistics on a production-adapter twin · corpus a synthetic multi-department document set · n=all strategies, several personas · tier R0
- [M3] Selective-ACL vector recall@10 by visibility bucket, hashing embedder · corpus a large generated enterprise corpus · n=4 buckets · tier R0
- [M4] Typed-first ranking vs expansion-first on relationship recall · corpus a synthetic multi-department document set, dev split · n=tens of dev questions · tier R0
- [M5] Cross-encoder gain with hashing vs real embedder, and MMR placement · corpus FiQA · n=public test queries · tier R0
- [M6] Chained retrieval plus cross-encoder on held-out multi-hop sets; reference-pipeline shortfall and latency · corpus 2WikiMultiHopQA, MuSiQue · n=several hundred held-out questions per set · tier R0
- [M7] Embedder swap and query-prefix ablation · corpus FiQA, SciFact · n=public test queries · tier R0
- [M8] Allowed-key list beyond the default terms limit · corpus contract test fixture · n=more keys than the default limit · tier R0

## Sources
- [S1] OpenSearch score ranker processor (RRF) · https://docs.opensearch.org/latest/search-plugins/search-pipelines/score-ranker-processor/ · fetched 2026-10-17
- [S2] An Analysis of Fusion Functions for Hybrid Retrieval · https://arxiv.org/abs/2210.11934 · fetched 2026-10-17
- [S3] pgvector README, filtering and iterative index scans · https://github.com/pgvector/pgvector · fetched 2026-10-17
- [S4] Filtered ANN Search in Vector Databases · https://arxiv.org/abs/2602.11443 · fetched 2026-10-17
- [S5] Elastic, controlling access at document and field level (limitations) · https://www.elastic.co/docs/deploy-manage/users-roles/cluster-or-deployment-auth/controlling-access-at-document-field-level · fetched 2026-10-17
- [S6] OpenSearch terms query · https://docs.opensearch.org/latest/query-dsl/term/terms/ · fetched 2026-10-17
- [S7] Selection Integrity for LLM Graph Memory · https://arxiv.org/abs/2606.12290 · fetched 2026-10-17
- [S8] PostgreSQL text search parsers · https://www.postgresql.org/docs/current/textsearch-parsers.html · fetched 2026-10-17
