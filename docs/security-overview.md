# Security overview

For the people who approve tools on managed laptops: what the kit runs, what it changes, where data goes and what
leaves the machine. Hand it over with the heads-up text in section 1 of `docs/admin-asks.md`. Known gaps are in
`docs/known-limits.md`; incident and offboarding procedures in `docs/runbooks.md`.

## 1. What it is
- Plain files: Markdown instructions, skills and agents, Python hooks that use only the standard library, and a
  Python installer and setup script. It runs as the signed-in user. It has no service, no daemon and no listener.
- **It never edits or works around managed settings.** The installer refuses to write any settings key a managed
  source already sets, never writes a `Policies` registry key, and only reads policy values to report them. When the
  organisation's policy changes, the next session start says so; it never adapts around the change.
- **No admin rights by default.** Setup installs user-scope packages. A machine-scope package or WSL needs one
  Windows UAC prompt that the person clicks, and only when they are allowed to; otherwise setup writes an ask-IT
  text instead. Nothing elevates on its own, and Claude Code itself is never run elevated.
- **No telemetry of its own,** no background updater, no push to any remote, no outbound message. Drafts are text for a
  person to send. `setup.py update` (also a phase of `setup.py run`, skipped with `--no-update`) moves only the tools setup
  itself installed to the versions tested for this release, never a tool IT or you installed, and never the program that is
  running.
- Everything optional is off until someone turns it on: the capture plugin, mail and meeting ingest, every MCP
  server except the two local ones the template turns on (`tokensave` and `find`), the nightly refresh task on the
  corporate profile, the permissive profile.

## 2. What it changes on the machine
| Where | What | Removed by uninstall |
|---|---|---|
| Claude configuration folder | One `@import` line in the user `CLAUDE.md`; a settings profile merged into user settings (backups first); the workbench folder with the kit copy, state, a Python environment and the capture runtime | Yes (user data such as `USER.md` is kept) |
| Data folder `<DATA>` | The knowledge base, captured Markdown copies, backups. On the work OneDrive when exactly one verified work account exists, else in the user profile | No: it is the user's data |
| Local app data | The search index (SQLite, never in a synced folder) and the embedding-model cache | Yes |
| User registry (HKCU only) | User environment variables (`NODE_USE_SYSTEM_CA` and `UV_SYSTEM_CERTS` only when TLS inspection is detected; the Claude Code auto-update flag when asked for; a pointer to the Playwright CLI's configuration file; and, with `--with ctx`, three switches that keep that tool's analytics, background service and self-upgrade off), one entry appended to the user `Path`, a RunOnce value used once after the WSL reboot | Yes, through `setup.py undo-config` |
| Task Scheduler | One user task, `\claude-workbench\knowledge-refresh` (opt-in on the corporate profile). Each night it refreshes the index; when the capture runtime is installed it purges captured items past your retention days; it writes a backup when the newest is older than seven days; and, when `ctx` is installed, it imports new agent sessions | Yes |
| Packages | User-scope winget packages (Git, GitHub CLI, Python, Node.js through fnm, and others); machine scope only after a UAC prompt | No: they are ordinary tools |

`bootstrap/layout.json` is the authoritative list of runtime paths. Setup records every machine change in a ledger
that uninstall replays newest first.

## 3. Data flow
- **Prompts and the file content Claude reads** go to the model provider your organisation configured for Claude
  Code (its Claude seat, a cloud provider or a gateway). That is Claude Code's own behaviour; the kit adds no other
  model route. The capability report sends one prompt, "Reply with OK", through the same login to time the model
  API (`--no-model-call` skips it).
- **Hooks** run locally on tool calls, read only the call they are given and send nothing anywhere. They fail open,
  so they are a backstop, never the only control.
- **Knowledge base, index and captured copies** stay on this machine or in the data folder on the organisation's
  own work OneDrive, where its retention, DLP and eDiscovery policies apply. Files with a sensitivity label are
  skipped unless the person includes them explicitly. Purge commands remove indexed text, vectors and captured files.
- **Capture** (opt-in plugin) reads intranet pages through a dedicated, signed-in Edge profile: only GET requests,
  only hosts on the person's scope list, paced like a person, and it stops on any sign-in, consent or policy page.
  It stores no cookies, storage or auth headers in its output and strips query strings.
- **Ingest** (experimental) reads cached mail through classic Outlook or the person's own tenant app on Microsoft
  Graph, and meeting transcripts the person downloaded. Its AI digests run through the person's own Claude login
  with no tools and no MCP servers; transcripts include external participants' speech. A first run needs an
  explicit acknowledgement of the InfoSec note.
