#!/usr/bin/env python3
"""probe.py: read-only capability probe (Python 3.10+, standard library only).

  py -3 bootstrap/probe.py [--out DIR] [--only s1,s2] [--extra-endpoint URL]... [--packages FILE]
                           [--git-hosts H1,H2] [--no-network] [--json]

Writes probe.json and probe.md under --out (default <CLAUDE_CONFIG_DIR or ~/.claude>/workbench/state) and nothing
else. All 16 sections are always present; a section that cannot be read says so in its status and notes. Exit 0 unless
the command line is wrong (2).

Rules: every child process goes through run(), whose allowlist raises on anything else and whose calls all carry a
timeout; decisions come from exit codes and structured data, never from English output; the probe never asks for
elevation and never changes the machine; the network part is serial, one 45 s budget, hosts only from the package
table, the model API, --git-hosts and --extra-endpoint.
"""
import argparse
import atexit
import csv
import datetime
import io
import json
import os
import platform
import re
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

KIT_VERSION = "0.3.3"
UA = "claude-workbench-probe/" + KIT_VERSION
NET_BUDGET_S = 45
HTTP_TIMEOUT = 4
SECTIONS = ("os", "hardware", "management", "identity", "app_control", "policies", "security", "tools",
            "virtualization", "network", "tls", "claude", "models", "github", "knowledge", "capture")
TOOLS = ("git", "gh", "node", "npm", "uv", "pwsh", "rg", "fd", "jq", "code", "claude", "winget", "wsl",
         "tokensave", "fnm", "curl", "bwrap")
IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0

# The one read-only PowerShell script (JSON out). Only get/select style cmdlets; run() accepts nothing else.
PS_MAIN = r"""
$ErrorActionPreference='SilentlyContinue';$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$o=[ordered]@{}
$o.lang="$($ExecutionContext.SessionState.LanguageMode)"
$o.execpol="$(Get-ExecutionPolicy)"
$mp=Get-ExecutionPolicy -List|Where-Object{$_.Scope -eq 'MachinePolicy'}|Select-Object -First 1
$o.pol_machine="$($mp.ExecutionPolicy)"
$up=Get-ExecutionPolicy -List|Where-Object{$_.Scope -eq 'UserPolicy'}|Select-Object -First 1
$o.pol_user="$($up.ExecutionPolicy)"
$cs=Get-CimInstance Win32_ComputerSystem
$pr=@(Get-CimInstance Win32_Processor)
$o.cpu=($pr|Select-Object -First 1).Name
$o.cores=($pr|Measure-Object NumberOfCores -Sum).Sum
$o.ram=$cs.TotalPhysicalMemory
$o.hv=$cs.HypervisorPresent
$o.fw=($pr|Select-Object -First 1).VirtualizationFirmwareEnabled
$o.gpu=@(Get-CimInstance Win32_VideoController|ForEach-Object Name)
$o.npu=@(Get-CimInstance Win32_PnPEntity -Filter "Name like '% NPU%' or Name like 'NPU%' or Name like '%AI Boost%' or Name like '%Neural Processing%' or Name like '%IPU Device%'"|ForEach-Object Name)
$o.battery=@(Get-CimInstance Win32_Battery).Count -gt 0
$o.plan=(Get-CimInstance -Namespace root\cimv2\power -ClassName Win32_PowerPlan|Where-Object IsActive|Select-Object -First 1).ElementName
$o.disks=@(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3'|Select-Object -First 4|ForEach-Object{
  $t=$null;try{$t=(Get-Partition -DriveLetter $_.DeviceID.Substring(0,1)|Get-Disk|Get-PhysicalDisk).MediaType}catch{}
  [ordered]@{mount=$_.DeviceID;type="$t";free=$_.FreeSpace}})
$mc=Get-MpComputerStatus;$mp=Get-MpPreference
$o.rtp=$mc.RealTimeProtectionEnabled
$ex=@($mp.ExclusionPath)+@($mp.ExclusionProcess)+@($mp.ExclusionExtension)
$o.exna=@($ex|Where-Object{"$_" -like 'N/A*'}).Count -gt 0
$o.excnt=@($ex|Where-Object{$_ -and "$_" -notlike 'N/A*'}).Count
$o.av=@(Get-CimInstance -Namespace root\SecurityCenter2 -ClassName AntiVirusProduct|ForEach-Object displayName)
$dg=Get-CimInstance -Namespace root\Microsoft\Windows\DeviceGuard -ClassName Win32_DeviceGuard
$o.wdac=$dg.UsermodeCodeIntegrityPolicyEnforcementStatus
$o.appid="$((Get-Service AppIDSvc).Status)"
$al=$null;try{$al=[xml](Get-AppLockerPolicy -Effective -Xml)}catch{}
$o.applocker=@($al.AppLockerPolicy.RuleCollection|ForEach-Object EnforcementMode)
$sv=@(Get-Service)
$o.svcok=$sv.Count -gt 0
$o.epm=@($sv|Where-Object{$_.DisplayName -like 'Microsoft EPM Agent*' -or $_.Name -like 'EpmAgent*'}).Count -gt 0
$o.dlpsvc=@($sv|Where-Object{$_.DisplayName -match 'DLP|Data Loss'}).Count -gt 0
$o.sched="$((Get-Service Schedule).Status)"
$un=@(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*','HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'|ForEach-Object DisplayName)
$o.dlpapp=@($un|Where-Object{$_ -match 'DLP|Data Loss'}).Count -gt 0
$o.label=@($un|Where-Object{$_ -match 'Information Protection|Sensitivity|Purview'}).Count -gt 0
$ap=@(Get-AppxPackage)
$o.appxok=$ap.Count -gt 0
$o.outlook_new=@($ap|Where-Object{$_.Name -eq 'Microsoft.OutlookForWindows'}).Count -gt 0
$o.teams_new=@($ap|Where-Object{$_.Name -eq 'MSTeams'}).Count -gt 0
$o.docs=[Environment]::GetFolderPath('MyDocuments')
$o.task=@(Get-ScheduledTask -TaskPath '\claude-workbench\' -TaskName 'knowledge-refresh').Count -gt 0
$o|ConvertTo-Json -Depth 4 -Compress
"""
PS_SCRIPTS = {PS_MAIN}
# node -e script: exit 0 reached the host, 3 certificate/TLS error, 4 timeout, 2 anything else.
NODE_TLS = ("require('https').get({host:process.argv[1],method:'HEAD',path:'/',timeout:4000,headers:{'user-agent':'"
            + UA + "'}},r=>{r.resume();process.exit(0)}).on('error',e=>process.exit(/CERT|SSL|TLS|ISSUER/.test(e.code||'')?3:2))"
            ".on('timeout',function(){process.exit(4)})")
PIP_ARGS = ["-m", "pip", "--disable-pip-version-check", "--timeout", "4", "--retries", "0", "index", "versions", "pip"]
GIT_LS = ["-c", "credential.helper=", "ls-remote", "--exit-code"]
PUBLIC_REPO = "/octocat/Hello-World.git"   # a public sample repository used only for the git TLS runtime check
HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")
VER_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")
CLAUDE_VER_RES = (re.compile(r"(\d+\.\d+\.\d+)\s*\(Claude Code\)"), re.compile(r"Claude Code\s+v?(\d+\.\d+\.\d+)", re.I))
PS_LANGUAGE_MODES = {m.lower(): m for m in ("FullLanguage", "ConstrainedLanguage", "RestrictedLanguage", "NoLanguage")}
PS_POLICIES = {m.lower(): m for m in ("Restricted", "AllSigned", "RemoteSigned", "Unrestricted", "Bypass", "Undefined")}


