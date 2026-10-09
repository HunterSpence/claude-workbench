---
name: brand-spec
description: "Ask one question at a time, then write BRAND_SPEC.md with locked design tokens."
disable-model-invocation: true
---

# brand-spec

UI built without a brand spec drifts to the same generic look every time. This interview fills in
the blanks once, writes them to `BRAND_SPEC.md`, and locks the tokens that `ui-build` and the deck
skills then use. Ask only what the files cannot answer.

## 0. Read before you ask
Look for what already exists and read it: a brand guide or style PDF, an existing `BRAND_SPEC.md`,
design tokens or CSS variables (`ui-build` step 1 lists where they hide), a deck template, the
product's current screens. Write down what you found and treat it as answered.
- A spec or a complete token set already exists: say so, show where, and ask whether the user
  wants to update it. Do not start a new interview over it.
- Material marked confidential or belonging to a client stays where it is: read it, do not copy it
  into the spec beyond what the spec needs (colours, type names, rules).

## 1. Ask
- **One question per message.** Use the interactive question tool when you have it, plain text when
  you do not. Never batch.
- When the user is unsure, give 2 to 4 concrete options with a one-line description each and mark
  the one you would pick.
- After every five questions, say what you have captured and ask whether it is right. Fix what they
  correct before going on.
- Stop at about thirty questions. Anything still open goes into the spec as `ASSUMED: ...` with your
  default, never invented as fact.

Cover these, skipping what step 0 answered:
1. **Purpose and feel.** What should a visitor do or feel in the first ten seconds? One adjective the
   product must be, and its opposite ("trustworthy, not slick"). Two products it should feel like and
   three it must not.
2. **Audience.** Who uses it, what they already know, how they decide (careful comparison, speed,
   a manager's sign-off). Which devices, and how much reading versus scanning.
3. **Visual identity.** Colour temperature and saturation; light, dark or both; fixed brand colours
   (ask for exact values) or a choice of four palettes; type mood (editorial, utility, friendly,
   neutral) and serif, sans or mono; density (airy, balanced, dense); imagery (photo, illustration,
   diagrams, type only, none).
4. **Motion.** None, subtle or expressive; two or three allowed patterns; patterns that are banned.
   The reduced-motion setting is honoured whatever they answer.
5. **Voice.** Formal, plain, warm or technical; how buttons and calls to action read; one headline
   they like and one they dislike.
6. **Must-do and limits.** What the interface must let people do; forms and their fields; systems it
   connects to; device priority; accessibility target (AA is the floor; say if AAA is needed).
7. **Success and failure.** What "great" looks like at launch in one concrete outcome, and the one
   thing that would ruin it.
8. **Anti-goals (required).** At least three things the product must not do, and three visual or
   interaction patterns never to use.

## 2. Lock the tokens
From the answers, propose a small token set and show it before writing:
- **Colour roles** (background, surface, text, muted text, accent, accent hover, border, and one each
  for success, warning, danger), each as `oklch(L C H)` with a hex fallback beside it, because not
  every tool reads OKLCH.
- **Contrast.** Text on its background at least 4.5:1, large text and interface parts at least 3:1.
  The axe run in `ui-build` reports contrast failures; run it on a real screen before you call the
  palette locked.
- **Type.** A display and a body stack ending in system fonts. A web font only when the font files
  are licensed and can be served from the product's own host (a font from a third-party host needs
  the organisation's approval).
- **Spacing, radius and motion.** A short spacing scale, three radii plus a pill, and three
  durations with their easing.

## 3. Write `BRAND_SPEC.md`
At the project root (or `docs/`), with these sections in order: **Personality**, **Audience**,
**Visual identity**, **Motion**, **Voice**, **Must-do and limits**, **Success and failure**,
**Anti-goals**, **Design tokens** (a CSS custom-property block plus the contrast pairs you checked),
**Open items** (every `ASSUMED:` line). Date it. Keep it under two pages: it is read at the start of
every UI task, so it has to be short.

Do not commit it to a shared repository unless the user says so: it can describe an unreleased
product or a client's identity.

## 4. Close
Tell the user where the file is, what is still `ASSUMED:`, and what happens next:
- UI work: `/workbench-core:ui-build` reads `BRAND_SPEC.md` first and uses the locked tokens.
- A deck: `/workbench-biz:branded-deck` takes the colours and fonts from the same file.
- A token must change: edit `BRAND_SPEC.md` first, then redo the work that used it. Do not patch
  one component.
