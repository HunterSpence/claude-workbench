"""Tests for the workbench-core hooks (session start, precompact, read-flood, checkpoint, ...) and the hook wiring itself. Run:
    python -m unittest discover -s plugins/workbench-core/scripts/tests
Each hook runs as a subprocess with a temp Claude home, workbench home and knowledge base."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # acceptance runs: a missing dependency fails, never skips
SCRIPTS = Path(__file__).resolve().parents[1]
PLUGIN = SCRIPTS.parent
REPO = PLUGIN.parents[1]
sys.path.insert(0, str(SCRIPTS))
import _wb  # noqa: E402
import auto_invoke  # noqa: E402
KEY = "AKIA" + "X" * 16          # built at runtime: this file holds no credential shape
WORD = "gu" + "ard"              # the removed feature's name, built at runtime: asserted absent from every banner


class Hooks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-hooks-"))
        self.kb = self.tmp / "kb"
        shutil.copytree(REPO / "kb-template", self.kb)
        (self.tmp / "claude").mkdir()
        self.wb = self.tmp / "claude" / "workbench"
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.tmp / "claude"), "WORKBENCH_KB_ROOT": str(self.kb),
                    "PYTHONIOENCODING": "utf-8"}
        self.env.pop("WORKBENCH_LOG_INSTRUCTIONS", None)
        # hermetic: no managed policy from this machine, and a stand-in for the capability report (never the real one)
        self.managed = self.tmp / "managed"
        self.managed.mkdir()
        self.marker = self.tmp / "report-called.json"
        (self.tmp / "stub_report.py").write_text(
            "import json, os, sys\ntmp = os.environ['WB_STUB_OUT'] + '.tmp'\n"
            "open(tmp, 'w').write(json.dumps(sys.argv[1:]))\nos.replace(tmp, os.environ['WB_STUB_OUT'])\n")
        self.env.update(WORKBENCH_POLICY_DIRS=str(self.managed), WORKBENCH_REPORT_CLI=str(self.tmp / "stub_report.py"),
                        WB_STUB_OUT=str(self.marker))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def kstate(self, kb=None):
        """The local KB state folder (flags, snapshots) for this test's KB, as the hooks compute it."""
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.tmp / "claude")}):
            return _wb.kb_state_dir(kb or self.kb)

    def tree(self, folder):
        return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))

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
        self.assertNotIn(WORD, ctx.lower(), "the banner names no removed feature")
        self.kstate().mkdir(parents=True, exist_ok=True)
        (self.kstate() / "precompact-s1.flag").write_text("x")
        ctx = self.hook("session_start.py", {"session_id": "s1"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("PRECOMPACT SAVE PENDING", ctx)

    def test_session_start_still_reads_an_earlier_kits_flags_in_the_kb(self):
        old = self.kb / ".state"
        old.mkdir()
        (old / "precompact-s1.flag").write_text("x")
        (old / "precompact-s9.flag").write_text("x")
        stale = old / "precompact-s8.flag"
        stale.write_text("x")
        os.utime(stale, (time.time() - 9 * 86400,) * 2)
        ctx = self.hook("session_start.py", {"session_id": "s1"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("PRECOMPACT SAVE PENDING", ctx)
        self.assertIn("1 other session(s) owe a save", ctx, "the fresh legacy flag counts, the 9-day-old one does not")
        (self.kstate()).mkdir(parents=True)
        (self.kstate() / "precompact-s1.flag").write_text("x")                  # the copy of the same flag: still one
        (self.kstate() / "precompact-s9.flag").write_text("x")
        ctx = self.hook("session_start.py", {"session_id": "s1"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("1 other session(s) owe a save", ctx)

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
        ctx = self.hook("session_start.py", {"session_id": "s1"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("main=opus/xhigh", ctx, "modelSettings effort beats the top-level effortLevel")
        self.assertIn("worker=sonnet/high", ctx)
        self.assertIn("haiku=haiku-x", ctx)
        self.assertIn("no longer imports the workbench instructions", ctx)
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
        before = self.tree(self.kb)
        self.assertIsNone(self.hook("precompact.py", {"session_id": "s2", "trigger": "auto"}))
        self.assertTrue((self.kstate() / "precompact-s2.flag").exists())
        self.assertEqual(len(list((self.kstate() / "snapshots").glob("active-context-*.md"))), 1)
        self.assertEqual(self.tree(self.kb), before, "the hook writes nothing into the knowledge base")
        self.assertRegex(json.loads((self.wb / "state" / "hooks-heartbeat.json").read_text())["last_precompact"],
                         r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_precompact_state_follows_the_kb_root(self):
        other = self.tmp / "kb2"
        shutil.copytree(REPO / "kb-template", other)
        (other / "active-context.md").write_text("# AC\n- two\n", encoding="utf-8")
        self.hook("precompact.py", {"session_id": "s3"}, env={"WORKBENCH_KB_ROOT": str(other)})
        self.hook("precompact.py", {"session_id": "s3"})
        self.assertNotEqual(self.kstate(other), self.kstate())
        self.assertTrue((self.kstate(other) / "precompact-s3.flag").exists() and (self.kstate() / "precompact-s3.flag").exists())

    def test_heartbeat_keeps_unknown_keys_and_stamps_last_start(self):
        """I3: <WB>/state/hooks-heartbeat.json = {last_start, last_precompact}; every SessionStart source stamps last_start."""
        self.state("hooks-heartbeat.json", {"note_from_setup": "keep me"})
        beat = self.wb / "state" / "hooks-heartbeat.json"
        read = lambda: json.loads(beat.read_text())  # noqa: E731
        stamp = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$"
        for source in ("startup", "resume", "clear", "compact"):
            d = read()
            d["last_start"] = "2000-01-01T00:00:00Z"
            beat.write_text(json.dumps(d))
            self.start(source)
            d = read()
            self.assertRegex(d["last_start"], stamp, source)
            self.assertNotEqual(d["last_start"], "2000-01-01T00:00:00Z", source)
            self.assertEqual(d["note_from_setup"], "keep me", source)
        self.hook("precompact.py", {"session_id": "s2"})
        d = read()
        self.assertRegex(d["last_precompact"], stamp)
        self.assertRegex(d["last_start"], stamp)                              # the other stamp is untouched
        self.assertEqual(sorted(d), ["last_precompact", "last_start", "note_from_setup"])

    def test_heartbeat_is_created_by_the_first_stamp_and_never_raises(self):
        beat = self.wb / "state" / "hooks-heartbeat.json"
        self.assertFalse(beat.exists())
        self.start("startup")
        self.assertEqual(sorted(json.loads(beat.read_text())), ["last_start"])
        self.assertEqual(list(beat.parent.glob("*.tmp")), [], "the atomic write leaves no temp file")
        beat.write_text("{broken")                                           # an unreadable file is replaced, not fatal
        self.start("startup")
        self.assertEqual(sorted(json.loads(beat.read_text())), ["last_start"])
        shutil.rmtree(self.wb / "state")
        (self.wb / "state").write_text("a file where the folder should be")   # unwritable: heartbeat() returns None
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.tmp / "claude")}):
            self.assertIsNone(_wb.heartbeat("last_start"))
        self.assertIn("PINS (user settings", self.start("startup"))           # and the banner still prints

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

    def status(self, j):
        r = subprocess.run([sys.executable, str(SCRIPTS / "statusline.py")], capture_output=True, text=True,
                           encoding="utf-8", env=self.env, timeout=60, input=json.dumps(j))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_statusline_cache_context_and_spend(self):
        full = {"model": {"id": "claude-opus-x", "display_name": "Opus"}, "context_window": {"used_percentage": 42.4},
                "cost": {"total_cost_usd": 1.234}, "prompt_cache": {"warm": True, "caching_observed": True, "hit_ratio": 0.912}}
        self.assertEqual(self.status(full), "[Opus] ctx:42% cache:91% warm $1.23")
        self.assertEqual(self.status({**full, "prompt_cache": {"warm": False, "hit_ratio": 0.4}}),
                         "[Opus] ctx:42% cache:40% cold $1.23")
        # missing or odd fields degrade to nothing, never an error
        for pc in (None, {}, "x", [], {"hit_ratio": "abc", "warm": True}, {"caching_observed": False, "hit_ratio": 0.9},
                   {"hit_ratio": None, "warm": None}):
            self.assertEqual(self.status({**full, "prompt_cache": pc}), "[Opus] ctx:42% $1.23", pc)
        self.assertEqual(self.status({"prompt_cache": {"warm": True}}), "[Claude] cache:warm")
        self.assertEqual(self.status({"prompt_cache": {"hit_ratio": 0.5}}), "[Claude] cache:50%")
        self.assertEqual(self.status({"cost": {}, "context_window": {}}), "[Claude]")

    def test_read_flood(self):
        big = self.tmp / "big.txt"
        big.write_text(("word " * 20 + "\n") * 2000, encoding="utf-8")
        out = self.hook("read_flood.py", {"tool_name": "Read", "tool_input": {"file_path": str(big)}})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIsNone(self.hook("read_flood.py", {"tool_input": {"file_path": str(big), "limit": 50}}))
        longline = self.tmp / "long.txt"
        longline.write_text("x," * 60_000 + "\n" + "y\n" * 100, encoding="utf-8")   # one huge line
        out = self.hook("read_flood.py", {"tool_input": {"file_path": str(longline), "limit": 5}})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        out = self.hook("read_flood.py", {"tool_input": {"file_path": str(self.tmp)}})
        self.assertIn("directory", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertTrue(out["hookSpecificOutput"]["permissionDecisionReason"].startswith("read-flood: "))
        small = self.tmp / "s.txt"
        small.write_text("hi")
        self.assertIsNone(self.hook("read_flood.py", {"tool_input": {"file_path": str(small)}}))
        self.assertIsNone(self.hook("read_flood.py", None, raw="not json"))
        log = self.wb / "logs" / "read-flood.log"
        self.assertFalse(log.exists())
        self.assertIsNone(self.hook("read_flood.py", {"tool_input": {"file_path": "no\0such.txt"}}))   # internal error: no decision
        self.assertIn("READFLOOD unhandled exception", log.read_text(encoding="utf-8"))
        if os.name == "nt":   # a Git Bash path is denied with the Windows path to use, never rewritten
            out = self.hook("read_flood.py", {"tool_input": {"file_path": "/tmp/" + "no-such-file-wb.txt"}})
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
            drive = str(small)[0].lower()
            out = self.hook("read_flood.py", {"tool_input": {"file_path": f"/{drive}" + str(small)[2:].replace("\\", "/")}})
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
        self.assertNotIn("/workbench-kb:save", out["hookSpecificOutput"]["additionalContext"])   # wrap-up must not match everything
        for p in ("I'm done for today", "that's it for now", "ok, let's wrap up"):
            out = self.hook("auto_invoke.py", {"hook_event_name": "UserPromptSubmit", "prompt": p})
            self.assertIn("/workbench-kb:save", out["hookSpecificOutput"]["additionalContext"], p)
        ctx = self.hook("auto_invoke.py", {"hook_event_name": "UserPromptSubmit",
                                           "prompt": "fix the failing test in the parser"})["hookSpecificOutput"]["additionalContext"]
        self.assertTrue("/workbench-core:repo-fix (" in ctx or "/workbench-core:ratchet (" in ctx, ctx)

    def test_installing_a_plugin_is_not_gated(self):
        """auto_invoke makes no permission decision on a shell command, even a plugin install."""
        ev = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "claude plugin install foo@bar"}}
        self.assertIsNone(self.hook("auto_invoke.py", ev))
        self.assertIn("hookSpecificOutput", self.hook("auto_invoke.py", {"hook_event_name": "UserPromptSubmit",
                                                                         "prompt": "ok, let's wrap up"}), "positive control")

    def test_auto_invoke_covers_every_skill(self):
        plugins = PLUGIN.parent
        dirs = [d for d in (PLUGIN / "skills", plugins / "workbench-kb" / "skills", plugins / "workbench-capture" / "skills")
                if d.is_dir()]
        kit = {d.name: d for root in dirs for d in root.iterdir() if (d / "SKILL.md").exists()}
        rows = {n for n, _, _ in auto_invoke.SKILLS}
        self.assertEqual(set(kit) - rows, set(), "every kit skill needs a trigger row")
        for skill, d in kit.items():
            if "disable-model-invocation: true" in (d / "SKILL.md").read_text(encoding="utf-8"):
                self.assertIn(skill, auto_invoke.USER_ONLY, f"{skill} is user-invoked: it may only be mentioned")
        # the frozen skill names (all merged or not): a row each; the renamed one is gone
        i8 = {"setup", "find", "repo-review", "plugin-factory", "plugin-review", "web-packager", "mcp-builder", "api-bridge",
              "capture", "ingest"}
        self.assertEqual(i8 - rows, set())
        self.assertNotIn("doc-index", rows)
        self.assertTrue({"setup", "capture", "ingest"} <= auto_invoke.USER_ONLY)
        self.assertEqual((auto_invoke.cmd("capture"), auto_invoke.cmd("ingest"), auto_invoke.cmd("setup"), auto_invoke.cmd("save")),
                         ("/workbench-capture:capture", "/workbench-capture:ingest", "/workbench-core:setup",
                          "/workbench-kb:save"))
        route = {"fix the bugs in github.com/acme/widgets": "repo-fix",
                 "review the repo read-only": "repo-review",
                 "redesign the settings page of the internal web app": "ui-build",
                 "draft a reply to this email": "draft-reply", "write a memo about the outage": "office-docx",
                 "make a deck for Friday": "office-pptx", "build a spreadsheet of the costs": "office-xlsx",
                 "can you drive the citrix remote desktop": "vdi-drive",
                 "find the latest version of the pricing doc": "find", "create a new claude plugin": "plugin-factory",
                 "build an mcp server for our ticketing": "mcp-builder", "wrap the internal api as an mcp tool": "api-bridge",
                 "run the workbench setup": "setup", "crawl the intranet wiki": "capture",
                 "ingest my meeting transcripts": "ingest"}
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

    # ── SessionStart: runtime assurance lines ──
    def state(self, name, obj, age_days=0):
        f = self.wb / "state" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(obj), encoding="utf-8")
        if age_days:
            t = time.time() - age_days * 86400
            os.utime(f, (t, t))
        return f

    def start(self, source="startup"):
        out = self.hook("session_start.py", {"session_id": "s1", "source": source})
        return out["hookSpecificOutput"]["additionalContext"]

    def called(self, timeout=20):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.marker.exists():
                try:
                    return json.loads(self.marker.read_text())
                except (PermissionError, ValueError):   # Windows: the stub's os.replace (or a scanner) still holds it
                    pass
            time.sleep(0.05)
        self.fail("the stand-in report command was never started")

    def test_session_start_quiet_when_nothing_is_wrong(self):
        ctx = self.start()
        for text in ("Setup pending", "Model routing", "managed policy changed", "have not run", "capability report"):
            self.assertNotIn(text, ctx)
        self.assertNotIn(WORD, ctx.lower())
        self.assertFalse(self.marker.exists())

    def test_session_start_setup_routing_policy_and_stale_report(self):
        self.state("setup-state.json", {"version": 1, "phase": "wsl", "running": False, "exit_code": 5,
                                        "next": "/workbench-core:setup resume", "ask_it": [{"item": "wsl", "text": "x"}],
                                        "failed": []})
        self.state("routing.effective.json", {"version": 1, "rows": [
            {"id": f"R-{i}", "persona": f"persona{i}", "model": "claude-sonnet-5-5" if i == 1 else "claude-opus-5-5",
             "effort": "xhigh", "fallback_used": i == 1} for i in range(7)]})
        self.state("policy-snapshot.json", {"version": 1, "classes": {"hooks_locked": False, "marketplaces_closed": False}})
        (self.managed / "managed-settings.json").write_text(json.dumps({"allowManagedHooksOnly": True,
                                                                        "strictKnownMarketplaces": []}))
        self.state("capability-pre.json", {"version": 1}, age_days=10)
        (self.kb / "active-context.md").write_text("\n".join(f"- line {i} " + "y" * 80 for i in range(400)), encoding="utf-8")
        out = self.hook("session_start.py", {"session_id": "s1", "source": "startup"})
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Setup pending: phase wsl, 1 item(s) for IT. Next: /workbench-core:setup resume", ctx)
        rows = [ln.strip() for ln in ctx.splitlines() if ln.startswith("  R-")]
        self.assertEqual(rows, ["R-0 persona0 opus-5-5/xhigh", "R-1 persona1 sonnet-5-5/xhigh*", "R-2 persona2 opus-5-5/xhigh",
                                "R-3 persona3 opus-5-5/xhigh", "R-4 persona4 opus-5-5/xhigh"])       # five rows, fallback marked
        self.assertIn("managed policy changed since setup: hooks_locked, marketplaces_closed; run setup.py doctor", ctx)
        self.assertIn("The capability report is 10 days old: a quick refresh was started in the background.", ctx)
        self.assertEqual(self.called(), ["run", "--phase", "refresh", "--quick", "--detach"])
        self.assertLessEqual(len(json.dumps(out, ensure_ascii=False).encode("utf-16-le")) // 2, 10_000)
        self.assertIn("TRUNCATED", ctx)                       # the notes stay; the active-context tail gives way
        self.assertIn("last_start", json.loads((self.wb / "state" / "hooks-heartbeat.json").read_text()))

    def test_session_start_knowledge_verify_line(self):
        import datetime as dt
        iso = lambda days: (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        self.assertNotIn("knowledge verify", self.start(), "no result file yet: say nothing")
        self.state("knowledge-verify.json", {"version": 1, "generated": iso(1), "steps": [],
                                             "summary": {"pass": 5, "warn": 1, "fail": 2, "failing": ["D3", "D9"]}})
        ctx = self.start()
        self.assertIn("knowledge verify: 2 failing (D3, D9); run setup.py doctor --deep", ctx)
        self.state("knowledge-verify.json", {"version": 1, "generated": iso(1), "steps": [],
                                             "summary": {"pass": 7, "warn": 0, "fail": 0, "failing": []}})
        self.assertNotIn("knowledge verify", self.start(), "a fresh all-pass result is quiet")
        self.state("knowledge-verify.json", {"version": 1, "generated": iso(31), "steps": [],
                                             "summary": {"pass": 7, "warn": 0, "fail": 0, "failing": []}})
        self.assertIn("knowledge verify is older than 30 days; run setup.py doctor --deep", self.start())
        for junk in ({"generated": "not a date"}, {"summary": "x"}, {"summary": {"failing": [1, {"a": 2}]}, "generated": iso(0)}):
            self.state("knowledge-verify.json", junk)
            self.assertIn("PINS (user settings", self.start(), "a damaged result never hides the rest of the banner")

    def test_session_start_policy_change_alone_starts_one_refresh_a_day(self):
        self.state("policy-snapshot.json", {"version": 1, "classes": {}})
        (self.managed / "managed-settings.json").write_text(json.dumps({"availableModels": ["x"]}))
        self.state("capability-post.json", {"version": 1})                      # fresh report, but the policy moved
        ctx = self.start()
        self.assertIn("managed policy changed since setup: models_restricted", ctx)
        self.assertIn("out of date after the policy change: a quick refresh was started", ctx)
        self.called()
        self.marker.unlink()
        self.state("capability-refresh.json", {"version": 1})                   # refreshed just now: not again
        self.assertNotIn("quick refresh", self.start())
        time.sleep(0.3)
        self.assertFalse(self.marker.exists())

    def test_session_start_survives_broken_state_files(self):
        for name in ("setup-state.json", "routing.effective.json", "hooks-heartbeat.json", "policy-snapshot.json"):
            (self.wb / "state").mkdir(parents=True, exist_ok=True)
            (self.wb / "state" / name).write_text("{not json", encoding="utf-8")
        (self.managed / "managed-settings.json").write_text("{broken")
        ctx = self.start()
        self.assertIn("PINS (user settings", ctx)

    # ── bug_hint (PostToolUseFailure) ──
    DETECTORS = {"version": 1, "detectors": [
        {"card": 7, "title": "Proxy certificate not trusted by node", "pattern": "UNABLE_TO_GET_ISSUER_CERT|self[- ]signed certificate",
         "repro": "Error: self-signed certificate in certificate chain"},
        {"card": 12, "title": "Path longer than 260 characters", "pattern": r"ENAMETOOLONG|filename or extension is too long",
         "repro": "The filename or extension is too long."}]}

    def failure(self, error, **kw):
        return self.hook("bug_hint.py", {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "error": error, **kw})

    def test_bug_hint_names_the_right_card(self):
        (self.kb / "_shared").mkdir(exist_ok=True)
        (self.kb / "_shared" / "bug-detectors.json").write_text(json.dumps(self.DETECTORS), encoding="utf-8")
        for d in self.DETECTORS["detectors"]:                                   # each detector fires on its own repro
            out = self.failure("Exit code 1\n" + d["repro"])["hookSpecificOutput"]
            self.assertEqual(out["hookEventName"], "PostToolUseFailure")
            self.assertEqual(out["additionalContext"], f"Known bug, card {d['card']}: {d['title']} (see _shared/bug-cards.md)")
        self.assertIsNone(self.failure("Exit code 1\nError: Cannot find module 'express'"))      # an unrelated error
        self.assertIsNone(self.failure("x" * 5000 + " ENAMETOOLONG"))                              # past the first 4 KB
        self.assertIsNone(self.failure("ENAMETOOLONG", is_interrupt=True))
        self.assertIsNone(self.hook("bug_hint.py", {"hook_event_name": "PostToolUseFailure"}))   # no error field
        self.assertIsNone(self.hook("bug_hint.py", None, raw="not json"))
        first = self.failure("self-signed certificate and ENAMETOOLONG")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("card 7", first)                                                             # at most one card

    def test_bug_hint_is_short_and_silent_on_bad_files(self):
        (self.kb / "_shared").mkdir(exist_ok=True)
        long = {"version": 1, "detectors": [{"card": 1, "title": "t " * 400, "pattern": "boom"}, {"card": "x", "pattern": "("}]}
        (self.kb / "_shared" / "bug-detectors.json").write_text(json.dumps(long), encoding="utf-8")
        msg = self.failure("boom")["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(msg), 300)
        self.assertTrue(msg.startswith("Known bug, card 1: ") and msg.endswith("(see _shared/bug-cards.md)"))
        self.assertIsNone(self.failure("no match here ("))                         # a broken regex row is skipped
        (self.kb / "_shared" / "bug-detectors.json").write_text("{nope", encoding="utf-8")
        self.assertIsNone(self.failure("boom"))
        (self.kb / "_shared" / "bug-detectors.json").unlink()
        self.assertIsNone(self.failure("boom"))

    def test_bug_hint_falls_back_to_the_kit_copy(self):
        kit = self.wb / "kit" / "kb-template" / "_shared"
        kit.mkdir(parents=True)
        (kit / "bug-detectors.json").write_text(json.dumps(self.DETECTORS), encoding="utf-8")
        shutil.rmtree(self.kb / "_shared", ignore_errors=True)
        self.assertIn("card 12", self.failure("ENAMETOOLONG")["hookSpecificOutput"]["additionalContext"])

    # ── policy_snapshot ──
    def snap(self, *args):
        r = subprocess.run([sys.executable, "-S", str(SCRIPTS / "policy_snapshot.py"), *args], capture_output=True, text=True,
                           encoding="utf-8", env=self.env, timeout=60)
        return r

    def test_policy_snapshot_detects_each_class_change(self):
        self.assertEqual(self.snap("--bogus").returncode, 2)
        base = json.loads(self.snap("--json", "--write").stdout)
        self.assertEqual(base["changed"], [])
        self.assertFalse(any(base["classes"].values()))
        self.assertRegex(base["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue((self.wb / "state" / "policy-snapshot.json").is_file())
        fixtures = {"hooks_locked": {"allowManagedHooksOnly": True}, "marketplaces_closed": {"strictKnownMarketplaces": []},
                    "models_restricted": {"deniedModels": ["claude-x"]}, "mcp_restricted": {"allowedMcpServers": [{"serverName": "a"}]},
                    "permissions_locked": {"permissions": {"disableBypassPermissionsMode": "disable"}}}
        for cls, conf in fixtures.items():
            (self.managed / "managed-settings.json").write_text(json.dumps(conf))
            got = json.loads(self.snap("--json").stdout)
            self.assertEqual(got["changed"], [cls], cls)
            self.assertTrue(got["classes"][cls])
            self.assertNotEqual(got["sha256"], base["sha256"])
        (self.managed / "managed-settings.json").unlink()
        (self.managed / "managed-mcp.json").write_text(json.dumps({"mcpServers": {}}))   # a managed MCP file locks MCP
        self.assertEqual(json.loads(self.snap("--json").stdout)["changed"], ["mcp_restricted"])
        (self.managed / "managed-mcp.json").unlink()
        (self.managed / "managed-settings.d").mkdir()                                       # drop-ins count too
        (self.managed / "managed-settings.d" / "10-hooks.json").write_text(json.dumps({"disableAllHooks": True}))
        self.assertEqual(json.loads(self.snap("--json").stdout)["changed"], ["hooks_locked"])
        (self.managed / "managed-settings.d" / "10-hooks.json").write_text("{broken")       # unreadable = present, hash moves
        self.assertNotEqual(json.loads(self.snap("--json").stdout)["sha256"], base["sha256"])
        self.assertIn("managed policy", self.snap().stdout)

    # ── settings profiles ──
    def profile(self, name):
        return json.loads((REPO / "settings" / "profiles" / f"{name}.fragment.json").read_text(encoding="utf-8"))

    def test_profiles_carry_the_16gb_keys_and_telemetry_off(self):
        for name, subagents in (("corporate", "8"), ("permissive", "12")):
            d = self.profile(name)
            self.assertEqual(d["crossSessionInbound"], "hold", name)
            self.assertEqual(d["env"]["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"], subagents, name)
            # DO_NOT_TRACK stays out of the Claude Code env: it also turns off feature-flag fetching; setup passes it to the tools it runs
            self.assertNotIn("DO_NOT_TRACK", d["env"], name)
            for k, v in {"HF_HUB_DISABLE_TELEMETRY": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                         "NPM_CONFIG_UPDATE_NOTIFIER": "false"}.items():
                self.assertEqual(d["env"].get(k), v, f"{name}: {k}")


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
        self.assertEqual(scripts("PreToolUse", "Read"), {"read_flood.py"})
        for tool in ("Bash", "PowerShell", "Edit", "Write", "NotebookEdit", "WebFetch", "Agent", "Grep"):
            self.assertEqual(scripts("PreToolUse", tool), set(), tool)
        # the whole PreToolUse section: the Read group, nothing else
        self.assertEqual([(g["matcher"], [Path(x["args"][-1]).name for x in g["hooks"]]) for g in h["PreToolUse"]],
                         [("Read", ["read_flood.py"])])
        self.assertEqual(scripts("PostToolUse", "Edit"), {"checkpoint.py", "ponytail_auto.py"})
        self.assertEqual(scripts("PostToolUse", "NotebookEdit"), {"ponytail_auto.py"})
        self.assertEqual(scripts("UserPromptSubmit"), {"ponytail_auto.py", "auto_invoke.py"})
        for ev, s in (("Stop", "cred_check.py"), ("PreCompact", "precompact.py"), ("ConfigChange", "config_change_log.py"),
                      ("InstructionsLoaded", "instructions_loaded.py"), ("SessionStart", "session_start.py")):
            self.assertIn(s, scripts(ev), ev)

    def test_tool_hooks_cover_nothing_but_read_and_shell(self):
        h = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
        def scripts(event, tool):
            return {Path(x["args"][-1]).name for g in h.get(event, []) if re.fullmatch(g.get("matcher", ".*"), tool)
                    for x in g["hooks"]}
        for verb in ("str_replace", "multi_str_replace", "insert_at", "insert_at_symbol", "replace_symbol", "ast_grep_rewrite",
                     "replace_lines", "delete_symbol", "search", "callers", "context", "status"):
            self.assertEqual(scripts("PreToolUse", "mcp__tokensave__tokensave_" + verb), set(), verb)
        for tool in ("mcp__postgres-db__execute_sql", "mcp__MySQL__run", "mcp__github__create_issue", "mcp__context7__query-docs"):
            self.assertEqual(scripts("PreToolUse", tool), set(), tool)
        self.assertNotIn("tokensave", (PLUGIN / "hooks" / "hooks.json").read_text().lower())   # code-graph rule: no hook names it

    def test_the_failure_hook_is_wired(self):
        h = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
        def scripts(event, tool):
            return {Path(x["args"][-1]).name for g in h.get(event, []) if re.fullmatch(g.get("matcher", ".*"), tool)
                    for x in g["hooks"]}
        for tool in ("Bash", "mcp__x__y"):
            self.assertEqual(scripts("PostToolUseFailure", tool), {"bug_hint.py"}, tool)
        self.assertNotIn("bug_hint.py", scripts("PostToolUse", "Bash"))

    def test_marketplace_lists_every_plugin(self):
        mk = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual(mk["name"], "workbench")
        names = {p["name"] for p in mk["plugins"]}
        self.assertEqual(names, {p.parent.parent.name for p in REPO.glob("plugins/*/.claude-plugin/plugin.json")})
        for p in mk["plugins"]:
            self.assertTrue((REPO / p["source"]).is_dir(), p["source"])


if __name__ == "__main__":
    unittest.main()
