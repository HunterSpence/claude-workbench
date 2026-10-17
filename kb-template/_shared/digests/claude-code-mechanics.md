---
title: Digest, Claude Code mechanics
domain: _shared
status: active
---
# Claude Code mechanics: lessons that keep recurring

Read this before changing a hook, a persona, a settings file or an instruction file, or before interpreting what a
session did.

## What loads when
- **Hook configuration and agent definitions are snapshotted at session start.** A changed timeout or a new persona
  reaches only new sessions. Verify an edit in a fresh headless run, never in the session that made it.
- **Hooks come from plugins as well as the settings file.** Audit both when chasing latency or a surprise.
- **A hook with a short timeout silently loses its output under load.** Keep hooks fast, raise the timeout, and verify
  injection per session instead of assuming it.
- **Always-loaded instructions are re-read on every call.** Their size is a recurring cost, and a new rule should cost
  a demotion elsewhere. Rules scoped by `paths:` vanish after compaction until a matching file is read, so a rule that
  must always bind is never path-scoped.
- **Compaction keeps what you tell it to.** Name the files, the open errors and the next step to preserve.
- **Subagents inherit the instruction files except the built-in Explore and Plan agents.** Paste the constraints a task
  needs into its prompt, and use a general-purpose agent for anything touching infrastructure, credentials or money.

## Models and effort
- **Effort resolves from the persona's frontmatter,** then the model's saved setting, then the global setting; a flag
  or environment variable outranks all three. A subagent runs at its own model's effort, not the session's.
- **A fallback model silently changes who produced a verdict.** Gate-type personas open their verdict with the model id
  they ran as.
- **Organisation limits win.** An allow-list may substitute a different model for a blocked one; on "model not
  allowed" step down the chain in the routing table instead of retrying.
- **Defaults differ between the API and Claude Code,** so a persona that relies on a default may run one level lower than
  expected. Set `effort:` explicitly.

## Permissions and the shell
- **Compound and inline commands prompt.** The checker evaluates every segment and cannot inspect `-c` strings. Write
  multi-step logic to a script file and keep allow rules specific.
- **Auto mode discards broad Bash and PowerShell allow rules** and sends the command to a classifier.
- **Hook and permission denials are not errors.** Counting them inflates the error list; read them as the controls
  working, and a denial is a stop, not a puzzle to route around.
- **Hand edits to a generated or reconciled settings file do not stick.** Edit the source of truth and regenerate.

## Reading and editing
- **Whole-file reads of big files fail.** Grep for the region, then read with an offset and a limit.
- **Edits fail when the file changed since the read.** Re-read just before editing, and keep edits small on files other
  sessions touch.
- **Invented paths** are rebuilt from memory. Search for the file name first.
- **Background work is reaped.** A waiter killed with its parent loses nothing only if results were written to disk.
- **After a bulk edit, prove nothing was lost.** A sweep, a scripted find-and-replace or a re-applied filtered diff can
  drop original lines: count the lines kept and re-run the health checks, because an inserted line shifts any pointer
  that names a line, and pairing each removed line with the next added one misses hunks with two removals in a row.

## Reading transcripts and logs
- **Transcripts write one line per content block under the same message id.** Take the maximum usage per id or
  output is undercounted.
- **Subagent transcripts live in a separate subtree.** Use a recursive glob or the totals miss the subagents.
- **Match the error shape, not a word.** Analysis scripts print the very error strings they search for.

## Headless runs
- **A headless run with tools disabled can still emit fake tool-call text** that burns a large output budget; detect it
  and re-run. A narrower setting-sources flag can drop user-level settings you expected.
- **`--bare`, strict MCP configuration and restricted modes are the safe defaults for unattended runs;** see
  `docs/headless-and-scheduling.md`.

## Cost
- **Most spend is cache reads and writes,** so context size is the lever. Clear between unrelated tasks, hand exploration
  to a subagent, and let a short idle gap pass only if the next turn can afford a cold cache.
- **Lower effort on the same model is usually cheaper than switching models,** and brevity instructions are safe for
  code but cut explanations and runbooks short.
