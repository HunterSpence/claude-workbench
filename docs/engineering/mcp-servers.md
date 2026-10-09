# Building MCP servers that work with Claude

How to go from "Claude should reach system X" to a server that is tested, safe by default and usable from Claude Code,
Desktop and the web apps. Read it on demand; the `mcp-builder` skill (`plugins/workbench-core/skills/mcp-builder/SKILL.md`)
does the scaffolding and the lint, this guide holds the reasoning and the failure catalog.

Facts here come from the protocol specification and the vendors' public pages as read in the last research pass. Version
numbers and limits move: re-check the SDK pins (section 1, step 4) and the host limits (section 4) before you rely on them.

## 1. Build steps

1. **Decide whether you need a server at all.** A skill alone covers procedure and formatting. A server is needed to read
   live data or act in a system. An existing first-party remote server beats building one; a community server that holds a
   raw key is not first-party.
2. **Pick where it runs.** Remote streamable HTTP for anything web users touch: it is the only kind a web connector can
   reach. Local stdio only for developer tools on one machine (package it for Desktop as an extension bundle). The older
   HTTP-plus-SSE transport is deprecated.
3. **Pick the protocol target.** Hosted Claude still opens with the 2025-era `initialize` handshake, while the current
   specification revision is stateless (no `initialize`, no session id, a mandatory discovery call). Serve the old handshake
   and, when the SDK does it for you, the stateless path. Keep handlers stateless so any replica answers, and pass
   cross-call state as explicit server-minted handles in tool arguments.
4. **Pick the SDK and pin it exactly.**

   | Stack | Pin | Use when |
   |---|---|---|
   | TypeScript `@modelcontextprotocol/server` (v2, the stable line) | 2.3.1 | a new TypeScript server; client in `@modelcontextprotocol/client` |
   | TypeScript `@modelcontextprotocol/sdk` (v1) | 1.32.1 | existing v1 code you are not migrating |
   | Python `mcp` (v2, class `MCPServer`, formerly `FastMCP`) | 2.3.0, MIT | a new Python server with full control |
   | Python `fastmcp` (built on SDK v2) | 4.0.11, Apache-2.0 | batteries: proxying, OpenAPI import, auth providers |

   Breaking changes from v1 to v2: the high-level class was renamed, wire types moved and became snake_case in Python,
   transport options (`host`, `port`, stateless and JSON-response switches, transport security) moved from the constructor
   to `run()` or the app builder, and server-initiated sampling and roots are gone. Pin the major, and pin `typescript`
   exactly too.
5. **Split wiring from logic.** `server` holds decorators, annotations, the auth gate and logging setup; `engine` holds
   plain functions you unit-test without MCP.
6. **Log to stderr.** On stdio a library that writes to stdout corrupts the JSON-RPC framing. Configure logging before
   importing application code. The specification now deprecates protocol-level logging: log to stderr or use OpenTelemetry.
7. **Enforce in the server, never in the client.** Read-only means a scoped credential and no write code path. Annotations
   are advice that clients must treat as untrusted. Strip dangerous environment variables at startup if a tool must never
   reach them.
8. **Budget responses.** Size pages to the host's cap (about 150,000 characters on the web apps, 25,000 tokens
   in Claude Code) and page rather than truncate silently.
9. **Protect the HTTP surface.** An explicit Host and Origin allowlist (add your public or tunnel host name or the SDK
   answers with a rejection), a request-body size cap, and authentication before the SDK parses anything. Bind to
   `localhost` unless you mean to expose the port.
10. **Test against the real client, then ship.** A custom connector runs on the same runtime as a directory listing; there
    is no staging environment. The ladder is section 5.

## 2. Tool design rules

| Rule | Why |
|---|---|
| Name at most 64 characters, `service_verb_noun`, one consistent prefix | review limit; discoverability |
| Separate read tools from write tools; split writes into create, update, delete | a catch-all tool with a `method` argument mixes safe and unsafe operations and is rejected in directory review |
| A freeform-query tool names or links the target API in its description | review rule |
| Every tool has a `title` and `readOnlyHint` (reads) or `destructiveHint` (writes); add `idempotentHint` and `openWorldHint` where true | Claude runs read-only tools without asking and always prompts for destructive ones |
| Annotations are UX, not security | clients treat them as untrusted |
| The description says what the tool does and when to call it; never instructions to Claude ("always call X first", "ignore other tools", fetch rules from a URL, hidden or encoded text) | rejection list; tool poisoning and shadowing |
| Flat, self-contained schemas: no `$ref`, `anyOf`, `oneOf`, `allOf`, `const`, no null unions; lower them at build time | the specification allows full JSON Schema, but some clients still reject these |
| Never accept caller identity as an argument (`user_id`, `email`, `as_user`); derive it from the authenticated credential | confused deputy |
| Refuse unknown arguments and say which | the SDK drops them silently otherwise |
| Return `structuredContent` and a text copy, declare an `outputSchema`, set `isError: true` with an actionable message on failure | the model can correct itself; generic errors fail review |
| Cursor pagination and an explicit byte budget; summary by default, detail on request | no full database dumps |
| An idempotency key on every non-idempotent write; validate inputs | retries are routine |
| Deterministic tools/list order; per-caller lists marked cache scope private | specification guidance and cache semantics |
| Permission-aware listing plus the same check at call time | listing is not the control |
| Treat every free-text field in results as untrusted: label it as data, say so in the server `instructions` | prompt injection through tool output |
| Prefer a few workflow-shaped tools over many endpoint mirrors; split a large surface into several connections by use case | picking the wrong tool among similar names is the dominant failure |
| No money movement and no generation of images, audio or video if you want a directory listing | unsupported use cases |

