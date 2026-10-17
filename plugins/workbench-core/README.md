# workbench-core

The main plugin of claude-workbench: agent personas, workflow skills and the stdlib-only hooks. The installer registers it from the local kit copy; invoke a skill as `/workbench-core:<skill>`. Claude also
picks a skill on its own when the task matches its description, except the user-invoked ones marked below.

## Agents (`agents/`)
Builders and gates: `flagship`, `blue-verify`, `security-auditor`. Attack and alternative: `red-team`, `green-team`.
Workers: `implementer`, `researcher`, `ops-runner`, `scout` (small-model reader). Only when asked: `sonnet-max`. Each
file pins its own model and effort; which persona fits which task is in `docs/model-routing.md` at the kit root.

## Skills (`skills/`)
| Group | Skills |
|---|---|
| Building and fixing | `cascade`, `ratchet`, `investigate`, `repo-fix`, `repo-review`, `spawn`, `handoff`, `ponytail` |
| Research and knowledge | `deep-research`, `find`, `ctx-agent-history-search` |
| Office and output | `office-docx`, `office-pptx`, `office-xlsx`, `office-render`, `ui-build`, `draft-reply` |
| Plugins and MCP | `skill-scan` |
| Setup and health | `brain-audit`, `github`, `linux-service-triage` |
| User-invoked only (Claude suggests them, never starts them) | `setup`, `cleanup`, `pc-checkup`, `vdi-drive`, `onboard`, and the authoring and admin skills `plugin-factory`, `plugin-review`, `web-packager`, `mcp-builder`, `api-bridge`, `app-navigator`, `mcp-heal`, `batch-review`, `brand-spec` |

## Hooks (`hooks/hooks.json`, scripts in `scripts/`)
- PreToolUse: a read-flood check on Read.
- SessionStart, UserPromptSubmit, PreCompact, Stop, ConfigChange and InstructionsLoaded: session context, journal
  checkpoints, a credential check on replies and a settings-change log.
- PostToolUseFailure: a one-line hint from the bug-card detectors.
Hooks fail open and none of them blocks a shell command; permission rules carry that (`settings/SETTINGS.md`). `/hooks` in Claude Code lists what is registered.

## Configuration
One option, `python`: the interpreter that runs the hooks. The installer fills in the one it detected; avoid the
Microsoft Store stub on Windows. Skills that need packages list them in their own `requirements.txt`.

## Licence
MIT, like the rest of the kit. Two skills are adapted from other projects and carry their notices: `ponytail` (MIT)
and `ctx-agent-history-search` (Apache-2.0); see `THIRD-PARTY.md` at the kit root.
