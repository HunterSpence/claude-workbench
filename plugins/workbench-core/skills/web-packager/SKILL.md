---
name: web-packager
description: "Check whether a skill or plugin can be uploaded to claude.ai and build the upload zip. Never uploads."
disable-model-invocation: true
---

# web-packager

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it appears unreplaced, use
> `py -3` on Windows and `python3` on Linux, macOS and WSL. Below it is `PY`; the script is
> `"${CLAUDE_SKILL_DIR}/scripts/package_web.py"` (`PK`).

Claude Code accepts many skill fields and plugin parts that claude.ai rejects. An upload with one unexpected frontmatter
key fails with a hard error, and a top-level `bin/` folder makes claude.ai refuse the whole plugin. This skill finds
those problems before the upload and produces the zip.

## Steps
1. **Check.** `PY PK PATH --check [--json]`. PATH is a skill folder (SKILL.md at its root) or a plugin folder. Exit 0 means
   portable, 1 means not, with a rule id per problem:
   - `F01` a Claude-Code-only key (`argument-hint`, `arguments`, `disable-model-invocation`, `user-invocable`,
     `disallowed-tools`, `model`, `effort`, `context`, `agent`, `background`, `hooks`, `paths`, `shell`, `when_to_use`,
     `version`); `F02` any other unknown key. Only `name`, `description`, `license`, `compatibility`, `metadata` and
     `allowed-tools` upload.
   - `F03` / `F04` a name that is not lowercase-hyphen, is over 64 characters, contains a reserved word or differs from
     its folder; a description that is empty, over 1,024 characters or holds `<` or `>`.
   - `F06` a top-level `bin/`. `P09` a local (stdio) MCP server: claude.ai connects only to remote https servers.
     `P10` `${user_config.*}` inside a server URL (ignored in chat). Layout, licence and secret rules apply too.
2. **Fix or strip.** Move behaviour that needs a Claude Code key into a Claude-Code-only sibling plugin. For frontmatter
   alone, `--strip` rewrites it for you: it drops the non-portable keys, folds `when_to_use` into the description (cut at
   1,024 characters) and lists every change in `PACKAGING.md` inside the zip. It cannot fix `bin/` or a stdio server.
3. **Zip.** `PY PK PATH --out FILE.zip [--strip]`. The zip is built from the folder itself: sorted entries, forward
   slashes, LF line endings, fixed timestamps (two runs are byte-identical), no `__pycache__`, `.pyc` or OS junk. A skill
   folder is stored under a folder named after the skill; a plugin folder at the zip root. The command prints the listing.
4. **Tell the user what will not survive.** Scripts a skill points to through `${CLAUDE_SKILL_DIR}` need code execution
   and get no network access on default organisation settings, so a skill that downloads or installs something will not
   work. Hooks, agents and local servers do not run in chat. Then give the upload path: Customize, Skills (a skill) or
   Customize, Plugins, Add, Upload plugin (a plugin).

## Never
Upload, publish or share anything for the user; include a credential; repackage a source-available or share-alike skill
you did not write (run `plugin-review` first if the source is not yours).
