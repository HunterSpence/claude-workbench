# Decide whether you need a knowledge graph or vector search

Automates it: none (a decision with gates; each tool has its own guide)

## When to use
Someone proposes embeddings, a vector database, a reranker or a knowledge graph for a set of documents, or the answers
from your knowledge base or `find` keep missing. You want to know whether the extra machinery will pay for itself before
anyone builds it. `<KIT>` is the kit folder (guide 01). The evidence and tool tables behind this guide are in the
knowledge-layer digest of your knowledge base (`_shared/digests/knowledge-layer.md`).

## Steps
1. **Collect real questions.** Write down twenty to fifty questions people actually asked (chat, tickets, search
   history), not ones you invent. Mark each one: a lookup of one fact, a question that needs two or more documents
   joined, or a question about the whole collection ("what are the main themes?").
2. **Measure what you already have.** Put the documents where the kit already searches (a `find` root, guide 28, or
   notes in the knowledge base) and run every question through keyword search:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py search "<question>" --mode keyword --root <label>
   py -3 <KIT>/plugins/workbench-kb/scripts/kb_search.py "<question>"
   ```
   Record whether the right document is in the first five results. Keep the questions in a file and measure the same
   way every time (guide 48 for features that call Claude, `docs/engineering/retrieval-eval.md` for search).
3. **Hold half back.** Split the questions into a dev half you may tune on and a held-out half you only measure.
4. **Climb one rung only when its gate fails**, and stop at the first rung that passes:

   | Rung | What you add | Climb to the next rung when |
   |---|---|---|
   | 1 | Markdown files, grep and read | answers miss across many documents |
   | 2 | read-only connectors to where the documents live | answers need repeatable citations |
   | 3 | a full-text index with paragraph ids and a citation check (`find`, `kb_search`) | the held-out half says so |
   | 4 | meaning search (embeddings) fused with keyword search | fewer than about 85 in 100 held-out questions find their document in the top five, mostly paraphrases |
   | 5 | a graph | the failing questions are whole-collection or multi-document joins that links and ids cannot answer |

5. **Before rung 4, check the kit.** `find` already has meaning search; it needs its embedding model. See whether
   vectors are on:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py status
   ```
6. **Before rung 5, try the graph that needs no model.** Links, ids and "supersedes" relations taken from the documents'
   own structure, walked with SQL, answer most "what is connected to this" questions. Make generated items carry the
   ids of the paragraphs they came from, so traceability is a join, not a model call. A graph built by a model costs a
   model call per chunk: price it on about fifty documents first.
7. **Check licences before a pilot.** Some search stores and graph engines are AGPL, SSPL or source-available
   (the digest's licence table); `THIRD-PARTY.md` lists what the kit itself ships (guide 54).
8. **Re-measure after each change** on the same questions, dev half and held-out half. Keep the change only if it helps
   on both and breaks nothing that worked before.

## Verify
- You have a file of real questions, a held-out half, and a recorded first result for each rung you tried.
- Every rung you climbed names the gate that failed, with the number from the run.
- After a change, no question that was found before is now missed (count these negative flips).

## Common failures
- **Building vectors because a demo looked good:** a demo is three questions you chose. Run the question file.
- **Tuning on the questions you report:** the numbers flatter you. Tune on the dev half, report the held-out half.
- **A graph for single-fact lookups:** published comparisons find plain retrieval as good or better for those; graphs
  help whole-collection and multi-hop questions.
- **Meaning search silently off:** `find` falls back to keyword-only when its model is missing or blocked;
  `doc_index.py status` says why.
- **A licence surprise after the pilot:** check before you start (step 7).
