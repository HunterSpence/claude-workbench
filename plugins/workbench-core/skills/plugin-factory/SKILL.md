---
name: plugin-factory
description: "Turn a plugin request into a tested plugin: scaffold, hooks, MCP server, tests, CI, validate."
disable-model-invocation: true
---

# plugin-factory

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it appears unreplaced, use
> `py -3` on Windows and `python3` on Linux, macOS and WSL. Below it is `PY`. Scripts are in
> `"${CLAUDE_SKILL_DIR}/scripts/"`: `scaffold.py` and `check_plugin.py`.

A plugin is a folder of skills, hooks, agents and MCP configuration that Claude Code (and, in part, Desktop, claude.ai
and the Office add-ins) loads as one unit. This skill turns "I want a plugin that does X" into a folder that already
passes its own tests, the rule check and `claude plugin validate --strict`.

## Steps
1. **Ask four things, no more.** Name (lowercase, hyphens; not starting with `claude-`, `anthropic-`, `anthropics-` or
   `cc-plugin-`). Kind: `content` (skills only), `guard` (adds a Bash hook), `integration` (adds an MCP server).
   Surfaces: `cli` (Claude Code only) or `all` (must also load on claude.ai). For `integration`, remote or stdio:
   claude.ai connects only to remote servers, so `--surfaces all` needs `--mcp remote`.
2. **Scaffold** into the marketplace repository (a new folder is fine; the first run creates the marketplace file, the
   CI workflow and a copy of the checker):
   ```bash
   PY "${CLAUDE_SKILL_DIR}/scripts/scaffold.py" NAME --kind content|integration|guard --surfaces cli|all [--mcp remote|stdio|none] --out REPO [--description TEXT] [--org-overlay]
   ```
   It refuses reserved names, an existing plugin and stdio servers for the web, and never touches user or managed settings.
3. **Fill in the substance.** Replace the placeholder text in `skills/NAME/SKILL.md` (when it applies, the steps, what to
   leave alone), the README line, and for a server the three example tools. Keep skill frontmatter to the six portable
   fields unless the plugin is Claude Code only. Put long reference text in a second file the skill links to.
4. **Check, test, validate** (all three must pass before anyone installs it):
   ```bash
   PY REPO/tools/check_plugin.py REPO                      # rules: layout, frontmatter, hooks, MCP pins, injection, secrets, licences
   PY -m unittest discover -s REPO/plugins/NAME/tests -v   # the generated tests plus yours
   claude plugin validate REPO --strict                    # reads only; no model call
   claude --plugin-dir REPO/plugins/NAME plugin details NAME   # inventory and the always-on token cost
   ```
5. **Roll out.** For a team inside an organisation use `--org-overlay` and read `org-overlay/README.md` (mirror steps,
   managed-settings snippet) and `coexistence.md` (what a governance layer can switch off). For claude.ai users run the
   `web-packager` skill. Before anyone else installs a plugin they did not write, run `plugin-review`.

## House rules the templates already follow
- Skills are text: one job each, a description that says when to use it, long material in linked files.
- Hooks use exec form (`command` plus `args`), `${CLAUDE_PLUGIN_ROOT}` for code, `${CLAUDE_PLUGIN_DATA}` for state, an
  explicit timeout and a narrow matcher; they fail open unless blocking is their job.
- Executables live in `scripts/`, never a top-level `bin/` (claude.ai refuses a plugin that has one).
- Secrets only as `sensitive: true` `userConfig` options, never in a header, an env block or a file.
- Third-party launchers (`npx`, `uvx`) are pinned to an exact version; remote servers use https.
- MCP tools have a title and a true `readOnlyHint` or `destructiveHint`; there is no catch-all request tool.

## Never
Edit a settings file from a plugin script; ship a credential, a private hostname or a personal path in a template; call
`claude plugin eval` without telling the user it makes model calls; publish or upload the result for the user.
