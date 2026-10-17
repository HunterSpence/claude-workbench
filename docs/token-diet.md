# Token diet for Claude Code

What actually reduces Claude Code token spend. Section 3 reports directions from one small run of headless Claude
Code sessions on one open-source repository, not numbers to plan with: measure your own before you keep anything
(section 5).

## 1. Know where your tokens go first

Method: take a couple of weeks of your own session logs, price every request at API rates, and
split the cost by token type: cache writes (context growth and cache misses), cache reads
(re-reading context on every call), thinking, code and tool-call arguments, and the prose the model
writes to you. `py -3 <KIT>/tools/token-split/token_split.py` does this from your local transcripts: it reads usage fields
only, never message text, and prices them with the table in section 6. `<KIT>` is the kit folder.

In typical heavy use, most of the cost is cache reads and writes, and very little is prose. So
"talk shorter" tricks can only touch a sliver. **Context size is the big lever.** Run `/usage`
and `/context` to see your own split before you change anything.

## 2. Free levers (built in, nothing to install or approve)

- `/clear` when you switch to an unrelated task. A fresh context is cheaper than dragging the old one.
- `/compact <what to keep>` before a long session gets heavy, and say what to keep.
- Hand exploration ("find where X is used", "read these 20 files") to a subagent. Only its summary
  comes back into your context.
- Use `/effort` deliberately. Routine edits rarely need the top level, and thinking is billed as output.
- **Lower the effort; Claude Code cannot turn thinking off** on Opus 5.5, Sonnet 5.5, Haiku 5.5 or the Fable models. For
  Haiku 5.5 the vendor found, in its own testing, that telling the model to answer directly did not stop it thinking
  (evidence E13 in `docs/model-routing.md`), so lower the level with `/effort` instead.
- **Pick the effort at the start of a task.** On Opus 5.5, Sonnet 5.5, Haiku 5.5 and Fable 5.1 with an API key or a Claude
  subscription, `/effort` mid-session keeps the prompt cache. On Bedrock, Google Cloud (Vertex), a Claude apps gateway, with
  `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` set, under a HIPAA configuration, and on older models, a mid-session change makes
  the next request re-read the whole conversation uncached, and Claude Code asks you to confirm while the cache is warm
  (section 8).
- **In API conversations, keep effort constant.** If your own script or app calls the API, changing the top-level effort
  between requests invalidates the prompt cache for that conversation. A per-message effort change keeps it, but only with
  the vendor's per-message effort beta header, with adaptive thinking (with thinking off, a per-message change returns an
  error), and not on Bedrock for Sonnet 5.5 or Haiku 5.5.
- Keep `CLAUDE.md` and everything it imports short: it is re-read on every call of every session.
- Keep the skill listing inside its budget; a listing over budget silently loses skill descriptions (section 7).
- Leave MCP servers you aren't using disconnected, and leave MCP tool search on (it is on by
  default; don't set `ENABLE_TOOL_SEARCH=false`) so unused tool definitions stay out of context.

## 3. What this kit uses, and the plain-text alternative

The build personas (`flagship`, `implementer`) carry the ponytail text (MIT). The plain-text block below is the
alternative: it needs no plugin, hook or marketplace approval. To switch, replace the ponytail section of a persona
with it:

> Be brief. Follow YAGNI: build only what is asked, and prefer the standard library and the
> simplest solution that meets every stated requirement. Never drop input validation, security
> checks, or error handling that prevents data loss. When asked to explain, teach, review, or
> write a procedure or runbook, be complete: keep every step and say why.

What the small run showed (direction only):
- **In build sessions both are the big saver.** Session cost fell on both models, mostly because the agent took
  fewer turns and so re-read its context less. The saving was largest on tickets that invited over-building and
  smaller on plain CRUD tickets. Blind review found no loss in completeness and no security gap.
- **Agents wrote fewer test lines**, though not much less often. Ask for tests when you want them.
- **In single answers the block is the safe option:** cost barely moved and every explanation stayed complete.
  The ponytail plugin made single answers on the mid-tier model cost more and dropped explanation steps, carries
  much more standing context than the block, and needs marketplace approval.
- **"Be brief." alone** saved a little on single answers, but some explanations missed a point and one runbook it
  wrote did not work. Fine for code-only sessions.
- **caveman** left explanations too terse for a junior reader.

## 4. Do not install

- **caveman "ultra" or "wenyan" modes.** They drop explanation quality first, and wenyan answers in
  Classical Chinese.
