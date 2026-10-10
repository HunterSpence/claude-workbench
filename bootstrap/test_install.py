"""Bootstrap check: merge rules, managed-policy handling, the one-owner values, and install -> uninstall round trips in
a temp home that must leave the user's files byte-identical. Run: python -m unittest discover -s bootstrap -p "test_install*"
Never touches the real Claude configuration (CLAUDE_CONFIG_DIR, USERPROFILE, HOME and LOCALAPPDATA point at a temp dir;
registry reads come from a JSON file). WB_V020_ARCHIVE = a `git archive` tar of the 0.2.0 release for the upgrade test."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import install as I  # noqa: E402
from test_setup import FakeEnv, WINDOWS_ONLY, assert_sandboxed, installs  # noqa: E402


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

    def test_store_python_is_refused(self):
        self.assertTrue(I.store_python(r"X:\AppData\Local\Microsoft\WindowsApps\python3.exe"))
        self.assertTrue(I.store_python("C:/Program Files/WindowsApps/PythonSoftwareFoundation.Python.3.12_x/python3.12.exe"))
        self.assertFalse(I.store_python(r"X:\AppData\Local\Programs\Python\Python313\python.exe"))
        self.assertFalse(I.store_python("/usr/bin/python3"))
        real = sys.executable
        try:
            sys.executable = r"X:\AppData\Local\Microsoft\WindowsApps\python3.exe"
            self.assertEqual(I.main([]), 2)
        finally:
            sys.executable = real

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
        (self.home / "registry.json").write_text("{}", encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("OneDrive", "WORKBENCH_", "WB_"))}
        self.env.update(USERPROFILE=str(self.home), HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.home / ".claude"),
                        LOCALAPPDATA=str(self.home / "lad"), WORKBENCH_FAKE_REGISTRY=str(self.home / "registry.json"),
                        WORKBENCH_FAKE_BIN=str(self.home / "nobin"))

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
        for kept in ("--profile", "permissive", "--upstream-plugins-optional", "--git-hosts", "--guard", "--approvals", "--setup", "--with",
                     "--no-nightly", "--no-update", "--data-root"):
            self.assertIn(kept, out)

    def test_no_update_and_the_new_opt_ins_reach_setup(self):
        for mode, verb in (("plan", " plan"), ("auto", " run --detach")):
            out = self.run_install("--setup", mode, "--no-update", "--with", "ctx,update-latest")
            line = next(x for x in out.splitlines() if "setup.py" in x)
            self.assertIn(verb, line)
            self.assertIn("--no-update", line, mode)
            self.assertIn("ctx,update-latest", line)
            self.assertNotIn("--no-update", next(x for x in self.run_install("--setup", mode).splitlines() if "setup.py" in x))
        self.assertIn("unknown option", self.run_install("--with", "nope", code=2))

    def test_dry_run_writes_nothing(self):
        before = self.digest()
        self.assertIn("DRY RUN", self.run_install())
        self.assertEqual(self.digest(), before)
        self.assertFalse((self.home / ".claude" / "workbench").exists())

    def test_guard_level_is_written_kept_across_upgrades_and_switchable(self):
        al = self.home / ".claude" / "workbench" / "corporate-allowlist.json"
        self.run_install("--apply", "--guard", "strict")
        self.assertEqual(json.loads(al.read_text(encoding="utf-8"))["guard_level"], "strict")
        self.run_install("--apply")                                                # an upgrade without the flag keeps it
        self.assertEqual(json.loads(al.read_text(encoding="utf-8"))["guard_level"], "strict")
        self.run_install("--apply", "--guard", "standard")
        self.assertEqual(json.loads(al.read_text(encoding="utf-8"))["guard_level"], "standard")
        self.run_install("--guard", "loose", code=2)                              # argparse refuses another value
        self.run_install("--apply", "--guard", "minimal")
        self.assertEqual(json.loads(al.read_text(encoding="utf-8"))["guard_level"], "minimal")

    def cfg(self):
        return json.loads((self.home / ".claude" / "workbench" / "config.json").read_text(encoding="utf-8"))

    def test_approvals_off_runs_ordinary_commands_without_prompts_is_kept_and_switches_back(self):
        before = self.digest()
        self.run_install("--apply")
        p = self.s()["permissions"]
        self.assertEqual((p["defaultMode"], p["disableBypassPermissionsMode"]), ("default", "disable"))
        self.assertEqual(self.cfg()["approvals"], "ask")
        out = self.run_install("--apply", "--approvals", "off")
        self.assertIn("approvals: off (new windows start in bypassPermissions)", out)
        p = self.s()["permissions"]
        self.assertEqual(p["defaultMode"], "bypassPermissions")
        self.assertNotIn("disableBypassPermissionsMode", p, "the kit's own lock on bypass mode is lifted")
        for rule in ("Bash(*)", "PowerShell(*)", "Edit(*)"):
            self.assertIn(rule, p["allow"])
        self.assertIn("Read(//**/.env)", p["deny"], "secret files stay denied")
        self.assertNotIn("Bash(gh release create *)", p.get("ask") or [], "the kit's ask rules are lifted: the guard asks instead")
        self.assertEqual(self.cfg()["approvals"], "off")
        self.run_install("--apply")                                              # an upgrade without the flag keeps it
        self.assertEqual(self.s()["permissions"]["defaultMode"], "bypassPermissions")
        self.assertNotIn("disableBypassPermissionsMode", self.s()["permissions"])
        self.run_install("--apply", "--approvals", "ask")
        p = self.s()["permissions"]
        self.assertEqual((p["defaultMode"], p["disableBypassPermissionsMode"]), ("default", "disable"))
        self.assertFalse({"Bash(*)", "PowerShell(*)", "Edit(*)"} & set(p["allow"]), "the broad allows go with it")
        self.assertIn("Bash(gh release create *)", p["ask"], "and the kit's ask rules come back")
        self.run_install("--apply", "--approvals", "off")
        self.run_install("--uninstall", "--apply")
        self.assertEqual(self.digest(), before, "uninstall after approvals off restores every file byte-identical")
        self.run_install("--approvals", "never", code=2)
        self.run_install("--appr", "off", code=2)                              # no abbreviations: the guard reads the full words
        self.run_install("--gua", "minimal", code=2)
        self.settings.write_text(json.dumps({"permissions": {"ask": ["Bash(my-own-deploy *)"]}}), encoding="utf-8")
        self.run_install("--apply")
        self.run_install("--apply", "--approvals", "off")
        self.assertEqual(self.s()["permissions"]["ask"], ["Bash(my-own-deploy *)"], "the user's own ask rule stays")
        self.run_install("--apply", "--guard", "minimal")
        al = self.home / ".claude" / "workbench" / "corporate-allowlist.json"
        self.assertEqual(json.loads(al.read_text(encoding="utf-8"))["guard_level"], "minimal")
        self.assertEqual(self.s()["permissions"]["defaultMode"], "bypassPermissions", "the other choice is kept")

    def test_approvals_ask_gives_back_the_users_own_mode_and_uninstall_is_still_clean(self):
        self.settings.write_text(json.dumps({"permissions": {"defaultMode": "acceptEdits"}}), encoding="utf-8")
        before = self.digest()
        self.run_install("--apply")
        self.assertEqual(self.s()["permissions"]["defaultMode"], "acceptEdits", "the kit keeps a mode the user set")
        self.run_install("--apply", "--approvals", "off")
        self.assertEqual(self.s()["permissions"]["defaultMode"], "bypassPermissions")
        self.assertEqual(self.cfg()["approvals_user_mode"], "acceptEdits")
        self.run_install("--apply", "--approvals", "off")                         # again: the remembered mode is not lost
        self.run_install("--apply", "--approvals", "ask")
        self.assertEqual(self.s()["permissions"]["defaultMode"], "acceptEdits", "the user's own mode comes back")
        self.assertNotIn("approvals_user_mode", self.cfg())
        self.run_install("--apply", "--approvals", "off")                         # a second full cycle keeps it too
        self.run_install("--apply", "--approvals", "ask")
        self.assertEqual(self.s()["permissions"]["defaultMode"], "acceptEdits", "the second cycle gives it back as well")
        self.run_install("--apply", "--approvals", "off")
        s = self.s()
        s["permissions"]["defaultMode"] = "plan"                                 # the user picks a mode while approvals are off
        self.settings.write_text(json.dumps(s), encoding="utf-8")
        self.run_install("--apply", "--approvals", "ask")
        self.assertEqual(self.s()["permissions"]["defaultMode"], "plan", "a mode picked since is not overwritten")
        self.settings.write_text(json.dumps(dict(s, permissions=dict(s["permissions"], defaultMode="bypassPermissions"))),
                                 encoding="utf-8")
        self.run_install("--apply", "--approvals", "off")
        self.run_install("--uninstall", "--apply")
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8")).get("permissions", {}).get("defaultMode"),
                         "acceptEdits", "uninstall still ends on the user's original mode")

    def test_approvals_off_records_the_lock_it_lifts_and_undo_puts_back_only_what_is_missing(self):
        self.run_install("--apply")
        self.run_install("--apply", "--approvals", "off")
        latest = sorted((self.home / ".claude" / "workbench" / "backups").glob("*/manifest.json"))[-1]
        ops = json.loads(latest.read_text(encoding="utf-8"))["settings_ops"]
        self.assertIn({"op": "del", "path": ["permissions", "disableBypassPermissionsMode"], "old": "disable"}, ops)
        user = {"permissions": {"defaultMode": "bypassPermissions"}}
        I.undo_settings(user, [{"op": "del", "path": ["permissions", "disableBypassPermissionsMode"], "old": "disable"}])
        self.assertEqual(user["permissions"]["disableBypassPermissionsMode"], "disable")
        mine = {"permissions": {"disableBypassPermissionsMode": "mine"}}
        I.undo_settings(mine, [{"op": "del", "path": ["permissions", "disableBypassPermissionsMode"], "old": "disable"}])
        self.assertEqual(mine["permissions"]["disableBypassPermissionsMode"], "mine", "a value set since is left alone")

    def test_approvals_off_falls_back_to_accept_edits_when_bypass_mode_is_locked(self):
        managed = self.home / "managed-settings.json"
        managed.write_text(json.dumps({"permissions": {"disableBypassPermissionsMode": "disable"}}), encoding="utf-8")
        self.env["WORKBENCH_MANAGED_SETTINGS"] = str(managed)
        out = self.run_install("--apply", "--approvals", "off")
        self.assertIn("managed settings keep bypass mode off", out)
        p = self.s()["permissions"]
        self.assertEqual(p["defaultMode"], "acceptEdits")
        self.assertIn("Bash(*)", p["allow"])
        del self.env["WORKBENCH_MANAGED_SETTINGS"]
        self.run_install("--apply", "--approvals", "off")                         # the lock is gone: bypass now
        self.assertEqual(self.s()["permissions"]["defaultMode"], "bypassPermissions")
        self.run_install("--apply", "--approvals", "ask")
        self.assertEqual(self.s()["permissions"]["defaultMode"], "default", "acceptEdits was the kit's, not the user's")
        self.run_install("--uninstall", "--apply")
        self.settings.write_text(json.dumps({"permissions": {"disableBypassPermissionsMode": "disable"}}), encoding="utf-8")
        out = self.run_install("--apply", "--approvals", "off")                  # the user's own lock, before any kit
        self.assertIn("you set permissions.disableBypassPermissionsMode yourself", out)
        p = self.s()["permissions"]
        self.assertEqual((p["disableBypassPermissionsMode"], p["defaultMode"]), ("disable", "acceptEdits"))

    def test_approvals_do_not_change_the_permissive_profile(self):
        self.run_install("--apply", "--profile", "permissive", "--approvals", "ask")
        p = self.s()["permissions"]
        self.assertEqual(p["defaultMode"], "bypassPermissions")
        self.assertNotIn("PowerShell(*)", p["allow"])

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
        kb = I.fwd(self.home / "Workbench" / "kb")
        self.assertEqual(s["env"]["WORKBENCH_KB_ROOT"], kb)
        self.assertIn(kb, s["permissions"]["additionalDirectories"])
        for pid in I.PLUGIN_IDS:
            self.assertEqual(s["pluginConfigs"][pid]["options"]["python"], I.fwd(sys.executable))
        self.assertIn("statusline", s["statusLine"]["command"].lower())
        raw = self.claude_md.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf# my notes\r\ncaf\xc3\xa9\r\n@workbench/instructions/CLAUDE.md\r\n"))
        self.assertTrue((self.home / "Workbench" / "kb" / "_shared" / "HOT.md").exists())
        self.assertIn("run yourself", self.run_install("--uninstall"))             # dry run names the CLI steps
        self.run_install("--uninstall", "--apply")
        self.assertEqual(self.digest(), before, "files not restored byte-identical")
        self.assertFalse((wb / "kit").exists())
        self.assertTrue((self.home / "Workbench" / "kb").exists(), "the KB must survive an uninstall")
        self.assertTrue((wb / "backups").is_dir(), "backups stay without --purge-backups")
        self.assertIn("would delete", self.run_install("--uninstall", "--purge-backups"))
        self.assertTrue((wb / "backups").is_dir(), "a dry run deletes nothing")
        self.run_install("--uninstall", "--purge-backups", "--apply")
        self.assertFalse((wb / "backups").exists(), "--purge-backups removes them after a clean uninstall")

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

    def kb_line(self, out):
        return next(ln.split(None, 2)[2] for ln in out.splitlines() if ln.strip().startswith("kb root"))

    def set_registry(self, d):
        (self.home / "registry.json").write_text(json.dumps(d), encoding="utf-8")

    def test_onedrive_placement(self):
        work, other, personal = (self.home / n for n in ("OneDrive - Example Org", "OneDrive - Other Org", "OneDrive"))
        for d in (work, other, personal):
            d.mkdir()
        acc = I.ONEDRIVE_ACCOUNTS
        self.set_registry({acc + r"\Business3": {"UserFolder": str(work), "ConfiguredTenantId": "t-1"},
                           acc + r"\Personal": {"UserFolder": str(personal)}})
        self.assertEqual(self.kb_line(self.run_install()), I.fwd(work / "Workbench" / "kb"))   # Business<N>, N != 1
        self.set_registry({acc + r"\Business1": {"UserFolder": str(work)}, acc + r"\Business2": {"UserFolder": str(other)}})
        self.assertIn("More than one work OneDrive", self.run_install(code=2))                   # never auto-picked
        self.assertEqual(self.kb_line(self.run_install("--data-root", str(other / "Workbench"))),
                         I.fwd(other / "Workbench" / "kb"))
        self.set_registry({acc + r"\Personal": {"UserFolder": str(personal)}})
        self.env["OneDrive"] = str(personal)                                                      # never used alone
        self.assertEqual(self.kb_line(self.run_install()), I.fwd(self.home / "Workbench" / "kb"))
        self.set_registry({acc + r"\Business1": {"UserFolder": str(work), "ConfiguredTenantId": "t-9"},
                           I.TENANT_ALLOW: {"t-1": "t-1"}})
        self.assertEqual(self.kb_line(self.run_install()), I.fwd(self.home / "Workbench" / "kb"), "tenant not allowed")
        self.env["CLAUDE_CONFIG_DIR"] = str(personal / ".claude")
        self.assertIn("inside a OneDrive folder", self.run_install(code=2))
        self.assertFalse((personal / ".claude").exists())

    def test_uninstall_undoes_setup_and_removes_runtime_paths(self):
        self.run_install("--apply")
        wb, lad = self.home / ".claude" / "workbench", self.home / "lad"
        for p in (wb / "venv" / "x", wb / "state" / "plan.json", wb / "bin" / "node.cmd", lad / "doc-index" / "knowledge" / "i.sqlite",
                  self.home / "Workbench" / "captured" / "intranet" / "a.md", wb / "capture" / "profile" / "c"):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")
        self.set_registry({r"HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce": {"wb-setup-resume": ["x", 1]}})
        (wb / "state" / "provision-ledger.json").write_text(json.dumps(          # this install's setup recorded it
            {"version": 1, "entries": [{"kind": "runonce", "name": "wb-setup-resume", "key": "runonce"}]}), encoding="utf-8")
        dry = self.run_install("--uninstall")
        self.assertIn("would remove", dry)
        self.assertIn("RunOnce value wb-setup-resume", dry)
        self.run_install("--uninstall", "--apply")
        for gone in (wb / "venv", wb / "state", wb / "bin", lad / "doc-index" / "knowledge", wb / "capture" / "profile"):
            self.assertFalse(gone.exists(), gone)
        self.assertTrue((self.home / "Workbench" / "captured" / "intranet" / "a.md").exists(), "captured files are user data")
        self.assertNotIn("wb-setup-resume", json.loads((self.home / "registry.json").read_text())[
            r"HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce"])


# A stand-in for the claude CLI, with the two behaviours the field showed: `plugin marketplace remove` wipes pluginConfigs, and
# an install without --config leaves the plugin's userConfig unset (it prints the CLI's own hint and exits 0).
# Modes (file "mode" in WB_FAKE_CLAUDE_DIR): honor (default) | ignore_config (accepts --config, stores nothing) |
# reject_config (an older CLI: exit 1 on an unknown option) | default_value (ignores --config and stores the manifest's own
# default, python3). A file "nowipe" there stops `marketplace remove` from clearing pluginConfigs.
FAKE_CLAUDE = r"""
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
d = Path(os.environ["WB_FAKE_CLAUDE_DIR"])
mode = (d / "mode").read_text().strip() if (d / "mode").exists() else "honor"
with open(d / "calls.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(a) + "\n")
sp = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "settings.json"
load = lambda: json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
save = lambda s: sp.write_text(json.dumps(s, indent=2), encoding="utf-8")
if a[:3] == ["plugin", "marketplace", "remove"]:
    if not (d / "nowipe").exists():
        s = load(); s["pluginConfigs"] = {}; save(s)
elif a[:3] == ["plugin", "marketplace", "add"]:
    print("added")
elif a[:2] == ["plugin", "install"]:
    pid, s = a[2], load()
    s.setdefault("enabledPlugins", {})[pid] = True
    if mode == "default_value":
        s.setdefault("pluginConfigs", {}).setdefault(pid, {}).setdefault("options", {})["python"] = "python3"
    elif "--config" in a:
        if mode == "reject_config":
            print("error: unknown option '--config'", file=sys.stderr); sys.exit(1)
        k, _, v = a[a.index("--config") + 1].partition("=")
        if mode != "ignore_config":
            s.setdefault("pluginConfigs", {}).setdefault(pid, {}).setdefault("options", {})[k] = v
    elif pid.startswith(("workbench-core", "workbench-kb")):
        print("1 userConfig option not yet set - run /plugin configure " + pid + " in Claude Code, or pass --config KEY=VALUE")
    save(s)
elif a[:2] == ["plugin", "uninstall"]:
    s = load(); s.get("enabledPlugins", {}).pop(a[2], None); s.get("pluginConfigs", {}).pop(a[2], None); save(s)
sys.exit(0)
"""


def fake_claude_bin(folder, calls_dir):
    """A folder with claude.cmd and claude (sh) that run FAKE_CLAUDE; returns the folder."""
    folder, calls_dir = Path(folder), Path(calls_dir)
    folder.mkdir(parents=True, exist_ok=True)
    calls_dir.mkdir(parents=True, exist_ok=True)
    (calls_dir / "fake_claude.py").write_text(FAKE_CLAUDE, encoding="utf-8")
    (folder / "claude.cmd").write_text(f'@"{sys.executable}" "{calls_dir / "fake_claude.py"}" %*\r\n', encoding="utf-8")
    sh = folder / "claude"
    sh.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{calls_dir / 'fake_claude.py'}' \"$@\"\n", encoding="utf-8", newline="\n")
    os.chmod(sh, 0o755)
    return folder


class PluginPython(unittest.TestCase):
    """G1: the plugin options survive the plugin step. The kit's own python is the value; the CLI is a fake."""
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="wb-pypin-"))
        self.addCleanup(shutil.rmtree, self.home, True)
        (self.home / "cfg-dir").mkdir()
        self.settings = self.home / "cfg-dir" / "settings.json"       # NOT <home>/.claude: a call-time ~/.claude lookup shows
        self.settings.write_text('{\n    "model": "mine"\n}\n', encoding="utf-8")
        (self.home / "registry.json").write_text("{}", encoding="utf-8")
        self.calls_dir = self.home / "fake-claude"
        fake_claude_bin(self.home / "bin", self.calls_dir)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("OneDrive", "WORKBENCH_", "WB_"))}
        self.env.update(USERPROFILE=str(self.home), HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.home / "cfg-dir"),
                        LOCALAPPDATA=str(self.home / "lad"), WORKBENCH_FAKE_REGISTRY=str(self.home / "registry.json"),
                        WORKBENCH_FAKE_BIN=str(self.home / "nobin"), WB_FAKE_CLAUDE_DIR=str(self.calls_dir),
                        PATH=str(self.home / "bin") + os.pathsep + os.environ.get("PATH", ""))
        p = mock.patch.dict(os.environ, self.env, clear=True)      # the WHOLE test: pin_python and self_test run in-process too
        p.start()
        self.addCleanup(p.stop)
        assert_sandboxed()

    def mode(self, m):
        (self.calls_dir / "mode").write_text(m, encoding="utf-8")

    def install(self, *args, code=0):
        r = subprocess.run([sys.executable, str(HERE / "install.py"), *args], capture_output=True, text=True,
                           encoding="utf-8", env=self.env, timeout=300)
        self.assertEqual(r.returncode, code, r.stdout[-2500:] + r.stderr[-800:])
        return r.stdout

    def calls(self):
        f = self.calls_dir / "calls.jsonl"
        return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []

    def options(self):
        s = json.loads(self.settings.read_text(encoding="utf-8"))
        return {pid: (((s.get("pluginConfigs") or {}).get(pid) or {}).get("options") or {}).get("python")
                for pid in I.PLUGIN_IDS}

    def want(self):
        return {pid: I.fwd(sys.executable) for pid in I.PLUGIN_IDS}

    def test_the_plugins_that_need_the_option_are_the_ones_whose_manifest_says_so(self):
        self.assertEqual(I.python_plugin_ids(), sorted(I.PLUGIN_IDS))
        for other in ("workbench-biz", "workbench-capture"):
            manifest = json.loads((HERE.parent / "plugins" / other / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
            self.assertNotIn("python", manifest.get("userConfig") or {}, other)

    def test_the_install_argv_carries_config_python_and_the_option_survives_a_cli_that_wipes_it(self):
        out = self.install("--apply")
        installs = [c for c in self.calls() if c[:2] == ["plugin", "install"]]
        by_id = {c[2]: c for c in installs}
        for pid in I.PLUGIN_IDS:
            self.assertEqual(by_id[pid], ["plugin", "install", pid, "--config", "python=" + I.fwd(sys.executable)], pid)
        self.assertEqual(by_id["workbench-biz@workbench"], ["plugin", "install", "workbench-biz@workbench"], "no option, no flag")
        self.assertEqual(self.options(), self.want(), "settings.json holds the interpreter after marketplace remove cleared it")
        self.assertNotIn("left the python option unset", out, "the flag did the work; no fallback write was needed")
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8"))["model"], "mine")

    def test_a_cli_that_accepts_but_ignores_config_gets_the_option_written_after_the_plugin_step(self):
        self.mode("ignore_config")
        out = self.install("--apply")
        self.assertIn("left the python option unset for", out)
        self.assertEqual(self.options(), self.want())

    def test_an_older_cli_that_rejects_config_is_retried_without_it_and_the_option_is_written(self):
        self.mode("reject_config")
        out = self.install("--apply")
        core = [c for c in self.calls() if c[:3] == ["plugin", "install", "workbench-core@workbench"]]
        self.assertEqual([("--config" in c) for c in core], [True, False], "tried with --config, then without")
        self.assertIn("workbench-core@workbench", out)
        self.assertEqual(self.options(), self.want())
        s = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertTrue(s["enabledPlugins"]["workbench-core@workbench"], "the plugin did get installed")

    def test_the_dry_run_and_the_no_cli_commands_show_the_flag(self):
        self.assertIn("--config python=" + I.fwd(sys.executable), self.install())
        out = self.install("--apply", "--no-cli")
        self.assertIn("--config python=", out)
        self.assertFalse(self.calls(), "--no-cli never calls the CLI")

    def new_installer(self):
        ns = argparse.Namespace(apply=True, profile="corporate", upstream_plugins=False, upstream_plugins_optional=False,
                                kb_root=None, data_root=None, git_hosts=None, setup=None, with_=None, no_nightly=False,
                                no_update=False, force=False, no_cli=True, uninstall=False, purge_backups=False)
        inst = I.Installer(ns)
        inst.build()
        inst.backup.mkdir(parents=True, exist_ok=True)
        return inst

    def test_the_whole_test_runs_under_the_temp_profile_and_a_call_time_home_lookup_stays_inside_it(self):
        assert_sandboxed()
        self.assertTrue(I.under(Path.home(), self.home))
        self.assertTrue(I.under(I.claude_home(), self.home))
        self.assertNotEqual(I.claude_home(), Path.home() / ".claude", "so a lookup that ignores CLAUDE_CONFIG_DIR is visible")
        inst = self.new_installer()
        self.settings.write_text("{}", encoding="utf-8")
        inst.pin_python(list(I.PLUGIN_IDS))
        self.assertEqual(self.options(), self.want())
        self.assertTrue(I.under(inst.claude_home, self.home))

    def test_a_stale_value_the_cli_leaves_or_fills_in_is_replaced_by_the_detected_python(self):
        self.mode("default_value")                               # the CLI stores the manifest default, python3, ignoring --config
        (self.calls_dir / "nowipe").write_text("x", encoding="utf-8")
        stale = I.fwd(self.home / "old-python" / "python.exe")
        self.settings.write_text(json.dumps({"model": "mine", "pluginConfigs": {
            pid: {"options": {"python": stale}} for pid in I.PLUGIN_IDS}}), encoding="utf-8")
        out = self.install("--apply")
        self.assertEqual(self.options(), self.want(), "any other value, set or not, is not the detected python")
        self.assertIn("the plugin step left the python option unset", out)
        self.assertIn("changes from \"python3\" to", out)

    def test_a_write_that_does_not_land_is_a_recorded_failure_not_a_silent_pass(self):
        inst = self.new_installer()
        self.settings.write_text("{}", encoding="utf-8")
        with mock.patch.object(I.Installer, "write_file", lambda self, path, text: None):
            inst.pin_python(list(I.PLUGIN_IDS))
        self.assertEqual(len(inst.failures), 2, inst.failures)
        self.assertIn("plugin option python is not set for workbench-core@workbench", inst.failures[0])
        self.assertIn("claude plugin install workbench-core@workbench --config python=", inst.failures[0])

    def test_pin_python_writes_where_missing_leaves_a_right_value_and_respects_a_managed_one(self):
        inst = self.new_installer()
        good = {"pluginConfigs": {"workbench-core@workbench": {"options": {"python": inst.python}}}}
        self.settings.write_text(json.dumps(good), encoding="utf-8")
        inst.pin_python(list(I.PLUGIN_IDS))
        self.assertEqual(inst.failures, [])
        self.assertEqual(self.options(), self.want(), "core was right, kb was written")
        inst2 = self.new_installer()
        inst2.managed = {"pluginConfigs": {"workbench-kb@workbench": {"options": {"python": "managed-python"}}}}
        self.settings.write_text("{}", encoding="utf-8")
        inst2.pin_python(["workbench-kb@workbench"])
        self.assertEqual(inst2.failures, [], "a value a managed source owns is not ours to write or to fail on")

    def test_uninstall_after_a_cli_install_leaves_no_option_behind(self):
        self.install("--apply")
        self.install("--uninstall", "--apply")
        s = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertNotIn("python", json.dumps(s.get("pluginConfigs", {})))
        self.assertEqual(s["model"], "mine")

    def test_the_installer_self_test_marks_its_call_so_the_heartbeat_can_tell_it_from_a_session(self):
        inst = self.new_installer()
        seen = []

        def fake_run(argv, **kw):
            seen.append(kw.get("env", {}))
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(
                {"hookSpecificOutput": {"permissionDecision": "deny"}}).encode(), stderr=b"")
        with mock.patch.object(I.subprocess, "run", fake_run):
            self.assertTrue(inst.self_test())
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].get("WB_SELF_TEST"), "1")



