"""Bootstrap check: merge rules, managed-policy handling, the one-owner values, and install -> uninstall round trips in
a temp home that must leave the user's files byte-identical. Run: python -m unittest discover -s bootstrap -p "test_install*"
Never touches the real Claude configuration (CLAUDE_CONFIG_DIR, USERPROFILE and HOME point at a temp dir)."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import install as I  # noqa: E402


class Merge(unittest.TestCase):
    def test_keeps_user_keys_unions_lists_and_skips_only_managed_scalars(self):
        user = {"model": "mine", "permissions": {"allow": ["A"]}, "env": {"X": "1"}}
        frag = {"model": "kit", "permissions": {"allow": ["A", "B"], "deny": ["D"], "defaultMode": "default"},
                "env": {"Y": "2"}, "$schema": "s"}
        managed = {"permissions": {"deny": ["M"], "defaultMode": "plan"}}
        ops, notes = [], []
        I.merge_settings(user, frag, managed, False, ops, notes)
        self.assertEqual(user, {"model": "mine", "permissions": {"allow": ["A", "B"], "deny": ["D"]},
                                "env": {"X": "1", "Y": "2"}})       # deny arrays merge across scopes: kept
        self.assertIn(("permissions.defaultMode", "set by a managed source"), notes)
        I.undo_settings(user, ops)
        self.assertEqual(user, {"model": "mine", "permissions": {"allow": ["A"]}, "env": {"X": "1"}})

    def test_managed_has(self):
        m = {"env": {"A": "1"}, "permissions": {"deny": ["x"]}, "statusLine": {"type": "command"}, "model": "m"}
        self.assertTrue(I.managed_has(m, ("model",), "k"))
        self.assertTrue(I.managed_has(m, ("env", "A"), "2"))
        self.assertFalse(I.managed_has(m, ("env", "B"), "2"))
        self.assertFalse(I.managed_has(m, ("permissions", "deny"), ["y"]))
        self.assertTrue(I.managed_has(m, ("statusLine",)))                 # no value: present at all = managed
        self.assertTrue(I.managed_has(m, ("model", "x"), "y"))              # a scalar above the key

    def test_marketplace_policy(self):
        gh = {"source": "github", "repo": "acme/tools"}
        self.assertTrue(I.marketplace_allowed(gh, {})[0])
        self.assertTrue(I.marketplace_allowed(gh, {"strictKnownMarketplaces": [{"source": "github", "repo": "acme/*"}]})[0])
        self.assertFalse(I.marketplace_allowed(gh, {"strictKnownMarketplaces": []})[0])
        self.assertFalse(I.marketplace_allowed(gh, {"blockedMarketplaces": [gh]})[0])
        d = {"source": "directory", "path": "C:/kits/claude-workbench"}
        self.assertTrue(I.marketplace_allowed(d, {"strictKnownMarketplaces": [{"source": "pathPattern",
                                                                                "pathPattern": "^C:/kits/"}]})[0])
        self.assertTrue(I.marketplace_allowed({"source": "git", "url": "https://git.example.com/a.git"},
                                              {"strictKnownMarketplaces": [{"source": "hostPattern",
                                                                            "hostPattern": "^git\\.example\\.com$"}]})[0])

    def test_statusline_command_forms(self):
        self.assertEqual(I.statusline_command("/usr/bin/python3", "/opt/u/.claude/workbench/statusline.py"),
                         "/usr/bin/python3 /opt/u/.claude/workbench/statusline.py")
        cmd = I.statusline_command("C:/No Such Dir/python.exe", "D:/Work Area/.claude/workbench/statusline.py")
        if os.name == "nt":
            self.assertEqual(cmd, "powershell -NoProfile -NonInteractive -Command \"& 'C:/No Such Dir/python.exe' "
                                  "'D:/Work Area/.claude/workbench/statusline.py'\"")
        else:
            self.assertEqual(cmd, "'C:/No Such Dir/python.exe' 'D:/Work Area/.claude/workbench/statusline.py'")

    def test_decode_text_falls_back_to_ansi(self):
        self.assertEqual(I.decode_text("caf\u00e9\r\n".encode("cp1252"))[:2], ("caf\u00e9\r\n", "cp1252"))
        self.assertEqual(I.decode_text(b"\xef\xbb\xbfx")[0::2], ("x", True))


class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="wb-boot-"))
        (self.home / ".claude").mkdir()
        self.settings = self.home / ".claude" / "settings.json"
        self.settings.write_text('{\n    "model": "mine",\n    "env": {"KEEP": "1"}\n}\n', encoding="utf-8")
        self.claude_md = self.home / ".claude" / "CLAUDE.md"
        self.claude_md.write_bytes(b"\xef\xbb\xbf# my notes\r\ncaf\xc3\xa9")      # BOM, CRLF, no final newline
        self.env = {**os.environ, "USERPROFILE": str(self.home), "HOME": str(self.home),
                    "CLAUDE_CONFIG_DIR": str(self.home / ".claude")}
        for k in ("WORKBENCH_KB_ROOT", "WORKBENCH_MANAGED_SETTINGS"):
            self.env.pop(k, None)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_install(self, *args, code=0):
        r = subprocess.run([sys.executable, str(HERE / "install.py"), "--no-cli", *args], capture_output=True,
                           text=True, encoding="utf-8", env=self.env, timeout=300)
        self.assertEqual(r.returncode, code, r.stdout[-1500:] + r.stderr[-800:])
        return r.stdout

    def digest(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.settings, self.claude_md)}

    def s(self):
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def test_help_has_no_retired_options(self):
        out = self.run_install("--help")
        for gone in ("--mode", "--no-prompts"):
            self.assertNotIn(gone, out)
        for kept in ("--profile", "permissive", "--upstream-plugins-optional", "--git-hosts"):
            self.assertIn(kept, out)

    def test_dry_run_writes_nothing(self):
        before = self.digest()
        self.assertIn("DRY RUN", self.run_install())
        self.assertEqual(self.digest(), before)
        self.assertFalse((self.home / ".claude" / "workbench").exists())

    def test_corporate_apply_then_uninstall_restores(self):
        before = self.digest()
        out = self.run_install("--apply", "--git-hosts", "git.corp.example,ghe.corp.example:8443")
        self.assertIn("Guard self-test (installed kit, this interpreter): PASS", out)
        self.assertIn("Corporate guard pack: ON, approved git hosts: git.corp.example, ghe.corp.example:8443", out)
        wb = self.home / ".claude" / "workbench"
        self.assertTrue((wb / "kit" / ".claude-plugin" / "marketplace.json").exists())
        s = self.s()
        self.assertEqual(s["model"], "mine")                                       # a user key is kept
        self.assertEqual(s["permissions"]["defaultMode"], "default")
        kb = I.fwd(self.home / "claude-kb")
        self.assertEqual(s["env"]["WORKBENCH_KB_ROOT"], kb)
        self.assertIn(kb, s["permissions"]["additionalDirectories"])
        for pid in I.PLUGIN_IDS:
            self.assertEqual(s["pluginConfigs"][pid]["options"]["python"], I.fwd(sys.executable))
        self.assertIn("statusline", s["statusLine"]["command"].lower())
        raw = self.claude_md.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf# my notes\r\ncaf\xc3\xa9\r\n@workbench/instructions/CLAUDE.md\r\n"))
        self.assertTrue((self.home / "claude-kb" / "_shared" / "HOT.md").exists())
        self.assertIn("run yourself", self.run_install("--uninstall"))             # dry run names the CLI steps
        self.run_install("--uninstall", "--apply")
        self.assertEqual(self.digest(), before, "files not restored byte-identical")
        self.assertFalse((wb / "kit").exists())
        self.assertTrue((self.home / "claude-kb").exists(), "the KB must survive an uninstall")

    def test_permissive_optional_upstream_and_one_owner_values(self):
        before = self.digest()
        self.run_install("--apply", "--profile", "permissive")
        s = self.s()
        self.assertEqual(s["permissions"]["defaultMode"], "bypassPermissions")
        self.assertTrue(s.get("extraKnownMarketplaces"))                           # permissive implies upstream
        self.assertNotIn("trailofbits", json.dumps(s))                             # optional ones are never implied
        out = self.run_install("--apply", "--profile", "permissive", "--upstream-plugins-optional",
                               "--kb-root", str(self.home / "kb2"))
        self.assertIn("KB root changes from", out)
        s = self.s()
        self.assertIn("trailofbits", json.dumps(s))
        kb2 = I.fwd(self.home / "kb2")
        self.assertEqual(s["env"]["WORKBENCH_KB_ROOT"], kb2)
        self.assertEqual([d for d in s["permissions"]["additionalDirectories"] if "kb" in d], [kb2])
        cfg = json.loads((self.home / ".claude" / "workbench" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["kb_root"], kb2)
        self.assertIn(kb2, (self.home / ".claude" / "workbench" / "instructions" / "rules" / "memory-protocol.md").read_text(encoding="utf-8"))
        self.run_install("--uninstall", "--apply")
        self.assertEqual(self.digest(), before)

    def test_managed_policy_stops_with_exit_3(self):
        pol = self.home / "managed.json"
        pol.write_text(json.dumps({"strictKnownMarketplaces": [{"source": "github", "repo": "acme/*"}]}), encoding="utf-8")
        self.env["WORKBENCH_MANAGED_SETTINGS"] = str(pol)
        before = self.digest()
        out = self.run_install("--apply", code=3)
        self.assertIn("Ask your IT team", out)
        self.assertEqual(self.digest(), before)
        self.assertFalse((self.home / ".claude" / "workbench").exists())

    def test_managed_upstream_marketplace_is_skipped(self):
        pol = self.home / "managed.json"
        kit = I.fwd(self.home / ".claude" / "workbench" / "kit")
        pol.write_text(json.dumps({"strictKnownMarketplaces": [{"source": "directory", "path": kit}]}), encoding="utf-8")
        self.env["WORKBENCH_MANAGED_SETTINGS"] = str(pol)
        out = self.run_install("--apply", "--upstream-plugins-optional")
        self.assertIn("skipped: not in the managed strictKnownMarketplaces allowlist", out)
        self.assertNotIn("trailofbits", json.dumps(self.s()))

    def test_records_config_dir_and_no_cli(self):
        self.run_install("--apply")
        wb = self.home / ".claude" / "workbench"
        rec = json.loads((wb / "kit" / I.RECORD).read_text(encoding="utf-8"))
        self.assertEqual(rec["claude_home"], I.fwd(self.home / ".claude"))
        man = json.loads(next((wb / "backups").glob("*/manifest.json")).read_text(encoding="utf-8"))
        self.assertTrue(man["no_cli"])
        fake = self.home / "bin"                                   # a claude on PATH that must not be called
        fake.mkdir()
        marker = self.home / "cli-called"
        for name, body in (("claude.cmd", f"@echo x> \"{marker}\"\r\n"), ("claude", f"#!/bin/sh\necho x > '{marker}'\n")):
            (fake / name).write_text(body, encoding="utf-8")
            os.chmod(fake / name, 0o755)
        self.env["PATH"] = str(fake) + os.pathsep + self.env.get("PATH", "")
        r = subprocess.run([sys.executable, str(HERE / "install.py"), "--uninstall", "--apply"], capture_output=True,
                           text=True, encoding="utf-8", env=self.env, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout[-800:])
        self.assertIn("run yourself: claude plugin uninstall", r.stdout)
        self.assertFalse(marker.exists(), "uninstall called the claude CLI for a --no-cli install")

    def test_bad_settings_json_is_exit_2_and_untouched(self):
        self.settings.write_text("{ not json", encoding="utf-8")
        before = self.digest()
        self.assertIn("is not valid JSON", self.run_install("--apply", code=2))
        self.assertEqual(self.digest(), before)


if __name__ == "__main__":
    unittest.main()
