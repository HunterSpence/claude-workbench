"""Managed-policy snapshot: hash the managed Claude settings and managed MCP config on this machine, derive five
classes, and compare them with the snapshot saved at setup.

    policy_snapshot.py [--write] [--json]

--json prints {"version", "generated", "sha256", "classes": {...}, "changed": [class names that differ from the saved
snapshot]}; --write saves it as <workbench home>/state/policy-snapshot.json. Exit 0 except a usage error (2). Read-only
except --write; stdlib only. Sources, the same ones the installer reads: managed-settings.json and managed-settings.d/*.json
and managed-mcp.json in the platform folder (Windows: %ProgramFiles%\\ClaudeCode), files named in WORKBENCH_MANAGED_SETTINGS,
and on Windows the HKLM / HKCU SOFTWARE\\Policies\\ClaudeCode "Settings" value. WORKBENCH_POLICY_DIRS (os.pathsep list)
replaces the folders and skips the registry; tests and support use it. An unreadable file counts as present."""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wb  # noqa: E402

CLASSES = ("hooks_locked", "marketplaces_closed", "models_restricted", "mcp_restricted", "permissions_locked")


def _read(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {"_unreadable": str(p)}
    except (OSError, ValueError):
        return {"_unreadable": str(p)}


def _dirs():
    if os.environ.get("WORKBENCH_POLICY_DIRS"):
        return [Path(d) for d in os.environ["WORKBENCH_POLICY_DIRS"].split(os.pathsep) if d]
    if os.name == "nt":
        return [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ClaudeCode"]
    if sys.platform == "darwin":
        return [Path("/Library/Application Support/ClaudeCode")]
    return [Path("/etc/claude-code"), Path("/mnt/c/Program Files/ClaudeCode")]


def sources():
    """([managed settings documents], [managed MCP documents])."""
    settings, mcp = [], []
    for d in _dirs():
        files = [d / "managed-settings.json"] + (sorted((d / "managed-settings.d").glob("*.json"))
                                                  if (d / "managed-settings.d").is_dir() else [])
        settings += [_read(f) for f in files if f.is_file()]
        mcp += [_read(f) for f in [d / "managed-mcp.json"] if f.is_file()]
    if not os.environ.get("WORKBENCH_POLICY_DIRS"):
        settings += [_read(f) for f in (os.environ.get("WORKBENCH_MANAGED_SETTINGS") or "").split(os.pathsep)
                     if f and os.path.isfile(f)]
        if os.name == "nt":
            try:
                import winreg
                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(hive, r"SOFTWARE\Policies\ClaudeCode") as k:
                            v, _ = winreg.QueryValueEx(k, "Settings")
                        settings.append(json.loads(v) if v else {})
                    except (OSError, ValueError):
                        continue
            except ImportError:
                pass
    return settings, mcp


def classes(settings, mcp):
    m = {}
    for d in settings:
        m.update(d)
    perms = m.get("permissions") if isinstance(m.get("permissions"), dict) else {}
    return {
        "hooks_locked": m.get("allowManagedHooksOnly") is True or m.get("disableAllHooks") is True,
        "marketplaces_closed": "strictKnownMarketplaces" in m,
        "models_restricted": bool(m.get("availableModels") or m.get("deniedModels")),
        "mcp_restricted": bool(mcp or m.get("allowedMcpServers") or m.get("deniedMcpServers")
                               or m.get("allowManagedMcpServersOnly") is True),
        "permissions_locked": m.get("allowManagedPermissionRulesOnly") is True
        or perms.get("disableBypassPermissionsMode") == "disable",
    }


def saved_path():
    return _wb.workbench_home() / "state" / "policy-snapshot.json"


def snapshot():
    settings, mcp = sources()
    blob = json.dumps({"settings": settings, "mcp": mcp}, sort_keys=True, separators=(",", ":"), default=str)
    return {"version": 1, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "sha256": hashlib.sha256(blob.encode("utf-8")).hexdigest(), "classes": classes(settings, mcp)}


def status():
    """snapshot() plus "changed": the classes whose value differs from the saved snapshot ([] when none is saved)."""
    snap = snapshot()
    old = _read(saved_path()).get("classes") if saved_path().is_file() else None
    snap["changed"] = [k for k in CLASSES if isinstance(old, dict) and bool(old.get(k)) != snap["classes"][k]]
    return snap


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="policy_snapshot.py", description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true", help="save the snapshot to <workbench home>/state/policy-snapshot.json")
    ap.add_argument("--json", action="store_true", help="print the snapshot as JSON")
    a = ap.parse_args(argv)
    snap = status()
    if a.write:
        p = saved_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps({k: v for k, v in snap.items() if k != "changed"}, indent=2), encoding="utf-8")
            os.replace(tmp, p)
        except OSError as e:
            print(f"could not save {p}: {e}", file=sys.stderr)
    if a.json:
        print(json.dumps(snap, indent=2))
    else:
        on = [k for k in CLASSES if snap["classes"][k]]
        print(f"managed policy {snap['sha256'][:12]}: " + (", ".join(on) or "nothing restricted")
              + ("; changed since setup: " + ", ".join(snap["changed"]) if snap["changed"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
