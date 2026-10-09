---
name: api-bridge
description: "Wrap an existing REST or OpenAPI API as a curated MCP server. For a server from scratch use mcp-builder."
disable-model-invocation: true
---

# api-bridge

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it appears unreplaced (the
> skill was copied in without the plugin), use `py -3` on Windows and `python3` on Linux, macOS and WSL, never the Microsoft
> Store `python` stub.

Turn an existing API into 5 to 15 workflow tools. The product is the curation, not a mirror of the endpoints. Reasoning, GraphQL
and proxy rules and private-host access: `docs/engineering/api-bridges.md`.

**Refuses:** a catch-all `api_request(method, path)` in any spelling; forwarding the caller's token upstream; identity from a
tool argument or an unsigned header; credentials, cookies or headers as tool arguments; one tool that mixes reads and writes.
**Never** put an upstream credential in a file or a log; it comes from the environment contract.

## 1. Inventory
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/openapi_inventory.py" openapi.json          # table
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/openapi_inventory.py" openapi.json --json   # for tooling
```
Method, path, parameters (`*` = required), body fields, auth, a response-size hint. JSON documents; YAML needs PyYAML.
No spec? Write the inventory by hand from the vendor's reference, one row per operation you might need.

## 2. Curate
Copy `${CLAUDE_SKILL_DIR}/templates/worksheet.md` and decide each operation: keep, merge into a workflow tool, or drop; read or
write; a name; why a model needs it; a byte budget. Drop by default. A draft for reference only:
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/openapi_draft.py" openapi.json --out draft.json
```
The draft is marked `_draft` and the bridge refuses it until you curate it: merge chatty reads, flip a write on deliberately,
write real descriptions, delete the marker.

## 3. Build the bridge
Copy `${CLAUDE_SKILL_DIR}/templates/bridge-python/` into the project (`bridge.py`, `worksheet.py`, `tests/`), put the curated
`worksheet.json` beside them, then check it against the spec:
```bash
"${user_config.python}" worksheet.py worksheet.json --spec openapi.json     # prints "worksheet ok" or the reasons
```
Environment contract (full table in the template README): `UPSTREAM_BASE_URL` (https; http only for localhost),
`UPSTREAM_TOKEN` (the bridge's own service credential), `UPSTREAM_TIMEOUT`, `UPSTREAM_RETRIES`, `BRIDGE_WORKSHEET`.
Upstream failures become `isError` with the status and a hint; `Retry-After` is honoured up to a cap; redirects are not followed;
oversized responses are errors that ask for a narrower request. Free text under `text_fields` is labelled as untrusted data.

## 4. Test
`python -m unittest discover -s tests` in the project runs the generated contract test (tool set equals worksheet, annotations
match modes, flat schemas, unknown arguments refused). Then run the bridge against the real API with a read-only credential
and confirm that a write endpoint you did not curate in is unreachable.

## 5. Serve it
- Developer clients, server on a private host: `${CLAUDE_SKILL_DIR}/templates/bridge-stdio-ssh.json` (replace the `<host>` placeholders).
- Web connectors, HTTP and auth: scaffold with the `mcp-builder` skill (`--http --auth ...`) and reuse `build_tool()` and
  `worksheet.py`; follow its deploy checklist.
- Bridging another MCP server, or GraphQL: the rules are in `docs/engineering/api-bridges.md` (text only; no code ships).
