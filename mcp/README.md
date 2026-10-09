# MCP servers

Setup registers one MCP server by itself: `find`, the local search over your documents and notes (no network).
`golden-config.template.json` describes it and the other generic servers worth having, each with its data egress
stated, and `tools/mcp-healer/` keeps your configuration matching the copy you fill in. Check your organisation's policy first: admins can
deploy, allow or deny MCP servers through managed settings, and those always win.

| server | default in template | egress | needs |
|---|---|---|---|
| tokensave | ensure | none (local index) | pinned binary, `tokensave init` per repo |
| playwright | ignore (optional; the Playwright CLI is preferred, guide 45) | local browser, only sites you open | Node.js, pinned `@playwright/mcp` |
| chrome-devtools | ignore (optional) | local browser; vendor usage statistics and CrUX trace-URL lookups switched off by flags and env | Node.js, Chrome |
| context7 | ignore (optional) | **hosted**: queries leave | optional `CONTEXT7_API_KEY` |
| github (hosted, read-only, `gh` token) | ignore (optional) | **hosted** by GitHub | `gh auth login`; the GitHub CLI app approved for your org |
| github-pat (hosted, read-only, own token) | ignore (optional) | **hosted** by GitHub | `WB_GITHUB_MCP_PAT` (fine-grained, read scopes) |
| github-ghe (GHE.com tenant) | ignore (optional) | **hosted** by GitHub, your tenant | `WB_GITHUB_MCP_PAT`; tenant name filled in |
| github-local (pinned local server) | ignore (optional) | local process; calls the GitHub API from your network | `gh auth login`; `gh_mcp_local.py HOST --install` once |
| find (local knowledge search) | ensure (registered by setup) | none (local index) | the knowledge virtual environment from setup |
| mslearn | ignore (optional) | **hosted** by Microsoft: queries leave; public docs only | nothing |
| azure (read-only) | ignore (optional) | local process; Azure Resource Manager with your `az login` | Node.js, Azure CLI signed in |
| azure-devops | ignore (optional) | local process; your Azure DevOps organisation with your `az login` | Node.js, Azure CLI, organisation name filled in |
| atlassian (Rovo) | ignore (optional) | **hosted** by Atlassian: Jira and Confluence content you can read | Cloud site; sign in with `/mcp` |
| bigquery | ignore (optional) | **hosted** by Google: queries and results | Cloud project roles, your own OAuth client (`WB_GOOGLE_OAUTH_CLIENT_ID`) |
| gcloud (preview) | ignore (optional) | **hosted** by Google: runs gcloud and bq as you | Cloud project roles, your own OAuth client |
| ms365 (community, read-only) | ignore (optional) | Microsoft Graph only | your own tenant app: `WB_MS365_CLIENT_ID`, `WB_MS365_TENANT_ID`, admin consent |
| brave-search | ignore (optional) | **hosted**: queries leave | `BRAVE_API_KEY` |
| exa | ignore (optional) | **hosted**: queries leave | `EXA_API_KEY` or OAuth |
| tavily | ignore (optional) | **hosted**: queries leave | `TAVILY_API_KEY` |
| postgres (read-only) | ignore (optional) | local process; talks only to the database you name; results enter the session | `uv`, `POSTGRES_MCP_DATABASE_URI` for a read-only role on a dev or replica database |

Not included, on purpose: servers that act on personal infrastructure or accounts, anything
AGPL-licensed, and servers that duplicate a built-in tool without adding much. Memory and code-intelligence servers
under AGPL, GPL or non-commercial licences are not shipped. Claude Code's built-in WebSearch and
WebFetch cover most search needs; the search servers are for teams that need more volume.

