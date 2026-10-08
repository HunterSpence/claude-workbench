#!/usr/bin/env python3
"""claude-workbench installer (Python 3.10+, stdlib only). This file IS the entry point:

  Windows:      py -3 bootstrap\\install.py [options]
  Linux / WSL:  python3 bootstrap/install.py [options]     (or: sh bootstrap/install.sh [options])

  --apply                       write the plan (without it nothing is written: the plan is printed)
  --profile corporate|permissive  settings profile (default corporate). permissive implies --upstream-plugins
  --upstream-plugins            also merge settings/upstream-plugins.fragment.json
  --upstream-plugins-optional   also merge settings/upstream-plugins.optional.fragment.json (never implied)
  --kb-root PATH                knowledge-base folder (default: the last install's, else ~/claude-kb)
  --git-hosts h1,h2             the git hosts company code may be pushed to (written to the corporate allowlist)
  --force                       replace settings keys you already set to something else
  --no-cli                      never call the claude CLI; print its commands instead
  --uninstall                   undo installs, newest first (also a dry run unless --apply)

No network, no admin rights, no git remote, no change to managed settings. Every changed file is backed up to
<workbench home>/backups/<timestamp>/ with a manifest that --uninstall replays. Paths: CLAUDE_HOME = CLAUDE_CONFIG_DIR
or ~/.claude; WORKBENCH_HOME = <CLAUDE_HOME>/workbench. The kit is copied to <WORKBENCH_HOME>/kit and the plugin
marketplace is registered from there, so the folder you unpacked can be moved or deleted afterwards.

Values with ONE owner, rewritten on every install (a change is printed as a warning): the KB root (env
WORKBENCH_KB_ROOT, permissions.additionalDirectories, config.json, the instruction text) and the Python path
(pluginConfigs of both plugins, the statusLine command, config.json).

Exit codes: 0 done (or dry run) · 1 unexpected error · 2 environment problem (old Python, unreadable settings.json,
bad option) · 3 blocked by your organisation's policy (ask your IT team) · 4 an apply step failed (see the output).
Test seam: WORKBENCH_MANAGED_SETTINGS (os.pathsep-separated JSON files) is read as an extra managed source.
"""
import argparse
import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VERSION = "0.2.0"
MARKETPLACE = "workbench"
PLUGIN_IDS = ("workbench-core@workbench", "workbench-kb@workbench")
BUILTIN_MARKETPLACES = {"claude-plugins-official": {"source": "github", "repo": "anthropics/claude-plugins-official"}}
KIT_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv", "venv", "node_modules", ".pytest_cache",
                                    "*.bak*", "installed-config.json")
RECORD = Path("plugins") / "workbench-core" / "scripts" / "installed-config.json"   # read by _wb.config_redirected()
ABSENT = {"__absent__": True}


class Stop(Exception):
    """A planned stop with an exit code and a message for the user."""
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def fwd(p):
    return str(p).replace("\\", "/")


def show(cmd):
    """A command as the user would type it in their own shell, every argument quoted as needed."""
    return subprocess.list2cmdline(cmd) if os.name == "nt" else shlex.join(cmd)


def sha(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def read_json(path):
    t = Path(path).read_text(encoding="utf-8-sig")
    d = json.loads(t) if t.strip() else {}
    if not isinstance(d, dict):
        raise ValueError(f"{path} does not hold a JSON object")
    return d


def decode_text(b):
    """(text, encoding, bom) of a user text file: UTF-8 (with or without BOM), else the Windows ANSI code page."""
    bom = b.startswith(b"\xef\xbb\xbf")
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return b[3:].decode(enc) if bom else b.decode(enc), enc, bom
        except UnicodeDecodeError:
            continue
    return b.decode("latin-1"), "latin-1", bom


def short_path(p):
    """The Windows 8.3 short form of an existing path (it has no spaces when 8.3 names are on), else p."""
    if os.name != "nt":
        return str(p)
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, 32768)
        return buf.value if 0 < n < 32768 else str(p)
    except Exception:
        return str(p)


def statusline_command(python, script):
    """A statusLine command that parses the same in Git Bash, PowerShell and cmd. Plain paths when they hold no space
    (Windows: their 8.3 short forms); else a PowerShell call with single-quoted paths, inside double quotes."""
    py, sl = (short_path(p) if " " in str(p) else str(p) for p in (python, script))
    if " " not in py + sl:
        return f"{fwd(py)} {fwd(sl)}"
    if os.name == "nt":
        q = lambda s: "'" + fwd(s).replace("'", "''") + "'"  # noqa: E731
        return f'powershell -NoProfile -NonInteractive -Command "& {q(python)} {q(script)}"'
    return f"{shlex.quote(fwd(python))} {shlex.quote(fwd(script))}"


