"""Ingest: the Teams and Copilot ask is the same wording everywhere it appears, and the setup runbook covers what the kit sets up.

Part 1 (ID1). The words of item (4) and the one-line tenant check come from the `capture-meeting-transcripts` ask in
bootstrap/features.json. They must read the same in common.ASKS (what a stopped run prints), references/asks.md,
guide 41 and docs/admin-asks.md. Every permission name here was quoted from a Microsoft Learn page; a name that is not
on that list must not appear in any of the five places.
Part 2. docs/SETUP-RUNBOOK.md names every package id, every Day-1 knowledge check, every setup command, every opt-in and
every feature that has an ask, and its named FAIL list equals the code's.
"""
import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
KIT = PLUGIN.parents[1]
SKILL = PLUGIN / "skills" / "ingest"
sys.path.insert(0, str(SKILL / "scripts"))
import common  # noqa: E402

TRANSCRIPT, INSIGHT = "OnlineMeetingTranscript.Read.All", "OnlineMeetingAiInsight.Read.All"
CHECK = "Get-CsTeamsMeetingConfiguration | Select EnableGraphTranscriptAccess, EnableAttributedTranscripts"
QUOTED = {TRANSCRIPT, INSIGHT}      # the only OnlineMeeting<...>.Read.<...> names a Learn page was quoted for


def read(rel):
    return (KIT / rel).read_text("utf-8")


def norm(text):
    """One line: a Markdown blockquote or a wrapped paragraph reads the same as the single line it was copied from."""
    return re.sub(r"\s+", " ", re.sub(r"\n[> \t]*", " ", text)).strip()


def features_ask(fid="capture-meeting-transcripts"):
    rows = json.loads(read("bootstrap/features.json"))["rows"]
    return next(r["ask_it"] for r in rows if r["id"] == fid)


def clause():
    """Item (4) of the features.json ask, as one sentence fragment."""
    m = re.search(r"\(4\) (if I hold .*?\(admin consent\))", features_ask())
    assert m, "item (4) is missing from the capture-meeting-transcripts ask in bootstrap/features.json"
    return m.group(1)


PLACES = {
    "asks.md": norm(read("plugins/workbench-capture/skills/ingest/references/asks.md")),
    "guide 41": norm(read("docs/howto/41-unlock-meeting-transcripts-and-mail.md")),
    "admin-asks": norm(read("docs/admin-asks.md")),
}


class TeamsAsk(unittest.TestCase):
    def test_features_ask_is_the_source_of_the_words(self):
        ask = features_ask()
        self.assertIn(TRANSCRIPT, ask)
        self.assertIn(INSIGHT, ask)
        self.assertEqual(clause(), "if I hold a Microsoft 365 Copilot licence, also the delegated permission "
                                   f"{INSIGHT} for meeting AI insights (admin consent)")
        self.assertTrue(ask.endswith("To see the tenant setting: " + CHECK), "the tenant check closes the ask")

    def test_the_stop_asks_carry_the_permission_names_and_the_tenant_check(self):
        consent, tenant = common.ASKS["admin-consent"], common.ASKS["transcripts-disabled"]
        for name in (TRANSCRIPT, INSIGHT, "delegated"):
            self.assertIn(name, consent)
        self.assertIn(clause(), consent, "the Copilot permission clause must read exactly as in features.json")
        for needle in (CHECK, "EnableGraphTranscriptAccess", "EnableAttributedTranscripts", "drop folder"):
            self.assertIn(needle, tenant)

    def test_every_place_carries_the_same_clause_and_the_same_check(self):
        for place, text in PLACES.items():
            with self.subTest(place=place):
                self.assertIn(clause(), text)
                self.assertIn(CHECK, text)
        self.assertIn(norm(features_ask()), PLACES["admin-asks"], "admin-asks holds the whole ask, ready to send")

    def test_the_reference_file_holds_each_stop_ask_word_for_word(self):
        asks = (SKILL / "references" / "asks.md").read_text("utf-8")
        for key, text in common.ASKS.items():
            self.assertIn(text, asks, key)

    def test_no_permission_name_outside_the_quoted_pair_appears(self):
        texts = {"common": " ".join(common.ASKS.values()), "features": features_ask(), **PLACES}
        for place, text in texts.items():
            with self.subTest(place=place):
                found = set(re.findall(r"OnlineMeeting[A-Za-z]*\.Read\.[A-Za-z]+", text))
                self.assertLessEqual(found, QUOTED, found - QUOTED)

    def test_the_fallback_is_named_in_the_guide_and_the_stop_ask(self):
        self.assertIn("recap", common.ASKS["transcripts-disabled"])
        self.assertIn("Recap", PLACES["guide 41"])
        self.assertIn("drop folder", PLACES["guide 41"])


