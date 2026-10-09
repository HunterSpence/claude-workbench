# Wrap an API as an MCP server

Automates it: /workbench-core:api-bridge

## When to use
A system already has a REST or OpenAPI interface (an internal API, for example) and you want Claude to use it without hand-writing a server. The product
is a short list of task-shaped tools, not a mirror of every endpoint. For a server from scratch use guide 22. `<KIT>` is
the kit folder (guide 01).

## Steps
1. List the operations (a spec file gives a table; with no spec, write one row per operation you might need):
   ```
   py -3 <KIT>/plugins/workbench-core/skills/api-bridge/scripts/openapi_inventory.py openapi.json
   ```
2. Curate. Copy `<KIT>/plugins/workbench-core/skills/api-bridge/templates/worksheet.md` and decide for each operation: keep,
   merge into a workflow tool, or drop. Drop by default. Mark read or write, give a name and a reason a model needs it,
   and a size limit. `openapi_draft.py` in the same folder writes a draft marked `_draft`; the bridge refuses it until you curate it.
3. Copy `<KIT>/plugins/workbench-core/skills/api-bridge/templates/bridge-python/` into your project, put the curated
   `worksheet.json` beside it and check it against the spec:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/api-bridge/templates/bridge-python/worksheet.py worksheet.json --spec openapi.json
   ```
4. Set the environment contract: `UPSTREAM_BASE_URL` (https), `UPSTREAM_TOKEN` (the bridge's own service credential, from
   your environment, never a file), `UPSTREAM_TIMEOUT`, `UPSTREAM_RETRIES` and `BRIDGE_WORKSHEET`.
5. Run the generated contract test (`py -3 -m unittest discover -s tests` in the project), then run the bridge against the
   real API with a read-only credential and confirm a write you did not curate in is unreachable.
6. Serve it: a private host over ssh for developer clients (`bridge-stdio-ssh.json` in the templates), or scaffold an HTTP
   server with guide 22 for web users. GraphQL and proxying another MCP server: `docs/engineering/api-bridges.md`.

## Verify
- `worksheet.py` prints "worksheet ok" and exits 0 (1 lists the reasons).
- The contract test passes: the tool set equals the worksheet, annotations match the modes, unknown arguments are refused.

## Common failures
- **Refused for a catch-all `api_request(method, path)`:** curate named tools instead.
- **Refused for forwarding the caller's token or taking identity from a header:** use the bridge's own credential.
- **"Draft" refusal:** you left the `_draft` marker in. Curate, then delete it.
- **Oversized response error:** ask for a narrower request or add a size limit to the worksheet.
