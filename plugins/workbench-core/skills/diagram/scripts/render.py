#!/usr/bin/env python3
"""render.py: turn a Mermaid (.mmd) or Excalidraw (.excalidraw) file into SVG + PNG, fully offline.

    py -3 render.py <file.mmd | file.excalidraw> [--out DIR] [--width 1600] [--bundle HTML]

Writes <stem>.svg and <stem>.png next to the source (or into --out), plus <stem>.excalidraw for a .mmd the converter can
read (flowcharts). It drives the offline diagram-render bundle in a local Edge or Chrome through render.mjs (playwright-core,
the same network block as the ui-build screenshot script): nothing leaves the machine.
Results are staged in a temp folder and moved into place only after every file checks out (a real SVG, a PNG with the
PNG signature and a size, a parseable scene), so a failed run leaves nothing half-written. A replaced .excalidraw that
differed is kept as <stem>.excalidraw.prev. Exit 0 = rendered, 1 = the render failed, 2 = the source or the setup is wrong.

Bundle: --bundle, else $DIAGRAM_RENDER_BUNDLE, else <config dir>/skills/diagram-render/diagram-render.html (tools/fetch-upstream,
default set), else the copy an older optional install left under skills/gstack. playwright-core: next to this file
(npm install --ignore-scripts in a copy of this folder) or in $DIAGRAM_NODE_MODULES. $DIAGRAM_NODE and $DIAGRAM_RENDERER
replace node and render.mjs (the tests use that to run without a browser)."""
import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
BUNDLE_REL = "diagram-render/diagram-render.html"                      # where fetch-upstream puts it, under <config dir>/skills
LEGACY_REL = "gstack/lib/diagram-render/dist/diagram-render.html"
KINDS = {".mmd": "mmd", ".mermaid": "mmd", ".excalidraw": "excalidraw"}
MAX_SOURCE = 256 * 1024          # a diagram source this large is not a diagram; the renderer would just thrash
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
TIMEOUT = 180


def die(code, msg):
    print(msg, file=sys.stderr)
    sys.exit(code)


def config_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def find_bundle(explicit=None):
    """The bundle path, or None. A bundle named by --bundle or the env var is used alone: no silent fall-through."""
    named = explicit or os.environ.get("DIAGRAM_RENDER_BUNDLE")
    if named:
        return Path(named) if Path(named).is_file() else None
    skills = config_dir() / "skills"
    return next((p for p in (skills / BUNDLE_REL, skills / LEGACY_REL) if p.is_file()), None)


def have_playwright():
    nm = os.environ.get("DIAGRAM_NODE_MODULES")
    return (Path(nm) if nm else HERE / "node_modules").joinpath("playwright-core", "package.json").is_file()


def read_source(path):
    """-> (kind, text); exits 2 on anything that is not a renderable source."""
    if not path.is_file():
        die(2, f"NO_SOURCE: {path} is not a file")
    kind = KINDS.get(path.suffix.lower())
    if not kind:
        die(2, f"BAD_SOURCE: {path.name}: expected .mmd, .mermaid or .excalidraw")
    size = path.stat().st_size
    if size == 0 or size > MAX_SOURCE:
        die(2, f"BAD_SOURCE: {path.name} is {size} bytes (allowed: 1 to {MAX_SOURCE})")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        die(2, f"BAD_SOURCE: {path.name} is not UTF-8 text")
    if kind == "excalidraw":
        try:
            scene = json.loads(text)
        except ValueError as e:
            die(2, f"BAD_SOURCE: {path.name} is not JSON ({e})")
        if not isinstance(scene, dict) or not isinstance(scene.get("elements"), list):
            die(2, f"BAD_SOURCE: {path.name} has no \"elements\" list, so it is not an Excalidraw scene")
    return kind, text


