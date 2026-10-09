"""skill-bench tests: offline, mock model plus a stub `claude` for the real runner path.
Run: WB_REQUIRE_ALL=1 py -3 -m unittest discover -s tools/skill-bench -v"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import runner_claude  # noqa: E402
import skill_bench as sb  # noqa: E402

STUB = r'''
import json, os, sys
a = sys.argv[1:]
prompt = sys.stdin.read()
system = a[a.index("--append-system-prompt") + 1]
cfg = os.environ.get("CLAUDE_CONFIG_DIR")
with open(os.environ["STUB_DUMP"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": a, "cwd_files": os.listdir("."), "cfg": cfg,
                        "cfg_files": os.listdir(cfg) if cfg and os.path.isdir(cfg) else None,
                        "api_key": os.environ.get("ANTHROPIC_API_KEY"), "nested": os.environ.get("CLAUDECODE"),
                        "prompt": prompt}) + "\n")
mode = os.environ.get("STUB_MODE", "ok")
if mode == "limit":
    print(json.dumps({"type": "result", "is_error": True, "result": "Claude usage limit reached"}))
    sys.exit(1)
text = "The three smallest primes greater than 20 are 23, 29 and 31. Their sum is 83."
if mode != "drop" and "[bench:" in system:
    text += "\n" + system[system.index("[bench:"):].split("]")[0] + "]"
u = {"input_tokens": 10, "output_tokens": 20, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 5}
if mode == "events":
    ev = [{"type": "assistant", "message": {"id": "m1", "usage": u}}, {"type": "assistant", "message": {"id": "m1", "usage": u}},
          {"type": "result", "is_error": False, "result": text, "total_cost_usd": 0.001, "duration_ms": 9}]
    print(json.dumps(ev))
else:
    print(json.dumps({"type": "result", "is_error": False, "result": text, "usage": u, "total_cost_usd": 0.001, "duration_ms": 9}))
'''


def cli(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = sb.main([str(a) for a in args])
    return rc, buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sb-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.packs = self.tmp / "packs"
        shutil.copytree(HERE / "packs", self.packs)

    def run_mock(self, out, arms="baseline,terse", reps=6, spec=None, pack="smoke"):
        env = {"WB_MOCK": json.dumps(spec or {})}
        with mock.patch.dict(os.environ, env):
            return cli("run", "--runner", "mock", "--model", "m", "--arms", arms, "--pack", pack, "--reps", reps,
                       "--out", out, "--packs-dir", self.packs)

    def score(self, out, *extra):
        return cli("score", "--out", out, "--packs-dir", self.packs, *extra)


class MockEndToEnd(Base):
    def test_pack_controls_good_passes_bad_fails(self):
        rc, out = cli("selftest", "--pack", "smoke")
        self.assertEqual(rc, 0, out)

    def test_run_then_score_reports_n_mean_ci_mde_and_arm_applied(self):
        out = self.tmp / "o"
        rc, _ = self.run_mock(out, spec={"scale": {"terse": 0.5}})
        self.assertEqual(rc, 0)
        rc, text = self.score(out)
        self.assertEqual(rc, 0, text)
        res = json.loads((out / "score.json").read_text("utf-8"))
        self.assertEqual(res["criteria_sha256"], sb.criteria_sha256(self.packs / "smoke"))
        self.assertEqual(res["arms"]["baseline"]["n"], 6)
        self.assertEqual(len(res["runs"]), 12)
        self.assertTrue(all(r["arm_applied"] for r in res["runs"]))
        s = res["paired"]["terse"]["metrics"]["output_tokens"]
        self.assertEqual(s["n"], 6)
        self.assertIsNotNone(s["mde"])
        self.assertEqual(len(s["ci95"]), 2)
        self.assertEqual(s["verdict"], "DETECTED")
        self.assertLess(s["mean"], 0)
        self.assertEqual(res["arms"]["baseline"]["answer_key_pass"], {"pass": 6, "of": 6})

    def test_below_mde_prints_untested_never_no_effect(self):
        out = self.tmp / "o"
        self.run_mock(out, reps=2)                       # no scale: the arm does nothing
        rc, text = self.score(out)
        self.assertEqual(rc, 0)
        line = next(x for x in text.splitlines() if x.lstrip().startswith("output_tokens") and "diff" in x)
        self.assertIn("UNTESTED", line)
        self.assertIn("MDE", line)
        self.assertNotIn("no effect", text.lower())
        out1 = self.tmp / "o1"
        self.run_mock(out1, reps=1)
        self.assertIn("UNTESTED: fewer than 2 pairs", self.score(out1)[1])

    def test_no_model_ranking_and_one_dir_one_model(self):
        out = self.tmp / "o"
        self.run_mock(out, reps=1)
        rc, text = self.score(out)
        self.assertIn("no model quality ranking", text)
        with mock.patch.dict(os.environ, {"WB_MOCK": "{}"}):
            rc, msg = cli("run", "--runner", "mock", "--model", "other", "--arms", "baseline,terse", "--pack", "smoke",
                          "--out", out, "--packs-dir", self.packs)
        self.assertEqual(rc, 2, msg)

    def test_resume_skips_finished_runs_and_usage_limit_stops(self):
        out = self.tmp / "o"
        rc, msg = self.run_mock(out, reps=5, spec={"limit_after": 3})
        self.assertEqual(rc, 4, msg)
        self.assertEqual(len(list((out / "runs").glob("*/*.json"))), 3)
        rc, msg = self.run_mock(out, reps=5)
        self.assertEqual((rc, "new=7" in msg), (0, True), msg)

    def test_negative_flips_are_counted(self):
        out = self.tmp / "o"
        self.run_mock(out, reps=3, spec={"bad": ["terse"]})
        self.score(out)
        p = json.loads((out / "score.json").read_text("utf-8"))["paired"]["terse"]
        self.assertEqual((p["broke"], p["fixed"]), (3, 0))


class Integrity(Base):
    def tamper(self):
        f = self.packs / "smoke" / "criteria.md"
        f.write_text(f.read_text("utf-8") + "\nA late edit.\n", encoding="utf-8", newline="\n")

    def test_changed_criteria_aborts_scoring(self):
        out = self.tmp / "o"
        self.run_mock(out, reps=2)
        self.tamper()
        rc, text = self.score(out)
        self.assertEqual(rc, 3, text)
        self.assertIn("ABORT", text)
        self.assertFalse((out / "score.json").exists())

    def test_changed_answer_key_aborts_scoring(self):
        out = self.tmp / "o"
        self.run_mock(out, reps=2)
        k = self.packs / "smoke" / "keys.json"
        k.write_text(k.read_text("utf-8").replace("83", "84"), encoding="utf-8", newline="\n")
        self.assertEqual(self.score(out)[0], 3)

    def test_the_hash_check_is_what_stops_a_tampered_file(self):
        """Test the test: with the check disabled the tampered pack scores, so the abort test above is load-bearing."""
        out = self.tmp / "o"
        self.run_mock(out, reps=2)
        self.tamper()
        with mock.patch.object(sb, "check_criteria", lambda meta, pack: None):
            self.assertEqual(self.score(out)[0], 0)

    def test_line_endings_do_not_change_the_hash(self):
        a = sb.criteria_sha256(self.packs / "smoke")
        f = self.packs / "smoke" / "criteria.md"
        f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(sb.criteria_sha256(self.packs / "smoke"), a)

    def test_silently_unapplied_arm_is_detected_excluded_and_counted(self):
        out = self.tmp / "o"
        self.run_mock(out, reps=4, spec={"drop": ["terse"]})
        rc, text = self.score(out)
        self.assertEqual(rc, 0, text)
        res = json.loads((out / "score.json").read_text("utf-8"))
        self.assertEqual(res["excluded_no_proof"], {"baseline": 0, "terse": 4})
        self.assertEqual(res["arms"]["terse"]["n"], 0)
        self.assertEqual(res["arms"]["baseline"]["n"], 4)
        self.assertEqual([r["arm_applied"] for r in res["runs"] if r["arm"] == "terse"], [False] * 4)
        self.assertNotIn("terse", res["paired"])
        self.assertIn("NO PROVEN RUNS", text)
        self.assertIn("paired terse vs baseline: UNTESTED", text)

    def test_a_wrong_trailer_code_is_not_proof(self):
        ok, _ = sb.split_trailer("answer\n[bench:aaaaaaaaaa]", "bbbbbbbbbb")
        self.assertFalse(ok)
        ok, ans = sb.split_trailer("answer\n`[bench:aaaaaaaaaa]`\n", "aaaaaaaaaa")
        self.assertEqual((ok, ans), (True, "answer"))

    def test_arm_names_cannot_escape_the_arms_dir(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            sb.load_arms(["../x"], HERE / "arms")

    def test_a_broken_key_stops_the_run(self):
        k = self.packs / "smoke" / "keys.json"
        k.write_text(k.read_text("utf-8").replace("Their sum is 83.", "Nothing."), encoding="utf-8", newline="\n")
        rc, msg = self.run_mock(self.tmp / "o", reps=1)
        self.assertEqual(rc, 2, msg)


class Stats(unittest.TestCase):
    def test_interval_and_mde_on_known_values(self):
        s = sb.summarize([1, 2, 3, 4, 5])
        self.assertAlmostEqual(s["mean"], 3)
        se = (2.5 / 5) ** 0.5
        self.assertAlmostEqual(s["ci95"][1] - 3, 2.776 * se, places=3)
        self.assertAlmostEqual(s["mde"], (2.776 + 0.941) * se, places=3)
        self.assertEqual(s["verdict"], "DETECTED")

    def test_a_wide_interval_is_untested(self):
        self.assertEqual(sb.summarize([-5, 6, -4, 7])["verdict"], "UNTESTED")
        self.assertEqual(sb.summarize([3])["verdict"], "UNTESTED")
        self.assertIsNone(sb.summarize([3])["ci95"])

    def test_quantile_tables_hold_the_textbook_values(self):
        self.assertEqual((sb.t975(1), sb.t975(10), sb.t975(30), sb.t975(500)), (12.706, 2.228, 2.042, 1.96))
        self.assertEqual((sb.t80(1), sb.t80(10), sb.t80(30), sb.t80(500)), (1.376, 0.879, 0.854, 0.842))


class ClaudeRunner(Base):
    """The real runner path against a stub `claude`: flags, env, config dir, login copy, proof, usage, limits."""

    def setUp(self):
        super().setUp()
        self.stub = self.tmp / "stub.py"
        self.stub.write_text(STUB, encoding="utf-8", newline="\n")
        self.dump = self.tmp / "dump.jsonl"
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.env = {"SKILL_BENCH_CLAUDE": json.dumps([sys.executable, str(self.stub)]), "STUB_DUMP": str(self.dump),
                    "CLAUDE_CONFIG_DIR": str(self.home), "ANTHROPIC_API_KEY": "dummy-not-a-key", "CLAUDECODE": "1",
                    "STUB_MODE": "ok"}

    def run_claude(self, out, mode="ok", reps=1, arms="baseline", extra=(), token=None):
        with mock.patch.dict(os.environ, {**self.env, "STUB_MODE": mode}):
            os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
            if token:
                os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
            return cli("run", "--runner", "claude", "--model", "model-x", "--arms", arms, "--pack", "smoke",
                       "--reps", reps, "--out", out, "--packs-dir", self.packs, *extra)

    def dumped(self):
        return json.loads(self.dump.read_text("utf-8").splitlines()[0])

    def test_flags_env_cwd_and_the_users_own_config_dir(self):
        rc, msg = self.run_claude(self.tmp / "o")
        self.assertEqual(rc, 0, msg)
        d = self.dumped()
        a = d["argv"]
        for flag in ("-p", "--safe-mode", "--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(flag, a)
        self.assertEqual(a[a.index("--tools") + 1], "")
        self.assertEqual(a[a.index("--output-format") + 1], "json")
        self.assertEqual(a[a.index("--setting-sources") + 1], "project,local")
        self.assertEqual(a[a.index("--model") + 1], "model-x")
        self.assertNotIn("smallest prime", " ".join(a))        # the task goes on stdin
        self.assertIn("smallest prime", d["prompt"])
        self.assertEqual(d["cwd_files"], [])                    # empty temp cwd
        self.assertEqual(d["cfg"], str(self.home), "no setup token: the config dir is the user's own, untouched")
        self.assertEqual(list(self.home.iterdir()), [], "nothing was written to the user's config dir")
        self.assertIsNone(d["api_key"])
        self.assertIsNone(d["nested"])

    def test_a_setup_token_gets_an_empty_throwaway_config_dir(self):
        self.run_claude(self.tmp / "o", token="dummy-setup-token")
        d = self.dumped()
        self.assertNotEqual(Path(d["cfg"]).resolve(), self.home.resolve())
        self.assertEqual(d["cfg_files"], [])
        self.assertFalse(Path(d["cfg"]).exists(), "the throwaway dir is removed at the end")
        self.assertEqual(list(self.home.iterdir()), [])

    def test_keep_api_key_keeps_it(self):
        self.run_claude(self.tmp / "o", extra=("--keep-api-key",))
        self.assertEqual(self.dumped()["api_key"], "dummy-not-a-key")

    def test_end_to_end_records_usage_cost_and_arm_applied(self):
        out = self.tmp / "o"
        self.assertEqual(self.run_claude(out, arms="baseline,terse", reps=2)[0], 0)
        rec = json.loads(next((out / "runs" / "baseline").glob("*.json")).read_text("utf-8"))
        self.assertTrue(rec["arm_applied"])
        self.assertEqual(rec["usage"]["output_tokens"], 20)
        self.assertEqual(rec["cost_usd"], 0.001)
        rc, text = self.score(out)
        self.assertEqual(rc, 0, text)
        self.assertIn("answer-key control 2/2", text)

    def test_a_dropped_arm_text_is_excluded(self):
        out = self.tmp / "o"
        self.run_claude(out, mode="drop", arms="baseline,terse")
        res = json.loads(self.score(out, "--json")[1])
        self.assertEqual(res["excluded_no_proof"], {"baseline": 1, "terse": 1})

    def test_usage_limit_stops_the_run(self):
        rc, msg = self.run_claude(self.tmp / "o", mode="limit", reps=3, arms="baseline,terse")
        self.assertEqual(rc, 4, msg)
        self.assertEqual(len(self.dump.read_text("utf-8").splitlines()), 1, "no call after the limit")

    def test_usage_counts_once_per_message_id(self):
        out = self.tmp / "o"
        self.run_claude(out, mode="events")
        rec = json.loads(next((out / "runs" / "baseline").glob("*.json")).read_text("utf-8"))
        self.assertEqual(rec["usage"]["output_tokens"], 20)
        self.assertEqual(rec["usage"]["cache_read_input_tokens"], 5)

    def test_parse_dict_and_events(self):
        u = {"input_tokens": 1, "output_tokens": 2}
        self.assertEqual(runner_claude.parse(json.dumps({"result": "r", "usage": u}))["usage"]["output_tokens"], 2)
        ev = [{"type": "assistant", "message": {"id": "a", "usage": u}}, {"type": "assistant", "message": {"id": "a", "usage": u}},
              {"type": "assistant", "message": {"id": "b", "usage": u}}, {"type": "result", "result": "r"}]
        self.assertEqual(runner_claude.parse(json.dumps(ev))["usage"]["output_tokens"], 4)


class NoLoginFiles(unittest.TestCase):
    """The kit never reads, copies or writes a login file: no file under tools/skill-bench names one. The needles are
    assembled at runtime so this file passes its own scan."""
    NEEDLES = ("cred" + "entials", "." + "claude.json", "key" + "chain")

    def test_no_file_under_skill_bench_names_a_login_file(self):
        files = [p for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        self.assertGreater(len(files), 8)
        for p in files:
            text = p.read_text("utf-8", errors="replace").lower()
            for n in self.NEEDLES:
                self.assertNotIn(n, text, f"{p.relative_to(HERE)} mentions {n!r}")

    def test_the_runner_makes_no_file_calls_besides_its_own_temp_dir(self):
        src = (HERE / "runner_claude.py").read_text("utf-8")
        for bad in ("copy2", "copyfile", "copy(", "open(", "read_bytes", "read_text", "write_text", "write_bytes"):
            self.assertNotIn(bad, src, f"runner_claude.py uses {bad}")


if __name__ == "__main__":
    unittest.main()
