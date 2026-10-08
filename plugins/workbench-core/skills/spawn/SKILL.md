---
name: spawn
description: "Action card for any Agent() call: pick the agent, then write a prompt the subagent can execute without your context. Use before delegating anything, especially work that depends on project knowledge, hosts, money or anything the subagent cannot see."
---

# /spawn: action card

**0.** Think-then-build (fix, build, refactor, migrate)? Load the `cascade` skill first; it runs the phases.

**1-3. Pick the agent.** Use the personas installed with this kit (`flagship`, `implementer`,
`researcher`, `ops-runner`, `security-auditor`, `red-team`, `green-team`, `blue-verify`) or the
built-in `general-purpose`. Each persona pins its own model and effort; pick the persona, never a
`model:` override. Never fork. The built-in `Explore` and `Plan` agents receive none of your
CLAUDE.md or rules, so never use them for anything touching hosts, money, credentials or policy.

A new persona earns its file only when it has a structural property a prompt cannot supply (a
`model:` or `effort:` pin, a tool restriction, a `skills:` preload, hooks) and real usage behind
it. Restrict a persona with `disallowedTools:`, not a `tools:` allowlist: an allowlist silently
drops tools you did not name (Grep, Glob, Skill, every MCP server). Agent folders are scanned
recursively, so archive a persona by moving it OUT of the agents tree.

**4. Prompt: the one worker-prompt template** (`cascade`, `ratchet` and `handoff` point here).
Subagents load CLAUDE.md and rules but NOT your conversation. Paste what they need; drop lines that
do not apply:
```
IN-FLIGHT (as of <time>): <1-5 live lines: open PR, today's decision, pending gate>
ROLE: <persona> - <one mission sentence>
CONTEXT: read <files or KB notes, absolute paths>; search more with <command>
FILES: you touch ONLY <absolute paths>. FORBIDDEN: <paths>. Unsure where a file is -> Glob first.
TEMPLATE: <worked example of the output, when it has a shape>
CONSTRAINTS (priority order; when two conflict, the earlier wins): <each stated here, not only in a file>
PRE-AUTHORIZED (do not stop to ask): <...>  FORBIDDEN (do not do): <...>
ENVIRONMENT: <OS and shell; path style; no foreground sleep (use background runs); how /tmp maps>
TASK: <task>
Do the work yourself; never fork or spawn.
RETURN CONTRACT: at most <N> words: what changed, measurements, uncertainties; evidence (file:line
  or output) per claim, each labelled VERIFIED / PLAUSIBLE / ASSUMED; your persona. No dumps.
End with ## DISCOVERIES (domain / note / observation) or "- none".
```
Lanes on the most capable models follow pointers well. Faster lanes (`implementer`, `green-team`,
`general-purpose`) need the spec, owned and forbidden files, acceptance test and every hard fact
pasted INLINE: a smaller model does not reliably open a file it was merely pointed at, so a
constraint missing from its own prompt does not exist for it.
