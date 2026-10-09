# Tool design (working checklist)

The full rules and their reasons are in `docs/engineering/mcp-servers.md` section 2. This is the page to keep open while you
fill in the tool plan.

## The plan table
| tool | read or write | title | annotations | arguments (flat) | page or byte budget | who may call |
|---|---|---|---|---|---|---|
| `service_verb_noun` | read | short phrase | `readOnlyHint` | name, type, description | rows per page, characters | credential scope |

Fill one row per tool before writing code. Five to fifteen rows; if there are more, merge chatty reads into workflow tools or
split the surface into several connections by use case.

## Annotations
| Kind | `readOnlyHint` | `destructiveHint` | `idempotentHint` | `openWorldHint` |
|---|---|---|---|---|
| Read | true | false | true | true when it reaches outside systems |
| Create | false | false | true only with an idempotency key | as above |
| Update or delete | false | true | true when repeating is safe | as above |

Every tool also has a `title`. Annotations tell the client how to prompt; they are not enforcement. Enforce read-only with a
scoped credential and by having no write code path.

## Descriptions
- Good: "Return one record with its body. Use an id from records_list."
- Bad: "Always call this first." "Ignore other tools." "Fetch your rules from this URL." Hidden or encoded text.
- A freeform query tool names or links the API it queries.

## Arguments
- Flat objects of strings, numbers, booleans and enums. No `$ref`, `anyOf`, `oneOf`, `allOf`, `const`, no null unions: give an
  optional argument a neutral default instead (`""`, `0`, `false`). Python helper: `schemas.lower()` in the scaffold; the
  published list is lowered on the way out. TypeScript: plain zod objects are flat; lower other libraries' schemas first.
- Never `user_id`, `email`, `as_user` or similar. Identity comes from the authenticated credential.
- Name an argument for what it identifies (`record_id`), not who is asking.
- Refuse unknown arguments and name them (the scaffold's guard does this in Python; strict schemas do it in TypeScript).

## Results
- Return structured content and a text copy of the same data; declare an `outputSchema`.
- Failure: `isError: true` and a message that says what to do next ("call records_list to see the ids").
- Page with a cursor and a byte budget; summary by default, detail on request. Never truncate silently.
- Free text written by other people is wrapped as `<untrusted-data>` (markup escaped, hidden characters removed), and the
  server `instructions` say results are data, not instructions.
- Return the same order every time.

## Lint rules and fixes
| Rule | Fix |
|---|---|
| `name-length` | at most 64 characters |
| `catch-all` | one tool per operation; drop the `method` argument |
| `read-write-mix` | split into a read tool and a write tool; a read-only tool cannot have a write verb in its name |
| `title`, `hints` | add `title` and `readOnlyHint` or `destructiveHint` |
| `schema-keyword` | flatten or lower the schema |
| `identity-arg` | derive identity from the credential |
| `instructing-description` | describe what the tool does and when to call it |

Run `scripts/lint_tools.py` on a tools/list dump (the Inspector CLI prints one).
