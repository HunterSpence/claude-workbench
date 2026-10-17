# Authoring: skills, agents, hooks, permission rules and rule files

How to write each kind of kit part and, as important, how to test it. Read it when you add something of your own. Your
own parts go in your user folder (or a project's `.claude` folder); the kit copy is replaced by the next release.
Layout and precedence: `docs/HOW-WE-WORK.md`.

The one habit that applies to all of them: **a part is not finished until one runnable check fails when it breaks.**

## 1. Skills

A skill is a folder with a `SKILL.md`: frontmatter, then the instructions. Examples to copy from:
`plugins/workbench-core/skills/cleanup/SKILL.md` (user-invoked only) and `plugins/workbench-core/skills/spawn/SKILL.md`.

```
---
name: my-skill
description: "Do X when Y. Use for A, B and C. NOT for D."
disable-model-invocation: true      # only when it must run on request, never on its own
---
# /plugin:my-skill: one line on what it does
Steps, safety rules, and where its scripts and references are.
```

- **The description is the trigger.** It decides whether Claude picks the skill, so lead with what the user would say
  and add "NOT for ..." for the near misses. A new kit skill's description stays within 300 characters, and the total
  across every kit skill within 16,000 (`py -3 tools/test_docs.py --budget` prints both).
- **`when_to_use` is the second trigger line, and it names a moment, not a topic.** It is appended to the description in
  the skill list and counts toward the same budget. Keep it to 90 characters or fewer. Write "ALWAYS load before <what the
  user is about to do>" for a skill that must not be skipped (the cases where Claude would otherwise answer from memory),
  and "Load before ..." for one that is merely useful. Do not repeat the description, and do not use it to widen the skill to
  near misses; those belong under "NOT for" in the description.
- **User-invoked only** (`disable-model-invocation: true`) for anything that deletes, publishes, spends or drives
  another person's machine.
- **Keep the body short.** Put long material in `references/*.md` and load it on demand; put code in `scripts/` and
  call it by relative path. List Python packages in a `requirements.txt` beside the skill.
- **Say what it must never do** in the first screen, for example write a credential value.
- **Name evidence labels** (verified, plausible, assumed) wherever the skill reports findings.

Test it:
1. Read the frontmatter back: the name, the length of the description, the flags.
2. Trigger test: write five prompts that should start it and five near misses that should not, run each in a fresh
   headless session (`claude -p`), and read the transcript for the skill call. To measure it on sessions you already have,
   put the same prompts into a probe file and run `tools/skill-probe/skill_probe.py` (guide 51): it counts, offline, how often
   each kind led to a `Skill` call and never prints your prompts.
3. Run its scripts under their own `unittest` file, with a bad input for every branch.
4. Scan it before installing it anywhere else: the `skill-scan` skill, then
   `py -3 tools/test_docs.py --deny <skill folder>` for personal strings and stray dates.

## 2. Agents (personas)

An agent is one Markdown file in an `agents` folder. Copy `plugins/workbench-core/agents/red-team.md`.

- **Frontmatter:** `name`, a `description` that says when to spawn it and when not to, `model` as a full model id (never
  a bare alias, which can resolve to an older generation on some providers), `effort`, `disallowedTools` (a verifier
  and an attacker get no Write or Edit), and a `color`.
- **Body:** the role in one line, the habits that matter, the facts it reads first, and a return contract (a short
  reply, evidence for every claim, a discoveries block at the end).
- **Keep the role-to-model mapping fixed** so findings stay attributable. A gate persona opens its reply with the model
  id it ran as, so a silent fallback is visible.
- **Organisation limits win** over the model and effort in the file.

Test it: agent files are read at session start, so start a **new** session, check it appears in `/agents`, then run
`claude -p --agent <name> "print your rules"` and confirm the model line, the tool limits and the return contract. Do
the same after every edit.

## 3. Hooks

A hook is a command that Claude Code runs on an event and feeds a JSON payload on stdin. The kit registers its hooks in
`plugins/workbench-core/hooks/hooks.json`; the scripts are in `plugins/workbench-core/scripts/`, and
`plugins/workbench-core/scripts/_wb.py` holds the shared path and file helpers.

- **Read stdin as UTF-8 that tolerates a byte-order mark** (`utf-8-sig`), and never raise: a crash is logged and the hook says
  nothing.
- **Say nothing, or print one JSON object,** and always exit zero unless the event defines another meaning. Know whether
  your hook fails open (default) or closed, and write the reason in the file.
- **Keep it fast.** A hook runs on every matching call. Do not start PowerShell, probe for interpreters or touch the
  network; a short timeout silently drops a slow hook's output.
- **Write atomically** (a temp file, then replace) and never to a path another session writes; journal instead.
- **Log the hook id with every caught exception,** with credential shapes redacted.
- The change takes effect in the **next** session.

Test it: pipe a sample payload into the script and assert the exit code and the output, including a payload with a
byte-order mark and one with a missing field:

```
printf '{"tool_name":"Bash","tool_input":{"command":"echo hi"}}' | python plugins/workbench-core/scripts/<hook>.py; echo $?
```

Then add the case to `plugins/workbench-core/scripts/tests/test_hooks.py`, the pattern to follow.

## 4. Permission rules

Permission rules are the kit's blocking control: `permissions.ask` in the settings profiles, plus one deny rule the
installer adds so only the save driver writes `active-context.md` (Edit/Write tools; a shell write is not stopped)
(`settings/SETTINGS.md`). Deny beats ask beats allow, in every mode.

- **A rule matches command text, not intent.** `Bash(git push *--force*)` asks before that text appears in a command; an
  alias or a script that hides the text goes past it. Write what the text looks like, and list what a rule cannot see in
  `docs/known-limits.md`.
- **Cover both shells.** The same pattern goes in once as `Bash(...)` and once as `PowerShell(...)`.
- **Path rules exist for `Edit(...)` and `Read(...)` only.** A path rule for `Write` or `NotebookEdit` is accepted and never
  consulted. Windows paths match in POSIX form (`C:\Users\name` is `//c/Users/name`).
- **A trailing ` *` also matches the bare command,** so `Bash(npm publish *)` covers `npm publish` too.
- **Test both ways:** a command that must ask, and a near miss that must not (`git push origin main` against a force-push
  rule). Run both in a scratch session before the rule ships.

## 5. Rules and instruction files

- One topic per file; every rule says why. Facts have one home: link to the owner instead of repeating.
- A rule that must always bind is never path-scoped (`paths:` frontmatter), because it disappears after compaction.
- Always-loaded files have a hard budget; a new rule costs a demotion elsewhere (`py -3 tools/test_docs.py --budget`).
- **Write `@` imports without quotes.** A path inside quotes is not imported, and a space in a path must be escaped with
  a backslash. Check what loaded in the Memory files list of `/context`.
- Test it by asking a fresh session a question the rule answers, and by deleting the rule to see the answer change. For the
  kit's red lines, `tools/rules-quiz/rules_quiz.py` (guide 51) puts four scenarios to a session and grades the saved replies:
  under nine of ten means reword the rule.

## 6. Knowledge-base notes and bug cards

- Notes: one fact, one home, front matter with a title, domain and status. `kb-template/README.md` has the layout and the
  folder taxonomy.
- Bug cards: add the next numbered card to `kb-template/_shared/bug-cards.md` with all five fields (symptom, root cause,
  fix, verifying test, how to spot it fast). Add a detector to `kb-template/_shared/bug-detectors.json` only when the
  error text is specific; it is tested against its sample and against unrelated errors.
- Keep names, hosts, dates and numbers out; describe the class, not the incident.

## 7. Before you share anything

Run both scanners on what you will publish:

```
py -3 tools/test_docs.py --deny <paths>
py -3 tools/scrub_scan.py --denylist <your private term list> <paths>
```

The first rejects provenance lines, hex runs, dates and (in knowledge files) numbers. The second
rejects personal identifiers and fails when it skips a directory it was asked to scan. Fix the text, not the scanner.

## 8. What to run, by kind

| Part | Smallest check | Command or place |
|---|---|---|
| Skill | trigger prompts, script tests, description budget | headless `claude -p`; `tools/skill-probe/skill_probe.py`; `py -3 tools/test_docs.py --budget` |
| Agent | fresh-session run of the persona | `claude -p --agent <name> "print your rules"` |
| Hook | piped payloads, including a malformed one | `plugins/workbench-core/scripts/tests/test_hooks.py` |
| Permission rule | one command that must ask and one near miss that must not | a scratch session |
| Rule file | budget and a fresh-session question | `py -3 tools/test_docs.py --budget`; `tools/rules-quiz/rules_quiz.py` |
| Note or card | search finds it; detector tests | `py -3 -m unittest discover -s tools -p "test_docs.py"` |
