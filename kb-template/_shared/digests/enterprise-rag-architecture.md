---
title: Digest, enterprise RAG architecture
domain: _shared
status: active
---
# Enterprise RAG architecture: permission-safe retrieval and derived knowledge

Lessons for retrieval systems where every user sees a different slice of the documents, from measurements on
synthetic multi-department document sets and from public studies. Read before building RAG for several
permission groups. Companions: the other `enterprise-rag-*` digests.

## The one invariant
- **Compute the caller's allowed set once per request and pass it explicitly into every read.** No ambient authority,
  no read path callable without it. Lexical, vector and graph queries filter inside the store's own query.
- **Authorise before any learned component sees text.** Retrieve-then-filter feeds forbidden text to candidate lists,
  rerankers and prompts; a study measured unauthorised context in 86.1% of retrieve-then-filter queries [S1].
- **Pre-filtering costs no recall; its gain is safety.** A matched pre-filter baseline equals retrieve-then-filter
  on evidence recall (no meaningful difference) while retrieve-then-filter exposes forbidden documents in about a quarter of cells [M1].

## The permission model
- **Allow in conjunctive normal form plus a deny list.** Each clause is a set of tokens (user, group, role); the
  caller needs one token from every clause. A derived fact concatenates its sources' clauses (most restrictive).
  An empty allow list means nobody, never everybody.
- **Store an ACL key on every chunk and fact.** Hash the canonical ACL, evaluate each distinct set once per principal
  and ACL version, cache the allowed keys, extend the cache incrementally when a revocation creates a new set.
- **Deny entries break monotonicity.** Trimming someone's group list before evaluation can switch off a deny that
  targeted that very group, so compute each principal's allowed set and intersect them. Unreadable membership: refuse.
- **The directory is authoritative.** Resolve groups at query time; unioning token group claims with directory groups
  makes every revocation wait for token expiry. Normalise principal tokens and scope document ids by tenant and source.

## Agents acting for a user
- **An agent working for a user reaches only what both may reach:** keep the overlap of the user's set, the agent's
  set, and the user's groups capped at the agent's ceiling. Through a read-only agent, an administrator is read-only.
- **When the token is unclear, say no:** an unknown agent, a broken or chained actor claim, or two agents in one
  token ends the request. A service-wide key carries no user, so it cannot be narrowed this way.
- **Identity never appears in an LLM-visible schema;** the server derives it from the credential.
- **Show each caller only the tools it may run, and check again on every call.** In a published test [S2], checks
  only inside the tool body revealed forbidden tools in 21.1% of attempts, filtered listings in none of 720 [S2],
  and scripted clients could still call tools they were not shown.

## Derived artifacts carry permissions too
Summaries, merged entities, counts, paths, sensitivity labels and cached answers are where document-level
permission filtering stops being enough. The generic pattern:
- **Entities hold identity only** (type plus business key); names and properties are separate facts with their own
  ACL key, so a merge can never widen visibility. An entity is visible only through a fact the caller can read, and an
  edge only when both endpoints are visible through their own facts.
- **Never persist summaries built from mixed ACLs.** Build global answers at query time over readable evidence, cache
  under a hash of the evidence set, re-check every source ACL on read. Stored summaries, hierarchy edges and scores are
  an attack surface too: editing 0.016% of them gave 88-94% attack success on two GraphRAG systems [S3].
- **Aggregates bind only visible items and every predicate in the question,** or refuse.
- **Answer sensitivity is the highest label among the visible items that built it,** read through the allowed set.
- **Saved answers and stored task results are shadow copies:** re-authorise on every read, expire them, purge them.
- **Every cache key includes identity.** A summary cache keyed by chunk ids and an author-chosen version is shared
  across tenants and goes stale after edits; key on tenant, chunk id and a hash of the text [M2].

## Graph construction and service shape
- **Ontology first, systems of record next, the LLM last.** Deterministic mappings build the backbone; the LLM only
  proposes schema-legal facts with a verbatim evidence quote. Proposals are hidden by default, rejections logged with
  a reason code, and a human rejection survives re-extraction. Typed query templates only on the request path.
- **Every fact carries provenance and two clocks** (source, version, extractor and prompt hash, evidence span, valid
  and recorded time). Updates close facts; erasure purges them.
- **Default output is an evidence pack** (cited passages, typed paths, bound counts) so the caller's own model,
  content filters and cost accounting still apply; a generate mode adds claim-level citation checks and abstention.
- **One operation registry generates REST, MCP tools and agent-to-agent skills,** so each check lives once.
- **Give the visibility rule one home.** Copies hand-written across Python, SQL and Cypher drift apart, and a review
  is how the drift is usually found. Add differential property tests across adapters and an architecture test that freezes
  the request-path calls allowed to read unfiltered data; give request code a reader port that always takes the set.
- **Engine-side enforcement is the second wall.** Row-level security under a non-owner role catches an app bug, but
  test every query form: a Postgres graph extension's path traversal skipped row-level security until a fix [S4].
