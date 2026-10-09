"""Checker for the how-to library in docs/howto (G20), with its own tests.

  WB_HOWTO_PART=1  checks guides 01-20 and the index only (the first half of the library); without it all 55 guides,
                   the >= 40 count and the `find` questions are checked.
  WB_REQUIRE_ALL=1 a missing dependency fails instead of skipping.
Run: python -m unittest tools/test_howto.py -v   (use the knowledge venv's python for the `find` check).
Each guide: a title, the four headings in order, one `Automates it:` line; every backticked kit path exists (test_docs
check_paths); every /<plugin>:<skill> is a skill folder; every `py -3|python|node <script>` names an existing script;
nothing always-loaded points at docs/howto; the 10 pre-registered questions in questions.json find their guide in the
top 3 (keyword mode, scratch index, no model download).
"""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: no test below skips, a missing file fails

import importlib.util  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

KIT = Path(__file__).resolve().parent.parent
HOWTO = KIT / "docs" / "howto"
FIND = KIT / "plugins" / "workbench-core" / "skills" / "find" / "scripts" / "doc_index.py"
PART = os.environ.get("WB_HOWTO_PART") == "1"
NAMES = """01-setup-first-day 02-read-the-capability-report 03-ask-it-for-access 04-proxies-and-tls-inspection
05-wsl-setup-and-resume 06-upgrade-and-uninstall 07-client-profiles 08-permission-modes-and-prompts
09-spawn-subagents-and-pick-models 10-save-session-knowledge 11-keep-token-use-low 12-headless-and-scheduled-runs
13-run-the-doctor-and-backups 14-write-a-skill-or-hook 15-connect-the-github-mcp-server 16-github-enterprise-hosts
17-review-an-unfamiliar-repo-safely 18-fix-a-bug-with-the-playbook 19-ci-with-claude-code-action
20-push-only-to-approved-hosts 21-scaffold-a-plugin 22-build-an-mcp-server 23-wrap-an-api-as-mcp
24-review-a-plugin-or-skill 25-package-a-skill-for-the-web 26-enable-an-enterprise-mcp-server
27-find-a-file-or-an-answer 28-add-a-library-to-find 29-keep-the-index-fresh 30-capture-intranet-pages
31-capture-shared-files 32-purge-indexed-or-captured-data 33-requirements-to-stories 34-meeting-notes-to-actions
35-status-report 36-scrub-a-document-before-sending 37-labelled-and-confidential-files 38-what-leaves-this-machine
39-when-a-policy-blocks-you 40-incident-first-steps 41-unlock-meeting-transcripts-and-mail
42-add-an-in-app-navigation-assistant 43-fix-a-red-error-in-claude-code 44-update-the-tools 45-browser-headless
46-draw-a-diagram-offline 47-lock-a-brand-spec-and-review-a-ui 48-build-an-eval
49-sweep-repositories-for-a-retiring-model-id 50-write-and-test-a-guard-rule 51-check-that-skills-fire-and-rules-hold
52-check-a-document-for-hidden-text 53-audit-and-clean-up 54-which-knowledge-tool-for-which-question
55-claude-code-on-a-virtual-desktop""".split()
FILES = [n + ".md" for n in NAMES]
MINE = FILES[:20] if PART else FILES
HEADINGS = ("## When to use", "## Steps", "## Verify", "## Common failures")
CODE = re.compile(r"```.*?```|`[^`\n]+`", re.S)
CMD = re.compile(r"(?<![\w-])(?:py -3|python3?|node)\s+(?:-[A-Za-z]+\s+)*[\"']?([^\s\"'`]+)")
SCRIPT = re.compile(r"\.(?:py|mjs|js|ps1)$")


