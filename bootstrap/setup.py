#!/usr/bin/env python3
"""claude-workbench setup: take this machine from "Claude Code only" to a verified workbench (Python 3.10+, stdlib).

  setup.py run [--detach] [--with LIST] [--no-nightly] [--no-update]
                                        report -> plan -> install -> WSL -> verify -> update -> onboard ->
                                        knowledge -> capture runtime -> knowledge-verify (+ nightly) -> routing -> report
  setup.py plan [--with LIST]           write <state>/plan.json, plan.md and workbench.winget; installs nothing
  setup.py resume                       continue after the WSL reboot (the RunOnce value runs it once at sign-in)
  setup.py verify                       version-probe every package (PATH re-read from the registry first)
  setup.py update [--check] [--json]    move the tools THIS kit installed to the tested pins in packages.json (--with
                                        update-latest: to the newest). IT-installed tools are only reported, tools in
                                        use are deferred with the one command to run. --check changes nothing. Writes
                                        <state>/update.json and update.md
  setup.py status [--json] [--wait N]   the state object; --wait returns early on a phase change
  setup.py undo-config [--apply]        undo what setup changed on this machine (dry run unless --apply)
  setup.py routing                      rewrite routing.effective.json from the routing table and the probe
  setup.py doctor [--deep] [--json] [--bundle OUT.zip]   --deep adds the Day-1 knowledge checks (D1-D23, written to
                                        <state>/knowledge-verify.json) to every doctor row; its exit is nonzero only
                                        for a FAIL in any row (a WARN exits 0)
  setup.py skills [--dry-run] [--force]  measure the whole skill listing; over 80% of Claude Code's limit, list the user's own skills
                                        by name only (skillOverrides, settings.json backed up first, values you set kept unless
                                        --force, plugin skills never touched). `run` does this too; the doctor has a row for it
  setup.py backup [--out ZIP] [--if-older-days N]   KB notes, journal + curated config -> <data root>/backup/ unless
                                        --out; with --if-older-days nothing is written while the newest backup is younger
  setup.py restore ZIP [--to DIR] [--apply] [--force] [--restore-settings]   hashes and paths checked first;
                                        settings files (hooks run code) only with --restore-settings
  setup.py report ...                   passes its arguments to bootstrap/report.py

It stops only where a person must act: a UAC prompt (the human clicks), a reboot, or a policy block, which becomes
an ask-IT line and is never retried by another route or shell. Decisions come from exit codes and registry or policy
values, never from a tool's English output. Software comes only from winget (and the Store through it), PyPI, npm and
vendors' own GitHub releases. Nothing here elevates by itself, writes a Policies key or touches managed settings.
State: <CLAUDE_CONFIG_DIR or ~/.claude>/workbench/state/. Exit codes: 0 done · 2 usage, environment or already
running · 3 done with ask-IT items · 4 a step failed · 5 waiting on a human (reboot).
Test seams (env): WORKBENCH_FAKE_BIN, WORKBENCH_FAKE_REGISTRY, WORKBENCH_MANAGED_SETTINGS, WORKBENCH_FIND_CLI,
WORKBENCH_REPORT_CLI, WORKBENCH_PROBE_JSON, WORKBENCH_POLICY_CLI, WORKBENCH_NET_POLL_S,
WORKBENCH_VERIFY_JSON (a canned knowledge-verify result).
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
sys.path.insert(0, str(HERE))
import asks as ASKS  # noqa: E402
import install as I  # noqa: E402
import knowledge_verify as KV  # noqa: E402
import skill_tiers as ST  # noqa: E402

fwd, show, sha = I.fwd, I.show, I.sha
PY = I.console_python()       # never pythonw for a child whose output is read (detached runs start under pythonw)
NO_WINDOW = 0x08000000 if os.name == "nt" else 0     # CREATE_NO_WINDOW: a console child of pythonw opens no window
WIN = os.name == "nt"
PHASES = ("report-pre", "plan", "install", "wsl", "reboot-wait", "resume", "verify", "update", "onboard", "knowledge",
          "capture-runtime", "knowledge-verify", "routing", "report-post", "done")
TAGS = ("works", "found", "no-admin", "one-admin-prompt", "ask-IT", "opt-in-off")
# Every subprocess setup starts gets these (pip, npm and model downloads included): no telemetry, no update nags.
TELEMETRY_ENV = {"HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                 "NPM_CONFIG_UPDATE_NOTIFIER": "false", "NPM_CONFIG_FUND": "false"}
ENV_KEY = r"HKCU\Environment"
HKLM_ENV = r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
RUNONCE_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce"
RUNONCE_NAME = "wb-setup-resume"
TASK = "\\claude-workbench\\knowledge-refresh"
APPINSTALLER = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\AppInstaller"
WSL_POLICY = r"HKLM\SOFTWARE\Policies\WSL"
STORE_POLICY = r"HKLM\SOFTWARE\Policies\Microsoft\WindowsStore"
APPX_POLICY = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\Appx"      # value names ASSUMED (confirm on a managed laptop)
DISTRO = "Ubuntu-24.04"                                             # plain "Ubuntu" is now 26.04: pin the LTS
NET_URL = "https://cdn.winget.microsoft.com/cache/source2.msix"
NET_POLL_S = float(os.environ.get("WORKBENCH_NET_POLL_S") or 10)
RUNONCE_MAX = 260                                                   # RunOnce command lines are cut at 260 characters

# winget return codes (winget-cli doc/windows/package-manager/winget/returnCodes.md) plus the Win32/HRESULT codes for
# "access denied" (5) and "cancelled", which is what a declined UAC prompt returns (1223).
DECLINED = {0x8A15010C, 0x8A15C00B, 0x8A150077, 1223, 0x800704C7}  # the human said no (UAC, agreement, sign-in)
POLICY_DENIED = {0x8A15003A, 0x8A15010F, 0x8A15001B, 0x8A15001C, 0x8A150019, 0x8A150085, 0x8A15C111, 5, 0x80070005}
DENIED = DECLINED | POLICY_DENIED                                   # hard stop: nothing retries these by another route
CONFIGURE_UNAVAILABLE = {0x8A150002, 0x8A15001D, 0x8A15001E, 0x8A15C004, 0x8A15C101, 0x8A15C102, 0x8A15C108,
                         0x8A15C112}                                # winget too old, or the DSC processor is missing
ALREADY = {0x8A150061, 0x8A15010D}
REBOOT = {0x8A150109, 3010}
NOT_FOUND = 0x8A150014
UPDATE_NOT_APPLICABLE = 0x8A15002B                                  # winget upgrade: no newer version exists
IN_USE = {0x8A150101, 0x8A150103, 0x8A150111}                       # the program, or one of its files, is running
DOWNGRADE = 0x8A15010E                                              # a higher version is already installed
# ctx (packages.json id "ctx"): everything that runs in the background or calls out is off before its first use.
CTX_ENV = {"CTX_ANALYTICS_ENABLED": "false", "CTX_DAEMON_ENABLED": "false", "CTX_UPGRADE_AUTO": "off"}
# ctx's own config file (<data root>/config.toml): the keys were verified against the pinned ctx 2.2.8 itself
# (build-notes/v032-fetch.md): ctx rejects unknown keys and wrong types, and `ctx docs show storage` documents these two.
CTX_CONFIG = (("analytics", "enabled", "false"),     # telemetry off; the CTX_ANALYTICS_ENABLED variable stays set too
              ("sources", "automatic", "false"))     # only named roots are read: no sweep of 30 other agents' folders
RESTART = ("Close every Claude Code window and start a new one from a fresh terminal: the new PATH and the plugin "
           "options only reach programs started after this run.")
CLI_CONFIG_ENV = "PLAYWRIGHT_MCP_CONFIG"                            # path to the Playwright CLI's configuration file
NPM_ENV = {"PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1"}                 # Edge is the browser: the CLI downloads none
UPDATE_ACTIONS = ("upgraded", "current", "deferred", "it-managed", "skipped-policy", "denied", "failed")
ASK = {
    "wsl": "Please allow WSL 2 on my managed laptop. Installing it (wsl --install --no-distribution) needs an "
           "administrator once and a reboot; I add the Ubuntu 24.04 distribution myself. If the WSL policy AllowWSL "
           "is 0 for my device, please enable it.",
    "winget-configure": "Please enable winget configuration (policy EnableWindowsPackageManagerConfiguration) so my "
                        "developer tools install from one reviewable configuration file. Until then setup installs "
                        "them one at a time with winget.",
    "capture-runtime": "Please allow browser automation for Microsoft Edge on my managed laptop (the "
                       "RemoteDebuggingAllowed policy is off). The workbench reads intranet pages I can already open, "
                       "read-only and at a human pace, in a dedicated signed-in profile.",
}


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hx(rc):
    return "none" if rc is None else (f"0x{rc:08X}" if rc > 0xFFFF else str(rc))


def jload(path, default=None):
    try:
        return I.read_json(path)
    except (OSError, ValueError, TypeError):
        return default


def atomic_write(path, text):
    """tmp in the same folder, then os.replace: a reader (or a crash) never sees half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    for _ in range(40):
        try:
            return os.replace(tmp, path)
        except PermissionError:      # Windows: a status reader holds the old file open for a moment
            time.sleep(0.05)
    os.replace(tmp, path)


def jparse(b):
    try:
        d = json.loads(decode(b) or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def jwrite(path, obj):
    atomic_write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def decode(b):
    """Tool output as text. wsl.exe prints UTF-16LE (with or without a BOM); everything else UTF-8."""
    b = b or b""
    if b.startswith(b"\xff\xfe") or (len(b) > 1 and b[1:2] == b"\0" and b[0:1] != b"\0"):
        return b.decode("utf-16-le", "replace").lstrip("﻿").replace("\0", "")
    return b.decode("utf-8", "replace").lstrip("﻿").replace("\0", "")


def parse_wsl_list(raw):
    """[{name, state, version, default}] from `wsl -l -v`. The header row is localised, so it is skipped by position;
    rows are NAME ... VERSION with '*' on the default. Structure only, never words."""
    rows = []
    for line in [ln for ln in decode(raw).splitlines() if ln.strip()][1:]:
        s = line.strip()
        default = s.startswith("*")
        parts = s.lstrip("*").split()
        if len(parts) >= 3 and parts[-1].isdigit():
            rows.append({"name": parts[0], "state": " ".join(parts[1:-1]), "version": int(parts[-1]), "default": default})
    return rows


def parse_version(raw):
    m = re.search(r"\d+\.\d+\.\d+", decode(raw))
    return m.group(0) if m else None


def packages():
    return I.read_json(HERE / "packages.json")["packages"]


def pkg(pid):
    return next(p for p in packages() if p["id"] == pid)


def find_python(ctx, accept=None):
    """(argv prefix, version) of the first Python the knowledge venv accepts, in the order of packages.json python313
    "accept" (the one list of accepted versions: 3.13, then 3.14); (None, None) when none answers."""
    for v in accept or pkg("python313")["accept"]:
        argv = ["py", f"-{v}"] if WIN else [f"python{v}"]
        rc, out = ctx.run([*argv, "--version"], timeout=60)
        m = re.search(r"(\d+\.\d+\.\d+)", decode(out)) if rc == 0 else None
        if m and m.group(1).startswith(v + "."):
            return argv, m.group(1)
    return None, None


def pythonw():
    p = Path(sys.executable).with_name("pythonw.exe")
    return str(p) if WIN and p.exists() else sys.executable


def runonce_command(pyw, script, limit=RUNONCE_MAX):
    """The RunOnce command line, or None when even the 8.3 short paths do not fit in `limit` characters."""
    for a, b in ((pyw, script), (I.short_path(pyw), I.short_path(script))):
        cmd = f'"{Path(a)}" "{Path(b)}" resume'
        if len(cmd) <= limit:
            return cmd
    return None


def task_xml(description, actions, enabled=True):
    """Task Scheduler XML for the signed-in user: daily, StartWhenAvailable, never on battery, least privilege."""
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    acts = "".join(f"<Exec><Command>{esc(c)}</Command><Arguments>{esc(a)}</Arguments></Exec>" for c, a in actions)
    return ('<?xml version="1.0" encoding="UTF-16"?>\n'
            '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
            f"<RegistrationInfo><Description>{esc(description)}</Description></RegistrationInfo>"
            "<Triggers><CalendarTrigger><StartBoundary>2026-01-01T02:30:00</StartBoundary><Enabled>true</Enabled>"
            "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers>"
            '<Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType>'
            "<RunLevel>LeastPrivilege</RunLevel></Principal></Principals>"
            "<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>"
            "<DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>"
            "<StopIfGoingOnBatteries>true</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable>"
            f"<ExecutionTimeLimit>PT2H</ExecutionTimeLimit><Enabled>{'true' if enabled else 'false'}</Enabled>"
            "<Priority>7</Priority></Settings>"
            f'<Actions Context="Author">{acts}</Actions></Task>\n')


def dsc_yaml(items):
    """winget configure document (DSC v3 processor) for the user-scope items. Microsoft.WinGet/Package has no scope
    property, so machine-scope packages never go here (winget's user-first preference would pick a portable build)."""
    out = ["# claude-workbench user-scope packages. Apply with:",
           "#   winget configure -f workbench.winget --accept-configuration-agreements --disable-interactivity",
           "$schema: https://raw.githubusercontent.com/PowerShell/DSC/main/schemas/2023/08/config/document.json",
           "metadata:", "  winget:", "    processor:", "      identifier: dscv3", "resources:"]
    for it in items:
        out += ["- type: Microsoft.WinGet/Package", f"  name: {re.sub(r'[^A-Za-z0-9]', '', it['item'])}",
                "  properties:", f"    id: {it['winget']}", "    source: winget", "    useLatest: true",
                "    acceptAgreements: true"]
    return "\n".join(out) + "\n"


def effective_routing(routing, models):
    """I3b rows in I3a order: the first chain model the managed policy allows; fallback_used when it is not the first."""
    provider = models.get("provider") or "anthropic"
    denied, avail = models.get("denied") or [], models.get("available")
    verified, match = isinstance(avail, list), models.get("match") or "exact"

    def ids(m):
        return {m, ((routing.get("provider_ids") or {}).get(m) or {}).get(provider) or m}

    def hit(lst, m):
        return any((i.startswith(e) if match == "prefix" else i == e) for e in lst for i in ids(m))
    rows = []
    for r in routing.get("rows") or []:
        why, pick = [], None
        for j, c in enumerate(r.get("chain") or []):
            if hit(denied, c["model"]):
                why.append(f"{c['model']} not allowed by managed deniedModels")
            elif verified and not hit(avail, c["model"]):
                why.append(f"{c['model']} not in managed availableModels")
            else:
                pick = (j, c)
                break
        if pick:
            j, c = pick
            m = ((routing.get("provider_ids") or {}).get(c["model"]) or {}).get(provider) or c["model"]
            rows.append({"id": r["id"], "persona": r.get("persona"), "model": m, "effort": c.get("effort"),
                         "fallback_used": j > 0, "reason": "; ".join(why) or None})
        else:
            rows.append({"id": r["id"], "persona": r.get("persona"), "model": None, "effort": None,
                         "fallback_used": True, "reason": "; ".join(why) or "empty chain"})
    return {"version": 1, "generated": now(), "provider": provider, "policy_sources": models.get("sources") or [],
            "models_verified": verified, "rows": rows}


# ── registry writes: HKCU only, never a Policies key (reads live in install.py) ──────────────────────────────
def _writable(key):
    k = key.replace("/", "\\")
    if not k.upper().startswith("HKCU\\") or "\\policies\\" in k.lower() + "\\":
        raise PermissionError(f"setup never writes {key}: only HKCU, never a Policies key")
    return k


def reg_set(key, name, data, typ=1):
    k = _writable(key)
    fake = os.environ.get("WORKBENCH_FAKE_REGISTRY")
    if fake:
        d = jload(fake, {}) or {}
        hit = next((x for x in d if I._rkey(x) == I._rkey(k)), k)
        d.setdefault(hit, {})[name] = [data, typ]
        return jwrite(fake, d)
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, k.split("\\", 1)[1], 0, winreg.KEY_SET_VALUE) as h:
        winreg.SetValueEx(h, name, 0, typ, data)


def reg_delete(key, name):
    k = _writable(key)
    fake = os.environ.get("WORKBENCH_FAKE_REGISTRY")
    if fake:
        d = jload(fake, {}) or {}
        for x in d:
            if I._rkey(x) == I._rkey(k):
                for n in [n for n in d[x] if n.lower() == name.lower()]:
                    del d[x][n]
        return jwrite(fake, d)
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, k.split("\\", 1)[1], 0, winreg.KEY_SET_VALUE) as h:
            winreg.DeleteValue(h, name)
    except FileNotFoundError:
        pass


def broadcast_env():
    """Tell Explorer the user environment changed, so new terminals see it without a sign-out."""
    if WIN and I.fake_registry() is None:
        try:
            import ctypes
            ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 3000, None)
        except Exception:
            pass


def blocked(path):
    """A policy value blocks when Enable*/Allow* = 0 or Block*/Disable*/Remove* = 1; an absent value never blocks."""
    key, _, name = path.rpartition("\\")
    v = I.reg_get(key, name)
    try:
        d = int(v[0]) if v else None
    except (TypeError, ValueError):
        return False
    if d is None:
        return False
    return d == 0 if re.match(r"(?i)enable|allow", name) else d == 1 if re.match(r"(?i)block|disable|remove", name) else False


def pid_alive(pid):
    if not pid:
        return False
    if WIN:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))      # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259            # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


