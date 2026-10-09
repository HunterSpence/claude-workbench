"""Tests for probe.py. Run: WB_REQUIRE_ALL=1 py -3 -m unittest discover -s bootstrap -p test_probe.py -v

A missing dependency FAILS when WB_REQUIRE_ALL=1 (REQUIRE) instead of skipping. WB_LIVE=1 adds the live test."""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"

import functools  # noqa: E402
import http.server  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import unittest  # noqa: E402
import urllib.error  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import probe  # noqa: E402

LIVE = os.environ.get("WB_LIVE") == "1"
FORBIDDEN = ["Run" + "As", "-Ver" + "b", "Set" + "Value", "Create" + "Key"]
OWNED = ["probe.py", "report.py", "devbench.py", "features.json", "test_probe.py", "test_report.py"]

FIXTURE_PACKAGES = {"version": 1, "packages": [
    {"id": "git", "name": "Git", "winget": "Git.Git", "scope": "user", "source": "winget", "hosts": ["github.com"],
     "admin": False, "optional_with": None, "verify": ["git", "--version"], "expect": r"(\d+\.\d+\.\d+)",
     "ask_it": "Please allow installing Git for my account.", "policy_keys": []},
    {"id": "node", "name": "Node.js", "winget": "OpenJS.NodeJS.LTS", "scope": "machine", "source": "winget",
     "hosts": ["nodejs.org", "registry.npmjs.org"], "admin": True, "optional_with": None, "verify": ["node", "--version"],
     "expect": r"v(\d+\.\d+\.\d+)", "ask_it": "Please allow installing Node.js for my account.",
     "policy_keys": [r"HKLM\SOFTWARE\Policies\Microsoft\Windows\AppInstaller"]},
    {"id": "uv", "name": "uv", "winget": None, "scope": "user", "source": "pypi", "hosts": ["pypi.org", "files.pythonhosted.org"],
     "admin": False, "optional_with": None, "verify": ["uv", "--version"], "expect": r"uv (\d+\.\d+\.\d+)",
     "ask_it": "Please allow the Python package index for my account.", "policy_keys": []},
    {"id": "jq", "name": "jq", "winget": None, "scope": "user", "source": "github-release",
     "hosts": ["github.com", "release-assets.githubusercontent.com"], "admin": False, "optional_with": None,
     "verify": ["jq", "--version"], "expect": r"jq-(\d+\.\d+\.\d+)", "ask_it": "Please allow release downloads from github.com.",
     "policy_keys": []},
    {"id": "claude", "name": "Claude Code", "winget": None, "scope": "user", "source": "vendor-url",
     "hosts": ["downloads.claude.ai"], "admin": False, "optional_with": None, "verify": ["claude", "--version"],
     "expect": r"(\d+\.\d+\.\d+)", "ask_it": "Please allow downloads.claude.ai.", "policy_keys": []},
    {"id": "knowledge-model", "name": "Embedding model", "winget": None, "scope": "user", "source": "vendor-url",
     "hosts": ["huggingface.co"], "admin": False, "optional_with": "knowledge", "verify": ["py", "-3.13", "--version"],
     "expect": r"Python (\d+\.\d+\.\d+)", "ask_it": "Please allow huggingface.co.", "policy_keys": []},
    {"id": "winget-source", "name": "Package source", "winget": None, "scope": "user", "source": "winget",
     "hosts": ["cdn.winget.microsoft.com"], "admin": False, "optional_with": None, "verify": ["winget", "--version"],
     "expect": r"v(\d+\.\d+\.\d+)", "ask_it": "Please allow cdn.winget.microsoft.com.", "policy_keys": []},
]}
FIXTURE_HOSTS = {h for p in FIXTURE_PACKAGES["packages"] for h in p["hosts"]}

BASE_REG = {
    r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion": {"EditionID": "Professional", "DisplayVersion": "24H2"},
    r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe": {"(Default)": r"D:\Edge\msedge.exe"},
    r"HKCU\Software\Microsoft\Edge\BLBeacon": {"version": "140.0.100"},
    r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings": {"ProxyEnable": 0},
}
BASE_PS = {"cpu": "Example CPU", "cores": 8, "ram": 17179869184, "hv": True, "fw": False, "gpu": ["Example GPU"], "npu": [],
           "battery": True, "plan": "Balanced", "disks": [{"mount": "C:", "type": "SSD", "free": 107374182400}],
           "rtp": True, "exna": False, "excnt": 0, "av": ["Windows Defender"], "wdac": 0, "appid": "Stopped", "applocker": [],
           "svcok": True, "epm": False, "dlpsvc": False, "sched": "Running", "dlpapp": False, "label": False, "appxok": True,
           "lang": "FullLanguage", "execpol": "RemoteSigned", "pol_machine": "Undefined", "pol_user": "Undefined",
           "outlook_new": False, "teams_new": True, "task": False, "docs": r"D:\Docs"}
BASE_TOOLS = {"git": "2.40.0", "gh": "2.30.0", "node": "20.11.0", "npm": "10.2.0", "uv": "0.4.0", "claude": "2.1.0",
              "winget": "1.7.0", "curl": "8.4.0", "jq": "1.7.1", "code": "1.90.0"}


