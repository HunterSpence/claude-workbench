"""Field fixes of v0.3.2 for the find skill: nested roots (F1), the remembered failed model download (F2, F3), the roots a
search covered (F4) and table columns (F5). Run from the repository root:
    WB_REQUIRE_ALL=1 python -m unittest discover -s plugins/workbench-core/skills/find/scripts/tests -v
Everything is fictional, stdlib-only apart from the one test that drives fastembed's own download loop, and offline: the
model fetcher is always a fake that counts its calls."""
import contextlib
import io
import json
import os
import re
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import doc_index as di  # noqa: E402
import test_find as tf  # noqa: E402  (its Env gives each test an isolated home, index and library)


class Nested(tf.Env):
    """F1: a folder that is a root of its own belongs to that root alone."""

    def setUp(self):
        super().setUp()
        self.outer = os.path.join(self.tmp, "outer")
        self.inner = os.path.join(self.outer, "inner")
        self.w("a.md", "Outer note about the zebrafish tank.\n", root=self.outer)
        self.w("b.md", "Inner note about the zebrafish tank.\n", root=self.inner)

    def add(self, path, label):
        con = self.con()
        try:
            return di.add_root(con, path, label)
        finally:
            con.close()

    def refresh(self, **kw):
        con = self.con()
        try:
            return di.refresh(con, self.db, embed="off", log=kw.pop("log", tf.quiet), **kw)
        finally:
            con.close()

    def hits(self, q="zebrafish"):
        return sorted(self.refs(q, limit=20))

    def both_roots(self, first=("outer", "inner")):
        for label in first:
            self.add(self.outer if label == "outer" else self.inner, label)

    def test_f1_one_hit_per_file_under_the_inner_root(self):
        """The field repro, through the command line."""
        for label, path in (("outer", self.outer), ("inner", self.inner)):
            self.assertEqual(self.cli("add-root", path, "--label", label)[0], 0)
        self.assertEqual(self.cli("refresh", "--all", "--embed", "off")[0], 0)
        res = self.cli_json("search", "zebrafish inner", "--json")
        self.assertEqual([h["ref"] for h in res["hits"]], ["inner/b.md#p1"])
        self.assertEqual(self.hits(), ["inner/b.md#p1", "outer/a.md#p1"])
        self.assertEqual(self.q("select count(*) from files where name='b.md'")[0][0], 1)
        self.assertEqual(self.q("select r.label from files f join roots r on r.id=f.root_id where f.name='b.md'")[0][0], "inner")

    def test_f1_an_index_built_by_the_old_code_loses_the_duplicate_on_the_next_refresh(self):
        self.both_roots()
        with mock.patch.object(di, "nested_roots", lambda *a: set()):   # what 0.3.1 did: no root knew about the others
            self.refresh()
        self.assertEqual(self.hits(), ["inner/b.md#p1", "outer/a.md#p1", "outer/inner/b.md#p1"])
        self.refresh()
        self.assertEqual(self.hits(), ["inner/b.md#p1", "outer/a.md#p1"])
        self.assertEqual(self.q("select count(*) from files where root_id=(select id from roots where label='outer')")[0][0], 1)

    def test_f1_the_duplicate_goes_without_prune_too(self):
        self.both_roots()
        with mock.patch.object(di, "nested_roots", lambda *a: set()):
            self.refresh()
        con = self.con()
        stats = di.index_root(con, con.execute("select id, label, path from roots where label='outer'").fetchone(), log=tf.quiet)   # `index`: prune off
        con.close()
        self.assertEqual((stats["removed"], self.hits()), (1, ["inner/b.md#p1", "outer/a.md#p1"]))

    def test_f1_a_root_whose_only_content_is_the_nested_folder_still_drops_the_duplicate(self):
        os.remove(os.path.join(self.outer, "a.md"))
        self.both_roots()
        with mock.patch.object(di, "nested_roots", lambda *a: set()):
            self.refresh()
        said = []
        self.refresh(log=said.append)
        self.assertEqual((self.hits(), said), (["inner/b.md#p1"], []))   # no "refusing to prune": nothing was lost, it moved
        self.assertEqual(self.q("select count(*) from files where root_id=(select id from roots where label='outer')")[0][0], 0)

    def test_f1_roots_added_in_reverse_order_give_the_same_result(self):
        self.both_roots(first=("inner", "outer"))
        self.refresh()
        self.assertEqual(self.hits(), ["inner/b.md#p1", "outer/a.md#p1"])
        self.assertEqual(self.q("select count(*) from files where name='b.md'")[0][0], 1)

    def test_f1_removing_the_inner_root_hands_its_files_back_to_the_outer_root(self):
        self.both_roots()
        self.refresh()
        self.assertEqual(self.cli("remove-root", "inner", "--purge")[0], 0)
        self.assertEqual(self.hits(), ["outer/a.md#p1"])                    # purged with its root
        self.assertEqual(self.cli("refresh", "--all", "--embed", "off")[0], 0)
        self.assertEqual(self.hits(), ["outer/a.md#p1", "outer/inner/b.md#p1"])
        self.assertEqual(self.q("select count(*) from files where name='b.md'")[0][0], 1)

    def test_f1_a_sibling_sharing_a_name_prefix_is_not_nested(self):
        self.w("c.md", "Sibling note about the zebrafish tank.\n", root=self.outer + "2")
        self.w("d.md", "Cousin note about the zebrafish tank.\n", root=os.path.join(self.outer, "inner2"))
        self.both_roots()
        self.add(self.outer + "2", "outer2")
        con = self.con()
        rid = lambda lab: con.execute("select id from roots where label=?", (lab,)).fetchone()[0]   # noqa: E731
        self.assertEqual(di.nested_roots(con, rid("outer"), self.outer), {di.norm_path(self.inner)})   # not outer2, not inner2
        self.assertEqual(di.nested_roots(con, rid("outer2"), self.outer + "2"), set())
        con.close()
        self.refresh()
        self.assertEqual(self.hits(), ["inner/b.md#p1", "outer/a.md#p1", "outer/inner2/d.md#p1", "outer2/c.md#p1"])

    def test_f1_searching_the_outer_root_returns_each_file_once_and_covers_both_roots(self):
        self.both_roots()
        self.refresh()
        res = self.search("zebrafish", root="outer", limit=20)
        self.assertEqual(sorted(h["ref"] for h in res["hits"]), ["inner/b.md#p1", "outer/a.md#p1"])
        self.assertEqual(res["coverage"]["roots"], ["outer", "inner"])
        res = self.search("zebrafish", root="inner", limit=20)
        self.assertEqual((sorted(h["ref"] for h in res["hits"]), res["coverage"]["roots"]), (["inner/b.md#p1"], ["inner"]))

    def test_f1_a_root_scope_covers_the_roots_nested_under_it(self):
        deeper = os.path.join(self.inner, "deeper")
        self.w("c.md", "Deep note about the zebrafish tank.\n", root=deeper)
        self.w("d.md", "Sibling note about the zebrafish tank.\n", root=self.outer + "2")
        self.both_roots()
        self.add(deeper, "deeper")
        self.add(self.outer + "2", "outer2")
        self.refresh()
        for scope, refs, covered in (("outer", ["deeper/c.md#p1", "inner/b.md#p1", "outer/a.md#p1"], ["outer", "inner", "deeper"]),
                                     ("inner", ["deeper/c.md#p1", "inner/b.md#p1"], ["inner", "deeper"]),
                                     ("deeper", ["deeper/c.md#p1"], ["deeper"]),
                                     ("outer2", ["outer2/d.md#p1"], ["outer2"])):   # a name-prefix sibling is not inside outer
            with self.subTest(scope=scope):
                res = self.search("zebrafish", root=scope, limit=20)
                self.assertEqual(sorted(h["ref"] for h in res["hits"]), refs)   # each file once
                self.assertEqual(res["coverage"]["roots"], covered)
        res = self.cli_json("search", "zebrafish", "--root", "outer", "--json", "--limit", "20")
        self.assertEqual((len(res["hits"]), res["coverage"]["roots"]), (3, ["outer", "inner", "deeper"]))
        con = self.con()
        self.assertEqual(sorted(r["ref"] for r in di.files_search(con, "md", 50, "outer")), ["deeper/c.md", "inner/b.md", "outer/a.md"])
        self.assertEqual(sorted(r["ref"] for r in di.files_search(con, "md", 50, "inner")), ["deeper/c.md", "inner/b.md"])
        self.assertEqual(len(di.files_search(con, "md", 50)), 4)   # no --root: every root
        con.close()

    def test_f1_an_absolute_path_resolves_to_the_most_specific_root(self):
        self.both_roots()
        self.refresh()
        con = self.con()
        self.assertEqual(di.find_file(con, os.path.join(self.inner, "b.md"))[1], "inner/b.md")
        self.assertEqual(di.find_file(con, os.path.join(self.outer, "a.md"))[1], "outer/a.md")
        self.assertIn(">> inner/b.md#p1", di.show(con, os.path.join(self.inner, "b.md") + "#p1"))
        con.close()

    def test_f1_a_root_equal_to_another_is_not_nested(self):
        self.add(self.outer, "outer")
        con = self.con()   # the same folder under a second label, as an older index or a hand edit can leave it
        con.execute("insert into roots(label, path, kind) values ('twin', ?, 'documents')", (self.outer,))
        con.commit()
        rid = con.execute("select id from roots where label='outer'").fetchone()[0]
        self.assertEqual(di.nested_roots(con, rid, self.outer), set())
        con.close()
        self.refresh()
        self.assertEqual(self.hits(), ["outer/a.md#p1", "outer/inner/b.md#p1", "twin/a.md#p1", "twin/inner/b.md#p1"])   # both whole, none emptied

    def test_f1_the_same_folder_spelled_another_way_is_the_same_root(self):
        self.assertEqual(self.add(self.outer, "outer"), "outer")
        self.assertEqual(self.add(self.outer + os.sep, "again"), "outer")
        self.assertEqual(self.add(os.path.join(self.outer, "..", "outer"), "again"), "outer")
        if os.path.normcase("A") == "a":   # Windows: paths ignore case
            self.assertEqual(self.add(self.outer.swapcase(), "again"), "outer")
        self.assertEqual(self.q("select count(*) from roots")[0][0], 1)

    def test_f1_paths_are_compared_the_way_the_os_does(self):
        """Stored paths with a trailing separator or the other case are still recognised as nested (case on Windows only)."""
        variants = [self.inner + os.sep, os.path.join(self.outer, ".", "inner")]
        if os.path.normcase("A") == "a":
            variants += [self.inner.swapcase(), self.inner.upper()]
        for n, stored in enumerate(variants):
            self.db = os.path.join(self.tmp, f"idx{n}", "index.sqlite")
            self.add(self.outer, "outer")
            con = self.con()
            con.execute("insert into roots(label, path, kind) values ('inner', ?, 'documents')", (stored,))
            con.commit()
            con.close()
            with self.subTest(stored=stored):
                con = self.con()   # index the outer root only: the stored inner path must be recognised as inside it
                row = con.execute("select id, label, path from roots where label='outer'").fetchone()
                di.index_root(con, row, log=tf.quiet)
                con.close()
                self.assertEqual(self.q("select count(*) from files where name='b.md'")[0][0], 0)
                self.assertEqual(self.q("select count(*) from files where name='a.md'")[0][0], 1)

    def test_f1_a_drive_root_contains_the_other_roots(self):
        self.add(self.outer, "outer")
        top = os.path.splitdrive(os.path.abspath(self.outer))[0] + os.sep   # C:\ or /
        con = self.con()
        for label in ("top", "top-twin"):   # the twin is another root with the very same path: equal, so not nested
            con.execute("insert into roots(label, path, kind) values (?, ?, 'documents')", (label, top))
        con.commit()
        rid = con.execute("select id from roots where label='top'").fetchone()[0]
        self.assertEqual(di.nested_roots(con, rid, top), {di.norm_path(self.outer)})
        con.close()


