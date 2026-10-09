#!/usr/bin/env python3
"""route_inventory.py: list a web app's page routes from its source and write the nav-map.md skeleton (stdlib only).

  route_inventory.py SRC [--out help/nav-map.md] [--override routes.override.json] [--check]

SRC is the folder that holds Next.js `app/` or `pages/` (also `src/app`, `src/pages`), or the React Router or Angular
sources (files that import react-router or @angular/router: JSX <Route path> tags and route objects with path and
children). Best effort, no build step: dynamic segments stay as written ([id], :id), lazy-loaded child modules lose
their parent prefix, and menus built from data are invisible. The override file fixes what the scan cannot see:
  {"add": [{"route": "/x", "title": "X", "purpose": "...", "who": "everyone"}], "drop": ["/internal/*"]}
An existing --out file is merged: rows you filled in are kept, new routes are added, routes no longer in the source are
kept and listed. --check writes nothing and exits 1 when the map and the source disagree (for CI).
"""
import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

SKIP_DIRS = {"node_modules", ".git", ".next", "dist", "build", "out", "coverage", ".turbo", ".angular", "__pycache__"}
PAGE_EXT = {".tsx", ".ts", ".jsx", ".js", ".mdx"}
CODE_EXT = {".tsx", ".ts", ".jsx", ".js", ".mjs"}
ROUTER_IMPORT = re.compile(r"""['"](?:react-router(?:-dom)?|@angular/router)['"]""")
ROUTE_TAG = re.compile(r"<(/?)Route\b")
JSX_PATH = re.compile(r"""\bpath\s*=\s*(?:"([^"]*)"|'([^']*)'|\{\s*["'`]([^"'`]*)["'`]\s*\})""")
PATH_KEY = re.compile(r"""path\s*:\s*(['"`])(.*?)\1""")
TITLE = re.compile(r"""metadata\b[^{=]*=\s*\{[^}]*?\btitle\s*:\s*["'`]([^"'`\n]+)["'`]|<title>([^<{]+)</title>""")
HEADER = ["| Route | Title | Purpose | Who |", "|---|---|---|---|"]


def files(src):
    for d, dirs, names in os.walk(src):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for n in sorted(names):
            yield Path(d, n)


def join(parent, path):
    full = path if path.startswith("/") else parent.rstrip("/") + "/" + path
    full = re.sub(r"/+", "/", full)
    return full.rstrip("/") or "/"


def next_route(parts):
    """URL path of a Next.js app/ folder, or None for private (_x) and intercepting ((.)x) folders."""
    segs = []
    for s in parts:
        if s.startswith("_") or (s.startswith("(") and not s.endswith(")")):
            return None
        if not (s.startswith("(") or s.startswith("@")):     # route groups and parallel slots are not URL segments
            segs.append(s)
    return "/" + "/".join(segs)


def pages_route(parts, stem):
    if parts[:1] == ["api"] or any(p.startswith("_") for p in parts) or stem.startswith("_") or stem in ("404", "500") \
            or re.search(r"\.(?:test|spec|stories)$", stem):
        return None
    return "/" + "/".join(parts + ([] if stem == "index" else [stem]))


def tag_end(text, i):
    """(index of the closing >, self-closing?) of a JSX tag whose name ends at i. Braces nest; quotes count at depth 0."""
    depth, quote = 0, None
    while i < len(text):
        ch = text[i]
        if quote:
            quote = None if ch == quote else quote
        elif depth == 0 and ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == ">" and depth == 0:
            return i, text[i - 1] == "/"
        i += 1
    return len(text), True


def jsx_routes(text):
    out, stack = [], []
    for m in ROUTE_TAG.finditer(text):
        if m.group(1):
            if stack:
                stack.pop()
            continue
        end, closed = tag_end(text, m.end())
        pm = JSX_PATH.search(text[m.end():end])
        path = next((g for g in pm.groups() if g is not None), None) if pm else None
        parent = stack[-1] if stack else ""
        full = join(parent, path) if path is not None else parent
        if path is not None and path != "*":
            out.append(full)
        if not closed:
            stack.append(full)
    return out


def skip_string(text, i):
    q, i = text[i], i + 1
    while i < len(text) and text[i] != q:
        i += 2 if text[i] == "\\" else 1
    return i + 1


