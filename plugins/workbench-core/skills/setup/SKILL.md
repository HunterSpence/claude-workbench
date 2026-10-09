---
name: setup
description: "Provision this machine for the workbench and keep it healthy: install, doctor, backup, profiles."
disable-model-invocation: true
---

# /workbench-core:setup

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it appears
> unreplaced, use `py -3` on Windows and `python3` elsewhere, never the Microsoft Store `python` stub.
> `SETUP` below means `"<python>" "<workbench home>/kit/bootstrap/setup.py"`, where the workbench home is
> `<CLAUDE_CONFIG_DIR or ~/.claude>/workbench`. `PROFILE` is `profile.py` in the same folder.

## Hard stop rule (read first)
A hook, permission, gateway or policy denial, a declined UAC prompt or an HTTP 403 from a proxy means STOP: quote
the message to the user word for word and report it. Never retry by another route, tool or shell, never change an
execution policy, never elevate on your own. Setup's own UAC request is the only elevation, and the human clicks it.

## Commands
| Goal | Run |
|---|---|
| Show what this machine can do, before anything installs | `SETUP report run --phase pre` |
| Provision in the background (report first, then installs) | `SETUP run --detach [--with nightly,capture,ctx,...]` (also installs the Playwright CLI when Node.js is there) |
| Poll it (returns early when the phase changes) | `SETUP status --json --wait 60` |
| Only plan (installs nothing) | `SETUP plan`, then read `<workbench home>/state/plan.md` |
| After the WSL reboot (normally automatic at sign-in) | `SETUP resume` |
| Which tools are behind their tested version (changes nothing) | `SETUP update --check`, then read `<workbench home>/state/update.md` |
| Move the tools setup installed to the tested versions | `SETUP update` (`--with update-latest`: the newest instead); a run does it after verify unless `--no-update` |
| Health check (exit 0 ok, 1 warnings, 2 errors) | `SETUP doctor` (`--bundle support.zip` for IT: redacted); rows `updates` and `claude startup warnings` included |
| Backup / restore drill | `SETUP backup`, then `SETUP restore <zip> --to <empty folder>` |
| Undo machine changes (task, RunOnce, env vars, Git key, PATH shim) | `SETUP undo-config`, then `--apply` |
| Per-client profile | `PROFILE create <name>` · `PROFILE list` · `PROFILE launch <name>` · `PROFILE remove <name>` |

## How to drive a run
1. Run the report and show the user its summary before anything else.
2. `SETUP run --detach`, then poll `SETUP status --json --wait 60` until `running` is false. Tell the user the
   phase in one short line each time; do not narrate every poll.
3. Read `exit_code`: 0 done · 3 done with ask-IT items · 4 a step failed · 5 waiting on a human (reboot) · 2 setup
   was already running or the environment is wrong.
4. For every `ask_it` entry, show its draft text so the user can send it to IT. For every `failed` entry, show the
   one-line error; do not work around it.
5. When the phase is `knowledge`, show `<kit>/bootstrap/infosec-note.txt` to the user once (setup logs it too).
6. Finish with `next` from the state (often `/workbench-core:onboard`).

## Never
- Run `SETUP run` in the foreground from a session: it can take an hour; always `--detach` and poll.
- Edit managed settings, policy keys or `.env` files, or turn on an opt-in (`--with`) the user did not ask for.
- Update a tool IT or the user installed: `update` lists it as it-managed and leaves it. A tool in use (git, PowerShell,
  Node.js, Claude Code) is deferred: show the user the command from `update.md`, never close their programs. `claude update`
  stays the user's choice. A denied update is an ask-IT item: quote it, do not retry.
- Put `CLAUDE_CONFIG_DIR`, a git repository or the knowledge index inside OneDrive (doctor fails on each).
