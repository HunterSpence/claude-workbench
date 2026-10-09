# mcp-healer

Keeps your user-scope MCP servers matching a golden file you own, and probes each one for real.
Run it through the `mcp-heal` skill, or directly:

`python` below means your Python 3.10+: `py -3` on Windows, `python3` on Linux, macOS and WSL.

```bash
python mcp_healer.py apply --golden <golden.json> --dry-run   # plan only
python mcp_healer.py apply --golden <golden.json>             # timestamped backup, validated atomic write
python mcp_healer.py unpark <name>                            # bring a parked server back
python mcp_healer.py check [--json] [--cwd <dir>]             # initialize-handshake your user-scope servers
python mcp_healer.py check --project <repo>                    # also LIST (never launch) <repo>/.mcp.json
```

- Start the golden file from `mcp/golden-config.template.json`. Actions: `ensure` (rebuild from the
  golden entry, or `preserveExisting` to keep the live entry and apply `setEnv`), `park` (move to
  `mcpServersParked`, which Claude Code ignores), `remove`, `ignore`. Unlisted servers are untouched.
- Secrets: keep them in your environment (servers inherit it, and `${VAR}` / `${VAR:-default}`
  expand in `command`, `args`, `env`, `url`, `headers`), or keep an existing value with
  `{"fromExisting": "VAR"}`. The tool prints server names and reasons, never values.
- An `ensure` entry is written as is, including `headersHelper` and `oauth` (Claude Code runs the helper and does the
  sign-in; this tool does neither). It is refused, with the reason printed, while a `{{PLACEHOLDER}}` is left anywhere in
  it (command, args, url, headers or helper) or a `${VAR}` without a default names a variable that is not set in the
  environment you ran the tool from. Set the variable and run it again.
- Managed MCP policy present (file-based managed settings or `managed-mcp.json`): `apply` refuses to
  write (exit 3) and names the policy.
- `.claude.json` location: `$CLAUDE_CONFIG_DIR/.claude.json` when that variable is set, else
  `~/.claude.json`; override with `--config`.
- `check` probes only servers in your own user-scope config. A repository's `.mcp.json` is never
  launched, fetched or `${VAR}`-expanded; `--project` lists its server names and nothing more.
- Stdio probes start with a minimal environment (`PATH`, `PATHEXT`, `SYSTEMROOT`, `WINDIR`,
  `COMSPEC`, `TEMP`, `TMP`, `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, plus the variables
  named in that server's own `env` block), in an empty temporary directory unless `--cwd` names one
  (cwd-sensitive servers such as a code-graph server need their repo), and the command is resolved
  on `PATH` only, never from the current directory. A server that needs a proxy variable to start
  must name it in its `env` block.
- Servers that managed `allowedMcpServers` / `deniedMcpServers` would block are reported as SKIP
  and never launched.
- A server with a `headersHelper` is reported as SKIP: a helper is a command, and `check` never runs one (use `/mcp`
  inside Claude Code). It also never signs in for you.
- HTTP servers get an `initialize` POST. Exit 1 if anything is DOWN. With no `.claude.json` yet, `check` says
  "no config yet" and exits 0 (`--json` prints `[]`); `apply` and `unpark` say the same and exit 1. No scheduling, no alerts, no
  network calls except the probes you run.

Tests: `python -m unittest discover -s tools/mcp-healer/tests`.
