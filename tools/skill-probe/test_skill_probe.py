"""Tests for skill_probe.py: fictional transcripts and skills written at test time, no network. Run:
    python -m unittest discover -s tools/skill-probe"""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: nothing here skips

import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
TOOL = HERE / "skill_probe.py"
sys.path.insert(0, str(HERE))
import skill_probe as sp  # noqa: E402

SECRET = "SENTINEL-PROMPT-TEXT"             # must never appear in anything the tool prints


def user(uid, text, **kw):
    return json.dumps({"type": "user", "uuid": uid, "message": {"role": "user", "content": text}, **kw})


def blocks(uid, *texts):
    return json.dumps({"type": "user", "uuid": uid, "message": {"role": "user", "content": [{"type": "text", "text": t} for t in texts]}})


def tool_result(uid):
    return json.dumps({"type": "user", "uuid": uid, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "x", "content": "draw a flowchart"}]}})


def call(name, inp, **kw):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"},
                                                                     {"type": "tool_use", "id": "t1", "name": name, "input": inp}]}, **kw})


SPEC = {"skills": {"chart": {"should": ["draw a flowchart", r"\bdiagram\b"], "should_not": ["what is a flowchart"]}}}


class Probe(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-probe-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tr = self.tmp / "tr" / "proj"
        self.tr.mkdir(parents=True)

    def transcript(self, *lines, name="s.jsonl", age=0):
        """Write a transcript; age (seconds) sets how old it looks, since the newest file is read first."""
        p = self.tr / name
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        t = time.time() - age
        os.utime(p, (t, t))

    def spec(self, d=SPEC):
        p = self.tmp / "p.json"
        p.write_text(json.dumps(d), encoding="utf-8")
        return p

    def result(self, d=SPEC):
        return sp.probe(sp.load_spec(self.spec(d)), sp.read_prompts(self.tmp / "tr"))

    def cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(TOOL), *args], capture_output=True, text=True, encoding="utf-8", timeout=60,
                              env={**os.environ, "CLAUDE_CONFIG_DIR": str(self.tmp / "claude"), "PYTHONIOENCODING": "utf-8"})

    # ── what counts ──
    def test_counts_should_and_should_not_prompts_that_led_to_a_skill_call(self):
        self.transcript(user("u1", "please draw a flowchart of login"), call("Skill", {"skill": "chart"}),
                        user("u2", "a diagram of billing, please"), call("Skill", {"skill": "other"}),
                        user("u3", "draw a flowchart of search"), call("Skill", {"skill": "chart", "args": "x"}),
                        user("u4", "what is a flowchart?"), call("Skill", {"skill": "chart"}),
                        user("u5", "what is a flowchart for"), call("Bash", {"command": "echo"}))
        r = self.result()["chart"]
        self.assertEqual((r["should"]["prompts"], r["should"]["fired"], r["should"]["rate"], r["should"]["ids"]), (3, 2, 0.667, ["u2"]))
        self.assertEqual((r["should_not"]["prompts"], r["should_not"]["fired"], r["should_not"]["ids"]), (2, 1, ["u4"]))

    def test_only_a_skill_tool_use_counts(self):
        self.transcript(user("u1", "draw a flowchart"), call("Read", {"file_path": "skills/chart/SKILL.md"}),
                        call("Bash", {"command": "cat skills/chart/SKILL.md", "skill": "chart"}),
                        call("Task", {"description": "use the chart skill", "skill": "chart", "prompt": "chart"}),
                        call("skill", {"skill": "chart"}), call("SkillList", {"skill": "chart"}),
                        call("Skill", {"name": "chart"}), call("Skill", "chart"),
                        json.dumps({"type": "assistant", "message": {"content": [      # one line, so the cheap pre-filter passes it
                            {"type": "tool_use", "id": "a", "name": "Skill", "input": {"args": "x"}},
                            {"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": "x", "skill": "chart"}},
                            {"type": "tool_use", "id": "c", "name": "Task", "input": {"skill": "chart"}}]}}),
                        user("u2", "draw a flowchart again"), call("mcp__x__Skill", {"skill": "chart"}))
        r = self.result()["chart"]["should"]
        self.assertEqual((r["prompts"], r["fired"]), (2, 0))

    def test_a_skill_call_belongs_to_the_prompt_before_it_only(self):
        self.transcript(user("u1", "draw a flowchart"), call("Read", {"file_path": "a"}), user("u2", "draw a flowchart"),
                        call("Skill", {"skill": "chart"}), tool_result("r1"), call("Read", {"file_path": "b"}), user("u3", "draw a flowchart"))
        r = self.result()["chart"]["should"]
        self.assertEqual((r["prompts"], r["fired"], r["ids"]), (3, 1, ["u1", "u3"]))

    def test_a_skill_call_before_the_first_prompt_and_in_other_files_is_not_counted(self):
        self.transcript(call("Skill", {"skill": "chart"}), user("u1", "draw a flowchart"), name="a.jsonl", age=0)
        self.transcript(call("Skill", {"skill": "chart"}), name="b.jsonl", age=100)         # read after a.jsonl
        self.assertEqual(self.result()["chart"]["should"]["fired"], 0)

    def test_plugin_qualified_names_count_for_the_bare_name_and_the_reverse(self):
        self.transcript(user("u1", "draw a flowchart"), call("Skill", {"skill": "some-plugin:chart"}))
        self.assertEqual(self.result()["chart"]["should"]["fired"], 1)
        self.assertEqual(self.result({"skills": {"some-plugin:chart": SPEC["skills"]["chart"]}})["some-plugin:chart"]["should"]["fired"], 1)
        self.assertEqual(self.result({"skills": {"cha": SPEC["skills"]["chart"]}})["cha"]["should"]["fired"], 0)     # not a suffix match

    def test_what_is_not_a_prompt(self):
        self.transcript(user("u1", "draw a flowchart", isMeta=True), user("u2", "draw a flowchart", isSidechain=True),
                        user("u3", "<command-name>/chart</command-name> draw a flowchart"), user("u4", "<system-reminder>draw a flowchart</system-reminder>"),
                        tool_result("u5"), user("u6", "   "), blocks("u7", "draw", "a flowchart"), user("u8", "DRAW A FLOWCHART"),
                        "not json", json.dumps([1]), json.dumps({"type": "user", "message": "x"}))
        r = self.result()["chart"]["should"]
        self.assertEqual((r["prompts"], r["ids"]), (1, ["u8"]))            # the blocks prompt joins "draw" and "a flowchart" with a newline

    def test_sidechain_skill_calls_do_not_count_for_the_main_prompt(self):
        self.transcript(user("u1", "draw a flowchart"), call("Skill", {"skill": "chart"}, isSidechain=True))
        self.assertEqual(self.result()["chart"]["should"]["fired"], 0)

    # ── verdicts ──
    def test_verdicts_need_five_prompts_and_use_the_floor_and_ceiling(self):
        def lines(n_fired, n_total, phrase, start):
            out = []
            for i in range(n_total):
                out += [user(f"{phrase[:1]}{start + i}", phrase), call("Skill", {"skill": "chart"}) if i < n_fired else call("Read", {"file_path": "a"})]
            return out
        spec = {"skills": {"chart": {"should": ["draw a flowchart"], "should_not": ["what is a flowchart"]}}}
        self.transcript(*lines(4, 4, "draw a flowchart", 0))
        self.assertEqual(self.result(spec)["chart"]["verdict"], "too few matching prompts to judge")
        self.transcript(*lines(4, 5, "draw a flowchart", 0), *lines(1, 5, "what is a flowchart", 0))
        self.assertEqual(self.result(spec)["chart"]["verdict"], "ok")
        self.transcript(*lines(3, 5, "draw a flowchart", 0), *lines(2, 5, "what is a flowchart", 0))
        v = self.result(spec)["chart"]["verdict"]
        self.assertIn("reword the description", v)
        self.assertIn("narrow the description", v)

    def test_a_skill_with_no_matching_prompts_has_no_rate(self):
        self.transcript(user("u1", "hello"))
        r = self.result()["chart"]
        self.assertEqual((r["should"]["prompts"], r["should"]["rate"]), (0, None))

    # ── the command line ──
    def test_the_report_never_prints_prompt_text(self):
        self.transcript(user("u1", f"draw a flowchart {SECRET}"), call("Read", {"file_path": f"{SECRET}.txt"}),
                        user("u2", f"what is a flowchart {SECRET}"), call("Skill", {"skill": "chart"}))
        r = self.cli("--spec", str(self.spec()), "--transcripts", str(self.tmp / "tr"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(SECRET, r.stdout + r.stderr)
        self.assertIn("missed ids: u1", r.stdout)
        self.assertIn("fired-on ids: u2", r.stdout)
        j = json.loads(self.cli("--spec", str(self.spec()), "--transcripts", str(self.tmp / "tr"), "--json").stdout)
        self.assertEqual((j["prompts"], j["skills"]["chart"]["should"]["prompts"]), (2, 1))
        self.assertNotIn(SECRET, json.dumps(j))

    def test_unusable_input_is_exit_2(self):
        self.transcript(user("u1", "x"))
        bad = ["not json", "{}", '{"skills": {}}', '{"skills": {"a": 1}}', '{"skills": {"a": {"should": "x"}}}',
               '{"skills": {"a": {"should": ["("]}}}', '{"skills": {"a": {}}}']
        for text in bad:
            p = self.tmp / "bad.json"
            p.write_text(text, encoding="utf-8")
            r = self.cli("--spec", str(p), "--transcripts", str(self.tmp / "tr"))
            self.assertEqual(r.returncode, 2, text)
            self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(self.cli("--spec", str(self.tmp / "missing.json"), "--transcripts", str(self.tmp / "tr")).returncode, 2)
        self.assertEqual(self.cli("--spec", str(self.spec()), "--transcripts", str(self.tmp / "none")).returncode, 2)
        (self.tmp / "empty").mkdir()
        self.assertEqual(self.cli("--spec", str(self.spec()), "--transcripts", str(self.tmp / "empty")).returncode, 2)
        self.assertEqual(self.cli().returncode, 2)

    def test_default_transcripts_folder_is_under_the_claude_home(self):
        proj = self.tmp / "claude" / "projects" / "p"
        proj.mkdir(parents=True)
        (proj / "a.jsonl").write_text(user("u1", "draw a flowchart") + "\n", encoding="utf-8")
        self.assertEqual(json.loads(self.cli("--spec", str(self.spec()), "--json").stdout)["prompts"], 1)

    def test_self_test_is_one_offline_line(self):
        r = self.cli("--self-test")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "skill_probe self-test ok"), r.stderr)


if __name__ == "__main__":
    unittest.main()