def object_routes(text):
    """Paths from route objects ({path, children: [...]}) in React Router and Angular, joined to their parent's path."""
    out, stack, i, n = [], [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"`" or (ch == "'" and not (i and text[i - 1].isalpha())):   # an apostrophe in JSX text is not a string
            i = skip_string(text, i)
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if ch == "{":
            stack.append(None)
        elif ch == "}":
            if stack:
                stack.pop()
        elif ch == "p" and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "_$.")):
            m = PATH_KEY.match(text, i)
            if m and stack and stack[-1] is None:
                parent = next((p for p in reversed(stack[:-1]) if p is not None), "")
                stack[-1] = join(parent, m.group(2))
                if m.group(2) not in ("*", "**"):
                    out.append(stack[-1])
                i = m.end()
                continue
        i += 1
    return out


def title_for(route, text=""):
    m = TITLE.search(text)
    if m:
        return (m.group(1) or m.group(2)).strip()
    static = [s for s in route.strip("/").split("/") if s and s[0] not in "[:{*"]
    if not static:
        return "Home"
    words = re.sub(r"[-_]+", " ", static[-1]).strip()
    return words[:1].upper() + words[1:] + (" detail" if route.rstrip("/").split("/")[-1][:1] in "[:{" else "")


def scan(src):
    """{route: (title, source file)} for every page route found under src."""
    src, found = Path(src), {}

    def add(route, f, text=""):
        if route and route not in found:
            found[route] = (title_for(route, text), f.relative_to(src).as_posix())
    for f in files(src):
        rel = f.relative_to(src).parts
        base = 1 if rel[:1] == ("src",) else 0
        if f.suffix in PAGE_EXT and len(rel) > base + 1 and rel[base] == "app" and f.stem == "page":
            route = next_route(list(rel[base + 1:-1]))
            if route:
                add(route, f, f.read_text(encoding="utf-8", errors="replace"))
        elif f.suffix in PAGE_EXT and len(rel) > base + 1 and rel[base] == "pages":
            route = pages_route(list(rel[base + 1:-1]), f.stem)
            if route:
                add(route, f, f.read_text(encoding="utf-8", errors="replace"))
        elif f.suffix in CODE_EXT and not f.name.endswith(".d.ts"):
            text = f.read_text(encoding="utf-8", errors="replace")
            if ROUTER_IMPORT.search(text):
                for route in jsx_routes(text) + object_routes(text):
                    add(route, f)
    return found


def read_map(path):
    """{route: [route, title, purpose, who]} from the table rows of a nav-map.md whose first cell is a /route."""
    rows = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        route = cells[0].strip("`") if cells else ""
        if line.lstrip().startswith("|") and route.startswith("/"):
            rows[route] = ([route] + cells[1:] + ["", "", ""])[:4]
    return rows


def build(found, existing, override):
    drop = override.get("drop", [])
    rows = dict(existing)
    for route, (title, _) in found.items():
        rows.setdefault(route, [route, title, "TODO", "TODO"])
    for a in override.get("add", []):
        rows[a["route"]] = [a["route"], a.get("title") or title_for(a["route"]), a.get("purpose", "TODO"), a.get("who", "TODO")]
    return {r: v for r, v in sorted(rows.items()) if not any(fnmatch.fnmatchcase(r, g) for g in drop)}


def render(rows):
    return "\n".join(["# Navigation map", "",
                      "One row per page a user can open. Who: the roles or plans that can open the page, comma-separated, "
                      "or everyone. Pages that are not listed here do not exist for the assistant.", ""] + HEADER +
                     ["| " + " | ".join(c.replace("|", "/") for c in v) + " |" for v in rows.values()]) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src")
    ap.add_argument("--out", default="help/nav-map.md")
    ap.add_argument("--override")
    ap.add_argument("--check", action="store_true", help="compare only; exit 1 when the map and the source disagree")
    a = ap.parse_args(argv)
    if not Path(a.src).is_dir():
        print(f"error: no such folder: {a.src}", file=sys.stderr)
        return 2
    override = json.loads(Path(a.override).read_text(encoding="utf-8")) if a.override else {}
    found = scan(a.src)
    out = Path(a.out)
    existing = read_map(out) if out.is_file() else {}
    rows = build(found, existing, override)
    new = [r for r in rows if r not in existing]
    gone = [r for r in rows if r in existing and r not in found and r not in {x["route"] for x in override.get("add", [])}]
    for r, (_, src) in sorted(found.items()):
        print(f"{r}\t{src}")
    if gone:
        print("in the map but not found in the source (kept): " + ", ".join(gone), file=sys.stderr)
    if a.check:
        print(f"check: {len(new)} route(s) missing from the map, {len(gone)} not found in the source")
        return 1 if new or gone else 0
    if not rows:
        print("error: no routes found: pass the folder that holds app/, pages/ or the router files", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(rows), encoding="utf-8", newline="\n")
    print(f"{len(rows)} routes ({len(new)} new) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
