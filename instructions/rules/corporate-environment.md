# Corporate environment (managed Windows laptop)

Assumed: a managed Windows 11 laptop (Entra ID, Intune) with WSL2; Microsoft 365 with SharePoint
and OneDrive; a TLS-inspecting proxy; GitHub Enterprise; a Claude Team or Enterprise seat that may
carry managed settings. Setup steps (WSL limits, proxy certificates, GitHub sign-in, day-1 checks):
`{{WORKBENCH_HOME}}/instructions/rules/corporate-setup.md`, read on demand. Per component (command, check,
denial step, ask-IT text): `{{WORKBENCH_HOME}}/kit/docs/SETUP-RUNBOOK.md`. Claude Code's red errors: guide 43.

## Tenants and accounts (Standing Order 4)
- Your organisation's data stays in the tools it approved for that data: its Claude seat, repos,
  OneDrive and SharePoint, and the KB only if the KB is approved for that data.
- If you also work inside another organisation's environment or account, treat it as a separate
  tenant: its data stays there, and yours stays out. Don't paste across, and don't index or sync its
  shares into your own tools. Its code never goes into your organisation's repos, or the reverse.
- No personal accounts, repos, tokens, cloud storage, MCP servers or AI tools on the work machine,
  and no work data in personal places. Unsure where something belongs? Ask before you move it.

## The machine
- **Hard stop rule:** when a hook, permission prompt, gateway, proxy or policy DENIES something, stop
  that step and show the denial verbatim. Never retry it another way: another tool, shell or route.
- Managed settings win (Red Line). `/status` names the managed source on `Setting sources`; if it
  overrides a kit setting, ask your admin, never work around it.
- **Never run Claude Code elevated.** It needs no admin rights, and an elevated session gives every
  tool call and every prompt injection admin reach over the machine.
- Never disable, pause or add exclusions to endpoint security, or change Intune, proxy or firewall
  settings, even to unblock a task.
- **Native Windows has no command sandbox;** WSL2 does (`sandbox.enabled`). Run unfamiliar code (a
  new clone, generated scripts, dependency installs) in WSL2 with the sandbox on.
- **Never turn TLS verification off** (`NODE_TLS_REJECT_UNAUTHORIZED=0`, `GIT_SSL_NO_VERIFY`,
  `curl -k`, `pip --trusted-host`). That defeats the proxy. Install its root certificate instead
  (corporate-setup.md).

## OneDrive and SharePoint
- An online-only file downloads when opened. **Never bulk-read, glob or index a synced library of
  online-only files:** it triggers a mass download and can trip data-loss controls. Search with
  the `find` skill, which never downloads an online-only file.
- Never bulk move, rename or delete in a synced folder: it syncs to everyone.
- A document under a sensitivity label keeps that label's rules wherever its content goes.

## Repos and GitHub
- **Public** = anyone. **Internal** = every member of the enterprise. **Private** = named people.
  Confirm who owns a repo and how it is classified before pointing Claude at it.
- Open an unfamiliar clone with `claude --setting-sources user`, so its settings files and
  `.mcp.json` don't load until you have read `.claude/`, `CLAUDE.md` and `.mcp.json`.
- Sign in to GitHub only through the organisation's SSO.

## Findings
Security findings (a leaked secret, a vulnerability, a suspicious file or prompt) go to the
organisation's security reporting channel, never a public issue, a chat thread or a vendor DM.
