"""In-app navigation assistant endpoint (FastAPI). Replace current_caller() with your app's session lookup first.

  pip install -r requirements.txt
  uvicorn app:app --port 8001
Environment: ANTHROPIC_API_KEY (or another credential source the SDK reads; server side only), NAV_DOCS (help folder,
default help), NAV_APP_NAME, NAV_SUPPORT_ROUTE (default /help), NAV_DAILY_LIMIT (questions per user per day, default 50).
"""
import json
import logging
import os

import anthropic
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

import navassist as nav

log = logging.getLogger("nav-assist")
CORPUS = nav.load_corpus(os.environ.get("NAV_DOCS", "help"))
APP_NAME = os.environ.get("NAV_APP_NAME", "the app")
SUPPORT = os.environ.get("NAV_SUPPORT_ROUTE", "/help")
LIMIT = nav.DailyLimit(int(os.environ.get("NAV_DAILY_LIMIT", "50")))
if len(CORPUS) // 4 < nav.MIN_CACHE_TOKENS:
    log.warning("nav-assist: the corpus is about %d tokens, under the minimum cacheable prefix", len(CORPUS) // 4)
client = anthropic.AsyncAnthropic()
app = FastAPI()


def current_caller(request: Request) -> dict:
    """REPLACE: return the signed-in caller from your session or auth middleware, for example
    {"tenant": ..., "user": ..., "role": ..., "plan": ...}. Never read these from the request body or the query string."""
    raise HTTPException(401, "not signed in")


def sse(obj):
    return f"data: {json.dumps(obj)}\n\n"


@app.post("/api/nav-assist")
async def nav_assist(request: Request, caller: dict = Depends(current_caller)):
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "send JSON")     # a cross-site form cannot send this type without a CORS preflight
    try:
        messages = nav.validate(await request.json())
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not LIMIT.allow((caller.get("tenant"), caller.get("user"))):
        raise HTTPException(429, "daily question limit reached")
    req = nav.build_request(CORPUS, {k: caller.get(k) for k in ("role", "plan", "permissions")}, messages,
                            APP_NAME, SUPPORT)

    async def events():
        try:
            async with client.messages.stream(**req) as stream:
                async for text in stream.text_stream:
                    yield sse({"text": text})
                final = await stream.get_final_message()
        except anthropic.APIError as e:
            log.warning("nav-assist: API error %s", type(e).__name__)
            yield sse({"error": "unavailable"})
            return
        problem, usage = nav.failure(final), final.usage
        log.info("nav-assist: stop=%s blocks=%s cache_read=%s cache_write=%s problem=%s", final.stop_reason,
                 [b.type for b in final.content], usage.cache_read_input_tokens, usage.cache_creation_input_tokens, problem)
        bad = nav.unsafe_links(nav.text_of(final))
        if bad:
            log.warning("nav-assist: the reply held %d unsafe link target(s), shown as plain text", len(bad))
        yield sse({"error": problem} if problem else {"done": True})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
