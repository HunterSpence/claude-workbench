# Browser automation

- **Default: local `playwright-cli`** (or a Playwright MCP). Run it visibly when the user
  wants to watch, headless otherwise. On a managed laptop it drives the installed Edge, headless; prefer
  the CLI to the Playwright MCP server, which ships off (guide 45). Take a fresh snapshot before each click: the page changes
  under you.
- **Parallel browser work:** give each agent its own named session or profile. In a shared default
  session, another agent's page silently becomes yours.
- **Don't ship visual work unseen:** preview, verify in the browser, merge, then re-confirm the
  live page.
- **A captcha, sign-in or 2FA prompt needs the user:** bring the window on-screen and hand it over.
  The user signs in and completes SSO or MFA themselves.
- A remote desktop drawn into an HTML canvas (Citrix, Horizon or Azure Virtual Desktop web
  clients, noVNC, Guacamole): the `vdi-drive` skill, user-invoked only.