`plugins/workbench-core/skills/mcp-builder/scripts/lint_tools.py` checks most of these on a dumped tools/list.

## 3. Auth patterns

| Pattern | Who it identifies | Web support | Use when |
|---|---|---|---|
| None | nobody | default | public data only |
| Lazy auth | anonymous until a protected tool is called | default | some tools are useful without an account |
| Static header (`authorization`, `x-api-key`, `x-auth-token`) | the organization, not a person | beta for some organizations; an owner enters it once | an internal tool with one service credential |
| OAuth with dynamic client registration | each user | default | your authorization server has a `registration_endpoint` |
| OAuth with a client ID metadata document | each user | default when both flags below are advertised | per-customer URLs, high traffic |
| OAuth with a vendor-held client | each user | by request | a stable confidential client |
| Credentials entered at connection time | each user, through the customer's own OAuth client | by request | customers must own the client |
| Enterprise managed authorization | each user through an identity-provider assertion, no consent screen | per vendor page | single-sign-on-first enterprises |
| `client_credentials` (machine to machine) | a service | not supported for connectors | CI and daemons only, never where a person should authorize |

**What Claude's OAuth client requires (stricter than the specification in seven places):**
1. It needs an HTTP `401`; a `WWW-Authenticate` header on a `200` is ignored.
2. It uses only the first entry of `authorization_servers`.
3. It prefers a client ID metadata document only when the authorization server advertises
   `client_id_metadata_document_supported: true` and the `none` token-endpoint auth method; otherwise it falls back to
   dynamic client registration.
4. A loopback redirect must match `localhost` and the numeric loopback address, on any port.
5. Timeouts: 10 seconds for discovery, registration and token calls, 30 seconds for refresh.
6. The `client_credentials` grant is not supported.
7. PKCE with S256 is always used.

**CIMD and DCR.** Dynamic client registration is deprecated in the current specification revision, but Claude supports it
by default and falls back to it. Ship the client ID metadata document **and** keep a `registration_endpoint`. For
high-traffic servers prefer the metadata document or a vendor-held client, because registration creates a new client on
every fresh connection.

**Redirect URIs.** Hosted apps use one fixed callback, `https://claude.ai/api/mcp/auth_callback`. Claude Code uses a loopback
address on an ephemeral port (RFC 8252). Allow both.

**Egress addresses.** If a firewall or bot filter sits in front of the server, allow the vendor's published outbound ranges.
Do not copy the ranges into your configuration from a document like this one; read them from the vendor's page when you
configure the allowlist and re-read it on a schedule: https://claude.com/docs/connectors/building/authentication

Server-side rules that hold whichever pattern you pick:
- **Validate audience and issuer.** Never pass the client's token to another service (token passthrough is forbidden): a
  gateway holds its own upstream credential and is the enforcement boundary.
- **Never derive privilege from an identity header** that a platform forwards unsigned. Authenticate the channel (client
  credentials, mutual TLS or an HMAC), resolve the role from which credential authenticated, and use the header only to
  scope reads and to log.
- Discovery: `401` with `WWW-Authenticate: Bearer resource_metadata="..."`; the protected-resource `resource` value must equal
  the URL exactly as users type it; authorization-server metadata must be reachable from the vendor's egress; the token
  endpoint accepts `application/x-www-form-urlencoded`; refresh errors use `invalid_grant`; rotate refresh tokens for public
  clients.
- `401` means re-authorizing will fix it; `403` means an entitlement problem that re-authorizing will not fix.
- Some identity providers need the MCP URL registered as an application ID URI (with a verified domain) or token requests
  fail with a resource-identifier error.
- Never accept a token in the query string.
- **In-band confirmation is not consent.** A two-call nonce handshake is satisfied by injected text with no human involved.
  Remove the privileged capability or confirm out of band.

## 4. Host limits and compatibility

