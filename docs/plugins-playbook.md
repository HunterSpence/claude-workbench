# Plugins playbook

How to build, test, ship and govern Claude plugins so one folder works as widely as it can. Facts below come from the
published Claude Code and claude.ai documentation; anything marked untested is a reasoned guess. Tools: the
`plugin-factory` skill scaffolds, `plugin-review` checks someone else's plugin, `web-packager` prepares a claude.ai
upload.

## 1. Anatomy of a plugin
A plugin is a folder. Only the manifest, .claude-plugin/plugin.json, is special, and even that is optional (without it the standard
layout is discovered); the kit always writes one.

| Path | Holds |
|---|---|
| .claude-plugin/plugin.json | name, version, description, author, licence, `userConfig`, component paths |
| `skills/NAME/SKILL.md` | a skill: frontmatter plus instructions; extra files beside it load on demand |
| `commands/`, `agents/` | slash commands (they load as skills in chat) and subagents |
| `hooks/hooks.json` | event handlers that run commands, HTTP calls or prompts |
| `.mcp.json` | MCP servers (remote or local) |
| `scripts/` | executables your hooks and servers call; never a top-level `bin/` |
| `settings.json` | only the `agent` and `subagentStatusLine` keys take effect |

Manifest rules worth knowing: `name` is lowercase-hyphen and namespaces every component; reserved are names starting
`claude-`, `anthropic-`, `anthropics-` or `cc-plugin-`, a few exact names, and `official` next to `claude` or
`anthropic`. Setting `version` pins users until you change it; leave it out to track commits, and never set it in both
the manifest and the marketplace entry (the manifest wins silently). `userConfig` options are typed; mark every secret
`sensitive: true` so it goes to the operating system's secure store, and give every non-secret option a default (Cowork
will not prompt, and an option without a default makes the server it feeds be ignored there).

Path variables: `${CLAUDE_PLUGIN_ROOT}` is the installed copy (it changes on update, so never write state there),
`${CLAUDE_PLUGIN_DATA}` survives updates (state, caches, virtual environments), `${CLAUDE_SKILL_DIR}` is the skill's own
folder, `${user_config.KEY}` a saved option. User-config substitution is rejected in shell-form hooks and in
`headersHelper`. Claude's own Bash tool calls see none of these variables.

What a plugin cannot do: set permissions, environment, model or status line; load a CLAUDE.md or `rules/`; give a plugin
agent its own hooks, servers or permission mode; override managed policy; run sandboxed (hooks, servers and mods run with
your user rights, outside the sandbox). A lasting guard therefore still needs a bootstrap or managed settings.

## 2. Surfaces: what loads where
| Surface | Loads |
|---|---|
| Claude Code (terminal, IDE) | everything |
| Desktop Code tab and Cowork | skills, commands, agents, hooks, remote and local MCP (local only when the session runs locally); ignores LSP, output styles, themes, plugin settings |
| claude.ai chat (web, Desktop chat, mobile) | skills (commands as skills) and remote MCP as connectors; no hooks, agents or local servers |
| Claude for Excel, PowerPoint, Word, Outlook | skills enabled in your Claude settings; not available when the add-in runs through a model gateway |
| Agent SDK | plugin folders by path (`type: local`) |

One plugin can serve all of them if it keeps skill frontmatter to the six portable fields, has no top-level `bin/`,
exposes integrations as a remote https MCP server with a fixed URL (no `${user_config}` in it) and signs users in with
OAuth rather than per-user options. Put shell-dependent hooks and local servers in a second, Claude-Code-only plugin.

The six portable skill fields: `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`. Anything
else is a hard upload error on claude.ai (`argument-hint`, `arguments`, `disable-model-invocation`, `user-invocable`,
`disallowed-tools`, `model`, `effort`, `context`, `agent`, `background`, `hooks`, `paths`, `shell`, `when_to_use`,
`version`, and unknown keys). In a plugin the same skills may load in chat anyway, but that path is untested here; do not
rely on it. The name must equal its folder (at most 64 characters, no `anthropic` or `claude`), the description is
non-empty, at most 1,024 characters and free of angle brackets, and a body under 500 lines loads best. Scripts a skill
runs need code execution, and on default organisation settings they have no network access, so a skill must not depend
on `pip install` or downloads; route outside data through connectors.

## 3. Hooks
- Prefer **exec form**: `"command": "${user_config.python}", "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/x.py"]`. No shell,
  no quoting trouble. In shell form, quote `"${CLAUDE_PLUGIN_ROOT}"`.
- Always set `timeout`. Use the narrowest `matcher` (and `if`) that does the job; a hook with no matcher on a tool event
  fires for every tool.
- Read the event as JSON on stdin. Exit 0 with no output makes no decision (the call goes through the normal permission
  flow); exit 2 blocks and shows stderr to Claude. Decide on purpose whether a failure should fail open or closed, and
  say so in the script header.
