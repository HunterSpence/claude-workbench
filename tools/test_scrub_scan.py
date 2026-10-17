"""Tests for scrub_scan.py with a throwaway tree and denylist. Run: python -m unittest discover -s tools -p "test_scrub*"
Every "personal" value below is assembled at runtime, so this file itself scans clean."""
import importlib.util
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"
HAVE_GIT = bool(shutil.which("git"))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scrub_scan  # noqa: E402

AT = "@"
DOT = "."
DOC_IP, LOOP_IP, VERSION = DOT.join("192 0 2 10".split()), DOT.join("127 0 0 1".split()), DOT.join("12345")
TERM = "zebra" + "corp"
L, R = "[" * 2, "]" * 2          # wiki link brackets, built so this file holds no literal link


class ScrubScan(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-scrub-"))
        self.tree = self.tmp / "tree"
        (self.tree / "sub").mkdir(parents=True)
        (self.tree / ".git").mkdir()
        self.deny = self.tmp / "deny.txt"
        self.deny.write_text(f"# private terms\n{TERM}\n\nre:(?i)proj-[0-9]{{4}}\nre:\\bACME\\b\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text):
        p = self.tree / rel
        p.write_text(text, encoding="utf-8")
        return p

    def run_scan(self, *extra):
        return scrub_scan.main([str(self.tree), "--root", str(self.tree), "--denylist", str(self.deny), *extra])

    def rules(self, text):
        self.write("x.md", text)
        _, hits = scrub_scan.scan([self.tree], self.tree, scrub_scan.load_denylist(self.deny))
        return sorted({h[2] for h in hits if not h[3]})

    def test_clean_tree_passes(self):
        self.write("a.md", f"Contact dev{AT}example.com, host {DOC_IP}, path %USERPROFILE%\\.claude, "
                   f"C:\\Users\\<you>\\x, /home/<user>/x, loopback {LOOP_IP}, version {VERSION}, git{AT}git.example.org:a\n")
        self.assertEqual(self.run_scan(), 0)

    def test_builtin_rules(self):
        self.assertEqual(self.rules("mail jane.doe" + AT + "corpmail.io"), ["G1"])
        self.assertEqual(self.rules("ssh to " + DOT.join("10 20 30 40".split()) + " now"), ["G2"])
        self.assertEqual(self.rules("C:\\" + "Users\\jdoe\\repo"), ["G3"])
        self.assertEqual(self.rules("cd /c/Users/" + "jdoe/repo"), ["G3"])
        self.assertEqual(self.rules("/home/" + "jdoe/.bashrc"), ["G3"])
        self.assertEqual(self.rules("call +1 555 " + "123 4567"), ["G4"])
        self.assertEqual(self.rules("see [" + "[ops/private-note]]"), ["G5"])
        self.assertEqual(self.rules("key AKIA" + "Q" * 16), ["G6"])

    def test_denylist_whole_word_case_insensitive_and_regex(self):
        self.assertEqual(self.rules(f"built for {TERM.upper()} last year"), ["D2"])
        self.assertEqual(self.rules(f"built for {TERM}ish things"), [])          # not a whole word
        self.assertEqual(self.rules("ticket PROJ-" + "1234"), ["D4"])
        self.assertEqual(self.rules("the ACME build"), ["D5"])                   # re: rules are case-sensitive
        self.assertEqual(self.rules("an acme of skill"), [])
        self.assertEqual(self.rules("pin brave-search-mcp-server" + AT + "2.1.4"), [])  # npm pin is not an e-mail

    def test_denylist_boundaries_catch_compounds(self):
        self.assertEqual(self.rules(f"x = foo_{TERM}_bar"), ["D2"])                 # underscore compound
        self.assertEqual(self.rules("class fooZebraCorp: pass"), ["D2"])           # camelCase step
        self.assertEqual(self.rules(f"{TERM}-tools.{TERM}2"), ["D2"])
        self.assertEqual(self.rules(f"x{TERM}"), [])                                # glued to a letter

    def test_scrub_ok_never_silences_a_denylist_term(self):
        self.assertEqual(self.rules(f"{TERM}  # scrub-ok: it is public anyway"), ["D2"])

    @unittest.skipUnless(HAVE_GIT or REQUIRE, "git not installed")
    def test_git_work_tree_uses_ls_files(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)
        (repo / ".gitignore").write_text("ignored.md\n", encoding="utf-8")
        (repo / "ignored.md").write_text(f"{TERM}\n", encoding="utf-8")
        (repo / "untracked.md").write_text("clean\n", encoding="utf-8")
        files = {f.name for f in scrub_scan.iter_files([repo], set())}
        self.assertEqual(files, {".gitignore", "untracked.md"})
        (repo / "untracked.md").write_text(f"{TERM}\n", encoding="utf-8")
        _, hits = scrub_scan.scan([repo], repo, scrub_scan.load_denylist(self.deny))
        self.assertEqual({(h[0], h[2]) for h in hits}, {("untracked.md", "D2")})

    def test_scrub_ok_needs_a_reason(self):
        self.assertEqual(self.rules("mail a" + AT + "corpmail.io  # scrub-ok: vendor support address"), [])
        self.assertEqual(self.rules("mail a" + AT + "corpmail.io  # scrub-ok:"), ["G1"])

    def test_skips_git_and_binary(self):
        (self.tree / ".git" / "config").write_text(f"{TERM}\n")
        self.write("a.md", "clean\n")
        (self.tree / "blob.bin").write_bytes(b"\0" + TERM.encode())
        r = subprocess.run([sys.executable, str(HERE / "scrub_scan.py"), str(self.tree), "--root", str(self.tree),
                            "--denylist", str(self.deny)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1, "a skipped binary fails the scan")
        self.assertIn("skipped (binary: NUL bytes or unreadable): 1", r.stdout)
        self.assertIn("blob.bin", r.stdout)
        self.assertIn("skipped (directory skipped outside git", r.stdout)
        self.assertEqual(self.run_scan("--allow-binary"), 0)
        (self.tree / "pic.jpg").write_bytes(b"\xff\xd8\xff")
        self.assertEqual(self.run_scan(), 1)

    def run_cli(self, tree):
        return subprocess.run([sys.executable, str(HERE / "scrub_scan.py"), str(tree), "--root", str(tree),
                               "--denylist", str(self.deny)], capture_output=True, text=True, timeout=60)

    def test_walk_mode_fails_on_a_skipped_directory(self):
        self.write("a.md", "clean\n")
        self.assertEqual(self.run_scan(), 0, "VCS metadata and tool caches are skipped quietly")
        (self.tree / "__pycache__").mkdir()
        self.assertEqual(self.run_scan(), 0)
        for name in ("build", "dist", "node_modules", ".venv"):
            (self.tree / name).mkdir()
            (self.tree / name / "x.md").write_text(f"{TERM}\n", encoding="utf-8")
            r = self.run_cli(self.tree)
            self.assertEqual(r.returncode, 1, name)
            self.assertIn("FAIL: walk mode skipped", r.stdout)
            self.assertNotIn(TERM, r.stdout.lower())
            shutil.rmtree(self.tree / name)
        self.assertEqual(self.run_scan(), 0)

    @unittest.skipUnless(HAVE_GIT or REQUIRE, "git not installed")
    def test_git_mode_scans_build_output_and_does_not_fail_on_it(self):
        repo = self.tmp / "repo3"
        (repo / "build").mkdir(parents=True)
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)
        (repo / "build" / "x.md").write_text("clean\n", encoding="utf-8")
        r = self.run_cli(repo)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("walk mode skipped", r.stdout)

    def test_zero_files_fails(self):
        self.assertEqual(self.run_scan(), 1)

    def office(self, name, core, app=""):
        p = self.tree / name
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("docProps/core.xml", core)
            if app:
                z.writestr("docProps/app.xml", app)
        return p

    def test_office_metadata(self):
        ns = ('xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
              'xmlns:dc="http://purl.org/dc/elements/1.1/"')
        self.office("a.docx", f"<cp:coreProperties {ns}><dc:creator>Jane Doe</dc:creator>"
                              f"<dc:title>{TERM} plan</dc:title></cp:coreProperties>",
                    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
                    "<Company>Initech</Company></Properties>")
        _, hits = scrub_scan.scan([self.tree], self.tree, scrub_scan.load_denylist(self.deny))
        got = {(h[0], h[2]) for h in hits}
        self.assertIn(("a.docx!docProps/core.xml", "G7"), got)
        self.assertIn(("a.docx!docProps/core.xml", "D2"), got)
        self.assertIn(("a.docx!docProps/app.xml", "G7"), got)
        self.assertFalse(any(h[4] and "Jane" in h[4] for h in hits), "author values are never echoed")
        shutil.rmtree(self.tree)
        self.tree.mkdir()
        self.office("b.xlsx", f"<cp:coreProperties {ns}><dc:creator>openpyxl</dc:creator></cp:coreProperties>")
        self.assertEqual(self.run_scan(), 0, "a generator's default author is fine")
        (self.tree / "c.pptx").write_bytes(b"not a zip")
        self.assertEqual(self.run_scan(), 1, "a broken Office file is an unscannable binary")

    def test_png_text_chunks(self):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        itxt = b"Description\0\x01\x00en\0\0" + zlib.compress(f"made for {TERM}".encode())
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"tEXt", b"Author\0Jane Doe") + chunk(b"iTXt", itxt) + chunk(b"IEND", b"")
        (self.tree / "shot.png").write_bytes(png)
        _, hits = scrub_scan.scan([self.tree], self.tree, scrub_scan.load_denylist(self.deny))
        rules = {h[2] for h in hits}
        self.assertIn("G7", rules)
        self.assertIn("D2", rules)
        (self.tree / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"tEXt", b"Software\0python") + chunk(b"IEND", b""))
        self.assertEqual(self.run_scan(), 0, "a PNG with only a Software chunk passes")

    def test_git_tracked_build_output_is_scanned(self):
        repo = self.tmp / "repo2"
        (repo / "build").mkdir(parents=True)
        (repo / "dist").mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)
        (repo / "build" / "notes.md").write_text(f"{TERM}\n", encoding="utf-8")
        (repo / "dist" / "x.md").write_text(f"{TERM}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "build/notes.md"], check=True, capture_output=True)
        _, hits = scrub_scan.scan([repo], repo, scrub_scan.load_denylist(self.deny))
        self.assertEqual({h[0] for h in hits}, {"build/notes.md", "dist/x.md"})

    def test_report_never_prints_terms_or_matches(self):
        self.write("sub/leak.md", f"{TERM} and jane" + AT + "corpmail.io\n")
        report = self.tmp / "SCRUB-REPORT.md"
        self.assertEqual(self.run_scan("--report", str(report)), 1)
        text = report.read_text(encoding="utf-8")
        self.assertIn("`sub/leak.md:1` D2", text)
        self.assertIn("`sub/leak.md:1` G1", text)
        self.assertNotIn(TERM, text.lower())
        self.assertNotIn("corpmail", text)

    def test_console_never_prints_denylist_terms(self):
        self.write("leak.md", f"{TERM}\n")
        r = subprocess.run([sys.executable, str(HERE / "scrub_scan.py"), str(self.tree), "--root", str(self.tree),
                            "--denylist", str(self.deny)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("D2", r.stdout)
        self.assertNotIn(TERM, r.stdout.lower())

    def test_env_var_denylist(self):
        self.write("leak.md", f"{TERM}\n")
        r = subprocess.run([sys.executable, str(HERE / "scrub_scan.py"), str(self.tree), "--root", str(self.tree)],
                           capture_output=True, text=True, timeout=60,
                           env={**__import__("os").environ, "WORKBENCH_DENYLIST": str(self.deny)})
        self.assertEqual(r.returncode, 1)

    # ---- G5: a wikilink is a hit, except one in kb-template/ whose target is a note in kb-template/ ----
    def put(self, files):
        for rel, text in files.items():
            p = self.tree / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")

    def link_hits(self, files, deny=None):
        """sorted [(path, line, rule)] of the unallowed hits over a tree holding `files`."""
        self.put(files)
        _, hits = scrub_scan.scan([self.tree], self.tree, scrub_scan.load_denylist(deny or self.deny))
        return sorted({(h[0], h[1], h[2]) for h in hits if not h[3]})

    NOTES = {"kb-template/00-index.md": "# index\n", "kb-template/ops/note.md": "n\n",
             "kb-template/_shared/bug-cards.md": "c\n", "kb-template/projects/demo/00-index.md": "d\n",
             "kb-template/ops/HOT.md": "h\n", "kb-template/infra/HOT.md": "h\n"}

    def test_template_links_to_template_notes_are_allowed(self):
        files = {**self.NOTES, "kb-template/ai/HOT.md": "\n".join([
            f"- part_of {L}00-index{R}", f"- {L}ops/note{R}", f"- {L}note{R}", f"- {L}ops/note|alias{R}",
            f"- {L}ops/note#Heading{R}", f"- {L}ops/note.md{R}", f"- {L}projects/demo{R}", f"- {L}Bug-Cards{R}"]) + "\n"}
        self.assertEqual(self.link_hits(files), [])

    def test_template_links_with_no_note_behind_them_are_hits(self):
        files = {**self.NOTES, "kb-template/ai/links.md": "\n".join([
            f"- {L}nowhere{R}", f"- {L}ops/missing{R}", f"- {L}HOT{R}", f"- {L}../docs/x{R}", f"- {L}00-index{R}"]) + "\n"}
        self.assertEqual(self.link_hits(files), [("kb-template/ai/links.md", n, "G5") for n in (1, 2, 3, 4)],
                         "a dead target, an ambiguous bare name (two HOT.md) and a path escape are hits; the live link is not")

    def test_links_outside_the_template_stay_hits_even_with_a_live_target(self):
        files = {**self.NOTES, "x.md": f"{L}00-index{R}\n", "docs/x.md": f"{L}00-index{R}\n",
                 "docs/kb-template/y.md": f"{L}00-index{R}\n", "tools/kb-template/z.md": f"{L}00-index{R}\n",
                 "kb-template-old/w.md": f"{L}00-index{R}\n", "kb-templatex/v.md": f"{L}00-index{R}\n",
                 "kb-template/ok.md": f"{L}00-index{R}\n"}
        self.assertEqual(self.link_hits(files), sorted((rel, 1, "G5") for rel in (
            "x.md", "docs/x.md", "docs/kb-template/y.md", "tools/kb-template/z.md", "kb-template-old/w.md", "kb-templatex/v.md")))

    def test_the_denylist_still_reads_the_target_of_an_allowed_link(self):
        deny = self.tmp / "deny2.txt"
        deny.write_text(f"# c\n{TERM}\nre:{re.escape(L)}[^\\]]+{re.escape(R)}\n", encoding="utf-8")   # D2 a term, D3 the link syntax
        files = {**self.NOTES, f"kb-template/{TERM}-notes.md": "z\n",
                 "kb-template/ok.md": f"{L}00-index{R}\n", "kb-template/term.md": f"{L}{TERM}-notes{R}\n",
                 "kb-template/dead.md": f"{L}nowhere{R}\n", "docs/x.md": f"{L}00-index{R}\n"}
        self.assertEqual(self.link_hits(files, deny), [("docs/x.md", 1, "D3"), ("docs/x.md", 1, "G5"),
                                                       ("kb-template/dead.md", 1, "D3"), ("kb-template/dead.md", 1, "G5"),
                                                       ("kb-template/term.md", 1, "D2")])

    def test_template_link_rule_is_a_strict_subset_of_kb_index_resolve(self):
        scripts = HERE.parent / "plugins" / "workbench-kb" / "scripts"
        with mock.patch.dict(os.environ, {"WORKBENCH_KB_ROOT": str(self.tmp / "kb"), "CLAUDE_CONFIG_DIR": str(self.tmp / "cc")}):
            sys.path.insert(0, str(scripts))
            try:
                spec = importlib.util.spec_from_file_location("kb_index_for_scrub_test", scripts / "kb_index.py")
                kb_index = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(kb_index)
            finally:
                sys.path.remove(str(scripts))
        notes = {k[len("kb-template/"):] for k in self.NOTES}
        for src in ("ai/HOT.md", "ops/note.md", "00-index.md", "projects/demo/00-index.md"):
            for target in ("00-index", "ops/note", "note", "note|alias", "ops/note#h", "ops/note.md", "projects/demo", "Bug-Cards",
                           "bug-cards", "HOT", "ops/missing", "nowhere", "../docs/x", "", "|alias", "ops\\note", "demo",
                           "Ops/Note", "ops/NOTE", "Bug Cards"):
                ok, res = scrub_scan.template_link_ok(target, src, notes), kb_index.resolve(target, src, notes) is not None
                self.assertTrue(res or not ok, f"{target!r} from {src}: the scan accepts what the KB cannot resolve")
        # positive control: resolve is the looser rule, the scan stays canonical on case and spaces
        self.assertTrue(kb_index.resolve("Ops/Note", "ai/HOT.md", notes) is not None)
        self.assertFalse(scrub_scan.template_link_ok("Ops/Note", "ai/HOT.md", notes))


if __name__ == "__main__":
    unittest.main()
