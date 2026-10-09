# {{name}}

An MCP server on the Python SDK (`mcp==2.3.0`). Wiring is in `server.py`, logic in `engine.py`, schema hygiene in
`schemas.py`. Replace the in-memory records in `engine.py` with the real system; keep the tool surface small.

## Surface matrix

| Tool | Kind | Annotations | Notes |
|---|---|---|---|
| `records_list` | read | `readOnlyHint` | stable order, cursor paging, limit 50 |
| `records_get` | read | `readOnlyHint` | body capped, free text labelled as untrusted data |
| `records_add` | write | `readOnlyHint=false`, `destructiveHint=false`, `idempotentHint` | needs an `idempotency_key` |

| Where it runs | How | Who can reach it |
|---|---|---|
# @@ if auth=none
| Local, one machine | `python server.py` (stdio) | the user who started it |
# @@ end
# @@ if http
| HTTP | `python server.py --http` | {{auth_note}} |
# @@ end

## Environment contract

| Variable | Needed | Meaning |
|---|---|---|
| `LOG_LEVEL` | no | root log level, default `INFO`; logs go to stderr only |
# @@ if http
| `MCP_HOST`, `MCP_PORT` | no | bind address (default `localhost`) and port (default 8000) |
| `MCP_MAX_BODY` | no | request-body cap in bytes, default 65536 |
| `MCP_ALLOWED_HOSTS` | for a public or tunnel host name | comma-separated Host names the DNS-rebinding check accepts |
# @@ end
# @@ if auth=header
| `MCP_STATIC_TOKEN` | yes | the shared secret, sent as `Authorization: Bearer <token>` or `X-Api-Key`; it identifies the deployment, not a person |
# @@ end
# @@ if auth=oauth
| `OAUTH_ISSUER` | yes | issuer URL of the authorization server |
| `PUBLIC_URL` | yes | the MCP URL exactly as users type it; it is the token audience and the protected-resource identifier |
| `OAUTH_JWKS_URL` | yes | the authorization server's key-set URL |
# @@ end

## Run and test

```bash
pip install .
# @@ if auth=none
python server.py                      # stdio
# @@ end
python -m unittest discover -s tests  # unit + contract + injection
```
# @@ if http
Serve over HTTP with `python server.py --http`, then check the protocol layer with the Inspector CLI (the CI file runs the
same commands):
`npx @modelcontextprotocol/inspector@2.10.1 --cli --transport http --server-url http://localhost:8000/mcp --method tools/list --strict`.
Exit codes: 0 ok, 1 usage, 2 no App, 3 auth required, 4 unreachable, 5 tool error, 6 strict schema error.
# @@ end
# @@ if auth=oauth

The tests sign tokens with a generated key and swap `server._signing_key` for it; in production the key comes from
`OAUTH_JWKS_URL`. Claude's connector needs a `401` with `resource_metadata` (the SDK serves the metadata document), the
first `authorization_servers` entry only, and an authorization server that supports PKCE with S256.
# @@ end

## Rules this server keeps
- Identity comes from the credential, never from a tool argument; no tool takes `user_id`, `email` or `as_user`.
- The caller's token is never passed to another service; use a service credential of your own.
- Unknown arguments are refused by name; failures return `isError` with a next step.
- Free text from the system is wrapped as `<untrusted-data>`, with markup escaped and hidden characters removed.
- Published schemas are flat: no `$ref`, `anyOf`, `oneOf`, `allOf` or `const` (`schemas.py` lowers them).
- Logs go to stderr; stdout is the protocol on stdio.

`evals/questions.xml` holds the question set for checking that a model picks the right tools.
