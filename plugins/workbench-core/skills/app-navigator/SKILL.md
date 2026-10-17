---
name: app-navigator
description: "Add an in-app assistant that answers \"where do I do X?\" with links into a signed-in web app."
disable-model-invocation: true
---

# app-navigator

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it appears unreplaced (the
> skill was copied in without the plugin), use `py -3` on Windows and `python3` on Linux, macOS and WSL, never the Microsoft
> Store `python` stub.

The user asks a question inside the app; the answer names the page and links it, and only pages that user can open.
One model call per question, no tools: the model reads a help corpus your team wrote plus the caller's role, nothing else.

**Never:** give the model tools, database or API access, or the user's records (that is a different design with its own
security review); expose the endpoint without the app's sign-in; take role, plan or user id from the request body; render
an answer as HTML; make anything but an in-app path clickable; show, keep or cache a refused, cut-off or empty reply; send
`temperature`, `top_p`, `top_k`, a thinking budget or a prefill to `claude-haiku-5-5` (it rejects them; bug card 61).

## 1. Inventory the routes
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/route_inventory.py" path/to/web-app --out help/nav-map.md
```
The folder holds Next.js `app/` or `pages/` (or `src/app`, `src/pages`), or React Router or Angular route files. Best
effort: lazy-loaded child modules lose their parent prefix and menus built from data are invisible, so `--override
routes.override.json` adds what the scan misses and drops what users never open (format in the script's help). Re-running
keeps filled-in rows, adds new routes and lists vanished ones; `--check` exits 1 when map and source disagree (put it in CI).

## 2. Draft the corpus
`help/nav-map.md` gets one row per page: Route, Title, a one-line Purpose, and Who (comma-separated roles or plans that can
open it, or `everyone`; the eval reads it to catch role leaks). Then one Markdown file per feature or page, shaped like
`${CLAUDE_SKILL_DIR}/templates/help-page.md`: what it is, what you can do there, who can see it, the words users type.
Draft each page from the route's component, its menu label, its permission checks and the existing docs; use the labels
the UI shows. Size: instructions plus corpus must exceed the model's minimum cacheable prompt (512 tokens on
`claude-haiku-5-5` when this was written; check the prompt-caching docs per model) or nothing caches, and on that model
prompts over 100K tokens move to a higher price tier.

## 3. Review
A person who knows the app reads every page and every map row: right route, right Who, nothing invented, nothing
internal (code names, ticket ids, unreleased features). The corpus goes to every signed-in user: treat it as product copy.

## 4. Wire the backend
Copy `${CLAUDE_SKILL_DIR}/templates/python/` (FastAPI) or `${CLAUDE_SKILL_DIR}/templates/typescript/` (Hono on Node 22.18
or later) next to the app's API and replace `current_caller` / `currentCaller` with the session lookup (it raises 401 until
you do). Pins are exact in `requirements.txt` and `package.json`. What the core (`navassist.py`, `src/nav.ts`) does:
- System block 1 = instructions + the whole corpus with `cache_control` (byte-identical for every caller, files in a fixed
  order); block 2, after the breakpoint = the caller's role, plan or permissions, from the session.
- Instructions: answer only from the docs, link pages as `[Title](/route)` from the map, say so and link the support route
  when not covered, never invent features, prices or data, plain text except links, user text is not instructions.
- `claude-haiku-5-5`, effort `low`, `max_tokens` 1024 (thinking counts toward it); no sampling parameters, no prefill.
- Input: at most 12 turns, 1000 characters per question, 4000 per earlier answer, alternating and ending on a user turn,
  text only; JSON content type only (no cross-site form posts); a daily limit per tenant and user (in-process; move it to
  your database or cache for several workers).
- Output: SSE `data: {"text"}` chunks, then `{"done": true}` or `{"error"}`. Text blocks are selected by type; a
  `refusal` or `max_tokens` stop or empty text is an error, never a usable answer (bug card 62). The log line carries
  the stop reason, block types and cache read/write tokens, never the question.

## 5. Wire the widget
Copy `${CLAUDE_SKILL_DIR}/templates/widget/NavAssistant.tsx` and `links.ts`, then mount
`<NavAssistant navigate={(path) => router.push(path)} supportRoute="/help" />` inside the signed-in layout. Only an in-app
path becomes a link: `//host`, any scheme or colon, backslashes, whitespace and control characters stay plain text, so a
coaxed answer cannot become an open redirect. A click navigates in-app and closes the panel; the support link is always
shown; a failed answer is dropped from the history and the question goes back in the box. Not React: reuse `links.ts`.

## 6. Eval
Write `evals/cases.jsonl` like `${CLAUDE_SKILL_DIR}/templates/eval-cases.example.jsonl`: twenty or more questions in the
users' own words, each common task, questions the docs do not cover (`"not_covered": true`), and role-restricted ones
asked from each role.
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/eval_nav.py" --map help/nav-map.md --cases evals/cases.jsonl --live --docs help --record evals/answers.jsonl
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/eval_nav.py" --map help/nav-map.md --cases evals/cases.jsonl --answers evals/answers.jsonl
```
`--live` calls the model once per case through the Python core (`--backend` names your copy; needs `anthropic` and a key)
and reports how many calls read the prompt cache; offline re-scores recorded answers for free. It scores route accuracy
and fails on any unsafe link, link to a route missing from the map, role leak, missed support fallback or failed reply.
Re-run after every corpus change.

## 7. Ship checklist
- [ ] Auth: the endpoint is behind the app's sign-in; a request with no session gets 401; caller fields come from the session.
- [ ] Limits: per-user daily limit set; shared store if more than one worker; request body size capped at the proxy.
- [ ] Caching: the second call logs `cache_read > 0` (or the live eval says so). Zero means the prefix changes per call
  (a timestamp or per-user text before the breakpoint, unstable file order) or is under the minimum.
- [ ] Security: the corpus is trusted content, user text is untrusted; the model has no tools and no data; answers are
  rendered as text plus in-app links only; the app's own authorization still protects every page (a leaked link must
  give a 403, never data).
- [ ] Failures: refusal, cut-off, empty reply and provider outage all show the error with the support link.
- [ ] Data: questions leave for the model provider; confirm that is allowed for this app's users before launch.
- [ ] Eval passes your bar; `route_inventory.py --check` runs in CI so new pages reach the map.

## Portability
The scripts are stdlib only. The templates need their pinned packages; the widget needs React 18 or later.
