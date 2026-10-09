"""H3: the issues log. bug_hint.py (PostToolUseFailure) appends one JSON line per failed tool call to <workbench home>/state/
issues.jsonl; issues.py show prints it as a numbered markdown table. Run:
    python -m unittest discover -s plugins/workbench-core/scripts/tests -p test_issues.py
Each hook runs as a subprocess with a temp Claude home. Every credential-shaped string is built at run time and is obviously fake."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import _wb  # noqa: E402
import bug_hint  # noqa: E402

FAKE_AWS = "AKIA" + "X" * 16                  # AWS access key id shape, not a key
FAKE_ENV = "API_TOKEN=" + "FAKE1234" * 3      # NAME=value shape with a digit, not a token
FAKE_SK = "sk-" + "FAKE" * 8                  # vendor key shape, not a key
TIME = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$"
KNOWN = {"version": 1, "detectors": [{"card": 7, "title": "Proxy certificate not trusted by node",
                                      "pattern": "self[- ]signed certificate"}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-issues-"))
        self.claude = self.tmp / "claude"
        self.state = self.claude / "workbench" / "state"
        self.log = self.state / "issues.jsonl"
        kb = self.tmp / "kb"
        (kb / "_shared").mkdir(parents=True)
        (kb / "_shared" / "bug-detectors.json").write_text(json.dumps(KNOWN), encoding="utf-8")
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.claude), "WORKBENCH_KB_ROOT": str(kb),
                    "PYTHONIOENCODING": "utf-8"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def failure(self, error="Exit code 1\nboom", raw=None, **kw):
        ev = {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "session_id": "sess-1", "error": error, **kw}
        t0 = time.monotonic()
        r = subprocess.run([sys.executable, "-S", str(SCRIPTS / "bug_hint.py")], capture_output=True, text=True,
                           encoding="utf-8", env=self.env, timeout=60, input=raw if raw is not None else json.dumps(ev))
        self.took = time.monotonic() - t0
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def rows(self, p=None):
        return [json.loads(x) for x in (p or self.log).read_text(encoding="utf-8").splitlines()]

    def show(self, *args):
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "issues.py"), "show", *args], capture_output=True,
                           text=True, encoding="utf-8", env=self.env, timeout=60)
        return r


class Log(Base):
    def test_one_line_per_failure_with_time_tool_session_and_first_ten_lines(self):
        err = "\n".join(f"line {i}" for i in range(1, 16))
        self.failure(err)
        (row,) = self.rows()
        self.assertEqual(set(row), {"time", "tool", "session", "error"})
        self.assertRegex(row["time"], TIME)
        self.assertEqual((row["tool"], row["session"]), ("Bash", "sess-1"))
        self.assertEqual(row["error"], [f"line {i}" for i in range(1, 11)])
        self.failure("second", tool_name="mcp__x__y", session_id="sess-2")
        self.assertEqual([(r["tool"], r["session"], r["error"]) for r in self.rows()[1:]],
                         [("mcp__x__y", "sess-2", ["second"])])
        self.assertEqual(len(self.log.read_text(encoding="utf-8").splitlines()), 2)       # one line each, never wrapped

    def test_the_hint_is_still_printed_and_not_changed(self):
        out = self.failure("Exit code 1\nself-signed certificate in certificate chain")
        self.assertEqual(out["hookSpecificOutput"]["additionalContext"],
                         "Known bug, card 7: Proxy certificate not trusted by node (see _shared/bug-cards.md)")
        self.assertEqual(len(self.rows()), 1)

    def test_a_fabricated_credential_is_redacted_before_it_is_written(self):
        self.failure(f"auth failed\nusing {FAKE_AWS} for the call\nexport {FAKE_ENV}\nkey {FAKE_SK}\nplain words stay")
        raw = self.log.read_text(encoding="utf-8")
        for secret in (FAKE_AWS, FAKE_ENV.split("=", 1)[1], FAKE_SK):
            self.assertNotIn(secret, raw)
        (row,) = self.rows()
        self.assertEqual(row["error"][0], "auth failed")
        self.assertEqual(row["error"][-1], "plain words stay")
        self.assertEqual(sum(x.count("[REDACTED]") for x in row["error"]), 3)

    def test_redaction_failure_writes_nothing_and_never_raises(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.claude)}), \
                mock.patch.object(_wb, "redact", side_effect=ImportError("no scanner")):
            self.assertIsNone(bug_hint.log_issue({"tool_name": "Bash", "error": f"x {FAKE_AWS}"}))
        self.assertFalse(self.log.exists())

    def test_only_the_first_ten_lines_are_scanned_and_long_lines_are_cut(self):
        self.failure("a" * 100_000 + "\n" + "\n".join(["b"] * 30))
        (row,) = self.rows()
        self.assertEqual(row["error"], ["[CUT]"] + ["b"] * 9)                                 # ten lines; the unbroken run past the window is dropped whole
        self.failure("word " * 5000 + "\n" + "\n".join(["b"] * 30))
        self.assertEqual(len(self.rows()[-1]["error"]), bug_hint.ISSUE_LINES)
        self.assertEqual(len(self.rows()[-1]["error"][0]), bug_hint.ISSUE_LINE_CHARS)         # prose is kept to the display width
        self.failure("z" * 3_000_000)                                                          # one enormous line is fast and bounded
        self.assertLess(self.took, 5)
        self.assertLess(len(self.log.read_text(encoding="utf-8").splitlines()[-1]), 25_000)
        self.assertEqual(self.rows()[-1]["error"], ["[CUT]"])

    def test_a_credential_straddling_the_display_cut_is_redacted_whole(self):
        """D2: the line used to be cut at 2000 characters BEFORE redaction, so half a token went to disk."""
        pre = ("ab " * 700)[:1989] + " "                                                      # the next character is column 1990
        tokens = {"github": "ghp_" + "Fake" * 9, "aws": "AKIA" + "X" * 16, "vendor": "sk-" + "FAKE" * 8}
        for name, tok in tokens.items():
            self.failure(pre + tok + " tail words")
            raw = self.log.read_text(encoding="utf-8")
            for frag in (tok, tok[:12], tok[-12:]):
                self.assertNotIn(frag, raw, f"{name}: {frag}")
            shown = self.rows()[-1]["error"][0]
            self.assertLessEqual(len(shown), bug_hint.ISSUE_LINE_CHARS)
            self.assertTrue(shown.endswith("[REDACTED]") and "[CUT]" not in shown, name)           # seen whole, so redacted, not dropped
        self.failure(pre + "FAKE" * 1000)                                                      # a run that outlasts the window: dropped whole
        self.assertNotIn("FAKEFAKE", self.log.read_text(encoding="utf-8"))

    def test_a_token_cut_by_the_window_leaves_no_fragment(self):
        tok = "ghp_" + "Fake" * 9
        for start in range(bug_hint.ISSUE_WINDOW - len(tok) - 3, bug_hint.ISSUE_WINDOW + 1, 7):   # every way the window can cut it
            line = ("ab " * 2000)[:start - 1] + " " + tok + " tail"
            (cut,) = bug_hint.issue_lines(line)
            cut = _wb.redact(cut)                                                             # what log_issue does next
            self.assertNotIn("Fake", cut, start)
            self.assertNotIn("ghp_", cut, start)
            self.assertLessEqual(len(cut), bug_hint.ISSUE_WINDOW + 5)
        self.assertEqual(bug_hint.issue_lines("short"), ["short"])
        self.assertEqual(bug_hint.issue_lines("x" * bug_hint.ISSUE_WINDOW), ["x" * bug_hint.ISSUE_WINDOW])   # not past the window: kept
        self.assertEqual(bug_hint.issue_lines("x" * (bug_hint.ISSUE_WINDOW + 1)), ["[CUT]"])

    def test_a_private_key_block_is_redacted_whole(self):
        head, tail = "-----BEGIN " + "RSA PRIVATE" + " KEY-----", "-----END " + "RSA PRIVATE" + " KEY-----"
        self.failure(f"ssh failed\n{head}\nFAKEBODYONE\nFAKEBODYTWO\n{tail}\nafter the key")
        raw = self.log.read_text(encoding="utf-8")
        for frag in ("FAKEBODY", "PRIVATE KEY"):
            self.assertNotIn(frag, raw)
        self.assertEqual(self.rows()[-1]["error"], ["ssh failed", "[REDACTED]", "after the key"])
        self.failure(f"cut off mid key\n{head}\nFAKEBODYTHREE\nFAKEBODYFOUR")                     # no END line: the rest is the key
        self.assertNotIn("FAKEBODY", self.log.read_text(encoding="utf-8").split("\n")[-2])
        self.assertEqual(self.rows()[-1]["error"], ["cut off mid key", "[REDACTED]"])
        self.assertEqual(_wb.redact(f"{head.replace('RSA', 'OPENSSH')}\nFAKEBODYFIVE\n{tail.replace('RSA', 'OPENSSH')}"), "[REDACTED]")

    def test_a_putty_key_file_is_redacted_whole(self):
        """D8: secretscan used to match the PuTTY header only; the body lines are the key."""
        ppk = ["PuTTY-User-Key-File-" + "3: ssh-ed25519", "Encryption: none", "Comment: fictional", "Public-Lines: 1", "AAAAFAKEPUBLICPART",
               "Private-Lines: 1", "FAKEPRIVATEBODY", "Private-MAC: " + "ab" * 16]
        self.failure("key load failed\n" + "\n".join(ppk) + "\nafter the key")
        raw = self.log.read_text(encoding="utf-8")
        for frag in ("FAKEPRIVATEBODY", "AAAAFAKE", "ssh-ed25519", "abababab"):
            self.assertNotIn(frag, raw)
        self.assertEqual(self.rows()[-1]["error"], ["key load failed", "[REDACTED]", "after the key"])
        self.assertEqual(_wb.redact("\n".join(ppk[:6])), "[REDACTED]")                  # no Private-MAC line: to the end of the text

    def test_more_credential_shapes_are_redacted_and_placeholders_are_not(self):
        """P3: shapes secretscan has no pattern for. Fabricated values only."""
        text = ("x-api" + "-key: FakeApiKeyValue99\n"                                      # built from pieces: no credential-shaped literal here
                "curl -u alice:" + "FakePw1x https://example.invalid/a\n"
                'body {"pass' + 'word": "FakePw1"} done\n'
                "GET https://example.invalid/b?sv=2022&si" + "g=FAKE%2Fsig%2Bvalue12345678%3D&se=1")
        self.failure(text)
        raw = self.log.read_text(encoding="utf-8")
        for secret in ("FakeApiKeyValue99", "FakePw1x", "FakePw1", "FAKE%2Fsig"):
            self.assertNotIn(secret, raw)
        (row,) = self.rows()
        self.assertEqual(row["error"], ["x-api-key: [REDACTED]", "curl -u alice:[REDACTED] https://example.invalid/a",
                                        'body {"password": "[REDACTED]"} done',
                                        "GET https://example.invalid/b?sv=2022&sig=[REDACTED]&se=1"])
        self.failure('{"pass' + 'word": "Fa\\"keTail9"} tool --pass' + "word=Pw1 --pass" + "word Fake9 done")
        self.assertEqual(self.rows()[-1]["error"], ['{"password": "[REDACTED]"} tool --password=[REDACTED] --password [REDACTED] done'])
        keep = ("x-api-key: <your key>\ncurl -u alice:$PW https://example.invalid\n"
                '{"password": ""} {"password": "${PW}"}\nsig=short')
        self.failure(keep)
        self.assertEqual("\n".join(self.rows()[-1]["error"]), keep)

    def test_interrupts_garbage_and_non_failure_events_are_not_logged(self):
        self.failure("stopped by the user", is_interrupt=True)
        self.failure(raw="not json")
        self.failure(raw="[]")
        self.failure(raw=json.dumps({"hook_event_name": "StopFailure", "session_id": "s", "last_assistant_message": "x"}))
        self.assertFalse(self.log.exists())
        self.failure(None)                                                                      # a failure with no error text still counts
        self.assertEqual(self.rows()[0]["error"], [])

    def test_rotates_at_5_mb_and_keeps_one_old_file(self):
        self.state.mkdir(parents=True)
        self.log.write_bytes(b"o" * (5 * 1024 * 1024 + 1))
        self.failure("fresh")
        old = self.state / "issues.jsonl.1"
        self.assertEqual(old.stat().st_size, 5 * 1024 * 1024 + 1)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["error"], ["fresh"])
        self.failure("again")
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(old.stat().st_size, 5 * 1024 * 1024 + 1)                            # no rotation below the limit
        self.log.write_bytes(b"n" * (5 * 1024 * 1024 + 1))
        self.failure("third")
        self.assertEqual(old.read_bytes()[:1], b"n")                                         # the .1 file was replaced
        self.assertEqual(sorted(p.name for p in self.state.glob("issues.jsonl*")),
                         ["issues.jsonl", "issues.jsonl.1", "issues.jsonl.lock"])

    def test_writes_only_inside_the_state_folder(self):
        def files():
            return {p for p in self.tmp.rglob("*") if p.is_file()}
        before = files()
        self.failure("boom", tool_name="../../../evil/tool", session_id="../../../evil/session")
        self.failure("boom", tool_name="x" * 5000, session_id="y" * 5000)
        new = files() - before
        self.assertTrue(new)
        for p in new:
            self.assertEqual(p.parent, self.state, p)
        self.assertEqual({p.name for p in new} - {"issues.jsonl.lock"}, {"issues.jsonl"})
        rows = self.rows()
        self.assertEqual((len(rows[1]["tool"]), len(rows[1]["session"])), (200, 80))

    def test_a_write_failure_does_not_break_the_hook(self):
        self.claude.joinpath("workbench").mkdir(parents=True)
        self.state.write_text("a file where the folder should be", encoding="utf-8")
        out = self.failure("self-signed certificate in certificate chain")                     # exit 0, hint still delivered
        self.assertIn("card 7", out["hookSpecificOutput"]["additionalContext"])
        self.assertTrue(self.state.is_file())
        self.state.unlink()
        self.state.mkdir()
        self.log.mkdir()                                                                     # the log path is a directory
        self.assertIsNone(self.failure("boom"))
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.claude)}), \
                mock.patch.object(_wb, "append_line", side_effect=OSError("disk full")):
            self.assertIsNone(bug_hint.log_issue({"tool_name": "Bash", "error": "boom"}))    # and an exception inside is swallowed


class Show(Base):
    def put(self, name, rows):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / name).write_text("".join(x if isinstance(x, str) else json.dumps(x) + "\n" for x in rows), encoding="utf-8")

    def test_numbered_markdown_table_in_the_order_it_happened(self):
        self.put("issues.jsonl.1", [{"time": "2001-01-01T00:00:00Z", "tool": "Read", "session": "s", "error": ["old one"]}])
        self.put("issues.jsonl", [
            {"time": "2001-02-03T04:05:06Z", "tool": "Bash", "session": "s", "error": ["", "Exit code 2", "second"]},
            "this line is not json\n",
            {"time": "2001-03-04T00:00:00Z", "tool": "mcp__a__b", "session": "s", "error": ["a | b", "x"]},
            {"time": "2001-03-05T00:00:00Z", "tool": "Edit", "session": "s", "error": []}])
        r = self.show()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            "| n | time | tool | first error line |", "|---|---|---|---|",
            "| 1 | 2001-01-01T00:00:00Z | Read | old one |",
            "| 2 | 2001-02-03T04:05:06Z | Bash | Exit code 2 |",
            "| 3 | 2001-03-04T00:00:00Z | mcp__a__b | a \\| b |",
            "| 4 | 2001-03-05T00:00:00Z | Edit | (no error text) |"])

    def test_since_filters_by_date_and_keeps_the_numbers(self):
        self.put("issues.jsonl", [{"time": f"2001-0{m}-15T12:00:00Z", "tool": "Bash", "session": "s", "error": [f"e{m}"]}
                                  for m in (1, 2, 3)])
        r = self.show("--since", "2001-02-15")
        self.assertEqual([x.split(" | ")[0] for x in r.stdout.splitlines()[2:]], ["| 2", "| 3"])
        self.assertEqual(self.show("--since", "2001-03-16").stdout.strip(), "No issues logged since 2001-03-16.")
        bad = self.show("--since", "last week")
        self.assertEqual(bad.returncode, 2)

    def test_empty_missing_and_long_and_non_ascii_lines(self):
        self.assertEqual(self.show().stdout.strip(), "No issues logged.")
        self.put("issues.jsonl", [{"time": "2001-01-01T00:00:00Z", "tool": "Bash", "session": "s",
                                   "error": ["caf\u00e9 \u2603 " + "w" * 400]}])
        r = self.show()
        self.assertEqual(r.returncode, 0, r.stderr)
        line = r.stdout.splitlines()[2]
        self.assertIn("caf\u00e9 \u2603", line)
        self.assertTrue(line.endswith("... |"))
        self.assertLess(len(line), 260)

    def test_the_log_the_hook_writes_is_the_log_the_renderer_reads(self):
        self.failure("Exit code 1\nfirst real line")
        self.failure(f"token {FAKE_AWS}", tool_name="PowerShell")
        r = self.show()
        rows = r.stdout.splitlines()[2:]
        self.assertEqual(len(rows), 2)
        self.assertRegex(rows[0], r"^\| 1 \| \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ \| Bash \| Exit code 1 \|$")
        self.assertIn("[REDACTED]", rows[1])
        self.assertNotIn(FAKE_AWS, r.stdout)


if __name__ == "__main__":
    unittest.main()