def need(tc, what, ok):
    if not ok:
        if REQUIRE:
            tc.fail("missing dependency: " + what)
        tc.skipTest("missing dependency: " + what)


class FakeSystem:
    """A machine in a dictionary: registry, PowerShell JSON, tool versions. Records every command it is asked to run."""

    def __init__(self, tmp, registry=None, ps=None, tools=None, admin=True, wsl_installed=False, distros=(), libs=None,
                 find=None, env=None):
        self.calls, self.fetched, self.tls_hosts = [], [], []
        self.environ = {"SystemRoot": r"C:\Windows", "LOCALAPPDATA": os.path.join(tmp, "lad"),
                        "CLAUDE_CONFIG_DIR": os.path.join(tmp, "cc"), "ProgramFiles": os.path.join(tmp, "pf")}
        self.environ.update(env or {})
        self.reg = {k.lower(): v for k, v in BASE_REG.items()}
        for k, v in (registry or {}).items():
            self.reg[k.lower()] = v
        self.ps = dict(BASE_PS, **(ps or {}))
        self.tools = dict(BASE_TOOLS, **(tools or {}))
        self.admin, self.wsl_installed, self.distros, self.libs, self.find = admin, wsl_installed, list(distros), libs or [], find

    def kw(self, **extra):
        d = dict(run_=self, which_=self.which, fetch_=self.fetch, tls_=self.tls, environ=self.environ, managed_files=[], kit=KIT)
        d.update(extra)
        return d

    def which(self, name):
        stem = probe._stem(name)
        return r"C:\fake\%s.exe" % stem if stem in self.tools or stem in ("py", "wsl") else None

    def fetch(self, url, timeout=4):
        self.fetched.append(url)
        return {"method": "HEAD", "result": "ok", "category": None, "http_status": 200, "bytes": 0, "ms": 25}

    def tls(self, host, bundle=None, timeout=4):
        self.tls_hosts.append(host)
        return {"host": host, "issuer_o": "Example CA", "issuer_cn": "Example Issuing CA", "system_ok": True, "bundle_ok": True,
                "inspected": "no"}

    def _reg(self, a):
        key = a[1].lower().replace("hkey_fake\\", "").replace("hkcr\\", "hklm\\software\\classes\\")
        vals = self.reg.get(key)
        subs = sorted(k for k in self.reg if k.startswith(key + "\\") and "\\" not in k[len(key) + 1:])
        if vals is None and not subs:
            return 1, b""
        lines = ["", "HKEY_FAKE\\" + a[1]]
        for n, v in (vals or {}).items():
            if len(a) == 4 and a[3] != n:
                continue
            lines.append("    %s    %s    %s" % (n, "REG_DWORD" if isinstance(v, int) else "REG_SZ", "0x%x" % v if isinstance(v, int) else v))
        lines += ["HKEY_FAKE\\" + s for s in subs] if len(a) == 2 else []
        return 0, "\r\n".join(lines).encode()

    def __call__(self, argv, timeout=15):
        self.calls.append(list(argv))
        exe, a = probe._stem(argv[0]), argv[1:]
        if exe == "reg":
            return self._reg(a)
        if exe == "whoami":
            sid = "S-1-5-32-544" if self.admin else "S-1-5-32-545"
            return 0, ('"Group Name","Type","SID","Attributes"\r\n"Example\\Group","Alias","%s","Mandatory group"\r\n' % sid).encode()
        if exe in ("powershell", "pwsh"):
            return 0, json.dumps(self.ps).encode()
        if exe == "dsregcmd":
            return 0, b"AzureAdJoined : NO\r\nDomainJoined : NO\r\nWorkplaceJoined : NO\r\n"
        if exe == "wsl":
            if a == ["--version"] and self.wsl_installed:
                return 0, "WSL version: 2.3.26\r\n".encode("utf-16-le")
            if a == ["-l", "-v"] and self.distros:
                rows = ["  NAME      STATE           VERSION"] + ["* %s   Running   %d" % d for d in self.distros]
                return 0, "\r\n".join(rows).encode("utf-16-le")
            return (0, b"") if a == ["--status"] and self.wsl_installed else (1, b"")
        if exe == "netsh":
            return 0, b"Direct access (no proxy server).\r\n"
        if exe == "claude" and a == ["doctor"]:
            return 0, b"Managed settings (remote): none\nOrganization policy: none\n"
        if exe == "curl" and "--max-time" in a:
            return 0, b"200"
        if exe == "node" and a[:1] == ["-e"]:
            return 0, b""
        if exe == "git" and "ls-remote" in a:
            return 0, b""
        if exe in ("py", "python", "python3") and "pip" in a:
            return 0, b"pip (25.0.1)\n"
        if self.find and argv[:len(self.find)] == self.find:
            return 0, json.dumps({"libraries": self.libs} if a[-2:-1] == ["discover"] else {"mode": "keyword", "vectors": 0}).encode()
        if exe == "py" and getattr(self, "py_versions", None) is not None and a[1:] == ["--version"]:
            v = next((x for x in self.py_versions if a[:1] == ["-" + x.rsplit(".", 1)[0]]), None)   # py -3.14 --version
            return (0, ("Python %s" % v).encode()) if v else (103, b"")
        if a and a[-1] == "--version":
            name = "python" if exe == "py" else exe
            v = self.tools.get(name) if exe != "py" else "3.13.1"
            return (0, (("v%s" % v) if exe == "node" else ("Python %s" % v) if exe == "py" else ("%s %s" % (exe, v))).encode()) if v else (None, b"")
        return None, b""


