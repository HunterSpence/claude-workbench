"""Tests for the auto-invoke rows added with the diagram and brand-spec skills: the two kit rows, the rows for skills
the kit does not ship (named only when installed), the always-on claude-api row, and the extra wrap-up phrases. Run:
    python -m unittest discover -s plugins/workbench-core/scripts/tests
The config dir is a temp folder in every test: nothing here reads the real ~/.claude."""
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
PLUGIN = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import auto_invoke as ai  # noqa: E402

EXTERNAL_PROMPTS = {
    "humanizer": ["rewrite this draft so it sounds more natural", "please humanize the intro paragraph",
                  "edit my post, it reads like an AI wrote it", "before finalizing the email, check the tone"],
    "playwright-cli": ["take a screenshot of this page", "click through the signup flow in a browser test",
                       "use playwright to open the dashboard"],
    "grilling": ["grill me on this rollout plan", "stress-test my plan for the migration", "poke holes in the design"],
}


class Rows(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-rows-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "claude"
        self.home.mkdir()
        patcher = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def skill(self, where, name):
        d = self.home / where / name if where == "skills" else self.home / "plugins" / "cache" / where / "skills" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n", encoding="utf-8")

    def named(self, prompt):
        """The skill names in the hints for one prompt."""
        out = []
        for h in ai.skill_hints(prompt):
            tok = h.split(" ", 1)[0]
            out.append(tok.rsplit(":", 1)[-1].lstrip("/"))
        return out

    # ---- the two kit skills ----------------------------------------------------------------------------------------
    def test_diagram_and_brand_spec_rows_fire_and_are_not_user_only(self):
        for prompt, want in (("draw an architecture diagram of the nightly pipeline", "diagram"),
                             ("turn this mermaid into an excalidraw file", "diagram"),
                             ("sketch the data flow chart for the import", "diagram"),
                             ("we need a brand spec before the redesign", "brand-spec"),
                             ("write a style guide for the new product", "brand-spec")):
            self.assertIn(want, self.named(prompt), prompt)
        self.assertFalse({"diagram", "brand-spec"} & ai.USER_ONLY, "both skills may be started by the model")
        self.assertEqual((ai.cmd("diagram"), ai.cmd("brand-spec")),
                         ("/workbench-core:diagram", "/workbench-core:brand-spec"))
        for quiet in ("what is the capital of France", "thanks", "brand new laptop arrived today"):
            self.assertEqual(set(self.named(quiet)) & {"diagram", "brand-spec"}, set(), quiet)
        for name in ("diagram", "brand-spec"):
            self.assertTrue((PLUGIN / "skills" / name / "SKILL.md").is_file(), name)

    # ---- rows for skills the kit does not ship ---------------------------------------------------------------------
    def test_external_rows_stay_silent_until_the_skill_is_installed(self):
        for name, prompts in EXTERNAL_PROMPTS.items():
            for p in prompts:
                self.assertNotIn(name, self.named(p), f"{name} is not installed: no hint for {p!r}")

    def test_external_rows_fire_for_a_user_skill_or_a_plugin_cache_copy(self):
        for where, label in (("skills", "user"), ("mkt/plug/1.0.0", "cache")):
            for name, prompts in EXTERNAL_PROMPTS.items():
                self.skill(where, name)
                for p in prompts:
                    self.assertIn(name, self.named(p), f"{label} copy of {name}: {p!r}")
            shutil.rmtree(self.home / "skills", ignore_errors=True)
            shutil.rmtree(self.home / "plugins", ignore_errors=True)

    def test_installed_counts_only_a_real_skill_file(self):
        self.assertFalse(ai.installed("humanizer"))
        (self.home / "skills" / "humanizer").mkdir(parents=True)                       # folder without SKILL.md
        self.assertFalse(ai.installed("humanizer"))
        self.skill("temp_git_123/plug/9", "humanizer")                                  # a half-finished clone
        self.assertFalse(ai.installed("humanizer"))
        (self.home / "plugins" / "cache" / "mkt" / "plug" / "1").mkdir(parents=True)    # a version dir without the skill
        self.assertFalse(ai.installed("humanizer"))
        self.skill("mkt/plug/2", "humanizer")
        self.assertTrue(ai.installed("humanizer"))
        self.assertFalse(ai.installed("grilling"))

    def test_the_installed_check_is_fast_on_a_busy_cache(self):
        for m in range(4):
            for p in range(5):
                for v in range(3):
                    (self.home / "plugins" / "cache" / f"mkt{m}" / f"plug{p}" / f"v{v}" / "skills" / "other").mkdir(parents=True)
        times = []
        for _ in range(7):
            t = time.perf_counter()
            self.assertFalse(ai.installed("humanizer"))      # a miss scans everything: the worst case
            times.append((time.perf_counter() - t) * 1000)
        self.assertLess(min(times), 5.0, f"60 version dirs took {min(times):.2f} ms at best")

    def test_external_names_get_a_bare_slash_command_and_the_sets_agree(self):
        rows = {n for n, _, _ in ai.SKILLS}
        self.assertTrue(ai.INSTALLED_ONLY <= ai.EXTERNAL <= rows)
        self.assertEqual(ai.EXTERNAL - ai.INSTALLED_ONLY, {"claude-api"}, "only the built-in skill is always on")
        for n in ai.EXTERNAL:
            self.assertEqual(ai.cmd(n), "/" + n)
        self.assertEqual(ai.cmd("save"), "/workbench-kb:save")      # the old mapping is untouched

    def test_claude_api_row_is_always_on_and_narrow(self):
        for p in ("what does Claude Opus cost per token on the batch API", "how big is the context window of sonnet 5",
                  "help me build an eval for the support bot", "set up prompt caching with the Anthropic SDK"):
            self.assertIn("claude-api", self.named(p), p)
        for p in ("create a new claude plugin", "claude code keeps asking for permission", "fix the parser", "avoid eval() in the parser"):
            self.assertNotIn("claude-api", self.named(p), p)
        self.assertIn("never from memory", [h for h in ai.skill_hints("what is the model pricing") if "claude-api" in h][0])

    def test_at_most_three_hints_and_priority_order_still_hold(self):
        p = "draw a diagram, build a new ui page, find the latest version of the pricing doc, review the repo read-only, grill me"
        self.skill("skills", "grilling")
        hints = ai.skill_hints(p)
        self.assertEqual(len(hints), ai.MAX_HINTS)
        order = [n for n, _, _ in ai.SKILLS]
        got = [order.index(h.split(" ", 1)[0].rsplit(":", 1)[-1].lstrip("/")) for h in hints]
        self.assertEqual(got, sorted(got))

    # ---- wrap-up phrases ---------------------------------------------------------------------------------------------
    def test_wrapup_gains_good_night_and_hand_it_off(self):
        for p in ("ok good night", "Goodnight!", "can you hand it off to a fresh session", "hand this off please"):
            self.assertTrue(ai.WRAPUP.search(p), p)
        for p in ("the hand-off protocol is described in section 4", "he handed it over", "good morning", "hand me the file"):
            self.assertFalse(ai.WRAPUP.search(p), p)
        for old in ("I'm done for today", "that's it for now", "ok, let's wrap up", "write a handoff"):
            self.assertTrue(ai.WRAPUP.search(old), old)

    # ---- through the real hook process -------------------------------------------------------------------------------
    def run_hook(self, prompt):
        env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.home)}
        r = subprocess.run([sys.executable, "-S", str(SCRIPTS / "auto_invoke.py")], capture_output=True, text=True, env=env,
                           encoding="utf-8", timeout=60,
                           input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""

    def test_hook_process_end_to_end(self):
        self.assertEqual(self.run_hook("rewrite this draft so it sounds more natural"), "")
        self.skill("skills", "humanizer")
        self.assertIn("/humanizer (", self.run_hook("rewrite this draft so it sounds more natural"))
        ctx = self.run_hook("ok good night")
        self.assertIn("/workbench-kb:save", ctx)
        self.assertIn("/workbench-core:diagram (", self.run_hook("sketch an architecture diagram"))
        self.assertIn("/claude-api (", self.run_hook("which Anthropic model is cheapest"))


if __name__ == "__main__":
    unittest.main()
