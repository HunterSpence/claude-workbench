# claude-workbench

An opinionated, portable setup for Claude Code: how to work, the rules that keep the work honest,
agent personas for build/attack/verify passes, workflow skills, safety hooks, a statusline, a
plain-text knowledge base, local document search, Office output, business skills, opt-in capture,
a machine capability report with background setup, and token-saving practice.

It runs on Windows (including managed corporate laptops), Linux and WSL, installs without admin
rights, and never edits or works around an organisation's managed settings.

## What's inside
| Part | What it gives you |
|---|---|
| `instructions/` | A core `CLAUDE.md`, rules (verification, memory, model routing, tool routing, code graph, shell, git, browser, corporate environment) and a working-style guide, all loaded every session and kept under a tested size budget; plus files read on demand: work workflows, judgment procedures, model profiles, a test-validity checklist and corporate setup steps |
| `plugins/workbench-core/` | Personas (flagship, blue-verify, red-team, green-team, researcher, implementer, ops-runner, security-auditor, scout, sonnet-max), the workflow skills and the hooks; see its `README.md`. Invoke a skill as `/workbench-core:<skill>` |
| `find` skill | One local index over your work libraries, captured pages and the how-to library: file catalog, keyword and meaning-based search, related files and the newest version, with a coverage report of what was not searched |
| Engineering skills | `repo-fix`, `repo-review` (read-only review of a foreign repository or folder in an isolated session), `plugin-factory`, `plugin-review` (68 rules, batch scorecards), `web-packager`, `mcp-builder` (Python and TypeScript scaffolds with lint and tests), `api-bridge` (a curated REST or OpenAPI surface as an MCP server), `app-navigator` (an in-app assistant that answers from the app's own help pages and links the right page), `diagram` (offline diagrams), `brand-spec` (lock a brand spec, then build and review a UI against it). Guides: `docs/plugins-playbook.md`, `docs/engineering/` |
| `plugins/workbench-kb/` | A Markdown knowledge base with full-text search, a journal, and a save skill (`/workbench-kb:save`) that never pushes anywhere by default. Seeded from `kb-template/` (a start-here index, topic digests and 97 bug cards, with detectors for the recognisable errors). Search returns one hit per note and tags superseded text; `kb_health` checks links, orphans, a known-answer set with fixed floors (`docs/engineering/retrieval-eval.md`) and a fact registry that flags a pinned fact gone stale |
| `plugins/workbench-biz/` | Eight portable business skills (requirements to stories, meeting to actions, status report, test cases, spreadsheet analysis, RFP and SOW drafts, branded decks, policy Q&A) for Claude web, desktop and CLI; instructions only; installed by default. Catalog: `docs/business-catalog.md` |
| `plugins/workbench-capture/` | Opt-in (`--with capture`): read-only capture of intranet pages through a dedicated signed-in Edge profile and of listed OneDrive files, paced (10 a minute, 200 an hour), scoped, and stopped by any sign-in, consent or policy page; experimental mail and meeting-transcript ingest. Its own plugin so IT can allow or deny it |
| `settings/` | Two profiles: `corporate` (the default) and `permissive` (no prompts, broad allow rules), upstream plugin sets, and the model routing table. Every key is explained in `SETTINGS.md` |
| `bootstrap/` | Install and uninstall (Python, no admin, dry run by default); the read-only capability report (`bootstrap/report.py`); setup, which provisions the machine in the background (`bootstrap/setup.py`); per-client profiles (`bootstrap/profile.py`) |
| `mcp/` | A catalog of MCP servers, every one off by default, each with where its data goes, plus a rejected list |
| `templates/github-actions/` | Workflow templates for Claude in CI (documentation only) |
| `tools/` | A one-command regression runner (`run_suites.py`) and the honest skip list (`skips.allow`), a cost and configuration bench for skills (`skill-bench`, it never ranks quality), transcript error mining, MCP health checks, a pinned fetcher for upstream skills, a pre-commit credential check, a memory-capped job runner, a settings redactor, a scanner for personal identifiers before you publish, `model-sweep` (gate a retiring model id), `token-split` (spend by token class), `mcp-nowin` (windowless MCP servers on Windows), and offline checks that rules hold and skills fire (`skill-probe`, `rules-quiz`). Every new tool answers `--self-test` |
| `docs/` | 54 task guides (`docs/howto/README.md`), the setup runbook a Claude session follows on Day 1 (`docs/SETUP-RUNBOOK.md`), how the kit works (`docs/HOW-WE-WORK.md`), models at a glance (`docs/models.md`), model routing, token use, and the coworker bundle: `known-limits.md`, `troubleshooting.md`, `rules-card.md`, `runbooks.md` |

## Permission rules
Permission rules only; the kit ships no guard hook. Both settings profiles ask before a force push, a repository delete
and a release delete. The installer adds one deny rule so only the save driver writes `active-context.md` (Edit/Write
tools; a shell write is not stopped) (`settings/SETTINGS.md`). Rules match command text, not intent: the limits are in
`docs/known-limits.md`.

## After install
Run `/workbench-core:onboard` to fill in your work profile (`USER.md`), then try the "first 10 minutes" in
[IMPORT.md](IMPORT.md). Something broken: `docs/troubleshooting.md`.

## Principles
- **Evidence over claims.** A green check is not evidence; verify the artifact. No tool calls means no research.
- **Build, attack, verify.** Big work gets a builder, an attacker on a different model, and a final verifier.
- **Opt-in and reversible.** Dry-run first, backups always, uninstall included.
- **Managed settings win.** The installer never writes a key a managed source sets.

## Install
See [IMPORT.md](IMPORT.md): one paste prompt does the whole chain. Short version: download a tagged release,
verify the hash, run `py -3 bootstrap/install.py` (dry run), read the plan, then run it again with
`--apply --setup auto`.

## Requirements
Claude Code and Python 3.10+. Setup installs the rest it can without admin rights (Git, GitHub CLI, Node.js,
WSL2 and others) and drafts an ask-IT text for anything it cannot.

## Licence
MIT; see [LICENSE](LICENSE). Third-party tools referenced here keep their own licences; see
[THIRD-PARTY.md](THIRD-PARTY.md). Nothing third-party with a restrictive licence is included.
