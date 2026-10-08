---
name: github
description: "GitHub through the gh CLI, including GitHub Enterprise Server, GHE.com data-residency tenants and Enterprise Managed Users: PRs, issues, Actions runs and logs, reviews, releases, API queries. Use for any GitHub task or 'which gh command' question. Not for local-only git work or complex web-UI flows."
---

# GitHub via `gh`

Use `gh` for everything GitHub-side; plain `git` for local commits, branches and pushes. Never
print a token (`gh auth token` output stays out of chat, logs and files).

## Which host am I talking to?
| Instance | Hostname | Auth |
|---|---|---|
| github.com | `github.com` (default) | `gh auth login`; or `GH_TOKEN` |
| GHE.com (data residency) | `<tenant>.ghe.com` | `gh auth login --hostname <tenant>.ghe.com`; `GH_TOKEN` also applies to `*.ghe.com` |
| GitHub Enterprise Server | your server, e.g. `github.<org>.example` | `gh auth login --hostname <host>`; or `GH_ENTERPRISE_TOKEN` |

- Inside a clone, `gh` infers the host from the `origin` remote. Elsewhere it uses `github.com`
  unless you pass `--hostname <host>` (auth, `gh api`), `--repo HOST/OWNER/REPO`, or set `GH_HOST`.
- `GH_REPO=HOST/OWNER/REPO` pins the repo for commands that otherwise need a local clone.
- Check first: `gh auth status` lists every host and the account on each. One machine can be signed
  in to github.com and an enterprise host at the same time.
- `gh config set -h <host> git_protocol https` (or `ssh`) sets the clone protocol per host.
- Enterprise Server API paths are `https://<host>/api/v3/...` and `/api/graphql`; `gh api
  --hostname <host> <path>` handles that for you, so always pass the short path (`repos/o/r`).

## Enterprise gotchas
- **Enterprise Managed Users (EMU):** accounts belong to the company identity provider and usually
  carry a suffix (`name_shortcode`). They cannot create public repos or gists, and cannot push,
  open issues or PRs, or comment outside the enterprise. A 403 or 404 on a public repo action is
  often this, not a bug.
- **SAML SSO orgs (non-EMU):** a token must be authorised for the org. Symptom: 403 with "Resource
  protected by organization SAML enforcement". Fix: `gh auth refresh -h <host>` and complete SSO in
  the browser, or authorise the token in the web UI.
- **IP allow lists:** an org may only accept requests from its network or VPN. A 403 that mentions
  an IP allow list is a network problem, not a dead token.
- **Fine-grained token or app restrictions:** the org may block classic tokens or require approval.
  Read the error body (`gh api ... --include`) before retrying.
- **Data residency (GHE.com):** API host is `api.<tenant>.ghe.com`; never assume `api.github.com`.
- Respect org policy on forks, Actions, Copilot and third-party apps; do not work around a block.

## Common commands
```bash
# PRs
gh pr list --repo OWNER/REPO --state open
gh pr view 55 --repo OWNER/REPO --json title,state,mergeable,reviewDecision,statusCheckRollup
gh pr checks 55 --repo OWNER/REPO
gh pr create --fill                      # from the current branch
gh pr diff 55 --repo OWNER/REPO
gh pr merge 55 --squash --auto           # merges when required checks pass (if the repo allows auto-merge)

# Issues
gh issue list --repo OWNER/REPO --state open --json number,title,labels
gh issue create --title "..." --body "..."

# Actions
gh run list --repo OWNER/REPO --limit 10
gh run view <run-id> --repo OWNER/REPO --log-failed   # only the failing steps
gh run rerun <run-id> --failed --repo OWNER/REPO
gh run watch <run-id> --repo OWNER/REPO --exit-status

# API (works on every host with --hostname)
gh api repos/OWNER/REPO --jq '{default: .default_branch, license: .license.spdx_id}'
gh api --hostname github.<org>.example repos/OWNER/REPO/pulls/55 --jq '.title'
gh api graphql -f query='query { viewer { login } }'
gh api --paginate repos/OWNER/REPO/issues --jq '.[].number'
```

## Habits
- Prefer `--json <fields> --jq <filter>` over parsing human output.
- Always pass `--repo` (or `GH_REPO`) when you are not inside the clone.
- Reading CI failures: `gh run view --log-failed` first; the full log only if that is empty.
- Rate limits: `gh api rate_limit --jq .resources.core`; cache repeated reads with `gh api --cache 1h`.
- Anything visible to other people (PR comments, issue replies, releases, merges into a deploying
  branch) follows your team's review rules; confirm with the user when in doubt.