- **Tool-output proxies with telemetry on by default** (read each
  proxy's README; some send an anonymous beacon unless you opt out). Every API call would pass through a
  third party.
- **context-mode.** It is under the Elastic License 2.0, which is not an open-source licence; ask
  your legal team first.
- **Copying `claude-token-efficient`'s `.claude/settings.json`.** It adds a PreCompact hook that runs
  `git commit --no-verify`, which skips your repo's commit checks.

(Licence and hook claims checked against the upstream repos.)

## 5. Measure your own

Use `/usage` and `/context` in Claude Code, `py -3 <KIT>/tools/token-split/token_split.py` for the split by token class, or
`npx ccusage` (MIT) over your local session logs.
Compare one normal week with one week on the diet before you keep it. Before you trust a result,
check that the change was actually applied and that both weeks had comparable work
(`instructions/rules/verification.md`): a saving measured on the wrong workload, or with the
change silently not applied, is not a saving.

## 6. Will a cheaper model save money?

Compare per token class, not by the headline price. The vendor's price table for the Anthropic API, in dollars per million
tokens (October 2026; check the pricing page before you rely on it). These numbers live in the `prices` key of
`settings/model-evidence.json`, are repeated for all four models in [Models at a glance](models.md), and a test keeps this
table equal to them:

| Token class | Haiku 5.5, prompt up to 100K tokens | Haiku 5.5, prompt over 100K | Sonnet 5.5 | Opus 5.5 |
|---|---|---|---|---|
| Input | 0.10 | 0.50 | 2 | 4 |
| Output | 0.50 | 2.50 | 10 | 20 |
| Cache write (5 minutes) | 0.125 | 0.625 | 2.50 | 5 |
| Cache read | 0.01 | 0.05 | 0.10 | 0.20 |

So Sonnet 5.5 costs twenty times Haiku 5.5 for input, output and cache writes on prompts up to 100K tokens, but only ten
times for cache reads. Above 100K tokens the gaps shrink to four times and two times. Opus 5.5 costs twice Sonnet 5.5 in
every class. Agent sessions spend most of their money on cache reads and writes, and most agent turns carry long prompts
(evidence O2 in `docs/model-routing.md`), so the long-prompt ratios decide: two times for cache reads, four times for
cache writes. On long prompts Haiku 5.5 is sure to cost less than Sonnet 5.5 while it uses under twice the tokens, and cannot
cost less at four times or more; in between, the token mix decides (mostly cache reads). Up to 100K tokens the bounds are ten
and twenty times. Sonnet 5.5 costs less than Opus 5.5 while it uses under twice the tokens.

Two things to recheck when you move work to Haiku 5.5. It counts about 30 percent more tokens for the same text than the
previous small model did, so a token cap, budget or cost estimate tuned on that model needs recomputing. Its minimum
cacheable prompt is 512 tokens, against 4,096 on the previous small model, so short prompts that never cached before can
now be cached.

## 7. The skill listing

Every turn, Claude Code puts a listing of your skills in front of the model: each skill's name, its `description` and its
`when_to_use` text. That text is how the model decides to start a skill on its own, so it is both a context cost and the routing
signal.

- **Budget.** The listing may use 1 percent of the model's context window (the setting `skillListingBudgetFraction`, default
  `0.01`; the environment variable `SLASH_COMMAND_TOOL_CHAR_BUDGET` sets a fixed character count instead). One skill's text is
  cut at 1,536 characters whatever the budget (`skillListingMaxDescChars`).
- **Overflow drops descriptions, not skills.** Over budget, Claude Code keeps every skill name but drops the descriptions of the
  least-used skills first. The skill still works when you type it, but the model is much less likely to choose it unprompted.
  Nothing fails and nothing is shown; `--debug` writes a warning to the debug log. A machine with organisation-synced skills and
  other plugins can pass the 30,000-character default: in 0.3.1 the kit's own skills were about half of it, and the rest is
  bundled, organisation-synced and other plugins' skills the kit cannot touch.
- **Measure it.** `/doctor` prints an estimate of the listing's context cost and its biggest contributors; the Skills row of
  `/context` shows its size after the budget is applied; `/skill-doctor` points at skills you never use.
- **A ceiling, not a cost.** Both kit profiles set `skillListingBudgetFraction` to `0.02`. The listing still grows only to the text
  that exists, so the setting costs nothing until the listing is bigger than the default budget, and then it keeps descriptions
  that would otherwise be dropped (`settings/SETTINGS.md`). A managed value wins.
- **Who can tier what.** `skillOverrides` (`on`, `name-only`, `user-invocable-only`, `off`) covers your own and project skills
  and never plugin skills: the vendor documents that plugin skills are not affected by it, and every kit skill is a plugin skill.
  (Skills synced from a claude.ai account land in `skills/synced/`; the vendor does not say whether `skillOverrides` reaches
  them, so check the state in `/skills`.) A plugin skill is managed through `/plugin`, or through its own frontmatter.
- **What the kit does about its own skills.** It tiers them in frontmatter. The authoring and admin skills (`batch-review`,
  `mcp-heal`, `plugin-factory`, `plugin-review`, `web-packager`, `mcp-builder`, `api-bridge`, `app-navigator`, `brand-spec`) join
  the skills you only ever type (`setup`, `onboard`, `cleanup`, `pc-checkup`, `vdi-drive`, capture, ingest) with
  `disable-model-invocation: true`, which keeps their descriptions out of the listing; the auto-invoke hint then tells you the
  skill exists instead of starting it. Every other description is short and leads with the words you would say. A test
  (`py -3 <KIT>/tools/test_docs.py --budget`) caps the kit's own text, prints an estimate of the whole listing (the kit, the
  enabled upstream plugins, and an allowance for bundled and organisation skills) and fails when the kit's part passes half of
  30,000 characters.
