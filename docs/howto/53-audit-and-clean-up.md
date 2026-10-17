# Audit your setup and clean up dead code

Automates it: /workbench-core:brain-audit (the report) and /workbench-core:cleanup (the archive step, only after you approve a list)

## When to use
After a big configuration change, when an instruction seems to be ignored, when the always-loaded text keeps growing, or when a
repository holds scripts and documents nobody uses. Both tools only read until you approve something. `<KIT>` is the kit folder
(guide 01).

## Steps
1. Run the audit: `/workbench-core:brain-audit`, or by hand
   `py -3 <KIT>/plugins/workbench-core/skills/brain-audit/scripts/audit.py --project .`
   Read CRITICAL and HIGH first. It prints file paths and setting names, never a value.
2. Get the instruction surface as data:
   `py -3 <KIT>/plugins/workbench-core/skills/brain-audit/scripts/audit.py --surface --json --project .`
   The answer is `{"surface": {...}, "exit": 0 or 1}` and the command exits with the same number. The keys are `bytes` (always
   loaded), `core_lines` (your longest CLAUDE.md), `rules_over_cap`, `paths_rules`, `duplicates`, `dead_refs`,
   `generated_drift` and `hidden_skills`. `paths_rules` is information only; anything else non-empty makes the exit 1.
3. Hidden skills: each entry names a skill that an instruction routes to and the settings file (`set_in`) that hides it. A
   `skillOverrides` value of `user-invocable-only` hides the skill from Claude, and `off` hides it from Claude and from the
   `/` menu; either way Claude cannot follow the route. Set the skill back to `on` or `name-only`, or reword the route so it
   asks you to run it. The setting does not apply to a plugin's skills: use `/plugin` for those.
   The edit is one key, `skillOverrides`, in your user `settings.json` (or `settings.local.json`): make it by hand with
   `/config` or an editor, or ask Claude and approve the prompt. Leave hooks, permissions, plugins and their options,
   environment and MCP servers alone for this step. Keys: `settings/SETTINGS.md`.
4. Duplicates are listed as `file:line` with a short id, not as text. Open each place, keep the line in one file and link to
   it from the others.
5. Over-long files: the documented target is under 200 lines per CLAUDE.md file. Move the parts that matter for only some
   work into path-scoped rules (they load when a matching file is read) or into a skill.
6. Look for dead files, read only:
   `py -3 <KIT>/plugins/workbench-core/skills/cleanup/scripts/scan_legacy.py --root . --json`
   It lists Markdown files whose front matter says `status: deprecated` (or obsolete, superseded, archived, dead, legacy,
   retired), and scripts in `scripts/`, `tools/` and `bin/` that no other file names and that have not changed for 30 days.
7. Treat every listed script as a question, not an answer. Something outside the repository may start it: a scheduled task, a
   cron entry, a launcher or the CI. Check those first (`/workbench-core:cleanup` has the commands). Add
   `--keep <glob>` for a known entry point so it stops appearing.
8. To archive, run `/workbench-core:cleanup` and name the exact files. It moves them with `git mv` into `_archive/<date>/` on a
   branch, writes a restore manifest, runs your build and tests, and stops at a pull request.
9. If you stop with work unfinished, `/workbench-core:handoff` writes the note. For client or tenant work it goes in that
   client's own folder, which has no remote and is never pushed, and it is scanned with
   `py -3 <KIT>/plugins/workbench-core/scripts/secretscan.py <file>` before the skill says it is done.

## Verify
- Rerun step 2: `exit` is 0, or every remaining item is one you decided to keep.
- `py -3 <KIT>/plugins/workbench-core/skills/cleanup/scripts/scan_legacy.py --self-test` prints one line and exits 0.
- After an archive branch: `git status` shows renames into `_archive/`, no deletion, and your own build and tests passed on
  that branch.
- `secretscan.py` prints `CLEAN` for the handoff file. Exit 1 lists `file:line` with a masked match; exit 2 means a file was
  not scanned, which is not a pass.

## Common failures
- **A route is reported as dead, but the skill is installed:** a plugin's skills are found through
  `<CH>/plugins/installed_plugins.json` in the configuration folder (`<CH>` is `CLAUDE_CONFIG_DIR` or `~/.claude`). Pass that
  folder with `--home` when you audit another one.
- **A hidden skill is not reported although Claude never uses it:** the check reads `skillOverrides` only. A skill whose own
  front matter says `disable-model-invocation: true` is hidden from Claude the same way; look for it by hand.
- **A prompt asks before a force push or before deleting a repository or a release:** that is a permission rule, listed in
  `settings/SETTINGS.md`. Answer it, or change the rule with `/permissions`.
- **A script is listed but is in use:** a scheduler or the CI starts it without any file naming it. Leave it, and add `--keep`.
- **A script you expected is missing from the list:** its name appears somewhere, even in a comment or a changelog, or it
  changed within the last 30 days. Run with `--stale-days 0` to see the second kind. For Python and JavaScript the bare module
  name counts as a mention too, so an imported module never appears.
- **A line you consider a duplicate is not listed:** only lines of 40 characters or more count, and fenced code, headings and
  imports are skipped.
- **The scan says nothing about a folder:** `_archive`, `node_modules`, `dist` and `build` are never read, in either direction.
