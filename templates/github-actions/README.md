# GitHub Actions templates for claude-code-action

Two workflow files to copy into a repository you control. They are documentation: the kit never installs or runs them.
Read this page, then adapt, then merge them through your normal review.

| File | What it does | Runs on |
|---|---|---|
| `claude.yml` | answers `@claude` in issues, comments and reviews | issue and comment events |
| `claude-review.yml` | reviews each non-draft pull request from a branch of the same repository | `pull_request` |

## Before you copy

1. **Allowed actions.** Organisations often allow only listed actions. Ask an owner to allow
   `anthropics/claude-code-action` and `actions/checkout` at the exact commits the files name.
2. **The Claude GitHub App** (or your own app) must be installed on the repository: the default path swaps the job's OIDC
   token (`id-token: write`) for the app's token. `/install-github-app` works on github.com only; on GHE.com and GitHub
   Enterprise Server an owner registers the app by hand. Support for those hosts is partial: read the action's setup
   page and open issues at the pinned version before you rely on it.
3. **Authentication.** One of: an API key secret, a Claude Code OAuth token secret, OIDC workload-identity federation
   (identifiers only, no secret), or Bedrock, Vertex or Foundry through the cloud's own OIDC trust. Never write a key
   into a workflow file. Do not set a static key and federation inputs together.
4. **Cost.** Every run uses Actions minutes and model usage. Keep `timeout-minutes` and `--max-turns` low.

## Why they are built this way

- **Pinned by commit.** Each `uses:` line names a full commit with the release tag in a trailing comment. A tag can be
  moved; a commit cannot. To bump: resolve the new tag to its commit (`gh api repos/<owner>/<repo>/git/ref/tags/<tag>`,
  and when that returns an annotated tag object, `gh api repos/<owner>/<repo>/git/tags/<sha>`), read the release notes,
  change both the hash and the comment, and let review approve the diff.
- **Least privilege.** `permissions: {}` at the top, then only what the job needs. The review job gets
  `pull-requests: write` because it comments; nothing gets `contents: write`.
- **Who can trigger it.** The action only responds to users with write access. Leave `allowed_non_write_users` and
  `allowed_bots` unset: setting them lets people or apps you have not vetted put text in front of the model.
- **Untrusted text.** Issue bodies, comments and pull request text reach the model. The action strips some hidden
  content, but new tricks appear, so keep the token narrow and treat what Claude writes as unreviewed.
- **No `pull_request_target`.** Fork pull requests run without secrets under `pull_request`. Switching to
  `pull_request_target` would give secrets to code from outside the repository.
- **Logs are readable by anyone who can read the repository.** Leave `show_full_output` off.

## Adapting

- Change the trigger word with `trigger_phrase`, or trigger by `assignee_trigger` or `label_trigger`.
- To run the review plugin on demand only, replace the `pull_request` trigger with a `workflow_dispatch` or a label.
- Self-hosted runners: the action accepts `path_to_claude_code_executable` and `path_to_bun_executable` for tools that are
  already installed on the runner.
- The plugin marketplace address and plugin name in `claude-review.yml` come from the action's documentation; re-check
  them whenever you bump the pin.
