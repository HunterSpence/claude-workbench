# Token diet for Claude Code

What actually reduces Claude Code token spend, measured on Opus 5.5 and Sonnet 5.5 in headless
Claude Code sessions. These are one benchmark's numbers on one repo: measure your own before you
keep anything (section 5).

## 1. Know where your tokens go first

Method: take a couple of weeks of your own session logs, price every request at API rates, and
split the cost by token type: cache writes (context growth and cache misses), cache reads
(re-reading context on every call), thinking, code and tool-call arguments, and the prose the model
writes to you.

In typical heavy use, most of the cost is cache reads and writes, and very little is prose. So
"talk shorter" tricks can only touch a sliver. **Context size is the big lever.** Run `/usage`
and `/context` to see your own split before you change anything.

## 2. Free levers (built in, nothing to install or approve)

- `/clear` when you switch to an unrelated task. A fresh context is cheaper than dragging the old one.
- `/compact <what to keep>` before a long session gets heavy, and say what to keep.
- Hand exploration ("find where X is used", "read these 20 files") to a subagent. Only its summary
  comes back into your context.
- Use `/effort` deliberately. Routine edits rarely need the top level, and thinking is billed as output.
- Keep `CLAUDE.md` and everything it imports short: it is re-read on every call of every session.
- Leave MCP servers you aren't using disconnected, and leave MCP tool search on (it is on by
  default; don't set `ENABLE_TOOL_SEARCH=false`) so unused tool definitions stay out of context.

## 3. What this kit uses, and the plain-text alternative

The build personas (`flagship`, `implementer`) carry the ponytail text (MIT). On Opus it saves about as much as the plain-text block below; on Sonnet the
block saved more. To switch, replace the ponytail section of a persona with this block. It needs no
plugin, hook or marketplace approval:

> Be brief. Follow YAGNI: build only what is asked, and prefer the standard library and the
> simplest solution that meets every stated requirement. Never drop input validation, security
> checks, or error handling that prevents data loss. When asked to explain, teach, review, or
> write a procedure or runbook, be complete: keep every step and say why.

**In build sessions it is the big saver.** Tested on 12 one-line feature tickets in an open-source
FastAPI + React app, each a real headless Claude Code session, 2 reps each:
- Session cost fell 49% on Opus 5.5 (xhigh) and 31% on Sonnet 5.5 (high).
- The agent took 29-41% fewer turns, so it re-read its context less. That is where the saving
  comes from.
- Half the tickets invited over-building. On plain CRUD tickets the saving was smaller: 35% on
  Opus, 17% on Sonnet.
- Two blind judges found no measured loss in completeness and no security gaps (no endpoint
  exposed another user's data).
- Agents wrote about half as many test lines, though not much less often. **Ask for tests when you
  want them.**

**In single answers it is the safe option.** The bill changed by about -2.5% on Opus and about 0 on
Sonnet, with 0 failures, and every explanation stayed complete.

Alternatives measured in the same benchmark:
- **ponytail** (MIT plugin): about the same saving on Opus in build sessions (-53%), less on Sonnet
  (-23%). It made Sonnet 5.5 cost more on single answers, dropped explanation steps, carries about
  16 times the standing context of the block, and needs marketplace approval.
- **"be brief."** alone: 6-8% saved on single answers, but a third of its explanations missed a
  point and one runbook it wrote didn't work. Fine for code-only sessions.
- **caveman**: left explanations too terse for a junior reader.

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

Use `/usage` and `/context` in Claude Code, or `npx ccusage` (MIT) over your local session logs.
Compare one normal week with one week on the diet before you keep it. Before you trust a result,
check that the change was actually applied and that both weeks had comparable work
(`instructions/rules/verification.md`): a saving measured on the wrong workload, or with the
change silently not applied, is not a saving.