| Host | Tool result cap | Call time limit | Not supported |
|---|---|---|---|
| Web and Desktop apps | about 150,000 characters | about 240 seconds | resource subscriptions, sampling, draft capabilities |
| Claude Code | 25,000 tokens by default (`MAX_MCP_OUTPUT_TOKENS`) | `MCP_TOOL_TIMEOUT` | sampling and draft capabilities |

Web connectors reach only public HTTPS endpoints (or an MCP tunnel). Local stdio servers work in Claude Code and Desktop only.
`plugins/workbench-core/skills/mcp-builder/references/hosts.md` has the compatibility table to fill in per server.

## 5. Testing ladder (cheapest first)

| Layer | What | Tooling |
|---|---|---|
| Unit | engine functions, no MCP | the language's test runner |
| In-memory wiring | client and server in one process: tool list, one call, key gate, `isError` | the SDK's in-memory client |
| Contract | exact tool set; static annotated metadata; no identity argument; deterministic order; structured and text result; every output validates against its `outputSchema`; error results flagged; unknown tool is a protocol error; auth header forms; missing credential; oversized request and foreign Host rejected; no state between requests | the generated `test_contract` file |
| Injection | planted payloads in bodies, file names and identifiers, split across chunks, come out labelled and inert in every output channel | the generated `test_injection` file |
| Protocol | `npx @modelcontextprotocol/inspector@2.10.1 --cli --transport http --server-url <url> --method tools/list`; `--method tools/call --tool-name X --tool-arg k=v` (or `--tool-args-json` to avoid number coercion); `--strict` for schema portability | the Inspector CLI |
| Both eras | once as a 2025-era client (handshake) and once against the stateless path | an SDK client that probes and falls back |
| Real client | add it as a custom connector (tunnel a local server, keep auth on); check Connected, the tool permission list, one approved call, and that the server log shows the arguments you expected | the web app |
| Model use | ten independent, read-only, multi-call, verifiable, stable question and answer pairs in XML | the eval question file the scaffold writes |
| Headless end to end | `claude -p` with the server configured: did the model pick the tools unprompted, does a bad key give a clean `isError` | Claude Code |

Inspector exit codes: 0 ok, 1 usage, 2 no App, 3 auth required, 4 unreachable, 5 tool error (`isError`), 6 strict schema
error. `--strict` reports bare boolean schemas as errors and type arrays, untyped schemas and remote `$ref` as warnings; it
does not flag `anyOf`, which the kit's own lint does. On some Windows and Node setups the CLI prints its JSON error and then
crashes instead of returning its code, so assert on the one-line JSON error on stderr as well as the exit
code. Syntax conflict: one vendor page shows `--cli <url> --transport http`; the Inspector v2 documentation uses
`--transport http --server-url <url>`. Use the v2 form and pin the version.

Rules: assert on `result.isError`, never on the HTTP status (tool errors arrive as `200`). A suite that only uses fixtures never
catches a live server's session requirement. Test the test: seed a defect and the suite must go red.

## 6. Deploy checklist for web connectors

1. Public HTTPS with globally routable DNS; no redirect to another host (the connector drops `Authorization` on a
   cross-host redirect).
2. WAF, CDN and bot rules exempt the MCP and OAuth paths or allow the vendor's published ranges.
3. `curl -i <url>` from a public network returns `401` or `405`, not a timeout; `/.well-known/oauth-protected-resource` and one
   authorization-server metadata path return `200` JSON.
4. Authorization server: S256 PKCE, both redirect URIs, a form-encoded token endpoint, answers within 10 seconds,
   `invalid_grant`, refresh rotation, client ID metadata documents and dynamic registration.
5. Results stay within 150,000 characters and 240 seconds; nothing relies on subscriptions, sampling or draft features.
6. Distribution on team and enterprise plans: an organization owner (or a custom role that manages libraries) adds the
   connector under organization settings, then members connect with their own accounts. A free plan allows one custom
   connector. Availability of a plugin does not add its bundled connectors; the owner adds those separately.
7. Optional request headers can ride alongside OAuth to prove origin.
8. Anything added by URL shows as Custom (unreviewed); a directory listing earns Community or Verified.
9. Do not gate behaviour on `clientInfo` names: they vary and are unauthenticated telemetry.
10. Interactive UI in the conversation is optional; a server returning renderable HTML gets a persistent host warning, so
    disable UI tools you do not need.

