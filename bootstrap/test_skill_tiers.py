"""K2: the skill listing measured on the machine and tiered. Fake skill trees and a fake settings.json in a temp folder: nothing
here reads this PC's Claude home, settings or registry. Names are fictional.
Run: python -m unittest discover -s bootstrap -p "test_skill_tiers.py" -v"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import install as I  # noqa: E402
import setup as S  # noqa: E402
import skill_tiers as ST  # noqa: E402

WINDOWS_ONLY = unittest.skipUnless(os.name == "nt" or os.environ.get("WB_REQUIRE_ALL") == "1", "fake .cmd programs need Windows")


def put_skill(base, folder, name=None, size=100, when="", hidden=False):
    d = Path(base) / folder
    d.mkdir(parents=True, exist_ok=True)
    fm = f"---\nname: {name or folder}\ndescription: {'d' * size}\n" + (f"when_to_use: {when}\n" if when else "") \
        + ("disable-model-invocation: true\n" if hidden else "") + "---\n\n# body\n"
    (d / "SKILL.md").write_text(fm, encoding="utf-8")


USER = (("routedskill", 1400), ("bigone", 1500), ("midone", 1000), ("smallone", 200), ("pmone", 300), ("pmtwo", 250),
        ("extraone", 1500))          # the pack skills are small on purpose: only "packs first" puts them in the changes


class World(unittest.TestCase):
    """A Claude home with the kit's plugins enabled, user, project and org-synced skills, and a kit folder whose instructions route
    to one user skill and whose lock files name two pack skills."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-tiers-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ch, self.kit, self.cwd = self.tmp / "claude", self.tmp / "kit", self.tmp / "project"
        for d in (self.ch, self.kit, self.cwd):
            d.mkdir()
        for i in range(14):                                    # the kit's own skills: 14 x (1,500 + name) characters
            put_skill(self.kit / "plugins" / "workbench-core" / "skills", f"kit{i:02d}", size=1500)
        put_skill(self.kit / "plugins" / "workbench-core" / "skills", "typed-by-user", size=900, hidden=True)
        (self.kit / "instructions" / "rules").mkdir(parents=True)
        (self.kit / "instructions" / "rules" / "tool-routing.md").write_text(
            "Use `routedskill` for prose a person reads. Use /workbench-kb:save to save.\n", encoding="utf-8")
        (self.kit / "tools" / "fetch-upstream").mkdir(parents=True)
        (self.kit / "tools" / "fetch-upstream" / "upstream.pm.lock.json").write_text(json.dumps({"sources": [{"id": "pm-pack", "files": [
            ["x/skills/pmone/SKILL.md", "pmone/SKILL.md", "00"], ["x/LICENSE", "pmone/LICENSE", "00"],
            ["x/skills/pmtwo/SKILL.md", "pmtwo/SKILL.md", "00"]]}]}), encoding="utf-8")
        self.settings = {"enabledPlugins": {"workbench-core@workbench": True}, "model": "model-x",
                         "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}}
        self.write_settings(self.settings)
        sk = self.ch / "skills"
        for folder, size in USER:
            put_skill(sk, folder, size=size)
        put_skill(sk / "synced" / "org_user", "orgskill", size=1500)
        put_skill(self.cwd / ".claude" / "skills", "projskill", size=700)

    def write_settings(self, d, name="settings.json"):
        (self.ch / name).write_text(json.dumps(d, indent=2), encoding="utf-8")

    def measure(self, allowance=0, env=None):
        return ST.measure(self.ch, self.kit, self.cwd, env={} if env is None else env, allowance=allowance)

    def size(self, info, key):
        return next(s["size"] for s in info["skills"] if s["key"] == key)


class Measure(World):
    def test_every_source_is_counted_and_hidden_skills_cost_nothing(self):
        info = self.measure()
        g = info["groups"]
        self.assertEqual(g["kit plugins"], 14 * (len("workbench-core:kit00") + 1500), "a typed-only skill adds nothing")
        self.assertEqual(self.size(info, "workbench-core:typed-by-user"), 0)
        self.assertEqual(g["user skills"], sum(len(n) + s for n, s in USER))
        self.assertEqual(g["org-synced skills"], len("orgskill") + 1500)
        self.assertEqual(g["project skills"], len("projskill") + 700)
        self.assertEqual(g["other plugins"], 0)
        self.assertEqual(info["total"], sum(g.values()))
        self.assertEqual(self.measure(allowance=ST.ALLOWANCE)["total"], info["total"] + ST.ALLOWANCE)

    def test_custom_commands_are_skills_too_the_users_can_be_tiered_a_plugins_cannot(self):
        (self.ch / "commands").mkdir()
        (self.ch / "commands" / "mycmd.md").write_text("---\ndescription: " + "c" * 300 + "\n---\nbody\n", encoding="utf-8")
        pc = self.kit / "plugins" / "workbench-core" / "commands"
        pc.mkdir()
        (pc / "plugcmd.md").write_text("---\ndescription: " + "p" * 200 + "\n---\nbody\n", encoding="utf-8")
        info = self.measure()
        by = {s["key"]: s for s in info["skills"]}
        self.assertEqual(by["mycmd"]["size"], len("mycmd") + 300)
        self.assertFalse(by["mycmd"]["plugin"])
        self.assertEqual((by["workbench-core:plugcmd"]["size"], by["workbench-core:plugcmd"]["plugin"]), (len("workbench-core:plugcmd") + 200, True))

    def test_description_plus_when_to_use_is_cut_at_the_entry_cap_and_name_only_and_hiding_overrides_count(self):
        put_skill(self.ch / "skills", "huge", size=5000, when="w" * 80)
        self.write_settings({**self.settings, "skillOverrides": {"smallone": "name-only", "midone": "off", "bigone": "user-invocable-only"}})
        info = self.measure()
        self.assertEqual(self.size(info, "huge"), len("huge") + ST.ENTRY_CAP)
        self.assertEqual(self.size(info, "smallone"), len("smallone"))
        self.assertEqual((self.size(info, "midone"), self.size(info, "bigone")), (0, 0))

    def test_an_enabled_plugin_other_than_the_kits_is_found_through_installed_plugins_json(self):
        other = self.tmp / "cache" / "other"
        put_skill(other / "skills", "otherskill", size=300)
        (self.ch / "plugins").mkdir()
        (self.ch / "plugins" / "installed_plugins.json").write_text(json.dumps(
            {"version": 2, "plugins": {"other-plugin@market": [{"scope": "user", "installPath": str(other), "version": "1"}]}}), encoding="utf-8")
        self.write_settings({**self.settings, "enabledPlugins": {"workbench-core@workbench": True, "other-plugin@market": True,
                                                                  "gone@market": True, "off@market": False}})
        info = self.measure()
        self.assertEqual(info["groups"]["other plugins"], len("other-plugin:otherskill") + 300)

    def test_the_limit_is_30000_scales_with_the_fraction_and_an_env_budget_is_the_limit(self):
        self.assertEqual(self.measure()["limit"], 30000)
        self.write_settings({**self.settings, "skillListingBudgetFraction": 0.02})
        self.assertEqual(self.measure()["limit"], 60000)
        self.assertEqual(self.measure(env={"SLASH_COMMAND_TOOL_CHAR_BUDGET": "12345"})["limit"], 12345)
        self.assertEqual(ST.limit_chars(self.ch, {}, {"skillListingBudgetFraction": 0.03})[0], 90000, "a managed value wins")


class Plan(World):
    def test_over_80_percent_packs_go_name_only_then_the_largest_others_until_under_and_routed_stay_on(self):
        info = self.measure()
        self.assertGreater(info["total"], 0.8 * info["limit"])
        plan = ST.plan(info, self.kit)
        ch = plan["changes"]
        self.assertTrue({"pmone", "pmtwo"} <= set(ch), "the pack skills go first, small as they are")
        self.assertNotIn("routedskill", ch)
        self.assertIn("routedskill", plan["kept_on"])
        self.assertEqual(set(ch.values()), {"name-only"})
        self.assertLessEqual(plan["after"], 0.8 * info["limit"])
        self.assertTrue(plan["reached"])
        others = [n for n in ch if n not in ("pmone", "pmtwo")]
        sizes = {s["name"]: s["size"] for s in info["skills"]}
        untouched = [sizes[n] for n in ("bigone", "midone", "smallone", "projskill", "orgskill", "extraone") if n not in ch]
        self.assertEqual(sorted(others), ["bigone", "extraone", "midone", "orgskill"], "the org-synced skill is tiered like the others")
        self.assertEqual(sorted(untouched), [208, 709], "largest first: what was left is smaller than everything taken")
        self.assertLess(max(untouched), min(sizes[n] for n in others))
        self.assertEqual(plan["after"], plan["before"] - sum(sizes[n] - len(n) for n in ch))
        plugin_names = {s["name"] for s in info["skills"] if s["plugin"]}
        self.assertFalse(plugin_names & set(ch), "a plugin skill is never tiered: skillOverrides does not apply to it")
        self.assertTrue(plugin_names and all(s["size"] for s in info["skills"] if s["plugin"] and not s["hidden"]))

    def test_a_raised_limit_does_not_raise_the_aim_a_lower_one_lowers_it_and_the_warning_follows_the_real_limit(self):
        self.write_settings({**self.settings, "skillListingBudgetFraction": 0.02})
        info = self.measure()
        self.assertEqual(info["limit"], 60000)
        plan = ST.plan(info, self.kit)
        self.assertEqual(plan["goal"], 24000)
        self.assertTrue(plan["changes"] and plan["reached"] and plan["after"] <= 24000, plan)
        self.assertEqual(ST.row(info)[0], "OK", "49% of the real limit")
        self.assertEqual(ST.row(dict(info, total=int(0.84 * 60000)))[0], "OK")
        self.assertEqual(ST.row(dict(info, total=int(0.85 * 60000)))[0], "WARN", "the 85% warning is against the real limit")
        low = self.measure(env={"SLASH_COMMAND_TOOL_CHAR_BUDGET": "20000"})
        self.assertEqual(ST.plan(low, self.kit)["goal"], 16000, "a lower limit lowers the aim")

    def test_a_skill_is_routed_only_when_the_instructions_call_it_by_name_not_when_they_use_the_word(self):
        (self.kit / "instructions" / "rules" / "more.md").write_text(
            "Run QA before release. Ask for a review. Use `humanizer`, /workbench-kb:save and /qa-extra; humanizerx is not it.\n",
            encoding="utf-8")
        got = ST.routed(self.kit, {"qa", "review", "humanizer", "save", "qa-extra", "pmone", "human"})
        self.assertEqual(got, {"humanizer", "save", "qa-extra"})

    def test_under_80_percent_changes_nothing(self):
        shutil.rmtree(self.ch / "skills")
        info = self.measure()
        self.assertLessEqual(info["total"], 0.8 * info["limit"])
        plan = ST.plan(info, self.kit)
        self.assertEqual((plan["changes"], plan["reached"]), ({}, True))

    def test_a_value_the_user_set_is_kept_unless_force(self):
        self.write_settings({**self.settings, "skillOverrides": {"bigone": "on", "midone": "name-only", "pmone": "off"}})
        info = self.measure()
        plan = ST.plan(info, self.kit)
        self.assertNotIn("bigone", plan["changes"])
        self.assertIn("bigone", plan["user_set"])
        self.assertNotIn("pmone", plan["changes"], "a skill the user switched off is not made visible again")
        self.assertNotIn("midone", plan["changes"] if plan["changes"].get("midone") != "name-only" else {}, "already name-only")
        forced = ST.plan(info, self.kit, force=True)
        self.assertEqual(forced["changes"].get("bigone"), "name-only")
        self.assertNotIn("pmone", forced["changes"])

    def test_when_every_skill_that_could_change_is_exhausted_the_target_is_reported_unreached(self):
        for i in range(10):
            put_skill(self.kit / "plugins" / "workbench-core" / "skills", f"more{i:02d}", size=1500)
        info = self.measure()
        plan = ST.plan(info, self.kit)
        self.assertFalse(plan["reached"])
        self.assertGreater(plan["after"], 0.8 * info["limit"])

    def test_row_warns_from_85_percent_and_the_public_detail_has_no_skill_names(self):
        info = self.measure()
        status, detail, public = ST.row(info)
        self.assertEqual(status, "WARN")
        self.assertIn("workbench-core:kit00", detail)
        self.assertEqual(len(detail.split("top: ")[1].split("; Claude")[0].split(", ")), 5, "the top five contributors")
        for name in ("bigone", "orgskill", "routedskill", "kit00"):
            self.assertNotIn(name, public)
        self.assertIn(f"{info['total']:,} of 30,000", public)
        ok = dict(info, total=int(0.84 * info["limit"]))
        self.assertEqual(ST.row(ok)[0], "OK")
        self.assertEqual(ST.row(dict(info, total=int(0.85 * info["limit"])))[0], "WARN")


class SetupStep(World):
    """do_skill_tiers: the write itself, in-process, against the fake Claude home."""
    def setUp(self):
        super().setUp()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("WORKBENCH_", "WB_", "OneDrive"))}
        env.update(CLAUDE_CONFIG_DIR=str(self.ch), USERPROFILE=str(self.tmp), HOME=str(self.tmp), LOCALAPPDATA=str(self.tmp / "lad"),
                   WORKBENCH_MANAGED_SETTINGS=str(self.tmp / "no-managed.json"), WORKBENCH_FAKE_REGISTRY=str(self.tmp / "reg.json"))
        (self.tmp / "reg.json").write_text("{}")
        for p in (mock.patch.dict(os.environ, env, clear=True), mock.patch.object(S, "KIT", self.kit),
                  mock.patch.object(Path, "cwd", return_value=self.cwd), mock.patch.object(ST, "ALLOWANCE", 0)):
            p.start()
            self.addCleanup(p.stop)

    def user(self):
        return json.loads((self.ch / "settings.json").read_text(encoding="utf-8"))

    def test_over_80_percent_writes_name_only_keeps_everything_else_backs_up_first_and_records_the_undo(self):
        shutil.rmtree(self.kit / "plugins" / "workbench-core" / "skills" / "kit13")       # so the aim is reachable round the user's "on"
        self.write_settings({**self.settings, "skillListingBudgetFraction": 0.0102,
                             "skillOverrides": {"extraone": "on", "midone": "name-only"}})
        before = (self.ch / "settings.json").read_bytes()
        ctx = S.Ctx()
        lines = S.do_skill_tiers(ctx)
        after = self.user()
        ov = after["skillOverrides"]
        self.assertEqual(ov["extraone"], "on", "a value the user set is untouched")
        self.assertEqual(ov["midone"], "name-only")
        self.assertEqual({k: v for k, v in ov.items() if k not in ("extraone", "midone")},
                         {"pmone": "name-only", "pmtwo": "name-only", "orgskill": "name-only", "bigone": "name-only"})
        self.assertIn("skillListingBudgetFraction 0.0102", lines[0], "the limit follows the fraction setting")
        self.assertTrue(any("left as set" in x and "extraone" in x for x in lines))
        self.assertNotIn("routedskill", ov)
        self.assertFalse([k for k in ov if k.startswith("workbench")], "no plugin skill")
        self.assertEqual({k: v for k, v in after.items() if k not in ("skillOverrides", "skillListingBudgetFraction")}, self.settings,
                         "no other key moved")
        backup = next((ctx.wb / "backups").glob("*-skill-tiers/settings.json"))
        self.assertEqual(backup.read_bytes(), before, "the backup is the file as it was")
        self.assertTrue(any("set " in x and "name-only" in x for x in lines))
        self.assertTrue(any(x.startswith("org-synced skills:") for x in lines), "the unverified org-synced case is said out loud")
        self.assertTrue((ctx.state_dir / "skill-tiers.md").is_file())
        self.assertTrue([n for n in ctx.notes if n.startswith("skill tiers:")])
        led = [e for e in S.Ctx().ledger()["entries"] if e.get("key") == S.TIERS_KEY]
        self.assertEqual((len(led), led[0]["kind"]), (1, "settings"))
        again = S.do_skill_tiers(S.Ctx())                          # idempotent: the second run changes nothing
        self.assertEqual(self.user(), after)
        self.assertTrue(any("no tiers needed" in x or "nothing to tier" in x for x in again), again)
        S.undo_config(apply=True)                                  # the user's own values stay, ours go
        self.assertEqual(self.user()["skillOverrides"], {"extraone": "on", "midone": "name-only"})

    def test_the_field_tree_with_a_raised_budget_fraction_is_still_tiered_to_80_percent_of_30000(self):
        self.write_settings({**self.settings, "skillListingBudgetFraction": 0.02})
        ctx = S.Ctx()
        lines = S.do_skill_tiers(ctx)
        self.assertIn("60,000", lines[0])
        self.assertIn("skillListingBudgetFraction 0.02", lines[0])
        self.assertFalse(any("no tiers needed" in x for x in lines), lines)
        ov = self.user()["skillOverrides"]
        self.assertTrue({"pmone", "pmtwo", "orgskill"} <= set(ov), ov)
        info = ST.measure(self.ch, self.kit, self.cwd, env={}, allowance=0)
        self.assertLessEqual(info["total"], 0.8 * 30000)

    def test_under_80_percent_writes_nothing_and_makes_no_backup(self):
        shutil.rmtree(self.ch / "skills")
        before = (self.ch / "settings.json").read_bytes()
        ctx = S.Ctx()
        S.do_skill_tiers(ctx)
        self.assertEqual((self.ch / "settings.json").read_bytes(), before)
        self.assertFalse((ctx.wb / "backups").exists())

    def test_force_replaces_a_value_the_user_set_and_dry_run_writes_nothing(self):
        self.write_settings({**self.settings, "skillOverrides": {"bigone": "on"}})
        before = (self.ch / "settings.json").read_bytes()
        S.do_skill_tiers(S.Ctx(), dry=True)
        self.assertEqual((self.ch / "settings.json").read_bytes(), before)
        S.do_skill_tiers(S.Ctx(), force=True)
        self.assertEqual(self.user()["skillOverrides"]["bigone"], "name-only")

    def test_a_settings_file_that_is_not_json_is_left_alone(self):
        (self.ch / "settings.json").write_text("{broken", encoding="utf-8")
        ctx = S.Ctx()
        self.assertEqual(S.do_skill_tiers(ctx), [])
        self.assertEqual((self.ch / "settings.json").read_text(encoding="utf-8"), "{broken")
        self.assertTrue([n for n in ctx.notes if "not valid JSON" in n])


