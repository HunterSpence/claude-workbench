#!/usr/bin/env python3
"""claude-workbench installer (Python 3.10+, stdlib only). This file IS the entry point:

  Windows:      py -3 bootstrap\\install.py [options]
  Linux / WSL:  python3 bootstrap/install.py [options]     (or: sh bootstrap/install.sh [options])

  --apply                       write the plan (without it nothing is written: the plan is printed)
  --profile corporate|permissive  settings profile (default corporate). permissive implies --upstream-plugins
  --upstream-plugins            also merge settings/upstream-plugins.fragment.json
  --upstream-plugins-optional   also merge settings/upstream-plugins.optional.fragment.json (never implied)
  --kb-root PATH                knowledge-base folder (default: the last install's, else <data root>/kb)
  --data-root PATH              workbench data folder (default: the last install's, else <work OneDrive>/Workbench
                                when exactly one verified work OneDrive exists, else ~/Workbench)
  --git-hosts h1,h2             accepted and ignored (older setup commands still pass it)
  --approvals ask|off           corporate profile: ask before each command (default) or run ordinary commands without
                                asking (new windows start in bypass mode; the kit's minimal ask rules and the
                                active-context deny still apply). Kept across upgrades
  --force                       replace settings keys you already set to something else
  --no-cli                      never call the claude CLI; print its commands instead
  --setup auto|plan             after --apply: show the capability report, then provision this machine in the
                                background (auto) or only write the plan (plan). Absent: print the next command.
  --with LIST                   opt-ins: tokensave, pm-pack, upstream-skills, capture, nightly, claude-winget,
                                claude-autoupdate, ctx, update-latest (comma-separated; passed on to setup)
  --no-nightly                  permissive profile: do not register the nightly knowledge refresh task
  --no-update                   passed on to setup: skip its update phase
  --uninstall                   undo installs, newest first, and the machine changes setup recorded (dry run
                                unless --apply)

No network, no admin rights, no git remote, no change to managed settings (setup, run separately or through --setup,
is what installs software). Every changed file is backed up to <workbench home>/backups/<timestamp>/ with a manifest
that --uninstall replays. Paths: CLAUDE_HOME = CLAUDE_CONFIG_DIR or ~/.claude; WORKBENCH_HOME = <CLAUDE_HOME>/workbench.
The kit is copied to <WORKBENCH_HOME>/kit and the plugin marketplace is registered from there, so the folder you
unpacked can be moved or deleted afterwards. CLAUDE_CONFIG_DIR inside a OneDrive folder is refused.

Values with ONE owner, rewritten on every install (a change is printed as a warning): the KB root (env
WORKBENCH_KB_ROOT, permissions.additionalDirectories, the active-context deny, config.json, the instruction text) and the
Python path (pluginConfigs of both plugins, the statusLine command, config.json).

Upgrades: permission rules an earlier kit wrote and the profile no longer has are retired (bootstrap/retired-rules.json;
a rule you wrote is never touched); list entries the kit wrote and you removed are not added again, and a kit plugin you
disabled stays disabled (<WB>/state/kit-written.json); files you changed in the kit copy, its instructions or the plugin
cache are copied with a diff to <WB>/state/local-patches/<timestamp>/ before they are replaced (never re-applied here).

Exit codes: 0 done (or dry run) · 1 unexpected error · 2 environment problem (old Python, unreadable settings.json,
bad option) · 3 blocked by your organisation's policy (ask your IT team) · 4 an apply step failed (see the output).
Test seams: WORKBENCH_MANAGED_SETTINGS (os.pathsep-separated JSON files) is read as an extra managed source;
WORKBENCH_FAKE_REGISTRY (a JSON file) replaces registry reads; WORKBENCH_REPORT_CLI replaces bootstrap/report.py.
"""
import argparse
import calendar
import copy
import difflib
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VERSION = "0.3.6"
MARKETPLACE = "workbench"
PLUGIN_IDS = ("workbench-core@workbench", "workbench-kb@workbench")    # pluginConfigs.<id>.options.python: these only
DEFAULT_PLUGINS = PLUGIN_IDS + ("workbench-biz@workbench",)
CAPTURE_PLUGIN = "workbench-capture@workbench"                          # only with --with capture
EXTRAS = ("tokensave", "pm-pack", "upstream-skills", "capture", "nightly", "claude-winget", "claude-autoupdate", "ctx",
          "update-latest")
# KB files an upgrade refreshes when the user has not edited them. The cards and their detectors move as ONE pair, so a
# detector never names a card the user's file lacks; digests move one file at a time.
KB_PAIR = ("_shared/bug-cards.md", "_shared/bug-detectors.json")
BUILTIN_MARKETPLACES = {"claude-plugins-official": {"source": "github", "repo": "anthropics/claude-plugins-official"}}
IGNORE = (".git", "__pycache__", "*.pyc", ".venv", "venv", "node_modules", ".pytest_cache", "*.bak*", "installed-config.json")
KIT_IGNORE = shutil.ignore_patterns(*IGNORE)
RECORD = Path("plugins") / "workbench-core" / "scripts" / "installed-config.json"   # read by profile.py (main_home)
ABSENT = {"__absent__": True}
LEDGER_KEYS = ("permissions.ask", "permissions.deny", "permissions.allow", "permissions.additionalDirectories")
SUBAGENT_MIN = (2, 1, 251)       # before it, CLAUDE_CODE_SUBAGENT_MODEL overrode every persona's own model
OLD = "gu" + "ard"               # the removed PreToolUse hook's name, built so a word scan of the kit finds no leftover


def off_text(pid):
    """What a kit plugin the user turned off means, said once per install and in the post-update verify."""
    name = pid.split("@")[0]
    if name == "workbench-core":
        return ("workbench-core is disabled (your choice; kept). It also runs session-start memory, the save reminders and "
                "the pre-compaction snapshot, so those are off too. To turn it back on: claude plugin enable "
                "workbench-core@workbench")
    return f"{name} is disabled (your choice; kept). To turn it back on: claude plugin enable {pid}"


def stamp_key(name):
    """Sort key of a backup folder name, oldest first: YYYYMMDD-HHMMSS, then its -N suffix (two installs in one second)."""
    parts = str(name).split("-")
    return "-".join(parts[:2]), int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0


def manifests_in_order(wb):
    """[(path, manifest)] of every live install manifest under <wb>/backups, oldest first. The folder stamp is LOCAL wall-clock
    time, which a laptop that changes time zone puts out of order, so the order is the manifest's own UTC stamp ("utc",
    0.3.5 on, taken when the manifest is written), else the file's mtime (written once, at the end of that install), then
    the folder stamp as the tie-break. Both are end-of-install times, so an old and a new manifest compare correctly."""
    out = []
    for f in (Path(wb) / "backups").glob("*/manifest.json"):
        m = json.loads(f.read_text(encoding="utf-8"))
        try:
            head, _, frac = str(m["utc"]).rstrip("Z").partition(".")
            ns = calendar.timegm(time.strptime(head, "%Y-%m-%dT%H:%M:%S")) * 10**9 + int((frac + "0" * 9)[:9])
        except (KeyError, ValueError):
            ns = f.stat().st_mtime_ns
        out.append(((ns, stamp_key(f.parent.name)), f, m))
    return [(f, m) for _, f, m in sorted(out, key=lambda x: x[0])]


def remove_once(cur, gone):
    """cur without ONE occurrence of each string in gone (a user's own duplicate copy of a kit string stays); order kept."""
    left = list(gone)
    out = []
    for x in cur:
        if x in left:
            left.remove(x)
        else:
            out.append(x)
    cur[:] = out


def perm_path(p):
    """A path in the form Claude Code's permission rules match: forward slashes, `X:/rest` -> `//x/rest` (drive letter
    lower-cased), `/rest` -> `//rest`."""
    s = fwd(p).rstrip("/")
    m = re.fullmatch(r"([A-Za-z]):(/.*)?", s)
    if m:
        return f"//{m.group(1).lower()}{m.group(2) or ''}"
    return s if s.startswith("//") or not s.startswith("/") else "/" + s


def ac_rule(kb):
    """The one deny rule: only the save driver writes the KB's active-context.md (an Edit rule covers every edit tool)."""
    return f"Edit({perm_path(kb)}/active-context.md)"


def lf_sha(path):
    """sha256 of a file's bytes with CRLF read as LF (the release manifests' form), or None when it cannot be read."""
    try:
        return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    except OSError:
        return None


