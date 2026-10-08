import json, os, sys, tempfile, unittest

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


if __name__ == "__main__":
    unittest.main()
