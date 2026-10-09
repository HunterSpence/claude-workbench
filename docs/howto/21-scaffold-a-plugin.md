# Scaffold a plugin

Automates it: /workbench-core:plugin-factory

## When to use
You want to package a few skills, a command guard or a connection to a system as a plugin your team can install, and you
want it to start out tested and checkable instead of hand-built. `<KIT>` is the kit folder (guide 01). Conventions and
background: `docs/plugins-playbook.md`.

## Steps
1. Decide four things. The name (lowercase and hyphens; it cannot start with `claude-`, `anthropic-`, `anthropics-` or
   `cc-plugin-`). The kind: `content` (skills only), `guard` (adds a shell hook) or `integration` (adds an MCP server).
   The surface: `cli` (Claude Code only) or `all` (must also load on claude.ai). For an integration, `remote` or `stdio`;
   claude.ai connects only to remote servers, so `all` needs `--mcp remote`.
2. Scaffold into a marketplace repository (a new folder is fine), or run `/workbench-core:plugin-factory` and describe it: "a plugin called team-notes with one skill". Claude can only suggest that command.
   ```
   py -3 <KIT>/plugins/workbench-core/skills/plugin-factory/scripts/scaffold.py team-notes --kind content --surfaces cli --out <repo>
   ```
   The first run also adds the checker, a CI workflow and the marketplace file. It never touches your settings.
3. Replace the placeholder text in the generated `skills/team-notes/SKILL.md` (when to use it, the steps, what to leave
   alone) and the README line. Keep the frontmatter to the six portable fields unless the plugin is Claude Code only.
   Put long reference text in a second file the skill links to.
4. Check, test and validate. All three must pass before anyone installs it:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/plugin-factory/scripts/check_plugin.py <repo>
   py -3 -m unittest discover -s <repo>/plugins/team-notes/tests -v
   claude plugin validate <repo> --strict
   ```
5. Before anyone else installs it, have a second person review it (guide 24). For claude.ai users package it (guide 25).
   For a rollout inside your organisation add `--org-overlay`: it also writes mirror steps and a managed-settings snippet
   for IT to review. You send them; the kit does not (guide 03).

## Verify
- `check_plugin.py` exits 0 (1 means a block or hold finding, named by rule number) and the unit tests pass.
- `<repo>/plugins/team-notes/` holds the manifest, the skill, README, LICENSE, CHANGELOG, SECURITY and tests, and the
  marketplace file lists it.

## Common failures
- **Exit 2, refused:** a reserved name, a plugin that already exists, or a stdio server with `--surfaces all`. Change the input.
- **The check flags a hook or launcher:** hooks use exec form (`command` plus `args`) with a timeout and a narrow matcher;
  `npx` and `uvx` launchers are pinned to an exact version; executables live in `scripts/`, never a top-level `bin/`.
- **A secret in a template:** secrets belong only in `userConfig` options marked `sensitive: true`, never in a header, env block or file.
- **Hooks do nothing after install:** your organisation may allow only managed hooks. Stop and use guide 03.
