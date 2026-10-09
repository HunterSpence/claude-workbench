// In-app navigation assistant endpoint (Hono on Node). Replace currentCaller() with your app's session lookup first.
//   npm install --ignore-scripts && npm start
// Environment: ANTHROPIC_API_KEY (or another credential source the SDK reads; server side only), NAV_DOCS (help folder,
// default help), NAV_APP_NAME, NAV_SUPPORT_ROUTE (default /help), NAV_DAILY_LIMIT (questions per user per day,
// default 50), PORT (default 8001).
import Anthropic from "@anthropic-ai/sdk";
import { serve } from "@hono/node-server";
import { Hono, type Context } from "hono";
import { streamSSE } from "hono/streaming";
import * as nav from "./nav.ts";

type Caller = { tenant: string; user: string; role?: string; plan?: string; permissions?: string[] };

const corpus = nav.loadCorpus(process.env.NAV_DOCS ?? "help");
const appName = process.env.NAV_APP_NAME ?? "the app";
const support = process.env.NAV_SUPPORT_ROUTE ?? "/help";
const limit = new nav.DailyLimit(Number(process.env.NAV_DAILY_LIMIT ?? 50));
if (corpus.length / 4 < nav.MIN_CACHE_TOKENS) {
  console.warn(`nav-assist: the corpus is about ${Math.round(corpus.length / 4)} tokens, under the minimum cacheable prefix`);
}
const client = new Anthropic();
const app = new Hono();

// REPLACE: return the signed-in caller from your session or auth middleware. Never read it from the body or query.
function currentCaller(_c: Context): Caller | null {
  return null;
}

app.post("/api/nav-assist", async (c) => {
  const caller = currentCaller(c);
  if (!caller) return c.json({ error: "not signed in" }, 401);
  // a cross-site form cannot send this type without a CORS preflight
  if ((c.req.header("content-type") ?? "").split(";")[0].trim() !== "application/json") {
    return c.json({ error: "send JSON" }, 415);
  }
  let messages: nav.Turn[];
  try {
    messages = nav.validate(await c.req.json());
  } catch (e) {
    return c.json({ error: (e as Error).message }, 400);
  }
  if (!limit.allow(JSON.stringify([caller.tenant, caller.user]))) {
    return c.json({ error: "daily question limit reached" }, 429);
  }
  const req = nav.buildRequest(corpus, { role: caller.role, plan: caller.plan, permissions: caller.permissions },
    messages, appName, support);
  c.header("Cache-Control", "no-store");
  return streamSSE(c, async (sse) => {
    let final: Anthropic.Message;
    try {
      const stream = client.messages.stream(req);
      for await (const ev of stream) {
        if (ev.type === "content_block_delta" && ev.delta.type === "text_delta") {
          await sse.writeSSE({ data: JSON.stringify({ text: ev.delta.text }) });
        }
      }
      final = await stream.finalMessage();
    } catch (e) {
      console.warn("nav-assist: API error", e instanceof Anthropic.APIError ? e.status : (e as Error).name);
      await sse.writeSSE({ data: JSON.stringify({ error: "unavailable" }) });
      return;
    }
    const problem = nav.failure(final);
    console.info("nav-assist:", JSON.stringify({
      stop: final.stop_reason, blocks: final.content.map((b) => b.type), problem,
      cache_read: final.usage.cache_read_input_tokens, cache_write: final.usage.cache_creation_input_tokens,
    }));
    const bad = nav.unsafeLinks(nav.textOf(final));
    if (bad.length) console.warn(`nav-assist: the reply held ${bad.length} unsafe link target(s), shown as plain text`);
    await sse.writeSSE({ data: JSON.stringify(problem ? { error: problem } : { done: true }) });
  });
});

serve({ fetch: app.fetch, port: Number(process.env.PORT ?? 8001) });