# ── the context: paths, config, probe, state, logging, tools ─────────────────────────────────────────────────
class Ctx:
    def __init__(self, with_=(), no_nightly=False, no_update=False):
        self.ch = I.claude_home()
        self.wb = self.ch / "workbench"
        self.state_dir = self.wb / "state"
        self.lad, self.home = I.lad(), Path.home()
        self.cfg = jload(self.wb / "config.json", {}) or {}
        self.profile = self.cfg.get("profile") or "corporate"
        self.data_error = None
        try:
            self.data = Path(self.cfg["data_root"]) if self.cfg.get("data_root") else I.resolve_data_root(None, {})[0]
        except I.Stop as e:
            self.data, self.data_error = self.home / "Workbench", str(e)
        self.kb = Path(self.cfg.get("kb_root") or self.data / "kb")
        st = jload(self.state_dir / "setup-state.json", {}) or {}
        opts = st.get("options") or {}
        self.prev_version = st.get("kit_version")                              # the release this machine ran before this run
        self.with_ = set(with_) if with_ else set(opts.get("with") or [])     # resume reuses the run's options
        self.no_nightly = bool(no_nightly or opts.get("no_nightly"))
        self.no_update = bool(no_update or opts.get("no_update"))
        self.st = {"version": 1, "phase": None, "running": False, "pid": None,
                   "exit_code": None, "next": None, "updated": None, "reboot_pending": False,
                   "ask_it": [], "failed": [], **st, "kit_version": I.VERSION}      # the running kit decides, never the old file
        self.st["options"] = {"with": sorted(self.with_), "no_nightly": self.no_nightly, "no_update": self.no_update}
        self.probe = {}
        self.notes = []
        self.suggestions = []                     # libraries find discovered but setup did not register (guide 28)
        self.roots_read = False                   # True once `find roots` was read, so "indexed or not" is known
        self.extra_env = {}                       # added to every program setup starts (ctx: its opt-outs, before first use)

    # state
    def save(self, **kw):
        self.st.update(kw, updated=now())
        jwrite(self.state_dir / "setup-state.json", self.st)

    def phase(self, name):
        self.log(f"== phase {name}")
        self.save(phase=name)

    def ask(self, item, text):
        """One entry per distinct ask: a second item that needs the same thing (two checks, one blocked download) is listed
        under the first as `also`, never as a second ask."""
        pairs = {}                                   # item -> text, from the deduplicated list the state holds
        for x in self.st["ask_it"]:
            pairs[x["item"]] = x["text"]
            pairs.update({a: x["text"] for a in x.get("also") or []})
        pairs[item] = text
        out = []
        for it, tx in pairs.items():
            same = next((o for o in out if ASKS.key(o["text"]) == ASKS.key(tx)), None)
            if same:
                same["also"] = [*(same.get("also") or []), it]
            else:
                out.append({"item": it, "text": tx})
        self.st["ask_it"] = out
        self.log(f"ASK IT [{item}]: {text}")

    def fail(self, item, error):
        self.st["failed"] = [x for x in self.st["failed"] if x["item"] != item] + [{"item": item, "error": error}]
        self.log(f"FAILED [{item}]: {error}")

    def clear(self, item):
        self.st["failed"] = [x for x in self.st["failed"] if x["item"] != item]

    def log(self, msg):
        line = f"{now()} {msg}"
        print(msg, file=sys.stderr, flush=True)      # stdout stays clean for --json output
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with open(self.state_dir / "setup.log", "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    # probe (I1): WORKBENCH_PROBE_JSON, else the probe the capability report recorded ("probe" in
    # capability-pre.json), else <state>/probe.json; probe.py runs only when none of them can be read
    def load_probe(self, run=True):
        env = os.environ.get("WORKBENCH_PROBE_JSON")
        ptr = (jload(self.state_dir / "capability-pre.json", {}) or {}).get("probe") if not env else None
        cands = [env] if env else ([Path(ptr) if os.path.isabs(str(ptr)) else self.state_dir / str(ptr)] if ptr else []) \
            + [self.state_dir / "probe.json"]
        d = next((x for x in (jload(c) for c in cands) if isinstance(x, dict)), None)
        if d is None and run and (HERE / "probe.py").exists():
            subprocess.run([PY, str(HERE / "probe.py"), "--out", str(self.state_dir), "--packages",
                            str(HERE / "packages.json")], capture_output=True, timeout=300, creationflags=NO_WINDOW)
            d = jload(self.state_dir / "probe.json")
        if d is None:
            self.notes.append("no probe.json: admin rights, TLS inspection and model policy are treated as unknown")
        self.probe = d or {}
        return self.probe

    def pdata(self, section):
        return ((self.probe.get("sections") or {}).get(section) or {}).get("data") or {}

    @property
    def admin(self):
        return self.pdata("identity").get("admin_capable") is True

    @property
    def tls_inspected(self):
        return any(h.get("inspected") == "yes" for h in self.pdata("tls").get("hosts") or [])

    # ledger of machine changes, replayed by undo-config
    def ledger(self):
        return jload(self.state_dir / "provision-ledger.json", {"version": 1, "entries": []})

    def record(self, entry, key):
        led = self.ledger()
        led["entries"] = [e for e in led["entries"] if e.get("key") != key] + [{**entry, "key": key, "at": now()}]
        jwrite(self.state_dir / "provision-ledger.json", led)

    # tools
    def fresh_path(self):
        """PATH as a new sign-in sees it: machine + user Path from the registry (expanded), WinGet Links, <WB>/bin."""
        parts = []
        for key in (HKLM_ENV, ENV_KEY):
            v = I.reg_get(key, "Path")
            if v and v[0]:
                parts += os.path.expandvars(str(v[0])).split(";")
        parts += [str(self.lad / "Microsoft" / "WinGet" / "Links"), str(self.wb / "bin")]
        if I.fake_registry() is None:
            parts += os.environ.get("PATH", "").split(os.pathsep)
        seen, out = set(), []
        for p in parts:
            if p and p.lower() not in seen:
                seen.add(p.lower())
                out.append(p)
        return os.pathsep.join(out)

    def which(self, name):
        fb = os.environ.get("WORKBENCH_FAKE_BIN")
        if fb:
            for ext in (".cmd", ""):
                if (Path(fb) / (name + ext)).is_file():
                    return str(Path(fb) / (name + ext))
        if os.path.isabs(name):
            return name if Path(name).is_file() else None
        return shutil.which(name, path=self.fresh_path())

    def run(self, argv, timeout=3600, cwd=None, alias=None, env=None):
        """(exit code or None when the program is missing, combined output bytes). alias = a fake-bin name that
        stands in for the whole command in tests (venv, pip). env = extra variables for this one call."""
        fb = os.environ.get("WORKBENCH_FAKE_BIN")
        if alias and fb and (Path(fb) / (alias + ".cmd")).is_file():
            argv, exe = [str(Path(fb) / (alias + ".cmd")), *argv], str(Path(fb) / (alias + ".cmd"))
        else:
            exe = self.which(str(argv[0]))
        if not exe:
            self.log(f"$ {show([str(a) for a in argv])} -> not found")
            return None, b""
        env = {**os.environ, "PATH": self.fresh_path(), **TELEMETRY_ENV, **self.extra_env, **(env or {})}
        try:
            r = subprocess.run([exe, *[str(a) for a in argv[1:]]], stdin=subprocess.DEVNULL, capture_output=True,
                               timeout=timeout, cwd=cwd, env=env, creationflags=0x08000000 if WIN else 0)
        except subprocess.TimeoutExpired:
            self.log(f"$ {show([str(a) for a in argv])} -> timeout after {timeout} s")
            return -1, b""
        except OSError as e:
            self.log(f"$ {show([str(a) for a in argv])} -> {e}")
            return None, b""
        rc = r.returncode & 0xFFFFFFFF if WIN else r.returncode
        self.log(f"$ {show([str(a) for a in argv])} -> {hx(rc)}")
        return rc, (r.stdout or b"") + (r.stderr or b"")

    def verify(self, p):
        """(works | found | absent, version) from the package's own verify argv; the PATH is re-read first. A package
        with "accept" (Python) works when any accepted version answers."""
        if p.get("accept"):
            argv, ver = find_python(self, p["accept"])
            return ("works", ver) if argv else ("absent", None)
        if not self.which(p["verify"][0]):
            return "absent", None
        rc, out = self.run(p["verify"], timeout=120)
        m = re.search(p["expect"], decode(out)) if rc == 0 else None
        return ("works", m.group(1)) if m else ("found", None)

    def find_cli(self):
        return os.environ.get("WORKBENCH_FIND_CLI") or str(KIT / "plugins" / "workbench-core" / "skills" / "find"
                                                              / "scripts" / "doc_index.py")

    def report_cli(self):
        return os.environ.get("WORKBENCH_REPORT_CLI") or str(HERE / "report.py")

    def policy_cli(self):
        return os.environ.get("WORKBENCH_POLICY_CLI") or str(KIT / "plugins" / "workbench-core" / "scripts"
                                                                / "policy_snapshot.py")

    def py_tool(self, script, *args, timeout=900):
        """(exit code, stdout bytes) of a kit Python CLI run with this interpreter; (None, b"") when it is missing. PATH is
        re-read from the registry, so a report after the installs sees the tools this run put on the user Path."""
        if not Path(script).is_file():
            return None, b""
        r = subprocess.run([PY, str(script), *[str(a) for a in args]], capture_output=True, timeout=timeout,
                           env={**os.environ, "PATH": self.fresh_path(), **TELEMETRY_ENV}, stdin=subprocess.DEVNULL,
                           creationflags=NO_WINDOW)
        self.log(f"$ {Path(script).name} {' '.join(str(a) for a in args)} -> {r.returncode}")
        return r.returncode, r.stdout or b""

    @property
    def store_blocked(self):
        return any(blocked(p) for p in (STORE_POLICY + r"\RemoveWindowsStore", STORE_POLICY + r"\DisableStoreApps",
                                        APPINSTALLER + r"\EnableMicrosoftStoreSource"))

    def venv_python(self, gui=False):
        return self.wb / "venv" / ("Scripts" if WIN else "bin") / (("pythonw.exe" if gui else "python.exe") if WIN else "python")


# ── locking and detaching (KILL3) ────────────────────────────────────────────────────────────────────────────
def lock_path(ctx):
    return ctx.state_dir / "setup.lock"


def lock_holder(ctx):
    try:
        pid = int(lock_path(ctx).read_text().strip() or 0)
    except (OSError, ValueError):
        return None
    return pid if pid_alive(pid) else None


def acquire(ctx):
    """O_EXCL pidfile; a lock whose pid is gone is stale and taken over."""
    ctx.state_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(lock_path(ctx), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            if lock_holder(ctx):
                return False
            lock_path(ctx).unlink(missing_ok=True)
    return False


def release(ctx):
    try:
        if lock_path(ctx).read_text().strip() == str(os.getpid()):
            lock_path(ctx).unlink()
    except OSError:
        pass


def detach(ctx, argv):
    """Re-launch `setup.py <argv>` with pythonw, detached, so it outlives the Claude Code session that started it."""
    if lock_holder(ctx):
        print("setup is already running (pid %s); poll it with: setup.py status --json --wait 60" % lock_holder(ctx))
        return 2
    ctx.state_dir.mkdir(parents=True, exist_ok=True)
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
              cwd=str(ctx.state_dir))        # the runner writes setup.log itself, tracebacks included
    cmd = [pythonw(), str(HERE / "setup.py"), *argv]
    if WIN:
        base = 0x00000008 | 0x00000200                  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        try:   # leave the caller's job object too, or closing the terminal kills setup; not every job allows it
            p = subprocess.Popen(cmd, creationflags=base | 0x01000000, **kw)
        except OSError:
            p = subprocess.Popen(cmd, creationflags=base, **kw)
    else:
        p = subprocess.Popen(cmd, start_new_session=True, **kw)
    print(f"setup is running in the background (pid {p.pid}); log: {fwd(ctx.state_dir / 'setup.log')}")
    print("poll: " + show([PY, fwd(HERE / "setup.py"), "status", "--json", "--wait", "60"]))
    return 0


# ── plan ─────────────────────────────────────────────────────────────────────────────────────────────────────
def appx_nonadmin_blocked():
    return blocked(APPX_POLICY + r"\BlockNonAdminUserInstall") or blocked(APPX_POLICY + r"\AllowAllTrustedApps")


def make_plan(ctx):
    items, admin = [], ctx.admin
    cli_off = any(blocked(APPINSTALLER + "\\" + n) for n in ("EnableAppInstaller",
                                                              "EnableWindowsPackageManagerCommandLineInterfaces"))
    configure_off = blocked(APPINSTALLER + r"\EnableWindowsPackageManagerConfiguration")
    winget = ctx.which("winget")
    for p in packages():
        if p["id"] == "fnm":
            continue                              # the user-scope route of node, planned with it
        it = {"item": p["id"], "name": p["name"], "source": p["source"], "winget": p.get("winget"),
              "scope": p["scope"], "hosts": p["hosts"], "tag": None, "version": None, "note": "", "via": None}
        items.append(it)
        it["ask_it"] = p["ask_it"]
        if p["optional_with"] and p["optional_with"] not in ctx.with_:
            it["tag"], it["note"] = "opt-in-off", f"add --with {p['optional_with']}"
            continue
        status, it["version"] = ctx.verify(p)
        if status == "works":
            it["tag"] = "works"
            if p.get("accept") and not it["version"].startswith(p["accept"][0] + "."):
                it["note"] = f"Python {it['version']} is accepted; {p['accept'][0]} is not installed"
            continue
        node = next((x for x in items if x["item"] == "node"), None) if p["source"] == "npm" else None
        if p["source"] == "npm" and (not node or node["tag"] in ("ask-IT", "opt-in-off")):
            it["tag"], it["note"] = "ask-IT", "needs Node.js (it brings npm), which is not available"
            it["ask_it"] = pkg("node")["ask_it"]
            continue
        if any(blocked(k) for k in p["policy_keys"]) or (p["source"] == "winget" and cli_off):
            it["tag"], it["note"] = "ask-IT", "blocked by an App Installer policy value"
            continue
        if p["source"] == "winget" and not winget:
            it["tag"], it["note"] = "ask-IT", "winget (App Installer) is not available"
            continue
        if p["id"] == "node" and not admin:
            f = pkg("fnm")
            if any(blocked(k) for k in f["policy_keys"]):
                it["tag"], it["note"] = "ask-IT", "no admin rights and fnm is blocked by policy"
                continue
            it.update(via="fnm", winget=f["winget"], scope="user", hosts=sorted(set(p["hosts"]) | set(f["hosts"])),
                      note="no admin rights: Node.js LTS through fnm with node/npm/npx shims")
        elif p["admin"] or (p["id"] == "pwsh" and appx_nonadmin_blocked()):
            if not admin:
                it["tag"], it["note"] = "ask-IT", "needs an administrator"
                continue
            it["scope"], it["note"] = "machine", "one UAC prompt (the installer elevates itself)"
        it["tag"] = "found" if status == "found" else ("one-admin-prompt" if it["scope"] == "machine" else "no-admin")
    if winget and not cli_off:
        items.append({"item": "winget-configure", "name": "winget configure (DSC v3)", "source": "winget",
                      "ask_it": ASK["winget-configure"],
                      "tag": "ask-IT" if configure_off else "no-admin", "scope": "user", "hosts": [],
                      "note": "configuration is off by policy: packages install one at a time" if configure_off else
                      ("the Store is blocked: Microsoft.DSC comes from the winget source first" if ctx.store_blocked else "")})
    items.append(wsl_item(ctx))
    if ctx.tls_inspected:
        items.append({"item": "tls-fixes", "name": "TLS inspection: system CA for Node, uv and Git", "source": "winget",
                      "tag": "no-admin", "scope": "user", "hosts": [], "note": "NODE_USE_SYSTEM_CA, UV_SYSTEM_CERTS, http.sslBackend"})
    for extra, name in (("claude-autoupdate", "Claude Code winget auto-update"), ("pm-pack", "PM skill pack"),
                        ("upstream-skills", "pinned upstream skills")):
        items.append({"item": extra, "name": name, "source": "github-release" if extra != "claude-autoupdate" else "winget",
                      "tag": "no-admin" if extra in ctx.with_ else "opt-in-off", "scope": "user", "hosts": [], "note": ""})
    items.append({"item": "update", "name": "update the tools this kit installed to the tested pins", "source": "winget",
                  "tag": "opt-in-off" if ctx.no_update else "no-admin", "scope": "user", "hosts": [],
                  "note": "--no-update" if ctx.no_update else
                  ("to the newest version (--with update-latest)" if "update-latest" in ctx.with_ else "")})
    items.append({"item": "nightly", "name": "nightly knowledge refresh (user task)", "source": "pypi",
                  "tag": "no-admin" if nightly_wanted(ctx) else "opt-in-off", "scope": "user", "hosts": [],
                  "note": "" if nightly_wanted(ctx) else ("add --with nightly" if ctx.profile == "corporate" else "--no-nightly")})
    cap = ctx.pdata("capture")
    items.append({"item": "capture-runtime", "name": "capture runtime", "source": "npm", "scope": "user", "hosts": [],
                  "ask_it": ASK["capture-runtime"],
                  "tag": "opt-in-off" if "capture" not in ctx.with_ else
                  ("ask-IT" if cap.get("automation_allowed") is False else "no-admin"),
                  "note": "headed only (headless mode is off by policy)" if cap.get("headless_allowed") is False else ""})
    plan = {"version": 1, "generated": now(), "admin_capable": admin, "store_blocked": ctx.store_blocked,
            "configure_off": configure_off, "notes": ctx.notes, "items": items}
    jwrite(ctx.state_dir / "plan.json", plan)
    atomic_write(ctx.state_dir / "plan.md", plan_md(plan))
    atomic_write(ctx.state_dir / "workbench.winget", dsc_yaml(user_winget(items)))
    return plan


def user_winget(items):
    return [it for it in items if it["tag"] in ("no-admin", "found") and it.get("source") == "winget"
            and it.get("winget") and it["scope"] == "user"]


def wsl_item(ctx):
    it = {"item": "wsl", "name": f"WSL 2 + {DISTRO}", "source": "msstore", "scope": "machine", "hosts": [], "note": "",
          "ask_it": ASK["wsl"]}
    if not WIN:
        return {**it, "tag": "works", "note": "not Windows"}
    if blocked(WSL_POLICY + r"\AllowWSL"):
        return {**it, "tag": "ask-IT", "note": "AllowWSL is 0 in the WSL policy"}
    installed, distros = wsl_state(ctx)
    if installed and any(d["name"].lower() == DISTRO.lower() for d in distros):
        return {**it, "tag": "works"}
    if installed:
        return {**it, "tag": "no-admin", "scope": "user", "note": f"WSL is on; {DISTRO} is added"}
    if not ctx.admin:
        return {**it, "tag": "ask-IT", "note": "needs an administrator once (no admin rights found)"}
    return {**it, "tag": "one-admin-prompt",
            "note": "one UAC prompt, then a reboot" + (" (--web-download: the Store is blocked)" if ctx.store_blocked else "")}


def wsl_state(ctx):
    rc, _ = ctx.run(["wsl", "--status"], timeout=60)
    rc2, out = ctx.run(["wsl", "-l", "-v"], timeout=60) if rc == 0 else (None, b"")
    return rc == 0, parse_wsl_list(out) if rc2 == 0 else []


def nightly_wanted(ctx):
    return "nightly" in ctx.with_ if ctx.profile == "corporate" else not ctx.no_nightly


def plan_md(plan):
    rows = "\n".join(f"| {it['item']} | {it['tag']} | {it.get('source', '')} | {it.get('scope', '')} | "
                     f"{(it.get('version') or '')} | {it.get('note', '')} |" for it in plan["items"])
    notes = "".join(f"- {n}\n" for n in plan.get("notes") or [])
    return (f"# Setup plan ({plan['generated']})\n\nAdmin-capable: {plan['admin_capable']}. Tags: works = nothing to do; "
            "found = on disk but its version call fails (reinstalled at the same scope); no-admin; one-admin-prompt "
            "(a UAC prompt you click); ask-IT (draft text in setup-state.json); opt-in-off.\n\n"
            "| item | tag | source | scope | version | note |\n|---|---|---|---|---|---|\n" + rows + "\n\n" + notes)


# ── install ──────────────────────────────────────────────────────────────────────────────────────────────────
def denial(ctx, it, rc, how):
    p = next((x for x in packages() if x["id"] == it["item"]), None)
    text = it.get("ask_it") or (p or {}).get("ask_it") or f"Please allow {it.get('name', it['item'])} on my managed laptop."
    if rc in DECLINED:
        ctx.fail(it["item"], f"{how} exit {hx(rc)}: the prompt was declined; nothing else was tried. Run setup again "
                             "and approve it, or ask IT.")
    else:   # a policy or access denial: hard stop, recorded as an ask-IT item; no other route or shell is tried
        ctx.ask(it["item"], text)
        ctx.log(f"STOP [{it['item']}]: {how} exit {hx(rc)} is a denial; not retried another way")
    it["result"] = "denied"


def record_pkg(ctx, p, it, ver, **extra):
    """The ledger entry that makes a tool this kit's own. Only recorded tools are ever updated (U1); a tool with no
    entry was put there by IT or by hand and is only reported."""
    ctx.record({"kind": "package", "id": p["id"], "source": p["source"], "scope": it.get("scope") or p["scope"],
                "version": ver, **extra}, f"pkg:{p['id']}")


def after_install(ctx, it, how, **extra):
    p = pkg("fnm") if it.get("via") == "fnm" else pkg(it["item"])
    status, ver = ctx.verify(p)
    if status == "works":
        ctx.clear(it["item"])
        it.update(result="installed", version=ver)
        record_pkg(ctx, p, it, ver, **extra)
    else:
        it["result"] = "failed"
        ctx.fail(it["item"], f"verify mismatch after {how}: `{' '.join(p['verify'])}` printed no version (the installer "
                             "reported success)")


def winget_install(ctx, it, scope):
    rc, _ = ctx.run(["winget", "install", "--id", it["winget"], "-e", "--source", "winget", "--scope", scope,
                     "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"])
    if rc in DENIED:
        return denial(ctx, it, rc, "winget install")
    if rc in REBOOT:
        ctx.save(reboot_pending=True)
    if rc == 0 or rc in ALREADY or rc in REBOOT:
        return after_install(ctx, it, f"winget install ({hx(rc)})")
    it["result"] = "failed"
    ctx.fail(it["item"], f"winget install exit {hx(rc)}")


def do_install(ctx, plan):
    items = plan["items"]
    user = user_winget(items)
    if user:
        mode = "fallback" if plan["configure_off"] else "configure"
        if mode == "configure" and plan["store_blocked"]:
            rc, _ = ctx.run(["winget", "list", "-e", "--id", "Microsoft.DSC", "--accept-source-agreements",
                             "--disable-interactivity"])
            if rc != 0:
                rc, _ = ctx.run(["winget", "install", "--id", "Microsoft.DSC", "-e", "--source", "winget", "--scope",
                                 "user", "--accept-package-agreements", "--accept-source-agreements",
                                 "--disable-interactivity"])
                if rc in DENIED:
                    for it in user:
                        denial(ctx, it, rc, "Microsoft.DSC install")
                    user, mode = [], "stopped"
                elif rc not in (0, *ALREADY):
                    mode = "fallback"
        if mode == "configure":
            f = ctx.state_dir / "workbench.winget"
            atomic_write(f, dsc_yaml(user))
            rc, _ = ctx.run(["winget", "configure", "-f", str(f), "--accept-configuration-agreements",
                             "--disable-interactivity"])
            if rc is None or rc in CONFIGURE_UNAVAILABLE:
                ctx.log(f"winget configure is unavailable ({hx(rc)}): installing package by package")
                mode = "fallback"
            elif rc in DENIED:
                for it in user:
                    denial(ctx, it, rc, "winget configure")
            else:
                for it in user:
                    after_install(ctx, it, f"winget configure ({hx(rc)})")
        if mode == "fallback":
            for it in user:
                winget_install(ctx, it, "user")
    for it in items:
        if it["tag"] in ("one-admin-prompt", "found") and it.get("winget") and it["scope"] == "machine":
            winget_install(ctx, it, "machine")   # the installer elevates itself: one UAC prompt the human clicks
        if it.get("via") == "fnm" and it.get("result") == "installed":
            fnm_node(ctx, it)
        p = next((x for x in packages() if x["id"] == it["item"]), None)
        if p and p["source"] == "github-release" and it["tag"] in ("no-admin", "found"):
            fetch_release(ctx, it)
        if p and p["source"] == "npm" and it["tag"] in ("no-admin", "found"):
            npm_install(ctx, it, p)
        if it["item"] == "tls-fixes":
            tls_fixes(ctx)
        if it["item"] == "claude-autoupdate" and it["tag"] == "no-admin":
            env_set(ctx, "CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE", "1")
        if it["item"] in ("pm-pack", "upstream-skills") and it["tag"] == "no-admin":
            fetch_upstream(ctx, it)
    jwrite(ctx.state_dir / "plan.json", plan)


def fnm_node(ctx, it):
    """Node.js LTS without admin: fnm + node/npm/npx shims in <WB>/bin, which is appended to the user Path."""
    fnm = ctx.which("fnm")
    for args in (["install", "--lts"], ["default", "lts-latest"]):     # fnm alias name lts-latest: ASSUMED
        rc, _ = ctx.run([fnm, *args]) if fnm else (None, b"")
        if rc != 0:
            it["result"] = "failed"
            return ctx.fail("node", f"fnm {' '.join(args)} exit {hx(rc)}")
    b = ctx.wb / "bin"
    b.mkdir(parents=True, exist_ok=True)
    for n in ("node", "npm", "npx"):
        f = b / f"{n}.cmd"
        f.write_text(f'@"{Path(fnm)}" exec --using=default {n} %*\r\n', encoding="utf-8", newline="")
        ctx.record({"kind": "file", "path": fwd(f), "sha256": sha(f)}, f"file:{fwd(f)}")
    path_append(ctx, str(b))
    status, ver = ctx.verify(pkg("node"))
    if status == "works":
        it.update(result="installed", version=ver)
    else:
        it["result"] = "failed"
        ctx.fail("node", "the node shim did not print a version")


def path_append(ctx, entry):
    """Append to HKCU Path through the registry API, keeping REG_EXPAND_SZ (never setx: it truncates at 1024)."""
    cur = I.reg_get(ENV_KEY, "Path") or ("", 2)
    data = str(cur[0] or "")
    norm = lambda x: os.path.normcase(os.path.normpath(os.path.expandvars(x.strip()))) if x.strip() else ""  # noqa: E731
    if norm(entry) in {norm(x) for x in data.split(";")}:        # same folder, whatever the case, slashes or %VAR% form
        return
    reg_set(ENV_KEY, "Path", (data.rstrip(";") + ";" + entry) if data else entry, cur[1] or 2)
    ctx.record({"kind": "path-append", "entry": entry}, f"path:{entry.lower()}")
    broadcast_env()


def env_set(ctx, name, value):
    old = I.reg_get(ENV_KEY, name)
    if old and str(old[0]) == value:
        return
    reg_set(ENV_KEY, name, value, 1)
    ctx.record({"kind": "env", "name": name, "value": value, "old": old[0] if old else None}, f"env:{name}")
    broadcast_env()


def tls_fixes(ctx):
    """Only when the probe saw TLS inspection: the system store for Node and uv (user env, never PATH), schannel for Git."""
    env_set(ctx, "NODE_USE_SYSTEM_CA", "1")
    env_set(ctx, "UV_SYSTEM_CERTS", "true")
    if ctx.which("git"):
        rc, out = ctx.run(["git", "config", "--global", "--get", "http.sslBackend"], timeout=60)
        old = decode(out).strip() if rc == 0 else None
        if old != "schannel":
            rc, _ = ctx.run(["git", "config", "--global", "http.sslBackend", "schannel"], timeout=60)
            if rc == 0:
                ctx.record({"kind": "gitconfig", "name": "http.sslBackend", "value": "schannel", "old": old},
                           "git:http.sslBackend")


# Schannel's "could not check revocation" (no reachable revocation point, or it is offline): what a TLS-inspecting proxy's
# re-signed certificates give. Matched on the error codes curl prints with --show-error, never on English text.
REVOCATION_UNCHECKED = re.compile(rb"CRYPT_E_NO_REVOCATION_CHECK|CRYPT_E_REVOCATION_OFFLINE|0x8009201[23]", re.I)


def curl(ctx, args, timeout):
    """ctx.run(curl args) with ONE logged retry for that Windows case only (exit 35 + one of those codes), adding
    --ssl-revoke-best-effort: it ignores just those two errors and keeps the revocation check, so a revoked certificate
    still fails. Never --ssl-no-revoke or -k. The retry is recorded for the doctor's TLS row."""
    rc, out = ctx.run(["curl", *args], timeout=timeout)
    if WIN and rc == 35 and REVOCATION_UNCHECKED.search(out or b""):
        ctx.log("curl exit 35: Schannel could not check the certificate's revocation (CRYPT_E_NO_REVOCATION_CHECK or "
                "CRYPT_E_REVOCATION_OFFLINE); retrying once with --ssl-revoke-best-effort")
        ctx.save(tls_revocation={"at": now(), "url": args[-1]})
        rc, out = ctx.run(["curl", "--ssl-revoke-best-effort", *args], timeout=timeout)
    return rc, out


def fetch_release(ctx, it):
    """A pinned vendor release zip: download, SHA-256 check, extract the one executable, switch telemetry off."""
    p = pkg(it["item"])
    dl = ctx.state_dir / "downloads"
    dl.mkdir(parents=True, exist_ok=True)
    z = dl / p["url"].rsplit("/", 1)[-1]
    rc, out = curl(ctx, ["--fail", "--location", "--silent", "--show-error", "--proto", "=https", "-o", str(z),
                         "-w", "%{http_code}", p["url"]], timeout=900)
    if rc != 0:
        code = (re.findall(r"\d{3}", decode(out)) or [""])[-1]
        if code in ("403", "407"):
            return denial(ctx, it, 5, f"download (HTTP {code} from the proxy)")
        it["result"] = "failed"
        return ctx.fail(it["item"], f"download exit {hx(rc)}")
    if sha(z) != p["sha256"]:
        z.unlink(missing_ok=True)
        it["result"] = "failed"
        return ctx.fail(it["item"], "SHA-256 mismatch: the download was deleted and not used")
    exe = f"{it['item']}.exe" if WIN else it["item"]
    b = ctx.wb / "bin"
    b.mkdir(parents=True, exist_ok=True)
    try:
        if z.suffix.lower() == ".zip":
            with zipfile.ZipFile(z) as zf:
                member = next((m for m in zf.namelist() if m.rsplit("/", 1)[-1].lower() == exe.lower()), None)
                if not member:
                    it["result"] = "failed"
                    return ctx.fail(it["item"], f"{exe} is not in the release zip")
                (b / exe).write_bytes(zf.read(member))   # written by base name only: no path from the archive is used
        else:                                            # the release asset is the executable itself (ctx)
            shutil.move(str(z), str(b / exe))
    except PermissionError:                              # Windows locks a running program's file
        it["result"] = "locked"
        return ctx.log(f"{exe} is in use: close it, then run setup.py update")
    ctx.record({"kind": "file", "path": fwd(b / exe), "sha256": sha(b / exe)}, f"file:{fwd(b / exe)}")
    if it["item"] == "tokensave":
        rc, _ = ctx.run([str(b / exe), "disable-upload-counter"], timeout=120)
        if rc != 0:
            (b / exe).unlink(missing_ok=True)
            it["result"] = "failed"
            return ctx.fail(it["item"], "disable-upload-counter failed, so the binary was removed unused")
    if it["item"] == "ctx":
        for k, v in CTX_ENV.items():                     # off before the first ctx run: this process, then every new shell
            ctx.extra_env[k] = v
            env_set(ctx, k, v)
        rc, _ = ctx.run([str(b / exe), "index", "mode", "manual"], alias="ctx", timeout=120)
        if rc != 0:
            (b / exe).unlink(missing_ok=True)
            it["result"] = "failed"
            return ctx.fail(it["item"], "`ctx index mode manual` failed, so the binary was removed unused")
    after_install(ctx, it, "the release download")


def writable_dir(path):
    """True when files can be created in path (or, for a folder npm will create, in its nearest existing parent)."""
    d = Path(path)
    while not d.exists() and d != d.parent:
        d = d.parent
    try:
        with tempfile.TemporaryFile(dir=d):
            return True
    except OSError:
        return False


def npm_prefix(ctx):
    """The global prefix npm installs into: the user's own when they can write there (on Windows, %AppData%\\npm by
    default), else <WB>/npm. (prefix, flag): flag is the prefix to pass as --prefix, or None."""
    rc, out = ctx.run(["npm", "config", "get", "prefix"], timeout=60)
    lines = [x.strip() for x in decode(out).splitlines() if x.strip()] if rc == 0 else []
    if lines and writable_dir(lines[-1]):
        return lines[-1], None
    own = str(ctx.wb / "npm")
    return own, own


def npm_install(ctx, it, p):
    """A global npm package at its pinned version, scripts off, then its config and skills. Needs Node (the plan checked)."""
    prefix, flag = npm_prefix(ctx)
    rc, out = ctx.run(npm_cmd(p, p["pin"], flag), env=NPM_ENV, timeout=1800)
    if rc != 0:
        if re.search(r"\bE40[37]\b", decode(out)):      # npm's own error code for a proxy or registry refusal
            return denial(ctx, it, 5, f"npm install (HTTP refusal from {p['hosts'][0]})")
        it["result"] = "failed"
        return ctx.fail(it["item"], f"npm install -g {p['npm']}@{p['pin']} exit {hx(rc)}")
    if flag:
        Path(flag).mkdir(parents=True, exist_ok=True)
        ctx.record({"kind": "dir", "path": fwd(flag)}, f"dir:{fwd(flag)}")
    if not ctx.which(p["verify"][0]):                    # a prefix that is not on the user Path yet
        path_append(ctx, prefix)
    after_install(ctx, it, "npm install", npm=p["npm"], **({"prefix": flag} if flag else {}))
    if it.get("result") == "installed":
        playwright_setup(ctx, p, it["version"])


def playwright_setup(ctx, p, ver):
    """Default browser = the installed Edge, headless unless Edge's own policy forbids it, through a config file the CLI
    reads from PLAYWRIGHT_MCP_CONFIG; then the CLI's skill, only from the pinned version."""
    cap = ctx.pdata("capture")
    if cap.get("edge_path"):
        cfg = ctx.state_dir / "playwright-cli.config.json"
        text = json.dumps({"browser": {"browserName": "chromium", "launchOptions": {
            "channel": "msedge", "headless": cap.get("headless_allowed") is not False}}}, indent=2) + "\n"
        if not cfg.exists() or cfg.read_text(encoding="utf-8") != text:
            atomic_write(cfg, text)
            ctx.record({"kind": "file", "path": fwd(cfg), "sha256": sha(cfg)}, f"file:{fwd(cfg)}")
        old = I.reg_get(ENV_KEY, CLI_CONFIG_ENV)
        if old and str(old[0]) != str(cfg):
            ctx.notes.append(f"playwright-cli: {CLI_CONFIG_ENV} already points at {old[0]}; kept. Browser settings for "
                             f"this kit are in {fwd(cfg)}")
        else:
            env_set(ctx, CLI_CONFIG_ENV, str(cfg))
        if cap.get("headless_allowed") is False:
            ctx.notes.append("playwright-cli: Edge's HeadlessModeEnabled policy is off, so the CLI opens a visible window")
    else:
        ctx.notes.append("playwright-cli: no Microsoft Edge was found; install Edge, or ask IT which browser is approved")
    if ver != p["pin"]:
        ctx.notes.append(f"playwright-cli {ver} is not the tested {p['pin']}: its skill was not installed")
        return
    rc, _ = ctx.run(["playwright-cli", "install", "--skills", "--global"], env=NPM_ENV, cwd=str(ctx.state_dir), timeout=300)
    if rc == 0:
        dest = ctx.home / ".claude" / "skills" / "playwright-cli"
        ctx.record({"kind": "skills", "what": "playwright-cli", "path": fwd(dest)}, "skills:playwright-cli")
        if ctx.ch.resolve() != (ctx.home / ".claude").resolve():
            ctx.notes.append(f"playwright-cli: its skill went to {fwd(dest)}; copy it to {fwd(ctx.ch / 'skills')} for this profile")
    else:
        ctx.notes.append(f"playwright-cli install --skills exit {hx(rc)}: the CLI works without it (playwright-cli --help)")


def fetch_upstream(ctx, it):
    done = {e.get("what") for e in ctx.ledger()["entries"] if e.get("kind") == "fetched"}
    if it["item"] in done:
        return
    args = ["--apply"] + (["--pm"] if it["item"] == "pm-pack" else [])
    rc, _ = ctx.py_tool(KIT / "tools" / "fetch-upstream" / "fetch_upstream.py", *args)
    if rc == 0:
        ctx.record({"kind": "fetched", "what": it["item"]}, f"fetched:{it['item']}")
    else:
        ctx.fail(it["item"], f"fetch_upstream {' '.join(args)} exit {hx(rc)}")


# ── WSL ──────────────────────────────────────────────────────────────────────────────────────────────────────
def do_wsl(ctx, plan):
    """'done' or 'reboot'. Install WSL without a distribution (one UAC prompt), then the pinned distribution."""
    it = next(i for i in plan["items"] if i["item"] == "wsl")
    if it["tag"] not in ("no-admin", "one-admin-prompt", "found"):
        return "done"
    web = ["--web-download"] if plan["store_blocked"] else []
    if it["tag"] == "one-admin-prompt":
        rc, _ = ctx.run(["wsl", "--install", "--no-distribution", *web])
        if rc in DENIED:
            denial(ctx, it, rc, "wsl --install")
            return "done"
        if rc not in (0, *REBOOT):
            ctx.fail("wsl", f"wsl --install --no-distribution exit {hx(rc)}")
            return "done"
        if rc in REBOOT or not wsl_state(ctx)[0]:
            schedule_resume(ctx)
            return "reboot"
    install_distro(ctx, it, web)
    return "done"


def schedule_resume(ctx):
    cmd = runonce_command(pythonw(), HERE / "setup.py")
    by_hand = show([PY, fwd(HERE / "setup.py"), "resume"])
    if cmd:
        reg_set(RUNONCE_KEY, RUNONCE_NAME, cmd, 1)
        ctx.record({"kind": "runonce", "name": RUNONCE_NAME}, "runonce")
    else:
        ctx.fail("wsl-resume", f"the resume command is longer than {RUNONCE_MAX} characters even with short paths; "
                               f"after the reboot run: {by_hand}")
    ctx.save(phase="reboot-wait", reboot_pending=True, exit_code=5,
             next="Restart Windows. Setup resumes by itself after you sign in (or run: " + by_hand + ")")
    ctx.log("waiting for a reboot: " + ctx.st["next"])


def install_distro(ctx, it, web):
    rc, _ = ctx.run(["wsl", "--install", "-d", DISTRO, "--no-launch", *web])
    if rc in DENIED:
        return denial(ctx, it, rc, f"wsl --install -d {DISTRO}")
    if rc != 0:
        it["result"] = "failed"
        return ctx.fail("wsl", f"wsl --install -d {DISTRO} exit {hx(rc)}")
    it["result"] = "installed"
    ctx.clear("wsl")
    ctx.notes.append(f"WSL: open a terminal and run `wsl -d {DISTRO}` once to create your Linux user (a human step)")
    wslconfig(ctx)


def wslconfig(ctx):
    """A .wslconfig for a 16 GB laptop, only when the user has none; mirrored networking only when policy allows it."""
    f = ctx.home / ".wslconfig"
    if f.exists():
        return
    lines = ["[wsl2]", "memory=6GB", "swap=4GB", "processors=4"]
    if not blocked(WSL_POLICY + r"\AllowNetworkingModeUserSetting"):
        lines.append("networkingMode=mirrored")
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ctx.record({"kind": "file", "path": fwd(f), "sha256": sha(f)}, f"file:{fwd(f)}")


def wait_network(ctx, budget_s=600):
    """True once any HTTP answer comes back (curl exit 0, even a proxy's 407); False after the budget."""
    end = time.time() + budget_s
    while True:
        rc, _ = curl(ctx, ["--head", "--silent", "--show-error", "--max-time", "10", "-o", os.devnull, NET_URL], timeout=30)
        if rc == 0:
            return True
        if time.time() + NET_POLL_S > end:
            return False
        time.sleep(NET_POLL_S)


# ── after installs: verify, onboard, knowledge, capture runtime, routing, report ─────────────────────────────
def do_verify(ctx, plan):
    for it in plan["items"]:
        p = next((x for x in packages() if x["id"] == it["item"]), None)
        if p and it["tag"] not in ("opt-in-off", "ask-IT") and it.get("result") != "denied":
            status, ver = ctx.verify(p)
            it["verified"], it["version"] = status == "works", ver or it.get("version")
            if status == "works":
                ctx.clear(it["item"])
            elif it.get("result") != "failed":
                ctx.fail(it["item"], f"`{' '.join(p['verify'])}` does not print a version")
    jwrite(ctx.state_dir / "plan.json", plan)


# ── update (U1): the tools THIS kit installed move to the tested pins; everything else is only reported ──────
def vkey(v):
    """A version as its numbers, so 2.55.0.windows.3 > 2.55.0 and 2.9.0 < 2.55.0; () when there is none."""
    return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))[:4])


