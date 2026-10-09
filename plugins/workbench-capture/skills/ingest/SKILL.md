---
name: ingest
description: EXPERIMENTAL. Turns downloaded Teams meeting transcripts and, opt-in, cached Outlook or Graph mail into one knowledge file per meeting or thread, each with a quarantined AI digest. Read-only, paced, stops at any security prompt or tenant gate. User-invoked.
disable-model-invocation: true
---

# /workbench-capture:ingest (experimental)

`ING` below means `<knowledge_python> "${CLAUDE_SKILL_DIR}/scripts/ingest.py"`, where `knowledge_python` is the value in
`<workbench home>/config.json`. First time only: `ING setup --apply` installs `requirements.txt` (pywin32, Windows) there.

## Hard stop rule (read first)
Exit code 3 means ingest stopped on purpose: Outlook refused or prompted for a protected property, a security prompt is
waiting, or the tenant has not allowed the route (transcripts off, admin approval missing). Show the user `stop.reason`
and `stop.ask` from the run report word for word. Never retry, never switch to another route or tool, never change an
Outlook, registry or tenant setting, never click a prompt. The report is `<workbench home>/capture/runs/<UTC>-ingest.json`.
Exit 5 means the InfoSec acknowledgement is missing; exit 4 is an error with a message.

## Before the first run
1. The user tells their security team first (the note is printed by `ING ack-infosec`; the checklist is in
   `${CLAUDE_SKILL_DIR}/references/asks.md`).
2. `ING ack-infosec` records the acknowledgement. Without it every run exits 5.

## Meetings
The user opens a past meeting in Teams, uses Download on the transcript (only where Teams offers it to them) and puts the
`.vtt` or `.docx` in `<data folder>/captured/_drop/meetings/` (an optional `<name>.meta.json` next to it can carry title,
start, end, organizer, attendees). Then `ING meetings run`: one file per meeting under `captured/meetings/<scope>/`, the
originals move to `<workbench home>/capture/drop-done/`, unreadable ones to `_drop/meetings/failed/`. A labelled `.docx`
keeps its name only. `ING meetings run --graph` also fetches transcripts through Microsoft Graph once the user's own
tenant app is configured and the tenant allows it (below).
Not shipped: the automatic Download click in Teams on the web (the page reads its data with POST requests, which capture's read-only rule stops); the user downloads by hand and ingest does the rest.

## Mail (experimental, opt-in)
- `ING mail probe` checks classic Outlook, reads the policy values, counts the Inbox, reads one subject, then one body in a
  child process with a 20 second timeout. A refusal, a prompt or a timeout is exit 3.
- `ING mail run --experimental --source com [--folders "Inbox,Sent Items"] [--since YYYY-MM-DD] [--max-items N]` reads the
  cached window of classic Outlook, incrementally: one file per conversation under `captured/outlook/<folder>/`. Labelled
  or rights-managed messages keep headers only; attachments are converted only when message and attachment are unlabelled.
- `--source graph` does the same over Microsoft Graph (`Mail.Read`) with the user's own tenant app.

## Graph setup (optional)
`ING config set graph_client_id <app id>` and `ING config set graph_tenant_id <tenant>` (an app registered in the user's own
tenant; a built-in or first-party ID is refused). The first run prints a device code for the user to enter. The sign-in
is cached encrypted for the current Windows user; `ING logout` removes it.

## Digests
After a run, new meeting files and new or changed threads inside `digest_window_days` (14) get one quarantined `claude -p`
call each, at most `digest_max_per_day` (30) a day, never for the first pass over a folder, never for labelled items. The
reply must fit `scripts/digest.schema.json` or it is rejected. The digest is appended under `## Digest (AI)`; the day's
rollup is `<KB>/inbox/<date>-digest.md`. Details: `${CLAUDE_SKILL_DIR}/references/quarantine.md`.

| Goal | Run |
|---|---|
| Acknowledge the InfoSec note | `ING ack-infosec` |
| Process the drop folder | `ING meetings run [--graph] [--no-digest] [--json]` |
| Check classic Outlook | `ING mail probe [--json]` |
| Ingest mail | `ING mail run --experimental --source com\|graph [--folders L] [--since D] [--max-items N] [--no-digest]` |
| Digest one file or the waiting ones | `ING digest PATH` · `ING digest --pending [--max N]` |
| Rebuild a day's rollup | `ING rollup [--date YYYY-MM-DD]` |
| Settings | `ING config get\|set KEY [VALUE]` |
| Remove copies | `ING purge --source meetings\|outlook [--older-than DAYS]` |
| Remove the Graph sign-in | `ING logout` |
| Where things stand | `ING status --json` |

## Reporting back
Say how many files were written, unchanged, skipped (and why), whether the run stopped and where the report is. Never paste
meeting or mail text into a reply unless the user asks. Known limits: `${CLAUDE_SKILL_DIR}/references/asks.md`.
