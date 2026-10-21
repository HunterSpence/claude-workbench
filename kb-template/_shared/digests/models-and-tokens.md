---
title: Digest, models and tokens
domain: _shared
status: active
---
# Models and tokens: which model, which effort, and what makes a session expensive

Read this before choosing a model or an effort level for a task or a subagent, before a long or parallel run, and when
the seat's usage runs out early. The kit's own documents hold the details and this note says where; it adds the vendor
facts that decide how they apply. Kit paths below sit under `<WB>/kit/` (`<WB>` is the `workbench` folder in your
Claude configuration folder).

## Route by task type
- **The routing table is `docs/model-routing.md`** (generated from `settings/model-routing.json`). Each task type (CODE,
  BREADTH, READ, BUILD, GATE, RESEARCH, OPS, DELIVERABLE, SECURITY, REGULATED, RED, GREEN) names a persona, a model
  preference order, what never to use and the evidence. Link it; never copy it into a note, because it is regenerated
  when the evidence moves.
- **Unsure which type?** Go one row up in stakes. On "model not allowed", step down that row's chain; never retry the
  same model or route around the restriction.
- **Where the rest lives:** the always-loaded `instructions/rules/model-policy.md` (roles, effort floor, Batch);
  `model-profiles.md` beside it (how to write a worker prompt per model); `docs/models.md` (overview, prices, vendor
  defaults); `docs/evidence/haiku-5-5.md` (the small model); `docs/engineering/routing-method.md` (how rows are chosen);
  `docs/token-diet.md` (what really saves tokens, price ratios, the skill listing).

## Effort
- **Kit policy:** `high` or `xhigh` for the Opus and Sonnet personas, `high` for Haiku, `max` only when the user asks
  (the `sonnet-max` persona). This is a quality-first default, not a vendor rule; an explicit user choice wins.
- **How Claude Code resolves the session level:** an explicit choice (`CLAUDE_CODE_EFFORT_LEVEL`, `--effort`, `/effort`)
  first, then saved settings (the per-model level or `effortLevel`), then the model's default [S4]. A subagent's or
  skill's `effort` frontmatter overrides the session level but not the environment variable [S4], and a per-call
  `effort` parameter overrides the frontmatter (Claude Code v2.1.292 or later) [S1].
- **So never set `CLAUDE_CODE_EFFORT_LEVEL` or `--effort`:** either one flattens every persona to one level.
- **Defaults are lower than the table:** Opus 5.5, Sonnet 5.5 and Haiku 5.5 default to `medium` in Claude Code [S4], so
  every persona sets `effort:` explicitly. Thinking cannot be switched off on these models; lower the effort instead.

## The small model's never-list (kit policy)
- Never for facts from memory, tool loops, code, ops, security, regulated work, final deliverables or gates, and never at
  `xhigh` or `max`. The evidence is the READ row of the routing table and `docs/evidence/haiku-5-5.md`. The `scout`
  persona is the one place it runs: reading text that is handed to it.

## Which model a subagent runs on
- **Order:** the per-call `model` parameter, then the subagent's `model` frontmatter, then `CLAUDE_CODE_SUBAGENT_MODEL`,
  then the main conversation's model [S1]. The kit's settings profiles set the variable so an unnamed general-purpose
  spawn runs the BREADTH row's model (`settings/SETTINGS.md`).
- **Version caveat:** before Claude Code v2.1.251 [S1] the variable came first and overrode both the parameter and the
  frontmatter [S1], which turns every persona into that one model. Check `claude --version` before relying on the order.
- **Check, do not assume:** `/tasks` names the model and effort of each running subagent (v2.1.242 or later) [S1]. The
  variable does not move the built-in Explore and Plan agents [S1]. Never set `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`: it
  forces one model onto every subagent, teammate and workflow agent [S1].

## Fallback
- **A fallback silently changes who produced a verdict.** Gate personas open each verdict with `Model: <id>` so a
  reader can tell (kit rule).
- **Mechanics:** a fallback chain switches for the current turn only and holds at most three models [S4]; entries the
  organisation's allow-list excludes are dropped [S4]; a subagent runs on a fallback model rather than failing [S4].
  Put each persona's fallback targets on the allow-list request: a fallback whose target is excluded does not run [S4].