class Failed(tf.Env):
    """F2 and F3: a model download that failed is remembered for 24 hours and named in mode_reason."""

    def setUp(self):
        super().setUp()
        os.environ.pop("HF_ENDPOINT", None)
        self.w("a.md", "# A\n\nThe quarterly rollout plan covers three regions.\n")
        self.calls = []
        self.outcome = di.ModelDownloadFailed("huggingface.co", "ConnectError")
        self.real_get_embedder = di.get_embedder
        p = mock.patch.object(di, "get_embedder", self.fetch)
        p.start()
        self.addCleanup(p.stop)
        self.index()

    def fetch(self, download=False):
        self.calls.append(download)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    def refresh(self, argv=("refresh", "--all")):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = di.main(["--db", self.db, *argv])
        self.assertEqual(rc, 0, err.getvalue())
        return out.getvalue(), err.getvalue()

    def age(self, hours):
        con = self.con()
        fail = json.loads(di.get_meta(con, "model_fail"))
        fail["at"] = di.iso(time.time() - hours * 3600)
        di.set_meta(con, "model_fail", json.dumps(fail))
        con.commit()
        con.close()

    def test_f2_mode_reason_names_the_host_and_the_error_class(self):
        self.refresh()
        res = self.search("rollout plan")
        self.assertEqual(res["mode"], "keyword")
        for part in ("huggingface.co", "ConnectError"):
            self.assertIn(part, res["mode_reason"])
        self.assertNotIn("no vectors yet", res["mode_reason"])
        out = self.cli_json("search", "rollout plan", "--json")   # from another process: the memory is in the index
        self.assertEqual(out["mode_reason"], res["mode_reason"])
        self.assertTrue(out["hits"])

    def test_f2_vectors_without_a_model_say_the_same(self):
        con = self.con()
        con.execute("insert into vec select id, ?, 384, zeroblob(1536) from paras", (di.MODEL,))
        con.commit()
        con.close()
        self.refresh()
        with mock.patch.object(di, "get_embedder", side_effect=di.ModelMissing("the embedding model is not downloaded yet (run: doc_index.py embed)")):
            reason = self.search("rollout plan")["mode_reason"]
        self.assertIn("huggingface.co failed (ConnectError)", reason)

    def place_model(self, content=b""):
        model = os.path.join(di.models_dir(), "models--Qdrant--bge-small-en-v1.5-onnx-Q", "snapshots", "abc", di.MODEL_FILE)
        os.makedirs(os.path.dirname(model))
        with open(model, "wb") as f:
            f.write(content)
        return model

    def test_f2_a_model_on_disk_means_the_failure_is_no_longer_the_reason(self):
        self.refresh()
        self.assertIn("ConnectError", self.search("rollout plan")["mode_reason"])
        self.place_model()
        reason = self.search("rollout plan")["mode_reason"]   # no vectors yet, but the model is here: embed will work
        self.assertIn("no vectors yet", reason)
        self.assertNotIn("model download from", reason)

    def test_f2_a_corrupt_model_keeps_its_own_reason(self):
        con = self.con()
        con.execute("insert into vec select id, ?, 384, zeroblob(1536) from paras", (di.MODEL,))
        con.commit()
        con.close()
        self.refresh()
        model = self.place_model(b"this is not the pinned model")
        with mock.patch.object(di, "get_embedder", self.real_get_embedder):
            reason = self.search("rollout plan")["mode_reason"]
        self.assertIn("SHA-256", reason)
        self.assertNotIn("model download from", reason)
        self.assertFalse(os.path.exists(model))

    def test_f2_without_a_failure_the_old_reasons_stand(self):
        self.assertIn("no vectors yet", self.search("rollout plan")["mode_reason"])

    def test_f3_a_refresh_inside_the_window_makes_no_network_attempt(self):
        out, err = self.refresh()
        self.assertEqual(self.calls, [True])
        out2, err2 = self.refresh()
        self.assertEqual(self.calls, [True])                               # still one: nothing was fetched the second time
        for text in (out, err, out2, err2):
            for bad in ("Traceback", "ERROR", "token", "Retrying", "sleeping"):
                self.assertNotIn(bad, text)
        lines = [ln for ln in err2.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, err2)                              # one plain line
        self.assertTrue(lines[0].startswith("embedding: model download from huggingface.co failed") and "huggingface.co" in lines[0] and "ConnectError" in lines[0], lines[0])
        self.assertEqual(json.loads(out2)["embed"]["embedded"], 0)

    def test_f3_the_json_output_stays_pure_json(self):
        out, err = self.refresh(("refresh", "--all", "--json"))
        self.assertEqual(json.loads(out)["embed"]["model"], None)
        self.assertIn("huggingface.co", err)

    def test_f3_after_24_hours_it_tries_once_again(self):
        self.refresh()
        self.age(23)
        self.refresh()
        self.assertEqual(self.calls, [True])                               # 23 h: still remembered
        self.age(25)
        self.refresh()
        self.assertEqual(self.calls, [True, True])                         # 25 h: one more attempt
        self.refresh()
        self.assertEqual(self.calls, [True, True])                         # and the new failure is remembered afresh
        con = self.con()
        self.assertIsNotNone(di.model_failure(con))
        con.close()

    def test_f3_another_download_host_is_a_new_try(self):
        self.refresh()
        os.environ["HF_ENDPOINT"] = "https://mirror.example.com"
        self.refresh()
        self.assertEqual(self.calls, [True, True])
        con = self.con()
        self.assertEqual(json.loads(di.get_meta(con, "model_fail"))["host"], "huggingface.co")   # the stand-in fetcher names its own host
        con.close()

    def test_f3_the_embed_command_tries_now(self):
        self.refresh()
        self.refresh(("embed",))
        self.assertEqual(self.calls, [True, True])

    def test_f3_a_model_found_on_disk_is_used_whatever_was_remembered(self):
        self.refresh()
        model = os.path.join(di.models_dir(), "models--Qdrant--bge-small-en-v1.5-onnx-Q", "snapshots", "abc", di.MODEL_FILE)
        os.makedirs(os.path.dirname(model))
        open(model, "wb").close()
        self.refresh()
        self.assertEqual(self.calls, [True, True])

    def test_f3_success_forgets_the_failure(self):
        tf.need(self, "numpy")
        self.refresh()
        self.age(25)
        self.outcome = tf.Vectors.Fake()
        self.refresh()
        con = self.con()
        self.assertIsNone(di.get_meta(con, "model_fail"))
        self.assertGreater(con.execute("select count(*) from vec").fetchone()[0], 0)
        con.close()
        self.assertEqual(self.search("rollout plan")["mode"], "hybrid")

    def test_f3_other_failures_are_not_remembered(self):
        self.outcome = di.ModelUnavailable("offline (HF_HUB_OFFLINE is set) and the embedding model is not downloaded")
        self.refresh()
        self.refresh()
        self.assertEqual(self.calls, [True, True])                         # no network was involved, so nothing to wait for
        con = self.con()
        self.assertIsNone(di.get_meta(con, "model_fail"))
        con.close()


