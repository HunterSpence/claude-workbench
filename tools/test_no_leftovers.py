#!/usr/bin/env python3
"""test_no_leftovers.py: the removed blocking-hook feature leaves no trace in the kit.

Walks `git ls-files` of a kit root (default: this repository; `--root DIR` names another) and fails on any
case-insensitive occurrence of the feature's name, in a file path or in a file's text, that is not in the EXCEPTIONS
table below. Every exception is an exact path plus an exact string plus a one-line reason. The word and every
exception string are built from fragments, so this file holds no occurrence itself.

Run: py -3 tools/test_no_leftovers.py -v
The self-tests (class SelfTest) use temp trees: a stray hit fails, the exception tree passes, an exception string moved
to another file fails. Class RealKit scans the real kit.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # acceptance runs: a missing dependency (git) fails, never skips
ROOT = Path(__file__).resolve().parents[1]

WORD = "gu" + "ard"
DEVICE = "Device" + "Gu" + "ard"
SAFE = "safe" + "gu" + "ard"                   # vendor text quoted verbatim; one entry covers singular and plural
OBJECT_MODEL = "Object Model " + "Gu" + "ard"
SPANISH = WORD + "ar"                          # the Spanish verb "to save" on a button label and in a write-action word list
PHRASES = ("no " + WORD, WORD + " was removed")   # the deliberate notes: at most one line per doc below
ROOT_ONE = "one " + WORD + " in the shared function"   # ponytail's licensed ruleset, quoted verbatim
ROOT_TWO = WORD + " in every caller"

# (path, string, reason). A string of None allows every occurrence in that file (release history).
EXCEPTIONS = [
    ("CHANGELOG.md", None, "release history keeps the old name"),
    ("plugins/workbench-capture/skills/ingest/references/asks.md", OBJECT_MODEL,
     "Microsoft's name for Outlook's programmatic-access policy, inside the ask text sent to IT"),
    ("plugins/workbench-capture/skills/ingest/scripts/common.py", OBJECT_MODEL,
     "the same ask text; test_ingest_static keeps it equal to asks.md"),
    ("bootstrap/probe.py", DEVICE, "a Windows WMI class name the probe queries"),
    ("docs/evidence/haiku-5-5.md", SAFE, "the vendor system card quoted verbatim"),
    ("docs/model-routing.md", SAFE, "the vendor system card quoted verbatim"),
    ("settings/model-evidence.json", SAFE, "the vendor system card quoted verbatim"),
    ("settings/model-routing.json", SAFE, "the vendor system card quoted verbatim"),
    ("kb-template/_shared/bug-cards.md", SAFE, "Claude Code's own error text quoted verbatim"),
    ("kb-template/_shared/bug-detectors.json", SAFE, "the detector that matches Claude Code's own error text"),
    ("plugins/workbench-capture/skills/capture/scripts/actions.mjs", SPANISH, "Spanish word in the write-action blocklist"),
    ("plugins/workbench-capture/tests/fixtures/site/www/buttons.html", SPANISH, "Spanish button label the blocklist test needs"),
    ("plugins/workbench-core/agents/flagship.md", ROOT_ONE, "ponytail ruleset, licensed verbatim"),
    ("plugins/workbench-core/agents/flagship.md", ROOT_TWO, "ponytail ruleset, licensed verbatim"),
    ("plugins/workbench-core/agents/implementer.md", ROOT_ONE, "ponytail ruleset, licensed verbatim"),
    ("plugins/workbench-core/agents/implementer.md", ROOT_TWO, "ponytail ruleset, licensed verbatim"),
    ("plugins/workbench-core/skills/ponytail/SKILL.md", ROOT_ONE, "ponytail ruleset, licensed verbatim"),
    ("plugins/workbench-core/skills/ponytail/SKILL.md", ROOT_TWO, "ponytail ruleset, licensed verbatim"),
]
# Docs that may say, once, that the kit has no such hook (a line holding one of PHRASES).
NOTE_DOCS = ["README.md", "IMPORT.md", "settings/SETTINGS.md", "docs/known-limits.md"]


def tracked(root):
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"git ls-files failed in {root}: {r.stderr.decode(errors='replace').strip()}")
    return [p for p in r.stdout.decode("utf-8").split("\0") if p]


def scan(root, files=None):
    """['path:line: text' or 'path: name', ...] for every occurrence the table does not allow."""
    root, bad = Path(root), []
    for rel in tracked(root) if files is None else files:
        if WORD in rel.lower():
            bad.append(f"{rel}: the file name holds the word")
        try:
            data = (root / rel).read_bytes()
        except OSError:
            continue
        if WORD.encode() not in data.lower():
            continue
        allowed = [s.lower() for p, s, _ in EXCEPTIONS if p == rel and s]
        if any(p == rel and s is None for p, s, _ in EXCEPTIONS):
            continue
        notes = 0
        for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            rest = line.lower()
            if WORD not in rest:
                continue
            if rel in NOTE_DOCS and any(ph in rest for ph in PHRASES):
                notes += 1
                for ph in PHRASES:
                    rest = rest.replace(ph, " ")
                if notes > 1:
                    bad.append(f"{rel}:{n}: a second deliberate note (one per doc)")
            for s in allowed:
                rest = rest.replace(s, " ")
            if WORD in rest:
                bad.append(f"{rel}:{n}: {line.strip()[:110]}")
    return bad


def make_tree(root, files):
    for rel, text in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return list(files)


def exception_tree():
    """One file per table row holding exactly the row's string, plus one note line in each NOTE_DOCS file."""
    files = {}
    for path, s, _ in EXCEPTIONS:
        files[path] = files.get(path, "") + f"line with {s or WORD}\n"
    for path in NOTE_DOCS:
        files[path] = f"The kit has {PHRASES[0]} hook.\n"
    return files


class SelfTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def scan(self, files):
        return scan(self.tmp.name, make_tree(self.tmp.name, files))

    def test_a_clean_tree_passes(self):
        self.assertEqual(self.scan({"docs/a.md": "nothing to see\n", "bootstrap/x.py": "print(1)\n"}), [])

    def test_a_stray_hit_fails_in_any_case(self):
        for word in (WORD, WORD.upper(), WORD.title(), "safe" + WORD, "un" + WORD + "ed"):
            with self.subTest(word=word):
                got = self.scan({"docs/a.md": f"fine\nthis line has {word} in it\n"})
                self.assertEqual(len(got), 1)
                self.assertTrue(got[0].startswith("docs/a.md:2:"), got)

    def test_a_file_name_with_the_word_fails(self):
        self.assertEqual(len(self.scan({f"tools/{WORD}-replay/readme.md": "clean text\n"})), 1)

    def test_the_exception_tree_passes(self):
        files = exception_tree()
        self.assertEqual(self.scan(files), [])
        self.assertGreaterEqual(len(files), 10)

    def test_an_exception_string_in_another_file_fails(self):
        for path, s, _ in EXCEPTIONS:
            if s is None:
                continue
            with self.subTest(string=s, path=path):
                other = "docs/other.md"
                self.assertNotEqual(path, other)
                got = self.scan({other: f"line with {s}\n"})
                self.assertEqual(len(got), 1, got)

    def test_an_exception_does_not_cover_a_second_hit_on_the_same_line(self):
        got = self.scan({"bootstrap/probe.py": f"{DEVICE} and then a stray {WORD}\n"})
        self.assertEqual(len(got), 1, got)

    def test_a_note_doc_may_hold_one_note_line_not_two(self):
        one = f"The kit has {PHRASES[0]} hook.\n"
        self.assertEqual(self.scan({"README.md": one}), [])
        self.assertEqual(len(self.scan({"README.md": one + f"Also, the {PHRASES[1]}.\n"})), 1)
        self.assertEqual(len(self.scan({"docs/howto/45-browser-headless.md": one})), 1, "a doc outside the list gets none")

    def test_a_note_line_does_not_hide_another_hit_on_it(self):
        self.assertEqual(len(self.scan({"README.md": f"{PHRASES[0]} hook; the {WORD} engine\n"})), 1)

    def test_a_whole_file_exception_covers_history_only_in_that_file(self):
        self.assertEqual(self.scan({"CHANGELOG.md": f"- removed the {WORD}\n- the {WORD} again\n"}), [])
        self.assertEqual(len(self.scan({"docs/CHANGELOG.md": f"- removed the {WORD}\n"})), 1)


class RealKit(unittest.TestCase):
    def test_the_kit_has_no_leftover_of_the_removed_feature(self):
        try:
            bad = scan(ROOT)
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            if REQUIRE:
                self.fail(f"git is needed under WB_REQUIRE_ALL=1: {e}")
            self.skipTest(f"git is not usable here: {e}")
        self.assertEqual(bad, [], f"{len(bad)} leftover(s):\n" + "\n".join(bad))


def main():
    global ROOT
    argv = sys.argv[:]
    if "--root" in argv:
        i = argv.index("--root")
        ROOT = Path(argv[i + 1]).resolve()
        del argv[i:i + 2]
    unittest.main(module=sys.modules[__name__], argv=argv)


if __name__ == "__main__":
    main()
