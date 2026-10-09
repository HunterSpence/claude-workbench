# Build an MCP server

Automates it: /workbench-core:mcp-builder

## When to use
You want Claude to reach one system (an internal tool, a data source, a service) through a connector of your own, and no
existing server fits. If the system already has a REST or OpenAPI description, use guide 23 instead. If a vendor already
ships a server, enabling theirs (guide 26) beats building one. `<KIT>` is the kit folder (guide 01).

## Steps
1. Answer six questions: which system, who uses it (web users, Claude Code, both), how many actions, how the system
   authenticates, whether calls run as each user or as one service identity, and how sensitive the data is. Then pick one:
   no server (a skill covers it), a vendor server, a remote HTTP server (anything web users touch) or a local stdio
   server (developer tools on one machine only).
2. Plan the tools in a table before any code: name, read or write, a title and hints, input fields, size limit. Aim for 5 to 15
   tools shaped like tasks, none that mixes reads and writes, none that takes the caller's identity as an argument. If you
   have a JSON dump of a server's tool list, lint it (exit 1 on any finding):
   ```
   py -3 <KIT>/plugins/workbench-core/skills/mcp-builder/scripts/lint_tools.py tools.json
   ```
3. Scaffold a project (`--lang py` or `ts`; `--auth header` or `oauth` protect the HTTP channel and need `--http`):
   ```
   py -3 <KIT>/plugins/workbench-core/skills/mcp-builder/scripts/scaffold_server.py --lang py --name my-server --auth none --out ./my-server
   ```
   You get the server, its logic, schema helpers, unit, contract and injection tests, an eval question file, a README and
   a CI workflow. Replace the example records with the real system, then rename the tools to match your plan.
4. Test cheapest first: the generated unit, contract and injection tests (`py -3 -m unittest discover -s ./my-server/tests`
   for Python; `npm install --ignore-scripts && npm run build && npm test` for TypeScript), then the protocol layer with the
   pinned Inspector, then a real client. Assert on `isError`, not on the HTTP status.
5. Write ten read-only questions in `evals/questions.xml` and run them headless (guide 12), reading which tools the model chose.
6. Before any web connector goes live read `<KIT>/plugins/workbench-core/skills/mcp-builder/references/deploy.md` and
   `hosts.md` next to it.

## Verify
- The lint and the generated tests pass, and they fail when you break one tool registration (test the test).
- The server never writes to standard output in stdio mode and never holds a credential value in a file, log or test.

## Common failures
- **A catch-all request tool or a `method` argument:** split it into task-shaped tools; the lint flags it.
- **A credential in a file:** it comes from the environment; rotate it if it was committed (guide 40).
- **Adding the connector to a shared organisation:** ask the owner first; a managed MCP policy may refuse it (guides 26 and 39).
- **Unpinned SDK:** the scaffold pins exact versions. Keep them and re-pin on purpose.