## Prompt cache
- **Layers:** system prompt and tool definitions, then project context (CLAUDE.md, rules), then the conversation; a
  change in one layer re-reads everything after it [S2].
- **Breakers:** switching model always rebuilds the cache [S2]; changing the set of loaded tool definitions does too,
  for example connecting an MCP server while tool search is off [S2]; compaction rebuilds the conversation layer [S2].
- **Keepers:** plan mode and skill loading arrive as messages [S2]; a plugin's skills, agents and hooks never break it
  [S2]; editing CLAUDE.md mid-session keeps the cache but the edit applies only after `/clear`, `/compact` or a
  restart [S2].
- **Does an effort switch break it?** On Opus 5.5, Sonnet 5.5, Haiku 5.5 and Fable 5.1 with an API key or a Claude
  subscription, no [S2]. It does on Bedrock on AWS, Google Cloud's Agent Platform or a Claude apps gateway, with
  `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` set, under a HIPAA configuration, and on other models [S2]. Fable 5.1 kept
  it only from Claude Code v2.1.260 [S2]. Choose model and effort at the start of a task anyway.
- **Lifetime (TTL), two buckets:** the main conversation gets one hour on a subscription within plan usage and five
  minutes with usage credits, an API key or a cloud provider; everything else (subagents, workflows, compaction,
  titles) gets five minutes, except a few server-controlled helper requests that get one hour on a subscription
  [S2]. A pause longer than that makes the next turn re-read the whole prefix.
- **Controls:** `promptCacheTtl` and `subagentPromptCacheTtl` take `5m` or `1h` (v2.1.242 or later) [S2];
  `ENABLE_PROMPT_CACHING_1H=1` asks for an hour and `FORCE_PROMPT_CACHING_5M=1` forces five minutes, for both [S2].
- **See it:** `/usage` shows a `Prompt cache (main)` line with hit ratio, misses and whether the cache is warm
  (v2.1.251 or later) [S2], and names the likely cause of the last miss from v2.1.260 [S2].

## Other cost levers
- **Batch API for work nobody waits on:** every token class at 50% of the standard price [S5]; most batches finish within
  an hour, and a batch not done in 24 hours expires [S5]. In the kit: `/workbench-core:batch-review` (needs an
  organisation API key).
- **`/insights`** reads up to 200 recent sessions on this machine [S3] and writes an HTML report on how you work
  (friction points, suggestions); its tokens count against your plan [S3].
- **Agent teams** use approximately 7x more tokens than standard sessions when teammates run in plan mode [S3], and are
  off by default [S3]. A subagent that returns a summary is the cheaper shape.
- **Prefer a CLI to an MCP server** when both exist (`gh`, `aws`, `gcloud`): a CLI adds no per-tool listing [S3].
- **Skill listing:** every skill name is always listed, but past the listing's budget of 1% of the context window the
  descriptions of the least-used skills are dropped first [S6], and each entry is cut at 1,536 characters [S6]. Raise
  the budget with `skillListingBudgetFraction`; the kit's numbers are in `docs/token-diet.md`.
- **Ponytail for build work:** what the coding rules save in single answers and in agent sessions, and why the way they
  arrive decides it, is in [[_shared/digests/ponytail-measurements]].
- **Context size is the big lever:** `/clear` between unrelated tasks, `/compact` with what to keep, exploration in a
  subagent, a short CLAUDE.md. Measure with `/usage` and `/context` before and after a change.

## Sources
- [S1] Claude Code docs, Create custom subagents · https://code.claude.com/docs/en/sub-agents · fetched 2026-10-17
- [S2] Claude Code docs, How Claude Code uses prompt caching · https://code.claude.com/docs/en/prompt-caching · fetched 2026-10-17
- [S3] Claude Code docs, Manage costs effectively · https://code.claude.com/docs/en/costs · fetched 2026-10-17
- [S4] Claude Code docs, Model configuration · https://code.claude.com/docs/en/model-config · fetched 2026-10-17
- [S5] Claude API docs, Message Batches API · https://platform.claude.com/docs/en/build-with-claude/batch-processing · fetched 2026-10-17
- [S6] Claude Code docs, Extend Claude with skills · https://code.claude.com/docs/en/skills · fetched 2026-10-17
