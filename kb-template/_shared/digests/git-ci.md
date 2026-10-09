---
title: Digest, git and CI
domain: _shared
status: active
---
# Git and CI: lessons that keep recurring

Read this before branching, cleaning up, writing a workflow or wiring a secret scanner.

## Worktrees, stashes and branches
- **The stash belongs to the repository, not the worktree.** Two agents stashing in sibling worktrees pop each other's
  entries. Commit work in progress to your own branch, or apply a stash by hash and drop only your own.
- **One shared checkout, one branch.** If several sessions share a working tree, one of them will switch the branch
  under another. Give every session its own worktree.
- **A branch checked out in a forgotten worktree is invisible.** `git worktree remove` leaves the branch behind and a
  fix can sit there unmerged. List worktrees and unmerged branches after every cleanup.
- **A folder inside a bigger repository is "a repo".** `git -C dir` walks up to the parent. Check for `dir/.git`
  before looping over folders, or set `GIT_CEILING_DIRECTORIES`.
- **Editable installs follow the main checkout.** In a worktree, put the worktree's source first on `PYTHONPATH`.

## Commits and hooks
- **`git commit --dry-run` does not run pre-commit hooks,** so it proves nothing about a hook. Make a real commit on a
  scratch branch.
- **Never skip hooks to get past a failure.** Fix the cause. A hook that cannot be satisfied is a finding for its owner.
- **Check `git status` before every commit.** A broad `add` stages generated output, caches and secrets; hooks only see
  what is staged.
- **Executable bits and line endings are decided on the committing machine.** Windows commits scripts without the bit;
  set it with `git update-index --chmod=+x` and keep a `.gitattributes` for `eol=lf`.
- **Use the organisation's identity and its approved remotes.** Check `git remote -v` before the first push; never
  create a public repository or gist from work content.
- **Publishing a secret is permanent.** Deleting the file or rewriting history closes nothing: forks, caches and
  object stores keep it. Rotate the credential, and list worktrees after a redaction because a worktree keeps the old
  blob.
- **Clone URLs with tokens persist the token** in the clone's config. Use a credential helper and delete temporary
  clones.

## Workflows
- **Untrusted text must not be substituted into a script.** Titles, branch names and comments go through `env:` and
  are read as quoted shell variables.
- **The default `pull_request` types omit "ready for review".** Marking a draft ready starts nothing unless you add the
  type.
- **A concurrency group that cancels in progress will cancel a deploy** during a burst of merges. Queue deploys.
- **A fallback job gated on another job's result string misfires when that job was refused.** Gate on an output and
  use `always()`.
- **A required check that a path filter skips never reports,** so the merge waits forever. Run the check always and
  let it exit early.
- **Side-effect steps (notifications, uploads) fail otherwise green runs.** Mark them non-fatal and guard them on the
  secret being set.
- **Self-hosted runners keep state between jobs.** Root-owned files, fixed temp paths and leftover caches fail the
  second run, not the first. Run a pre-checkout cleanup, or use ephemeral runners.
- **Shallow clones hide history** that version stamping, blame and changelog tools need; fetch full depth where they run.
- **Actions pinned by tag can move.** Pin third-party actions to a full commit and review updates.
- **Date filters on run listings exclude today.** Filter locally.
- **A path-filtered deploy workflow does not run for a change outside its filter,** so a configuration-only edit
  deploys nothing. Put the configuration under the filter or run the workflow by hand.
- **Claude's GitHub action skips itself on a pull request that edits a workflow file,** and the check is green with
  nothing run. It compares its own workflow with the default branch's and, on a mismatch, logs "Skipping action due to
  workflow validation". That is expected until the change merges: read the step log before trusting a green check, and
  test the merged workflow on a fresh pull request.
- **A workflow linter can exit non-zero on style-level findings.** actionlint runs the shell checker and
  reports its info-level notes (a missing quote) as problems, so the step fails. Fix the quoting; never wrap the
  linter in `|| true`.
- **A download step that ignores HTTP errors saves the error page.** `curl` does not treat an error status as a
  failure unless you pass `--fail`; add it, then check the exit code of the step.

## Rollback
- **Keep the previous build available until the new one is proven.**
- **A re-pointed tag is not a rollback:** roll back to the recorded identity of the previous build.

## Dependencies and lockfiles
- **Use one install mode everywhere** (frozen in CI) and regenerate the lockfile in the same change as the manifest.
- **An override that did nothing is a finding:** regenerate and check the resolved version in the lockfile.
- **Package managers now skip install scripts by default.** Allow them per package, on purpose, and check the pinned
  version against the registry rather than a stale "outdated" report.
- **A package that links its binary in an install script stays a placeholder while scripts are blocked.** Claude Code's
  own npm package works this way: if the script is skipped, the `claude` command is the placeholder, not the program.
  Allow that one package's script, or use the vendor's installer.

## Scanners and secrets
- **A fixture holding literal secret formats trips the scanner it tests.** Build it at run time, and pick a positive
  control that the allowlist does not already match.
- **Generic rules flag hashes.** Require vendor prefixes in custom rules and allowlist evidence folders by path.
- **A filesystem vulnerability scan reads the lock files it finds.** In a repository with several projects a finding
  may belong to a project you did not touch: scan one project's folder, or one lock file, and read the target named in
  the report before blaming the change.
- **A file scan does not cover pull request bodies or commit messages.** In a public repository keep local paths, host
  names and tracebacks with user paths out of both.