- **Timeouts on every client, an end-to-end deadline,** and caches and leases in the request context.

## What holds up and what does not
- **Holds up:** filtering inside every store; per-fact ACLs; query-time global summaries; typed routing for
  relationship and traceability questions where the domain has explicit structure [M3]; evidence packs by default.
- **Does not:** graph routing on a domain with weak explicit structure [M3]; offline lexical abstention on near-miss
  unanswerable questions [M4]; trusting a planted leak suite alone, since real leaks tend to take shapes nobody
  planted [M5].
- **Process:** survey current published work before designing the core, or the design lands below the state of the
  art; an adversarial review of the design before coding predicts many real defects, mostly in permission semantics.

## Stack choices and licences
| Component | Role | Licence |
|---|---|---|
| Postgres with pgvector | catalog, graph tables, vectors, full text | PostgreSQL-style permissive [S5] |
| OpenSearch | chunk index for large estates | Apache-2.0 [S6] |
| Elasticsearch | avoid embedding it | AGPL-3.0, SSPL or Elastic License 2.0 [S7] |
| Neo4j Community | graph server | GPL-3.0: separate server, never bundled [S8] |
| fastembed, bge-small-en-v1.5 | CPU ONNX embedder | Apache-2.0, MIT [S9] [S10] |
| bge-reranker-v2-m3, ms-marco MiniLM-L6-v2 | cross-encoder rerankers | Apache-2.0 [S11] [S12] |
| Qwen3-Embedding-0.6B | stronger open embedder | Apache-2.0 [S13] |
| Docling, Presidio | parsing, PII detection | MIT [S14] [S16] |
| PyMuPDF | avoid: copyleft | AGPL-3.0 or commercial [S15] |
| LightRAG | graph-RAG baseline arm | MIT [S17] |

## Measurements
- [M1] Evidence recall and exposure, matched pre-filter vs retrieve-then-filter · corpus a synthetic multi-department document set, several personas · n=a few dozen test questions · tier R0
- [M2] Summary-cache key defect caught by a planted cache probe · corpus a synthetic multi-department document set · n=2 corpora · tier R0
- [M3] Graph-routing recall lift on relationship and trace questions: about +0.5 (interval excludes zero) with explicit structure, about +0.2 (includes zero) without · corpus a synthetic multi-department document set · n=about a dozen questions per arm · tier R0
- [M4] Offline lexical abstention on near-miss unanswerables: most refused in one domain, under a third in the other · corpus a synthetic multi-department document set · n=about ten questions per arm · tier R0
- [M5] Name linking pooled across ACL keys: thousands of non-interference differences before the fix, none after; group clipping found by review · corpus a generated enterprise with skewed ACLs · n=about a thousand sampled cells · tier R0

## Sources
- [S1] Authorization-First Retrieval · https://aclanthology.org/2026.trustnlp-main.15/ · fetched 2026-10-17
- [S2] Zero-Trust Authorization for Enterprise MCP · https://arxiv.org/abs/2609.22573 · fetched 2026-10-17
- [S3] Hop-Decayed Influence (GraphRAG) · https://arxiv.org/abs/2610.02373 · fetched 2026-10-17
- [S4] Apache AGE PR, RLS in traversal · https://github.com/apache/age/pull/2561 · fetched 2026-10-17
- [S5] pgvector licence · https://github.com/pgvector/pgvector/blob/master/LICENSE · fetched 2026-10-17
- [S6] OpenSearch licence · https://github.com/opensearch-project/OpenSearch · fetched 2026-10-17
- [S7] Elasticsearch licence · https://github.com/elastic/elasticsearch/blob/main/LICENSE.txt · fetched 2026-10-17
- [S8] Neo4j licence · https://github.com/neo4j/neo4j · fetched 2026-10-17
- [S9] fastembed · https://pypi.org/project/fastembed/ · fetched 2026-10-17
- [S10] bge-small-en-v1.5 · https://huggingface.co/BAAI/bge-small-en-v1.5 · fetched 2026-10-17
- [S11] bge-reranker-v2-m3 · https://huggingface.co/BAAI/bge-reranker-v2-m3 · fetched 2026-10-17
- [S12] ms-marco-MiniLM-L6-v2 · https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2 · fetched 2026-10-17
- [S13] Qwen3-Embedding-0.6B · https://huggingface.co/Qwen/Qwen3-Embedding-0.6B · fetched 2026-10-17
- [S14] Docling · https://pypi.org/project/docling/ · fetched 2026-10-17
- [S15] PyMuPDF · https://pypi.org/project/PyMuPDF/ · fetched 2026-10-17
- [S16] presidio-analyzer · https://pypi.org/project/presidio-analyzer/ · fetched 2026-10-17
- [S17] LightRAG licence · https://github.com/HKUDS/LightRAG · fetched 2026-10-17
