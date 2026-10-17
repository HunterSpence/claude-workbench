---
title: _shared HOT
domain: _shared
status: active
---
# _shared: hot facts

Scope: facts every task needs: team conventions, environment, tools, contacts by role.
Keep this file under its byte cap (`kb_audit.py --caps-json`). Over the cap, demote whole lines with
`kb_demote.py`; never shorten text in place.

## Current state
- On-demand knowledge shipped with the kit: `digests/` (topic digests, listed under Relations) and `bug-cards.md`
  (recurring failures with fixes; search it by symptom words before debugging).
- Choosing a model, an effort level or a subagent's model, or saving tokens: [[_shared/digests/models-and-tokens]].
- Search, RAG and knowledge graphs: [[_shared/digests/knowledge-layer]] (ladder, evidence, tools, licences) and
  [[_shared/digests/retrieval-eval-method]] (measuring a change honestly).
- Permission-safe retrieval for many users: [[_shared/digests/enterprise-rag-architecture]],
  [[_shared/digests/enterprise-rag-retrieval]], [[_shared/digests/enterprise-rag-ingestion]],
  [[_shared/digests/enterprise-rag-evaluation]], [[_shared/digests/enterprise-rag-failure-modes]].
- Reports and PDFs: [[_shared/digests/reports-and-pdfs]]. A grounded, role-aware help assistant:
  [[_shared/digests/internal-assistant]].

## Decision heuristics

## Error blacklist (symptom -> root cause -> fix)

## Relations
- part_of [[00-index]]
- lists [[_shared/bug-cards]]
- lists [[_shared/digests/claude-code-mechanics]]
- lists [[_shared/digests/enterprise-rag-architecture]]
- lists [[_shared/digests/enterprise-rag-evaluation]]
- lists [[_shared/digests/enterprise-rag-failure-modes]]
- lists [[_shared/digests/enterprise-rag-ingestion]]
- lists [[_shared/digests/enterprise-rag-retrieval]]
- lists [[_shared/digests/git-ci]]
- lists [[_shared/digests/internal-assistant]]
- lists [[_shared/digests/knowledge-layer]]
- lists [[_shared/digests/mcp]]
- lists [[_shared/digests/models-and-tokens]]
- lists [[_shared/digests/orchestration]]
- lists [[_shared/digests/reports-and-pdfs]]
- lists [[_shared/digests/retrieval-eval-method]]
- lists [[_shared/digests/testing]]
- lists [[_shared/digests/windows-shell]]
