# claude-workbench

An opinionated, portable setup for Claude Code: how to work, the rules that keep the work honest,
agent personas for build/attack/verify passes, workflow skills, safety hooks, a statusline, a
plain-text knowledge base, local document search, Office output, and token-saving practice.

It runs on Windows (including managed corporate laptops), Linux and WSL, installs without admin
rights, and never edits or works around an organisation's managed settings.

## What's inside
| Part | What it gives you |
|---|---|
| `instructions/` | A core `CLAUDE.md`, rules (verification, memory, model routing, tool routing, code graph, shell, git, browser, corporate environment) and a working-style guide |
| `plugins/workbench-core/agents/` | Personas: flagship (build), blue-verify (final gate), red-team (attack), green-team (independent alternative), researcher, implementer, ops-runner, security-auditor |
| `plugins/workbench-core/skills/` | cascade, ratchet, handoff, spawn, investigate, cleanup, brain-audit, deep-research, github (incl. Enterprise hosts), skill-scan, linux-service-triage, agent-history search, mcp-heal, batch-review, pc-checkup, doc-index, Office (pptx, xlsx, render), ponytail |
| `plugins/workbench-core/scripts/` | Hooks: a shell-aware guard engine with generic and corporate rule packs, session start, statusline, read-flood guard, checkpoints, credential scan |
| `plugins/workbench-kb/` | A Markdown knowledge base with full-text search, a journal, and a `save` skill that never pushes anywhere by default |
| `settings/` | Two profiles: `corporate` (the default) and `permissive` (no prompts, broad allow rules), plus optional upstream plugin sets. Every key is explained in `SETTINGS.md` |
| `bootstrap/` | Install and uninstall (Python, no admin). Dry-run by default |
| `tools/` | Transcript error mining, MCP health checks, a pinned fetcher for recommended upstream skills, and a scanner for personal identifiers before you publish a repo |
| `mcp/` | A template of useful MCP servers, each with where its data goes |
| `docs/token-diet.md` | Where Claude Code tokens actually go, and what reduces them |

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
