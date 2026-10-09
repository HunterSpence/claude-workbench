"""Tests for the StopFailure relay in bug_hint.py: queue on StopFailure, inject once on the next prompt. Run:
    python -m unittest discover -s plugins/workbench-core/scripts/tests -p "test_relay.py"
Each case runs the script as a subprocess (python -S, as the hook does) with a temp Claude home and the kit's real
detector file, so the card numbers in the enum map are checked against the shipped cards."""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: nothing here skips
SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[2]
SCRIPT = SCRIPTS / "bug_hint.py"
SHARED = REPO / "kb-template" / "_shared"
sys.path.insert(0, str(SCRIPTS))
import bug_hint  # noqa: E402

# The twelve StopFailure `error` values the hooks documentation lists.
DOCUMENTED = ["rate_limit", "overloaded", "authentication_failed", "oauth_org_not_allowed", "account_on_hold",
              "billing_error", "invalid_request", "model_not_found", "server_error", "max_output_tokens",
              "cloud_credential_error", "unknown"]
NO_CARD = {"invalid_request", "max_output_tokens", "unknown"}   # no card covers these classes
BELL_OUT = {"terminalSequence": "\u0007"}
NOMATCH = "API Error: the request ended for a reason no detector knows (zz9)"


class Relay(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-relay-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.kb = self.tmp / "kb"
        (self.kb / "_shared").mkdir(parents=True)
        shutil.copy(SHARED / "bug-detectors.json", self.kb / "_shared" / "bug-detectors.json")
        self.home = self.tmp / "claude"
        self.state = self.home / "workbench" / "state"
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.home), "WORKBENCH_KB_ROOT": str(self.kb),
                    "PYTHONIOENCODING": "utf-8"}

    def run_hook(self, event, *args, raw=None):
        r = subprocess.run([sys.executable, "-S", str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8",
                           env=self.env, timeout=60, input=raw if raw is not None else json.dumps(event))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def stop(self, sid="s1", error="rate_limit", message=NOMATCH, **kw):
        ev = {"session_id": sid, "hook_event_name": "StopFailure", "error": error, "last_assistant_message": message, **kw}
        return self.run_hook(ev)

    def prompt(self, sid="s1"):
        out = self.run_hook({"session_id": sid, "hook_event_name": "UserPromptSubmit", "prompt": "go on"}, "--pending")
        return out["hookSpecificOutput"]["additionalContext"] if out else None

    def pending(self, sid="s1"):
        return self.state / f"pending-hint-{sid}.json"

    def row(self, sid="s1"):
        return json.loads(self.pending(sid).read_text(encoding="utf-8"))

    # ── queue ──
    def test_the_message_text_is_matched_first_and_only_a_bell_is_printed(self):
        out = self.stop(error="server_error", message="API Error: Repeated 529 Overloaded errors. The API is at capacity")
        self.assertEqual(out, BELL_OUT)
        row = self.row()
        self.assertEqual((row["card"], row["source"]), (67, "message"))
        self.assertEqual(sorted(row), ["card", "created", "source", "title"])
        self.assertTrue(row["title"])
        age = datetime.now(timezone.utc) - datetime.fromisoformat(row["created"].replace("Z", "+00:00"))
        self.assertLess(abs(age.total_seconds()), 120)
        self.assertEqual([p.name for p in self.state.iterdir()], ["pending-hint-s1.json"])    # no temp file left behind

    def test_the_message_wins_over_the_error_type(self):
        self.stop(error="overloaded", message="Credit balance is too low")
        self.assertEqual(self.row()["card"], 69)

    def test_the_error_type_is_the_fallback_when_the_message_matches_nothing(self):
        self.assertEqual(self.stop(error="overloaded"), BELL_OUT)
        row = self.row()
        self.assertEqual((row["card"], row["source"]), (67, "error"))
        self.assertIn(row["title"], {d["title"] for d in json.loads((SHARED / "bug-detectors.json").read_text("utf-8"))["detectors"]})
        self.stop(sid="s2", error="authentication_failed", message="")
        self.assertEqual(self.row("s2")["card"], 70)
        self.stop(sid="s3", error="model_not_found", last_assistant_message=None)
        self.assertEqual(self.row("s3")["card"], 76)

    def test_a_match_beyond_the_first_4_kb_is_not_a_match(self):
        self.stop(error="overloaded", message="x" * 5000 + " Credit balance is too low")
        self.assertEqual((self.row()["card"], self.row()["source"]), (67, "error"))

    def test_every_documented_error_type_is_mapped_or_has_no_card(self):
        self.assertEqual(sorted(DOCUMENTED), sorted(set(bug_hint.ENUM_CARD) | NO_CARD))
        cards = (SHARED / "bug-cards.md").read_text(encoding="utf-8")
        for err, card in bug_hint.ENUM_CARD.items():
            with self.subTest(error=err):
                self.assertIsNotNone(bug_hint.title_of(card), "no detector row carries this card")
                self.assertRegex(cards, rf"(?m)^### {card}\. ")
                self.stop(sid="e-" + err, error=err)
                self.assertEqual(self.row("e-" + err)["card"], card)

    def test_error_types_with_no_card_queue_nothing_but_still_ring_the_bell(self):
        for err in sorted(NO_CARD) + ["a_future_type", None, 7]:
            with self.subTest(error=err):
                self.assertEqual(self.stop(sid="n1", error=err), BELL_OUT)
                self.assertFalse(self.pending("n1").exists())

    def test_a_second_failure_replaces_the_first(self):
        self.stop(error="rate_limit")
        self.stop(error="billing_error")
        self.assertEqual(self.row()["card"], 69)

    # ── deliver ──
    def test_the_hint_is_injected_once_for_its_own_session_then_deleted(self):
        self.stop(error="rate_limit")
        msg = self.prompt()
        self.assertTrue(msg.startswith(bug_hint.LEAD + "Known bug, card 19: "), msg)
        self.assertTrue(msg.endswith("(see _shared/bug-cards.md)"))
        self.assertLessEqual(len(msg), 300)
        self.assertFalse(self.pending().exists(), "the pending file must be deleted once it is injected")
        self.assertIsNone(self.prompt(), "injected twice")

    def test_another_sessions_file_is_never_read_or_deleted(self):
        self.stop(sid="a", error="rate_limit")
        self.assertIsNone(self.prompt("b"))
        self.assertIsNone(self.prompt("a-b"))
        self.assertTrue(self.pending("a").exists())
        self.assertIn("card 19", self.prompt("a"))

    def test_no_pending_file_and_a_missing_state_folder_print_nothing(self):
        self.assertIsNone(self.prompt())
        self.assertFalse(self.state.exists() and any(self.state.iterdir()))

    def test_a_corrupt_file_is_consumed_without_output(self):
        self.state.mkdir(parents=True)
        for bad in ("{nope", "[]", '{"card": "x", "title": "t"}', '{"title": "t"}', ""):
            self.pending().write_text(bad, encoding="utf-8")
            self.assertIsNone(self.prompt(), bad)
            self.assertFalse(self.pending().exists(), bad)

    def test_the_injected_line_is_capped_at_300_characters(self):
        self.state.mkdir(parents=True)
        self.pending().write_text(json.dumps({"card": 5, "title": "t " * 400, "source": "message", "created": "x"}), encoding="utf-8")
        self.assertEqual(len(self.prompt()), 300)

    # ── stale files, bad input ──
    def test_files_older_than_24_hours_are_removed_and_fresh_ones_kept(self):
        self.state.mkdir(parents=True)
        old, fresh, tmpf = (self.state / n for n in ("pending-hint-old.json", "pending-hint-fresh.json", "pending-hint-x.json.9.tmp"))
        for p in (old, fresh, tmpf):
            p.write_text("{}", encoding="utf-8")
        for p in (old, tmpf):
            t = time.time() - 25 * 3600
            os.utime(p, (t, t))
        other = self.state / "update.json"                  # not ours: never touched, however old
        other.write_text("{}", encoding="utf-8")
        os.utime(other, (time.time() - 99 * 3600,) * 2)
        self.assertIsNone(self.prompt("nobody"))
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), ["pending-hint-fresh.json", "update.json"])
        old.write_text("{}", encoding="utf-8")
        os.utime(old, (time.time() - 30 * 3600,) * 2)
        self.stop(sid="new")                                # the StopFailure path prunes too
        self.assertFalse(old.exists())

    def test_it_always_exits_zero_and_never_writes_outside_the_state_folder(self):
        for raw in ("not json", "", "[]", "null", '{"hook_event_name": "StopFailure"}',
                    json.dumps({"hook_event_name": "StopFailure", "session_id": 5, "error": "rate_limit"})):
            self.run_hook(None, raw=raw)
            self.run_hook(None, "--pending", raw=raw)
        for sid in ("../evil", "..\\evil", "a/b", "C:/x", "a" * 81, "", "a b", "x\n"):
            self.stop(sid=sid)
            self.assertIsNone(self.prompt(sid))
        self.assertEqual([p for p in self.tmp.rglob("*") if p.is_file() and self.kb not in p.parents], [])   # nothing written at all

    def test_an_unwritable_state_folder_is_not_an_error(self):
        (self.home / "workbench").mkdir(parents=True)
        (self.home / "workbench" / "state").write_text("a file where the folder should be", encoding="utf-8")
        self.assertEqual(self.stop(), BELL_OUT)
        self.assertIsNone(self.prompt())

    def test_a_bom_in_the_payload_is_tolerated(self):
        self.run_hook(None, raw="\ufeff" + json.dumps({"session_id": "s1", "hook_event_name": "StopFailure", "error": "overloaded"}))
        self.assertEqual(self.row()["card"], 67)

    # ── the constant B2 reads, and the old event ──
    def test_the_floor_is_a_literal_three_tuple_that_setup_can_read_without_importing(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        vals = [ast.literal_eval(n.value) for n in tree.body
                if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "STOPFAILURE_MIN_CC" for t in n.targets)]
        self.assertEqual(vals, [bug_hint.STOPFAILURE_MIN_CC])
        v = bug_hint.STOPFAILURE_MIN_CC
        self.assertTrue(len(v) == 3 and all(isinstance(i, int) and i >= 0 for i in v), v)

    def test_post_tool_use_failure_is_unchanged(self):
        out = self.run_hook({"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "error": "Credit balance is too low"})
        ctx = out["hookSpecificOutput"]
        self.assertEqual(ctx["hookEventName"], "PostToolUseFailure")
        self.assertTrue(ctx["additionalContext"].startswith("Known bug, card 69: "))
        self.assertEqual(list(self.state.glob("pending-hint-*")), [])      # no relay file; the only state is the issues log (H3)
        self.assertEqual([p.name for p in self.state.iterdir() if p.suffix != ".lock"], ["issues.jsonl"])


if __name__ == "__main__":
    unittest.main()
