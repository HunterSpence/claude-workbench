"""Presence tests for the settings profiles: each key v0.3.2 added is in the profile(s) that should carry it, with the
value the docs name, and settings/SETTINGS.md explains it. Run: python -m unittest discover -s settings"""
import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILES = ("corporate", "permissive")


def profile(name):
    return json.loads((HERE / "profiles" / f"{name}.fragment.json").read_text(encoding="utf-8"))


def rows(heading):
    """The table rows (as text) under one '## heading' of SETTINGS.md."""
    text = (HERE / "SETTINGS.md").read_text(encoding="utf-8")
    body = text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    return [x for x in body.splitlines() if x.startswith("| `")]


def row(heading, key):
    found = [r for r in rows(heading) if r.startswith(f"| `{key}` ")]
    assert len(found) == 1, f"{key}: {len(found)} rows under {heading!r}"
    return found[0]


class Profiles(unittest.TestCase):
    def test_skill_listing_budget_fraction_is_a_number_in_both_profiles(self):
        for name in PROFILES:
            v = profile(name).get("skillListingBudgetFraction")
            self.assertIs(type(v), float, f"{name}: a number, as the settings reference types it")
            self.assertEqual(v, 0.02, name)
            self.assertTrue(0 < v <= 1, name)

    def test_mcp_timeout_is_60000_in_both_profiles(self):
        for name in PROFILES:
            self.assertEqual(profile(name)["env"].get("MCP_TIMEOUT"), "60000", name)

    def test_msys2_arg_conv_excl_is_the_three_prefixes_in_both_profiles(self):
        for name in PROFILES:
            self.assertEqual(profile(name)["env"].get("MSYS2_ARG_CONV_EXCL"), "origin/;upstream/;refs/", name)
            self.assertNotEqual(profile(name)["env"]["MSYS2_ARG_CONV_EXCL"], "*", "the blanket form turns every conversion off")

    def test_no_server_wide_tokensave_allow_in_either_profile(self):
        for name in PROFILES:
            allow = profile(name).get("permissions", {}).get("allow", [])
            self.assertEqual([a for a in allow if a.startswith("mcp__tokensave")], [], name)
            self.assertIn("Edit(*)" if name == "permissive" else "WebSearch", allow, f"{name}: the rest of the allow list is intact")

    def test_every_env_value_is_a_string(self):
        for name in PROFILES:
            bad = {k: v for k, v in profile(name)["env"].items() if not isinstance(v, str)}
            self.assertEqual(bad, {}, f"{name}: Claude Code env values are strings")


class Docs(unittest.TestCase):
    def test_both_profiles_table_has_a_row_for_each_new_key(self):
        for key in ("skillListingBudgetFraction", "env.MCP_TIMEOUT", "env.MSYS2_ARG_CONV_EXCL"):
            self.assertTrue(row("Both profiles", key).count("|") >= 5, key)
        self.assertIn("0.02", row("Both profiles", "skillListingBudgetFraction"))
        self.assertIn("60000", row("Both profiles", "env.MCP_TIMEOUT"))
        self.assertIn("origin/;upstream/;refs/", row("Both profiles", "env.MSYS2_ARG_CONV_EXCL"))

    def test_the_msys2_row_shows_the_form_that_is_really_rewritten(self):
        """Verified on Git 2.55 with the variable unset: `origin/main:/abs/x` -> `origin\\main;C:\\...`; `origin/main:path` is never rewritten."""
        r = row("Both profiles", "env.MSYS2_ARG_CONV_EXCL")
        self.assertIn("origin/main:/path", r)
        self.assertIn("`origin\\main;C:\\...`", r)
        self.assertIn("refs/heads/a:/b", r)
        self.assertIn("never rewritten", r)
        self.assertNotIn("git show origin/main:path", r, "the old example is a form Git Bash never rewrites")

    def test_the_listing_fraction_is_documented_as_a_ceiling_with_the_overflow_reason(self):
        r = row("Both profiles", "skillListingBudgetFraction")
        self.assertRegex(r, r"ceiling, not a cost")
        self.assertIn("30,000", r)
        self.assertNotRegex(r, r"\d\d,\d{3} characters against")   # no measured figure from one machine

    def test_mcp_timeout_left_the_differ_table_and_tokensave_left_the_allow_row(self):
        self.assertEqual([r for r in rows("Where the profiles differ") if r.startswith("| `env.MCP_TIMEOUT`")], [])
        cells = [c.strip() for c in row("Where the profiles differ", "permissions.allow").split("|")]
        self.assertNotIn("mcp__tokensave", cells[3], "the permissive cell no longer lists the server-wide allow")
        self.assertIn("mcp__tokensave", cells[4], "the why column explains the missing rule")
        self.assertIn("server-wide", cells[4])

    def test_the_skill_overrides_row_says_plugin_skills_are_out_of_reach_and_where_the_kit_tiers(self):
        r = row("Optional keys (in neither profile; add them if your policy asks)", "skillOverrides")
        for want in ("never the kit's", "plugin skills are not affected", "disable-model-invocation: true",
                     "docs/token-diet.md", "never overwrites a value you set"):
            self.assertIn(want, r)


if __name__ == "__main__":
    unittest.main()