@WINDOWS_ONLY
class Cli(unittest.TestCase):
    """The same step through the real command line, with the setup test suite's fake programs and registry."""
    @classmethod
    def setUpClass(cls):
        import test_setup as T
        cls.T = T
        cls.tmp = Path(tempfile.mkdtemp(prefix="wb-kit-"))
        cls.kit = T.mini_kit(cls.tmp / "kit")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def env(self):
        e = self.T.FakeEnv(kit=self.kit, scenario={"wsl": "installed", "distros": ["Ubuntu-24.04"]})
        self.addCleanup(e.close)
        for i in range(1, 14):                                  # 13 skills of 1,500 characters + the bundled-skill allowance: over 85%
            put_skill(e.ch / "skills", f"skill{i:02d}", size=1500)
        return e

    def doctor_row(self, e):
        d = e.run("doctor", "--json")
        return next(x for x in json.loads(d.stdout[:d.stdout.rindex("}") + 1])["rows"] if x["check"] == "skill listing")

    def test_the_skills_command_the_doctor_row_and_a_full_run_agree(self):
        e = self.env()
        r = e.run("skills", "--dry-run", code=0)
        self.assertIn("would set 2 of your own skill(s) to name-only", r.stdout)
        self.assertEqual(r.stdout.count("would set 2"), 1)
        self.assertNotIn("would set", r.stderr, "the lines are printed once, not again through the log")
        self.assertFalse((e.ch / "settings.json").exists(), "a dry run writes nothing")
        row = self.doctor_row(e)
        self.assertEqual(row["status"], "WARN")
        self.assertIn("setup.py skills", row["detail"])
        e.run("run", code=0)
        self.assertEqual(json.loads((e.ch / "settings.json").read_text(encoding="utf-8"))["skillOverrides"], {"skill01": "name-only", "skill02": "name-only"},
                         "largest first, and it stops once under 80%")
        self.assertTrue([n for n in e.state().get("notes") or [] if n.startswith("skill tiers:")])
        marker = json.loads((e.wb / "state" / "post-update-verify.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["version"], I.VERSION, "a finished setup run leaves the post-update marker")
        self.assertEqual(self.doctor_row(e)["status"], "OK", "after the tiers the doctor row is satisfied")


if __name__ == "__main__":
    unittest.main()