def ledger_pkgs(ctx):
    return {e["id"]: e for e in ctx.ledger()["entries"] if e.get("kind") == "package"}


def winget_cmd(p, scope, target):
    """winget upgrade for one package. target None = the newest version (only with --with update-latest)."""
    return (["winget", "upgrade", "--id", p["winget"], "-e", "--source", "winget"] + (["--version", target] if target else [])
            + ["--scope", scope, "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"])


def npm_cmd(p, target, prefix=None):
    return (["npm", "install", "-g", f"{p['npm']}@{target or 'latest'}", "--ignore-scripts", "--no-audit", "--no-fund"]
            + (["--prefix", prefix] if prefix else []))


def update_row(ctx, p, led, check):
    """One IP3 row for package p; None when p is not installed at all. Order of decisions: not ours -> reported only;
    policy -> skipped; already at the pin -> current; in use or machine-wide -> deferred with its command; --check ->
    deferred; else run it and judge it by the after-probe version alone."""
    status, before = ctx.verify(p)
    if status == "absent":
        return None
    latest = "update-latest" in ctx.with_ and p["source"] in ("winget", "npm")
    target = None if latest else p.get("pin")
    row = {"id": p["id"], "before": before, "target": target or "latest", "after": None, "action": "current",
           "command": None, "note": ""}
    e = led.get(p["id"])
    if not e:
        return {**row, "action": "it-managed", "note": "not installed by this kit (IT or by hand): reported only, never changed"}
    scope = e.get("scope") or p["scope"]
    # update_argv: the tool's own updater, for a package whose winget catalogue lags its releases (Claude Code)
    argv = (list(p["update_argv"]) if p.get("update_argv") else winget_cmd(p, scope, target) if p["source"] == "winget"
            else npm_cmd(p, target, e.get("prefix")) if p["source"] == "npm"
            else [PY, fwd(HERE / "setup.py"), "update"])
    row["command"] = show([str(a) for a in argv])
    if p["source"] == "winget" and any(blocked(k) for k in p["policy_keys"]):
        return {**row, "action": "skipped-policy", "note": "an App Installer policy value blocks winget; ask IT"}
    if not latest and not target:
        return {**row, "note": "no tested pin for this tool"}
    if not latest and before and vkey(before) >= vkey(target):
        return {**row, "note": "newer than the tested pin: left alone" if vkey(before) > vkey(target) else ""}
    if p.get("in_use"):
        return {**row, "action": "deferred", "note": f"{p['name']} is in use: close everything that runs it, then run the command"}
    if scope == "machine":
        return {**row, "action": "deferred", "note": "machine-wide install: setup never elevates; ask IT, or run the command "
                                                     "yourself in an administrator shell"}
    if check:
        return {**row, "action": "deferred", "note": "check only, nothing was changed: run setup.py update to apply"}
    return run_update(ctx, p, e, row, argv, target, before)


