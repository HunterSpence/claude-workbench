"""Tests for the api-bridge skill: inventory and draft scripts on a fixture API, the worksheet checks, and a curated
bridge driven end to end by the Python SDK client against that fixture (which counts every hit).

  WB_REQUIRE_ALL=1 python -m unittest discover -s <this dir> -v      (needs the `mcp` package)
"""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: a missing dependency fails instead of skipping

import asyncio  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
import urllib.request  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
BRIDGE = SKILL / "templates" / "bridge-python"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BRIDGE))
sys.path.insert(0, str(SKILL / "scripts"))
import openapi_draft  # noqa: E402
import openapi_inventory  # noqa: E402
import worksheet  # noqa: E402
from fixture_api import TOKEN, FixtureAPI  # noqa: E402

try:
    from mcp import ClientSession, StdioServerParameters, stdio_client
except ImportError:
    if REQUIRE:
        raise
    ClientSession = None

READS = {
    "version": 1, "service": "example",
    "tools": [
        {"name": "items_get", "title": "Get an item", "description": "Return one item and its history. Use an id from items_list.",
         "mode": "read", "operations": ["GET /items/{item_id}", "GET /items/{item_id}/history"],
         "params": [{"name": "item_id", "in": "path", "type": "string", "required": True, "description": "Item identifier"}],
         "text_fields": ["note"], "max_bytes": 20000},
        {"name": "items_list", "title": "List items", "description": "List items, one page per call.", "mode": "read",
         "operations": ["GET /items"],
         "params": [{"name": "limit", "in": "query", "type": "integer", "required": False, "default": 20, "description": "Page size"}],
         "text_fields": ["name", "note"], "max_bytes": 20000},
        {"name": "flaky_get", "title": "Flaky read", "description": "Read an endpoint that rate limits once.", "mode": "read",
         "operations": ["GET /flaky"], "params": [], "max_bytes": 5000},
    ],
}
CREATE = {"name": "items_create", "title": "Create an item", "description": "Create an item. Repeating a call with the same idempotency_key does not create a second one.",
          "mode": "write", "operations": ["POST /items"], "destructive": False, "idempotency_header": "Idempotency-Key",
          "params": [{"name": "name", "in": "body", "type": "string", "required": True, "description": "Item name"}], "max_bytes": 5000}
WITH_WRITE = {**READS, "tools": READS["tools"] + [CREATE]}


def run_bridge(api, ws, steps):
    """Copy the template beside `ws`, start it over stdio against `api`, run the async `steps(session)`; return its result."""
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("bridge.py", "worksheet.py"):
            shutil.copy(BRIDGE / name, tmp)
        Path(tmp, "worksheet.json").write_text(json.dumps(ws), encoding="utf-8")
        params = StdioServerParameters(command=sys.executable, args=["bridge.py"], cwd=tmp,
                                       env={"UPSTREAM_BASE_URL": api.base_url, "UPSTREAM_TOKEN": TOKEN})

        async def go():
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await steps(session)
        return asyncio.run(go())


async def call(session, name, args):
    res = await session.call_tool(name, args)
    return {"is_error": res.is_error, "data": res.structured_content, "text": res.content[0].text if res.content else ""}


class Scripts(unittest.TestCase):
    def test_inventory_and_draft_run_on_the_fixture_spec(self):
        with FixtureAPI() as api, tempfile.TemporaryDirectory() as tmp:
            spec_file = Path(tmp) / "openapi.json"
            spec_file.write_bytes(urllib.request.urlopen(api.base_url + "/openapi.json").read())   # the fixture serves its own spec
            inv = subprocess.run([sys.executable, str(SKILL / "scripts/openapi_inventory.py"), str(spec_file), "--json"], capture_output=True, text=True)
            self.assertEqual(inv.returncode, 0, inv.stderr)
            rows = json.loads(inv.stdout)
            self.assertEqual({(r["method"], r["path"]) for r in rows},
                             {("GET", "/items"), ("POST", "/items"), ("GET", "/items/{item_id}"), ("DELETE", "/items/{item_id}"),
                              ("GET", "/items/{item_id}/history"), ("GET", "/flaky")})
            get_item = next(r for r in rows if r["operation_id"] == "getItem")
            self.assertEqual(get_item["params"], ["item_id:path*"])
            self.assertEqual(get_item["auth"], ["bearerAuth"])
            self.assertEqual(get_item["size"], {"list": False, "properties": 3})
            table = subprocess.run([sys.executable, str(SKILL / "scripts/openapi_inventory.py"), str(spec_file)], capture_output=True, text=True)
            self.assertIn("6 operations (4 reads, 2 writes)", table.stdout)
            out = Path(tmp) / "draft.json"
            self.assertEqual(subprocess.run([sys.executable, str(SKILL / "scripts/openapi_draft.py"), str(spec_file), "--out", str(out)]).returncode, 0)
            draft = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("_draft", draft)
            self.assertEqual(len(draft["tools"]), 6)
            self.assertEqual({t["name"] for t in draft["tools"] if not t["keep"]}, {"create_item", "delete_item"})   # writes default to drop
            # the draft is reference only: the worksheet check refuses it until it is curated
            self.assertTrue(any("draft" in e for e in worksheet.check(draft)))
            self.assertEqual(subprocess.run([sys.executable, str(BRIDGE / "worksheet.py"), str(out)], capture_output=True).returncode, 1)


