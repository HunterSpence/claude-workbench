#!/usr/bin/env python3
"""check_plugin.py: the plugin-review rules as a gate for your own plugin repository (a copy sits in generated repos).

  check_plugin.py PATH [--target cli|web|all] [--json]

PATH is a plugin folder, or a marketplace repository root: then the marketplace file is checked and so is every
plugins/* folder. The default target is the plugin's own metadata.surfaces in plugin.json ("cli" or "all"), else all.
Exit 0 when there is no block or hold finding, 1 otherwise, 2 for a usage error. Stdlib only; imports plugin_rules.py
from its own folder (generated repos) or from the plugin-review skill (the kit).
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for d in (HERE, HERE.parent.parent / "plugin-review" / "scripts"):
    if (d / "plugin_rules.py").is_file():
        sys.path.insert(0, str(d))
        break
import plugin_rules as R  # noqa: E402


def check(path, target=None):
    """-> [(name, target, findings)] for a plugin folder or a marketplace root."""
    path = Path(path)
    out = []
    if (path / ".claude-plugin" / "marketplace.json").is_file() and not (path / ".claude-plugin" / "plugin.json").is_file():
        root = R.Plugin(path)
        out.append((path.name or ".", target or "all", [f for f in R.run_rules(root, [r for r in R.RULES if r[1] == 2])]))
        for d in sorted((path / "plugins").glob("*/")) if (path / "plugins").is_dir() else []:
            out += check(d, target)
        return out
    p = R.Plugin(path)
    meta = p.manifest.get("metadata") if isinstance(p.manifest.get("metadata"), dict) else {}
    t = target or {"cli": "cli", "all": "all"}.get(str(meta.get("surfaces")), "all")
    out.append((path.name, t, R.run_rules(p, target=t)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--target", choices=["cli", "web", "all"])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not Path(a.path).is_dir():
        print(f"check_plugin: {a.path} is not a folder", file=sys.stderr)
        return 2
    results = check(a.path, a.target)
    failed = any(f["severity"] in ("block", "hold") for _n, _t, fs in results for f in fs)
    if a.json:
        print(json.dumps({"rules_sha256": R.rules_sha256(), "passed": not failed,
                          "results": [{"name": n, "target": t, "findings": fs} for n, t, fs in results]}, indent=1))
    else:
        for n, t, fs in results:
            bad = [f for f in fs if f["severity"] in ("block", "hold")]
            print(f"{'FAIL' if bad else 'ok  '} {n} (target {t}): {len(bad)} block/hold, {len(fs) - len(bad)} warn/note")
            for f in fs:
                if f["severity"] in ("block", "hold", "warn"):
                    print(f"  {f['severity']:5} {f['rule']} {f['file']}:{f['line']} {f['msg']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
