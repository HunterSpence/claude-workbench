# Drive a browser from the command line, headless

Automates it: `playwright-cli --help`

## When to use
Claude should open your own web app, click through it and take screenshots, with no window in the way, and without
loading a browser tool's schemas into every session. `<KIT>` is the kit folder (guide 01); `<WB>` is the workbench
folder inside your Claude config folder.

## Steps
1. Setup installs the Playwright CLI (npm package `@playwright/cli`, Apache-2.0) at the version tested for this kit release,
   with install scripts off and no browser download, when Node.js is present: `py -3 <KIT>/bootstrap/setup.py run`.
   Check it: `playwright-cli --version`. Without Node.js the plan shows an ask-IT item for it (guide 03).
2. The browser is the Microsoft Edge already on the laptop, headless. Setup writes `<WB>/state/playwright-cli.config.json`
   (Edge channel, headless) and points the user variable `PLAYWRIGHT_MCP_CONFIG` at it. A variable you already set is kept.
   If IT's Edge policy `HeadlessModeEnabled` is off, the file asks for a visible window instead.
3. Use it from a session by asking Claude, or by hand:
   ```
   playwright-cli open http://localhost:3000
   playwright-cli snapshot
   playwright-cli click e15
   playwright-cli screenshot --filename=page.png
   playwright-cli close
   ```
   Add `--headed` to `open` to watch. Name a session with `-s=name`; `playwright-cli list` and `close-all` manage them.
   A headless session closes itself after an hour without commands.
4. On the corporate profile each shell command prompts unless you allowed it, so read every `playwright-cli` command before
   you approve it, above all three kinds: `upload` and `drop` (a file from this machine goes into the page), `eval` and
   `run-code` (code runs inside the page), and `open`, `goto` or `tab-new` to any address that is not localhost or a loopback
   address. The kit adds no other check around them; approve only what you meant.
5. CLI or MCP: this CLI is the better fit for coding work because a command prints a short result instead of a large page
   tree, and a skill tells Claude how to use it. The `playwright` entry in `<KIT>/mcp/golden-config.template.json`
   (`@playwright/mcp`) is the other route, for long loops that need the page held in memory. It ships off (`ignore`), so
   its tools do not load; set its action to `ensure` in your own copy only when you need that route (guide 26).
6. To remove it: `py -3 <KIT>/bootstrap/setup.py undo-config --apply` runs `npm uninstall -g`, deletes the config file and the
   variable. The skill folder it installed under your home folder stays; delete it by hand.

## Verify
- `playwright-cli --version` prints a version, and `py -3 <KIT>/bootstrap/setup.py report run --phase refresh --quick` shows
  the `pkg-playwright-cli` and `browser-automation` rows as READY.
- `playwright-cli open http://localhost:3000` followed by `playwright-cli screenshot` writes a PNG and shows no window.
- On the corporate profile, open a browser first, then go to an outside page: `playwright-cli open about:blank`, then
  `playwright-cli goto https://example.org`. Claude Code asks for your approval before the `goto` (`open about:blank` needs none).
  Finish with `playwright-cli close`.

## Common failures
- **`browser-automation` is BLOCKED-BY-POLICY:** Edge's `RemoteDebuggingAllowed` policy is off. Send the row's ask-IT text to IT.
- **`The browser 'default' is not open, please run open first` (exit 1):** `goto`, `snapshot`, `click` and the other commands act
  on a browser that is already open. Run `playwright-cli open about:blank` (or `open` with your page's address) first;
  `playwright-cli list` shows what is open.
- **No window appears and you wanted one:** add `--headed`. With `HeadlessModeEnabled` off the config already does.
- **The plan says "needs Node.js":** install Node.js first (guide 01), then run setup again.
- **The npm install is refused (E403 or E407):** a proxy or registry policy; setup records an ask-IT item and does not retry.
- **"No Microsoft Edge was found" in the setup notes:** no config file is written. Install Edge or ask IT which browser is approved.
- **The CLI's skill is missing:** setup installs it only from the tested CLI version. A newer CLI still works; run
  `playwright-cli --help`.
