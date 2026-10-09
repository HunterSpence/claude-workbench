// Contract: what every client can rely on. Run: npm run build && npm test
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { after, before, describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import { findForbidden } from "../src/schemas.js";
// @@ if http
import type { AddressInfo } from "node:net";
import { request, type Server } from "node:http";
// @@ if auth=oauth
import { generateKeyPair, SignJWT } from "jose";
import { createHttp, MAX_BODY_BYTES, testHooks } from "../src/server.js";
// @@ end
// @@ if auth!=oauth
import { createHttp, MAX_BODY_BYTES } from "../src/server.js";
// @@ end
// @@ end

const SERVER = fileURLToPath(new URL("../src/server.js", import.meta.url));
const EXPECTED = ["records_add", "records_get", "records_list"];
const IDENTITY = new Set(["user", "userid", "username", "email", "asuser", "actas", "onbehalfof", "caller", "requester"]);
const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");
const text = (r: { content: unknown }) => (r.content as { text: string }[])[0].text;

// @@ if auth=none
describe("contract over stdio", () => {
  let client: Client;
  before(async () => {
    client = new Client({ name: "contract-test", version: "0.0.0" });
    await client.connect(new StdioClientTransport({ command: process.execPath, args: [SERVER] }));
  });
  after(async () => { await client.close(); });

  it("exact tool set in stable order", async () => {
    const names = (await client.listTools()).tools.map((t) => t.name);
    assert.deepEqual(names, EXPECTED);
    assert.deepEqual(names, (await client.listTools()).tools.map((t) => t.name));
  });

  it("annotations, flat schemas, no identity argument", async () => {
    for (const t of (await client.listTools()).tools) {
      assert.ok(t.title && t.annotations?.title, t.name);
      assert.notEqual(t.annotations?.readOnlyHint, undefined, t.name);
      assert.notEqual(t.annotations?.destructiveHint, undefined, t.name);
      assert.deepEqual(findForbidden(t.inputSchema), [], t.name);
      assert.deepEqual(findForbidden(t.outputSchema ?? {}), [], t.name);
      for (const p of Object.keys((t.inputSchema as { properties?: object }).properties ?? {})) assert.ok(!IDENTITY.has(norm(p)), `${t.name}.${p}`);
    }
  });

  it("structured and text result", async () => {
    const r = await client.callTool({ name: "records_get", arguments: { record_id: "r1" } });
    assert.ok(!r.isError);
    assert.equal((r.structuredContent as { id: string }).id, "r1");
    assert.deepEqual(JSON.parse(text(r)), r.structuredContent);
  });

  it("failure is isError with a next step", async () => {
    const r = await client.callTool({ name: "records_get", arguments: { record_id: "nope" } });
    assert.equal(r.isError, true);
    assert.match(text(r), /records_list/);
  });

  it("unknown arguments are refused by name", async () => {
    const r = await client.callTool({ name: "records_get", arguments: { record_id: "r1", bogus: 1 } }).catch((e: Error) => e);
    const msg = r instanceof Error ? r.message : text(r) + String(r.isError);
    assert.match(msg, /bogus/);
    assert.ok(r instanceof Error || r.isError === true);
  });
});

describe("stdout", () => {
  it("carries only protocol messages", () => {
    const msg = { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "t", version: "0" } } };
    const p = spawnSync(process.execPath, [SERVER], { input: JSON.stringify(msg) + "\n", encoding: "utf8", timeout: 60000 });
    const lines = p.stdout.split("\n").filter((l) => l.trim());
    assert.ok(lines.length > 0);
    for (const l of lines) assert.equal(JSON.parse(l).jsonrpc, "2.0");
  });
});

