"""Tests for plugin-factory: scaffold each kind into scratch, run the generated tests and check_plugin, validate with the
claude CLI (no model call, temporary config folder), start the generated stdio server and talk to it. Run:
  WB_REQUIRE_ALL=1 py -3 -m unittest discover -s plugins/workbench-core/skills/plugin-factory/tests -v
"""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: nothing below skips; a missing dependency fails

import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

SKILL = Path(__file__).resolve().parents[1]
SCAFFOLD = SKILL / "scripts" / "scaffold.py"
CHECK = SKILL / "scripts" / "check_plugin.py"
sys.path.insert(0, str(SKILL.parent / "plugin-review" / "scripts"))
CLAUDE = shutil.which("claude")
CASES = [("notes-content", "content", "cli", None), ("notes-guard", "guard", "all", None),
         ("notes-remote", "integration", "all", "remote"), ("notes-stdio", "integration", "cli", "stdio")]
TMP = REPO = None


def py(script, *args, cwd=None):
    return subprocess.run([sys.executable, "-I", str(script), *map(str, args)], capture_output=True, text=True, timeout=300, cwd=cwd)


def claude(*args):
    with tempfile.TemporaryDirectory() as cfg:
        env = dict(os.environ, CLAUDE_CONFIG_DIR=cfg)
        return subprocess.run([CLAUDE, *map(str, args)], capture_output=True, text=True, timeout=300, env=env, stdin=subprocess.DEVNULL)


