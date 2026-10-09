# Run the doctor and keep a tested backup

Automates it: `py -3 <KIT>/bootstrap/setup.py doctor`

## When to use
Something feels off after an update, IT changed a policy, a session warns that guards have not run lately, or you want a
backup you have actually restored once. `<KIT>` is the kit folder (guide 01).

## Steps
1. Run the doctor. Exit code 0 is OK, 1 warnings, 2 errors:
   `py -3 <KIT>/bootstrap/setup.py doctor`
   Each line is a check: capability report, TLS and network, guard heartbeat, MCP servers, knowledge index, backup age,
   managed policy, setup state, and placement (config folder, knowledge index and git repositories must stay out of OneDrive).
2. To check the knowledge layer as well, run the deep doctor. It is a superset: it first runs the Day-1 knowledge checks
   (the knowledge base is seeded, its state folder works, search and the link graph meet their bar, `find` answers a
   how-to question, the hooks behave, the kit's own tools pass their self-tests, and more), each in a sandbox so your notes
   and index are not touched, then every doctor row above:
   `py -3 <KIT>/bootstrap/setup.py doctor --deep`
   Its exit code is 2 when any row is FAIL and 0 otherwise: a warning never makes it nonzero (the plain doctor exits 1 on a
   warning). The checks appear as rows named `knowledge: <name>`, and the full result is in `<WB>/state/knowledge-verify.json`
   (`<WB>` is the workbench folder inside your Claude config folder). Add `--json` for a script. It takes longer than the plain
   doctor.
3. For IT or a bug report, add a redacted bundle (no notes, no tokens):
   `py -3 <KIT>/bootstrap/setup.py doctor --bundle support.zip`
4. Make a backup (knowledge-base notes and the journal, your profile and rules, workbench config; settings are included
   redacted, as reference):
   `py -3 <KIT>/bootstrap/setup.py backup`
   The zip goes to `<DATA>/backup/` unless you pass `--out <zip>`. Weekly is enough, and the nightly task does it for you:
   `py -3 <KIT>/bootstrap/setup.py backup --if-older-days 7` writes nothing while the newest backup is younger than that.
   The machine-local state in `<WB>/kb-state/` is not in the zip: it holds locks, flags and recovery snapshots, not your notes.
5. Prove it restores, the restore drill. Restore into an empty scratch folder, which writes only there:
   `py -3 <KIT>/bootstrap/setup.py restore <zip> --to <empty folder>`
   Without `--to` or `--apply` it is a dry run that lists what it would restore. The deep doctor runs the same drill on your
   newest backup in a temporary folder (row `knowledge: backup`); run it by hand to see what a restore would write.
6. For a real restore use `--apply`. It skips files newer than the backup unless you add `--force`, and settings files only with
   `--restore-settings`, after printing each hook command in them for you to read.
7. To check servers only: `py -3 <KIT>/tools/mcp-healer/mcp_healer.py check`

## Verify
- The doctor lists every check above and exits 0 or 1. The deep doctor exits 0 with no FAIL row (warnings are allowed).
- The restore drill prints "N file(s) verified" with N equal to the files you expect, and the scratch folder holds them.
- The "backup" row reads OK (within 7 days).

## Common failures
- **The deep doctor exits 2:** read the rows marked FAIL. A doctor row (placement, guard heartbeat) is handled below. A
  `knowledge: <name>` row names the check, and its detail says what failed: `kb-machinery` means the knowledge base's own
  unit tests failed on this machine (`py -3 -m unittest discover -s <KIT>/plugins/workbench-kb/tests` shows which);
  `kb-retrieval` or `kb-graph` mean search or the link graph fell below the bar fixed in advance; `find-keyword` means a
  how-to question no longer finds its guide; `hooks` means a hook script misbehaved in its sandbox; `record` means the
  state folder is not writable; `kit-tools` means a kit tool failed its own `--self-test`. Fix it, then run the deep doctor
  again.
- **A `knowledge:` row is WARN and carries an ask-IT text:** that check needs something IT controls (a model download, an MCP
  allow list, a browser policy). Send the text (guide 03); the exit code stays 0. A check that timed out is also a WARN:
  run the deep doctor again.
- **FAIL on a placement row:** a folder is inside OneDrive. Move it out; databases and git repositories corrupt there.
- **WARN "guard heartbeat":** the guards have not fired recently. Start Claude Code, run any tool, run the doctor again;
  if it persists, hooks may be locked (guide 03).
- **ERROR hash mismatch or unsafe path in a backup:** nothing is restored. Take a fresh backup; do not edit the zip.
- **"never backed up":** run step 4. Keep the zip where your organisation allows, not on a personal cloud drive.
