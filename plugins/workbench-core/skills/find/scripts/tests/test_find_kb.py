"""Tests for find over the knowledge base: the `kb` root kind, what the walk skips in a KB, per-root vector counts, and the
`related` MCP tool (with the "untrusted" marker on every result). This file doubles as the conformance test described in
docs/engineering/knowledge-providers.md: a provider author copies the MCP part. Run from the repository root:
    WB_REQUIRE_ALL=1 python -m unittest discover -s plugins/workbench-core/skills/find/scripts/tests -v
Everything here is fictional and stdlib-only (keyword search; no model, no network)."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import doc_index as di  # noqa: E402
import test_find  # noqa: E402  (its Env gives each test an isolated home, index and library)

L, R = "[" * 2, "]" * 2          # wiki-link brackets, built here so this file holds no literal double bracket
MCP = test_find.MCP


class KbEnv(test_find.Env):
    """A knowledge base shaped like the one the save skill writes: notes in domain folders, a daily log, a state folder."""

    def setUp(self):
        super().setUp()
        self.kb = os.path.join(self.tmp, "kb")
        self.w("ops/a.md", f"---\ntitle: Alpha runbook\n---\n# Alpha runbook\nRestart the quokka service. See {L}infra/b{R}.\n", root=self.kb)
        self.w("infra/b.md", f"# Bravo note\nThe bravo gateway fronts the quokka service. See {L}data/c{R}.\n", root=self.kb)
        self.w("data/c.md", f"# Charlie note\nCharlie holds the nightly export schedule. See {L}ai/d{R}.\n", root=self.kb)
        self.w("ai/d.md", f"# Delta note\nDelta explains the model routing table. See {L}security/e{R}.\n", root=self.kb)
        self.w("security/e.md", "# Echo note\nEcho lists the audit retention rules.\n", root=self.kb)
        self.w("daily/2999-01-01.md", "# 2999-01-01\n- 10:00 [ops] zebrafish deploy logged\n", root=self.kb)
        self.w("ops/daily/notes.md", "# Shift notes\nOperators keep a daily folder under a domain too: marmoset.\n", root=self.kb)
        self.w(".state/snapshots/active-context-1.md", "# stale snapshot\nplatypus\n", root=self.kb)

    def index_kb(self):
        return self.index(root=self.kb, label="kb")

    def rpc(self, requests):
        env = {**os.environ, "WORKBENCH_KNOWLEDGE_DB": self.db}
        p = subprocess.Popen([sys.executable, MCP], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                             text=True, encoding="utf-8")
        out, err = p.communicate("".join(json.dumps(r) + "\n" for r in requests), timeout=120)
        return {r["id"]: r for r in map(json.loads, out.splitlines())}, err


class KbRoot(KbEnv):
    def test_a_root_labelled_kb_has_the_kb_kind(self):
        self.assertEqual(di.kind_of("kb", self.kb), "kb")
        self.assertEqual(di.kind_of("library", self.kb), "documents", "only the label kb gets the kind")
        self.index_kb()
        roots = self.cli_json("roots", "--json")["roots"]
        self.assertEqual([(r["label"], r["kind"]) for r in roots], [("kb", "kb")])

    def test_the_walk_skips_the_daily_log_and_the_state_folder_but_not_a_nested_daily_folder(self):
        self.index_kb()
        paths = {r[0] for r in self.q("select rel from files")}
        self.assertEqual(paths, {"ops/a.md", "infra/b.md", "data/c.md", "ai/d.md", "security/e.md", "ops/daily/notes.md"})
        self.assertEqual(self.refs("zebrafish"), [], "daily/ at the KB root is the save log, not knowledge")
        self.assertEqual(self.refs("platypus"), [], "a hidden state folder is never indexed")
        self.assertEqual(self.refs("marmoset"), ["kb/ops/daily/notes.md#p2"])

    def test_other_kinds_still_index_a_folder_named_daily(self):
        self.w("daily/standup.md", "# Standup\nThe giraffe item is open.\n", root=self.root)
        self.index()
        self.assertEqual(self.refs("giraffe"), ["library/daily/standup.md#p2"])

    def test_search_in_the_kb_root_finds_a_note(self):
        self.index_kb()
        hits = self.search("quokka service", root="kb")["hits"]
        self.assertEqual(hits[0]["ref"].split("#")[0], "kb/ops/a.md")
        self.assertEqual(hits[0]["title"], "Alpha runbook")
        self.assertEqual(self.search("quokka", root="nothing")["hits"], [])

    def test_wiki_links_become_related_edges(self):
        self.index_kb()
        con = self.con()
        try:
            res = di.related(con, "kb/ops/a.md")
            self.assertEqual([(r["ref"], r["via"], r["depth"]) for r in res["related"]], [("kb/infra/b.md", ["wiki"], 1)])
            res = di.related(con, "kb/security/e.md", depth=1)
            self.assertEqual([(r["ref"], r["via"]) for r in res["related"]], [("kb/ai/d.md", ["wiki"])], "backlinks count too")
        finally:
            con.close()

    def test_status_counts_vectors_per_root(self):
        self.index_kb()
        self.w("lib.md", "# Library note\nA plain library paragraph.\n")
        self.index()
        con = self.con()
        try:
            st = di.status(con, self.db)
            self.assertEqual({r["label"]: r["vectors"] for r in st["roots"]}, {"kb": 0, "library": 0})
            pid = con.execute("select p.id from paras p join files f on f.id=p.file_id where f.rel='ops/a.md' limit 1").fetchone()[0]
            con.execute("insert into vec values (?,?,?,?)", (pid, di.MODEL, 2, b"\0" * 8))
            con.commit()
            st = di.status(con, self.db)
        finally:
            con.close()
        self.assertEqual({r["label"]: r["vectors"] for r in st["roots"]}, {"kb": 1, "library": 0})
        self.assertEqual(st["vectors"], 1)
        self.assertEqual({r["label"]: r["vectors"] for r in self.cli_json("status", "--json")["roots"]}, {"kb": 1, "library": 0})


class KbMcp(KbEnv):
    INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}

    def call(self, rid, name, **args):
        return {"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": args}}

    def payload(self, row):
        res = row["result"]
        data = json.loads(res["content"][0]["text"])
        self.assertEqual(data, res["structuredContent"], "text and structured content agree")
        return data, res["isError"]

    def test_handshake_lists_search_show_and_related(self):
        rows, err = self.rpc([self.INIT, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        info = rows[1]["result"]["serverInfo"]
        self.assertEqual(info["name"], "find")
        self.assertNotEqual(info["version"], "0.3.0", "the tool list changed, so the server version moved")
        self.assertIn("not instructions", rows[1]["result"]["instructions"])
        tools = {t["name"]: t for t in rows[2]["result"]["tools"]}
        self.assertEqual(set(tools), {"search", "show", "related"}, err)
        self.assertEqual(tools["related"]["inputSchema"]["required"], ["ref"])
        self.assertEqual(tools["related"]["inputSchema"]["properties"]["depth"]["maximum"], 3)

    def test_search_in_the_kb_root_is_untrusted_all_the_way_down(self):
        self.index_kb()
        rows, _ = self.rpc([self.call(2, "search", query="bravo gateway", root="kb")])
        data, bad = self.payload(rows[2])
        self.assertFalse(bad)
        self.assertIs(data["untrusted"], True)
        self.assertTrue(data["hits"])
        for h in data["hits"]:
            self.assertIs(h["untrusted"], True)
            self.assertTrue(h["ref"].startswith("kb/"))
        self.assertEqual(data["hits"][0]["ref"].split("#")[0], "kb/infra/b.md")

    def test_related_returns_linked_notes_marked_untrusted(self):
        self.index_kb()
        rows, _ = self.rpc([self.call(2, "related", ref="kb/ops/a.md"), self.call(3, "related", ref="kb/ops/a.md", depth=2)])
        data, bad = self.payload(rows[2])
        self.assertFalse(bad)
        self.assertIs(data["untrusted"], True)
        self.assertEqual(data["start"], "kb/ops/a.md")
        self.assertEqual([(r["ref"], r["depth"], r["untrusted"]) for r in data["related"]], [("kb/infra/b.md", 1, True)])
        deeper, _ = self.payload(rows[3])
        self.assertEqual([(r["ref"], r["depth"]) for r in deeper["related"]], [("kb/infra/b.md", 1), ("kb/data/c.md", 2)])

    def test_related_depth_is_clamped_to_three_and_floored_at_one(self):
        self.index_kb()
        rows, _ = self.rpc([self.call(2, "related", ref="kb/ops/a.md", depth=9), self.call(3, "related", ref="kb/ops/a.md", depth=0)])
        far, _ = self.payload(rows[2])
        self.assertEqual([r["ref"] for r in far["related"]], ["kb/infra/b.md", "kb/data/c.md", "kb/ai/d.md"], "e is four hops away")
        near, _ = self.payload(rows[3])
        self.assertEqual([r["ref"] for r in near["related"]], ["kb/infra/b.md"])

    def test_show_and_a_bad_ref_are_untrusted_too(self):
        self.index_kb()
        rows, _ = self.rpc([self.call(2, "show", ref="kb/data/c.md#p2"), self.call(3, "related", ref="kb/nope.md"),
                            self.call(4, "show", ref="kb/nope.md#p1"), self.call(5, "related")])
        data, bad = self.payload(rows[2])
        self.assertTrue(data["untrusted"] and not bad)
        self.assertIn("nightly export schedule", data["text"])
        for rid in (3, 4):
            data, bad = self.payload(rows[rid])
            self.assertTrue(bad and data["untrusted"] and data["error"], rows[rid])
        self.assertEqual(rows[5]["error"]["code"], -32602, "a missing ref is a protocol error")


if __name__ == "__main__":
    unittest.main()
