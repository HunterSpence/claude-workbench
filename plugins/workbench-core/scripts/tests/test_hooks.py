"""Tests for the workbench-core hooks other than the guard engine, plus the hook wiring itself. Run:
    python -m unittest discover -s plugins/workbench-core/scripts/tests
Each hook runs as a subprocess with a temp Claude home, workbench home and knowledge base."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
PLUGIN = SCRIPTS.parent
REPO = PLUGIN.parents[1]
KEY = "AKIA" + "X" * 16          # built at runtime: this file holds no credential shape


class Hooks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-hooks-"))
        self.kb = self.tmp / "kb"
        shutil.copytree(REPO / "kb-template", self.kb)
        (self.tmp / "claude").mkdir()
        self.wb = self.tmp / "claude" / "workbench"
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.tmp / "claude"), "WORKBENCH_KB_ROOT": str(self.kb),
                    "GUARDS_LOG_DIR": str(self.tmp / "logs"), "PYTHONIOENCODING": "utf-8"}
        self.env.pop("WORKBENCH_LOG_INSTRUCTIONS", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def hook(self, script, event, raw=None, env=None):
        r = subprocess.run([sys.executable, "-S", str(SCRIPTS / script)], capture_output=True, text=True,
                           encoding="utf-8", env={**self.env, **(env or {})}, timeout=120,
                           input=raw if raw is not None else json.dumps(event))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('"allow"', r.stdout, f"{script} answered allow")          # no hook ever allows
        self.assertNotIn("updatedInput", r.stdout, f"{script} rewrote a tool input")
        return json.loads(r.stdout) if r.stdout.strip() else None

    def test_session_start(self):
        (self.kb / "active-context.md").write_text("# AC\n- open: proxy cert rollout\n", encoding="utf-8")
        (self.tmp / "claude" / "settings.json").write_text(json.dumps({"model": "opus", "effortLevel": "high"}))
        out = self.hook("session_start.py", {"session_id": "s1", "source": "startup"})
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("proxy cert rollout", ctx)
        self.assertIn("PINS (user settings; managed policy may override", ctx)
        self.assertIn("main=opus/high", ctx)
        self.assertIn("every push to a remote host is refused until the user adds hosts", ctx)
        (self.kb / ".state").mkdir(exist_ok=True)
        (self.kb / ".state" / "precompact-s1.flag").write_text("x")
        ctx = self.hook("session_start.py", {"session_id": "s1"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("PRECOMPACT SAVE PENDING", ctx)

    def test_session_start_pins_health_and_due_items(self):
        import datetime
        today = datetime.date.today()
        past, far = (today - datetime.timedelta(days=3)).isoformat(), (today + datetime.timedelta(days=30)).isoformat()
        (self.kb / "active-context.md").write_text(f"# AC\n- {past} send the report\n- {far} later\n- ~~{past} done~~\n",
                                                   encoding="utf-8")
        (self.tmp / "claude" / "settings.json").write_text(json.dumps({
            "model": "opus", "effortLevel": "low", "modelSettings": {"opus": {"effortLevel": "xhigh"}, "sonnet": {"effortLevel": "high"}},
            "env": {"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet", "ANTHROPIC_DEFAULT_HAIKU_MODEL": "haiku-x"}}))
        (self.wb / "instructions").mkdir(parents=True)
        (self.wb / "instructions" / "CLAUDE.md").write_text("x")
        (self.tmp / "claude" / "CLAUDE.md").write_text("# mine\n")
        (self.tmp / "logs").mkdir()
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        (self.tmp / "logs" / "guards.log").write_text(f"{stamp} sid=s tool=Bash cwd=/x ERROR rule y skipped\n")
        ctx = self.hook("session_start.py", {"session_id": "s1"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("main=opus/xhigh", ctx, "modelSettings effort beats the top-level effortLevel")
        self.assertIn("worker=sonnet/high", ctx)
        self.assertIn("haiku=haiku-x", ctx)
        self.assertIn("no longer imports the workbench instructions", ctx)
        self.assertIn("1 guard error(s) since yesterday", ctx)
        self.assertIn(f"OVERDUE - {past} send the report", ctx)
        self.assertNotIn(f"DUE - {far}", ctx)
        self.assertNotIn("OVERDUE - ~~", ctx)
        self.assertIn("USER.md is missing", ctx)
        (self.wb / "USER.md").write_text((REPO / "templates" / "USER.md").read_text(encoding="utf-8"), encoding="utf-8")
        ctx = self.hook("session_start.py", {"session_id": "s1"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("still the blank template: suggest the user run /workbench-core:onboard", ctx)
        (self.wb / "USER.md").write_text("# About me\n- **Name I go by:** Sam\n", encoding="utf-8")
        (self.tmp / "claude" / "CLAUDE.md").write_text("@workbench/instructions/CLAUDE.md\n")
        ctx = self.hook("session_start.py", {"session_id": "s1"})["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("no longer imports", ctx)
        self.assertNotIn("/workbench-core:onboard", ctx)

    def test_session_start_caps_output(self):
        (self.kb / "active-context.md").write_text("\n".join(f"- line {i} " + "y" * 80 for i in range(400)),
                                                   encoding="utf-8")
        out = self.hook("session_start.py", {"session_id": "s1"})
        s = json.dumps(out, ensure_ascii=False)
        self.assertLessEqual(len(s.encode("utf-16-le")) // 2, 10_000)
        self.assertIn("TRUNCATED", out["hookSpecificOutput"]["additionalContext"])

    def test_session_start_without_kb(self):
        shutil.rmtree(self.kb)
        ctx = self.hook("session_start.py", {})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("does not exist", ctx)

    def test_precompact(self):
        (self.kb / "active-context.md").write_text("# AC\n", encoding="utf-8")
        self.assertIsNone(self.hook("precompact.py", {"session_id": "s2", "trigger": "auto"}))
        self.assertTrue((self.kb / ".state" / "precompact-s2.flag").exists())
        self.assertEqual(len(list((self.kb / ".state" / "snapshots").glob("active-context-*.md"))), 1)

    def test_statusline(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "statusline.py")], capture_output=True, text=True,
                           encoding="utf-8", env=self.env, timeout=60, input=json.dumps({
                               "model": {"id": "claude-opus-x", "display_name": "Opus"}, "effort": {"level": "high"},
                               "context_window": {"used_percentage": 42.4}, "workspace": {"current_dir": "/srv/app"},
                               "cost": {"total_cost_usd": 1.234}, "rate_limits": {"five_hour": {"used_percentage": 91}}}))
        self.assertEqual(r.stdout.strip(), "[Opus] high ctx:42% app $1.23 !5h:91%")
        r = subprocess.run([sys.executable, str(SCRIPTS / "statusline.py")], capture_output=True, text=True,
                           input="garbage", timeout=60)
        self.assertEqual(r.stdout.strip(), "[Claude]")

    def test_read_flood_guard(self):
        big = self.tmp / "big.txt"
        big.write_text(("word " * 20 + "\n") * 2000, encoding="utf-8")
        out = self.hook("read_flood_guard.py", {"tool_name": "Read", "tool_input": {"file_path": str(big)}})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIsNone(self.hook("read_flood_guard.py", {"tool_input": {"file_path": str(big), "limit": 50}}))
        longline = self.tmp / "long.txt"
        longline.write_text("x," * 60_000 + "\n" + "y\n" * 100, encoding="utf-8")   # one huge line
        out = self.hook("read_flood_guard.py", {"tool_input": {"file_path": str(longline), "limit": 5}})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        out = self.hook("read_flood_guard.py", {"tool_input": {"file_path": str(self.tmp)}})
        self.assertIn("directory", out["hookSpecificOutput"]["permissionDecisionReason"])
        small = self.tmp / "s.txt"
        small.write_text("hi")
        self.assertIsNone(self.hook("read_flood_guard.py", {"tool_input": {"file_path": str(small)}}))
        self.assertIsNone(self.hook("read_flood_guard.py", None, raw="not json"))
        if os.name == "nt":   # a Git Bash path is denied with the Windows path to use, never rewritten
            out = self.hook("read_flood_guard.py", {"tool_input": {"file_path": "/tmp/" + "no-such-file-wb.txt"}})
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
            drive = str(small)[0].lower()
            out = self.hook("read_flood_guard.py", {"tool_input": {"file_path": f"/{drive}" + str(small)[2:].replace("\\", "/")}})
            self.assertIn(str(small).replace("\\", "/")[2:], out["hookSpecificOutput"]["permissionDecisionReason"])

    def transcript(self, text):
        p = self.tmp / "t.jsonl"
        p.write_text("\n".join(json.dumps(x) for x in (
            {"type": "user", "message": {"role": "user", "content": "hi"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})),
            encoding="utf-8")
        return str(p)

    def test_cred_check(self):
        out = self.hook("cred_check.py", {"transcript_path": self.transcript(f"Here it is: {KEY}")})
        self.assertEqual(out["decision"], "block")
        self.assertNotIn(KEY, out["reason"])
        self.assertIsNone(self.hook("cred_check.py", {"transcript_path": self.transcript("All done, tests pass.")}))
        self.assertIsNone(self.hook("cred_check.py", {"transcript_path": self.transcript(KEY), "stop_hook_active": True}))

    def test_auto_invoke(self):
        out = self.hook("auto_invoke.py", {"hook_event_name": "UserPromptSubmit", "prompt": "ok, let's wrap up"})
        self.assertIn("/workbench-kb:save", out["hookSpecificOutput"]["additionalContext"])
        out = self.hook("auto_invoke.py", {"hook_event_name": "UserPromptSubmit", "prompt": "refactor the parser"})
        self.assertIn("/workbench-core:cascade", out["hookSpecificOutput"]["additionalContext"])
        for p in ("I'm done for today", "that's it for now", "ok, let's wrap up"):
            out = self.hook("auto_invoke.py", {"hook_event_name": "UserPromptSubmit", "prompt": p})
            self.assertIn("/workbench-kb:save", out["hookSpecificOutput"]["additionalContext"], p)
        ctx = self.hook("auto_invoke.py", {"hook_event_name": "UserPromptSubmit",
                                           "prompt": "fix the failing test in the parser"})["hookSpecificOutput"]["additionalContext"]
        self.assertTrue("/workbench-core:repo-fix (" in ctx or "/workbench-core:ratchet (" in ctx, ctx)

    def test_install_gate(self):
        ev = lambda c: {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": c}}  # noqa: E731
        plain, marked = "claude plugin install foo@bar", "claude plugin install foo@bar  # skill-scanned"
        none = {"SKILLSPECTOR_EXE": str(self.tmp / "missing.exe"), "PATH": str(self.tmp)}
        for cmd in (plain, marked):    # no scanner: ask, marker or not
            out = self.hook("auto_invoke.py", ev(cmd), env=none)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask", cmd)
        exe = self.tmp / "skillspector.exe"
        exe.write_text("x")
        have = {"SKILLSPECTOR_EXE": str(exe)}
        self.assertEqual(self.hook("auto_invoke.py", ev(plain), env=have)["hookSpecificOutput"]["permissionDecision"], "deny")
        out = self.hook("auto_invoke.py", ev(marked), env=have)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask", "the marker alone never passes")

    def test_auto_invoke_covers_every_skill(self):
        sys.path.insert(0, str(PLUGIN / "scripts"))
        import auto_invoke
        kit = {d.name for d in (PLUGIN / "skills").iterdir() if (d / "SKILL.md").exists()}
        kit |= {d.name for d in (PLUGIN.parent / "workbench-kb" / "skills").iterdir() if (d / "SKILL.md").exists()}
        self.assertEqual(kit - {n for n, _, _ in auto_invoke.SKILLS}, set(), "every kit skill needs a trigger row")
        for skill in kit:
            text = (PLUGIN / "skills" / skill / "SKILL.md") if (PLUGIN / "skills" / skill).exists() else None
            if text and "disable-model-invocation: true" in text.read_text(encoding="utf-8"):
                self.assertIn(skill, auto_invoke.USER_ONLY, f"{skill} is user-invoked: it may only be mentioned")
        route = {"fix the bugs in github.com/acme/widgets": "repo-fix",
                 "redesign the settings page of the internal web app": "ui-build",
                 "draft a reply to this email": "draft-reply", "write a memo about the outage": "office-docx",
                 "make a deck for Friday": "office-pptx", "build a spreadsheet of the costs": "office-xlsx",
                 "can you drive the citrix remote desktop": "vdi-drive"}
        for prompt, skill in route.items():
            out = self.hook("auto_invoke.py", {"hook_event_name": "UserPromptSubmit", "prompt": prompt})
            ctx = out["hookSpecificOutput"]["additionalContext"]
            self.assertIn(auto_invoke.cmd(skill) + (" is user-invoked only" if skill in auto_invoke.USER_ONLY else " ("),
                          ctx, prompt)
        self.assertIsNone(self.hook("auto_invoke.py", {"hook_event_name": "UserPromptSubmit", "prompt": "thanks"}))

    def test_ponytail_auto_once_per_context(self):
        skill = PLUGIN / "skills" / "ponytail" / "SKILL.md"
        ev = {"hook_event_name": "UserPromptSubmit", "prompt": "implement the cache", "session_id": "p1"}
        out = self.hook("ponytail_auto.py", ev)
        if not skill.exists():
            self.assertIsNone(out)   # no skill text, no injection
            return
        self.assertIn("ponytail", out["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.hook("ponytail_auto.py", ev))
        self.hook("ponytail_auto.py", {"hook_event_name": "SessionStart", "source": "compact", "session_id": "p1"})
        self.assertIsNotNone(self.hook("ponytail_auto.py", ev))

    def test_checkpoint_cadence(self):
        ev = {"session_id": "c1", "tool_name": "Edit", "tool_input": {"file_path": str(self.tmp / "x.py")}}
        outs = [self.hook("checkpoint.py", ev) for _ in range(25)]
        self.assertTrue(all(o is None for o in outs[:24]))
        self.assertIn("JOURNAL CHECKPOINT", outs[24]["hookSpecificOutput"]["additionalContext"])
        sub = {**ev, "agent_id": "a1"}
        self.assertIsNone(self.hook("checkpoint.py", sub))

    def test_logs(self):
        self.hook("config_change_log.py", {"source": "user_settings", "file_path": "settings.json"})
        self.assertIn("source=user_settings", (self.wb / "logs" / "config-change.log").read_text())
        log = self.wb / "logs" / "instructions-loaded.jsonl"
        kit_file = self.wb / "instructions" / "CLAUDE.md"
        kit_file.parent.mkdir(parents=True)
        kit_file.write_bytes(b"a\r\nb\r\n")
        users_own = self.tmp / "claude" / "CLAUDE.md"
        users_own.write_text("# mine\n")
        self.hook("instructions_loaded.py", {"file_path": str(kit_file), "load_reason": "session_start"})
        self.assertFalse(log.exists(), "logging must be off unless WORKBENCH_LOG_INSTRUCTIONS=1")
        on = {"WORKBENCH_LOG_INSTRUCTIONS": "1"}
        self.hook("instructions_loaded.py", {"file_path": str(users_own), "load_reason": "session_start"}, env=on)
        self.assertFalse(log.exists(), "the user's own instruction files are never logged")
        self.hook("instructions_loaded.py", {"file_path": str(kit_file), "load_reason": "session_start"}, env=on)
        row = json.loads(log.read_text().splitlines()[-1])
        self.assertEqual((row["bytes"], row["load_reason"]), (4, "session_start"))

class Wiring(unittest.TestCase):
    def hook_files(self):
        return sorted(REPO.glob("plugins/*/hooks/hooks.json"))

    def test_every_hook_command_is_exec_form_and_exists(self):
        for hf in self.hook_files():
            plugin = hf.parents[1]
            for event, groups in json.loads(hf.read_text())["hooks"].items():
                for g in groups:
                    for h in g["hooks"]:
                        self.assertEqual(h["command"], "${user_config.python}", f"{hf}: {event}")
                        script = h["args"][-1].replace("${CLAUDE_PLUGIN_ROOT}", str(plugin))
                        self.assertTrue(Path(script).exists(), script)
                        self.assertTrue(script.endswith(".py"))
            self.assertNotIn("tokensave", hf.read_text().lower())
            uc = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text()).get("userConfig", {})
            self.assertIn("python", uc, f"{plugin.name} needs a python userConfig for its hooks")

    def test_hook_wiring_events(self):
        h = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
        def scripts(event, tool=None):
            return {Path(x["args"][-1]).name for g in h.get(event, [])
                    if tool is None or re.fullmatch(g.get("matcher", ".*"), tool) for x in g["hooks"]}
        self.assertEqual(scripts("PreToolUse", "Bash"), {"pretooluse.py", "auto_invoke.py"})
        for tool in ("Edit", "Write", "NotebookEdit", "WebFetch", "Agent", "Grep"):
            self.assertIn("pretooluse.py", scripts("PreToolUse", tool), tool)
        self.assertEqual(scripts("PreToolUse", "Read"), {"pretooluse.py", "read_flood_guard.py"})
        self.assertEqual(scripts("PostToolUse", "Edit"), {"checkpoint.py", "ponytail_auto.py"})
        self.assertEqual(scripts("PostToolUse", "NotebookEdit"), {"ponytail_auto.py"})
        self.assertEqual(scripts("UserPromptSubmit"), {"ponytail_auto.py", "auto_invoke.py"})
        for ev, s in (("Stop", "cred_check.py"), ("PreCompact", "precompact.py"), ("ConfigChange", "config_change_log.py"),
                      ("InstructionsLoaded", "instructions_loaded.py"), ("SessionStart", "session_start.py")):
            self.assertIn(s, scripts(ev), ev)

    def test_marketplace_lists_every_plugin(self):
        mk = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual(mk["name"], "workbench")
        names = {p["name"] for p in mk["plugins"]}
        self.assertEqual(names, {p.parent.parent.name for p in REPO.glob("plugins/*/.claude-plugin/plugin.json")})
        for p in mk["plugins"]:
            self.assertTrue((REPO / p["source"]).is_dir(), p["source"])


if __name__ == "__main__":
    unittest.main()
