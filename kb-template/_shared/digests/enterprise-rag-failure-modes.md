---
title: Digest, enterprise RAG failure modes and gotchas
domain: _shared
status: active
---
# Enterprise RAG failure modes: gotchas from permission-filtered search

Defects that permission-filtered retrieval runs into, each stated as a vendor-documented behaviour or a fact
anyone can reproduce. Read before shipping permission-filtered search on Postgres, OpenSearch or a graph store, and
when a leak test, a latency number or an eval result looks too good. Design answers live in the other
`enterprise-rag-*` digests.

## Permission side channels
- **Relevance statistics over hidden rows.** Elasticsearch document-level security leaves the global statistics used
  for scoring untouched [S1]; any engine BM25 computed over the whole index or shard lets hidden documents move a
  visible score. Only a non-interference twin test sees it; an id-level leak check never will.
- **Tie order follows hidden history.** Equal-score results sorted by insertion order reveal hidden creation order;
  break ties on visible keys (score, degree, name, id).
- **Existence oracles.** A visible edge to a restricted entity, a count that includes hidden items, a missing-link
  report that states absence as fact, or a "not found" that differs from "forbidden" each reveal hidden data. Return
  identical errors for hidden and missing, and phrase missing-link reports as judged on what the caller can read.
- **Deny unmasking.** Clipping a user's groups to a gateway's ceiling, then evaluating, drops the very group a deny
  rule targets. Intersect allowed sets instead.
- **Shadow copies.** Saved answers, stored asynchronous task results, caches and eval datasets keep content after a
  revocation or purge unless each read re-authorises and each purge reaches them.
- **Replay across replicas.** A one-time assertion remembered per process can be replayed once on every other
  replica; keep nonces in the shared catalog and fail closed when it is unavailable.

## Search engine and database behaviour
- **Filtered HNSW is approximate.** pgvector applies filters after the index scan, so a selective filter returns
  far fewer rows than asked; iterative scans or an exact path fix it, and disabling index scans per transaction
  forces exact search for recall checks [S2]. Planners sometimes ignore index settings, so record each arm's plan.
- **Delete-by-query with conflicts set to proceed skips documents that changed mid-run** [S3]. On a revocation that
  leaves stale chunks at the wider ACL; abort on conflict, retry, and fail closed.
- **Postgres text search splits identifiers:** the default parser reads a hyphen followed by digits as a signed
  integer token [S4], so ticket and requirement keys break apart. Index a tsvector built from your own tokenizer.
- **Large allowed-key lists hit terms limits:** OpenSearch's terms query defaults to 65,536 terms [S5].
- **Graph extensions may bypass row-level security.** A Postgres graph extension's variable-length and shortest-path
  traversal read tables directly and ignored policies until an upstream fix added an enforcement setting [S6]. Test
  every traversal form under a non-owner role without the bypass attribute.
- **Refresh on every bulk write is slow:** forcing a refresh after each bulk request crawls; refreshing only when a
  write narrows access is dozens of times faster [M5].
- **Schema migration on every connect deadlocks.** An unconditional `ALTER TABLE` at connection time takes exclusive
  locks and can deadlock live searches under modest concurrency; check the catalog before altering [M6].
- **Shared clusters run out of connections** under parallel test steps; give each heavy step its own pool budget.

## Embedding, reranking and model serving
- **Same text, different vector.** A local embedding server that reuses the previous request's cached prefix can make
  identical text embed differently (small differences, around the fourth decimal place) depending on the request
  before it; turning prompt caching off may not stop it, while a one-token flush request before each embedding does,
  with flush pairs serialised across processes [M1].
- **Converted models drift.** A GGUF conversion of a cross-encoder can fail a score-parity test that the ONNX
  export passes [M2]; parity-test every converted model against its reference.
- **Thread oversubscription.** Default ONNX runtime threading under concurrent searches wastes CPU; capping each
  embedder at two threads cut per-search CPU by roughly an order of magnitude with identical results [M3].
- **Query-time entity linking dominates latency at scale:** on a large generated corpus it took most of each search,
  because one- and two-character fragments match most name rows; use one bulk indexed name lookup per query and
  skip linking for strategies that do not use it [M4].
