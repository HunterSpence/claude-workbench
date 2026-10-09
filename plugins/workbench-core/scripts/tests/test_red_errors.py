"""The red-error cards (67 to 94) and their detectors, checked through the real hook code on the real kit files.
Messages are the ones Claude Code and the API document. Run:
    python -m unittest discover -s plugins/workbench-core/scripts/tests -p "test_red_errors.py"
bug_hint.hint() reads the knowledge base first and falls back to the kit copy; here the knowledge base and the Claude
home are empty temp folders, so every answer comes from <kit>/kb-template/_shared."""
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[2]
SHARED = REPO / "kb-template" / "_shared"
sys.path.insert(0, str(SCRIPTS))
import bug_hint  # noqa: E402

# message as the docs print it -> the card that must be named. The first two went to the wrong card (6 and 4) while
# the new detectors sat after the old ones; the next two are the API error types.
PUBLISHED = [
    ("bash: line 1: syntax error near unexpected token `<'\nbash: line 1: `<!DOCTYPE html>'", 85),
    ("Connection dropped (ECONNRESET)", 72),
    ("{'type': 'error', 'error': {'type': 'rate_limit_error', 'message': 'slow down'}}", 19),
    ("{'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'Overloaded'}}", 67),
    ("API Error: Repeated 529 Overloaded errors. The API is at capacity — this is usually temporary.", 67),
    ("Can't reach the API server — check your internet or DNS (ENOTFOUND)", 72),
    ("Unable to connect to API: SSL certificate verification failed (UNABLE_TO_GET_ISSUER_CERT_LOCALLY).", 18),
    ("You've hit your session limit · resets 3:45pm", 68),
    ("Your organization has disabled Claude subscription access for Claude Code", 71),
    ("API Error: 400 due to tool use concurrency issues. Run /rewind to recover the conversation.", 78),
    ("WebFetch cannot fetch localhost or other hostnames without a dot. To reach a local server, use Bash with curl instead.", 91),
    ("'claude' is not recognized as an internal or external command", 12),
    ("API Error: Request rejected (429) · this may be a temporary capacity issue.", 19),
    ("Agent terminated early due to an API error: API Error: Repeated 529 Overloaded errors", 19),
    ("Prompt is too long", 74),
    ("Not logged in · Please run /login", 70),
    ("Credit balance is too low", 69),
    ("Concurrent subagent limit reached", 19),
    # not Claude Code's own messages: the three later cards (95 to 97), whose detectors sit at the end of the list
    ("fatal: 'C:/work/wt-fix' contains modified or untracked files, use --force to delete it", 95),
    ('WARN The "API_URL" variable is not set. Defaulting to a blank string.', 96),
    ("sqlite3.DatabaseError: file is not a database", 97),
]


class RedErrors(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="wb-red-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(tmp / "claude"), "WORKBENCH_KB_ROOT": str(tmp / "kb")})
        env.start()
        self.addCleanup(env.stop)
        self.det = json.loads((SHARED / "bug-detectors.json").read_text(encoding="utf-8"))["detectors"]
        self.cards = (SHARED / "bug-cards.md").read_text(encoding="utf-8")

    def card_of(self, text):
        h = bug_hint.hint(text)
        m = re.match(r"Known bug, card (\d+): ", h or "")
        return int(m.group(1)) if m else None

    def test_the_hook_reads_the_kit_files_and_names_the_card_for_each_published_message(self):
        self.assertEqual(len(bug_hint.detectors()), len(self.det))
        for text, card in PUBLISHED:
            self.assertEqual(self.card_of(text), card, text[:60])
            self.assertEqual(self.card_of("Exit code 1\n" + text), card, text[:60])

    def test_unrelated_errors_stay_silent(self):
        for text in ("ValueError: invalid literal for int() with base 10: 'abc'", "npm ERR! missing script: build",
                     "FAILED tests/test_sample.py::test_total - assert 1 == 2"):
            self.assertIsNone(bug_hint.hint(text))

    def test_every_new_card_has_a_detector_and_every_detector_has_its_card(self):
        have = {int(n) for n in re.findall(r"(?m)^### (\d+)\. ", self.cards)}
        self.assertLessEqual(set(range(67, 95)), have)
        self.assertLessEqual(set(range(67, 95)), {d["card"] for d in self.det}, "a new card without a detector")
        self.assertEqual({d["card"] for d in self.det} - have, set(), "a detector names a card the file lacks")

    def test_the_new_cards_obey_the_knowledge_rules(self):
        spec = importlib.util.spec_from_file_location("wb_test_docs", REPO / "tools" / "test_docs.py")
        docs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(docs)
        self.assertEqual(docs.check_cards(self.cards, {"version": 1, "detectors": self.det}), [])
        new = self.cards[self.cards.index("### 67. "):]
        self.assertEqual([m for ln in new.splitlines() for m in docs.DENY["P5"].findall(docs.STRUCTURAL_ID.sub(" ", ln))], [],
                         "a number of two or more digits")
        self.assertTrue(all(ord(c) < 128 for c in new), "the cards file stays plain ASCII")

    def test_overloaded_is_no_longer_a_fan_out_rate_limit(self):
        card19 = [d for d in self.det if d["card"] == 19 and "rate limit" in d["pattern"]]
        self.assertEqual(len(card19), 1)
        self.assertNotIn("overloaded", card19[0]["pattern"])
        self.assertEqual(self.card_of("Rate limit exceeded. Retry after a few seconds."), 19)

    def test_new_detectors_come_before_the_old_ones(self):
        later = 3                                   # cards 95 to 97 come last: the old ones stay in front of them, in their order
        old = 41                                    # the detectors the earlier release shipped
        self.assertGreater(len(self.det), old + 40)
        self.assertEqual([d["card"] for d in self.det[-later:]], [95, 96, 97])
        self.assertTrue(all(d["card"] <= 66 for d in self.det[-old - later:-later]))
        self.assertEqual(self.card_of("Connection dropped (ECONNRESET)"), 72, "not the dead-hosts card")

    def test_a_failed_compose_up_with_a_busy_port_is_not_the_stale_environment_card(self):
        warn = 'WARN The "API_URL" variable is not set. Defaulting to a blank string.'
        for real in ("Error response from daemon: Bind for localhost:3000 failed: port is already allocated",
                     "listen tcp localhost:3000: bind: address already in use",
                     'Error response from daemon: Get "https://registry.example.com/v2/": tls: failed to verify certificate: '
                     "x509: certificate signed by unknown authority"):
            self.assertNotEqual(self.card_of(f"Exit code 1\n{warn}\n{real}"), 96, real)
            self.assertNotEqual(self.card_of(f"Exit code 1\n{real}\n{warn}"), 96, real)
        self.assertEqual(self.card_of(f"Exit code 1\n{warn}\nservice api failed to start"), 96)

    def test_the_sqlite_detector_wants_the_sqlite_messages_not_any_not_a_database_text(self):
        self.assertEqual(self.card_of("sqlite3.OperationalError: database disk image is malformed"), 97)
        self.assertIsNone(self.card_of("Error: the path is not a database server"))


if __name__ == "__main__":
    unittest.main()
