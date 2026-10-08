#!/usr/bin/env python3
"""mcp_healer.py: keep user-scope MCP servers matching a golden config, and probe them for real.

  python mcp_healer.py apply --golden golden-config.json [--dry-run]   reconcile .claude.json
  python mcp_healer.py unpark NAME                                     restore a parked server
  python mcp_healer.py check [--json] [--cwd DIR] [--project DIR]      probe your user-scope servers

apply: only servers named in the golden file are touched. Actions: "ensure" (build or update),
"remove", "park" (move the definition to mcpServersParked, a key Claude Code ignores, so it costs
nothing at startup and its env stays in the file), "ignore". Timestamped backup, write to .tmp,
re-parse, check the server set, then atomic replace. Server names and reasons are printed, values
never. If a managed MCP policy is in force, apply runs as a dry run and names the policy: managed
settings always win and this tool never works around them.

check: probes ONLY the servers in your own user-scope config. Stdio servers are launched with a
minimal environment (OS essentials plus the variables named in that server's own "env" block),
from an empty temporary directory unless --cwd is given, and their command is resolved on PATH
only (never the current directory); each gets a JSON-RPC `initialize`. HTTP servers get an
`initialize` POST (the one network call, made only when you run it). Servers that managed
allowedMcpServers / deniedMcpServers would block are skipped, not launched. A repository's
.mcp.json is never launched or expanded: --project only LISTS its server names. Exit code 1 if
anything is DOWN. Config changes take effect on the next Claude Code restart. Stdlib only.
"""
import argparse, datetime, fnmatch, glob, json, os, re, shutil, subprocess, sys, tempfile, threading, urllib.error, urllib.request

OK, DEGRADED, DOWN, SKIP = "OK", "DEGRADED", "DOWN", "SKIP"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
# Variables a process needs to start at all on Windows/Linux. Nothing secret; everything else is dropped.
BASE_ENV = ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE",
            "APPDATA", "LOCALAPPDATA")
MANAGED_KEYS = ("allowManagedMcpServersOnly", "allowedMcpServers", "deniedMcpServers",
                "managedMcpServers", "strictPluginOnlyCustomization")


def config_path():
    # ASSUMED: with CLAUDE_CONFIG_DIR set, Claude Code keeps .claude.json inside that dir.
    d = os.environ.get("CLAUDE_CONFIG_DIR")
    return os.path.join(os.path.expanduser(d), ".claude.json") if d else os.path.expanduser("~/.claude.json")


def managed_dir():
    if os.name == "nt":
        return r"C:\Program Files\ClaudeCode"
    return "/Library/Application Support/ClaudeCode" if sys.platform == "darwin" else "/etc/claude-code"


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def managed_mcp_policy(mdir=None):
    """Return 'file: reason' strings for any file-based managed MCP control (registry and
    server-delivered policy are invisible here; `/status` shows those)."""
    mdir = mdir or managed_dir()
    found = []
    if os.path.exists(os.path.join(mdir, "managed-mcp.json")):
        found.append(os.path.join(mdir, "managed-mcp.json") + ": managed MCP servers deployed")
    files = [os.path.join(mdir, "managed-settings.json")] + sorted(glob.glob(os.path.join(mdir, "managed-settings.d", "*.json")))
    for f in files:
        try:
            s = load(f)
        except (OSError, ValueError):
            continue
        for k in MANAGED_KEYS:
            v = s.get(k)
            if k == "strictPluginOnlyCustomization" and not (v is True or (isinstance(v, list) and any("mcp" in str(x).lower() for x in v))):
                continue
            if v not in (None, False, []):
                found.append(f"{f}: {k}")
    return found


