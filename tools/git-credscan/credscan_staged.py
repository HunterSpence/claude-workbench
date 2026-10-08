#!/usr/bin/env python3
"""credscan_staged.py: block a commit whose ADDED lines carry a credential-shaped value. Pre-commit hook or CLI.

  credscan_staged.py                 scan `git diff --cached` in the current repo; prints `path:line masked`
  credscan_staged.py --json          {"files": [...], "findings": [{"file", "line", "match"}]}
  credscan_staged.py --install DIR   write DIR/.git/hooks/pre-commit that runs this file (never overwrites a hook)

Only added lines are scanned: content already in history needs rotating, not re-flagging. Findings are always masked
(first 4 characters + length). Exit 0 clean, 1 findings (the commit is blocked), 2 could not scan (fail closed).
The pattern set is the kit's secretscan.py (plugins/workbench-core/scripts), the same one the save driver and the
credential Stop hook use. Standard library plus git; no network.
"""
import codecs
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCANNER_DIR = Path(os.environ.get("WORKBENCH_SECRETSCAN_DIR") or HERE.parent.parent / "plugins" / "workbench-core" / "scripts")
MAX_BYTES = 5 * 1024 * 1024          # a bigger added diff is reported NOT SCANNED, never passed silently
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _path(header):
    p = header[4:]
    if p.startswith('"') and p.endswith('"'):   # git C-quotes paths holding quotes, backslashes or control chars
        p = codecs.escape_decode(p[1:-1].encode("utf-8"))[0].decode("utf-8", "replace")
    return p[2:] if p.startswith("b/") else None   # /dev/null (a deletion) -> None


def added_lines(cwd=None):
    """{path: {new_line_no: text}} for every added line in the index against HEAD. Binary files have no hunks."""
    p = subprocess.run(["git", "-c", "core.quotepath=false", "diff", "--cached", "-U0", "--no-color", "--no-ext-diff",
                        "--no-textconv", "--diff-filter=ACMR", "--src-prefix=a/", "--dst-prefix=b/"],
                       capture_output=True, cwd=cwd)
    if p.returncode != 0:
        raise RuntimeError("git diff --cached failed: " + p.stderr.decode("utf-8", "replace")[:200])
    files, path, line, header = {}, None, 0, False
    for raw in p.stdout.decode("utf-8", "replace").split("\n"):
        if raw.startswith("diff --git "):
            path, header = None, True
        elif header and raw.startswith("+++ "):
            path = _path(raw)
        elif raw.startswith("@@ "):
            header = False
            m = HUNK.match(raw)
            line = int(m.group(1)) if m else 0
        elif not header and path and raw.startswith("+"):
            files.setdefault(path, {})[line] = raw[1:].rstrip("\r")
            line += 1
    return files


def scan(cwd=None):
    sys.path.insert(0, str(SCANNER_DIR))
    import secretscan
    out = []
    for path, lines in added_lines(cwd).items():
        size = sum(len(t) for t in lines.values())
        if size > MAX_BYTES:
            out.append({"file": path, "line": 1, "match": f"NOT SCANNED: {size:,} bytes of added lines exceed the "
                        f"{MAX_BYTES // 1048576} MB scan limit"})
            continue
        text = "\n".join(lines.get(i, "") for i in range(1, max(lines) + 1))   # line N of text = added line N
        for s, e in secretscan.scan_text(text):
            out.append({"file": path, "line": text.count("\n", 0, s) + 1, "match": secretscan.mask(text[s:e])})
    return out


def install(repo):
    gitdir = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"], capture_output=True, text=True)
    if gitdir.returncode != 0:
        print(f"not a git repository: {repo}", file=sys.stderr)
        return 2
    custom = subprocess.run(["git", "-C", str(repo), "config", "--get", "core.hooksPath"], capture_output=True, text=True)
    if custom.stdout.strip():
        print(f"this repo uses core.hooksPath={custom.stdout.strip()} (or a hook framework): add a step that runs\n"
              f"  {shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))}\nto it instead.")
        return 2
    hooks = Path(repo) / gitdir.stdout.strip() if not Path(gitdir.stdout.strip()).is_absolute() else Path(gitdir.stdout.strip())
    hook = hooks / "pre-commit"
    if hook.exists():
        print(f"{hook} already exists: left alone. Add this line to it:\n  "
              f"{shlex.quote(Path(sys.executable).as_posix())} {shlex.quote(Path(__file__).resolve().as_posix())} || exit 1")
        return 2
    hooks.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\n# Credential gate (claude-workbench tools/git-credscan). Bypass: none; fix the commit.\n"
                    f"exec {shlex.quote(Path(sys.executable).as_posix())} {shlex.quote(Path(__file__).resolve().as_posix())}\n",
                    encoding="utf-8", newline="\n")
    try:
        hook.chmod(0o755)
    except OSError:
        pass
    print(f"installed {hook}")
    return 0


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    if a[:1] == ["--install"]:
        return install(a[1] if len(a) > 1 else ".")
    as_json = "--json" in a
    try:
        found = scan()
    except Exception as e:   # fail closed: an unscanned diff never passes
        msg = f"credscan_staged: could not scan the staged diff: {type(e).__name__}: {e}"[:300]
        print(json.dumps({"error": msg}) if as_json else msg, file=sys.stdout if as_json else sys.stderr)
        return 2
    if as_json:
        print(json.dumps({"files": sorted({f["file"] for f in found}), "findings": found}))
    else:
        for f in found:
            print(f"{f['file']}:{f['line']} {f['match']}")
        if found:
            print(f"pre-commit: {len(found)} finding(s) in staged lines, commit blocked. Move the credential to your "
                  "secret store, refer to it by name, and re-stage.", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
