# Git mechanics (the policy itself is Standing Order 1 in CLAUDE.md)

## Branching and worktrees
- Branch off the default branch first. Never switch the branch of a checkout another session is
  using: create a worktree instead (`git worktree add ../<repo>-<topic> -b <branch>`).
- Never force-push or delete `main`/`master` (or the repo's protected branches). Never rewrite
  history someone else has pulled.
- **Never backdate a commit.** Never `--no-verify`, and never bypass commit signing, unless the user
  asks for that specific commit. Pushes go only to approved remotes (Red Line).

## Before a PR and merging
- Run the repo's own checks (lint, tests, any scanner the repo's CI runs) locally when CI is red or
  when the repo has no CI. A green CI run is still not evidence the change works
  (`rules/verification.md`).
- Review: the bundled `/code-review` (and `/security-review` for anything touching auth, secrets or
  a public surface).
- **Shared repos:** open the PR and request review per your organisation's policy; merge only once
  the required reviews and checks pass.
- **Your own sandbox repos** (a repo you created yourself in a sandbox organisation or namespace
  you own, holding nothing others depend on): `gh pr create --fill` then
  `gh pr merge --squash --auto` is fine where the repo allows auto-merge; it merges once required
  checks pass. Anything else is a shared repo.
- **Never post review comments on someone else's PR** unless they or the user asked for that
  review. Run review tools that can post to a PR (for example `adamsreview` in PR mode) against
  the local diff instead, unless asked.
- A merge that would trigger something a third party sees (a release note, a post, a customer
  email) needs the user's confirmation, or decouple that step from the merge.

## Commits
- Small, single-purpose commits with a message that says why. Never commit a credential, a `.env`
  file, or generated secrets; check `git diff --cached` before committing.

## Secrets hygiene
- After any redaction sweep, run `git worktree list`: a worktree can still hold the old content.
- **Deleting a file from a public repo closes nothing.** Forks, caches, and access by old commit
  SHA survive a history rewrite. Rotating the credential is the only fix; record it in your
  organisation's rotation process.
- Before a credential reset or rotation, prove you can write the new value to its secret store.
  A rotation that completes and then fails to store the new value locks you out.
