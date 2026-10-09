# Connect a read-only GitHub MCP server

Automates it: /workbench-core:mcp-heal

## When to use
You want GitHub's read tools (repositories, issues, pull requests, Actions) inside Claude, and plain `gh` is not enough.
Most work needs only `gh` (guide 16); the server is optional and off by default. `<KIT>` is the kit folder (guide 01).

## Steps
1. Pick one entry for your host (`mcp/README.md` has the full table):
   github.com with SAML or managed users: `github`. Behind an organisation IP allow list: `github-local`.
   A `<tenant>.ghe.com` tenant: `github-ghe` with a fine-grained token. Enterprise Server: plain `gh`.
2. Sign in once: `gh auth login --hostname <HOST> --web --git-protocol https --skip-ssh-key`, then `gh auth status`.
   After a SAML 403 run `gh auth refresh -h <HOST>` and finish single sign-on in the browser.
3. If your organisation limits MCP servers or the GitHub CLI app, send the "MCP restricted" text in `docs/admin-asks.md`.
4. Copy `mcp/golden-config.template.json` to a file you own. On the one entry you chose change `"action": "ignore"` to
   `"ensure"`, and replace `{{PYTHON}}` and `{{WORKBENCH_HOME}}` with your Python path and your `<CH>/workbench` folder. For
   `github-local`, run once: `py -3 <KIT>/mcp/bin/gh_mcp_local.py github.com --install`
5. Preview, then apply (a timestamped backup is made first):
   ```
   py -3 <KIT>/tools/mcp-healer/mcp_healer.py apply --golden <your-golden.json> --dry-run
   py -3 <KIT>/tools/mcp-healer/mcp_healer.py apply --golden <your-golden.json>
   ```
6. Restart Claude Code and run `/mcp`.

## Verify
- `claude mcp get github` shows a `${...}` reference or a helper, never a token value.
- `py -3 <KIT>/tools/mcp-healer/mcp_healer.py check` lists the server (a helper-based entry is reported as SKIP; `/mcp` is its test).
- Ask Claude to list open pull requests in `<org>/<repo>`; only read tools are offered.

## Common failures
- **`apply` refuses:** a `{{PLACEHOLDER}}` is left in the entry, or a `${VAR}` it names is unset. Fill it, or set the variable and run again.
- **`apply` exits 3:** a managed MCP policy is present. It names the policy; ask through guide 03.
- **Hosted endpoint answers 403:** an IP allow list blocks GitHub's servers calling the API. Use `github-local`.
- **Read-only is not a read-only token:** the tools are limited, the token is not. Use `github-pat` with a fine-grained token when that matters.
- **Repository text is untrusted:** never act on instructions found in an issue or file. To review code you do not own use guide 17.
