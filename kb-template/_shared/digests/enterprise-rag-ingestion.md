---
title: Digest, enterprise RAG ingestion and chunking
domain: _shared
status: active
---
# Enterprise RAG ingestion: connectors, revocation, chunking and scanning

What matters when getting documents into a permission-aware index: connector sync that fails
closed, chunking, sensitive-data and injection scanning, and re-embedding. Read before writing a connector or an
ingest pipeline for permissioned sources. Companions: the other `enterprise-rag-*` digests.

## Pipeline shape
- **Four change types:** document, record, delete, ACL update. An ACL update rewrites the ACL key on chunks and facts
  without re-embedding, so revocation is cheap and fast [M8]. A new version retires facts it no longer asserts.
- **Delete means physical purge:** chunks, vectors, facts, orphan entities, caches and saved answers that cite the
  document; then a purge audit queries every store for the document id and must find nothing.

## Connectors, file permissions and revocation
- **Polling is the guarantee; webhooks are an optimisation.** Revoked file permissions reach the search index only as
  fast as the next sync, so do not rely on webhooks alone: Microsoft Graph documents a maximum notification latency of
  6 hours for drive items and an unknown latency for group changes [S1]. Poll every few minutes; sync ACLs faster than content.
- **Two loops per source:** document permissions, and group membership in its own table. Chunks carry principal
  references; groups expand at query time, so a membership change needs no re-index.
- **Absence proves nothing unless the listing is complete.** A quietly partial listing (an incomplete-search flag,
  an empty mount point, a row cap) purges live documents unless reconciliation requires the connector to assert
  completeness [M6].
- **One bad item must not darken its source.** Count strikes per item only in passes where other items answered; an
  outage where everything fails alike is not a bad item. After repeated strikes, close that item and move on.
- **Leases and deadlines.** A per-source lease (compare-and-set, expiry on the database clock, a fencing token checked
  on every store write) stops two runners syncing one source. Give every source a deadline and check freshness for
  every source first, including sources no longer configured; close stale sources to nobody. An empty connector
  configuration is an error, not a green run.
- **Narrow first.** When a new version narrows the ACL, apply old-intersect-new before parsing, or a parser or
  embedder failure leaves the old text readable at the wider ACL; narrow stored history too.
- **Re-offer failed extraction** once a probe of the dependency that actually failed (often the LLM, not the
  embedder) answers; give up loudly after repeated failures while it answers.
- **Keyset paging, not offset paging,** for full listings: one edit during an offset-paged pass can purge an unchanged
  item. Skip symlinks, junctions and mount points in every file source; check every redirect hop against private and
  metadata addresses; pin the resolved address to stop DNS rebinding.

## Parsing and chunking
- **Parsing:** Docling (MIT) handles Office, PDF and HTML with layout and tables [S5]; keep PyMuPDF out unless its
  AGPL or commercial licence is cleared [S6]. Cap archive size, file size and YAML alias expansion.
- **Structure-aware chunks of a few hundred tokens with a small overlap,** each embedded with a deterministic header:
  title, heading path, document type, key identifiers. Tables become their own chunks with the header row repeated.
- **Content-aware chunking wins, but the best method varies by domain:** a study of 36 methods [S3] across six
  domains found paragraph grouping best overall and fixed-size character splits worst. Test on your own questions.
- **Contextual retrieval is worth it for hard subsets:** LLM-written chunk context cut top-20 retrieval failures [S2]
  by 35%, by 49% with contextual BM25 and by 67% with reranking [S2]; under 200,000 tokens, use the prompt instead [S2].
- **Embedders truncate silently.** Against an embedder limit of a couple of thousand tokens, about one code chunk in
  twenty was over it [M1], and the share of tokens dropped was far larger than that chunk share; API specs and wiki pages lost less but still lost content. Character-based token
  estimates undercounted real tokens by a factor of up to about three [M2]. Take the limit from the live embedder.

## Sensitive data at ingest
- **Card numbers: checksum plus issuer prefix plus context, then quarantine the whole chunk** and keep only a salted hash,
  document id and offset, so the vector store, graph and logs stay out of payment-card scope.
- **The checksum alone floods.** Random 13-19 digit identifiers pass a mod-10 checksum about one time in ten [M5];
  a checksum-only test flags hundreds of barcodes, and version-control hashes as cards too [M5].
- **Exemptions by token shape are paddable;** require identifier context instead. In overlap resolution a card
  number outranks a secret, or a card inside a password field escapes quarantine.
