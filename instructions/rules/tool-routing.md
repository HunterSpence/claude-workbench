# Tool routing (use these without being asked)

MCP tool schemas are deferred at startup: search with ToolSearch before you **ever claim a
configured tool is unavailable**. A server that "failed to connect" is a connection failure, not a
missing capability: say so and let the user fix it; never silently route around it.

## By task
- **Web research:** native WebSearch and WebFetch; long-form or comparison research goes to the
  `researcher` agent or `deep-research`. A 403 is not "unreadable": say which fetcher failed. A bot
  wall or captcha is a stop: hand it to the user. WebSearch is one per-session budget shared with
  every subagent: plan research fan-outs around it.
- **Work documents:** `find` searches one local index over synced work libraries, captured pages
  and the kit's how-tos; cite the originals.
- **Which knowledge tool** (guide 54): `find` for documents, `kb_search` for curated notes, `ctx` for past
  sessions, the code graph for symbols, WebSearch for the outside.
- **Office output:** `office-pptx`, `office-xlsx` and `office-docx` build files; `office-render`
  renders them so you check the result first, and scrubs a copy before an Office file leaves the
  organisation. Editing inside Office: the Claude for Microsoft 365 add-ins, if your admin allows them.
- **GitHub:** the `gh` CLI against your enterprise host (`--hostname`, or `GH_HOST`); the `github`
  skill covers the details.
- **Framework or SDK docs:** the vendor's site through WebFetch, or a docs MCP your organisation
  approved. Claude models, pricing, limits and evals: the bundled `claude-api` skill, never memory.
- **Code graph:** `rules/code-graph.md`. **Browser:** `rules/browser.md`.
- **Databases:** read-only unless the user asks otherwise; production writes are a Red Line.
- **Servers:** ssh as the least-privileged user that can do the job; an admin or root login is
  break-glass, so say why first.
- **Reports** meant for someone else: an Artifact link when your organisation's Claude offers
  Artifacts (your own organisation's data only; the user decides who sees it), else a Markdown
  file in the workspace, with its path.
- **Review:** the bundled `/code-review`, `/security-review` for the branch's security diff,
  `/simplify` for cleanup.
- **How-to guides:** search them with `find` (its root `howto`); read on demand, never always-loaded.

## Skills (use them when the task fits, unasked; invoke as `/workbench-core:<name>`)
`cascade` (fix, build, refactor, migrate) · `ratchet` (fix and re-audit until clean) · `handoff` · `spawn` ·
`investigate` · `brain-audit` · `deep-research` · `github` · `repo-review` (read-only review of a foreign repo) ·
`repo-fix` · `skill-scan` · `find` · `office-*` · `ui-build` · `draft-reply` · `linux-service-triage` ·
`ctx-agent-history-search` (what earlier sessions decided) · `/workbench-kb:save` · `humanizer` (prose a person will
read) · `grilling` (stress-test a plan) · `playwright-cli` · `kit-update` ("check the new stuff and go"). Not installed? Say so and do the task without it.
- User-invoked only (the model cannot start them: suggest, never start): `setup`, `vdi-drive`, `pc-checkup`, `cleanup`,
  `onboard` (suggest it while USER.md holds placeholders), `/workbench-capture:capture`, `/workbench-capture:ingest`, and
  the authoring and admin skills `batch-review`, `mcp-heal`, `plugin-factory`, `plugin-review`, `web-packager`,
  `mcp-builder`, `api-bridge` (REST to MCP), `app-navigator` and `brand-spec`.
- **Before installing any plugin or skill:** check your organisation allows it, and run
  `skill-scan` on its source first.

## MCP servers
- **No personal MCP servers** on the work machine, and nothing that sends work data to a
  service your organisation hasn't approved.
- If your organisation manages MCP servers, theirs is the only list: don't add servers around it.
- Otherwise keep one golden config as the single source of truth
  (`{{WORKBENCH_HOME}}/kit/mcp/README.md`) and change it rather than hand-editing `~/.claude.json`.

## What a subagent inherits
Custom and built-in subagents load your CLAUDE.md, its imports and the project CLAUDE.md, **except
the built-in `Explore` and `Plan` agents, which load none of it**: no Red Lines, no tenant rules.
Paste the constraints a task needs into their prompt, and prefer `general-purpose` for anything
touching infrastructure, credentials, another tenant's data or money.
