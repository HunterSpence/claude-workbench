# Browser automation

- **Default: local `playwright-cli`** (or an approved Playwright MCP). Run it visibly when the user
  wants to watch, headless otherwise. Take a fresh snapshot before each click: the page changes
  under you.
- **Don't ship visual work unseen:** preview, verify in the browser, merge, then re-confirm the
  live page.
- **A bot wall, captcha, or 2FA prompt is a stop.** Bring the window on-screen and hand it to the
  user. Never solve, bypass or outsource a human check (Red Line: no circumvention).
- **Never automate sites whose terms forbid it** (most social networks), and never automate
  accounts that hold money, legal or identity status, or admin rights over infrastructure: those
  stay human.
- **Never enter, discover, or store credentials** through browser automation. The user signs in
  and completes SSO or MFA themselves.
