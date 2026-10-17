# Charts in a PDF report: inline SVG

Inline SVG prints as vector shapes with selectable text, stays sharp at any zoom and needs no script. A canvas or a bitmap chart does not.
A chart that needs JavaScript is outside the default path (it would need `--virtual-time-budget` and a policy that allows scripts).

## Recipe
- `<figure>` around an `<svg viewBox="0 0 500 200" width="100%" role="img" aria-label="...">` with a `<title>` first. The caption
  (`<figcaption>`) says what the reader should see, not what the chart is.
- Set `font-family` on the `<svg>` (it does not inherit the page font in every case) and use text at 8 pt or more once scaled to the page width.
- Label the marks directly (value above a bar, name at the end of a line) so no legend lookup is needed.
- Colour: one accent for the point being made and a muted grey for the rest. Where several series are needed use a colour-blind-safe set (blue,
  orange, teal, grey) with at least 3:1 contrast against the page, and make sure the chart still reads in greyscale (different marker shapes or
  direct labels). Do not use red against green.
- Keep the figure whole across pages (`figure { break-inside: avoid }` is in `report.css`) and give the SVG a fixed `viewBox` height.

## Smallest working chart
```html
<figure>
<svg viewBox="0 0 300 140" width="100%" role="img" aria-label="Tasks closed per quarter" font-family="Segoe UI, Arial, sans-serif">
<title>Tasks closed per quarter</title>
<rect x="30" y="80" width="50" height="50" fill="#0b5cad"/><text x="55" y="72" text-anchor="middle" font-size="12">18</text>
<rect x="110" y="40" width="50" height="90" fill="#0b5cad"/><text x="135" y="32" text-anchor="middle" font-size="12">31</text>
<text x="55" y="134" text-anchor="middle" font-size="11" fill="#5a6672">Q1</text><text x="135" y="134" text-anchor="middle" font-size="11" fill="#5a6672">Q2</text>
</svg>
<figcaption>Figure 1. Closed tasks rose from 18 to 31.</figcaption>
</figure>
```
Markdown passes a block like this through untouched if it has no blank line inside it.

## Where charts come from
- By hand or by script: compute coordinates in Python and write the SVG string (the sample test in `scripts/tests/sample.py` does this).
- The `diagram` skill draws architecture and flow diagrams offline as SVG; embed its SVG file's content directly.
- A plotting library is not part of the kit. If the user already has one, export SVG with text kept as text, not as outlines.

## Check
Build, then read the page PNG at full size: labels must not collide or clip, and the bars or lines must match the numbers in the text.