class Upgrade(unittest.TestCase):
    """0.2.0 -> 0.3.0: user values kept, kit values updated, new KB files seeded with hashes (MAJ12), uninstall."""
    def setUp(self):
        arc = os.environ.get("WB_V020_ARCHIVE")
        if not arc or not Path(arc).is_file():
            if REQUIRE:
                self.fail("WB_V020_ARCHIVE (a git archive tar of the 0.2.0 release) is required")
            self.skipTest("WB_V020_ARCHIVE not set")
        self.t = Path(tempfile.mkdtemp(prefix="wb-up-"))
        self.addCleanup(shutil.rmtree, self.t, True)
        (self.t / "v020").mkdir()
        with tarfile.open(arc) as tf:
            tf.extractall(self.t / "v020", filter="data")
        self.kit = self.t / "kit030"                    # this kit plus two new template files and a changed fragment
        shutil.copytree(HERE.parent, self.kit, ignore=I.KIT_IGNORE)
        for n in ("upgrade-a.md", "upgrade-b.md"):
            (self.kit / "kb-template" / "_shared" / n).write_text(f"# {n}\n", encoding="utf-8")
        frag = self.kit / "settings" / "profiles" / "corporate.fragment.json"
        d = json.loads(frag.read_text(encoding="utf-8"))
        self.old_cleanup = d["cleanupPeriodDays"]
        d["cleanupPeriodDays"] = self.old_cleanup + 1
        d["env"]["WB_UPGRADE_PROBE"] = "1"
        frag.write_text(json.dumps(d, indent=2), encoding="utf-8")
        self.home = self.t / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.settings, self.claude_md = self.home / ".claude" / "settings.json", self.home / ".claude" / "CLAUDE.md"
        self.settings.write_text('{\n    "model": "mine",\n    "env": {"KEEP": "1"}\n}\n', encoding="utf-8")
        self.claude_md.write_bytes(b"\xef\xbb\xbf# my notes\r\ncaf\xc3\xa9")
        (self.t / "reg.json").write_text("{}", encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("OneDrive", "WORKBENCH_", "WB_"))}
        self.env.update(USERPROFILE=str(self.home), HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.home / ".claude"),
                        LOCALAPPDATA=str(self.t / "lad"), WORKBENCH_FAKE_REGISTRY=str(self.t / "reg.json"),
                        WORKBENCH_FAKE_BIN=str(self.t / "nobin"))
        self.before = {p.name: p.read_bytes() for p in (self.settings, self.claude_md)}

    def inst(self, kit, *args):
        r = subprocess.run([sys.executable, str(kit / "bootstrap" / "install.py"), "--no-cli", *args], capture_output=True,
                           text=True, encoding="utf-8", env=self.env, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-1000:])
        return r.stdout

    def s(self):
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def test_upgrade_keeps_user_values_seeds_and_uninstalls(self):
        self.inst(self.t / "v020", "--apply")
        kb = self.home / "claude-kb"                      # 0.2.0's default KB, kept by the upgrade
        s = self.s()
        s["permissions"]["defaultMode"] = "plan"          # the user changes a value the kit wrote
        self.settings.write_text(json.dumps(s, indent=2), encoding="utf-8")
        out = self.inst(self.kit, "--apply")
        self.assertRegex(out, r"add \d+ new template file\(s\): .*_shared/upgrade-a\.md")
        s = self.s()
        self.assertEqual(s["permissions"]["defaultMode"], "plan", "a user value survives the upgrade")
        self.assertEqual(s["env"]["WB_UPGRADE_PROBE"], "1", "new kit keys are added")
        self.assertEqual(s["cleanupPeriodDays"], self.old_cleanup + 1, "a value still equal to the old kit's is updated")
        cfg = json.loads((self.home / ".claude" / "workbench" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual((cfg["version"], cfg["kb_root"]), (I.VERSION, I.fwd(kb)))
        man = json.loads(sorted((self.home / ".claude" / "workbench" / "backups").glob("*/manifest.json"))[-1].read_text())
        seeded = {Path(x["path"]).name: x["sha256"] for x in man["kb_seeded"]}
        self.assertLessEqual({"upgrade-a.md", "upgrade-b.md"}, set(seeded))      # plus whatever this release added
        for x in man["kb_seeded"]:
            self.assertEqual(x["sha256"], I.sha(x["path"]), x["path"])
        (kb / "_shared" / "upgrade-a.md").write_text("# mine now\n", encoding="utf-8")
        (kb / "_shared" / "upgrade-b.md").unlink()
        time.sleep(1.1)                                   # a new backup folder per install
        self.assertNotIn("new template file", self.inst(self.kit, "--apply"))
        self.assertFalse((kb / "_shared" / "upgrade-b.md").exists(), "a deleted seeded file is never re-seeded")
        self.inst(self.kit, "--uninstall", "--apply")
        self.assertEqual((kb / "_shared" / "upgrade-a.md").read_text(encoding="utf-8"), "# mine now\n")
        self.assertEqual(self.claude_md.read_bytes(), self.before["CLAUDE.md"])
        self.assertEqual(self.s(), {"model": "mine", "env": {"KEEP": "1"}, "permissions": {"defaultMode": "plan"}},
                         "everything the kits wrote is gone; the user's own choice stays")

    def test_upgrade_then_uninstall_is_byte_identical(self):
        self.inst(self.t / "v020", "--apply")
        self.inst(self.kit, "--apply")
        self.inst(self.kit, "--uninstall", "--apply")
        self.assertEqual({p.name: p.read_bytes() for p in (self.settings, self.claude_md)}, self.before)
        self.assertFalse((self.home / ".claude" / "workbench" / "kit").exists())


class RetirePermissions(unittest.TestCase):
    """An upgrade removes the permission entries an EARLIER kit install added and the profile now applied dropped (0.3.1's permissive
    profile allowed mcp__tokensave server-wide; 0.3.2's does not), and never an entry the user added. Two kit copies stand in for
    the two releases: they differ only in that one entry of the permissive profile."""
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="wb-retire-"))
        self.addCleanup(shutil.rmtree, self.t, True)
        self.old = self.kit("old", with_entry=True)
        self.new = self.kit("new", with_entry=False)
        self.home = self.t / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.settings = self.home / ".claude" / "settings.json"
        (self.t / "reg.json").write_text("{}", encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("OneDrive", "WORKBENCH_", "WB_"))}
        self.env.update(USERPROFILE=str(self.home), HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.home / ".claude"),
                        LOCALAPPDATA=str(self.t / "lad"), WORKBENCH_FAKE_REGISTRY=str(self.t / "reg.json"),
                        WORKBENCH_FAKE_BIN=str(self.t / "nobin"))

    def kit(self, name, with_entry, deny=(), ask=()):
        k = self.t / name
        shutil.copytree(HERE.parent, k, ignore=I.KIT_IGNORE)
        f = k / "settings" / "profiles" / "permissive.fragment.json"
        d = json.loads(f.read_text(encoding="utf-8"))
        d["permissions"]["allow"] = [x for x in d["permissions"]["allow"] if x != "mcp__tokensave"] + \
            (["mcp__tokensave"] if with_entry else [])
        for key, extra in (("deny", deny), ("ask", ask)):
            d["permissions"][key] = list(d["permissions"].get(key) or []) + list(extra)
        f.write_text(json.dumps(d, indent=2), encoding="utf-8")
        return k

    def inst(self, kit, *args):
        time.sleep(1.1)                                   # a new backup folder per install
        r = subprocess.run([sys.executable, str(kit / "bootstrap" / "install.py"), "--no-cli", "--profile", "permissive", *args],
                           capture_output=True, text=True, encoding="utf-8", env=self.env, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-1000:])
        return r.stdout

    def allow(self):
        return json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]["allow"]

    def test_the_upgrade_drops_the_entry_the_old_kit_added_keeps_the_users_own_and_uninstall_still_works(self):
        self.inst(self.old, "--apply")
        self.assertIn("mcp__tokensave", self.allow(), "the 0.3.1-style install added it")
        s = json.loads(self.settings.read_text(encoding="utf-8"))
        s["permissions"]["allow"].append("Bash(my-own-tool:*)")           # the person's own entry, added afterwards
        self.settings.write_text(json.dumps(s, indent=2), encoding="utf-8")
        out = self.inst(self.new, "--apply")
        allow = self.allow()
        self.assertNotIn("mcp__tokensave", allow)
        self.assertIn("Bash(my-own-tool:*)", allow)
        self.assertIn("Bash(*)", allow, "the entries the new profile still has stay")
        self.assertIn('permissions.allow: removed "mcp__tokensave"', out)
        again = self.inst(self.new, "--apply")                              # a third install changes nothing more
        self.assertEqual(self.allow(), allow)
        self.assertNotIn("removed", again)
        self.inst(self.new, "--uninstall", "--apply")                       # the upgrade is reversible: its backup is restored
        self.assertIn("mcp__tokensave", self.allow())
        self.assertIn("Bash(my-own-tool:*)", self.allow())

    def test_uninstall_after_the_upgrade_puts_the_file_back_as_it_was_before_any_kit_install(self):
        self.settings.write_text('{\n    "model": "mine"\n}\n', encoding="utf-8")
        before = self.settings.read_bytes()
        self.inst(self.old, "--apply")
        self.inst(self.new, "--apply")
        self.assertNotIn("mcp__tokensave", self.allow())
        self.inst(self.new, "--uninstall", "--apply")
        self.assertEqual(self.settings.read_bytes(), before)

    def test_an_entry_the_user_had_before_any_kit_install_is_never_removed(self):
        self.settings.write_text(json.dumps({"permissions": {"allow": ["mcp__tokensave"]}}), encoding="utf-8")   # theirs
        self.inst(self.old, "--apply")
        self.inst(self.new, "--apply")
        self.assertIn("mcp__tokensave", self.allow())

    def test_an_entry_the_new_profile_still_has_stays(self):
        self.inst(self.old, "--apply")
        self.inst(self.old, "--apply")                                      # same profile again
        self.assertIn("mcp__tokensave", self.allow())

    DENY, ASK = "Read(//**/zebrafish-secret)", "Bash(zebrafish-tool:*)"

    def test_a_deny_or_ask_entry_a_profile_dropped_STAYS_and_additional_directories_are_not_touched(self):
        """Removing a deny or an ask would loosen policy (on a managed laptop most of all), so only allow entries are retired."""
        old = self.kit("old-da", with_entry=True, deny=[self.DENY], ask=[self.ASK])
        self.inst(old, "--apply")
        s = json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]
        self.assertIn(self.DENY, s["deny"])
        self.assertIn(self.ASK, s["ask"])
        kb = s["additionalDirectories"]
        self.assertTrue(kb, "the install added the KB root there")
        out = self.inst(self.new, "--apply")                                # the new profile has neither entry
        got = json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]
        self.assertIn(self.DENY, got["deny"])
        self.assertIn(self.ASK, got["ask"])
        self.assertNotIn("mcp__tokensave", got["allow"], "the allow entry is still retired")
        self.assertEqual(got["additionalDirectories"], kb)
        self.assertNotIn("permissions.deny: removed", out)
        self.assertNotIn("permissions.ask: removed", out)

    def test_a_downgrade_keeps_the_deny_the_newer_kit_added(self):
        newer = self.kit("newer", with_entry=False, deny=[self.DENY])
        older = self.kit("older", with_entry=False)
        self.inst(newer, "--apply")
        self.assertIn(self.DENY, json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]["deny"])
        out = self.inst(older, "--apply")                                   # an older kit runs after the newer one
        self.assertIn(self.DENY, json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]["deny"])
        self.assertNotIn("removed", out)


