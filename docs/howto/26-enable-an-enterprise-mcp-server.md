# Enable an enterprise MCP server

Automates it: /workbench-core:mcp-heal

## When to use
You want Claude to read from a service your organisation already runs (Azure, Azure DevOps, Jira and Confluence, BigQuery,
Microsoft documentation, a read-only database, and so on) through a ready-made MCP server, not one you write. Every
catalog entry ships off. `<KIT>` is the kit folder (guide 01); the catalog and each server's data route are in `mcp/README.md`.

## Steps
1. Read the entry in `mcp/README.md` first. Its `egress` column says where your data goes: a hosted server sends every
   query to a third party (guide 38). Check with the data owner and your security team before turning one on.
2. Check your organisation's policy. Managed settings can allow, deny or fix the MCP list, and they always win. If a server
   is not allowed, the ask is "MCP restricted" in `docs/admin-asks.md`: name the server, an exact version, read-only mode,
   and where it starts from. You send it (guide 03).
3. Copy `<KIT>/mcp/golden-config.template.json` to a file you own. In the entry you want, change `"action": "ignore"` to
   `"ensure"` and fill every `{{PLACEHOLDER}}`. Keys are `${VAR}` references; put the values in your environment or the
   operating system's credential store, never in this file.
4. Sign in where the server uses your own login (for Azure, `az login` first). Then preview and apply:
   ```
   py -3 <KIT>/tools/mcp-healer/mcp_healer.py apply --golden <your-golden.json> --dry-run
   py -3 <KIT>/tools/mcp-healer/mcp_healer.py apply --golden <your-golden.json>
   ```
   Or ask Claude to run `/workbench-core:mcp-heal`. Restart Claude Code; MCP changes load on the next start.
5. Probe it for real, then sign in to hosted servers from inside Claude Code with `/mcp`:
   ```
   py -3 <KIT>/tools/mcp-healer/mcp_healer.py check
   ```

## Verify
- `check` prints OK for the server: it answered an initialize handshake. DEGRADED means slow first start or a sign-in or key is still needed.
- `claude mcp get <name>` shows the `${...}` reference, never a value.
- The server's tools appear in Claude Code only after the restart; ask it one read-only question.

## Common failures
- **`apply` exits 3 and names the policy:** a managed MCP policy is in force. That is a stop, not an obstacle: report it word for word, use the ask in step 2, and do not hand-edit `.claude.json`.
- **Refused while a placeholder or variable is unset:** the healer names which one. Set it and run again.
- **DOWN, launcher missing:** install Node.js or `uv` (setup does, guide 01), or run the server's command by hand to read its error.
- **SKIP:** a managed deny list or a `headersHelper` command; `check` never runs one. Use `/mcp` inside Claude Code.
- **Transcripts or mail answer 403:** the tenant has not allowed it. See guide 41.
