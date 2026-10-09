"""Tests for the diagram skill's renderer. Run:
    python -m unittest discover -s plugins/workbench-core/skills/diagram/tests
Most tests drive render.py with a stand-in for render.mjs (no browser, no bundle). `Live` renders for real: it needs node,
playwright-core (next to render.mjs or in $DIAGRAM_NODE_MODULES), Edge or Chrome, and the bundle ($DIAGRAM_RENDER_BUNDLE or
the fetch-upstream location); without them it skips, and with WB_REQUIRE_ALL=1 a missing piece fails instead."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: nothing below skips; a missing piece fails
SKILL = Path(__file__).resolve().parents[1]
REPO = SKILL.parents[3]
spec = importlib.util.spec_from_file_location("diagram_render", SKILL / "scripts" / "render.py")
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)


def chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)


def tiny_png(w=4, h=3):
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    return (render.PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# A stand-in for render.mjs: same arguments, behaviour picked by FAKE_MODE, every call logged to FAKE_LOG.
FAKE = r'''
import json, os, sys, time
a = sys.argv[1:]
get = lambda k: a[a.index(k) + 1]
base, kind, mode = get("--out-base"), get("--kind"), os.environ.get("FAKE_MODE", "good")
open(os.environ["FAKE_LOG"], "a").write(json.dumps(a) + "\n")
png = bytes.fromhex(os.environ["FAKE_PNG"])
svg = "<svg xmlns='http://www.w3.org/2000/svg'><rect width='4' height='3'/></svg>"
info = {"written": [], "blocked": [], "notes": []}
if mode == "fail":
    sys.stderr.write("RENDER_FAILED: Parse error on line 3\n    at Parser.parse (file:///x.html:1:2)\n    at Zg0.parse (x)\n")
    sys.exit(1)
if mode == "hang":
    time.sleep(30)
if mode != "no_svg":
    open(base + ".svg", "w").write("hello" if mode == "bad_svg" else svg)
if mode not in ("no_png",):
    open(base + ".png", "wb").write({"bad_png": b"not a png", "empty_png": b"", "short_png": png[:20]}.get(mode, png))
if kind == "mmd" and mode not in ("skip_scene",):
    open(base + ".excalidraw", "w").write("not json" if mode == "bad_scene" else '{"elements": [{"id": "x"}]}')
if mode == "skip_scene":
    info["notes"].append("EXCALIDRAW_SKIPPED: the converter reads flowcharts only")
if mode == "blocked":
    info["blocked"] = ["https://fonts.example.net/a.woff2", "https://fonts.example.net/b.woff2"]
print(json.dumps(info))
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-diagram-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cfg = self.tmp / "cfg"
        self.cfg.mkdir()
        self.fake = self.tmp / "fake_render.py"
        self.fake.write_text(FAKE, encoding="utf-8")
        self.log = self.tmp / "fake.log"
        self.bundle = self.tmp / "bundle.html"
        self.bundle.write_text("<html></html>", encoding="utf-8")
        self.work = self.tmp / "work"
        self.work.mkdir()
        env = {"CLAUDE_CONFIG_DIR": str(self.cfg), "DIAGRAM_NODE": sys.executable, "DIAGRAM_RENDERER": str(self.fake),
               "DIAGRAM_RENDER_BUNDLE": str(self.bundle), "FAKE_LOG": str(self.log), "FAKE_PNG": tiny_png().hex()}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)

    def src(self, name="flow.mmd", text="flowchart LR\n  A --> B\n"):
        p = self.work / name
        p.write_text(text, encoding="utf-8")
        return p

    def run_render(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = render.main([str(a) for a in args])
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def mode(self, m):
        return mock.patch.dict(os.environ, {"FAKE_MODE": m})


class Outputs(Base):
    def test_a_good_render_puts_svg_png_and_scene_next_to_the_source(self):
        s = self.src()
        code, out, _ = self.run_render(s)
        self.assertEqual(code, 0)
        for ext in ("svg", "png", "excalidraw"):
            self.assertTrue((self.work / f"flow.{ext}").is_file(), ext)
        self.assertTrue((self.work / "flow.png").read_bytes().startswith(render.PNG_SIGNATURE))
        self.assertIn("RENDERED", out)
        self.assertIn("offline: 0 outside request(s) refused", out)
        call = self.calls()[0]
        self.assertEqual(call[call.index("--kind") + 1], "mmd")
        self.assertEqual(call[call.index("--bundle") + 1], str(self.bundle))
        self.assertEqual(call[call.index("--width") + 1], "1600")
        self.assertNotIn(str(self.work), call[call.index("--out-base") + 1], "the renderer writes to a staging folder first")

    def test_out_folder_and_width_and_mermaid_extension(self):
        s = self.src("net.mermaid")
        code, _, _ = self.run_render(s, "--out", self.tmp / "dest" / "deep", "--width", 900)
        self.assertEqual(code, 0)
        self.assertTrue((self.tmp / "dest" / "deep" / "net.png").is_file())
        self.assertFalse((self.work / "net.png").exists())
        self.assertEqual(self.calls()[0][self.calls()[0].index("--width") + 1], "900")

    def test_an_excalidraw_source_makes_svg_and_png_only(self):
        s = self.src("sketch.excalidraw", '{"elements": []}')
        self.assertEqual(self.run_render(s)[0], 0)
        self.assertTrue((self.work / "sketch.svg").is_file() and (self.work / "sketch.png").is_file())
        self.assertFalse((self.work / "sketch.excalidraw.prev").exists())
        self.assertEqual(self.calls()[0][self.calls()[0].index("--kind") + 1], "excalidraw")
        self.assertEqual(json.loads(s.read_text()), {"elements": []}, "the source is never rewritten")

    def test_a_scene_the_converter_skips_is_noted_and_not_listed(self):
        s = self.src("seq.mmd", "sequenceDiagram\n  A->>B: hi\n")
        with self.mode("skip_scene"):
            code, out, _ = self.run_render(s)
        self.assertEqual(code, 0)
        self.assertIn("EXCALIDRAW_SKIPPED", out)
        self.assertFalse((self.work / "seq.excalidraw").exists())
        self.assertTrue((self.work / "seq.png").is_file())

    def test_blocked_requests_are_reported_by_host_only(self):
        with self.mode("blocked"):
            code, out, _ = self.run_render(self.src())
        self.assertEqual(code, 0)
        self.assertIn("2 outside request(s) refused (fonts.example.net)", out)

    def test_a_replaced_scene_that_differs_is_kept_as_prev(self):
        s = self.src()
        (self.work / "flow.excalidraw").write_text("hand edited", encoding="utf-8")
        code, out, _ = self.run_render(s)
        self.assertEqual(code, 0)
        self.assertEqual((self.work / "flow.excalidraw.prev").read_text(), "hand edited")
        self.assertIn("PREVIOUS flow.excalidraw kept as flow.excalidraw.prev", out)
        self.run_render(s)       # identical scene the second time: no new .prev message
        self.assertEqual((self.work / "flow.excalidraw.prev").read_text(), "hand edited")


class Failures(Base):
    """Every way the renderer can claim success without having produced a diagram must fail, and leave nothing behind."""

    def test_exit_zero_with_no_png_is_a_failure_and_nothing_is_written(self):
        for m in ("no_png", "bad_png", "empty_png", "short_png"):
            with self.mode(m):
                code, _, err = self.run_render(self.src())
            self.assertEqual(code, 1, m)
            self.assertIn("no PNG", err, m)
            self.assertEqual(sorted(p.name for p in self.work.iterdir()), ["flow.mmd"], f"{m}: no half-written outputs")

    def test_a_missing_or_fake_svg_fails(self):
        for m in ("no_svg", "bad_svg"):
            with self.mode(m):
                code, _, err = self.run_render(self.src())
            self.assertEqual((code, "no SVG" in err), (1, True), m)
            self.assertEqual(sorted(p.name for p in self.work.iterdir()), ["flow.mmd"], m)

    def test_a_scene_that_is_not_a_scene_fails(self):
        with self.mode("bad_scene"):
            code, _, err = self.run_render(self.src())
        self.assertEqual((code, "not a scene" in err), (1, True))
        self.assertFalse((self.work / "flow.png").exists())

    def test_a_failed_render_keeps_the_old_outputs_and_shows_the_message_without_the_stack(self):
        s = self.src()
        (self.work / "flow.png").write_bytes(b"old png")
        with self.mode("fail"):
            code, _, err = self.run_render(s)
        self.assertEqual(code, 1)
        self.assertIn("Parse error on line 3", err)
        self.assertNotIn("at Parser.parse", err)
        self.assertEqual((self.work / "flow.png").read_bytes(), b"old png")

    def test_a_hung_renderer_times_out(self):
        with self.mode("hang"), mock.patch.object(render, "TIMEOUT", 1):
            code, _, err = self.run_render(self.src())
        self.assertEqual((code, "no result after 1 seconds" in err), (1, True))

    def test_the_staging_folder_is_removed_after_success_and_failure(self):
        tmpdir = self.tmp / "t"
        tmpdir.mkdir()
        with mock.patch.object(tempfile, "tempdir", str(tmpdir)):
            self.run_render(self.src())
            with self.mode("fail"):
                self.run_render(self.src())
        self.assertEqual(list(tmpdir.iterdir()), [])


class Inputs(Base):
    def assert_refused(self, args, code, word):
        got, _, err = self.run_render(*args)
        self.assertEqual((got, word in err), (2, True), err)
        self.assertEqual(self.calls(), [], "the renderer is never started for a bad request")

    def test_bad_sources_are_refused_before_any_render(self):
        self.assert_refused([self.work / "nope.mmd"], 2, "NO_SOURCE")
        self.assert_refused([self.src("notes.txt")], 2, "expected .mmd")
        self.assert_refused([self.src("empty.mmd", "")], 2, "0 bytes")
        self.assert_refused([self.src("big.mmd", "a" * (render.MAX_SOURCE + 1))], 2, "bytes")
        (self.work / "bin.mmd").write_bytes(b"\xff\xfe\x00bad")
        self.assert_refused([self.work / "bin.mmd"], 2, "not UTF-8")
        self.assert_refused([self.src("x.excalidraw", "not json")], 2, "not JSON")
        self.assert_refused([self.src("y.excalidraw", '{"type": "excalidraw"}')], 2, "elements")
        self.assert_refused([self.src("z.excalidraw", "[1, 2]")], 2, "elements")

    def test_width_is_bounded(self):
        s = self.src()
        for w in (199, 4001, 0):
            self.assert_refused([s, "--width", w], 2, "BAD_WIDTH")
        self.assertEqual(self.run_render(s, "--width", 200)[0], 0)
        self.assertEqual(self.run_render(s, "--width", 4000)[0], 0)

    def test_bundle_lookup_order_and_no_silent_fallthrough(self):
        s = self.src()
        with mock.patch.dict(os.environ):
            os.environ.pop("DIAGRAM_RENDER_BUNDLE")
            self.assert_refused([s], 2, "BUNDLE_MISSING")
            legacy = self.cfg / "skills" / render.LEGACY_REL
            legacy.parent.mkdir(parents=True)
            legacy.write_text("x")
            self.assertEqual(render.find_bundle(), legacy)
            fetched = self.cfg / "skills" / render.BUNDLE_REL
            fetched.parent.mkdir(parents=True)
            fetched.write_text("x")
            self.assertEqual(render.find_bundle(), fetched, "the fetch-upstream location beats the legacy one")
            mine = self.tmp / "mine.html"
            mine.write_text("x")
            self.assertEqual(render.find_bundle(str(mine)), mine, "--bundle beats everything")
            os.environ["DIAGRAM_RENDER_BUNDLE"] = str(self.tmp / "gone.html")
            self.assertIsNone(render.find_bundle(), "a named bundle that is missing is not replaced by another")
            self.assert_refused([s], 2, "BUNDLE_MISSING")

    def test_missing_node_and_missing_playwright_say_what_to_do(self):
        s = self.src()
        with mock.patch.dict(os.environ):
            os.environ.pop("DIAGRAM_NODE")
            with mock.patch.object(render.shutil, "which", return_value=None):
                self.assert_refused([s], 2, "NODE_MISSING")
            os.environ.pop("DIAGRAM_RENDERER")
            os.environ["DIAGRAM_NODE"] = sys.executable
            os.environ["DIAGRAM_NODE_MODULES"] = str(self.tmp / "no-modules")
            self.assert_refused([s], 2, "PLAYWRIGHT_MISSING")
            (self.tmp / "no-modules" / "playwright-core").mkdir(parents=True)
            (self.tmp / "no-modules" / "playwright-core" / "package.json").write_text("{}")
            self.assertTrue(render.have_playwright())


class Wiring(unittest.TestCase):
    """The pieces that must agree with each other across files."""

    def test_the_default_bundle_path_is_where_the_default_lock_installs_it(self):
        lock = REPO / "tools" / "fetch-upstream" / "upstream.lock.json"
        if not lock.is_file():
            if REQUIRE:
                self.fail("tools/fetch-upstream/upstream.lock.json is missing")
            self.skipTest("not inside the kit checkout")
        src = {s["id"]: s for s in json.loads(lock.read_text(encoding="utf-8"))["sources"]}["diagram-render"]
        dests = [d for _, d, _ in src["files"]]
        self.assertIn(render.BUNDLE_REL, dests)
        self.assertEqual(src["license"], "MIT")
        self.assertIn(render.BUNDLE_REL.split("/")[0] + "/LICENSE", dests, "the licence travels with the bundle")

    def test_playwright_core_is_pinned_like_ui_build(self):
        mine = json.loads((SKILL / "scripts" / "package.json").read_text())["dependencies"]["playwright-core"]
        ui = REPO / "plugins" / "workbench-core" / "skills" / "ui-build" / "scripts" / "package.json"
        self.assertRegex(mine, r"^\d+\.\d+\.\d+$", "an exact version, never a range")
        self.assertEqual(mine, json.loads(ui.read_text())["dependencies"]["playwright-core"])

    def test_skill_text_is_ours_and_names_real_files(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        fm = text.split("---")[1]
        self.assertIn("name: diagram", fm)
        desc = [l for l in fm.splitlines() if l.startswith("description:")][0][len("description:"):].strip()
        self.assertLessEqual(len(desc), 300)
        for gone in ("preamble", "telemetry", "~/.gstack", "gstack-config", "browse daemon", "$B "):
            self.assertNotIn(gone, text, gone)
        for name in ("render.py", "render.mjs", "package.json"):
            self.assertIn(name, text)
            self.assertTrue((SKILL / "scripts" / name).is_file(), name)

    def test_render_mjs_blocks_everything_but_local_origins(self):
        node = shutil.which("node")
        if not node:
            if REQUIRE:
                self.fail("node is not on PATH")
            self.skipTest("node is not on PATH")
        url = (SKILL / "scripts" / "render.mjs").as_uri()
        code = (f"import {{ isLocal, launchArgs }} from {json.dumps(url)};"
                "const a = launchArgs();"
                "console.log(JSON.stringify({"
                "yes: ['file:///C:/x/a.html', 'http://localhost:1/', 'http://app.localhost/', 'data:text/plain,hi', 'about:blank']"
                ".map(isLocal),"
                "no: ['https://example.com/', 'https://esm.sh/x.woff2', 'http://localhost.example.com/', 'ftp://localhost/', 'nonsense']"
                ".map(isLocal), args: a}));")
        r = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["yes"], [True] * 5)
        self.assertEqual(got["no"], [False] * 5)
        args = got["args"]
        self.assertTrue(any(a.startswith("--proxy-server=http://") and a.endswith(":9") for a in args), "proxy to nowhere")
        self.assertIn("--proxy-bypass-list=", args, "no host bypasses the proxy but loopback")
        self.assertTrue(any(a.startswith("--host-resolver-rules=MAP * ~NOTFOUND") for a in args), "no DNS for other names")
        self.assertIn("--force-webrtc-ip-handling-policy=disable_non_proxied_udp", args)


class Live(unittest.TestCase):
    """A real render: node + playwright-core + Edge or Chrome + the offline bundle. No network is needed or used."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-diagram-live-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        why = ("node is not on PATH" if not shutil.which("node") else
               "the diagram-render bundle is not installed (tools/fetch-upstream, or DIAGRAM_RENDER_BUNDLE)" if not render.find_bundle() else
               "playwright-core is not installed (npm install --ignore-scripts next to render.mjs, or DIAGRAM_NODE_MODULES)"
               if not render.have_playwright() else "")
        if why:
            if REQUIRE:
                self.fail(why)
            self.skipTest(why)
        self.out = self.tmp / "out"

    def render(self, name, text, *extra):
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k not in ("DIAGRAM_NODE", "DIAGRAM_RENDERER")}
        r = subprocess.run([sys.executable, str(SKILL / "scripts" / "render.py"), str(p), "--out", str(self.out), *extra],
                           capture_output=True, text=True, encoding="utf-8", env=env, timeout=240)
        return r

    def test_a_flowchart_renders_offline_to_svg_png_and_scene(self):
        r = self.render("flow.mmd", "flowchart LR\n  A[Request] --> B{Valid?}\n  B -- yes --> C[Store]\n  B -- no --> D[Reject]\n", "--width", "800")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("offline: 0 outside request(s) refused", r.stdout, "the bundle asked for nothing outside the machine")
        png = (self.out / "flow.png").read_bytes()
        self.assertTrue(png.startswith(render.PNG_SIGNATURE))
        self.assertEqual(struct.unpack(">I", png[16:20])[0], 800, "the PNG is as wide as asked")
        self.assertGreater(len(png), 2000, "a drawn diagram, not a blank canvas")
        svg = (self.out / "flow.svg").read_text(encoding="utf-8")
        for label in ("Request", "Valid?", "Reject"):
            self.assertIn(label, svg)
        scene = json.loads((self.out / "flow.excalidraw").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(scene["elements"]), 4)

    def test_a_sequence_diagram_renders(self):
        r = self.render("seq.mmd", "sequenceDiagram\n  participant U as User\n  participant S as Service\n  U->>S: request\n  S-->>U: reply\n")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue((self.out / "seq.png").read_bytes().startswith(render.PNG_SIGNATURE))
        self.assertIn("reply", (self.out / "seq.svg").read_text(encoding="utf-8"))

    def test_an_excalidraw_scene_renders_and_nothing_goes_out(self):
        first = self.render("flow.mmd", "flowchart LR\n  A --> B\n")
        self.assertEqual(first.returncode, 0, first.stderr)
        scene = (self.out / "flow.excalidraw").read_text(encoding="utf-8")
        r = self.render("sketch.excalidraw", scene)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue((self.out / "sketch.png").read_bytes().startswith(render.PNG_SIGNATURE))
        self.assertFalse((self.out / "sketch.excalidraw").exists())
        # the bundle asks a web-font host for its hand-drawn font; the block refuses it and the render still succeeds
        self.assertRegex(r.stdout, r"offline: \d+ outside request\(s\) refused")

    def test_a_syntax_error_fails_with_the_parser_message_and_writes_nothing(self):
        r = self.render("bad.mmd", "flowchart LR\n  A --> \n  [[[ nonsense\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Parse error", r.stderr)
        self.assertFalse(self.out.exists() and any(self.out.iterdir()))


if __name__ == "__main__":
    unittest.main()