// @@ end
// @@ if http
describe("contract over HTTP", () => {
  let srv: Server;
  let base = "";
  let AUTH: Record<string, string> = {};
  const LIST = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" });
  // @@ if auth=oauth
  const AUDIENCE = "http://localhost/mcp";
  let key: Awaited<ReturnType<typeof generateKeyPair>>;
  const token = async (claims: Record<string, unknown>, k = key.privateKey) =>
    "Bearer " + (await new SignJWT({ ...claims }).setProtectedHeader({ alg: "RS256" }).sign(k));
  const base_claims = () => ({ iss: "https://issuer.example.com", aud: AUDIENCE, exp: Math.floor(Date.now() / 1000) + 300, sub: "someone" });
  // @@ end
  before(async () => {
    // @@ if auth=header
    process.env.MCP_STATIC_TOKEN = "test-token-test-token";
    AUTH = { Authorization: "Bearer " + process.env.MCP_STATIC_TOKEN };
    // @@ end
    // @@ if auth=oauth
    process.env.OAUTH_ISSUER = "https://issuer.example.com";
    process.env.PUBLIC_URL = AUDIENCE;
    process.env.OAUTH_JWKS_URL = "https://issuer.example.com/jwks";
    key = await generateKeyPair("RS256");
    testHooks.keyResolver = async () => key.publicKey; // stands in for the authorization server's key set
    AUTH = { Authorization: await token(base_claims()) };
    // @@ end
    srv = createHttp();
    await new Promise<void>((ok) => srv.listen(0, "localhost", ok));
    base = `http://localhost:${(srv.address() as AddressInfo).port}/mcp`;
  });
  after(() => { srv.close(); });
  const post = (body: string, headers: Record<string, string> = {}) =>
    fetch(base, { method: "POST", body, headers: { "content-type": "application/json", accept: "application/json, text/event-stream", ...headers } });

  it("lists the tools", async () => {
    const r = await post(LIST, AUTH);
    assert.equal(r.status, 200);
    const body = await r.text();
    for (const n of EXPECTED) assert.ok(body.includes(n), n);
  });

  it("rejects an oversized request", async () => {
    assert.equal((await post("x".repeat(MAX_BODY_BYTES + 1), AUTH)).status, 413);
  });

  // @@ if auth=header
  it("missing or wrong credential is 401", async () => {
    assert.equal((await post(LIST)).status, 401);
    assert.equal((await post(LIST, { Authorization: "Bearer wrong" })).status, 401);
    assert.equal((await post(LIST, { "X-Api-Key": process.env.MCP_STATIC_TOKEN! })).status, 200);
  });

  // @@ end
  // @@ if auth=oauth
  it("no token is 401 with resource_metadata, and the metadata is served", async () => {
    const r = await post(LIST);
    assert.equal(r.status, 401);
    assert.match(r.headers.get("www-authenticate") ?? "", /resource_metadata/);
    const meta = await fetch(base.replace("/mcp", "/.well-known/oauth-protected-resource/mcp"));
    assert.deepEqual(((await meta.json()) as { authorization_servers: string[] }).authorization_servers, ["https://issuer.example.com"]);
  });

  it("tokens are checked for signature, audience and expiry", async () => {
    const other = await generateKeyPair("RS256");
    assert.equal((await post(LIST, { Authorization: await token({ ...base_claims(), aud: "http://other.example/mcp" }) })).status, 401);
    assert.equal((await post(LIST, { Authorization: await token({ ...base_claims(), exp: Math.floor(Date.now() / 1000) - 10 }) })).status, 401);
    assert.equal((await post(LIST, { Authorization: await token(base_claims(), other.privateKey) })).status, 401);
    assert.equal((await post(LIST, { Authorization: "Bearer not-a-jwt" })).status, 401);
  });

  // @@ end
  it("rejects a foreign Host", async () => {
    const { port } = srv.address() as AddressInfo;
    const status = await new Promise<number>((ok, fail) => {
      const req = request({ host: "localhost", port, method: "POST", path: "/mcp", headers: { host: "evil.example", "content-type": "application/json", accept: "application/json, text/event-stream", ...AUTH } }, (res) => { res.resume(); ok(res.statusCode ?? 0); });
      req.on("error", fail);
      req.end(LIST);
    });
    assert.ok([403, 421].includes(status), String(status));
  });
});
// @@ end
