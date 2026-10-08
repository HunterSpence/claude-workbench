# Knowledge base

A plain-Markdown knowledge base that Claude reads and writes through the `save` skill (workbench-kb plugin).
The bootstrap copies this folder to your KB root (default `~/claude-kb`) once and never overwrites it.

## Layout
| Path | What it holds | Who writes it |
|---|---|---|
| `active-context.md` | In-flight state, read at every session start | only `save_driver.py --ac-write` (a locked 3-way merge) |
| `inbox.jsonl` | The journal: one line per update, append-only | `save_driver.py --inbox-add` |
| `<domain>/HOT.md` | Current facts, decision heuristics, error blacklist | the save skill; byte-capped |
| `<domain>/history.md` | Session records; old ones roll into `history/YYYY-MM.md` | the save skill and the driver |
| `<domain>/<topic>.md` | Reusable knowledge (runbooks, configs, patterns), with frontmatter | the save skill |
| `daily/YYYY-MM-DD.md` | One line per save | the driver |
| `.state/` | Locks, flags, snapshots, metrics | the tools only; keep it out of git |

The search index is a SQLite file under `<claude config dir>/workbench/cache/`, outside this folder, so a synced
folder (OneDrive and similar) never holds a live database file.

## Domains
`_shared`, `platform`, `infra`, `data`, `ai`, `security`, `ops`, `projects`. Every folder here that holds a
`HOT.md` is a domain, so add or rename folders to fit your work. Route each fact to one domain; link to it from elsewhere instead of
repeating it (a link is the note path, such as `ops/some-note`, in double square brackets; links resolve against
this folder).

## Rules that keep it useful
- One fact, one home. A fact stated twice drifts.
- Changing a fact: keep the old line and mark it `SUPERSEDED (YYYY-MM-DD): was X, now Y`.
- Over a cap: demote with `kb_demote.py`, never compress text in place.
- No credentials, ever. The save driver refuses to finish while a file it writes holds a credential-shaped value.
- Work data stays where your organisation allows it. If you make this folder a git repository, the save driver
  commits locally; it pushes only when you configured a remote yourself AND pass `--push`.

## Tools (in the workbench-kb plugin's `scripts/`)
`save_driver.py` (the save skill's driver), `kb_search.py` (search), `kb_health.py` (checks), `kb_demote.py`
(move HOT.md lines to history), `kb_index.py` (rebuild the index), `kb_audit.py` (caps).
