# Fix a red error message in Claude Code

Automates it: none (a hook names a card after a failed tool call; the steps below are for you)

## When to use
Claude Code printed an error in red: the API is overloaded, a usage limit, "Not logged in", "Unable to connect to API", a model
that is not available, an MCP server that dropped, a managed-settings warning, an installer that returned a web page. The
kit has a card for each common one (cards 67 to 94 in `kb-template/_shared/bug-cards.md`). `<KIT>` is the kit folder
(guide 01).

## Steps
1. Copy the message exactly, with its first line and any `API Error:` tail. Do not paraphrase it: the cards are found by the
   words Claude Code prints.
2. Note where it appeared. After a failed tool call, the failure hook may already have named a card in one line: open that
   card. Errors that end the turn (API, usage, sign-in, network) and warnings printed at startup reach no hook, so
   search by hand:
   `py -3 <KIT>/plugins/workbench-kb/scripts/kb_search.py "<words from the message>" --domain _shared --limit 5`
3. Open the card and use its first move for the group:
   - **Capacity, server error (card 67):** wait, retry once, try another model with `/model`, check the status page.
   - **Usage window or spend limit (68):** not a bug. Note the reset time or ask the budget owner; never retry in a loop.
   - **Sign-in (69 to 71):** `/status` shows which credential is in force; `Get-ChildItem Env:ANTHROPIC*` shows a stray key;
     `/login` renews a saved sign-in. If the organization refuses the account, send the exact line to your admin
     (`docs/admin-asks.md`) and stop signing in again.
   - **Network, proxy, TLS (72, 73, 18):** from the same shell run `curl.exe -I https://api.anthropic.com`; guide 04 has the proxy
     and certificate steps.
   - **Context or request too large (74, 75):** `/context`, then `/compact` or `/clear`.
   - **Model or version (76, 77):** `/model` and pick from the list; `claude update`, then a new session.
   - **Out-of-step history (78):** `claude update`, then `/rewind`.
   - **MCP (79, 80):** `claude mcp get <name>` prints an `Issue:` line; `/mcp` to sign in again or reconnect.
   - **Hooks, settings, trust, permission rules (81, 82, 89, 90):** run `claude doctor` and read what it lists; managed
     settings belong to your IT team.
   - **Windows install and shell (83 to 88, 94, 12):** `where.exe claude`, the installer line for your shell, the
     antivirus and temp-folder notes on the card.
   - **WebFetch, safety check, browser sign-in (91 to 93):** the card says whether the fix is a host allow-list, a new session
     or a free local port.
4. A refusal by policy (a managed setting, a gateway, a denied tool) is a decision, not a bug. Report it verbatim and do not
   retry another way (card 51, guide 39).
5. No card fits: follow guide 18. If the class will come back, add a card to your `_shared/bug-cards.md`: the next number,
   all five fields, the class and not the incident.

## Verify
- The same prompt now succeeds, with no substituted model and no repeated warning at startup.
- `/status` shows the account, model and credential you intended.
- For network errors, `curl.exe` through your proxy and one `claude -p` call both succeed; for installer errors,
  `claude --version` prints a version in a new window.

## Common failures
- **The hook said nothing:** it only sees failed tool calls. A turn-ending error never reaches it, so search the cards by
  hand (step 2).
- **A search finds nothing:** it is keyword search; retry once with the message's own words, such as the error type name.
- **"Claude Code process exited with code 1" in an editor or SDK:** that wrapper hides the cause. Read the process's own
  output (in VS Code, View output logs) and search with those words.
- **The error returns after every fix:** read the `request-id` or the `Response:` clause in the message and send it with the
  full line to the team that owns the proxy or the account; do not keep retrying.
- **Pasting a credential into a ticket:** quote the message and its request id only, never a key or token.