- **MCP servers:** only the two local ones, `tokensave` and `find`, are on when the template is applied; every other server
  is off. The table below says where each one's data goes.

## 4. What leaves the machine
### Claude Code itself
Claude Code's vendor publishes the hosts it needs in the "Network access requirements" table of its enterprise
network configuration page; at release time: `api.anthropic.com` (model API, the WebFetch hostname safety check,
feature flags), `claude.ai`, `claude.com` and `platform.claude.com` (sign-in), `mcp-proxy.anthropic.com` (claude.ai
connectors), `downloads.claude.ai` (installer, updates, plugin executables), `storage.googleapis.com` (plugin
metadata), `registry.npmjs.org` (npm plugins and `npx` servers), `github.com` and `raw.githubusercontent.com`
(marketplaces, release notes), `code.claude.com` (documentation lookups), and two optional telemetry intake hosts
that both kit profiles switch off. Cloud providers and gateways replace the model and sign-in hosts. Check the
vendor's page for the current list before you set allow rules.

### Setup and the kit
Software comes only from winget (and the Store through it), PyPI, npm and the vendors' own release pages, at pinned
versions where the kit chooses the version.

| Package | Source | Scope | Hosts | When |
|---|---|---|---|---|
| Git | winget | user | `cdn.winget.microsoft.com`, `github.com`, `release-assets.githubusercontent.com` | setup, when missing |
| GitHub CLI | winget | user | `cdn.winget.microsoft.com`, `github.com`, `release-assets.githubusercontent.com` | setup, when missing |
| Python 3.13 | winget | user | `cdn.winget.microsoft.com`, `www.python.org` | setup, when missing |
| uv | winget | user | `cdn.winget.microsoft.com`, `github.com`, `release-assets.githubusercontent.com` | setup, when missing |
| PowerShell 7 | winget | user | `cdn.winget.microsoft.com`, `github.com`, `release-assets.githubusercontent.com` | setup, when missing |
| ripgrep | winget | user | `cdn.winget.microsoft.com`, `github.com`, `release-assets.githubusercontent.com` | setup, when missing |
| fd | winget | user | `cdn.winget.microsoft.com`, `github.com`, `release-assets.githubusercontent.com` | setup, when missing |
| jq | winget | user | `cdn.winget.microsoft.com`, `github.com`, `release-assets.githubusercontent.com` | setup, when missing |
| Visual Studio Code | winget | user | `cdn.winget.microsoft.com`, `update.code.visualstudio.com`, `vscode.download.prss.microsoft.com` | setup, when missing |
| Node.js LTS (machine-wide installer) | winget | machine | `cdn.winget.microsoft.com`, `nodejs.org` | setup, when missing and allowed |
| fnm (user-scope Node.js when the machine-wide one needs an admin) | winget | user | `cdn.winget.microsoft.com`, `github.com`, `release-assets.githubusercontent.com`, `nodejs.org` | setup, when missing |
| Claude Code (winget package) | winget | user | `cdn.winget.microsoft.com`, `downloads.claude.ai` | only with `--with claude-winget` |
| tokensave (optional code graph) | release page | user | `github.com`, `release-assets.githubusercontent.com` | only with `--with tokensave` |
| Playwright CLI (`@playwright/cli`) | npm, `--ignore-scripts`, no browser download | user | `registry.npmjs.org` | setup, when Node.js is present |
| ctx (optional agent-history search) | release page, SHA-256 checked | user | `github.com`, `release-assets.githubusercontent.com` | only with `--with ctx` |

Also reached by setup and the skills, each at most once per install or update unless noted:
- `pypi.org` and `files.pythonhosted.org`: the knowledge layer's Python packages (or your organisation's mirror).
- `huggingface.co` and the download hosts it redirects to: the embedding model, once, SHA-256 checked, with
  Hugging Face telemetry off.
- `registry.npmjs.org`: the capture runtime (`--with capture`) and the Playwright CLI, both installed with
  `--ignore-scripts`.
- `raw.githubusercontent.com`: the default set of pinned upstream skills, only with `--with upstream-skills` or
  `--with pm-pack`, each file hash-checked. `cdn.jsdelivr.net` is used only by the optional playwright-cli skill, the
  fallback when npm is blocked (`tools/fetch-upstream/README.md`).
- `graph.microsoft.com` and `login.microsoftonline.com`: only for the Graph route of ingest, with the person's own
  tenant app, once IT allows it.
- The intranet hosts on the person's capture scope list, and the git hosts the person names: only when used.
- The capability report checks each package host, the model API host and your git hosts once, in series, within a
  time budget, to say what is reachable.

