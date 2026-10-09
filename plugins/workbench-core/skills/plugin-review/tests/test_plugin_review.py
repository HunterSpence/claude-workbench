"""Tests for plugin-review: seeded recall, hold-out recall (reported), false-positive controls, test-the-test,
archive intake, batch scorecards and rule-set hashing. Run:
  WB_REQUIRE_ALL=1 py -3 -m unittest discover -s plugins/workbench-core/skills/plugin-review/tests -v
WB_HOLDOUT_SEED picks the hold-out set (default 7). Never tune a rule against the hold-out numbers.
"""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: nothing below skips; a missing dependency fails

import csv  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
import zipfile  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest import mock  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))
import make_fixtures as MF  # noqa: E402
import plugin_rules as R  # noqa: E402
import review_plugin as RP  # noqa: E402

SEED = os.environ.get("WB_HOLDOUT_SEED", "7")
TMP = FX = None


def setUpModule():
    global TMP, FX
    TMP = Path(tempfile.mkdtemp(prefix="wb-pr-test-"))
    FX = MF.build(TMP / "fx", SEED)


def tearDownModule():
    RP.rmtree(TMP)


def bad(rep):
    return [(f["severity"], f["rule"], f["file"]) for f in rep["findings"] if f["severity"] in ("block", "hold")]


def matched(items, rules=None):
    """items: [(id, plugin path, expected)] -> list of ids whose expected (rule, file) shows up in a review."""
    out = []
    for did, path, exp in items:
        rep = RP.review(path, "all")
        if any(f["rule"] == exp["rule"] and f["file"] == exp["file"] for f in rep["findings"]):
            out.append(did)
    return out


def make_zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            z.writestr(name, data)
    return path


class Controls(unittest.TestCase):
    def test_clean_control_has_no_block_or_hold(self):
        rep = RP.review(FX["clean"], "all")
        self.assertEqual(bad(rep), [])
        self.assertEqual(rep["verdict"], "ship")
        self.assertEqual(rep["surfaces"], {"cli": True, "desktop": True, "web": True})

    def test_near_miss_negatives_stay_quiet(self):
        for nid, target, path in FX["near"]:
            with self.subTest(nid):
                self.assertEqual(bad(RP.review(path, target)), [])

    def test_accented_names_are_not_lookalikes(self):
        self.assertIsNone(R.lookalike("Caf" + chr(0xE9) + " Tools"))
        self.assertTrue(R.lookalike("N" + MF.CYR_O + "tes"))

    def test_frontmatter_folded_description(self):
        fm, body = R.frontmatter("---\nname: a\ndescription: >\n  one two\n  three\n---\nbody\n")
        self.assertEqual(fm["description"][0], "one two three")
        self.assertEqual(body, 1)


class Recall(unittest.TestCase):
    def test_seeded_recall_and_block_recall(self):
        items = FX["seeded"]
        hit = set(matched(items))
        blocks = [i for i in items if i[2]["severity"] == "block"]
        bhit = [i for i in blocks if i[0] in hit]
        print(f"\nRECALL seeded {len(hit)}/{len(items)} = {len(hit) / len(items):.2f}; block-severity {len(bhit)}/{len(blocks)}")
        self.assertGreaterEqual(len(hit) / len(items), 0.80)
        self.assertEqual(len(bhit), len(blocks), "missed: " + ", ".join(i[0] for i in blocks if i[0] not in hit))

    def test_holdout_recall_is_reported(self):
        items = FX["holdout"]
        self.assertEqual(len(items), 6)
        hit = set(matched(items))
        print(f"\nHOLDOUT seed={SEED} recall {len(hit)}/{len(items)} = {len(hit) / len(items):.2f}; missed: "
              + (", ".join(i[0] for i in items if i[0] not in hit) or "none"))

    def test_every_rule_is_exercised_by_a_fixture(self):
        covered = {i[2]["rule"] for i in FX["seeded"]}
        # D02 needs a denylist file and S01 needs the claude CLI: both have their own tests below
        self.assertEqual(sorted({r[0] for r in R.RULES} - covered), ["D02-denylist", "S01-claude-validate"])

    def test_deleting_a_rule_drops_recall(self):
        items = FX["seeded"]
        before = len(matched(items))
        by_rule = {}
        for it in items:
            by_rule.setdefault(it[2]["rule"], []).append(it)
        for rid, group in sorted(by_rule.items()):
            with self.subTest(rid), mock.patch.object(R, "RULES", [r for r in R.RULES if r[0] != rid]):
                self.assertEqual(matched(group), [], f"{rid} still matched after it was removed")
        biggest = max(by_rule, key=lambda k: len(by_rule[k]))
        with mock.patch.object(R, "RULES", [r for r in R.RULES if r[0] != biggest]):
            after = len(matched(items))
        print(f"\nTEST-THE-TEST removed {biggest} (covers {len(by_rule[biggest])}): recall {before}/{len(items)} -> {after}/{len(items)}")
        self.assertLessEqual(after, before - len(by_rule[biggest]))
        self.assertLess(after, before)


