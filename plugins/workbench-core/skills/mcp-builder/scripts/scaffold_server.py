#!/usr/bin/env python3
"""scaffold_server.py: generate a tested MCP server project from the templates beside this skill.

  python scaffold_server.py --lang py|ts --name NAME --auth none|oauth|header [--http] --out DIR

--auth header|oauth protect the HTTP channel, so they need --http. The output has the server, its logic, schema
helpers, unit + contract + injection tests, an eval question file, a README and .github/workflows/ci.yml.
Template blocks are fenced by marker lines `# @@ if COND` ... `# @@ end` (or `//` in TypeScript/JSON), COND being
`http`, `!http`, `lang=py`, `auth=header`, `auth!=none` and so on. Stdlib only.
"""
import argparse
import re
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
MARK = re.compile(r"^[ \t]*(?:#|//) @@ (?:if (?P<cond>\S+)|(?P<end>end))[ \t]*$")
TEXT = {".py", ".ts", ".json", ".toml", ".md", ".xml", ".yml", ".yaml", ".txt", ".gitignore"}
AUTH_NOTE = {"none": "localhost only; put it behind your own gate before exposing it",
             "header": "callers holding the shared secret", "oauth": "users who sign in through the authorization server"}


def holds(cond, ctx):
    if cond in ("http", "!http"):
        return ctx["http"] == (cond == "http")
    key, op, val = re.match(r"(\w+)(!?=)(\w+)$", cond).groups()
    return (ctx[key] == val) == (op == "=")


def render(text, ctx):
    """Drop the blocks whose condition fails (markers always go), then fill {{name}} and {{auth_note}}."""
    out, stack = [], []
    for line in text.splitlines(keepends=True):
        m = MARK.match(line.rstrip("\r\n"))
        if m and m["end"]:
            stack.pop()
        elif m:
            stack.append(holds(m["cond"], ctx))
        elif all(stack):
            out.append(line)
    if stack:
        raise ValueError("unbalanced @@ markers")
    return "".join(out).replace("{{name}}", ctx["name"]).replace("{{auth_note}}", AUTH_NOTE[ctx["auth"]])


def scaffold(lang, name, auth, http, out):
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,40}", name):
        raise ValueError("--name must be lowercase letters, digits and hyphens, starting with a letter (2-41 characters)")
    if auth != "none" and not http:
        raise ValueError(f"--auth {auth} protects the HTTP channel: add --http")
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"{out} is not empty")
    ctx = {"lang": lang, "name": name, "auth": auth, "http": http}
    src = SKILL / "templates" / {"py": "python", "ts": "typescript"}[lang]
    files = {p.relative_to(src).as_posix(): p for p in sorted(src.rglob("*")) if p.is_file()}
    files[".github/workflows/ci.yml"] = SKILL / "templates" / "ci" / "mcp-server.yml"
    for rel, p in files.items():
        if p.suffix not in TEXT and p.name not in TEXT:
            continue
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(render(p.read_text(encoding="utf-8"), ctx).encode("utf-8"))   # bytes: LF on every host
    ignore = "__pycache__/\n*.pyc\n" if lang == "py" else "node_modules/\ndist/\n"
    (out / ".gitignore").write_bytes(ignore.encode())
    return sorted(files) + [".gitignore"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", choices=["py", "ts"], required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--auth", choices=["none", "oauth", "header"], default="none")
    ap.add_argument("--http", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        made = scaffold(a.lang, a.name, a.auth, a.http, a.out)
    except ValueError as e:
        print(f"scaffold_server: {e}", file=sys.stderr)
        return 2
    print(f"wrote {len(made)} files to {a.out}")
    print("next: pip install . && python -m unittest discover -s tests" if a.lang == "py" else
          "next: npm install --ignore-scripts && npm run build && npm test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
