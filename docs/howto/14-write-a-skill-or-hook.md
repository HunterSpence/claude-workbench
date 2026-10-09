# Write your own skill or hook, with a test

Automates it: none (the rules are in `docs/AUTHORING.md`)

## When to use
You repeat a procedure often enough to write it down (a skill), or want something to run on a Claude Code event (a hook).
Put your own parts in a `skills` folder under your Claude configuration folder (or a project's `.claude` folder), never in
the kit copy: the next release replaces that. `<KIT>` is the kit folder (guide 01).

## Steps
1. **Skill.** Make a folder with a `SKILL.md`: frontmatter with `name` and a `description` that leads with what you would say
   ("Do X when Y. Use for A, B. NOT for D."), then short steps. Mark `disable-model-invocation: true` for anything that
   deletes, publishes or spends. Put long text in `references/` and code in `scripts/`. Copy the shape of
   `plugins/workbench-core/skills/cleanup/SKILL.md`.
2. Say what it must never do in the first screen: no credential values, no outbound message without approval, no bypassing a control.
3. **Hook.** A hook is a command that reads one JSON event on stdin and prints nothing or one JSON object. Read stdin as
   UTF-8 and never raise; decide whether it fails open or closed and write that in the file; keep it fast; write
   atomically. A change applies in the next session.
4. Test the hook by piping an event into it:
   `printf '{"tool_name":"Bash","tool_input":{"command":"echo hi"}}' | python <your-hook>.py; echo $?`
   Add a case with a missing field. The pattern to copy is `plugins/workbench-core/scripts/tests/test_hooks.py`.
5. Test the skill: five prompts that should trigger it and five near misses that should not, each in a fresh
   `claude -p` session, reading the transcript for the skill call.
6. Scan before sharing: run `/workbench-core:skill-scan`, then `py -3 <KIT>/tools/test_docs.py --deny <your folder>` for stray dates and
   hex strings, and `py -3 <KIT>/tools/scrub_scan.py <your folder>` for personal identifiers.

## Verify
- The skill appears in `/skills` in a new session, and a trigger prompt calls it while a near miss does not.
- The hook test exits with the code you set for good, malformed and empty input.
- Both scanners exit 0.

## Common failures
- **The skill never triggers:** the description is vague. Lead with the user's words and name the near misses.
- **The hook does nothing:** it is read at session start. Open a new session, and remember a crash is logged, not shown.
- **A hook slows every call:** it started PowerShell or touched the network. Hooks run on each matching call; keep them cheap.
- **A guard or rule file:** these need positive and negative controls and a budget check; read sections 4 and 5 of `docs/AUTHORING.md` first.
