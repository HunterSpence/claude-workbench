# Testing (working checklist)

The ladder with reasons: `docs/engineering/mcp-servers.md` section 5.

## What the scaffold generates
| File | Checks |
|---|---|
| unit tests (`test_engine`) | engine functions without MCP; paging, validation, idempotency, labelling; schema helpers |
| contract tests (`test_contract`) | exact tool set in stable order; `title` and hints on every tool; flat schemas; no identity argument; structured and text result agree; `isError` with a next step; unknown arguments refused by name; both protocol eras; stdout carries only protocol messages (stdio); on HTTP: oversized request rejected, foreign Host rejected, missing or wrong credential gets 401, tokens checked for signature, audience and expiry |
| injection tests (`test_injection`) | planted payloads (instruction text, a forged closing tag, hidden characters, text split across fields) come out inside `<untrusted-data>` with markup escaped and nothing hidden |
| `ci.yml` | the tests above, then for `--http` the Inspector against the running server |

## Inspector CLI (pin the version)
```bash
npx @modelcontextprotocol/inspector@2.10.1 --cli --transport http --server-url http://localhost:8000/mcp --method tools/list --strict
npx @modelcontextprotocol/inspector@2.10.1 --cli --transport http --server-url http://localhost:8000/mcp --method tools/call --tool-name records_get --tool-args-json '{"record_id":"r1"}'
```
| Exit | Meaning |
|---|---|
| 0 | ok |
| 1 | usage |
| 2 | no App (UI resource) |
| 3 | authentication required |
| 4 | unreachable |
| 5 | tool error (`isError`) |
| 6 | strict schema error |

`--strict` needs `--method tools/list`. It errors on bare boolean schemas and warns on type arrays, untyped schemas and remote
`$ref`; it does not flag `anyOf`, so keep `lint_tools.py` in the loop. CI for a protected server expects exit 3 without
credentials, which proves the gate. Use `--tool-args-json` when a numeric argument must stay a number. On some Windows and Node
setups the CLI exits 0xC0000409 after printing its JSON error instead of returning the code: read the error JSON on stderr.

## Both protocol eras
Hosted Claude opens with the 2025-era `initialize` handshake; newer clients use the stateless path. The SDK clients probe and
fall back; run the contract once with each (`mode="legacy"` and `"auto"` in the Python client).

## Real client
Add the server as a custom connector (tunnel a local server, keep auth on). Check: Connected, the tool permission list, one
approved call, and that the server log shows the arguments you expected.

## Model use
Ten independent, read-only, multi-call questions with a stable answer, in `evals/questions.xml`. Run headless and read the
transcript for the tools the model picked unprompted; check that a bad key gives a clean `isError`.

## Rules
- Assert on `result.isError`, never on the HTTP status: tool errors arrive as `200`.
- A fixture-only suite never catches a live server's session requirement; do one run against the deployed endpoint.
- **Test the test:** break one tool registration (rename it, drop its decorator) and confirm the same checks fail. Seed a
  schema defect and confirm the lint or Inspector reports it.
