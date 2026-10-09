# Add Claude to a repository's CI

Automates it: none (two ready workflow files in `templates/github-actions/`)

## When to use
You own a repository and want Claude to answer `@claude` mentions in issues and pull requests, or to review each pull
request. The files are documentation: the kit never installs or runs them. Merge them through your normal review.

## Steps
1. Read `templates/github-actions/README.md`. Then pick `templates/github-actions/claude.yml` (answers `@claude`) or
   `templates/github-actions/claude-review.yml` (reviews each non-draft pull request from a branch of the same repository), or both.
2. Ask a repository or organisation owner for three things: the actions `anthropics/claude-code-action` and `actions/checkout` allowed
   at the exact commits the files name; the Claude GitHub App installed on the repository (`/install-github-app` works on
   github.com only; on a `.ghe.com` tenant or Enterprise Server an owner registers the app by hand); and one authentication
   secret.
3. Choose one way to authenticate: an API key secret, a Claude Code OAuth token secret, identity federation (identifiers only),
   or a cloud provider's own trust. Keep values in repository secrets, never in the file. Do not set a static key and federation together.
4. Copy the file to `.github/workflows/` on a branch, keep `permissions: {}` at the top, keep `timeout-minutes` and `--max-turns`
   low, and open a pull request. Leave `allowed_non_write_users` and `allowed_bots` unset.
5. Expect no Claude run on that pull request. The action compares the workflow file with the one on the default branch and
   skips itself on a mismatch, so the pull request that adds or edits a workflow file shows a green check with nothing run.
   After it merges, comment `@claude` on an issue as a user with write access.

## Verify
- `gh run list --repo <org>/<repo> --limit 5` shows the workflow ran.
- `gh run view <run-id> --repo <org>/<repo> --log-failed` is empty for a good run.
- Claude's reply appears in the thread, and the run used only the permissions the file declares.

## Common failures
- **Green check, but Claude did nothing, on the pull request that edits the workflow:** by design. The step log says
  "Skipping action due to workflow validation"; the action's own message calls it expected for new workflows and for pull
  requests that change one. Merge the change, then test on a new issue or pull request.
- **`actionlint` fails on a style note:** it reports the shell checker's info-level findings, such as an unquoted variable, as
  problems and exits 1. Quote the variable; do not hide the exit code.
- **A download step "succeeds" and saves an error page:** `curl` does not treat an HTTP error status as a failure unless you
  pass `--fail`. Add it, and check the step's exit code.
- **A vulnerability scan names a project you did not change:** `trivy fs` looks at the lock files it finds. Scan one project's
  folder, or one lock file, and read the target named in the report.
- **Workflow does not start:** the action is not on the organisation's allowed list. Ask the owner; do not switch to a different action.
- **Authentication or app-token error:** the Claude GitHub App is missing or the secret name does not match the file.
- **Fork pull requests get no secrets:** correct and intended. Do not switch to `pull_request_target`; it would hand secrets to outside code.
- **Cost surprise:** every run uses Actions minutes and model usage; lower the turn and time limits.
- **Logs show too much:** keep `show_full_output` off; logs are readable by anyone who can read the repository.
