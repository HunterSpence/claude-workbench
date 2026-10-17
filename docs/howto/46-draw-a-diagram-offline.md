# Draw a diagram for a document, deck or pull request

Automates it: /workbench-core:diagram

## When to use
You need a flowchart, a sequence of calls between systems or an architecture sketch, and you want it as text you can keep
in git, a file you can edit by hand, and an SVG and PNG you can paste into a document, a deck or a pull request. Nothing
is sent to an online diagram service: a local Edge or Chrome renders it from a file on disk and cannot reach the network.
`<KIT>` is the kit folder (guide 01).

## Steps
1. Ask Claude: "draw a diagram of how a support request moves from the portal to the resolver queue". It writes
   `intake.mmd` (Mermaid text) next to your document and keeps the label wording you gave it. Or write the Mermaid yourself.
2. Once per machine, ask IT as for any download, then fetch the renderer. It is one HTML file, checked against a pinned
   SHA-256 and kept in `<CH>/skills/diagram-render/`:
   ```
   py -3 <KIT>/tools/fetch-upstream/fetch_upstream.py --apply --only diagram-render
   ```
3. Once per machine, install the browser driver in an empty working folder outside any repository. Copy
   `<KIT>/plugins/workbench-core/skills/diagram/scripts/package.json` there and run `npm install --ignore-scripts`. No
   browser is downloaded; the installed Edge or Chrome is used.
4. Render, with `DIAGRAM_NODE_MODULES` pointing at the `node_modules` folder from step 3:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/diagram/scripts/render.py intake.mmd
   ```
   It writes `intake.svg` and `intake.png`, and `intake.excalidraw` for flowcharts.
5. Open the PNG. Look for clipped or overlapping labels, lines that hide the flow, text too small for where it will be
   used. Fix the `.mmd`, render again, and stop after a round that finds nothing.
6. Put the PNG or SVG in the document and keep the `.mmd` beside it. To change the drawing by hand, open the
   `.excalidraw` in an Excalidraw editor, then render from that file
   (`render.py intake.excalidraw` writes the SVG and PNG only) and stop re-rendering the `.mmd`.

## Verify
- The run prints `RENDERED` followed by the paths, and a line `offline: 0 outside request(s) refused`. A `.excalidraw`
  source can show one or two refused requests: the page asks a web-font host for its hand-drawn font, the block refuses
  it, and the text falls back to a plain font.
- The PNG opens, is the width you asked for (1600 pixels unless `--width`) and every label is readable.
- To check the tool itself: `py -3 -I -m unittest discover -s <KIT>/plugins/workbench-core/skills/diagram/tests` passes
  (the live render test skips with a reason when the renderer, the driver or a browser is missing).

## Common failures
- **`BUNDLE_MISSING`:** step 2 has not run, or the download was blocked. Behind a proxy that re-signs HTTPS, see guide 04.
  `DIAGRAM_RENDER_BUNDLE` can point at a copy IT gave you.
- **`PLAYWRIGHT_MISSING`:** `DIAGRAM_NODE_MODULES` is not set to the `node_modules` folder from step 3.
- **`no Edge or Chrome found`:** set `UI_BROWSER` to a browser executable.
- **A Mermaid parse error:** the message names the line. Quote labels that hold brackets or colons, and never name a
  flowchart node `end` in lowercase.
- **No `.excalidraw` came out:** the converter reads flowcharts only; the SVG and PNG are complete.
- **The render says it failed with no PNG, and no file appears:** by design nothing half-written is left behind; run again,
  and if it repeats, halve the diagram.
