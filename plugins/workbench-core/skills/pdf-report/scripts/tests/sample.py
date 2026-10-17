"""A generic sample report ("Acme quarterly status") for the pdf-report tests. Built from code, so no document is stored.
The text is invented; the table rows carry unique tokens (T-001 ...) so a row cut across a page boundary can be found."""
import pathlib

OWNERS = ("Team A", "Team B", "Team C")
LONG = "with a longer note that wraps onto a second line in the narrow task column so rows differ in height"


def chart_svg():
    bars = [("Q1", 18), ("Q2", 26), ("Q3", 31), ("Q4", 40)]
    parts = []
    for i, (label, v) in enumerate(bars):
        x, h = 40 + i * 110, v * 3.4
        parts.append(f'<rect x="{x}" y="{170 - h:.0f}" width="70" height="{h:.0f}" fill="#0b5cad"/>'
                     f'<text x="{x + 35}" y="{162 - h:.0f}" text-anchor="middle" font-size="13" fill="#1b2733">{v}</text>'
                     f'<text x="{x + 35}" y="190" text-anchor="middle" font-size="12" fill="#5a6672">{label}</text>')
    return ('<figure><svg viewBox="0 0 500 200" width="100%" role="img" aria-label="Tasks closed per quarter" '
            'font-family="Segoe UI, Arial, sans-serif"><title>Tasks closed per quarter</title>'
            + "".join(parts) + '<line x1="30" y1="170" x2="490" y2="170" stroke="#5a6672"/></svg>'
            '<figcaption>Figure 1. Tasks closed per quarter (sample data).</figcaption></figure>')


def sample_markdown(rows=70):
    table = ["| ID | Task | Owner | Status | Hours |", "|---|---|---|:---:|---:|"]
    for i in range(1, rows + 1):
        note = f" {LONG}" if i % 5 == 0 else ""
        table.append(f"| T-{i:03d} | Task {i:03d} item{note} | {OWNERS[i % 3]} | Done | {i * 1.5:.1f} |")
    return "\n".join([
        "---", "title: Acme quarterly status", "subtitle: Third quarter review", "author: Acme Operations", "date: Third quarter",
        "classification: Internal", "cover: yes", "---", "",
        "# Summary", "",
        "Acme closed the planned work for the quarter and moved the open risks into the next plan. "
        "This sample report exists to test the PDF builder: it has a cover, a contents page, a chart and a long table.", "",
        "> **Decision needed:** approve the plan for the next quarter by the review date.", "",
        "# Results", "", "## Delivery", "",
        "Delivery improved in every quarter. The chart below shows tasks closed per quarter.", "",
        chart_svg(), "",
        "## Quality", "",
        "- **Defects:** fewer escapes than last quarter.", "- **Reviews:** every change was reviewed before release.",
        "- **Open risks:** two, both with owners and dates.", "",
        '# Task log {: .pb }', "",
        "The table below lists every task; its header repeats on each page and no row is split across pages.", "",
        *table, "",
        "# Next steps", "", "1. Approve the plan.", "2. Start the next quarter.", "3. Review risks monthly.", "",
    ])


def write_sample(folder, rows=70, name="sample-report.md"):
    p = pathlib.Path(folder) / name
    p.write_text(sample_markdown(rows), encoding="utf-8")
    return p