## find (local knowledge search)
`plugins/workbench-core/skills/find/scripts/find_mcp.py` serves three tools over stdio: `search` (hybrid when vectors
exist, keyword otherwise; optional `root`), `show` (the paragraphs around a ref) and `related` (files linked to a ref,
`depth` 1 to 3). It reads only the local index, which covers your document libraries, captured pages, the how-to
library and your knowledge base (root `kb`). Every result, hit and related file carries `"untrusted": true`: the text
comes from documents and is data, never instructions. The skill and CLI stay the primary interface; the server is for
subagents and the desktop app. To plug in a different source, see `docs/engineering/knowledge-providers.md`.

## Document conversion licences
The find index converts Office, PDF and HTML files to text with MarkItDown. These are the licences of the four
converters teams usually weigh, each quoted from the project's own LICENSE file (read in October 2026).

| Converter | Licence text, quoted | In this kit |
|---|---|---|
| MarkItDown | "MIT License" ... "Permission is hereby granted, free of charge, to any person obtaining a copy of this software" | installed in the knowledge environment, version pinned |
| Docling | "MIT License" ... "Permission is hereby granted, free of charge, to any person obtaining a copy of this software" | not shipped |
| Unstructured | "Apache License Version 2.0, January 2004" | not shipped |
| Apache Tika | "Apache License Version 2.0, January 2004"; also "Apache Tika includes a number of subcomponents with separate copyright notices and license terms." | not shipped |

A project licence does not cover its dependencies, bundled components, model weights or optional extras: read those
before adding one, and have your licence review sign off the exact version.

## Using the healer
```bash
python tools/mcp-healer/mcp_healer.py apply --golden <your-golden.json> --dry-run   # the plan
python tools/mcp-healer/mcp_healer.py apply --golden <your-golden.json>             # backup, then write
python tools/mcp-healer/mcp_healer.py check                                         # probe every server (never runs a headersHelper)
```
Or run `/workbench-core:mcp-heal` yourself (Claude can only suggest it). If a managed MCP policy is present (`managed-mcp.json`,
or `allowedMcpServers`, `deniedMcpServers`, `allowManagedMcpServersOnly`, `managedMcpServers` or
`strictPluginOnlyCustomization` in managed settings), `apply` refuses to write and names the
policy. The healer reads only file-based managed settings; `/status` shows policy delivered by the
registry or by the server.

## Keys
Keys are written as `${VAR}` in the template (or come from a `headersHelper` command) and are expanded by
Claude Code when it starts a server. Keep the values in your environment or your OS credential store, never in the
golden file, a repo, or a chat. The healer refuses to write an `ensure` entry while a `{{PLACEHOLDER}}` or a
`${VAR}` without a default is still unset, and says which. Corporate keys come from whoever owns the account; never use a personal key for work
data. Behind a TLS-inspecting proxy, Node-based servers need `NODE_EXTRA_CA_CERTS` pointing at your
organisation's CA bundle.

## Token cost
Every MCP tool schema that loads at startup costs context on every turn. The template sets
`"alwaysLoad": false` so tools load on demand through tool search. Park servers you rarely use
(`"action": "park"`): the definition stays in `.claude.json` under `mcpServersParked`, which Claude
Code ignores, and `mcp_healer.py unpark NAME` brings it back.

## GitHub: which server for which host
Start with Step 0 for every host, then pick one entry. `<HOST>` is `github.com`, `<tenant>.ghe.com` or your Enterprise
Server host, for example `ghe.example.com`.
```bash
gh auth login --hostname <HOST> --web --git-protocol https --skip-ssh-key
gh auth status                                # every host and account
gh api --hostname <HOST> user --jq .login     # a SAML 403 here: gh auth refresh -h <HOST>, finish SSO in the browser
```
| Host | First choice | Then | Notes |
|---|---|---|---|
| github.com (SAML or EMU) | `github`: hosted, `/readonly`, token from `gh` via `gh_mcp_headers.py` | `github-pat`, then `github-local`, then plain `gh` | needs the GitHub CLI OAuth app approved for the org; the `gh` token is broad although the tools are read-only |
| github.com behind an org IP allow list | `github-local` | plain `gh` | the hosted endpoint answers 403 because GitHub's servers, not your laptop, call the API |
| GHE.com (data residency) | `github-ghe` with a fine-grained token | `github-local` with your tenant host | EMU: the enterprise must allow personal tokens; the `/readonly` path is not documented for this host, so read-only comes from the `X-MCP-Readonly` header |
| GitHub Enterprise Server | plain `gh` (the `github` skill) | `github-local` (EXPERIMENTAL) | GitHub documents the local server there, Anthropic's GHES page says use the gh CLI: prove it on your instance first |

