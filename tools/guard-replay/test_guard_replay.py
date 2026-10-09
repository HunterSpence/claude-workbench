"""Tests for guard_replay.py: fictional transcripts written at test time, a throwaway Claude home, no network. Run:
    python -m unittest discover -s tools/guard-replay"""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: nothing here skips

import hashlib  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
TOOL = HERE / "guard_replay.py"
CORPORATE = HERE.parents[1] / "plugins" / "workbench-core" / "scripts" / "guards" / "rulepacks" / "corporate.py"
SENTINEL = "SENTINEL-COMMAND-TEXT"          # must never appear in anything the tool prints
EMPTY_PACK = "SHELL = ()\n"
ASK_PACK = ("import engine as E\n\n\ndef rule(c):\n    if 'asked-by-candidate' in c.cmd:\n"
            "        E.ask('check this', 'candidate-rule', c.cmd)\n\n\nSHELL = (rule,)\n")


def line(tid, name, ti, cwd="/work/app"):
    return json.dumps({"type": "assistant", "cwd": cwd, "message": {"content": [
        {"type": "text", "text": "ok"}, {"type": "tool_use", "id": tid, "name": name, "input": ti}]}})


class Replay(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-replay-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tr = self.tmp / "tr"
        self.tr.mkdir()
        self.home = self.tmp / "claude"
        self.live = self.home / "workbench" / "logs"                   # what a real session would be writing
        self.live.mkdir(parents=True)
        (self.live / "guards.log").write_text("earlier line\n", encoding="utf-8")
        # the expected verdicts below are the strict level's (the default is standard: no-verify asks there)
        (self.home / "workbench" / "corporate-allowlist.json").write_text('{"guard_level": "strict"}\n', encoding="utf-8")
        self.scratch = self.tmp / "scratch"
        self.scratch.mkdir()
        self.env = {k: v for k, v in os.environ.items() if k != "GUARDS_LOG_DIR"}
        self.env.update(CLAUDE_CONFIG_DIR=str(self.home), WORKBENCH_LOG_DIR=str(self.live), PYTHONIOENCODING="utf-8",
                        TMP=str(self.scratch), TEMP=str(self.scratch), TMPDIR=str(self.scratch))

    def transcript(self, *rows, name="s.jsonl"):
        (self.tr / name).write_text("\n".join(rows) + "\n", encoding="utf-8")

    def pack(self, text, name="cand.py"):
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    def cli(self, *args, env=None):
        return subprocess.run([sys.executable, "-I", str(TOOL), *args], capture_output=True, text=True, encoding="utf-8",
                              env={**self.env, **(env or {})}, timeout=120)

    def snapshot(self):
        return sorted((p.relative_to(self.home).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "")
                      for p in self.home.rglob("*"))

    def basic(self):
        self.transcript(line("t_force", "Bash", {"command": f"git push --force origin main  # {SENTINEL}"}),
                        line("t_nv", "Bash", {"command": "git commit --no-verify -m msg"}),   # only the generic pack judges this
                        line("t_echo", "Bash", {"command": "echo hello"}),
                        line("t_cand", "Bash", {"command": "echo asked-by-candidate"}))

    # ── what it reports ──
    def test_it_compares_baseline_with_candidate_and_names_ids_and_guards_only(self):
        self.basic()
        r = self.cli("--rules", self.pack(ASK_PACK), "--transcripts", str(self.tr))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("baseline : pass 2  ask 0  deny 2", r.stdout)
        self.assertIn("candidate: pass 1  ask 1  deny 2", r.stdout)
        self.assertIn("changed: 1  (looser 0, stricter 1)", r.stdout)
        self.assertIn("t_cand  pass -> ask  stricter  [candidate-rule]", r.stdout)
        for text in (r.stdout, r.stderr):
            self.assertNotIn(SENTINEL, text)
            self.assertNotIn("asked-by-candidate", text)
            self.assertNotIn("git push", text)

    def test_json_output_lists_every_change(self):
        self.transcript(*[line(f"t{i}", "Bash", {"command": "git commit --no-verify -m msg"}) for i in range(50)])
        r = self.cli("--rules", self.pack(EMPTY_PACK, "generic.py"), "--transcripts", str(self.tr), "--json")
        d = json.loads(r.stdout)
        self.assertEqual((d["calls"], len(d["changed"]), d["looser"], d["stricter"]), (50, 50, 50, 0))
        self.assertEqual(d["candidate"], "generic.py replaces")
        text = self.cli("--rules", self.pack(EMPTY_PACK, "generic.py"), "--transcripts", str(self.tr)).stdout
        self.assertIn("... and 10 more", text)

    def test_a_pack_named_like_a_shipped_pack_replaces_it_and_any_other_name_is_added(self):
        self.basic()
        d = json.loads(self.cli("--rules", self.pack(EMPTY_PACK, "generic.py"), "--transcripts", str(self.tr), "--json").stdout)
        self.assertEqual([(c["id"], c["baseline"], c["candidate"]) for c in d["changed"]], [("t_nv", "deny", "pass")])
        self.assertEqual(d["changed"][0]["guards"], ["no-verify"])
        d = json.loads(self.cli("--rules", self.pack(EMPTY_PACK, "extra.py"), "--transcripts", str(self.tr), "--json").stdout)
        self.assertEqual((d["changed"], d["candidate"]), ([], "extra.py adds"))

    def test_the_real_corporate_pack_as_candidate_changes_nothing(self):
        self.basic()
        d = json.loads(self.cli("--rules", str(CORPORATE), "--transcripts", str(self.tr), "--json").stdout)
        self.assertEqual(d["changed"], [])

    def test_strict_fails_only_when_something_got_looser(self):
        self.basic()
        args = ("--transcripts", str(self.tr), "--strict")
        self.assertEqual(self.cli("--rules", self.pack(EMPTY_PACK, "generic.py"), *args).returncode, 1)
        self.assertEqual(self.cli("--rules", self.pack(ASK_PACK), *args).returncode, 0)

    # ── it never touches the live guard log ──
    def test_the_live_guard_log_and_home_are_unchanged(self):
        self.basic()
        before = self.snapshot()
        for env in ({}, {"GUARDS_LOG_DIR": str(self.live)}):      # unset, and set to the live folder by the caller
            r = self.cli("--rules", self.pack(ASK_PACK), "--transcripts", str(self.tr), env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self.snapshot(), before, f"the replay wrote under the Claude home (env {env})")
        self.assertEqual((self.live / "guards.log").read_text(encoding="utf-8"), "earlier line\n")

    def test_its_temporary_log_folder_is_removed(self):
        self.basic()
        for rules in (self.pack(ASK_PACK), str(self.tmp / "missing.py"), self.pack("raise RuntimeError('boom')\n", "boom.py")):
            self.cli("--rules", rules, "--transcripts", str(self.tr))
        self.assertEqual(list(self.scratch.iterdir()), [])

    # ── input handling ──
    def test_ids_are_counted_once_and_bad_lines_are_skipped(self):
        self.transcript(line("dup", "Bash", {"command": "echo a"}), line("dup", "Bash", {"command": "echo a"}), "not json {",
                        json.dumps({"message": {"content": "plain text"}}), json.dumps([1, 2]),
                        line("t_bad_input", "Bash", {"command": "echo b"}).replace('"input": {"command": "echo b"}', '"input": "x"'),
                        line("bad id with spaces", "Bash", {"command": "echo c"}), line("ok", "Read", {"file_path": "notes.txt"}))
        d = json.loads(self.cli("--rules", self.pack(EMPTY_PACK, "extra.py"), "--transcripts", str(self.tr), "--json").stdout)
        self.assertEqual(d["calls"], 3)

    def test_max_calls_caps_the_replay_and_says_so(self):
        self.transcript(*[line(f"t{i}", "Bash", {"command": "echo hi"}) for i in range(20)])
        d = json.loads(self.cli("--rules", self.pack(EMPTY_PACK, "extra.py"), "--transcripts", str(self.tr), "--max-calls", "5", "--json").stdout)
        self.assertEqual((d["calls"], d["capped"]), (5, True))

    def test_unusable_input_is_exit_2_with_one_plain_message(self):
        self.basic()
        empty = self.tmp / "empty"
        empty.mkdir()
        bad = [("--rules", str(self.tmp / "nope.py"), "--transcripts", str(self.tr)),
               ("--rules", self.pack("x = 1\n", "not-an-identifier.py"), "--transcripts", str(self.tr)),
               ("--rules", self.pack("def (:\n", "broken.py"), "--transcripts", str(self.tr)),
               ("--rules", self.pack("raise RuntimeError('boom')\n", "boom.py"), "--transcripts", str(self.tr)),
               ("--rules", self.pack(EMPTY_PACK), "--transcripts", str(self.tmp / "no-such-folder")),
               ("--rules", self.pack(EMPTY_PACK), "--transcripts", str(empty))]
        for args in bad:
            r = self.cli(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertNotIn("Traceback", r.stderr)
            self.assertNotIn(SENTINEL, r.stdout + r.stderr)
        self.assertEqual(self.cli().returncode, 2)               # --rules is required

    def test_default_transcripts_folder_is_under_the_claude_home(self):
        proj = self.home / "projects" / "p1"
        proj.mkdir(parents=True)
        (proj / "a.jsonl").write_text(line("t1", "Bash", {"command": "echo hi"}) + "\n", encoding="utf-8")
        d = json.loads(self.cli("--rules", self.pack(EMPTY_PACK, "extra.py"), "--json").stdout)
        self.assertEqual(d["calls"], 1)

    def test_self_test_is_one_offline_line(self):
        r = self.cli("--self-test")
        self.assertEqual((r.returncode, len(r.stdout.strip().splitlines())), (0, 1), r.stderr)
        self.assertEqual(r.stdout.strip(), "guard_replay self-test ok")


if __name__ == "__main__":
    unittest.main()