- **What setup does for the rest.** For skills that are not plugin skills, `setup` measures the whole listing and, when the part
  the kit can control would pass 80 percent of the limit, writes `name-only` tiers for the biggest ones. It keeps the skills the
  kit routes to on, never writes `user-invocable-only` or `off` by itself, never overwrites a value you set, and takes a backup
  first. A permission rule or the user decides edits to your `settings.json` (`settings/SETTINGS.md`), so the tiers are applied
  by the setup step you run, not by a session on its own.
- **Check a skill still gets chosen.** After you shorten a description, measure it: `py -3 <KIT>/tools/skill-probe/skill_probe.py
  --kit` (guide 51) counts how often the kit's skills start on the prompts they should catch.

## 8. Prompt cache

Every request re-sends the whole conversation; the cache lets the API read the unchanged start of it at the cache-read rate
(a tenth of the input price on Haiku 5.5, a twentieth on Opus 5.5 and Sonnet 5.5, a fortieth on Fable 5.1) instead of
processing it again. The match is exact from the first token, so a change anywhere early recomputes everything after it. The
vendor's cost page puts caching first among the cost levers and, in its own measurements, usually the largest (E42, fetched
Oct 2026).

- **What breaks it** (one slower, dearer turn, then it is cached again; E37): a model switch (each model has its own cache,
  which includes `opusplan` toggles, a skill whose frontmatter names another model and an automatic model fallback); an effort
  change outside the conditions in the next point; turning fast mode on; connecting or removing an MCP server when tool
  definitions load upfront (with tool search, the default, a mid-session change leaves the cache intact); denying a whole tool
  when tool search is off; compaction (by design); a pause longer than the cache lifetime; many images; a Claude Code upgrade.
- **What keeps it** (E37): editing `CLAUDE.md` mid-session (the edit does not apply until `/clear`, `/compact` or a restart),
  changing permission mode, invoking skills, `/rewind`, and spawning a subagent, which warms a cache of its own.
- **Does an effort change break it?** In Claude Code, no on Opus 5.5, Sonnet 5.5, Haiku 5.5 and Fable 5.1 with an API key or a
  Claude subscription (E37). Yes on Bedrock, Google Cloud's Agent Platform, a Claude apps gateway, with
  `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` set, under a HIPAA configuration and on older models, where Claude Code asks you to
  confirm while the cache is warm. In an API conversation of your own, a top-level effort change does break it (E42). The two
  sources agree once the conditions are stated. Pick the level at the start of a task anyway, and sweep effort levels in separate
  sessions so the comparison is clean.
- **Two lifetime buckets** (E37): the main conversation, and everything else (subagents, workflows, teammates, forks, compaction,
  session titles). On a Claude subscription within plan usage the main conversation gets one hour and the rest five minutes;
  with an API key, a cloud provider or usage credits, both get five minutes. Choose a lifetime with `promptCacheTtl` and
  `subagentPromptCacheTtl` (`5m` or `1h`, Claude Code 2.1.242 or newer) or their environment twins, `ENABLE_PROMPT_CACHING_1H=1`
  for both buckets, and `FORCE_PROMPT_CACHING_5M=1` to override everything (E37, E41). A one-hour write costs twice the input
  price (E32), so it pays only when a session idles past five minutes between turns. The corporate profile sets only
  `subagentPromptCacheTtl` to `5m`, so subagents, whose requests are short-lived, keep the five-minute lifetime. It leaves
  `ENABLE_PROMPT_CACHING_1H` off: the flag adds nothing for the main conversation on a seat within plan usage and pays only on
  billed usage with frequent idle gaps (`settings/SETTINGS.md`).
- **See your own hit rate:** `/usage` adds a `Prompt cache (main)` line after the first response (hit share, misses with a likely
  cause, warm or cold; main conversation only; Claude Code 2.1.251 or newer, the likely-cause text 2.1.260 or newer; E39, E37).
  `/insights` writes a report on how you work rather than how many tokens you used (E39).
- **Agent teams** use roughly seven times the tokens of a standard session when teammates run in plan mode: each teammate has
  its own context. Use Sonnet for teammates, keep teams small and shut them down when done (E39).
- **Command-line tools over MCP servers:** `gh`, `aws`, `gcloud` and similar add no per-tool listing, so they are more
  context-efficient than a tool server, even with tool definitions deferred (E39).
- **Batch** takes half off input and output for work that can wait, and the vendor says it stacks with the cache multipliers,
  with best-effort cache hits inside a batch (E43).
- **Re-run failures, not everything:** when a checker can fail a result, the vendor measured running at `low` effort and
  re-running only the failures at `high` as cheaper than `high` throughout, at the same or a slightly better pass rate (E42).