class WorksheetChecks(unittest.TestCase):
    def reasons(self, **changes):
        tool = {**copy.deepcopy(READS["tools"][0]), **changes}
        return worksheet.check({**READS, "tools": [tool]}), tool

    def test_the_curated_reads_and_the_example_pass(self):
        self.assertEqual(worksheet.check(READS), [])
        self.assertEqual(worksheet.check(WITH_WRITE), [])
        self.assertEqual(worksheet.check(json.loads((BRIDGE / "worksheet.example.json").read_text(encoding="utf-8"))), [])
        spec = FixtureAPI().spec()
        self.assertEqual(worksheet.check(WITH_WRITE, spec), [])
        self.assertTrue(any("not in the OpenAPI" in e for e in worksheet.check({**READS, "tools": [{**READS["tools"][2], "operations": ["GET /nowhere"]}]}, spec)))

    def test_a_catch_all_request_tool_is_refused(self):
        catch_all = {"name": "api_request", "title": "Call the API", "description": "Call any endpoint.", "mode": "read",
                     "operations": ["{method} {path}"], "params": [{"name": "method", "in": "query", "type": "string", "required": True},
                                                                      {"name": "path", "in": "query", "type": "string", "required": True}]}
        errs = worksheet.check({**READS, "tools": [catch_all]})
        self.assertTrue(any("catch-all" in e and "literal" in e for e in errs), errs)
        self.assertTrue(any("param 'method'" in e for e in errs))
        self.assertTrue(any("param 'path'" in e for e in errs))
        self.assertEqual(subprocess.run([sys.executable, str(BRIDGE / "worksheet.py"), self._write({**READS, "tools": [catch_all]})], capture_output=True).returncode, 1)

    def _write(self, ws):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        self.addCleanup(os.unlink, f.name)
        json.dump(ws, f)
        f.close()
        return f.name

    def test_forwarding_identity_headers_credentials_and_mixing_are_refused(self):
        errs, _ = self.reasons(forward_token=True)
        self.assertTrue(any("must not forward the caller's token" in e for e in errs))
        self.assertTrue(any("unsigned header" in e for e in worksheet.check({**READS, "identity_header": "X-User"})))
        errs, _ = self.reasons(params=[{"name": "as_user", "in": "query", "type": "string", "required": True}])
        self.assertTrue(any("caller identity" in e for e in errs))
        errs, _ = self.reasons(params=[{"name": "authorization", "in": "query", "type": "string", "required": True}])
        self.assertTrue(any("credential" in e for e in errs))
        errs, _ = self.reasons(params=[{"name": "x", "in": "header", "type": "string", "required": True}])
        self.assertTrue(any("headers and cookies" in e for e in errs))
        errs, _ = self.reasons(operations=["GET /items/{item_id}", "DELETE /items/{item_id}"])
        self.assertTrue(any("read tool may only use GET" in e for e in errs))
        errs, _ = self.reasons(mode="write", operations=["GET /items/{item_id}"], destructive=False, idempotent=True)
        self.assertTrue(any("exactly one POST" in e for e in errs))
        errs, _ = self.reasons(mode="write", operations=["DELETE /items/{item_id}"])
        self.assertTrue(any("destructive" in e for e in errs) and any("idempotency" in e for e in errs))

    def test_tool_count_and_defaults_are_enforced(self):
        many = [{**READS["tools"][2], "name": f"flaky_{i}"} for i in range(16)]
        self.assertTrue(any("16 kept tools" in e for e in worksheet.check({**READS, "tools": many})))
        self.assertTrue(any("0 kept tools" in e for e in worksheet.check({**READS, "tools": []})))
        errs, _ = self.reasons(params=[{"name": "limit", "in": "query", "type": "integer", "required": False}])
        self.assertTrue(any("need a `default`" in e for e in errs))
        errs, _ = self.reasons(keep=False)
        self.assertTrue(any("0 kept tools" in e for e in errs))   # a dropped tool does not count


