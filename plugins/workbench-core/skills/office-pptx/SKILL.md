---
name: office-pptx
description: "Build or rebuild a PowerPoint deck (.pptx) with python-pptx from an outline or corporate template (tables, editable charts, images, speaker notes), then render every slide and fix it. Use for \"make a deck\", \"turn this into slides\", \"use our template\", \"add a chart slide\"."
when_to_use: "ALWAYS load before creating or editing a PowerPoint deck, even a small one."
---

# office-pptx

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it
> appears unreplaced (the skill was copied in without the plugin), use `py -3` on Windows and
> `python3` on Linux, macOS and WSL, never the Microsoft Store `python` stub.

`scripts/build_deck.py` turns a JSON outline into a deck. You write the outline; the script does
the python-pptx work. Setup once: `"${user_config.python}" -m pip install --user -r "${CLAUDE_SKILL_DIR}/requirements.txt"`.

## 1. Plan the story before any slide
- One message per slide, written as the title ("Build time fell 40% after caching", not "Build
  time"). A reader who sees only the titles should get the argument.
- At most about 6 bullets, each under one line; detail goes in speaker notes.
- Prefer a chart or a table to a paragraph of numbers. One chart per slide, one point per chart.

## 2. Start from the template when there is one
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/build_deck.py" layouts template.pptx
```
lists every layout and its placeholders. Name layouts in the outline (`"layout": "Title Only"`) so
the deck inherits the template's fonts, colours and master. Template sample slides are removed
unless `"keep_template_slides": true`. The template must be a `.pptx`: save a `.potx` as `.pptx`
in PowerPoint first; macro-enabled files (`.pptm`, `.potm`) are refused. Content slides (bullets,
tables, charts, images) always get a layout with a top title, so content never sits under a
centred title-slide heading.
Never hard-code brand colours or fonts the template already defines.

## 3. Write the outline and build
Outline format: see the docstring at the top of `scripts/build_deck.py` (title/subtitle, nested
`bullets`, `table` with `columns` and `rows`, `chart` with `type` bar/column/stacked/line/pie/
doughnut, `categories`, `series`, optional `number_format`, `data_labels`, `legend`,
`chart_title`, `image`, `notes`).
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/build_deck.py" build outline.json deck.pptx
```
Without a template the deck is 16:9 (13.333 x 7.5 in), with the built-in layouts stretched to fit.
A long title shrinks (down to 20 pt), then wraps onto more lines and pushes the body down, so it
never overlaps the content; the estimate is approximate, so the render step still checks it.
Horizontal bar charts list the first category at the top, with the value axis at the bottom.
Image and template paths must stay inside the outline's folder; `..` escapes, other absolute paths,
network paths and URLs are refused unless you pass `--allow-outside` (a network path can send
Windows credentials to that server).
Charts are native PowerPoint charts (editable data), not pictures. Images are scaled to fit the
content area without distortion. Empty placeholders are removed so no "Click to add text" boxes
remain. `LINT` lines flag long titles, too many bullets, long bullets, big tables and missing
titles: fix the outline, not the file.

## 4. QA loop: render, look at every slide, fix, repeat
python-pptx cannot measure text, so overflow is only visible in a render.
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/../office-render/scripts/render.py" deck.pptx --out render/
```
Then Read every PNG it lists, one by one. For each slide check: text inside its box, nothing
overlapping, readable size (body 14 pt or more), chart labels legible, table not cramped, images
not distorted, consistent alignment, nothing left over from the template. Write the defects as a
list, fix the outline (shorter text, split the slide, different layout), rebuild, re-render.
Stop after the round that finds nothing, at most three rounds, and report what you checked.
For a final sign-off on a client-facing deck, render with real PowerPoint (`--engine office`),
since other renderers substitute fonts.

## Editing an existing deck
Small text changes: open it with python-pptx, change the runs you need, save under a new name, and
render. Structural changes (reordering, new slide types): rebuild from an outline instead of
patching XML by hand.

## Before it leaves the organisation
Render check first (section above), then scrub a copy and send only the copy:
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/../office-render/scripts/scrub.py" deck.pptx --out deck-send.pptx --json
```
It removes hidden slides and every link to them, comments, author and company names and the preview image; add `--strip-notes` to drop speaker notes too. The sensitivity label stays. Details and limits: the office-render skill.

## Alternatives
Anthropic's official `document-skills` plugin and the Claude for PowerPoint add-in are optional,
separately licensed alternatives; see `THIRD-PARTY.md` before installing either.
