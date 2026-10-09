# Before the first full run: tell the team that watches bulk access

Capture reads pages and files you can already open, at a human pace. A monitoring team may still see an automated
browser, a run of page loads or a run of file reads and raise an alert. Telling them first is cheap and avoids a
needless incident. Do this before the first full run, not after the first alert.

## Checklist
1. Read `guardrails.md` so you can answer questions about what capture does and does not do.
2. Decide the scope: your own sites and the files shared with you first; list anything sensitive in the deny list.
3. Check that your organisation allows local automation of Edge for you: the policies `RemoteDebuggingAllowed` and
   `HeadlessModeEnabled` must not be turned off for this device (headless can be off; remote debugging cannot).
4. Send the heads-up text below to the security or monitoring team and wait for a reply or an agreed date.
5. Pick where copies live: the data folder (possibly your work OneDrive, under its retention and DLP rules) or this
   machine only (`scope set placement.<source> local`).
6. Do a `--dry-run` first, then a small real run (`--max-per-hour 30`), then the full run.
7. Keep the run reports (`<WB>/capture/runs/`): they list every address or file, a hash, and an expiry.
8. Know how to stop and undo: close the window, `capture purge`, `capture logout`.

## Heads-up text (edit the brackets)
Subject: Heads-up: I am starting a read-only local index of my own work pages and files

Hello [team],

From [date] I will run a small tool on my managed laptop that reads pages and files I can already open and saves
read-only Markdown copies for local search. I am telling you first so a pattern of page loads is not mistaken for
something else.

- What: [intranet start URLs, and the folders of my OneDrive sync folder that I listed]. A sensitivity-labelled page or
  file is skipped. Nothing is written back: the tool refuses any write, and aborts any request that is not a read.
- How: Microsoft Edge started by the tool with its own profile folder, signed in by me once. No cookies, tokens or
  stored sign-in state are read or copied. If a sign-in, consent, policy or block page appears, the tool stops and does
  not retry.
- Pace: at most 10 page loads or file reads a minute and 200 an hour, with random pauses. The first run is a small one.
- Where the copies live: [this laptop only / my work OneDrive data folder, under the organisation's retention and DLP
  rules]. I can delete them at any time with one command.
- When: [dates and times]. Please tell me if you would like a different window, a lower rate or a different scope, or
  if any of this is not allowed on this device.

Thanks,
[name]

## If an alert fires anyway
Stop the run (close the window), keep the newest report from `<WB>/capture/runs/`, and send it to the team with the
time. The report shows exactly what was read and at what pace.