def claude_ver(text):
    """The version in `claude --version` output: the token labelled Claude Code, else the first number (a banner may come first)."""
    t = (text or "")[:2000]
    for rx in CLAUDE_VER_RES + (VER_RE,):
        m = rx.search(t)
        if m:
            return m.group(1)
    return None


# ── the one subprocess wrapper ────────────────────────────────────────────────────────────────────────────────
def _stem(p):
    return os.path.splitext(os.path.basename(p))[0].lower()


def _curl_ok(a):
    if a == ["--version"]:
        return True
    flags = {"-s", "-I", "--proxy-negotiate", "--max-time", "-o", "-w", "-A", "--proxy-user"}
    vals = {"NUL", "/dev/null", "%{http_code}", ":", UA}
    return (len(a) > 1 and "--max-time" in a and a[-1].startswith("https://")
            and all(x in flags or x in vals or x.isdigit() for x in a[:-1]))


def allowed(argv, extra=()):
    """True only for the read-only commands the probe needs. `extra` = exact argv lists (find CLI, package checks)."""
    if not argv or not isinstance(argv, (list, tuple)) or any(not isinstance(x, str) for x in argv):
        return False
    argv = list(argv)
    if argv in [list(e) for e in extra]:
        return True
    exe, a = _stem(argv[0]), argv[1:]
    if exe == "whoami":
        return a == ["/groups", "/fo", "csv"]
    if exe in ("powershell", "pwsh") and len(a) == 4:
        return a[:3] == ["-NoProfile", "-NonInteractive", "-Command"] and a[3] in PS_SCRIPTS
    if exe == "reg":
        return (len(a) in (2, 4) and a[0] == "query" and a[1].upper().startswith("HK")
                and (len(a) == 2 or (a[2] == "/v" and a[3] != "")))
    if exe == "winget":
        return a in (["--info"], ["--version"])
    if exe == "wsl":
        return a in (["--status"], ["--version"], ["-l", "-v"])
    if exe == "netsh":
        return a == ["winhttp", "show", "proxy"]
    if exe == "dsregcmd":
        return a == ["/status"]
    if exe == "claude" and a == ["doctor"]:
        return True
    if exe == "curl":
        return _curl_ok(a)
    if exe == "node" and a[:1] == ["-e"] and len(a) == 3:
        return a[1] == NODE_TLS and bool(HOST_RE.match(a[2]))
    if exe in ("py", "python", "python3"):
        return a == PIP_ARGS or a == ["-3"] + PIP_ARGS or (len(a) == 2 and re.fullmatch(r"-\d(\.\d+)?", a[0])
                                                          and a[1] == "--version") or a == ["--version"]
    if exe == "git" and a[:4] == GIT_LS and len(a) == 6:
        return a[4].startswith("https://") and a[5] == "HEAD"
    return a == ["--version"] and bool(re.fullmatch(r"[\w.+-]+", exe))   # <tool> --version


_SCRATCH = []


def scratch():
    """One temp folder for the state/cache files child tools like to write on first run; removed when the probe exits."""
    if not _SCRATCH:
        _SCRATCH.append(tempfile.mkdtemp(prefix="wb-probe-"))
        atexit.register(shutil.rmtree, _SCRATCH[0], True)
    return _SCRATCH[0]


SYS_TOOLS = ("whoami", "reg", "netsh", "dsregcmd", "wsl", "curl", "fsutil")


def resolve(name):
    """Windows system tools come from System32 (a Git-for-Windows `whoami` on PATH is a different program)."""
    stem = _stem(name)
    if IS_WIN and (stem in SYS_TOOLS or stem == "powershell"):
        root = os.environ.get("SystemRoot", r"C:\Windows")
        p = os.path.join(root, "System32", *(["WindowsPowerShell", "v1.0"] if stem == "powershell" else []), stem + ".exe")
        if os.path.isfile(p):
            return p
    return shutil.which(name)


def run(argv, timeout=15, extra=(), env=None):
    """The probe's only child-process call. -> (exit code, combined output bytes); exit code None = not found, timed
    out or could not start. Raises ValueError for any command outside the allowlist."""
    if not allowed(argv, extra):
        raise ValueError("command not allowed: " + " ".join(str(x) for x in list(argv)[:3]))
    exe = resolve(argv[0])
    if not exe:
        return None, b""
    e = dict(os.environ, PIP_NO_CACHE_DIR="1", PIP_DISABLE_PIP_VERSION_CHECK="1", GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never",
             NODE_DISABLE_COMPILE_CACHE="1", npm_config_update_notifier="false", GH_NO_UPDATE_NOTIFIER="1", DO_NOT_TRACK="1",
             POWERSHELL_TELEMETRY_OPTOUT="1", POWERSHELL_UPDATECHECK="Off", XDG_STATE_HOME=scratch(), XDG_CACHE_HOME=scratch())
    if _stem(argv[0]) in ("powershell", "pwsh"):
        e["USERPROFILE"] = e["LOCALAPPDATA"] = scratch()   # PowerShell keeps start-up profile data there; keep it out of the user's profile
    e.update(env or {})
    try:
        p = subprocess.run([exe] + list(argv[1:]), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, timeout=timeout, creationflags=NO_WINDOW, env=e)
    except (OSError, subprocess.SubprocessError):
        return None, b""
    return p.returncode, p.stdout


def txt(b, enc="utf-8"):
    s = (b or b"").decode(enc, "replace").replace("\x00", "").lstrip("\ufeff")
    return s.replace("\r\n", "\n")


# ── registry (read through `reg query`) ───────────────────────────────────────────────────────────────────────
_REG_LINE = re.compile(r"^\s{4}(.+?)\s{4}(REG_\w+)(?:\s{4}(.*))?$")


def _reg(run_, key, name=None):
    rc, out = run_(["reg", "query", key] + (["/v", name] if name else []))
    return rc, txt(out).split("\n")


def reg_values(run_, key, name=None):
    """{value name: int | str} for one key; {} = key absent; None = reg could not run."""
    rc, lines = _reg(run_, key, name)
    if rc is None:
        return None
    vals = {}
    for ln in lines if rc == 0 else []:
        m = _REG_LINE.match(ln)
        if m:
            v = (m.group(3) or "").strip()
            vals[m.group(1)] = int(v, 16) if m.group(2) in ("REG_DWORD", "REG_QWORD") and v.startswith("0x") else v
    return vals


def reg_subkeys(run_, key):
    """Full key names under `key` (the first HKEY_ line of the output is the key itself)."""
    rc, lines = _reg(run_, key)
    heads = [ln.strip() for ln in lines if rc == 0 and ln.upper().startswith("HKEY_")]
    return heads[1:]


# ── network ───────────────────────────────────────────────────────────────────────────────────────────────────
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):   # a 3xx is an answer; never follow it to a host that is not on the list
        return None


