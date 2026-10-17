# workbench-capture

Opt-in plugin (installed only with `--with capture`). It reads work surfaces you can already open and saves read-only
Markdown copies for the knowledge layer. It is separate from `workbench-core` so IT can allow or deny it on its own.

| Skill | What it does |
|---|---|
| `capture` | Intranet pages through a dedicated signed-in Edge profile, and listed files from your OneDrive sync folder. Paced, scoped, read-only. |
| `ingest` | Meeting transcripts and mail, experimental. |

The limits are in `skills/capture/references/limits.md`; the sources and their settings are in
`skills/capture/references/sources.md`.

The runtime is Node (20 or newer) with one dependency, `playwright-core`, installed by the setup skill into
`<WB>/capture/app/` with `npm install --ignore-scripts`.
