"""knowledge_verify.py checks. Every step runs against a fake kit in a temp folder: stand-in kit CLIs driven by a scenario
file (KB scripts, find, the MCP healer and server, setup backup/restore, the self-tests), the kit's own hook scripts and
run_suites.py copied in, and fake programs on WORKBENCH_FAKE_BIN. Nothing touches this machine's profile, KB or index.
Run: python -m unittest discover -s bootstrap -p "test_knowledge_verify.py" -v   (WB_REQUIRE_ALL=1: a skip fails)"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import knowledge_verify as KV  # noqa: E402
import setup as S  # noqa: E402

QUESTIONS = json.loads((REPO / "docs" / "howto" / "questions.json").read_text(encoding="utf-8"))["questions"]

STUB = r'''
import json, os, sys, time
from pathlib import Path
d = Path(os.environ["WB_KV_DIR"])
sc = json.loads((d / "scenario.json").read_text(encoding="utf-8"))
a = sys.argv[1:]
with open(d / "calls.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps({"tool": TOOL, "argv": a, "env": {k: os.environ.get(k) for k in (
        "CLAUDE_CONFIG_DIR", "WORKBENCH_KB_ROOT", "KB_INDEX_DB", "HF_HUB_OFFLINE", "WORKBENCH_HOME",
        "WORKBENCH_KNOWLEDGE_DB", "WB_FIND_LAZY")}}) + "\n")
time.sleep(sc.get("sleep", {}).get(TOOL, 0))
def out(o):
    sys.stdout.write(json.dumps(o) + "\n")
rc = sc.get("rc", {}).get(TOOL, 0)
if TOOL == "kb_health":
    res = [{"check": c, "status": s, "detail": c + " fixture"} for c, s in {
        "layout": "PASS", "caps": "PASS", "frontmatter": "PASS", "index": "PASS", "dead-links": "PASS", "orphans": "PASS",
        "secrets": "PASS", **sc.get("health", {})}.items()]
    if "--eval" in a:
        res.append({"check": "eval", "status": sc.get("eval", "PASS"), "detail": "hit@1 0.9 >= floors (fixture)"})
    out({"kb_root": os.environ.get("WORKBENCH_KB_ROOT"), "results": res, "exit": 0})
elif TOOL == "kb_index":
    import sqlite3
    db = Path(os.environ.get("KB_INDEX_DB") or d / "live-kb.db")
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("create table if not exists meta(k text primary key, v text)")
    con.execute("insert or replace into meta values ('fts', ?)", (sc.get("fts", "1"),))
    con.commit(); con.close()
    out({"index": db.as_posix(), "result": "ok (fixture)"})
elif TOOL == "save_driver":
    kb = Path(os.environ["WORKBENCH_KB_ROOT"])
    if not sc.get("journal_lost"):
        with open(kb / "inbox.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": "t", "text": a[a.index("--inbox-add") + 1]}) + "\n")
    out({"ok": True})
elif TOOL == "kb_search":
    if "--related" in a:
        out([{"path": p, "via": "link", "depth": 1} for p in sc.get("kb_related", ["00-index.md", "_shared/HOT.md", "ai/HOT.md"])])
    else:
        f = Path(os.environ["WORKBENCH_KB_ROOT"]) / "inbox.jsonl"
        lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
        out({"query": a[-2], "hits": [{"path": "inbox.jsonl", "line": i + 1} for i, x in enumerate(lines)
                                      if "knowledge layer verified" in x]})
elif TOOL == "find":
    db = a[a.index("--db") + 1] if "--db" in a else None
    cmd = a[2:] if db else a
    store = Path(db + ".json") if db else d / "live-find.json"
    st = json.loads(store.read_text()) if store.exists() else {"roots": {}}
    if cmd[0] == "add-root":
        st["roots"][cmd[cmd.index("--label") + 1]] = {"ok": 0, "vectors": 0}
    elif cmd[0] == "refresh":
        lab = cmd[cmd.index("--root") + 1]
        st["roots"][lab] = {"ok": sc.get("find_ok", {}).get(lab, 3), "vectors": sc.get("vectors", 5)}
    elif cmd[0] == "status":
        hybrid = all(r["vectors"] for r in st["roots"].values()) and st["roots"] and sc.get("vectors", 5)
        out({"roots": [{"label": k, "files": {"ok": v["ok"]}, "vectors": v["vectors"]} for k, v in st["roots"].items()],
             "mode": "hybrid" if hybrid else "keyword", "paragraphs": 42,
             "last_refresh": sc.get("last_refresh", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))})
    elif cmd[0] == "roots":
        out({"roots": [{"label": x, "path": "p", "kind": x, "files": 1} for x in sc.get("live_roots", ["captured", "howto", "kb"])]})
    elif cmd[0] == "search":
        q, mode = cmd[1], cmd[cmd.index("--mode") + 1]
        want = next(x["expect"] for x in json.loads(Path(sc["questions"]).read_text(encoding="utf-8"))["questions"] if x["q"] == q)
        miss = sc.get("misses", 0) > 0 and q in [x["q"] for x in json.loads(Path(sc["questions"]).read_text(encoding="utf-8"))["questions"]][:sc.get("misses", 0)]
        names = ["99-other.md", "98-other.md", "97-other.md", Path(want).name] if miss else [Path(want).name, "99-other.md"]
        arms = {"bm25": 1, "dense": 2 if mode == "hybrid" else None}
        out({"mode": mode, "hits": [{"ref": "howto/" + n + "#p1", "path": n, "arms": arms} for n in names]})
    elif cmd[0] == "related":
        out({"start": cmd[1], "related": [{"ref": r} for r in sc.get("find_related", ["howto/README.md"])]})
    elif cmd[0] == "newest":
        out({"query": cmd[1], "newest": {"ref": sc.get("newest", cmd[1])}, "superseded": []})
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(st))
    rc = sc.get("rc", {}).get("find:" + cmd[0], rc)
elif TOOL == "healer":
    cfg, golden = Path(a[a.index("--config") + 1]), json.loads(Path(a[a.index("--golden") + 1]).read_text(encoding="utf-8"))
    if rc == 0:
        c = json.loads(cfg.read_text(encoding="utf-8"))
        for name, spec in golden["servers"].items():
            if spec.get("action") == "remove":
                c.get("mcpServers", {}).pop(name, None)
            else:
                c.setdefault("mcpServers", {})[name] = {k: v for k, v in spec.items() if k in ("command", "args", "env")}
        cfg.write_text(json.dumps(c), encoding="utf-8")
elif TOOL == "find_mcp":
    for line in sys.stdin:
        m = json.loads(line)
        if "id" not in m:
            continue
        r = {"protocolVersion": "2025-06-18", "serverInfo": {"name": "find"}} if m["method"] == "initialize" else \
            {"tools": [{"name": n} for n in sc.get("mcp_tools", ["search", "show", "related"])]} if m["method"] == "tools/list" else \
            {"structuredContent": {"untrusted": True, "hits": [{"ref": "howto/27-find-a-file-or-an-answer.md#p1",
                                                              "untrusted": not sc.get("mcp_trusted")}]}}
        out({"jsonrpc": "2.0", "id": m["id"], "result": r})
elif TOOL == "setup":
    if a[0] == "backup":
        z = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "fixture-backup.zip"
        z.write_bytes(b"PK\x05\x06" + b"\0" * 18)
        sd = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "workbench" / "state"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "backup.json").write_text(json.dumps({"last": "2026-01-05T10:00:00Z", "path": z.as_posix()}))
    elif a[0] == "restore":
        rc = sc.get("restore_rc", 0)
elif TOOL.startswith("selftest:"):
    rc = sc.get("selftest_rc", {}).get(TOOL[9:], 0)
    print("self-test ok" if rc == 0 else "self-test failed")
elif TOOL == "playwright-cli":
    print("0.1.22") if a == ["--version"] else None
    rc = sc.get("cli_open_rc", 0) if "open" in a else 0
elif TOOL == "schtasks":
    rc = 1
sys.exit(rc)
'''

# a bug_hint.py that implements IR2 the way the relay contract says (pending file, inject once, delete)
RELAY_HINT = r'''
import json, os, sys
from pathlib import Path
STOPFAILURE_MIN_CC = (2, 1, 200)
ev = json.loads(sys.stdin.read() or "{}")
st = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "workbench" / "state"
f = st / f"pending-hint-{ev.get('session_id')}.json"
if "--pending" in sys.argv:
    done, keep = f.with_name(f.name + ".done"), os.environ.get("WB_KV_KEEP_PENDING")
    if f.exists() and not done.exists():
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "additionalContext": json.loads(f.read_text())["title"]}}))
        if keep == "2":             # injects once but leaves the file behind
            done.write_text("x")
        elif keep != "1":           # "1": injects again on every prompt
            f.unlink()
elif ev.get("hook_event_name") == "StopFailure" and "overloaded" in str(ev.get("last_assistant_message")):
    st.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"card": 67, "title": "fixture card", "source": "message", "created": "t"}))
sys.exit(0)
'''


def tool_file(path, tool):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"TOOL = {tool!r}\nimport os\nexec(compile(open(os.environ['WB_KV_STUB'], encoding='utf-8').read(), "
                    "'stub', 'exec'))\n", encoding="utf-8")


def fake_kit(dst):
    kit = Path(dst)
    for rel in ("bootstrap/knowledge-checks.json", "bootstrap/packages.json", "bootstrap/features.json",
                "mcp/golden-config.template.json", "tools/run_suites.py", "tools/memcap/memcap.py",
                "plugins/workbench-kb/scripts/kb_audit.py", "plugins/workbench-kb/scripts/savelock.py"):
        (kit / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, kit / rel)
    shutil.copytree(REPO / "kb-template", kit / "kb-template")
    for f in ("_wb.py", "session_start.py", "precompact.py"):
        (kit / "plugins/workbench-core/scripts").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / "plugins/workbench-core/scripts" / f, kit / "plugins/workbench-core/scripts" / f)
    (kit / "plugins/workbench-core/scripts/bug_hint.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")   # no relay
    (kit / "tools/skips.allow").write_text("test_fake::Fake.test_allowed_skip  # fixture: allowed\n", encoding="utf-8")
    tests = kit / "plugins/workbench-kb/tests"
    tests.mkdir(parents=True)
    (tests / "test_fake.py").write_text(
        "import os, unittest\nclass Fake(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
        "    def test_allowed_skip(self):\n        self.skipTest('fixture')\n", encoding="utf-8")
    for name in ("kb_health", "kb_index", "kb_search", "save_driver"):
        tool_file(kit / "plugins/workbench-kb/scripts" / f"{name}.py", name)
    tool_file(kit / "tools/mcp-healer/mcp_healer.py", "healer")
    tool_file(kit / "plugins/workbench-core/skills/find/scripts/find_mcp.py", "find_mcp")
    tool_file(kit / "bootstrap/setup.py", "setup")
    for rel in ("tools/model-sweep/model_sweep.py", "tools/token-split/token_split.py"):     # two of the nine IT1 tools
        tool_file(kit / rel, "selftest:" + Path(rel).stem)
    (kit / "docs/howto").mkdir(parents=True)
    shutil.copyfile(REPO / "docs/howto/questions.json", kit / "docs/howto/questions.json")
    return kit


class Env:
    """A temp profile (config dir, KB from kb-template, find index stand-in), a fake kit and a scenario."""
    def __init__(self, scenario=None, capture=None):
        self.root = Path(tempfile.mkdtemp(prefix="wb-kv-"))
        self.kit = fake_kit(self.root / "kit")
        self.home, self.ch = self.root / "home", self.root / "home" / ".claude"
        self.wb, self.kb, self.bin = self.ch / "workbench", self.root / "data" / "kb", self.root / "fakebin"
        for d in (self.wb / "state", self.bin, self.root / "lad"):
            d.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.kit / "kb-template", self.kb)
        (self.kb / "00-index.md").write_text("# Index\n", encoding="utf-8")
        self.live_find = self.root / "lad" / "index.sqlite"
        self.live_find.write_bytes(b"")
        (self.wb / "config.json").write_text(json.dumps({"profile": "corporate", "data_root": I_fwd(self.root / "data"),
                                                         "kb_root": I_fwd(self.kb), "knowledge_db": I_fwd(self.live_find)}))
        (self.ch / ".claude.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        (self.ch / "settings.json").write_text(json.dumps({"enabledPlugins": {p: True for p in KV.PLUGINS}}), encoding="utf-8")
        (self.wb / "state" / "guard-heartbeat.json").write_text(json.dumps({"last_start": "2026-01-05T10:00:00Z"}))
        self.probe = self.root / "probe.json"
        self.probe.write_text(json.dumps({"sections": {"capture": {"data": capture or {
            "automation_allowed": True, "headless_allowed": True, "edge_path": "C:/Edge/msedge.exe"}}}}), encoding="utf-8")
        self.scenario = {"questions": str(REPO / "docs/howto/questions.json"), **(scenario or {})}
        self.save()
        stub = self.root / "stub.py"
        stub.write_text(STUB, encoding="utf-8")
        find = self.root / "find_stub.py"
        tool_file(find, "find")
        base = {k: v for k, v in os.environ.items() if not k.startswith(("WORKBENCH_", "WB_", "OneDrive", "KB_INDEX"))}
        self.env = {**base, "CLAUDE_CONFIG_DIR": str(self.ch), "USERPROFILE": str(self.home), "HOME": str(self.home),
                    "LOCALAPPDATA": str(self.root / "lad"), "WB_KV_DIR": str(self.root), "WB_KV_STUB": str(stub),
                    "WORKBENCH_FIND_CLI": str(find), "WORKBENCH_FAKE_BIN": str(self.bin),
                    "WORKBENCH_FAKE_REGISTRY": str(self.root / "registry.json"), "WORKBENCH_PROBE_JSON": str(self.probe)}
        (self.root / "registry.json").write_text("{}")

    def save(self):
        (self.root / "scenario.json").write_text(json.dumps(self.scenario), encoding="utf-8")

    def program(self, name, tool=None):
        """A program on the fake PATH that runs the stand-in as `tool`."""
        impl = self.bin / f"{name}_impl.py"
        tool_file(impl, tool or name)
        if os.name == "nt":
            (self.bin / f"{name}.cmd").write_text(f'@"{sys.executable}" "{impl}" %*\r\n', encoding="utf-8")
        else:
            p = self.bin / name
            p.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n', encoding="utf-8")
            p.chmod(0o755)

    def calls(self, tool=None):
        p = self.root / "calls.jsonl"
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []
        return [c for c in rows if tool is None or c["tool"] == tool]

    def ctx(self):
        return S.Ctx()

    def run(self, mode="doctor"):
        with mock.patch.dict(os.environ, self.env, clear=True):
            return KV.run(S.Ctx(), mode, self.kit)

    def step(self, fn, mode="doctor", prep=None):
        """One step on a fresh verifier: (status, detail, ask)."""
        with mock.patch.dict(os.environ, self.env, clear=True):
            v = KV.Verifier(S.Ctx(), mode, self.kit)
            try:
                for p in prep or ():
                    p(v)
                res = fn(v)
                row = KV.step_row(fn.__name__.split("_")[0].upper(), "x", res, 0)
                return row["status"], row["detail"], row["ask_it"]
            finally:
                shutil.rmtree(v.sb, ignore_errors=True)

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def I_fwd(p):
    return str(p).replace("\\", "/")


def by_id(doc):
    return {s["id"]: s for s in doc["steps"]}


class Base(unittest.TestCase):
    def env(self, **kw):
        e = Env(**kw)
        self.addCleanup(e.close)
        return e


class Rules(unittest.TestCase):
    def test_the_named_fail_list_is_exactly_the_plans(self):
        self.assertEqual(set(KV.FAIL_LIST), {"D1", "D2", "D3", "D4", "D5", "D6", "D7", "D10", "D14", "D20", "D21"})

    def test_a_named_step_keeps_its_fail_and_every_other_step_is_capped_at_warn(self):
        for sid, name, _fn in KV.STEPS + (("D20", "record", None),):
            row = KV.step_row(sid, name, (KV.FAIL, "x"), 0)
            self.assertEqual(row["status"], KV.FAIL if sid in KV.FAIL_LIST else KV.WARN, sid)
        for sid in ("D9", "D11", "D13", "D15", "D16", "D17", "D18", "D19", "D22", "D23"):      # environment-dependent
            self.assertNotIn(sid, KV.FAIL_LIST)

    def test_every_step_from_d1_to_d23_is_listed_once_and_d0_is_the_doctors_placement_rows(self):
        ids = [s[0] for s in KV.STEPS] + ["D20"]
        self.assertEqual(sorted(ids, key=lambda x: int(x[1:])), [f"D{n}" for n in range(1, 24)])

    def test_the_record_shape_is_ik2(self):
        doc = KV.document([KV.step_row("D3", "kb-machinery", (KV.FAIL, "y" * 400), 12.7),
                           KV.step_row("D9", "find-build", (KV.WARN, "w", "ask"), 3)])
        self.assertEqual(set(doc), {"version", "generated", "kit_version", "steps", "summary"})
        self.assertEqual(doc["summary"], {"pass": 0, "warn": 1, "fail": 1, "failing": ["D3"]})
        s = doc["steps"][0]
        self.assertEqual(set(s), {"id", "name", "status", "detail", "ms", "ask_it"})
        self.assertEqual((len(s["detail"]), s["ms"], s["ask_it"]), (300, 12, None))
        self.assertEqual(doc["steps"][1]["ask_it"], "ask")

    def test_the_relay_floor_is_read_without_running_the_file(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "bug_hint.py"
            f.write_text("raise SystemExit('never run')\nSTOPFAILURE_MIN_CC = (2, 1, 250)\n", encoding="utf-8")
            self.assertEqual(KV.stopfailure_floor(f), (2, 1, 250))
            for bad in ("X = 1\n", "STOPFAILURE_MIN_CC = '2.1.250'\n", "STOPFAILURE_MIN_CC = (2, 1)\n", "def (:\n"):
                f.write_text(bad, encoding="utf-8")
                self.assertIsNone(KV.stopfailure_floor(f), bad)
            self.assertIsNone(KV.stopfailure_floor(Path(t) / "missing.py"))


class Record(Base):
    def test_the_record_is_written_atomically_and_read_back(self):
        e = self.env()
        with mock.patch.dict(os.environ, e.env, clear=True):
            ctx = S.Ctx()
            path = ctx.state_dir / "knowledge-verify.json"
            path.write_text('{"previous": true}\n', encoding="utf-8")
            doc = KV.record(ctx, [KV.step_row("D1", "kb-seeded", (KV.PASS, "ok"), 1)])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), doc)
            self.assertEqual(by_id(doc)["D20"]["status"], KV.PASS)
            with mock.patch.object(KV.os, "replace", side_effect=OSError("disk full")):
                doc = KV.record(ctx, [KV.step_row("D1", "kb-seeded", (KV.PASS, "ok"), 1)])
            self.assertEqual(by_id(doc)["D20"]["status"], KV.FAIL)
            self.assertEqual(doc["summary"]["failing"], ["D20"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["summary"]["fail"], 0, "the old file is intact")
            self.assertEqual([p.name for p in path.parent.glob(".knowledge-verify.json.*")], [], "no temp file left")


class Steps(Base):
    def test_kb_seeded(self):
        e = self.env()
        self.assertEqual(e.step(KV.d1_kb_seeded)[0], KV.PASS)
        (e.kb / "00-index.md").unlink()
        st, detail, _ = e.step(KV.d1_kb_seeded)
        self.assertEqual(st, KV.FAIL)
        self.assertIn("00-index.md", detail)
        (e.kb / "00-index.md").write_text("# Index\n", encoding="utf-8")
        shutil.rmtree(e.kb / "security")
        self.assertEqual(e.step(KV.d1_kb_seeded)[0], KV.FAIL, "seven domains")

    def test_kb_state_is_local_and_free_and_an_old_state_folder_waits_for_the_next_save(self):
        e = self.env()
        st, detail, _ = e.step(KV.d2_kb_state, mode="setup")
        self.assertEqual(st, KV.PASS, detail)
        self.assertTrue(list((e.wb / "kb-state").glob("*/save.lock")), "the lock lives in the local state folder")
        (e.kb / ".state").mkdir()
        self.assertEqual(e.step(KV.d2_kb_state)[0], KV.WARN)
        (e.kit / "plugins/workbench-kb/scripts/kb_audit.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
        self.assertEqual(e.step(KV.d2_kb_state)[0], KV.FAIL)

    def test_kb_state_in_doctor_mode_creates_nothing(self):
        e = self.env()
        st, _, _ = e.step(KV.d2_kb_state)
        self.assertEqual(st, KV.WARN, "not created yet")
        self.assertFalse((e.wb / "kb-state").exists())

    def test_kb_machinery_runs_the_kit_tests_and_only_allowed_skips_pass(self):
        e = self.env()
        st, detail, _ = e.step(KV.d3_kb_machinery)
        self.assertEqual(st, KV.PASS, detail)
        self.assertIn("1 allowed skip", detail)
        t = e.kit / "plugins/workbench-kb/tests/test_fake.py"
        t.write_text(t.read_text(encoding="utf-8") + "    def test_odd_skip(self):\n        self.skipTest('x')\n", encoding="utf-8")
        st, detail, _ = e.step(KV.d3_kb_machinery)
        self.assertEqual(st, KV.FAIL)
        self.assertIn("test_odd_skip", detail)
        t.write_text("import unittest\nclass Fake(unittest.TestCase):\n    def test_bad(self):\n        self.fail()\n",
                     encoding="utf-8")
        self.assertEqual(e.step(KV.d3_kb_machinery)[0], KV.FAIL)

    def test_journal_in_doctor_mode_touches_only_a_sandbox_and_setup_writes_one_live_line(self):
        e = self.env()
        self.assertEqual(e.step(KV.d4_journal)[0], KV.PASS)
        self.assertFalse((e.kb / "inbox.jsonl").exists(), "doctor never writes the live KB")
        self.assertEqual(e.step(KV.d4_journal, mode="setup")[0], KV.PASS)
        lines = (e.kb / "inbox.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("knowledge layer verified", lines[0])
        e.scenario["journal_lost"] = True
        e.save()
        self.assertEqual(e.step(KV.d4_journal)[0], KV.FAIL)

    def test_kb_index_in_doctor_mode_builds_into_the_sandbox(self):
        e = self.env()
        self.assertEqual(e.step(KV.d5_kb_index)[0], KV.PASS)
        built = [c["env"]["KB_INDEX_DB"] for c in e.calls("kb_index")]
        self.assertTrue(built and all(b and "wb-verify-" in b for b in built), built)
        e.scenario.update(fts="0")
        e.save()
        self.assertEqual(e.step(KV.d5_kb_index)[0], KV.WARN, "no FTS5: plain-table fallback")
        e.scenario.update(fts="1", health={"secrets": "FAIL"})
        e.save()
        self.assertEqual(e.step(KV.d5_kb_index)[0], KV.FAIL)
        e.scenario.update(health={"dead-links": "WARN"})
        e.save()
        self.assertEqual(e.step(KV.d5_kb_index)[0], KV.WARN)

    def test_kb_retrieval_reads_the_eval_floor_on_a_template_sandbox(self):
        e = self.env()
        (e.kit / "plugins/workbench-kb/tests/kb_canned.json").write_text('{"cases": []}', encoding="utf-8")
        self.assertEqual(e.step(KV.d6_kb_retrieval)[0], KV.PASS)
        ev = [c for c in e.calls("kb_health") if "--eval" in c["argv"]][-1]
        self.assertNotEqual(ev["env"]["WORKBENCH_KB_ROOT"], str(e.kb), "a sandbox copy, never the live KB")
        e.scenario["eval"] = "FAIL"
        e.save()
        self.assertEqual(e.step(KV.d6_kb_retrieval)[0], KV.FAIL)
        (e.kit / "plugins/workbench-kb/tests/kb_canned.json").unlink()
        self.assertEqual(e.step(KV.d6_kb_retrieval)[0], KV.FAIL)

    def test_kb_graph_needs_every_expected_note(self):
        e = self.env()
        self.assertEqual(e.step(KV.d7_kb_graph)[0], KV.PASS)
        e.scenario["kb_related"] = ["00-index.md"]
        e.save()
        st, detail, _ = e.step(KV.d7_kb_graph)
        self.assertEqual((st, "_shared/HOT.md" in detail), (KV.FAIL, True))

    def test_find_build_keyword_meaning_and_graph_on_a_sandbox_index(self):
        e = self.env()

        def chain(v):
            out = [KV.d9_find_build(v)[0], KV.d10_find_keyword(v)[0], KV.d11_find_meaning(v)[0], KV.d12_find_graph(v)[0]]
            return KV.PASS if out == [KV.PASS] * 4 else KV.FAIL, json.dumps(out)
        st, detail, _ = e.step(chain)
        self.assertEqual(st, KV.PASS, detail)
        calls = e.calls("find")
        self.assertTrue(all("--db" in c["argv"] for c in calls), "every find call names the sandbox index")
        self.assertTrue(all(c["env"]["HF_HUB_OFFLINE"] == "1" for c in calls), "the doctor never downloads the model")
        self.assertFalse((e.root / "live-find.json").exists(), "the live index is untouched")

    def test_find_without_vectors_is_keyword_only_with_the_hybrid_ask(self):
        e = self.env(scenario={"vectors": 0})
        res = {}

        def chain(v):
            res.update(d9=KV.step_row("D9", "x", KV.d9_find_build(v), 0), d10=KV.d10_find_keyword(v)[0],
                       d11=KV.step_row("D11", "x", KV.d11_find_meaning(v), 0))
            return KV.PASS, ""
        e.step(chain)
        self.assertEqual(res["d9"]["status"], KV.WARN)
        self.assertIn("huggingface", res["d9"]["ask_it"])
        self.assertEqual((res["d10"], res["d11"]["status"]), (KV.PASS, KV.WARN))

    def test_find_keyword_needs_ten_of_ten(self):
        e = self.env(scenario={"misses": 1})
        st = {}

        def chain(v):
            KV.d9_find_build(v)
            st["d10"] = KV.d10_find_keyword(v)
            return KV.PASS, ""
        e.step(chain)
        self.assertEqual(st["d10"][0], KV.FAIL)
        self.assertIn("9/10", st["d10"][1])

    def test_find_keyword_fails_when_the_howto_index_is_empty_and_warns_after_a_timeout(self):
        e = self.env(scenario={"find_ok": {"howto": 0}})
        self.assertEqual(e.step(KV.d10_find_keyword, prep=[KV.d9_find_build])[0], KV.FAIL)
        e.scenario.update(find_ok={})
        e.save()
        with mock.patch.object(KV.Verifier, "run", autospec=True, side_effect=KV.Timeout(1)):
            def d9(v):
                try:
                    KV.d9_find_build(v)
                except KV.Timeout:
                    pass
            self.assertEqual(e.step(KV.d10_find_keyword, prep=[d9])[0], KV.WARN)

    def test_find_mcp_registers_the_filled_find_entry_records_it_and_shakes_hands(self):
        e = self.env()
        st, detail, _ = e.step(KV.d13_find_mcp, mode="setup")
        self.assertEqual(st, KV.PASS, detail)
        golden = json.loads((e.wb / "state" / "find-mcp.golden.json").read_text(encoding="utf-8"))
        self.assertEqual(list(golden["servers"]), ["find"])
        spec = golden["servers"]["find"]
        self.assertNotIn("{{", json.dumps(spec))
        self.assertEqual(spec["args"], [I_fwd(e.kit / "plugins/workbench-core/skills/find/scripts/find_mcp.py")])
        led = json.loads((e.wb / "state" / "provision-ledger.json").read_text(encoding="utf-8"))["entries"]
        self.assertEqual([x["kind"] for x in led], ["mcp"])
        self.assertTrue(all(c["env"]["WB_FIND_LAZY"] == "0" for c in e.calls("find_mcp")), "no background refresh")
        e.scenario["mcp_trusted"] = True
        e.save()
        self.assertEqual(e.step(KV.d13_find_mcp)[0], KV.WARN, "a hit without untrusted: true")
        e.live_find.unlink()
        n = len(e.calls("find_mcp"))
        st, detail, _ = e.step(KV.d13_find_mcp)
        self.assertEqual(st, KV.WARN)
        self.assertIn("no live index", detail)
        self.assertFalse(e.live_find.exists(), "a missing live index is never created by the check")
        self.assertEqual(len(e.calls("find_mcp")), n + 1)

    def test_find_mcp_under_a_managed_policy_is_a_warn_with_the_ask(self):
        e = self.env(scenario={"rc": {"healer": 3}})
        st, _, ask = e.step(KV.d13_find_mcp, mode="setup")
        self.assertEqual(st, KV.WARN)
        self.assertIn("allow list", ask)
        self.assertFalse((e.wb / "state" / "provision-ledger.json").exists(), "nothing registered, nothing recorded")

    def test_hooks_run_in_a_sandbox_and_never_write_the_kb(self):
        e = self.env()
        st, detail, _ = e.step(KV.d14_hooks)
        self.assertEqual(st, KV.PASS, detail)
        self.assertIn("relay is not in this kit", detail)
        self.assertFalse((e.wb / "kb-state").exists(), "the live state folder is untouched")
        pc = e.kit / "plugins/workbench-core/scripts/precompact.py"       # an earlier kit: the flag inside the KB
        old = 'return _wb.kb_state_dir(kb) / f"precompact-'
        self.assertIn(old, pc.read_text(encoding="utf-8"))
        pc.write_text(pc.read_text(encoding="utf-8").replace(old, 'return kb / ".state" / f"precompact-'), encoding="utf-8")
        st, detail, _ = e.step(KV.d14_hooks)
        self.assertEqual(st, KV.FAIL)
        self.assertIn("inside the KB", detail)

    def test_hooks_without_a_session_or_plugins_are_a_warn(self):
        e = self.env()
        (e.wb / "state" / "guard-heartbeat.json").unlink()
        (e.ch / "settings.json").write_text("{}", encoding="utf-8")
        st, detail, _ = e.step(KV.d14_hooks)
        self.assertEqual(st, KV.WARN)
        self.assertIn("not enabled yet", detail)

    def test_a_silent_session_start_fails_the_hooks_step(self):
        e = self.env()
        (e.kit / "plugins/workbench-core/scripts/session_start.py").write_text("print('{}')\n", encoding="utf-8")
        self.assertEqual(e.step(KV.d14_hooks)[0], KV.FAIL)

    def test_the_relay_dry_run_needs_inject_once_then_delete(self):
        e = self.env()
        (e.kit / "plugins/workbench-core/scripts/bug_hint.py").write_text(RELAY_HINT, encoding="utf-8")
        st, detail, _ = e.step(KV.d14_hooks)
        self.assertEqual(st, KV.PASS, detail)
        self.assertIn("relay dry run ok", detail)
        e.env["WB_KV_KEEP_PENDING"] = "1"
        st, detail, _ = e.step(KV.d14_hooks)
        self.assertEqual(st, KV.FAIL)
        self.assertIn("did not inject and delete", detail)
        e.env["WB_KV_KEEP_PENDING"] = "2"
        st, detail, _ = e.step(KV.d14_hooks)
        self.assertEqual(st, KV.FAIL, "injected once, but the hint file stays behind")
        self.assertIn("did not inject and delete", detail)

    def test_backup_restore_drill(self):
        e = self.env()
        self.assertEqual(e.step(KV.d16_backup)[0], KV.WARN, "never backed up")
        self.assertEqual(e.step(KV.d16_backup, mode="setup")[0], KV.PASS)
        restore = [c for c in e.calls("setup") if c["argv"][0] == "restore"]
        self.assertIn("--to", restore[-1]["argv"])
        e.scenario["restore_rc"] = 4
        e.save()
        self.assertEqual(e.step(KV.d16_backup)[0], KV.WARN)

    def test_kit_tools_self_test_a_missing_tool_is_skipped_never_failed(self):
        e = self.env()
        st, detail, _ = e.step(KV.d21_kit_tools)
        self.assertEqual(st, KV.PASS, detail)
        self.assertIn("2 tool(s)", detail)
        self.assertIn("hidden_text", detail)
        for c in e.calls():
            if c["tool"].startswith("selftest:"):
                self.assertEqual(c["argv"], ["--self-test"])
        e.scenario["selftest_rc"] = {"token_split": 1}
        e.save()
        self.assertEqual(e.step(KV.d21_kit_tools)[0], KV.FAIL)
        e.scenario["selftest_rc"] = {}
        e.save()
        ht = e.kit / "plugins/workbench-core/skills/office-render/scripts/hidden_text.py"     # a tool with venv packages
        tool_file(ht, "selftest:hidden_text")
        (ht.parents[1] / "requirements.txt").write_text("pypdfium2==5.14.0\n", encoding="utf-8")
        st, detail, _ = e.step(KV.d21_kit_tools)
        self.assertEqual(st, KV.PASS)
        self.assertIn("after setup.py run makes the knowledge venv: hidden_text", detail)
        self.assertFalse([c for c in e.calls() if c["tool"] == "selftest:hidden_text"], "not run without the venv")
        cfg = json.loads((e.wb / "config.json").read_text())
        (e.wb / "config.json").write_text(json.dumps({**cfg, "knowledge_python": I_fwd(sys.executable)}))
        st, detail, _ = e.step(KV.d21_kit_tools)
        self.assertEqual((st, "3 tool(s)" in detail), (KV.PASS, True), detail)
        for rel in ("tools/model-sweep/model_sweep.py", "tools/token-split/token_split.py",
                    "plugins/workbench-core/skills/office-render/scripts/hidden_text.py"):
            (e.kit / rel).unlink()
        self.assertEqual(e.step(KV.d21_kit_tools)[0], KV.SKIP)

    def test_updates_read_the_update_record(self):
        e = self.env()
        self.assertEqual(e.step(KV.d22_updates)[0], KV.WARN, "no record yet")
        (e.wb / "state" / "update.json").write_text(json.dumps({"items": [{"id": "git", "action": "current"}]}))
        self.assertEqual(e.step(KV.d22_updates)[0], KV.PASS)
        (e.wb / "state" / "update.json").write_text(json.dumps({"items": [{"id": "git", "action": "failed"}]}))
        self.assertEqual(e.step(KV.d22_updates)[0], KV.WARN)

    @unittest.skipUnless(os.name == "nt" or REQUIRE, "fake .cmd programs need Windows")
    def test_browser_cli_opens_and_closes_headless_edge_and_a_policy_block_is_a_warn_with_the_ask(self):
        e = self.env()
        st, _, ask = e.step(KV.d23_browser_cli)
        self.assertEqual(st, KV.WARN, "not installed")
        self.assertTrue(ask)
        e.program("playwright-cli")
        st, detail, _ = e.step(KV.d23_browser_cli)
        self.assertEqual(st, KV.PASS, detail)
        argv = [c["argv"] for c in e.calls("playwright-cli") if c["argv"] != ["--version"]]
        self.assertEqual(argv, [["-s=wb-verify", "open", "about:blank", "--browser=msedge"], ["-s=wb-verify", "close"]])
        e.scenario["cli_open_rc"] = 1
        e.save()
        self.assertEqual(e.step(KV.d23_browser_cli)[0], KV.WARN)
        e.probe.write_text(json.dumps({"sections": {"capture": {"data": {"automation_allowed": True, "headless_allowed": False,
                                                                         "edge_path": "C:/Edge/msedge.exe"}}}}))
        before = len(e.calls("playwright-cli"))
        st, detail, ask = e.step(KV.d23_browser_cli)
        self.assertEqual(st, KV.WARN)
        self.assertIn("headless", detail)
        self.assertIn("HeadlessModeEnabled", ask)
        self.assertEqual(len(e.calls("playwright-cli")), before + 1, "only --version: nothing launched under the policy")
        e.probe.write_text(json.dumps({"sections": {"capture": {"data": {"automation_allowed": False}}}}))
        st, _, ask = e.step(KV.d23_browser_cli)
        self.assertEqual(st, KV.WARN)
        self.assertIn("RemoteDebuggingAllowed", ask)

    def test_live_find_reads_never_start_a_background_refresh(self):
        e = self.env()
        self.assertEqual(e.step(KV.d8_find_roots)[0], KV.PASS)
        self.assertEqual(e.step(KV.d19_full_refresh)[0], KV.PASS)
        live = [c for c in e.calls("find") if "--db" not in c["argv"]]
        self.assertEqual([c["argv"][0] for c in live], ["roots", "status"])
        self.assertTrue(all(c["env"]["WB_FIND_LAZY"] == "0" for c in live))
        e.scenario["live_roots"] = ["captured", "howto"]
        e.save()
        st, detail, _ = e.step(KV.d8_find_roots)
        self.assertEqual((st, "kb" in detail), (KV.WARN, True))
        self.assertEqual(e.step(KV.d19_full_refresh, mode="setup")[0], KV.SKIP, "setup starts it after the phase")

    def test_opt_ins_and_capture_off(self):
        e = self.env()
        self.assertEqual(e.step(KV.d18_opt_ins)[0], KV.OFF)
        self.assertEqual(e.step(KV.d17_capture)[0], KV.OFF)


class WholeRun(Base):
    def test_a_doctor_run_passes_writes_only_the_record_and_leaves_no_sandbox(self):
        e = self.env()
        (e.kit / "plugins/workbench-kb/tests/kb_canned.json").write_text('{"cases": []}', encoding="utf-8")
        (e.ch / ".claude.json").write_text(json.dumps({"mcpServers": {"find": {
            "command": sys.executable, "args": [str(e.kit / "plugins/workbench-core/skills/find/scripts/find_mcp.py")]}}}))
        snap = lambda: sorted((p.relative_to(e.root).as_posix(), p.stat().st_size if p.is_file() else -1)  # noqa: E731
                              for p in e.root.rglob("*") if "kit" not in p.relative_to(e.root).parts[:1]
                              and p.name not in ("calls.jsonl", "setup.log", "live-find.json"))
        e.step(KV.d2_kb_state, mode="setup")          # a profile where the state folder and save.lock exist
        before = snap()
        tmp_before = set(Path(tempfile.gettempdir()).glob("wb-verify-*"))
        doc = e.run("doctor")
        steps = by_id(doc)
        self.assertEqual(doc["summary"]["failing"], [], json.dumps(doc["steps"], indent=1))
        for sid in KV.FAIL_LIST:
            self.assertEqual(steps[sid]["status"], KV.PASS, steps[sid])
        self.assertEqual(json.loads((e.wb / "state" / "knowledge-verify.json").read_text(encoding="utf-8")), doc)
        changed = sorted(set(snap()) ^ set(before))
        self.assertEqual({c[0] for c in changed}, {"home/.claude/workbench/state/knowledge-verify.json"}, changed)
        self.assertEqual(set(Path(tempfile.gettempdir()).glob("wb-verify-*")) - tmp_before, set(), "sandbox removed")

    def test_a_crashing_check_is_a_fail_only_for_a_named_step(self):
        e = self.env()
        with mock.patch.object(KV, "STEPS", (("D9", "find-build", lambda v: 1 / 0), ("D3", "kb-machinery", lambda v: 1 / 0))):
            doc = e.run("doctor")
        self.assertEqual({s["id"]: s["status"] for s in doc["steps"]}, {"D9": KV.WARN, "D3": KV.FAIL, "D20": KV.PASS})
        self.assertIn("ZeroDivisionError", by_id(doc)["D3"]["detail"])

    def test_a_timeout_is_a_warn_naming_the_step_even_for_a_named_one(self):
        e = self.env()

        def slow(v):
            raise KV.Timeout(5)
        with mock.patch.object(KV, "STEPS", (("D3", "kb-machinery", slow),)):
            doc = e.run("doctor")
        self.assertEqual(by_id(doc)["D3"]["status"], KV.WARN)
        self.assertIn("kb-machinery timed out", by_id(doc)["D3"]["detail"])


if __name__ == "__main__":
    unittest.main()