class DownloadLoop(tf.Env):
    """F3 through fastembed's own download code, with the network entry point faked."""

    def test_f3_one_attempt_no_sleep_no_library_log_lines_no_token_wording(self):
        tf.need(self, "numpy", "fastembed")
        from fastembed.common import model_management as mm
        from loguru import logger
        os.environ["HF_HUB_OFFLINE"] = "0"
        os.environ.pop("HF_ENDPOINT", None)

        class Blocked(OSError):
            pass
        network, sleeps, lines = [], [], []

        def model_info(*a, **k):
            network.append(a)
            raise Blocked("401 Unauthorized: Invalid user token for https://huggingface.co/api/models/x")
        sink = logger.add(lines.append, level="DEBUG")
        try:
            with mock.patch.object(mm, "model_info", model_info), mock.patch("time.sleep", lambda s: sleeps.append(s)):
                with self.assertRaises(di.ModelDownloadFailed) as cm:
                    di.get_embedder(download=True)
        finally:
            logger.remove(sink)
        self.assertEqual((len(network), sleeps, lines), (1, [], []))
        self.assertEqual((cm.exception.host, cm.exception.error), ("huggingface.co", "Blocked"))
        self.assertNotIn("token", str(cm.exception).lower())
        self.assertIs(mm.time, time)                                        # the patch is undone
        with self.assertRaises(di.ModelDownloadFailed):                     # and a second call is again exactly one attempt
            with mock.patch.object(mm, "model_info", model_info), mock.patch("time.sleep", lambda s: sleeps.append(s)):
                di.get_embedder(download=True)
        self.assertEqual((len(network), sleeps), (2, []))

    def test_f3_a_library_that_changed_shape_is_left_alone(self):
        tf.need(self, "numpy", "fastembed")
        from fastembed.common import model_management as mm
        name = "download_files_from_huggingface"
        static = staticmethod(lambda *a, **k: None)   # not the classmethod this code knows how to wrap
        with mock.patch.object(mm.ModelManagement, name, static):
            with di.one_download_attempt({}):
                self.assertIs(mm.ModelManagement.__dict__[name], static)
                self.assertIs(mm.time, time)

    def test_f3_a_tls_failure_inside_the_library_still_retries_over_plain_https(self):
        tf.need(self, "numpy", "fastembed")
        from fastembed.common import model_management as mm
        import huggingface_hub.constants as hc
        os.environ["HF_HUB_OFFLINE"] = "0"
        os.environ.pop("HF_HUB_DISABLE_XET", None)
        network = []

        def model_info(*a, **k):
            network.append(os.environ.get("HF_HUB_DISABLE_XET"))
            raise OSError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")   # the library swallows this one too
        with mock.patch.object(mm, "model_info", model_info), mock.patch("time.sleep", lambda s: None), \
                mock.patch.object(hc, "HF_HUB_DISABLE_XET", False):
            with self.assertRaises(di.ModelDownloadFailed) as cm:
                di.get_embedder(download=True)
        self.assertEqual(network, [None, "1"])
        self.assertEqual(cm.exception.error, "OSError")
        os.environ.pop("HF_HUB_DISABLE_XET", None)


