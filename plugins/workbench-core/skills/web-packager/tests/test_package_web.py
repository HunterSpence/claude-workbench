"""Tests for web-packager/scripts/package_web.py. Run:
  WB_REQUIRE_ALL=1 py -3 -m unittest discover -s plugins/workbench-core/skills/web-packager/tests -v
"""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: nothing below skips; a missing file fails

import hashlib  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
import zipfile  # noqa: E402
from pathlib import Path  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
PACK = SCRIPTS / "package_web.py"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin-review" / "scripts"))
import plugin_rules as R  # noqa: E402

GROUP3 = ["argument-hint", "arguments", "disable-model-invocation", "user-invocable", "disallowed-tools", "model", "effort",
          "context", "agent", "background", "hooks", "paths", "shell", "when_to_use", "version"]

SIX = ("---\nname: notes\ndescription: Save and list short working notes. Use when the user asks to remember something.\n"
       "license: MIT\ncompatibility: Any surface that loads skills.\nmetadata:\n  author: example\nallowed-tools: Read\n---\n\n# Notes\n\nSave a note.\n")
README = ("# Acme Notes\n\nAcme Notes keeps short working notes next to your project. It adds one skill that saves and lists notes "
          "and nothing else at all. Install it, then ask Claude to save a note whenever you want to remember something.\n")


def run(*args):
    r = subprocess.run([sys.executable, "-I", str(PACK), *map(str, args)], capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout, r.stderr


def put(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)


def skill_dir(root, extra="", name="notes"):
    d = Path(root) / name
    put(d, "SKILL.md", SIX.replace("allowed-tools: Read\n", "allowed-tools: Read\n" + (extra.rstrip("\n") + "\n" if extra else "")))
    put(d, "scripts/helper.py", "print('hello')\n")
    return d


def plugin_dir(root, name="plugin"):
    d = Path(root) / name
    put(d, ".claude-plugin/plugin.json", json.dumps({"name": "acme-notes", "version": "0.1.0", "description": "Notes.", "license": "MIT"}))
    put(d, "README.md", README)
    put(d, "LICENSE", "MIT License\n")
    put(d, "skills/notes/SKILL.md", SIX)
    return d


class Rejects(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="wb-pw-"))

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def assert_rejected(self, folder, rule, needle=""):
        code, out, _ = run(folder, "--check", "--json")
        rep = json.loads(out)
        self.assertEqual(code, 1, out)
        self.assertFalse(rep["portable"])
        self.assertEqual((rep["surface"], len(rep["rules_sha256"])), ("web", 64))
        hits = [f for f in rep["findings"] if f["rule"] == rule]
        self.assertTrue(hits, [f["rule"] for f in rep["findings"]])
        self.assertTrue(any(needle in f["msg"] or needle in f["file"] for f in hits), hits)

    def test_key_list_matches_the_rules(self):
        self.assertEqual(sorted(GROUP3), sorted(R.NONPORTABLE_KEYS))

    def test_every_group3_key_is_rejected(self):
        for key in GROUP3:
            with self.subTest(key):
                self.assert_rejected(skill_dir(self.t / key, f"{key}: x"), "F01-nonportable-key", key)

    def test_unknown_key_is_rejected(self):
        self.assert_rejected(skill_dir(self.t, "owner-team: platform"), "F02-unknown-key", "owner-team")

    def test_bin_dir_is_rejected(self):
        d = plugin_dir(self.t)
        put(d, "bin/run.sh", "#!/bin/sh\n")
        self.assert_rejected(d, "F06-bin-dir", "bin")

    def test_local_stdio_server_is_rejected(self):
        d = plugin_dir(self.t)
        put(d, ".mcp.json", json.dumps({"mcpServers": {"local": {"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/server.py"]}}}))
        self.assert_rejected(d, "P09-local-stdio-server", "local")

    def test_user_config_in_mcp_url_is_rejected(self):
        d = plugin_dir(self.t)
        put(d, ".mcp.json", json.dumps({"mcpServers": {"r": {"type": "http", "url": "https://${user_config.host}/mcp"}}}))
        self.assert_rejected(d, "P10-user-config-in-url", "user_config")

    def test_bad_name_and_description(self):
        d = skill_dir(self.t)
        put(d, "SKILL.md", SIX.replace("name: notes", "name: Claude Helper").replace("Save and list", "Save <b>and</b> list"))
        code, out, _ = run(d, "--check", "--json")
        rules = {f["rule"] for f in json.loads(out)["findings"]}
        self.assertEqual(code, 1)
        self.assertTrue({"F03-skill-name", "F04-skill-description"} <= rules, rules)

    def test_usage_errors(self):
        self.assertEqual(run(self.t / "missing", "--check")[0], 2)
        self.assertEqual(run(self.t)[0], 2)