- **Native libraries can be blocked by application control** on managed Windows machines (deep-learning runtimes,
  compiled database drivers). Prefer ONNX models and pure-Python driver modes (psycopg supports `PSYCOPG_IMPL=python`).
- **OpenAI-compatible local servers differ:** some read `max_tokens` and ignore `max_completion_tokens`, reasoning
  may be on by default, and some models emit inline thinking blocks that must be stripped before citation checks.

## Ingest and parsing
- **Type coercion fails open.** YAML reads a zero-padded key as an integer, so a narrowing override can match nothing;
  `str.isdigit` accepts superscript digits (use `isdecimal`); a nested-document converter that walks children twice
  grows exponentially with depth. Cap depth, compute lazily, and isolate failures per item.
- **Neutralisers miss Unicode tricks:** full-width angle brackets become real ones after NFKC unless you normalise
  before escaping; a URL scheme glued to a non-ASCII letter slips past a word boundary; stripping every zero-width
  joiner breaks Persian text, so keep joiners between non-ASCII letters.
- **Secrets leak through config echoes.** An evidence pack that exports settings echoes them, and a password
  containing `#` parses as a URL fragment and splits into host and port. Mask declared secret fields and reduce DSNs to scheme and host.
- **Revoked keys survive reloads** keyed on file size and modification time; reload on a content hash, and fail
  closed on a broken file. Chain audit logs with a keyed MAC plus an externally anchored head.

## Test and harness traps
- **Local suites that skip database tests when a connection string is unset** prove nothing about the SQL.
- **Piping a test run through `tail` hides its exit code;** read the code, not the summary.
- **Editable installs in worktrees import the main checkout** unless the worktree's source path comes first.
- **Package managers that hardlink files into several virtualenvs** turn an edit in one into an edit in all.
- **Hash-seed dependence:** set iteration order can change a chunk's lexical score across processes, by a small but
  real margin of about two hundredths [M7]; compare outputs across two processes with a pinned seed.
- **Emulators are not production:** emulator latency is never a performance claim, and the vendor README beats forum
  posts on what an emulator supports.
- **Webhooks lag:** Microsoft Graph lists a maximum notification latency of 6 hours for drive items [S7]; poll.

## Measurements
- [M1] Embedding drift from cached-prefix reuse in a local embedding server, and the flush fix (determinism from roughly nine in ten to all) · corpus a synthetic multi-department document set · n=all chunks re-embedded across restarts · tier R0
- [M2] Cross-encoder score parity, GGUF conversion vs ONNX export · corpus public retrieval benchmark pairs · n=2 conversions · tier R0
- [M3] Per-search CPU and wall time with explicit embedder threads, identical ranked ids · corpus a synthetic multi-department document set · n=all strategies · tier R0
- [M4] Share of search latency in query-time entity linking, most of each search · corpus a large generated enterprise corpus · n=traced searches per strategy · tier R0
- [M5] Write throughput before and after refresh only on narrowing writes · corpus contract test documents · n=a few hundred documents per run · tier R0
- [M6] Schema-init lock deadlock under concurrent search · corpus a generated enterprise · n=one concurrency level · tier R0
- [M7] Lexical score for one chunk across two processes · corpus a synthetic multi-department document set · n=2 processes · tier R0

## Sources
- [S1] Elastic, document level security limitations · https://www.elastic.co/docs/deploy-manage/users-roles/cluster-or-deployment-auth/controlling-access-at-document-field-level · fetched 2026-10-17
- [S2] pgvector README · https://github.com/pgvector/pgvector · fetched 2026-10-17
- [S3] OpenSearch delete by query · https://docs.opensearch.org/latest/api-reference/document-apis/delete-by-query/ · fetched 2026-10-17
- [S4] PostgreSQL text search parsers · https://www.postgresql.org/docs/current/textsearch-parsers.html · fetched 2026-10-17
- [S5] OpenSearch terms query · https://docs.opensearch.org/latest/query-dsl/term/terms/ · fetched 2026-10-17
- [S6] Apache AGE PR, RLS in traversal · https://github.com/apache/age/pull/2561 · fetched 2026-10-17
- [S7] Microsoft Graph change notifications overview · https://learn.microsoft.com/en-us/graph/change-notifications-overview · fetched 2026-10-17
