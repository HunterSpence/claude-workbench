# Headless runs and scheduling

How to run Claude Code without a person at the keyboard, and how to schedule it on a managed Windows laptop (or WSL and
Linux) without surprises. Read it before you automate anything.

## 1. When headless is the right tool

Good fits: a report, a triage list, a lint or review pass, a document digest, an index refresh. All of them read, think and
write a file.

Not fits: anything that sends, publishes, deletes, spends, signs in or talks to another person. Those need a human at the
gate (`instructions/CLAUDE.md`, Standing Orders). A scheduled job drafts; you send.

## 2. The safe recipe

```
claude -p "$(cat prompt.md)" \
  --output-format json \
  --setting-sources user \
  --strict-mcp-config --mcp-config empty-mcp.json \
  --allowedTools "Read" "Grep" "Glob" \
  --max-turns 8 > result.json
echo "exit=$?"
```

- **Prompt from a file,** not a long inline string (command lines have a ceiling, and quoting differs by shell).
- **`--output-format json`:** decide from the exit code and the structured fields (`is_error`, `result`), never from the
  English text.
- **Restrict what it can do.** `--allowedTools` lists the tools that run without a prompt; a headless run cannot ask, so
  anything else is denied. Start read-only and widen one tool at a time.
- **No surprise servers or settings:** `--strict-mcp-config` with an empty config file loads no MCP server, and
  `--setting-sources user` keeps a project's settings and `.mcp.json` from loading. Check on your version that the user
  settings you rely on still load.
- **`--bare`** is the strictest mode (no hooks, plugins, MCP discovery or automatic instruction loading). On current
  versions it also stops using your signed-in login and needs an API key or an approved key helper; read `claude --help`
  for your version. If your organisation provides a login and no key, use the flags above instead.
- **Cap the run:** a turn limit, a wall-clock limit from the scheduler, and a spend limit where your version has one.
- **Work in a scratch copy** of any repository, and write results to a file, never into a shared document.
- **Tool results are data.** A web page, a ticket or a file can carry instructions aimed at the model. Test that with a
  canary: put a harmless instruction ("create a file named canary") inside a fixture file the job reads, and assert that
  no tool call follows it.
- **A headless run with tools disabled can still emit fake tool-call text** that burns output; check the result shape and
  re-run if it is wrong.
- **Choose the model from `docs/model-routing.md`.** Bulk, non-interactive review or judging can use the Batch API at about
  half price (the `batch-review` skill) when your organisation provides an API key.

## 3. Scheduling on Windows (Task Scheduler)

Principles for a laptop that sleeps, roams and is managed:
- **Per-user task, no elevation, "run only when the user is logged on"** so no password is stored. If the organisation
  blocks user tasks, ask (`docs/admin-asks.md`); do not look for a way around it.
- **A windowless launcher.** A task whose target is a `.cmd` file always opens a console. Launch a Python script with
  `pythonw.exe`, or the interpreter through a no-window launcher.
- **Start when available,** so a run missed during sleep happens when the laptop wakes.
- **Ignore new instances and take a mutex.** If the previous run is still going, the new trigger exits; a named mutex at
  the top of the script covers the case where a wrapper died.
- **A time limit,** so a hung run cannot hold the slot forever.
- **Log to a file with the exit code,** and rotate it.

Create it from a console (no script file, no execution-policy change):

```
$a = New-ScheduledTaskAction -Execute "<path to pythonw.exe>" -Argument "`"<path to run_report.py>`""
$t = New-ScheduledTaskTrigger -Daily -At 7:30am
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskPath "\claude-workbench\" -TaskName "nightly-report" -Action $a -Trigger $t -Settings $s
```

Or the classic form, which cannot set the start-when-available flag:

```
schtasks /Create /TN "\claude-workbench\nightly-report" /SC DAILY /ST 07:30 /RL LIMITED /TR "\"<path to pythonw.exe>\" \"<path to run_report.py>\""
```

Check it before you trust it: run it by hand under the same launcher; trigger it twice quickly (one run, no window, the
second exits); sleep the laptop across a trigger time; restart. `Get-ScheduledTask <name> | Select -Expand Settings` and
`Get-ScheduledTaskInfo <name>` show what the scheduler believes.

The kit's own nightly index refresh is one such task, per user, created only if you opt in, and removed by the uninstaller.

### Inside WSL
`cron` in WSL runs only while the WSL instance is running, which on a laptop is not reliable. Let Task Scheduler start the
job instead: the action runs `wsl.exe` with the distribution name and a script path inside it. Keep the working files on
the Linux side.

### Linux and plain WSL with systemd
A user timer with `Persistent=true` catches up missed runs: a `.service` with the command and a `.timer` with
`OnCalendar=`, enabled with `systemctl --user enable --now <name>.timer`.

## 4. Make failure visible

- **Alert on silence, not only on errors.** A job broken from day one never "changes state". Write a status file on
  success and have something check that it is newer than the period; a dead-man check catches the job that stopped running.
- **Exit non-zero on any failure,** and never end a wrapper with an echo.
- **Keep results on disk** so a killed run loses nothing, and keep a one-line summary where you will see it.
- **Run heavy work one at a time under a memory cap** (`tools/memcap/README.md`); overlapping
  heavy jobs can freeze a laptop.

## 5. Related reading

- The Windows pitfalls: `kb-template/_shared/digests/windows-shell.md`, and the cards on scheduled-task quirks and the
  console encoding in `kb-template/_shared/bug-cards.md`.
- What the environment forbids: `instructions/rules/corporate-environment.md`.