def run_update(ctx, p, e, row, argv, target, before):
    it = {"item": p["id"], "name": p["name"], "ask_it": p["ask_it"]}

    def fail(note):
        ctx.fail(f"update:{p['id']}", note)
        return {**row, "action": "failed", "note": note}
    rc = 0
    if p["source"] == "winget":
        rc, _ = ctx.run(argv, timeout=3600)
        if rc in DENIED:
            denial(ctx, it, rc, "winget upgrade")
            return {**row, "action": "denied", "note": f"exit {hx(rc)}: a denial, not retried; the ask-IT text is in the setup state"}
        if rc in IN_USE:
            return {**row, "action": "deferred", "note": f"exit {hx(rc)}: the program is running; close it, then run the command"}
        if rc in REBOOT:
            ctx.save(reboot_pending=True)
        if rc is None or not (rc == 0 or rc in ALREADY | REBOOT | {UPDATE_NOT_APPLICABLE, DOWNGRADE}):
            return fail(f"winget upgrade exit {hx(rc)}")
    elif p["source"] == "npm":
        rc, out = ctx.run(argv, env=NPM_ENV, timeout=1800)
        if rc != 0:
            if re.search(r"\bE40[37]\b", decode(out)):
                denial(ctx, it, 5, f"npm install (HTTP refusal from {p['hosts'][0]})")
                return {**row, "action": "denied", "note": "the registry refused it: not retried; the ask-IT text is in the setup state"}
            return fail(f"npm install exit {hx(rc)}")
    else:                                              # a pinned, checksummed release: the same code as the first install
        fetch_release(ctx, it)
        if it.get("result") == "denied":
            return {**row, "action": "denied", "note": "the download was refused: not retried"}
        if it.get("result") == "locked":
            return {**row, "action": "deferred", "note": "the program is running: close it, then run the command"}
        if it.get("result") == "failed":
            return {**row, "action": "failed", "note": "see the failed list in the setup state"}
    status, after = ctx.verify(p)
    row["after"] = after
    if target is None and status == "works" and vkey(after) == vkey(before):
        return {**row, "note": "already the newest version"}
    if status == "works" and (vkey(after) > vkey(before) if target is None else vkey(after) >= vkey(target)):
        ctx.record({**e, "version": after}, f"pkg:{p['id']}")
        return {**row, "action": "upgraded"}
    return fail(f"exit {hx(rc)} but `{' '.join(p['verify'])}` reports {after or 'no version'}, not {target or 'a newer one'}")


def req_pins(req):
    """{normalised name: version} for the exact pins (name==version, extras allowed) in a requirements file."""
    out = {}
    for ln in Path(req).read_text(encoding="utf-8").splitlines():
        m = re.match(r"([A-Za-z0-9_.-]+)(?:\[.*?\])?==([^\s;#]+)", ln.strip())
        if m:
            out[re.sub(r"[-_.]+", "-", m.group(1)).lower()] = m.group(2)
    return out


def pip_list(ctx, kpy, *args):
    rc, out = ctx.run([str(kpy), "-m", "pip", "list", *args, "--format=json", "--disable-pip-version-check"],
                      alias="pip", timeout=600)
    try:
        v = json.loads(decode(out)) if rc == 0 else None
    except ValueError:
        v = None
    return [x for x in v if isinstance(x, dict) and "name" in x] if isinstance(v, list) else None


def update_venv(ctx, check):
    """The knowledge venv back on its requirements pins; newer releases of those packages are report-only rows."""
    kpy = ctx.venv_python()
    req = KIT / "plugins" / "workbench-core" / "skills" / "find" / "requirements.txt"
    if not kpy.exists() or not req.is_file():
        return []
    norm = lambda n: re.sub(r"[-_.]+", "-", n).lower()  # noqa: E731
    pins = req_pins(req)
    have = {norm(x["name"]): x["version"] for x in pip_list(ctx, kpy) or []}
    drift = {n: v for n, v in pins.items() if have and have.get(n) != v}
    cmd = show([str(kpy), "-m", "pip", "install", "-r", fwd(req)])
    before, rows, rc = dict(have), [], 0
    if drift and not check:
        rc, _ = ctx.run([str(kpy), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(req)], alias="pip", timeout=3600)
        have = {norm(x["name"]): x["version"] for x in pip_list(ctx, kpy) or []} if rc == 0 else have
    for n, v in sorted(drift.items()):
        done = not check and have.get(n) == v
        rows.append({"id": f"pip:{n}", "before": before.get(n), "target": v, "after": None if check else have.get(n),
                     "action": "deferred" if check else "upgraded" if done else "failed", "command": cmd,
                     "note": "check only: the venv differs from its pins" if check else "" if done else
                     f"pip install -r exit {hx(rc)}; still not at the pin"})
    bad = [r["id"] for r in rows if r["action"] == "failed"]
    if bad:
        ctx.fail("update:venv", f"not at the requirements pin after pip install -r: {', '.join(bad)}")
    newer = {norm(x["name"]): x["latest_version"] for x in pip_list(ctx, kpy, "--outdated") or [] if "latest_version" in x}
    for n in sorted(set(pins) & set(newer)):
        if n not in drift:
            rows.append({"id": f"pip:{n}", "before": have.get(n), "target": pins[n], "after": None, "action": "current",
                         "command": None, "note": f"{newer[n]} exists; not installed (this kit moves only to tested pins)"})
    return rows


def update_md(doc):
    rows = "\n".join(f"| {r['id']} | {r['before'] or ''} | {r['target']} | {r['after'] or ''} | {r['action']} | "
                     f"{('`' + r['command'] + '`') if r['command'] else ''} | {r['note']} |" for r in doc["items"])
    return (f"# Update ({doc['generated']})\n\nOnly tools this kit installed are changed, and only to the tested pin in "
            "packages.json (`--with update-latest`: the newest). A tool IT or you installed is listed as it-managed and left "
            "alone. deferred = not done now; the command column is what to run.\n\n"
            "| item | before | target | after | action | command | note |\n|---|---|---|---|---|---|---|\n" + rows + "\n")


def do_update(ctx, check=False):
    """Write <state>/update.json (IP3) and update.md; returns the document. Windows only: the rows are winget, npm and
    release downloads."""
    rows = []
    ctx.st["failed"] = [x for x in ctx.st["failed"] if not x["item"].startswith("update:")]    # this run's verdict replaces the last
    if WIN:
        led = ledger_pkgs(ctx)
        rows = [r for r in (update_row(ctx, p, led, check) for p in packages()) if r]
        rows += update_venv(ctx, check)
    doc = {"version": 1, "generated": now(), "items": rows}
    jwrite(ctx.state_dir / "update.json", doc)
    atomic_write(ctx.state_dir / "update.md", update_md(doc))
    return doc


def cmd_update(ctx, check=False, as_json=False):
    if lock_holder(ctx):
        print("setup is running; its update result is written to " + fwd(ctx.state_dir / "update.json"))
        return 2
    out = {}
    # a one-off `update --with update-latest` must not become the options a later plain `run` reuses
    ctx.st["options"] = (jload(ctx.state_dir / "setup-state.json", {}) or {}).get("options") or \
        {"with": [], "no_nightly": False, "no_update": False}

    def body():
        out["doc"] = do_update(ctx, check)
        return 0
    rc = body() if check else locked(ctx, body)
    doc = out.get("doc")
    if doc is None:
        return rc
    print(json.dumps(doc, indent=2, ensure_ascii=False) if as_json else update_md(doc))
    acts = {r["action"] for r in doc["items"]}
    return 4 if "failed" in acts else 3 if "denied" in acts else 0


def do_onboard(ctx):
    src = Path(ctx.cfg["dev_drive"]) / "src" if ctx.cfg.get("dev_drive") else ctx.home / "src"
    if not src.exists() and not I.in_onedrive(src):
        src.mkdir(parents=True, exist_ok=True)
    user, tpl = ctx.wb / "USER.md", KIT / "templates" / "USER.md"
    if user.exists() and tpl.exists() and user.read_bytes() == tpl.read_bytes():
        ctx.notes.append("onboarding: run /workbench-core:onboard to fill in USER.md")


