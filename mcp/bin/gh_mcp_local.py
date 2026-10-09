#!/usr/bin/env python3
"""gh_mcp_local.py HOST [--install]: run the local github-mcp-server over stdio, read-only, with your gh token.

Use it when an organisation IP allow list blocks the hosted endpoint (the local binary calls the API from your own
network), or for a GitHub Enterprise Server host (experimental: GitHub documents it, Anthropic's own GHES page says
use the gh CLI). Claude Code runs it as the server command, so stdout is the MCP pipe: every message goes to stderr.

  gh_mcp_local.py github.com            token from `gh auth token --hostname HOST`, then
                                        github-mcp-server stdio --read-only --lockdown-mode
                                        --toolsets=context,repos,issues,pull_requests,actions
  gh_mcp_local.py HOST --install        download the pinned release, verify its SHA-256, unpack the binary

The token and GITHUB_HOST exist only in the child's environment (GITHUB_HOST is set for hosts other than github.com).
Every GITHUB_* variable you already have is dropped first: the server lets an environment variable beat a flag, so an
inherited GITHUB_TOOLSETS or GITHUB_READ_ONLY could otherwise undo the flags above. The binary lives in
<workbench>/bin (WB_GH_MCP_BIN names another file); a binary on PATH is the fallback.
"""
import argparse
import hashlib
import io
import os
import platform
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gh_mcp_headers  # noqa: E402

VERSION = "v2.0.1"
BASE = f"https://github.com/github/github-mcp-server/releases/download/{VERSION}/"
# Asset SHA-256 values as published with the release (GitHub's own digest of each asset). Move deliberately: new
# tag, new digests. Other platforms: build from source or put a binary on PATH.
PINS = {
    ("Windows", "x86_64"): ("github-mcp-server_Windows_x86_64.zip",
                            "ec37110134fd94f2980ae78ed0d69493623e730da97f0983050cc46539c30a30"),
    ("Linux", "x86_64"): ("github-mcp-server_Linux_x86_64.tar.gz",
                          "f39c3cf56e9b2883b64e30215a48a120d911e4ed0cd6a83dddae1260279b02e6"),
}
SERVER_ARGS = ["stdio", "--read-only", "--lockdown-mode", "--toolsets=context,repos,issues,pull_requests,actions"]
EXE = "github-mcp-server.exe" if os.name == "nt" else "github-mcp-server"


def say(msg):
    print(f"gh_mcp_local: {msg}", file=sys.stderr)


def target_exe():
    """Where the binary is kept: WB_GH_MCP_BIN, else <workbench>/bin when this file sits in <workbench>/kit/mcp/bin."""
    if os.environ.get("WB_GH_MCP_BIN"):
        return Path(os.environ["WB_GH_MCP_BIN"])
    kit = Path(__file__).resolve().parents[2]
    return (kit.parent / "bin" / EXE) if kit.name == "kit" else Path(EXE)


def find_exe():
    t = target_exe()
    return str(t) if t.is_file() else gh_mcp_headers.which("github-mcp-server")


def child_env(host, token, environ=None):
    env = {k: v for k, v in (environ if environ is not None else os.environ).items() if not k.upper().startswith("GITHUB_")}
    env["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
    if host.lower() != "github.com":
        env["GITHUB_HOST"] = "https://" + host
    return env


def install(dest, pins=None, opener=urllib.request.urlopen, system=None, machine=None):
    """Download the pinned asset for this platform, check its SHA-256, write only the server binary to dest."""
    pins = PINS if pins is None else pins
    machine = {"AMD64": "x86_64", "x64": "x86_64"}.get(platform.machine(), platform.machine()) if machine is None else machine
    key = (system or platform.system(), machine)
    if key not in pins:
        raise SystemExit(f"gh_mcp_local: no pinned download for {key[0]} {key[1]}; build github-mcp-server from source or put it on PATH")
    asset, want = pins[key]
    with opener(BASE + asset) as r:
        blob = r.read()
    got = hashlib.sha256(blob).hexdigest()
    if got != want:
        raise SystemExit(f"gh_mcp_local: checksum mismatch for {asset} (wanted {want}, got {got}); nothing installed")
    name = "github-mcp-server.exe" if asset.endswith(".zip") else "github-mcp-server"
    if asset.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            data = next((z.read(n) for n in z.namelist() if Path(n).name == name), None)
    else:
        with tarfile.open(fileobj=io.BytesIO(blob)) as t:
            m = next((m for m in t.getmembers() if m.isfile() and Path(m.name).name == name), None)
            data = t.extractfile(m).read() if m else None
    if data is None:
        raise SystemExit(f"gh_mcp_local: {name} not found inside {asset}; nothing installed")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    os.chmod(tmp, 0o755)
    os.replace(tmp, dest)
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host", nargs="?", default="github.com")
    ap.add_argument("--install", action="store_true", help=f"fetch and verify the pinned release {VERSION}")
    a = ap.parse_args(argv)
    if not gh_mcp_headers.HOST_RE.fullmatch(a.host):
        say("HOST must be a host name such as github.com")
        return 2
    if a.install:
        say(f"installed {install(target_exe())} ({VERSION}, checksum verified)")
        return 0
    exe = find_exe()
    if not exe:
        say(f"github-mcp-server not found; run: {Path(sys.argv[0]).name} {a.host} --install")
        return 1
    token = gh_mcp_headers.gh_token(a.host)
    if not token:
        say(f"no gh token for {a.host}; run: gh auth login --hostname {a.host}")
        return 1
    return subprocess.run([exe, *SERVER_ARGS], env=child_env(a.host, token)).returncode


if __name__ == "__main__":
    sys.exit(main())