- **A hook cannot overrule a permission rule.** PreToolUse decisions combine as deny, then defer, then ask, then allow,
  and deny and ask rules from settings are evaluated whatever a hook returns. A guard hook adds checks; it never grants
  what a managed deny rule forbids.
- Keep state in `${CLAUDE_PLUGIN_DATA}`. No network calls, environment credential reads, `eval`, inline `-c` programs
  or recursive deletes without a stated reason; the reviewer flags each.
- Test a hook by piping a recorded event into it and asserting the exit code and output, including a Windows path and a
  folder with a space in it. The guard template ships six such tests.

## 4. MCP servers in plugins
- Remote servers: `type` `http`, an https URL, OAuth where the service supports it. Claude's connector client follows
  the 2025-era authorization specs; check the connector documentation for the redirect addresses to allow.
- Local servers: a plugin file started with plain arguments (`command` plus `args`), never a shell string, `npm run` or
  `-c`. Third-party launchers (`npx`, `uvx`, `bunx`) are pinned to an exact version; `uv run` uses `--locked`; no
  registry override files; no bundle fetched from a URL.
- Secrets: a `sensitive` option referenced as `${user_config.NAME}` in a header or env value. Never a literal, never an
  environment variable read from the user's shell.
- Tools: a title and a true `readOnlyHint` or `destructiveHint` on each; names at most 64 characters; descriptions say
  what the tool does, not how Claude should behave; specific errors; no tool that takes a free-form HTTP method.
- A managed MCP file (`managed-mcp.json`) takes exclusive control: plugin servers are refused. See section 7.

## 5. Marketplaces and distribution
`.claude-plugin/marketplace.json` holds `name`, `owner`, and `plugins[]` with `name`, `source` (`./relative`, or `github`,
`url`, `git-subdir` objects with a 40-character `sha` for anything third-party), `description`, `category`. Users get an
update only when the computed version changes (manifest, then marketplace entry, then commit).

Two routes into an organisation:
1. **Organisation sync** from the claude.ai admin console: sync from a private or internal repository (github.com, GitHub
   Enterprise Server, or GitLab) with the Claude app installed on it. It reads the default branch only, ignores tags,
   needs no member access to the repository, and refuses any plugin with a top-level `bin/`. Availability per group
   (not available, available, installed by default, required) is set in the console. Members' own plugin publishing can
   be set to require review.
2. **Managed settings**: `extraKnownMarketplaces` (with `autoUpdate`), `enabledPlugins`, `strictKnownMarketplaces`. Every
   machine clones with its own git credentials and no prompts, so a credential helper must already hold a login; a
   `GITHUB_TOKEN` in the environment alone does nothing. Background auto-update is off until a user or the managed entry
   turns it on, and it fails silently when a prompt would be needed.
The plugin-factory `--org-overlay` option writes a mirror checklist, a managed-settings snippet and coexistence notes.

## 6. Develop and test
| Step | Command |
|---|---|
| Load for one session | `claude --plugin-dir ./plugin` (folder or zip); `/reload-plugins` after edits |
| Inventory and token cost | `claude plugin details NAME` |
| Validate | `claude plugin validate DIR --strict` (exit 0 clean, 1 findings; reads only) |
| Rules | `python tools/check_plugin.py DIR` (this kit's plugin-review rules as a gate) |
| Unit tests | hooks by piped events; servers by a stdio client (initialize, tools/list, tools/call) |
| Evals | `claude plugin eval .` runs cases against a model, with a no-plugin baseline; it costs money, needs credentials, and on native Windows any case that grants a shell needs WSL or a Linux runner |
| Release | bump `version`, `claude plugin tag --push`, dependants resolve ranges against the tags |
Use a temporary `CLAUDE_CONFIG_DIR` for any experiment so your real configuration is untouched.

## 7. Governance and coexistence
Four managed keys decide how a second plugin lives next to an organisation's own: `allowManagedHooksOnly` (your hooks
run only if your plugin is force-enabled in the managed list), a managed MCP file (plugin servers refused; skills,
agents and hooks still load), `allowedMcpServers` / `deniedMcpServers` (checked against plugin servers too) and
`strictKnownMarketplaces` (must list your marketplace). Find out which are set (`/status`, or ask the administrator)
before building an integration plugin. Telemetry names your own plugins `third-party` unless
`OTEL_LOG_TOOL_DETAILS=1` is set. Reviewing other people's plugins: `docs/engineering/plugin-review.md`.

## 8. Packaging for claude.ai
Run `web-packager` on the folder. It rejects each non-portable item with a rule id, can rewrite frontmatter with
`--strip` (recording changes in `PACKAGING.md`), and zips with forward slashes, LF endings and no caches. Upload is the
user's step: Customize, Skills, or Customize, Plugins, Add, Upload plugin. A zip may be at most 200 MB and 5,000 files for
the plugin route.