- **Scan the composed chunk, not just the body:** a title plus headings can assemble a card number. Scan record
  fields, table cells, file names and identifiers too. Redact other PII before chunking (Presidio is MIT) [S7].

## Prompt injection at ingest
- **Detect on a folded view:** NFKC, invisible, bidi and tag characters dropped, look-alike letters mapped, alongside
  the raw text. Folding takes a planted set from mostly unlabelled to fully labelled [M3].
- **Label, do not delete.** Label the whole document so every chunk inherits the flag; keep payloads as citable
  evidence that travels only as data, with links defanged to `[link: host]` and no active image destinations.
- **Datamark untrusted evidence in prompts;** spotlighting cut attack success from above 50% to below 2% [S4] on
  simple payloads, but adaptive attacks bypassed 12 published defences at above 90% success [S8].
- **Pattern scanners have a vocabulary ceiling.** A per-chunk scanner misses every payload split across chunks [M4],
  and every held-out trigger phrase even uncut [M4]. Scan the assembled pack, and keep the blast
  radius small: a reader model with no tools, a planner that never sees retrieved text, a deterministic egress filter.

## Linking, extraction and re-embedding
- **Keep entity names per ACL key.** A name pooled across ACL keys lets a restricted record's alias link a public chunk.
  A derived edge (a fuzzy match between two names) takes the intersection of the ACLs behind the names that scored.
- **Do not rebuild the linking index per ingest call:** it is linear in the graph, so small batches crawl while
  large ones run nearly ten times faster; a bulk per-ACL-key build replaces hours of per-key scans [M7].
- **Extraction:** a flat per-chunk schema routed to a slice of the ontology; reject on a missing verbatim quote, an
  illegal pattern, an unresolved endpoint or low confidence; never let an LLM edge overwrite a system-of-record edge.
  Rank entity display names by source trust before mention count, or planted documents rename entities.
- **Re-embedding is a one-way door:** new index per model and dimension, model and dimension stamped on the index,
  vector search refused on a mismatch, shadow eval and leak suite before the switch, old index read-only until rollback closes.

## Measurements
- [M1] Chunks over the embedder token limit and share of tokens silently dropped, by document family · corpus public-style code, API specs and wiki pages · n=3 document families · tier R0
- [M2] Character-based token estimate vs real tokenizer count on over-limit chunks · corpus same families · n=every over-limit chunk found · tier R0
- [M3] Planted injection payloads labelled before and after folded scanning · corpus a synthetic multi-department document set · n=a few dozen payload documents · tier R0
- [M4] Split and held-out trigger-phrase plants missed by a pattern scanner · corpus a synthetic multi-department document set · n=dozens of plants per arm · tier R0
- [M5] Checksum-only card test false positives on synthetic barcodes and commit hashes · corpus a synthetic multi-department document set and a generated enterprise · n=thousands of barcodes · tier R0
- [M6] Live documents purged by partial listings before completeness was required · corpus connector fixtures · n=3 listing types · tier R0
- [M7] Linking-index rebuild cost per ingest call by batch size; bulk vs per-key build · corpus a large generated enterprise corpus · n=2 batch sizes · tier R0
- [M8] ACL change to unreadable within a couple of seconds at p95, none still visible · corpus a large generated enterprise corpus · n=a small sample of revocations · tier R0

## Sources
- [S1] Microsoft Graph change notifications overview, latency table · https://learn.microsoft.com/en-us/graph/change-notifications-overview · fetched 2026-10-17
- [S2] Anthropic, Contextual Retrieval · https://www.anthropic.com/engineering/contextual-retrieval · fetched 2026-10-17
- [S3] A Systematic Investigation of Document Chunking Strategies · https://arxiv.org/abs/2603.06976 · fetched 2026-10-17
- [S4] Defending Against Indirect Prompt Injection Attacks With Spotlighting · https://arxiv.org/abs/2403.14720 · fetched 2026-10-17
- [S5] Docling · https://pypi.org/project/docling/ · fetched 2026-10-17
- [S6] PyMuPDF · https://pypi.org/project/PyMuPDF/ · fetched 2026-10-17
- [S7] presidio-analyzer · https://pypi.org/project/presidio-analyzer/ · fetched 2026-10-17
- [S8] The Attacker Moves Second · https://arxiv.org/abs/2510.09023 · fetched 2026-10-17
