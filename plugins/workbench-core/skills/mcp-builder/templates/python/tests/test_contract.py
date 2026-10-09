"""Contract: what every client can rely on. Run: python -m unittest discover -s tests"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# @@ if auth=oauth
import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

os.environ.setdefault("OAUTH_ISSUER", "https://issuer.example.com")
os.environ.setdefault("PUBLIC_URL", "http://localhost/mcp")
# @@ end
# @@ if auth=header
os.environ.setdefault("MCP_STATIC_TOKEN", "test-token-test-token")
# @@ end
# @@ if http
import http.client  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import uvicorn  # noqa: E402
# @@ end
from mcp import Client  # noqa: E402

import schemas  # noqa: E402
import server  # noqa: E402

EXPECTED = {"records_list", "records_get", "records_add"}
IDENTITY = {"user", "userid", "username", "email", "asuser", "actas", "onbehalfof", "caller", "requester"}


def norm(name):
    return "".join(c for c in name.lower() if c.isalnum())


class Contract(unittest.IsolatedAsyncioTestCase):
    async def test_exact_tool_set_in_stable_order(self):
        async with Client(server.mcp) as c:
            names = [t.name for t in (await c.list_tools()).tools]
            self.assertEqual(names, [t.name for t in (await c.list_tools()).tools])
        self.assertEqual(set(names), EXPECTED)
        self.assertEqual(names, sorted(names))

    async def test_annotations_flat_schemas_no_identity_argument(self):
        async with Client(server.mcp) as c:
            tools = (await c.list_tools()).tools
        for t in tools:
            a = t.annotations
            self.assertTrue(t.title and a and a.title, t.name)
            self.assertIsNotNone(a.read_only_hint, t.name)
            self.assertIsNotNone(a.destructive_hint, t.name)
            self.assertEqual(schemas.find_forbidden(t.input_schema), [], t.name)
            self.assertEqual(schemas.find_forbidden(t.output_schema or {}), [], t.name)
            self.assertFalse({norm(p) for p in t.input_schema.get("properties", {})} & IDENTITY, t.name)
        self.assertTrue(next(t for t in tools if t.name == "records_get").annotations.read_only_hint)
        self.assertFalse(next(t for t in tools if t.name == "records_add").annotations.read_only_hint)

    async def test_structured_and_text_result(self):
        async with Client(server.mcp) as c:
            r = await c.call_tool("records_get", {"record_id": "r1"})
        self.assertFalse(r.is_error)
        self.assertEqual(r.structured_content["id"], "r1")
        self.assertEqual(json.loads(r.content[0].text), r.structured_content)

    async def test_failure_is_iserror_with_a_next_step(self):
        async with Client(server.mcp) as c:
            r = await c.call_tool("records_get", {"record_id": "nope"})
        self.assertTrue(r.is_error)
        self.assertIn("records_list", r.content[0].text)

    async def test_unknown_arguments_are_refused_by_name(self):
        async with Client(server.mcp) as c:
            r = await c.call_tool("records_get", {"record_id": "r1", "bogus": 1})
        self.assertTrue(r.is_error)
        self.assertIn("bogus", r.content[0].text)

    async def test_both_protocol_eras(self):
        for mode in ("auto", "legacy"):
            async with Client(server.mcp, mode=mode) as c:
                self.assertEqual({t.name for t in (await c.list_tools()).tools}, EXPECTED)


# @@ if auth=none
class Stdout(unittest.TestCase):
    def test_stdout_carries_only_protocol_messages(self):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
        p = subprocess.run([sys.executable, os.path.join(ROOT, "server.py")], input=json.dumps(msg) + "\n",
                           capture_output=True, text=True, timeout=60)
        lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
        self.assertTrue(lines)
        for ln in lines:
            self.assertEqual(json.loads(ln)["jsonrpc"], "2.0")


# @@ end
# @@ if http
class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as s:
            s.bind(("localhost", 0))
            cls.port = s.getsockname()[1]
        cls.srv = uvicorn.Server(uvicorn.Config(server.build_app(), host="localhost", port=cls.port, log_config=None))
        threading.Thread(target=cls.srv.run, daemon=True).start()
        while not cls.srv.started:
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True

    def post(self, body, host=None, extra=None):
        c = http.client.HTTPConnection("localhost", self.port, timeout=30)
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **(extra or {})}
        if host:
            h["Host"] = host
        c.request("POST", "/mcp", body=body, headers=h)
        r = c.getresponse()
        out = r.status, r.read()
        c.close()
        return out

    # @@ if auth=header
    AUTH = {"Authorization": "Bearer " + os.environ["MCP_STATIC_TOKEN"]}
    # @@ end
    # @@ if auth=none
    AUTH = {}
    # @@ end
    # @@ if auth=oauth
    AUTH = {}   # a valid token needs the authorization server's key; see README (testing OAuth)
    # @@ end
    LIST = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    # @@ if auth!=oauth
    def test_list_over_http(self):
        status, body = self.post(self.LIST, extra=self.AUTH)
        self.assertEqual(status, 200)
        self.assertEqual({t["name"] for t in json.loads(body)["result"]["tools"]}, EXPECTED)

    def test_oversized_request_is_rejected(self):
        self.assertEqual(self.post("x" * (server.MAX_BODY + 1), extra=self.AUTH)[0], 413)

    def test_foreign_host_is_rejected(self):
        self.assertIn(self.post(self.LIST, host="evil.example", extra=self.AUTH)[0], (403, 421))

    # @@ end
    # @@ if auth=header
    def test_missing_or_wrong_credential_is_401(self):
        self.assertEqual(self.post(self.LIST)[0], 401)
        self.assertEqual(self.post(self.LIST, extra={"Authorization": "Bearer wrong"})[0], 401)
        self.assertEqual(self.post(self.LIST, extra={"X-Api-Key": os.environ["MCP_STATIC_TOKEN"]})[0], 200)

    # @@ end
    # @@ if auth=oauth
    def test_no_token_is_401_with_resource_metadata(self):
        c = http.client.HTTPConnection("localhost", self.port, timeout=30)
        c.request("POST", "/mcp", body=self.LIST, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        r = c.getresponse()
        self.assertEqual(r.status, 401)
        self.assertIn("resource_metadata", r.getheader("WWW-Authenticate", ""))
        c.close()

    def test_tokens_are_checked_for_signature_audience_and_expiry(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        server._signing_key = lambda token: key.public_key()   # stands in for the authorization server's key set
        now = int(time.time())
        claims = {"iss": server.ISSUER, "aud": server.PUBLIC_URL, "exp": now + 300, "sub": "someone"}
        sign = lambda c, k=key: {"Authorization": "Bearer " + jwt.encode(c, k, algorithm="RS256")}  # noqa: E731
        self.assertEqual(self.post(self.LIST, extra=sign(claims))[0], 200)
        self.assertEqual(self.post(self.LIST, extra=sign({**claims, "aud": "http://other.example/mcp"}))[0], 401)
        self.assertEqual(self.post(self.LIST, extra=sign({**claims, "exp": now - 10}))[0], 401)
        self.assertEqual(self.post(self.LIST, extra=sign(claims, rsa.generate_private_key(public_exponent=65537, key_size=2048)))[0], 401)
        self.assertEqual(self.post(self.LIST, extra={"Authorization": "Bearer not-a-jwt"})[0], 401)

    # @@ end


# @@ end
if __name__ == "__main__":
    unittest.main()
