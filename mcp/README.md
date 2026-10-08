# MCP servers

The kit installs no MCP server by itself. `golden-config.template.json` describes the generic
servers worth having, each with its data egress stated, and `tools/mcp-healer/` keeps your
configuration matching the copy you fill in. Check your organisation's policy first: admins can
deploy, allow or deny MCP servers through managed settings, and those always win.

| server | default in template | egress | needs |
|---|---|---|---|
| tokensave | ensure | none (local index) | pinned binary, `tokensave init` per repo |
| playwright | ensure | local browser, only sites you open | Node.js, pinned `@playwright/mcp` |
| chrome-devtools | ignore (optional) | local browser; vendor usage statistics and CrUX trace-URL lookups switched off by flags and env | Node.js, Chrome |
| context7 | ignore (optional) | **hosted**: queries leave | optional `CONTEXT7_API_KEY` |
| github (remote, read-only) | ignore (optional) | **hosted** by GitHub | `GITHUB_MCP_PAT` (fine-grained, read scopes) |
| brave-search | ignore (optional) | **hosted**: queries leave | `BRAVE_API_KEY` |
| exa | ignore (optional) | **hosted**: queries leave | `EXA_API_KEY` or OAuth |
| tavily | ignore (optional) | **hosted**: queries leave | `TAVILY_API_KEY` |

Not included, on purpose: servers tied to one person's infrastructure (SSH, databases, hosting
accounts, messaging), anything AGPL-licensed (for example a popular local-memory server), and
servers that duplicate a built-in tool without adding much. Claude Code's built-in WebSearch and
WebFetch cover most search needs; the search servers are for teams that need more volume.

## Using the healer
```bash
python tools/mcp-healer/mcp_healer.py apply --golden <your-golden.json> --dry-run   # the plan
python tools/mcp-healer/mcp_healer.py apply --golden <your-golden.json>             # backup, then write
python tools/mcp-healer/mcp_healer.py check                                         # probe every server
```
Or ask Claude to run the `mcp-heal` skill. If a managed MCP policy is present (`managed-mcp.json`,
or `allowedMcpServers`, `deniedMcpServers`, `allowManagedMcpServersOnly`, `managedMcpServers` or
`strictPluginOnlyCustomization` in managed settings), `apply` refuses to write and names the
policy. The healer reads only file-based managed settings; `/status` shows policy delivered by the
registry or by the server.

## Keys
Keys are written as `${VAR}` in the template and expanded by Claude Code when it starts a server.
Keep the values in your environment or your OS credential store, never in the golden file, a repo,
or a chat. Corporate keys come from whoever owns the account; never use a personal key for work
data. Behind a TLS-inspecting proxy, Node-based servers need `NODE_EXTRA_CA_CERTS` pointing at your
organisation's CA bundle.

## Token cost
Every MCP tool schema that loads at startup costs context on every turn. The template sets
`"alwaysLoad": false` so tools load on demand through tool search. Park servers you rarely use
(`"action": "park"`): the definition stays in `.claude.json` under `mcpServersParked`, which Claude
Code ignores, and `mcp_healer.py unpark NAME` brings it back.

## GitHub: which server for which host
- github.com: the template's remote endpoint `https://api.githubcopilot.com/mcp/readonly` (the
  `/readonly` suffix restricts it to read tools).
- GHE.com data residency: `https://copilot-api.<tenant>.ghe.com/mcp` (add `/readonly` the same way).
- GitHub Enterprise Server: no remote endpoint. Run the local `github-mcp-server` binary with
  `GITHUB_HOST=https://<your-server>` and `--read-only`, or skip MCP and use the `gh` CLI through
  the `github` skill, which already handles every host.
- Enterprise Managed Users and SSO orgs: the token must be authorised for the org; see the `github`
  skill's enterprise notes.

## tokensave (local code graph)
A Rust code-graph server (MIT, `aovestdipaperino/tokensave`) that answers "who calls this", "what
breaks if I change it" and similar from a local index, so Claude reads less code.

Install a **pinned, verified** binary. Never run `tokensave install` or `tokensave upgrade`:
`install` registers the server globally and adds its own hooks, CLAUDE.md rules and tool
permissions; `upgrade` replaces the binary outside your control.
```bash
tag=v7.15.0      # pick a release and keep it until you choose to move
gh release download $tag -R aovestdipaperino/tokensave -p "tokensave-$tag-x86_64-windows.zip" -p SHA256SUMS
grep "tokensave-$tag-x86_64-windows.zip" SHA256SUMS | sha256sum -c -
```
(Linux and WSL: the `x86_64-linux.tar.gz` asset. PowerShell: compare `(Get-FileHash <zip>).Hash`
with the line in `SHA256SUMS`.) GitHub Enterprise users: `gh release download` needs
`--hostname github.com` if your default host is an enterprise server. Unpack to a folder you own,
for example `%USERPROFILE%\.local\bin`, and put its absolute path in `{{TOKENSAVE_BIN}}`. Then, once
per repository you want indexed:
```bash
cd <repo> && tokensave init        # creates .tokensave/ (add it to .gitignore)
tokensave sync                     # incremental refresh after changes
```
Rules that keep it contained:
- **No hook command may contain the word "tokensave".** A hook that calls its CLI can re-register
  its integrations. Run `tokensave sync` by hand or from your own scheduler.
- Pass `graph_root` to query another initialised repo instead of re-indexing.
- It misses some cross-file calls in some languages; confirm a blast radius with grep before a
  risky change.

## Playwright and Chrome DevTools
For testing apps you own or are allowed to test. Keep versions pinned (`@x.y.z`, never `@latest`)
and `--isolated`, so neither server touches your signed-in browser profile. Chrome DevTools MCP
sends usage statistics to its vendor by default, and its performance tools send trace URLs to
Google's CrUX API; the template turns both off with `--no-usage-statistics`,
`CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1` and `--no-performance-crux`. Do not remove them.

## Hosted servers (context7, GitHub remote, brave-search, exa, tavily)
Everything you send leaves your machine. Enable one only if your organisation allows that
service, and never put code, internal names, customer data or secrets in a query.
