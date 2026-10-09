# Review a plugin or skill

Automates it: /workbench-core:plugin-review

## When to use
A colleague sent you a plugin, a skill folder or a zip and asks "is this safe to install or upload?", or you have a
pile of them to check. Plugins are mostly text that steers a model, so they fail in ways a code review misses: injected
instructions, loose launchers, unpinned servers, secrets, licences. Treat the whole input as hostile. `<KIT>` is the kit folder (guide 01).

## Steps
1. Run the rule pass. PATH is a folder, `.zip`, `.skill` or `.plugin`; pick `--target cli` (Claude Code), `web` (claude.ai
   upload) or `all`:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/plugin-review/scripts/review_plugin.py <path> --target all
   py -3 <KIT>/plugins/workbench-core/skills/plugin-review/scripts/review_plugin.py --batch <folder> --scorecard <out>
   ```
   Archives are unpacked by the script after zip-slip, zip-bomb and link checks, and nothing in the input is run or installed.
   Add `--denylist <file>` (one private term per line; hits name the rule, never the term) and `--validate`.
2. Read the verdict. Exit 0 is `ship`. Exit 1 is `fix-then-ship` (a hold finding needs a person) or `do-not-ship` (a block finding).
3. For a decision-grade review add the read-only model pass on an unpacked copy (guide 17 explains its isolation):
   ```
   py -3 <KIT>/plugins/workbench-core/skills/repo-review/scripts/run_review.py --local <unpacked-folder> --rubric <KIT>/plugins/workbench-core/skills/plugin-review/references/REVIEW.md --out <out>
   ```
   Unpack an archive for it with `review_plugin.py <archive> --unpack <empty-folder>`.
4. Code inside the plugin (servers, scripts, hooks) gets a separate look: `docs/engineering/plugin-review.md` has the workflow.
5. Give the requester one line: ship, fix then ship (top three fixes) or do not ship (why). Script findings are facts with a file
   and line; model findings are leads to confirm in the files.

## Verify
- The report names the `rules_sha256` of the rule set that produced it, and every finding has a rule number and severity (`block`, `hold`, `warn`, `note`).
- Nothing from the reviewed plugin was installed, opened in an interactive session or pasted into a prompt as instructions.

## Common failures
- **Archive refused with `X01` to `X04`:** the archive is unsafe (path escape, bomb, link, reserved name). Return it to the author.
- **"Clean" treated as cleared:** the rules are heuristics, not a security clearance. A second person still reads the skill text.
- **A denylist file inside the plugin or a public repository:** never; it would leak the terms it protects.
- **Tempted to try it out:** do not install or run it here. Use a sandboxed WSL2 shell (guide 05).