def tree_files(root):
    """{posix path: Path} of the files under root, without what a kit copy never holds (IGNORE)."""
    root, out = Path(root), {}
    skip = lambda n: any(fnmatch.fnmatch(n, pat) for pat in IGNORE)  # noqa: E731
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if not skip(x)]
        for n in names:
            if not skip(n):
                p = Path(d) / n
                out[p.relative_to(root).as_posix()] = p
    return out


def move_retry(src, dst, tries=3):
    """Move a file, retrying while another process holds it open (Windows); True when it moved."""
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    for i in range(tries):
        try:
            shutil.move(str(src), str(dst))
            return True
        except OSError:
            if i + 1 < tries:
                time.sleep(0.5)
    return False


def python_plugin_ids(repo=REPO):
    """Ids (name@workbench) of the kit's plugins whose manifest declares userConfig.python: the plugins whose hooks and
    scripts fail with `Plugin option "python" isn't set` until pluginConfigs.<id>.options.python holds an interpreter."""
    out = []
    for m in sorted(Path(repo, "plugins").glob("*/.claude-plugin/plugin.json")):
        try:
            if "python" in (read_json(m).get("userConfig") or {}):
                out.append(f"{m.parent.parent.name}@{MARKETPLACE}")
        except (OSError, ValueError):
            continue
    return out


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


def console_python(exe=None):
    """python.exe beside pythonw.exe (else exe unchanged), for every Python child whose output is read. A pythonw
    process hands its own children no standard handles, so under a detached (pythonw) setup run their output is lost."""
    p = Path(exe or sys.executable)
    c = p.with_name("python.exe")
    return str(c) if p.name.lower() == "pythonw.exe" and c.is_file() else str(p)


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


# ── paths, registry reads, OneDrive placement (shared with setup.py and profile.py) ──────────────────────────
def claude_home():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def lad():
    """%LOCALAPPDATA% on Windows, ~/.cache elsewhere (layout token <LAD>)."""
    v = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
    return Path(v) if v else Path.home() / ".cache"


def under(child, parent):
    """True when child is parent or inside it (case-insensitive on Windows, separators normalised)."""
    if not child or not parent:
        return False
    c, p = (fwd(os.path.abspath(str(x))).rstrip("/") for x in (child, parent))
    if os.name == "nt":
        c, p = c.lower(), p.lower()
    return c == p or c.startswith(p + "/")


_HIVES = {"HKLM": "HKEY_LOCAL_MACHINE", "HKCU": "HKEY_CURRENT_USER"}


def _rkey(k):
    return k.replace("/", "\\").strip("\\").lower()


def fake_registry():
    """The JSON test registry {"HKCU\\\\Key": {"Value": data | [data, type]}} or None when the real one is used."""
    f = os.environ.get("WORKBENCH_FAKE_REGISTRY")
    if not f:
        return None
    try:
        return read_json(f)
    except (OSError, ValueError):
        return {}


def _winreg_open(key):
    import winreg
    hive, _, sub = key.replace("/", "\\").partition("\\")
    return winreg.OpenKey(getattr(winreg, _HIVES.get(hive.upper(), hive.upper())), sub)


def reg_values(key):
    """{name: (data, type)} of a registry key, or None when the key does not exist. Read-only."""
    fake = fake_registry()
    if fake is not None:
        for k, vals in fake.items():
            if _rkey(k) == _rkey(key):
                return {n: tuple(v) if isinstance(v, list) else (v, 4 if isinstance(v, int) else 1)
                        for n, v in (vals or {}).items()}
        return None
    if os.name != "nt":
        return None
    import winreg
    try:
        with _winreg_open(key) as h:
            out, i = {}, 0
            while True:
                try:
                    n, d, t = winreg.EnumValue(h, i)
                except OSError:
                    return out
                out[n], i = (d, t), i + 1
    except OSError:
        return None


def reg_get(key, name):
    """(data, type) of one registry value, or None. Value names are case-insensitive, as in Windows."""
    for n, v in (reg_values(key) or {}).items():
        if n.lower() == name.lower():
            return v
    return None


def reg_subkeys(key):
    fake = fake_registry()
    if fake is not None:
        pre = _rkey(key) + "\\"
        return sorted({k.replace("/", "\\").strip("\\")[len(pre):].split("\\")[0]
                       for k in fake if _rkey(k).startswith(pre)})
    if os.name != "nt":
        return []
    import winreg
    try:
        with _winreg_open(key) as h:
            out, i = [], 0
            while True:
                try:
                    out.append(winreg.EnumKey(h, i))
                except OSError:
                    return out
                i += 1
    except OSError:
        return []


ONEDRIVE_ACCOUNTS = r"HKCU\Software\Microsoft\OneDrive\Accounts"
TENANT_ALLOW = r"HKLM\SOFTWARE\Policies\Microsoft\OneDrive\AllowTenantList"


def onedrive_roots():
    """(work, personal, every_root). work = [(folder, tenant id or None)] from Accounts\\Business<N> (N is not always 1)
    plus %OneDriveCommercial%; personal = Accounts\\Personal plus %OneDriveConsumer%; every_root adds %OneDrive%,
    which can point at either and is never used alone to pick a work folder. Tenant value name ConfiguredTenantId is
    ASSUMED (confirm on a managed laptop)."""
    work, personal = [], []
    for sub in reg_subkeys(ONEDRIVE_ACCOUNTS):
        key = ONEDRIVE_ACCOUNTS + "\\" + sub
        folder = (reg_get(key, "UserFolder") or (None,))[0]
        if not folder:
            continue
        if re.fullmatch(r"business\d+", sub, re.I):
            work.append((folder, (reg_get(key, "ConfiguredTenantId") or (None,))[0]))
        elif sub.lower() == "personal":
            personal.append(folder)
    env = os.environ
    if env.get("OneDriveCommercial") and not any(under(env["OneDriveCommercial"], w) and under(w, env["OneDriveCommercial"])
                                                 for w, _ in work):
        work.append((env["OneDriveCommercial"], None))
    if env.get("OneDriveConsumer"):
        personal.append(env["OneDriveConsumer"])
    every = [w for w, _ in work] + personal + ([env["OneDrive"]] if env.get("OneDrive") else [])
    return work, personal, every


def work_onedrive():
    """(root, candidates): root is the single verified work OneDrive folder, else None. A candidate must exist, must not
    sit under a personal OneDrive and, when the machine policy AllowTenantList exists, must carry a listed tenant."""
    work, personal, _ = onedrive_roots()
    allow = reg_values(TENANT_ALLOW)
    allowed = None if allow is None else {str(x).lower() for n, (d, _) in allow.items() for x in (n, d)}
    seen = {}
    for folder, tenant in work:
        p = Path(folder)
        if not p.is_dir() or any(under(p, q) for q in personal):
            continue
        if allowed is not None and (not tenant or str(tenant).lower() not in allowed):
            continue
        seen.setdefault(fwd(p).lower(), p)
    cands = list(seen.values())
    return (cands[0] if len(cands) == 1 else None), cands


def in_onedrive(path):
    """True when path is inside any OneDrive folder (work or personal)."""
    return any(under(path, r) for r in onedrive_roots()[2])


