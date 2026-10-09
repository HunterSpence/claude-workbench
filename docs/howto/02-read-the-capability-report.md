# Read the capability report

Automates it: `py -3 <KIT>/bootstrap/report.py run --phase pre`

## When to use
Before you install anything, to see what this machine can do. Again after IT changes a setting, to see what unlocked.
`<KIT>` is the kit folder (guide 01).

## Steps
1. Run the report (add `--quick` to skip the network, the speed bench and the model call; it then takes under 20 seconds):
   `py -3 <KIT>/bootstrap/report.py run --phase pre`
2. It prints a short summary and writes `capability-pre.md`, `.json` and `.html` into `<WB>/state/`. Open the `.html`
   or `.md`: Machine, Features, Security posture, Dev speed and Roadmap.
3. In the Features table read the status of each row, with the reason beside it:
   - **READY**: works now.
   - **INSTALLABLE**: setup can install it without help.
   - **NEEDS-IT**: someone with admin rights must allow it.
   - **BLOCKED-BY-POLICY**: your organisation's policy forbids it today.
   - **UNKNOWN**: the probe could not tell; read the row's evidence.
4. Read the Roadmap at the end: a ranked list of asks, each with the features it unlocks. In the `.html`, every NEEDS-IT and
   BLOCKED-BY-POLICY row shows a ready-to-send "Ask IT" text (guide 03).
5. After setup, or after IT answers, run it again and compare:
   ```
   py -3 <KIT>/bootstrap/report.py run --phase post
   py -3 <KIT>/bootstrap/report.py diff <old>.json <new>.json
   ```
   `post` also writes `capability-diff.md` against `capability-pre.json`.

## Verify
- The three `capability-pre` files exist and the Features section starts with a count per status.
- After an IT change, `capability-diff.md` shows the row that moved, for example NEEDS-IT to READY.

## Common failures
- **Many UNKNOWN rows:** you used `--quick`, or a section could not be read. Run without `--quick`.
- **Network rows blocked or `proxy-auth`:** a proxy sits in the way. See guide 04.
- **The report takes long:** add `--detach` and keep working; it writes the same files when done.
- **A row says BLOCKED-BY-POLICY for something you need:** send its ask text. A refusal is a decision; do not look
  for a way round it.