class ShortNames(tf.Env):
    """Windows 8.3 short names (PROGRA~1): one folder spelled two ways is one folder. On a volume without short names, and
    elsewhere, a stand-in expander knows two made-up aliases, so the same assertions run."""

    @staticmethod
    def short_of(path):
        if os.name != "nt":
            return path
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        return buf.value if ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf)) else path

    def setUp(self):
        super().setUp()
        self.outer = os.path.join(self.tmp, "outer-long-folder-name")
        self.inner = os.path.join(self.outer, "inner-long-folder-name")
        self.w("a.md", "Outer note about the zebrafish tank.\n", root=self.outer)
        self.w("b.md", "Inner note about the zebrafish tank.\n", root=self.inner)
        self.real_long_path = di.long_path
        self.real_names = self.short_of(self.inner).lower() != self.inner.lower()
        if self.real_names:
            self.a_outer, self.a_inner = self.short_of(self.outer), self.short_of(self.inner)
        else:
            self.a_outer = os.path.join(self.tmp, "OUTERL~1")
            self.a_inner = os.path.join(self.a_outer, "INNERL~1")
            p = mock.patch.object(di, "long_path", lambda s: s.replace("OUTERL~1", "outer-long-folder-name").replace("INNERL~1", "inner-long-folder-name"))
            p.start()
            self.addCleanup(p.stop)

    def refresh_with(self, outer, inner, db):
        self.db = os.path.join(self.tmp, db, "index.sqlite")
        con = self.con()
        di.add_root(con, outer, "outer")
        di.add_root(con, inner, "inner")
        di.refresh(con, self.db, embed="off", log=tf.quiet)
        con.close()
        return sorted(self.refs("zebrafish", limit=20))

    def test_8_3_a_long_outer_root_and_a_short_spelled_inner_root_do_not_duplicate(self):
        self.assertEqual(self.refresh_with(self.outer, self.a_inner, "i1"), ["inner/b.md#p1", "outer/a.md#p1"])

    def test_8_3_a_short_spelled_outer_root_and_a_long_inner_root_do_not_duplicate(self):
        self.assertEqual(self.refresh_with(self.a_outer, self.inner, "i2"), ["inner/b.md#p1", "outer/a.md#p1"])

    def test_8_3_both_short_spelled_do_not_duplicate(self):
        self.assertEqual(self.refresh_with(self.a_outer, self.a_inner, "i3"), ["inner/b.md#p1", "outer/a.md#p1"])
        self.assertEqual(self.q("select count(*) from files where name='b.md'")[0][0], 1)

    def test_8_3_the_same_folder_added_by_its_long_and_its_short_name_is_one_root(self):
        con = self.con()
        self.assertEqual(di.add_root(con, self.outer, "outer"), "outer")
        self.assertEqual(di.add_root(con, self.a_outer, "again"), "outer")
        self.assertEqual(con.execute("select count(*) from roots").fetchone()[0], 1)
        con.close()

    def test_8_3_an_absolute_path_in_either_spelling_resolves_to_the_inner_root(self):
        self.refresh_with(self.outer, self.inner, "i4")
        con = self.con()
        for spelled in (os.path.join(self.inner, "b.md"), os.path.join(self.a_inner, "b.md")):
            self.assertEqual(di.find_file(con, spelled)[1], "inner/b.md")
        con.close()

    def test_8_3_long_path_expands_what_exists_and_keeps_the_rest(self):
        norm = os.path.normcase
        self.assertEqual(norm(self.real_long_path(os.path.join(self.outer, "missing", "x"))), norm(os.path.join(self.outer, "missing", "x")))
        if self.real_names:
            self.assertEqual(norm(self.real_long_path(os.path.join(self.a_inner, "nope", "x"))), norm(os.path.join(self.inner, "nope", "x")))
            self.assertEqual(norm(self.real_long_path(self.a_inner)), norm(self.inner))
        if os.name != "nt":
            self.assertEqual(self.real_long_path(self.a_inner), self.a_inner)


