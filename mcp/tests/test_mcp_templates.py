"""Tests for mcp/golden-config.template.json, the GitHub helper scripts and the healer's handling of the catalog.

Run: WB_REQUIRE_ALL=1 py -3 -m unittest discover -s mcp/tests -v
No network: fake `gh` and fake server programs are written into a temp dir at test time.
"""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: nothing below skips; a missing file fails

import importlib.util  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tarfile  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
import zipfile  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402
from hashlib import sha256  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest import mock  # noqa: E402

KIT = Path(__file__).resolve().parents[2]
TEMPLATE = KIT / "mcp" / "golden-config.template.json"
HEADERS = KIT / "mcp" / "bin" / "gh_mcp_headers.py"
LOCAL = KIT / "mcp" / "bin" / "gh_mcp_local.py"
for sub in ("mcp/bin", "tools/mcp-healer", "plugins/workbench-core/scripts"):
    sys.path.insert(0, str(KIT / sub))
import gh_mcp_headers  # noqa: E402
import gh_mcp_local  # noqa: E402
import mcp_healer as mh  # noqa: E402
import secretscan  # noqa: E402

TEXT = TEMPLATE.read_text(encoding="utf-8")
SERVERS = json.loads(TEXT)["servers"]
ENSURE_OK = {"find"}                # local, no-egress servers that ship on; find is registered by setup
PARK_OK = {"tokensave"}             # local, no-egress, registered PARKED: its serve exits until a repository is indexed
REF = re.compile(r"^(Bearer )?\$\{[A-Z0-9_]+(:-[^}]*)?\}$")
SECRETISH = re.compile(r"(?i)token|secret|key|password|passwd|\bpat\b|_pat\b|auth")

I7_FIND = {"action": "ensure", "egress": "none: local index on this machine",
           "command": "{{KNOWLEDGE_PYTHON}}",
           "args": ["{{WORKBENCH_HOME}}/kit/plugins/workbench-core/skills/find/scripts/find_mcp.py"],
           "alwaysLoad": False,
           "reason": "Registered by setup: the find skill's search, show and related as MCP tools for subagents and the "
                     "desktop app. Local index, no network. The skill and CLI stay the primary interface."}


def make_launcher(folder, name, py_source):
    """A program called `name` that runs py_source with this interpreter (name.cmd on Windows, a script elsewhere)."""
    folder = Path(folder)
    script = folder / (name + "_impl.py")
    script.write_text(py_source, encoding="utf-8")
    if os.name == "nt":
        path = folder / (name + ".cmd")
        path.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        path = folder / name
        path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        path.chmod(0o755)
    return path


