---
title: Knowledge base index
status: active
---
# Knowledge base index

Start here. This note says where things live and links to every domain, and each domain's HOT.md links back, so a
related-notes walk from any domain reaches the rest. Add a line here when you add a domain or a long-lived note.

## Domains
Every domain folder holds a HOT.md (current facts, byte-capped), an optional history.md and its topic notes.
- [[_shared/HOT]]: facts every task needs, and the on-demand digests and bug cards that ship with the kit
- [[platform/HOT]]: the applications you build: architecture, UI, testing, code review
- [[infra/HOT]]: servers, containers, CI/CD, networking, DNS and certificates, monitoring
- [[data/HOT]]: databases, pipelines, schemas, data quality
- [[ai/HOT]]: models, agents, prompts, RAG, evaluation, Claude Code itself
- [[security/HOT]]: secrets handling, hardening, findings, compliance
- [[ops/HOT]]: how work runs: this knowledge base, docs, cost, research, debugging
- [[projects/HOT]]: multi-session projects, one folder per project

## Shipped with the kit
- [[_shared/bug-cards]]: recurring failures, each with symptom, cause, fix and a test
- Digests, read on demand: [[_shared/digests/windows-shell]], [[_shared/digests/git-ci]],
  [[_shared/digests/claude-code-mechanics]], [[_shared/digests/mcp]], [[_shared/digests/testing]] and
  [[_shared/digests/orchestration]]
- Kit knowledge, read on demand: [[_shared/digests/models-and-tokens]] (models, effort, tokens),
  [[_shared/digests/knowledge-layer]] and [[_shared/digests/retrieval-eval-method]] (search, RAG, graphs, measuring),
  [[_shared/digests/reports-and-pdfs]], [[_shared/digests/internal-assistant]], and the enterprise RAG set
  [[_shared/digests/enterprise-rag-architecture]], [[_shared/digests/enterprise-rag-retrieval]],
  [[_shared/digests/enterprise-rag-ingestion]], [[_shared/digests/enterprise-rag-evaluation]] and
  [[_shared/digests/enterprise-rag-failure-modes]]
- How the kit itself works: [[_shared/digests/workbench-explainer]] (with the explainer and poster PDFs beside it) and
  [[_shared/digests/ponytail-measurements]] (what the coding rules save)
- [[ops/model-routing-ledger]]: an append-only record of routing picks that surprised you

## Looking something up
Search by the words the note would use, then widen: `kb_search.py "terms"`, then `kb_search.py --related <note>` to
see what links to or from a hit. A miss is not proof the knowledge base has nothing; retry once with the exact tool,
error string or name.
