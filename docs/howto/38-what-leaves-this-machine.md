# What leaves this machine

Automates it: none (a reading guide for you and your security team)

## When to use
Your manager, a customer or your security team asks "where does our data go when you use Claude and this kit, and what is
sent to the cloud?", or you want to know before you give it a document, turn on a connector or switch on capture. `<KIT>` is the kit folder (guide 01).

## Steps
1. Start from the plain rule: whatever Claude reads or you type in a session (prompts, file contents it opens, command
   output, tool results) goes to the model service your organisation approved, under your Claude seat. "Local" tools do not
   change that for text you hand to Claude.
2. Know what stays on this machine. The `find` index is one local file with a full-text copy of what it read; no search sends
   anything. The first full index downloads one small embedding model (a download, not an upload). The capability report
   and probe read your settings and test whether hosts answer; the results stay in your profile.
3. Know what capture and ingest do. They read only the addresses, folders and mailboxes you listed, at a human pace, and save
   copies on this machine or in your work OneDrive, where your organisation's retention, DLP and eDiscovery rules apply. AI
   digests of meetings and mail go to the model service through your own sign-in; transcripts can hold the speech of people
   outside your organisation. The note to give your security team is `bootstrap/infosec-note.txt`.
4. Check each MCP server before enabling it. The `egress` column in `mcp/README.md` (and the `egress` field of each entry in
   `<KIT>/mcp/golden-config.template.json`) says whether it is local or hosted. Hosted servers send your queries to a third
   party: never put code, internal names, customer data or secrets in a query (guide 26).
5. Know the outbound guard. Publishing and uploading commands ask you first, and a push to a git host not on your list is
   refused; the hosts your organisation approves go in `<KIT>/plugins/workbench-core/scripts/guards/corporate-allowlist.template.json`
   (guide 20). The guard reads shell commands; it is a safety net, not a firewall.
6. The hosts setup downloads from are the `hosts` entries in `<KIT>/bootstrap/packages.json`: package sources and vendor release pages.

Hard stop rule: any hook, permission, gateway or policy denial means stop and report it word for word; never retry another
way. `docs/admin-asks.md` has the asks. See also docs/security-overview.md.

## Verify
- For any task you can say which of three it is: model service only, local only, or a named third-party hosted server.
- `claude mcp get <name>` shows a `${...}` reference, never a value, and `py -3 <KIT>/tools/mcp-healer/mcp_healer.py check` lists the servers you actually run.

## Common failures
- **"It is local, so it is not sent":** true for the index, false for anything Claude reads.
- **A hosted connector enabled without asking:** its data route needs your security team's agreement, not just a working sign-in.
- **A personal account, cloud drive or tool on the managed laptop:** never; work data stays in places your organisation approved.
- **A secret in a prompt or file:** treat it as exposed and follow guide 40.