def setUpModule():
    global TMP, REPO
    TMP = Path(tempfile.mkdtemp(prefix="wb-pf-test-"))
    REPO = TMP / "repo"
    for name, kind, surfaces, mcp in CASES:
        args = [name, "--kind", kind, "--surfaces", surfaces, "--out", REPO] + (["--mcp", mcp] if mcp else [])
        r = py(SCAFFOLD, *args + (["--org-overlay"] if name == "notes-guard" else []))
        assert r.returncode == 0, r.stderr


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class Generated(unittest.TestCase):
    def need_claude(self):
        if not CLAUDE:
            self.assertFalse(REQUIRE, "claude CLI not found")
            self.skipTest("claude CLI not found")

    def test_generated_tests_pass(self):
        for name, *_ in CASES:
            with self.subTest(name):
                r = subprocess.run([sys.executable, "-I", "-m", "unittest", "discover", "-s", str(REPO / "plugins" / name / "tests")],
                                   capture_output=True, text=True, timeout=300)
                self.assertEqual(r.returncode, 0, r.stderr[-800:])

    def test_check_plugin_passes_both_copies(self):
        for script in (CHECK, REPO / "tools" / "check_plugin.py"):
            r = py(script, REPO)
            self.assertEqual(r.returncode, 0, r.stdout)
            for name, *_ in CASES:
                self.assertIn(f"ok   {name}", r.stdout)

    def test_claude_validate_strict(self):
        self.need_claude()
        r = claude("plugin", "validate", REPO, "--strict")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for name, *_ in CASES:
            r = claude("plugin", "validate", REPO / "plugins" / name, "--strict")
            self.assertEqual(r.returncode, 0, name + r.stdout + r.stderr)

    def test_plugin_dir_details_lists_the_skill(self):
        self.need_claude()
        for name, *_ in CASES:
            with self.subTest(name):
                r = claude("--plugin-dir", REPO / "plugins" / name, "plugin", "details", name)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertRegex(r.stdout, rf"Skills \(1\)\s+{name}")

    def test_stdio_server_answers_initialize_and_tools_list(self):
        server = REPO / "plugins" / "notes-stdio" / "server" / "server.py"
        p = subprocess.Popen([sys.executable, "-I", str(server)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", bufsize=1)
        timer = threading.Timer(30, p.kill)
        timer.start()
        try:
            def ask(msg):
                p.stdin.write(json.dumps(msg) + "\n")
                p.stdin.flush()
                return json.loads(p.stdout.readline())
            init = ask({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}})
            self.assertEqual(init["result"]["serverInfo"]["name"], "notes-stdio")
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            tools = ask({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
            self.assertGreaterEqual(len(tools), 1)
            self.assertEqual(len(tools), 3)
            self.assertEqual(ask({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ping"}})["result"]["content"][0]["text"], "pong")
        finally:
            timer.cancel()
            p.kill()
            p.communicate()

    def test_generated_plugins_pass_the_reviewer(self):
        import review_plugin as RP
        for name, _k, surfaces, _m in CASES:
            with self.subTest(name):
                rep = RP.review(REPO / "plugins" / name, "cli" if surfaces == "cli" else "all")
                self.assertEqual([f for f in rep["findings"] if f["severity"] in ("block", "hold")], [])

    def test_web_surface_plugins_are_web_portable(self):
        packer = SKILL.parent / "web-packager" / "scripts" / "package_web.py"
        for name, _k, surfaces, _m in CASES:
            r = py(packer, REPO / "plugins" / name, "--check")
            self.assertEqual(r.returncode == 0, surfaces == "all", name + r.stdout)

    def test_ci_workflow_pins_every_action_by_commit(self):
        text = (REPO / ".github" / "workflows" / "plugins.yml").read_text(encoding="utf-8")
        uses = re.findall(r"uses:\s*(\S+)", text)
        self.assertTrue(uses)
        for u in uses:
            self.assertRegex(u, r"@[0-9a-f]{40}$", u)
        self.assertIn("claude plugin validate . --strict", text)

    def test_repo_files_and_marketplace(self):
        market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual([e["name"] for e in market["plugins"]], [c[0] for c in CASES])
        self.assertTrue(all(e["source"] == f"./plugins/{e['name']}" and "version" not in e for e in market["plugins"]))
        for rel in ("tools/check_plugin.py", "tools/plugin_rules.py", "tools/secretscan.py", ".gitattributes"):
            self.assertTrue((REPO / rel).is_file(), rel)

    def test_org_overlay(self):
        snippet = json.loads((REPO / "org-overlay" / "managed-settings.snippet.json").read_text(encoding="utf-8"))
        self.assertEqual(set(snippet), {"extraKnownMarketplaces", "enabledPlugins", "strictKnownMarketplaces"})
        self.assertTrue(next(iter(snippet["extraKnownMarketplaces"].values()))["autoUpdate"])
        self.assertIn("notes-guard@", next(iter(snippet["enabledPlugins"])))
        self.assertIn("allowManagedHooksOnly", (REPO / "org-overlay" / "coexistence.md").read_text(encoding="utf-8"))

    def test_no_token_left_and_lf_only(self):
        for f in REPO.rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                data = f.read_bytes()
                self.assertFalse(b"\r\n" in data, str(f))
                self.assertIsNone(re.search(rb"__[A-Z][A-Z_]{2,}__", data), str(f))

    def test_guard_plugin_never_edits_settings(self):
        for f in (REPO / "plugins" / "notes-guard").rglob("*.py"):
            self.assertNotRegex(f.read_text(encoding="utf-8"), r"settings\.json|settings\.local")


class Refusals(unittest.TestCase):
    def test_reserved_names_are_refused_and_nothing_is_written(self):
        out = TMP / "refused"
        for bad in ("claude-helper", "anthropic-tools", "claude", "cc-plugin-x", "Bad_Name"):
            with self.subTest(bad):
                r = py(SCAFFOLD, bad, "--kind", "content", "--surfaces", "cli", "--out", out)
                self.assertEqual(r.returncode, 2, r.stdout)
                self.assertIn("refused", r.stderr)
        self.assertFalse(out.exists())

    def test_stdio_for_the_web_and_duplicates_are_refused(self):
        r = py(SCAFFOLD, "x-stdio", "--kind", "integration", "--surfaces", "all", "--mcp", "stdio", "--out", TMP / "r2")
        self.assertEqual(r.returncode, 2)
        self.assertIn("remote", r.stderr)
        r = py(SCAFFOLD, "notes-content", "--kind", "content", "--surfaces", "cli", "--out", REPO)
        self.assertEqual(r.returncode, 2)

    def test_reserved_name_fails_validate_and_check(self):
        d = TMP / "bad-name" / "plugins" / "bad-name"
        shutil.copytree(REPO / "plugins" / "notes-content", d)
        mf = d / ".claude-plugin" / "plugin.json"
        mf.write_text(mf.read_text(encoding="utf-8").replace('"notes-content"', '"claude-helper"'), encoding="utf-8")
        r = py(CHECK, d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("L04-reserved-name", r.stdout)
        if CLAUDE:
            self.assertNotEqual(claude("plugin", "validate", d, "--strict").returncode, 0)
        else:
            self.assertFalse(REQUIRE, "claude CLI not found")

    def test_non_portable_key_fails_the_check_for_all_surfaces(self):
        d = TMP / "bad-key" / "plugins" / "notes-guard"
        shutil.copytree(REPO / "plugins" / "notes-guard", d)
        sk = d / "skills" / "notes-guard" / "SKILL.md"
        sk.write_text(sk.read_text(encoding="utf-8").replace("allowed-tools: Read\n", "allowed-tools: Read\nmodel: opus\n"), encoding="utf-8")
        r = py(CHECK, d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("F01-nonportable-key", r.stdout)
        self.assertEqual(py(CHECK, d, "--target", "cli").returncode, 0)       # fine for Claude Code alone

    def test_a_skill_with_a_hook_secret_read_is_caught_in_a_generated_repo(self):
        d = TMP / "bad-hook" / "plugins" / "notes-guard"
        shutil.copytree(REPO / "plugins" / "notes-guard", d)
        g = d / "scripts" / "guard.py"
        g.write_text(g.read_text(encoding="utf-8") + '\ntoken = os.environ["GITHUB_TOKEN"]\n', encoding="utf-8")
        r = py(CHECK, d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("H07-env-credential-read", r.stdout)


if __name__ == "__main__":
    unittest.main()
