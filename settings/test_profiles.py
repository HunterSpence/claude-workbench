"""Tests for the settings profiles: each key the kit sets is in the profile(s) that should carry it, with the value the docs
name, and settings/SETTINGS.md explains it. Also: the minimal permission rules (I5), the subagent-model key, the merge that
keeps a user's own values, and the routing table in instructions/rules/model-policy.md against settings/model-routing.json.

Run (WB_REQUIRE_ALL=1: a missing dependency fails, nothing skips): python -m unittest settings/test_profiles.py -v
"""
import importlib.util
import json
import os
import re
import unittest
from pathlib import Path

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: a missing dependency fails here instead of skipping

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
PROFILES = ("corporate", "permissive")
POLICY = KIT / "instructions" / "rules" / "model-policy.md"
POLICY_MAX_BYTES = 3450          # I9 budget for the always-loaded model policy (LF bytes)

# The command patterns of the minimal ask set (I5 a): each is written as Bash(...) and as PowerShell(...).
COMMAND_PATTERNS = [
    "git push *--force*", "git push -f*", "git push * -f*", "git push * +*", "git push +*",
    "git * push *--force*", "git * push -f*", "git * push * -f*", "git * push * +*",
    "gh repo delete *", "gh release delete *",
]
# The 14 secret-file reads that earlier releases denied. No profile carries them any more, as a deny or an ask; the
# installer's retired-rules list takes them out of an older install's settings. Copied byte for byte from 0.3.4.
OLD_SECRET_READS = [
    "Read(//**/.env)", "Read(//**/.env.*)", "Read(//**/*.pem)", "Read(//**/*.key)", "Read(//**/*.pfx)", "Read(//**/*.p12)",
    "Read(~/.ssh/**)", "Read(~/.aws/**)", "Read(~/.azure/**)", "Read(~/.kube/**)", "Read(~/.config/gcloud/**)",
    "Read(~/.docker/config.json)", "Read(~/.git-credentials)", "Read(~/.netrc)",
]
WORD = "gu" + "ard"              # built from pieces so this file holds no hit for the repository-wide search
NOTE = "no " + WORD + " hook"    # the one deliberate note SETTINGS.md carries
FAMILY = {"Opus": "claude-opus-5-5", "Sonnet": "claude-sonnet-5-5", "Haiku": "claude-haiku-5-5"}


def need(ok, msg):
    """A missing dependency fails under WB_REQUIRE_ALL=1 and skips otherwise."""
    if not ok:
        if REQUIRE:
            raise AssertionError(msg)
        raise unittest.SkipTest(msg)


def profile(name):
    return json.loads((HERE / "profiles" / f"{name}.fragment.json").read_text(encoding="utf-8"))


def settings_text():
    return (HERE / "SETTINGS.md").read_text(encoding="utf-8")


def rows(heading):
    """The table rows (as text) under one '## heading' of SETTINGS.md."""
    body = settings_text().split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    return [x for x in body.splitlines() if x.startswith("| `")]


def row(heading, key):
    found = [r for r in rows(heading) if r.startswith(f"| `{key}` ")]
    assert len(found) == 1, f"{key}: {len(found)} rows under {heading!r}"
    return found[0]


def rule_matches(pattern, command):
    """PROXY of Claude Code's Bash rule matcher, from the permissions page (E40): `*` stands in for any text, and a
    trailing ' *' that is the rule's only wildcard also matches the bare command. It is a stand-in, not the real matcher:
    the real check is the live probe, run in a Claude Code session with the profile applied."""
    if re.fullmatch(re.escape(pattern).replace(r"\*", ".*"), command, re.S):
        return True
    return pattern.endswith(" *") and "*" not in pattern[:-1] and command == pattern[:-2]


def asks_matching(command, patterns=COMMAND_PATTERNS):
    return [p for p in patterns if rule_matches(p, command)]