def check_outputs(work, kind):
    """Names of the staged files that are good; exits 1 naming the first bad or missing one."""
    svg, png, scene = work / "out.svg", work / "out.png", work / "out.excalidraw"
    if not svg.is_file() or "<svg" not in svg.read_text(encoding="utf-8", errors="replace")[:2000]:
        die(1, "RENDER_FAILED: no SVG came out of the renderer")
    data = png.read_bytes() if png.is_file() else b""
    if not data.startswith(PNG_SIGNATURE) or len(data) < 33 or min(struct.unpack(">II", data[16:24])) < 1:
        die(1, "RENDER_FAILED: no PNG came out of the renderer (missing, empty or not a PNG)")
    good = ["svg", "png"]
    if kind == "mmd" and scene.is_file():
        try:
            ok = isinstance(json.loads(scene.read_text(encoding="utf-8")).get("elements"), list)
        except ValueError:
            ok = False
        if not ok:
            die(1, "RENDER_FAILED: the .excalidraw the converter wrote is not a scene")
        good.append("excalidraw")
    return good


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--out", help="folder for the outputs (default: next to the source)")
    ap.add_argument("--width", type=int, default=1600, help="PNG width in pixels, 200 to 4000 (default 1600)")
    ap.add_argument("--bundle", help="path to diagram-render.html")
    a = ap.parse_args(argv)
    if not 200 <= a.width <= 4000:
        die(2, "BAD_WIDTH: --width must be between 200 and 4000")
    src = Path(a.source).resolve()
    kind, _ = read_source(src)
    custom = os.environ.get("DIAGRAM_RENDERER")
    bundle = find_bundle(a.bundle)
    if not bundle:
        die(2, "BUNDLE_MISSING: diagram-render.html not found. Install it: py -3 <kit>/tools/fetch-upstream/fetch_upstream.py --apply "
               "(it lands in <config dir>/skills/diagram-render/), or point --bundle / DIAGRAM_RENDER_BUNDLE at the file.")
    node = os.environ.get("DIAGRAM_NODE") or shutil.which("node")
    if not node:
        die(2, "NODE_MISSING: node is not on PATH (the renderer is a small Node script)")
    if not custom and not have_playwright():
        die(2, "PLAYWRIGHT_MISSING: playwright-core is not installed next to render.mjs. In a working folder outside the repo: "
               "copy this scripts folder, run `npm install --ignore-scripts` there, and run that copy's render.py "
               "(or set DIAGRAM_NODE_MODULES to a node_modules folder that has playwright-core).")
    out_dir = Path(a.out).resolve() if a.out else src.parent
    work = Path(tempfile.mkdtemp(prefix="diagram-render-"))
    try:
        cmd = [node, custom or str(HERE / "render.mjs"), "--src", str(src), "--kind", kind, "--bundle", str(bundle),
               "--out-base", str(work / "out"), "--width", str(a.width)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            die(1, f"RENDER_FAILED: no result after {TIMEOUT} seconds")
        if r.returncode:
            text = r.stderr.strip() or r.stdout.strip() or f"exit {r.returncode}"
            die(1, "\n".join(l for l in text.splitlines() if not re.match(r"\s{2,}at\s", l))[:900])   # the message, not the stack
        good = check_outputs(work, kind)
        info = {}
        try:
            info = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            pass
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for ext in good:
            dest = out_dir / f"{src.stem}.{ext}"
            if ext == "excalidraw" and dest.is_file() and dest.read_bytes() != (work / "out.excalidraw").read_bytes():
                os.replace(dest, dest.with_name(dest.name + ".prev"))
                print(f"PREVIOUS {dest.name} kept as {dest.name}.prev")
            os.replace(work / f"out.{ext}", dest)
            written.append(str(dest))
        for note in info.get("notes", []):
            print(note)
        blocked = sorted({urlparse(u).hostname or u for u in info.get("blocked", [])})
        print("RENDERED " + " ".join(written))
        print(f"offline: {len(info.get('blocked', []))} outside request(s) refused" + (f" ({', '.join(blocked)})" if blocked else ""))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