# ── managed settings ─────────────────────────────────────────────────────────────────────────────────────────
def managed_sources():
    """[(label, dict)] for every managed source readable on this machine. Server-managed settings are never here."""
    out, files = [], []
    if os.name == "nt":
        files.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ClaudeCode" / "managed-settings.json")
    elif sys.platform == "darwin":
        files.append(Path("/Library/Application Support/ClaudeCode/managed-settings.json"))
    else:
        files.append(Path("/etc/claude-code/managed-settings.json"))
        files.append(Path("/mnt/c/Program Files/ClaudeCode/managed-settings.json"))   # WSL: the Windows side
    for f in list(files):
        d = f.with_name("managed-settings.d")
        if d.is_dir():
            files += sorted(d.glob("*.json"))
    files += [Path(p) for p in (os.environ.get("WORKBENCH_MANAGED_SETTINGS") or "").split(os.pathsep) if p]
    for f in files:
        if f.is_file():
            try:
                out.append((fwd(f), read_json(f)))
            except (OSError, ValueError) as e:
                out.append((f"{fwd(f)} (unreadable: {e}; treated as present)", {}))
    if os.name == "nt":
        try:
            import winreg
            for hive, name in ((winreg.HKEY_LOCAL_MACHINE, "HKLM"), (winreg.HKEY_CURRENT_USER, "HKCU")):
                try:
                    with winreg.OpenKey(hive, r"SOFTWARE\Policies\ClaudeCode") as k:
                        v, _ = winreg.QueryValueEx(k, "Settings")
                    out.append((f"{name}\\SOFTWARE\\Policies\\ClaudeCode", json.loads(v) if v else {}))
                except FileNotFoundError:
                    continue
                except (OSError, ValueError) as e:
                    out.append((f"{name} policy key (unreadable: {e})", {}))
        except ImportError:
            pass
    return out


def deep_merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            deep_merge(a[k], v)
        elif isinstance(v, list) and isinstance(a.get(k), list):
            a[k] = a[k] + [x for x in v if x not in a[k]]
        else:
            a[k] = v
    return a


def managed_has(managed, path, value=None):
    """True when a managed source sets this key as a SCALAR (or a scalar above it). Objects are checked per sub-key and
    arrays are not blocked: deny/allow arrays merge across scopes, so the kit's entries still apply beside the
    organisation's."""
    cur = managed
    for i, k in enumerate(path):
        if not isinstance(cur, dict) or k not in cur:
            return False
        cur = cur[k]
        if i < len(path) - 1 and not isinstance(cur, dict):
            return True
    if isinstance(cur, dict) and isinstance(value, dict):
        return False
    return not (isinstance(cur, list) and isinstance(value, list))


