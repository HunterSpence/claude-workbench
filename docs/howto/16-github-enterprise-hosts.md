# Use GitHub Enterprise hosts with gh

Automates it: /workbench-core:github

## When to use
Your code lives on an enterprise GitHub host: managed users on github.com, a `<tenant>.ghe.com` data-residency tenant, or
Enterprise Server such as `ghe.example.com`. Sign in through your organisation's single sign-on.

## Steps
1. Sign in once per host (the web flow keeps the token in the system credential store; never use `--insecure-storage`):
   `gh auth login --hostname ghe.example.com --web --git-protocol https --skip-ssh-key`
2. List every host and account: `gh auth status`. Several accounts on one host: `gh auth switch --hostname <host> --user <login>`.
3. Let git use the same sign-in for HTTPS: `gh auth setup-git --hostname <host>`. Keep one credential helper per host.
4. Inside a clone, `gh` takes the host from `origin`. Elsewhere pass `--hostname <host>` (auth, `gh api`), `--repo HOST/OWNER/REPO`,
   or set `GH_HOST`.
5. Call the API with the short path: `gh api --hostname <host> repos/<owner>/<repo> --jq .default_branch`. For Enterprise Server `gh`
   adds `/api/v3` itself; a `.ghe.com` tenant's API host is `api.<tenant>.ghe.com`, never `api.github.com`.
6. Token variables, if you use them: `GH_TOKEN` applies to github.com and `*.ghe.com`; `GH_ENTERPRISE_TOKEN` applies to Enterprise Server.

## Verify
- `gh auth status` lists the host with your organisation account.
- `gh api --hostname <host> user --jq .login` prints your login.
- `gh pr list --repo <host>/<org>/<repo>` returns the repository's pull requests.

## Common failures
- **403 "Resource protected by organization SAML enforcement":** `gh auth refresh -h <host>` and finish single sign-on in the browser.
- **403 mentioning an IP allow list:** a network problem, not a dead token. Connect from the allowed network or VPN.
- **403 or 404 on a public repository action:** managed users cannot act outside the enterprise. That is policy, not a bug.
- **Wrong account active:** `gh auth switch`, then re-check with `gh auth status`.
- **Sign-in prompts keep appearing:** two credential helpers answer in turn. Keep one.
- **Never print a token** (`gh auth token`) into chat, a log or a file.
