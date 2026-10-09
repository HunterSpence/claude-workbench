# Bridging existing APIs to Claude

How to wrap a REST, OpenAPI or GraphQL API, or another MCP server, as a curated MCP server. Companion to `docs/engineering/mcp-servers.md`; the `api-bridge` skill
(`plugins/workbench-core/skills/api-bridge/SKILL.md`) holds the scripts and the bridge template.

A bridge is a product decision, not a conversion. A model picks tools better from a handful of workflow-shaped ones than from
a mirror of every endpoint, so the work is curation.

## 1. REST and OpenAPI to MCP

1. **Inventory.** List every operation: method, path, parameters, auth, a size hint for the response
   (`openapi_inventory.py`).
2. **Curate.** Fill the worksheet (`plugins/workbench-core/skills/api-bridge/templates/worksheet.md`): keep, merge or drop each operation; mark it read or write; name
   the workflow tools; set a byte budget. Target 5 to 15 tools. Merge chatty reads into one tool. Drop by default: a write
   endpoint exists for the model only when a row keeps it.
3. **Draft, for reference only.** A generator (`openapi_draft.py`, or an OpenAPI-import feature in a framework) shows names and
   parameters. The framework vendors themselves say generation is for bootstrapping and prototyping, not for mirroring an
   API, and that models do significantly better with a curated server. The draft carries a marker the bridge refuses.
4. **Write the curated bridge.** Hand-write `worksheet.json` and run the bridge template. Keep the upstream credential in the
   bridge. Per-user upstream calls need per-user OAuth upstream; with only a service credential the bridge must do the
   scoping itself.
5. **Read the generated server's environment contract** if you do use a generator: generators often read a generic bearer
   token and base URL, not the vendor's key name.
6. **Map errors.** An upstream failure becomes `isError` with the upstream status and a hint; honour `Retry-After` within a
   cap and report it beyond; retry with backoff; never follow a redirect with the service credential attached.
7. **Test from the worksheet.** The contract test compares the published tool set with the worksheet, checks annotations
   against modes, flat schemas, and that unknown arguments are refused. Run the bridge against a local fixture API that counts
   hits so you can show that a write endpoint is unreachable until it is curated in.

What the template refuses, by design:
- a catch-all `api_request(method, path)` tool, in any spelling (a `method`, `verb`, `path` or `url` argument, or an operation
  that is not a literal `METHOD /path`);
- forwarding the caller's token upstream (the bridge sends its own service credential only);
- taking identity from a tool argument or from an unsigned header; credentials, cookies and headers are not tool arguments;
- mixing reads and writes in one tool, or a write without a destructive flag and an idempotency header;
- more than 15 tools, or draft output that was never curated.

Environment contract and error mapping: `plugins/workbench-core/skills/api-bridge/templates/bridge-python/README.md`.

## 2. GraphQL to MCP

Prefer **named, persisted operations as tools** over a raw `query` tool: each operation is one tool with typed variables, the
way a REST operation is. If a raw query tool is unavoidable, make it read-only, name the API in its description (a directory
review rule), cap query depth and cost, and refuse mutations. Rate budgets are often shared with the vendor's ordinary API
calls and keyed per app client per tenant, so budget for that. This is guidance only; the kit ships no GraphQL code.

## 3. MCP to MCP proxy or gateway

Use one when you must curate, re-authenticate, audit or re-host a third-party server. Rules:
- Re-authenticate at the proxy and never forward the client's token (token passthrough is forbidden).
- Allowlist tools, **pin a hash of each tool definition** and re-compare it on a schedule: a description that changes after
  approval is a rug pull.
- Assess tool descriptions across all connected servers together: shadowing happens between servers.
- Strip cookies and connection-owned headers at the trust boundary.
- Framework proxies can also bridge transports (stdio to HTTP and back). This is guidance only; the kit ships no proxy code.

## 4. Reaching a server on a private host

**stdio over SSH (developer clients only).** Bind the remote server to `localhost`, then let the client config run the server
through `ssh`: MCP rides the SSH channel, with no open port and no tunnel. Use a least-privilege SSH user. A shell start-up file
that prints to stdout breaks the framing; use `-T` and a non-interactive command. This works for Claude Code and Desktop, never
for web connectors. A sample client config with `<host>` placeholders is
`plugins/workbench-core/skills/api-bridge/templates/bridge-stdio-ssh.json`.

**Private network to Claude on the web.** In order of preference: a public HTTPS endpoint with auth and a WAF exemption for the
vendor's published ranges; or an MCP tunnel (an outbound-only tunnel to the vendor's proxy, offered to enterprise plans by
request; tunnel host names accept only Claude, so test from Claude rather than curl). Split-horizon or VPN-only DNS is the
classic "works in the CLI, not on the web" failure.

## 5. Checks before you ship a bridge

- `python worksheet.py worksheet.json --spec openapi.json` prints `worksheet ok`.
- The contract test passes and a write endpoint you did not curate in is unreachable (the fixture shows zero hits).
- The tool list passes `plugins/workbench-core/skills/mcp-builder/scripts/lint_tools.py`.
- Responses are within the host's result cap (`plugins/workbench-core/skills/mcp-builder/references/hosts.md`), and free
  text from other people is labelled as untrusted data.
- The deploy checklist in `docs/engineering/mcp-servers.md` (section 6) is done for any remote deployment.