def _source_host(src):
    s = src.get("source")
    if s == "github":
        return "github.com"
    u = str(src.get("url") or "")
    m = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([^/:?#]+)", u, re.I) or re.match(r"^[^@/\s]+@([^:/\s]+):", u)
    return m.group(1).lower() if m else None


def marketplace_allowed(src, managed):
    """(allowed?, why) for a marketplace source under managed strictKnownMarketplaces / blockedMarketplaces."""
    def matches(entry):
        if not isinstance(entry, dict):
            return False
        es = entry.get("source")
        if es == "hostPattern":
            h = _source_host(src)
            return bool(h) and bool(re.search(entry.get("hostPattern") or "$^", h))
        if es == "pathPattern":
            return src.get("source") in ("file", "directory") and bool(re.search(entry.get("pathPattern") or "$^",
                                                                              str(src.get("path") or "")))
        if es != src.get("source"):
            return False
        if es == "github":
            repo, want = str(src.get("repo") or ""), str(entry.get("repo") or "")
            ok = want == repo or (want.endswith("/*") and repo.split("/")[0] == want[:-2])
            return ok and entry.get("ref") == src.get("ref") and (not entry.get("path") or entry.get("path") == src.get("path"))
        key = {"git": "url", "url": "url", "file": "path", "directory": "path"}.get(es)
        same = lambda x, y: fwd(x).rstrip("/").lower() == fwd(y).rstrip("/").lower() if key == "path" else x == y  # noqa: E731
        return bool(key) and same(str(entry.get(key) or ""), str(src.get(key) or "")) and entry.get("ref") == src.get("ref")
    for e in managed.get("blockedMarketplaces") or []:
        if matches(e):
            return False, "blocked by the managed blockedMarketplaces list"
    allow = managed.get("strictKnownMarketplaces", managed.get("allowedMarketplaces"))
    if allow is not None and not any(matches(e) for e in allow):
        return False, "not in the managed strictKnownMarketplaces allowlist"
    return True, ""


# ── settings merge ───────────────────────────────────────────────────────────────────────────────────────────
def merge_settings(user, frag, managed, force, ops, notes, path=()):
    """Merge frag into user in place: a key the user set is kept (unless force), arrays are unioned, a key a managed
    source sets as a scalar is skipped. Records undo ops; notes skipped keys as (path, why)."""
    for k, v in frag.items():
        if k == "$schema" and not path:
            continue
        p = path + (k,)
        dotted = ".".join(p)
        if managed_has(managed, p, v):
            notes.append((dotted, "set by a managed source"))
            continue
        if isinstance(v, dict) and (k not in user or isinstance(user[k], dict)):
            if k not in user:
                user[k] = {}
                ops.append({"op": "set", "path": list(p), "value": {}, "old": ABSENT, "container": True})
            merge_settings(user[k], v, managed, force, ops, notes, p)
        elif isinstance(v, list) and isinstance(user.get(k), list):
            add = [x for x in v if x not in user[k]]
            if add:
                user[k].extend(copy.deepcopy(add))
                ops.append({"op": "list-add", "path": list(p), "items": add})
        elif k not in user:
            user[k] = copy.deepcopy(v)
            ops.append({"op": "set", "path": list(p), "value": v, "old": ABSENT})
        elif user[k] != v:
            if force:
                ops.append({"op": "set", "path": list(p), "value": v, "old": user[k]})
                user[k] = copy.deepcopy(v)
                notes.append((dotted, "replaced (--force)"))
            else:
                notes.append((dotted, "you already set it (kept; --force replaces)"))


def own(user, path, value, managed, ops, notes, warnings):
    """Set a value the kit owns (KB root, Python path, statusLine) to its current value, whatever an earlier install
    wrote. A change is a warning; a managed scalar wins."""
    if managed_has(managed, tuple(path)):
        notes.append((".".join(path), "set by a managed source"))
        return
    cur = user
    for i, k in enumerate(path[:-1]):
        if k not in cur:
            cur[k] = {}
            ops.append({"op": "set", "path": list(path[:i + 1]), "value": {}, "old": ABSENT, "container": True})
        if not isinstance(cur[k], dict):
            notes.append((".".join(path), f"{'.'.join(path[:i + 1])} is not an object"))
            return
        cur = cur[k]
    old = cur.get(path[-1], ABSENT)
    if old == value:
        return
    if old is not ABSENT:
        warnings.append(f"{'.'.join(path)} changes from {json.dumps(old)} to {json.dumps(value)}")
    ops.append({"op": "set", "path": list(path), "value": value, "old": old})
    cur[path[-1]] = copy.deepcopy(value)


def undo_settings(user, ops):
    """Reverse merge ops on the CURRENT file: only values still equal to what the install wrote are touched."""
    for op in reversed(ops):
        *parents, last = op["path"]
        cur = user
        for k in parents:
            cur = cur.get(k) if isinstance(cur, dict) else None
        if not isinstance(cur, dict):
            continue
        if op["op"] == "list-remove":
            cur.setdefault(last, [])
            cur[last] += [x for x in op["items"] if x not in cur[last]]
            continue
        if last not in cur:
            continue
        if op["op"] == "list-add" and isinstance(cur[last], list):
            cur[last] = [x for x in cur[last] if x not in op["items"]]
            if not cur[last]:
                del cur[last]
        elif op["op"] == "set":
            if op.get("container"):
                if cur[last] == {}:
                    del cur[last]
            elif cur[last] == op["value"]:
                if op["old"] == ABSENT:
                    del cur[last]
                else:
                    cur[last] = op["old"]


def fill(text, values):
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def fill_json(obj, values):
    if isinstance(obj, str):
        return fill(obj, values)
    if isinstance(obj, list):
        return [fill_json(x, values) for x in obj]
    if isinstance(obj, dict):
        return {k: fill_json(v, values) for k, v in obj.items()}
    return obj


def store_python(exe):
    """True for the Microsoft Store Python and its App Execution Alias stub (both live under WindowsApps)."""
    return "\\windowsapps\\" in str(exe).replace("/", "\\").lower()


# ── the installer ────────────────────────────────────────────────────────────────────────────────────────────
class Installer:
    def __init__(self, a):
        self.a = a
        self.claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
        self.wb = self.claude_home / "workbench"
        self.kit = self.wb / "kit"
        self.python = fwd(sys.executable)
        try:
            self.prev = read_json(self.wb / "config.json")
        except (OSError, ValueError):
            self.prev = {}
        kb = a.kb_root or self.prev.get("kb_root") or str(Path.home() / "claude-kb")
        self.kb = Path(os.path.abspath(os.path.expanduser(kb)))
        self.upstream = a.upstream_plugins or a.profile == "permissive"
        self.values = {"CLAUDE_HOME": fwd(self.claude_home), "WORKBENCH_HOME": fwd(self.wb), "KB_ROOT": fwd(self.kb),
                       "PYTHON": f'"{self.python}"' if " " in self.python else self.python}
        self.sources = managed_sources()
        self.managed = {}
        for _, d in self.sources:
            deep_merge(self.managed, d)
        self.plan, self.warnings, self.actions, self.failures = [], [], [], []
        stamp, n = time.strftime("%Y%m%d-%H%M%S"), 0
        while (self.wb / "backups" / (stamp + (f"-{n}" if n else ""))).exists():   # two installs in one second
            n += 1
        self.stamp = stamp + (f"-{n}" if n else "")
        self.backup = self.wb / "backups" / self.stamp
        self.manifest = {"version": VERSION, "ts": self.stamp, "repo": fwd(REPO), "profile": a.profile, "files": [],
                         "created": [], "created_trees": [], "settings_ops": [], "cli": [], "no_cli": bool(a.no_cli)}
        self.claude = None if a.no_cli else shutil.which("claude")

    def todo(self, text, fn=None):
        self.plan.append(text)
        if fn:
            self.actions.append(fn)

    # ── file helpers that record what uninstall needs ──
    def back_up(self, path):
        path = Path(path)
        if any(f["path"] == fwd(path) for f in self.manifest["files"]):
            return
        entry = {"path": fwd(path), "existed": path.exists(), "backup": None}
        if path.exists():
            dst = self.backup / "files" / f"{len(self.manifest['files']):02d}-{path.name}"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dst)
            entry["backup"] = fwd(dst)
        self.manifest["files"].append(entry)

    def write_bytes(self, path, data):
        self.back_up(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(data)
        for f in self.manifest["files"]:
            if f["path"] == fwd(path):
                f["sha_after"] = sha(path)

    def write_file(self, path, text):
        self.write_bytes(path, text.encode("utf-8"))

    def create_file(self, path, text):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding="utf-8", newline="\n")
        self.manifest["created"].append({"path": fwd(path), "sha_after": sha(path)})

    def replace_tree(self, src, dst, substitute=None, ignore=None):
        if dst.exists():
            keep = self.backup / "trees" / dst.name
            if not keep.exists():
                shutil.copytree(dst, keep)
            self.manifest.setdefault("replaced_trees", []).append({"path": fwd(dst), "backup": fwd(keep)})
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=ignore)
        if substitute:
            for f in dst.rglob("*.md"):
                t = f.read_text(encoding="utf-8")
                n = substitute(t)
                if n != t:
                    f.write_text(n, encoding="utf-8", newline="\n")
        self.manifest["created_trees"].append(fwd(dst))

    # ── planning ──
    def build(self):
        self.check_policy()
        self.plan_kit()
        self.plan_instructions()
        self.plan_files()
        self.plan_kb()
        settings, ops, notes = self.plan_settings()
        self.todo(f"[settings] merge into {fwd(self.claude_home / 'settings.json')}: {len(ops)} change(s) planned"
                  + "".join(f"\n      skip {k}: {why}" for k, why in notes),
                  lambda: self.write_settings(settings, ops, notes))
        self.plan_plugins()

    def check_policy(self):
        m = self.managed
        ok, why = marketplace_allowed({"source": "directory", "path": fwd(self.kit)}, m)
        if not ok:
            raise Stop(3, f"Your organisation's plugin policy does not allow this kit ({why}). Nothing was changed. "
                          "Ask your IT team to allow the workbench plugins (or to deploy them centrally); do not work "
                          "around the policy.")
        if m.get("allowManagedHooksOnly") is True:
            self.warnings.append("Managed allowManagedHooksOnly is on: the workbench hooks (guards, session start, "
                                 "statusline) will NOT run unless your IT team force-enables workbench-core in managed "
                                 "enabledPlugins. Agents and skills still load.")

    def plan_kit(self):
        def record():   # before the plugin install, so the CLI's copy of the plugin carries it; part of the kit tree
            (self.kit / RECORD).write_text(json.dumps({"claude_home": fwd(self.claude_home)}, indent=2) + "\n",
                                           encoding="utf-8", newline="\n")
        if REPO.resolve() == self.kit.resolve():
            self.todo(f"[kit] running from the installed kit at {fwd(self.kit)}: kept in place")
        else:
            self.todo(f"[kit] copy this release to {fwd(self.kit)} (the plugins load from there, so the folder you "
                      "unpacked can be moved or deleted)", lambda: self.replace_tree(REPO, self.kit, ignore=KIT_IGNORE))
        self.todo(f"[kit] record the config dir in {fwd(self.kit / RECORD)} (the guards fail closed if "
                  "CLAUDE_CONFIG_DIR later points elsewhere)", record)

    def plan_instructions(self):
        src = REPO / "instructions"
        if not src.is_dir():
            self.warnings.append("instructions/ is missing from this copy of the kit: skipped")
            return
        dst = self.wb / "instructions"
        line = "@workbench/instructions/CLAUDE.md"
        cmd = self.claude_home / "CLAUDE.md"
        raw = cmd.read_bytes() if cmd.exists() else b""
        text, enc, bom = decode_text(raw)
        self.todo(f"[instructions] copy instructions/ to {fwd(dst)} (placeholders filled in)",
                  lambda: self.replace_tree(src, dst, lambda t: fill(t, self.values)))
        if line in [ln.strip() for ln in text.splitlines()]:
            self.todo(f"[instructions] {fwd(cmd)} already imports them")
            return
        eol = "\r\n" if "\r\n" in text else "\n"

        def append():
            add = ("" if not text or text.endswith(("\n", "\r")) else eol) + line + eol
            data = (b"\xef\xbb\xbf" if bom else b"") + (text + add).encode(enc if enc != "latin-1" else "utf-8")
            self.write_bytes(cmd, data)
        self.manifest["claude_md_line"] = line
        self.todo(f"[instructions] append `{line}` to {fwd(cmd)} (its encoding and line endings kept)", append)

    def plan_files(self):
        user = self.wb / "USER.md"
        if user.exists():
            self.todo(f"[files] keep your {fwd(user)}")
        elif (REPO / "templates" / "USER.md").exists():
            self.todo(f"[files] create {fwd(user)} from templates/USER.md (fill it in afterwards)",
                      lambda: self.create_file(user, (REPO / "templates" / "USER.md").read_text(encoding="utf-8")))
        sl = self.wb / "statusline.py"
        src = REPO / "plugins" / "workbench-core" / "scripts" / "statusline.py"
        self.todo(f"[files] copy statusline.py to {fwd(sl)}", lambda: self.write_file(sl, src.read_text(encoding="utf-8")))
        if self.prev.get("kb_root") and fwd(self.prev["kb_root"]) != fwd(self.kb):
            self.warnings.append(f"KB root changes from {self.prev['kb_root']} to {fwd(self.kb)}: env, "
                                 "additionalDirectories, config.json and the instructions are all updated")
        if self.prev.get("python") and self.prev["python"] != self.python:
            self.warnings.append(f"Python changes from {self.prev['python']} to {self.python}: the hooks and the "
                                 "statusline are updated")
        cfg = self.wb / "config.json"
        body = lambda: json.dumps({"version": VERSION, "kb_root": fwd(self.kb), "python": self.python,  # noqa: E731
                                   "profile": self.a.profile, "kit": fwd(self.kit), "statusLine": self.statusline()},
                                  indent=2) + "\n"
        self.todo(f"[files] write {fwd(cfg)} (kb_root, python, statusLine)", lambda: self.write_file(cfg, body()))
        self.plan_allowlist()

    def plan_allowlist(self):
        al = self.wb / "corporate-allowlist.json"
        tpl = REPO / "plugins" / "workbench-core" / "scripts" / "guards" / "corporate-allowlist.template.json"
        hosts = [h.strip() for h in (self.a.git_hosts or "").split(",") if h.strip()]
        bad = [h for h in hosts if not re.fullmatch(r"[A-Za-z0-9._-]+(?::\d+)?", h)]
        if bad:
            raise Stop(2, f"--git-hosts: not a host name: {', '.join(bad)}")
        if al.exists():
            if not hosts:
                self.todo(f"[guards] keep your {fwd(al)}")
                return
            try:
                conf = read_json(al)
            except (OSError, ValueError) as e:
                raise Stop(2, f"{fwd(al)} is not valid JSON ({e}); fix it by hand first")
            conf["git_remote_hosts"] = hosts
            self.todo(f"[guards] set git_remote_hosts in {fwd(al)} to {hosts}",
                      lambda: self.write_file(al, json.dumps(conf, indent=2) + "\n"))
            return
        conf = read_json(tpl)
        conf["git_remote_hosts"] = hosts
        self.todo(f"[guards] create {fwd(al)}: corporate pack ON, approved git hosts {hosts or 'none yet'}",
                  lambda: self.create_file(al, json.dumps(conf, indent=2) + "\n"))
        if not hosts:
            self.warnings.append("No git hosts approved yet: every push to a remote host will be refused. Re-run with "
                                 "--git-hosts <your company's git hosts>, or edit corporate-allowlist.json by hand.")

    def plan_kb(self):
        if "onedrive" in fwd(self.kb).lower():
            self.warnings.append(f"The KB root {fwd(self.kb)} is inside a OneDrive folder. That works (the search "
                                 "index lives outside it), but do not make it a git repository there, and check your "
                                 "organisation allows this data in that location.")
        if self.kb.exists() and any(self.kb.iterdir()):
            self.todo(f"[kb] keep the existing knowledge base at {fwd(self.kb)}")
            return

        def make():
            if self.kb.exists():
                self.kb.rmdir()
            shutil.copytree(REPO / "kb-template", self.kb)
            self.manifest["kb_created"] = fwd(self.kb)
        self.todo(f"[kb] create the knowledge base at {fwd(self.kb)} from kb-template/ (uninstall never deletes it)", make)

    def fragment(self):
        p = REPO / "settings" / "profiles" / f"{self.a.profile}.fragment.json"
        if not p.exists():
            raise Stop(2, f"settings profile not found: {fwd(p)}")
        return fill_json(read_json(p), self.values), p

    def _upstream(self, name):
        up = REPO / "settings" / name
        if not up.exists():
            self.warnings.append(f"settings/{name} not found: skipped")
            return {}
        upf, skipped = fill_json(read_json(up), self.values), set()
        for mname, entry in list((upf.get("extraKnownMarketplaces") or {}).items()):
            ok, why = marketplace_allowed((entry or {}).get("source") or {}, self.managed)
            if not ok:
                skipped.add(mname)
                del upf["extraKnownMarketplaces"][mname]
                self.warnings.append(f"upstream marketplace {mname} skipped: {why}")
        for mname, msrc in BUILTIN_MARKETPLACES.items():
            if not marketplace_allowed(msrc, self.managed)[0] and \
                    any(p.endswith("@" + mname) for p in upf.get("enabledPlugins") or {}):
                skipped.add(mname)
                self.warnings.append(f"plugins from {mname} skipped: not allowed by managed marketplace policy")
        for pid in list(upf.get("enabledPlugins") or {}):
            if pid.split("@")[-1] in skipped:
                del upf["enabledPlugins"][pid]
        upf.pop("$schema", None)
        return upf

    def plan_settings(self):
        sp = self.claude_home / "settings.json"
        try:
            settings = read_json(sp) if sp.exists() else {}
        except (OSError, ValueError) as e:
            raise Stop(2, f"{fwd(sp)} is not valid JSON ({e}). Fix it first; nothing was changed.")
        frag, src = self.fragment()
        frag = copy.deepcopy(frag)
        frag.pop("statusLine", None)              # kit-owned values are written at apply time by owned_settings()
        (frag.get("env") or {}).pop("WORKBENCH_KB_ROOT", None)
        if self.upstream:
            deep_merge(frag, self._upstream("upstream-plugins.fragment.json"))
        if self.a.upstream_plugins_optional:
            deep_merge(frag, self._upstream("upstream-plugins.optional.fragment.json"))
        ops, notes = [], []
        merge_settings(settings, frag, self.managed, self.a.force, ops, notes)
        self.plan.append(f"[settings] profile {self.a.profile} ({fwd(src.relative_to(REPO))}); upstream plugins: "
                         f"{'yes' if self.upstream else 'no'}; optional upstream plugins: "
                         f"{'yes' if self.a.upstream_plugins_optional else 'no'}")
        self.manifest["settings_ops"] = ops
        return settings, ops, notes

    def statusline(self):
        """Computed after statusline.py is written: a Windows short path exists only for an existing file."""
        return {"type": "command", "command": statusline_command(self.python, self.wb / "statusline.py")}

    def owned_settings(self, settings, ops, notes):
        """The values with one owner. Called at apply time, after the files they point at exist."""
        own(settings, ["env", "WORKBENCH_KB_ROOT"], fwd(self.kb), self.managed, ops, notes, self.warnings)
        if not managed_has(self.managed, ("permissions", "additionalDirectories"), []):
            perms = settings.setdefault("permissions", {})
            dirs = perms.setdefault("additionalDirectories", [])
            old = fwd(self.prev.get("kb_root") or "")
            if old and old != fwd(self.kb) and old in dirs:
                dirs.remove(old)
                ops.append({"op": "list-remove", "path": ["permissions", "additionalDirectories"], "items": [old]})
            if fwd(self.kb) not in dirs:
                dirs.append(fwd(self.kb))
                ops.append({"op": "list-add", "path": ["permissions", "additionalDirectories"], "items": [fwd(self.kb)]})
        for pid in PLUGIN_IDS:
            own(settings, ["pluginConfigs", pid, "options", "python"], self.python, self.managed, ops, notes,
                self.warnings)
        sl = self.statusline()
        cur = settings.get("statusLine")
        mine = not cur or cur == self.prev.get("statusLine") or "workbench/statusline" in json.dumps(cur).lower()
        if mine or self.a.force:
            own(settings, ["statusLine"], sl, self.managed, ops, notes, self.warnings)
        else:
            notes.append(("statusLine", "you set your own (kept; --force replaces it with the workbench statusline)"))

    def write_settings(self, settings, ops, notes):
        self.owned_settings(settings, ops, notes)
        self.write_file(self.claude_home / "settings.json", json.dumps(settings, indent=2, ensure_ascii=False) + "\n")

    def plan_plugins(self):
        src = self.kit if REPO.resolve() != self.kit.resolve() else REPO
        cmds = [["claude", "plugin", "marketplace", "remove", MARKETPLACE],
                ["claude", "plugin", "marketplace", "add", fwd(src)]] + \
               [["claude", "plugin", "install", i] for i in PLUGIN_IDS]
        shown = "\n".join(f"      {show(c)}" for c in cmds[1:])
        if not self.claude:
            self.todo("[plugins] the claude CLI is not on PATH (or --no-cli was given): after --apply, run:\n" + shown)
            self.manifest["cli_pending"] = list(PLUGIN_IDS)
            return

        def run():
            for i, c in enumerate(cmds):
                r = subprocess.run([self.claude, *c[1:]], capture_output=True, timeout=600)
                out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()
                if i == 0:     # removing an older registration of the same name; "not found" is fine
                    continue
                print(f"  {show(c)} -> exit {r.returncode}\n" + "\n".join("    " + ln for ln in out.splitlines()))
                if r.returncode != 0:
                    self.failures.append(show(c))
                elif c[2] == "install":
                    self.manifest["cli"].append(c[3])
                else:
                    self.manifest["marketplace_added"] = True
        self.todo("[plugins] register the kit copy as the local marketplace `workbench` and install:\n" + shown, run)

    # ── run ──
    def report(self):
        print(f"claude-workbench {VERSION} installer ({'APPLY' if self.a.apply else 'DRY RUN: nothing is written; add --apply'})")
        for k, v in (("kit source", fwd(REPO)), ("claude home", fwd(self.claude_home)), ("workbench home", fwd(self.wb)),
                     ("python", self.python), ("kb root", fwd(self.kb)), ("profile", self.a.profile)):
            print(f"  {k:15s} {v}")
        print("Managed settings found on this machine: " + (", ".join(s for s, _ in self.sources) or "none") +
              ".\n  Server-managed settings (admin console) cannot be read from disk: after install, /status shows "
              "what is in force.")
        if self.managed:
            print("  Managed keys (a scalar one is never written by this install): " + ", ".join(sorted(self.managed)))
        print("Plan:")
        for line in self.plan:
            print("  " + line)

    def apply(self):
        self.backup.mkdir(parents=True, exist_ok=True)
        try:
            for fn in self.actions:
                fn()
        finally:
            (self.backup / "manifest.json").write_text(json.dumps(self.manifest, indent=2) + "\n", encoding="utf-8")
        for w in self.warnings:
            print("WARNING: " + w)
        print(f"Applied. Backups and the uninstall manifest: {fwd(self.backup)}")
        if not self.self_test():
            self.failures.append("guard self-test")

    def self_test(self):
        """Hooks fail open, so prove the installed guard denies a known-bad call with this interpreter."""
        root = self.kit if self.kit.exists() else REPO
        guard = root / "plugins" / "workbench-core" / "scripts" / "guards" / "pretooluse.py"
        ok = False
        with tempfile.TemporaryDirectory() as logs:   # keep the probe out of the real guard log
            env = {**os.environ, "GUARDS_LOG_DIR": logs, "CLAUDE_CONFIG_DIR": str(self.claude_home)}
            try:
                ev = {"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}, "cwd": logs}
                r = subprocess.run([sys.executable, "-S", str(guard)], input=json.dumps(ev).encode(),
                                   capture_output=True, timeout=60, env=env)
                ok = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
            except Exception:
                ok = False
        print("Guard self-test (installed kit, this interpreter): " + ("PASS" if ok else "FAIL: the guards would not block"))
        try:
            conf = read_json(self.wb / "corporate-allowlist.json")
        except (OSError, ValueError):
            conf = {}
        hosts = conf.get("git_remote_hosts") or []
        print("Corporate guard pack: " + ("OFF (enabled is false in corporate-allowlist.json)" if conf.get("enabled") is False
              else f"ON, approved git hosts: {', '.join(hosts)}" if hosts
              else "ON, no approved git hosts yet: every push to a remote host is refused until you add them"))
        print("Next: start Claude Code, run /status and /hooks, then ask Claude to `git push --force origin main` in a "
              "scratch repo; it must be blocked. That is the only proof the installed hooks run.")
        return ok


# ── uninstall ────────────────────────────────────────────────────────────────────────────────────────────────
def _rewrite_text_file(p, keep_line):
    """Rewrite a user text file without the lines keep_line() rejects, keeping its encoding, BOM and line endings."""
    text, enc, bom = decode_text(p.read_bytes())
    out = "".join(ln for ln in text.splitlines(keepends=True) if keep_line(ln))
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + out.encode(enc if enc != "latin-1" else "utf-8"))


