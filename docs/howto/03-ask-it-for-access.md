# Ask IT for access, the right way

Automates it: none (the drafts are in `docs/admin-asks.md`)

## When to use
Setup stops with an "ask IT" item, a capability row says NEEDS-IT or BLOCKED-BY-POLICY, or a hook, plugin
source, model or MCP server is refused on your managed laptop.

## Steps
1. Find the exact block. Setup lists it: `py -3 <KIT>/bootstrap/setup.py status --json` has an `ask_it` list, each
   entry an `item` and a draft `text`. The `.html` capability report shows the same text under the row, and its Roadmap ranks the asks (guide 02).
2. Open `docs/admin-asks.md` and pick the matching text: hooks locked, marketplaces closed, models restricted, MCP
   restricted, permissions locked, a proxy that re-signs HTTPS, WSL2 and virtualization, package sources, git host and sign-in.
3. Fill the `<...>` placeholders. Ask for the smallest thing that unlocks the step, name the exact setting, folder or
   host, and offer the alternative that needs no change ("or I skip this feature").
4. Send it yourself.
5. Keep the answer. When IT acts, refresh: `py -3 <KIT>/bootstrap/report.py run --phase refresh`, then
   `py -3 <KIT>/bootstrap/setup.py run --detach`.

## Verify
- The row moves from NEEDS-IT or BLOCKED-BY-POLICY to INSTALLABLE or READY, and the `ask_it` list shrinks.
- `py -3 <KIT>/plugins/workbench-core/scripts/policy_snapshot.py --json` names a policy class under `changed` when the
  managed policy differs from the saved snapshot.

## Common failures
- **IT says no:** that is the answer. Work without the feature; the kit continues with everything that is not blocked.
- **Tempted to bypass:** never ask for, accept or build a workaround that disables a control, and never retry a
  blocked step by another route, tool or shell.
- **An approval dialog offers "request approval":** do not press it for someone else; it notifies administrators.
- **The ask is vague and gets ignored:** name the setting (for example `allowManagedHooksOnly`) and what you need it for.