def models_md_ids():
    """Every model id the kit's models page shows: the overview table's API id column and the generated ids block."""
    text = (KIT / "docs" / "models.md").read_text(encoding="utf-8")
    ids = set(re.findall(r"^\| Claude [^|]+\| `([^`]+)` \|", text, re.M))
    block = text.split("<!-- begin:ids -->", 1)[1].split("<!-- end:ids -->", 1)[0]
    return ids | set(re.findall(r"`(claude-[a-z]+-\d+(?:-\d+)*)`", block))


def load_install():
    path = KIT / "bootstrap" / "install.py"
    need(path.is_file(), "bootstrap/install.py is missing")
    spec = importlib.util.spec_from_file_location("wb_install_for_profiles", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


class ModelTuning(unittest.TestCase):
    def test_corporate_subagent_model_is_an_id_from_the_models_doc(self):
        got = profile("corporate")["env"].get("CLAUDE_CODE_SUBAGENT_MODEL")
        self.assertEqual(got, "claude-sonnet-5-5")
        self.assertIn(got, models_md_ids(), "an id in docs/models.md's id table")
        self.assertEqual(profile("permissive")["env"].get("CLAUDE_CODE_SUBAGENT_MODEL"), got, "both profiles agree")

    def test_corporate_performance_keys(self):
        p = profile("corporate")
        for key, want in (("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", "75"), ("ENABLE_TOOL_SEARCH", "auto:1")):
            self.assertEqual(p["env"].get(key), want, key)
        self.assertNotIn("ENABLE_PROMPT_CACHING_1H", p["env"], "optional and off in corporate (SETTINGS.md)")
        self.assertEqual(profile("permissive")["env"].get("ENABLE_PROMPT_CACHING_1H"), "1", "permissive keeps its earlier value")
        self.assertEqual(p.get("subagentPromptCacheTtl"), "5m")
        self.assertEqual(p["permissions"]["defaultMode"], "default", "corporate keeps prompting")

    def test_no_profile_forces_the_subagent_model_or_sets_the_effort_overrides(self):
        for name in PROFILES:
            text = (HERE / "profiles" / f"{name}.fragment.json").read_text(encoding="utf-8")
            for banned in ("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_EFFORT_LEVEL", "--effort"):
                self.assertNotIn(banned, text, f"{name}: {banned}")
        self.assertNotIn("includeGitInstructions", profile("corporate"), "the built-in git instructions stay on for corporate")

    def test_fable_effort_is_high_in_both_profiles(self):
        for name in PROFILES:
            self.assertEqual(profile(name)["modelSettings"]["claude-fable-5-1"], {"effortLevel": "high"}, name)

    def test_the_merge_keeps_a_users_own_model_and_subagent_model(self):
        install = load_install()
        for name in PROFILES:
            user = {"model": "claude-haiku-5-5", "env": {"CLAUDE_CODE_SUBAGENT_MODEL": "haiku"}}
            ops, notes = [], []
            install.merge_settings(user, profile(name), {}, False, ops, notes)
            self.assertEqual(user["model"], "claude-haiku-5-5", name)
            self.assertEqual(user["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "haiku", name)
            self.assertIn("env.CLAUDE_CODE_SUBAGENT_MODEL", [n[0] for n in notes], f"{name}: the kept value is reported")
            self.assertIn("MCP_TIMEOUT", user["env"], f"{name}: the rest of the profile still merges")
        fresh = {}
        install.merge_settings(fresh, profile("corporate"), {}, False, [], [])
        self.assertEqual(fresh["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "claude-sonnet-5-5", "positive control: a fresh file gets it")


class PermissionRules(unittest.TestCase):
    def test_both_profiles_carry_the_same_minimal_asks_and_no_deny(self):
        a, b = profile("corporate")["permissions"], profile("permissive")["permissions"]
        self.assertEqual(a["ask"], b["ask"])
        want = [f"Bash({c})" for c in COMMAND_PATTERNS] + [f"PowerShell({c})" for c in COMMAND_PATTERNS]
        self.assertEqual(a["ask"], want)
        self.assertEqual(len(a["ask"]), 22)
        self.assertEqual(len(set(a["ask"])), 22, "no duplicate")
        for name, perms in (("corporate", a), ("permissive", b)):
            self.assertNotIn("deny", perms, f"{name}: the only deny is the installer's active-context rule")

    def test_eleven_command_patterns_per_shell_and_no_read_rule(self):
        ask = profile("corporate")["permissions"]["ask"]
        for shell in ("Bash", "PowerShell"):
            got = [x[len(shell) + 1:-1] for x in ask if x.startswith(shell + "(")]
            self.assertEqual(got, COMMAND_PATTERNS, shell)
            self.assertEqual(len(got), 11, shell)
        self.assertEqual([x for x in ask if not x.startswith(("Bash(", "PowerShell("))], [], "no Read or other tool rule")

    def test_the_old_secret_reads_are_retired_on_upgrade(self):
        """An older install's 14 secret-file denies leave settings.json through the retired-rules list (kit strings only)."""
        retired = json.loads((KIT / "bootstrap" / "retired-rules.json").read_text(encoding="utf-8"))
        self.assertEqual([r for r in OLD_SECRET_READS if r not in retired["deny"]], [])
        for name in PROFILES:
            self.assertEqual([r for r in OLD_SECRET_READS if r in json.dumps(profile(name))], [], name)

    def test_matcher_proxy_ordinary_and_outward_commands_ask_nothing(self):
        """PROXY (see rule_matches): everyday commands, and the publish, upload, secret and visibility commands earlier
        releases asked about, match none of the 11 patterns."""
        for cmd in ("git push origin main", "git push", "git push -u origin feature", "git -C x push origin main",
                    "git status", "git commit -m fix", "gh repo view x", "gh pr create --fill", "npm install",
                    "npm publish", "pnpm publish --access public", "twine upload dist/*", "dotnet nuget push a.nupkg",
                    "gh repo edit x --visibility public", "gh secret set TOKEN", "gh secret delete TOKEN", "gh gist create f",
                    "scp a host:b", "sftp host", "docker push img:tag", "aws s3 cp a s3://b/c", "gsutil cp a gs://b",
                    "az storage blob upload --file f", "rsync -a a b", "curl -T f https://example.com/x", "gh release list"):
            self.assertEqual(asks_matching(cmd), [], cmd)

    def test_matcher_proxy_force_push_and_delete_commands_ask(self):
        """PROXY (see rule_matches): the irreversible commands each match at least one pattern, bare and with arguments."""
        for cmd in ("git push --force origin main", "git push -f", "git push origin +main", "git push +main", "git -C x push --force origin main",
                    "git push origin main --force-with-lease", "git -c user.name=x push -f origin main", "git -C x push origin +main",
                    "gh repo delete x", "gh repo delete", "gh release delete v1", "gh release delete v1 --yes"):
            self.assertTrue(asks_matching(cmd), cmd)

    def test_matcher_proxy_positive_control_a_removed_pattern_stops_matching(self):
        """The test can fail: without its pattern, the command it covered is no longer matched."""
        fewer = [p for p in COMMAND_PATTERNS if p != "git push * +*"]
        self.assertTrue(asks_matching("git push origin +main"))
        self.assertEqual(asks_matching("git push origin +main", fewer), [])
        bare = [p for p in COMMAND_PATTERNS if p != "git push +*"]
        self.assertEqual(asks_matching("git push +main"), ["git push +*"])
        self.assertEqual(asks_matching("git push +main", bare), [])

    def test_settings_md_lists_every_rule_and_the_limits(self):
        text = settings_text()
        section = text.split("## Permission rules\n", 1)[1].split("\n## ", 1)[0]
        for c in COMMAND_PATTERNS:
            self.assertIn(c, section, c)
        self.assertNotIn("Read(", section, "no read rule is listed")
        for want in ("Edit(//", "active-context.md", "critical path", "allowManagedPermissionRulesOnly",
                     "a shell or MCP write is not stopped", "bash -c", "alias", "git push -uf", NOTE):
            self.assertIn(want, section, want)
        self.assertEqual(text.count(NOTE), 1, "one deliberate note, no more")
        self.assertNotRegex(text.replace(NOTE, ""), "(?i)" + WORD)


class RoutingTable(unittest.TestCase):
    """The table in the always-loaded model policy must equal the first choice of every row of settings/model-routing.json."""

    def table(self):
        found = re.findall(r"^\| ([A-Z]+): [^|]+\| ([\w-]+) \| (Opus|Sonnet|Haiku) (\w+) \|$", POLICY.read_text(encoding="utf-8"), re.M)
        return [("R-" + t.lower(), persona, FAMILY[fam], effort) for t, persona, fam, effort in found]

    def test_table_equals_the_first_choices_row_by_row(self):
        routing = json.loads((HERE / "model-routing.json").read_text(encoding="utf-8"))["rows"]
        want = [(r["id"], r["persona"], r["chain"][0]["model"], r["chain"][0]["effort"]) for r in routing]
        self.assertEqual(self.table(), want)
        self.assertEqual(len(want), 12)

    def test_policy_stays_inside_its_budget_with_lf_line_endings(self):
        raw = POLICY.read_bytes()
        self.assertNotIn(b"\r", raw, "LF line endings")
        self.assertLessEqual(len(raw), POLICY_MAX_BYTES)

    def test_policy_keeps_the_pointers_and_the_fable_rule(self):
        text = POLICY.read_text(encoding="utf-8")
        for want in ("Unsure? One row up", "step down that row's chain", "docs/token-diet.md", "_shared/digests/models-and-tokens",
                     "Fable 5.1 only when the user names it", "offer it, never route to it"):
            self.assertIn(want, text, want)


class Docs(unittest.TestCase):
    def test_both_profiles_table_has_a_row_for_each_new_key(self):
        for key in ("skillListingBudgetFraction", "env.MCP_TIMEOUT", "env.MSYS2_ARG_CONV_EXCL", "env.CLAUDE_CODE_SUBAGENT_MODEL",
                    "env.CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", "env.ENABLE_TOOL_SEARCH", "subagentPromptCacheTtl"):
            self.assertTrue(row("Both profiles", key).count("|") >= 5, key)
        r = row("Where the profiles differ", "env.ENABLE_PROMPT_CACHING_1H")
        for want in ("not set (optional)", "off in corporate", "5 to 60 minute idle gaps", "twice the input price (E32, fetched Oct 2026)"):
            self.assertIn(want, r, want)
        self.assertEqual([x for x in rows("Both profiles") if x.startswith("| `env.ENABLE_PROMPT_CACHING_1H`")], [])
        self.assertIn("0.02", row("Both profiles", "skillListingBudgetFraction"))
        self.assertIn("60000", row("Both profiles", "env.MCP_TIMEOUT"))
        self.assertIn("origin/;upstream/;refs/", row("Both profiles", "env.MSYS2_ARG_CONV_EXCL"))

    def test_the_subagent_model_row_carries_the_version_caveat_and_the_force_warning(self):
        r = row("Both profiles", "env.CLAUDE_CODE_SUBAGENT_MODEL")
        for want in ("claude-sonnet-5-5", "2.1.251", "claude --version", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "Explore",
                     "general-purpose", "(E36, fetched Oct 2026)"):
            self.assertIn(want, r, want)
        for key in ("env.CLAUDE_CODE_SUBAGENT_MODEL", "subagentPromptCacheTtl"):
            self.assertEqual([x for x in rows("Where the profiles differ") if x.startswith(f"| `{key}`")], [], f"{key} moved to both")

    def test_the_fable_level_and_claude_code_defaults_are_documented(self):
        r = row("Both profiles", "modelSettings")
        self.assertRegex(r, r"Fable 5\.1 `high`")
        self.assertIn("(E38, fetched Oct 2026)", r)

    def test_deny_row_is_gone_and_the_ask_row_points_at_the_rules_section(self):
        self.assertEqual([x for x in rows("Both profiles") if x.startswith("| `permissions.deny`")], [])
        r = row("Both profiles", "permissions.ask")
        self.assertIn("Permission rules", r)
        self.assertIn("22", r)

    def test_no_markdown_row_carries_an_iso_date(self):
        self.assertNotRegex(settings_text(), r"(?<![0-9])20\d\d-\d\d-\d\d(?![0-9])")

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