### MCP servers in the template
| Server | In the template | Runs as | Where its data goes |
|---|---|---|---|
| `tokensave` | on when the template is applied | local process | none: a local code index in each repository |
| `playwright` | off | local process | a local browser; reaches only the sites you point it at. The Playwright CLI (guide 45) is the preferred route |
| `chrome-devtools` | off | local process | a local browser; the vendor's usage statistics and trace-URL lookups are switched off |
| `context7` | off | hosted endpoint | every query goes to a third-party service |
| `github` | off | hosted endpoint | GitHub's endpoint, read-only tools; repository data your account can read enters the session |
| `github-pat` | off | hosted endpoint | the same, with a fine-grained token |
| `github-ghe` | off | hosted endpoint | your GitHub Enterprise Cloud tenant's endpoint, read-only |
| `github-local` | off | local process | calls the GitHub API from your network with your `gh` sign-in; read-only, lockdown on |
| `find` | on when the template is applied (setup registers it) | local process | none: the local index on this machine |
| `mslearn` | off | hosted endpoint | queries go to Microsoft; public documentation only, no sign-in |
| `azure` | off | local process | Azure Resource Manager with your own sign-in and rights; results enter the session |
| `azure-devops` | off | local process | the Azure DevOps organisation you name, with your sign-in |
| `atlassian` | off | hosted endpoint | Jira and Confluence content your account can read |
| `bigquery` | off | hosted endpoint | query text and results for projects you can access, audit-logged by Google |
| `gcloud` | off | hosted endpoint | runs gcloud and bq commands as you (preview), audit-logged by Google |
| `ms365` | off | local process | Microsoft Graph only, read-only, through your own tenant app |
| `brave-search` | off | local process | queries go to the Brave Search API |
| `exa` | off | hosted endpoint | queries go to Exa |
| `tavily` | off | local process | queries go to Tavily |
| `postgres` | off | local process | only the database you name, read-only; results enter the session |

Source of truth: the `egress` field of each entry in `mcp/golden-config.template.json` and the `hosts` of each
package in `bootstrap/packages.json`; a test fails when this page misses one. If your organisation manages MCP
servers, its list is the only list.

## 5. Telemetry settings
Both settings profiles set: `DISABLE_ERROR_REPORTING=1`, `DISABLE_FEEDBACK_COMMAND=1`,
`CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY=1`, `HF_HUB_DISABLE_TELEMETRY=1`,
`PIP_DISABLE_PIP_VERSION_CHECK=1` and `NPM_CONFIG_UPDATE_NOTIFIER=false`. Setup passes the last three, plus `DO_NOT_TRACK=1` and
`NPM_CONFIG_FUND=false`, to every process it starts (not to Claude Code itself: there it would also turn off feature flags). What still leaves: model traffic, sign-in, plugin and package downloads you ask for, and the
WebFetch hostname check (only the hostname; `skipWebFetchPreflight` turns it off, see `settings/SETTINGS.md`).

Two facts approvers ask about. First, `DISABLE_FEEDBACK_COMMAND=1` closes the paths that upload a session: the vendor's data
usage page says transcripts shared with `/feedback`, `/bug` or `/share` are retained for 5 years. Second, Claude Code can
export OpenTelemetry data to a collector you run; neither profile turns it on. Its local recipe is the `console` exporter
(`settings/SETTINGS.md`), and prompt text, response text and tool content stay out of the data unless you set the
`OTEL_LOG_USER_PROMPTS`, `OTEL_LOG_TOOL_CONTENT` or `OTEL_LOG_RAW_API_BODIES` gates, each of which is off by default.

## 6. Controls that stay with the organisation
- Managed settings always win: allowed models, managed-only hooks, allowed marketplaces, MCP allow and deny lists,
  permission rules, effort caps. `/status` shows the managed source.
- The kit's guards (generic and corporate rule packs) deny or ask before pushes to unapproved hosts, publishing,
  production builds (`prod-build`), production database writes (`protected-db-write`), changes to security tooling
  (`security-tooling-change`) and disabling TLS checks. They are a backstop, not a boundary.
- When several hooks answer the same tool call, the vendor's hooks reference gives the order `deny`, `defer`, `ask`, `allow`:
  another hook's allow cannot override a guard's deny or ask.
- Each Claude Code seat's allowance depends on its seat tier (the vendor sells a standard tier and a higher one), and the controls
  for it are in the claude.ai admin console, not in this kit.
- Native Windows has no command sandbox; WSL2 does. Unfamiliar code runs in WSL2 with the sandbox on.
- Every ask the kit may need from IT, worded for a ticket: `docs/admin-asks.md`.