class KbPair(unittest.TestCase):
    """RE-10: bug-cards.md and bug-detectors.json refresh as ONE pair, digests one file at a time, and a file the user
    edited is never overwritten. The "old" kit is this kit with an earlier cards file (no card above sixty-six), its
    detectors, and two digests that differ."""
    CARDS, DET = "bug-cards.md", "bug-detectors.json"
    DIGESTS = ("windows-shell.md", "git-ci.md")

    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="wb-pair-"))
        self.addCleanup(shutil.rmtree, self.t, True)
        self.new_sh = HERE.parent / "kb-template" / "_shared"
        cards = (self.new_sh / self.CARDS).read_text(encoding="utf-8")
        det = json.loads((self.new_sh / self.DET).read_text(encoding="utf-8"))
        self.assertGreater(len(cards), cards.index("### 67. "), "the real pack has the new cards")
        self.old = self.t / "old"
        shutil.copytree(HERE.parent, self.old, ignore=I.KIT_IGNORE)
        sh = self.old / "kb-template" / "_shared"
        (sh / self.CARDS).write_text(cards[:cards.index("### 67. ")].rstrip("\n") + "\n", encoding="utf-8", newline="\n")
        det["detectors"] = [d for d in det["detectors"] if d["card"] <= 66]
        (sh / self.DET).write_text(json.dumps(det, indent=1) + "\n", encoding="utf-8", newline="\n")
        for n in self.DIGESTS:
            (sh / "digests" / n).write_text("old copy of " + n + "\n", encoding="utf-8")
        self.home, self.kb = self.t / "home", self.t / "kb"
        (self.home / ".claude").mkdir(parents=True)
        (self.t / "reg.json").write_text("{}", encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("OneDrive", "WORKBENCH_", "WB_"))}
        self.env.update(USERPROFILE=str(self.home), HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.home / ".claude"),
                        LOCALAPPDATA=str(self.t / "lad"), WORKBENCH_FAKE_REGISTRY=str(self.t / "reg.json"),
                        WORKBENCH_FAKE_BIN=str(self.t / "nobin"))
        self.inst(self.old, "--apply")               # the earlier release: the KB is made from ITS template
        self.old_pair = self.pair()
        self.new_pair = {n: (self.new_sh / n).read_bytes() for n in (self.CARDS, self.DET)}
        self.assertNotEqual(self.old_pair, self.new_pair)

    def inst(self, kit, *args, code=0):
        time.sleep(1.1)                              # a new backup folder per install
        r = subprocess.run([sys.executable, str(kit / "bootstrap" / "install.py"), "--no-cli", "--kb-root", str(self.kb),
                            *args], capture_output=True, text=True, encoding="utf-8", env=self.env, timeout=300)
        self.assertEqual(r.returncode, code, r.stdout[-2000:] + r.stderr[-1000:])
        return r.stdout

    def pair(self):
        return {n: (self.kb / "_shared" / n).read_bytes() for n in (self.CARDS, self.DET)}

    def orphans(self):
        """Card numbers the user's detectors name that the user's cards file lacks."""
        have = {int(m) for m in re.findall(r"(?m)^### (\d+)\. ", (self.kb / "_shared" / self.CARDS).read_text(encoding="utf-8"))}
        want = {d["card"] for d in json.loads((self.kb / "_shared" / self.DET).read_text(encoding="utf-8"))["detectors"]}
        return want - have

    def edit(self, name, text):
        p = self.kb / "_shared" / name
        p.write_text(p.read_text(encoding="utf-8") + text, encoding="utf-8", newline="\n")

    def test_untouched_pair_refreshes_together_and_uninstall_restores_it(self):
        out = self.inst(HERE.parent, "--apply")
        self.assertRegex(out, r"refresh \d+ unedited file\(s\) to this release: .*bug-cards\.md, _shared/bug-detectors\.json")
        self.assertEqual(self.pair(), self.new_pair)
        self.assertEqual(self.orphans(), set())
        self.assertNotIn("refresh", self.inst(HERE.parent, "--apply"), "a current pair is left alone")
        self.inst(HERE.parent, "--uninstall", "--apply")
        self.assertEqual(self.pair(), self.old_pair, "uninstall puts the earlier copies back")

    def test_an_install_without_recorded_hashes_is_judged_by_the_previous_kit_copy(self):
        for mf in (self.home / ".claude" / "workbench" / "backups").glob("*/manifest.json"):
            m = json.loads(mf.read_text(encoding="utf-8"))
            m.pop("kb_shas", None)                   # an earlier release recorded none
            mf.write_text(json.dumps(m), encoding="utf-8")
        self.inst(HERE.parent, "--apply")
        self.assertEqual(self.pair(), self.new_pair)

    def test_with_the_previous_kit_copy_gone_the_recorded_hashes_decide(self):
        shutil.rmtree(self.home / ".claude" / "workbench" / "kit")
        self.inst(HERE.parent, "--apply")
        self.assertEqual(self.pair(), self.new_pair)
        self.edit(self.CARDS, "\nmine\n")
        shutil.rmtree(self.home / ".claude" / "workbench" / "kit")
        mine = self.pair()
        self.assertIn("is edited", self.inst(HERE.parent, "--apply"))
        self.assertEqual(self.pair(), mine)

    def test_edited_cards_keep_both_files_and_warn(self):
        self.edit(self.CARDS, "\nmy own note\n")
        mine = self.pair()
        out = self.inst(HERE.parent, "--apply")
        self.assertEqual(self.pair(), mine, "neither file moved")
        self.assertRegex(out, r"WARNING: Kept your bug-cards.md and bug-detectors.json .*bug-cards\.md is edited\. .*/kit/kb-template/_shared")
        self.assertEqual(self.orphans(), set())

    def test_edited_detectors_keep_both_files_and_warn(self):
        self.edit(self.DET, " ")
        mine = self.pair()
        out = self.inst(HERE.parent, "--apply")
        self.assertEqual(self.pair(), mine, "the cards did not move without their detectors")
        self.assertRegex(out, r"WARNING: Kept your bug-cards.md and bug-detectors.json .*bug-detectors\.json is edited")
        self.assertEqual(self.orphans(), set())

    def test_a_removed_cards_file_stays_removed_and_the_detectors_stay_put(self):
        (self.kb / "_shared" / self.CARDS).unlink()
        out = self.inst(HERE.parent, "--apply")
        self.assertFalse((self.kb / "_shared" / self.CARDS).exists())
        self.assertEqual((self.kb / "_shared" / self.DET).read_bytes(), self.old_pair[self.DET])
        self.assertIn("bug-cards.md is removed", out)

    def test_digests_refresh_one_file_at_a_time(self):
        self.edit("digests/git-ci.md", "mine\n")
        mine = (self.kb / "_shared" / "digests" / "git-ci.md").read_bytes()
        out = self.inst(HERE.parent, "--apply")
        self.assertEqual((self.kb / "_shared" / "digests" / "git-ci.md").read_bytes(), mine)
        self.assertEqual((self.kb / "_shared" / "digests" / "windows-shell.md").read_bytes(),
                         (self.new_sh / "digests" / "windows-shell.md").read_bytes())
        self.assertIn("Kept your edited _shared/digests/git-ci.md", out)
        self.assertEqual(self.pair(), self.new_pair, "an edited digest does not hold the pair back")


