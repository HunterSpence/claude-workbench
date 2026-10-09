# workbench-core

The main plugin of claude-workbench: agent personas, workflow skills and the stdlib-only hooks, including the guard
engine. The installer registers it from the local kit copy; invoke a skill as `/workbench-core:<skill>`. Claude also
picks a skill on its own when the task matches its description, except the user-invoked ones marked below.

## Agents (`agents/`)
Builders and gates: `flagship`, `blue-verify`, `security-auditor`. Attack and alternative: `red-team`, `green-team`.
Workers: `implementer`, `researcher`, `ops-runner`, `scout` (small-model reader). Only when asked: `sonnet-max`. Each
file pins its own model and effort; which persona fits which task is in `docs/model-routing.md` at the kit root.

## Skills (`skills/`)
| Group | Skills |
|---|---|
| Building and fixing | `cascade`, `ratchet`, `investigate`, `repo-fix`, `repo-review`, `spawn`, `handoff`, `ponytail` |
| Research and knowledge | `deep-research`, `find`, `ctx-agent-history-search`, `batch-review` |
| Office and output | `office-docx`, `office-pptx`, `office-xlsx`, `office-render`, `ui-build`, `draft-reply` |
| Plugins and MCP | `plugin-factory`, `plugin-review`, `web-packager`, `mcp-builder`, `api-bridge`, `app-navigator`, `mcp-heal`, `skill-scan` |
| Setup and health | `onboard`, `brain-audit`, `github`, `linux-service-triage` |
| User-invoked only | `setup`, `cleanup`, `pc-checkup`, `vdi-drive` |

## Hooks (`hooks/hooks.json`, scripts in `scripts/`)
- PreToolUse: the guard engine (`scripts/guards/`, generic and corporate rule packs), a read-flood guard and the
  skill auto-invoke hint.
- SessionStart, UserPromptSubmit, PreCompact, Stop, ConfigChange and InstructionsLoaded: session context, journal
  checkpoints, a credential check on replies and a settings-change log.
- PostToolUseFailure: a one-line hint from the bug-card detectors.
Hooks fail open, so a guard is a backstop, never the only control. Test them with the guard test in `IMPORT.md`.

## Configuration
One option, `python`: the interpreter that runs the hooks. The installer fills in the one it detected; avoid the
Microsoft Store stub on Windows. Skills that need packages list them in their own `requirements.txt`.

## Licence
MIT, like the rest of the kit. Two skills are adapted from other projects and carry their notices: `ponytail` (MIT)
and `ctx-agent-history-search` (Apache-2.0); see `THIRD-PARTY.md` at the kit root.
