"""Tests for token_split.py: fictional model ids and prices, fake transcripts in a temp folder, no network."""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: nothing here skips

import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import token_split as ts  # noqa: E402

KIT = HERE.parents[1]
SENTINEL = "SENTINEL-" + "q" * 16
# input, output, cache write (5 minutes), cache read: USD per million tokens, chosen so every product is exact
PRICES = {"claude-test-1": {"input": 1.0, "output": 10.0, "cache_write": 2.0, "cache_read": 0.1, "long_context": None,
                            "evidence": "E32", "as_of": "2026-10"},
          "claude-tier-1": {"input": 1.0, "output": 10.0, "cache_write": 2.0, "cache_read": 0.1, "evidence": "E32",
                            "as_of": "2026-10", "long_context": {"over_tokens": 1_000_000, "input": 5.0, "output": 50.0,
                                                                  "cache_write": 10.0, "cache_read": 0.5}}}


def msg(mid, model, usage, content=()):
    return json.dumps({"type": "assistant", "cwd": SENTINEL, "message": {"id": mid, "model": model, "usage": usage,
                                                                          "content": list(content)}})


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.proj = self.tmp / f"projects-{SENTINEL}" / "p"
        self.proj.mkdir(parents=True)
        self.prices_file = self.tmp / "evidence.json"
        self.prices_file.write_text(json.dumps({"prices": PRICES}), encoding="utf-8")
        self.addCleanup(self._t.cleanup)

    def put(self, lines, name="s.jsonl"):
        (self.proj / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_cli(self, *args):
        r = subprocess.run([sys.executable, "-I", str(HERE / "token_split.py"), "--projects", str(self.proj.parent),
                            "--prices", str(self.prices_file), *args], capture_output=True, text=True)
        return r

    def report(self, **kw):
        return ts.report(self.proj.parent, kw.get("days", 1), ts.load_prices(self.prices_file))


class Money(Base):
    def test_usage_is_the_max_per_message_id_not_the_sum(self):
        self.put([msg("a", "claude-test-1", {"input_tokens": 1_000_000, "output_tokens": 4_000_000}),
                  msg("a", "claude-test-1", {"input_tokens": 1_000_000, "output_tokens": 10_000_000})])
        self.assertEqual(self.report()["api_equivalent_usd"], 1 * 1.0 + 10 * 10.0)

    def test_the_same_id_in_two_files_counts_once(self):
        line = msg("a", "claude-test-1", {"input_tokens": 1_000_000})
        self.put([line], "one.jsonl")
        self.put([line], "two.jsonl")
        self.assertEqual(self.report()["messages"], 1)
        self.assertEqual(self.report()["api_equivalent_usd"], 1.0)

    def test_cache_classes_use_the_table(self):
        u = {"input_tokens": 0, "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000,
             "cache_creation": {"ephemeral_1h_input_tokens": 400_000}}
        self.put([msg("a", "claude-test-1", u)])
        r = self.report()
        self.assertAlmostEqual(r["by_model"]["claude-test-1"]["cache_read"], 0.1)
        # 600K five-minute writes at 2.0 plus 400K one-hour writes at twice the input price (1.0 * 2)
        self.assertAlmostEqual(r["by_model"]["claude-test-1"]["cache_write"], 0.6 * 2.0 + 0.4 * 2.0)

    def test_long_prompt_tier_is_per_message_and_strictly_over(self):
        at = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
        over = {"input_tokens": 1_000_001, "output_tokens": 1_000_000}
        self.put([msg("a", "claude-tier-1", at)])
        self.assertAlmostEqual(self.report()["api_equivalent_usd"], 1.0 + 10.0, places=3)
        self.put([msg("a", "claude-tier-1", over)])
        self.assertAlmostEqual(self.report()["api_equivalent_usd"], 5.0 + 50.0, places=3)
        self.put([msg("a", "claude-tier-1", at), msg("b", "claude-tier-1", over)])
        self.assertAlmostEqual(self.report()["api_equivalent_usd"], 11.0 + 55.0, places=3)

    def test_prices_come_from_the_file_given(self):
        self.put([msg("a", "claude-test-1", {"input_tokens": 1_000_000})])
        first = json.loads(self.run_cli("--json").stdout)["api_equivalent_usd"]
        doubled = json.loads(json.dumps({"prices": PRICES}))
        doubled["prices"]["claude-test-1"]["input"] = 7.0
        self.prices_file.write_text(json.dumps(doubled), encoding="utf-8")
        self.assertEqual((first, json.loads(self.run_cli("--json").stdout)["api_equivalent_usd"]), (1.0, 7.0))

    def test_an_unlisted_model_is_named_not_priced(self):
        self.put([msg("a", "claude-other-9", {"input_tokens": 1_000_000}), msg("b", "claude-test-1", {"input_tokens": 1_000_000})])
        r = self.report()
        self.assertEqual((r["priced_messages"], r["unpriced_messages"], r["api_equivalent_usd"]),
                         (1, {"claude-other-9": 1}, 1.0))

    def test_model_strings_with_a_suffix_match_but_a_longer_number_does_not(self):
        self.put([msg("a", "claude-test-1[1m]", {"input_tokens": 1_000_000}),
                  msg("b", "claude-test-1-20261007", {"input_tokens": 1_000_000}),
                  msg("c", "claude-test-10", {"input_tokens": 1_000_000})])
        r = self.report()
        self.assertEqual((r["priced_messages"], r["unpriced_messages"]), (2, {"claude-test-10": 1}))


class Split(Base):
    def test_visible_output_splits_by_character_share(self):
        tool_input = {"k": "z" * 20}
        text = "t" * 30
        n_tool = len(json.dumps(tool_input))
        self.put([msg("a", "claude-test-1", {"output_tokens": 1_000_000}, [{"type": "text", "text": text}]),
                  msg("a", "claude-test-1", {"output_tokens": 1_000_000}, [{"type": "tool_use", "id": "x", "input": tool_input}])])
        s = self.report()["share"]
        self.assertAlmostEqual(s["output_prose"], 30 / (30 + n_tool), places=3)
        self.assertAlmostEqual(s["output_tool_args"], n_tool / (30 + n_tool), places=3)

    def test_a_repeated_block_is_counted_once(self):
        block = {"type": "text", "text": "t" * 30}
        tool = {"type": "tool_use", "id": "x", "input": {"k": "v"}}
        u = {"output_tokens": 1_000_000}
        self.put([msg("a", "claude-test-1", u, [block]), msg("a", "claude-test-1", u, [block]),
                  msg("a", "claude-test-1", u, [tool])])
        s = self.report()["share"]
        self.assertAlmostEqual(s["output_prose"], 30 / (30 + len(json.dumps(tool["input"]))), places=3)

    def test_thinking_tokens_are_used_when_present_and_capped_at_output(self):
        u = {"output_tokens": 1_000_000, "output_tokens_details": {"thinking_tokens": 250_000}}
        self.put([msg("a", "claude-test-1", u, [{"type": "text", "text": "hello"}])])
        r = self.report()
        self.assertTrue(r["thinking_reported"])
        self.assertAlmostEqual(r["by_model"]["claude-test-1"]["output_thinking"], 2.5)
        self.assertAlmostEqual(r["by_model"]["claude-test-1"]["output_prose"], 7.5)
        u["output_tokens_details"]["thinking_tokens"] = 9_000_000
        self.put([msg("a", "claude-test-1", u)])
        self.assertAlmostEqual(self.report()["by_model"]["claude-test-1"]["output_thinking"], 10.0)

    def test_no_thinking_count_is_reported_as_unreported(self):
        self.put([msg("a", "claude-test-1", {"output_tokens": 10})])
        self.assertFalse(self.report()["thinking_reported"])

    def test_output_without_blocks_is_other_not_lost(self):
        self.put([msg("a", "claude-test-1", {"output_tokens": 1_000_000})])
        self.assertAlmostEqual(self.report()["share"]["output_other"], 1.0)


class Privacy(Base):
    def test_no_content_path_or_folder_name_is_printed(self):
        self.put([msg("a", "claude-test-1", {"input_tokens": 5, "output_tokens": 9},
                      [{"type": "text", "text": SENTINEL}, {"type": "tool_use", "id": SENTINEL, "input": {"p": SENTINEL}}])])
        for args in ((), ("--json",)):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn(SENTINEL, r.stdout + r.stderr, args)

    def test_a_malformed_line_and_a_foreign_shape_are_skipped(self):
        self.put(["not json \"usage\"", json.dumps({"message": "usage"}), json.dumps({"message": {"usage": 3, "id": "a"}}),
                  msg("b", "claude-test-1", {"input_tokens": 1_000_000})])
        self.assertEqual(self.report()["messages"], 1)


class Cli(Base):
    def test_files_older_than_the_window_are_ignored(self):
        self.put([msg("a", "claude-test-1", {"input_tokens": 1_000_000})])
        old = time.time() - 40 * 86400
        os.utime(self.proj / "s.jsonl", (old, old))
        self.assertEqual(self.report(days=14)["messages"], 0)
        self.assertEqual(self.report(days=60)["messages"], 1)

    def test_missing_folder_and_bad_prices_fail_loudly(self):
        r = subprocess.run([sys.executable, "-I", str(HERE / "token_split.py"), "--projects", str(self.tmp / "none"),
                            "--prices", str(self.prices_file)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.prices_file.write_text("{}", encoding="utf-8")
        self.put([msg("a", "claude-test-1", {})])
        r = self.run_cli()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no usable", r.stderr)

    def test_self_test_is_one_offline_line_and_exits_zero(self):
        t = time.time()
        r = subprocess.run([sys.executable, "-I", str(HERE / "token_split.py"), "--self-test"], capture_output=True, text=True)
        self.assertEqual((r.returncode, len(r.stdout.strip().splitlines())), (0, 1), r.stderr)
        self.assertLess(time.time() - t, 10)


FAKE_CLAUDE = """
import json, os, sys, time
a = sys.argv[1:]
def hang():
    if os.environ.get("FAKE_PIDFILE"):
        open(os.environ["FAKE_PIDFILE"], "w").write(str(os.getpid()))
    time.sleep(40)
    sys.exit(1)
if a == ["--help"]:
    if os.environ.get("FAKE_MODE") == "hang-help":
        hang()
    print("Options:")
    for f in os.environ.get("FAKE_HELP_FLAGS", "--safe-mode --output-format").split():
        print("  " + f + "   description")
    sys.exit(0)
rec = os.environ["FAKE_RECORD"]
open(rec, "a").write(json.dumps({"argv": a, "stdin": sys.stdin.read(), "cwd": os.getcwd()}) + "\\n")
mode = os.environ.get("FAKE_MODE", "ok")
safe = "--safe-mode" in a
if mode == "hang":
    hang()
if mode == "inverted":
    safe = not safe
if mode == "fail":
    sys.stderr.write("Not logged in\\nsecond line\\n")
    sys.exit(1)
usage = {"input_tokens": 3, "cache_creation_input_tokens": 100 if safe else 40000, "cache_read_input_tokens": 14900 if safe else 0,
         "output_tokens": 5}
reply = {"type": "result", "subtype": "success", "is_error": mode == "iserror", "num_turns": 2 if mode == "two-turns" else 1,
         "result": "REPLY-SENTINEL", "usage": usage}
if mode in ("max-turns", "max-turns-nousage"):
    reply.update(subtype="error_max_turns", is_error=True, num_turns=2)
    del reply["result"]
if mode == "max-turns-nousage":
    del reply["usage"]
if mode == "nousage":
    del reply["usage"]
if mode == "notjson":
    print("not json at all")
elif mode == "list":
    print(json.dumps([{"type": "system"}, reply]))
else:
    print(json.dumps(reply))
if mode.startswith("max-turns"):
    sys.exit(1)
"""


def alive(pid):
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True, text=True).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class Startup(unittest.TestCase):
    """`startup` against a fake claude on PATH (the only claude the child can find): no model call, no sign-in."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.tmp = Path(self._t.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.rec = self.tmp / "rec.jsonl"
        script = self.bin / "fake_claude_impl.py"
        script.write_text(FAKE_CLAUDE, encoding="utf-8")
        if os.name == "nt":
            (self.bin / "claude.cmd").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
        else:
            (self.bin / "claude").write_text(f'#!/bin/sh\n"{sys.executable}" "{script}" "$@"\n', encoding="utf-8")    # no exec: the fake stays a grandchild
            (self.bin / "claude").chmod(0o755)

    def run_cli(self, *args, path=None, **env):
        e = {**os.environ, "PATH": str(self.bin) if path is None else str(path), "FAKE_RECORD": str(self.rec), **env}
        return subprocess.run([sys.executable, "-I", str(HERE / "token_split.py"), "startup", *args], capture_output=True, text=True, env=e,
                              cwd=str(self.tmp), timeout=120)

    def runs(self):
        rows = [json.loads(x) for x in self.rec.read_text().splitlines()] if self.rec.exists() else []
        return rows

    def test_two_runs_differ_only_by_safe_mode_and_use_one_fixed_prompt(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        first, second = self.runs()
        self.assertEqual(second["argv"], first["argv"] + ["--safe-mode"])
        self.assertEqual(first["argv"], ["-p", "--output-format", "json", "--no-session-persistence", "--max-turns", "1"])
        self.assertEqual((first["stdin"], second["stdin"]), (ts.STARTUP_PROMPT, ts.STARTUP_PROMPT))
        self.assertNotIn("@", ts.STARTUP_PROMPT)

    def test_the_table_prints_both_rows_and_the_difference_of_the_whole_prompt(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        # current: 3 + 40,000 + 0 = 40,003; safe mode: 3 + 100 + 14,900 = 15,003; difference 25,000
        self.assertRegex(r.stdout, r"current settings\s+3\s+40,000\s+0\s+40,003")
        self.assertRegex(r.stdout, r"--safe-mode\s+3\s+100\s+14,900\s+15,003")
        self.assertRegex(r.stdout, r"difference\s+25,000")
        self.assertNotIn("REPLY-SENTINEL", r.stdout + r.stderr, "the model's reply is never printed")

    def test_a_warm_cache_does_not_change_the_difference(self):
        j = json.loads(self.run_cli("--json").stdout)
        self.assertEqual(j["difference"], 25_000)
        input_plus_write = lambda row: row["input"] + row["cache_write"]   # noqa: E731
        self.assertNotEqual(input_plus_write(j["current"]) - input_plus_write(j["safe_mode"]), j["difference"],
                            "input plus cache write alone would overstate it: the safe-mode run read its prefix from the cache")
        self.assertEqual(j["current"], {"input": 3, "cache_write": 40_000, "cache_read": 0, "context": 40_003, "turns": 1})

    def test_a_claude_without_safe_mode_gets_one_run_and_exit_2(self):
        r = self.run_cli(FAKE_HELP_FLAGS="--output-format")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(self.runs()), 1)
        self.assertIn("--safe-mode", r.stderr)
        self.assertIn("40,003", r.stdout)
        self.assertNotIn("difference", r.stdout)

    def test_no_claude_on_path_exits_2_with_a_plain_message(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        r = self.run_cli(path=empty)
        self.assertEqual(r.returncode, 2)
        self.assertIn("claude command was not found", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_a_failed_or_unusable_run_stops_with_the_exit_code_and_never_prints_the_reply(self):
        for mode in ("fail", "iserror", "nousage", "notjson"):
            with self.subTest(mode=mode):
                self.rec.unlink(missing_ok=True)
                r = self.run_cli(FAKE_MODE=mode)
                self.assertEqual(r.returncode, 2)
                self.assertIn("no usable usage numbers", r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertNotIn("REPLY-SENTINEL", r.stdout + r.stderr)
                self.assertEqual(len(self.runs()), 1, "a failed first run ends it: no second call")
        self.assertIn("Not logged in", self.run_cli(FAKE_MODE="fail").stderr)

    def test_more_than_one_turn_is_flagged(self):
        r = self.run_cli(FAKE_MODE="two-turns")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("more than one turn", r.stdout)
        self.assertNotIn("more than one turn", self.run_cli().stdout)

    def test_a_list_shaped_result_is_read_too(self):
        r = self.run_cli("--json", FAKE_MODE="list")
        self.assertEqual(json.loads(r.stdout)["difference"], 25_000, r.stderr)

    def test_a_hung_run_is_stopped_with_its_whole_process_tree_and_exits_2_on_time(self):
        """npm installs Claude Code behind a .cmd shim: killing only the shim left the call waiting for the child (41 s for --timeout 4)."""
        pidfile = self.tmp / "hang.pid"
        t0 = time.time()
        r = self.run_cli("--timeout", "5", FAKE_MODE="hang", FAKE_PIDFILE=str(pidfile))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertLess(time.time() - t0, 20)
        self.assertIn("timed out after 5 s", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        pid = int(pidfile.read_text())
        for _ in range(50):
            if not alive(pid):
                break
            time.sleep(0.2)
        self.assertFalse(alive(pid), "the fake claude behind the shim was left running")

    def test_a_hung_help_says_timed_out_not_that_the_flag_is_missing(self):
        pidfile = self.tmp / "hang-help.pid"
        t0 = time.time()
        r = self.run_cli("--timeout", "5", FAKE_MODE="hang-help", FAKE_PIDFILE=str(pidfile))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertLess(time.time() - t0, 20)
        self.assertIn("timed out", r.stderr)
        self.assertNotIn("does not list", r.stderr)
        self.assertEqual(self.runs(), [], "no measuring run starts after a help that never answered")
        pid = int(pidfile.read_text())
        for _ in range(50):
            if not alive(pid):
                break
            time.sleep(0.2)
        self.assertFalse(alive(pid))

    def test_a_call_stopped_at_the_one_turn_limit_is_accepted_for_its_first_turn_and_says_so(self):
        r = self.run_cli(FAKE_MODE="max-turns")          # subtype error_max_turns, is_error true, exit 1 if claude chose to
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"difference\s+25,000")
        self.assertIn("stopped at the one-turn limit", r.stdout)
        self.assertEqual(json.loads(self.run_cli("--json", FAKE_MODE="max-turns").stdout)["current"]["turn_limit"], True)
        self.assertNotIn("turn limit", self.run_cli().stdout)
        r = self.run_cli(FAKE_MODE="max-turns-nousage")  # without usage there is nothing to report
        self.assertEqual(r.returncode, 2)
        self.assertIn("no usable usage numbers", r.stderr)

    def test_a_negative_difference_is_flagged_in_the_table_and_the_json(self):
        r = self.run_cli(FAKE_MODE="inverted")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"difference\s+-25,000")
        self.assertIn("difference is negative", r.stdout)
        j = json.loads(self.run_cli("--json", FAKE_MODE="inverted").stdout)
        self.assertEqual(j["difference"], -25_000)
        self.assertIn("negative", j["note"])
        self.assertNotIn("note", json.loads(self.run_cli("--json").stdout))
        self.assertNotIn("negative", self.run_cli().stdout)

    def test_the_transcript_report_and_its_flags_are_untouched(self):
        r = subprocess.run([sys.executable, "-I", str(HERE / "token_split.py"), "--projects", str(self.tmp / "none")], capture_output=True, text=True)
        self.assertEqual((r.returncode, "no transcript folder" in r.stderr), (2, True))


class RealTable(unittest.TestCase):
    def test_the_kit_table_loads_every_model_with_a_long_tier_only_where_listed(self):
        got = ts.load_prices()
        raw = json.loads((KIT / "settings" / "model-evidence.json").read_text(encoding="utf-8"))["prices"]
        self.assertEqual(set(got), set(raw))
        for model, p in got.items():
            self.assertEqual(p["base"], {k: float(raw[model][k]) for k in ts.FIELDS})
            self.assertEqual(bool(p["long"]), bool(raw[model]["long_context"]))


if __name__ == "__main__":
    unittest.main()
