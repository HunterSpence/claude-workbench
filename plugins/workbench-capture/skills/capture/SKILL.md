---
name: capture
description: Read-only capture of work pages and shared files into the local knowledge layer - intranet pages through a dedicated signed-in Edge profile, listed OneDrive files from the sync folder. Paced, scoped, stops on any sign-in, consent or policy page. User-invoked.
disable-model-invocation: true
---

# /workbench-capture:capture

`CAP` below means `node "<workbench home>/capture/app/capture.mjs"`, where the workbench home is
`<CLAUDE_CONFIG_DIR or ~/.claude>/workbench`. It exists only when setup ran with `--with capture`.

## Hard stop rule (read first)
Exit code 3 means capture stopped on purpose: a sign-in, second-step, consent, policy, data-protection or block page,
a hit on the hourly cap, a non-GET request, a tenant mismatch or a browser policy. Show the user `stop.kind`,
`stop.reason` and `stop.ask` from the run report word for word. Sign-in and second steps are the user's to complete
(`CAP login`).

## Before the first run
1. The Edge policies `RemoteDebuggingAllowed` and `HeadlessModeEnabled` must not be turned off for this device. If
   `RemoteDebuggingAllowed` is off, capture stops with the ask for IT and does nothing else.
2. Set the scope. Own sites and files shared with the user come first; the deny list is for what to skip.
3. Do a `--dry-run` first, then a small real run (`--max-per-hour 30`), then the full run.

```bash
CAP scope set tenant example.com                        # the tenant the signed-in account must belong to
CAP scope add --source intranet https://intranet.example.com/handbook/
CAP scope add --deny --source intranet /handbook/people/
CAP scope list                                          # JSON of everything below
CAP login                                               # a window opens; the USER signs in and closes it
```
A URL entry is stored without its query string and fragment (sharing links carry tokens there). Only the hosts of the
scope may be navigated to. A deny entry blocks any address or path that contains it, in any letter case.

## Commands
| Goal | Run |
|---|---|
| Sign in once (headed; the user does it) | `CAP login` |
| Capture a source | `CAP run --source intranet` (add `--dry-run` to list without writing) |
| Lower the hourly cap | `CAP run --source S --max-per-hour 60` (the cap can be lowered, never raised above 200) |
| Include sensitivity-labelled items | `CAP run --source S --include-labelled` |
| See scope and the last run | `CAP status` · `CAP scope list [--source S]` |
| Edit scope | `CAP scope add\|remove [--source S] [--deny] VALUE` · `CAP scope set KEY VALUE` |
| Remove captured copies | `CAP purge [--source S] [--older-than DAYS]` |
| Remove the saved sign-in | `CAP logout` |

`scope set` keys: `tenant`, `retention_days`, `sync_root`, `max_depth`, `max_pages`, `max_files`, `placement.<source>`
(`local` keeps that source's copies under `<WB>/capture/local/<source>/` instead of the data folder; register that
folder yourself with the find skill's `add-root`).

## Shared files (no browser)
1. In the OneDrive web app, open "Shared with me" and use "Add shortcut to My files" yourself, once per folder or file.
   Capture never clicks it. Wait for OneDrive to sync the shortcut.
2. `CAP scope set sync_root "<your OneDrive folder>"`.
3. List only what you want, relative to that folder: `CAP scope add --source shared-files "Shared/Planning"`. A folder
   entry means every readable file inside it, so list a folder only when you want all of it.
4. `CAP run --source shared-files`. Each file is read once (a paced hydration), converted by the find skill's `convert`,
   and written; a sensitivity-labelled file is skipped and named in the report.

## What a run produces
- Files under `<DATA>/captured/<source>/<scope>/<date>-<title>-<8 hex>.md` with front matter (`source`, `url`, `title`,
  `author`, `modified`, `captured_at`, `labels`, `scope`). The find skill indexes them; a hit shows `url` and `source`.
- A report at `<WB>/capture/runs/<UTC stamp>.json`: `status`, `exit`, `stop`, `entries` (`url`, `path`, `sha256`,
  `expires` = capture time plus `retention_days`), `skipped` (with reasons), `counts.paced`.
- Pace: at most 10 loads, clicks, downloads or file reads a minute and 200 an hour, with a random pause between them.

## Reporting back
Say how many pages or files were written and skipped (and why), whether the run stopped, and where the report is. Sources, settings and the module contract:
`${CLAUDE_SKILL_DIR}/references/sources.md`. Every limit and its known gaps: `${CLAUDE_SKILL_DIR}/references/limits.md`.
