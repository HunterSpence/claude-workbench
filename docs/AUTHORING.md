# Authoring: skills, agents, hooks, guards and rules

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
- **Say what it must never do** in the first screen: no credential values, no outbound message without approval,
  no bypassing a control.
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

- **Read stdin as UTF-8 with a byte-order-mark guard** (`utf-8-sig`), and never raise: a crash is logged and the hook says
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

## 4. Guards (PreToolUse rules)

Guards are rules inside one engine, `plugins/workbench-core/scripts/guards/engine.py`, which parses the shell command once
and runs the rule packs: `rulepacks/generic.py` (safety rules that mean the same everywhere) and `rulepacks/corporate.py`
(rules driven by your organisation's allowlist, whose template is
`plugins/workbench-core/scripts/guards/corporate-allowlist.template.json`). The corporate pack's ids include
`prod-build` (no build or deploy over ssh to a host in `production_hosts`), `protected-db-write` (no SQL write to a
table in `protected_db_tables`), `security-tooling-change` and `publish-confirm`; an empty key means no opinion. The
GitHub write verbs that `publish-confirm` asks about live in one list,
`plugins/workbench-core/scripts/guards/gh_write_verbs.json`.

- **A rule is a function of the parsed call.** It does nothing when the call is fine, calls the engine's block helper with
  a message, a guard id and a detail to deny, or the ask helper to ask. A deny outranks an ask. A guard never returns
  "allow" and never rewrites a tool's input. An allow only skips the prompt for a call no rule covers; deny and ask rules
  still apply whatever a hook returns, so a guard adds checks and grants nothing.
- **Put the rule in a pack's tuple** for its tool kind: shell, write, read or tool. Each rule is its own unit, so a crash in
  one skips only that rule and is logged.
- **The message tells the agent what to do instead,** with the exact command where one exists. A denial is a stop, not a
  puzzle: the agent must report it, not retry in another shape.
- **Blind spots are the norm.** Prose that merely mentions a command is not the command; heredocs, runner strings
  (`ssh host '...'`, `bash -c`) and encoded commands need the engine's helpers.
- No log-only mode and no switches the agent can reach; a misfiring rule is switched off by disabling the plugin.

### Writing a rule that holds

- **Regex boundaries: say what may not touch the word, not what must.** A plain `\b` treats `-` and `.` as boundaries, so
  `\bpush\b` also fires on `git-push-helper` and on a file called `push.md`. Use a lookbehind and lookahead that name the
  characters that would make it a different word, such as `(?<![\w.-])push(?![\w.-])`, and match case-insensitively
  (Windows names and `.EXE` arrive in any case). Do not anchor with `^` unless the rule is about the start of a statement:
  the same command also arrives after `&&`, `;`, `|`, `$(` and `cd x &&`. Give every pattern three samples: a hit after
  `&&`, a hit as a full path (`/usr/bin/tool`), and a longer word that must pass.
- **Readers that execute commands.** A command that looks like a reader can run anything its flags name: `find -exec`,
  `xargs`, `awk` with `system(`, GNU `sed` with the `e` command, `rg --pre`, `tar --to-command` and
  `--checkpoint-action=exec`, and any reader piped into an interpreter (`Get-Content f | Invoke-Expression`). A rule about
  what a command reads must look at the flags and at what follows a pipe, not just at the first word.
- **Why a read-only exemption for executing readers fails.** "Reading is safe, so let `find` through" keys on the command
  name, and the name cannot see the flags. Once the name is exempt, every flag and every pipe on it is exempt too, and the
  executing form walks through unseen. The fix is to exempt an exact argument shape (these flags, no pipe) and keep the
  deny on the executing flags, or to drop the exemption. Any exemption you add needs its own negative control: the same
  command with an executing flag must still be refused.
- **Write guard tests with the Write tool, not a shell heredoc.** A guard test contains the very strings the guard exists to
  catch. Typed into a shell command, the string passes through the shell's quoting (and, for Python, a second layer), so the
  sample you test is not the sample you meant, and a guard can refuse your own command. The file tool writes the bytes
  exactly. Build credential-shaped values at run time (two string pieces joined) so no literal sits in the file, and run the
  file, not an inline `python -c` copy of it.
- **Measure before you block a host.** A deny or ask on a host people already use trains them to approve without reading.
  Before a rule that names hosts ships, replay your own past tool calls through it (`tools/guard-replay/guard_replay.py`,
  guide 50) and read three numbers: how many calls it would have refused, how many it would have asked about, and how many
  of those were calls you wanted. Match the host exactly, not by suffix. Prefer an ask to a deny until the number is small.

Test it with two controls in `plugins/workbench-core/scripts/guards/tests/test_guards.py`: a **positive control** that
must block (built from invented commands and placeholder paths, with secret shapes assembled at run time) and a
**negative control** that must pass, then run the suite:

```
python -m unittest discover -s plugins/workbench-core/scripts/guards/tests
```

Then prove the test can fail: take the rule out in a scratch copy and confirm the positive control now fails. Last,
replay your own history through the changed pack (guide 50) and read the "looser" count first.

## 5. Rules and instruction files

- One topic per file; every rule says why. Facts have one home: link to the owner instead of repeating.
- A rule that must always bind is never path-scoped (`paths:` frontmatter), because it disappears after compaction.
- Always-loaded files have a hard budget; a new rule costs a demotion elsewhere (`py -3 tools/test_docs.py --budget`).
- **Write `@` imports without quotes.** A path inside quotes is not imported, and a space in a path must be escaped with
  a backslash. Check what loaded in the Memory files list of `/context`.
- Test it by asking a fresh session a question the rule answers, and by deleting the rule to see the answer change. For the
  kit's red lines, `tools/rules-quiz/rules_quiz.py` (guide 51) puts twelve scenarios to a session and grades the saved replies:
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
| Guard | one positive and one negative control, then a replay of past calls | `plugins/workbench-core/scripts/guards/tests/test_guards.py`; `tools/guard-replay/guard_replay.py` |
| Rule file | budget and a fresh-session question | `py -3 tools/test_docs.py --budget`; `tools/rules-quiz/rules_quiz.py` |
| Note or card | search finds it; detector tests | `py -3 -m unittest discover -s tools -p "test_docs.py"` |
