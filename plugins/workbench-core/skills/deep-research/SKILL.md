---
name: deep-research
description: Deep, verified web research that ends in a decision list (critical / yes / maybe / no). Use for "deep research", "/workbench-core:deep-research", "research in depth", or a question that needs many sources checked and adversarially verified (vendor or tool evaluation, "should we adopt Y"). Not for a single fact (answer inline) and not for code search.
---

# /workbench-core:deep-research

Uses only Claude Code's built-in `WebSearch` and `WebFetch` tools plus subagents. No extra keys,
no third-party search service. If your organisation restricts web access, those tools follow its
policy; do not route around a block.

## Pipeline
1. **Frame (you, before any search).** Restate the question, the decision it feeds, and what would
   change the answer. Today's date goes in the frame: "current" means as of that date. Split the
   question into 4-8 **lanes** (one angle each: official docs and changelogs, security and licence,
   cost and limits, independent benchmarks, community reports, alternatives, what is coming next).
2. **Research lanes (parallel subagents).** One `researcher` per lane, launched in one message.
   Each lane prompt (write it with the `spawn` skill) carries the frame, its single angle, and this
   contract:
   - search, then FETCH every source it cites; a search snippet is not a source;
   - every claim carries its URL, the page's own date, and a label: PUBLISHED (vendor or primary
     page fetched), REPORTED (third party), or INFERENCE (the agent's reasoning);
   - say what it could not reach and which tool failed ("the fetch returned an empty page" is a
     fact about the fetcher, not about the page);
   - at most 600 words, findings ranked by impact on the decision.
3. **Citation check (you).** Re-fetch a sample of the cited URLs yourself, all of them for any
   claim that decides the outcome. Drop claims whose URL is dead or does not say what was claimed.
   A vendor's roadmap or a researched date is a rumour, not a commitment.
4. **Red team.** One `red-team` agent gets the surviving findings (not the lane narratives) and
   tries to refute each: newer contradicting sources, conflicts of interest, benchmark flaws,
   replication status (author-only, or reproduced independently?). It returns per finding:
   STANDS, WEAKENED (why) or REFUTED (source).
5. **Judge.** `blue-verify` (or you, for a small question) builds the decision list from what
   survived, and labels each line VERIFIED, PLAUSIBLE or ASSUMED.

Need more search volume than the built-in tool allows? The optional search MCP servers in
`mcp/README.md` (each needs a key your organisation approves; queries leave the machine) can back a
lane. Never paste internal names, code or customer data into a search query.

Small question? Collapse to 2-3 lanes and skip step 4 only if the user agrees; say that you did.

## Output
Write the report to a local file (`research/<slug>-<YYYY-MM-DD>.md` in the working folder, or
where the user says). Publish it to a shareable page or Artifact only when the user asks, and only
when it contains nothing but public sources and your own organisation's information: never another
organisation's or tenant's data, such as a client's or partner's. Shape:

```markdown
# <question> (researched <date>)
## Bottom line (3-5 lines; lead with anything critical)
## State of the field (short)
## Decision list
| Bucket | Item | Action | Why | Red-team status | Sources |
|---|---|---|---|---|---|
| critical | ... | do now | ... | STANDS | [1][4] |
| yes | ... | adopt | ... | WEAKENED: ... | [2] |
| maybe | ... | test first: <what test> | ... | STANDS | [3] |
| no | ... | skip | ... | REFUTED: ... | [5] |
## What we could not verify
## Sources (numbered; URL, publisher, page date, fetched date)
```

Rules for the buckets: an adopt or reject that rests on a benchmark names whether anyone other than
the author reproduced it. A null result from a broken or untested test is UNTESTED, never a "no".
Never present a researched date or a forum claim as a vendor commitment.
