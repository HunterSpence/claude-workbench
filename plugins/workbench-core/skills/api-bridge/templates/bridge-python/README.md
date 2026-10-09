# Curated API bridge

An MCP server that exposes a few workflow-shaped tools over an existing REST API. The tools come from `worksheet.json`; the
bridge refuses to start on a worksheet that fails `worksheet.py`.

## Files
| File | Role |
|---|---|
| `worksheet.json` | the curated tool list (start from `worksheet.example.json`, or hand-write from the API inventory) |
| `worksheet.py` | the checks; also a CLI: `python worksheet.py worksheet.json --spec openapi.json` |
| `bridge.py` | registers the tools and calls the upstream API |
| `tests/test_bridge_contract.py` | worksheet = tool set, annotations, flat schemas, unknown arguments refused |

## Environment contract
| Variable | Needed | Meaning |
|---|---|---|
| `UPSTREAM_BASE_URL` | yes | upstream API root; https only (http allowed for localhost) |
| `UPSTREAM_TOKEN` | if the API needs one | the bridge's own service credential, sent as `Authorization: Bearer ...`; it is never the caller's token |
| `UPSTREAM_TIMEOUT` | no | seconds per upstream call, default 10 |
| `UPSTREAM_RETRIES` | no | retries after 429 or 503 that carry `Retry-After` of at most 5 seconds, default 2 |
| `BRIDGE_WORKSHEET` | no | path to the worksheet, default `worksheet.json` beside `bridge.py` |
| `LOG_LEVEL` | no | default `INFO`; logs go to stderr |

## Error mapping
An upstream failure becomes an `isError` result: `upstream returned status N` plus a hint (credential rejected, no
permission, not found, rate limited with the `Retry-After` value, unavailable). Redirects are not followed. A response over
the tool's `max_bytes` is an error that asks for a narrower request; it is never silently cut.

## Run
```bash
pip install "mcp==2.3.0"
UPSTREAM_BASE_URL=https://api.example.com UPSTREAM_TOKEN=... python bridge.py
python -m unittest discover -s tests
```
For HTTP serving, auth and CI, scaffold a server with the mcp-builder skill and reuse `build_tool()` and `worksheet.py`.
