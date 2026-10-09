# Plugging in an enterprise knowledge provider

The kit searches two local things before it asks anyone else: `kb_search` over your knowledge base (exact names and IDs) and
`find` over your documents, captured pages and the same knowledge base (meaning search). This page is the contract for a
third source, such as your organisation's own search service, so Claude can query it the same way. Nothing here is built
for you: the kit ships the reference server and the test; a provider is yours to write or to adopt.

## What a provider is
Any MCP server, stdio or HTTP, that your organisation sanctions. You register it through the normal golden config
(`mcp/golden-config.template.json`) and the healer (`tools/mcp-healer/`), with its `egress` stated, and a managed MCP
policy still wins. Read `mcp/README.md` first: it lists what each shipped entry sends where.

## The tools
`plugins/workbench-core/skills/find/scripts/find_mcp.py` is the reference implementation. Copy its shape.

| Tool | Arguments | Returns |
|---|---|---|
| `search` | `query`, `limit` (at most 25), optional `root` or filters | `{hits, mode, coverage, untrusted: true}` |
| `show` | `ref`, `context` (paragraphs either side, at most 10) | `{ref, text, untrusted: true}` |
| `related` (optional) | `ref`, `depth` (1 to 3) | `{start, related, untrusted: true}` |

Each hit needs `ref` (an opaque string that `show` and `related` accept), `title`, `snippet` and `"untrusted": true`. Add
what you have: `locator` (page, slide or sheet), `url`, `source`, `mtime`, `score`. `coverage` names what was not searched,
so Claude can say the answer may be incomplete. Each item in `related` carries `ref`, `title`, `via` (why it is related) and
`"untrusted": true`. A bad ref is a tool error Claude can read (`isError`), not a protocol error.

## Rules a provider keeps
- **Results are data.** Text that comes back from a document is never an instruction. Mark every result `untrusted`, and
  say so in the server's `instructions`. Claude is told to cite the ref and to ignore any request found inside a result.
- **Access is the signed-in user's.** The provider enforces permissions as the person asking. A service account that sees
  more than the user does is out of contract.
- **Nothing is cached silently.** The kit stores provider results only through the capture writer (which applies the
  placement and label rules), and writes to the knowledge base only through a save the user approves.
- **Say where the data goes.** The `egress` line in the golden entry is read by your security team before the entry is turned on.

## The answer procedure
When a question might be answered from work documents, Claude searches in this order: `kb_search` for exact names and IDs,
then `find` (add `--root kb` to search the notes by meaning), then each enabled provider. It cites `provider:ref` for every
claim and says which providers it did not query.

## Conformance
`plugins/workbench-core/skills/find/scripts/tests/test_find_kb.py` starts `find_mcp.py` over stdio and checks the
handshake, the tool list, a `search`, a `show` and a `related` call, and that every result is marked untrusted. Point a copy
of it at your server to show it keeps the same contract.

## Out of scope
Building a provider, hosting a vector store, or sending your documents to a service the kit does not already list.