def do_knowledge(ctx):
    find = ctx.find_cli()
    if not Path(find).is_file():
        return ctx.fail("knowledge", f"the find CLI is not in this kit ({fwd(find)})")
    kpy = ctx.venv_python()
    if not kpy.exists():
        argv, _ver = find_python(ctx)
        if not argv:
            return ctx.fail("knowledge", f"no Python {' or '.join(pkg('python313')['accept'])} was found: the knowledge "
                                         "venv needs one")
        rc, _ = ctx.run([*argv, "-m", "venv", str(ctx.wb / "venv")], alias="venv", timeout=600)
        if rc != 0:
            return ctx.fail("knowledge", f"creating the venv failed ({hx(rc)})")
    skills = KIT / "plugins" / "workbench-core" / "skills"
    for req, key in ((skills / "find" / "requirements.txt", "knowledge_requirements_sha256"),
                     (skills / "office-render" / "requirements.txt", "office_requirements_sha256"),
                     (skills / "pdf-report" / "requirements.txt", "pdf_requirements_sha256")):
        if req.exists() and ctx.cfg.get(key) != sha(req):       # the same venv: find, the office renderer, the pdf report
            rc, _ = ctx.run([str(kpy), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(req)],
                            alias="pip", timeout=3600)
            if rc != 0:
                return ctx.fail("knowledge", f"pip install -r {fwd(req.relative_to(KIT))} exit {hx(rc)}")
            set_config(ctx, **{key: sha(req)})
    set_config(ctx, knowledge_python=fwd(kpy), knowledge_db=ctx.cfg.get("knowledge_db") or
               fwd(ctx.lad / "doc-index" / "knowledge" / "index.sqlite"))
    rc, out = ctx.py_tool(find, "discover", "--json")
    libs = (jparse(out).get("libraries") or []) if rc == 0 else []
    # A discovered library (a work OneDrive, a SharePoint sync, Documents) is a suggestion, never a root setup registers:
    # it can contain the KB and captured roots (one run indexed 24 notes twice), and guide 28 says to index a scoped folder.
    ctx.suggestions = [{"path": fwd(lib["path"]), "kind": lib.get("kind"), "label": lib.get("label"), "root": None}
                       for lib in libs if isinstance(lib, dict) and lib.get("path")]
    (ctx.data / "captured").mkdir(parents=True, exist_ok=True)
    roots = [(str(ctx.data / "captured"), "captured")]
    if (KIT / "docs" / "howto").is_dir():
        roots.append((str(KIT / "docs" / "howto"), "howto"))
    if ctx.kb.is_dir():
        roots.append((str(ctx.kb), "kb"))           # meaning search over the KB: the fallback after kb_search
    for path, label in roots:
        rc, _ = ctx.py_tool(find, "add-root", path, *(["--label", label] if label else []), "--json")
        if rc != 0:
            ctx.fail("knowledge", f"add-root {label or path} exit {hx(rc)}")
    # Which discovered libraries are ALREADY search roots (a 0.3.1 setup registered them, and the nightly refresh keeps indexing
    # them)? Read the index's root list; never remove one here, that is the person's data choice.
    rc, out = ctx.py_tool(find, "roots", "--json")
    reg = json_in(out).get("roots") if rc == 0 else None
    if isinstance(reg, list):
        key = lambda p: fwd(p).lower().rstrip("/")  # noqa: E731
        have = {key(r["path"]): r.get("label") for r in reg if isinstance(r, dict) and r.get("path")}
        for sug in ctx.suggestions:
            sug["root"] = have.get(key(sug["path"]))
        ctx.roots_read = True


RELAY_KEY = "settings:stopfailure-relay"
EXEC_FORM_MIN_CC = (2, 1, 139)   # official CHANGELOG 2.1.139: hook `args` (exec form), which the relay entries use
KIT_LEDGER = "kit-written.json"  # I7: <WB>/state/kit-written.json; setup reads and writes only its `relay_hooks` key


def relay_mark(ctx):
    """The ledger's relay_hooks: "written", "removed-by-user" or None (missing or unreadable ledger, or any other value)."""
    d = jload(ctx.state_dir / KIT_LEDGER)
    v = d.get("relay_hooks") if isinstance(d, dict) else None
    return v if v in ("written", "removed-by-user") else None


def relay_mark_set(ctx, value):
    """Set only relay_hooks; every other ledger key is kept as read. A missing or unreadable ledger is started with the I7 shape."""
    p = ctx.state_dir / KIT_LEDGER
    d = jload(p)
    if not isinstance(d, dict):
        if value is None:
            return
        keys = ("permissions.ask", "permissions.deny", "permissions.allow", "permissions.additionalDirectories")
        d = {"version": 1, "lists": {k: [] for k in keys}, "user_removed": {k: [] for k in keys}, "plugins": {}, "updated": now()}
    if d.get("relay_hooks") != value:
        d["relay_hooks"] = value
        jwrite(p, d)


def relay_pair_present(user):
    """Both relay hooks (a bug_hint.py command under StopFailure and under UserPromptSubmit) are in this settings object."""
    try:
        hooks = user.get("hooks") if isinstance(user.get("hooks"), dict) else {}
        return all(any("bug_hint.py" in json.dumps(h.get("args") or h.get("command") or "")
                       for g in hooks.get(ev) or [] if isinstance(g, dict) for h in g.get("hooks") or [] if isinstance(h, dict))
                   for ev in ("StopFailure", "UserPromptSubmit"))
    except Exception:
        return True      # an odd shape is no proof the user removed anything


def relay_hooks(ctx):
    """IR3: two user-settings hooks for the StopFailure relay (StopFailure -> bug_hint.py; UserPromptSubmit -> bug_hint.py
    --pending), only when this kit's bug_hint.py carries STOPFAILURE_MIN_CC and Claude Code is at or above it. Never in
    the plugin's static hooks.json. Merged with install.py's settings merge; the ops are ledger-recorded for undo-config.
    An earlier run's entries are undone first, so a moved kit or a new python never leaves a stale pair behind.
    I7 ledger: a pair the ledger says setup wrote but settings.json no longer holds was removed by the user: it is
    never added again."""
    script = KIT / "plugins" / "workbench-core" / "scripts" / "bug_hint.py"
    sp = ctx.ch / "settings.json"
    try:
        user = I.read_json(sp) if sp.exists() else {}
    except (OSError, ValueError) as e:
        return ctx.notes.append(f"StopFailure relay: {fwd(sp)} is not valid JSON ({e}); nothing was changed")
    old = next((e for e in ctx.ledger()["entries"] if e.get("key") == RELAY_KEY), None)
    before = json.dumps(user, sort_keys=True)
    mark = relay_mark(ctx)
    gone = mark == "written" and not relay_pair_present(user)   # judged before setup's own undo below
    if gone:
        mark = "removed-by-user"
        relay_mark_set(ctx, mark)
    if old:
        I.undo_settings(user, old.get("ops") or [])
    floor = KV.stopfailure_floor(script)
    _, ver = ctx.verify(pkg("claude"))
    managed = {}
    for _src, d in I.managed_sources():
        I.deep_merge(managed, d)
    ops, notes, added = [], [], False
    if mark == "removed-by-user":      # the user's choice: one note when it is first seen, silence after
        if gone:
            ctx.notes.append("StopFailure relay: you removed these hooks from settings.json, so they are not added again "
                             f"(state/{KIT_LEDGER}, key relay_hooks)")
    elif floor is None:
        ctx.notes.append("StopFailure relay: this kit's bug_hint.py does not ship it; nothing installed")
    elif not ver or vkey(ver) < max(floor, EXEC_FORM_MIN_CC):
        ctx.notes.append(f"StopFailure relay: needs Claude Code {'.'.join(map(str, max(floor, EXEC_FORM_MIN_CC)))} or later, this machine has "
                         f"{ver or 'no claude on PATH'}; nothing installed (setup.py run adds it after an update)")
    elif managed.get("allowManagedHooksOnly") is True:
        ctx.notes.append("StopFailure relay: managed allowManagedHooksOnly is on, so user hooks never run; nothing installed")
    else:
        py = ctx.cfg.get("python") or PY
        frag = {"hooks": {ev: [{"hooks": [{"type": "command", "command": py, "args": ["-S", fwd(script), *extra],
                                           "timeout": 10}]}] for ev, extra in (("StopFailure", []),
                                                                               ("UserPromptSubmit", ["--pending"]))}}
        I.merge_settings(user, frag, managed, False, ops, notes)
        added = True
    if json.dumps(user, sort_keys=True) != before:
        atomic_write(sp, json.dumps(user, indent=2, ensure_ascii=False) + "\n")
    if ops:      # replaces the earlier entry
        ctx.record({"kind": "settings", "what": "StopFailure relay hooks", "path": fwd(sp), "ops": ops}, RELAY_KEY)
    elif old:
        led = ctx.ledger()
        led["entries"] = [e for e in led["entries"] if e.get("key") != RELAY_KEY]
        jwrite(ctx.state_dir / "provision-ledger.json", led)
    if added:
        relay_mark_set(ctx, "written")
    elif mark == "written":      # setup removed its own pair and could not add it back: nothing is written now
        relay_mark_set(ctx, None)


def do_knowledge_verify(ctx):
    """The Day-1 knowledge checks (knowledge_verify.py, setup mode). A named FAIL fails the run (exit 4); a WARN with an
    IT ask becomes an ask-IT item; the rest are notes. The full index refresh starts only after this phase."""
    doc = KV.run(ctx, "setup")
    for s in doc["steps"]:
        if s.get("ask_it"):
            ctx.ask(f"knowledge:{s['name']}", s["ask_it"])
        if s["status"] == "WARN":
            ctx.notes.append(f"knowledge verify {s['id']} {s['name']}: {s['detail']}")
    bad = doc["summary"]["failing"]
    if bad:
        ctx.fail("knowledge-verify", f"failing: {', '.join(bad)} (details: {fwd(ctx.state_dir / 'knowledge-verify.json')}; "
                                     "re-check with setup.py doctor --deep)")
    else:
        ctx.clear("knowledge-verify")
    return doc


def do_path(ctx):
    """<WB>/bin on the user Path, so the bare commands the guides use (ctx, tokensave, node, playwright-cli) resolve in a
    new terminal. Idempotent (path_append) and undone by undo-config; Windows only."""
    if not WIN:
        return
    b = ctx.wb / "bin"
    b.mkdir(parents=True, exist_ok=True)
    path_append(ctx, str(b))


def toml_set(text, table, key, literal):
    """text with `key = literal` set inside [table]: the key's line is replaced, a missing key goes right under the
    header, a missing table is appended. Every other line (comments, other tables) is kept as written."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    head = re.compile(r"^\s*\[\s*([^\[\]]+?)\s*\]\s*(#.*)?$")
    start = next((i for i, ln in enumerate(lines) if (m := head.match(ln.rstrip("\r\n"))) and m.group(1) == table), None)
    if start is None:
        return text + ("" if not text or text.endswith("\n") else nl) + (nl if text.strip() else "") + \
            f"[{table}]{nl}{key} = {literal}{nl}"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    for i in range(start + 1, end):
        if re.match(rf"^\s*{re.escape(key)}\s*=", lines[i]):
            lines[i] = f"{key} = {literal}{nl}"
            return "".join(lines)
    lines.insert(start + 1, f"{key} = {literal}{nl}")
    return "".join(lines)


def json_in(raw):
    """The first JSON object in a program's combined output (a warning line may come before or after it), else {}."""
    t = decode(raw)
    a, b = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[a:b + 1]) if 0 <= a < b else {}
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def ctx_config_path(ctx, exe):
    """The file ctx itself reads: `ctx status --format json` names it (config_path, checked on 2.2.8); else the documented
    default <CTX_DATA_ROOT or ~/.ctx>/config.toml. Only the JSON is read, never the exit code."""
    _, out = ctx.run([str(exe), "status", "--format", "json"], alias="ctx", timeout=120)
    p = json_in(out).get("config_path")
    return Path(p) if p else Path(os.environ.get("CTX_DATA_ROOT") or ctx.home / ".ctx") / "config.toml"


def do_ctx_config(ctx):
    """ctx 2.2.8 sends analytics by default and reads every agent's history folder it can find (34 absent ones failed the
    nightly import, Last Result 1). For the ctx THIS kit installed: write the opt-out and `automatic = false` into ctx's own
    config.toml (line edits, nothing else touched, validated with tomllib when the interpreter has it), then register the
    Claude Code folder as the one named root through ctx's own editor. A `claude` root the user defined differently stays."""
    if not ledger_pkgs(ctx).get("ctx"):
        return                                              # IT's or the user's own ctx: its config stays theirs
    exe = ctx.wb / "bin" / ("ctx.exe" if WIN else "ctx")
    if not exe.is_file():
        return
    ctx.extra_env.update(CTX_ENV)                           # off before any further ctx call, even in a shell that predates them
    try:
        import tomllib
    except ImportError:                                     # Python 3.10: the edit could not be checked, so it is not made
        return ctx.notes.append(
            "ctx: this Python (3.10) cannot validate TOML, so setup did not edit ctx's config.toml; its analytics and "
            "daemon opt-outs stay on through the user environment variables. To limit it to Claude Code by hand, add to ctx's "
            "config.toml: [analytics] enabled = false, and [sources] automatic = false, then run: ctx sources add claude "
            f"--provider claude --root {ctx.ch}. Or run setup with Python 3.11 or newer.")
    cfg = ctx_config_path(ctx, exe)
    try:
        old = cfg.read_text(encoding="utf-8-sig") if cfg.is_file() else ""
        tomllib.loads(old)
        new = old
        for table, key, lit in CTX_CONFIG:
            new = toml_set(new, table, key, lit)
        got = tomllib.loads(new)
        if any(got.get(t, {}).get(k) is not (lit == "true") for t, k, lit in CTX_CONFIG):
            raise ValueError("the edited file does not read back with the wanted values")
    except (OSError, ValueError) as e:                      # tomllib.TOMLDecodeError is a ValueError
        return ctx.fail("ctx-config", f"{fwd(cfg)} was left unchanged ({e}); fix or move that file, then run setup again")
    ctx.clear("ctx-config")
    if new != old:
        atomic_write(cfg, new)
    rc, _ = ctx.run([str(exe), "sources", "add", "claude", "--provider", "claude", "--root", str(ctx.ch)], alias="ctx",
                    timeout=120)
    if rc != 0:
        ctx.notes.append(f"ctx: a source named `claude` is already defined with other settings in {fwd(cfg)}; kept as it "
                         "is. With automatic discovery off, ctx reads only the roots listed there.")


def runs_this_exe(entry, exe):
    """The MCP entry starts this binary: the same path, or the bare name the kit's bin folder resolves."""
    cmd = str((entry or {}).get("command") or "") if isinstance(entry, dict) else ""
    if not cmd:
        return False
    if os.path.normcase(os.path.basename(cmd)) in ("tokensave", "tokensave.exe", "tokensave.cmd") and os.sep not in cmd and "/" not in cmd:
        return True
    return os.path.normcase(os.path.abspath(cmd)) == os.path.normcase(os.path.abspath(str(exe)))


def tokensave_projects(ctx):
    """How many repositories tokensave has indexed (its global registry, ~/.tokensave/global.db): 0 when there is no
    registry, None when it cannot be read. `serve` exits before the handshake only while this is 0."""
    db = ctx.home / ".tokensave" / "global.db"
    if not db.is_file():
        return 0
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=5)
        try:
            return con.execute("select count(*) from projects").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return None


def tokensave_down(ctx, live):
    """The healer's own probe says this one tokensave entry does not start. It probes a config holding only that entry
    (never the user's other servers), with a short timeout; anything unclear, a timeout included, reads as not down."""
    probe = ctx.state_dir / "tokensave-probe.json"
    jwrite(probe, {"mcpServers": {"tokensave": live}})
    try:
        rc, out = ctx.py_tool(KIT / "tools" / "mcp-healer" / "mcp_healer.py", "--config", probe, "check", "--json",
                              "--timeout", "30", timeout=90)
        rows = json.loads(decode(out))
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return False
    finally:
        probe.unlink(missing_ok=True)
    return rc in (0, 1) and isinstance(rows, list) and any(
        isinstance(r, dict) and r.get("server") == "tokensave" and r.get("status") == "DOWN" for r in rows)