def managed_lists(mdir=None):
    """(allowed or None, denied) entries from file-based managed settings.
    ponytail: allowlists from several managed files are unioned; Claude Code takes the
    highest-ranked one, so this may probe a server Claude Code would block. Denials are unioned too."""
    mdir = mdir or managed_dir()
    allowed, denied = None, []
    for f in [os.path.join(mdir, "managed-settings.json")] + sorted(glob.glob(os.path.join(mdir, "managed-settings.d", "*.json"))):
        try:
            s = load(f)
        except (OSError, ValueError):
            continue
        if isinstance(s.get("allowedMcpServers"), list):
            allowed = (allowed or []) + s["allowedMcpServers"]
        denied += s.get("deniedMcpServers") or []
    return allowed, denied


def _matches(entry, name, spec):
    if not isinstance(entry, dict):
        return False
    if "serverName" in entry:
        return entry["serverName"] == name
    if "serverCommand" in entry:
        return entry["serverCommand"] == [spec.get("command")] + list(spec.get("args") or [])
    if "serverUrl" in entry:
        return bool(spec.get("url")) and fnmatch.fnmatch(spec["url"], entry["serverUrl"])
    return False


def policy_blocks(name, spec, allowed, denied):
    if any(_matches(e, name, spec) for e in denied):
        return "denied by managed deniedMcpServers"
    if allowed is not None and not any(_matches(e, name, spec) for e in allowed):
        return "not in managed allowedMcpServers"
    return None