class LongPathCalls(unittest.TestCase):
    """long_path asks the file system only about paths that can hold an 8.3 name (those with a "~"): on an unreachable
    network share every such question stalls for about 20 seconds. A counting stand-in for ctypes, on any OS."""

    def count_calls(self, *paths):
        calls = []

        class Buf:
            value = ""

            def __len__(self):
                return 32768
        k32 = mock.Mock()
        k32.GetLongPathNameW.side_effect = lambda head, buf, size: calls.append(head) or 0   # 0: "no such path", the fallback runs
        fake = mock.Mock(create_unicode_buffer=lambda n: Buf(), windll=mock.Mock(kernel32=k32))
        with mock.patch.dict(sys.modules, {"ctypes": fake}), mock.patch.object(os, "name", "nt"):
            for p in paths:
                di.long_path(p)
                di.long_path(p)
        return calls

    def test_a_path_without_a_tilde_never_reaches_the_file_system(self):
        self.assertEqual(self.count_calls("\\\\files.example.com\\share\\docs", "D:\\shared\\reports", "\\\\host\\share"), [])

    def test_a_path_with_a_tilde_still_does(self):
        calls = self.count_calls("C:\\PROGRA~1\\docs")
        self.assertTrue(calls and calls[0] == "C:\\PROGRA~1\\docs", calls)