## 7. Failure catalog (symptom, cause, fix)

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | A stdio server dies or returns garbage on the first call | a library or debug print writes to stdout | send all logging to stderr and configure it before importing application code |
| 2 | A health probe reports an exit before the handshake, but the server works in the client | the probe starts it from the wrong working directory and the server needs its project folder | set the working directory in the probe and in any scheduled task; probe the dependency, not the raw endpoint |
| 3 | A generated server returns 401 with a valid key | the config sets the vendor's key name, but the generated code reads generic bearer-token and base-URL variables | read the generated server's environment contract and set exactly those |
| 4 | The URL becomes `https://https://...` | the binary prepends the scheme itself | pass a bare host |
| 5 | A bare tools/list returns 400 about a missing session id | a 2025-era stateful server needs `initialize` and a session header first | run the handshake, or serve stateless |
| 6 | 406 | `Accept` lacks `application/json` or `text/event-stream` | send both |
| 7 | 405 on POST | an old SSE-only server | switch to streamable HTTP |
| 8 | 404 when a session header is sent | the session expired or the server restarted | initialize again; retrying the same session never works |
| 9 | Behaviour changes silently after the handshake | a missing protocol-version header makes the server assume the oldest revision; an invalid value is a hard 400 | always send a valid header |
| 10 | Monitoring is green and users see failures | tool errors are HTTP 200 with `isError` in the result | assert on `isError`; treat Inspector exit 5 as a failure |
| 11 | An empty tool list or empty results, with no error | an entitlement, licence or plan gate, or an identity without access | check one known record in the vendor's UI as the same identity; 401 means re-authorize, 403 means entitlement |
| 12 | Works from the CLI or curl, fails from the web app | split-horizon, VPN-only or dynamic DNS | public DNS or an MCP tunnel |
| 13 | The edge logs show 403 or 429 that the application never produced | a WAF or bot rule blocks the connector's egress | allow the published ranges or exempt the MCP and OAuth paths |
| 14 | The MCP server sees the request but the authorization server sees nothing | no `resource_metadata` in the 401 and `/.well-known/*` returns 404 | add the `WWW-Authenticate` pointer and serve the metadata |
| 15 | "Authorization failed" after a redirect | a cross-host redirect drops `Authorization` | register the final URL |
| 16 | The token step returns 415 | the token endpoint parses JSON only | accept form-urlencoded bodies |
| 17 | The flow fails although a token is issued | discovery, registration or token calls took more than 10 seconds, or refresh more than 30, often a buffering proxy | stream headers early and check proxies |
| 18 | Reconnect loops after expiry | refresh errors are not `invalid_grant`, or refresh tokens are not rotated for public clients | fix the error codes and rotate |
| 19 | Token requests fail with a resource-identifier error from the identity provider | the MCP URL is not registered as an application ID URI on the app registration | register it, with a verified domain |
| 20 | 403 "Invalid Host" through a tunnel | the DNS-rebinding allowlist holds only `localhost` | add the tunnel or public host name to the allowed hosts |
| 21 | Issuer or audience mismatch | the metadata issuer differs from the token signer, or the token was minted for another resource | align the issuer and validate the resource indicator |
| 22 | A "read-only" audit passes and the server still writes | write and raw-passthrough tools hide behind read-shaped names, and annotations are advisory | audit by behaviour and withhold write scopes |
| 23 | Anyone who reaches the endpoint can act as anyone | privilege derived from an unsigned identity header (confused deputy) | authenticate the channel and take the role from the credential |
| 24 | Injected text completed a "confirmed" write | in-band nonce confirmation | remove the capability or confirm out of band |
| 25 | An approved tool now behaves differently | the description changed after approval (rug pull) | pin and hash tool definitions and re-compare on a schedule |
| 26 | The model passes a field and nothing happens | the SDK drops unknown arguments silently | refuse them and name them |
| 27 | A client rejects the tool schema | `$ref`, `anyOf`, `oneOf` or `const` emitted from model classes | lower schemas at build time |
| 28 | Output is cut off | it exceeds the host cap | page to a byte budget |
| 29 | v1 code breaks on import after a fresh install | an unpinned install pulled the new major (renames, snake_case, moved transport arguments) | pin the major and migrate deliberately |
| 30 | "Unexpected key(s) in SKILL.md frontmatter" on upload | fields that only Claude Code understands are in a skill archive | strip to the portable fields |
| 31 | An uploaded archive is "not a skill" | `SKILL.md` sits at the archive root, or the folder name differs from `name` | zip the folder itself and match the names |
| 32 | Rate limits appear only after rollout | limits are keyed per app client per tenant | load-test at user scale |
| 33 | A tool is visible but the call returns a Connect card | that user has not completed per-user OAuth; visibility is not the same as working | each user connects once |

## 8. Where things are

- Skill: `plugins/workbench-core/skills/mcp-builder/SKILL.md` (scaffold, lint, templates, references).
- Wrapping an existing REST API: `docs/engineering/api-bridges.md` and the `api-bridge` skill.
- Official pages (read the current versions): https://modelcontextprotocol.io/specification and
  https://claude.com/docs/connectors/building/authentication
