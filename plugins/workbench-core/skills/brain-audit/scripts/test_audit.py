import json, os, subprocess, sys, tempfile, time, unittest

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: a missing dependency fails instead of skipping (none is needed here)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class AuditTest(unittest.TestCase):
    def test_findings(self):
        with tempfile.TemporaryDirectory() as h:
            w(os.path.join(h, "CLAUDE.md"), "\n".join(["Core.", "@" "rules-extra.md", "@" "missing.md", "`@" "literal.md` is not an import.",
                                               "Use /cascade and /nosuchskill.", "```", "@" "fenced.md /fencedroute", "```", ""]))
            w(os.path.join(h, "rules-extra.md"), "extra\n")
            w(os.path.join(h, "rules", "a.md"), "always\n")
            w(os.path.join(h, "rules", "b.md"), "---\npaths:\n  - src/**\n---\nscoped\n")
            w(os.path.join(h, "skills", "cascade", "SKILL.md"), "---\nname: cascade\n---\n")
            w(os.path.join(h, "agents", "_archive-old", "x.md"), "old persona\n")
            w(os.path.join(h, "settings.json.bak-1"), "{}")
            w(os.path.join(h, "settings.json"), json.dumps({
                "env": {"SOME_API_KEY": "literal-value", "SAFE": "1", "REF_TOKEN": "<YOUR_TOKEN>"},
                "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python /nonexistent/dir/guard.py"}]}]}}))
            F = audit.audit(h)
            text = json.dumps(F)
            got = lambda sev, needle: any(f["severity"] == sev and needle in f["finding"] for f in F)
            self.assertTrue(got("HIGH", "archive folder"), text)
            self.assertTrue(got("CRITICAL", "credential-bearing"), text)
            self.assertTrue(got("MEDIUM", "dead @import -> missing.md"), text)
            self.assertFalse(any("literal.md" in f["finding"] or "fenced" in f["finding"] for f in F), "code imports/routes must be ignored")
            self.assertTrue(got("INFO", "path-scoped"), text)
            self.assertTrue(got("LOW", "/nosuchskill"), text)
            self.assertFalse(any("/cascade" in f["finding"] for f in F), "installed skill must not be flagged")
            self.assertTrue(got("HIGH", "hook target missing"), text)
            self.assertTrue(got("HIGH", "env.SOME_API_KEY"), text)
            self.assertFalse(any("REF_TOKEN" in f["finding"] for f in F), "placeholder must not be flagged")
            self.assertNotIn("literal-value", text, "a credential value must never be printed")
            size = next(f for f in F if "always-loaded" in f["finding"])
            self.assertIn("3 files", size["finding"])  # CLAUDE.md + import + unconditional rule; scoped rule excluded


LONG = "Run the full test suite before every merge and read the failures, never only the summary line."
OTHER = "Keep each change small enough that one reviewer can hold the whole diff in mind at once."


class SurfaceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.h = os.path.join(self._tmp.name, "home")
        self.proj = os.path.join(self._tmp.name, "proj")
        os.makedirs(self.h)
        os.makedirs(self.proj)
        self.addCleanup(self._tmp.cleanup)

    def sf(self, project=None, **kw):
        r = audit.surface(self.h, project, **kw)
        self.assertEqual(set(r), {"surface", "exit"})
        self.assertEqual(set(r["surface"]), {"bytes", "core_lines", "rules_over_cap", "paths_rules", "duplicates",
                                             "dead_refs", "generated_drift", "hidden_skills"})
        return r

    def settings(self, folder, data, name="settings.json"):
        w(os.path.join(folder, name), json.dumps(data))

    def test_a_clean_surface_exits_zero_and_lists_scoped_rules_as_information(self):
        w(os.path.join(self.h, "CLAUDE.md"), "Short core.\n")
        w(os.path.join(self.h, "rules", "a.md"), "always\n")
        w(os.path.join(self.h, "rules", "b.md"), "---\npaths:\n  - src/**\n---\n" + "scoped line\n" * 300)
        r = self.sf()
        self.assertEqual(r["exit"], 0, r)
        self.assertEqual([os.path.basename(x) for x in r["surface"]["paths_rules"]], ["b.md"])
        self.assertEqual(r["surface"]["rules_over_cap"], [], "a path-scoped rule is not counted against the cap")
        self.assertEqual(r["surface"]["core_lines"], 2)
        self.assertGreater(r["surface"]["bytes"], 0)

    def test_long_files_are_flagged(self):
        w(os.path.join(self.h, "CLAUDE.md"), "line\n" * 250)
        w(os.path.join(self.h, "rules", "long.md"), "rule\n" * 250)
        r = self.sf()
        self.assertEqual(r["exit"], 1)
        self.assertEqual(r["surface"]["core_lines"], 251)
        self.assertEqual([(os.path.basename(x["file"]), x["lines"], x["cap"]) for x in r["surface"]["rules_over_cap"]], [("long.md", 251, 200)])
        self.assertEqual(self.sf(max_lines=300)["exit"], 0, "the cap is an option")

    def test_the_same_line_in_two_places_is_reported_by_location_not_text(self):
        secret_like = "Set the deploy " + "API_TOKEN=" + "abc123" * 4 + " in the shell before the release step."
        w(os.path.join(self.h, "CLAUDE.md"), f"# Core\n- {LONG}\n{secret_like}\nShort line.\n```\n{OTHER}\n{OTHER}\n```\n")
        w(os.path.join(self.h, "rules", "a.md"), f"# Rules\n1. {LONG.upper()}\n{secret_like}\nShort line.\n{OTHER}\n")
        r = self.sf()
        dups = r["surface"]["duplicates"]
        self.assertEqual(len(dups), 2, dups)             # LONG (list marker and case ignored) and the secret-like line; fenced OTHER and short lines are not
        self.assertEqual({d["count"] for d in dups}, {2})
        self.assertEqual(r["exit"], 1)
        text = json.dumps(r)
        self.assertNotIn("abc123" * 4, text, "a duplicate is reported by file:line and digest, never by its text")
        self.assertNotIn("full test suite", text)
        self.assertTrue(all(len(d["id"]) == 8 and all(":" in a for a in d["at"]) for d in dups))
        F = audit.audit(self.h)
        self.assertEqual(sum(1 for f in F if "appears 2 times" in f["finding"]), 2)

    def test_a_line_repeated_inside_one_file_counts(self):
        w(os.path.join(self.h, "CLAUDE.md"), f"{LONG}\nsomething else entirely\n{LONG}\n")
        self.assertEqual([d["count"] for d in self.sf()["surface"]["duplicates"]], [2])

    def test_hidden_skills_include_off_and_user_only_but_not_name_only(self):
        w(os.path.join(self.h, "CLAUDE.md"), "Use /alpha for A, `/beta` for B, /gamma for C, /delta for D, /plug for E.\n"
                                              "```\n/fenced is only an example\n```\n")
        for n in ("alpha", "beta", "gamma", "delta", "fenced"):
            w(os.path.join(self.h, "skills", n, "SKILL.md"), f"---\nname: {n}\n---\n")
        w(os.path.join(self.h, "plugins", "installed_plugins.json"), json.dumps({"plugins": {"vendor@m": [{"installPath": os.path.join(self.h, "pl")}]}}))
        w(os.path.join(self.h, "pl", "skills", "plug", "SKILL.md"), "---\nname: plug\n---\n")
        self.settings(self.h, {"skillOverrides": {"alpha": "off", "beta": "user-invocable-only", "gamma": "name-only",
                                                   "delta": "on", "plug": "off", "fenced": "off"}})
        hidden = {(x["skill"], x["state"]) for x in self.sf()["surface"]["hidden_skills"]}
        self.assertEqual(hidden, {("alpha", "off"), ("beta", "user-invocable-only")})
        r = self.sf()
        self.assertEqual(r["exit"], 1)
        F = audit.audit(self.h)
        self.assertTrue(any(f["severity"] == "MEDIUM" and "/alpha" in f["finding"] and "\"off\"" in f["finding"] for f in F), F)

    def test_a_project_local_setting_hides_a_skill_and_wins_over_the_user_setting(self):
        w(os.path.join(self.proj, "CLAUDE.md"), "Run /ship when the branch is ready.\n")
        w(os.path.join(self.proj, ".claude", "skills", "ship", "SKILL.md"), "---\nname: ship\n---\n")
        self.settings(self.h, {"skillOverrides": {"ship": "off"}})
        self.settings(os.path.join(self.proj, ".claude"), {"skillOverrides": {"ship": "on"}}, "settings.local.json")
        self.assertEqual(self.sf(self.proj)["surface"]["hidden_skills"], [])
        self.settings(os.path.join(self.proj, ".claude"), {"skillOverrides": {"ship": "off"}}, "settings.local.json")
        got = self.sf(self.proj)["surface"]["hidden_skills"]
        self.assertEqual([(x["skill"], x["state"]) for x in got], [("ship", "off")])
        self.assertTrue(got[0]["set_in"].endswith("settings.local.json"))

    def test_dead_imports_and_routes_are_listed(self):
        w(os.path.join(self.h, "CLAUDE.md"), "@" "missing.md\nUse /nosuchskill now.\n")
        refs = {(x["kind"], x["ref"]) for x in self.sf()["surface"]["dead_refs"]}
        self.assertEqual(refs, {("import", "missing.md"), ("route", "/nosuchskill")})

    def test_generated_files_that_are_orphaned_or_stale_are_listed(self):
        w(os.path.join(self.h, "CLAUDE.md"), "<!-- Generated by `make-docs` from `src/list.json` and `src/gone.json`. -->\nBody.\n")
        w(os.path.join(self.h, "src", "list.json"), "{}")
        old = time.time() - 5 * 86400
        os.utime(os.path.join(self.h, "CLAUDE.md"), (old, old))
        got = {(x["source"], x["kind"]) for x in self.sf()["surface"]["generated_drift"]}
        self.assertEqual(got, {("src/list.json", "stale"), ("src/gone.json", "orphan")})

    def test_the_command_line_prints_json_and_exits_with_the_same_code(self):
        w(os.path.join(self.h, "CLAUDE.md"), "Use /nosuchskill now.\n")
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit.py"),
                            "--home", self.h, "--surface", "--json"], capture_output=True, text=True, encoding="utf-8")
        out = json.loads(r.stdout)
        self.assertEqual((r.returncode, out["exit"]), (1, 1))
        self.assertEqual(out["surface"]["dead_refs"][0]["ref"], "/nosuchskill")
        w(os.path.join(self.h, "CLAUDE.md"), "Nothing to flag.\n")
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit.py"),
                            "--home", self.h, "--surface"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("Report only", r.stdout)


if __name__ == "__main__":
    unittest.main()