class Intake(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(dir=TMP))

    def refused(self, entries, rule, name="x.zip", **kw):
        z = make_zip(self.d / name, entries)
        rep = RP.review(z, "all")
        self.assertTrue(rep["refused"], rep["findings"])
        self.assertIn(rule, {f["rule"] for f in rep["findings"]})
        self.assertEqual(rep["verdict"], "refused")
        return rep

    def test_zip_slip_variants(self):
        for entry in ("../evil.txt", "..\\evil.txt", "a/../../evil.txt", "/abs/evil.txt", "C:/evil.txt", "C:\\evil.txt", "a/b:stream"):
            with self.subTest(entry):
                self.refused([("ok.txt", "x"), (entry, "pwn")], "X01-zip-slip")
        self.assertFalse((TMP / "evil.txt").exists() or (self.d.parent / "evil.txt").exists())

    def test_zip_bomb_by_ratio(self):
        self.refused([("big.txt", b"\0" * (6 << 20))], "X02-zip-bomb")

    def test_zip_bomb_by_entry_count(self):
        with mock.patch.object(RP, "MAX_ENTRIES", 5):
            self.refused([(f"f{i}.txt", "x") for i in range(8)], "X02-zip-bomb")

    def test_zip_symlink_entry(self):
        z = self.d / "link.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zi = zipfile.ZipInfo("alias")
            zi.create_system = 3
            zi.external_attr = 0o120777 << 16
            zf.writestr(zi, "../../etc/passwd")
        rep = RP.review(z, "all")
        self.assertIn("X03-zip-symlink", {f["rule"] for f in rep["findings"]})

    def test_windows_device_names(self):
        self.refused([("con.txt", "x")], "X04-reserved-device-name")

    def test_wrapped_plugin_archive_is_reviewed_and_scratch_removed(self):
        entries = [("acme-notes/" + str(p.relative_to(FX["clean"])).replace("\\", "/"), p.read_bytes())
                   for p in sorted(FX["clean"].rglob("*")) if p.is_file()]
        for ext in (".zip", ".plugin"):
            z = make_zip(self.d / ("acme" + ext), entries)
            made = []
            real = tempfile.mkdtemp

            def spy(*a, **k):
                made.append(real(*a, **k))
                return made[-1]
            with mock.patch.object(RP.tempfile, "mkdtemp", spy):
                rep = RP.review(z, "all")
            self.assertEqual((rep["kind"], rep["verdict"]), ("plugin", "ship"), bad(rep))
            self.assertTrue(made and not any(Path(m).exists() for m in made))

    def test_skill_archive(self):
        z = make_zip(self.d / "notes.skill", [("notes/SKILL.md", MF.SKILL)])
        rep = RP.review(z, "web")
        self.assertEqual(rep["kind"], "skills")
        self.assertEqual(bad(rep), [])
        self.assertNotIn("F01-nonportable-key", {f["rule"] for f in rep["findings"]})

    def test_unpack_flag_extracts_safely_for_the_model_pass(self):
        py = [sys.executable, "-I", str(SCRIPTS / "review_plugin.py")]
        good = make_zip(self.d / "g.zip", [("acme/README.md", "hello"), ("acme/skills/a/SKILL.md", MF.SKILL)])
        r = subprocess.run(py + [str(good), "--unpack", str(self.d / "out")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((Path(r.stdout.strip()) / "README.md").is_file())
        evil = make_zip(self.d / "e.zip", [("../escape.txt", "x")])
        r = subprocess.run(py + [str(evil), "--unpack", str(self.d / "out2")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("X01-zip-slip", r.stderr)
        self.assertFalse((self.d / "out2").exists() or (self.d / "escape.txt").exists())
        self.assertEqual(subprocess.run(py + [str(good), "--unpack", str(self.d / "out")], capture_output=True, timeout=60).returncode, 2)

    def test_judgment_step_command_is_hardened(self):
        """MAJ9: the model pass goes through the hardened runner; its argv must carry the isolation flags."""
        runner = HERE.parents[1] / "repo-review" / "scripts" / "run_review.py"
        rubric = HERE.parent / "references" / "REVIEW.md"
        self.assertTrue(runner.is_file() and rubric.is_file())
        r = subprocess.run([sys.executable, "-I", str(runner), "--local", str(FX["clean"]), "--rubric", str(rubric),
                            "--out", str(self.d / "o"), "--print-argv"], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = json.loads(r.stdout)
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--setting-sources", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "user")

    def test_not_an_archive_is_a_usage_error(self):
        (self.d / "a.txt").write_text("x")
        with self.assertRaises(FileNotFoundError):
            RP.review(self.d / "a.txt")
        self.assertEqual(RP.main([str(self.d / "missing")]), 2)

    def test_nothing_in_the_input_runs(self):
        hostile = self.d / "hostile"
        shutil.copytree(FX["clean"], hostile)
        marker = self.d / "PWNED"
        code = f"open({str(marker)!r}, 'w').write('x')\n"
        for rel in ("scripts/pwn.py", "setup.py", "conftest.py", "sitecustomize.py", "usercustomize.py", "__init__.py", "json.py", "re.py"):
            (hostile / rel).write_text(code, encoding="utf-8")
        (hostile / ".mcp.json").write_text(json.dumps({"mcpServers": {"x": {"command": sys.executable, "args": [str(hostile / "scripts/pwn.py")]}}}))
        RP.review(hostile, "all")
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "review_plugin.py"), str(hostile), "--json"],
                           cwd=hostile, capture_output=True, text=True, timeout=120)
        self.assertIn("findings", json.loads(r.stdout))
        self.assertFalse(marker.exists(), "the reviewer ran code from the input")


class Batch(unittest.TestCase):
    def test_batch_writes_both_scorecards_and_children_run_isolated(self):
        d = Path(tempfile.mkdtemp(dir=TMP))
        batch = d / "in"
        batch.mkdir()
        shutil.copytree(FX["clean"], batch / "clean-one")
        shutil.copytree(FX["seeded"][0][1], batch / "defect-one")
        make_zip(batch / "slip.zip", [("../evil.txt", "x")])
        calls = []
        real = subprocess.run

        def spy(cmd, *a, **k):
            calls.append(cmd)
            return real(cmd, *a, **k)
        with mock.patch.object(RP.subprocess, "run", spy):
            rows = RP.batch(batch, d / "out")
        self.assertTrue(calls and all(c[1] == "-I" for c in calls), calls)
        self.assertEqual({r[0]: r[1] for r in rows}, {"clean-one": "ship", "defect-one": "do-not-ship", "slip.zip": "refused"})
        with open(d / "out" / "scorecard.csv", encoding="utf-8", newline="") as f:
            got = list(csv.reader(f))
        self.assertEqual(got[0], ["plugin", "verdict", "block", "hold", "warn", "note", "top_findings"])
        self.assertEqual(len(got), 4)
        md = (d / "out" / "scorecard.md").read_text(encoding="utf-8")
        self.assertIn("defect-one", md)
        self.assertIn("X01-zip-slip", md)

    def test_batch_from_a_list_file(self):
        d = Path(tempfile.mkdtemp(dir=TMP))
        lst = d / "list.txt"
        lst.write_text("# plugins\n" + str(FX["clean"]) + "\n", encoding="utf-8")
        rows = RP.batch(lst, d / "out")
        self.assertEqual([r[1] for r in rows], ["ship"])


class RuleSet(unittest.TestCase):
    def run_cli(self):
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "review_plugin.py"), str(FX["clean"]), "--json"],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_rules_sha256_is_stable_and_moves_with_a_rule(self):
        a, b = self.run_cli(), self.run_cli()
        self.assertEqual(a["rules_sha256"], b["rules_sha256"])
        self.assertEqual(len(a["rules_sha256"]), 64)
        src = Path(R.__file__).read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(R.rules_sha256(), a["rules_sha256"])
        self.assertNotEqual(R.rules_sha256(source=src.replace(b'"F05-body-length", 3, "warn"', b'"F05-body-length", 3, "hold"')), a["rules_sha256"])
        self.assertNotEqual(R.rules_sha256(rules=R.RULES[:-1]), a["rules_sha256"])

    def test_every_rule_is_documented(self):
        doc = (HERE.parents[4] / "docs" / "engineering" / "plugin-review.md").read_text(encoding="utf-8")
        self.assertEqual([r[0] for r in R.RULES if f"`{r[0]}`" not in doc], [])

    def test_skill_descriptions_stay_short(self):
        for skill in ("plugin-review", "plugin-factory", "web-packager"):
            fm = R.frontmatter((HERE.parents[1] / skill / "SKILL.md").read_text(encoding="utf-8"))[0]
            self.assertLessEqual(len(fm["description"][0]), 300, skill)

    def test_report_shape(self):
        rep = self.run_cli()
        self.assertTrue(set(rep) >= {"path", "kind", "verdict", "surfaces", "stats", "rules_sha256", "findings"})
        d = Path(tempfile.mkdtemp(dir=TMP))
        shutil.copytree(FX["seeded"][0][1], d / "p")
        rep = RP.review(d / "p")
        self.assertEqual(set(rep["findings"][0]), {"rule", "group", "file", "line", "severity", "msg"})

    def test_cli_exit_codes(self):
        py = [sys.executable, "-I", str(SCRIPTS / "review_plugin.py")]
        self.assertEqual(subprocess.run(py + [str(FX["clean"])], capture_output=True, timeout=120).returncode, 0)
        self.assertEqual(subprocess.run(py + [str(FX["seeded"][0][1])], capture_output=True, timeout=120).returncode, 1)
        self.assertEqual(subprocess.run(py + [str(TMP / "nope")], capture_output=True, timeout=120).returncode, 2)

    def test_denylist_names_the_rule_never_the_term(self):
        d = Path(tempfile.mkdtemp(dir=TMP))
        dl = d / "deny.txt"
        dl.write_text("# comment\nexample author\nre:(?i)ignore trailing\n", encoding="utf-8")
        rep = RP.review(FX["clean"], "all", denylist=dl)
        hits = [f for f in rep["findings"] if f["rule"] == "D02-denylist"]
        self.assertTrue(hits)
        for f in hits:
            self.assertRegex(f["msg"], r"denylist rule [23]$")
            self.assertNotIn("ignore trailing", f["msg"].lower())
        self.assertIn("block", {f["severity"] for f in hits})

    def test_claude_validate_is_opt_in(self):
        exe = shutil.which("claude")
        if not exe:
            self.assertFalse(REQUIRE, "claude CLI not found")
            self.skipTest("claude CLI not found")
        self.assertNotIn("S01-claude-validate", {f["rule"] for f in RP.review(FX["clean"], "cli")["findings"]})
        reserved = next(p for d, p, e in FX["seeded"] if d == "reserved_name")
        rep = RP.review(reserved, "cli", validate=True)
        self.assertIn("S01-claude-validate", {f["rule"] for f in rep["findings"]})


if __name__ == "__main__":
    unittest.main()
