"""Show the issues log (<workbench home>/state/issues.jsonl, written by bug_hint.py on every failed tool call) as a numbered
markdown table: n | time | tool | first error line. The older file (issues.jsonl.1) is read first, so numbers follow the
order the failures happened in. Read-only; a line that is not valid JSON is skipped.

  py -3 <KIT>/plugins/workbench-core/scripts/issues.py show [--since YYYY-MM-DD]

--since keeps rows whose UTC time is on or after that date (or full timestamp); numbers stay the same with and without it.
Exit 0 (an empty or missing log prints a one-line note), 2 on a bad --since.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wb  # noqa: E402

CELL = 160


def rows():
    out = []
    base = _wb.workbench_home() / "state" / "issues.jsonl"
    for p in (base.with_name(base.name + ".1"), base):
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    out.append(r)
        except OSError:
            continue
    return out


def cell(v):
    v = " ".join(str(v).split()).replace("|", "\\|")
    return v if len(v) <= CELL else v[:CELL - 3] + "..."


def first_line(r):
    err = r.get("error")
    err = err if isinstance(err, list) else [err] if isinstance(err, str) else []
    return next((x for x in map(str, err) if x.strip()), "(no error text)")


def table(since=None):
    shown = [(n, r) for n, r in enumerate(rows(), 1) if not since or str(r.get("time", "")) >= since]
    if not shown:
        return "No issues logged." if not since else f"No issues logged since {since}."
    return "\n".join(["| n | time | tool | first error line |", "|---|---|---|---|"] +
                     [f"| {n} | {cell(r.get('time', ''))} | {cell(r.get('tool', ''))} | {cell(first_line(r))} |" for n, r in shown])


def main(argv):
    ap = argparse.ArgumentParser(prog="issues.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["show"])
    ap.add_argument("--since", metavar="DATE")
    a = ap.parse_args(argv)
    if a.since and not re.fullmatch(r"\d{4}-\d\d-\d\d(?:T[\d:.]*Z?)?", a.since):
        print("--since takes a date such as 2026-01-31 (UTC)", file=sys.stderr)
        return 2
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # an error line may hold any character
    except (AttributeError, ValueError):
        pass
    print(table(a.since))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
