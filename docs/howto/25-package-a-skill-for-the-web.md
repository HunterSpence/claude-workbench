# Package a skill for the web

Automates it: /workbench-core:web-packager

## When to use
Colleagues who work on claude.ai (the browser) need your skill or plugin, and you want to know first whether it will upload
and what will not survive there. Claude Code accepts many fields and parts that claude.ai rejects: one unexpected frontmatter
key fails the upload, and a top-level `bin/` folder makes it refuse the whole plugin. `<KIT>` is the kit folder (guide 01).

## Steps
1. Check the folder (a skill folder with SKILL.md at its root, or a plugin folder). Exit 0 means portable, 1 means not, with a rule number per problem:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/web-packager/scripts/package_web.py <folder> --check
   ```
   The usual findings: `F01` a Claude-Code-only key, `F02` any other unknown key, `F03` or `F04` a bad name or description,
   `F06` a top-level `bin/`, `P09` a local (stdio) MCP server (claude.ai connects only to remote https servers).
2. Fix them. For frontmatter alone, `--strip` drops the non-portable keys and folds `when_to_use` into the description.
   It cannot fix `bin/` or a stdio server; move that behaviour to a Claude-Code-only sibling plugin.
3. Build the zip (it refuses while the check fails):
   ```
   py -3 <KIT>/plugins/workbench-core/skills/web-packager/scripts/package_web.py <folder> --out <name>.zip --strip
   ```
   Forward slashes, LF endings, sorted entries and fixed timestamps: two runs give identical bytes. The listing is printed.
4. Tell the users what will not work: scripts a skill points to need code execution and, on default organisation settings,
   have no network, so a skill that downloads or installs something fails. Hooks, agents and local servers do not run in chat.
5. Upload it yourself, where your organisation allows custom skills: Customize, Skills (a skill) or Customize, Plugins, Add,
   Upload plugin (a plugin). The kit never uploads anything. Review a package you did not write first (guide 24).

## Verify
- `--check` exits 0, and `--check --json` shows `"portable": true`.
- The zip lists one folder named after the skill (or the plugin at the root) and no `__pycache__`, `.pyc` or OS junk files.

## Common failures
- **Upload fails with a frontmatter error:** only `name`, `description`, `license`, `compatibility`, `metadata` and `allowed-tools` upload. Run `--strip`.
- **Description rejected:** it is empty, over 1,024 characters, or holds `<` or `>`.
- **Custom skills are switched off for your organisation:** that is a decision; ask through guide 03 and do not look for another way in.