FAKE_GH = '''
import json, os, sys
open(os.environ["FAKE_RECORD"], "a").write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:4] == ["auth", "token", "--hostname"] and os.environ.get("FAKE_GH_MODE") != "notoken":
    print("fake-token-for-test")
else:
    sys.exit(1)
'''
FAKE_SERVER = '''
import json, os, sys
env = {k: v for k, v in os.environ.items() if k.upper().startswith("GITHUB_")}
open(os.environ["FAKE_RECORD"], "w").write(json.dumps({"argv": sys.argv[1:], "env": env}))
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.bin = self.d / "bin"
        self.bin.mkdir()
        self.record = self.d / "record.jsonl"
        self.env = dict(os.environ, PATH=str(self.bin), FAKE_RECORD=str(self.record))
        self.env.pop("FAKE_GH_MODE", None)

    def helper(self, *args, cwd=None, env=None):
        return subprocess.run([sys.executable, str(HEADERS), *args], capture_output=True, text=True,
                              env=env or self.env, cwd=cwd, timeout=60)

    def calls(self):
        return [json.loads(x) for x in self.record.read_text().splitlines()] if self.record.exists() else []


class TemplateTest(unittest.TestCase):
    def test_valid_json_and_every_entry_states_its_egress(self):
        self.assertTrue(SERVERS)
        for name, spec in SERVERS.items():
            self.assertTrue(spec.get("egress"), f"{name}: no egress line")
            self.assertIn(spec.get("action"), ("ensure", "ignore", "park"), name)
            if name not in ENSURE_OK | PARK_OK:
                self.assertEqual(spec["action"], "ignore", f"{name} must ship off")
            self.assertIs(spec.get("alwaysLoad"), False, name)

    def test_every_credential_is_a_reference_or_a_helper(self):
        for name, spec in SERVERS.items():
            for block in ("env", "headers"):
                for k, v in (spec.get(block) or {}).items():
                    if SECRETISH.search(k):
                        self.assertRegex(v, REF, f"{name}.{block}.{k} is not a ${{VAR}} reference")
            if "oauth" in spec:
                self.assertRegex(spec["oauth"]["clientId"], REF, name)
            if "headersHelper" in spec:
                self.assertNotRegex(spec["headersHelper"], r"(?i)bearer|token=|password", name)
        self.assertEqual(secretscan.scan_text(TEXT), [], "secretscan found a credential-shaped literal")

    def test_secretscan_would_catch_a_literal(self):          # test the test
        literal = TEXT.replace("Bearer ${WB_GITHUB_MCP_PAT}", "Bearer " + "a1b2c3d4" * 5, 1)
        self.assertTrue(secretscan.scan_text(literal))
        with self.assertRaises(AssertionError):
            self.assertRegex("Bearer " + "a1b2c3d4" * 5, REF)

    def test_tokensave_ships_parked_and_the_healer_registers_it_parked_when_filled(self):
        spec = SERVERS["tokensave"]
        self.assertEqual((spec["action"], spec["args"]), ("park", ["serve"]))
        self.assertIn("PARKED", spec["reason"])
        with tempfile.TemporaryDirectory() as t:
            cfg, golden = os.path.join(t, ".claude.json"), os.path.join(t, "golden.json")
            Path(cfg).write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
            Path(golden).write_text(json.dumps({"servers": {"tokensave": dict(spec, command="/opt/bin/tokensave")}}), encoding="utf-8")
            c = json.loads(Path(cfg).read_text(encoding="utf-8"))
            changes, warnings = mh.plan(json.loads(Path(golden).read_text(encoding="utf-8")), c)
            self.assertEqual(warnings, [])
            self.assertEqual(c["mcpServers"], {}, "nothing live")
            self.assertEqual(c["mcpServersParked"]["tokensave"]["command"], "/opt/bin/tokensave")
            self.assertTrue(any("registered parked" in x for x in changes))
            c = {"mcpServers": {}}
            _, warnings = mh.plan({"servers": {"tokensave": spec}}, c)
            self.assertTrue(any("PLACEHOLDER" in w for w in warnings), "an unfilled template entry is refused, as before")

    def test_find_entry_is_interface_I7_exactly(self):
        self.assertEqual(SERVERS["find"], I7_FIND)

    def test_only_local_no_egress_servers_ship_on(self):
        on = {k for k, v in SERVERS.items() if v["action"] == "ensure"}
        self.assertEqual(on, ENSURE_OK)
        self.assertEqual({k for k, v in SERVERS.items() if v["action"] == "park"}, PARK_OK)
        for k in on | PARK_OK:
            self.assertTrue(SERVERS[k]["egress"].startswith(("none", "local")), f"{k} ships on but its egress is not local")

    def test_the_playwright_mcp_server_ships_off_because_the_cli_is_preferred(self):
        pw = SERVERS["playwright"]
        self.assertEqual(pw["action"], "ignore")
        self.assertTrue(pw["reason"].startswith("OPTIONAL, off by default"))
        self.assertIn("Playwright CLI", pw["reason"])
        self.assertTrue(any(a.startswith("@playwright/mcp@") and "latest" not in a for a in pw["args"]), "still pinned")

    def test_healer_skips_find_until_setup_fills_the_placeholders(self):
        d = Path(tempfile.mkdtemp())
        golden, cfg, managed = d / "golden.json", d / ".claude.json", d / "managed"
        managed.mkdir()
        golden.write_text(json.dumps({"servers": {"find": SERVERS["find"]}}), encoding="utf-8")
        cfg.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            mh.main(["--config", str(cfg), "apply", "--golden", str(golden), "--managed-dir", str(managed), "--dry-run"])
        self.assertIn("SKIPPED find", buf.getvalue())
        self.assertIn("still has a {{PLACEHOLDER}}", buf.getvalue())
        self.assertIn("{{KNOWLEDGE_PYTHON}}", json.dumps(SERVERS["find"]))      # what setup has to fill

    def test_github_recipes(self):
        g, pat, ghe, loc = (SERVERS[k] for k in ("github", "github-pat", "github-ghe", "github-local"))
        self.assertEqual(g["url"], "https://api.githubcopilot.com/mcp/readonly")
        self.assertEqual(g["headersHelper"], "{{PYTHON}} {{WORKBENCH_HOME}}/kit/mcp/bin/gh_mcp_headers.py github.com")
        self.assertNotIn("Authorization", g["headers"])
        self.assertEqual(g["headers"]["X-MCP-Lockdown"], "true")
        self.assertIn("X-MCP-Toolsets", g["headers"])
        self.assertEqual(pat["headers"]["Authorization"], "Bearer ${WB_GITHUB_MCP_PAT}")
        self.assertRegex(ghe["url"], r"^https://copilot-api\.\{\{GHE_SUBDOMAIN\}\}\.ghe\.com/mcp$")
        self.assertEqual(ghe["headers"]["X-MCP-Readonly"], "true")
        self.assertEqual(loc["args"][0], "{{WORKBENCH_HOME}}/kit/mcp/bin/gh_mcp_local.py")
        self.assertNotRegex(TEXT, r"(?<!WB_)GITHUB_MCP_PAT")      # the old name is gone
        self.assertNotRegex(TEXT.lower(), r"dynamic-toolsets")

    def test_catalog_has_the_enterprise_servers_with_pinned_launchers(self):
        for name in ("mslearn", "azure", "azure-devops", "atlassian", "bigquery", "gcloud", "ms365"):
            self.assertIn(name, SERVERS)
        self.assertEqual(SERVERS["atlassian"]["url"], "https://mcp.atlassian.com/v2/mcp")
        self.assertIn("azcli", SERVERS["azure-devops"]["args"])
        for name, spec in SERVERS.items():
            if spec.get("command") == "npx":
                pkgs = [a for a in spec["args"] if re.match(r"^(@[\w.-]+/)?[\w.-]+@", a)]
                self.assertTrue(pkgs, name)
                for a in pkgs:
                    self.assertRegex(a, r"@\d+\.\d+\.\d+$", f"{name}: {a} is not an exact version")

    def test_ms365_entry(self):
        m = SERVERS["ms365"]
        self.assertEqual(m["action"], "ignore")
        self.assertEqual(m["egress"], "Microsoft Graph only")
        self.assertEqual(m["env"], {"MS365_MCP_CLIENT_ID": "${WB_MS365_CLIENT_ID}", "MS365_MCP_TENANT_ID": "${WB_MS365_TENANT_ID}"})
        pkg = next(a for a in m["args"] if "ms-365-mcp-server" in a)
        self.assertRegex(pkg, r"^@softeria/ms-365-mcp-server@\d+\.\d+\.\d+$")
        for flag in ("--read-only", "--org-mode", "--enabled-tools"):
            self.assertIn(flag, m["args"])
        allow = m["args"][m["args"].index("--enabled-tools") + 1]
        names = re.fullmatch(r"\^\(([a-z0-9|-]+)\)\$", allow).group(1).split("|")
        self.assertGreaterEqual(len(names), 10)
        for n in names:
            self.assertRegex(n, r"^(list|get)-", n)                                     # reads only
            self.assertNotRegex(n, r"shared|attachment|batch|bytes|recording|send|create|update|delete", n)
        for need in ("mail", "calendar", "transcript"):
            self.assertTrue(any(need in n for n in names), need)
        self.assertRegex(m["reason"], r"(?i)admin")
        self.assertRegex(m["reason"], r"(?i)transcript")
        self.assertNotIn("--http", m["args"])

    def test_healer_refuses_ms365_until_both_variables_are_set(self):
        d = Path(tempfile.mkdtemp())
        golden, cfg, managed = d / "golden.json", d / ".claude.json", d / "managed"
        managed.mkdir()
        entry = dict(SERVERS["ms365"], action="ensure")
        golden.write_text(json.dumps({"servers": {"ms365": entry}}), encoding="utf-8")
        cfg.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        both = {"WB_MS365_CLIENT_ID": "client-id-value", "WB_MS365_TENANT_ID": "tenant-id-value"}

        def apply(env):
            clean = {k: v for k, v in os.environ.items() if k not in both}
            buf = io.StringIO()
            with mock.patch.dict(os.environ, {**clean, **env}, clear=True), redirect_stdout(buf):
                rc = mh.main(["--config", str(cfg), "apply", "--golden", str(golden), "--managed-dir", str(managed)])
            return rc, buf.getvalue()

        rc, out = apply({})
        self.assertIn("SKIPPED ms365", out)
        self.assertIn("WB_MS365_CLIENT_ID, WB_MS365_TENANT_ID", out)
        rc, out = apply({"WB_MS365_CLIENT_ID": "client-id-value"})
        self.assertIn("SKIPPED ms365", out)
        self.assertIn("WB_MS365_TENANT_ID", out)
        self.assertNotIn("WB_MS365_CLIENT_ID,", out)
        self.assertEqual(json.loads(cfg.read_text())["mcpServers"], {})
        rc, out = apply(both)
        self.assertEqual(rc, 0, out)
        written = json.loads(cfg.read_text())["mcpServers"]["ms365"]
        self.assertEqual(written["env"], entry["env"])                                  # references, never values
        self.assertNotIn("client-id-value", cfg.read_text() + out)

    def test_healer_refuses_unfilled_placeholders_in_the_github_entries(self):
        d = Path(tempfile.mkdtemp())
        golden, cfg, managed = d / "golden.json", d / ".claude.json", d / "managed"
        managed.mkdir()
        golden.write_text(json.dumps({"servers": {k: dict(SERVERS[k], action="ensure") for k in ("github", "github-ghe", "github-local")}}), encoding="utf-8")
        cfg.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"WB_GITHUB_MCP_PAT": "x"}), redirect_stdout(buf):
            mh.main(["--config", str(cfg), "apply", "--golden", str(golden), "--managed-dir", str(managed), "--dry-run"])
        for k in ("github", "github-ghe", "github-local"):
            self.assertIn(f"SKIPPED {k}", buf.getvalue())


class HeadersHelperTest(Base):
    def test_prints_only_the_json_object(self):
        make_launcher(self.bin, "gh", FAKE_GH)
        r = self.helper("github.com")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"Authorization": "Bearer fake-token-for-test"})
        self.assertEqual(r.stdout, '{"Authorization":"Bearer fake-token-for-test"}')    # nothing else, no newline
        self.assertEqual(r.stderr, "")
        asked = ["auth", "token", "--hostname", "github.com"]
        self.assertEqual(self.calls(), [asked])

    def test_host_argument_is_passed_through(self):
        make_launcher(self.bin, "gh", FAKE_GH)
        self.assertEqual(self.helper("tenant.ghe.com").returncode, 0)
        asked = ["auth", "token", "--hostname", "tenant.ghe.com"]
        self.assertEqual(self.calls(), [asked])

    def test_exit_1_when_gh_has_no_token_and_nothing_leaks(self):
        make_launcher(self.bin, "gh", FAKE_GH)
        r = self.helper("github.com", env=dict(self.env, FAKE_GH_MODE="notoken"))
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("gh auth login", r.stderr)
        self.assertNotIn("fake-token", r.stderr)

    def test_exit_1_when_gh_is_missing(self):
        r = self.helper("github.com")
        self.assertEqual((r.returncode, r.stdout), (1, ""))

    def test_host_cannot_be_an_option(self):
        make_launcher(self.bin, "gh", FAKE_GH)
        r = self.helper("--hostname=evil")
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertEqual(self.calls(), [])

    def test_gh_planted_in_the_working_directory_is_never_run(self):
        work = self.d / "work"
        work.mkdir()
        make_launcher(work, "gh", FAKE_GH)                       # same name, but only in the current directory
        r = self.helper("github.com", cwd=work)
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertEqual(self.calls(), [])


class LocalWrapperTest(Base):
    def test_server_argv_is_interface_I10(self):
        self.assertEqual(gh_mcp_local.SERVER_ARGS,
                         ["stdio", "--read-only", "--lockdown-mode", "--toolsets=context,repos,issues,pull_requests,actions"])

    def test_child_env_drops_inherited_github_settings_and_sets_token_and_host(self):
        inherited = {"GITHUB_TOOLSETS": "all", "GITHUB_READ_ONLY": "0", "github_host": "x", "PATH": "p", "GITHUB_PERSONAL_ACCESS_TOKEN": "old"}
        env = gh_mcp_local.child_env("tenant.ghe.com", "tok", inherited)
        self.assertEqual(env, {"PATH": "p", "GITHUB_PERSONAL_ACCESS_TOKEN": "tok", "GITHUB_HOST": "https://tenant.ghe.com"})
        self.assertNotIn("GITHUB_HOST", gh_mcp_local.child_env("github.com", "tok", {}))

    def test_runs_the_server_with_token_in_the_child_environment_only(self):
        make_launcher(self.bin, "gh", FAKE_GH)
        server = make_launcher(self.d, "fake-server", FAKE_SERVER)
        out_file = self.d / "server.json"
        env = dict(self.env, WB_GH_MCP_BIN=str(server), FAKE_RECORD=str(out_file), GITHUB_TOOLSETS="all", GITHUB_READ_ONLY="0")
        r = subprocess.run([sys.executable, str(LOCAL), "tenant.ghe.com"], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")                                              # stdout is the MCP pipe
        got = json.loads(out_file.read_text())
        self.assertEqual(got["argv"], gh_mcp_local.SERVER_ARGS)
        self.assertEqual(got["env"], {"GITHUB_PERSONAL_ACCESS_TOKEN": "fake-token-for-test", "GITHUB_HOST": "https://tenant.ghe.com"})
        self.assertNotIn("fake-token", r.stderr)

    def test_no_binary_and_no_token_are_clear_errors(self):
        env = dict(self.env, WB_GH_MCP_BIN=str(self.d / "absent"))
        r = subprocess.run([sys.executable, str(LOCAL), "github.com"], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("--install", r.stderr)
        make_launcher(self.bin, "gh", FAKE_GH)
        server = make_launcher(self.d, "fake-server", FAKE_SERVER)
        env = dict(self.env, WB_GH_MCP_BIN=str(server), FAKE_GH_MODE="notoken")
        r = subprocess.run([sys.executable, str(LOCAL), "github.com"], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.d / "server.json").exists())

    def test_pins_are_a_release_tag_and_sha256_digests(self):
        self.assertRegex(gh_mcp_local.VERSION, r"^v\d+\.\d+\.\d+$")
        self.assertIn(gh_mcp_local.VERSION, gh_mcp_local.BASE)
        for key, (asset, digest) in gh_mcp_local.PINS.items():
            self.assertRegex(digest, r"^[0-9a-f]{64}$", key)
            self.assertTrue(asset.startswith("github-mcp-server_"), asset)

    def opener_for(self, blob):
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return lambda url: R(blob)

    def test_install_verifies_the_checksum_before_writing_anything(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("LICENSE", "mit")
            z.writestr("github-mcp-server.exe", b"binary-bytes")
        blob = buf.getvalue()
        pins = {("Windows", "x86_64"): ("github-mcp-server_Windows_x86_64.zip", sha256(blob).hexdigest())}
        dest = self.d / "out" / "github-mcp-server.exe"
        gh_mcp_local.install(dest, pins, self.opener_for(blob), "Windows", "x86_64")
        self.assertEqual(dest.read_bytes(), b"binary-bytes")
        self.assertEqual([p.name for p in dest.parent.iterdir()], ["github-mcp-server.exe"])       # no LICENSE, no .part
        bad = self.d / "bad" / "github-mcp-server.exe"
        with self.assertRaises(SystemExit) as cm:
            gh_mcp_local.install(bad, pins, self.opener_for(blob + b"tampered"), "Windows", "x86_64")
        self.assertIn("checksum mismatch", str(cm.exception))
        self.assertFalse(bad.parent.exists())
        with self.assertRaises(SystemExit):
            gh_mcp_local.install(bad, pins, self.opener_for(blob), "Plan9", "mips")

    def test_install_unpacks_a_tarball_member_by_name_only(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            info = tarfile.TarInfo("../../escape/github-mcp-server")
            payload = b"elf-bytes"
            info.size = len(payload)
            t.addfile(info, io.BytesIO(payload))
        blob = buf.getvalue()
        pins = {("Linux", "x86_64"): ("github-mcp-server_Linux_x86_64.tar.gz", sha256(blob).hexdigest())}
        dest = self.d / "out" / "github-mcp-server"
        gh_mcp_local.install(dest, pins, self.opener_for(blob), "Linux", "x86_64")
        self.assertEqual(dest.read_bytes(), b"elf-bytes")
        self.assertFalse((self.d / "escape").exists())


if __name__ == "__main__":
    unittest.main()
