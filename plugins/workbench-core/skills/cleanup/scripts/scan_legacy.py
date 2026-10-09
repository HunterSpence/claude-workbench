#!/usr/bin/env python3
"""Report-only scan for dead or legacy files in a repository (stdlib only). It reads; it never moves, edits or deletes.

    python scan_legacy.py --root DIR [--json] [--stale-days 30] [--script-dirs scripts,tools,bin] [--keep GLOB ...]
    python scan_legacy.py --self-test

Two kinds of candidate:
  doc     a Markdown file whose front matter says `status:` deprecated, obsolete, superseded, archived, dead, legacy or retired
  script  a file in one of the script folders whose file name (for Python and JavaScript also its module name) appears in no
          other text file of the repository and that has not changed for --stale-days days
`--json` prints {"candidates": [{"path", "reason", "last_commit_days"}]}; last_commit_days is null when git cannot say (the age
then comes from the file's modification time). Exit 0 unless the arguments are wrong (2).

A script nothing in the repository mentions can still be started by a scheduler, a launcher or CI, none of which a text search
sees. Every script candidate is therefore "review", never "confirmed": check those places (see the cleanup skill) before archiving.
Precision over recall: a name that is mentioned anywhere, even in a comment, keeps the file off the list.
"""
import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEAD = {"deprecated", "obsolete", "superseded", "archived", "dead", "legacy", "retired"}
SCRIPT_EXT = {".ps1", ".py", ".sh", ".mjs", ".js", ".cjs", ".ts", ".cmd", ".bat"}
MODULE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts"}         # imported without the extension, so the bare name counts as a mention
ENTRY = {"__init__.py", "__main__.py", "conftest.py", "setup.py", "manage.py", "main.py", "cli.py", "index.js", "index.mjs", "index.ts"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "_archive", "dist", "build"}
TEXT_MAX = 1_000_000          # a file larger than this is not read for mentions
FILE_MAX = 20_000             # beyond this many files the scan stops reading more and says so


def listing(root):
    """(relative posix paths, git available): tracked plus untracked-not-ignored files in a work tree, else a walk."""
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           capture_output=True, timeout=60)
        if r.returncode == 0 and (Path(root) / ".git").exists():
            return sorted(set(x for x in r.stdout.decode("utf-8", "replace").split("\0") if x)), True
    except (OSError, subprocess.SubprocessError):
        pass
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        out += [(Path(d) / f).relative_to(root).as_posix() for f in files]
    return sorted(out), False


def skipped(rel):
    return any(part in SKIP_DIRS for part in rel.split("/")[:-1])


def read(path):
    try:
        if os.path.getsize(path) > TEXT_MAX:
            return ""
        b = Path(path).read_bytes()
    except OSError:
        return ""
    return "" if b"\0" in b[:4096] else b.decode("utf-8", "replace")


def status_of(text):
    m = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    if m:
        s = re.search(r"^status\s*:\s*[\"']?([A-Za-z-]+)", m.group(1), re.M | re.I)
        return s.group(1).lower() if s else None
    return None


def commit_days(root, rel, now):
    try:
        r = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%ct", "--", rel], capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip().isdigit():
            return max(0, int((now - int(r.stdout.strip())) // 86400))
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def scan(root, stale_days=30, script_dirs=("scripts", "tools", "bin"), keep=(), now=None):
    root = Path(root)
    now = now or time.time()
    files, has_git = listing(root)
    files = [f for f in files if not skipped(f)]
    notes = []
    if len(files) > FILE_MAX:
        notes.append(f"only the first {FILE_MAX} of {len(files)} files were read for mentions")
        files_read = files[:FILE_MAX]
    else:
        files_read = files
    scripts = [f for f in files if Path(f).suffix.lower() in SCRIPT_EXT and f.split("/")[0] in script_dirs
               and Path(f).name not in ENTRY and not re.match(r"test_|.*[._]test\.|.*_test\.", Path(f).name)
               and not any(fnmatch.fnmatchcase(f, k) or fnmatch.fnmatchcase(Path(f).name, k) for k in keep)]
    needles = {}
    for f in scripts:
        p = Path(f)
        needles[f] = [re.compile(re.escape(p.name))] + (
            [re.compile(r"(?<![\w-])" + re.escape(p.stem) + r"(?![\w-])")] if p.suffix.lower() in MODULE_EXT else [])
    mentioned = set()
    out = []
    for f in files_read:
        text = read(root / f)
        if not text:
            continue
        if f.lower().endswith(".md"):
            st = status_of(text)
            if st in DEAD:
                out.append({"path": f, "reason": f"front matter status: {st}", "last_commit_days": commit_days(root, f, now) if has_git else None})
        for s, rxs in needles.items():
            if s not in mentioned and s != f and any(rx.search(text) for rx in rxs):
                mentioned.add(s)
    for s in scripts:
        if s in mentioned:
            continue
        days = commit_days(root, s, now) if has_git else None
        age = days if days is not None else int((now - os.path.getmtime(root / s)) // 86400)
        if age >= stale_days:
            out.append({"path": s, "reason": f"script named in no other file; unchanged {age} days; check schedulers and CI before archiving",
                        "last_commit_days": days})
    out.sort(key=lambda c: c["path"])
    return {"candidates": out, **({"notes": notes} if notes else {})}


def tree_state(root):
    return sorted((p.relative_to(root).as_posix(), p.stat().st_size, p.read_bytes()) for p in Path(root).rglob("*") if p.is_file())


def self_test():
    """Offline, in a temporary folder: the right files are listed, the others are not, and nothing is touched."""
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        files = {
            "scripts/orphan.sh": "echo hi\n", "scripts/used.sh": "echo used\n", "scripts/lib_util.py": "X = 1\n",
            "scripts/run_it.py": "import lib_util\n", "scripts/test_thing.py": "x = 1\n", "scripts/main.py": "x = 1\n",
            "docs/old.md": "---\nstatus: deprecated\n---\nOld.\n", "docs/live.md": "---\nstatus: active\n---\nLive.\n",
            "README.md": "Run scripts/used.sh and scripts/run_it.py.\n",
        }
        for rel, body in files.items():
            (r / rel).parent.mkdir(parents=True, exist_ok=True)
            (r / rel).write_text(body, encoding="utf-8")
        before = tree_state(r)
        got = [c["path"] for c in scan(r, stale_days=0)["candidates"]]
        assert got == ["docs/old.md", "scripts/orphan.sh"], got
        assert [c["path"] for c in scan(r, stale_days=30)["candidates"]] == ["docs/old.md"], "a fresh script is not stale"
        assert tree_state(r) == before, "the scan changed the tree"
    print("scan_legacy self-test ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--stale-days", type=int, default=30)
    ap.add_argument("--script-dirs", default="scripts,tools,bin", help="top-level folders whose scripts are checked for mentions")
    ap.add_argument("--keep", action="append", default=[], help="glob of a path or file name to leave out (a known entry point); repeatable")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        self_test()
        return 0
    if not a.root or not os.path.isdir(a.root):
        print("error: --root must name an existing folder", file=sys.stderr)
        return 2
    res = scan(a.root, a.stale_days, tuple(x for x in a.script_dirs.split(",") if x), tuple(a.keep))
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        for c in res["candidates"]:
            print(f"{c['path']}\t{c['reason']}\t{'' if c['last_commit_days'] is None else str(c['last_commit_days']) + ' days since the last commit'}")
        print(f"{len(res['candidates'])} candidate(s). Report only: nothing was moved or deleted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
