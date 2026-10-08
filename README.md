# claude-workbench

An opinionated, portable setup for Claude Code: how to work, the rules that keep the work honest,
agent personas for build/attack/verify passes, workflow skills, safety hooks, a statusline, a
plain-text knowledge base, local document search, Office output, and token-saving practice.

It runs on Windows (including managed corporate laptops), Linux and WSL, installs without admin
rights, and never edits or works around an organisation's managed settings.

## What's inside
| Part | What it gives you |
|---|---|
| `instructions/` | A core `CLAUDE.md`, rules (verification, memory, model routing, tool routing, code graph, shell, git, browser, corporate environment) and a working-style guide, all loaded every session; plus files read on demand: work workflows (repos, new code, UIs, Office files, replies), judgment procedures, model profiles, a test-validity checklist and corporate setup steps |
| `plugins/workbench-core/agents/` | Personas: flagship (build), blue-verify (final gate), red-team (attack), green-team (independent alternative), researcher, implementer, ops-runner, security-auditor |
| `plugins/workbench-core/skills/` | cascade, ratchet, handoff, spawn, investigate, cleanup, brain-audit, deep-research, github (incl. Enterprise hosts), skill-scan, linux-service-triage, agent-history search, mcp-heal, batch-review, pc-checkup, doc-index, Office (pptx, xlsx, docx, render), ui-build, draft-reply, repo-fix, vdi-drive (opt-in, runs only when asked), onboard, ponytail. Invoke as `/workbench-core:<skill>` |
| `plugins/workbench-core/scripts/` | Hooks: a shell-aware guard engine with generic and corporate rule packs, session start, statusline, read-flood guard, checkpoints, credential scan |
| `plugins/workbench-kb/` | A Markdown knowledge base with full-text search, a journal, and a save skill (`/workbench-kb:save`) that never pushes anywhere by default |
| `settings/` | Two profiles: `corporate` (the default) and `permissive` (no prompts, broad allow rules), plus upstream plugin sets (security guidance, PR review and frontend design on). Every key is explained in `SETTINGS.md` |
| `bootstrap/` | Install and uninstall (Python, no admin). Dry-run by default |
| `tools/` | Transcript error mining, MCP health checks, a pinned fetcher for recommended upstream skills (`fetch-upstream --optional` adds the design set), a pre-commit credential check (git-credscan), a memory-capped job runner (memcap), a settings redactor (redact-settings), and a scanner for personal identifiers before you publish a repo |
| `mcp/` | A template of useful MCP servers, each with where its data goes |
| `docs/token-diet.md` | Where Claude Code tokens actually go, and what reduces them |

## Guards
The guard hooks deny or ask before risky calls. The rules live in the two rule packs,
`plugins/workbench-core/scripts/guards/rulepacks/generic.py` and `corporate.py`. Among them:
`push-default-branch` denies a push straight to main, master or the remote's default branch;
`msys-path` denies Windows file writes given as `/c/...` or `/mnt/c/...`; `publish-confirm` asks before
gists, releases, package publishes, uploads, PR comments, approvals and admin merges; and installing a
plugin or skill asks first, after a `skill-scan` when the scanner is installed. In bypass mode only permission ask
rules are sure to prompt, so both settings profiles also carry `permissions.ask` rules for the publishing
verbs (`settings/SETTINGS.md`).

## After install
Run `/workbench-core:onboard` to fill in your work profile (`USER.md`). Details in [IMPORT.md](IMPORT.md).

## Principles
- **Evidence over claims.** A green check is not evidence; verify the artifact. No tool calls means no research.
- **Build, attack, verify.** Big work gets a builder, an attacker on a different model, and a final verifier.
- **Opt-in and reversible.** Dry-run first, backups always, uninstall included.
- **Respect the organisation.** Managed settings win. Nothing edits them, phones home, or works around a control.

## Install
See [IMPORT.md](IMPORT.md). Short version: download a tagged release, verify the hash, run
`py -3 bootstrap/install.py` (dry-run), read the plan, then run it again with `--apply`.

## Requirements
Claude Code and Python 3.10+. Optional: Git, Node.js, WSL2.

## Licence
MIT; see [LICENSE](LICENSE). Third-party tools referenced here keep their own licences; see
[THIRD-PARTY.md](THIRD-PARTY.md). Nothing third-party with a restrictive licence is included.
