# Capture intranet pages

Automates it: /workbench-capture:capture

## When to use
You want the handbook, wiki or policy pages on your company intranet searchable next to your documents, so you can ask
Claude "what does the travel policy say?" and get a cited answer. Capture opens only the addresses you list, in its own
Edge profile, at a human pace, read-only, and saves Markdown copies. It is opt-in. `<KIT>` is the kit folder (guide 01).
Below, `CAP` means: run `capture.mjs` from the `<WB>/capture/app/` folder with node.

## Steps
1. Install the capture add-on if it is missing: `py -3 <KIT>/bootstrap/setup.py run --detach --with capture`. Your
   organisation must not have turned off the Edge policy `RemoteDebuggingAllowed` for this device; if it has, capture
   stops with an ask for IT (guide 03) and does nothing else.
2. Set the scope. Your own sites come first; the deny list holds what to skip:
   ```
   CAP scope set tenant example.com
   CAP scope add --source intranet https://intranet.example.com/handbook/
   CAP scope add --deny --source intranet /handbook/people/
   CAP scope list
   ```
3. Sign in once. `CAP login` opens a window; you sign in, including any second step, and close it. Capture never signs in for you.
4. Try small, then full: `CAP run --source intranet --dry-run` lists what it would read; then
   `CAP run --source intranet --max-per-hour 30`; then `CAP run --source intranet`.
5. Refresh the index (guide 29) so the copies are searchable.

Hard stop rule: exit code 3 means capture stopped on purpose (a sign-in, consent, policy or block page, the hourly cap, a
non-GET request). Report `stop.kind`, `stop.reason` and `stop.ask` from the run report word for word. `docs/admin-asks.md`
has the ask for IT.

Not in this release: the Teams and Outlook-on-the-web sources. Those web apps read their data with POST requests, and capture blocks every non-GET request.

## Verify
- The report `<WB>/capture/runs/<UTC stamp>.json` lists every address read, a hash and an expiry; `CAP status` shows scope and the last run.
- Files exist under `<DATA>/captured/intranet/`, and a search with `--source intranet` finds a phrase from one page.

## Common failures
- **Exit 3, sign-in page again:** the session expired. Run `CAP login` yourself, then rerun.
- **Exit 3, hourly cap:** the pace is at most 10 actions a minute and 200 an hour. Wait and run again; the cap can be lowered, never raised.
- **Pages missing from the result:** a page with a sensitivity-label badge is skipped and named in the report; `robots.txt` rules, depth 2 and 50 pages per run also apply.
- **Old copies pile up:** each report entry has an `expires` date (capture time plus `retention_days`, 90 by default; `CAP scope set retention_days <n>` changes it). Remove copies on demand with guide 32.
