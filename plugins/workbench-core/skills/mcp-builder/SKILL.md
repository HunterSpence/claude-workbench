---
name: mcp-builder
description: "Build and test an MCP server from scratch. To wrap an existing REST API use api-bridge."
disable-model-invocation: true
---

# mcp-builder

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it appears unreplaced (the
> skill was copied in without the plugin), use `py -3` on Windows and `python3` on Linux, macOS and WSL, never the Microsoft
> Store `python` stub.

Take the user from "I want Claude to reach system X" to a tested server. The scripts here are stdlib only; the generated
project needs the SDK. Reasoning and the failure catalog: `docs/engineering/mcp-servers.md`.

**Never:** put a credential value in a file, a log or a test; build one tool that mixes reads and writes or takes a `method`
argument; accept caller identity as a tool argument; pass the caller's token to another service; write to stdout from a stdio
server; use an unpinned SDK. Ask before you add a connector to a shared organization.

## 1. Interrogate, then recommend
Ask: which system, who uses it (web users, Claude Code, both), how many actions, how upstream authenticates, whether calls are
per user or one service identity, how sensitive the data is. Then pick one:
- **No server:** a skill covers procedure and formatting.
- **Vendor server:** an existing first-party remote server beats building one.
- **Remote HTTP server:** anything web users touch.
- **Local stdio server:** developer tools on one machine only.
Existing REST or OpenAPI API to wrap: stop and use the `api-bridge` skill.

## 2. Plan the tools before any code
Write a table: tool name, read or write, annotations, input schema, page budget. Check it against `references/tool-design.md`
(5 to 15 tools, workflow-shaped, no identity argument). If you already have a tools/list dump, lint it:
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/lint_tools.py" tools.json
```
It flags long names, catch-all request tools, read and write mixing, missing `title` or hints, `$ref`/`anyOf`/`oneOf`/`allOf`/`const`,
identity-like arguments and instructing descriptions. Exit 1 on any finding.

## 3. Scaffold
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/scaffold_server.py" --lang py --name my-server --auth none --out ./my-server
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/scaffold_server.py" --lang ts --name my-server --auth header --http --out ./my-server
```
`--auth none|header|oauth`; `header` and `oauth` protect the HTTP channel, so they need `--http`. Python pins `mcp==2.3.0`;
TypeScript pins `@modelcontextprotocol/server@2.3.1` and `typescript` exactly. Output: the server (wiring), `engine` (plain
functions), `schemas` (flat-schema helpers), unit, contract and injection tests, an eval question file, a README with the
surface matrix and environment contract, and `.github/workflows/ci.yml` (tests plus the Inspector for `--http`).
Replace the in-memory example records with the real system, then rename the tools to match the plan.

## 4. Test, cheapest first
Unit, then in-memory contract and injection tests (generated), then the protocol layer with the pinned Inspector CLI, then the
real client. Details and exit codes: `references/testing.md`. Python: `python -m unittest discover -s tests`.
TypeScript: `npm install --ignore-scripts && npm run build && npm test`. Assert on `isError`, never on the HTTP status.
Test the test: break one registration and confirm the suite goes red.

## 5. Auth, deploy, hosts
- Auth pattern and Claude's OAuth client rules: `references/auth.md`.
- Deploy checklist for web connectors: `references/deploy.md`.
- What each host supports and its limits: `references/hosts.md`.

## 6. Eval set
Write ten independent, read-only, multi-call questions with stable, verifiable answers in `evals/questions.xml`. Run them
headless (`claude -p` with the server configured) and read which tools the model chose.

## Portability
The guidance and the lint work in a chat that only has a pasted tools/list. Scaffolding needs code execution or Claude Code.
