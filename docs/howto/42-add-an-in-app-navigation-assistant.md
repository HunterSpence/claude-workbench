# Add an in-app navigation assistant

Automates it: /workbench-core:app-navigator

## When to use
Users of a web app you build keep asking where things are ("where do I change my plan?"). You want a small panel in the
signed-in app that answers from your own help pages and links the right page, only pages that user can open. The model
gets no tools and no data, only the help pages and the caller's role. `<KIT>` is the kit folder (guide 01).

## Steps
1. List the app's page routes into a navigation map (Next.js, React Router or Angular source):
   ```
   py -3 <KIT>/plugins/workbench-core/skills/app-navigator/scripts/route_inventory.py path/to/web-app --out help/nav-map.md
   ```
2. Fill in each map row: a one-line purpose and who can open the page (roles or plans, or `everyone`). Delete pages users
   never open.
3. Ask Claude to draft one help page per feature from the UI code and existing docs, shaped like
   `<KIT>/plugins/workbench-core/skills/app-navigator/templates/help-page.md`. Someone who knows the app reviews every page.
4. In `<KIT>/plugins/workbench-core/skills/app-navigator/templates/`, copy the `python` (FastAPI) or `typescript` (Hono)
   backend next to the app's API and connect its caller function to your sign-in session. Copy the `widget` folder into
   the front end and mount the panel.
5. Write evaluation questions like `<KIT>/plugins/workbench-core/skills/app-navigator/templates/eval-cases.example.jsonl`
   and run them against the model:
   ```
   py -3 <KIT>/plugins/workbench-core/skills/app-navigator/scripts/eval_nav.py --map help/nav-map.md --cases evals/cases.jsonl --live --docs help --record evals/answers.jsonl
   ```
6. Work through the ship checklist in the skill (sign-in, limits, caching, security notes) before users see it.

## Verify
- The eval prints `RESULT: PASS`, with no unsafe links, unknown routes or role leaks.
- A request with no session gets 401; the second question logs a cache read above zero.
- In the panel, a link opens the page in the app and closes the panel; a link to another site shows as plain text.

## Common failures
- **Every call fails after a model change:** the request carries `temperature`, `top_p`, a thinking budget or ends on
  an assistant turn; the templates send none of these, so check your edits.
- **Blank or cut-off answers:** `max_tokens` is too low for thinking plus the answer; raise it or lower the effort.
- **No cache reads:** something before the breakpoint changes per call (a timestamp, the user's name), or the corpus is
  under the model's minimum cacheable size.
- **Links to pages that do not exist:** the page is missing from the map or the help pages; add it and re-run the eval.
- **Routes missing from the map:** the scan cannot see menus built from data or lazy modules; add them with `--override`.
