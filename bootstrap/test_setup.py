"""setup.py checks. Unit tests of the parsers, policy rules and builders, then whole runs in a temp home against fake
winget/wsl/schtasks/curl/setx/venv/pip/npm/node/git/fnm programs and a JSON registry (WORKBENCH_FAKE_BIN,
WORKBENCH_FAKE_REGISTRY): nothing touches this machine's registry, PATH, scheduler or software.
Run: python -m unittest discover -s bootstrap -p "test_setup.py" -v   (WB_REQUIRE_ALL=1: a skip fails instead)"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import install as I  # noqa: E402
import knowledge_verify as KV  # noqa: E402
import setup as S  # noqa: E402

WINDOWS_ONLY = unittest.skipUnless(os.name == "nt" or REQUIRE, "fake .cmd programs need Windows")
REAL_HOME = Path.home()      # captured at import, before any test replaces the environment


def assert_sandboxed():
    """Fail when HOME, USERPROFILE, CLAUDE_CONFIG_DIR or LOCALAPPDATA (or what Path.home() returns from them) point outside the
    system temp folder. A test that builds an installer or a setup context in-process must run ENTIRELY under a temp profile:
    code that resolves Path.home() or the config dir at call time would otherwise write into the developer's real ~/.claude."""
    tmp = tempfile.gettempdir()
    for k in ("HOME", "USERPROFILE", "CLAUDE_CONFIG_DIR", "LOCALAPPDATA"):
        v = os.environ.get(k)
        if not v or not I.under(v, tmp):
            raise AssertionError(f"{k}={v!r} is not inside the temp folder {tmp}: this test would touch a real profile")
    if not I.under(Path.home(), tmp):
        raise AssertionError(f"Path.home() is {Path.home()}, outside the temp folder {tmp}")
TEL = list(S.TELEMETRY_ENV)
# Neutralised `wsl` output for a machine without WSL (captured by live_controls.py step 4), plus a synthetic
# `-l -v` table in the documented layout. Encoded to UTF-16LE here, as wsl.exe writes them. Without WSL all three
# commands exit non-zero, print on stderr when piped, with no BOM and "\r\r\n".
WSL_LIVE_STATUS = ("The Windows Subsystem for Linux is not installed. You can install by running 'wsl.exe --install'."
                   "\r\r\nFor more information please visit https://aka.ms/wslinstall\r\r\n")
WSL_TABLE = ("  NAME            STATE           VERSION\r\r\n* Ubuntu-24.04    Running         2\r\r\n"
             "  Distro          Stopped         2\r\r\n")

FAKE = r'''
import json, os, re, shutil, sys, time
from pathlib import Path
d = Path(os.environ["WB_FAKE_DIR"])
tool, args = sys.argv[1], sys.argv[2:]
sc = json.loads((d / "scenario.json").read_text())
stp = d / "state.json"
st = json.loads(stp.read_text()) if stp.exists() else {"installed": [], "wsl": sc.get("wsl", "absent"),
                                                        "distros": sc.get("distros", []), "git": {}, "net": 0}
with open(d / "calls.jsonl", "a") as f:
    f.write(json.dumps({"tool": tool, "argv": args, "cwd": os.getcwd(), "t": time.time(),
                        "env": {k: os.environ.get(k) for k in TEL}, "skip_dl": os.environ.get("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"),
                        "ctx_env": {k: os.environ.get(k) for k in ("CTX_ANALYTICS_ENABLED", "CTX_DAEMON_ENABLED", "CTX_UPGRADE_AUTO")}}) + "\n")
links = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "WinGet" / "Links"
def save(): stp.write_text(json.dumps(st))
def out(s, utf16=False):
    sys.stdout.buffer.write(s.encode("utf-16-le") if utf16 else s.encode()); sys.stdout.flush()
def done(c=0):
    save(); sys.exit(c - 2 ** 32 if c >= 2 ** 31 else c)
def make(wid):
    name = sc["ids"][wid][0]
    links.mkdir(parents=True, exist_ok=True)
    (links / f"{name}.cmd").write_text(f'@"{sys.executable}" "{__file__}" exe:{name} %*\r\n')
    st["installed"] = sorted(set(st["installed"]) | {wid})
if tool == "winget":
    sub = args[0]
    wid = args[args.index("--id") + 1] if "--id" in args else None
    if sub == "list":
        done(0 if wid in st["installed"] else 0x8A150014)
    if sub == "upgrade":      # scenario: upgrade_rc {id: code}; upgrade_lie = exit 0 and change nothing; latest {id: version}
        rc = sc.get("upgrade_rc", {}).get(wid, 0)
        if rc == 0 and not sc.get("upgrade_lie"):
            v = args[args.index("--version") + 1] if "--version" in args else sc.get("latest", {}).get(wid)
            if v:
                st.setdefault("versions", {})[sc["ids"][wid][0]] = v
        done(rc)
    if sub == "configure":
        time.sleep(sc.get("sleep", 0))
        rc = sc.get("configure_rc", 0)
        if rc == 0 and not sc.get("lie"):
            for w in re.findall(r"id: (\S+)", Path(args[args.index("-f") + 1]).read_text()):
                make(w)
        done(rc)
    if sub == "install":
        rc = sc.get("install_rc", {}).get(wid, 0)
        if rc == 0 and not sc.get("lie"):
            make(wid)
        done(rc)
    if sub == "uninstall":
        st["installed"] = [x for x in st["installed"] if x != wid]
        done(0)
    done(0)
if tool.startswith("exe:"):
    name = tool[4:]
    if name == "ctx" and sc.get("ctx_exe") and not Path(sc["ctx_exe"]).exists():
        done(1)                                 # the shim outlives a deleted ctx.exe only in this fake: act as if it were gone
    cargs = args[1:] if name == "ctx" and args[:1] and args[0].lower().endswith("ctx.exe") else args   # alias= puts the exe path first
    if name == "ctx" and cargs[:1] == ["status"]:        # what ctx 2.2.8 prints: the config file it reads (build-notes/v032-fetch.md)
        root = os.environ.get("CTX_DATA_ROOT") or str(Path(os.environ["USERPROFILE"]) / ".ctx")
        out(json.dumps({"config_path": str(Path(root) / "config.toml")}) + "\n"); done(0)
    if name == "ctx" and cargs[:2] == ["sources", "add"]:    # the vendor's editor: add; same settings = kept; other settings = exit 1
        root = Path(os.environ.get("CTX_DATA_ROOT") or Path(os.environ["USERPROFILE"]) / ".ctx")
        cfgf = root / "config.toml"
        txt = cfgf.read_text(encoding="utf-8") if cfgf.exists() else ""
        nm, rt = cargs[2], cargs[cargs.index("--root") + 1]
        head = f"[sources.roots.{nm}]"
        if head in txt:
            done(0 if f"path = '{rt}'" in txt else 1)
        root.mkdir(parents=True, exist_ok=True)
        cfgf.write_text(txt + ("\n" if txt and not txt.endswith("\n") else "") + f"\n{head}\nprovider = \"claude\"\npath = '{rt}'\n", encoding="utf-8")
        done(0)
    if name == "git" and args[:2] == ["config", "--global"]:
        a = args[2:]
        if a[0] == "--get":
            if a[1] in st["git"]:
                out(st["git"][a[1]] + "\n"); done(0)
            done(1)
        if a[0] == "--unset":
            st["git"].pop(a[1], None); done(0)
        st["git"][a[0]] = a[1]; done(0)
    if name == "fnm" and args and args[0] == "exec":
        out("v24.20.0\n"); done(0)
    if name == "node" and any(x.endswith("capture.mjs") for x in args):
        out("capture 0.3.0\n"); done(0)
    if name == "py" and "py_versions" in sc:      # scenario py_versions: the Pythons this py launcher finds, e.g. ["3.14.2"]
        v = next((x for x in sc["py_versions"] if args[:1] == ["-" + x.rsplit(".", 1)[0]]), None)
        if v:
            out(f"Python {v}\n"); done(0)
        done(103)
    base = next(t for w, (n, t) in sc["ids"].items() if n == name)
    v = st.get("versions", {}).get(name)       # a version an upgrade or an npm install set: replaces the number in the text
    out((re.sub(r"\d+\.\d+\.\d+", v, base, count=1) if v else base) + "\n")
    done(0)
if tool == "wsl":
    inst = st["wsl"] == "installed"
    if args == ["--status"]:
        out("Default Version: 2\r\n", True); done(0 if inst else 50)
    if args == ["-l", "-v"]:
        if not inst:
            done(50)
        rows = "".join(f"{'*' if i == 0 else ' '} {n:<16}Stopped         2\r\n" for i, n in enumerate(st["distros"]))
        out("  NAME              STATE           VERSION\r\n" + rows, True); done(0)
    if args == ["--version"]:
        out("WSL version: 9.9.9\r\n", True); done(0 if inst else 50)
    if args[:2] == ["--install", "--no-distribution"]:
        rc = sc.get("wsl_install_rc", 0)
        if rc == 0:
            st["wsl"] = "pending" if sc.get("needs_reboot", True) else "installed"
        done(rc)
    if args[:2] == ["--install", "-d"]:
        st["distros"].append(args[2]); done(0)
    done(1)
if tool == "claude":      # claude doctor: scenario claude_doctor = the text it prints
    out(sc.get("claude_doctor", "")); done(sc.get("claude_rc", 0))
if tool == "schtasks":
    tasks = d / "tasks"; tasks.mkdir(exist_ok=True)
    name = args[args.index("/TN") + 1]
    f = tasks / (re.sub(r"[^A-Za-z0-9-]", "_", name) + ".xml")
    if args[0] == "/Create":
        shutil.copyfile(args[args.index("/XML") + 1], f); done(sc.get("schtasks_create_rc", 0))
    if args[0] == "/Query":
        if f.exists():
            out(f.read_bytes().decode("utf-16")); done(0)
        done(1)
    if args[0] == "/Delete":
        f.unlink(missing_ok=True); done(0)
    done(0)
if tool == "curl":       # scenario curl_35: the stderr of an exit 35 without --ssl-revoke-best-effort (or always: curl_35_always)
    if sc.get("curl_35") and ("--ssl-revoke-best-effort" not in args or sc.get("curl_35_always")):
        if "--show-error" in args or "--silent" not in args:      # curl prints the reason only then
            sys.stderr.write("curl: (35) schannel: next InitializeSecurityContext failed: " + sc["curl_35"] + "\n")
        done(35)
    if "--head" in args:
        st["net"] += 1
        done(7 if st["net"] <= sc.get("net_fail", 0) else 0)
    if "-o" in args and "curl_body" in sc:      # a release download: write the fixture, and the program it installs
        Path(args[args.index("-o") + 1]).write_bytes(sc["curl_body"].encode())
        for name in sc.get("curl_shim", []):
            (Path(sc["fakebin"]) / f"{name}.cmd").write_text(f'@"{sys.executable}" "{__file__}" exe:{name} %*\r\n')
        out("200")
    done(sc.get("curl_rc", 0))
if tool == "venv":
    p = Path(args[-1]) / "Scripts"; p.mkdir(parents=True, exist_ok=True)
    (p / "python.exe").write_bytes(b""); done(0)
if tool == "npm":
    if args[:3] == ["config", "get", "prefix"]:
        out(sc.get("npm_prefix", "") + "\n"); done(0)
    if args[:1] in (["install"], ["uninstall"]) and "-g" in args:
        spec = args[args.index("-g") + 1]
        pkgname, _, ver = spec.rpartition("@")
        binname = {"@playwright/cli": "playwright-cli"}.get(pkgname or spec, "tool")
        prefix = Path(args[args.index("--prefix") + 1] if "--prefix" in args else sc.get("npm_prefix") or ".")
        if args[0] == "uninstall":
            (prefix / f"{binname}.cmd").unlink(missing_ok=True); st.get("versions", {}).pop(binname, None); done(sc.get("npm_rc", 0))
        out(sc.get("npm_out", ""))
        rc = sc.get("npm_rc", 0)
        if rc == 0 and not sc.get("lie"):
            prefix.mkdir(parents=True, exist_ok=True)
            (prefix / f"{binname}.cmd").write_text(f'@"{sys.executable}" "{__file__}" exe:{binname} %*\r\n')
            st.setdefault("versions", {})[binname] = sc.get("npm_force") or (sc.get("npm_latest", "9.9.9") if ver == "latest" else ver)
        done(rc)
    (Path.cwd() / "node_modules").mkdir(exist_ok=True); done(0)
if tool == "pip":
    if "list" in args:      # scenario: pip_list [{"name","version"}], pip_outdated [{"name","version","latest_version"}]
        out(json.dumps(sc.get("pip_outdated" if "--outdated" in args else "pip_list", []))); done(0)
    done(sc.get("pip_rc", 0))
done(0)
'''.replace("TEL", json.dumps(TEL))

STUB = r'''
import json, os, sys, time
from pathlib import Path
TOOL = "{tool}"
with open(Path(os.environ["WB_FAKE_DIR"]) / "calls.jsonl", "a") as f:
    f.write(json.dumps({{"tool": TOOL, "argv": sys.argv[1:], "t": time.time(), "env": {{}}, "path": os.environ.get("PATH")}}) + "\n")
a = sys.argv[1:]
if TOOL == "find":
    if a[0] == "discover":
        libs = json.loads(os.environ["WB_FAKE_LIBS"]) if os.environ.get("WB_FAKE_LIBS") else [
            {{"path": os.environ["WB_FAKE_LIB"], "kind": "documents", "label": "documents",
             "on_device_files": 2, "cloud_only_files": 0, "sampled": False}}]
        print(json.dumps({{"libraries": libs}}))
    elif a[0] == "add-root":
        print(json.dumps({{"root": a[a.index("--label") + 1] if "--label" in a else "x", "path": a[1]}}))
    elif a[0] == "status":
        print(json.dumps({{"last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "paragraphs": 3}}))
    elif a[0] == "roots":
        print(os.environ.get("WB_FAKE_ROOTS") or "{{}}")
    else:
        print("{{}}")
elif TOOL == "policy":
    print(json.dumps({{"version": 1, "changed": json.loads(os.environ.get("WB_FAKE_POLICY_CHANGED", "[]"))}}))
elif TOOL == "report":
    cap = os.environ.get("WB_FAKE_CAPABILITY")
    if cap and "--phase" in a:      # the capability file the real report.py would write (its rows carry the asks)
        sd = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "workbench", "state")
        os.makedirs(sd, exist_ok=True)
        open(os.path.join(sd, "capability-" + a[a.index("--phase") + 1] + ".json"), "w", encoding="utf-8").write(cap)
    print("report " + " ".join(a))
else:
    print("report " + " ".join(a))
'''

REVOCATION_ERR = ("CRYPT_E_NO_REVOCATION_CHECK (0x80092012) - The revocation function was unable to check revocation for "
                  "the certificate.")
PACKAGES = json.loads((HERE / "packages.json").read_text(encoding="utf-8"))["packages"]
VERSION_TEXT = {"git": "git version 2.55.0", "gh": "gh version 2.102.0 (stable)", "py": "Python 3.13.15",
                "uv": "uv 0.12.21", "pwsh": "PowerShell 7.6.6", "rg": "ripgrep 15.2.0", "fd": "fd 10.5.0",
                "jq": "jq-1.8.2", "code": "1.140.0", "node": "v24.19.0", "fnm": "fnm 1.39.0",
                "claude": "2.1.295 (Claude Code)", "tokensave": "tokensave 7.12.1", "playwright-cli": "0.1.22",
                "ctx": "ctx 2.2.8"}       # = the pins in packages.json: a fresh install is already "current"
IDS = {p["winget"]: [p["verify"][0], VERSION_TEXT[p["verify"][0]]] for p in PACKAGES if p.get("winget")}
IDS.update({"npm:@playwright/cli": ["playwright-cli", VERSION_TEXT["playwright-cli"]],
            "release:ctx": ["ctx", VERSION_TEXT["ctx"]], "release:tokensave": ["tokensave", VERSION_TEXT["tokensave"]]})
ROUTING = {"version": 1, "provider_ids": {"claude-opus-5-5": {"bedrock": "vendor.claude-opus-5-5"}},
           "rows": [{"id": "R-build-hard", "persona": "flagship", "evidence": ["E1"],
                     "chain": [{"model": "claude-opus-5-5", "effort": "xhigh"}, {"model": "claude-sonnet-5-5", "effort": "xhigh"}]},
                    {"id": "R-routine", "persona": "implementer", "evidence": ["E2"],
                     "chain": [{"model": "claude-sonnet-5-5", "effort": "high"}]}]}


def mini_kit(dst):
    """The parts of the kit setup.py runs, plus fixtures for the files other slices own (routing table, find
    requirements, capture scripts, how-to folder)."""
    dst = Path(dst)
    (dst / "bootstrap").mkdir(parents=True)
    for f in HERE.iterdir():
        if f.suffix in (".py", ".json", ".txt", ".sh") and not f.name.startswith(("test_", "probe", "report", "devbench")):
            shutil.copyfile(f, dst / "bootstrap" / f.name)
    for t in ("memcap", "redact-settings", "mcp-healer"):
        shutil.copytree(REPO / "tools" / t, dst / "tools" / t, ignore=shutil.ignore_patterns("__pycache__", "test*"))
    (dst / "plugins/workbench-core/scripts").mkdir(parents=True)
    for f in ("secretscan.py", "bug_hint.py", "_wb.py"):
        shutil.copyfile(REPO / "plugins/workbench-core/scripts" / f, dst / "plugins/workbench-core/scripts" / f)
    (dst / "kb-template/_shared").mkdir(parents=True)          # the doctor reads `claude doctor` through these detectors
    (dst / "kb-template/_shared/bug-detectors.json").write_text(json.dumps({"detectors": [
        {"card": 12, "title": "fixture startup warning", "pattern": "fixture-startup-warning"}]}), encoding="utf-8")
    (dst / "settings").mkdir()
    (dst / "settings/model-routing.json").write_text(json.dumps(ROUTING), encoding="utf-8")
    req = dst / "plugins/workbench-core/skills/find/requirements.txt"
    req.parent.mkdir(parents=True)
    req.write_text("fastembed==0.9.0\n", encoding="utf-8")
    office = dst / "plugins/workbench-core/skills/office-render/requirements.txt"
    office.parent.mkdir(parents=True)
    office.write_text("pypdfium2==5.14.0\n", encoding="utf-8")
    cap = dst / "plugins/workbench-capture/skills/capture/scripts"
    cap.mkdir(parents=True)
    (cap / "package.json").write_text('{"name": "capture", "version": "0.3.0"}\n', encoding="utf-8")
    (cap / "capture.mjs").write_text("// fixture\n", encoding="utf-8")
    (dst / "mcp").mkdir()
    shutil.copyfile(REPO / "mcp/golden-config.template.json", dst / "mcp/golden-config.template.json")
    (dst / "docs/howto").mkdir(parents=True)
    (dst / "templates").mkdir()
    shutil.copyfile(REPO / "templates/USER.md", dst / "templates/USER.md")
    return dst


def probe_json(admin=True, tls=False, denied=(), automation=True, headless=True, edge="C:/Edge/msedge.exe"):
    sec = lambda d: {"status": "ok", "data": d, "notes": []}  # noqa: E731
    return {"version": 1, "sections": {
        "identity": sec({"admin_capable": admin, "elevated_now": False, "epm_present": False, "method": "whoami-groups"}),
        "tls": sec({"hosts": [{"host": "pypi.org", "inspected": "yes" if tls else "no"}],
                    "runtimes": [{"runtime": "python", "ok": True, "category": None}]}),
        "network": sec({"endpoints": [{"name": "pypi", "result": "ok"}]}),
        "models": sec({"provider": "anthropic", "available": "unverified", "denied": list(denied), "match": "exact",
                       "enforce": False, "sources": ["managed-settings.json"]}),
        "capture": sec({"automation_allowed": automation, "headless_allowed": headless, "edge_path": edge})}}