def classify(e):
    """exception -> (result, category, http status)"""
    if isinstance(e, urllib.error.HTTPError):
        return ("proxy-auth", "proxy-denied", 407) if e.code == 407 else ("ok", None, e.code)
    r = e.reason if isinstance(e, urllib.error.URLError) else e
    if isinstance(r, socket.gaierror):
        return "blocked", "dns", None
    if isinstance(r, (socket.timeout, TimeoutError)):
        return "blocked", "timeout", None
    if isinstance(r, ssl.SSLError):
        return "blocked", "tls", None
    if isinstance(r, OSError):
        m = re.search(r"Tunnel connection failed: (\d{3})", str(r))
        if m:
            return ("proxy-auth", "proxy-denied", 407) if m.group(1) == "407" else ("blocked", "proxy-denied", int(m.group(1)))
        return "blocked", "connect", None
    return "error", "http", None


def fetch(url, opener=None, timeout=HTTP_TIMEOUT):
    """HEAD (then, if HEAD is refused, a GET of at most 64 KB held in memory). -> endpoint fields."""
    opener = opener or urllib.request.build_opener(_NoRedirect)
    out = {"method": "HEAD", "result": "ok", "category": None, "http_status": None, "bytes": 0}
    t0 = time.monotonic()

    def go(method):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
        try:
            with opener.open(req, timeout=timeout) as r:
                return r.status, len(r.read(65536)) if method == "GET" else 0
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, 0
    try:
        status, n = go("HEAD")
        if status in (405, 501):
            out["method"] = "GET"
            status, n = go("GET")
        out["http_status"], out["bytes"] = status, n
        if status == 407:
            out["result"], out["category"] = "proxy-auth", "proxy-denied"
    except Exception as e:   # noqa: BLE001: every failure is data, never a crash
        out["result"], out["category"], out["http_status"] = classify(e)
    out["ms"] = int((time.monotonic() - t0) * 1000)
    return out


def _handshake(host, ctx, timeout):
    try:
        with socket.create_connection((host, 443), timeout=timeout) as s, ctx.wrap_socket(s, server_hostname=host) as t:
            return True, t.getpeercert()
    except (OSError, ValueError):
        return False, None


def tls_probe(host, bundle_ctx=None, timeout=HTTP_TIMEOUT):
    """Does the certificate chain validate against the system store, and against the Mozilla bundle?"""
    r = {"host": host, "issuer_o": None, "issuer_cn": None, "system_ok": False, "bundle_ok": None, "inspected": "unknown"}
    ok, cert = _handshake(host, ssl.create_default_context(), timeout)
    r["system_ok"] = ok
    for rdn in (cert or {}).get("issuer", ()):
        for k, v in rdn:
            if k == "organizationName":
                r["issuer_o"] = v
            elif k == "commonName":
                r["issuer_cn"] = v
    if bundle_ctx is not None and ok:
        r["bundle_ok"] = _handshake(host, bundle_ctx, timeout)[0]
    if ok and r["bundle_ok"] is not None:
        r["inspected"] = "no" if r["bundle_ok"] else "yes"   # trusted by the store but not by the public bundle
    return r


def bundle_context():
    try:
        from pip._vendor import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:   # noqa: BLE001
        return None


def model_endpoint(env):
    """(provider, URL of the model API host) from the environment the CLI itself reads."""
    def on(k):
        return str(env.get(k, "")).lower() in ("1", "true", "yes")
    if on("CLAUDE_CODE_USE_BEDROCK"):
        return "bedrock", "https://bedrock-runtime.%s.amazonaws.com/" % (
            env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "us-east-1")
    if on("CLAUDE_CODE_USE_VERTEX"):
        r = env.get("CLOUD_ML_REGION") or "us-east5"
        return "vertex", "https://aiplatform.googleapis.com/" if r == "global" else "https://%s-aiplatform.googleapis.com/" % r
    if on("CLAUDE_CODE_USE_FOUNDRY"):
        res = env.get("ANTHROPIC_FOUNDRY_RESOURCE")
        return "foundry", env.get("ANTHROPIC_FOUNDRY_BASE_URL") or (f"https://{res}.services.ai.azure.com/" if res else None)
    base = env.get("ANTHROPIC_BASE_URL")
    if base and "api.anthropic.com" not in base:
        return "gateway", base
    return "anthropic", "https://api.anthropic.com/"


def host_of(url):
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/:?#]+)", url or "", re.I)
    return m.group(1).lower() if m else None


def skeleton(name):
    wsl = {"installed": False, "version": None, "distros": []}
    s = {
        "os": {"system": None, "platform": None, "arch": None, "build": None, "edition": None, "display_version": None},
        "hardware": {"cpu": None, "cores": None, "ram_gb": None, "gpu": [], "npu": [], "disks": [], "battery": None,
                     "power_plan": None},
        "management": {"aad_joined": None, "domain_joined": None, "workplace_joined": None, "mdm_enrolled": None},
        "identity": {"admin_capable": None, "elevated_now": None, "epm_present": None, "method": "whoami-groups"},
        "app_control": {"wdac": "unknown", "applocker": "unknown",
                        "powershell": {"language_mode": "unknown", "execution_policy": "unknown", "gpo_machine": "unknown",
                                       "gpo_user": "unknown"}},
        "policies": {"managed_claude": {"present": False, "sources": [], "keys": [], "hooks_managed_only": None,
                                        "disable_all_hooks": None, "mcp_allow": None, "mcp_deny": [],
                                        "mcp_managed_only": None, "marketplaces_strict": False, "models_allow": None,
                                        "models_deny": []},
                     "wsl": {}, "winget": {}, "store": {}, "package_keys": {}},
        "security": {"defender_realtime": None, "defender_exclusions": "unknown", "dlp_agent": "unknown",
                     "label_client": "unknown", "av_products": []},
        "tools": {t: {"found": False, "works": False, "version": None, "path": None} for t in
                  TOOLS + ("python313", "edge")} | {"packages": {}},
        "virtualization": {"hypervisor_present": None, "firmware_virtualization": None, "virt_ok": None, "wsl": wsl},
        "network": {"user_agent": UA, "budget_s": NET_BUDGET_S, "endpoints": [],
                    "proxy": {"enabled": None, "pac": None, "server": None, "env": [], "winhttp": None}},
        "tls": {"hosts": [], "runtimes": []},
        "claude": {"version": None, "logged_in": None, "plugins_installed": [],
                   "doctor": {"server_managed": None, "org_policy": None, "parsed": False}},
        "models": {"provider": "anthropic", "available": "unverified", "denied": [], "match": None, "enforce": False,
                   "sources": []},
        "github": {"hosts": []},
        "knowledge": {"libraries": [], "find": {"available": False, "mode": None, "vectors": None}, "verify": None,
                      "refresh_task": None, "schedule_service": None,
                      "work_cloud": {"found": False, "root": None, "kfm": None, "accounts": 0}},
        "capture": {"edge_path": None, "edge_version": None, "automation_allowed": None, "headless_allowed": None,
                    "policy_keys": {"RemoteDebuggingAllowed": None, "HeadlessModeEnabled": None},
                    "outlook_client": "unknown", "teams_client": "unknown", "app_installed": False,
                    "outlook_cache_window": None, "outlook_object_model_policy": {}},
    }
    return s[name]