@unittest.skipIf(ClientSession is None, "mcp is not installed")
class CuratedBridge(unittest.TestCase):
    def test_a_client_call_is_answered_from_the_fixture_api(self):
        async def steps(s):
            tools = (await s.list_tools()).tools
            got = await call(s, "items_get", {"item_id": "a1"})
            missing = await call(s, "items_get", {"item_id": "zz"})
            bogus = await call(s, "items_list", {"limit": 5, "bogus": 1})
            traversal = await call(s, "items_get", {"item_id": ".."})
            return tools, got, missing, bogus, traversal

        with FixtureAPI() as api:
            tools, got, missing, bogus, traversal = run_bridge(api, READS, steps)
            self.assertEqual({t.name for t in tools}, {"items_get", "items_list", "flaky_get"})
            self.assertTrue(all(t.annotations.read_only_hint and t.title for t in tools))
            self.assertFalse(got["is_error"])
            item = got["data"]["data"]["GET /items/{item_id}"]
            self.assertEqual((item["id"], item["name"]), ("a1", "First"))
            self.assertTrue(item["note"].startswith("<untrusted-data>") and item["note"].endswith("</untrusted-data>"))   # free text is labelled
            self.assertEqual(got["data"]["data"]["GET /items/{item_id}/history"]["events"], ["created a1"])
            self.assertEqual(api.hits["GET /items/{item_id}"], 2)   # the 'a1' call and the 'zz' call: the fixture counted the hits
            self.assertEqual(api.hits["GET /items/{item_id}/history"], 1)
            self.assertTrue(missing["is_error"])
            self.assertIn("status 404", missing["text"])
            self.assertTrue(bogus["is_error"] and "bogus" in bogus["text"])
            self.assertTrue(traversal["is_error"])
            self.assertEqual(set(api.auth_seen), {f"Bearer {TOKEN}"})   # only the bridge's own credential ever reached upstream

    def test_retry_after_is_honoured(self):
        async def steps(s):
            return await call(s, "flaky_get", {})
        with FixtureAPI() as api:
            res = run_bridge(api, READS, steps)
            self.assertFalse(res["is_error"], res["text"])
            self.assertEqual(res["data"]["data"], {"ok": True})
            self.assertEqual(api.hits["GET /flaky"], 2)   # one 429 with Retry-After, then the retry

    def test_a_write_endpoint_is_not_exposed_unless_curated_in(self):
        async def read_only(s):
            names = {t.name for t in (await s.list_tools()).tools}
            attempt = await call(s, "items_create", {"name": "X", "idempotency_key": "key-for-test-1"})
            return names, attempt

        async def curated(s):
            tool = next(t for t in (await s.list_tools()).tools if t.name == "items_create")
            made = await call(s, "items_create", {"name": "Third", "idempotency_key": "key-for-test-1"})
            return tool, made

        with FixtureAPI() as api:
            names, attempt = run_bridge(api, READS, read_only)
            self.assertNotIn("items_create", names)
            self.assertTrue(attempt["is_error"])
            self.assertEqual(api.hits["POST /items"] + api.hits["DELETE /items/{item_id}"], 0)   # nothing reached a write endpoint
            tool, made = run_bridge(api, WITH_WRITE, curated)
            self.assertFalse(tool.annotations.read_only_hint)
            self.assertIs(tool.annotations.destructive_hint, False)
            self.assertIn("idempotency_key", tool.input_schema["properties"])
            self.assertFalse(made["is_error"], made["text"])
            self.assertEqual(api.hits["POST /items"], 1)
            self.assertEqual(api.idempotency_seen, ["key-for-test-1"])
            self.assertEqual(api.items["a3"]["name"], "Third")
            self.assertEqual(api.hits["DELETE /items/{item_id}"], 0)   # the delete was never curated in

    def test_the_bridge_refuses_to_start_on_a_bad_worksheet(self):
        catch_all = {**READS, "tools": [{"name": "api_request", "title": "t", "description": "d", "mode": "read", "operations": ["{method} {path}"], "params": []}]}
        for ws in (catch_all, openapi_draft.draft(FixtureAPI().spec())):
            with tempfile.TemporaryDirectory() as tmp:
                for name in ("bridge.py", "worksheet.py"):
                    shutil.copy(BRIDGE / name, tmp)
                Path(tmp, "worksheet.json").write_text(json.dumps(ws), encoding="utf-8")
                r = subprocess.run([sys.executable, "bridge.py"], cwd=tmp, capture_output=True, text=True, timeout=60, input="")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("worksheet refused", r.stderr)

    def test_the_templates_own_contract_tests_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(BRIDGE, tmp, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copy(BRIDGE / "worksheet.example.json", Path(tmp) / "worksheet.json")
            r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=tmp, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr[-1500:])


class SshSample(unittest.TestCase):
    def test_sample_is_json_with_placeholders_only(self):
        text = (SKILL / "templates" / "bridge-stdio-ssh.json").read_text(encoding="utf-8")
        cfg = json.loads(text)
        server = next(iter(cfg["mcpServers"].values()))
        self.assertEqual(server["command"], "ssh")
        self.assertIn("<host>", server["args"])
        self.assertIn("-T", server["args"])


if __name__ == "__main__":
    unittest.main()