class FakeEnv:
    def __init__(self, kit=None, profile="corporate", scenario=None, probe=None, registry=None, preinstalled=(), ch_name=None):
        self.root = Path(tempfile.mkdtemp(prefix="wb-setup-"))
        self.home, self.lad = self.root / "home", self.root / "lad"
        self.ch = self.root / ch_name if ch_name else self.home / ".claude"      # ch_name: CLAUDE_CONFIG_DIR is NOT ~/.claude
        self.wb, self.bin, self.dir = self.ch / "workbench", self.root / "fakebin", self.root / "fake"
        for d in (self.wb, self.bin, self.dir, self.lad, self.root / "lib"):
            d.mkdir(parents=True, exist_ok=True)
        self.index = self.lad / "doc-index" / "knowledge" / "index.sqlite"     # an index setup built earlier
        self.index.parent.mkdir(parents=True)
        self.index.write_bytes(b"")
        self.kit = Path(kit) if kit else REPO
        self.setup = self.kit / "bootstrap" / "setup.py"
        self.reg = self.root / "registry.json"
        self.reg.write_text(json.dumps({"HKCU\\Environment": {"Path": [r"%LOCALAPPDATA%\Tools", 2]}, **(registry or {})}))
        self.registry_before = json.loads(self.reg.read_text())
        self.scenario = {"ids": IDS, "fakebin": str(self.bin), **(scenario or {})}
        (self.dir / "scenario.json").write_text(json.dumps(self.scenario))
        (self.dir / "fake.py").write_text(FAKE, encoding="utf-8")
        for t in ("winget", "wsl", "schtasks", "curl", "setx", "venv", "pip", "npm", "attrib"):
            (self.bin / f"{t}.cmd").write_text(f'@"{sys.executable}" "{self.dir / "fake.py"}" {t} %*\r\n')
        stubs = {}
        for t in ("find", "report", "policy"):
            stubs[t] = self.dir / f"{t}_stub.py"
            stubs[t].write_text(STUB.format(tool=t), encoding="utf-8")
        self.probe = self.dir / "probe.json"
        self.set_probe(probe or probe_json())
        self.managed = self.root / "managed-settings.json"
        self.managed.write_text('{"permissions": {"deny": ["Read(./.env)"]}}', encoding="utf-8")
        (self.wb / "config.json").write_text(json.dumps({"profile": profile, "data_root": I.fwd(self.home / "Workbench"),
                                                         "kb_root": I.fwd(self.home / "Workbench" / "kb")}))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("OneDrive", "WORKBENCH_", "WB_"))}
        self.env.update(USERPROFILE=str(self.home), HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.ch),
                        LOCALAPPDATA=str(self.lad), WORKBENCH_FAKE_BIN=str(self.bin), WORKBENCH_FAKE_REGISTRY=str(self.reg),
                        WB_FAKE_DIR=str(self.dir), WB_FAKE_LIB=str(self.root / "lib"), WORKBENCH_NET_POLL_S="0.05",
                        WORKBENCH_PROBE_JSON=str(self.probe), WORKBENCH_FIND_CLI=str(stubs["find"]),
                        WORKBENCH_REPORT_CLI=str(stubs["report"]), WORKBENCH_POLICY_CLI=str(stubs["policy"]),
                        WORKBENCH_MANAGED_SETTINGS=str(self.managed), WORKBENCH_VERIFY_JSON=str(self.dir / "verify.json"))
        self.set_verify()
        for wid in preinstalled:
            self.fake("winget", "install", "--id", wid)

    def set_probe(self, d):
        self.probe.write_text(json.dumps(d), encoding="utf-8")

    def set_verify(self, **status):
        """The Day-1 knowledge checks' result (knowledge_verify.py is tested on its own): every step PASS unless named,
        e.g. set_verify(D3="FAIL", D9=("WARN", "an ask"))."""
        rows = []
        for sid, name, _fn in KV.STEPS:
            st = status.get(sid, "PASS")
            st, ask = st if isinstance(st, tuple) else (st, None)
            rows.append({"id": sid, "name": name, "status": st, "detail": f"{name} fixture", "ms": 1, "ask_it": ask})
        (self.dir / "verify.json").write_text(json.dumps({"steps": rows}), encoding="utf-8")

    def add_tool(self, name, exe=False):
        """A program in the fake bin folder. exe=True: it answers like an installed tool (its version text from the
        scenario ids); else it is a plain fake that logs its call (the FAKE tool branch of that name)."""
        (self.bin / f"{name}.cmd").write_text(f'@"{sys.executable}" "{self.dir / "fake.py"}" {"exe:" if exe else ""}{name} %*\r\n')

    def set_scenario(self, **kw):
        self.scenario.update(kw)
        (self.dir / "scenario.json").write_text(json.dumps(self.scenario))

    def set_fake_state(self, **kw):
        p = self.dir / "state.json"
        st = json.loads(p.read_text()) if p.exists() else {}
        st.update(kw)
        p.write_text(json.dumps(st))

    def fake(self, *args):
        subprocess.run([sys.executable, str(self.dir / "fake.py"), *args], env=self.env, capture_output=True)

    def run(self, *args, code=None, timeout=300, script=None):
        r = subprocess.run([sys.executable, str(script or self.setup), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=self.env, cwd=str(self.root), timeout=timeout)
        if code is not None:
            assert r.returncode == code, f"exit {r.returncode} != {code}\n{r.stdout[-3000:]}\n{r.stderr[-2000:]}"
        return r

    def calls(self, tool=None):
        p = self.dir / "calls.jsonl"
        rows = [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
        return [c for c in rows if tool is None or c["tool"] == tool]

    def clear_calls(self):
        (self.dir / "calls.jsonl").unlink(missing_ok=True)

    def state(self):
        return json.loads((self.wb / "state" / "setup-state.json").read_text(encoding="utf-8"))

    def registry(self):
        return json.loads(self.reg.read_text())

    def wait_done(self, limit=180):
        end = time.time() + limit
        while time.time() < end:
            st = json.loads(self.run("status", "--json", "--wait", "5").stdout)
            if st.get("exit_code") is not None and not st["running"]:
                return st
        raise AssertionError("setup did not finish")

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def installs(env):
    """winget install/upgrade/configure, wsl --install, pip and npm installs, task creation: what a second run must not make
    (pip list and npm config are reads)."""
    return [c for c in env.calls() if (c["tool"] == "winget" and c["argv"][0] in ("install", "upgrade", "configure"))
            or (c["tool"] == "wsl" and c["argv"][:1] == ["--install"]) or (c["tool"] in ("pip", "npm") and "install" in c["argv"])
            or (c["tool"] == "schtasks" and c["argv"][0] == "/Create")]


class Units(unittest.TestCase):
    def test_wsl_utf16_fixtures_parse(self):
        rows = S.parse_wsl_list(WSL_TABLE.encode("utf-16-le"))
        self.assertEqual([(r["name"], r["version"], r["default"]) for r in rows], [("Ubuntu-24.04", 2, True), ("Distro", 2, False)])
        self.assertEqual(S.parse_wsl_list(b"\xff\xfe" + WSL_TABLE.encode("utf-16-le"))[0]["name"], "Ubuntu-24.04")
        live = S.decode(WSL_LIVE_STATUS.encode("utf-16-le"))
        self.assertEqual(live, WSL_LIVE_STATUS)                                         # no BOM: still UTF-16LE
        self.assertEqual(S.decode(b"\xff\xfe" + WSL_LIVE_STATUS.encode("utf-16-le")), WSL_LIVE_STATUS)
        self.assertEqual(S.parse_wsl_list(WSL_LIVE_STATUS.encode("utf-16-le")), [])     # not installed: no rows
        self.assertEqual(S.decode("plain".encode()), "plain")

    def test_exit_code_classes_are_disjoint_and_documented(self):
        self.assertFalse(S.DENIED & S.CONFIGURE_UNAVAILABLE)
        self.assertFalse((S.ALREADY | S.REBOOT) & S.DENIED)
        self.assertIn(0x8A15003A, S.DENIED)               # APPINSTALLER_CLI_ERROR_BLOCKED_BY_POLICY
        self.assertIn(0x8A15010F, S.DENIED)               # INSTALL_BLOCKED_BY_POLICY
        self.assertIn(1223, S.DECLINED)                   # UAC prompt declined

    def test_policy_polarity(self):
        with tempfile.TemporaryDirectory() as t:
            reg = Path(t) / "r.json"
            reg.write_text(json.dumps({S.WSL_POLICY: {"AllowWSL": 0}, S.APPX_POLICY: {"BlockNonAdminUserInstall": 1},
                                       S.APPINSTALLER: {"EnableAppInstaller": 1}}))
            old = os.environ.get("WORKBENCH_FAKE_REGISTRY")
            os.environ["WORKBENCH_FAKE_REGISTRY"] = str(reg)
            try:
                self.assertTrue(S.blocked(S.WSL_POLICY + r"\AllowWSL"))
                self.assertTrue(S.blocked(S.APPX_POLICY + r"\BlockNonAdminUserInstall"))
                self.assertFalse(S.blocked(S.APPINSTALLER + r"\EnableAppInstaller"))
                self.assertFalse(S.blocked(S.APPINSTALLER + r"\EnableDefaultSource"))     # absent never blocks
            finally:
                os.environ.pop("WORKBENCH_FAKE_REGISTRY") if old is None else os.environ.update(WORKBENCH_FAKE_REGISTRY=old)

    def test_registry_writes_refuse_hklm_and_policies(self):
        for key in (r"HKLM\SOFTWARE\Policies\WSL", r"HKCU\Software\Policies\Microsoft\Edge", r"HKLM\SOFTWARE\x"):
            with self.assertRaises(PermissionError):
                S.reg_set(key, "x", 1, 4)
            with self.assertRaises(PermissionError):
                S.reg_delete(key, "x")

    def test_runonce_length_and_short_path_fallback(self):
        cmd = S.runonce_command("C:/py/pythonw.exe", "C:/k/bootstrap/setup.py")
        self.assertTrue(cmd.startswith('"') and cmd.endswith(" resume") and len(cmd) <= 260)
        with tempfile.TemporaryDirectory() as t:
            deep = Path(t).joinpath(*["a long folder name " + str(i) for i in range(12)], "bootstrap")
            deep.mkdir(parents=True)
            script = deep / "setup.py"
            script.write_text("", encoding="utf-8")
            long_cmd = f'"{Path(sys.executable)}" "{script}" resume'
            self.assertGreater(len(long_cmd), 260)
            got = S.runonce_command(sys.executable, script)
            if I.short_path(script) != str(script) and len(f'"{I.short_path(sys.executable)}" "{I.short_path(script)}" resume') <= 260:
                self.assertIsNotNone(got)
                self.assertLessEqual(len(got), 260)
            else:   # 8.3 names are off on this volume: setup must refuse rather than write a truncated command
                self.assertIsNone(got)

    def test_routing_falls_back_on_denied_model(self):
        eff = S.effective_routing(ROUTING, {"provider": "anthropic", "available": "unverified",
                                            "denied": ["claude-opus-5-5"], "match": "exact", "sources": ["m.json"]})
        r = {x["id"]: x for x in eff["rows"]}
        self.assertEqual([x["id"] for x in eff["rows"]], ["R-build-hard", "R-routine"])     # I3a row order kept
        self.assertEqual((r["R-build-hard"]["model"], r["R-build-hard"]["fallback_used"]), ("claude-sonnet-5-5", True))
        self.assertIn("deniedModels", r["R-build-hard"]["reason"])
        self.assertFalse(r["R-routine"]["fallback_used"])
        self.assertFalse(eff["models_verified"])
        eff = S.effective_routing(ROUTING, {"provider": "bedrock", "available": ["claude-sonnet"], "match": "prefix"})
        self.assertTrue(eff["models_verified"])
        self.assertEqual(eff["rows"][0]["model"], "claude-sonnet-5-5")
        eff = S.effective_routing(ROUTING, {"provider": "bedrock", "denied": [], "available": "unverified"})
        self.assertEqual(eff["rows"][0]["model"], "vendor.claude-opus-5-5")                 # provider id mapping

    def test_task_xml_and_dsc_yaml(self):
        x = S.task_xml("desc & more", [("C:/py/pythonw.exe", '"a" --mb 2048 -- b refresh --all --embed auto')])
        for want in ("<StartWhenAvailable>true", "<DisallowStartIfOnBatteries>true", "<StopIfGoingOnBatteries>true",
                     "<Description>desc &amp; more</Description>", "LeastPrivilege", "--mb 2048"):
            self.assertIn(want, x)
        y = S.dsc_yaml([{"item": "git", "winget": "Git.Git"}, {"item": "python313", "winget": "Python.Python.3.13"}])
        self.assertIn("identifier: dscv3", y)
        self.assertEqual(y.count("acceptAgreements: true"), 2)
        self.assertIn("id: Git.Git", y)

    def test_plan_sources_and_hosts_are_official(self):
        ok_src = {"winget", "msstore", "pypi", "npm", "github-release", "vendor-url"}
        ok_host = {"cdn.winget.microsoft.com", "github.com", "release-assets.githubusercontent.com", "www.python.org",
                   "nodejs.org", "update.code.visualstudio.com", "vscode.download.prss.microsoft.com", "downloads.claude.ai",
                   "registry.npmjs.org"}
        for p in PACKAGES:
            self.assertIn(p["source"], ok_src, p["id"])
            self.assertLessEqual(set(p["hosts"]), ok_host, p["id"])
            self.assertTrue(p["ask_it"] and p["verify"] and "(" in p["expect"], p["id"])
            if p["source"] == "github-release":
                self.assertRegex(p["url"], r"^https://github\.com/[^/]+/[^/]+/releases/download/v\d+\.\d+\.\d+/")
                self.assertRegex(p["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual([p["scope"] for p in PACKAGES if p["id"] == "node"], ["machine"])

    def test_crash_mid_write_leaves_valid_state(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "setup-state.json"
            S.jwrite(f, {"phase": "plan"})
            real = os.replace

            def boom(a, b):
                raise KeyboardInterrupt("simulated crash")
            S.os.replace = boom
            try:
                with self.assertRaises(KeyboardInterrupt):
                    S.jwrite(f, {"phase": "install", "big": "x" * 100000})
            finally:
                S.os.replace = real
            self.assertEqual(json.loads(f.read_text(encoding="utf-8")), {"phase": "plan"})

    def test_layout_json_shape(self):
        lay = json.loads((HERE / "layout.json").read_text(encoding="utf-8"))
        self.assertEqual(lay["version"], 1)
        for t in ("<CH>", "<WB>", "<KIT>", "<LAD>", "<HOME>", "<ONEDRIVE_WORK>", "<DATA>", "<KB>", "<DEVDRIVE>", "<SRC>"):
            self.assertIn(t, lay["tokens"])
        paths = {e["path"]: e for e in lay["paths"]}
        for p in ("<WB>/state/", "<WB>/config.json", "<WB>/profiles.json", "<WB>/venv/", "<WB>/bin/", "<WB>/capture/app/",
                  "<WB>/capture/profile/", "<WB>/capture/scope.json", "<WB>/capture/runs/", "<LAD>/doc-index/knowledge/",
                  "<LAD>/doc-index/models/", "<LAD>/wb-review/", "<HOME>/.claude-profiles/", "<DATA>/", "<DATA>/captured/",
                  "<DATA>/backup/", "<SRC>/", "<DATA>/captured/_drop/meetings/"):
            self.assertIn(p, paths)
        for e in lay["paths"]:
            self.assertIn(e["kind"], ("dir", "file", "task", "registry", "env"))
            self.assertIn(e["uninstall"], ("remove", "keep"))
            self.assertIn(e["class"], ("state", "cache", "user-data", "runtime", "config", "backup"))
            self.assertIn(e["placement"], ("local-only", "work-cloud-ok"))
            if e["class"] in ("user-data", "backup") and e["path"].startswith("<DATA>"):
                self.assertEqual((e["uninstall"], e["placement"]), ("keep", "work-cloud-ok"), e["path"])
        self.assertEqual(paths["<SRC>/"]["placement"], "local-only")
        for p in ("<LAD>/doc-index/knowledge/", "<WB>/capture/profile/"):
            self.assertEqual(paths[p]["placement"], "local-only")

    def test_every_user_variable_setup_sets_has_a_layout_row_and_is_removed_on_uninstall(self):
        import re
        lay = {e["path"]: e for e in json.loads((HERE / "layout.json").read_text(encoding="utf-8"))["paths"]}
        names = set(re.findall(r'env_set\(ctx, "([A-Z_]+)"', (HERE / "setup.py").read_text(encoding="utf-8")))
        names |= set(S.CTX_ENV) | {S.CLI_CONFIG_ENV}
        self.assertTrue({"NODE_USE_SYSTEM_CA", "CTX_DAEMON_ENABLED", "PLAYWRIGHT_MCP_CONFIG"} <= names)
        for n in names:
            self.assertIn(n, lay, n)
            self.assertEqual((lay[n]["kind"], lay[n]["creator"], lay[n]["uninstall"]), ("env", "bootstrap/setup.py", "remove"), n)

    def test_infosec_note(self):
        t = (HERE / "infosec-note.txt").read_text(encoding="utf-8")
        for want in ("security team", "retention, DLP and eDiscovery", "outside your organisation", "purge"):
            self.assertIn(want, t)
        self.assertEqual(len([ln for ln in t.splitlines() if ln.strip()]), 1)           # one paragraph


class RestoreSafety(unittest.TestCase):
    """A backup zip sits in a synced folder, so restore treats it as untrusted input."""
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="wb-restore-"))
        old = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old), shutil.rmtree(self.t, True)))
        (self.t / "reg.json").write_text("{}")
        (self.t / "ch" / "workbench").mkdir(parents=True)
        (self.t / "ch" / "workbench" / "config.json").write_text(json.dumps(
            {"data_root": I.fwd(self.t / "data"), "kb_root": I.fwd(self.t / "kb")}))
        os.environ.update(CLAUDE_CONFIG_DIR=str(self.t / "ch"), WORKBENCH_FAKE_REGISTRY=str(self.t / "reg.json"),
                          HOME=str(self.t / "home"), USERPROFILE=str(self.t / "home"), LOCALAPPDATA=str(self.t / "lad"))
        assert_sandboxed()

    def restore(self, arc, data=b"x", symlink=False, **kw):
        z = self.t / "b.zip"
        with zipfile.ZipFile(z, "w") as zf:
            info = zipfile.ZipInfo(arc)
            if symlink:
                info.external_attr = 0o120777 << 16
            zf.writestr(info, data)
            zf.writestr("manifest.json", json.dumps({"version": 1, "files": [
                {"path": arc, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "mtime": 0}]}))
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = S.cmd_restore(S.Ctx(), z, **kw)
        return rc, buf.getvalue()

    def test_unsafe_members_are_refused(self):
        for arc in ("KB/..\\..\\x", "KB/C:x", "KB/./x", "/KB/x", "KB/../x", "KB//x", "C:/x", "KB/a/../../x"):
            for kw in ({"to": str(self.t / "out")}, {"apply": True}):
                rc, out = self.restore(arc, **kw)
                self.assertEqual(rc, 4, (arc, out))
                self.assertFalse((self.t / "out").exists(), arc)
        self.assertFalse((self.t / "x").exists())

    def test_symlink_member_is_refused(self):
        rc, out = self.restore("KB/link.md", b"../../outside", symlink=True, apply=True)
        self.assertEqual(rc, 4)
        self.assertIn("link", out)
        self.assertFalse((self.t / "kb" / "link.md").exists())

    def test_settings_with_a_hook_need_the_flag(self):
        body = json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "evil-tool --now"}]}]}})
        rc, out = self.restore("CH/settings.json", body.encode(), apply=True)
        self.assertEqual(rc, 0)
        self.assertIn("evil-tool --now", out)
        self.assertFalse((self.t / "ch" / "settings.json").exists(), "not written without --restore-settings")
        rc, out = self.restore("CH/settings.json", body.encode(), apply=True, restore_settings=True)
        self.assertIn("evil-tool --now", out)
        self.assertTrue((self.t / "ch" / "settings.json").exists())

    def test_a_safe_member_restores(self):
        rc, _ = self.restore("KB/notes/a.md", b"# a\n", apply=True)
        self.assertEqual(rc, 0)
        self.assertEqual((self.t / "kb" / "notes" / "a.md").read_bytes(), b"# a\n")