def resolve_data_root(arg, prev):
    """(data root, work OneDrive root or None). Order: --data-root, the last install's data_root, then the single
    verified work OneDrive + /Workbench, else ~/Workbench. Two or more work folders stop the install: the user picks."""
    if arg:
        return Path(os.path.abspath(os.path.expanduser(arg))), work_onedrive()[0]
    root, cands = work_onedrive()
    if prev.get("data_root"):
        return Path(prev["data_root"]), root
    if len(cands) > 1:
        raise Stop(2, "More than one work OneDrive folder is synced on this machine (" + ", ".join(fwd(c) for c in cands)
                   + "). Choose where workbench data lives: re-run with --data-root <folder>/Workbench (one of them, "
                     "or a local folder). It is never picked automatically.")
    return (root / "Workbench" if root else Path.home() / "Workbench"), root


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
def merge_settings(user, frag, managed, force, ops, notes, path=(), prev=None):
    """Merge frag into user in place: a key the user set is kept (unless force), arrays are unioned, a key a managed
    source sets as a scalar is skipped. prev = {path tuple: value} an earlier kit install wrote: a value still equal to
    it is the kit's, so an upgrade updates it. Records undo ops; notes skipped keys as (path, why)."""
    prev = prev or {}
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
            merge_settings(user[k], v, managed, force, ops, notes, p, prev)
        elif isinstance(v, list) and isinstance(user.get(k), list):
            add = [x for x in v if x not in user[k]]
            if add:
                user[k].extend(copy.deepcopy(add))
                ops.append({"op": "list-add", "path": list(p), "items": add})
        elif k not in user:
            user[k] = copy.deepcopy(v)
            ops.append({"op": "set", "path": list(p), "value": v, "old": ABSENT})
        elif user[k] != v:
            if force or (p in prev and prev[p] == user[k]):
                ops.append({"op": "set", "path": list(p), "value": v, "old": user[k]})
                user[k] = copy.deepcopy(v)
                notes.append((dotted, "replaced (--force)" if force else "updated: still the value the previous kit wrote"))
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
        if op["op"] == "del":                               # a key the install removed comes back, unless set since
            cur.setdefault(last, copy.deepcopy(op["old"]))
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
        self.claude_home = claude_home()
        if in_onedrive(self.claude_home):
            raise Stop(2, f"CLAUDE_CONFIG_DIR ({fwd(self.claude_home)}) is inside a OneDrive folder. Claude Code keeps "
                          "session history, plugin caches and sign-in state there, which must stay on this machine. "
                          "Unset it (default ~/.claude) or point it at a local folder; nothing was changed.")
        self.wb = self.claude_home / "workbench"
        self.kit = self.wb / "kit"
        self.python = fwd(sys.executable)
        try:
            self.prev = read_json(self.wb / "config.json")
        except (OSError, ValueError):
            self.prev = {}
        self.with_ = [w.strip() for w in (a.with_ or "").split(",") if w.strip()]
        bad = [w for w in self.with_ if w not in EXTRAS]
        if bad:
            raise Stop(2, f"--with: unknown option(s) {', '.join(bad)}; known: {', '.join(EXTRAS)}")
        self.data, self.od_work = resolve_data_root(a.data_root, self.prev)
        kb = a.kb_root or self.prev.get("kb_root") or str(self.data / "kb")
        self.kb = Path(os.path.abspath(os.path.expanduser(kb)))
        self.prior = [m for _, m in manifests_in_order(self.wb)]
        self.upstream = a.upstream_plugins or a.profile == "permissive"
        self.approvals = getattr(a, "approvals", None) or (self.prev.get("approvals") if self.prev.get("approvals") in ("ask", "off") else "ask")
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
                         "created": [], "created_trees": [], "settings_ops": [], "cli": [], "no_cli": bool(a.no_cli),
                         "kb_root": fwd(self.kb), "kb_seeded": []}
        self.claude = None if a.no_cli else shutil.which("claude")
        self.ledger_path = self.wb / "state" / "kit-written.json"
        try:
            self.ledger = read_json(self.ledger_path)
        except (OSError, ValueError):
            self.ledger = {}                          # none (or unreadable): nothing counts as removed by the user
        self.plugin_choice, self.core_off, self.plugin_snap = {}, False, {}
        self.frag_lists, self.user_removed = {k: [] for k in LEDGER_KEYS}, {k: [] for k in LEDGER_KEYS}

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
        self.plan_local_changes()
        self.plan_leftovers()
        self.plan_kit()
        self.plan_instructions()
        self.plan_files()
        self.plan_kb()
        settings, ops, notes = self.plan_settings()
        self.todo(f"[settings] merge into {fwd(self.claude_home / 'settings.json')}: {len(ops)} change(s) planned"
                  + "".join(f"\n      skip {k}: {why}" for k, why in notes),
                  lambda: self.write_settings(settings, ops, notes))
        self.plan_plugins()
        self.todo(f"[state] record what this install wrote in {fwd(self.ledger_path)} (an entry you remove later is not "
                  "added again)", self.write_ledger)

    def check_policy(self):
        m = self.managed
        ok, why = marketplace_allowed({"source": "directory", "path": fwd(self.kit)}, m)
        if not ok:
            raise Stop(3, f"Your organisation's plugin policy does not allow this kit ({why}). Nothing was changed. "
                          "Ask your IT team to allow the workbench plugins (or to deploy them centrally); do not work "
                          "around the policy.")
        if m.get("allowManagedHooksOnly") is True:
            self.warnings.append("Managed allowManagedHooksOnly is on: the workbench hooks (session start, save reminders, "
                                 "statusline) will NOT run unless your IT team force-enables workbench-core in managed "
                                 "enabledPlugins. Agents and skills still load.")
        if any(d.get("allowManagedPermissionRulesOnly") is True for _, d in self.sources):
            self.warnings.append("your organisation allows only managed permission rules: the kit's ask rules and the "
                                 "active-context deny are inert on this machine")

    # ── upgrades: local changes, files the removed hook left, the kit's own record ──
    def plan_local_changes(self):
        """R4: before anything is replaced, copy what this machine changed in the kit copy, its instructions and the plugin
        cache (with a diff) to <WB>/state/local-patches/<ts>/, against the hashes of the release it was installed from."""
        if not (self.kit.is_dir() or (self.wb / "instructions").is_dir()):
            return
        self.todo(f"[kit] look for local changes in {fwd(self.kit)}, {fwd(self.wb / 'instructions')} and the plugin cache "
                  f"(kept with a diff in {fwd(self.wb / 'state' / 'local-patches')}; never applied again by the installer)",
                  self.keep_local_changes)

    def baseline(self):
        """(hashes, kind): the state manifest the last install wrote, else the bundled manifest of the previous release."""
        try:
            return read_json(self.wb / "state" / "kit-manifest.json")["files"], "state-manifest"
        except (OSError, ValueError, KeyError, TypeError):
            pass
        v = str(self.prev.get("version") or "")
        try:
            return read_json(REPO / "bootstrap" / "release-manifests" / f"{v}.json")["files"], f"bundled:{v}"
        except (OSError, ValueError, KeyError, TypeError):
            return None, "none"

    def cache_trees(self):
        """[(kit-relative prefix, folder)] of the plugin cache: <CH>/plugins/cache/workbench/<plugin>/<version>/ for the version
        the old kit copy declares, else the only version folder there is."""
        out, root = [], self.claude_home / "plugins" / "cache" / MARKETPLACE
        for d in sorted(p for p in root.glob("*") if p.is_dir()) if root.is_dir() else []:
            try:
                v = str(read_json(self.kit / "plugins" / d.name / ".claude-plugin" / "plugin.json").get("version") or "")
            except (OSError, ValueError):
                v = ""
            vers = [p for p in d.iterdir() if p.is_dir()]
            pick = d / v if v and (d / v).is_dir() else vers[0] if len(vers) == 1 else None
            if pick:
                out.append((f"plugins/{d.name}/", pick))
        return out

    def keep_local_changes(self):
        base, kind = self.baseline()
        new = set(tree_files(REPO))
        rows, skipped = [], 0
        q = lambda s: f'"{s}"' if " " in s else s  # noqa: E731
        prev_values = {**self.values, "KB_ROOT": fwd(self.prev.get("kb_root") or self.kb),
                       "PYTHON": q(str(self.prev.get("python") or self.python))}

        def note(where, rel, change, local, expected):
            nonlocal skipped
            if rel not in new:              # the new release no longer ships it: never reported, only counted
                skipped += 1
            else:
                rows.append((where, rel, change, local, expected))
        if base is not None:
            trees = ([("kit", "", self.kit)] if REPO.resolve() != self.kit.resolve() else []) + \
                    [("cache", pre, d) for pre, d in self.cache_trees()]
            for where, pre, root in trees:
                have = {pre + r: p for r, p in tree_files(root).items()}
                for rel, p in have.items():
                    if base.get(rel) != lf_sha(p):
                        note(where, rel, "modified" if rel in base else "added", p, REPO / rel)
                for rel in base if where == "kit" else ():      # the CLI's cache copy is not the whole kit: no "deleted" there
                    if rel not in have and not any(fnmatch.fnmatch(x, pat) for x in rel.split("/") for pat in IGNORE):
                        note(where, rel, "deleted", None, None)
        old_ins, cur_ins = tree_files(self.kit / "instructions"), tree_files(self.wb / "instructions")
        if old_ins and cur_ins:
            for rel in sorted(set(old_ins) | set(cur_ins)):
                if rel not in cur_ins:
                    note("instructions", f"instructions/{rel}", "deleted", None, None)
                    continue
                if rel not in old_ins:
                    note("instructions", f"instructions/{rel}", "added", cur_ins[rel], None)
                    continue
                want = old_ins[rel].read_bytes()
                if rel.endswith(".md"):
                    want = fill(want.decode("utf-8", "replace"), prev_values).encode("utf-8")
                if want.replace(b"\r\n", b"\n") != cur_ins[rel].read_bytes().replace(b"\r\n", b"\n"):
                    note("instructions", f"instructions/{rel}", "modified", cur_ins[rel], want)
        cache = self.claude_home / "plugins" / "cache" / MARKETPLACE
        if not rows and kind != "none":
            print("  local changes: none" + (f" ({skipped} file(s) this release no longer ships were not compared)" if skipped else ""))
            return
        out = self.wb / "state" / "local-patches" / self.stamp
        files = []
        copies = [tree_files(self.kit), {pre + r: f for pre, d in self.cache_trees() for r, f in tree_files(d).items()}] + \
                 [tree_files(d) for d in sorted(self.wb.glob("backups/*/trees/kit"), reverse=True)]   # older kit copies

        def old_copy(rel):
            """A file whose content is the OLD release's (its hash is the baseline's): the new release unchanged upstream, the
            other copy (kit or cache), or a kit copy an earlier install backed up."""
            for f in [REPO / rel] + [c[rel] for c in copies if rel in c]:
                if f.is_file() and lf_sha(f) == base.get(rel):
                    return f
            return None
        for n, (where, rel, change, local, expected) in enumerate(rows):
            entry = {"path": rel, "where": where, "change": change, "diff": None, "copy": None, "base": None}
            if local is not None:
                entry["copy"] = f"files/{n:03d}-{Path(rel).name}"
                (out / "files").mkdir(parents=True, exist_ok=True)
                shutil.copyfile(local, out / entry["copy"])
            if change == "modified":
                try:
                    old = old_copy(rel) if isinstance(expected, Path) else None
                    if not isinstance(expected, Path):                  # instructions: the old copy as it was filled in
                        a, label, entry["base"] = expected, f"{rel} (base: old release, as installed)", "old"
                    elif old is not None:
                        a, label, entry["base"] = old.read_bytes(), f"{rel} (base: old release)", "old"
                    else:                                               # no old copy left: this diff also undoes upstream changes
                        a, label, entry["base"] = expected.read_bytes(), f"{rel} (base: NEW release {VERSION}; upstream changed too)", "new"
                    diff = "".join(difflib.unified_diff(a.decode("utf-8").replace("\r\n", "\n").splitlines(True),
                                                        local.read_bytes().decode("utf-8").replace("\r\n", "\n").splitlines(True),
                                                        label, f"{rel} (this machine)"))
                    entry["diff"] = f"diffs/{n:03d}.diff"
                    (out / "diffs").mkdir(parents=True, exist_ok=True)
                    (out / entry["diff"]).write_text(diff, encoding="utf-8", newline="\n")
                except (OSError, UnicodeDecodeError):
                    entry["diff"] = None                       # a binary file: the copy is all there is
            files.append(entry)
        out.mkdir(parents=True, exist_ok=True)
        backup = None
        if cache.is_dir():
            shutil.copytree(cache, out / "plugin-cache", ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
            backup = "plugin-cache/"
        (out / "patches.json").write_text(json.dumps({
            "version": 1, "from_version": self.prev.get("version"), "to_version": VERSION, "baseline": kind, "files": files,
            "cache_backup": backup, "skipped_removed_upstream": skipped}, indent=2) + "\n", encoding="utf-8", newline="\n")
        self.manifest["local_patches"] = fwd(out)
        print(f"  {len(files)} local change(s) kept at {fwd(out)}; the kit-update skill reviews them" if files else
              f"  local changes: none found, but there was no release manifest to compare the kit copy with; the plugin cache "
              f"is kept at {fwd(out)} and the old kit copy in {fwd(self.backup / 'trees')}")

    def leftovers(self):
        """[(file, name under the archive folder)] of the files the removed PreToolUse hook left (I6)."""
        logs = Path(os.environ.get("WORKBENCH_LOG_DIR") or self.wb / "logs")
        cands = [self.wb / "corporate-allowlist.json", self.wb / "state" / f"{OLD}-heartbeat.json",
                 logs / f"{OLD}s.log", logs / f"{OLD}s.log.1"]
        return [(p, fwd(p.relative_to(self.wb)) if under(p, self.wb) else f"logs/{p.name}") for p in cands if p.is_file()]

    def plan_leftovers(self):
        found = self.leftovers()
        if not found:
            return
        dst = self.backup / f"{OLD}-leftovers"

        def archive():
            moved = []
            for p, rel in found:
                if move_retry(p, dst / rel):
                    moved.append({"path": fwd(p), "to": fwd(dst / rel)})
                else:
                    self.warnings.append(f"{fwd(p)} is in use and was left in place; delete it once no program holds it")
            self.manifest["archived"] = moved
            print(f"  archived {len(moved)} file(s) left by the removed PreToolUse hook to {fwd(dst)}")
        self.todo(f"[cleanup] archive {len(found)} file(s) left by the removed PreToolUse hook (allowlist, heartbeat, logs) "
                  f"to {fwd(dst)}", archive)

    def write_kit_manifest(self):
        """The hashes of the release just copied: the next install tells this machine's own changes from it."""
        files = {rel: lf_sha(p) for rel, p in sorted(tree_files(self.kit).items())}
        p = self.wb / "state" / "kit-manifest.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps({"version": VERSION, "files": files}, indent=1) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, p)

    def plan_kit(self):
        def record():   # before the plugin install, so the CLI's copy of the plugin carries it; part of the kit tree
            (self.kit / RECORD).write_text(json.dumps({"claude_home": fwd(self.claude_home)}, indent=2) + "\n",
                                           encoding="utf-8", newline="\n")

        def copy_kit():
            self.replace_tree(REPO, self.kit, ignore=KIT_IGNORE)
            self.write_kit_manifest()
        if REPO.resolve() == self.kit.resolve():
            self.todo(f"[kit] running from the installed kit at {fwd(self.kit)}: kept in place")
        else:
            self.todo(f"[kit] copy this release to {fwd(self.kit)} (the plugins load from there, so the folder you "
                      "unpacked can be moved or deleted)", copy_kit)
        self.todo(f"[kit] record the config dir in {fwd(self.kit / RECORD)} (profile.py finds the main install from it)",
                  record)

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
        mine = {"version": VERSION, "kb_root": fwd(self.kb), "data_root": fwd(self.data), "python": self.python,
                "profile": self.a.profile, "kit": fwd(self.kit), "approvals": self.approvals,
                "approvals_user_mode": None, "approvals_wrote_mode": None}   # filled at write time: plan_settings runs after this
        # keys setup.py and profile.py own (knowledge_python, knowledge_db, ...) survive a re-install
        body = lambda: json.dumps({k: v for k, v in {**{k: v for k, v in self.prev.items() if k not in mine},  # noqa: E731
                                                     **mine, "approvals_user_mode": getattr(self, "user_mode", None),
                                                     "approvals_wrote_mode": getattr(self, "wrote_mode", None),
                                                     "statusLine": self.statusline()}.items() if v is not None},
                                  indent=2) + "\n"
        self.todo(f"[files] write {fwd(cfg)} (kb_root, data_root, python, statusLine)", lambda: self.write_file(cfg, body()))

    def plan_kb(self):
        if in_onedrive(self.kb) or "onedrive" in fwd(self.kb).lower():
            self.warnings.append(f"The KB root {fwd(self.kb)} is inside a OneDrive folder. That works (the search "
                                 "index lives outside it), but do not make it a git repository there, and check your "
                                 "organisation allows this data in that location.")
        tpl = REPO / "kb-template"
        files = sorted(fwd(p.relative_to(tpl)) for p in tpl.rglob("*") if p.is_file()) if tpl.is_dir() else []
        self.todo(f"[data] workbench data root {fwd(self.data)} ("
                  + (f"in the work OneDrive {fwd(self.od_work)}; pinned to stay on this device"
                     if self.od_work and under(self.data, self.od_work) else "local") + ")", self.make_data)
        if self.kb.exists() and any(self.kb.iterdir()):
            # MAJ12: seed template files the KB lacks, but never one an earlier install seeded and the user deleted
            known = {s["path"] for m in self.prior for s in m.get("kb_seeded") or []} | \
                    {fwd(Path(m["kb_created"]) / f) for m in self.prior if m.get("kb_created") for f in m.get("kb_files") or []}
            shas = {}   # KB path -> every hash an install put there
            for m in self.prior:
                for s in m.get("kb_seeded") or []:
                    shas.setdefault(s["path"], set()).add(s["sha256"])
                for k, h in (m.get("kb_shas") or {}).items():
                    shas.setdefault(k, set()).add(h)

            def state(rel):
                # stock = byte-equal to the previous kit copy (still on disk: the kit is replaced at apply) or a recorded hash
                dst = self.kb / rel
                if not dst.exists():
                    return "deleted" if fwd(dst) in known else "missing"
                h, prev = sha(dst), sha(self.kit / "kb-template" / rel)
                return "current" if h == sha(tpl / rel) else "stock" if h == prev or h in shas.get(fwd(dst), ()) else "edited"
            st = {f: state(f) for f in files if f in KB_PAIR or f.startswith("_shared/digests/")}
            pair_ok = all(st[f] in ("stock", "current", "missing") for f in KB_PAIR if f in st)
            todo_pair = [f for f in KB_PAIR if f in st and pair_ok and st[f] in ("stock", "missing")]
            seed = [f for f in files if not (self.kb / f).exists() and fwd(self.kb / f) not in known and f not in KB_PAIR]
            seed += [f for f in todo_pair if st[f] == "missing"]
            refresh = [f for f in todo_pair + sorted(f for f in st if f not in KB_PAIR) if st[f] == "stock"]
            if not pair_ok:
                why = ", ".join(f"{Path(f).name} is {'edited' if st[f] == 'edited' else 'removed'}"
                                for f in KB_PAIR if st.get(f) in ("edited", "deleted"))
                self.warnings.append(f"Kept your bug-cards.md and bug-detectors.json as they are: they update together, and "
                                     f"{why}. This release's pair is in {fwd(self.kit / 'kb-template' / '_shared')}; "
                                     "copy both over yours to take it.")
            for f in (f for f in st if st[f] == "edited" and f not in KB_PAIR):
                self.warnings.append(f"Kept your edited {f}; this release's copy is at {fwd(self.kit / 'kb-template' / f)}.")
            if not seed and not refresh:
                self.todo(f"[kb] keep the existing knowledge base at {fwd(self.kb)}")
                return

            def add():
                for f in seed:
                    dst = self.kb / f
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(tpl / f, dst)
                    self.manifest["kb_seeded"].append({"path": fwd(dst), "sha256": sha(dst)})
                for f in refresh:   # backed up and recorded like any changed file: uninstall puts the old copy back
                    self.write_bytes(self.kb / f, (tpl / f).read_bytes())
                    self.manifest.setdefault("kb_shas", {})[fwd(self.kb / f)] = sha(self.kb / f)
            self.todo(f"[kb] keep the knowledge base at {fwd(self.kb)}"
                      + (f"; add {len(seed)} new template file(s): " + ", ".join(seed) + " (uninstall removes them only if unchanged)"
                         if seed else "")
                      + (f"; refresh {len(refresh)} unedited file(s) to this release: " + ", ".join(refresh)
                         + " (uninstall restores the old copy)" if refresh else ""), add)
            return

        def make():
            if self.kb.exists():
                self.kb.rmdir()
            shutil.copytree(tpl, self.kb)
            self.manifest["kb_created"] = fwd(self.kb)
            self.manifest["kb_files"] = files
            self.manifest["kb_shas"] = {fwd(self.kb / f): sha(self.kb / f) for f in files
                                        if f in KB_PAIR or f.startswith("_shared/digests/")}
        self.todo(f"[kb] create the knowledge base at {fwd(self.kb)} from kb-template/ (uninstall never deletes it)", make)

    def make_data(self):
        new = not self.data.exists()
        self.data.mkdir(parents=True, exist_ok=True)
        if new and os.name == "nt" and self.od_work and under(self.data, self.od_work) and shutil.which("attrib"):
            # "Always keep on this device": reads never trigger a cloud download and work offline
            subprocess.run(["attrib", "+P", "-U", str(self.data)], capture_output=True, timeout=60)

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
        ep = settings.get("enabledPlugins") if isinstance(settings.get("enabledPlugins"), dict) else {}
        self.plugin_snap = {pid: ep.get(pid, ABSENT) for pid in DEFAULT_PLUGINS + (CAPTURE_PLUGIN,)}   # before the CLI step
        self.subagent_gate(frag)
        ops, notes = [], []
        prev = {tuple(op["path"]): op["value"] for m in self.prior for op in m.get("settings_ops") or []
                if op.get("op") == "set" and not op.get("container")}
        kit_default = (frag.get("permissions") or {}).get("defaultMode")
        mode = self.approvals_off(settings, frag, ops, prev) if self.approvals == "off" and self.a.profile == "corporate" else None
        full = copy.deepcopy(frag)                 # what the profile carries, before the entries the user removed come out
        self.before = copy.deepcopy(settings.get("permissions")) if isinstance(settings.get("permissions"), dict) else {}
        self.strip_user_removed(settings, frag, sp.exists())
        merge_settings(settings, frag, self.managed, self.a.force, ops, notes, prev=prev)
        path = ("permissions", "defaultMode")
        cur = (settings.get("permissions") or {}).get("defaultMode") if isinstance(settings.get("permissions"), dict) else None
        self.user_mode, self.wrote_mode = self.prev.get("approvals_user_mode"), None
        if mode:
            if cur not in (None, mode, kit_default, self.prev.get("approvals_wrote_mode")):   # the user's own: --approvals ask gives it back
                self.user_mode = cur
            own(settings, list(path), mode, self.managed, ops, notes, self.warnings)
            self.wrote_mode = mode
        elif self.user_mode and self.a.profile == "corporate":
            if cur == kit_default:                                         # the merge put the kit's default back: give theirs
                own(settings, list(path), self.user_mode, self.managed, ops, notes, self.warnings)
            self.user_mode = None                                          # a mode they picked since is theirs to keep
        self.retire_permissions(settings, full, ops)
        self.retire_old_rules(settings, full, ops)
        if managed_has(self.managed, ("permissions", "deny"), []):
            notes.append(("permissions.deny", "set by a managed source: the active-context deny is not written"))
        self.plan.append(f"[settings] profile {self.a.profile} ({fwd(src.relative_to(REPO))}); upstream plugins: "
                         f"{'yes' if self.upstream else 'no'}; optional upstream plugins: "
                         f"{'yes' if self.a.upstream_plugins_optional else 'no'}"
                         + (f"; approvals: off (new windows start in {mode})" if mode else
                            "; approvals: ask" if self.a.profile == "corporate" else ""))
        self.manifest["settings_ops"] = ops
        return settings, ops, notes

    def approvals_off(self, settings, frag, ops, prev):
        """--approvals off on the corporate profile: ordinary commands run without a prompt. Changes the profile before the
        merge: no disableBypassPermissionsMode, and Bash(*), PowerShell(*) and Edit(*) allowed (they matter when bypass mode is
        unavailable, and the profile's ask rules and the active-context deny still win over them). Removes the disableBypassPermissionsMode an earlier kit
        install wrote, recorded so uninstall or `--approvals ask` puts it back. Returns the mode new windows start in:
        bypassPermissions, or acceptEdits when a managed policy or the user's own setting keeps bypass mode off."""
        perms = frag.setdefault("permissions", {})
        perms.pop("disableBypassPermissionsMode", None)
        perms.pop("defaultMode", None)                     # owned below, after the merge (the minimal ask set stays)
        perms["allow"] = list(dict.fromkeys((perms.get("allow") or []) + ["Bash(*)", "PowerShell(*)", "Edit(*)"]))
        key = ("permissions", "disableBypassPermissionsMode")
        if managed_has(self.managed, key):
            self.warnings.append("approvals off: your organisation's managed settings keep bypass mode off, so new windows "
                                 "start in acceptEdits and the allow rules run ordinary commands without a prompt")
            return "acceptEdits"
        cur = settings.get("permissions") if isinstance(settings.get("permissions"), dict) else {}
        if key[1] in cur:
            if prev.get(key) == cur[key[1]]:               # the value an earlier kit install wrote: the kit's to remove
                ops.append({"op": "del", "path": list(key), "old": cur[key[1]]})
                del cur[key[1]]
            else:
                self.warnings.append(f"approvals off: you set permissions.disableBypassPermissionsMode yourself, so it is kept; "
                                     "new windows start in acceptEdits and the allow rules run ordinary commands without a prompt")
                return "acceptEdits"
        return "bypassPermissions"

    def kit_added(self, path):
        """Entries of a permissions list the kit still owns, replaying every earlier install's manifest OLDEST FIRST: a list-add
        of the missing entries or the whole list it created makes an entry the kit's; a list-remove (an approvals-off lift, a
        retire) makes it no longer the kit's, so a string the user typed after that is the user's. An entry the user already
        had is never in a list-add."""
        out = []
        for m in self.prior:
            for op in m.get("settings_ops") or []:
                if tuple(op.get("path") or ()) != tuple(path):
                    continue
                if op.get("op") == "list-remove":
                    gone = op.get("items") or []
                    out = [x for x in out if x not in gone]
                    continue
                if op.get("op") == "list-add":
                    items = op.get("items") or []
                elif op.get("op") == "set" and op.get("old") == ABSENT and isinstance(op.get("value"), list):
                    items = op["value"]
                else:
                    continue
                out += [x for x in items if x not in out]
        return out

    def retire_permissions(self, settings, frag, ops):
        """merge_settings only ever adds to a list, so an entry a newer profile dropped would stay for ever (0.3.1's permissive
        profile allowed `mcp__tokensave` server-wide; later ones do not). On an upgrade, remove the permission entries an EARLIER
        kit install added (its manifest records them: a list-add of the missing entries, or the whole list it created; an entry the user
        already had is in neither) and the profile now being applied no longer carries. A user's own entry is never touched.
        Only the ALLOW list here: dropping an allow can only tighten what Claude may do, while dropping a deny or an ask would
        loosen policy (on a managed laptop, and when an older kit runs after a newer one); asks and denies leave only through
        retire_old_rules (named strings). Recorded as list-remove, so uninstall puts them back before it undoes the earlier
        install."""
        added = {("permissions", "allow"): self.kit_added(("permissions", "allow"))}
        for path, items in added.items():
            cur = (settings.get("permissions") or {}).get(path[1])
            want = ((frag.get("permissions") or {}).get(path[1])) or []
            if not isinstance(cur, list) or managed_has(self.managed, path, []):
                continue
            gone = []
            for x in items:
                if x in cur and x not in want and x not in gone:
                    gone.append(x)
            if gone:
                remove_once(cur, gone)
                ops.append({"op": "list-remove", "path": list(path), "items": gone})
                self.warnings.append(f"{'.'.join(path)}: removed {', '.join(json.dumps(x) for x in gone)}. An earlier kit install "
                                     "added it and the profile now applied no longer has it (an entry you added yourself is kept).")

    def retire_old_rules(self, settings, frag, ops):
        """R2: the ask and deny strings the profiles of releases 0.2.0-0.3.4 carried (bootstrap/retired-rules.json, kit strings
        only) leave settings.json when the profile now applied no longer has them, and only with evidence the kit wrote them:
        the manifests, replayed oldest first, say the kit still owns the entry; or, when no manifest survives, an earlier install
        is evident (config.json or the kit copy) AND the old kit's whole block is there (at least 90% of the asks every release
        carried, all but one of its denies), so exact strings are the kit's. Without that evidence nothing is retired and one
        warning says so. A rule the user wrote is never touched, one occurrence per string goes (a user's own duplicate copy
        stays), the order of what remains is kept, and the active-context deny is never retired. One list-remove op per list."""
        try:
            retired = read_json(REPO / "bootstrap" / "retired-rules.json")
        except (OSError, ValueError):
            return self.warnings.append("bootstrap/retired-rules.json is missing from this copy of the kit: no old rule retired")
        perms = settings.get("permissions") if isinstance(settings.get("permissions"), dict) else {}
        exact = not self.prior and ((self.wb / "config.json").exists() or self.kit.is_dir())
        every = retired.get("every_release") if isinstance(retired.get("every_release"), dict) else {}
        unproven = []
        for key in ("ask", "deny"):
            cur = perms.get(key)
            if not isinstance(cur, list) or managed_has(self.managed, ("permissions", key), []):
                continue
            keep = set((frag.get("permissions") or {}).get(key) or [])
            if key == "deny":
                keep |= {ac_rule(self.kb)} | ({ac_rule(self.prev["kb_root"])} if self.prev.get("kb_root") else set())
            mine, old = set(self.kit_added(("permissions", key))), retired.get(key) or []
            core = old[:int(every.get(key) or 0)]
            have = sum(1 for x in core if x in (self.before.get(key) or []))     # what the user's file held, not the merge
            block = bool(core) and have >= (-(-9 * len(core) // 10) if key == "ask" else len(core) - 1)
            cand = [x for x in dict.fromkeys(x for x in cur if isinstance(x, str)) if x in set(old) and x not in keep]
            gone = [x for x in cand if x in mine or (exact and block)]
            if exact and not block and cand:
                unproven.append(f"permissions.{key} {len(cand)} (old kit block: {have} of {len(core)})")
            if gone:
                remove_once(cur, gone)
                ops.append({"op": "list-remove", "path": ["permissions", key], "items": gone})
                self.plan.append(f"[settings] permissions.{key}: retire {len(gone)} rule(s) an earlier kit wrote that this "
                                 "release no longer has (rules you wrote are kept)")
        if unproven:
            self.warnings.append("kept rules that equal an old kit's strings, because no install manifest shows the kit wrote "
                                 "them and the old kit's block is not there: " + "; ".join(unproven))

    def strip_user_removed(self, settings, frag, exists):
        """I7: an entry the ledger lists as kit-written and settings.json no longer has was removed by the user: it is
        remembered and taken out of the fragment, so the merge does not add it again. The kit's own single-owner entries
        (the active-context deny, the KB folder) are rewritten every time and never count. No ledger: nothing is removed."""
        led = self.ledger if isinstance(self.ledger, dict) else {}
        lists = led.get("lists") if isinstance(led.get("lists"), dict) else {}
        old = led.get("user_removed") if isinstance(led.get("user_removed"), dict) else {}
        self.user_removed = {k: [x for x in old.get(k) or [] if isinstance(x, str)] for k in LEDGER_KEYS}
        owned = {"permissions.deny": {ac_rule(self.kb)}, "permissions.additionalDirectories": {fwd(self.kb)}}
        if self.prev.get("kb_root"):
            owned["permissions.deny"].add(ac_rule(self.prev["kb_root"]))
            owned["permissions.additionalDirectories"].add(fwd(self.prev["kb_root"]))
        perms = settings.get("permissions") if isinstance(settings.get("permissions"), dict) else {}
        fp = frag.get("permissions") if isinstance(frag.get("permissions"), dict) else {}
        for key in LEDGER_KEYS:
            sub, got = key.split(".")[1], self.user_removed[key]
            cur = perms.get(sub) if isinstance(perms.get(sub), list) else []
            for x in (lists.get(key) or []) if exists else []:
                if x not in cur and x not in owned.get(key, ()) and x not in got:
                    got.append(x)
            if isinstance(fp.get(sub), list):
                fp[sub] = [x for x in fp[sub] if x not in got]
            self.frag_lists[key] = list(fp.get(sub) or []) if isinstance(fp.get(sub), list) else []
        n = sum(len(v) for v in self.user_removed.values())
        if n:
            self.plan.append(f"[settings] {n} entry/entries the kit wrote and you removed stay removed ({fwd(self.ledger_path)})")

    def claude_version(self):
        """(version tuple, text) of the claude CLI, or (None, None): no CLI, --no-cli, or no version line in its answer."""
        if not self.claude:
            return None, None
        try:
            r = subprocess.run([self.claude, "--version"], capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None, None
        for ln in ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").splitlines():
            ln = ln.strip()
            m = re.search(r"(\d+)\.(\d+)\.(\d+)", ln) if ln.endswith("(Claude Code)") or ln.startswith("Claude Code") else None
            if m:
                return tuple(int(x) for x in m.groups()), m.group(0)
        return None, None

    def subagent_gate(self, frag):
        """G-G: CLAUDE_CODE_SUBAGENT_MODEL is written only for Claude Code 2.1.251 or newer; older, it overrides every persona's
        own model. A value the user already has is never touched (the merge keeps it)."""
        env = frag.get("env") if isinstance(frag.get("env"), dict) else {}
        if "CLAUDE_CODE_SUBAGENT_MODEL" not in env:
            return
        ver, text = self.claude_version()
        if ver is None or ver < SUBAGENT_MIN:
            env.pop("CLAUDE_CODE_SUBAGENT_MODEL")
            self.warnings.append(f"CLAUDE_CODE_SUBAGENT_MODEL not set: Claude Code {text or 'unknown'} lets it override every "
                                 "persona's model (fixed in 2.1.251). Update Claude Code and re-run the installer.")

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
        if not managed_has(self.managed, ("permissions", "deny"), []):   # any profile, any approvals mode; a KB move takes it along
            deny = settings.setdefault("permissions", {}).setdefault("deny", [])
            old, new = (ac_rule(self.prev["kb_root"]) if self.prev.get("kb_root") else None), ac_rule(self.kb)
            if old and old != new and old in deny:
                deny[:] = [x for x in deny if x != old]
                ops.append({"op": "list-remove", "path": ["permissions", "deny"], "items": [old]})
            if new not in deny:
                deny.append(new)
                ops.append({"op": "list-add", "path": ["permissions", "deny"], "items": [new]})
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
        ids = []
        for i in DEFAULT_PLUGINS + ((CAPTURE_PLUGIN,) if "capture" in self.with_ else ()):
            if (REPO / "plugins" / i.split("@")[0]).is_dir():
                ids.append(i)
            else:
                self.warnings.append(f"plugin {i} is not in this copy of the kit: skipped")
        self.plugin_choices(ids)
        ids = [i for i in ids if self.plugin_choice.get(i) != "removed-by-user"]     # uninstalled by the user: stays so
        pyids = [i for i in ids if i in python_plugin_ids()]     # their manifests declare userConfig.python
        config = ["--config", f"python={self.python}"]
        cmds = [["claude", "plugin", "marketplace", "remove", MARKETPLACE],
                ["claude", "plugin", "marketplace", "add", fwd(src)]] + \
               [["claude", "plugin", "install", i] + (config if i in pyids else []) for i in ids]
        shown = "\n".join(f"      {show(c)}" for c in cmds[1:])
        if not self.claude:
            self.todo("[plugins] the claude CLI is not on PATH (or --no-cli was given): after --apply, run:\n" + shown)
            if not self.a.no_cli:
                self.warnings.append("plugins were NOT re-registered: no `claude` command was found on PATH, so Claude Code keeps "
                                     "the plugin versions it had. Run the [plugins] commands above from a terminal where "
                                     "`claude --version` works, then restart Claude Code.")
            self.manifest["cli_pending"] = ids
            return

        def call(c):
            r = subprocess.run([self.claude, *c[1:]], capture_output=True, timeout=600)
            out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()
            print(f"  {show(c)} -> exit {r.returncode}\n" + "\n".join("    " + ln for ln in out.splitlines()))
            return r

        def run():
            for i, c in enumerate(cmds):
                if i == 0:     # removing an older registration of the same name; "not found" is fine
                    subprocess.run([self.claude, *c[1:]], capture_output=True, timeout=600)
                    continue
                r = call(c)
                if r.returncode != 0 and "--config" in c:
                    # an older CLI may not know --config: install without it; pin_python writes the setting afterwards
                    c = c[:-len(config)]
                    r = call(c)
                if r.returncode != 0:
                    self.failures.append(show(c))
                elif c[2] == "install":
                    self.manifest["cli"].append(c[3])
                else:
                    self.manifest["marketplace_added"] = True
            self.pin_python([i for i in pyids if i in self.manifest["cli"]])
            self.keep_plugin_choices()
        kept = [f"{i} ({self.plugin_choice[i]}, kept)" for i in self.plugin_choice if self.plugin_choice[i] != "enabled"]
        self.todo("[plugins] register the kit copy as the local marketplace `workbench` and install:\n" + shown
                  + ("".join(f"\n      keep {k}" for k in kept)), run)

    def plugin_choices(self, ids):
        """Item 6: a kit plugin the user set to false stays false; one a prior install's CLI step installed and that is gone
        from enabledPlugins now was uninstalled by the user and is not installed again. The newest prior install that ran
        the CLI is the evidence (an earlier failed step is never read as the user's choice). Never `claude plugin enable`."""
        last = next((m.get("cli") or [] for m in reversed(self.prior) if not m.get("no_cli")), [])
        led = self.ledger.get("plugins") if isinstance(self.ledger.get("plugins"), dict) else {}
        for pid, v in self.plugin_snap.items():
            if v is False:
                self.plugin_choice[pid] = "disabled-by-user"
            elif v is ABSENT and (pid in last or led.get(pid) == "removed-by-user") and pid in ids:
                self.plugin_choice[pid] = "removed-by-user"
            elif pid in ids:
                self.plugin_choice[pid] = "enabled"
        self.core_off = self.plugin_choice.get("workbench-core@workbench") in ("disabled-by-user", "removed-by-user")

    def keep_plugin_choices(self):
        """After the CLI step (which re-enables every plugin it installs): write false back for a plugin the user disabled."""
        sp = self.claude_home / "settings.json"
        try:
            s = read_json(sp)
        except (OSError, ValueError):
            return self.failures.append(f"{fwd(sp)} cannot be read back to keep the plugins you disabled off")
        ep = s.setdefault("enabledPlugins", {}) if isinstance(s.get("enabledPlugins", {}), dict) else None
        todo = [pid for pid, c in self.plugin_choice.items() if c == "disabled-by-user" and ep is not None
                and ep.get(pid) is not False and not managed_has(self.managed, ("enabledPlugins", pid))]
        for pid in todo:     # old = the value before this install: undo leaves it off too
            self.manifest["settings_ops"].append({"op": "set", "path": ["enabledPlugins", pid], "value": False, "old": False})
            ep[pid] = False
        if todo:
            self.write_file(sp, json.dumps(s, indent=2, ensure_ascii=False) + "\n")

    def pin_python(self, ids):
        """`marketplace remove` clears pluginConfigs, and an install without --config leaves userConfig unset; an unset
        python makes every hook fail (`Plugin option "python" isn't set`), silently. After the plugin step: write the
        interpreter where it is missing, read settings.json back, and fail loudly if it is still absent."""
        sp = self.claude_home / "settings.json"
        path = lambda i: ("pluginConfigs", i, "options", "python")  # noqa: E731

        def have():
            try:
                s = read_json(sp)
            except (OSError, ValueError):
                return None, {}
            return s, {i: (((s.get("pluginConfigs") or {}).get(i) or {}).get("options") or {}).get("python") for i in ids}
        s, now = have()
        if s is None:
            return self.failures.append(f"{fwd(sp)} cannot be read back after the plugin step")
        missing = [i for i in ids if now[i] != self.python and not managed_has(self.managed, path(i))]
        if missing:
            for i in missing:
                own(s, list(path(i)), self.python, self.managed, self.manifest["settings_ops"], [], self.warnings)
            self.write_file(sp, json.dumps(s, indent=2, ensure_ascii=False) + "\n")
            print("  the plugin step left the python option unset for " + ", ".join(missing) + ": wrote it to settings.json")
            s, now = have()
        for i in ids:
            if now.get(i) != self.python and not managed_has(self.managed, path(i)):
                self.failures.append(f"plugin option python is not set for {i} in {fwd(sp)}, so its hooks fail: run "
                                     f"claude plugin install {i} --config python={self.python}")

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
            now = time.time()
            self.manifest["utc"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now % 1 * 1e6):06d}Z"
            (self.backup / "manifest.json").write_text(json.dumps(self.manifest, indent=2) + "\n", encoding="utf-8")
        for w in self.warnings:
            print("WARNING: " + w)
        if self.core_off:
            print(off_text("workbench-core@workbench"))
        print(f"Applied. Backups and the uninstall manifest: {fwd(self.backup)}")
        print("Next: start Claude Code and run /hooks: the workbench hooks must be listed.")

    def write_ledger(self):
        """I7 <WB>/state/kit-written.json: the list entries this install wrote and still finds in settings.json, the entries
        the user removed, the plugins the user turned off. Every other key (setup's relay_hooks, unknown ones) is kept."""
        try:
            s = read_json(self.claude_home / "settings.json")
        except (OSError, ValueError):
            s = {}
        perms = s.get("permissions") if isinstance(s.get("permissions"), dict) else {}
        lists = {}
        for key in LEDGER_KEYS:
            sub = key.split(".")[1]
            cur = perms.get(sub) if isinstance(perms.get(sub), list) else []
            owned = {"permissions.deny": [ac_rule(self.kb)], "permissions.additionalDirectories": [fwd(self.kb)]}.get(key, [])
            lists[key] = list(dict.fromkeys(x for x in self.frag_lists[key] + owned if x in cur))
        d = dict(self.ledger) if isinstance(self.ledger, dict) else {}
        old = d.get("plugins") if isinstance(d.get("plugins"), dict) else {}
        d.update({"version": 1, "lists": lists, "user_removed": self.user_removed, "plugins": {**old, **self.plugin_choice},
                  "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        d.setdefault("relay_hooks", None)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ledger_path.with_name(f".{self.ledger_path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, self.ledger_path)

    # ── --setup: the capability report first, then provisioning ──
    def setup_cmds(self):
        kit = self.kit if (self.kit / "bootstrap" / "setup.py").exists() else REPO
        py, setup = fwd(sys.executable), fwd(kit / "bootstrap" / "setup.py")
        extra = (["--with", ",".join(self.with_)] if self.with_ else []) + (["--no-nightly"] if self.a.no_nightly else []) + \
                (["--no-update"] if self.a.no_update else [])
        report = os.environ.get("WORKBENCH_REPORT_CLI") or fwd(kit / "bootstrap" / "report.py")
        pre = [py, report, "run", "--phase", "pre", "--packages", fwd(kit / "bootstrap" / "packages.json")]
        return pre, [py, setup, "plan", *extra], [py, setup, "run", "--detach", *extra], [py, setup, "status", "--json", "--wait", "60"]

    def chain_setup(self):
        """--setup auto: report pre (shown before any install), then the detached setup runner; plan: report + plan."""
        pre, plan, run, poll = self.setup_cmds()
        if not self.a.setup:
            print("Next, to provision this machine (capability report first, then installs; it stops only for a UAC "
                  "prompt, a reboot or something your IT team must allow):\n  " + show(run) + "\n  then poll: " + show(poll))
            return 0
        if Path(pre[1]).exists():
            print("Capability report (before anything is installed):", flush=True)
            r = subprocess.run(pre, timeout=600)
            if r.returncode:
                print(f"WARNING: the capability report exited {r.returncode}; setup continues")
        else:
            print(f"WARNING: {pre[1]} is not in this copy of the kit: no capability report")
        if self.a.setup == "plan":
            return subprocess.run(plan, timeout=600).returncode
        r = subprocess.run(run, timeout=120)
        if r.returncode == 0:
            print("Setup is running in the background. Poll it with:\n  " + show(poll))
        return r.returncode


# ── uninstall ────────────────────────────────────────────────────────────────────────────────────────────────
def _rewrite_text_file(p, keep_line):
    """Rewrite a user text file without the lines keep_line() rejects, keeping its encoding, BOM and line endings."""
    text, enc, bom = decode_text(p.read_bytes())
    out = "".join(ln for ln in text.splitlines(keepends=True) if keep_line(ln))
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + out.encode(enc if enc != "latin-1" else "utf-8"))


def layout_resolved(home):
    """[(entry, absolute path or None)] for the layout.json dir/file entries, tokens resolved for this install."""
    wb = home / "workbench"
    try:
        cfg = read_json(wb / "config.json")
    except (OSError, ValueError):
        cfg = {}
    dev = cfg.get("dev_drive")
    tok = {"<CH>": home, "<WB>": wb, "<KIT>": wb / "kit", "<LAD>": lad(), "<HOME>": Path.home(),
           "<DATA>": cfg.get("data_root"), "<KB>": cfg.get("kb_root"), "<DEVDRIVE>": dev,
           "<SRC>": Path(dev) / "src" if dev else Path.home() / "src"}
    if cfg.get("profile_of"):     # a per-client profile shares <LAD> with the main install: never remove its caches
        tok["<LAD>"] = None
    try:
        entries = read_json(Path(__file__).resolve().parent / "layout.json")["paths"]
    except (OSError, ValueError, KeyError):
        return []
    out = []
    for e in entries:
        if e.get("kind") in ("dir", "file"):
            t, _, rest = e["path"].partition("/")
            out.append((e, Path(tok[t]) / rest if tok.get(t) else None))
    return out


def layout_removals(home):
    """Paths layout.json marks uninstall=remove. Task, registry and env entries are setup's undo-config job."""
    return [p for e, p in layout_resolved(home) if p and e.get("uninstall") == "remove"]


def uninstall(a):
    claude_home_ = claude_home()
    wb = claude_home_ / "workbench"
    manifests = list(reversed(manifests_in_order(wb)))      # newest first
    print(f"claude-workbench uninstall ({'APPLY' if a.apply else 'DRY RUN: nothing is changed; add --apply'})")
    removals = layout_removals(claude_home_)
    failed = False
    try:   # machine changes setup recorded (task, RunOnce, env vars, gitconfig key, PATH shim, capture profile)
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import setup as setup_mod
        failed = setup_mod.undo_config(apply=a.apply) != 0
    except ImportError:
        print("  setup.py is not next to this installer: machine changes (if any) were not undone")
    if not manifests:
        print(f"  nothing to undo: no install manifest under {fwd(wb / 'backups')}")
        remove_layout(a, removals)
        return purge_backups(a, wb, failed)
    keep = wb / "backups" / f"uninstall-{time.strftime('%Y%m%d-%H%M%S')}"
    claude = None if a.no_cli else shutil.which("claude")
    ran = set()
    for mf, m in manifests:
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
                    if f["existed"] and orig is not None and s == orig:
                        shutil.copy2(f["backup"], p)   # the same content as before the install: its own bytes and format back
                    elif not f["existed"] and not s:
                        p.unlink()   # the install created it; only empty objects (left by the claude CLI) remain
                    else:
                        p.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
            elif p.name == "CLAUDE.md" and p.exists() and m.get("claude_md_line"):
                print(f"    {f['path']} changed since the install: removing only the @import line")
                if a.apply:
                    _rewrite_text_file(p, lambda ln: ln.strip() != m["claude_md_line"])
            elif p.exists():
                print(f"    {f['path']} changed since the install: left as is (backup: {f.get('backup')})")
        for s in m.get("kb_seeded") or []:
            p = Path(s["path"])
            if not p.exists():
                continue
            if sha(p) != s.get("sha256"):
                print(f"    keep {s['path']} (a template file this install added; you edited it)")
                continue
            print(f"    remove {s['path']} (a template file this install added, unchanged)")
            if a.apply:
                p.unlink()
                kb, d = Path(m.get("kb_root") or p.parent), p.parent
                while d != kb and under(d, kb) and not any(d.iterdir()):
                    d.rmdir()
                    d = d.parent
        if m.get("kb_created"):
            print(f"    keep the knowledge base at {m['kb_created']} (your data; delete it yourself if you want)")
        if a.apply:
            os.replace(mf, mf.with_name("manifest.uninstalled.json"))
    for d in (wb / "instructions",):
        if a.apply and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    remove_layout(a, removals)
    print(f"Done. Logs, backups and the knowledge base stay: {fwd(wb)}" if not a.purge_backups else
          f"Done. Logs and the knowledge base stay: {fwd(wb)}")
    return purge_backups(a, wb, failed)


def remove_layout(a, removals):
    """Runtime folders and files layout.json marks remove (state, venv, shims, caches, the capture runtime)."""
    for p in removals:
        if p.exists():
            print(f"    {'remove' if a.apply else 'would remove'} {fwd(p)}")
            if a.apply:
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)


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
    ap = argparse.ArgumentParser(allow_abbrev=False, description="claude-workbench installer: a dry run unless --apply. "
                                             "Run it as: py -3 bootstrap\\install.py (Windows) or python3 "
                                             "bootstrap/install.py (Linux, WSL).")
    ap.add_argument("--apply", action="store_true", help="write the plan (default: print it only)")
    ap.add_argument("--profile", choices=["corporate", "permissive"], default="corporate",
                    help="settings profile (default corporate); permissive implies --upstream-plugins")
    ap.add_argument("--upstream-plugins", action="store_true", help="merge settings/upstream-plugins.fragment.json")
    ap.add_argument("--upstream-plugins-optional", action="store_true",
                    help="merge settings/upstream-plugins.optional.fragment.json (never implied)")
    ap.add_argument("--kb-root", help="knowledge-base folder (default: the last install's, else <data root>/kb)")
    ap.add_argument("--data-root", help="workbench data folder (default: the last install's, else <work OneDrive>/"
                                        "Workbench when exactly one verified work OneDrive exists, else ~/Workbench)")
    ap.add_argument("--git-hosts", help="accepted and ignored, so older setup commands still run")
    ap.add_argument("--approvals", choices=["ask", "off"], help="corporate profile: ask before each command (default) or run "
                                                                 "ordinary commands without asking; kept across upgrades")
    ap.add_argument("--setup", choices=["auto", "plan"], help="after --apply: capability report, then provision "
                                                               "(auto, in the background) or only plan")
    ap.add_argument("--with", dest="with_", help="opt-ins, comma-separated: " + ", ".join(EXTRAS))
    ap.add_argument("--no-nightly", action="store_true", help="permissive profile: no nightly knowledge refresh task")
    ap.add_argument("--no-update", action="store_true", help="passed on to setup: skip its update phase")
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
            if a.setup:
                pre, plan, run, _ = inst.setup_cmds()
                print(f"--setup {a.setup}: after --apply, would run:\n  {show(pre)}\n  {show(plan if a.setup == 'plan' else run)}")
            return 0
        inst.apply()
        if inst.failures:
            print("FAILED steps: " + "; ".join(inst.failures))
            return 4
        return inst.chain_setup()
    except Stop as s:
        print(("STOP: " if s.code == 3 else "ERROR: ") + str(s))
        return s.code


if __name__ == "__main__":
    sys.exit(main())
