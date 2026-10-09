# Lock a brand spec, then build and review a UI against it

Automates it: /workbench-core:brand-spec

## When to use
A product, internal tool or deck has no style guide yet and someone is about to build screens for it. Ten minutes of
questions now stop the work drifting to a generic look. The same guide covers reviewing an existing UI against a fixed
checklist. `<KIT>` is the kit folder (guide 01).

## Steps
1. Run `/workbench-core:brand-spec` for the Project Heron portal (Claude cannot start it; if you only ask for a brand spec, it
   will suggest the command). It first reads what already exists (a style guide,
   design tokens, a deck template, the current screens) and asks only what those leave open.
2. Answer one question at a time. Say "pick for me" and it offers two to four options with a recommended one. After every
   fifth question it summarises what it has and waits for your correction.
3. Read the `BRAND_SPEC.md` it writes: personality, audience, visual identity, motion, voice, anti-goals and a block of
   locked tokens (colour roles as OKLCH with a hex fallback, fonts, spacing, radii, motion times). Check the `Open items`
   section: every `ASSUMED:` line is a guess to confirm or change.
4. Build or change screens with `/workbench-core:ui-build`. It reads `BRAND_SPEC.md` when the project has no tokens of its
   own, runs the app locally, screenshots it at 1440 and 390 pixels in light and dark, and runs an accessibility check.
5. To review a UI, ask: "review this page against the design rules". Once per machine, install the pinned rules list the
   review reads from disk (ask IT first, as for any download):
   ```
   py -3 <KIT>/tools/fetch-upstream/fetch_upstream.py --apply --only web-interface-guidelines
   ```
   The review fixes what it finds in code it changed and lists the rest as `file:line - rule - fix`.
6. If a token has to change, edit `BRAND_SPEC.md` first, then redo the screens that used it.

## Verify
- `BRAND_SPEC.md` has every section in order, a date, at least three anti-goals and three banned patterns, and its text and
  background colour pairs are listed with the ratios checked (4.5:1 for text, 3:1 for large text and interface parts).
- The `ui-build` run ends with before and after screenshots, an accessibility result with no serious or critical
  violation left, and no `OVERFLOW` line at 390 pixels.
- A review lists findings by screenshot and region, with a fix for each blocker and major one.

## Common failures
- **The UI skill ignores the spec:** it is not at the project root or in `docs/`. Move it, or tell Claude the path.
- **The interview wanders past thirty questions:** say "stop, mark the rest ASSUMED"; the spec records your defaults
  instead of inventing answers.
- **The review says the rules list is missing:** step 5 has not run, or the download was blocked (guide 04). It then does
  the pass from the playbook rubric and says so; it never fetches the list from the web.
- **Contrast fails after the palette was locked:** change the token, not the component, and re-run the accessibility check.
- **A web font does not load in the screenshots:** the screenshot script blocks third-party hosts. Use a system font, or
  serve licensed font files from the product's own host; `--allow-fonts` is only for a font host your organisation allows.
- **Client or unreleased material:** keep `BRAND_SPEC.md` out of shared repositories unless the owner agrees.