@WINDOWS_ONLY
class Flows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wb-kit-"))
        cls.kit = mini_kit(cls.tmp / "kit")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def env(self, **kw):
        e = FakeEnv(kit=self.kit, **kw)
        self.addCleanup(e.close)
        return e

    def test_full_run_then_second_run_is_a_no_op(self):
        e = self.env(profile="permissive", scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"]},
                     probe=probe_json(admin=True, tls=True, denied=["claude-opus-5-5"]))
        (e.home / "Workbench" / "kb").mkdir(parents=True)
        e.run("run", "--with", "capture", code=0)
        c = e.calls()
        first_winget = next(i for i, x in enumerate(c) if x["tool"] == "winget")
        self.assertLess(next(i for i, x in enumerate(c) if x["tool"] == "report" and "pre" in x["argv"]), first_winget)
        conf = [x for x in c if x["tool"] == "winget" and x["argv"][0] == "configure"]
        self.assertEqual(len(conf), 1)
        self.assertIn("--accept-configuration-agreements", conf[0]["argv"])
        y = (e.wb / "state" / "workbench.winget").read_text(encoding="utf-8")
        self.assertIn("acceptAgreements: true", y)
        self.assertNotIn("OpenJS.NodeJS.LTS", y)                         # machine scope never goes through configure
        node = [x for x in c if x["tool"] == "winget" and x["argv"][:3] == ["install", "--id", "OpenJS.NodeJS.LTS"]]
        self.assertEqual(len(node), 1)
        self.assertEqual(node[0]["argv"][node[0]["argv"].index("--scope") + 1], "machine")
        for i, x in enumerate(c):      # every install call is followed by its own verify argv
            if x["tool"] == "winget" and x["argv"][0] == "install":
                name = IDS[x["argv"][2]][0]
                self.assertTrue(any(y["tool"] == f"exe:{name}" for y in c[i + 1:]), name)
        task = [x for x in c if x["tool"] == "schtasks" and x["argv"][0] == "/Create"]
        self.assertEqual(len(task), 1, "permissive registers the nightly task by default")
        xml = (e.dir / "tasks" / "_claude-workbench_knowledge-refresh.xml").read_bytes().decode("utf-16")
        for want in ("DisallowStartIfOnBatteries>true", "StopIfGoingOnBatteries>true", "StartWhenAvailable>true",
                     "--mb 2048", "refresh --all --embed auto", "pythonw", "purge --older-than 90",
                     "backup --if-older-days 7"):
            self.assertIn(want, xml)
        for x in [x for x in c if x["tool"] in ("pip", "npm")]:
            self.assertEqual(x["env"], S.TELEMETRY_ENV, x["tool"])
        self.assertEqual({x["tool"] for x in c if x["tool"] in ("pip", "npm")}, {"pip", "npm"})
        reg = e.registry()
        env = {k.lower(): v for k, v in reg["HKCU\\Environment"].items()}
        self.assertEqual(env["node_use_system_ca"][0], "1")
        self.assertEqual(env["uv_system_certs"][0], "true")
        self.assertEqual(json.loads((e.dir / "state.json").read_text())["git"], {"http.sslBackend": "schannel"})
        self.assertFalse([k for k in reg if "policies" in k.lower()], "no Policies key is ever written")
        self.assertEqual(e.managed.read_text(encoding="utf-8"), '{"permissions": {"deny": ["Read(./.env)"]}}')
        self.assertFalse(e.calls("setx"), "setx is never used")
        eff = json.loads((e.wb / "state" / "routing.effective.json").read_text(encoding="utf-8"))
        self.assertTrue(eff["rows"][0]["fallback_used"])
        self.assertEqual(eff["rows"][0]["model"], "claude-sonnet-5-5")
        roots = [x["argv"] for x in e.calls("find") if x["argv"][0] == "add-root"]
        self.assertEqual(sorted(a[a.index("--label") + 1] for a in roots), ["captured", "howto", "kb"],
                         "the discovered Documents library is a suggestion, not a root")
        cfg = json.loads((e.wb / "config.json").read_text(encoding="utf-8"))
        self.assertTrue(cfg["knowledge_python"].endswith("venv/Scripts/python.exe"))
        self.assertTrue(cfg["knowledge_db"].endswith("doc-index/knowledge/index.sqlite"))
        st = e.state()
        self.assertEqual((st["phase"], st["exit_code"], st["running"], st["infosec_shown"]), ("done", 0, False, True))
        self.assertIn("INFOSEC NOTE", (e.wb / "state" / "setup.log").read_text(encoding="utf-8"))
        plan = json.loads((e.wb / "state" / "plan.json").read_text(encoding="utf-8"))
        self.assertTrue({it["tag"] for it in plan["items"]} <= set(S.TAGS))
        e.clear_calls()
        e.run("run", code=0)                 # idempotent: the options are remembered, nothing is installed again
        self.assertEqual(installs(e), [], "a second run makes no install call")

    def test_corporate_task_only_with_nightly(self):
        e = self.env(scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"]})
        e.run("run", code=0)
        self.assertFalse([x for x in e.calls("schtasks") if x["argv"][0] == "/Create"], "corporate: no task by default")
        self.assertTrue([x for x in e.calls("find") if x["argv"][:3] == ["refresh", "--all", "--detach"]])
        e.run("run", "--with", "nightly", code=0)
        self.assertEqual(len([x for x in e.calls("schtasks") if x["argv"][0] == "/Create"]), 1)
        self.assertTrue([x for x in e.calls("schtasks") if x["argv"][0] == "/Run"])

    def test_the_schedule_check_passes_on_the_task_setup_registered(self):
        e = self.env(scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"]})
        e.run("run", "--with", "nightly", code=0)
        with mock.patch.dict(os.environ, e.env, clear=True):
            v = KV.Verifier(S.Ctx(), "doctor", e.kit)
            try:
                st, detail = KV.d15_schedule(v)[:2]
            finally:
                shutil.rmtree(v.sb, ignore_errors=True)
        self.assertEqual(st, KV.PASS, detail)      # the XML file is CRLF on Windows; setup recorded the LF text's hash

    def test_the_post_report_sees_the_path_as_a_new_sign_in_would(self):
        e = self.env(scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"]})
        e.run("run", code=0)
        post = [c for c in e.calls("report") if "post" in c["argv"]]
        self.assertEqual(len(post), 1)
        parts = [x.lower() for x in post[0]["path"].split(os.pathsep)]
        for want in (e.lad / "Microsoft" / "WinGet" / "Links", e.lad / "Tools", e.wb / "bin"):    # Links, the user Path
            self.assertIn(str(want).lower(), parts)

    def test_an_installed_python_3_14_is_accepted_and_3_13_is_installed_only_when_none_is(self):
        e = self.env(scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"], "py_versions": ["3.14.2"]},
                     preinstalled=("Python.Python.3.13",))                    # puts a `py` launcher on the fake PATH
        e.clear_calls()
        e.run("run", code=0)
        plan = {it["item"]: it for it in json.loads((e.wb / "state" / "plan.json").read_text(encoding="utf-8"))["items"]}
        self.assertEqual((plan["python313"]["tag"], plan["python313"]["version"]), ("works", "3.14.2"))
        self.assertIn("3.14.2", plan["python313"]["note"])
        self.assertFalse([c for c in e.calls("winget") if "Python.Python.3.13" in c["argv"]], "3.13 is not installed")
        self.assertNotIn("Python.Python.3.13", (e.wb / "state" / "workbench.winget").read_text(encoding="utf-8"))
        venv = [c["argv"][:4] for c in e.calls("venv")]
        self.assertEqual((len(venv), venv[0]), (1, ["py", "-3.14", "-m", "venv"]), "the venv is made from it")
        e = self.env(scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"], "py_versions": ["3.13.15", "3.14.2"]},
                     preinstalled=("Python.Python.3.13",))
        e.clear_calls()
        e.run("run", code=0)
        venv = [c["argv"][:4] for c in e.calls("venv")]
        self.assertEqual(venv[0], ["py", "-3.13", "-m", "venv"], "with both installed, 3.13 is preferred")
        e = self.env(scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"], "py_versions": ["3.12.9"]},
                     preinstalled=("Python.Python.3.13",))
        e.run("plan", code=0)
        plan = {it["item"]: it for it in json.loads((e.wb / "state" / "plan.json").read_text(encoding="utf-8"))["items"]}
        self.assertEqual(plan["python313"]["tag"], "no-admin", "no accepted Python: 3.13 is installed")
        self.assertIn("Python.Python.3.13", (e.wb / "state" / "workbench.winget").read_text(encoding="utf-8"))
        e.run("run", code=4)
        failed = {x["item"]: x["error"] for x in e.state()["failed"]}
        self.assertIn("no Python 3.13 or 3.14 was found", failed["knowledge"])

    def test_lying_winget_is_a_verify_failure(self):
        e = self.env(scenario={"lie": True, "wsl": "installed", "distros": ["Ubuntu-24.04"]})
        e.run("run", code=4)
        failed = {x["item"]: x["error"] for x in e.state()["failed"]}
        self.assertIn("git", failed)
        self.assertIn("verify mismatch", failed["git"])

    def test_denial_is_a_hard_stop(self):
        e = self.env(scenario={"configure_rc": 0x8A15003A, "wsl": "installed", "distros": ["Ubuntu-24.04"]},
                     preinstalled=("Python.Python.3.13",))
        e.run("run", code=3)
        user_installs = [x for x in e.calls("winget") if x["argv"][0] == "install" and "user" in x["argv"]]
        self.assertEqual(user_installs, [], "no per-package fallback after a denial")
        self.assertIn("git", {x["item"] for x in e.state()["ask_it"]})

    def test_configure_unavailable_falls_back_per_package(self):
        e = self.env(scenario={"configure_rc": 0x8A150002, "wsl": "installed", "distros": ["Ubuntu-24.04"]})
        e.run("run", code=0)
        c = e.calls()
        ids = [x["argv"][2] for x in c if x["tool"] == "winget" and x["argv"][0] == "install" and "user" in x["argv"]]
        self.assertIn("Git.Git", ids)
        self.assertIn("Python.Python.3.13", ids)
        for i, x in enumerate(c):
            if x["tool"] == "winget" and x["argv"][0] == "install":
                self.assertTrue(any(y["tool"] == f"exe:{IDS[x['argv'][2]][0]}" for y in c[i + 1:]))

    def test_policy_blocks_become_ask_it(self):
        e = self.env(registry={S.WSL_POLICY: {"AllowWSL": 0}, S.APPINSTALLER: {"EnableWindowsPackageManagerConfiguration": 0}})
        e.run("run", code=3)
        asks = {x["item"]: x["text"] for x in e.state()["ask_it"]}
        self.assertIn("wsl", asks)
        self.assertIn("winget-configure", asks)
        self.assertFalse([x for x in e.calls("wsl") if x["argv"][:1] == ["--install"]])
        self.assertFalse([x for x in e.calls("winget") if x["argv"][0] == "configure"])
        self.assertTrue([x for x in e.calls("winget") if x["argv"][0] == "install"])
        self.assertEqual({k: v for k, v in e.registry().items() if "olicies" in k}, {
            k: v for k, v in e.registry_before.items() if "olicies" in k}, "policy keys are read, never written")

    def test_reboot_and_resume_from_a_long_profile_path(self):
        kit = mini_kit(Path(tempfile.mkdtemp(prefix="wb-long-")).joinpath(
            *[f"a rather long folder name number {i}" for i in range(4)], "kit"))
        self.addCleanup(shutil.rmtree, kit.parents[4], True)
        e = FakeEnv(kit=kit, scenario={"wsl": "absent", "net_fail": 2}, probe=probe_json(admin=True))
        self.addCleanup(e.close)
        e.run("run", code=5)
        st = e.state()
        self.assertEqual((st["phase"], st["reboot_pending"], st["exit_code"]), ("reboot-wait", True, 5))
        runonce = {k.lower(): v for k, v in e.registry().items()}[S.RUNONCE_KEY.lower()][S.RUNONCE_NAME][0]
        self.assertLessEqual(len(runonce), 260)
        self.assertGreater(len(f'"{sys.executable}" "{kit / "bootstrap" / "setup.py"}" resume'), 260, "the test path is long")
        self.assertTrue(runonce.endswith(" resume"))
        self.assertTrue([x for x in e.calls("wsl") if x["argv"][:2] == ["--install", "--no-distribution"]])
        e.set_fake_state(wsl="installed")       # the reboot happened
        e.run("resume", code=0)
        self.assertGreaterEqual(len([x for x in e.calls("curl") if "--head" in x["argv"]]), 3, "waited for network")
        self.assertTrue([x for x in e.calls("wsl") if x["argv"][:4] == ["--install", "-d", "Ubuntu-24.04", "--no-launch"]])
        self.assertIsNone(I.reg_get(S.RUNONCE_KEY, S.RUNONCE_NAME) if False else
                          {k.lower(): v for k, v in e.registry().items()}[S.RUNONCE_KEY.lower()].get(S.RUNONCE_NAME))
        self.assertTrue((e.home / ".wslconfig").exists())

    def test_undo_config_removes_what_setup_recorded(self):
        e = self.env(scenario={"wsl": "absent"}, probe=probe_json(admin=False, tls=True))
        e.run("run", "--with", "nightly", code=3)             # no admin: node through fnm, WSL becomes an IT ask
        shims = e.wb / "bin"
        self.assertTrue((shims / "npm.cmd").exists())
        path = {k.lower(): v for k, v in e.registry().items()}["hkcu\\environment"]["Path"]
        self.assertEqual(path[1], 2, "REG_EXPAND_SZ kept")
        self.assertIn(str(shims), path[0])
        self.assertTrue(path[0].startswith(r"%LOCALAPPDATA%\Tools"), "existing entries kept unexpanded")
        e.set_probe(probe_json(admin=True, tls=True))         # a second run that reaches the reboot step
        e.run("run", code=5)
        self.assertIn(S.RUNONCE_NAME, {k.lower(): v for k, v in e.registry().items()}[S.RUNONCE_KEY.lower()])
        dry = e.run("undo-config", code=0).stdout
        self.assertIn("would:", dry)
        e.run("undo-config", "--apply", code=0)
        reg = {k.lower(): v for k, v in e.registry().items()}
        env = {k.lower(): v for k, v in reg["hkcu\\environment"].items()}
        self.assertNotIn("node_use_system_ca", env)
        self.assertNotIn("uv_system_certs", env)
        self.assertEqual(env["path"][0], r"%LOCALAPPDATA%\Tools")
        self.assertNotIn(S.RUNONCE_NAME, reg[S.RUNONCE_KEY.lower()])
        self.assertFalse((e.dir / "tasks" / "_claude-workbench_knowledge-refresh.xml").exists())
        self.assertEqual(json.loads((e.dir / "state.json").read_text())["git"], {})
        self.assertFalse((shims / "npm.cmd").exists())

    def test_probe_comes_from_the_capability_report(self):
        kit = mini_kit(Path(tempfile.mkdtemp(prefix="wb-probe-")) / "kit")
        self.addCleanup(shutil.rmtree, kit.parent, True)
        (kit / "bootstrap" / "probe.py").write_text(
            "import json, os, sys, time\nfrom pathlib import Path\n"
            "open(Path(os.environ['WB_FAKE_DIR']) / 'calls.jsonl', 'a').write(json.dumps({'tool': 'probe', 'argv': sys.argv[1:], "
            "'t': time.time(), 'env': {}}) + '\\n')\n"
            f"Path(sys.argv[sys.argv.index('--out') + 1], 'probe.json').write_text(json.dumps({json.dumps(probe_json(admin=False))}))\n",
            encoding="utf-8")
        e = FakeEnv(kit=kit)
        self.addCleanup(e.close)
        del e.env["WORKBENCH_PROBE_JSON"]
        sd = e.wb / "state"
        sd.mkdir(parents=True)
        S.jwrite(sd / "probe-pre.json", probe_json(admin=True))
        S.jwrite(sd / "capability-pre.json", {"version": 1, "phase": "pre", "probe": str(sd / "probe-pre.json")})
        e.run("plan", code=0)
        self.assertEqual(e.calls("probe"), [], "the report's probe is reused: no second probe run")
        self.assertTrue(json.loads((sd / "plan.json").read_text(encoding="utf-8"))["admin_capable"])
        (sd / "capability-pre.json").unlink()
        e.run("plan", code=0)
        self.assertEqual(len(e.calls("probe")), 1, "no report: the probe runs once")
        self.assertFalse(json.loads((sd / "plan.json").read_text(encoding="utf-8"))["admin_capable"])

    def test_undo_leaves_another_installs_task_and_runonce(self):
        e = self.env()
        e.reg.write_text(json.dumps({**e.registry(), S.RUNONCE_KEY: {S.RUNONCE_NAME: ["x", 1]}}))
        tasks = e.dir / "tasks"
        tasks.mkdir()
        (tasks / "_claude-workbench_knowledge-refresh.xml").write_text("<Task/>", encoding="utf-16")
        e.run("undo-config", "--apply", code=0)       # this install's ledger recorded neither
        self.assertIn(S.RUNONCE_NAME, e.registry()[S.RUNONCE_KEY])
        self.assertTrue((tasks / "_claude-workbench_knowledge-refresh.xml").exists())
        self.assertFalse([x for x in e.calls("schtasks") if x["argv"][0] == "/Delete"])

    def test_second_runner_is_refused_while_locked(self):
        e = self.env()
        (e.wb / "state").mkdir(parents=True, exist_ok=True)
        (e.wb / "state" / "setup.lock").write_text(str(os.getpid()))
        self.assertIn("already running", e.run("run", code=2).stdout)
        (e.wb / "state" / "setup.lock").write_text("999999")      # a dead pid: stale, taken over
        e.run("plan", code=0)

    def test_detached_run_and_status_wait(self):
        e = self.env(scenario={"sleep": 4, "wsl": "installed", "distros": ["Ubuntu-24.04"]})
        e.run("run", "--detach", code=0)
        end = time.time() + 60
        while time.time() < end and not (e.wb / "state" / "setup-state.json").exists():
            time.sleep(0.2)
        while time.time() < end and e.state().get("phase") != "install":
            time.sleep(0.1)
        t0 = time.time()
        st = json.loads(e.run("status", "--json", "--wait", "40").stdout)
        self.assertLess(time.time() - t0, 30, "--wait returned on the phase change, not the timeout")
        self.assertNotEqual(st["phase"], "install")
        self.assertNotEqual(e.state().get("pid"), os.getpid())
        self.assertEqual(e.wait_done()["exit_code"], 0)

    def test_doctor_never_creates_a_missing_knowledge_index(self):
        e = self.env()
        e.index.unlink()                                     # a machine where setup has not built the index yet
        rows = {x["check"]: x for x in json.loads(e.run("doctor", "--json").stdout)["rows"]}
        self.assertEqual(rows["knowledge index"]["status"], "WARN")
        self.assertIn("no index yet", rows["knowledge index"]["detail"])
        self.assertFalse(e.index.exists(), "opening a missing index through find status would create it")

    def test_doctor_exit_codes(self):
        e = self.env()
        sd = e.wb / "state"
        sd.mkdir(parents=True, exist_ok=True)
        S.jwrite(sd / "setup-state.json", {"phase": "done", "failed": [], "ask_it": []})
        S.jwrite(sd / "guard-heartbeat.json", {"version": 1, "last_fired": S.now(), "sessions_since_fire": 0, "fired_total": 4})
        S.jwrite(sd / "backup.json", {"last": S.now(), "path": "x.zip"})
        r = e.run("doctor", "--json")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(json.loads(r.stdout)["exit_code"], 0)
        S.jwrite(sd / "guard-heartbeat.json", {"version": 1, "last_fired": S.now(), "sessions_since_fire": 5, "fired_total": 4})
        self.assertEqual(e.run("doctor").returncode, 2, "guards silent for 5 sessions is an error")
        S.jwrite(sd / "guard-heartbeat.json", {"version": 1, "last_fired": S.now(), "sessions_since_fire": 0, "fired_total": 4})
        (sd / "backup.json").unlink()
        self.assertEqual(e.run("doctor").returncode, 1, "no backup yet is a warning")
        od = e.root / "OneDrive - Example Org"
        (od / "Workbench" / "kb" / "repo" / ".git").mkdir(parents=True)
        e.reg.write_text(json.dumps({**e.registry(), I.ONEDRIVE_ACCOUNTS + r"\Business3": {"UserFolder": str(od)}}))
        cfg = json.loads((e.wb / "config.json").read_text())
        cfg.update(data_root=I.fwd(od / "Workbench"), kb_root=I.fwd(od / "Workbench" / "kb"),
                   knowledge_db=I.fwd(od / "index.sqlite"))
        (e.wb / "config.json").write_text(json.dumps(cfg))
        S.jwrite(sd / "backup.json", {"last": S.now(), "path": "x.zip"})
        r = e.run("doctor", "--json", "--bundle", str(e.root / "bundle.zip"))
        self.assertEqual(r.returncode, 2)
        fails = [x["check"] for x in json.loads(r.stdout[:r.stdout.rindex("}") + 1])["rows"] if x["status"] == "FAIL"]
        self.assertIn("placement: knowledge index", fails)
        self.assertIn("placement: git in OneDrive", fails)
        names = zipfile.ZipFile(e.root / "bundle.zip").namelist()
        self.assertIn("doctor.json", names)
        self.assertFalse([n for n in names if n.lower().endswith(".md")], "never USER.md or KB notes")

    def test_backup_restore_round_trip(self):
        e = self.env()
        kb = e.home / "Workbench" / "kb"
        (kb / "notes" / "topic").mkdir(parents=True)
        (kb / "notes" / "topic" / "a.md").write_text("# a\nbody\n", encoding="utf-8")
        (kb / "index.sqlite").write_bytes(b"not backed up")
        (e.wb / "USER.md").write_text("me\n", encoding="utf-8")
        (e.ch / "settings.json").write_text('{"env": {"TOKEN_X": "abc"}, "model": "m"}', encoding="utf-8")
        out = e.run("backup", code=0).stdout
        self.assertRegex(out, r"in \d+\.\d s")
        z = next((e.home / "Workbench" / "backup").glob("workbench-backup-*.zip"))
        names = zipfile.ZipFile(z).namelist()
        self.assertIn("KB/notes/topic/a.md", names)
        self.assertNotIn("KB/index.sqlite", names)
        self.assertNotIn("abc", zipfile.ZipFile(z).read("CH/settings.redacted.json").decode())
        dst = e.root / "restored"
        out = e.run("restore", str(z), "--to", str(dst), code=0).stdout
        self.assertRegex(out, r"in \d+\.\d s")
        for arc, src in (("KB/notes/topic/a.md", kb / "notes/topic/a.md"), ("WB/USER.md", e.wb / "USER.md"),
                         ("WB/config.json", e.wb / "config.json")):
            self.assertEqual(hashlib.sha256((dst / arc).read_bytes()).hexdigest(), hashlib.sha256(src.read_bytes()).hexdigest())
        self.assertIn("would restore", e.run("restore", str(z), code=0).stdout)
        (e.wb / "USER.md").write_text("newer\n", encoding="utf-8")
        os.utime(e.wb / "USER.md", (time.time() + 100, time.time() + 100))
        self.assertIn("newer than the backup", e.run("restore", str(z), "--apply", code=0).stdout)
        self.assertEqual((e.wb / "USER.md").read_text(encoding="utf-8"), "newer\n")
        e.run("restore", str(z), "--apply", "--force", code=0)
        self.assertEqual((e.wb / "USER.md").read_text(encoding="utf-8"), "me\n")
        self.assertTrue(json.loads((e.wb / "state" / "backup.json").read_text())["path"].endswith(".zip"))


# ── update (U1), the Playwright CLI and ctx ─────────────────────────────────────────────────────────────────────
def older(**texts):
    """Scenario ids with some tools installed at an older version: older(**{"GitHub.cli": "gh version 2.40.0 (stable)"})."""
    return {**IDS, **{wid: [IDS[wid][0], text] for wid, text in texts.items()}}


GH_OLD = older(**{"GitHub.cli": "gh version 2.40.0 (stable)"})
GIT_PWSH_OLD = older(**{"Git.Git": "git version 2.40.0", "Microsoft.PowerShell": "PowerShell 7.3.0"})


def mine(pid, **kw):
    """A ledger entry for a tool this kit installed."""
    return {"kind": "package", "id": pid, "source": "winget", "scope": "user", "version": "1.0.0", "key": "pkg:" + pid,
            "at": S.now(), **kw}


def seed(e, entries=(), **options):
    """The ledger and the remembered run options a previous setup run would have left."""
    S.jwrite(e.wb / "state" / "provision-ledger.json", {"version": 1, "entries": list(entries)})
    if options:
        S.jwrite(e.wb / "state" / "setup-state.json", {"options": {"with": [], "no_nightly": False, "no_update": False, **options}})


def update_doc(e):
    return json.loads((e.wb / "state" / "update.json").read_text(encoding="utf-8"))


def upgrades(e):
    return [c["argv"] for c in e.calls("winget") if c["argv"][0] == "upgrade"]


class UpdateUnits(unittest.TestCase):
    def test_every_package_has_a_pin_and_the_four_in_use_tools_are_flagged(self):
        for p in PACKAGES:
            self.assertRegex(p["pin"], r"^\d+\.\d+(\.\d+)?$", p["id"])
            if p["source"] == "github-release":
                self.assertIn("/v" + p["pin"] + "/", p["url"], p["id"] + ": the pin is the version of the pinned URL")
        self.assertEqual({p["id"] for p in PACKAGES if p.get("in_use")}, {"claude", "git", "pwsh", "node"})
        cli = next(p for p in PACKAGES if p["id"] == "playwright-cli")
        self.assertEqual((cli["source"], cli["npm"], cli["scope"], cli["admin"], cli["optional_with"], cli["hosts"]),
                         ("npm", "@playwright/cli", "user", False, None, ["registry.npmjs.org"]))
        self.assertEqual(cli["verify"], ["playwright-cli", "--version"])
        ctx_row = next(p for p in PACKAGES if p["id"] == "ctx")
        self.assertEqual((ctx_row["source"], ctx_row["optional_with"], ctx_row["verify"]), ("github-release", "ctx", ["ctx", "--version"]))

    def test_versions_compare_as_numbers(self):
        self.assertLess(S.vkey("2.9.0"), S.vkey("2.55.0"))
        self.assertLess(S.vkey("2.55.0"), S.vkey("2.55.0.windows.3"))
        self.assertEqual(S.vkey(None), ())
        self.assertEqual(S.vkey("git version 2.55.0.windows.3"), (2, 55, 0, 3))
        self.assertEqual(S.vkey("v24.19.0"), (24, 19, 0))

    def test_the_commands_carry_the_documented_flags(self):
        gh = next(p for p in PACKAGES if p["id"] == "gh")
        pinned = S.winget_cmd(gh, "user", "2.102.0")
        self.assertEqual(pinned[:7], ["winget", "upgrade", "--id", "GitHub.cli", "-e", "--source", "winget"])
        self.assertEqual(pinned[pinned.index("--version") + 1], "2.102.0")
        self.assertEqual(pinned[pinned.index("--scope") + 1], "user")
        for flag in ("--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"):
            self.assertIn(flag, pinned)
        self.assertNotIn("--version", S.winget_cmd(gh, "user", None), "the newest version names no version")
        cli = next(p for p in PACKAGES if p["id"] == "playwright-cli")
        self.assertEqual(S.npm_cmd(cli, "0.1.22"), ["npm", "install", "-g", "@playwright/cli@0.1.22", "--ignore-scripts",
                                                    "--no-audit", "--no-fund"])
        self.assertEqual(S.npm_cmd(cli, None, "P")[-2:], ["--prefix", "P"])
        self.assertIn("@playwright/cli@latest", S.npm_cmd(cli, None))

    def test_a_tool_with_its_own_updater_prints_that_command_instead_of_winget(self):
        class Fake:
            with_ = set()

            def verify(self, p):
                return "works", "2.1.200"
        claude = {**next(p for p in PACKAGES if p["id"] == "claude"), "update_argv": ["claude", "update"]}
        led = {"claude": {"kind": "package", "id": "claude", "scope": "user"}}
        row = S.update_row(Fake(), claude, led, False)
        self.assertEqual((row["action"], row["command"]), ("deferred", S.show(["claude", "update"])), "in use: printed, never run")
        plain = {k: v for k, v in claude.items() if k != "update_argv"}
        self.assertIn("winget", S.update_row(Fake(), plain, led, False)["command"])

    def test_there_is_no_elevation_path_in_setup(self):
        src = (HERE / "setup.py").read_text(encoding="utf-8").lower()
        for bad in ("run" + "as", "-verb " + "run", "--scope " + "machine", "start-process"):
            self.assertNotIn(bad, src)

    def test_the_updates_doctor_row(self):
        self.assertEqual(S.updates_row(None)[0], "INFO")
        self.assertEqual(S.updates_row({"items": [{"id": "git", "action": "current"}, {"id": "jq", "action": "it-managed"}]})[0], "OK")
        st, detail = S.updates_row({"items": [{"id": "git", "action": "deferred"}, {"id": "gh", "action": "failed"}]})
        self.assertEqual(st, "WARN")
        self.assertIn("gh", detail)
        self.assertIn("git", detail)

    def test_requirement_pins_ignore_everything_else(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "r.txt"
            f.write_text("# c\nmarkitdown[docx,pdf]==0.1.8\nFast_Embed==0.9.0 ; python_version>'3'\nnumpy>=2\n-r other.txt\n", encoding="utf-8")
            self.assertEqual(S.req_pins(f), {"markitdown": "0.1.8", "fast-embed": "0.9.0"})


@WINDOWS_ONLY
class UpdateFlows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wb-kit-"))
        cls.kit = mini_kit(cls.tmp / "kit")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def env(self, **kw):
        kw.setdefault("scenario", {"wsl": "installed", "distros": ["Ubuntu-24.04"]})
        e = FakeEnv(kit=self.kit, **kw)
        self.addCleanup(e.close)
        e.clear_calls()                                                  # the fixture's own preinstalls are not setup's calls
        return e

    def test_check_changes_nothing_reports_it_managed_and_writes_ip3(self):
        e = self.env(scenario={"ids": GH_OLD}, preinstalled=("GitHub.cli", "Git.Git"))     # installed by "IT": no ledger entry
        e.clear_calls()                                                                     # the fixture's own installs
        r = e.run("update", "--check", "--json", code=0)
        doc = json.loads(r.stdout)
        self.assertEqual((doc["version"], sorted(doc)), (1, ["generated", "items", "version"]))
        self.assertEqual(doc, update_doc(e))
        self.assertTrue((e.wb / "state" / "update.md").is_file())
        rows = {x["id"]: x for x in doc["items"]}
        self.assertEqual(sorted(rows), ["gh", "git"], "only installed tools get a row")
        for x in rows.values():
            self.assertEqual(sorted(x), ["action", "after", "before", "command", "id", "note", "target"])
            self.assertEqual(x["action"], "it-managed")
            self.assertIn(x["action"], S.UPDATE_ACTIONS)
        self.assertEqual((rows["gh"]["before"], rows["gh"]["target"]), ("2.40.0", "2.102.0"))
        self.assertEqual(upgrades(e), [])
        self.assertEqual(installs(e), [])

    def test_only_what_the_kit_installed_moves_and_only_to_the_pin(self):
        e = self.env(scenario={"ids": older(**{"GitHub.cli": "gh version 2.40.0 (stable)", "jqlang.jq": "jq-1.5.0"})},
                     preinstalled=("GitHub.cli", "jqlang.jq"))
        seed(e, [mine("gh", version="2.40.0")])                       # jq is IT's: no ledger entry
        e.run("update", code=0)
        up = upgrades(e)
        self.assertEqual(len(up), 1, up)
        self.assertEqual(up[0][up[0].index("--id") + 1], "GitHub.cli")
        self.assertEqual(up[0][up[0].index("--version") + 1], "2.102.0", "the pin, never the newest")
        rows = {x["id"]: x for x in update_doc(e)["items"]}
        self.assertEqual((rows["gh"]["action"], rows["gh"]["before"], rows["gh"]["after"]), ("upgraded", "2.40.0", "2.102.0"))
        self.assertEqual((rows["jq"]["action"], rows["jq"]["before"], rows["jq"]["after"]), ("it-managed", "1.5.0", None))
        led = {x["id"]: x for x in json.loads((e.wb / "state" / "provision-ledger.json").read_text())["entries"]}
        self.assertEqual(led["gh"]["version"], "2.102.0")
        e.clear_calls()
        e.run("update", code=0)
        self.assertEqual(upgrades(e), [], "at the pin now: nothing runs again")
        self.assertEqual({x["id"]: x["action"] for x in update_doc(e)["items"]}["gh"], "current")

    def test_exit_zero_with_the_version_unchanged_is_a_failure(self):
        e = self.env(scenario={"ids": GH_OLD, "upgrade_lie": True}, preinstalled=("GitHub.cli",))
        seed(e, [mine("gh", version="2.40.0")])
        e.run("update", code=4)
        row = next(x for x in update_doc(e)["items"] if x["id"] == "gh")
        self.assertEqual((row["action"], row["after"]), ("failed", "2.40.0"))
        self.assertIn("2.102.0", row["note"])
        self.assertIn("update:gh", {x["item"] for x in e.state()["failed"]})

    def test_tools_in_use_are_deferred_with_their_command_and_never_replaced(self):
        e = self.env(scenario={"ids": GIT_PWSH_OLD}, preinstalled=("Git.Git", "Microsoft.PowerShell"))
        seed(e, [mine("git", version="2.40.0"), mine("pwsh", version="7.3.0")])
        e.run("update", code=0)
        self.assertEqual(upgrades(e), [])
        rows = {x["id"]: x for x in update_doc(e)["items"]}
        for pid, wid in (("git", "Git.Git"), ("pwsh", "Microsoft.PowerShell")):
            self.assertEqual(rows[pid]["action"], "deferred")
            self.assertIn(f"--id {wid} -e", rows[pid]["command"])
            self.assertIn("--version", rows[pid]["command"])
            self.assertIn("in use", rows[pid]["note"])
        self.assertIn(rows["git"]["command"], (e.wb / "state" / "update.md").read_text(encoding="utf-8"))

    def test_a_running_program_answer_from_winget_defers_too(self):
        e = self.env(scenario={"ids": GH_OLD, "upgrade_rc": {"GitHub.cli": 0x8A150101}}, preinstalled=("GitHub.cli",))
        seed(e, [mine("gh", version="2.40.0")])
        e.run("update", code=0)
        self.assertEqual(len(upgrades(e)), 1, "not retried")
        self.assertEqual(next(x for x in update_doc(e)["items"] if x["id"] == "gh")["action"], "deferred")

    def test_a_denial_is_asked_of_it_and_never_retried(self):
        e = self.env(scenario={"ids": GH_OLD, "upgrade_rc": {"GitHub.cli": 0x8A15003A}}, preinstalled=("GitHub.cli",))
        seed(e, [mine("gh", version="2.40.0")])
        e.run("update", code=3)
        self.assertEqual(len(upgrades(e)), 1)
        self.assertEqual(next(x for x in update_doc(e)["items"] if x["id"] == "gh")["action"], "denied")
        self.assertIn("gh", {x["item"] for x in e.state()["ask_it"]})

    def test_newest_only_with_update_latest_and_it_is_not_remembered(self):
        e = self.env(scenario={"ids": GH_OLD, "latest": {"GitHub.cli": "2.150.0"}}, preinstalled=("GitHub.cli",))
        seed(e, [mine("gh", version="2.40.0")], **{"with": ["update-latest"]})
        e.run("update", code=0)
        up = upgrades(e)
        self.assertEqual(len(up), 1)
        self.assertNotIn("--version", up[0])
        self.assertEqual(next(x for x in update_doc(e)["items"] if x["id"] == "gh")["after"], "2.150.0")
        e.set_scenario(upgrade_rc={"GitHub.cli": 0x8A15002B})       # nothing newer exists
        e.clear_calls()
        e.run("update", code=0)
        row = next(x for x in update_doc(e)["items"] if x["id"] == "gh")
        self.assertEqual((row["action"], row["note"]), ("current", "already the newest version"))

    def test_without_update_latest_the_pin_is_the_target_even_when_a_newer_one_exists(self):
        e = self.env(scenario={"ids": GH_OLD, "latest": {"GitHub.cli": "2.150.0"}}, preinstalled=("GitHub.cli",))
        seed(e, [mine("gh", version="2.40.0")])
        e.run("update", code=0)
        self.assertEqual(next(x for x in update_doc(e)["items"] if x["id"] == "gh")["after"], "2.102.0")

    def test_at_the_pin_or_newer_nothing_runs(self):
        e = self.env(scenario={"ids": older(**{"astral-sh.uv": "uv 0.99.0"})}, preinstalled=("GitHub.cli", "astral-sh.uv"))
        seed(e, [mine("gh", version="2.102.0"), mine("uv", version="0.12.21")])
        e.run("update", code=0)
        self.assertEqual(upgrades(e), [])
        rows = {x["id"]: x for x in update_doc(e)["items"]}
        self.assertEqual((rows["gh"]["action"], rows["uv"]["action"]), ("current", "current"))
        self.assertIn("newer than the tested pin", rows["uv"]["note"])

    def test_a_policy_block_skips_the_update(self):
        e = self.env(scenario={"ids": GH_OLD}, preinstalled=("GitHub.cli",), registry={S.APPINSTALLER: {"EnableAppInstaller": 0}})
        seed(e, [mine("gh", version="2.40.0")])
        e.run("update", code=0)
        self.assertEqual(upgrades(e), [])
        self.assertEqual(next(x for x in update_doc(e)["items"] if x["id"] == "gh")["action"], "skipped-policy")

    def test_a_machine_wide_install_is_never_elevated(self):
        e = self.env(scenario={"ids": older(**{"Microsoft.VisualStudioCode": "1.100.0"})}, preinstalled=("Microsoft.VisualStudioCode",))
        seed(e, [mine("code", scope="machine", version="1.100.0")])
        e.run("update", code=0)
        self.assertEqual(upgrades(e), [])
        row = next(x for x in update_doc(e)["items"] if x["id"] == "code")
        self.assertEqual(row["action"], "deferred")
        self.assertIn("never elevates", row["note"])

    def test_check_defers_what_would_change_and_runs_nothing(self):
        e = self.env(scenario={"ids": GH_OLD}, preinstalled=("GitHub.cli",))
        seed(e, [mine("gh", version="2.40.0")])
        e.run("update", "--check", code=0)
        self.assertEqual(upgrades(e), [])
        row = next(x for x in update_doc(e)["items"] if x["id"] == "gh")
        self.assertEqual(row["action"], "deferred")
        self.assertIn("check only", row["note"])

    def test_the_run_installs_into_the_ledger_and_leaves_it_tools_alone(self):
        e = self.env(preinstalled=("Python.Python.3.13",))                # IT put Python there before setup ran
        e.run("run", code=0)
        led = {x["id"]: x for x in json.loads((e.wb / "state" / "provision-ledger.json").read_text())["entries"] if x["kind"] == "package"}
        self.assertIn("git", led)
        self.assertEqual((led["git"]["source"], led["git"]["scope"]), ("winget", "user"))
        self.assertEqual(led["node"]["scope"], "machine")
        self.assertNotIn("python313", led, "a tool setup did not install is never taken over")
        rows = {x["id"]: x for x in update_doc(e)["items"]}
        self.assertEqual(rows["python313"]["action"], "it-managed")
        self.assertEqual(rows["git"]["action"], "current", "a fresh install is already at the pin")
        self.assertEqual(upgrades(e), [])
        self.assertIn("== phase update", (e.wb / "state" / "setup.log").read_text(encoding="utf-8"))

    def test_no_update_skips_the_phase_and_the_plan_says_so(self):
        e = self.env()
        e.run("run", "--no-update", code=0)
        self.assertNotIn("== phase update", (e.wb / "state" / "setup.log").read_text(encoding="utf-8"))
        self.assertFalse((e.wb / "state" / "update.json").exists())
        plan = {x["item"]: x for x in json.loads((e.wb / "state" / "plan.json").read_text(encoding="utf-8"))["items"]}
        self.assertEqual((plan["update"]["tag"], plan["update"]["note"]), ("opt-in-off", "--no-update"))
        self.assertTrue(e.state()["options"]["no_update"])
        e2 = self.env()
        e2.run("plan", code=0)
        plan = {x["item"]: x for x in json.loads((e2.wb / "state" / "plan.json").read_text(encoding="utf-8"))["items"]}
        self.assertEqual(plan["update"]["tag"], "no-admin")

    def test_the_new_flags_are_accepted_on_the_command_line(self):
        e = self.env()
        plan = lambda: {x["item"]: x for x in json.loads((e.wb / "state" / "plan.json").read_text(encoding="utf-8"))["items"]}  # noqa: E731
        e.run("plan", "--no-update", code=0)
        self.assertEqual((plan()["update"]["tag"], plan()["update"]["note"]), ("opt-in-off", "--no-update"))
        e.run("plan", "--with", "ctx,update-latest", code=0)
        self.assertEqual(plan()["ctx"]["tag"], "no-admin")
        self.assertEqual((plan()["update"]["tag"], plan()["update"]["note"]), ("no-admin", "to the newest version (--with update-latest)"))
        e.run("update", "--with", "update-latest", code=0)               # takes the lock and saves the state
        self.assertTrue((e.wb / "state" / "setup-state.json").is_file())
        self.assertFalse((S.jload(e.wb / "state" / "setup-state.json", {}) or {}).get("options", {}).get("with"),
                         "a one-off update --with is not remembered for the next run")
        self.assertIn("unknown option", e.run("run", "--with", "nonsense", code=2).stdout)
        self.assertEqual(e.run("run", "--no-update", "--detach", code=0).returncode, 0)
        self.assertTrue(e.wait_done()["options"]["no_update"], "the detached runner got --no-update too")

    def test_plan_lists_the_new_items_with_known_tags(self):
        e = self.env()
        e.run("plan", code=0)
        plan = {x["item"]: x for x in json.loads((e.wb / "state" / "plan.json").read_text(encoding="utf-8"))["items"]}
        for item in ("playwright-cli", "ctx", "update"):
            self.assertIn(plan[item]["tag"], S.TAGS, item)
        self.assertEqual(plan["playwright-cli"]["tag"], "no-admin")
        self.assertEqual(plan["ctx"]["tag"], "opt-in-off")

    def test_venv_is_resynced_to_its_pins_and_newer_releases_are_report_only(self):
        e = self.env()
        e.run("run", code=0)                                               # builds the fake venv
        e.set_scenario(pip_list=[{"name": "fastembed", "version": "0.8.0"}])
        e.clear_calls()
        e.run("update", "--check", code=0)
        self.assertFalse([c for c in e.calls("pip") if "install" in c["argv"]], "--check installs nothing")
        row = next(x for x in update_doc(e)["items"] if x["id"] == "pip:fastembed")
        self.assertEqual((row["action"], row["before"], row["target"]), ("deferred", "0.8.0", "0.9.0"))
        e.run("update", code=4)                                            # the fake pip does not change the list: still drifted
        self.assertEqual(len([c for c in e.calls("pip") if "install" in c["argv"]]), 1)
        self.assertEqual(next(x for x in update_doc(e)["items"] if x["id"] == "pip:fastembed")["action"], "failed")
        e.set_scenario(pip_list=[{"name": "fastembed", "version": "0.9.0"}],
                       pip_outdated=[{"name": "fastembed", "version": "0.9.0", "latest_version": "0.10.0"},
                                     {"name": "transitive", "version": "1", "latest_version": "2"}])
        e.clear_calls()
        e.run("update", code=0)
        self.assertFalse([c for c in e.calls("pip") if "install" in c["argv"]])
        rows = {x["id"]: x for x in update_doc(e)["items"]}
        self.assertEqual(rows["pip:fastembed"]["action"], "current")
        self.assertIn("0.10.0", rows["pip:fastembed"]["note"])
        self.assertNotIn("pip:transitive", rows, "only packages the kit pins get a row")

    # ── the Playwright CLI ──
    def test_playwright_cli_installs_pinned_with_edge_and_undoes(self):
        e = self.env()
        e.run("run", code=0)
        npm = [c for c in e.calls("npm") if c["argv"][:1] == ["install"] and "-g" in c["argv"]]
        self.assertEqual(len(npm), 1)
        own = str(e.wb / "npm")
        self.assertEqual(npm[0]["argv"], ["install", "-g", "@playwright/cli@0.1.22", "--ignore-scripts", "--no-audit", "--no-fund",
                                          "--prefix", own])
        self.assertEqual(npm[0]["skip_dl"], "1")
        skills = [c for c in e.calls("exe:playwright-cli") if c["argv"][:1] == ["install"]]
        want = ["install", "--skills", "--global"]
        self.assertEqual([c["argv"] for c in skills], [want])
        self.assertEqual(skills[0]["skip_dl"], "1")
        cfg = json.loads((e.wb / "state" / "playwright-cli.config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg, {"browser": {"browserName": "chromium", "launchOptions": {"channel": "msedge", "headless": True}}})
        reg = {k.lower(): v for k, v in e.registry().items()}["hkcu\\environment"]
        self.assertEqual(reg[S.CLI_CONFIG_ENV][0], str(e.wb / "state" / "playwright-cli.config.json"))
        self.assertIn(own, reg["Path"][0], "the own prefix is on the user Path")
        led = [x for x in json.loads((e.wb / "state" / "provision-ledger.json").read_text())["entries"] if x.get("id") == "playwright-cli"]
        self.assertEqual((led[0]["source"], led[0]["npm"], led[0]["prefix"]), ("npm", "@playwright/cli", own))
        row = next(x for x in update_doc(e)["items"] if x["id"] == "playwright-cli")
        self.assertEqual(row["action"], "current")
        e.clear_calls()
        e.run("run", code=0)
        self.assertEqual([c for c in e.calls("npm") if "install" in c["argv"]], [], "second run: no install")
        e.run("undo-config", "--apply", code=0)
        un = [c["argv"] for c in e.calls("npm") if c["argv"][:1] == ["uninstall"]]
        want = ["uninstall", "-g", "@playwright/cli", "--prefix", own]
        self.assertEqual(un, [want])
        reg = {k.lower(): v for k, v in e.registry().items()}["hkcu\\environment"]
        self.assertNotIn(S.CLI_CONFIG_ENV, reg)
        self.assertNotIn(own, reg["Path"][0])
        self.assertFalse((e.wb / "state" / "playwright-cli.config.json").exists())
        self.assertFalse((e.wb / "npm").exists())

    def test_playwright_cli_uses_the_users_own_writable_prefix(self):
        e = self.env()
        mine_dir = e.root / "npm-global"
        e.set_scenario(npm_prefix=str(mine_dir))
        e.run("run", code=0)
        npm = [c["argv"] for c in e.calls("npm") if c["argv"][:1] == ["install"] and "-g" in c["argv"]]
        self.assertNotIn("--prefix", npm[0])
        self.assertTrue((mine_dir / "playwright-cli.cmd").exists())
        reg = {k.lower(): v for k, v in e.registry().items()}["hkcu\\environment"]
        self.assertIn(str(mine_dir), reg["Path"][0], "added to the user Path when it was not on it")
        self.assertFalse((e.wb / "npm").exists())

    def test_playwright_cli_headless_off_by_edge_policy_and_no_edge(self):
        e = self.env(probe=probe_json(headless=False))
        e.run("run", code=0)
        cfg = json.loads((e.wb / "state" / "playwright-cli.config.json").read_text(encoding="utf-8"))
        self.assertIs(cfg["browser"]["launchOptions"]["headless"], False)
        e2 = self.env(probe=probe_json(edge=None))
        e2.run("run", code=0)
        self.assertFalse((e2.wb / "state" / "playwright-cli.config.json").exists())
        self.assertNotIn(S.CLI_CONFIG_ENV, e2.registry()["HKCU\\Environment"])
        self.assertTrue([n for n in e2.state().get("notes", []) if "no Microsoft Edge" in n])

    def test_a_users_own_cli_config_variable_is_kept(self):
        e = self.env(registry={"HKCU\\Environment": {"Path": [r"%LOCALAPPDATA%\Tools", 2], S.CLI_CONFIG_ENV: ["D:/mine.json", 1]}})
        e.run("run", code=0)
        self.assertEqual(e.registry()["HKCU\\Environment"][S.CLI_CONFIG_ENV][0], "D:/mine.json")
        self.assertTrue([n for n in e.state().get("notes", []) if "already points at" in n])

    def test_without_node_the_cli_is_an_it_ask_and_npm_is_never_called(self):
        e = self.env(registry={S.APPINSTALLER: {"EnableAppInstaller": 0}}, probe=probe_json(admin=False))
        e.run("plan", code=0)
        plan = {x["item"]: x for x in json.loads((e.wb / "state" / "plan.json").read_text(encoding="utf-8"))["items"]}
        self.assertEqual(plan["node"]["tag"], "ask-IT")
        self.assertEqual(plan["playwright-cli"]["tag"], "ask-IT")
        self.assertIn("Node.js", plan["playwright-cli"]["note"])
        self.assertEqual([c for c in e.calls("npm")], [])

    def test_a_registry_refusal_is_a_denial_and_not_retried(self):
        e = self.env(scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"], "npm_rc": 1, "npm_out": "npm error code E403\n"})
        e.run("run", code=3)
        self.assertEqual(len([c for c in e.calls("npm") if c["argv"][:1] == ["install"] and "-g" in c["argv"]]), 1)
        self.assertIn("playwright-cli", {x["item"] for x in e.state()["ask_it"]})
        self.assertFalse(e.calls("exe:playwright-cli"), "no skills from a CLI that was not installed")

    def test_a_cli_other_than_the_pin_gets_no_skill(self):
        e = self.env(scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"], "npm_force": "0.1.30"})
        e.run("run", code=0)               # whatever npm installed, the skill text only ever comes from the tested version
        self.assertFalse([c for c in e.calls("exe:playwright-cli") if c["argv"][:1] == ["install"]])
        self.assertTrue([n for n in e.state().get("notes", []) if "not the tested 0.1.22" in n])
        self.assertEqual(next(x for x in update_doc(e)["items"] if x["id"] == "playwright-cli")["action"], "current",
                         "a newer CLI than the pin is left alone")

    def cli_update_env(self, **scenario):
        """An installed Playwright CLI at an old version that setup put there (ledger entry), npm answering per scenario."""
        ids = {**IDS, "npm:@playwright/cli": ["playwright-cli", "0.1.10"]}
        e = self.env(scenario={"ids": ids, **scenario})
        e.add_tool("playwright-cli", exe=True)
        e.set_scenario(npm_prefix=str(e.root / "npm-global"))
        seed(e, [mine("playwright-cli", source="npm", npm="@playwright/cli", version="0.1.10")])
        return e

    def test_the_cli_is_updated_through_npm_to_the_pin_by_its_own_version_call(self):
        e = self.cli_update_env()
        e.run("update", code=0)
        npm = [c for c in e.calls("npm") if c["argv"][:1] == ["install"]]
        self.assertEqual(len(npm), 1)
        self.assertEqual(npm[0]["argv"], ["install", "-g", "@playwright/cli@0.1.22", "--ignore-scripts", "--no-audit", "--no-fund"])
        self.assertEqual(npm[0]["skip_dl"], "1")
        row = next(x for x in update_doc(e)["items"] if x["id"] == "playwright-cli")
        self.assertEqual((row["action"], row["before"], row["after"]), ("upgraded", "0.1.10", "0.1.22"))
        e.clear_calls()
        e.run("update", code=0)
        self.assertEqual([c for c in e.calls("npm")], [], "at the pin now")

    def test_a_cli_update_that_changes_nothing_is_a_failure_and_a_refusal_is_never_retried(self):
        e = self.cli_update_env(npm_force="0.1.10")                   # npm exits 0 and the installed version stays old
        e.run("update", code=4)
        row = next(x for x in update_doc(e)["items"] if x["id"] == "playwright-cli")
        self.assertEqual((row["action"], row["after"]), ("failed", "0.1.10"))
        e = self.cli_update_env(npm_rc=1, npm_out="npm error code E403\n")
        e.run("update", code=3)
        self.assertEqual(len([c for c in e.calls("npm") if c["argv"][:1] == ["install"]]), 1)
        self.assertEqual(next(x for x in update_doc(e)["items"] if x["id"] == "playwright-cli")["action"], "denied")
        self.assertIn("playwright-cli", {x["item"] for x in e.state()["ask_it"]})
        e = self.cli_update_env(npm_rc=1, npm_out="npm error something else\n")
        e.run("update", code=4)
        self.assertEqual(next(x for x in update_doc(e)["items"] if x["id"] == "playwright-cli")["action"], "failed")

    # ── ctx ──
    def ctx_env(self, body="ctx-fixture-bytes", sha=None, **scenario):
        import hashlib as h
        kit = mini_kit(Path(tempfile.mkdtemp(prefix="wb-kit3-")) / "kit")
        self.addCleanup(shutil.rmtree, kit.parent, True)
        pk = json.loads((kit / "bootstrap" / "packages.json").read_text(encoding="utf-8"))
        for row in pk["packages"]:
            if row["id"] == "ctx":
                row["sha256"] = sha or h.sha256(body.encode()).hexdigest()
        (kit / "bootstrap" / "packages.json").write_text(json.dumps(pk), encoding="utf-8")
        e = FakeEnv(kit=kit, scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"], "curl_body": body, "curl_shim": ["ctx"],
                                       **scenario})
        self.addCleanup(e.close)
        return e

    def test_ctx_is_fetched_checksummed_switched_quiet_and_recorded(self):
        e = self.ctx_env()
        e.run("run", "--with", "ctx", code=0)
        dl = [c["argv"] for c in e.calls("curl") if "-o" in c["argv"]]
        self.assertEqual(len(dl), 1)
        self.assertEqual(dl[0][-1], "https://github.com/ctxrs/ctx/releases/download/v2.2.8/ctx-windows-x64.exe")
        self.assertIn("--proto", dl[0])
        self.assertEqual((e.wb / "bin" / "ctx.exe").read_bytes(), b"ctx-fixture-bytes")
        reg = e.registry()["HKCU\\Environment"]
        self.assertEqual([reg[k][0] for k in sorted(S.CTX_ENV)], [S.CTX_ENV[k] for k in sorted(S.CTX_ENV)])
        mode = [c for c in e.calls("exe:ctx") if c["argv"][-3:] == ["index", "mode", "manual"]]
        self.assertEqual(len(mode), 1)
        self.assertEqual(mode[0]["ctx_env"], S.CTX_ENV, "off before the first ctx run, in that very process")
        first = next(c for c in e.calls("exe:ctx"))
        self.assertEqual(first["ctx_env"], S.CTX_ENV, "the version check runs with the opt-outs too")
        led = [x for x in json.loads((e.wb / "state" / "provision-ledger.json").read_text())["entries"] if x.get("id") == "ctx"]
        self.assertEqual((led[0]["kind"], led[0]["source"]), ("package", "github-release"))
        self.assertEqual(next(x for x in update_doc(e)["items"] if x["id"] == "ctx")["action"], "current")
        e.run("undo-config", "--apply", code=0)
        self.assertFalse((e.wb / "bin" / "ctx.exe").exists())
        reg = e.registry()["HKCU\\Environment"]
        for k in S.CTX_ENV:
            self.assertNotIn(k, reg)

    def test_a_proxy_certificate_without_revocation_points_is_retried_once_best_effort_and_still_checksummed(self):
        e = self.ctx_env(curl_35=REVOCATION_ERR)
        e.run("run", "--with", "ctx", code=0)
        dl = [c["argv"] for c in e.calls("curl") if "-o" in c["argv"]]
        self.assertEqual(len(dl), 2)
        self.assertNotIn("--ssl-revoke-best-effort", dl[0])
        self.assertEqual(dl[1], ["--ssl-revoke-best-effort", *dl[0]], "the same command, with only that flag added")
        self.assertEqual((e.wb / "bin" / "ctx.exe").read_bytes(), b"ctx-fixture-bytes")
        self.assertIn("--ssl-revoke-best-effort", (e.wb / "state" / "setup.log").read_text(encoding="utf-8"))
        for c in e.calls("curl"):
            self.assertFalse({"-k", "--insecure", "--ssl-no-revoke"} & set(c["argv"]), c["argv"])
        rows = {x["check"]: x for x in json.loads(e.run("doctor", "--json").stdout)["rows"]}
        self.assertEqual(rows["TLS + network"]["status"], "WARN")
        self.assertIn("CRYPT_E_NO_REVOCATION_CHECK", rows["TLS + network"]["detail"])
        e = self.ctx_env(curl_35=REVOCATION_ERR, sha="0" * 64, curl_shim=[])     # the pinned checksum still decides
        e.run("run", "--with", "ctx", code=4)
        self.assertFalse((e.wb / "bin" / "ctx.exe").exists())
        self.assertIn("SHA-256 mismatch", {x["item"]: x["error"] for x in e.state()["failed"]}["ctx"])

    def test_any_other_tls_failure_is_not_retried(self):
        for err, always in (("SEC_E_UNTRUSTED_ROOT (0x80090325) - The certificate chain was issued by an authority that "
                             "is not trusted.", False), (REVOCATION_ERR, True)):
            e = self.ctx_env(curl_35=err, curl_35_always=always)
            e.run("run", "--with", "ctx", code=4)
            self.assertEqual(len([c for c in e.calls("curl") if "-o" in c["argv"]]), 1 if not always else 2, err)
            self.assertIn("download exit 35", {x["item"]: x["error"] for x in e.state()["failed"]}["ctx"])
            self.assertEqual(bool(e.state().get("tls_revocation")), always)

    def test_the_network_wait_retries_best_effort_too(self):
        e = self.env(scenario={"curl_35": REVOCATION_ERR})
        with mock.patch.dict(os.environ, e.env, clear=True):
            self.assertTrue(S.wait_network(S.Ctx(), budget_s=5))
        heads = [c["argv"] for c in e.calls("curl")]
        self.assertEqual([("--ssl-revoke-best-effort" in a, "--head" in a) for a in heads], [(False, True), (True, True)])

    def test_ctx_with_a_wrong_checksum_is_deleted_unused(self):
        e = self.ctx_env(sha="0" * 64, curl_shim=[])
        e.run("run", "--with", "ctx", code=4)
        self.assertFalse((e.wb / "bin" / "ctx.exe").exists())
        self.assertFalse(list((e.wb / "state" / "downloads").glob("ctx*")), "the download was deleted")
        self.assertIn("SHA-256 mismatch", {x["item"]: x["error"] for x in e.state()["failed"]}["ctx"])
        self.assertFalse([c for c in e.calls("exe:ctx")], "a binary that failed its checksum never runs")

    def test_ctx_is_not_kept_when_manual_indexing_cannot_be_set(self):
        e = self.ctx_env()
        e.set_scenario(ctx_exe=str(e.wb / "bin" / "ctx.exe"))
        # the fake `ctx index mode manual` must fail
        orig = e.dir / "fake.py"
        orig.write_text(orig.read_text(encoding="utf-8").replace(
            'if name == "git" and args[:2]', 'if name == "ctx" and args[-3:] == ["index", "mode", "manual"]: done(1)\n    if name == "git" and args[:2]', 1),
            encoding="utf-8")
        e.run("run", "--with", "ctx", code=4)
        self.assertFalse((e.wb / "bin" / "ctx.exe").exists())
        self.assertIn("index mode manual", {x["item"]: x["error"] for x in e.state()["failed"]}["ctx"])

    def test_ctx_off_by_default(self):
        e = self.env()
        e.run("run", code=0)
        self.assertFalse([c for c in e.calls("curl") if "-o" in c["argv"]])
        self.assertFalse((e.wb / "bin" / "ctx.exe").exists())

    # ── the doctor ──
    def test_doctor_reads_claude_doctor_through_the_bug_cards_and_shows_updates(self):
        e = self.env()
        sd = e.wb / "state"
        sd.mkdir(parents=True, exist_ok=True)
        S.jwrite(sd / "setup-state.json", {"phase": "done", "failed": [], "ask_it": []})
        S.jwrite(sd / "guard-heartbeat.json", {"version": 1, "last_fired": S.now(), "sessions_since_fire": 0, "fired_total": 4})
        S.jwrite(sd / "backup.json", {"last": S.now(), "path": "x.zip"})
        rows = lambda: {x["check"]: x for x in json.loads(e.run("doctor", "--json").stdout)["rows"]}  # noqa: E731
        r = rows()
        self.assertEqual(r["claude startup warnings"]["status"], "INFO", "claude is not installed here")
        self.assertEqual(r["updates"]["status"], "INFO")
        e.add_tool("claude")
        e.set_scenario(claude_doctor="Installation: ok\nfixture-startup-warning: something odd\nSearch: ok\n")
        r = rows()
        self.assertEqual(r["claude startup warnings"]["status"], "WARN")
        self.assertIn("card 12", r["claude startup warnings"]["detail"])
        calls = [c for c in e.calls("claude") if c["argv"] == ["doctor"]]
        self.assertTrue(calls)
        e.set_scenario(claude_doctor="Installation: ok\n")
        self.assertEqual(rows()["claude startup warnings"]["status"], "OK")
        e.set_scenario(claude_doctor="")
        self.assertEqual(rows()["claude startup warnings"]["status"], "INFO")
        S.jwrite(sd / "update.json", {"version": 1, "generated": S.now(), "items": [{"id": "git", "action": "deferred"}]})
        self.assertEqual(rows()["updates"]["status"], "WARN")
        out = e.run("doctor")
        self.assertEqual(out.returncode, 1, "WARN only: exit 1")



class DayOne(unittest.TestCase):
    """The knowledge-verify phase, doctor --deep and the backup changes, through whole runs (the checks are canned here:
    test_knowledge_verify.py tests them)."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wb-kit-"))
        cls.kit = mini_kit(cls.tmp / "kit")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def env(self, **kw):
        e = FakeEnv(kit=self.kit, **kw)
        self.addCleanup(e.close)
        return e

    def test_the_phase_sits_after_the_capture_runtime_and_before_the_full_refresh(self):
        self.assertEqual(S.PHASES[S.PHASES.index("capture-runtime") + 1], "knowledge-verify")
        self.assertEqual(S.PHASES[S.PHASES.index("knowledge-verify") + 1], "routing")

    @WINDOWS_ONLY
    def test_the_run_records_the_checks_then_starts_the_full_refresh(self):
        e = self.env(scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"]})
        e.run("run", code=0)
        log = (e.wb / "state" / "setup.log").read_text(encoding="utf-8")
        self.assertLess(log.index("== phase capture-runtime"), log.index("== phase knowledge-verify"))
        self.assertLess(log.index("== phase knowledge-verify"), log.index("== phase routing"))
        kvf = e.wb / "state" / "knowledge-verify.json"
        doc = json.loads(kvf.read_text(encoding="utf-8"))
        self.assertEqual((doc["summary"]["fail"], doc["kit_version"]), (0, I.VERSION))
        reqs = [c["argv"][c["argv"].index("-r") + 1].replace("\\", "/") for c in e.calls("pip") if "-r" in c["argv"]]
        self.assertEqual([r.split("/skills/")[1] for r in reqs], ["find/requirements.txt", "office-render/requirements.txt"])
        full = [c for c in e.calls("find") if c["argv"][:3] == ["refresh", "--all", "--detach"]]
        self.assertTrue(full)
        self.assertGreater(full[0]["t"], kvf.stat().st_mtime - 1, "the full refresh starts after the checks")

    @WINDOWS_ONLY
    def test_a_named_fail_fails_the_run_and_a_warning_with_an_ask_is_an_it_item(self):
        e = self.env(scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"]})
        e.set_verify(D3="FAIL")
        e.run("run", code=4)
        failed = {x["item"]: x["error"] for x in e.state()["failed"]}
        self.assertIn("D3", failed["knowledge-verify"])
        e.set_verify(D9=("WARN", "Please allow the model download."))
        e.run("run", code=3)
        st = e.state()
        self.assertFalse(st["failed"])
        self.assertIn({"item": "knowledge:find-build", "text": "Please allow the model download."}, st["ask_it"])

    def test_doctor_deep_exits_zero_on_warnings_and_two_only_on_a_named_fail(self):
        e = self.env()
        sd = e.wb / "state"
        sd.mkdir(parents=True, exist_ok=True)
        S.jwrite(sd / "setup-state.json", {"phase": "done", "failed": [], "ask_it": []})
        e.set_verify(D9="WARN", D23=("WARN", "Please allow headless mode."), D17="OPT-IN-OFF")
        self.assertEqual(e.run("doctor").returncode, 1, "plain doctor: no backup and no heartbeat are warnings")
        r = e.run("doctor", "--deep", "--json")
        self.assertEqual(r.returncode, 0, r.stdout[-2000:])
        out = json.loads(r.stdout)
        rows = {x["check"]: x for x in out["rows"]}
        self.assertEqual(rows["knowledge: find-build"]["status"], "WARN")
        self.assertEqual(rows["knowledge: capture"]["status"], "INFO")
        self.assertEqual(rows["knowledge: record"]["status"], "OK")
        self.assertEqual(rows["backup"]["status"], "WARN")
        self.assertEqual((out["exit_code"], out["knowledge_verify"]["fail"]), (0, 0))
        self.assertTrue((sd / "knowledge-verify.json").is_file())
        e.set_verify(D6="FAIL")
        r = e.run("doctor", "--deep", "--json")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(json.loads(r.stdout)["knowledge_verify"]["failing"], ["D6"])

    def test_doctor_deep_is_a_superset_a_regular_fail_row_exits_two_and_a_regular_warn_exits_zero(self):
        e = self.env()
        sd = e.wb / "state"
        sd.mkdir(parents=True, exist_ok=True)
        S.jwrite(sd / "setup-state.json", {"phase": "done", "failed": [], "ask_it": []})
        S.jwrite(sd / "backup.json", {"last": S.now(), "path": "x.zip"})
        S.jwrite(sd / "guard-heartbeat.json", {"version": 1, "last_fired": S.now(), "sessions_since_fire": 0, "fired_total": 4})
        S.jwrite(sd / "update.json", {"version": 1, "generated": S.now(), "items": [{"id": "git", "action": "deferred"}]})
        r = e.run("doctor", "--deep", "--json")                 # all knowledge checks PASS; a regular WARN row only
        rows = {x["check"]: x["status"] for x in json.loads(r.stdout)["rows"]}
        self.assertEqual(rows["updates"], "WARN")
        self.assertNotIn("FAIL", rows.values())
        self.assertEqual(r.returncode, 0, "a regular WARN under --deep exits 0")
        self.assertEqual(e.run("doctor").returncode, 1, "plain doctor: the same WARN exits 1")
        S.jwrite(sd / "guard-heartbeat.json", {"version": 1, "last_fired": S.now(), "sessions_since_fire": 5, "fired_total": 4})
        r = e.run("doctor", "--deep", "--json")                 # guards silent for 5 sessions: a regular FAIL row
        out = json.loads(r.stdout)
        self.assertEqual({x["check"]: x["status"] for x in out["rows"]}["guard heartbeat"], "FAIL")
        self.assertEqual(out["knowledge_verify"]["failing"], [], "no knowledge check failed")
        self.assertEqual((r.returncode, out["exit_code"]), (2, 2), "a regular FAIL row under --deep exits 2")
        self.assertEqual(e.run("doctor").returncode, 2)

    def test_backup_keeps_the_journal_and_skips_while_the_last_one_is_recent(self):
        e = self.env()
        kb = e.home / "Workbench" / "kb"
        (kb / "ops").mkdir(parents=True)
        (kb / "ops" / "HOT.md").write_text("# ops\n", encoding="utf-8")
        (kb / "inbox.jsonl").write_text('{"ts": "t", "text": "a journal line"}\n', encoding="utf-8")
        e.run("backup", code=0)
        zips = sorted((e.home / "Workbench" / "backup").glob("*.zip"))
        self.assertIn("KB/inbox.jsonl", zipfile.ZipFile(zips[0]).namelist())
        r = e.run("backup", "--if-older-days", "7", code=0)
        self.assertIn("nothing written", r.stdout)
        self.assertEqual(len(list((e.home / "Workbench" / "backup").glob("*.zip"))), 1)
        S.jwrite(e.wb / "state" / "backup.json", {"last": "2026-01-01T00:00:00Z", "path": I.fwd(zips[0])})
        time.sleep(1.1)                                  # backup zip names carry seconds
        e.run("backup", "--if-older-days", "7", code=0)
        self.assertEqual(len(list((e.home / "Workbench" / "backup").glob("*.zip"))), 2)


RELAY = "STOPFAILURE_MIN_CC = ({0}, {1}, {2})\nimport sys\nsys.exit(0)\n"


class Relay(unittest.TestCase):
    """IR3: the StopFailure relay hooks in user settings.json, by the version floor bug_hint.py declares."""
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wb-relay-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.ch, self.kit = self.root / "ch", self.root / "kit"
        self.hint = self.kit / "plugins" / "workbench-core" / "scripts" / "bug_hint.py"
        self.hint.parent.mkdir(parents=True)
        (self.ch / "workbench").mkdir(parents=True)
        (self.ch / "workbench" / "config.json").write_text(json.dumps({
            "data_root": I.fwd(self.root / "data"), "kb_root": I.fwd(self.root / "data" / "kb"), "python": "C:/Py/python.exe"}))
        self.user = {"model": "x", "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "my-own-hook"}]}]}}
        (self.ch / "settings.json").write_text(json.dumps(self.user), encoding="utf-8")
        self.managed = self.root / "managed.json"
        self.managed.write_text("{}", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("WORKBENCH_", "WB_"))}
        env.update(CLAUDE_CONFIG_DIR=str(self.ch), WORKBENCH_MANAGED_SETTINGS=str(self.managed),
                   WORKBENCH_FAKE_REGISTRY=str(self.root / "reg.json"), WORKBENCH_FAKE_BIN=str(self.root / "bin"),
                   HOME=str(self.root / "home"), USERPROFILE=str(self.root / "home"), LOCALAPPDATA=str(self.root / "lad"))
        (self.root / "reg.json").write_text("{}")
        for p in (mock.patch.dict(os.environ, env, clear=True), mock.patch.object(S, "KIT", self.kit)):
            p.start()
            self.addCleanup(p.stop)
        assert_sandboxed()

    def install(self, version="2.1.295"):
        ctx = S.Ctx()
        with mock.patch.object(S.Ctx, "verify", return_value=("works", version) if version else ("absent", None)):
            S.relay_hooks(ctx)
        return ctx

    def settings(self):
        return json.loads((self.ch / "settings.json").read_text(encoding="utf-8"))

    def ledger(self):
        f = self.ch / "workbench" / "state" / "provision-ledger.json"
        return json.loads(f.read_text(encoding="utf-8"))["entries"] if f.exists() else []

    def test_at_or_above_the_floor_both_hooks_are_added_with_absolute_paths_recorded_and_undone(self):
        self.hint.write_text(RELAY.format(2, 1, 295), encoding="utf-8")
        self.install("2.1.295")
        h = self.settings()["hooks"]
        stop = h["StopFailure"][0]["hooks"][0]
        self.assertEqual((stop["command"], stop["args"]), ("C:/Py/python.exe", ["-S", I.fwd(self.hint)]))
        self.assertTrue(Path(stop["args"][1]).is_absolute())
        self.assertEqual(h["UserPromptSubmit"][0], self.user["hooks"]["UserPromptSubmit"][0], "the user's own hook stays first")
        self.assertEqual(h["UserPromptSubmit"][1]["hooks"][0]["args"], ["-S", I.fwd(self.hint), "--pending"])
        self.assertEqual(self.settings()["model"], "x")
        self.assertEqual([e["kind"] for e in self.ledger()], ["settings"])
        self.install("2.1.300")                                         # idempotent
        self.assertEqual(len(self.settings()["hooks"]["StopFailure"]), 1)
        self.assertEqual(len(self.ledger()), 1)
        S.undo_config(apply=True)
        self.assertEqual(self.settings(), self.user)
        self.assertEqual(self.ledger(), [])

    def test_the_exec_form_floor_binds_when_it_is_above_the_relay_floor(self):
        self.hint.write_text(RELAY.format(2, 1, 78), encoding="utf-8")       # StopFailure exists, hook `args` does not yet
        ctx = self.install("2.1.100")
        self.assertEqual((self.settings(), self.ledger()), (self.user, []))
        self.assertTrue(any("2.1.139" in n for n in ctx.notes), ctx.notes)

    def test_below_the_floor_nothing_is_installed_and_a_note_says_why(self):
        self.hint.write_text(RELAY.format(2, 1, 296), encoding="utf-8")
        ctx = self.install("2.1.295")
        self.assertEqual(self.settings(), self.user)
        self.assertEqual(self.ledger(), [])
        self.assertTrue(any("2.1.296" in n for n in ctx.notes))
        self.install(None)                                              # no claude on PATH at all
        self.assertEqual(self.settings(), self.user)

    def test_without_the_constant_nothing_is_installed(self):
        self.hint.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        ctx = self.install("9.9.9")
        self.assertEqual((self.settings(), self.ledger()), (self.user, []))
        self.assertTrue(any("does not ship it" in n for n in ctx.notes))

    def test_an_earlier_relay_goes_when_the_floor_is_no_longer_met(self):
        self.hint.write_text(RELAY.format(2, 1, 250), encoding="utf-8")
        self.install("2.1.295")
        self.assertIn("StopFailure", self.settings()["hooks"])
        self.install("2.1.100")
        self.assertEqual((self.settings(), self.ledger()), (self.user, []))

    def test_managed_hooks_only_installs_nothing(self):
        self.hint.write_text(RELAY.format(2, 1, 250), encoding="utf-8")
        self.managed.write_text('{"allowManagedHooksOnly": true}', encoding="utf-8")
        self.install("2.1.295")
        self.assertEqual(self.settings(), self.user)

    def test_the_static_plugin_hooks_never_carry_the_relay(self):
        hooks = (REPO / "plugins" / "workbench-core" / "hooks" / "hooks.json").read_text(encoding="utf-8")
        self.assertNotIn("StopFailure", hooks)
        self.assertNotIn("--pending", hooks)

    def test_undo_config_removes_the_find_mcp_server_setup_registered(self):
        healer = self.kit / "tools" / "mcp-healer" / "mcp_healer.py"
        healer.parent.mkdir(parents=True)
        healer.write_text("import json, sys\na = sys.argv[1:]\ncfg = a[a.index('--config') + 1]\n"
                          "g = json.load(open(a[a.index('--golden') + 1]))\nc = json.load(open(cfg))\n"
                          "[c['mcpServers'].pop(n, None) for n, s in g['servers'].items() if s['action'] == 'remove']\n"
                          "json.dump(c, open(cfg, 'w'))\n", encoding="utf-8")
        cfg = self.ch / ".claude.json"
        cfg.write_text(json.dumps({"mcpServers": {"find": {"command": "py"}, "mine": {"command": "x"}}}))
        S.jwrite(self.ch / "workbench" / "state" / "provision-ledger.json", {"version": 1, "entries": [
            {"kind": "mcp", "name": "find", "config": I.fwd(cfg), "key": "mcp:find"}]})
        S.undo_config(apply=False)
        self.assertIn("find", json.loads(cfg.read_text())["mcpServers"], "a dry run changes nothing")
        self.assertEqual(S.undo_config(apply=True), 0)
        self.assertEqual(json.loads(cfg.read_text())["mcpServers"], {"mine": {"command": "x"}})


def setup_report_lines(e):
    return (e.wb / "state" / "setup-report.md").read_text(encoding="utf-8").rstrip("\n").splitlines()


class FieldFixes(unittest.TestCase):
    """v0.3.2 field fixes in setup.py: G2 doctor rows, G3 roots, G4 tokensave parked, G5 PATH and the report's last line, G6 ctx
    config, G7 kit_version. Fakes only: no registry, scheduler, winget, npm or home folder of this PC is touched."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wb-kit-"))
        cls.kit = mini_kit(cls.tmp / "kit")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def env(self, **kw):
        kw.setdefault("scenario", {"wsl": "installed", "distros": ["Ubuntu-24.04"]})
        e = FakeEnv(kit=self.kit, **kw)
        self.addCleanup(e.close)
        return e

    def in_process(self, e):
        """Run the rest of this test with the fake machine as os.environ (not only while an object is built)."""
        p = mock.patch.dict(os.environ, e.env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        assert_sandboxed()

    def test_the_guard_refuses_an_environment_that_points_at_a_real_profile(self):
        e = self.env()
        self.in_process(e)
        assert_sandboxed()
        for key in ("HOME", "USERPROFILE", "CLAUDE_CONFIG_DIR", "LOCALAPPDATA"):
            with mock.patch.dict(os.environ, {key: str(REAL_HOME / ".claude")}):
                with self.assertRaises(AssertionError, msg=key):
                    assert_sandboxed()
        with mock.patch.dict(os.environ, {"USERPROFILE": ""}):
            with self.assertRaises(AssertionError):
                assert_sandboxed()

    # ── G2: the doctor reads the plugin options, and only a real guard fire counts ──
    def healthy_doctor_state(self, e):
        sd = e.wb / "state"
        sd.mkdir(parents=True, exist_ok=True)
        S.jwrite(sd / "setup-state.json", {"phase": "done", "failed": [], "ask_it": []})
        S.jwrite(sd / "guard-heartbeat.json", {"version": 1, "last_fired": S.now(), "sessions_since_fire": 0, "fired_total": 4})
        S.jwrite(sd / "backup.json", {"last": S.now(), "path": "x.zip"})
        return sd

    def doctor_rows(self, e, *args):
        r = e.run("doctor", "--json", *args)
        return r.returncode, {x["check"]: x for x in json.loads(r.stdout[:r.stdout.rindex("}") + 1])["rows"]}

    def test_doctor_plugin_option_row_unset_missing_interpreter_ok_and_disabled(self):
        e = self.env()
        self.healthy_doctor_state(e)
        sp = e.ch / "settings.json"
        on = {"workbench-core@workbench": True, "workbench-kb@workbench": True}
        rc, rows = self.doctor_rows(e)
        self.assertEqual((rc, rows["plugin python option"]["status"]), (0, "INFO"), "nothing enabled yet")
        sp.write_text(json.dumps({"enabledPlugins": on, "pluginConfigs": {}}), encoding="utf-8")
        rc, rows = self.doctor_rows(e)                                   # unset: the field failure
        row = rows["plugin python option"]
        self.assertEqual((rc, row["status"]), (2, "FAIL"))
        self.assertIn("workbench-core@workbench: python is not set", row["detail"])
        self.assertIn("workbench-kb@workbench: python is not set", row["detail"])
        self.assertIn("Plugin option \"python\" isn't set", row["detail"])
        self.assertIn("claude plugin install <id> --config python=", row["detail"])
        self.assertEqual(rows["guard heartbeat"]["status"], "OK", "the heartbeat alone cannot see it: that is why this row exists")
        self.assertEqual(e.run("doctor", "--deep").returncode, 2, "doctor --deep exits 2 on it")
        gone = I.fwd(e.root / "nowhere" / "python.exe")                  # an interpreter that does not run
        sp.write_text(json.dumps({"enabledPlugins": on, "pluginConfigs": {
            "workbench-core@workbench": {"options": {"python": gone}},
            "workbench-kb@workbench": {"options": {"python": I.fwd(sys.executable)}}}}), encoding="utf-8")
        rc, rows = self.doctor_rows(e)
        row = rows["plugin python option"]
        self.assertEqual((rc, row["status"]), (2, "FAIL"))
        self.assertIn(f"workbench-core@workbench: {gone} does not run", row["detail"])
        self.assertNotIn("workbench-kb", row["detail"])
        sp.write_text(json.dumps({"enabledPlugins": on, "pluginConfigs": {i: {"options": {"python": I.fwd(sys.executable)}}
                                                                          for i in on}}), encoding="utf-8")
        rc, rows = self.doctor_rows(e)
        self.assertEqual((rc, rows["plugin python option"]["status"]), (0, "OK"))
        self.assertEqual(e.run("doctor", "--deep").returncode, 0)
        sp.write_text(json.dumps({"enabledPlugins": {"workbench-core@workbench": False}}), encoding="utf-8")
        rc, rows = self.doctor_rows(e)
        self.assertEqual((rc, rows["plugin python option"]["status"]), (0, "INFO"), "a disabled plugin is not checked")

    def test_doctor_heartbeat_counts_only_a_real_fire_not_the_installer_self_test(self):
        e = self.env()
        sd = self.healthy_doctor_state(e)
        S.jwrite(sd / "guard-heartbeat.json", {"version": 1, "self_test_at": S.now(), "sessions_since_fire": 0, "fired_total": 0})
        rc, rows = self.doctor_rows(e)
        self.assertEqual(rows["guard heartbeat"]["status"], "WARN")
        self.assertIn("self-test", rows["guard heartbeat"]["detail"])
        self.assertEqual(rc, 1)
        S.jwrite(sd / "guard-heartbeat.json", {"version": 1, "last_fired": S.now(), "self_test_at": S.now(),
                                               "sessions_since_fire": 0, "fired_total": 4})
        self.assertEqual(self.doctor_rows(e)[1]["guard heartbeat"]["status"], "OK")

    # ── G13 ──
    ASK = ("Please allow downloads from huggingface.co (a one-time embedding model), or provide an approved internal mirror of "
           "the model files.")

    def test_two_checks_that_need_the_same_download_are_one_ask_in_setup_the_doctor_and_the_status(self):
        e = self.env()
        e.set_verify(D9=("WARN", self.ASK), D11=("WARN", self.ASK.replace("Please", "please  ")))
        e.run("run", code=3)
        asked = [x for x in e.state()["ask_it"] if S.ASKS.key(x["text"]) == S.ASKS.key(self.ASK)]
        self.assertEqual(len(asked), 1, e.state()["ask_it"])
        self.assertEqual((asked[0]["item"], asked[0]["also"]), ("knowledge:find-build", ["knowledge:find-meaning"]))
        rc, rows = self.doctor_rows(e)
        self.assertIn("1 ask-IT item(s)", rows["setup"]["detail"])
        self.assertEqual(rows["IT asks"]["detail"].count("huggingface.co"), 1)
        self.assertIn("1 distinct ask(s)", rows["IT asks"]["detail"])
        self.assertEqual(rows["IT asks"]["status"], "INFO")
        self.assertEqual(e.run("status").stdout.count("huggingface.co"), 1)

    def test_ctx_ask_replaces_the_same_item_and_a_new_wording_of_a_different_ask_stays_separate(self):
        e = self.env()
        self.in_process(e)
        ctx = S.Ctx()
        ctx.ask("a", "Please allow X.")
        ctx.ask("b", "please   allow x.")
        ctx.ask("c", "Please allow Y.")
        ctx.ask("a", "Please allow X.")
        self.assertEqual([(x["item"], x.get("also")) for x in ctx.st["ask_it"]], [("a", ["b"]), ("c", None)])
        ctx.ask("a", "Something else entirely.")
        self.assertEqual([(x["item"], x["text"]) for x in ctx.st["ask_it"]],
                         [("a", "Something else entirely."), ("b", "Please allow X."), ("c", "Please allow Y.")],
                         "b still needs what a used to share with it")

    def test_the_doctor_says_no_ask_outstanding_on_a_clean_machine(self):
        e = self.env()
        self.healthy_doctor_state(e)
        rc, rows = self.doctor_rows(e)
        self.assertEqual((rows["IT asks"]["status"], rows["IT asks"]["detail"]), ("OK", "none outstanding"))


    # ── review round: item 1 (the healer's exit code), 3 (indexed by an earlier setup), 4 (a live tokensave), 5 (one ask list),
    #    7 (doctor corners), 8 (no tomllib) ──
    def test_mcp_row_reads_the_healers_exit_code_and_a_traceback_is_never_healthy(self):
        down = json.dumps([{"server": "dead", "status": "DOWN", "detail": "x"}])
        ok = json.dumps([{"server": "a", "status": "OK", "detail": "x"}])
        self.assertEqual(S.mcp_row(None, 0, ok.encode()), ("OK", "healthy"))
        self.assertEqual(S.mcp_row(None, 0, b"[]"), ("OK", "healthy"))
        self.assertEqual(S.mcp_row(None, 1, down.encode())[0], "WARN")
        for rc, out in ((1, b""), (1, b"Traceback (most recent call last):\n"), (2, ok.encode()), (None, ok.encode()),
                        (0, b""), (0, b"{}"), (-1, b"")):
            st, detail = S.mcp_row(None, rc, out)
            self.assertEqual(st, "WARN", (rc, out))
            self.assertIn(f"mcp_healer.py check exit {rc} gave no readable result: run it by hand", detail)

    def test_a_malformed_claude_json_makes_the_mcp_row_warn_not_say_healthy(self):
        e = self.env()
        self.healthy_doctor_state(e)
        (e.ch / ".claude.json").write_text("{ not json", encoding="utf-8")
        rc, rows = self.doctor_rows(e)
        self.assertEqual(rows["MCP servers"]["status"], "WARN")
        self.assertIn("gave no readable result: run it by hand", rows["MCP servers"]["detail"])
        self.assertNotIn("healthy", rows["MCP servers"]["detail"])
        self.assertEqual(rc, 1)

    def libs(self):
        return [{"path": I.fwd(self.tmp / "OneDrive - Example Org"), "kind": "onedrive-business", "label": "example-org"},
                {"path": I.fwd(self.tmp / "Documents"), "kind": "documents", "label": "documents"}]

    def test_a_library_an_earlier_setup_registered_is_named_as_such_and_never_removed_by_this_one(self):
        libs = self.libs()
        e = self.env()
        (e.home / "Workbench" / "kb").mkdir(parents=True)
        # the index holds the Documents library as a root already (a 0.3.1 setup added it), spelled with backslashes and capitals
        old = str(Path(libs[1]["path"])).upper()
        e.env["WB_FAKE_LIBS"] = json.dumps(libs)
        e.env["WB_FAKE_ROOTS"] = json.dumps({"roots": [{"label": "docs-old", "kind": "documents", "path": old, "files": 12},
                                                       {"label": "kb", "kind": "kb", "path": "x", "files": 1}]})
        e.run("run", code=0)
        text = "\n".join(setup_report_lines(e))
        self.assertIn("indexed by an earlier setup: remove-root docs-old", text)
        self.assertIn("Setup does not remove a root", text)
        self.assertIn("never all of OneDrive", text)
        known = [x for x in e.state()["suggestions"] if x["root"]]
        self.assertEqual([(x["kind"], x["root"]) for x in known], [("documents", "docs-old")])
        fresh = text.split("Libraries found on this machine but NOT indexed")[1]
        self.assertIn("example-org", fresh)
        self.assertNotIn("Documents", fresh.replace("Documents (", "x"), "the registered one is not listed as not indexed")
        argvs = [c["argv"][0] for c in e.calls("find")]
        self.assertNotIn("remove-root", argvs)
        self.assertEqual(sorted(c["argv"][c["argv"].index("--label") + 1] for c in e.calls("find") if c["argv"][0] == "add-root"),
                         ["captured", "howto", "kb"], "and it registered nothing new either")

    def test_when_the_roots_cannot_be_read_the_report_does_not_claim_a_library_is_not_indexed(self):
        e = self.env()
        e.env["WB_FAKE_LIBS"] = json.dumps(self.libs())      # the stub's `roots` answers {} : no root list
        e.run("run", code=0)
        text = "\n".join(setup_report_lines(e))
        self.assertIn("the registered roots could not be read", text)
        self.assertNotIn("NOT indexed", text)
        self.assertIn(I.fwd(self.tmp / "Documents"), text)

    def test_a_live_tokensave_entry_gets_a_note_with_the_one_command_and_is_not_changed(self):
        e = self.env()
        e.add_tool("tokensave", exe=True)
        cfg = e.ch / ".claude.json"
        mine = {"mcpServers": {"tokensave": {"command": "my-own", "args": ["serve"]}}}
        cfg.write_text(json.dumps(mine), encoding="utf-8")
        e.run("run", "--with", "tokensave", code=0)
        self.assertEqual(json.loads(cfg.read_text(encoding="utf-8")), mine)
        note = next(n for n in e.state()["notes"] if n.startswith("tokensave:") and "LIVE" in n)
        self.assertIn("mcp_healer.py", note)
        self.assertIn("apply --golden", note)
        self.assertIn("tokensave-mcp.golden.json", note)
        g = json.loads((e.wb / "state" / "tokensave-mcp.golden.json").read_text(encoding="utf-8"))
        self.assertEqual(g["servers"]["tokensave"]["action"], "park")
        self.assertIn("unpark tokensave", note)

    def test_a_live_entry_for_the_kits_own_binary_that_cannot_start_is_parked(self):
        e = self.env()
        e.add_tool("tokensave", exe=True)
        cfg = e.ch / ".claude.json"
        live = {"command": str(e.bin / "tokensave.cmd"), "args": ["serve"]}             # a hand registration of the kit's server
        cfg.write_text(json.dumps({"mcpServers": {"tokensave": live}}), encoding="utf-8")
        e.run("run", "--with", "tokensave", code=0)
        got = json.loads(cfg.read_text(encoding="utf-8"))
        self.assertNotIn("tokensave", got.get("mcpServers") or {}, "a server that exits before the handshake is not left live")
        self.assertIn("tokensave", got["mcpServersParked"])
        self.assertTrue([n for n in e.state()["notes"] if "setup PARKED it" in n and "unpark tokensave" in n])
        led = json.loads((e.wb / "state" / "provision-ledger.json").read_text(encoding="utf-8"))["entries"]
        self.assertTrue([x for x in led if x.get("key") == "mcp:tokensave"], "uninstall must know setup parked it")
        self.assertFalse((e.wb / "state" / "tokensave-probe.json").exists(), "the one-entry probe config is removed")

    def _kit_binary_entry(self, e):
        e.add_tool("tokensave", exe=True)
        cfg = e.ch / ".claude.json"
        live = {"command": str(e.bin / "tokensave.cmd"), "args": ["serve"]}
        cfg.write_text(json.dumps({"mcpServers": {"tokensave": live}}), encoding="utf-8")
        return cfg, live

    def _registry(self, e, rows=None):
        db = e.home / ".tokensave" / "global.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        if rows is None:
            return db.write_bytes(b"not a database\n" * 64)
        con = sqlite3.connect(db)
        con.execute("create table projects (path text primary key, tokens_saved integer not null default 0)")
        con.executemany("insert into projects (path) values (?)", [(r,) for r in rows])
        con.commit()
        con.close()

    def test_an_empty_registry_still_parks_the_kit_binary_entry(self):
        e = self.env()
        cfg, live = self._kit_binary_entry(e)
        self._registry(e, rows=[])
        e.run("run", "--with", "tokensave", code=0)
        got = json.loads(cfg.read_text(encoding="utf-8"))
        self.assertNotIn("tokensave", got.get("mcpServers") or {}, "the read must see 0, not fail")
        self.assertIn("tokensave", got["mcpServersParked"])

    def test_an_unreadable_registry_leaves_the_entry_live(self):
        e = self.env()
        cfg, live = self._kit_binary_entry(e)
        self._registry(e, rows=None)
        e.run("run", "--with", "tokensave", code=0)
        self.assertEqual(json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]["tokensave"], live, "unknown is not empty")

    def test_a_kit_binary_entry_stays_live_once_tokensave_has_indexed_a_repository(self):
        e = self.env()
        cfg, live = self._kit_binary_entry(e)
        self._registry(e, rows=["C:/repo"])
        e.run("run", "--with", "tokensave", code=0)
        got = json.loads(cfg.read_text(encoding="utf-8"))
        self.assertEqual(got["mcpServers"]["tokensave"], live, "the healer's empty-folder probe is not proof it is down")
        note = [n for n in e.state()["notes"] if n.startswith("tokensave:")]
        self.assertTrue(note and "indexed 1 repository, so setup left it on" in note[0], note)
        self.assertNotIn("exits until", note[0], "no advice to park a server that is in use")

    def test_a_kit_binary_entry_the_user_unparked_stays_live(self):
        e = self.env()
        cfg, live = self._kit_binary_entry(e)
        seed(e, [{"kind": "mcp", "name": "tokensave", "config": S.fwd(cfg), "key": "mcp:tokensave", "at": S.now()}])
        e.run("run", "--with", "tokensave", code=0)
        self.assertEqual(json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]["tokensave"], live,
                         "setup parked it once; a live entry now means the user turned it back on")

    def test_tokensave_down_probes_only_that_entry_and_reads_anything_unclear_as_not_down(self):
        e = self.env()
        self.in_process(e)
        ctx = S.Ctx()
        live = {"command": "tokensave", "args": ["serve"]}
        seen = []

        def answer(rc, out=b"", exc=None):
            def py_tool(script, *args, timeout=900):
                cfg = json.loads(Path(args[args.index("--config") + 1]).read_text(encoding="utf-8"))
                seen.append((cfg, args, timeout))
                if exc:
                    raise exc
                return rc, out
            return py_tool

        cases = [(answer(1, json.dumps([{"server": "tokensave", "status": "DOWN"}]).encode()), True),
                 (answer(0, json.dumps([{"server": "tokensave", "status": "UP"}]).encode()), False),
                 (answer(1, b"not json"), False),
                 (answer(2, json.dumps([{"server": "tokensave", "status": "DOWN"}]).encode()), False),
                 (answer(1, json.dumps({"server": "tokensave"}).encode()), False),
                 (answer(None, exc=subprocess.TimeoutExpired("healer", 90)), False)]
        for fake, want in cases:
            with self.subTest(want=want, n=len(seen)), mock.patch.object(ctx, "py_tool", fake):
                self.assertEqual(S.tokensave_down(ctx, live), want)
        self.assertTrue(all(cfg == {"mcpServers": {"tokensave": live}} for cfg, _, _ in seen), "never the user's other servers")
        self.assertTrue(all("--timeout" in a and a[a.index("--timeout") + 1] == "30" and t <= 120 for _, a, t in seen))
        self.assertFalse((ctx.state_dir / "tokensave-probe.json").exists())

    def test_a_config_whose_servers_are_not_an_object_does_not_stop_setup(self):
        e = self.env()
        e.add_tool("tokensave", exe=True)
        cfg = e.ch / ".claude.json"
        cfg.write_text(json.dumps({"mcpServers": ["odd"], "mcpServersParked": 5}), encoding="utf-8")
        e.run("run", "--with", "tokensave", code=0)          # an exception in a phase would be exit 4

    def test_runs_this_exe_matches_the_path_or_the_bare_name_only(self):
        exe = str(self.kit / "bin" / "tokensave.exe")
        self.assertTrue(S.runs_this_exe({"command": exe}, exe))
        self.assertTrue(S.runs_this_exe({"command": "tokensave"}, exe))
        self.assertFalse(S.runs_this_exe({"command": "my-own"}, exe))
        self.assertFalse(S.runs_this_exe({"command": str(self.kit / "other" / "tokensave.exe")}, exe))
        self.assertFalse(S.runs_this_exe({}, exe))

    def report_ask_env(self, ask_only_in_report=False):
        ask = ("Please allow downloads from huggingface.co (a one-time embedding model), or provide an approved internal mirror "
               "of the model files.")
        e = self.env()
        rows = [{"id": "find-hybrid", "status": "NEEDS-IT", "ask_it": ask},
                {"id": "capture-teams", "status": "NEEDS-IT", "ask_it": "Please allow the capture add-on for Teams."},
                {"id": "wsl2", "status": "READY", "ask_it": None}]
        e.env["WB_FAKE_CAPABILITY"] = json.dumps({"features": rows})
        if not ask_only_in_report:
            e.set_verify(D9=("WARN", ask), D11=("WARN", ask.upper()))
        return e, ask

    def test_the_setup_report_lists_the_one_deduplicated_ask_list_including_the_post_report_s(self):
        e, ask = self.report_ask_env()
        e.run("run", code=3)
        text = "\n".join(setup_report_lines(e))
        self.assertEqual(text.count("huggingface.co"), 1, "setup, two Day-1 checks and the report raised it: one line")
        self.assertEqual(text.count("Teams"), 1, "an ask only the post report raised reaches the same list")
        self.assertIn("IT asks (2, each listed once", text)
        line = next(x for x in text.splitlines() if "huggingface.co" in x)
        for src in ("setup", "day-1 check D9", "day-1 check D11", "report find-hybrid"):
            self.assertIn(src, line)
        self.assertNotIn("- ASK IT", text, "no second, unfiltered list")

    def test_an_ask_only_the_post_report_raised_is_listed_and_does_not_change_the_exit_code(self):
        e, _ = self.report_ask_env(ask_only_in_report=True)
        e.run("run", code=0)
        text = "\n".join(setup_report_lines(e))
        self.assertIn("IT asks (2, each listed once", text)
        self.assertEqual(text.count("Teams"), 1)
        self.assertEqual(e.state()["ask_it"], [], "setup itself asked for nothing")

    def test_the_doctor_fails_an_interpreter_that_exists_but_does_not_run(self):
        e = self.env()
        self.healthy_doctor_state(e)
        bad = e.root / "bad" / ("python.cmd" if os.name == "nt" else "python")
        bad.parent.mkdir()
        bad.write_text("@exit /b 9009\r\n" if os.name == "nt" else "#!/bin/sh\nexit 127\n", encoding="utf-8")
        bad.chmod(0o755)
        on = {"workbench-core@workbench": True}
        (e.ch / "settings.json").write_text(json.dumps({"enabledPlugins": on, "pluginConfigs": {
            "workbench-core@workbench": {"options": {"python": I.fwd(bad)}}}}), encoding="utf-8")
        rc, rows = self.doctor_rows(e)
        self.assertTrue(bad.is_file())
        self.assertEqual((rc, rows["plugin python option"]["status"]), (2, "FAIL"))
        self.assertIn(f"{I.fwd(bad)} does not run", rows["plugin python option"]["detail"])

    def test_the_doctor_reads_settings_in_claude_config_dir_when_that_is_not_the_home_dot_claude(self):
        e = self.env(ch_name="cfg-elsewhere")
        self.assertNotEqual(e.ch, e.home / ".claude")
        self.healthy_doctor_state(e)
        on = {"workbench-core@workbench": True}
        decoy = e.home / ".claude"
        decoy.mkdir(parents=True, exist_ok=True)
        (decoy / "settings.json").write_text(json.dumps({"enabledPlugins": on, "pluginConfigs": {
            "workbench-core@workbench": {"options": {"python": I.fwd(sys.executable)}}}}), encoding="utf-8")
        (e.ch / "settings.json").write_text(json.dumps({"enabledPlugins": on}), encoding="utf-8")      # the real one: unset
        rc, rows = self.doctor_rows(e)
        self.assertEqual((rc, rows["plugin python option"]["status"]), (2, "FAIL"), "the decoy in ~/.claude must not be read")
        (e.ch / "settings.json").write_text(json.dumps({"enabledPlugins": on, "pluginConfigs": {
            "workbench-core@workbench": {"options": {"python": I.fwd(sys.executable)}}}}), encoding="utf-8")
        (decoy / "settings.json").write_text(json.dumps({"enabledPlugins": on}), encoding="utf-8")      # now the decoy is the bad one
        rc, rows = self.doctor_rows(e)
        self.assertEqual((rc, rows["plugin python option"]["status"]), (0, "OK"))
        e.run("run", code=0)                                    # and a whole run works with a config dir elsewhere
        self.assertTrue((e.ch / "workbench" / "state" / "setup-report.md").is_file())

    def test_without_tomllib_the_ctx_config_is_not_edited_and_the_note_says_what_to_do_by_hand(self):
        e = self.ctx_env()
        e.run("run", "--with", "ctx", code=0)                   # installs the fake ctx and records it
        cfg = self.ctx_cfg(e)
        cfg.unlink()
        e.clear_calls()
        self.in_process(e)
        ctx = S.Ctx()
        with mock.patch.dict(sys.modules, {"tomllib": None}):     # `import tomllib` raises ImportError, as on Python 3.10
            S.do_ctx_config(ctx)
        self.assertFalse(cfg.exists(), "nothing was written unvalidated")
        self.assertEqual(ctx.st["failed"], [])
        note = next(n for n in ctx.notes if "cannot validate TOML" in n)
        for want in ("[analytics] enabled = false", "[sources] automatic = false", "ctx sources add claude", "3.11"):
            self.assertIn(want, note)
        self.assertFalse([c for c in e.calls("exe:ctx") if c["argv"][1:3] == ["sources", "add"]])
        self.assertEqual(ctx.extra_env, S.CTX_ENV, "the environment opt-outs stay on")

    # ── G7 ──
    def test_kit_version_is_the_running_kit_after_an_upgrade_from_a_0_3_0_state_file(self):
        e = self.env()
        sd = e.wb / "state"
        sd.mkdir(parents=True, exist_ok=True)
        S.jwrite(sd / "setup-state.json", {"version": 1, "kit_version": "0.3.0", "phase": "done", "infosec_shown": True,
                                           "options": {"with": [], "no_nightly": False, "no_update": False}})
        self.in_process(e)
        ctx = S.Ctx()
        self.assertEqual(ctx.st["kit_version"], I.VERSION)
        self.assertTrue(ctx.st["infosec_shown"], "the rest of the old state is kept")
        e.run("run", code=0)
        self.assertEqual(e.state()["kit_version"], I.VERSION)

    # ── G3, G5: roots, PATH and the report ──
    def test_discovered_libraries_are_suggestions_with_a_pointer_to_guide_28_never_roots(self):
        libs = [{"path": I.fwd(self.tmp / "OneDrive - Example Org"), "kind": "onedrive-business", "label": "example-org"},
                {"path": I.fwd(self.tmp / "Example Org" / "Shared Docs"), "kind": "sharepoint-sync", "label": "shared-docs"},
                {"path": I.fwd(self.tmp / "Documents"), "kind": "documents", "label": "documents"}]
        e = self.env()
        (e.home / "Workbench" / "kb").mkdir(parents=True)
        e.env["WB_FAKE_LIBS"] = json.dumps(libs)
        r = e.run("run", code=0)
        roots = sorted(a["argv"][a["argv"].index("--label") + 1] for a in e.calls("find") if a["argv"][0] == "add-root")
        self.assertEqual(roots, ["captured", "howto", "kb"])
        lines = setup_report_lines(e)
        text = "\n".join(lines)
        for lib in libs:
            self.assertIn(lib["path"], text)
            self.assertIn(lib["kind"], text)
        self.assertIn("guide 28", text)
        self.assertIn("docs/howto/28-add-a-library-to-find.md", text)
        self.assertIn("never all of OneDrive", text)
        self.assertEqual([x["kind"] for x in e.state()["suggestions"]], ["onedrive-business", "sharepoint-sync", "documents"])
        self.assertEqual(lines[-1], S.RESTART, "the restart line is the last line of the report")
        self.assertEqual(r.stdout.rstrip("\n").splitlines()[-1], S.RESTART, "and the last line the run prints")
        self.assertIn(S.RESTART, e.run("status").stdout)

    def test_report_has_no_suggestion_block_when_nothing_was_discovered_and_still_ends_with_the_restart_line(self):
        e = self.env()
        e.env["WB_FAKE_LIBS"] = "[]"
        e.run("run", code=0)
        lines = setup_report_lines(e)
        self.assertNotIn("NOT indexed", "\n".join(lines))
        self.assertEqual(lines[-1], S.RESTART)
        self.assertIn("Close every Claude Code window", S.RESTART)
        self.assertIn("fresh terminal", S.RESTART)

    def user_path(self, e):
        return {k.lower(): v for k, v in e.registry()["HKCU\\Environment"].items()}["path"]

    def test_wb_bin_joins_the_user_path_once_keeping_the_expand_type_and_undo_removes_it(self):
        e = self.env()
        e.run("run", code=0)
        data, typ = self.user_path(e)
        parts = data.split(";")
        self.assertEqual(typ, 2, "REG_EXPAND_SZ stays")
        self.assertEqual(parts[0], r"%LOCALAPPDATA%\Tools", "what was there stays, unexpanded")
        self.assertEqual([x for x in parts if x.lower() == str(e.wb / "bin").lower()], [str(e.wb / "bin")])
        self.assertTrue((e.wb / "bin").is_dir())
        e.run("run", code=0)
        self.assertEqual(self.user_path(e)[0], data, "a second run changes nothing: no duplicate")
        e.run("undo-config", "--apply", code=0)
        self.assertNotIn(str(e.wb / "bin").lower(), [x.lower() for x in self.user_path(e)[0].split(";")])

    def test_wb_bin_already_on_the_path_in_another_spelling_is_not_added_again(self):
        e = self.env()
        spelled = "%USERPROFILE%/.CLAUDE/workbench/bin/"                  # same folder: other case, slashes, %VAR% form, trailing slash
        reg = e.registry()
        reg["HKCU\\Environment"]["Path"] = [r"%LOCALAPPDATA%\Tools;" + spelled, 2]
        e.reg.write_text(json.dumps(reg))
        e.run("run", code=0)
        parts = self.user_path(e)[0].split(";")
        self.assertEqual(parts[:2], [r"%LOCALAPPDATA%\Tools", spelled], "the user's own spelling stays")
        self.assertEqual([x for x in parts if "workbench" in x.lower() and x.lower().rstrip("\\/").endswith("bin")], [spelled])

    def test_path_is_never_written_to_hklm_or_a_policies_key(self):
        e = self.env()
        e.run("run", code=0)
        self.assertFalse([k for k in e.registry() if k.upper().startswith("HKLM") or "policies" in k.lower()])

    # ── G4: tokensave is registered parked ──
    def test_tokensave_is_registered_parked_the_healer_and_the_doctor_say_parked_and_undo_removes_it(self):
        e = self.env()
        e.add_tool("tokensave", exe=True)
        cfg = e.ch / ".claude.json"
        cfg.write_text(json.dumps({"mcpServers": {"mine": {"command": "x", "disabled": True}}}), encoding="utf-8")
        e.run("run", "--with", "tokensave", code=0)
        got = json.loads(cfg.read_text(encoding="utf-8"))
        self.assertEqual(sorted(got["mcpServers"]), ["mine"], "nothing live: serve would exit until a repo is indexed")
        parked = got["mcpServersParked"]["tokensave"]
        self.assertTrue(parked["command"].lower().endswith("tokensave.cmd"), parked)
        self.assertEqual(parked["args"], ["serve"])
        self.assertTrue([n for n in e.state()["notes"] if "tokensave: registered PARKED" in n and "unpark tokensave" in n])
        led = [x for x in json.loads((e.wb / "state" / "provision-ledger.json").read_text())["entries"] if x.get("key") == "mcp:tokensave"]
        self.assertEqual(len(led), 1)
        healer = self.kit / "tools" / "mcp-healer" / "mcp_healer.py"
        chk = subprocess.run([sys.executable, str(healer), "--config", str(cfg), "check", "--json"], capture_output=True, text=True,
                             env=e.env)
        rows = {r["server"]: r for r in json.loads(chk.stdout)}
        self.assertEqual(rows["tokensave"]["status"], "PARKED")
        self.assertEqual(chk.returncode, 0, "a parked server is not DOWN")
        self.healthy_doctor_state(e)
        rc, drows = self.doctor_rows(e)
        self.assertEqual((drows["MCP servers"]["status"], rc), ("OK", 0))
        self.assertIn("PARKED", drows["MCP servers"]["detail"])
        self.assertIn("tokensave init", drows["MCP servers"]["detail"])
        e.run("run", "--with", "tokensave", code=0)
        self.assertEqual(json.loads(cfg.read_text(encoding="utf-8"))["mcpServersParked"]["tokensave"], parked, "a second run is a no-op")
        e.run("undo-config", "--apply", code=0)
        left = json.loads(cfg.read_text(encoding="utf-8"))
        self.assertNotIn("tokensave", left.get("mcpServers", {}))
        self.assertNotIn("tokensave", left.get("mcpServersParked", {}))
        self.assertEqual(left["mcpServers"], {"mine": {"command": "x", "disabled": True}})

    def test_a_tokensave_entry_the_user_has_is_left_alone_and_without_the_opt_in_nothing_is_registered(self):
        e = self.env()
        e.add_tool("tokensave", exe=True)
        cfg = e.ch / ".claude.json"
        mine = {"mcpServers": {"tokensave": {"command": "my-own", "args": ["serve"]}}}
        cfg.write_text(json.dumps(mine), encoding="utf-8")
        e.run("run", "--with", "tokensave", code=0)
        self.assertEqual(json.loads(cfg.read_text(encoding="utf-8")), mine)
        cfg.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        e2 = self.env()
        e2.add_tool("tokensave", exe=True)
        (e2.ch / ".claude.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        e2.run("run", code=0)
        self.assertNotIn("mcpServersParked", json.loads((e2.ch / ".claude.json").read_text(encoding="utf-8")))

    def test_tokensave_waits_for_claude_code_to_have_written_its_config(self):
        e = self.env()
        e.add_tool("tokensave", exe=True)
        e.run("run", "--with", "tokensave", code=0)
        self.assertFalse((e.ch / ".claude.json").exists(), "setup does not create the file Claude Code owns")
        self.assertTrue([n for n in e.state()["notes"] if "tokensave:" in n and "start Claude Code once" in n])

    # ── G6: ctx's own config file ──
    def ctx_env(self, **scenario):
        import hashlib as h
        body = "ctx-fixture-bytes"
        kit = mini_kit(Path(tempfile.mkdtemp(prefix="wb-kit4-")) / "kit")
        self.addCleanup(shutil.rmtree, kit.parent, True)
        pk = json.loads((kit / "bootstrap" / "packages.json").read_text(encoding="utf-8"))
        for row in pk["packages"]:
            if row["id"] == "ctx":
                row["sha256"] = h.sha256(body.encode()).hexdigest()
        (kit / "bootstrap" / "packages.json").write_text(json.dumps(pk), encoding="utf-8")
        e = FakeEnv(kit=kit, scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"], "curl_body": body, "curl_shim": ["ctx"],
                                       **scenario})
        self.addCleanup(e.close)
        return e

    def ctx_cfg(self, e):
        return e.home / ".ctx" / "config.toml"

    def test_toml_set_edits_one_line_and_keeps_everything_else(self):
        self.assertEqual(S.toml_set("", "analytics", "enabled", "false"), "[analytics]\nenabled = false\n")
        t = "# mine\n[indexing]\nmode = \"manual\"\n"
        out = S.toml_set(t, "analytics", "enabled", "false")
        self.assertEqual(out, t + "\n[analytics]\nenabled = false\n")
        t = "[analytics]\n# keep me\nenabled = true # why\nother = 1\n[sources]\nautomatic = true\n"
        out = S.toml_set(S.toml_set(t, "analytics", "enabled", "false"), "sources", "automatic", "false")
        self.assertEqual(out, "[analytics]\n# keep me\nenabled = false\nother = 1\n[sources]\nautomatic = false\n")
        self.assertEqual(S.toml_set("[analytics]\nx = 1\n", "analytics", "enabled", "false"), "[analytics]\nenabled = false\nx = 1\n")
        self.assertEqual(S.toml_set("[ analytics ]  # t\r\nx = 1\r\n", "analytics", "enabled", "false"),
                         "[ analytics ]  # t\r\nenabled = false\r\nx = 1\r\n", "CRLF kept, a spaced header with a comment found")
        t = "[" * 2 + "analytics" + "]" * 2 + "\nenabled = true\n"        # an array of tables is a different thing
        self.assertTrue(S.toml_set(t, "analytics", "enabled", "false").endswith("\n[analytics]\nenabled = false\n"))
        both = S.toml_set(S.toml_set("", "analytics", "enabled", "false"), "analytics", "enabled", "false")
        self.assertEqual(both, "[analytics]\nenabled = false\n", "idempotent")

    def test_ctx_gets_the_opt_out_and_only_the_claude_folder_and_a_second_run_changes_nothing(self):
        e = self.ctx_env()
        e.run("run", "--with", "ctx", code=0)
        cfg = self.ctx_cfg(e)
        text = cfg.read_text(encoding="utf-8")
        try:
            import tomllib
            got = tomllib.loads(text)
            self.assertIs(got["analytics"]["enabled"], False)
            self.assertIs(got["sources"]["automatic"], False)
            self.assertEqual(got["sources"]["roots"]["claude"], {"provider": "claude", "path": str(e.ch)})
        except ImportError:
            self.assertIn("[analytics]\nenabled = false", text)
            self.assertIn("[sources]\nautomatic = false", text)
        adds = [c["argv"][1:] for c in e.calls("exe:ctx") if c["argv"][1:3] == ["sources", "add"]]       # argv[0] is the exe path
        want = ["sources", "add", "claude", "--provider", "claude", "--root", str(e.ch)]
        self.assertEqual(adds, [want])
        status = [c for c in e.calls("exe:ctx") if c["argv"][1:2] == ["status"]]
        self.assertEqual(status[0]["argv"][1:], ["status", "--format", "json"], "setup asks ctx where its config file is")
        self.assertEqual(status[0]["ctx_env"], S.CTX_ENV, "the env opt-outs are on for every ctx call, too")
        before = cfg.read_bytes()
        e.run("run", "--with", "ctx", code=0)
        self.assertEqual(cfg.read_bytes(), before)

    def test_the_nightly_ctx_action_is_the_last_one_and_is_not_wrapped_so_a_real_failure_still_shows(self):
        e = self.ctx_env()
        e.run("run", "--with", "ctx,nightly", code=0)
        xml = (e.dir / "tasks" / "_claude-workbench_knowledge-refresh.xml").read_bytes().decode("utf-16")
        execs = re.findall(r"<Exec><Command>(.*?)</Command><Arguments>(.*?)</Arguments></Exec>", xml)
        cmd, args = execs[-1]
        self.assertTrue(cmd.lower().endswith("ctx.exe"))
        self.assertEqual(args, "import --all", "the source list comes from ctx's config, not from the task")
        self.assertFalse(re.search(r"cmd(\.exe)?\s*/c|exit 0|\|\|", xml, re.I), "no wrapper turns a ctx failure into success")

    def test_ctx_config_keeps_the_users_lines_comments_and_other_tables(self):
        e = self.ctx_env()
        cfg = self.ctx_cfg(e)
        cfg.parent.mkdir(parents=True)
        cfg.write_text("# my ctx\n[analytics]\nenabled = true # on\n\n[indexing]\nmode = \"manual\"\n", encoding="utf-8")
        e.run("run", "--with", "ctx", code=0)
        text = cfg.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# my ctx\n[analytics]\nenabled = false\n"), text)
        self.assertIn("[indexing]\nmode = \"manual\"\n", text)
        self.assertIn("[sources]\nautomatic = false\n", text)

    def test_a_claude_root_the_user_defined_differently_stays_and_a_note_says_so(self):
        e = self.ctx_env()
        cfg = self.ctx_cfg(e)
        cfg.parent.mkdir(parents=True)
        mine = "[sources.roots.claude]\nprovider = \"claude\"\npath = 'D:\\\\elsewhere\\\\claude'\n"
        cfg.write_text(mine, encoding="utf-8")
        e.run("run", "--with", "ctx", code=0)
        text = cfg.read_text(encoding="utf-8")
        self.assertIn(mine, text)
        self.assertEqual(text.count("[sources.roots.claude]"), 1)
        self.assertTrue([n for n in e.state()["notes"] if "named `claude` is already defined" in n])

    def test_an_unreadable_ctx_config_is_left_unchanged_and_the_run_fails_loudly(self):
        try:
            import tomllib  # noqa: F401
        except ImportError:
            self.skipTest("Python 3.10 has no tomllib: the file is edited without validation there")
        e = self.ctx_env()
        cfg = self.ctx_cfg(e)
        cfg.parent.mkdir(parents=True)
        cfg.write_text("[analytics\nenabled = = true\n", encoding="utf-8")
        e.run("run", "--with", "ctx", code=4)
        self.assertEqual(cfg.read_text(encoding="utf-8"), "[analytics\nenabled = = true\n")
        self.assertIn("ctx-config", {x["item"] for x in e.state()["failed"]})
        self.assertFalse([c for c in e.calls("exe:ctx") if c["argv"][1:3] == ["sources", "add"]])

    def test_a_ctx_the_kit_did_not_install_keeps_its_config_untouched(self):
        e = self.env()
        e.run("run", code=0)
        self.assertFalse(self.ctx_cfg(e).exists())
        self.assertFalse([c for c in e.calls("exe:ctx") if c["argv"][1:2] in (["status"], ["sources"])])


if __name__ == "__main__":
    unittest.main()
