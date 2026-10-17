# Corporate environment (managed Windows laptop)

Assumed: a managed Windows 11 laptop (Entra ID, Intune) with WSL2; Microsoft 365 with SharePoint
and OneDrive; a TLS-inspecting proxy; GitHub Enterprise; a Claude Team or Enterprise seat that may
carry managed settings. Setup steps (WSL limits, proxy certificates, GitHub sign-in, day-1 checks):
`{{WORKBENCH_HOME}}/instructions/rules/corporate-setup.md`, read on demand. Per component (command, check,
denial step, ask-IT text): `{{WORKBENCH_HOME}}/kit/docs/SETUP-RUNBOOK.md`. Claude Code's red errors: guide 43.

## The machine
- Managed settings win. `/status` names the managed source on `Setting sources`; if it overrides a
  kit setting, ask your admin.
- Claude Code needs no admin rights: run it as the signed-in user.
- **Native Windows has no command sandbox;** WSL2 does (`sandbox.enabled`). Run unfamiliar code (a
  new clone, generated scripts, dependency installs) in WSL2 with the sandbox on.
- **TLS errors behind the proxy:** install the proxy's root certificate (corporate-setup.md).

## OneDrive and SharePoint
- An online-only file downloads when opened. **Never bulk-read, glob or index a synced library of
  online-only files:** it triggers a mass download. Search with the `find` skill, which never
  downloads an online-only file.
- Never bulk move, rename or delete in a synced folder: it syncs to everyone.

## Repos and GitHub
- Open an unfamiliar clone with `claude --setting-sources user`, so its settings files and
  `.mcp.json` don't load until you have read `.claude/`, `CLAUDE.md` and `.mcp.json`.