@WINDOWS_ONLY
class SetupChain(unittest.TestCase):
    """--setup auto: the capability report runs before any install, then setup detaches (KILL3)."""
    def test_setup_auto_report_first_then_detached_runner(self):
        e = FakeEnv(scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"]})
        self.addCleanup(e.close)
        (e.wb / "config.json").unlink()
        r = e.run("--apply", "--no-cli", "--setup", "auto", script=HERE / "install.py", timeout=300)
        t_back = time.time()
        self.assertEqual(r.returncode, 0, r.stdout[-2000:])
        self.assertIn("Setup is running in the background", r.stdout)
        st = e.wait_done()
        self.assertIn(st["exit_code"], (0, 3, 4))
        c = e.calls()
        report = next(i for i, x in enumerate(c) if x["tool"] == "report" and "pre" in x["argv"])
        first_install = next(i for i, x in enumerate(c) if x["tool"] == "winget")
        self.assertLess(report, first_install, "the report is shown before any install")
        self.assertLess(t_back, max(x["t"] for x in c), "install returned while the detached runner kept working")
        self.assertTrue((e.wb / "state" / "setup.log").exists())

    def test_setup_plan_installs_nothing(self):
        e = FakeEnv(scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"]})
        self.addCleanup(e.close)
        (e.wb / "config.json").unlink()
        r = e.run("--apply", "--no-cli", "--setup", "plan", script=HERE / "install.py", timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:])
        self.assertTrue((e.wb / "state" / "plan.md").exists())
        self.assertTrue([x for x in e.calls("report") if "pre" in x["argv"]])
        self.assertEqual(installs(e), [])


if __name__ == "__main__":
    unittest.main()
