import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: nothing below skips; a missing file fails

import hashlib, io, json, re, shutil, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout

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
        with open(os.path.join(self.skills, "a", "UPSTREAM.txt"), encoding="utf-8") as f:
            note = f.read()
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
        self.assertEqual(sorted(s["id"] for s in lk["sources"]),
                         ["diagram-render", "humanizer", "web-interface-guidelines"])               # default set (IP1)
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
            self.assertNotRegex(s["base"], r"/(?:main|master|HEAD)/", s["id"] + ": a moving ref")

    def test_default_set_records_licence_text_and_data_only(self):
        """The two new default sources are data folders (no SKILL.md) that ship the upstream LICENSE beside the files."""
        with open(os.path.join(HERE, "upstream.lock.json"), encoding="utf-8") as f:
            lk = {s["id"]: s for s in json.load(f)["sources"]}
        for sid, want in (("web-interface-guidelines", {"command.md", "LICENSE"}),
                          ("diagram-render", {"diagram-render.html", "BUILD_INFO.json", "THIRD-PARTY-LICENSES.md", "LICENSE"})):
            s = lk[sid]
            self.assertRegex(s["commit"], r"^[0-9a-f]{40}$")
            self.assertEqual(s["license"], "MIT")
            self.assertEqual({d.split("/", 1)[1] for _, d, _ in s["files"]}, want, sid)
            self.assertEqual({d.split("/", 1)[0] for _, d, _ in s["files"]}, {sid}, "one folder, named like the source")
            self.assertFalse(any(d.endswith("SKILL.md") for _, d, _ in s["files"]), sid + " must stay out of the skill list")
        self.assertNotIn("playwright-cli", lk, "the pinned playwright-cli skill is the optional-set fallback")

    def test_default_set_mocked_install_and_tamper(self):
        with open(os.path.join(HERE, "upstream.lock.json"), encoding="utf-8") as f:
            lk = json.load(f)
        body = {s["base"] + src: ("content of " + src).encode() for s in lk["sources"] for src, _d, _h in s["files"]}
        for s in lk["sources"]:
            for e in s["files"]:
                e[2] = H(body[s["base"] + e[0]])
        res = fu.fetch(lk, self.skills, apply=True, get=lambda u: body[u], backup_root=self.bak, log=lambda *_: None)
        self.assertEqual(res, {s["id"]: "installed" for s in lk["sources"]})
        for sid in ("web-interface-guidelines", "diagram-render"):
            with open(os.path.join(self.skills, sid, "UPSTREAM.txt"), encoding="utf-8") as f:
                self.assertIn("licence: MIT", f.read())
        shutil.rmtree(self.skills)
        url = [s for s in lk["sources"] if s["id"] == "diagram-render"][0]["base"] + "lib/diagram-render/dist/diagram-render.html"
        res = fu.fetch(lk, self.skills, apply=True, get=lambda u: b"changed" if u == url else body[u],
                       backup_root=self.bak, log=lambda *_: None)
        self.assertTrue(res["diagram-render"].startswith("failed: SHA-256 mismatch"))
        self.assertFalse(os.path.exists(os.path.join(self.skills, "diagram-render")), "nothing written for a bad source")
        self.assertEqual(res["humanizer"], "installed", "one bad source does not block the others")

    def test_optional_flag_adds_the_design_set_dry_run(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(fu.main(["--optional", "--skills-dir", self.skills]), 0)
        out = buf.getvalue()
        self.assertIn("OPTIONAL SET: NOT RECOMMENDED", out)
        for sid in ("humanizer", "web-interface-guidelines", "diagram-render", "playwright-cli", "impeccable", "gstack"):
            self.assertIn(f"PLAN    {sid} ", out)
        self.assertNotIn("PLAN    web-design-guidelines ", out, "the live-fetch entry is gone: the rules are pinned now")
        self.assertEqual(os.listdir(self.skills) if os.path.exists(self.skills) else [], [], "dry run writes nothing")
        buf = io.StringIO()
        with redirect_stdout(buf):
            fu.main(["--skills-dir", self.skills])
        self.assertNotIn("PLAN    gstack ", buf.getvalue(), "without --optional the design set stays out")
        self.assertNotIn("playwright-cli", buf.getvalue(), "without --optional the fallback skill stays out")
        self.assertIn("PLAN    diagram-render ", buf.getvalue(), "the default set carries the offline renderer")


class PmPackTest(unittest.TestCase):
    """The product-management pack (--pm): pinned, permissive, skills and licences only."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.skills, self.bak = os.path.join(self.d, "skills"), os.path.join(self.d, "bak")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def pm_lock(self):
        with open(os.path.join(HERE, "upstream.pm.lock.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_pm_lock_is_pinned_permissive_and_only_skills(self):
        lk = self.pm_lock()
        self.assertEqual([s["id"] for s in lk["sources"]], ["pm-pack"])
        s = lk["sources"][0]
        self.assertTrue(s["license"].startswith(fu.PERMISSIVE))
        self.assertRegex(s["commit"], r"^[0-9a-f]{40}$")
        self.assertIn(s["commit"], s["base"])
        skills = set()
        for src, dest, sha in s["files"]:
            self.assertRegex(sha, r"^[0-9a-f]{64}$")
            fu.safe_dest(self.skills, dest)
            self.assertRegex(dest, r"^[a-z0-9-]+/(SKILL\.md|LICENSE)$")
            self.assertRegex(src, r"^product-management/(skills/[a-z0-9-]+/SKILL\.md|LICENSE)$")
            self.assertNotIn(".mcp.json", src)
            skills.add(dest.split("/")[0])
        self.assertEqual(len(skills), 8)
        for k in skills:
            self.assertEqual(sorted(d.split("/")[1] for _, d, _ in s["files"] if d.startswith(k + "/")), ["LICENSE", "SKILL.md"])

    def test_pm_flag_dry_run_and_exclusions(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(fu.main(["--pm", "--skills-dir", self.skills]), 0)
        self.assertIn("PLAN    pm-pack ", buf.getvalue())
        self.assertNotIn("humanizer", buf.getvalue())
        self.assertFalse(os.path.exists(self.skills))
        buf = io.StringIO()
        with redirect_stdout(buf):
            fu.main(["--skills-dir", self.skills])
        self.assertNotIn("pm-pack", buf.getvalue(), "the default set stays without the pack")
        for bad in (["--pm", "--optional"], ["--pm", "--lock", "x.json"]):
            with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                fu.main(bad + ["--skills-dir", self.skills])

    def test_pm_mocked_download_installs_and_a_tampered_file_installs_nothing(self):
        lk = self.pm_lock()
        body = {lk["sources"][0]["base"] + src: ("content of " + src).encode() for src, _d, _h in lk["sources"][0]["files"]}
        for entry in lk["sources"][0]["files"]:
            entry[2] = H(body[lk["sources"][0]["base"] + entry[0]])
        res = fu.fetch(lk, self.skills, apply=True, get=lambda u: body[u], backup_root=self.bak, log=lambda *_: None)
        self.assertEqual(res, {"pm-pack": "installed"})
        for _src, dest, _h in lk["sources"][0]["files"]:
            self.assertTrue(os.path.isfile(os.path.join(self.skills, dest)), dest)
        self.assertFalse(any(f == ".mcp.json" for _r, _d, fs in os.walk(self.skills) for f in fs))
        with open(os.path.join(self.skills, "write-spec", "UPSTREAM.txt"), encoding="utf-8") as f:
            note = f.read()
        self.assertIn("Apache-2.0", note)
        self.assertIn(lk["sources"][0]["commit"], note)
        shutil.rmtree(self.skills)
        bad_url = lk["sources"][0]["base"] + "product-management/skills/write-spec/SKILL.md"
        tampered = dict(body, **{bad_url: b"changed"})
        res = fu.fetch(lk, self.skills, apply=True, get=lambda u: tampered[u], backup_root=self.bak, log=lambda *_: None)
        self.assertTrue(res["pm-pack"].startswith("failed: SHA-256 mismatch"))
        self.assertFalse(os.path.exists(self.skills))


if __name__ == "__main__":
    unittest.main()