class Packs(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="wb-pw-"))

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def test_portable_six_field_skill_passes_and_zips(self):
        d = skill_dir(self.t)
        put(d, "scripts/__pycache__/helper.cpython-313.pyc", b"\0junk")
        put(d, "notes.md", "line one\r\nline two\r\n")
        code, out, _ = run(d, "--check", "--json")
        rep = json.loads(out)
        self.assertEqual((code, rep["portable"]), (0, True), rep["findings"])
        self.assertEqual([f for f in rep["findings"] if f["severity"] in ("block", "hold")], [])
        z = self.t / "notes.zip"
        code, out, err = run(d, "--out", z)
        self.assertEqual(code, 0, err)
        with zipfile.ZipFile(z) as zf:
            self.assertIsNone(zf.testzip())
            names = zf.namelist()
            self.assertEqual(names, sorted(names))
            self.assertIn("notes/SKILL.md", names)
            self.assertIn("notes/scripts/helper.py", names)
            self.assertFalse([n for n in names if "pycache" in n or n.endswith(".pyc") or "\\" in n])
            self.assertEqual(zf.read("notes/notes.md"), b"line one\nline two\n")
            self.assertTrue(zf.read("notes/SKILL.md").startswith(b"---\nname: notes\n"))
        self.assertIn("notes/SKILL.md", out)
        z2 = self.t / "again.zip"
        run(d, "--out", z2)
        self.assertEqual(hashlib.sha256(z.read_bytes()).digest(), hashlib.sha256(z2.read_bytes()).digest(), "zip is not reproducible")

    def test_plugin_zip_has_the_manifest_at_the_root(self):
        d = plugin_dir(self.t)
        z = self.t / "p.zip"
        self.assertEqual(run(d, "--out", z)[0], 0)
        self.assertIn(".claude-plugin/plugin.json", zipfile.ZipFile(z).namelist())

    def test_non_portable_skill_is_refused_without_strip(self):
        d = skill_dir(self.t, 'argument-hint: "[topic]"')
        z = self.t / "n.zip"
        code, _, err = run(d, "--out", z)
        self.assertEqual(code, 1)
        self.assertFalse(z.exists())
        self.assertIn("F01-nonportable-key", err)

    def test_strip_rewrites_frontmatter_and_records_it(self):
        d = skill_dir(self.t, 'argument-hint: "[topic]"\nmodel: opus\nwhen_to_use: when the user wants to remember something\n')
        before = (d / "SKILL.md").read_bytes()
        z = self.t / "s.zip"
        code, _, err = run(d, "--out", z, "--strip")
        self.assertEqual(code, 0, err)
        self.assertEqual((d / "SKILL.md").read_bytes(), before, "the source folder must not change")
        zf = zipfile.ZipFile(z)
        skill = zf.read("notes/SKILL.md").decode()
        self.assertNotIn("argument-hint", skill)
        self.assertNotIn("model:", skill)
        self.assertNotIn("when_to_use", skill)
        self.assertIn("when the user wants to remember something", skill)
        note = zf.read("notes/PACKAGING.md").decode()
        for needle in ("argument-hint", "model", "when_to_use", "folded"):
            self.assertIn(needle, note)
        out = self.t / "unzipped"
        zf.extractall(out)
        self.assertEqual(run(out / "notes", "--check")[0], 0)

    def test_strip_cannot_fix_a_bin_dir(self):
        d = plugin_dir(self.t)
        put(d, "bin/run.sh", "#!/bin/sh\n")
        z = self.t / "b.zip"
        self.assertEqual(run(d, "--out", z, "--strip")[0], 1)
        self.assertFalse(z.exists())


if __name__ == "__main__":
    unittest.main()
