#!/usr/bin/env python3
"""profile.py: per-client Claude Code profiles. Each has its own config folder, KB and knowledge index, so nothing
from one client's work is visible in another's sessions (Python 3.10+, stdlib only).

  profile.py create NAME [--kb DIR] [-- install.py options]   e.g. -- --profile corporate --git-hosts git.example.com
  profile.py list [--json]
  profile.py remove NAME [--purge-kb]                         uninstalls that copy; the KB stays unless --purge-kb
  profile.py launch NAME [-- claude arguments]                runs claude with that profile's config folder

Folders: <home>/.claude-profiles/<name>/{config,kb}; its index <LAD>/doc-index/knowledge-<name>/index.sqlite. The
registry is <main install>/workbench/profiles.json; the guard accepts a CLAUDE_CONFIG_DIR registered there. The KB
stays local unless --kb points at the client's (or employer's) approved cloud folder. Exit: 0 ok, 2 usage, else the
installer's or claude's exit code.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import install as I  # noqa: E402
from setup import jload, jwrite, now  # noqa: E402

NAME = re.compile(r"[a-z0-9-]{1,32}")


def main_home():
    """The main install's config folder: the one this kit copy recorded, else CLAUDE_CONFIG_DIR or ~/.claude."""
    rec = jload(I.REPO / I.RECORD, {}) or {}
    return Path(rec["claude_home"]) if rec.get("claude_home") else I.claude_home()


def registry():
    p = main_home() / "workbench" / "profiles.json"
    return p, jload(p, {"version": 1, "profiles": []}) or {"version": 1, "profiles": []}


def find(name):
    p, reg = registry()
    return next((x for x in reg["profiles"] if x["name"] == name), None)


def install(config_dir, kb, args):
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(config_dir), "WORKBENCH_KB_ROOT": str(kb)}
    return subprocess.run([sys.executable, str(HERE / "install.py"), *args], env=env).returncode


def create(name, kb, extra):
    if not NAME.fullmatch(name):
        print("a profile name is 1-32 characters of a-z, 0-9 and -")
        return 2
    if find(name):
        print(f"profile {name} already exists")
        return 2
    base = Path.home() / ".claude-profiles" / name
    cfg_dir, kb_dir = base / "config", Path(os.path.abspath(kb)) if kb else base / "kb"
    if I.in_onedrive(cfg_dir):
        print(f"{I.fwd(cfg_dir)} is inside OneDrive: a config folder must stay local")
        return 2
    cfg_dir.mkdir(parents=True, exist_ok=True)
    rc = install(cfg_dir, kb_dir, ["--apply", "--kb-root", str(kb_dir), "--data-root", str(base), *extra])
    if rc != 0:
        print(f"install into the profile exited {rc}; the profile was not registered ({I.fwd(base)} kept for a look)")
        return rc
    wb, main_wb = cfg_dir / "workbench", main_home() / "workbench"
    if (main_wb / "corporate-allowlist.json").is_file():
        shutil.copyfile(main_wb / "corporate-allowlist.json", wb / "corporate-allowlist.json")
    db = I.lad() / "doc-index" / f"knowledge-{name}" / "index.sqlite"
    cfg = jload(wb / "config.json", {}) or {}
    jwrite(wb / "config.json", {**cfg, "knowledge_db": I.fwd(db), "profile_of": I.fwd(main_home())})
    p, reg = registry()
    reg["profiles"].append({"name": name, "config_dir": I.fwd(cfg_dir), "kb_root": I.fwd(kb_dir),
                            "knowledge_db": I.fwd(db), "created": now()})
    jwrite(p, reg)
    print(f"profile {name}: config {I.fwd(cfg_dir)}, KB {I.fwd(kb_dir)}. Start it with: profile.py launch {name}")
    return 0


def remove(name, purge_kb):
    prof = find(name)
    if not prof:
        print(f"no profile {name}")
        return 2
    cfg_dir = Path(prof["config_dir"])
    rc = install(cfg_dir, prof["kb_root"], ["--uninstall", "--apply"]) if cfg_dir.exists() else 0
    if rc != 0:
        print(f"uninstall of the profile exited {rc}: it stays registered; fix that first")
        return rc
    shutil.rmtree(cfg_dir, ignore_errors=True)
    shutil.rmtree(Path(prof["knowledge_db"]).parent, ignore_errors=True)    # the profile's own index (a cache)
    if purge_kb:
        shutil.rmtree(prof["kb_root"], ignore_errors=True)
    base = cfg_dir.parent
    for d in (base / "captured", base / "backup", base):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    p, reg = registry()
    reg["profiles"] = [x for x in reg["profiles"] if x["name"] != name]
    jwrite(p, reg)
    print(f"profile {name} removed" + ("" if purge_kb else f"; its KB stays at {prof['kb_root']}"))
    return 0


def launch(name, args):
    prof = find(name)
    if not prof:
        print(f"no profile {name}")
        return 2
    claude = shutil.which("claude")
    if not claude:
        print("the claude CLI is not on PATH")
        return 2
    env = {**os.environ, "CLAUDE_CONFIG_DIR": prof["config_dir"], "WORKBENCH_KB_ROOT": prof["kb_root"]}
    return subprocess.run([claude, *args], env=env).returncode


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    argv = argv[:argv.index("--")] if "--" in argv else argv
    ap = argparse.ArgumentParser(description="per-client Claude Code profiles")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create")
    p.add_argument("name")
    p.add_argument("--kb")
    p = sub.add_parser("list")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("remove")
    p.add_argument("name")
    p.add_argument("--purge-kb", action="store_true")
    p = sub.add_parser("launch")
    p.add_argument("name")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    if a.cmd == "create":
        return create(a.name, a.kb, rest)
    if a.cmd == "remove":
        return remove(a.name, a.purge_kb)
    if a.cmd == "launch":
        return launch(a.name, rest)
    reg = registry()[1]
    if a.json:
        print(json.dumps(reg, indent=2))
    else:
        for x in reg["profiles"]:
            print(f"{x['name']:<20} {x['config_dir']}  KB {x['kb_root']}")
        if not reg["profiles"]:
            print("no profiles yet: profile.py create <name>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