def section(text, start, end):
    """The part of the runbook from the heading that starts with `start` up to the one that starts with `end`."""
    i = text.index("\n" + start)
    return text[i:text.index("\n" + end, i + 1)]


def rows(sec):
    """The cells of every Markdown table row in sec (the separator row is dropped)."""
    out = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in sec.splitlines() if ln.startswith("|")]
    return [r for r in out if not set("".join(r)) <= set("-: ")]


def ticks(cell):
    return re.findall(r"`([^`]+)`", cell)


class RunbookCoverage(unittest.TestCase):
    raw = read("docs/SETUP-RUNBOOK.md")
    runbook = norm(raw)

    def test_every_package_id_has_a_row_in_the_package_table(self):
        ids = [p["id"] for p in json.loads(read("bootstrap/packages.json"))["packages"]]
        self.assertGreaterEqual(len(ids), 15)
        named = {t for r in rows(section(self.raw, "### 2.3", "### 2.4")) for t in ticks(r[0])}
        self.assertEqual([i for i in ids if i not in named], [])

    def test_every_day_one_check_has_a_row_with_its_name(self):
        src = read("bootstrap/knowledge_verify.py")
        steps = re.findall(r'\("(D\d+)", "([a-z0-9-]+)", d\d+_', src) + [("D20", "record")]
        self.assertEqual(len(steps), 23)
        have = {(ticks(r[0])[0], ticks(r[1])[0]) for r in rows(section(self.raw, "### 2.7", "### 2.8"))
                if len(r) > 1 and ticks(r[0]) and ticks(r[1])}
        self.assertEqual([f"{i} {n}" for i, n in steps if (i, n) not in have], [])

    def test_the_named_fail_list_is_the_codes(self):
        code = re.search(r"FAIL_LIST = \(([^)]*)\)", read("bootstrap/knowledge_verify.py")).group(1)
        want = re.findall(r"D\d+", code)
        got = re.search(r"Named FAIL list: ((?:D\d+(?:, )?)+)", self.runbook)
        self.assertTrue(got, "the runbook needs a line 'Named FAIL list: D1, D2, ...'")
        self.assertEqual(re.findall(r"D\d+", got.group(1)), want)

    def test_every_setup_command_and_opt_in_is_named(self):
        setup = read("bootstrap/setup.py")
        cmds = re.findall(r'sub\.add_parser\("([a-z-]+)"', setup) + ["run", "plan"]   # run and plan come from a loop
        self.assertGreaterEqual(len(set(cmds)), 12)
        self.assertEqual([c for c in sorted(set(cmds)) if f"SETUP {c}" not in self.runbook and f"setup.py {c}" not in self.runbook], [])
        extras = re.search(r"EXTRAS = \(([^)]*)\)", read("bootstrap/install.py"), re.S).group(1)
        names = re.findall(r'"([a-z-]+)"', extras)
        self.assertGreaterEqual(len(names), 9)
        self.assertEqual([n for n in names if f"`{n}`" not in self.runbook], [])

    def test_every_feature_that_has_an_ask_is_in_the_ask_index(self):
        feats = json.loads(read("bootstrap/features.json"))["rows"]
        ids = [r["id"] for r in feats if r.get("ask_it")]
        self.assertGreaterEqual(len(ids), 15)
        named = {t for r in rows(section(self.raw, "## 5.", "## 6.")) for t in ticks(r[0])}
        self.assertEqual([i for i in ids if i not in named], [])

    def test_the_report_ratings_each_have_a_row_in_the_ratings_table(self):
        named = {t for r in rows(section(self.raw, "### 2.2", "### 2.3")) for t in ticks(r[0])}
        self.assertEqual({"READY", "INSTALLABLE", "NEEDS-IT", "BLOCKED-BY-POLICY", "UNKNOWN"} - named, set())


if __name__ == "__main__":
    unittest.main()
