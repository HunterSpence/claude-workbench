# Git mechanics (Standing Order 1 in CLAUDE.md)

## Branching and worktrees
- Branch off the default branch first. Never switch the branch of a checkout another session is
  using: create a worktree instead (`git worktree add ../<repo>-<topic> -b <branch>`).
- Never rewrite history someone else has pulled.
- **Never backdate a commit.** Never `--no-verify`, and never bypass commit signing, unless the user
  asks for that specific commit.

## Before a PR and merging
- Run the repo's own checks (lint, tests, any scanner the repo's CI runs) locally when CI is red or
  when the repo has no CI.
- Review: the bundled `/code-review` (and `/security-review` for anything touching auth or a
  public surface).
- Where the repo allows auto-merge: `gh pr create --fill` then `gh pr merge --squash --auto`; it
  merges once required checks pass.

## Commits
- Small, single-purpose commits with a message that says why. Check `git diff --cached` before
  committing. Credential scan for staged files:
  `{{WORKBENCH_HOME}}/kit/tools/git-credscan/credscan_staged.py --install <repo>`.
