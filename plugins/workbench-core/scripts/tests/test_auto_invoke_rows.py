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
    def test_diagram_and_brand_spec_rows_fire_diagram_is_model_started_brand_spec_is_user_only(self):
        for prompt, want in (("draw an architecture diagram of the nightly pipeline", "diagram"),
                             ("turn this mermaid into an excalidraw file", "diagram"),
                             ("sketch the data flow chart for the import", "diagram"),
                             ("we need a brand spec before the redesign", "brand-spec"),
                             ("write a style guide for the new product", "brand-spec")):
            self.assertIn(want, self.named(prompt), prompt)
        self.assertNotIn("diagram", ai.USER_ONLY, "the model may start diagram")
        self.assertIn("brand-spec", ai.USER_ONLY, "brand-spec is a one-time intake: hidden from the model, suggested to the user")
        self.assertIn("/workbench-core:brand-spec is user-invoked only", ai.skill_hints("we need a brand spec before the redesign")[0])
        self.assertEqual((ai.cmd("diagram"), ai.cmd("brand-spec")),
                         ("/workbench-core:diagram", "/workbench-core:brand-spec"))
        for quiet in ("what is the capital of France", "thanks", "brand new laptop arrived today"):
            self.assertEqual(set(self.named(quiet)) & {"diagram", "brand-spec"}, set(), quiet)
        for name in ("diagram", "brand-spec"):
            self.assertTrue((PLUGIN / "skills" / name / "SKILL.md").is_file(), name)

    def test_user_only_is_exactly_the_skills_that_hide_from_the_model(self):
        """USER_ONLY and `disable-model-invocation: true` must agree both ways: a skill the model cannot start is only ever
        suggested, and a skill the model can start is never described as user-only."""
        hidden = set()
        for f in PLUGIN.parent.glob("*/skills/*/SKILL.md"):
            head = f.read_text(encoding="utf-8").split("---")[1]
            if any(line.strip() == "disable-model-invocation: true" for line in head.splitlines()):
                hidden.add(f.parent.name)
        self.assertEqual(hidden, ai.USER_ONLY)
        for name in ("batch-review", "mcp-heal", "plugin-factory", "plugin-review", "web-packager", "mcp-builder",
                     "api-bridge", "app-navigator", "brand-spec"):
            self.assertIn(name, hidden, f"{name}: authoring and admin skills are hidden from the model")

    # ---- the nine skills hidden from the model keep their old trigger phrases as hints --------------------------------
    # Every quoted phrase in the v0.3.1 descriptions of the nine skills (the descriptions that told the model when to start
    # them). The model no longer sees those descriptions, so the hook is the only thing that can still say the skill exists.
    OLD_PHRASES = {
        "api-bridge": ["let Claude use this API"],
        "brand-spec": ["what should this look and feel like", "brand intake", "new product, no style guide"],
        "mcp-builder": ["build an MCP server", "build a connector for X"],
        "mcp-heal": ["/workbench-core:mcp-heal", "an MCP server is broken", "MCP tools missing", "check my MCP servers"],
        "plugin-factory": ["make a plugin", "package this plugin for the team"],
        "plugin-review": ["review this plugin", "check this skill before upload"],
        "web-packager": ["can web users use this", "package this skill for claude.ai"],
    }

    def test_every_old_description_phrase_of_the_hidden_skills_still_gets_a_hint(self):
        self.assertEqual(sum(len(v) for v in self.OLD_PHRASES.values()), 16)
        for skill, phrases in self.OLD_PHRASES.items():
            self.assertIn(skill, ai.USER_ONLY)
            for phrase in phrases:
                for prompt in (phrase, f"Hi, quick one: {phrase}, please", f"{phrase.capitalize()}?"):
                    self.assertIn(skill, self.named(prompt), prompt)
                hint = next(h for h in ai.skill_hints(phrase) if h.startswith(ai.cmd(skill)))
                self.assertIn("is user-invoked only", hint, phrase)
                self.assertIn("do not start it", hint, phrase)

    # Ordinary prompts that an earlier, broader version of the new alternatives answered with a user-only hint, plus everyday work.
    QUIET = (
        "package this for the team as a pdf", "fresh look and feel for the quarterly deck", "no style guide for these emails",
        "a connector between our crm export and the finance spreadsheet", "let the model use the api key", "we bought a connector for salesforce",
        "how do i use the api from python", "let the model use the api keys from the vault", "write a status update for the team standup",
        "reply to the email from finance about the invoice", "join these two spreadsheets on customer id",
        "summarise the meeting notes into action items", "why does this function return None when the list is empty",
        "what is the difference between a list and a tuple in python", "can you rename these files to lowercase", "check the spelling in my notes",
        "how many days until the end of the quarter", "translate this paragraph into french", "sort this column by date",
        "the build is slow on my laptop", "the MCP spec says servers use JSON-RPC", "package the report for the team to read",
        "look and listen carefully", "the Slack connector for Claude is enabled", "can users log in", "we have no budget guide",
        "upload the file to the server", "what is the capital of France", "brand new laptop arrived today",
    )

    def test_kit_update_row_fires_for_turning_approvals_off_or_on_and_nothing_else(self):
        for q in ("turn off the bash approvals", "please switch off command approvals on this laptop", "turn on approvals again",
                  "turn the guard way down", "set the guard to minimal", "I want the minimal guard"):
            self.assertIn("kit-update", self.named(q), q)
        for q in ("the approvals workflow in our PR process", "who approves the budget", "turn off the lights",
                  "switch on dark mode", "the security guard was down the hall", "a minimal example"):
            self.assertNotIn("kit-update", self.named(q), q)

    def test_the_new_hint_alternatives_stay_quiet_on_ordinary_prompts(self):
        self.assertEqual(len(self.QUIET), len(set(self.QUIET)))
        self.assertGreaterEqual(len(self.QUIET), 20)
        noisy = {q: sorted(set(self.named(q)) & ai.USER_ONLY) for q in self.QUIET if set(self.named(q)) & ai.USER_ONLY}
        self.assertEqual(noisy, {}, "a user-only hint on an ordinary prompt is noise the user pays for every turn")

    # ---- nothing the model reads tells it to start a skill it cannot start -------------------------------------------------
    AMBIGUOUS = {"setup", "cleanup", "onboard", "capture", "ingest"}      # ordinary words: only /plugin:name or a backticked `name` counts
    SUGGESTS = ("suggest", "user-invoked", "only they can start", "cannot start", "the user runs", "the user can run", "tell the user")
    STARTS = (r"\b(?:run|runs|start|starts|invoke|invokes|use|uses|load|loads|call|calls|launch|trigger|through|via|prefer|prefers|"
              r"apply|execute|kick off|hand (?:it )?(?:off )?to|delegate to)\b")
    NEGATED = r"\b(?:never|not|don't|do not|without|cannot|can't)\b"
    CLAUSE_BREAK = r"[.;:!?] |, |\) | then | and | but "

    def model_facing_files(self):
        kit = PLUGIN.parents[1]
        files = list((kit / "instructions").rglob("*.md")) + list((kit / "templates").glob("*.md")) + list(kit.glob("plugins/*/agents/*.md"))
        for skill_md in kit.glob("plugins/*/skills/*/SKILL.md"):
            if skill_md.parent.name not in ai.USER_ONLY:                     # the body of a skill only the user starts is read after the user starts it
                files += [skill_md, *skill_md.parent.glob("references/*.md")]
        return sorted(files)

    def offenders(self, text):
        """[(line, skill)]: a user-only skill's name with a verb of starting (run, use, prefer, hand off to ...) in the clause just
        before it, and nothing in that same clause saying the user starts it (suggest, tell the user ...) or forbidding it (never, not)."""
        import re
        out = []
        for name in sorted(ai.USER_ONLY):
            rx = (rf"/workbench-[a-z]+:{name}\b|`{name}`" if name in self.AMBIGUOUS
                  else rf"(?<![\w/-]){re.escape(name)}(?![\w/-])")                  # not a folder or file name
            for m in re.finditer(rx, text):
                clause = re.split(self.CLAUSE_BREAK, re.sub(r"\s+", " ", text[max(0, m.start() - 120):m.start()]))[-1]
                if (re.search(self.STARTS, clause, re.I) and not any(s in clause.lower() for s in self.SUGGESTS)
                        and not re.search(self.NEGATED, clause, re.I)):
                    out.append((text.count("\n", 0, m.start()) + 1, name))
        return sorted(set(out))

    def test_no_instruction_agent_or_model_visible_skill_tells_claude_to_start_a_user_only_skill(self):
        kit = PLUGIN.parents[1]
        bad = [f"{f.relative_to(kit).as_posix()}:{n} tells Claude to start {name}"
               for f in self.model_facing_files() for n, name in self.offenders(f.read_text(encoding="utf-8"))]
        self.assertEqual(bad, [], "a skill with disable-model-invocation cannot be started by the model: say 'suggest the user run it'")
        self.assertGreater(len(self.model_facing_files()), 30, "the scan reached the instruction, agent and skill files")

    def test_tool_routing_lists_no_user_only_skill_among_those_claude_starts(self):
        import re
        text = (PLUGIN.parents[1] / "instructions" / "rules" / "tool-routing.md").read_text(encoding="utf-8")
        started, user_only = text.split("## Skills", 1)[1].split("\n## ", 1)[0].split("- User-invoked only", 1)
        started_names = set(re.findall(r"`(?:/[\w-]+:)?([a-z][\w-]*)`", started))
        self.assertIn("cascade", started_names)
        self.assertEqual(started_names & ai.USER_ONLY, set(), "the list of skills Claude starts names a skill only the user can start")
        for name in sorted(ai.USER_ONLY):
            self.assertRegex(user_only, rf"(?<![\w-]){name}(?![\w-])", f"{name} is missing from the user-invoked-only list")

    def test_the_text_check_itself_catches_the_old_wording_and_the_new_shapes(self):
        for bad in ("- **Brand spec:** a `BRAND_SPEC.md` (from `brand-spec`) is the design system.\n  A product with neither and a look: run `brand-spec` first.\n",
                    "- Non-interactive review, judging or bulk passes go through\n  `batch-review` (Batch API: half price).\n",
                    "Review volume that needs no conversation goes through the\n  `batch-review` skill, if your organisation provides its API key.\n",
                    "Or ask Claude to run `/workbench-core:mcp-heal` for you.\n",
                    "- Prefer `batch-review` for bulk grading passes.\n",
                    "- After the review, run `cleanup` on the scratch folder.\n",
                    "- Suggest a commit message, then run `mcp-heal`.\n",
                    "- Hand it off to `/workbench-core:plugin-review` when done.\n",
                    "- For bulk passes, delegate to `batch-review`.\n",
                    "Apply `plugin-factory` to scaffold it, and tell the user it is done.\n"):
            self.assertTrue(self.offenders(bad), bad)
        for good in ("- A product with neither and a look to decide: suggest the user run `/workbench-core:brand-spec` first.\n",
                     "- Passes can use the Batch API: suggest the user run `/workbench-core:batch-review`.\n",
                     "`BRAND_SPEC.md` (see `brand-spec`), then this page.\n",
                     "- User-invoked only (the model cannot start them): `vdi-drive`, `pc-checkup`, `cleanup`.\n",
                     "- Never run a code-graph tool's `install`, `setup`, `upgrade` or `doctor`.\n",
                     "- Do not run `cleanup` yourself; the user runs it.\n",
                     "- Suggest a commit message, then suggest the user run `mcp-heal`.\n"):
            self.assertEqual(self.offenders(good), [], good)

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
