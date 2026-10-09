# Auth (working checklist)

Patterns and server-side rules in full: `docs/engineering/mcp-servers.md` section 3.

## Pick a pattern
1. Public data only: **none**.
2. Some tools work without an account: **lazy auth** (anonymous until a protected tool is called).
3. Internal tool with one service credential: **static header**. It identifies the deployment, not a person, and availability
   depends on the organization's plan.
4. Per-user access: **OAuth**. Ship a client ID metadata document **and** keep dynamic client registration; prefer the
   metadata document (or a vendor-held client) for high-traffic servers.
5. Never `client_credentials` for a connector a person should authorize: Claude does not support the grant.

## What the scaffold generates
| `--auth` | Python | TypeScript | Environment |
|---|---|---|---|
| `none` | no gate; stdio, or HTTP on `localhost` | same | none |
| `header` | ASGI gate: constant-time compare of `Authorization: Bearer` or `X-Api-Key` before the SDK parses anything | node gate with the same compare | `MCP_STATIC_TOKEN` |
| `oauth` | SDK resource-server auth with a JWT verifier (signature, issuer, audience, expiry) and protected-resource metadata | bearer gate with the same checks and a metadata route | `OAUTH_ISSUER`, `PUBLIC_URL`, `OAUTH_JWKS_URL` |

`header` and `oauth` need `--http`: a stdio server's principal is the user who started it. The generated tests show a `401`
without a credential and with a wrong one; the OAuth tests sign tokens with a generated key.

## Claude's OAuth client (what your authorization server must do)
- Return an HTTP `401` (not a header on a `200`) with `WWW-Authenticate: Bearer resource_metadata="..."`.
- Put your authorization server **first** in `authorization_servers`: only the first entry is used.
- Advertise `client_id_metadata_document_supported: true` and the `none` token-endpoint auth method to be offered the metadata
  document flow; otherwise Claude registers dynamically.
- Accept loopback redirects on any port for `localhost` and the numeric loopback address, plus the hosted callback
  `https://claude.ai/api/mcp/auth_callback`.
- Answer discovery, registration and token calls within 10 seconds (refresh within 30); use `invalid_grant` for refresh errors;
  accept form-encoded token requests; require S256 PKCE.
- The protected-resource `resource` value equals the MCP URL exactly as the user types it; the token audience is the same value.

## Rules that hold for every pattern
- Validate issuer and audience; never pass the caller's token to another service (use a service credential of the server's own).
- Take privilege from which credential authenticated, not from an identity header a gateway forwards unsigned.
- `401` = re-authorize will fix it; `403` = entitlement, re-authorizing will not.
- Never read a token from the query string. Never log a token.
- In-band confirmation ("call confirm with this nonce") is satisfied by injected text: confirm out of band or remove the capability.
- If a firewall sits in front, allow the vendor's published egress ranges; read them from the vendor's page when you configure
  it (https://claude.com/docs/connectors/building/authentication) and do not copy them into documents.
