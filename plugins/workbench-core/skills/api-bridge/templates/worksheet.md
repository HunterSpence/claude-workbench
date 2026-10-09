# Curation worksheet

One row per API operation the inventory lists. Decide, then write the kept rows into `worksheet.json`.

| operation | decision (keep / merge into `<tool>` / drop) | read or write | tool name | why a model needs it | page or byte budget |
|---|---|---|---|---|---|
| `GET /items/{item_id}` | merge into `items_summary` | read | `items_summary` | one call answers "what is the state of item X" | 20000 bytes |
| `GET /items/{item_id}/lines` | merge into `items_summary` | read | `items_summary` | same | |
| `POST /items` | keep | write | `items_create` | the one action users ask for | idempotency header |
| `DELETE /items/{item_id}` | drop | write | | rarely wanted, hard to undo | |

## Rules for the decisions
- 5 to 15 tools in total. A tool answers a question or does a job; it does not mirror an endpoint.
- Reads and writes never share a tool. A write is exactly one operation and says whether it is destructive.
- Every write has an idempotency header (the bridge adds an `idempotency_key` argument) or is naturally idempotent.
- Drop by default. A write endpoint exists for the model only when a row above keeps it.
- Name an argument for what it identifies (`item_id`). Never for who is asking (`user_id`, `email`, `as_user`).
- Free text written by other people (names, notes, comments) goes in `text_fields` so it is labelled as untrusted data.
- Set `max_bytes` from the host's cap (150000 characters on the web apps).

## `worksheet.json` shape
```json
{
  "version": 1,
  "service": "example",
  "tools": [
    {"name": "items_summary", "title": "Item summary", "description": "Return an item with its lines.",
     "mode": "read", "operations": ["GET /items/{item_id}", "GET /items/{item_id}/lines"],
     "params": [{"name": "item_id", "in": "path", "type": "string", "required": true, "description": "Item identifier"}],
     "text_fields": ["note"], "max_bytes": 20000}
  ]
}
```
A write tool adds `"destructive": true|false` and `"idempotency_header": "Idempotency-Key"`. An optional argument needs a
`default` (never null). `"keep": false` records a considered drop. Run `python worksheet.py worksheet.json --spec openapi.json`
until it prints `worksheet ok`.
