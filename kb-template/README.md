# Knowledge base

A plain-Markdown knowledge base that Claude reads and writes through the `save` skill (workbench-kb plugin).
The bootstrap copies this folder to your KB root (default `~/claude-kb`) once and never overwrites it.

## Layout
| Path | What it holds | Who writes it |
|---|---|---|
| `active-context.md` | In-flight state, read at every session start | only `save_driver.py --ac-write` (a locked 3-way merge) |
| `00-index.md` | Where to start: links every domain and each long-lived note, so a related-notes walk from any domain reaches the rest | you and the save skill; add a line when you add a domain or a long-lived note |
| `inbox.jsonl` | The journal: one line per update, append-only | `save_driver.py --inbox-add` |
| `<domain>/HOT.md` | Current facts, decision heuristics, error blacklist | the save skill; byte-capped |
| `<domain>/history.md` | Session records; old ones roll into `history/YYYY-MM.md` | the save skill and the driver |
| `<domain>/<topic>.md` | Reusable knowledge (runbooks, configs, patterns), with frontmatter | the save skill; the driver stamps `updated:` |
| `daily/YYYY-MM-DD.md` | One line per save | the driver |
| `_shared/digests/*.md` | On-demand topic digests: Windows and shell, git and CI, Claude Code, MCP, testing, orchestration, models and tokens, the knowledge layer, retrieval evaluation, reports and PDFs, the internal assistant, enterprise RAG (five notes), ponytail measurements, and how the kit works (with the explainer and poster PDFs beside it) | shipped with the kit |
| `_shared/bug-cards.md`, `_shared/bug-detectors.json` | Recurring failures with their fixes, and the error patterns that point to them | shipped with the kit |
| `_shared/facts.json` | The fact registry: facts that must have one home (see Pinned facts) | you; checked by `kb_health.py facts` |
| `inbox/` | Drops awaiting triage (daily digests, pasted notes); nothing in it is promoted automatically | the ingest skill, you |

Nothing derived lives in this folder, so a synced folder (OneDrive and similar) never holds a live database file or a
lock. Both sit on this machine under `<claude config dir>/workbench/`:

| Path | What it holds |
|---|---|
| `cache/kb-<key>.db` | The search index (SQLite); rebuilt on demand |
| `kb-state/<key>/` | The save lock, precompact flags, active-context snapshots, save metrics and journal windows |

`<key>` is eight hex digits of this folder's path, so two knowledge bases never share either. An earlier kit kept the
state in a `.state/` folder here: the first `save_driver.py --pre` copies it across (it never moves or deletes it, and
the old copy stays readable for one release). Delete `.state/` by hand once you are on the next release. Uninstalling
keeps `kb-state/`, because the snapshots in it are recovery copies.

## Domains
`_shared`, `platform`, `infra`, `data`, `ai`, `security`, `ops`, `projects`. Every folder here that holds a
`HOT.md` is a domain, so add or rename folders to fit your work. Route each fact to one domain; link to it from elsewhere instead of
repeating it (a link is the note path, such as `ops/some-note`, in double square brackets; links resolve against
this folder).

## Folder taxonomy
Source first, never move. Where a file lives is decided by where it came from, so no judgment is needed and links
never break.
- `inbox/` holds drops awaiting triage; file them within a day. Authored knowledge is `<domain>/<topic>.md`: the
  domain folders above are the topic list, and the save skill writes nowhere else.
- Captured material (pages, shared files, mail threads, meetings) lives in a `captured` folder next to the KB
  (`<DATA>/captured/`), never inside it: the KB tools walk the whole KB root, and bulk captures would swamp its
  caps and scans.
- One file per item: one page, one shared file, one mail thread, one meeting occurrence. Re-capturing overwrites the
  same file.
- Never move a file after writing it. To retire one, set `status: archived` in its front matter. Search does not read
  `status`: an archived note ranks like any other. It ranks lower only where a passage is marked SUPERSEDED, OBSOLETE
  or CORRECTED, and for history records, so mark the retired passage as well.
- At most three levels below the KB root. Slugs use lowercase letters, digits and hyphens, at most sixty characters;
  the full path stays under two hundred and forty characters so Windows tools and sync clients cope.

## Pinned facts
A fact that gets looked up wrongly, or that a tool keeps contradicting, is worth pinning. Write it once, in the note
that owns it, with the date you last checked it, any signal you know to mislead, and the owner. A made-up example, a
line in `infra/build-server.md`:

    - The build server runs in region east-a. `verified: YYYY-MM` · misleading signal: the console's default-region label still says west-b · owner: infra/build-server

Then register it in `_shared/facts.json` so a check catches drift: `owner` is that note, `canonical` the text it must keep
stating (`region east-a`), `forbidden` the alternates that may appear nowhere else (`region west-b`). `kb_health.py facts`
fails when a forbidden text turns up in another note or in an always-loaded instruction file, or when the owner stops
stating its canonical text. The owner note itself may name the misleading value; lines marked SUPERSEDED, history
records, `daily/`, `inbox/` and README files are not checked. An empty registry costs nothing.

## Rules that keep it useful
- One fact, one home. A fact stated twice drifts.
- Changing a fact: keep the old line and mark it `SUPERSEDED (YYYY-MM-DD): was X, now Y`. Before you add or change a
  fact, it helps to search for notes that already state it, so two notes do not disagree with neither one marked.
- Over a cap: demote with `kb_demote.py`, never compress text in place.
- `updated:` in a note's front matter is the driver's job: a save stamps today's date on each note it was told about
  whose content changed since the save began. It never adds a front matter block to a note that has none, and it leaves
  a HOT.md alone when the stamp would take it past its cap.
- No credentials, ever. The save driver refuses to finish while a file it writes holds a credential-shaped value.
- If you make this folder a git repository, the save driver commits locally; it pushes only when you configured a remote yourself AND pass `--push`.

## Tools (in the workbench-kb plugin's `scripts/`)
`save_driver.py` (the save skill's driver), `kb_search.py` (search), `kb_health.py` (checks), `kb_facts.py` (the
fact registry's check), `kb_demote.py` (move HOT.md lines to history), `kb_index.py` (rebuild the index), `kb_audit.py`
(caps). A save ends with two advisory lines (the size of the always-loaded instructions; once a week, notes marked
deprecated or obsolete). They never block it, and a tool that is missing reads "skipped".
