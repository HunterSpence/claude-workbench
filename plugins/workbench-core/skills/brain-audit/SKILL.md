---
name: brain-audit
description: Read-only health check of the Claude Code configuration and knowledge base. Finds archives still inside discovery paths, backup files next to live config, dead @imports, routes to skills that do not exist, missing hook targets, credential-looking values in settings, vendor-owned rule files, path-scoped rules, managed settings in force, and an oversized always-loaded instruction surface. Use for "audit the setup", "check the KB", "brain-audit", "is the config clean", or after a big config or plugin change. Outputs a ranked fix list and applies nothing.
---

# brain-audit

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it
> appears unreplaced (the skill was copied in without the plugin), use `py -3` on Windows and
> `python3` on Linux, macOS and WSL, never the Microsoft Store `python` stub.

Report only; never edit. Fixes are a separate request.

## 1. Run the checker
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/audit.py" --project "$PWD"
```
Add `--json` for machine output, `--max-kb N` to
change the always-loaded warning threshold (default 40 KB), `--home DIR` to audit another config
dir. Exit code 1 means at least one CRITICAL or HIGH finding.

What it checks, and why each matters:
| Check | Why |
|---|---|
| Archive folders under `agents/`, `rules/`, `commands/`, `skills/`, project `.claude/` | These trees are discovered recursively: an "archived" persona or rule is still loaded |
| `*.bak*` next to live files | Read by nothing, grepped by everything; a backup of `settings.json` or `.claude.json` may hold credentials (CRITICAL) |
| Dead `@imports` and the always-loaded size | Every byte of CLAUDE.md, its imports (4 hops) and unconditional rules is paid on every turn |
| `/name` routes to skills that are not installed | An instruction that routes to a missing skill is unfollowable |
| Hook targets that do not exist | A missing target fails on every matching event |
| Credential-looking literal values in `settings.json` `env` | Settings files get copied, synced and shared; the checker prints the key name only |
| Read-only and path-scoped rules | A vendor upgrade can rewrite a read-only rule; a `paths:` rule is absent until a matching file is read |
| Managed settings present | They outrank everything here; never edit or work around them |

## 2. Delegate to tools that own their facts
- Knowledge base: if the workbench KB plugin is installed, run its health or audit command (see
  its `save` skill) and report its FAILs verbatim. Do not re-derive its caps here.
- Code graph or other installed auditors: run their own health command; a check that silently did
  not run reads as a pass, so a missing or failing tool is itself a MEDIUM finding.

## 3. Judgment checks the script cannot do
- **Contradictions:** two instruction files that state the same fact differently. Pick the owner
  file, make the other link to it. One fact, one home.
- **Stale facts:** dates, versions, model ids or hostnames typed into instructions. Prefer a pointer
  to the file or tool that owns the live value.
- **Warnings nobody can act on:** a check that fires every session trains everyone to skip
  warnings. Fix the check or fix the rule.
- In a fresh session, `/doctor` and `/status` show load errors and which settings sources apply.

## Output
One ranked table, CRITICAL and HIGH first, no padding rows:

| Severity | File | Finding | One-line fix |
|---|---|---|---|

End with counts by severity and: "Fixes not applied; this is report-only. Say 'fix these' to apply."
Any check that could not run gets its own MEDIUM row naming what was missing. **Never print a
credential value**: write `credential present at <file> -> env.<NAME>` and stop.