def parse_doctor(text):
    """`claude doctor` output is ASSUMED to be 'label: value' lines; "not fetched" means unknown. parsed = a label was found."""
    def look(pat):
        for ln in text.lower().split("\n"):
            if re.search(pat, ln):
                val = ln.split(":", 1)[-1]
                if re.search(r"not fetched|unknown", val):
                    return None, True
                if re.search(r"\b(yes|true|active|enabled|found|present|applied|fetched|on)\b", val) and not re.search(r"\bnot\b", val):
                    return True, True
                if re.search(r"\b(no|none|false|inactive|disabled|not|off)\b", val):
                    return False, True
                return None, True
        return None, False
    sm, f1 = look(r"managed settings|server[- ]managed")
    org, f2 = look(r"organi[sz]ation polic")
    return {"server_managed": sm, "org_policy": org, "parsed": f1 or f2}


def find_cli(kit, environ):
    s = environ.get("WORKBENCH_FIND_CLI")
    if s:
        return json.loads(s) if s.lstrip().startswith("[") else [x.strip('"') for x in shlex.split(s, posix=not IS_WIN)]
    p = os.path.join(kit, "plugins", "workbench-core", "skills", "find", "scripts", "doc_index.py")
    return [sys.executable, p] if os.path.isfile(p) else None


def detect_platform():
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    try:
        with open("/proc/version", encoding="utf-8") as f:
            if "microsoft" in f.read().lower():
                return "wsl"
    except OSError:
        pass
    return "linux"