def uninstall(a):
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
    wb = claude_home / "workbench"
    manifests = sorted((wb / "backups").glob("*/manifest.json"), reverse=True)
    print(f"claude-workbench uninstall ({'APPLY' if a.apply else 'DRY RUN: nothing is changed; add --apply'})")
    if not manifests:
        print(f"  nothing to undo: no install manifest under {fwd(wb / 'backups')}")
        return purge_backups(a, wb, False)
    keep = wb / "backups" / f"uninstall-{time.strftime('%Y%m%d-%H%M%S')}"
    claude = None if a.no_cli else shutil.which("claude")
    failed, ran = False, set()
    for mf in manifests:
        m = json.loads(mf.read_text(encoding="utf-8"))
        print(f"  undo install {m['ts']} (profile {m.get('profile')}):")
        ids = list(m.get("cli") or []) + list(m.get("cli_pending") or [])
        cmds = [["claude", "plugin", "uninstall", i] for i in ids]
        if m.get("marketplace_added") or ids:
            cmds.append(["claude", "plugin", "marketplace", "remove", MARKETPLACE])
        use_cli = claude and not m.get("no_cli")          # an install done with --no-cli is undone the same way
        for c in [c for c in cmds if show(c) not in ran]:   # an older install's CLI steps were already undone
            ran.add(show(c))
            if a.apply and use_cli:
                r = subprocess.run([claude, *c[1:]], capture_output=True, timeout=600)
                out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()
                print(f"    {show(c)} -> exit {r.returncode}" + (f"\n      {out}" if r.returncode else ""))
            else:
                print(f"    {'run yourself: ' if not use_cli else 'would run: '}{show(c)}")
        for i, t in enumerate(m.get("created_trees") or []):
            print(f"    remove copied folder {t}")
            if a.apply and Path(t).exists():
                shutil.copytree(t, keep / "trees" / f"{i:02d}-{Path(t).name}", dirs_exist_ok=True)
                shutil.rmtree(t)
        for rt in m.get("replaced_trees") or []:
            print(f"    restore folder {rt['path']} from its backup")
            if a.apply and Path(rt["backup"]).exists():
                shutil.rmtree(rt["path"], ignore_errors=True)
                shutil.copytree(rt["backup"], rt["path"])
        for c in m.get("created") or []:
            p = Path(c["path"])
            changed = p.exists() and c.get("sha_after") and sha(p) != c["sha_after"]
            print(f"    remove {c['path']}" + (" (you edited it: a copy is kept in the uninstall backup)" if changed else ""))
            if a.apply and p.exists():
                if changed:
                    (keep / "files").mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, keep / "files" / p.name)
                p.unlink()
        for f in m.get("files") or []:
            p = Path(f["path"])
            if f.get("sha_after") and sha(p) == f["sha_after"]:
                print(f"    restore {f['path']} " + ("from its backup" if f["existed"] else "(remove: the install created it)"))
                if a.apply:
                    if f["existed"]:
                        shutil.copy2(f["backup"], p)
                    else:
                        p.unlink(missing_ok=True)
            elif p.name == "settings.json" and p.exists():
                print(f"    {f['path']} changed since the install: removing only what the install added")
                if a.apply:
                    try:
                        s = read_json(p)
                    except (OSError, ValueError) as e:
                        print(f"      cannot read it ({e}): left as is; backup at {f.get('backup')}")
                        failed = True
                        continue
                    undo_settings(s, m.get("settings_ops") or [])
                    try:   # empty objects the claude CLI leaves behind (enabledPlugins: {}) that were not there before
                        orig = read_json(f["backup"]) if f["existed"] else {}
                    except (OSError, ValueError, TypeError):
                        orig = None
                    if orig is not None:
                        for k in [k for k, v in s.items() if v in ({}, []) and k not in orig]:
                            del s[k]
                    if not f["existed"] and not s:
                        p.unlink()   # the install created it; only empty objects (left by the claude CLI) remain
                    else:
                        p.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
            elif p.name == "CLAUDE.md" and p.exists() and m.get("claude_md_line"):
                print(f"    {f['path']} changed since the install: removing only the @import line")
                if a.apply:
                    _rewrite_text_file(p, lambda ln: ln.strip() != m["claude_md_line"])
            elif p.exists():
                print(f"    {f['path']} changed since the install: left as is (backup: {f.get('backup')})")
        if m.get("kb_created"):
            print(f"    keep the knowledge base at {m['kb_created']} (your data; delete it yourself if you want)")
        if a.apply:
            os.replace(mf, mf.with_name("manifest.uninstalled.json"))
    for d in (wb / "instructions",):
        if a.apply and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    print(f"Done. Logs, backups and the knowledge base stay: {fwd(wb)}" if not a.purge_backups else
          f"Done. Logs and the knowledge base stay: {fwd(wb)}")
    return purge_backups(a, wb, failed)