- `gh_mcp_headers.py <host>` prints only `{"Authorization":"Bearer <token>"}` (the token comes from `gh auth token`) and
  exits 1 when gh has no token. It runs only when Claude Code connects; `mcp_healer.py check` never runs a helper.
- `gh_mcp_local.py <host>` runs `github-mcp-server stdio --read-only --lockdown-mode
  --toolsets=context,repos,issues,pull_requests,actions` with the token in the child environment only, and drops every
  inherited `GITHUB_*` variable first (an environment variable beats a flag in that server). `--install` downloads the
  pinned release for Windows or Linux x86_64 and checks its SHA-256 before unpacking. Docker is not used: Docker
  Desktop needs a paid licence at larger organisations.
- Read-only tools are not a read-only token: `/readonly` and `--read-only` limit what the server offers, not what the
  token could do elsewhere. Use `github-pat` with a fine-grained token when that matters.
- Lockdown mode filters public-repository content only and is "not an authorization boundary". Repository text stays
  untrusted whatever you set. Dynamic toolsets no longer exist; `X-MCP-Toolsets` (hosted) and `--toolsets` (local)
  choose what is exposed.
- Some credential names, such as common cloud and API-key variables, read as empty inside remote `url` and `headers`.
  The kit's own name `WB_GITHUB_MCP_PAT` avoids the question (it replaces the earlier `GITHUB_MCP_PAT`). After editing,
  run `claude mcp get <name>`: it must show the `${...}` reference, never a value.
- Reviewing a repository you do not own: use the `repo-review` skill, never an MCP server loaded from that repository.

## Enterprise catalog
Every entry is off (`ignore`) and states its egress. None of them adds access you do not already have: they act with
your sign-in. Check each with your organisation before enabling it.
- **mslearn**: public Microsoft documentation search; queries go to Microsoft, no sign-in.
- **azure**: the Azure MCP server (stable 2.0 line, pinned, `--read-only`). Run `az login` first.
- **azure-devops**: local mode on the Azure CLI login. The hosted Azure DevOps endpoint needs your own Entra app
  registration for Claude Code, so it is not in the catalog.
- **atlassian**: Rovo MCP v2 for Jira and Confluence Cloud (Data Center is not supported by it). An Atlassian admin
  can block the endpoint; write tools exist.
- **bigquery**, **gcloud**: Google-hosted. They need project roles for your identity and your own OAuth client (desktop
  type); the client secret is entered when Claude Code asks and never stored in the golden file. `gcloud` is a public
  preview and can run mutating commands with your rights.
