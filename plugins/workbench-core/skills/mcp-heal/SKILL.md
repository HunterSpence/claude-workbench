---
name: mcp-heal
description: Reconcile the user's MCP servers to their golden config and probe every server for real (stdio initialize handshake, HTTP initialize), then report OK / DEGRADED / DOWN with the fix for each. Use for "/workbench-core:mcp-heal", "an MCP server is broken", "MCP tools missing", "check my MCP servers", or after editing the golden config.
---

# /workbench-core:mcp-heal

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it
> appears unreplaced (the skill was copied in without the plugin), use `py -3` on Windows and
> `python3` on Linux, macOS and WSL, never the Microsoft Store `python` stub.

The healer is `tools/mcp-healer/mcp_healer.py` in the installed kit: `<config dir>/workbench/kit/`
(the config dir is `$CLAUDE_CONFIG_DIR`, else `~/.claude`, which is `%USERPROFILE%\.claude` on
Windows). Below, `<kit>` means that folder; if it is missing, use the unpacked release folder. Its
desired state is a golden file the user owns, started from `<kit>/mcp/golden-config.template.json`. Never hand-edit
`.claude.json` (it holds the sign-in session and per-project state); change the golden file and let
the healer reconcile.

1. Find the golden file. None yet: copy the template, fill the placeholders with the user, and stop
   there if they have not chosen servers.
2. Preview, then apply only with the user's OK:
   ```bash
   "${user_config.python}" <kit>/tools/mcp-healer/mcp_healer.py apply --golden <golden.json> --dry-run
   "${user_config.python}" <kit>/tools/mcp-healer/mcp_healer.py apply --golden <golden.json>
   ```
   Exit code 3 means a managed MCP policy is in force: report the file and key it names and stop.
   Managed settings win; do not work around them.
3. Probe the user's own servers:
   ```bash
   "${user_config.python}" <kit>/tools/mcp-healer/mcp_healer.py check
   ```
   It probes only user-scope servers, each with a minimal environment (OS essentials plus the
   variables named in that server's `env` block), from an empty temporary directory, with the
   command resolved on `PATH` only. A server that needs its repository (a code-graph server) gets
   `--cwd <that repo>`, and only for a repository the user trusts. Managed allow/deny lists are
   honoured: blocked servers show as SKIP. **Never probe a repository's `.mcp.json`**: anyone can
   commit one. `--project <repo>` only lists its server names; Claude Code itself asks before
   trusting project servers.
4. Summarise per server in plain language:
   - **OK**: the server answered `initialize`.
   - **DEGRADED**: slow first start (a package download), or an HTTP server that needs sign-in or a
     key (401/403). Sign in via `/mcp` in Claude Code.
   - **DOWN**: launcher missing (install it or fix the path), exited before the handshake (run its
     command by hand to see the error), or unreachable URL (network, proxy or allowlist).
5. Remind the user that MCP config changes load on the next Claude Code restart.

Rules: never print or `cat` `.claude.json` or any env value; the healer prints names and reasons
only. Package-launched servers are pinned to an exact version, never `@latest`.
A server that sends data to a hosted service stays off unless the user's organisation allows it.
