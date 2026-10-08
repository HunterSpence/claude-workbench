# Tool routing (use these without being asked)

MCP tool schemas are deferred at startup: search with ToolSearch before you **ever claim a
configured tool is unavailable**. A server that "failed to connect" is a connection failure, not a
missing capability: say so and let the user fix it; never silently route around it.

## By task
- **Web research:** native WebSearch and WebFetch; long-form or comparison research goes to the
  `researcher` agent or `/workbench-core:deep-research`. A 403 is not "unreadable": say which fetcher
  failed. A bot wall or captcha is a stop: hand it to the user. WebSearch is one per-session
  budget shared with every subagent: plan research fan-outs around it.
- **Work documents:** let OneDrive sync the library, then search a scoped, locally kept folder with
  the `doc-index` skill and cite the originals.
- **Office output:** `office-pptx` and `office-xlsx` build files; `office-render` renders them so
  you check the result first. For editing inside Excel, PowerPoint, Word or Outlook: the official
  Claude for Microsoft 365 add-ins, if your tenant's admin allows them.
- **GitHub:** the `gh` CLI against your enterprise host (`--hostname`, or `GH_HOST`; see
  `rules/corporate-environment.md`). The `github` skill covers the details.
- **Docs for a framework or SDK:** the vendor's site through WebFetch, or a docs MCP only if your
  organisation approved it. Claude and Anthropic models, pricing and limits: the bundled
  `claude-api` skill, never memory.
- **Code graph:** `rules/code-graph.md`.
- **Databases:** read-only queries unless the user asks otherwise; production writes are a Red Line.
- **Servers:** ssh as the least-privileged user that can do the job; an admin or root login is
  break-glass, so say why first. Never ask the user to ssh for you.
- **Reports** (deep research, comparisons, analyses meant for someone else): an Artifact link when
  your organisation's Claude offers Artifacts, for your own organisation's data only, never another
  tenant's; the user decides who sees it. Otherwise a Markdown file in the workspace, with its path.
- **Browser:** `rules/browser.md`.
- **Review:** the bundled `/code-review` for correctness, `/security-review` for the branch's
  security diff, `/simplify` for cleanup.

## Skills (use them when the task fits, unasked; invoke as `/workbench-core:<name>`, the KB's as `/workbench-kb:save`)
`cascade` (fix, build, refactor, migrate) · `ratchet` (fix and re-audit until clean) · `handoff` ·
`onboard` (fill in USER.md; suggest it when USER.md still holds placeholders) · `spawn` (write a
delegation prompt) · `investigate` · `cleanup` · `brain-audit` (setup and KB
health) · `deep-research` · `github` · `skill-scan` · `doc-index` · `office-pptx` · `office-xlsx` ·
`office-docx` · `office-render` · `ui-build` · `draft-reply` · `batch-review` ·
`repo-fix` (review and fix a repository) · `linux-service-triage` · `ctx-agent-history-search` (what
earlier sessions decided) · `mcp-heal` ·
`save` (KB). If one isn't installed, say so and do the task without it.
- `vdi-drive`, `pc-checkup` and `cleanup` are user-invoked only: suggest
  `/workbench-core:<name>`, never start them.
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
the built-in `Explore` and `Plan` agents, which load none of it**: no Red Lines, no tenant rules, no rules.
Paste the constraints a task needs into their prompt, and prefer `general-purpose` for anything
touching infrastructure, credentials, another tenant's data or money.