- **ms365**: the community `@softeria/ms-365-mcp-server` (MIT), not bundled, pinned to an exact version, `--read-only`,
  `--org-mode`, and an `--enabled-tools` list limited to reading your own mail, calendar and meeting transcripts
  (checked against that version's tool list; re-check when you re-pin). It uses YOUR tenant's app registration:
  `MS365_MCP_CLIENT_ID=${WB_MS365_CLIENT_ID}` and `MS365_MCP_TENANT_ID=${WB_MS365_TENANT_ID}`. The healer refuses the
  entry until both variables are set, and the vendor's built-in multi-tenant app is never used. Needs tenant-admin
  consent for `Mail.Read`, `Calendars.Read`, `OnlineMeetings.Read` and `OnlineMeetingTranscript.Read.All`, and the
  tenant's transcript policy must allow transcripts (Graph answers 403 when it does not). It does not sanitise what it
  returns: mail and transcript text can carry instructions aimed at the model, so treat it as data. Have your security
  team review the package at the pinned version before enabling it.

### Rejected
| Server | Why not |
|---|---|
| `floriscornel/teams-mcp` | defaults to a first-party Microsoft client ID that is not yours; reads chats and channels only, no transcripts |
| Lokka in its default mode | defaults to the vendor's multi-tenant app and exposes a broad generic Graph tool that can write; admin-oriented |
| a bot-registration Teams MCP server | needs a bot registration and a client secret, and reaches channel threads only |
| any server fed a browser-extracted access token (`set-access-token`, `AUTH_TOKEN`) | token extraction; it works around the sign-in policy instead of using it |

Not in the catalog on purpose: a Microsoft 365 connector that needs a Copilot licence, and any server that asks for the
broad Graph permissions it does not need for reading.

## tokensave (local code graph)
A Rust code-graph server (MIT, `aovestdipaperino/tokensave`) that answers "who calls this", "what
breaks if I change it" and similar from a local index, so Claude reads less code.

Install a **pinned, verified** binary. Never run `tokensave install`, `reinstall`, `upgrade`, `doctor`,
`uninstall`, `claude-install` or `claude-uninstall`: `install` registers the server globally and adds
its own hooks, CLAUDE.md rules and tool permissions; `reinstall` and `claude-install` rewrite them
again and `uninstall` and `claude-uninstall` remove them (tokensave itself says to run `reinstall` to
update permissions); `upgrade` replaces the binary outside your control; `doctor` is not read-only,
it "auto-repairs" by adding hooks to your Claude Code settings (observed with 7.12.1 on a plain
diagnostic run). The workbench guard blocks all seven when they are typed as the command, also inside `$(...)`,
a script block or a `powershell -Command` string. It does not see one that another program starts or that is spelled
indirectly (`xargs`, `find -exec`, `Start-Process`, an alias, a shim: the list is in `docs/known-limits.md`), so the rule
holds only while nobody goes looking for a way around it.
The kit pins 7.12.1: from 7.13.0, the first launch of a new version silently reinstalls its agent integrations
(rules text and git-hook sections), so move past the pin only after reviewing what that writes.
```bash
tag=v7.12.1      # pick a release and keep it until you choose to move
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
- **Its edit tools are guarded like Edit and Write.** The server can also change files (`str_replace`, `multi_str_replace`,
  `insert_at`, `insert_at_symbol`, `replace_symbol`, `ast_grep_rewrite`, `replace_lines`, `delete_symbol`). The guard puts
  their `path` (tokensave has no `project_root` option: a relative path is read against the folder the server was started in,
  taken to be the session's folder; a root the call supplies is judged as well, and any other base-folder key makes the call ask)
  through the same checks: credential files, `.env` files, the guards' own configuration and
  your settings files are refused, and so is a folder that holds them (`~/.claude`, your home folder), because a rewrite tool
  reaches everything beneath the folder it is given. Approving the server as a whole therefore does not approve those
  paths; the search and callers tools are untouched.
- Pass `graph_root` to query another initialised repo instead of re-indexing.
- It misses some cross-file calls in some languages; confirm a blast radius with grep before a
  risky change.

## Playwright and Chrome DevTools
For testing apps you own or are allowed to test. Keep versions pinned (`@x.y.z`, never `@latest`)
and `--isolated`, so neither server touches your signed-in browser profile. Chrome DevTools MCP
sends usage statistics to its vendor by default, and its performance tools send trace URLs to
Google's CrUX API; the template turns both off with `--no-usage-statistics`,
`CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1` and `--no-performance-crux`. Do not remove them.

## Hosted servers (context7, GitHub remote, mslearn, atlassian, bigquery, gcloud, brave-search, exa, tavily)
Everything you send leaves your machine. Enable one only if your organisation allows that
service, and never put code, internal names, customer data or secrets in a query.