class Coverage(tf.Env):
    def test_f4_coverage_roots_lists_only_the_roots_searched(self):
        d2 = os.path.join(self.tmp, "second")
        self.w("a.md", "zebrafish in the first library")
        self.w("b.md", "zebrafish in the second library", root=d2)
        self.index(label="docs")
        self.index(root=d2, label="other")
        self.assertEqual(self.search("zebrafish")["coverage"]["roots"], ["docs", "other"])
        self.assertEqual(self.search("zebrafish", root="docs")["coverage"]["roots"], ["docs"])
        self.assertEqual(self.search("zebrafish", root="other")["coverage"]["roots"], ["other"])
        self.assertEqual(self.search("zebrafish", root="nowhere")["coverage"]["roots"], [])
        self.assertEqual(self.cli_json("search", "zebrafish", "--root", "other", "--json")["coverage"]["roots"], ["other"])


class Columns(tf.Env):
    LONG = "a-rather-long-library-label-for-the-team-share"

    def test_f5_table_sizes_columns_from_the_data(self):
        self.assertEqual(di.table([("ab", "x", 5, "p"), ("a-very-long-label", "yy", 12345, "q")], right=(2,)),
                         ["ab" + " " * 17 + "x" + " " * 7 + "5  p", "a-very-long-label  yy  12345  q"])
        self.assertEqual(di.table([("a", "")], indent="  "), ["  a"])      # no trailing spaces

    def test_f5_roots_columns_never_touch(self):
        self.w("a.md", "plain words")
        self.assertEqual(self.cli("add-root", self.root, "--label", self.LONG)[0], 0)
        self.assertEqual(self.cli("add-root", os.path.join(self.tmp, "x"), "--label", "x")[0], 0)
        rc, out, _ = self.cli("roots")
        self.assertEqual(rc, 0)
        rows = [re.match(r"^(\S+)\s{2,}(\S+)\s{2,}\s*(\d+)\s{2,}(.+)$", ln) for ln in out.splitlines()]
        self.assertTrue(all(rows), out)
        self.assertEqual([m.group(1) for m in rows], [self.LONG, "x"])
        self.assertEqual(len({m.start(4) for m in rows}), 1)                # the path column starts in one place

    def test_f5_status_lists_roots_and_problems_in_separate_columns(self):
        self.w("a.md", "plain words")
        with open(os.path.join(self.root, "locked.docx"), "wb") as f:
            f.write(di.OLE_MAGIC + b"\0" * 100)
        self.index(label=self.LONG)
        con = self.con()
        con.execute("update files set status='cloud-only', error='online only' where name='a.md'")   # the longest status word
        con.commit()
        con.close()
        rc, out, _ = self.cli("status")
        self.assertEqual(rc, 0)
        lines = out.splitlines()
        root = next(ln for ln in lines if self.LONG in ln and not ln.lstrip().startswith(("cloud", "failed")))
        self.assertRegex(root, r"^  " + re.escape(self.LONG) + r"\s{2,}\d+ files\s{2,}\d+ vectors\s{2,}\S")
        for status in ("cloud-only", "failed"):
            line = next(ln for ln in lines if ln.lstrip().startswith(status))
            self.assertRegex(line, r"^  " + status + r"\s{2,}" + re.escape(self.LONG) + r"/\S+")
        cloud, failed = (next(ln for ln in lines if ln.lstrip().startswith(s)) for s in ("cloud-only", "failed"))
        self.assertEqual(cloud.index(self.LONG), failed.index(self.LONG))   # the ref column lines up


if __name__ == "__main__":
    unittest.main()