def resolve(command):
    """Absolute path of a command found on PATH only: never the current directory, so a file
    planted in a repository cannot stand in for npx, node or python."""
    if os.path.isabs(command):
        return command if os.path.exists(command) else None
    if os.sep in command or "/" in command:
        return None
    exts = [""] + (os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").lower().split(";") if os.name == "nt" else [])
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d or not os.path.isabs(d):
            continue
        for ext in exts:
            c = os.path.join(d, command + ext)
            if os.path.isfile(c):
                return c
    return None


def probe_env(spec):
    env = {k: os.environ[k] for k in BASE_ENV if k in os.environ}
    env.update({k: expand(v) for k, v in (spec.get("env") or {}).items()})
    return env


def build(name, spec, existing):
    """Desired server object for an 'ensure' entry, or (None, why) when it cannot be built."""
    if spec.get("preserveExisting"):
        if existing is None:
            return None, "not configured and preserveExisting is set (add it once by hand or via `claude mcp add`)"
        obj = json.loads(json.dumps(existing))
        for k, v in (spec.get("setEnv") or {}).items():
            obj.setdefault("env", {})[k] = v
    else:
        obj = {k: spec[k] for k in ("type", "command", "args", "url", "headers") if k in spec}
        env = {}
        for k, ev in (spec.get("env") or {}).items():
            if isinstance(ev, dict) and "fromExisting" in ev:   # keep a secret already in the live entry
                val = ((existing or {}).get("env") or {}).get(ev["fromExisting"])
                if not val:
                    return None, f"env {k}: no value to keep in the live entry; set it once by hand"
                env[k] = val
            elif isinstance(ev, dict) and "literal" in ev:
                env[k] = ev["literal"]
            else:
                env[k] = ev
        if env:
            obj["env"] = env
        if any("{{" in str(v) for v in [obj.get("command", "")] + list(obj.get("args", []))):
            return None, "golden entry still has a {{PLACEHOLDER}}; fill it in first"
    if "alwaysLoad" in spec:
        obj["alwaysLoad"] = spec["alwaysLoad"]
    elif existing and "alwaysLoad" in existing:
        obj["alwaysLoad"] = existing["alwaysLoad"]
    return obj, "preserve + tweak" if spec.get("preserveExisting") else "rebuild"


def plan(golden, cfg):
    """Mutates cfg toward golden; returns (changes, warnings)."""
    servers = cfg.setdefault("mcpServers", {})
    parked = cfg.setdefault("mcpServersParked", {})
    changes, warnings = [], []
    for name, spec in (golden.get("servers") or {}).items():
        action, reason, existing = spec.get("action", "ensure"), spec.get("reason", ""), servers.get(name)
        if action == "remove":
            if existing is not None:
                changes.append(f"REMOVE  {name}  - {reason}")
                del servers[name]
            if name in parked:
                changes.append(f"REMOVE  {name} (parked)  - {reason}")
                del parked[name]
        elif action == "park":
            if existing is not None:
                changes.append(f"PARK    {name}  - {reason}")
                parked[name] = servers.pop(name)
        elif action == "ensure":
            if existing is None and name in parked:
                changes.append(f"UNPARK  {name}  - golden says ensure")
                servers[name] = parked.pop(name)
                continue
            obj, why = build(name, spec, existing)
            if obj is None:
                warnings.append(f"SKIPPED {name}  - {why}")
            elif obj != existing:
                changes.append(f"ENSURE  {name}  ({why})  - {reason}")
                servers[name] = obj
        elif action != "ignore":
            warnings.append(f"UNKNOWN action '{action}' for {name}")
    if not parked:
        del cfg["mcpServersParked"]
    return changes, warnings


def write(cfg, path, expect):
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = f"{path}.heal-bak-{ts}"
    shutil.copy2(path, bak)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    try:
        if set(load(tmp).get("mcpServers", {})) != expect:
            raise ValueError("server set changed during write")
    except ValueError as e:
        os.remove(tmp)
        print(f"VALIDATION FAILED ({e}); live file untouched. Backup: {bak}")
        return False
    os.replace(tmp, path)
    print(f"Wrote {path}\nBackup: {bak}\nRestart Claude Code to load the change.")
    return True


def cmd_apply(a):
    golden, cfg = load(a.golden), load(a.config)
    changes, warnings = plan(golden, cfg)
    for w in warnings:
        print("  " + w)
    if not changes:
        print("OK: config already matches the golden file.")
        return 0
    policy = managed_mcp_policy(a.managed_dir)
    print(("Planned" if a.dry_run or policy else "Applying") + " changes:")
    for c in changes:
        print("  " + c)
    if policy:
        print("Managed MCP policy in force; not writing (managed settings win):")
        for p in policy:
            print("  " + p)
        return 3
    if a.dry_run:
        print("(dry run: nothing written)")
        return 0
    return 0 if write(cfg, a.config, set(cfg.get("mcpServers", {}))) else 1


def cmd_unpark(a):
    cfg = load(a.config)
    parked = cfg.get("mcpServersParked") or {}
    if a.name not in parked:
        print(f"'{a.name}' is not parked. Parked: {', '.join(sorted(parked)) or '(none)'}")
        return 1
    cfg.setdefault("mcpServers", {})[a.name] = parked.pop(a.name)
    print(f"UNPARK {a.name} (the next apply re-parks it while the golden file says park)")
    return 0 if write(cfg, a.config, set(cfg["mcpServers"])) else 1


def expand(v):
    """Claude Code's ${VAR} and ${VAR:-default} expansion, so the probe launches what it launches."""
    return re.sub(r"\$\{(\w+)(?::-([^}]*))?\}", lambda m: os.environ.get(m.group(1), m.group(2) or ""), str(v))


def handshake(spec, cwd, timeout):
    command = expand(spec.get("command") or "")
    if not command:
        return SKIP, "no command"
    exe = resolve(command)
    if not exe:
        return DOWN, f"launcher not found on PATH: {command}"
    cmd = [exe] + [expand(x) for x in spec.get("args") or []]
    env = probe_env(spec)
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "mcp-healer", "version": "1"}}}
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             env=env, cwd=cwd, text=True, encoding="utf-8", errors="ignore", creationflags=NO_WINDOW)
    except OSError as e:
        return DOWN, f"launch failed: {str(e)[:80]}"
    got = {}

    def reader():
        for line in p.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("id") == 1:
                got["msg"] = msg
                return

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        p.stdin.write(json.dumps(init) + "\n")
        p.stdin.flush()
    except OSError:
        pass
    t.join(timeout)
    try:  # reader finished without an answer = stdout closed = the process is exiting
        rc = p.wait(timeout=2) if not t.is_alive() and "msg" not in got else p.poll()
    except subprocess.TimeoutExpired:
        rc = None
    p.kill()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    for f in (p.stdin, p.stdout):
        try:
            f.close()
        except OSError:
            pass
    m = got.get("msg")
    if m and "result" in m:
        si = (m["result"] or {}).get("serverInfo") or {}
        return OK, f"handshake ok ({si.get('name', '?')} {si.get('version', '')})".strip()
    if m:
        return DOWN, "initialize error: " + str((m.get("error") or {}).get("message", ""))[:80]
    return (DOWN, f"exited rc={rc} before handshake") if rc is not None else (DEGRADED, f"no answer in {timeout}s (first-run download?)")


