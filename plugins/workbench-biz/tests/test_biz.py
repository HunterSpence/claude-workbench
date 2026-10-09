import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: nothing below skips; a missing file or tool fails

import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[1]
KIT = PLUGIN.parents[1]
PACKAGER = KIT / "plugins/workbench-core/skills/web-packager/scripts/package_web.py"
CATALOG = KIT / "docs/business-catalog.md"
STARTER = ["requirements-to-stories", "meeting-to-actions", "status-report", "test-cases-from-requirements",
           "excel-analyst", "rfp-sow-drafter", "branded-deck", "policy-qa"]
PORTABLE = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
READ_ONLY = {"Read", "Glob", "Grep", "Skill"}
# keys the eval runner accepts per grader type (its schema is strict), plus the prompt.md keys we use
GRADER_KEYS = {"regex": {"type", "target", "pattern", "flags", "match", "weight", "arm"},
               "tool_used": {"type", "tool", "input_match", "min", "max", "weight", "arm"},
               "llm": {"type", "focus", "weight", "arm"},
               "file_exists": {"type", "path", "exists", "weight", "arm"}}
OUTCOME = {"regex", "llm", "file_exists"}
PROMPT_KEYS = {"max_turns", "timeout_seconds", "allowed_tools", "model", "runs"}


def frontmatter(path):
    """-> ({key: raw value}, body). Top-level `key: value` lines between the first two --- lines."""
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    assert lines[0] == "---", f"{path}: no frontmatter"
    end = lines.index("---", 1)
    fm = {}
    for ln in lines[1:end]:
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", ln)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm, "\n".join(lines[end + 1:])


def plugin_files():
    return [p for p in PLUGIN.rglob("*") if p.is_file() and "__pycache__" not in p.parts]


