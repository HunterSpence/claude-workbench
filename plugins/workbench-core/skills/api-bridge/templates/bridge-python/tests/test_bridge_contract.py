"""Contract for a curated bridge: the tool set is the worksheet, annotations match modes, schemas are flat, no catch-all or
identity argument, unknown arguments are refused. Run: python -m unittest discover -s tests"""
import asyncio
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("UPSTREAM_BASE_URL", "http://localhost:9")   # never contacted by these tests

import bridge  # noqa: E402
import worksheet  # noqa: E402
from mcp import Client  # noqa: E402

FORBIDDEN = ("$ref", "anyOf", "oneOf", "allOf", "const")


def keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from keys(v)


class BridgeContract(unittest.TestCase):
    def setUp(self):
        self.ws = bridge.load()
        self.kept = {t["name"]: t for t in worksheet.kept(self.ws)}

    def test_worksheet_passes_its_own_checks(self):
        self.assertEqual(worksheet.check(self.ws), [])

    def test_tools_match_the_worksheet(self):
        async def go():
            async with Client(bridge.mcp) as c:
                return (await c.list_tools()).tools
        tools = asyncio.run(go())
        self.assertEqual([t.name for t in tools], sorted(self.kept))
        for t in tools:
            entry = self.kept[t.name]
            self.assertEqual(t.annotations.read_only_hint, entry["mode"] == "read", t.name)
            self.assertIsNotNone(t.annotations.destructive_hint, t.name)
            self.assertFalse(set(keys(t.input_schema)) & set(FORBIDDEN), t.name)
            if entry["mode"] == "write" and entry.get("idempotency_header"):
                self.assertIn("idempotency_key", t.input_schema["properties"])

    def test_unknown_arguments_are_refused_by_name(self):
        async def go():
            async with Client(bridge.mcp) as c:
                return await c.call_tool(sorted(self.kept)[0], {"bogus": 1})
        res = asyncio.run(go())
        self.assertTrue(res.is_error)
        self.assertIn("bogus", res.content[0].text)


if __name__ == "__main__":
    unittest.main()