def purge_backups(a, wb, failed):
    """--purge-backups: delete <workbench>/backups, only after an uninstall that did not fail."""
    if not getattr(a, "purge_backups", False):
        return 4 if failed else 0
    d = wb / "backups"
    if failed:
        print(f"  backups kept at {fwd(d)}: the uninstall did not finish cleanly, and they are how to recover")
        return 4
    if not d.is_dir():
        return 0
    edited = list(d.glob("uninstall-*/files/*"))
    print(f"  {'delete' if a.apply else 'would delete'} {fwd(d)}"
          + (f" (including {len(edited)} copy/copies of files you had edited)" if edited else ""))
    if a.apply:
        shutil.rmtree(d)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="claude-workbench installer: a dry run unless --apply. "
                                             "Run it as: py -3 bootstrap\\install.py (Windows) or python3 "
                                             "bootstrap/install.py (Linux, WSL).")
    ap.add_argument("--apply", action="store_true", help="write the plan (default: print it only)")
    ap.add_argument("--profile", choices=["corporate", "permissive"], default="corporate",
                    help="settings profile (default corporate); permissive implies --upstream-plugins")
    ap.add_argument("--upstream-plugins", action="store_true", help="merge settings/upstream-plugins.fragment.json")
    ap.add_argument("--upstream-plugins-optional", action="store_true",
                    help="merge settings/upstream-plugins.optional.fragment.json (never implied)")
    ap.add_argument("--kb-root", help="knowledge-base folder (default: the last install's, else ~/claude-kb)")
    ap.add_argument("--git-hosts", help="comma-separated git hosts company code may be pushed to")
    ap.add_argument("--force", action="store_true", help="replace settings keys you already set")
    ap.add_argument("--no-cli", action="store_true", help="never call the claude CLI; print its commands instead")
    ap.add_argument("--uninstall", action="store_true", help="undo installs, newest first (dry run unless --apply)")
    ap.add_argument("--purge-backups", action="store_true",
                    help="with --uninstall: also delete <workbench>/backups once the uninstall succeeded")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.")
        return 2
    if store_python(sys.executable):
        print("This is the Microsoft Store Python (its path is under WindowsApps). Store apps get a private, redirected "
              "copy of shared folders such as AppData and TEMP, so the hooks' logs and state would land somewhere else. "
              "Install Python from python.org, winget or your organisation's software portal, then run: "
              "py -3 bootstrap\\install.py")
        return 2
    try:
        if a.uninstall:
            return uninstall(a)
        inst = Installer(a)
        inst.build()
        inst.report()
        if not a.apply:
            for w in inst.warnings:
                print("WARNING: " + w)
            return 0
        inst.apply()
        if inst.failures:
            print("FAILED steps: " + "; ".join(inst.failures))
            return 4
        return 0
    except Stop as s:
        print(("STOP: " if s.code == 3 else "ERROR: ") + str(s))
        return s.code


if __name__ == "__main__":
    sys.exit(main())
