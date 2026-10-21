---
title: Digest, how this workbench works (the explainer and the poster)
domain: _shared
status: active
---
# How this workbench works: the explainer, the poster, and where each answer lives

Read this when someone asks how the kit works, what is in it, whether it has RAG or a knowledge graph, or what it
saves, and before explaining the kit to a colleague or a manager. Two PDFs sit beside this note in `_shared/digests/`:
- `workbench-explainer.pdf`: the long explainer, twelve chapters plus a list of the how-to guides and a list of the
  tools. `find` indexes it with the rest of the knowledge base, so it can answer questions about the kit with page
  citations.
- `workbench-poster.pdf`: one landscape page with the session flow, the agent team, every skill, the knowledge layer,
  the machine layer and the token savers.

Both describe the release named on their cover. Each fact in them has a home in the kit, listed below; when a PDF and
the kit disagree, the kit file wins. An upgrade replaces both PDFs (and this note) unless you edited them.

## Chapter map of the explainer
1. Summary: what the kit adds to a plain Claude Code install, and the headline savings with their source tier. Home:
   `README.md`.
2. How it is put together: the four plugins, what is in the box, what happens during a session, the hooks. Home:
   `docs/HOW-WE-WORK.md`.
3. Installing, checking and updating: the Day-1 sequence, the capability report, the doctor and the Day-1 knowledge
   checks, the one-phrase update, uninstall and profiles. Home: `IMPORT.md` and `docs/SETUP-RUNBOOK.md`.
4. The rules layer: which instruction wins in a conflict, the core file, the rule files, how rules are tested. Home:
   `instructions/` and `docs/rules-card.md`.
5. The skills, by area: engineering, platform building, knowledge and research, office documents, business-analyst
   work, kit administration, third-party skills. Home: each plugin's `skills/` folder and `docs/business-catalog.md`.
6. The agent team and how work flows: the personas, routing by task type, build then attack then verify. Home:
   `plugins/workbench-core/agents/` and `docs/model-routing.md`.
7. The knowledge layer: this knowledge base, the link graph, `find` and its RAG pipeline, capture and ingest, which
   tool answers which question. Home: [[_shared/digests/knowledge-layer]] and the `find` skill.
8. Ponytail: the coding ladder, how the kit loads it, what it saves, where it hurts. Home:
   [[_shared/digests/ponytail-measurements]].
9. Token savings: where the spend goes, the prices that drive the design, every lever, the tricks left out. Home:
   [[_shared/digests/models-and-tokens]] and `docs/token-diet.md`.
10. Why it is smart: the design ideas behind the rules, the team, the memory and the search.
11. Safety, privacy and honest limits. Home: `docs/known-limits.md`.
12. Glossary, then the appendices: every how-to guide (`docs/howto/`) and every tool (`tools/`).

## The short answers
- **RAG or a knowledge graph?** RAG plus a link graph; no language model builds the graph. `find` retrieves cited
  paragraphs with keyword ranking and a local embedding model, fused. The graph comes from the documents' own
  structure: wiki links, hyperlinks, newer-version chains, ticket ids, people and meetings, the same folder. This
  knowledge base adds its own wiki-link walk (`kb_search.py --related`). Why there is no model-built graph:
  [[_shared/digests/knowledge-layer]].
- **What does it save?** Most of an agent session's cost is the context it re-reads on every call, so the kit's levers
  are context levers: small always-loaded rules, a trimmed skill listing, tools loaded on demand, a small model for
  reading, subagents for exploration, the Batch API for work nobody waits on, and ponytail for build work. Figures:
  [[_shared/digests/models-and-tokens]] and [[_shared/digests/ponytail-measurements]].
- **Which model does which job?** The routing table, `docs/model-routing.md`; never copy it into a note.
- **Is it safe on a managed laptop?** It installs without admin rights, does not edit managed settings, and backs up
  every file it changes so uninstall can put them back. Its known limits are listed in `docs/known-limits.md`.
- **Is ponytail the kit's own?** No. It is a third-party MIT project [S1], adapted into one skill, scoped to code and
  ranked below the organisation's coding standards and the user's explicit requests.

## Using the PDFs
- **To answer a question from them,** search with `find` and cite the page it returns; do not quote either PDF from
  memory.
- **To share the kit's story,** send the explainer as it is. The poster prints on one large landscape sheet or reads on
  a screen.
- **If a number in a PDF looks out of date,** check its home file first, then say which release the PDF describes.

## Sources
- [S1] ponytail repository README (licence) · https://github.com/DietrichGebert/ponytail · fetched 2026-10-20
