---
title: Digest, grounded role-aware internal assistant
domain: _shared
status: active
---
# Internal assistant: a grounded, role-aware help assistant that links the right page

Read this before building a help chatbot or question-answering assistant that answers employees or customers from your
own documentation, links them to the right page, and must keep admin-only content from ordinary users. The full
walk-through is the guide named below.

## The pattern in twelve lines
1. **Docs first:** one short doc per page or feature. Each opens with a **Where:** line (the click path, then the page
   address), uses the exact on-screen labels, and says what is not supported. One site map per audience sits in every
   audience's corpus. Prices, rates and percentages stay out.
2. **A route registry is the source of truth for navigation:** address, page name and minimum role for every page,
   generated from the app's router and kept beside the docs. The role-by-feature visibility matrix comes from it and is
   signed off by the system owner.
3. **Links are tested:** every address in the docs and in answers must match the registry and the reader's role;
   unknown addresses are shown as text, never as links. A coverage test proves the docs cover every page: each route is
   linked by a doc or sits on a reviewed exclusions list.
4. **The audience is mandatory:** a folder or file-name prefix that a script reads. A doc with
   no audience, or an unknown one, is not loaded.
5. **Small corpus: send each role's whole corpus, cached,** under a token-budget test. Cache reads cost a fraction of
   the base input price, and a prompt under the model's minimum cacheable length is not cached, with no error [S2].
   Larger: retrieval per collection, one collection per audience where retrieval has no document-level permission
   filter, chunks that repeat the page title and its Where: line (context on every chunk cut retrieval failures in the
   vendor's tests [S1]), and the site map always included.
6. **A grounding prompt:** answer only from the docs, copy click paths exactly, link only registry addresses, name but
   never link pages on another site, and use one exact "not covered" sentence that points to support.
7. **Lowest reasoning effort that passes the eval:** effort trades thoroughness for tokens, and lower levels save
   tokens [S3]. Leave out sampling parameters a model rejects, and handle refusal stops and an output cut off before
   any text [S4].
8. **A front door:** the role comes from the identity provider on the server and fails closed to the lowest role; the
   current page is a validated wording hint that never widens access; a daily cap per user; history rebuilt or bounded,
   with fabricated assistant turns dropped.
9. **An output filter:** only safe internal paths that match the registry become links, markdown the surface cannot
   render is stripped, and following a link keeps the conversation.
10. **Evaluation per role before every publish:** golden items with must-contain facts, a must-link route, must-refuse,
    never-contain strings and a no-figures flag. Model-free checks run first (coverage, gating, a line-level leak test,
    and refused items proven gated because the same strings are present for admins). The scoring script is itself
    tested on recorded and known-bad answers; mutation tests and a live run through the real route follow.
11. **Operations:** a free key check decides availability (only an authentication failure means unavailable, admins
    see the reason, the assistant never vanishes silently), run logs show cache reads, a scheduled known-answer probe
    watches quality.
12. **Freshness:** a dated what's-new page per audience built from the release log, and a flag-to-doc check that fails
    until a switched-off feature's doc says it is paused.

## On a visual flow builder
Map each piece to a capability, not a product: document collections per audience; retrieval settings (chunk size,
hybrid search, top-k, a similarity cut-off); a branching step that picks answer, "not covered" or out of scope; prompt
templates; an evaluation step with a question set and an LLM judge; run logs with cost and latency; input and output
filters; and access set per published assistant. The doc checks (links, roles, coverage, no figures) run as a script
step or a custom check before upload; the answer-link check is
an output filter or a code step after the model. If the chat surface renders no links, answer with the click path plus
the full address as text.

## Where to go next
- **The walk-through** (route registry, doc shape, platform mapping, steps, eval set, rollout checklist): "Build a
  grounded, role-aware internal assistant" in `docs/howto/`.
- **The coded variant** inside a web app you build (route list, help pages plus the caller's role, no tools, a cached
  whole-corpus prompt, an eval that fails on unknown or unsafe links): `/workbench-core:app-navigator` and "Add an
  in-app navigation assistant" in `docs/howto/`.
- **Permission-safe retrieval at scale** (per-document access, derived summaries, leak testing): the
  `enterprise-rag-*` digests, starting with `enterprise-rag-architecture`.
- **Graph or flat docs:** the knowledge-layer digest. Docs that explain cross-page interplay answer most questions
  without a graph.

## Sources
- [S1] Anthropic, Contextual Retrieval in AI Systems · https://www.anthropic.com/news/contextual-retrieval · fetched 2026-10-17
- [S2] Claude API docs, Prompt caching · https://platform.claude.com/docs/en/build-with-claude/prompt-caching · fetched 2026-10-17
- [S3] Claude API docs, Effort · https://platform.claude.com/docs/en/build-with-claude/effort · fetched 2026-10-17
- [S4] Claude API docs, Claude Haiku 5.5 migration guide · https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide · fetched 2026-10-17
