# Review code you did not write, safely

Automates it: /workbench-core:repo-review

## When to use
Someone handed you a codebase you do not trust (a pull request, a vendor's repository, a plugin folder) and you want to look
through it without letting anything in it run. Foreign code is hostile input: its instruction files, MCP config, hooks and
pull request text can all carry instructions aimed at an AI. `<KIT>` is the kit folder (guide 01).

## Steps
1. Get the owner's agreement first and confirm the repository's classification. The review sends file contents to the
   model service; being able to read a repository is not permission to do that.
2. Add one line `HOST/OWNER/REPO` (no wildcards) to your allowlist file `<WB>/review-allowlist.txt`. Start from
   `plugins/workbench-core/skills/repo-review/scripts/review-allowlist.example.txt`. Anything else is refused before any fetch.
3. Run the review (or just ask Claude: "review ghe.example.com/<org>/<repo>, PR 12"):
   ```
   py -3 <KIT>/plugins/workbench-core/skills/repo-review/scripts/run_review.py ghe.example.com/<org>/<repo> --pr 12
   py -3 <KIT>/plugins/workbench-core/skills/repo-review/scripts/run_review.py --local <folder>
   ```
   It clones shallowly, strips `.git`, secret-shaped files and links, and runs Claude with only Read, Grep and Glob, no
   MCP server and no project settings. Add `--print-argv` to see the exact command first.
4. Read `<LAD>/wb-review/reviews/<run>/`: findings in JSON, a draft `review.md`, and `run.log`. Findings are leads: open
   the files and confirm each one.
5. Post only after you have read `review.md` and decided to. The post step needs the confirm token printed in the skill; do not add it on your own.

## Verify
- Check the isolation after each Claude Code upgrade:
  `py -3 <KIT>/plugins/workbench-core/skills/repo-review/scripts/run_review.py --canary --live`
  It prints PASS only if the hostile fixture was not obeyed, no marker file or MCP connection appeared and the `.env` value stayed unread.
- A review run leaves its scratch folder deleted (unless `--keep-scratch`).

## Common failures
- **Refused, repository not allowlisted:** the runner prints the file it expects. Add the line only after step 1.
- **You opened the clone in an interactive session:** do not. If you must, start with `claude --setting-sources user` and read `.claude/`, `CLAUDE.md` and `.mcp.json` first.
- **Tempted to build or test it here:** never install or run the foreign code on this machine; use WSL2 with the sandbox on (guide 05).
- **A secret appears in the material:** report it to your security channel, not a public issue (guide 40).