class Portable(unittest.TestCase):
    def test_manifest(self):
        m = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        kit = json.loads((PLUGIN.parents[1] / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual((m["name"], m["version"]), ("workbench-biz", kit["metadata"]["version"]))   # the kit's one version
        self.assertNotIn("userConfig", m)
        for forbidden in ("bin", "hooks", ".mcp.json", "settings.json", "agents"):
            self.assertFalse((PLUGIN / forbidden).exists(), forbidden)

    def test_skills_are_exactly_the_starter_pack(self):
        self.assertEqual(sorted(p.name for p in (PLUGIN / "skills").iterdir()), sorted(STARTER))

    def test_frontmatter_six_fields_and_description_limit(self):
        for s in STARTER:
            fm, body = frontmatter(PLUGIN / "skills" / s / "SKILL.md")
            self.assertLessEqual(set(fm), PORTABLE, f"{s}: non-portable key")
            self.assertEqual(fm["name"], s)
            d = fm["description"]
            self.assertTrue(0 < len(d) <= 250, f"{s}: description is {len(d)} characters")
            # a plain YAML scalar breaks on ": " or " #"; claude.ai parses real YAML
            self.assertNotIn(": ", d, s)
            self.assertNotIn(" #", d, s)
            self.assertNotRegex(d, r"[<>]")
            self.assertLess(len(body.split("\n")), 120, f"{s}: body too long")

    def test_instructions_use_no_network_or_installs(self):
        bad = re.compile(r"pip3? install|npm (install|i )|curl |wget |Invoke-WebRequest|https?://|\bsudo\b|\bBash\b|PowerShell", re.I)
        for p in (PLUGIN / "skills").rglob("*.md"):
            for n, ln in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
                self.assertIsNone(bad.search(ln), f"{p.relative_to(PLUGIN)}:{n}: {ln[:80]}")

    def test_no_price_is_filled_in(self):
        t = (PLUGIN / "skills/rfp-sow-drafter/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("[RATE: set by a human]", t)
        self.assertIsNone(re.search(r"[$£€]\s?\d", t))

    def test_package_web_check_passes_each_skill_and_the_plugin(self):
        self.assertTrue(PACKAGER.is_file(), "web-packager is missing from the tree")
        for target in [PLUGIN] + [PLUGIN / "skills" / s for s in STARTER]:
            r = subprocess.run([sys.executable, "-I", str(PACKAGER), str(target), "--check", "--json"],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, f"{target.name}: {r.stdout[:600]}")
            out = json.loads(r.stdout)
            self.assertTrue(out["portable"], target.name)
            self.assertEqual([f for f in out["findings"] if f["severity"] in ("block", "hold")], [], target.name)


class Evals(unittest.TestCase):
    def case(self, name):
        d = PLUGIN / "evals" / name
        fm, body = frontmatter(d / "prompt.md")
        self.assertLessEqual(set(fm), PROMPT_KEYS, name)
        self.assertTrue(body.strip(), f"{name}: empty prompt")
        tools = {t.strip() for t in fm["allowed_tools"].strip("[]").split(",") if t.strip()}
        self.assertTrue(tools and tools <= READ_ONLY, f"{name}: text-only cases may grant only {sorted(READ_ONLY)}")
        self.assertGreaterEqual(int(fm.get("runs", "3")), 3, name)
        graders = []
        for g in sorted((d / "graders").glob("*.md")):
            gfm, gbody = frontmatter(g)
            kind = gfm.get("type")
            self.assertIn(kind, GRADER_KEYS, f"{g.name}: unknown grader type")
            self.assertLessEqual(set(gfm), GRADER_KEYS[kind], f"{g.name}: key the runner rejects")
            if kind in ("regex", "llm"):
                self.assertTrue(gbody.strip(), f"{g.name}: empty body")
            if kind == "regex":
                re.compile(gbody.strip())
            graders.append((kind, gfm))
        self.assertTrue(any(k in OUTCOME for k, _ in graders), f"{name}: needs an outcome grader, not only tool_used")
        return graders

    def test_every_skill_has_a_case_with_graders(self):
        for s in STARTER:
            graders = self.case(s)
            fired = [g for k, g in graders if k == "tool_used" and g["tool"] == "Skill" and s in g.get("input_match", "")]
            self.assertTrue(fired, f"{s}: no tool_used Skill grader naming the skill")
            self.assertTrue(any(k == "llm" for k, _ in graders), f"{s}: no llm outcome grader")

    def test_one_negative_case_and_no_strays(self):
        graders = self.case("negative-unrelated")
        self.assertTrue(any(k == "tool_used" and g["tool"] == "Skill" and g.get("min") == "0" and g.get("max") == "0"
                            and g.get("arm") == "both" for k, g in graders))
        self.assertEqual(sorted(p.name for p in (PLUGIN / "evals").iterdir()), sorted(STARTER + ["negative-unrelated"]))


class Catalog(unittest.TestCase):
    def test_catalog_lists_built_and_specs_the_rest(self):
        t = CATALOG.read_text(encoding="utf-8")
        for s in STARTER:
            self.assertIn(f"`{s}`", t)
        self.assertIn("`plugin-preflight`", t)
        specs = re.split(r"(?m)^### ", t.split("## Specs", 1)[1])[1:]
        self.assertGreaterEqual(len(specs), 12)
        for spec in specs:
            for label in ("Trigger:", "Inputs:", "Output:", "Eval sketch:"):
                self.assertIn(label, spec, spec.split("\n")[0])


class Privacy(unittest.TestCase):
    """Cheap shape checks; the full term list is the private denylist, run through tools/scrub_scan.py."""

    def test_no_ip_numbers_dates_or_real_looking_addresses(self):
        for p in plugin_files() + [CATALOG]:
            if p.suffix.lower() not in {".md", ".json", ".py", ".txt"}:
                continue
            t = p.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", t), f"{p.name}: dotted-quad number")
            self.assertIsNone(re.search(r"(?<!\d)20\d\d-\d\d-\d\d(?!\d)", t), f"{p.name}: ISO date")
            for addr in re.findall(r"[\w.+-]+@([\w-]+\.[\w.-]+)", t):
                self.assertIn(addr.lower(), {"example.com", "example.org"}, f"{p.name}: address domain {addr}")


if __name__ == "__main__":
    unittest.main()
