# Understand permission modes and cut the prompts you can

Automates it: none (settings are yours to change; Claude does not edit them)

## When to use
Claude asks to approve too many commands, a mode you expect will not start, or a permission rule stopped a command and you
want to know whether it is a prompt you can tune or a deny you cannot.

## Steps
1. See what applies. In Claude Code run `/status`: the `Setting sources` line names every settings file, including a
   managed one. A managed value always wins over anything below.
2. Know the two kit profiles (`settings/SETTINGS.md`). **corporate** (default) asks before anything beyond reads and
   turns bypass mode off. **permissive** starts in bypass mode with broad allow rules; your organisation may disable that mode,
   and then Claude Code will not enter it.
3. Want no prompts for ordinary commands on the corporate profile? Tell Claude "turn off the bash approvals": the
   kit-update skill runs `kit_update.py set --approvals off`, and new windows start without command
   prompts. "Turn on approvals again" undoes it. Details: `settings/SETTINGS.md`, "Command approvals".
4. Know what never changes: the kit's ask rules (a force push, a repository delete, a release delete) prompt even in bypass
   mode, and the deny on the knowledge base's `active-context.md` applies in every mode.
5. Cut routine prompts: allow commands one pattern at a time in your user settings, for example `Bash(git status *)`,
   `Bash(git diff *)`, `Bash(git log *)`. Edit the file by hand or with `/permissions` or `/config`.
6. Treat a deny differently from a prompt: it is a stop. Read it, do what it says, and never retry the same
   action in another shape.

## Verify
- Run `git status` through Claude: no prompt. Ask it to run `git push --force` in a scratch repository: it still asks.
- `/status` still lists the same managed source as before.

## Common failures
- **Bypass mode will not start:** a managed `permissions.disableBypassPermissionsMode` is set. That is policy; ask only
  through guide 03.
- **Your allow rules are ignored:** a managed `allowManagedPermissionRulesOnly` ignores user rules, and allow rules have
  no effect inside bypass mode.
- **The prompt returns for a long command:** a rule matches the command as written, so a chained or wrapped command does
  not match a rule for its first part. Allow the plain command.
- **A rule asks before a force push or a delete:** the rules are listed in `settings/SETTINGS.md`.