def do_tokensave_mcp(ctx):
    """tokensave's `serve` exits while no repository is indexed, so a live entry shows DOWN and warns in every doctor run.
    Register it PARKED instead (mcpServersParked, which Claude Code ignores) through the healer; `unpark` turns it on after
    `tokensave init`. Only with --with tokensave, only when the user has no entry of that name, and a managed MCP policy wins."""
    if "tokensave" not in ctx.with_:
        return
    exe, cfgp = ctx.which("tokensave"), KV.user_mcp_config(ctx)
    if not exe:
        return
    if not cfgp.is_file():
        return ctx.notes.append(f"tokensave: {fwd(cfgp)} does not exist yet; start Claude Code once, then run setup.py run "
                                "again to register the code-graph server (parked)")
    cur = jload(cfgp, {}) or {}
    cur = cur if isinstance(cur, dict) else {}
    tpl = ((jload(KIT / "mcp" / "golden-config.template.json", {}) or {}).get("servers") or {}).get("tokensave")
    if not tpl:
        return
    spec = {**tpl, "action": "park", "command": fwd(exe),
            "reason": "Registered parked by setup: serve exits until a repository is indexed (tokensave init)."}
    g = ctx.state_dir / "tokensave-mcp.golden.json"
    jwrite(g, {"_readme": "Written by setup.py: the tokensave MCP server only, parked.", "servers": {"tokensave": spec}})
    servers = cur.get("mcpServers")
    live = servers.get("tokensave") if isinstance(servers, dict) else None
    unparked = any(x.get("key") == "mcp:tokensave" for x in ctx.ledger()["entries"])   # setup parked it before: the user turned it on
    mine = live is not None and runs_this_exe(live, exe)
    projects = tokensave_projects(ctx) if mine else None
    if mine and not unparked and projects == 0 and tokensave_down(ctx, live):
        # an entry for the kit's own binary that cannot start (no repository indexed yet): park it, unpark after `tokensave init`
        rc, _ = ctx.py_tool(KIT / "tools" / "mcp-healer" / "mcp_healer.py", "--config", cfgp, "apply", "--golden", g, timeout=120)
        if rc == 0:
            ctx.record({"kind": "mcp", "name": "tokensave", "config": fwd(cfgp)}, "mcp:tokensave")
            return ctx.notes.append("tokensave: its live entry runs the kit's binary and exits until a repository is indexed, so setup "
                                    "PARKED it. After `tokensave init` in a repo run `mcp_healer.py unpark tokensave` and restart "
                                    "Claude Code.")
    if mine and projects:                                   # in use: sessions inside an indexed repository start it there
        return ctx.notes.append(
            f"tokensave: registered LIVE in {fwd(cfgp)} and it has indexed {projects} repositor{'y' if projects == 1 else 'ies'}, so "
            "setup left it on. The doctor's MCP check starts it in an empty folder, where it can exit before answering; Claude Code "
            "sessions inside an indexed repository use it normally.")
    if live is not None:                                     # someone else's entry, or one that runs: it stays; say what it costs
        park = show([PY, fwd(KIT / "tools" / "mcp-healer" / "mcp_healer.py"), "--config", fwd(cfgp), "apply", "--golden", fwd(g)])
        return ctx.notes.append(
            f"tokensave: it is registered LIVE in {fwd(cfgp)}, and its serve exits until a repository is indexed, so the MCP check "
            f"shows it DOWN. Setup did not change it. To park it: {park}  (after tokensave init: mcp_healer.py unpark tokensave).")
    if "tokensave" in (cur.get("mcpServersParked") if isinstance(cur.get("mcpServersParked"), dict) else {}):
        return                                              # already parked, by an earlier run or by the user
    rc, _ = ctx.py_tool(KIT / "tools" / "mcp-healer" / "mcp_healer.py", "--config", cfgp, "apply", "--golden", g, timeout=120)
    if rc == 3:
        return ctx.notes.append("tokensave: a managed MCP policy is in force, so the code-graph server was not registered")
    if rc != 0:
        return ctx.notes.append(f"tokensave: mcp_healer.py apply exit {rc}; the code-graph server was not registered")
    ctx.record({"kind": "mcp", "name": "tokensave", "config": fwd(cfgp)}, "mcp:tokensave")
    ctx.notes.append("tokensave: registered PARKED (it exits until a repository is indexed). After `tokensave init` in a repo "
                     "run `mcp_healer.py unpark tokensave` and restart Claude Code.")


def do_nightly(ctx):
    """After the knowledge checks, so their bounded refreshes never compete with the full one for memory. First full
    build: run the task when it exists, else a detached refresh."""
    find = ctx.find_cli()
    if not Path(find).is_file():
        return
    if WIN and nightly_wanted(ctx):
        nightly_task(ctx, find)
    if WIN and task_exists(ctx):
        ctx.run(["schtasks", "/Run", "/TN", TASK], timeout=60)
    else:
        ctx.py_tool(find, "refresh", "--all", "--detach")


def set_config(ctx, **kw):
    ctx.cfg = {**(jload(ctx.wb / "config.json", {}) or {}), **kw}
    jwrite(ctx.wb / "config.json", ctx.cfg)


def task_exists(ctx, name=TASK):
    return ctx.run(["schtasks", "/Query", "/TN", name], timeout=60)[0] == 0


def nightly_task(ctx, find):
    memcap = KIT / "tools" / "memcap" / "memcap.py"
    acts = [(pythonw(), f'"{memcap}" --mb 2048 -- "{ctx.venv_python(gui=True)}" "{find}" refresh --all --embed auto')]
    app = ctx.wb / "capture" / "app"
    if app.is_dir():
        days = int(ctx.cfg.get("capture_retention_days") or 90)
        acts.append((ctx.which("node") or "node", f'"{app / "capture.mjs"}" purge --older-than {days}'))
    acts.append((pythonw(), f'"{HERE / "setup.py"}" backup --if-older-days 7'))          # weekly, from a daily task
    ctxexe = ctx.wb / "bin" / ("ctx.exe" if WIN else "ctx")
    if ctxexe.is_file():
        acts.append((str(ctxexe), "import --all"))
    xml = task_xml("claude-workbench: refresh the local knowledge index (memory-capped, mains power only)", acts)
    f = ctx.state_dir / "knowledge-refresh.xml"
    digest = hashlib.sha256(xml.encode("utf-8")).hexdigest()
    old = next((e for e in ctx.ledger()["entries"] if e.get("kind") == "task" and e.get("name") == TASK), None)
    if old and old.get("xml_sha256") == digest and task_exists(ctx):
        return
    f.write_text(xml, encoding="utf-16")
    rc, _ = ctx.run(["schtasks", "/Create", "/XML", str(f), "/TN", TASK, "/F"], timeout=120)
    if rc == 0:
        ctx.record({"kind": "task", "name": TASK, "xml_sha256": digest}, f"task:{TASK}")
    else:
        ctx.fail("nightly", f"schtasks /Create exit {hx(rc)}")


