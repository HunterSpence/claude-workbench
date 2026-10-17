# When a policy blocks you

Automates it: none (the asks are in `docs/admin-asks.md`)

## When to use
A hook refuses a command, a permission prompt will not allow something, a proxy or gateway answers 403, a model or plugin
source is not allowed, setup says STOP, or capture or ingest ends with exit code 3. `<KIT>` is the kit folder (guide 01).

## Steps
1. Stop that step. Retrying it through another tool, shell or route meets the same block. Do not press "request
   approval" for someone else: it notifies administrators.
2. Copy the message word for word, with its rule name, setting name and file. For capture and ingest, copy `stop.kind`,
   `stop.reason` and `stop.ask` from the newest run report in `<WB>/capture/runs/`.
3. Name the class of block. In Claude Code, `/status` lists the managed settings source. Then:
   ```
   py -3 <KIT>/plugins/workbench-core/scripts/policy_snapshot.py --json
   py -3 <KIT>/bootstrap/report.py run --phase refresh --quick
   ```
   The first shows which classes of managed policy apply and whether they changed. The second marks the matching capability row NEEDS-IT or BLOCKED-BY-POLICY.
4. Open `docs/admin-asks.md` and take the matching text: hooks locked, marketplaces closed, models restricted, MCP restricted,
   permissions locked, a proxy that re-signs HTTPS, WSL and virtualization, package sources, git host and sign-in. Fill the
   placeholders, ask for the smallest thing that unlocks the step, offer the no-change alternative, and send it yourself (guide 03).
5. Carry on with the work that is not blocked, and tell whoever is waiting which part is held and why.
6. Keep the answer. When IT acts, refresh the report and run setup again.


## Verify
- Your ask quotes the block exactly and names one setting, folder or host.
- After IT acts, the capability row moves to INSTALLABLE or READY, and `policy_snapshot.py --json` names the class under `changed` whenever the managed policy differs from the saved snapshot.

## Common failures
- **Same block, different tool:** it is the same denial.
- **IT says no:** that is the answer. The kit continues with everything not blocked (guide 03).
- **The block hides a real fault:** if the message looks wrong (a rule that cannot apply), report that too; do not fix it yourself.