# ── the probe ─────────────────────────────────────────────────────────────────────────────────────────────────
class Probe:
    def __init__(self, kit=None, packages=None, git_hosts=(), extras=(), network=True, quick=False, run_=run,
                 fetch_=fetch, tls_=tls_probe, environ=None, managed_files=None, clock=time.monotonic, which_=resolve,
                 doctor=False):
        self.environ = dict(os.environ if environ is None else environ)
        self.kit = kit or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.git_hosts, self.extras, self.network, self.quick = list(git_hosts), list(extras), network, quick
        self.fetch, self.tls, self.clock = fetch_, tls_, clock
        self.platform = detect_platform()
        self.ch = self.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
        self.wb = os.path.join(self.ch, "workbench")
        self.pkgs, self.pkg_notes = self._load_packages(packages)
        self.find = find_cli(self.kit, self.environ)
        self.extra = [self.find + ["discover", "--json"], self.find + ["status", "--json"]] if self.find else []
        self.extra += [p["verify"] for p in self.pkgs if isinstance(p.get("verify"), list)
                       and len(p["verify"]) in (2, 3) and p["verify"][-1] == "--version"]
        self._run, self.which, self.doctor = run_, which_, doctor
        self.managed_files = managed_files
        self._c = {}
        self.deadline = None

    # helpers --------------------------------------------------------------------------------------------------
    def run(self, argv, timeout=15):
        if not allowed(argv, self.extra):
            raise ValueError("command not allowed: " + " ".join(argv[:3]))
        return self._run(argv, timeout)

    def once(self, key, fn):
        if key not in self._c:
            self._c[key] = fn()
        return self._c[key]

    def _load_packages(self, path):
        path = path or os.path.join(self.kit, "bootstrap", "packages.json")
        self.endpoint_hosts = []
        try:
            with open(path, encoding="utf-8-sig") as f:
                doc = json.load(f)
            pk = doc.get("packages") or []
            # hosts that are not a package's download but a feature's (the embedding model): probed like any package host
            self.endpoint_hosts = [e["host"] for e in doc.get("endpoints") or [] if isinstance(e, dict) and isinstance(e.get("host"), str)]
            return [p for p in pk if isinstance(p, dict) and p.get("id")], []
        except (OSError, ValueError) as e:
            return [], ["package table not read (%s)" % type(e).__name__]

    def left(self):
        return 0 if self.deadline is None else max(0.0, self.deadline - self.clock())

    def ps(self):
        def go():
            if not IS_WIN:
                return {}
            rc, out = self.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_MAIN], 40)
            try:
                v = json.loads(txt(out)) if rc == 0 else {}
                return v if isinstance(v, dict) else {}
            except ValueError:
                return {}
        return self.once("ps", go)

    def managed(self):
        """merged managed settings dict + source labels (files, then HKLM/HKCU policy key)."""
        def go():
            files, srcs, merged = [], [], {}
            if self.managed_files is not None:
                files = list(self.managed_files)
            else:
                pf = self.environ.get("ProgramFiles", r"C:\Program Files")
                base = ([os.path.join(pf, "ClaudeCode")] if IS_WIN else
                        ["/Library/Application Support/ClaudeCode"] if sys.platform == "darwin" else
                        ["/etc/claude-code", "/mnt/c/Program Files/ClaudeCode"])
                for b in base:
                    files.append(os.path.join(b, "managed-settings.json"))
                    d = os.path.join(b, "managed-settings.d")
                    if os.path.isdir(d):
                        files += sorted(os.path.join(d, n) for n in os.listdir(d) if n.endswith(".json"))
                files += [x for x in (self.environ.get("WORKBENCH_MANAGED_SETTINGS") or "").split(os.pathsep) if x]
            docs = []
            for f in files:
                if os.path.isfile(f):
                    try:
                        with open(f, encoding="utf-8-sig") as fh:
                            docs.append(("file", json.load(fh)))
                    except (OSError, ValueError):
                        docs.append(("file (unreadable, treated as present)", {}))
            if IS_WIN or self.managed_files is None:
                for hive in ("HKLM", "HKCU"):
                    v = reg_values(self.run, hive + r"\SOFTWARE\Policies\ClaudeCode")
                    if v and v.get("Settings"):
                        try:
                            docs.append(("registry " + hive, json.loads(v["Settings"])))
                        except ValueError:
                            docs.append(("registry " + hive + " (unreadable, treated as present)", {}))
            for label, doc in docs:
                srcs.append(label)
                if isinstance(doc, dict):
                    for k, val in doc.items():
                        if isinstance(val, list) and isinstance(merged.get(k), list):
                            merged[k] = merged[k] + [x for x in val if x not in merged[k]]
                        elif isinstance(val, dict) and isinstance(merged.get(k), dict):
                            merged[k].update(val)
                        else:
                            merged[k] = val
            return merged, srcs
        return self.once("managed", go)

    def env(self):
        env = dict(self.environ)
        env.update({k: str(v) for k, v in (self.managed()[0].get("env") or {}).items()})
        return env

    def model_api(self):
        return self.once("model_api", lambda: model_endpoint(self.env()))

    # sections: fill d (a copy of the skeleton), return (status, notes) ----------------------------------------
    def s_os(self, d, notes):
        d.update(system=platform.system(), platform=self.platform, arch=platform.machine())
        if IS_WIN:
            d["build"] = platform.version()
            v = reg_values(self.run, r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion") or {}
            d["edition"], d["display_version"] = v.get("EditionID"), v.get("DisplayVersion")
            return "ok" if d["edition"] else "partial"
        d["build"] = platform.release()
        return "ok"

    def s_hardware(self, d, notes):
        p = self.ps()
        if p:
            d.update(cpu=p.get("cpu"), cores=p.get("cores"), gpu=p.get("gpu") or [], npu=p.get("npu") or [],
                     battery=p.get("battery"), power_plan=p.get("plan"))
            if p.get("ram"):
                d["ram_gb"] = round(float(p["ram"]) / 2 ** 30, 1)
            d["disks"] = [{"mount": x.get("mount"), "type": {"SSD": "ssd", "HDD": "hdd"}.get(x.get("type"), "unknown"),
                           "free_gb": round(float(x.get("free") or 0) / 2 ** 30, 1)}
                          for x in (p.get("disks") or []) if isinstance(x, dict)]
            return "ok" if d["cpu"] else "partial"
        d["cpu"], d["cores"] = platform.processor() or platform.machine(), os.cpu_count()
        try:
            du = shutil.disk_usage(os.path.expanduser("~"))
            d["disks"] = [{"mount": "~", "type": "unknown", "free_gb": round(du.free / 2 ** 30, 1)}]
            with open("/proc/meminfo", encoding="utf-8") as f:
                d["ram_gb"] = round(int(re.search(r"MemTotal:\s+(\d+)", f.read()).group(1)) / 2 ** 20, 1)
        except (OSError, AttributeError):
            pass
        if not IS_WIN:
            return "partial"
        notes.append("PowerShell data unavailable")
        return "unavailable"

    def s_management(self, d, notes):
        if not IS_WIN:
            return "n/a"
        rc, out = self.run(["dsregcmd", "/status"])
        if rc is None:
            return "unavailable"
        kv = {}
        for ln in txt(out).split("\n"):
            m = re.match(r"^\s*([A-Za-z]+)\s*:\s*(.*?)\s*$", ln)
            if m:
                kv.setdefault(m.group(1), m.group(2))
        yes = lambda k: None if k not in kv else kv[k].upper() == "YES"   # noqa: E731
        d.update(aad_joined=yes("AzureAdJoined"), domain_joined=yes("DomainJoined"), workplace_joined=yes("WorkplaceJoined"),
                 mdm_enrolled=bool(kv.get("MdmUrl")) if kv else None)
        return "ok" if kv else "partial"

    def s_identity(self, d, notes):
        if not IS_WIN:
            d.update(admin_capable=hasattr(os, "geteuid") and os.geteuid() == 0, elevated_now=hasattr(os, "geteuid") and os.geteuid() == 0,
                     epm_present=False, method="euid")
            return "partial"
        d["epm_present"] = self.ps().get("epm")
        rc, out = self.run(["whoami", "/groups", "/fo", "csv"])
        if rc != 0:
            return "partial" if d["epm_present"] is not None else "unavailable"
        sids = {r[2] for r in csv.reader(io.StringIO(txt(out))) if len(r) >= 3}
        d["admin_capable"], d["elevated_now"] = "S-1-5-32-544" in sids, "S-1-16-12288" in sids
        return "ok"

    def s_app_control(self, d, notes):
        p = self.ps()
        if not p:
            return "unavailable" if IS_WIN else "n/a"
        w = p.get("wdac")
        d["wdac"] = {2: "enforced", 1: "audit", 0: "off"}.get(w, "unknown")
        modes = [str(m).lower() for m in (p.get("applocker") or [])]
        d["applocker"] = ("enforced" if "enabled" in modes else "audit" if "auditonly" in modes else
                          "none" if modes else "unknown")
        # what the probe's own PowerShell session sees, which is the session Claude Code's PowerShell tool gets too
        pol = lambda v: PS_POLICIES.get(str(v or "").strip().lower(), "unknown")   # noqa: E731
        d["powershell"] = {"language_mode": PS_LANGUAGE_MODES.get(str(p.get("lang") or "").strip().lower(), "unknown"),
                           "execution_policy": pol(p.get("execpol")), "gpo_machine": pol(p.get("pol_machine")),
                           "gpo_user": pol(p.get("pol_user"))}
        return "ok"

    def s_policies(self, d, notes):
        merged, srcs = self.managed()
        m = d["managed_claude"]
        names = lambda v: [x if isinstance(x, str) else (x.get("serverName") or x.get("serverUrl") or x.get("serverCommand") or "")   # noqa: E731
                           for x in v] if isinstance(v, list) else None
        m.update(present=bool(srcs), sources=srcs, keys=sorted(merged), hooks_managed_only=merged.get("allowManagedHooksOnly"),
                 disable_all_hooks=merged.get("disableAllHooks"), mcp_allow=names(merged.get("allowedMcpServers")),
                 mcp_deny=names(merged.get("deniedMcpServers")) or [], mcp_managed_only=merged.get("allowManagedMcpServersOnly"),
                 marketplaces_strict="strictKnownMarketplaces" in merged,
                 models_allow=merged.get("availableModels") if isinstance(merged.get("availableModels"), list) else None,
                 models_deny=merged.get("deniedModels") if isinstance(merged.get("deniedModels"), list) else [])
        if not IS_WIN:
            return "partial"
        any_ran = False
        for name, keys in (("wsl", (r"HKLM\SOFTWARE\Policies\WSL", r"HKLM\SOFTWARE\Policies\Microsoft\WSL")),
                           ("winget", (r"HKLM\SOFTWARE\Policies\Microsoft\Windows\AppInstaller",)),
                           ("store", (r"HKLM\SOFTWARE\Policies\Microsoft\WindowsStore",))):
            for k in keys:
                v = reg_values(self.run, k)
                any_ran |= v is not None
                d[name].update(v or {})
        for pk in self.pkgs:
            for k in pk.get("policy_keys") or []:
                if isinstance(k, str) and k.upper().startswith("HK") and k not in d["package_keys"]:
                    d["package_keys"][k] = reg_values(self.run, k)
        return "ok" if any_ran else "unavailable"

    def s_security(self, d, notes):
        p = self.ps()
        if not p:
            return "unavailable" if IS_WIN else "n/a"
        d["defender_realtime"] = p.get("rtp")
        d["defender_exclusions"] = ("unknown" if p.get("exna") or p.get("rtp") is None else
                                    "present" if p.get("excnt") else "none")
        d["dlp_agent"] = "present" if p.get("dlpsvc") or p.get("dlpapp") else "none" if p.get("svcok") else "unknown"
        d["label_client"] = "present" if p.get("label") else "none" if p.get("svcok") else "unknown"
        d["av_products"] = [x for x in (p.get("av") or []) if isinstance(x, str)]
        return "ok"

    def version_of(self, argv, rx=VER_RE):
        rc, out = self.run(argv)
        m = rx.search(txt(out)) if rc == 0 else None
        return rc, (m.group(1) if m else None)

    def s_tools(self, d, notes):
        for t in TOOLS:
            exe = "curl.exe" if t == "curl" and IS_WIN else t
            path = self.which(exe)
            e = d[t]
            if t == "wsl":
                continue   # filled from the virtualization checks below
            if t == "bwrap" and self.platform not in ("linux", "wsl"):
                continue
            e["found"], e["path"] = bool(path), path
            if path:
                if t == "claude":   # same parse as s_claude: a banner line must not be read as the version
                    rc, out = self.run([exe, "--version"])
                    v = claude_ver(txt(out)) if rc == 0 else None
                else:
                    rc, v = self.version_of([exe, "--version"])
                e["works"], e["version"] = rc == 0 and v is not None, v
        v = self.wsl()
        d["wsl"].update(found=bool(self.which("wsl")), path=self.which("wsl"), works=v["installed"], version=v["version"])
        if IS_WIN:
            ver = self.accepted_python()
            d["python313"].update(found=ver is not None, works=ver is not None, version=ver, path=self.which("py"))
        c = self.capture_facts()
        d["edge"].update(found=bool(c["edge_path"]), works=bool(c["edge_version"]), version=c["edge_version"], path=c["edge_path"])
        for p in self.pkgs:
            e = d["packages"][p["id"]] = {"found": False, "works": False, "version": None, "path": None}
            v = p.get("verify")
            if isinstance(v, list) and v and isinstance(v[0], str):
                e["path"] = self.which(v[0])
                e["found"] = bool(e["path"])
                if e["found"] and v in self.extra:
                    rc, out = self.run(v)
                    if _stem(v[0]) == "claude":   # same parse as s_claude
                        ver = claude_ver(txt(out)) if rc == 0 else None
                        e["works"], e["version"] = ver is not None, ver
                        continue
                    try:
                        m = re.search(p.get("expect") or VER_RE.pattern, txt(out))
                    except re.error:
                        m = None
                    e["works"], e["version"] = rc == 0 and m is not None, (m.group(1) if m and m.groups() else None)
            if p.get("accept") and IS_WIN and not e["works"]:      # Python: any version the kit accepts is present
                ver = self.accepted_python()
                if ver:
                    e.update(found=True, works=True, version=ver)
        return "ok"

    def accepted_python(self):
        """The version of the first Python the knowledge venv accepts (packages.json python313 "accept"), else None."""
        acc = next((p["accept"] for p in self.pkgs if p.get("id") == "python313" and p.get("accept")), None) or ["3.13"]
        for v in acc:
            rc, ver = self.version_of(["py", "-" + v, "--version"], re.compile(r"(\d+\.\d+\.\d+)"))
            if rc == 0 and ver and ver.startswith(v + "."):
                return ver
        return None

    def wsl(self):
        def go():
            w = {"installed": False, "version": None, "distros": []}
            if not IS_WIN:
                return w
            rc, out = self.run(["wsl", "--version"])
            m = VER_RE.search(txt(out, "utf-16-le")) if rc == 0 else None
            w["installed"], w["version"] = m is not None, (m.group(1) if m else None)
            rc2, out2 = self.run(["wsl", "-l", "-v"])
            if rc2 == 0:
                for ln in [x for x in txt(out2, "utf-16-le").split("\n") if x.strip()][1:]:
                    parts = ln.replace("*", " ").split()
                    if len(parts) >= 3 and parts[-1].isdigit():
                        w["distros"].append({"name": parts[0], "state": parts[-2], "version": int(parts[-1])})
            if not w["installed"] and self.run(["wsl", "--status"])[0] == 0 and w["distros"]:
                w["installed"] = True
            return w
        return self.once("wsl", go)

    def s_virtualization(self, d, notes):
        if not IS_WIN:
            d["wsl"]["inside_wsl"] = self.platform == "wsl"
            return "n/a"
        p = self.ps()
        hv, fw = p.get("hv"), p.get("fw")
        d.update(hypervisor_present=hv, firmware_virtualization=fw)
        d["virt_ok"] = True if hv is True else fw   # a running hypervisor makes the firmware flag read false
        d["wsl"] = self.wsl()
        return "ok" if hv is not None else "partial"

    # network --------------------------------------------------------------------------------------------------
    def plan_hosts(self):
        out = []
        for h in [h for p in self.pkgs for h in p.get("hosts") or []] + self.endpoint_hosts:
            if isinstance(h, str) and h and h not in out:
                out.append(h)
        return out

    def endpoint_specs(self):
        specs = []
        _, murl = self.model_api()
        if murl:
            specs.append(("model_api", murl))
        specs += [("git:" + h, "https://%s/" % h) for h in self.git_hosts]
        specs += [("extra:" + (host_of(u) or u), u) for u in self.extras]
        specs += [(h, h if h.startswith("http") else "https://%s/" % h) for h in self.plan_hosts()]
        seen, out = set(), []
        for n, u in specs:
            if u not in seen:
                seen.add(u)
                out.append((n, u))
        return out

    def net(self):
        def go():
            eps = []
            self.deadline = self.clock() + NET_BUDGET_S
            for name, url in self.endpoint_specs():
                e = {"name": name, "url": url, "method": "HEAD", "result": "not-tested", "category": None,
                     "http_status": None, "ms": 0, "bytes": 0, "proxy_negotiate_ok": None}
                if self.network and not self.quick:
                    if self.left() < 0.5:
                        e["category"] = "budget"
                    else:
                        e.update(self.fetch(url, timeout=min(HTTP_TIMEOUT, self.left())))
                        if e["result"] == "proxy-auth":
                            e["proxy_negotiate_ok"] = self.negotiate_retest(url)
                eps.append(e)
            return eps
        return self.once("net", go)

    def negotiate_retest(self, url):
        rc, out = self.run(["curl.exe" if IS_WIN else "curl", "--proxy-negotiate", "--proxy-user", ":", "-s", "-I", "-o",
                            os.devnull if not IS_WIN else "NUL", "-w", "%{http_code}", "--max-time", "4", "-A", UA, url], 8)
        if rc is None:
            return None
        m = re.search(r"(\d{3})\s*$", txt(out))
        return rc == 0 and m is not None and m.group(1) not in ("407", "000")

    def proxy(self):
        pr = {"enabled": None, "pac": None, "server": None, "env": sorted(k for k in self.environ
              if k.lower() in ("http_proxy", "https_proxy", "all_proxy") and self.environ[k]), "winhttp": None}
        if IS_WIN:
            v = reg_values(self.run, r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings")
            if v is not None:
                pr.update(enabled=v.get("ProxyEnable") == 1, pac=bool(v.get("AutoConfigURL")), server=v.get("ProxyServer") or None)
            rc, out = self.run(["netsh", "winhttp", "show", "proxy"])   # informational only: the text is not parsed
            pr["winhttp"] = txt(out).strip().split("\n")[0][:120] if rc == 0 else None
        return pr

    def s_network(self, d, notes):
        d["proxy"] = self.proxy()
        d["endpoints"] = self.net()
        if not self.network or self.quick:
            notes.append("network checks skipped")
            return "partial"
        res = [e["result"] for e in d["endpoints"]]
        if "not-tested" in res:
            notes.append("network budget used up: some endpoints not tested")
        return "ok" if res and all(r == "ok" for r in res) else "partial" if "ok" in res else "unavailable"

    def s_tls(self, d, notes):
        if not self.network or self.quick:
            notes.append("TLS checks skipped")
            return "partial"
        eps = self.net()
        hosts = []
        for e in eps:
            h = host_of(e["url"])
            if h and h not in hosts and e["result"] in ("ok", "proxy-auth"):
                hosts.append(h)
        bundle = bundle_context()
        if bundle is None:
            notes.append("no public certificate bundle found: inspection check limited")
        for h in hosts[:8]:
            if self.left() < 1:
                notes.append("TLS host checks cut short by the budget")
                break
            d["hosts"].append(self.tls(h, bundle, min(HTTP_TIMEOUT, self.left())))
        plan = [host_of(e["url"]) for e in eps if e["name"] not in ("model_api",) and not e["name"].startswith(("extra:", "git:"))]
        plan = [h for h in plan if h]
        if not plan:
            notes.append("no plan host to test the runtimes against")
            return "partial"
        h0 = plan[0]
        gh = next((h for h in plan if h == "github.com"), None)
        t = self.tools_cached()
        checks = [("python", lambda: self.rt_python(h0)), ("node", lambda: self.rt_node(h0)),
                  ("git", lambda: self.rt_git(gh)), ("pip", lambda: self.rt_pip()), ("curl", lambda: self.rt_curl(h0))]
        for name, fn in checks:
            if name in ("node", "git", "curl") and not t.get(name, {}).get("found"):
                continue
            if self.left() < 1:
                notes.append("runtime checks cut short by the budget")
                break
            r = fn()
            if r is not None:
                d["runtimes"].append({"runtime": name, "ok": r[0], "category": r[1]})
        return "ok"

    def tools_cached(self):
        return {n: {"found": bool(self.which("curl.exe" if n == "curl" and IS_WIN else n))} for n in ("node", "git", "curl")}

    def rt_python(self, host):
        r = self.fetch("https://%s/" % host, timeout=min(HTTP_TIMEOUT, self.left()))
        return r["result"] in ("ok", "proxy-auth"), (r["category"] if r["result"] != "ok" else None)

    def rt_node(self, host):
        rc, _ = self.run(["node", "-e", NODE_TLS, host], min(8, self.left()) or 1)
        return rc == 0, {0: None, 3: "tls", 4: "timeout"}.get(rc, "error")

    def rt_git(self, host):
        if not host:
            return None
        rc, _ = self.run(["git"] + GIT_LS + ["https://%s%s" % (host, PUBLIC_REPO), "HEAD"], min(10, self.left()) or 1)
        return rc == 0, None if rc == 0 else "error"

    def rt_pip(self):
        rc, _ = self.run(["py", "-3"] + PIP_ARGS if IS_WIN else ["python3"] + PIP_ARGS, min(12, self.left()) or 1)
        return rc == 0, None if rc == 0 else "error"

    def rt_curl(self, host):
        rc, _ = self.run(["curl.exe" if IS_WIN else "curl", "-s", "-I", "-o", "NUL" if IS_WIN else "/dev/null", "-w", "%{http_code}",
                          "--max-time", "4", "-A", UA, "https://%s/" % host], 8)
        return rc == 0, {0: None, 6: "dns", 7: "connect", 28: "timeout"}.get(rc, "tls" if rc in (35, 51, 58, 60, 77) else "error")

    # claude, models, github, knowledge, capture ---------------------------------------------------------------
    def s_claude(self, d, notes):
        exe = self.which("claude")
        if not exe:
            notes.append("claude not found on PATH")
            return "unavailable"
        rc, out = self.run(["claude", "--version"])
        d["version"] = claude_ver(txt(out)) if rc == 0 else None
        env = self.env()
        d["logged_in"] = (True if env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN") or self.model_api()[0] != "anthropic"
                          or os.path.isfile(os.path.join(self.ch, ".credentials.json")) else None if sys.platform == "darwin" else False)
        if not self.doctor:   # `claude doctor` rewrites the CLI's own config files, so it runs only on request
            notes.append("claude doctor not run (--with-doctor): it updates the CLI's own config files")
        elif rc == 0 and not self.quick:
            rc2, out = self.run(["claude", "doctor"], 10)
            if rc2 is not None:
                d["doctor"] = parse_doctor(txt(out))
        try:
            with open(os.path.join(self.ch, "plugins", "installed_plugins.json"), encoding="utf-8-sig") as f:
                j = json.load(f)
            d["plugins_installed"] = sorted(j.get("plugins", j) if isinstance(j.get("plugins", j), dict) else [])
        except (OSError, ValueError, AttributeError):
            pass
        return "ok" if rc == 0 else "partial"

    def s_models(self, d, notes):
        m = self.managed()[0]
        prov = self.model_api()[0]
        allow, deny = m.get("availableModels"), m.get("deniedModels")
        d.update(provider=prov, available=[str(x) for x in allow] if isinstance(allow, list) and allow else "unverified",
                 denied=[str(x) for x in deny] if isinstance(deny, list) else [],
                 enforce=bool(allow or deny), sources=self.managed()[1])
        d["match"] = "prefix" if d["enforce"] else None   # ASSUMED: list entries match by prefix
        return "ok"

    def s_github(self, d, notes):
        eps = {host_of(e["url"]): e for e in self.net()}
        hosts = []
        for h in list(dict.fromkeys(["github.com"] + self.git_hosts)):
            kind = "github.com" if h == "github.com" else "ghe.com" if h.endswith(".ghe.com") else "ghes"
            e = eps.get(h)
            hosts.append({"host": h, "kind": kind, "result": e["result"] if e else "not-tested"})
        d["hosts"] = hosts
        return "ok"

    def knowledge_verify(self, notes):
        """IK2, read-only: the summary of <WB>/state/knowledge-verify.json ({pass, warn, fail, failing} plus `generated`),
        None when the Day-1 check has not run yet or the file is not understood."""
        path = os.path.join(self.wb, "state", "knowledge-verify.json")
        try:
            with open(path, encoding="utf-8-sig") as f:
                j = json.load(f)
            s = j["summary"]
            steps = {str(r["id"])[:8]: str(r.get("status"))[:16] for r in j.get("steps") or [] if isinstance(r, dict) and r.get("id")}
            tools = {}      # D18 records each optional tool's own status (ctx and tokensave are rated apart)
            for r in j.get("steps") or []:
                if isinstance(r, dict) and r.get("id") == "D18" and isinstance(r.get("tools"), dict):
                    tools = {str(k)[:32]: str(v)[:16] for k, v in list(r["tools"].items())[:8]}
            return {"pass": int(s["pass"]), "warn": int(s["warn"]), "fail": int(s["fail"]),
                    "failing": [str(x) for x in s.get("failing") or []][:20], "generated": str(j.get("generated") or "")[:40],
                    "steps": dict(list(steps.items())[:40]), "tools": tools}
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            notes.append("knowledge-verify.json not understood")
            return None

    def s_knowledge(self, d, notes):
        d["verify"] = self.knowledge_verify(notes)
        p = self.ps()
        d["refresh_task"] = p.get("task") if p else None
        d["schedule_service"] = p.get("sched") or None if p else None
        if self.find and not self.quick:
            rc, out = self.run(self.find + ["discover", "--json"], 20)
            try:
                d["libraries"] = json.loads(txt(out)).get("libraries", []) if rc == 0 else []
            except (ValueError, AttributeError):
                notes.append("find: discover output not understood")
            rc, out = self.run(self.find + ["status", "--json"], 20)
            try:
                st = json.loads(txt(out)) if rc == 0 else None
                if isinstance(st, dict):
                    d["find"] = {"available": True, "mode": st.get("mode"), "vectors": st.get("vectors")}
            except ValueError:
                notes.append("find: status output not understood")
        elif not self.find:
            notes.append("find CLI not installed yet")
        if IS_WIN:
            d["work_cloud"] = self.work_cloud()
            if d["work_cloud"]["accounts"] > 1:
                notes.append("several work accounts: setup will ask")
        return "ok" if p or not IS_WIN else "partial"

    def work_cloud(self):
        """Work-cloud sync accounts: every Business<N> subkey with a UserFolder (a Personal account never counts)."""
        wc = {"found": False, "root": None, "kfm": None, "accounts": 0}
        roots = []
        for k in reg_subkeys(self.run, r"HKCU\Software\Microsoft\OneDrive\Accounts"):
            if k.rsplit("\\", 1)[-1].lower().startswith("business"):
                uf = (reg_values(self.run, k, "UserFolder") or {}).get("UserFolder")
                if uf and uf not in roots:
                    roots.append(uf)
        wc["accounts"], wc["found"] = len(roots), bool(roots)
        wc["root"] = roots[0] if len(roots) == 1 else None
        docs = self.ps().get("docs")
        if roots and docs:
            norm = lambda x: os.path.normcase(os.path.normpath(os.path.expandvars(x)))   # noqa: E731
            wc["kfm"] = any(norm(docs) == norm(r) or norm(docs).startswith(norm(r) + os.sep) for r in roots)
        return wc

    def capture_facts(self):
        def go():
            c = skeleton("capture")
            if not IS_WIN:
                return c
            ap = reg_values(self.run, r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe") or {}
            path = (ap.get("(Default)") or "").strip('"') or self.which("msedge")
            c["edge_path"] = path or None
            bl = reg_values(self.run, r"HKCU\Software\Microsoft\Edge\BLBeacon", "version") or {}
            c["edge_version"] = bl.get("version") or None
            ran, keys = False, c["policy_keys"]
            for hive in ("HKLM", "HKCU"):
                v = reg_values(self.run, hive + r"\SOFTWARE\Policies\Microsoft\Edge")
                if v is None:
                    continue
                ran = True
                for k in keys:
                    if isinstance(v.get(k), int):
                        keys[k] = v[k] if keys[k] is None else min(keys[k], v[k])   # 0 (off) wins over any other value
            if ran:
                c["automation_allowed"], c["headless_allowed"] = keys["RemoteDebuggingAllowed"] != 0, keys["HeadlessModeEnabled"] != 0
            return c
        return self.once("capture", go)

    def s_capture(self, d, notes):
        d.update(self.capture_facts())
        if not IS_WIN:
            return "n/a"
        p = self.ps()
        classic = (reg_values(self.run, r"HKCR\Outlook.Application") not in (None, {})
                   or reg_values(self.run, r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE") not in (None, {}))
        if p.get("appxok"):
            new = bool(p.get("outlook_new"))
            d["outlook_client"] = "both" if classic and new else "classic" if classic else "new" if new else "none"
            lad = self.environ.get("LOCALAPPDATA") or ""
            classic_t = bool(lad) and os.path.isfile(os.path.join(lad, "Microsoft", "Teams", "Update.exe"))
            d["teams_client"] = "new" if p.get("teams_new") else "classic" if classic_t else "none"
        d["app_installed"] = os.path.isdir(os.path.join(self.wb, "capture", "app"))
        d["outlook_cache_window"] = self.cache_window()
        for hive in ("HKLM", "HKCU"):   # read-only; a later hive's value wins
            d["outlook_object_model_policy"].update(
                reg_values(self.run, hive + r"\SOFTWARE\Policies\Microsoft\Office\16.0\Outlook\Security") or {})
        return "ok" if p else "partial"

    def cache_window(self):
        """Classic Outlook cached-mode sync window as text (policy value first), None when not set. Format ASSUMED:
        SyncWindowSettingDays = days, else SyncWindowSetting = months (0 = everything)."""
        for key in (r"HKCU\SOFTWARE\Policies\Microsoft\Office\16.0\Outlook\Cached Mode",
                    r"HKCU\Software\Microsoft\Office\16.0\Outlook\Cached Mode"):
            v = reg_values(self.run, key) or {}
            if isinstance(v.get("SyncWindowSettingDays"), int) and v["SyncWindowSettingDays"] > 0:
                return "%d days" % v["SyncWindowSettingDays"]
            if isinstance(v.get("SyncWindowSetting"), int):
                n = v["SyncWindowSetting"]
                return "all mail" if n == 0 else "%d months" % n
        return None


def collect(only=None, **kw):
    """Run the probe -> the I1 document. Never raises for a failing check; a section that breaks says so."""
    t0 = time.monotonic()
    p = Probe(**kw)
    out = {}
    for name in SECTIONS:
        d, notes = skeleton(name), []
        if only and name not in only:
            out[name] = {"status": "n/a", "data": d, "notes": ["not selected"]}
            continue
        try:
            st = getattr(p, "s_" + name)(d, notes)
        except Exception as e:   # noqa: BLE001
            st = "unavailable"
            notes.append("%s: %s" % (type(e).__name__, str(e)[:160]))
        out[name] = {"status": st, "data": d, "notes": notes + (p.pkg_notes if name == "network" else [])}
    return {"version": 1, "kit_version": KIT_VERSION, "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_s": round(time.monotonic() - t0, 1), "platform": p.platform, "sections": out}


# ── output ────────────────────────────────────────────────────────────────────────────────────────────────────
def write_atomic(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def to_markdown(doc):
    lines = ["# Probe", "", "Generated %s, %ss, platform %s." % (doc["generated"], doc["duration_s"], doc["platform"]), ""]
    for name, s in doc["sections"].items():
        lines += ["## %s (%s)" % (name, s["status"])] + ["- " + n for n in s["notes"]]
        body = json.dumps(s["data"], indent=1, sort_keys=True)
        lines += ["", "```json", body if len(body) < 1500 else body[:1500] + "\n...", "```", ""]
    return "\n".join(lines)


def default_out(environ=None):
    e = os.environ if environ is None else environ
    return os.path.join(e.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"), "workbench", "state")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only capability probe.")
    ap.add_argument("--out")
    ap.add_argument("--only", default="")
    ap.add_argument("--extra-endpoint", action="append", default=[])
    ap.add_argument("--packages")
    ap.add_argument("--git-hosts", default="")
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--with-doctor", action="store_true", help="also run `claude doctor` (it rewrites the CLI's own config files)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    only = [x for x in a.only.split(",") if x]
    bad = [x for x in only if x not in SECTIONS]
    if bad:
        ap.error("unknown section(s): " + ", ".join(bad))
    doc = collect(only=only or None, packages=a.packages, git_hosts=[h for h in a.git_hosts.split(",") if h],
                  extras=a.extra_endpoint, network=not a.no_network, doctor=a.with_doctor)
    out = a.out or default_out()
    write_atomic(os.path.join(out, "probe.json"), json.dumps(doc, indent=1))
    write_atomic(os.path.join(out, "probe.md"), to_markdown(doc))
    print(json.dumps(doc) if a.json else "probe: %d sections in %ss -> %s" % (len(doc["sections"]), doc["duration_s"], out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