def collect(fs, **kw):
    return probe.collect(**fs.kw(**kw))


_fx = []


def fixture_file():
    # recreated when missing: other suites in the same run clean up their temp trees
    if not _fx or not os.path.isfile(os.path.join(_fx[0], "packages.json")):
        d = tempfile.mkdtemp(prefix="wb-fixture-")
        _fx[:] = [d]
        with open(os.path.join(d, "packages.json"), "w", encoding="utf-8") as f:
            json.dump(FIXTURE_PACKAGES, f)
    return os.path.join(_fx[0], "packages.json")


def tearDownModule():
    for d in _fx:
        shutil.rmtree(d, ignore_errors=True)


def rd(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def rj(path):
    return json.loads(rd(path))


def tree(root):
    return sorted((os.path.relpath(os.path.join(dp, f), root), os.path.getsize(os.path.join(dp, f)))
                  for dp, _dn, fn in os.walk(root) for f in fn)


def tmpdir(tc):
    d = tempfile.mkdtemp(prefix="wb-test-")
    tc.addCleanup(shutil.rmtree, d, True)
    return d


class Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return b""


class RecOpener:
    """Fake urllib opener: records host, method, User-Agent, thread and how many requests overlap."""

    def __init__(self):
        self.seen, self.active, self.max_active = [], 0, 0

    def open(self, req, timeout=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.seen.append((urllib.parse.urlparse(req.full_url).hostname, req.get_method(), req.get_header("User-agent"),
                          threading.current_thread().name))
        self.active -= 1
        return Resp()


class AllowlistTests(unittest.TestCase):
    def test_forbidden_argv_raises(self):
        bad = [["cmd", "/c", "dir"], ["reg", "add", r"HKCU\Software\X"], ["reg", "delete", r"HKCU\Software\X"],
               ["reg", "query", "Software\\X"], ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Set-Item x 1"],
               ["powershell", "-Command", "Get-Date"], ["winget", "install", "x"], ["wsl", "--install"], ["git", "clone", "x"],
               ["curl.exe", "-o", "out.bin", "--max-time", "4", "https://example.com/"], ["node", "-e", "process.exit(0)", "x.example.com"],
               ["whoami", "/all"], ["claude", "login"], ["py", "-m", "pip", "install", "x"], ["rm", "-rf", "x"], []]
        for argv in bad:
            with self.assertRaises(ValueError, msg=str(argv)):
                probe.run(argv)

    def test_allowed_examples(self):
        good = [["git", "--version"], ["whoami", "/groups", "/fo", "csv"], ["reg", "query", r"HKLM\Software\X"],
                ["reg", "query", r"HKCU\Software\X", "/v", "Name"], ["wsl", "--status"], ["wsl", "-l", "-v"], ["winget", "--info"],
                ["netsh", "winhttp", "show", "proxy"], ["dsregcmd", "/status"], ["claude", "doctor"], ["py", "-3.13", "--version"],
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", probe.PS_MAIN]]
        for argv in good:
            self.assertTrue(probe.allowed(argv), argv)

    def test_static_forbidden_strings_and_dotted_quads(self):
        for name in OWNED:
            with open(os.path.join(HERE, name), encoding="utf-8") as f:
                text = f.read()
            if name.endswith(".py"):
                for bad in FORBIDDEN:
                    self.assertNotIn(bad, text, "%s contains a forbidden string" % name)
            self.assertIsNone(re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text), "%s has a dotted-quad number" % name)

    def test_script_only_runs_known_powershell(self):
        self.assertEqual(len(probe.PS_SCRIPTS), 1)
        self.assertNotRegex(probe.PS_MAIN, r"\b(Set|New|Remove|Start|Stop|Invoke|Add|Enable|Disable|Install)-")


class SectionTests(unittest.TestCase):
    def test_sixteen_sections_when_every_subprocess_fails(self):
        def dead(argv, timeout=15):
            return None, b""
        doc = probe.collect(run_=dead, which_=lambda n: None, fetch_=lambda u, timeout=4: {"result": "blocked", "category": "connect"},
                            tls_=lambda *a: {}, environ={}, managed_files=[], kit=KIT)
        self.assertEqual(list(doc["sections"]), list(probe.SECTIONS))
        self.assertEqual(len(doc["sections"]), 16)
        for s in doc["sections"].values():
            self.assertIn(s["status"], ("ok", "partial", "unavailable", "n/a"))
            self.assertIsInstance(s["data"], dict)
            self.assertIsInstance(s["notes"], list)

    def test_sixteen_sections_when_a_section_crashes(self):
        def boom(argv, timeout=15):
            raise OSError("boom")
        doc = probe.collect(run_=boom, which_=lambda n: "x", environ={}, managed_files=[], kit=KIT, network=False)
        self.assertEqual(len(doc["sections"]), 16)
        self.assertTrue(any(s["status"] == "unavailable" and s["notes"] for s in doc["sections"].values()))

    def test_only_keeps_all_sections(self):
        doc = probe.collect(only=["os"], network=False, kit=KIT)
        self.assertEqual(len(doc["sections"]), 16)
        self.assertEqual(doc["sections"]["tls"]["status"], "n/a")

    def test_healthy_machine_issues_only_allowed_commands(self):
        need(self, "Windows", probe.IS_WIN)
        fs = FakeSystem(tmpdir(self))
        doc = collect(fs, packages=fixture_file())
        notes = [n for s in doc["sections"].values() for n in s["notes"]]
        self.assertFalse([n for n in notes if "not allowed" in n], notes)
        self.assertEqual(doc["sections"]["hardware"]["data"]["ram_gb"], 16.0)
        self.assertEqual(doc["sections"]["hardware"]["data"]["disks"][0]["type"], "ssd")
        self.assertTrue(doc["sections"]["identity"]["data"]["admin_capable"])
        self.assertTrue(doc["sections"]["tools"]["data"]["git"]["works"])
        self.assertFalse(doc["sections"]["tools"]["data"]["wsl"]["works"])
        self.assertEqual(doc["sections"]["tools"]["data"]["packages"]["node"]["version"], "20.11.0")
        self.assertEqual(doc["sections"]["capture"]["data"]["edge_version"], "140.0.100")
        self.assertIs(doc["sections"]["capture"]["data"]["automation_allowed"], True)

    def test_an_accepted_python_3_14_counts_as_the_knowledge_python(self):
        need(self, "Windows", probe.IS_WIN)
        row = next(p for p in json.loads(rd(os.path.join(KIT, "bootstrap", "packages.json")))["packages"] if p["id"] == "python313")
        pk = os.path.join(tmpdir(self), "packages.json")
        with open(pk, "w", encoding="utf-8") as f:
            json.dump({"packages": FIXTURE_PACKAGES["packages"] + [row]}, f)
        for have, want in ((["3.14.2"], "3.14.2"), (["3.13.15", "3.14.2"], "3.13.15"), (["3.12.9"], None)):
            fs = FakeSystem(tmpdir(self))
            fs.py_versions = have
            t = collect(fs, packages=pk)["sections"]["tools"]["data"]
            self.assertEqual((t["packages"]["python313"]["works"], t["packages"]["python313"]["version"]), (bool(want), want))
            self.assertEqual(t["python313"]["version"], want, have)

    def test_hypervisor_makes_virtualization_ok(self):
        need(self, "Windows", probe.IS_WIN)
        d = collect(FakeSystem(tmpdir(self), ps={"hv": True, "fw": False}), network=False)["sections"]["virtualization"]["data"]
        self.assertTrue(d["virt_ok"])
        d = collect(FakeSystem(tmpdir(self), ps={"hv": False, "fw": False}), network=False)["sections"]["virtualization"]["data"]
        self.assertFalse(d["virt_ok"])

    def test_wsl_output_is_decoded_as_utf16(self):
        need(self, "Windows", probe.IS_WIN)
        fs = FakeSystem(tmpdir(self), wsl_installed=True, distros=[("Linux-A", 2), ("Linux-B", 1)])
        w = collect(fs, network=False)["sections"]["virtualization"]["data"]["wsl"]
        self.assertTrue(w["installed"])
        self.assertEqual(w["version"], "2.3.26")
        self.assertEqual([(x["name"], x["version"]) for x in w["distros"]], [("Linux-A", 2), ("Linux-B", 1)])


class PolicyTests(unittest.TestCase):
    def test_simulated_policy_blocks_are_read(self):
        need(self, "Windows", probe.IS_WIN)
        reg = {r"HKLM\SOFTWARE\Policies\Microsoft\Edge": {"RemoteDebuggingAllowed": 0},
               r"HKLM\SOFTWARE\Policies\WSL": {"AllowWSL": 0},
               r"HKLM\SOFTWARE\Policies\ClaudeCode": {"Settings": json.dumps(
                   {"allowManagedHooksOnly": True, "deniedModels": ["claude-opus-5-5"], "strictKnownMarketplaces": []})}}
        doc = collect(FakeSystem(tmpdir(self), registry=reg), network=False)["sections"]
        self.assertIs(doc["capture"]["data"]["automation_allowed"], False)
        self.assertEqual(doc["policies"]["data"]["wsl"]["AllowWSL"], 0)
        m = doc["policies"]["data"]["managed_claude"]
        self.assertTrue(m["hooks_managed_only"] and m["marketplaces_strict"])
        self.assertEqual(doc["models"]["data"]["denied"], ["claude-opus-5-5"])
        self.assertEqual(doc["models"]["data"]["available"], "unverified")

    def test_managed_allow_list_is_verified(self):
        need(self, "Windows", probe.IS_WIN)
        reg = {r"HKCU\SOFTWARE\Policies\ClaudeCode": {"Settings": json.dumps({"availableModels": ["claude-sonnet-5"]})}}
        d = collect(FakeSystem(tmpdir(self), registry=reg), network=False)["sections"]["models"]["data"]
        self.assertEqual(d["available"], ["claude-sonnet-5"])
        self.assertTrue(d["enforce"])

    def test_managed_file_is_read(self):
        d = tmpdir(self)
        f = os.path.join(d, "managed.json")
        with open(f, "w", encoding="utf-8") as fh:
            json.dump({"disableAllHooks": True, "allowedMcpServers": [{"serverName": "alpha"}, "beta"]}, fh)
        doc = probe.collect(only=["policies"], managed_files=[f], kit=KIT, network=False, run_=lambda a, t=15: (None, b""),
                            which_=lambda n: None, environ={})
        m = doc["sections"]["policies"]["data"]["managed_claude"]
        self.assertTrue(m["disable_all_hooks"])
        self.assertEqual(m["mcp_allow"], ["alpha", "beta"])

    def test_doctor_parse_is_marked_unparsed_when_unknown(self):
        self.assertFalse(probe.parse_doctor("nothing useful here")["parsed"])
        r = probe.parse_doctor("Managed settings (remote): fetched\nOrganization policy: none")
        self.assertEqual((r["server_managed"], r["org_policy"], r["parsed"]), (True, False, True))
        r = probe.parse_doctor("Managed settings (remote): not fetched - no usable credentials\nOrganization policy: not fetched: no key")
        self.assertEqual((r["server_managed"], r["org_policy"], r["parsed"]), (None, None, True))

    def test_doctor_runs_only_on_request(self):
        need(self, "Windows", probe.IS_WIN)
        fs = FakeSystem(tmpdir(self))
        d = collect(fs, only=["claude"], network=False)["sections"]["claude"]
        self.assertFalse([c for c in fs.calls if c[:2] == ["claude", "doctor"]])
        self.assertFalse(d["data"]["doctor"]["parsed"])
        d = collect(fs, only=["claude"], network=False, doctor=True)["sections"]["claude"]
        self.assertTrue([c for c in fs.calls if c[:2] == ["claude", "doctor"]])
        self.assertEqual(d["data"]["doctor"]["server_managed"], False)

    def test_claude_version_survives_a_banner_line(self):
        need(self, "Windows", probe.IS_WIN)
        fs = FakeSystem(tmpdir(self))

        def stored(text, rc=0):
            def run(argv, timeout=15):
                if probe._stem(argv[0]) == "claude" and argv[1:] == ["--version"]:
                    return rc, text.encode()
                return fs(argv, timeout)
            doc = collect(fs, only=["claude", "tools"], network=False, run_=run, packages=fixture_file())["sections"]
            seen = {doc["claude"]["data"]["version"], doc["tools"]["data"]["claude"]["version"],
                    doc["tools"]["data"]["packages"]["claude"]["version"]}
            self.assertEqual(len(seen), 1, seen)                   # the claude section, the tools entry and the package check agree
            return seen.pop()
        self.assertEqual(stored("Update available: 9.9.9\r\n2.1.292 (Claude Code)\r\n"), "2.1.292")   # the banner's number is not it
        self.assertEqual(stored("Welcome back 7.7.7\nClaude Code v2.1.292"), "2.1.292")
        self.assertEqual(stored("2.1.292 (Claude Code)"), "2.1.292")
        self.assertEqual(stored("claude 2.1.0"), "2.1.0")                       # plain output: the first version, as before
        self.assertEqual(stored("2.1.292 (Claude Code)", rc=1), None)           # a failed command stores no version
        self.assertEqual(stored("x" * 3000 + " 2.1.292 (Claude Code)"), None)    # the scan is capped


class PowerShellControlTests(unittest.TestCase):
    """What PowerShell lets Claude do: the language mode, the effective script policy and the two group-policy scopes."""
    FULL = {"language_mode": "FullLanguage", "execution_policy": "RemoteSigned", "gpo_machine": "Undefined", "gpo_user": "Undefined"}

    def facts(self, **ps):
        need(self, "Windows", probe.IS_WIN)
        fs = FakeSystem(tmpdir(self), ps=ps)
        return collect(fs, only=["app_control"], network=False)["sections"]["app_control"]["data"]["powershell"]

    def test_full_language_with_no_group_policy(self):
        self.assertEqual(self.facts(), self.FULL)

    def test_constrained_language_is_reported_as_it_is(self):
        self.assertEqual(self.facts(lang="ConstrainedLanguage")["language_mode"], "ConstrainedLanguage")
        for mode in ("RestrictedLanguage", "NoLanguage"):
            self.assertEqual(self.facts(lang=mode)["language_mode"], mode)

    def test_group_policy_scopes_are_kept_apart(self):
        f = self.facts(execpol="AllSigned", pol_machine="AllSigned", pol_user="Restricted")
        self.assertEqual((f["execution_policy"], f["gpo_machine"], f["gpo_user"]), ("AllSigned", "AllSigned", "Restricted"))
        f = self.facts(pol_machine="Undefined", pol_user="AllSigned")
        self.assertEqual((f["gpo_machine"], f["gpo_user"]), ("Undefined", "AllSigned"))

    def test_case_is_normalised_and_junk_or_missing_values_read_as_unknown(self):
        self.assertEqual(self.facts(lang="fulllanguage", execpol="remotesigned")["language_mode"], "FullLanguage")
        f = self.facts(lang="bogus", execpol=None, pol_machine="", pol_user=42)
        self.assertEqual(set(f.values()), {"unknown"})

    def test_a_failed_powershell_gives_unknown_everywhere(self):
        need(self, "Windows", probe.IS_WIN)
        doc = probe.collect(only=["app_control"], run_=lambda a, t=15: (None, b""), which_=lambda n: None, environ={},
                            managed_files=[], kit=KIT, network=False)["sections"]["app_control"]
        self.assertEqual(doc["status"], "unavailable")
        self.assertEqual(set(doc["data"]["powershell"].values()), {"unknown"})
        self.assertEqual(set(doc["data"]["powershell"]), set(self.FULL))     # the keys exist even when nothing could be read


class AddendumTests(unittest.TestCase):
    def cap(self, **kw):
        need(self, "Windows", probe.IS_WIN)
        return collect(FakeSystem(tmpdir(self), **kw), network=False)["sections"]["capture"]["data"]

    def test_outlook_and_teams_clients(self):
        self.assertEqual(self.cap()["outlook_client"], "none")
        self.assertEqual(self.cap()["teams_client"], "new")
        self.assertEqual(self.cap(registry={r"HKLM\SOFTWARE\Classes\Outlook.Application": {"(Default)": "x"}})["outlook_client"], "classic")
        self.assertEqual(self.cap(ps={"outlook_new": True})["outlook_client"], "new")
        both = self.cap(ps={"outlook_new": True}, registry={r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE": {"(Default)": "x"}})
        self.assertEqual(both["outlook_client"], "both")
        self.assertEqual(self.cap(ps={"teams_new": False})["teams_client"], "none")
        self.assertEqual(self.cap(ps={"appxok": False})["outlook_client"], "unknown")

    def test_cache_window_and_object_model_policy(self):
        c = self.cap()
        self.assertIsNone(c["outlook_cache_window"])
        self.assertEqual(c["outlook_object_model_policy"], {})
        c = self.cap(registry={r"HKCU\Software\Microsoft\Office\16.0\Outlook\Cached Mode": {"SyncWindowSetting": 3}})
        self.assertEqual(c["outlook_cache_window"], "3 months")
        c = self.cap(registry={r"HKCU\Software\Policies\Microsoft\Office\16.0\Outlook\Cached Mode": {"SyncWindowSetting": 1, "SyncWindowSettingDays": 14}})
        self.assertEqual(c["outlook_cache_window"], "14 days")
        c = self.cap(registry={r"HKLM\Software\Policies\Microsoft\Office\16.0\Outlook\Security": {"AdminSecurityMode": 3, "PromptOOMAddressBookAccess": 2}})
        self.assertEqual(c["outlook_object_model_policy"], {"AdminSecurityMode": 3, "PromptOOMAddressBookAccess": 2})

    def work(self, accounts, docs=r"D:\Docs"):
        need(self, "Windows", probe.IS_WIN)
        base = r"HKCU\Software\Microsoft\OneDrive\Accounts"
        reg = {base: {"LastUpdate": 1}, base + r"\Personal": {"UserFolder": r"D:\Home\Personal"}}
        for i, root in enumerate(accounts, 1):
            reg["%s\\Business%d" % (base, i)] = {"UserFolder": root}
        fs = FakeSystem(tmpdir(self), registry=reg, ps={"docs": docs})
        s = collect(fs, network=False)["sections"]["knowledge"]
        return s["data"]["work_cloud"], s["notes"]

    def test_work_cloud_accounts(self):
        wc, _ = self.work([])
        self.assertEqual((wc["found"], wc["root"], wc["accounts"]), (False, None, 0))   # a personal account never counts
        wc, _ = self.work([r"D:\Work\Org One"], docs=r"D:\Work\Org One\Documents")
        self.assertEqual((wc["found"], wc["root"], wc["accounts"], wc["kfm"]), (True, r"D:\Work\Org One", 1, True))
        wc, _ = self.work([r"D:\Work\Org One"], docs=r"D:\Docs")
        self.assertIs(wc["kfm"], False)
        wc, notes = self.work([r"D:\Work\Org One", r"D:\Work\Org Two"])
        self.assertEqual((wc["found"], wc["root"], wc["accounts"]), (True, None, 2))
        self.assertIn("several work accounts: setup will ask", notes)


class KnowledgeVerifyTests(unittest.TestCase):
    """IK2: the probe reads <WB>/state/knowledge-verify.json (read-only) into knowledge.verify."""
    def verify(self, text=None):
        need(self, "Windows", probe.IS_WIN)
        fs = FakeSystem(tmpdir(self))
        if text is not None:
            f = os.path.join(fs.environ["CLAUDE_CONFIG_DIR"], "workbench", "state", "knowledge-verify.json")
            os.makedirs(os.path.dirname(f))
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(text)
            before = tree(fs.environ["CLAUDE_CONFIG_DIR"])
        s = collect(fs, network=False)["sections"]["knowledge"]
        if text is not None:
            self.assertEqual(tree(fs.environ["CLAUDE_CONFIG_DIR"]), before, "the probe only reads it")
        return s["data"]["verify"], s["notes"]

    def test_missing_file_is_not_run_yet(self):
        self.assertEqual(self.verify(), (None, []))

    def test_summary_is_read(self):
        doc = {"version": 1, "generated": "2026-10-08T01:02:03Z", "kit_version": "0.3.0",
               "steps": [{"id": "D3", "name": "kb-machinery", "status": "FAIL", "detail": "x", "ms": 5, "ask_it": None}],
               "summary": {"pass": 12, "warn": 1, "fail": 1, "failing": ["D3"]}}
        v, notes = self.verify(json.dumps(doc))
        self.assertEqual(v, {"pass": 12, "warn": 1, "fail": 1, "failing": ["D3"], "generated": "2026-10-08T01:02:03Z",
                             "steps": {"D3": "FAIL"}, "tools": {}})
        self.assertEqual(notes, [])

    def test_each_optional_tool_status_of_d18_is_carried_apart(self):
        doc = {"version": 1, "generated": "2026-10-08T01:02:03Z",
               "steps": [{"id": "D18", "name": "opt-ins", "status": "WARN", "detail": "x", "ms": 5, "ask_it": None,
                          "tools": {"ctx": "PASS", "tokensave": "WARN"}}],
               "summary": {"pass": 0, "warn": 1, "fail": 0, "failing": []}}
        v, notes = self.verify(json.dumps(doc))
        self.assertEqual((v["steps"], v["tools"]), ({"D18": "WARN"}, {"ctx": "PASS", "tokensave": "WARN"}))
        self.assertEqual(notes, [])

    def test_a_broken_file_is_none_with_a_note(self):
        for text in ("not json", "{}", '{"summary": {"pass": "x"}}', '{"summary": []}', "[]"):
            v, notes = self.verify(text)
            self.assertIsNone(v, text)
            self.assertIn("knowledge-verify.json not understood", notes, text)


class FindCliTests(unittest.TestCase):
    def test_find_cli_stub_is_used_for_discover_and_status(self):
        need(self, "Windows", probe.IS_WIN)
        cli = [sys.executable, "stub_find.py"]
        libs = [{"path": "D:/Lib", "kind": "documents", "label": "docs", "on_device_files": 3, "cloud_only_files": 0, "sampled": False}]
        fs = FakeSystem(tmpdir(self), find=cli, libs=libs, env={"WORKBENCH_FIND_CLI": json.dumps(cli)})
        k = collect(fs, network=False)["sections"]["knowledge"]
        self.assertEqual(k["data"]["libraries"], libs)
        self.assertTrue(k["data"]["find"]["available"])
        self.assertEqual(k["data"]["find"]["mode"], "keyword")


class NetworkTests(unittest.TestCase):
    def test_unreachable_invalid_is_blocked_dns(self):
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        r = probe.fetch("https://unreachable.invalid/", opener=op)
        self.assertEqual((r["result"], r["category"]), ("blocked", "dns"))
        doc = probe.collect(only=["network"], extras=["https://unreachable.invalid/"], fetch_=functools.partial(probe.fetch, opener=op),
                            run_=lambda a, t=15: (None, b""), which_=lambda n: None,
                            environ={"ANTHROPIC_BASE_URL": "https://gateway.invalid/"}, managed_files=[], kit=KIT)
        eps = {e["name"]: e for e in doc["sections"]["network"]["data"]["endpoints"]}
        self.assertEqual((eps["extra:unreachable.invalid"]["result"], eps["extra:unreachable.invalid"]["category"]), ("blocked", "dns"))

    def test_proxy_407_is_proxy_auth_and_is_retested_with_negotiate(self):
        class H(http.server.BaseHTTPRequestHandler):
            def do_CONNECT(self):
                self.send_response(407)
                self.send_header("Proxy-Authenticate", "Negotiate")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("localhost", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({"https": "http://localhost:%d" % srv.server_address[1]}))
        r = probe.fetch("https://example.com/", opener=op)
        self.assertEqual(r["result"], "proxy-auth")
        calls = []

        def run(argv, timeout=15):
            calls.append(argv)
            return 0, b"200"
        doc = probe.collect(only=["network"], extras=["https://example.com/"], fetch_=functools.partial(probe.fetch, opener=op),
                            run_=run, which_=lambda n: None, environ={}, managed_files=[], kit=KIT)
        eps = doc["sections"]["network"]["data"]["endpoints"]
        self.assertTrue(eps and all(e["result"] == "proxy-auth" and e["proxy_negotiate_ok"] is True for e in eps))
        self.assertTrue(any("--proxy-negotiate" in c for c in calls))

    def test_only_listed_hosts_are_contacted_serially_with_the_user_agent(self):
        need(self, "Windows", probe.IS_WIN)
        fs = FakeSystem(tmpdir(self))
        rec = RecOpener()
        doc = collect(fs, packages=fixture_file(), git_hosts=["ghe.example.com"], extras=["https://extra.example.com/x"],
                      fetch_=functools.partial(probe.fetch, opener=rec))
        allowed = FIXTURE_HOSTS | {"api.anthropic.com", "ghe.example.com", "extra.example.com"}
        hosts = [h for h, *_ in rec.seen]
        self.assertTrue(hosts)
        self.assertLessEqual(set(hosts), allowed)
        self.assertEqual({u for _h, _m, u, _t in rec.seen}, {probe.UA})
        self.assertEqual(probe.UA, "claude-workbench-probe/" + probe.KIT_VERSION)
        self.assertEqual(rec.max_active, 1)
        self.assertEqual(len({t for *_x, t in rec.seen}), 1)
        self.assertEqual({m for _h, m, *_x in rec.seen}, {"HEAD"})
        self.assertLessEqual(set(fs.tls_hosts), allowed)
        urls = [c[-1] for c in fs.calls if probe._stem(c[0]) == "curl" and "--max-time" in c] + [c[-2] for c in fs.calls if "ls-remote" in c] + \
               [c[-1] for c in fs.calls if c[:2] == ["node", "-e"]]
        for u in urls:
            self.assertIn(probe.host_of(u) or u, allowed)
        self.assertEqual(doc["sections"]["network"]["data"]["user_agent"], probe.UA)

    def test_budget_cuts_the_remaining_endpoints(self):
        need(self, "Windows", probe.IS_WIN)
        t = [0.0]

        def slow(url, timeout=4):
            t[0] += 20
            return {"method": "HEAD", "result": "ok", "category": None, "http_status": 200, "bytes": 0, "ms": 20000}
        fs = FakeSystem(tmpdir(self))
        doc = collect(fs, only=["network"], packages=fixture_file(), fetch_=slow, clock=lambda: t[0])
        res = [(e["result"], e["category"]) for e in doc["sections"]["network"]["data"]["endpoints"]]
        self.assertEqual(res[:3], [("ok", None)] * 3)
        self.assertTrue(all(r == ("not-tested", "budget") for r in res[3:]), res)

    def test_http_405_on_head_falls_back_to_a_bounded_get(self):
        class Op:
            def __init__(self):
                self.methods = []

            def open(self, req, timeout=None):
                self.methods.append(req.get_method())
                if req.get_method() == "HEAD":
                    raise urllib.error.HTTPError(req.full_url, 405, "no", {}, None)
                return Resp()
        op = Op()
        r = probe.fetch("https://example.com/", opener=op)
        self.assertEqual((op.methods, r["method"], r["result"]), (["HEAD", "GET"], "GET", "ok"))

    def test_quick_skips_the_network_entirely(self):
        fs = FakeSystem(tmpdir(self))
        doc = collect(fs, packages=fixture_file(), quick=True)
        self.assertEqual(fs.fetched, [])
        self.assertEqual({e["result"] for e in doc["sections"]["network"]["data"]["endpoints"]}, {"not-tested"})


class WriteTests(unittest.TestCase):
    def test_writes_only_under_out(self):
        tmp = tmpdir(self)
        home, out = os.path.join(tmp, "home"), os.path.join(tmp, "out")
        for sub in ("home", "home/.claude", "home/AppData/Local", "home/AppData/Roaming", "tmp"):
            os.makedirs(os.path.join(tmp, sub), exist_ok=True)
        env = dict(os.environ, HOME=home, USERPROFILE=home, APPDATA=os.path.join(home, "AppData/Roaming"),
                   LOCALAPPDATA=os.path.join(home, "AppData/Local"), TEMP=os.path.join(tmp, "tmp"), TMP=os.path.join(tmp, "tmp"),
                   TMPDIR=os.path.join(tmp, "tmp"), CLAUDE_CONFIG_DIR=os.path.join(home, ".claude"))

        def snap(root, skip):
            s = set()
            for dp, _dn, fn in os.walk(root):
                if os.path.abspath(dp).startswith(os.path.abspath(skip)):
                    continue
                s |= {(os.path.relpath(os.path.join(dp, f), root), os.path.getsize(os.path.join(dp, f))) for f in fn}
            return s
        kit_before = tree(HERE)
        before = snap(tmp, out)
        p = subprocess.run([sys.executable, os.path.join(HERE, "probe.py"), "--out", out, "--no-network", "--packages", fixture_file()],
                           env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        extra = snap(tmp, out) - before
        self.assertEqual(extra, set(), "files written outside --out")
        self.assertEqual(sorted(os.listdir(out)), ["probe.json", "probe.md"])
        self.assertEqual(tree(HERE), kit_before, "the kit folder changed")
        self.assertEqual(len(rj(os.path.join(out, "probe.json"))["sections"]), 16)

    def test_usage_error_exits_2(self):
        p = subprocess.run([sys.executable, os.path.join(HERE, "probe.py"), "--only", "nonsense"], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 2)


class LiveTests(unittest.TestCase):
    @unittest.skipUnless(LIVE, "WB_LIVE=1 runs the full live probe")
    def test_full_probe_stays_under_90_seconds(self):
        doc = probe.collect(packages=fixture_file(), extras=["https://unreachable.invalid/"], kit=KIT)
        self.assertEqual(len(doc["sections"]), 16)
        self.assertLess(doc["duration_s"], 90)


if __name__ == "__main__":
    unittest.main()
