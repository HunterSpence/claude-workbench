# Keep token use low

Automates it: none (built-in commands, plus `tools/token-split/token_split.py` for the cost split; measurements in `docs/token-diet.md`)

## When to use
Sessions hit usage limits early, or a long session gets slow and expensive. Most of the cost is the context being re-read
on every call, so the lever is context size, not shorter answers.

## Steps
1. Look before you change anything. In Claude Code run `/usage` and `/context`. Note the numbers. For the split of your own
   spend by token class run `py -3 <KIT>/tools/token-split/token_split.py`; it reads usage fields from your local transcripts,
   never their text, and shows how much goes to cache reads and writes, thinking, prose and tool-call arguments.
2. Switch tasks with `/clear`. A fresh context is cheaper than dragging an unrelated one along.
3. Before a long session gets heavy, run `/compact <what to keep>` and say what must survive. Save notes first (guide 10).
4. Send exploration to a subagent ("find where X is used", "read these 20 files"). Only its summary returns to your
   context (guide 09).
5. Use `/effort` on purpose. Routine edits rarely need the top level; thinking is billed as output. To cut thinking, lower
   the effort: Claude Code cannot turn it off on the current models, and on Haiku 5.5 the vendor found, in its own testing,
   that telling the model to answer directly did not stop it thinking. Set the level at the start of a task: on some setups
   (Bedrock, Google Cloud, a gateway, older models) a mid-session change makes the next request re-read the conversation
   uncached, and Claude Code asks you to confirm (`docs/token-diet.md`).
6. Protect the prompt cache. A model switch, a tool server joining or leaving when tools load upfront, compaction and a pause
   longer than the cache lifetime make the next turn re-read everything; an effort change does not on Opus 5.5, Sonnet 5.5,
   Haiku 5.5 and Fable 5.1 with an API key or a subscription. The main conversation's cache lives one hour on a subscription
   within plan usage and five minutes otherwise, subagents' five minutes (E37, fetched Oct 2026; `docs/token-diet.md`, section 8).
   Read your own hit rate on the `Prompt cache (main)` line of `/usage`, and run `/insights` to see how you work. Agent teams
   cost about seven times a standard session, and command-line tools beat tool servers on context (E39).
7. Keep always-loaded files short: your `CLAUDE.md` and everything it imports are re-read every call. Check the kit's
   budget with `py -3 <KIT>/tools/test_docs.py --budget`.
8. Check what a session costs before you type anything: run `py -3 <KIT>/tools/token-split/token_split.py startup`. A long skill
   listing is part of it, and a listing over budget silently drops skill descriptions; `/doctor` shows the listing's estimate
   and its biggest contributors (`docs/token-diet.md`, "The skill listing").
9. Leave MCP servers you are not using disconnected and keep tool search on (do not set `ENABLE_TOOL_SEARCH=false`).
10. Measure again after a normal week, with comparable work. `docs/token-diet.md` explains what was measured, what to skip,
   and which popular tricks cost more than they save. `<KIT>` is the kit folder (guide 01).

## Verify
- `/context` shows a smaller starting context than step 1, or `/usage` shows a lower weekly total for comparable work.
- A second run of `token_split.py` over a comparable stretch shows a smaller share in the class you targeted.
- `py -3 <KIT>/tools/test_docs.py --budget` exits 0.

## Common failures
- **"Be brief" instructions made explanations worse:** they are safe for code-only work and wrong for explanations and
  runbooks. Do not apply them there.
- **`token_split.py` names a model it cannot price:** the price table does not list that id. Add it, with its vendor evidence
  row, to `settings/model-evidence.json` (`docs/models.md`, "Keeping it current"), or ignore that line of the report.
- **Tokens still climb:** a tool server or a pasted log keeps re-entering context. Compact, or restart with `/clear`.
- **A saving that vanished:** check the change was applied at all and that both weeks had similar work before you believe it.
- **A tool proxy with default telemetry:** read its README first; every call would pass through a third party.
- **A fan-out stops mid-run on a Team or seat-based Enterprise seat:** the five-hour and weekly allowance is the ceiling.
  Past it you need usage credits, which an admin enables, with spend limits for the organisation, for a member and, on
  Enterprise, for a group. Ask which tier you hold and whether credits are on (`docs/admin-asks.md`), or plan the work
  around the windows.
