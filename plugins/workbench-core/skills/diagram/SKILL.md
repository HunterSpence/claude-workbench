---
name: diagram
description: "Turn an English description or Mermaid text into a diagram: .mmd source, editable .excalidraw, SVG and PNG, rendered offline in a local browser. Use for flowcharts, sequence, state and architecture sketches for docs, decks and pull requests."
when_to_use: "ALWAYS load when a diagram, flowchart or architecture sketch is requested."
---

# diagram

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it
> appears unreplaced (the skill was copied in without the plugin), use `py -3` on Windows and
> `python3` on Linux, macOS and WSL, never the Microsoft Store `python` stub.

The loop is: **write the source, render, look at the PNG, fix, re-render.** A diagram nobody looked
at is not done. The renderer works from a bundle on disk in a local Edge or Chrome that cannot reach
the network, so the text of your diagram (system names, hosts, flows) never leaves the machine.

## 1. Write the source (Mermaid)
From an English description, write `<name>.mmd` next to the document that will use it (or in
a `diagrams/` folder of your repository). One idea per diagram; about 25 nodes at most, and split the rest.
- Pick the type from the question: a flow or pipeline is `flowchart LR` (left to right reads best in
  a document), a conversation between systems is `sequenceDiagram`, a lifecycle is `stateDiagram-v2`,
  tables and keys are `erDiagram`.
- Short labels. Quote any label that holds brackets, parentheses or a colon: `A["Queue (retry)"]`.
- A node named `end` (all lowercase) breaks a flowchart; write `End` or `done`.
- Group with `subgraph` (trust zones, teams, environments). Mark one path as the happy path.
- Name things the way the people who read it name them; no invented system names.

If the user hands you Mermaid, an `.excalidraw` file or a picture to redraw, start from that and
keep their labels.

## 2. Setup (once)
Two things are needed, neither is in the repo you are working on:
```bash
# the renderer bundle (one HTML file) goes to <config dir>/skills/diagram-render/
"${user_config.python}" <kit>/tools/fetch-upstream/fetch_upstream.py --apply --only diagram-render

# playwright-core (the same version ui-build uses), in a working folder outside the repo
cp -r "${CLAUDE_SKILL_DIR}/scripts" ./diagram-tool && cd diagram-tool && npm install --ignore-scripts   # no browser download
```
Or install it in any empty folder (copy `package.json` there, run the same `npm install`) and set
`DIAGRAM_NODE_MODULES` to that folder's `node_modules`; then `render.py` runs from the skill folder.
`fetch_upstream.py` verifies the file against a pinned SHA-256 first; ask your organisation before
you run it, as for any download. `render.mjs` drives the browser (the installed Edge or Chrome;
`UI_BROWSER` names another) and `package.json` pins playwright-core. With the copy, run
`diagram-tool/render.py` in the next step.

## 3. Render
```bash
"${user_config.python}" ./diagram-tool/render.py diagrams/intake.mmd            # writes intake.svg, intake.png, intake.excalidraw
"${user_config.python}" ./diagram-tool/render.py diagrams/intake.mmd --width 2400 --out build/
```
- `.svg` and `.png` are the deliverables; the PNG is 1600 px wide unless `--width` (200 to 4000).
- `.excalidraw` is an editable scene. The converter reads flowcharts (it printed
  `EXCALIDRAW_SKIPPED` for other types and left the SVG and PNG complete).
- Output is checked before it is moved into place: a real SVG, a PNG with a size, a readable scene.
  A failed run writes nothing and exits non-zero; do not report a diagram as rendered without the
  `RENDERED` line.
- The last line says how many outside requests the browser refused. Nothing is ever sent.
  A hand-drawn-style font is requested from a web font host when you render a `.excalidraw`; it is
  refused, and the text falls back to a plain font (labels can wrap differently).
- Mermaid syntax errors come back as the parser's own message with the line; fix that line.

## 4. Look, fix, re-render
Open the PNG (read the image file) and write down the defects: clipped or overlapping labels,
crossing lines that hide the flow, text too small at the size it will be used, a node nobody can
name. Fix the `.mmd`, re-render, look again. Stop after a round that finds nothing, at most three
rounds. Put the PNG in the document, link the `.mmd` beside it so the next person can edit the text.

## 5. Hand-editing
`render.py x.mmd` regenerates `x.excalidraw` every time (the previous one is kept as
`x.excalidraw.prev`, one generation). Once someone edits the `.excalidraw` by hand, render from that
file (`render.py x.excalidraw` writes `x.svg` and `x.png` only) and stop re-rendering the `.mmd`.
Open the scene in any Excalidraw editor.

## Failures
- `BUNDLE_MISSING` - step 2, first block, or set `DIAGRAM_RENDER_BUNDLE` to the file.
- `PLAYWRIGHT_MISSING` - you ran `render.py` from the plugin folder; run the copy that has `node_modules`.
- `no Edge or Chrome found` - set `UI_BROWSER` to a browser executable.
- `NODE_MISSING` - Node.js is not on PATH; ui-build needs it too, so ask for it as for any tool.
- `RENDER_FAILED ... no PNG` - the page produced no image; re-run once, then check the `.mmd` renders
  by lowering its size (remove half the nodes).
