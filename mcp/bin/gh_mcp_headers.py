#!/usr/bin/env python3
"""gh_mcp_headers.py HOST: print {"Authorization":"Bearer <token>"} for an MCP `headersHelper`.

The token is whatever `gh auth token --hostname HOST` prints: no new secret, nothing stored in a file. The JSON
object is the only thing written to stdout (no newline); problems go to stderr and never contain the token.
Exit 0 on success, 1 when gh is missing or holds no token for HOST, 2 on a malformed HOST.
"""
import json
import os
import re
import subprocess
import sys

HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*(:\d+)?")


def which(command):
    """command on PATH only (honours PATHEXT), never the current directory: a helper often starts inside a
    repository, and shutil.which would run a gh.exe planted there on Windows."""
    exts = (os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").lower().split(";") if os.name == "nt" else []) + [""]
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if d and os.path.isabs(d):
            for ext in exts:
                c = os.path.join(d, command + ext)
                if os.path.isfile(c):
                    return c
    return None


def gh_token(host):
    """The gh token for host, or None. The caller checks HOST_RE first, so a host can never be read as an option."""
    gh = which("gh")
    if not gh:
        return None
    try:
        r = subprocess.run([gh, "auth", "token", "--hostname", host], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    token = r.stdout.strip()
    return token if r.returncode == 0 and token else None


def main(argv):
    host = argv[1] if len(argv) > 1 else "github.com"
    if not HOST_RE.fullmatch(host):
        print("gh_mcp_headers: HOST must be a host name such as github.com", file=sys.stderr)
        return 2
    token = gh_token(host)
    if not token:
        print(f"gh_mcp_headers: no gh token for {host}; run: gh auth login --hostname {host}", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps({"Authorization": "Bearer " + token}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
