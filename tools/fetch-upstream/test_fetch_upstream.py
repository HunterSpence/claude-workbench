import hashlib, json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_upstream as fu

H = lambda b: hashlib.sha256(b).hexdigest()
FILES = {"https://x/a/SKILL.md": b"---\nname: a\n---\n", "https://x/a/LICENSE": b"MIT License"}


def lock(files=None, license_="MIT"):
    files = files or [["SKILL.md", "a/SKILL.md", H(FILES["https://x/a/SKILL.md"])],
                      ["LICENSE", "a/LICENSE", H(FILES["https://x/a/LICENSE"])]]
    return {"sources": [{"id": "a", "license": license_, "upstream": "o/a", "ref": "v1", "commit": "c0ffee",
                         "base": "https://x/a/", "note": "n", "files": files}]}


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.skills, self.bak = os.path.join(self.d, "skills"), os.path.join(self.d, "bak")
        self.calls = []

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def get(self, url):
        self.calls.append(url)
        return FILES[url]

    def run_fetch(self, lk, **kw):
        return fu.fetch(lk, self.skills, get=self.get, backup_root=self.bak, log=lambda *_: None, **kw)

    def test_dry_run_downloads_and_writes_nothing(self):
        self.assertEqual(self.run_fetch(lock()), {"a": "planned"})
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(self.skills))

    def test_apply_installs_with_upstream_note(self):
        self.assertEqual(self.run_fetch(lock(), apply=True), {"a": "installed"})
        self.assertTrue(os.path.exists(os.path.join(self.skills, "a", "LICENSE")))
        note = open(os.path.join(self.skills, "a", "UPSTREAM.txt"), encoding="utf-8").read()
        self.assertIn("licence: MIT", note)
        self.assertIn("c0ffee", note)
        self.assertTrue(self.run_fetch(lock(), apply=True)["a"].startswith("skipped"))   # no silent overwrite
        self.assertEqual(self.run_fetch(lock(), apply=True, force=True), {"a": "installed"})
        self.assertEqual(len(os.listdir(self.bak)), 1)                                       # old copy kept, outside skills

    def test_hash_mismatch_writes_nothing(self):
        bad = lock([ ["SKILL.md", "a/SKILL.md", H(b"other")] ])
        self.assertTrue(self.run_fetch(bad, apply=True)["a"].startswith("failed: SHA-256 mismatch"))
        self.assertFalse(os.path.exists(os.path.join(self.skills, "a")))

    def test_refuses_non_permissive_and_path_escape(self):
        self.assertTrue(self.run_fetch(lock(license_="Proprietary"), apply=True)["a"].startswith("refused"))
        esc = lock([["SKILL.md", "../evil/SKILL.md", H(FILES["https://x/a/SKILL.md"])]])
        self.assertIn("escapes", self.run_fetch(esc, apply=True)["a"])
        self.assertFalse(os.path.exists(os.path.join(self.d, "evil")))

    def test_shipped_locks_are_pinned_and_permissive(self):
        with open(os.path.join(HERE, "upstream.lock.json"), encoding="utf-8") as f:
            lk = json.load(f)
        self.assertEqual(sorted(s["id"] for s in lk["sources"]), ["humanizer", "playwright-cli"])   # default set
        with open(os.path.join(HERE, "upstream.optional.lock.json"), encoding="utf-8") as f:
            opt = json.load(f)
        self.assertIn("NOT RECOMMENDED", opt["_readme"])
        for s in lk["sources"] + opt["sources"]:
            self.assertTrue(s["license"].startswith(fu.PERMISSIVE), s["id"])
            self.assertTrue(s.get("commit") or s["kind"] == "npm", s["id"])
            if s.get("commit"):
                self.assertIn(s["commit"], s["base"])            # URL pinned to the commit, not a branch
            for src, dest, sha in s["files"]:
                self.assertEqual(len(sha), 64)
                fu.safe_dest(self.skills, dest)

    def test_optional_flag_adds_the_design_set_dry_run(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(fu.main(["--optional", "--skills-dir", self.skills]), 0)
        out = buf.getvalue()
        self.assertIn("OPTIONAL SET: NOT RECOMMENDED", out)
        for sid in ("humanizer", "playwright-cli", "impeccable", "gstack", "web-design-guidelines"):
            self.assertIn(f"PLAN    {sid} ", out)
        self.assertEqual(os.listdir(self.skills) if os.path.exists(self.skills) else [], [], "dry run writes nothing")
        buf = io.StringIO()
        with redirect_stdout(buf):
            fu.main(["--skills-dir", self.skills])
        self.assertNotIn("gstack", buf.getvalue(), "without --optional the design set stays out")


if __name__ == "__main__":
    unittest.main()
