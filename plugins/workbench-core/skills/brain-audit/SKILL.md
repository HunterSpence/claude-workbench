---
name: brain-audit
description: "Read-only health check of the Claude Code setup and knowledge base: stale archives, backup files, dead @imports, missing skill or hook targets, credential-looking settings, oversized always-loaded files. Use for \"audit the setup\", \"brain-audit\" or after a config change."
when_to_use: "ALWAYS load when instructions, hooks or the KB seem stale, ignored or contradictory."
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
| Hidden skills | A route to a skill that `skillOverrides` sets to `user-invocable-only` or `off` cannot be followed by the model (see 1b) |
| A CLAUDE.md or an unconditional rule over 200 lines | The documented target is under 200 lines per CLAUDE.md file; longer files reduce adherence |
| The same long line in two places | One fact, one home; the report gives `file:line` and a digest, never the text |
| A file that says it is generated from another file | Flags it when the source is newer by a day or more, or gone |

### 1b. The instruction surface, as data
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/audit.py" --surface --json --project "$PWD"
```
Prints `{"surface": {...}, "exit": 0|1}` and exits with that code (`--max-lines N` changes the 200-line target). Keys:
`bytes` (always loaded), `core_lines` (longest CLAUDE.md), `rules_over_cap`, `paths_rules` (information only: those load
on demand, and again after `/compact` only once a matching file is read), `duplicates`, `dead_refs` (imports and routes),
`generated_drift`, `hidden_skills`. Exit is 1 when anything but `paths_rules` is non-empty, `core_lines` passes the target or
`bytes` passes `--max-kb`. Other skills can run this to put one line in front of the user.

`skillOverrides` (in user, project or local settings) has four states per skill name: `on`, `name-only`,
`user-invocable-only` (hidden from Claude, still in the `/` menu) and `off` (hidden from both). The check counts the last
two as hidden: a hidden skill returns an error when invoked by its full name, so an instruction that routes to it is
broken. Plugin skills are not affected by `skillOverrides`; manage those through `/plugin`. Two fixes, never both: set the
skill back to `on` or `name-only`, or reword the route so it tells the user to run it. A skill whose own
frontmatter forbids model invocation is unfollowable the same way; the script does not read frontmatter for that, so check it
by eye when a route does not work.

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
