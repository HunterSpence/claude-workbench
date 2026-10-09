# {{name}}

An MCP server on the TypeScript SDK v2 (`@modelcontextprotocol/server` 2.3.1). Wiring is in `src/server.ts`, logic in
`src/engine.ts`, schema hygiene in `src/schemas.ts`. Replace the in-memory records in `src/engine.ts` with the real
system; keep the tool surface small. It answers both the 2025-era `initialize` handshake and the 2026 stateless path.

## Surface matrix

| Tool | Kind | Annotations | Notes |
|---|---|---|---|
| `records_list` | read | `readOnlyHint` | stable order, cursor paging, limit 50 |
| `records_get` | read | `readOnlyHint` | body capped, free text labelled as untrusted data |
| `records_add` | write | `readOnlyHint=false`, `destructiveHint=false`, `idempotentHint` | needs an `idempotency_key` |

| Where it runs | How | Who can reach it |
|---|---|---|
// @@ if auth=none
| Local, one machine | `node dist/src/server.js` (stdio) | the user who started it |
// @@ end
// @@ if http
| HTTP | `node dist/src/server.js --http` | {{auth_note}} |
// @@ end

## Environment contract

| Variable | Needed | Meaning |
|---|---|---|
// @@ if http
| `MCP_HOST`, `MCP_PORT` | no | bind address (default `localhost`) and port (default 8000) |
| `MCP_MAX_BODY` | no | request-body cap in bytes, default 65536 |
| `MCP_ALLOWED_HOSTS` | for a public or tunnel host name | comma-separated Host names the DNS-rebinding check accepts |
// @@ end
// @@ if auth=header
| `MCP_STATIC_TOKEN` | yes | the shared secret, sent as `Authorization: Bearer <token>` or `X-Api-Key`; it identifies the deployment, not a person |
// @@ end
// @@ if auth=oauth
| `OAUTH_ISSUER` | yes | issuer URL of the authorization server |
| `PUBLIC_URL` | yes | the MCP URL exactly as users type it; it is the token audience and the protected-resource identifier |
| `OAUTH_JWKS_URL` | yes | the authorization server's key-set URL |
// @@ end
// @@ if auth=none
| (none) | | stdio needs no configuration; logs go to stderr |
// @@ end

## Build and test

```bash
npm install --ignore-scripts   # commit package-lock.json, then use `npm ci --ignore-scripts` in CI
npm run build                  # tsc
npm test                       # unit + contract + injection (node:test)
```
// @@ if http
Serve over HTTP with `node dist/src/server.js --http`, then check the protocol layer with the Inspector CLI (the CI file
runs the same command):
`npx @modelcontextprotocol/inspector@2.10.1 --cli --transport http --server-url http://localhost:8000/mcp --method tools/list --strict`.
Exit codes: 0 ok, 1 usage, 2 no App, 3 auth required, 4 unreachable, 5 tool error, 6 strict schema error.
// @@ end

## Rules this server keeps
- Identity comes from the credential, never from a tool argument; no tool takes `user_id`, `email` or `as_user`.
- The caller's token is never passed to another service; use a service credential of your own.
- Schemas are strict: an unknown argument is refused by name. Failures return `isError` with a next step.
- Free text from the system is wrapped as `<untrusted-data>`, with markup escaped and hidden characters removed.
- Published schemas stay flat: no `$ref`, `anyOf`, `oneOf`, `allOf` or `const`. Plain zod objects are flat; when you
  register a schema made by another library, pass it through `lower()` in `src/schemas.ts` first.
- Never `console.log`: stdout is the protocol on stdio.

`evals/questions.xml` holds the question set for checking that a model picks the right tools.