def load_docs_checker():
    spec = importlib.util.spec_from_file_location("wb_test_docs", KIT / "tools" / "test_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def script_missing(tok, kit=KIT):
    """The token when it is a script path that does not resolve to a file in the kit, else None."""
    tok = tok.replace("\\", "/")
    if not SCRIPT.search(tok):
        return None
    top = {p.name for p in Path(kit).iterdir()}
    if tok.startswith("<KIT>/"):
        p = Path(kit) / tok[6:]
    elif "/" in tok and tok.split("/", 1)[0] in top:
        p = Path(kit) / tok
    else:
        return tok   # a location this checker cannot resolve: write it as <KIT>/...
    return None if p.is_file() else tok


def guide_errors(text, kit=KIT):
    """Problems with one guide's text (path existence is checked separately, on the file)."""
    errs, lines = [], text.splitlines()
    if not lines or not lines[0].startswith("# ") or sum(1 for x in lines if x.startswith("# ")) != 1:
        errs.append("the first line must be the only '# <title>' line")
    pos = [lines.index(h) if h in lines else -1 for h in HEADINGS]
    errs += [f"missing heading {h!r}" for h, i in zip(HEADINGS, pos) if i < 0]
    if -1 not in pos and pos != sorted(pos):
        errs.append("the four headings are out of order")
    if sum(1 for x in lines if re.match(r"Automates it: \S", x)) != 1:
        errs.append("needs exactly one 'Automates it: <skill or command | none>' line")
    for plugin, skill in re.findall(r"/(workbench-[a-z]+):([a-z0-9-]+)", text):
        if not (Path(kit) / "plugins" / plugin / "skills" / skill / "SKILL.md").is_file():
            errs.append(f"no such skill: /{plugin}:{skill}")
    for span in CODE.findall(text):
        errs += [f"script not found: {t}" for t in (script_missing(m, kit) for m in CMD.findall(span)) if t]
    return errs


def mentions_howto(root, files):
    return [str(f) for f in files if "docs/howto" in Path(f).read_text(encoding="utf-8", errors="replace")]


class Howto(unittest.TestCase):
    docs = load_docs_checker()

    def test_guides_present(self):
        missing = [f for f in MINE if not (HOWTO / f).is_file()]
        self.assertEqual(missing, [], "guide files missing")
        if not PART:
            self.assertGreaterEqual(len(list(HOWTO.glob("[0-9][0-9]-*.md"))), 40)

    def test_every_guide_shape_skills_and_scripts(self):
        for f in MINE:
            with self.subTest(guide=f):
                self.assertEqual(guide_errors((HOWTO / f).read_text(encoding="utf-8")), [])

    def test_backticked_kit_paths_exist(self):
        for f in MINE:
            with self.subTest(guide=f):
                self.assertEqual(self.docs.check_paths(HOWTO / f, KIT), [])

    def test_index_lists_every_guide_in_seven_groups(self):
        text = (HOWTO / "README.md").read_text(encoding="utf-8")
        self.assertEqual([f for f in FILES if f not in text], [], "guides the index does not link")
        self.assertGreaterEqual(len([x for x in text.splitlines() if x.startswith("## ")]), 7)

    def test_nothing_always_loaded_points_here(self):
        files = list((KIT / "instructions").rglob("*.*")) + list(self.docs.always_loaded(KIT))
        self.assertEqual(mentions_howto(KIT, files), [])

    def test_questions_file_shape(self):
        qs = json.loads((HOWTO / "questions.json").read_text(encoding="utf-8"))
        self.assertEqual(qs["version"], 1)
        got = [Path(q["expect"]).name for q in qs["questions"]]
        self.assertEqual(len(got), 10)
        self.assertEqual(sum(1 for g in got if g in FILES[:20]), 5)
        self.assertEqual(sum(1 for g in got if g in FILES[20:40]), 5)
        self.assertTrue(all(q["expect"] == f"docs/howto/{Path(q['expect']).name}" for q in qs["questions"]))


if not PART:   # the questions span guides 01-40: part mode (S9a alone) cannot answer them, so the class is absent

    class FindQuestions(unittest.TestCase):
        def test_find_returns_the_expected_guide_in_the_top_3(self):
            tmp = Path(tempfile.mkdtemp(prefix="wb-howto-"))
            self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
            env = dict(os.environ, WB_FIND_LAZY="0", WB_KNOWLEDGE_REEXEC="1", HF_HUB_OFFLINE="1", PYTHONUTF8="1")

            def cli(*a):
                return subprocess.run([sys.executable, str(FIND), "--db", str(tmp / "k.sqlite"), *a], env=env,
                                      capture_output=True, text=True, encoding="utf-8", timeout=600)
            for step in (["add-root", str(HOWTO), "--label", "howto"], ["refresh", "--root", "howto", "--embed", "off"]):
                r = cli(*step)
                if r.returncode and not REQUIRE and "No module named" in r.stderr:
                    self.skipTest("knowledge packages missing: " + r.stderr.strip().splitlines()[-1])
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            for q in json.loads((HOWTO / "questions.json").read_text(encoding="utf-8"))["questions"]:
                with self.subTest(question=q["q"][:50]):
                    r = cli("search", q["q"], "--mode", "keyword", "--limit", "3", "--root", "howto", "--json")
                    self.assertEqual(r.returncode, 0, r.stderr)
                    top = [Path(h["path"]).name for h in json.loads(r.stdout)["hits"]]
                    self.assertIn(Path(q["expect"]).name, top)


GOOD = """# A guide

Automates it: /workbench-core:setup

## When to use
x
## Steps
`py -3 <KIT>/bootstrap/setup.py status --json`
## Verify
x
## Common failures
x
"""


class CheckerTestsTheChecker(unittest.TestCase):
    """Test the test: each bad fixture must fail, the good one must pass."""

    def test_good_fixture_passes(self):
        self.assertEqual(guide_errors(GOOD), [])

    def test_missing_verify_heading_fails(self):
        self.assertIn("missing heading '## Verify'", guide_errors(GOOD.replace("## Verify\n", "")))

    def test_headings_out_of_order_fail(self):
        a, b = "## Steps\n", "## Verify\n"
        self.assertTrue(any("out of order" in e for e in guide_errors(GOOD.replace(a, "@@").replace(b, a).replace("@@", b))))

    def test_missing_automates_line_fails(self):
        self.assertTrue(guide_errors(GOOD.replace("Automates it: /workbench-core:setup\n", "")))

    def test_nonexistent_script_fails(self):
        for cmd in ("py -3 <KIT>/bootstrap/no_such_tool.py run", "python3 tools/nope.py", "node plugins/x/missing.mjs",
                    "py -3 helper.py"):
            self.assertTrue(any("script not found" in e for e in guide_errors(GOOD + f"```\n{cmd}\n```\n")), cmd)

    def test_unknown_skill_fails(self):
        self.assertIn("no such skill: /workbench-core:no-such-skill",
                      guide_errors(GOOD + "Run /workbench-core:no-such-skill.\n"))

    def test_nonexistent_backticked_kit_path_fails(self):
        tmp = Path(tempfile.mkdtemp(prefix="wb-howto-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        f = tmp / "g.md"
        f.write_text(GOOD + "See `docs/no-such-page.md` and `docs/HOW-WE-WORK.md`.\n", encoding="utf-8")
        self.assertEqual(Howto.docs.check_paths(f, KIT), ["docs/no-such-page.md"])

    def test_always_loaded_reference_is_found(self):
        tmp = Path(tempfile.mkdtemp(prefix="wb-howto-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        f = tmp / "rule.md"
        f.write_text("read docs/howto/01-x.md first\n", encoding="utf-8")
        self.assertEqual(mentions_howto(tmp, [f]), [str(f)])


if __name__ == "__main__":
    unittest.main()
