# Browser automation

- **Default: local `playwright-cli`** (or an approved Playwright MCP). Run it visibly when the user
  wants to watch, headless otherwise. Take a fresh snapshot before each click: the page changes
  under you.
- **Parallel browser work:** give each agent its own named session or profile. In a shared default
  session, another agent's page silently becomes yours.
- **Don't ship visual work unseen:** preview, verify in the browser, merge, then re-confirm the
  live page.
- **A bot wall, captcha, or 2FA prompt is a stop.** Bring the window on-screen and hand it to the
  user. Never solve, bypass or outsource a human check (Red Line: no circumvention).
- **Never automate sites whose terms forbid it** (most social networks), and never automate
  accounts that hold money, legal or identity status, or admin rights over infrastructure: those
  stay human.
- A remote desktop drawn into an HTML canvas (Citrix, Horizon or Azure Virtual Desktop web
  clients, noVNC, Guacamole): the `vdi-drive` skill, user-invoked only. It needs the desktop
  owner's written authorisation and a local authorisation note; never enter, discover or store
  credentials through it.
- **Never enter, discover, or store credentials** through browser automation. The user signs in
  and completes SSO or MFA themselves.
