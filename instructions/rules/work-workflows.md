# Work workflows (read on demand; not imported)

Read the section that matches the task before you start. Each lists the skills, the steps, and what
"done" means. The rules in CLAUDE.md and `rules/*.md` still bind; this file only orders the work.
A skill that isn't installed: say so and follow the steps without it.

## 1. Fixing and reviewing repos
**Skills:** `repo-fix`, `github`, `cascade`, `ratchet`, `investigate`, the built-in `/code-review` and
`/security-review`, `adamsreview` (local diff unless the PR's author asked).
1. Clone into a scratch folder outside OneDrive. Open an unfamiliar clone with
   `claude --setting-sources user` until you have read its `.claude/`, `CLAUDE.md` and `.mcp.json`.
2. Read the README, the CI config, the contributing guide, the PR template, `CODEOWNERS` and the
   tests before touching code. Find how the repo builds, lints and tests itself.
3. Reproduce the problem first. No reproduction, no fix: report what you tried.
4. One branch per fix, off the default branch. Never push to the default branch.
5. Write a test that fails before the fix, then the smallest diff that makes it pass (`ratchet`
   when there are several defects). Fix the shared function, not each caller.
6. Run the repo's own linters, type checks and tests locally. Read exit codes directly.
7. Draft the PR description in the repo's template: what changed, why, how it was tested
   (commands and results), and the risk. Request review from the code owners; don't merge a shared
   repo yourself.
- **Reviewing someone else's code:** findings go to the author privately first, as file:line with a
  proposed change and the reason. Post on their PR only when they or the user asked for it.
  Security findings go through the organisation's reporting channel, never a PR comment.
- **Done:** the failing test now passes, the repo's own checks pass locally, the branch is pushed
  to an approved remote, and the PR description is drafted for the user (or the PR is open if the
  user asked).

## 2. Writing new code
**Skills:** `cascade` (diagnose, plan, implement, verify), `spawn`, `red-team` and `blue-verify`
for anything big, `/code-review`.
1. Research first: how this repo already solves similar problems (helpers, patterns, naming), and
   the current docs for every library you'll call. Note the date of what you read.
2. Plan with a definition of done before the first edit. Say what is genuinely novel.
3. Build in small steps, each with a test. Reuse before writing; no new dependency without a reason
   and the organisation's approval.
4. Big or risky work gets a red/blue pass: `red-team` attacks the design or diff, `blue-verify`
   gates it.
- **Done:** the behaviour works end to end (run it, don't infer it), tests cover the new logic, CI
  is green, and the PR description says how it was verified.

## 3. Designing and building UIs
**Skills:** `ui-build` (visual QA loop), the `frontend-design` plugin, `playwright-cli`. Optional
design skills: `tools/fetch-upstream --optional`, after approval (`THIRD-PARTY.md`).
1. Find the existing design system first: tokens (colour, type, spacing), components, brand rules
   and any UI guidelines. Use them; never invent a parallel set.
2. Use real or realistic content, never lorem ipsum. Cover empty, loading, error and long-text
   states.
3. Accessibility: text contrast at least 4.5:1, every control reachable and usable by keyboard,
   visible focus, labels on every input, alt text, no meaning carried by colour alone.
4. Responsive down to phone width (about 360-390 px) with no horizontal scroll. Support light and
   dark if the app does.
5. Render it and look: screenshots at desktop and phone widths through `playwright-cli`. Fix what
   you see, then shoot again.
6. Put before and after screenshots in the PR.
- **Done:** it matches the design system, passes the accessibility checks above, looks right at
  both widths in screenshots you actually viewed, and the PR shows before and after.

## 4. Spreadsheets, decks and documents
**Skills:** `office-xlsx`, `office-pptx`, `office-docx` (Word), `office-render` (render and check).
1. Start from the organisation's template when one exists: its theme, fonts, logo and layouts.
2. Spreadsheets: formulas, not pasted values; inputs separated from calculations; one consistent
   style for headers, numbers, dates and currency; named sheets; no hard-coded totals.
3. Decks: one message per slide, the title states it; consistent layout; nothing overlaps or runs
   off the slide; sources on data slides.
4. Render every page or slide with `office-render` and look at each one. Fix, render again.
5. Google Sheets or Slides, LibreOffice and similar tools: build the same file formats (.xlsx,
   .pptx, .docx) and import them.
- **Done:** every page or slide rendered and checked, formulas recalculate, and the file opens
  cleanly in the target app.

## 5. Drafting replies (email, chat)
**Skills:** `draft-reply`, `humanizer`.
1. Always a draft. The user sends. Never send, schedule or reply-all unless the user asks for that
   specific action.
2. Read the whole thread first. Answer what was asked.
3. Write in the user's voice: short and direct, the answer first, then any asks, each with an owner
   and a date. No filler.
4. Quote only what you reply to, under the thread's own quote header.
5. Email gets two versions, plain text and HTML, in the style USER.md describes under "How I write"
   (default: plain paragraphs and the user's signature). If you build the draft as a file, set
   `In-Reply-To` and `References` so it threads.
6. Run a `humanizer` pass, then re-read it as the recipient.
7. Nothing confidential leaves its audience: check every recipient, attachment and quoted line.
- **Done:** a draft the user can send unchanged, with the recipients and subject stated.