def do_capture(ctx, plan):
    it = next(i for i in plan["items"] if i["item"] == "capture-runtime")
    if it["tag"] == "opt-in-off":
        return
    if it["tag"] == "ask-IT":
        return
    src = KIT / "plugins" / "workbench-capture" / "skills" / "capture" / "scripts"
    if not src.is_dir():
        return ctx.fail("capture-runtime", "the capture plugin is not in this kit")
    app = ctx.wb / "capture" / "app"
    shutil.copytree(src, app, dirs_exist_ok=True, ignore=shutil.ignore_patterns("node_modules"))
    want = sha(app / "package.json")
    if not (ctx.cfg.get("capture_package_sha256") == want and (app / "node_modules").is_dir()):
        rc, _ = ctx.run(["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=str(app), timeout=1800)
        if rc != 0:
            return ctx.fail("capture-runtime", f"npm install exit {hx(rc)}")
        set_config(ctx, capture_package_sha256=want)
    rc, out = ctx.run(["node", str(app / "capture.mjs"), "--version"], timeout=60)
    if rc != 0 or not re.match(r"capture \d+\.\d+\.\d+", decode(out).strip()):
        return ctx.fail("capture-runtime", "capture.mjs --version did not print `capture <version>`")
    ctx.clear("capture-runtime")


def do_routing(ctx):
    src = KIT / "settings" / "model-routing.json"
    routing = jload(src)
    if routing is None:
        ctx.notes.append("routing: settings/model-routing.json is not in this kit; routing.effective.json not written")
        return None
    eff = effective_routing(routing, ctx.pdata("models"))
    jwrite(ctx.state_dir / "routing.effective.json", eff)
    return eff


def do_report_post(ctx):
    rc, _ = ctx.py_tool(ctx.policy_cli(), "--write")
    if rc is None:
        ctx.notes.append("policy snapshot: policy_snapshot.py is not in this kit")
    rc, out = ctx.py_tool(ctx.report_cli(), "run", "--phase", "post", "--packages", HERE / "packages.json", timeout=600)
    if rc is None:
        ctx.notes.append("capability report: report.py is not in this kit")
    else:
        ctx.log(decode(out).strip())


def setup_report(ctx, code):
    """The text a person reads when setup ends (also <state>/setup-report.md): what failed, what IT must allow, the notes, the
    libraries find found but setup did not register, and, as its LAST line, the restart every new PATH and plugin option needs."""
    L = [f"# Setup report ({now()})", "",
         f"Result: {'done' if code == 0 else 'done, with requests for IT' if code == 3 else 'a step failed'} (exit {code})."]
    for x in ctx.st["failed"]:
        L.append(f"- FAILED {x['item']}: {x['error']}")
    L += [f"- {n}" for n in ctx.notes]
    wanted = ASKS.gather(str(ctx.state_dir))     # the ONE list: setup's asks, the Day-1 checks' and the post report's, each once
    if wanted:
        L += ["", f"IT asks ({len(wanted)}, each listed once; send them together):"]
        L += [f"{i}. {a['ask']}  [{', '.join(a['sources'])}]" for i, a in enumerate(wanted, 1)]
    name = lambda x: f"{x['label'] or Path(x['path']).name} ({x['kind']}): {x['path']}"  # noqa: E731
    known = [x for x in ctx.suggestions if x.get("root")]
    fresh = [x for x in ctx.suggestions if not x.get("root")]
    if known:
        L += ["", "Libraries an earlier setup registered as search roots: they can overlap kb and captured, and the nightly "
              "refresh keeps indexing them. Guide 28 (docs/howto/28-add-a-library-to-find.md in the kit) says to index a scoped "
              "folder, never all of OneDrive. Setup does not remove a root (that is your data choice); to follow the guide run "
              f"`{fwd(ctx.find_cli())} remove-root <label>` (add --purge to drop what it indexed)."]
        L += [f"- {name(x)} - indexed by an earlier setup: remove-root {x['root']}" for x in known]
    if fresh:
        L += ["", ("Libraries found on this machine but NOT indexed" if ctx.roots_read else
                   "Libraries found on this machine (the registered roots could not be read, so whether they are indexed is not "
                   "known)") + " (setup registers only kb, howto and captured). Index a scoped folder, never all of OneDrive: "
              "see guide 28, docs/howto/28-add-a-library-to-find.md in the kit."]
        L += [f"- {name(x)}" for x in fresh]
    return "\n".join(L + ["", RESTART]) + "\n"


def finish(ctx):
    code = 4 if ctx.st["failed"] else 3 if ctx.st["ask_it"] else 0
    nxt = next((n for n in ctx.notes if n.startswith("onboarding")), None)
    ctx.save(phase="done", exit_code=code, reboot_pending=False, notes=ctx.notes, suggestions=ctx.suggestions,
             next="/workbench-core:onboard" if nxt else "nothing; check health any time with: setup.py doctor")
    text = setup_report(ctx, code)
    atomic_write(ctx.state_dir / "setup-report.md", text)
    write_marker(ctx, exit_code=code)
    print(text, end="")
    return code


def after_wsl(ctx, plan):
    ctx.phase("verify")
    do_verify(ctx, plan)
    do_path(ctx)
    do_ctx_config(ctx)
    if not ctx.no_update:
        ctx.phase("update")
        do_update(ctx)
    ctx.phase("onboard")
    do_onboard(ctx)
    ctx.phase("knowledge")
    do_knowledge(ctx)
    relay_hooks(ctx)
    do_skill_tiers(ctx)
    ctx.phase("capture-runtime")
    do_capture(ctx, plan)
    ctx.phase("knowledge-verify")
    do_knowledge_verify(ctx)
    do_tokensave_mcp(ctx)
    do_nightly(ctx)
    ctx.phase("routing")
    do_routing(ctx)
    ctx.phase("report-post")
    do_report_post(ctx)
    if I.reg_get(RUNONCE_KEY, RUNONCE_NAME):
        reg_delete(RUNONCE_KEY, RUNONCE_NAME)
    return finish(ctx)


def locked(ctx, body):
    """Run body under the lock with running/pid in the state; exit 2 when another runner holds the lock."""
    if ctx.data_error:
        print("ERROR: " + ctx.data_error)
        return 2
    if I.in_onedrive(ctx.ch):
        print(f"ERROR: CLAUDE_CONFIG_DIR ({fwd(ctx.ch)}) is inside a OneDrive folder; point it at a local folder.")
        return 2
    if not acquire(ctx):
        print(f"setup is already running (pid {lock_holder(ctx)}); poll it with: setup.py status --json --wait 60")
        return 2
    try:
        ctx.save(running=True, pid=os.getpid(), exit_code=None)
        return body()
    except Exception as e:      # the state must say what happened, the lock must go
        import traceback
        ctx.log(traceback.format_exc())
        ctx.fail("setup", f"{type(e).__name__}: {e}")
        ctx.save(exit_code=4)
        raise
    finally:
        ctx.save(running=False, pid=None)
        release(ctx)


def cmd_run(ctx):
    def body():
        ctx.st.update(ask_it=[], failed=[], reboot_pending=False, tls_revocation=None)
        ctx.phase("report-pre")
        if not (ctx.state_dir / "capability-pre.json").exists():
            rc, out = ctx.py_tool(ctx.report_cli(), "run", "--phase", "pre", "--packages", HERE / "packages.json",
                                  timeout=600)
            ctx.log(decode(out).strip() if rc is not None else "capability report: report.py is not in this kit")
        ctx.load_probe()
        if ctx.pdata("identity").get("elevated_now") is True:
            ctx.notes.append("setup ran elevated: winget can install user-scope packages from here but refuses to remove "
                             "them (0x8A15007D); run later changes from a normal terminal")
        ctx.phase("plan")
        plan = make_plan(ctx) if WIN else make_plan_posix(ctx)
        for it in plan["items"]:
            if it["tag"] == "ask-IT":
                ctx.ask(it["item"], it.get("ask_it") or f"Please allow {it.get('name', it['item'])}.")
        ctx.phase("install")
        do_install(ctx, plan)
        ctx.phase("wsl")
        if do_wsl(ctx, plan) == "reboot":
            jwrite(ctx.state_dir / "plan.json", plan)
            return 5
        return after_wsl(ctx, plan)
    return locked(ctx, body)


def make_plan_posix(ctx):
    """Linux, WSL and macOS: no packages are installed (use the distribution's package manager); the knowledge layer,
    routing and reports still run."""
    plan = {"version": 1, "generated": now(), "admin_capable": False, "store_blocked": False, "configure_off": False,
            "notes": ctx.notes + ["not Windows: install git, gh, node, python3.13 (or 3.14), rg, fd and jq with your package manager"],
            "items": [{"item": "update", "tag": "opt-in-off", "source": "winget", "scope": "user", "hosts": [],
                       "note": "use your package manager"},
                      {"item": "nightly", "tag": "opt-in-off", "source": "pypi", "scope": "user", "hosts": [], "note": "use cron"},
                      {"item": "capture-runtime", "tag": "opt-in-off", "source": "npm", "scope": "user", "hosts": [], "note": ""},
                      {"item": "wsl", "tag": "works", "source": "msstore", "scope": "user", "hosts": [], "note": "not Windows"}]}
    jwrite(ctx.state_dir / "plan.json", plan)
    atomic_write(ctx.state_dir / "plan.md", plan_md(plan))
    return plan


def cmd_resume(ctx):
    def body():
        ctx.load_probe(run=False)
        ctx.phase("resume")
        if I.reg_get(RUNONCE_KEY, RUNONCE_NAME):
            reg_delete(RUNONCE_KEY, RUNONCE_NAME)
        plan = jload(ctx.state_dir / "plan.json")
        if not plan:
            print("no plan.json: nothing to resume; run: setup.py run")
            return 2
        if not wait_network(ctx):
            ctx.log("no network answer after 10 minutes; trying the WSL step anyway")
        it = next(i for i in plan["items"] if i["item"] == "wsl")
        if it["tag"] in ("no-admin", "one-admin-prompt", "found") and it.get("result") != "denied":
            install_distro(ctx, it, ["--web-download"] if plan.get("store_blocked") else [])
        ctx.save(reboot_pending=False)
        return after_wsl(ctx, plan)
    return locked(ctx, body)


def cmd_plan(ctx):
    if lock_holder(ctx):
        print("setup is running; its plan is in " + fwd(ctx.state_dir / "plan.md"))
        return 2
    ctx.load_probe()
    plan = make_plan(ctx) if WIN else make_plan_posix(ctx)
    print(plan_md(plan))
    print(f"written: {fwd(ctx.state_dir / 'plan.md')}, plan.json, workbench.winget (nothing was installed)")
    return 0


def cmd_verify(ctx):
    bad = 0
    for p in packages():
        if p["optional_with"] and p["optional_with"] not in ctx.with_:
            continue
        status, ver = ctx.verify(p)
        print(f"{p['id']:<10} {status:<7} {ver or ''}")
        bad += status != "works" and p["id"] != "fnm"
    return 4 if bad else 0


def read_report(state_file):
    try:
        return (Path(state_file).parent / "setup-report.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def cmd_status(ctx, as_json, wait):
    path = ctx.state_dir / "setup-state.json"
    st = jload(path, {}) or {}
    if wait:
        first, end = st.get("phase"), time.time() + wait
        while time.time() < end:
            if st.get("phase") != first or (st and not lock_holder(ctx)):
                break
            time.sleep(0.5)
            st = jload(path, st) or st
    st["running"] = bool(lock_holder(ctx))
    if as_json:
        print(json.dumps(st, indent=2, ensure_ascii=False))
    else:
        print(f"phase {st.get('phase')} · running {st['running']} · exit {st.get('exit_code')} · next: {st.get('next')}")
        rep = read_report(path) if st.get("phase") == "done" else ""
        if rep:                                      # the report already lists every failure, ask and note once
            print("\n" + rep, end="")
        else:
            for x in st.get("ask_it") or []:
                print(f"  ask IT [{x['item']}]: {x['text']}")
            for x in st.get("failed") or []:
                print(f"  failed [{x['item']}]: {x['error']}")
    return 0


# ── K2 skill tiers and the K1 post-update marker ─────────────────────────────────────────────────────────────
TIERS_KEY = "settings:skill-tiers"
MARKER = "post-update-verify.json"      # written by setup and kit_update.py; session_start.py reads it; kit_update.py verify clears it


def write_marker(ctx, **extra):
    """A verify is pending: the first session after the restart tells Claude to run `kit_update.py verify` once."""
    jwrite(ctx.state_dir / MARKER, {"version": I.VERSION, "time": now(), "from_version": ctx.prev_version, **extra})


def managed_settings():
    m = {}
    for _src, d in I.managed_sources():
        I.deep_merge(m, d)
    return m


def do_skill_tiers(ctx, force=False, dry=False, log=True):
    """K2. Measure the whole skill listing (skill_tiers.measure) and, when it is over 80% of the 30,000-character default limit
    (a raised skillListingBudgetFraction does not raise this aim; the doctor row still warns against the real limit), list the
    user's OWN skills by name only through skillOverrides in settings.json: skills the kit's instructions route to stay on, pack
    skills go name-only, then the largest others until under 80%. A plugin's skills are never touched (skillOverrides does not
    apply to them), a value the user set is never overwritten (force: it is), the file is backed up first and the change is
    recorded for undo-config. Returns the lines to show; the full list goes to <state>/skill-tiers.md. Skill names stay here."""
    sp = ctx.ch / "settings.json"
    try:
        user = I.read_json(sp) if sp.exists() else {}
    except (OSError, ValueError) as e:
        ctx.notes.append(f"skill tiers: {fwd(sp)} is not valid JSON ({e}); nothing was changed")
        return []
    managed = managed_settings()
    info = ST.measure(ctx.ch, KIT, Path.cwd(), managed=managed)
    plan = ST.plan(info, KIT, force)
    ch, goal = plan["changes"], plan["goal"]
    lines = [f"skill listing: about {info['total']:,} of {info['limit']:,} characters ({info['pct']}%); limit from {info['limit_from']}"]
    backup, skipped = None, []
    if ch and not dry:
        backup = ctx.wb / "backups" / (time.strftime("%Y%m%d-%H%M%S") + "-skill-tiers") / "settings.json"
        if sp.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sp, backup)
        ops, notes = [], []
        I.merge_settings(user, {"skillOverrides": ch}, managed, force, ops, notes)
        skipped = [k.rsplit(".", 1)[-1] for k, _why in notes]
        if ops:
            atomic_write(sp, json.dumps(user, indent=2, ensure_ascii=False) + "\n")
            old = next((e for e in ctx.ledger()["entries"] if e.get("key") == TIERS_KEY), None)
            ctx.record({"kind": "settings", "what": "skill tiers (skillOverrides)", "path": fwd(sp),
                        "ops": ((old or {}).get("ops") or []) + ops}, TIERS_KEY)
    if not ch:
        lines.append(f"no tiers needed: at or under {goal:,} characters (80% of the default limit)" if plan["reached"] else
                     "nothing to tier: every skill that could change is on by your choice, routed to by the kit, or already name-only")
    else:
        by = {s["name"]: s for s in info["skills"] if not s["plugin"]}
        lines.append(f"{'would set' if dry else 'set'} {len(ch)} of your own skill(s) to name-only in {fwd(sp)}; the listing falls "
                     f"from about {plan['before']:,} to about {plan['after']:,} characters")
        lines += [f"  {n}  ({by[n]['group']}, saves {by[n]['size'] - len(by[n]['key']):,})" for n in sorted(ch, key=lambda n: -by[n]["size"])]
        if any(by[n]["group"] == "org-synced skills" for n in ch):
            lines.append("org-synced skills: Claude Code's documentation does not say whether skillOverrides applies to them; if the "
                         "listing stays full, ask your Claude admin to tier them")
    if plan["kept_on"]:
        lines.append("kept on (the kit's instructions route to them): " + ", ".join(plan["kept_on"]))
    if plan["user_set"] or skipped:
        lines.append("left as set (yours, or a managed value): " + ", ".join(sorted({*plan["user_set"], *skipped})))
    if not plan["reached"]:
        lines.append(f"still over the 80% target ({plan['after']:,} of {goal:,}): the rest is plugin skills, which skillOverrides cannot "
                     "change, and the bundled-skill allowance")
    if backup and backup.exists():
        lines.append(f"backup of settings.json: {fwd(backup)}")
    body = "\n".join(x if x.startswith("  ") else f"- {x}" for x in lines)
    atomic_write(ctx.state_dir / "skill-tiers.md", f"# Skill tiers ({now()})\n\n{body}\n")
    if ch and not dry or not plan["reached"]:
        ctx.notes.append(f"skill tiers: {len(ch)} skill(s) set to name-only, listing about {plan['before']:,} -> {plan['after']:,} of "
                         f"{info['limit']:,} characters" + ("" if plan["reached"] else "; still over 80%, only plugin skills are left to cut")
                         + f"; details in {fwd(ctx.state_dir / 'skill-tiers.md')}")
    for x in lines if log else ():
        ctx.log(x)
    return lines


def cmd_skills(ctx, force, dry):
    if lock_holder(ctx):
        print(f"setup is running (pid {lock_holder(ctx)}); run this when it has finished")
        return 2
    print("\n".join(do_skill_tiers(ctx, force, dry, log=False)))      # the lines go to stdout once, not to stderr again
    return 0


# ── undo-config ──────────────────────────────────────────────────────────────────────────────────────────────
def undo_config(apply=False):
    """Undo the machine changes this install's setup recorded in its ledger (newest first). Called by install.py
    --uninstall. 0 = done, 4 = something could not be undone (it stays in the ledger)."""
    ctx = Ctx()
    say = (lambda m: print("    " + m)) if apply else (lambda m: print("    would: " + m))
    led, keep, bad = ctx.ledger(), [], False
    # only what THIS install's ledger recorded: the task and RunOnce names are shared by every install on the machine
    names = {e.get("name") for e in led["entries"] if e.get("kind") == "task"}
    runonce = any(e.get("kind") == "runonce" for e in led["entries"])
    for e in reversed(led["entries"]):
        k = e.get("kind")
        if k == "env":
            cur = I.reg_get(ENV_KEY, e["name"])
            if cur and str(cur[0]) == e["value"]:
                say(f"{'restore' if e.get('old') is not None else 'remove'} user env {e['name']}")
                if apply:
                    reg_set(ENV_KEY, e["name"], e["old"], 1) if e.get("old") is not None else reg_delete(ENV_KEY, e["name"])
            elif cur:
                say(f"leave user env {e['name']} (changed since setup set it)")
        elif k == "path-append":
            cur = I.reg_get(ENV_KEY, "Path")
            if cur and any(x.lower() == e["entry"].lower() for x in str(cur[0]).split(";")):
                say(f"remove {e['entry']} from the user Path")
                if apply:
                    reg_set(ENV_KEY, "Path", ";".join(x for x in str(cur[0]).split(";") if x.lower() != e["entry"].lower()),
                            cur[1])
        elif k == "gitconfig":
            rc, out = ctx.run(["git", "config", "--global", "--get", e["name"]], timeout=60)
            if rc == 0 and decode(out).strip() == e["value"]:
                say(f"git config --global {e['name']}: {'restore' if e.get('old') else 'unset'}")
                if apply:
                    ctx.run(["git", "config", "--global", e["name"], e["old"]] if e.get("old") else
                            ["git", "config", "--global", "--unset", e["name"]], timeout=60)
        elif k == "file":
            p = Path(e["path"])
            if p.exists() and sha(p) == e.get("sha256"):
                say(f"remove {e['path']}")
                if apply:
                    p.unlink()
            elif p.exists():
                say(f"leave {e['path']} (changed since setup wrote it)")
        elif k in ("task", "runonce"):
            continue                              # handled below, once per recorded name
        elif k == "fetched":
            say(f"leave the {e['what']} skills in your skills folder (yours now; delete them by hand)")
        elif k == "skills":
            say(f"leave the {e['what']} skill in {e['path']} (yours now; delete it by hand)")
        elif k == "package" and e.get("source") == "npm":
            say(f"npm uninstall -g {e['npm']}")
            if apply and ctx.run(["npm", "uninstall", "-g", e["npm"], *(["--prefix", e["prefix"]] if e.get("prefix") else [])],
                                 timeout=600)[0] != 0:
                bad = True
                keep.append(e)
        elif k == "settings":           # the StopFailure relay hooks: only values still equal to what setup wrote go
            sp = Path(e["path"])
            try:
                user = I.read_json(sp) if sp.exists() else None
            except (OSError, ValueError):
                user = None
            if user is None:
                say(f"leave {e['path']} (missing or not valid JSON)")
            else:
                say(f"remove the {e.get('what', 'setup')} from {e['path']}")
                if apply:
                    I.undo_settings(user, e.get("ops") or [])
                    atomic_write(sp, json.dumps(user, indent=2, ensure_ascii=False) + "\n")
                    relay_mark_set(ctx, None)      # setup took its own pair out: the ledger no longer says "written"
        elif k == "mcp":                # the find MCP server setup registered: removed through the healer, which backs up
            say(f"remove the user MCP server {e['name']} from {e['config']}")
            if apply and Path(e["config"]).is_file():
                g = ctx.state_dir / "undo-mcp.golden.json"
                jwrite(g, {"servers": {e["name"]: {"action": "remove", "reason": "setup.py undo-config"}}})
                if ctx.py_tool(KIT / "tools" / "mcp-healer" / "mcp_healer.py", "--config", e["config"], "apply",
                               "--golden", g, timeout=120)[0] != 0:
                    bad = True
                    keep.append(e)
                g.unlink(missing_ok=True)
        elif k == "dir":
            d = Path(e["path"])
            if d.is_dir() and d.resolve().is_relative_to(ctx.wb.resolve()):      # only ever a folder under <WB>
                say(f"remove {e['path']}")
                if apply:
                    shutil.rmtree(d, ignore_errors=True)
    if WIN:
        for n in sorted(names):
            if task_exists(ctx, n):
                say(f"delete scheduled task {n}")
                if apply and ctx.run(["schtasks", "/Delete", "/TN", n, "/F"], timeout=60)[0] != 0:
                    bad = True
                    keep += [e for e in led["entries"] if e.get("name") == n]
    if runonce and I.reg_get(RUNONCE_KEY, RUNONCE_NAME):
        say(f"delete the RunOnce value {RUNONCE_NAME}")
        if apply:
            reg_delete(RUNONCE_KEY, RUNONCE_NAME)
    prof = ctx.wb / "capture" / "profile"
    if prof.exists():
        say(f"remove the capture browser profile {fwd(prof)}")
        if apply:
            shutil.rmtree(prof, ignore_errors=True)
    if apply and ctx.state_dir.exists():
        jwrite(ctx.state_dir / "provision-ledger.json", {"version": 1, "entries": keep})
    return 4 if bad else 0


# ── doctor ───────────────────────────────────────────────────────────────────────────────────────────────────
def find_git(root, depth=4, budget=20000):
    """First .git folder under root within depth (bounded walk; listing never hydrates cloud files)."""
    root, seen = Path(root), 0
    if not root.is_dir():
        return None
    stack = [(root, 0)]
    while stack:   # ponytail: bounded DFS, a full scan of a large OneDrive would be slow
        d, n = stack.pop()
        try:
            for c in d.iterdir():
                seen += 1
                if c.name == ".git":
                    return c
                if c.is_dir() and not c.is_symlink() and n < depth:
                    stack.append((c, n + 1))
        except OSError:
            continue
        if seen > budget:
            return None
    return None


def placement_rows(ctx):
    rows = []
    work, cands = I.work_onedrive()
    if I.in_onedrive(ctx.ch):
        rows.append(("placement: config dir", "FAIL", f"{fwd(ctx.ch)} is inside OneDrive; keep it local"))
    kdb = ctx.cfg.get("knowledge_db") or fwd(ctx.lad / "doc-index" / "knowledge" / "index.sqlite")
    if I.in_onedrive(kdb):
        rows.append(("placement: knowledge index", "FAIL", f"{kdb} is inside OneDrive (SQLite with WAL corrupts there)"))
    for e, p in I.layout_resolved(ctx.ch):
        if p is None:
            continue
        if e.get("placement") == "local-only" and I.in_onedrive(p):
            rows.append(("placement: " + e["path"], "FAIL", f"{fwd(p)} must stay local, it is inside OneDrive"))
    for r in {fwd(x) for x in (ctx.data, ctx.kb, work) if x}:
        g = find_git(r) if I.in_onedrive(r) else None
        if g:
            rows.append(("placement: git in OneDrive", "FAIL", f"{fwd(g)}: no git repository inside OneDrive (lock files "
                                                               "and conflict copies corrupt it); move it to <HOME>/src"))
    if len(cands) > 1:
        rows.append(("placement: work OneDrive", "WARN", f"{len(cands)} work OneDrive folders; data stays at {fwd(ctx.data)}"))
    elif work and not I.under(ctx.data, work):
        rows.append(("placement: work OneDrive", "WARN", f"a work OneDrive exists ({fwd(work)}) but data is local; re-run "
                                                         "install with --data-root to use it"))
    return rows or [("placement", "OK", "local-only paths are local; no git inside OneDrive")]


updates_row = KV.updates_row     # (status, detail) for the `updates` row from update.json (IP3); D22 reads it too


def known_bugs(text):
    """Distinct `Known bug, card N: ...` lines the kit's own detectors give for a text (bug_hint.py, imported by path)."""
    f = KIT / "plugins" / "workbench-core" / "scripts" / "bug_hint.py"
    if not f.is_file():
        return []
    try:
        spec = importlib.util.spec_from_file_location("wb_bug_hint", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        found = []
        for ln in text.splitlines()[:300]:
            h = mod.hint(ln)
            if h and h not in found:
                found.append(h)
        return found
    except Exception:       # a broken detector file must not break the doctor
        return []


def claude_sweep(ctx):
    """(status, detail): `claude doctor` (60 s, stdin closed) read through the bug-card detectors; INFO when no text comes back."""
    rc, out = ctx.run(["claude", "doctor"], timeout=60)
    text = decode(out).strip()
    if rc is None:
        return "INFO", "claude is not on this PATH: nothing to read"
    if rc == -1:
        return "INFO", "claude doctor did not answer within 60 s"
    if not text:
        return "INFO", f"claude doctor printed nothing (exit {hx(rc)})"
    hits = known_bugs(text)
    if hits:
        return "WARN", " | ".join(hits[:3]) + (f" (+{len(hits) - 3} more)" if len(hits) > 3 else "")
    return "OK", f"{len(text.splitlines())} line(s) read; none matches a known bug card"


def plugin_option_row(ctx):
    """(status, detail): every enabled workbench plugin whose manifest declares userConfig.python has pluginConfigs.<id>.options.
    python set to an interpreter that runs. Unset means every hook of that plugin fails with `Plugin option "python" isn't set`
    and no hook runs, while the heartbeat can still read OK from an earlier session."""
    sp = ctx.ch / "settings.json"
    try:
        user = I.read_json(sp) if sp.exists() else {}
    except (OSError, ValueError) as e:
        return "WARN", f"{fwd(sp)} is not valid JSON ({e}): the plugin options cannot be checked"
    on = [i for i in I.python_plugin_ids(KIT) or I.PLUGIN_IDS if (user.get("enabledPlugins") or {}).get(i) is True]
    if not on:
        return "INFO", "no workbench plugin that needs a python option is enabled in settings.json yet"
    bad = []
    for i in on:
        py = (((user.get("pluginConfigs") or {}).get(i) or {}).get("options") or {}).get("python")
        if not py or not isinstance(py, str):
            bad.append(f"{i}: python is not set")
        elif ctx.run([py, "--version"], timeout=30)[0] != 0:
            bad.append(f"{i}: {py} does not run")
    if bad:
        fix = ctx.cfg.get("python") or fwd(PY)
        return "FAIL", ("; ".join(bad) + ". Every hook of that plugin fails with `Plugin option \"python\" isn't set`, so "
                        f"none of its hooks run. Fix, for each: claude plugin install <id> --config python={fix}")
    return "OK", f"{len(on)} plugin(s) have a python option that runs"


def mcp_row(ctx, rc, out):
    """(status, detail) from `mcp_healer.py check --json` (exit code and output): DOWN warns, PARKED never does. The healer exits
    0 or 1 and prints a JSON list; anything else (a traceback on a malformed .claude.json) is not "healthy"."""
    try:
        rows = json.loads(decode(out))
    except ValueError:
        rows = None
    if rc not in (0, 1) or not isinstance(rows, list):
        return "WARN", f"mcp_healer.py check exit {rc} gave no readable result: run it by hand"
    rows = [r for r in rows if isinstance(r, dict)]
    down = [r["server"] for r in rows if r.get("status") == "DOWN"]
    parked = [r["server"] for r in rows if r.get("status") == "PARKED"]
    tail = ("; PARKED (not loaded at startup, not an error): " + ", ".join(parked)
            + "; turn one on with: mcp_healer.py unpark <name>"
            + ("; tokensave needs `tokensave init` in a repository first" if "tokensave" in parked else "")) if parked else ""
    if down:
        return "WARN", "DOWN: " + ", ".join(down) + " (run mcp_healer.py check)" + tail
    return "OK", "healthy" + tail


KV_SHOWN = {"PASS": "OK", "WARN": "WARN", "FAIL": "FAIL", "SKIP": "INFO", "OPT-IN-OFF": "INFO"}


def cmd_doctor(ctx, as_json=False, bundle=None, deep=False):
    """Health rows; exit 2 on a FAIL row, 1 on a WARN, else 0. --deep is a superset: it first runs the Day-1 knowledge
    checks (doctor mode: live reads only, writes only knowledge-verify.json), adds one row per check, and exits 2 when
    ANY row is FAIL (a doctor row or a named knowledge check), else 0: a WARN never makes it nonzero (U11)."""
    rows = []
    add = lambda c, s, d: rows.append((c, s, d))  # noqa: E731
    outputs = {}
    kv = KV.run(ctx, "doctor") if deep else None
    if kv:
        outputs["knowledge-verify.json"] = kv
    rc, out = ctx.py_tool(ctx.report_cli(), "run", "--phase", "refresh", "--quick", timeout=120)
    add("capability report (quick)", "OK" if rc == 0 else "WARN", "refreshed" if rc == 0 else
        ("report.py is not in this kit" if rc is None else f"exit {rc}"))
    probe_json = os.environ.get("WORKBENCH_PROBE_JSON")
    if probe_json:
        pj = jload(probe_json, {})
    else:
        prc, pout = ctx.py_tool(HERE / "probe.py", "--only", "tls,network", "--json", timeout=180)
        pj = jparse(pout) if prc == 0 else None
    rev = (jload(ctx.state_dir / "setup-state.json", {}) or {}).get("tls_revocation")
    rev = [f"curl could not check certificate revocation (CRYPT_E_NO_REVOCATION_CHECK: a TLS-inspecting proxy's "
           f"certificates name no reachable revocation point); setup's downloads retried with --ssl-revoke-best-effort "
           f"({rev.get('at')})"] if isinstance(rev, dict) else []
    if pj is None:
        add("TLS + network", "WARN", "; ".join(["probe.py is not in this kit"] + rev))
    else:
        outputs["probe.json"] = pj
        sec = pj.get("sections") or {}
        bad_rt = [r["runtime"] for r in ((sec.get("tls") or {}).get("data") or {}).get("runtimes") or [] if not r.get("ok")]
        blocked_ep = [e["name"] for e in ((sec.get("network") or {}).get("data") or {}).get("endpoints") or []
                      if e.get("result") in ("blocked", "error", "proxy-auth")]
        add("TLS + network", "WARN" if bad_rt or blocked_ep or rev else "OK",
            ", ".join([f"TLS fails: {', '.join(bad_rt)}"] * bool(bad_rt) + [f"blocked: {', '.join(blocked_ep)}"] * bool(blocked_ep)
                      + rev) or "every runtime verifies TLS; every endpoint answers")
    hb = jload(ctx.state_dir / "hooks-heartbeat.json")      # I3: SessionStart stamps last_start; never a FAIL
    last = hb.get("last_start") if isinstance(hb, dict) else None
    if isinstance(last, str) and last:
        add("hooks heartbeat", "OK", f"last session start {last}")
    else:
        add("hooks heartbeat", "WARN", "no Claude Code session has started since the install: start one, then run the doctor again")
    add("plugin python option", *plugin_option_row(ctx))
    add("skill listing", *ST.row(ST.measure(ctx.ch, KIT, Path.cwd(), managed=managed_settings()))[:2])
    user_mcp = (ctx.ch / ".claude.json") if os.environ.get("CLAUDE_CONFIG_DIR") else ctx.home / ".claude.json"
    if not user_mcp.is_file():
        add("MCP servers", "OK", "no user-scope MCP configuration yet")
    else:
        rc, out = ctx.py_tool(KIT / "tools" / "mcp-healer" / "mcp_healer.py", "check", "--json", timeout=300)
        add("MCP servers", *(("WARN", "mcp_healer.py is not in this kit") if rc is None else mcp_row(ctx, rc, out)))
    kdb = Path(os.environ.get("WORKBENCH_KNOWLEDGE_DB") or ctx.cfg.get("knowledge_db")
               or ctx.lad / "doc-index" / "knowledge" / "index.sqlite")
    # `find status` opens the index, and opening a missing one creates it: the doctor only reads, so look first
    rc, out = ctx.py_tool(ctx.find_cli(), "status", "--json", timeout=120) if kdb.is_file() else (None, "")
    status = jparse(out) if rc == 0 else None
    if not kdb.is_file():
        add("knowledge index", "WARN", "no index yet: setup.py run builds it")
    elif status is None:
        add("knowledge index", "WARN", "the find CLI did not answer")
    else:
        outputs["find-status.json"] = status
        last = status.get("last_refresh")
        age = (time.time() - datetime.datetime.strptime(last[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()) / 3600 if last else None
        add("knowledge index", "OK" if age is not None and age < 48 else "WARN",
            f"last refresh {last or 'never'}; {status.get('paragraphs', 0)} paragraphs")
    bj = jload(ctx.state_dir / "backup.json")
    cloud = I.in_onedrive(ctx.data)
    if not bj:
        add("backup", "WARN", "never backed up: run setup.py backup" + ("" if cloud else
            " (no cloud copy: keep the zip in a location your employer approves)"))
    else:
        days = (time.time() - datetime.datetime.strptime(bj["last"][:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()) / 86400
        add("backup", "OK" if days <= 7 else "WARN", f"last {bj['last']} ({days:.0f} days ago) at {bj.get('path')}")
    rc, out = ctx.py_tool(ctx.policy_cli(), "--json", timeout=60)
    pol = jparse(out) if rc == 0 else None
    add("managed policy", "WARN" if pol is None or pol.get("changed") else "OK",
        "policy_snapshot.py did not answer" if pol is None else
        (f"changed since setup: {', '.join(pol['changed'])}" if pol.get("changed") else "unchanged since setup"))
    st = jload(ctx.state_dir / "setup-state.json", {}) or {}
    outputs["setup-state.json"] = st
    if st.get("failed"):
        add("setup", "FAIL", "; ".join(f"{x['item']}: {x['error']}" for x in st["failed"]))
    elif st.get("ask_it") or st.get("reboot_pending"):
        add("setup", "WARN", f"{len(st.get('ask_it') or [])} ask-IT item(s)" + (", reboot pending" if st.get("reboot_pending") else ""))
    else:
        add("setup", "OK", f"phase {st.get('phase') or 'not run'}")
    wanted = ASKS.gather(str(ctx.state_dir))      # the same list setup and the capability report show: one line per distinct ask
    outputs["it-asks.json"] = {"asks": wanted}
    add("IT asks", "INFO" if wanted else "OK", (f"{len(wanted)} distinct ask(s), each listed once: " + " | ".join(
        f"{i}. {a['ask'][:110]}" for i, a in enumerate(wanted, 1))) if wanted else "none outstanding")
    up = jload(ctx.state_dir / "update.json")
    if up:
        outputs["update.json"] = up
    add("updates", *updates_row(up))
    add("claude startup warnings", *claude_sweep(ctx))
    rows += placement_rows(ctx)
    code = 2 if any(s == "FAIL" for _, s, _ in rows) else 1 if any(s == "WARN" for _, s, _ in rows) else 0
    if kv:
        rows += [(f"knowledge: {x['name']}", KV_SHOWN.get(x["status"], "WARN"), f"{x['id']} {x['detail']}") for x in kv["steps"]]
        code = 2 if any(s == "FAIL" for _, s, _ in rows) else 0       # every row, the doctor's own included
    result = {"version": 1, "generated": now(), "exit_code": code,
              "rows": [{"check": c, "status": s, "detail": d} for c, s, d in rows]}
    if kv:
        result["knowledge_verify"] = kv["summary"]
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        for c, s, d in rows:
            print(f"{s:<5} {c:<34} {d}")
    if bundle:
        make_bundle(ctx, bundle, {"doctor.json": result, **outputs})
    return code


def make_bundle(ctx, out, outputs):
    """A support zip: every JSON passes through tools/redact-settings first. Never USER.md, KB notes or tokens."""
    import tempfile
    redact = KIT / "tools" / "redact-settings" / "redact_settings.py"
    extra = {"settings.json": ctx.ch / "settings.json", "plan.json": ctx.state_dir / "plan.json",
             "routing.effective.json": ctx.state_dir / "routing.effective.json"}
    with tempfile.TemporaryDirectory() as t, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, obj in outputs.items():
            (Path(t) / ("raw-" + name)).write_text(json.dumps(obj), encoding="utf-8")
            extra[name] = Path(t) / ("raw-" + name)
        for name, src in extra.items():
            if not Path(src).is_file():
                continue
            dst = Path(t) / name
            r = subprocess.run([PY, str(redact), str(src), str(dst)], capture_output=True, timeout=120,
                               creationflags=NO_WINDOW)
            if r.returncode == 0 and dst.exists():
                z.write(dst, name)
    print(f"support bundle (redacted): {fwd(out)}")


# ── backup / restore ─────────────────────────────────────────────────────────────────────────────────────────
def backup_sources(ctx):
    """[(archive name, path)]: KB notes (no index), USER.md, workbench config, capture scope, profiles, and
    the user's own CLAUDE.md, rules, agents and skills (Markdown only). settings.json goes in redacted, as reference."""
    out = []
    if ctx.kb.is_dir():
        out += [(f"KB/{fwd(p.relative_to(ctx.kb))}", p) for p in sorted(ctx.kb.rglob("*.md")) if ".git" not in p.parts]
        if (ctx.kb / "inbox.jsonl").is_file():          # the journal: lines not yet folded into active-context
            out.append(("KB/inbox.jsonl", ctx.kb / "inbox.jsonl"))
    for rel in ("USER.md", "config.json", "profiles.json", "capture/scope.json"):
        if (ctx.wb / rel).is_file():
            out.append((f"WB/{rel}", ctx.wb / rel))
    if (ctx.ch / "CLAUDE.md").is_file():
        out.append(("CH/CLAUDE.md", ctx.ch / "CLAUDE.md"))
    for d in ("rules", "agents", "skills"):
        if (ctx.ch / d).is_dir():
            out += [(f"CH/{fwd(p.relative_to(ctx.ch))}", p) for p in sorted((ctx.ch / d).rglob("*.md"))]
    return [(a, p) for a, p in out if not p.name.lower().startswith(".credentials")]


def backup_age_days(ctx):
    bj = jload(ctx.state_dir / "backup.json", {}) or {}
    try:
        return (time.time() - datetime.datetime.strptime(bj["last"][:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()) / 86400
    except (KeyError, TypeError, ValueError):
        return None


def cmd_backup(ctx, out=None, if_older_days=None):
    t0 = time.time()
    age = backup_age_days(ctx)
    if if_older_days is not None and age is not None and age < if_older_days:
        print(f"backup: the newest is {age:.1f} days old (under {if_older_days}); nothing written")
        return 0
    out = Path(out) if out else ctx.data / "backup" / f"workbench-backup-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    files = []
    tmp = out.with_name(out.name + ".tmp")          # OneDrive never uploads .tmp files: only the finished zip syncs
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, p in backup_sources(ctx):
            data = p.read_bytes()
            z.writestr(arc, data)
            files.append({"path": arc, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                          "mtime": p.stat().st_mtime})
        sp = ctx.ch / "settings.json"
        if sp.is_file():
            red = out.with_name(out.name + ".settings.tmp")
            r = subprocess.run([PY, str(KIT / "tools" / "redact-settings" / "redact_settings.py"),
                                str(sp), str(red)], capture_output=True, timeout=120, creationflags=NO_WINDOW)
            if r.returncode == 0 and red.exists():
                z.write(red, "CH/settings.redacted.json")
            red.unlink(missing_ok=True)
        z.writestr("manifest.json", json.dumps({"version": 1, "created": now(), "files": files}, indent=1))
    os.replace(tmp, out)
    jwrite(ctx.state_dir / "backup.json", {"last": now(), "path": fwd(out)})
    print(f"backup: {len(files)} file(s) -> {fwd(out)} in {time.time() - t0:.1f} s")
    return 0


SETTINGS_NAMES = {"settings.json", "settings.local.json", "settings.redacted.json"}


def member_parts(arc, tops):
    """The '/'-separated parts of a safe archive member, else None: no backslash, no colon or drive in any part, no
    empty, '.' or '..' part, no absolute path, and a known top folder."""
    if not isinstance(arc, str) or "\\" in arc or arc.startswith("/"):
        return None
    parts = arc.split("/")
    if len(parts) < 2 or parts[0] not in tops or any(x in ("", ".", "..") or ":" in x for x in parts):
        return None
    return parts


def hook_commands(data):
    """Every hook command in a settings.json body (a restored one can run code at the next session start)."""
    try:
        hooks = json.loads(data.decode("utf-8-sig")).get("hooks") or {}
    except (ValueError, AttributeError, UnicodeDecodeError):
        return ["<unreadable settings file: not restored>"]
    return [h.get("command", "") for groups in hooks.values() if isinstance(groups, list) for g in groups
            if isinstance(g, dict) for h in g.get("hooks") or [] if isinstance(h, dict)]


def cmd_restore(ctx, src, to=None, apply=False, force=False, restore_settings=False):
    t0 = time.time()
    dest = {"KB": ctx.kb, "WB": ctx.wb, "CH": ctx.ch}
    with zipfile.ZipFile(src) as z:
        man = json.loads(z.read("manifest.json"))
        checked = []
        for f in man["files"]:
            arc = f.get("path")
            parts = member_parts(arc, dest)
            if not parts:
                print(f"ERROR: unsafe path in the backup: {arc!r}; nothing was restored")
                return 4
            try:
                info = z.getinfo(arc)
            except KeyError:
                print(f"ERROR: {arc} is listed but missing; nothing was restored")
                return 4
            if (info.external_attr >> 16) & 0o170000 == 0o120000 or info.is_dir():
                print(f"ERROR: {arc} is a link or a folder entry; nothing was restored")
                return 4
            if info.file_size != f["size"]:
                print(f"ERROR: size mismatch for {arc}; nothing was restored")
                return 4
            data = z.read(arc)
            if hashlib.sha256(data).hexdigest() != f["sha256"]:
                print(f"ERROR: hash mismatch for {arc}: nothing was restored")
                return 4
            base = (Path(to) if to else dest[parts[0]]).resolve()
            dst = (base / ("/".join(parts) if to else "/".join(parts[1:]))).resolve()
            if not dst.is_relative_to(base):
                print(f"ERROR: {arc} resolves outside {fwd(base)}; nothing was restored")
                return 4
            checked.append((f, data, dst, parts))
    n = 0
    for f, data, dst, parts in checked:
        if parts[0] == "CH" and parts[-1] in SETTINGS_NAMES:
            for c in hook_commands(data):
                print(f"  hook command in {f['path']}: {c}")
            if not restore_settings:
                print(f"  skip {f['path']}: settings files are written only with --restore-settings")
                continue
        if not (to or apply):
            print(f"  would restore {f['path']} -> {fwd(dst)}")
            continue
        if apply and not to and dst.exists() and dst.stat().st_mtime > f["mtime"] + 1 and not force:
            print(f"  keep {fwd(dst)}: newer than the backup (--force replaces it)")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        os.utime(dst, (f["mtime"], f["mtime"]))
        n += 1
    print(f"restore: {len(checked)} file(s) verified, {n} written"
          + (f" to {fwd(to)}" if to else "" if apply else " (dry run: add --to DIR or --apply)")
          + f", in {time.time() - t0:.1f} s")
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────────────────
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="claude-workbench setup (see the module docstring)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "plan"):
        p = sub.add_parser(name)
        p.add_argument("--with", dest="with_", default="")
        p.add_argument("--no-nightly", action="store_true")
        p.add_argument("--no-update", action="store_true")
        if name == "run":
            p.add_argument("--detach", action="store_true")
    sub.add_parser("resume")
    sub.add_parser("verify")
    p = sub.add_parser("update")
    p.add_argument("--with", dest="with_", default="")
    p.add_argument("--check", action="store_true")
    p.add_argument("--json", action="store_true")
    sub.add_parser("routing")
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p.add_argument("--wait", type=float, default=0)
    p = sub.add_parser("undo-config")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("doctor")
    p.add_argument("--json", action="store_true")
    p.add_argument("--deep", action="store_true")
    p.add_argument("--bundle")
    p = sub.add_parser("skills")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("backup")
    p.add_argument("--out")
    p.add_argument("--if-older-days", type=float, dest="if_older_days")
    p = sub.add_parser("restore")
    p.add_argument("zip")
    p.add_argument("--to")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--restore-settings", action="store_true")
    sub.add_parser("report", add_help=False)
    if argv[:1] == ["report"]:
        ctx = Ctx()
        if not Path(ctx.report_cli()).is_file():
            print("report.py is not in this kit")
            return 2
        return subprocess.run([PY, ctx.report_cli(), *argv[1:]]).returncode
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    with_ = [w.strip() for w in (getattr(a, "with_", "") or "").split(",") if w.strip()]
    bad = [w for w in with_ if w not in I.EXTRAS]
    if bad:
        print(f"--with: unknown option(s) {', '.join(bad)}; known: {', '.join(I.EXTRAS)}")
        return 2
    ctx = Ctx(with_, getattr(a, "no_nightly", False), getattr(a, "no_update", False))
    if a.cmd == "update":
        return cmd_update(ctx, a.check, a.json)
    if a.cmd == "run":
        if a.detach:
            return detach(ctx, [x for x in argv if x != "--detach"])
        return cmd_run(ctx)
    if a.cmd == "resume":
        return cmd_resume(ctx)
    if a.cmd == "plan":
        return cmd_plan(ctx)
    if a.cmd == "verify":
        return cmd_verify(ctx)
    if a.cmd == "status":
        return cmd_status(ctx, a.json, a.wait)
    if a.cmd == "undo-config":
        print(f"claude-workbench undo-config ({'APPLY' if a.apply else 'DRY RUN: add --apply'})")
        return undo_config(a.apply)
    if a.cmd == "routing":
        ctx.load_probe(run=False)
        eff = do_routing(ctx)
        print(json.dumps(eff, indent=2) if eff else "\n".join(ctx.notes))
        return 0 if eff else 4
    if a.cmd == "doctor":
        return cmd_doctor(ctx, a.json, a.bundle, a.deep)
    if a.cmd == "skills":
        return cmd_skills(ctx, a.force, a.dry_run)
    if a.cmd == "backup":
        return cmd_backup(ctx, a.out, a.if_older_days)
    if a.cmd == "restore":
        return cmd_restore(ctx, a.zip, a.to, a.apply, a.force, a.restore_settings)
    return 2


if __name__ == "__main__":
    sys.exit(main())
