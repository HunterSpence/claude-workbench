---
name: ui-build
description: Build or change a web UI the careful way - find the design system first (tokens, components, CSS variables), make the change with it, run the app locally, screenshot at 1440px and 390px in light and dark, run an accessibility check, look at every screenshot, fix, re-shoot, and keep before/after pairs for the PR. Use for "build this page", "redesign this screen", "fix the layout", "make it responsive", "add dark mode", "polish the UI", or any frontend or design change to a product UI or an internal web app.
---

# ui-build

The loop is: **find the system, change, run, shoot, look, fix, re-shoot.** A UI change nobody looked
at is not done; a green build says nothing about how it looks.

## 1. Find the design system before writing any style
Search the repo, in this order, and write down what you find:
- **Tokens:** CSS custom properties (`--color-`, `--space-`, `--radius-`, `--font-`), theme files
  (`theme.ts`, `tokens.json`, `*.tokens.*`), `tailwind.config.*` / `@theme` blocks, SCSS variables.
- **Components:** the shared component folder or package (`components/ui`, `@<org>/design-system`,
  a Storybook), and how existing screens import them.
- **Patterns:** a page that already does something similar; copy its structure.
- **Dark mode:** how it is switched (`prefers-color-scheme`, a `data-theme` or `.dark` class).

Use tokens and existing components. Never hard-code a colour, spacing value, radius or font that a
token covers, and never add a UI library the project does not already use without asking. If the
repo has no system, keep values in one place (a small set of CSS variables) rather than scattered.

## 2. Make the change
Small, reviewable steps. Semantic HTML first (`button`, `nav`, `main`, `label` tied to inputs,
headings in order). Every state: loading, empty, error, long text, many items, no permission.
Keyboard: everything reachable with Tab, visible focus, Escape closes overlays.

## 3. Run it locally
Use the project's own command (`npm run dev`, `pnpm dev`, `npm run storybook`, `make run`; check
`package.json` scripts and the README). Run it in the background and note the local URL. If it needs
secrets or a backend you do not have, ask the user; do not point it at a shared or production
environment.

## 4. Screenshot and check
Setup once, in a working folder outside the repo:
```bash
cp -r "${CLAUDE_SKILL_DIR}/scripts" ./ui-shots && cd ui-shots && npm install --ignore-scripts   # playwright-core + axe-core, no browser download
```
Then, before you change anything and again after:
```bash
node shoot.mjs http://localhost:3000/settings --out ../shots --label before   # later: --label after
```
- Shoots 1440px and 390px wide, light and dark (dark is dropped when the page ignores
  `prefers-color-scheme`); `--widths`, `--schemes`, `--full-page`, `--wait-for <selector>` adjust it.
  For an app whose dark mode is a class or attribute, add a query parameter or a story that sets it.
- Uses the installed Edge or Chrome headless (`UI_BROWSER` overrides). Only the local app is
  reachable: every other request (CDNs, fonts, analytics, APIs elsewhere) is blocked and listed in
  `<label>-summary.json`, so nothing leaves the machine. The block holds twice over: a request
  filter, and below it a proxy to nowhere that only loopback bypasses, with no DNS for other names
  and no WebRTC around the proxy. Redirect chains that leave the local app are listed under
  `redirects`, and service workers cannot register. `--allow-fonts` lets Google Fonts through
  (`fonts.googleapis.com` and `fonts.gstatic.com`, nothing else) when the design depends on them and
  your organisation allows it. If the page needs anything else to render, tell the user rather than
  unblocking it.
- Checks horizontal overflow at each width (`document.documentElement.scrollWidth` wider than the
  viewport) and names the elements that cause it; the CLI prints an `OVERFLOW` line. At phone width
  this is a defect to fix, not a note.
- Runs axe-core on each width and prints the violations; without axe-core it writes Playwright's
  ARIA snapshot instead. Console errors are recorded too.
- If `playwright-cli` is installed (see `THIRD-PARTY.md`), you can use it for interactive checks
  (click through a flow, hover states) against the same local URL.

## 5. Look, fix, re-shoot
Read **every** PNG. For each one write the defects: overflow (fix every `OVERFLOW` line) and clipping, overlap, misaligned edges,
inconsistent spacing, text too small (under 14px body on mobile), contrast, touch targets under
about 44px on 390px, broken dark mode (unreadable text, hard-coded white), focus not visible, empty
or error states missing. Fix all axe violations of impact serious or critical; list the rest. Then
re-shoot and re-read the changed views. Stop after a round that finds nothing, at most three rounds.

## 6. Hand over
Keep the `before-*` and `after-*` pairs. `node shoot.mjs pairs ../shots` prints a Markdown table
for the PR description. Do not commit screenshots unless the repo already keeps them. Report what
you checked, the widths and schemes, the a11y result, and anything you could not check.

## Optional design skills
`impeccable`, gstack's `design-review` and `qa`, and `web-design-guidelines` add critique and polish
passes. They are not installed by default (runtime downloads and local telemetry; see
`THIRD-PARTY.md`); `tools/fetch-upstream` installs them with `--optional` after your organisation
approves.