def http_probe(spec, timeout):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                  "clientInfo": {"name": "mcp-healer", "version": "1"}}}).encode()
    hdr = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    hdr.update({k: expand(v) for k, v in (spec.get("headers") or {}).items()})
    try:
        with urllib.request.urlopen(urllib.request.Request(expand(spec["url"]), body, hdr, method="POST"), timeout=timeout) as r:
            return OK, f"initialize -> {r.status}"
    except urllib.error.HTTPError as e:
        return (DEGRADED, f"initialize -> {e.code} (needs sign-in or a key)") if e.code in (401, 403) else (DOWN, f"initialize -> {e.code}")
    except Exception as e:
        return DOWN, f"unreachable: {str(e)[:80]}"


def probe(name, spec, cwd, timeout, allowed=None, denied=()):
    if spec.get("disabled"):
        return SKIP, "disabled"
    blocked = policy_blocks(name, spec, allowed, denied)
    if blocked:
        return SKIP, blocked
    if spec.get("type") in ("http", "sse") or (spec.get("url") and not spec.get("command")):
        return http_probe(spec, timeout) if spec.get("url") else (DOWN, "no url")
    return handshake(spec, cwd, timeout)


def cmd_check(a):
    cfg = load(a.config)
    servers = dict(cfg.get("mcpServers") or {})   # user scope only: your own configuration
    allowed, denied = managed_lists(a.managed_dir)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as empty:
        cwd = a.cwd or empty
        rows = [(n, *probe(n, s, cwd, a.timeout, allowed, denied)) for n, s in sorted(servers.items())]
    rows += [(n, SKIP, "parked") for n in sorted(cfg.get("mcpServersParked") or {})]
    if a.project:   # list only: a repository's servers are never launched, fetched or expanded here
        pj = os.path.join(a.project, ".mcp.json")
        try:
            names = sorted((load(pj).get("mcpServers") or {}))
        except (OSError, ValueError):
            names = []
        rows += [(f"{n} (project, not probed)", SKIP, "listed only; Claude Code asks before it trusts project servers") for n in names]
    if a.json:
        print(json.dumps([{"server": n, "status": s, "detail": d} for n, s, d in rows], indent=1))
    else:
        for n, s, d in rows:
            print(f"{s:<9}{n:<32}{d}")
        if not rows:
            print("no MCP servers configured")
    return 1 if any(s == DOWN for _, s, _ in rows) else 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=config_path(), help="path to .claude.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("apply")
    p.add_argument("--golden", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--managed-dir", default=None, help=argparse.SUPPRESS)
    p = sub.add_parser("unpark")
    p.add_argument("name")
    p = sub.add_parser("check")
    p.add_argument("--json", action="store_true")
    p.add_argument("--cwd", default=None, help="directory stdio servers start in (default: an empty temp dir; "
                                                    "give your repo for servers that need one)")
    p.add_argument("--project", help="LIST (never launch) the servers in <dir>/.mcp.json")
    p.add_argument("--timeout", type=int, default=45)
    p.add_argument("--managed-dir", default=None, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    return {"apply": cmd_apply, "unpark": cmd_unpark, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
