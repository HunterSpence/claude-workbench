import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_catalog as sc


class ScanCatalogTest(unittest.TestCase):
    def test_skill_dirs_treats_pack_as_one_and_skips_archives(self):
        with tempfile.TemporaryDirectory() as r:
            for p in ("a/SKILL.md", "a/sub/SKILL.md", "b/SKILL.md", "_archive_old/c/SKILL.md"):
                os.makedirs(os.path.join(r, os.path.dirname(p)), exist_ok=True)
                open(os.path.join(r, p), "w").close()
            self.assertEqual(sorted(sc.skill_dirs(r, "s")), ["s/a", "s/b"])

    def test_delta_flags_new_and_increased_only(self):
        rows = [{"skill": "x", "status": "OK", "high_signal": 2},
                {"skill": "y", "status": "OK", "high_signal": 1},
                {"skill": "z", "status": "OK", "high_signal": 1},
                {"skill": "q", "status": "OK", "high_signal": 0},
                {"skill": "e", "status": "SCAN_ERROR"}]
        flagged = sc.delta(rows, {"x": 1, "y": 1})
        self.assertEqual(sorted(r["skill"] for r in flagged), ["x", "z"])
        self.assertEqual(rows[2]["delta"], "NEW")
        self.assertEqual(rows[3]["delta"], 0)


if __name__ == "__main__":
    unittest.main()
