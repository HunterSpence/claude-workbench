# Rules card

The kit's rules on one page. The full text is in `instructions/CLAUDE.md` and its rules; your organisation's policy
outranks all of it.

## Never (Red Lines)
- Edit or bypass a managed setting or an organisation control (endpoint security, the proxy, DLP, managed hooks), or
  run Claude Code as administrator. Guard: `security-tooling-change`.
- Build or deploy to production by hand, even when CI is broken: production changes go through the pipeline.
  Guard: `prod-build`.
- Write directly to a production database: migrations and the pipeline only. Guard: `protected-db-write`.
- Write a credential value anywhere (a prompt, note, commit, log or draft), or relay a one-time code to anyone.
- Fabricate or backdate a document or record.
- Use stealth browsers, captcha solvers or anything that gets around a bot wall.
- Push to a remote your organisation has not approved, or make work content public without approval.

## Hard stop rule
When a hook, permission prompt, gateway, proxy or policy denies something: stop that step, show the denial word for
word, and never retry it another way (another tool, shell or route). Ask IT with the text in `docs/admin-asks.md`.

## Confirm first
Anything a third party sees (email, chat, tickets, posts, PR comments), irreversible deletions, real money, credential
changes, and speaking for you in public. Messages are drafts you send yourself.

## Data
- Your organisation's data stays in the tools it approved for that data. Another organisation's data stays in its
  own environment.
- No personal accounts, tokens, cloud storage, MCP servers or AI tools on the work machine.
- Never bulk-read or index online-only OneDrive files; never bulk move or delete in a synced folder.
- A sensitivity label follows the content wherever it goes. Before an Office file leaves the organisation: render it,
  scrub a copy, send the copy.
- Tell your security team before the first capture, mail or meeting ingest run.

## Working habits
- Evidence over claims: a green check is not proof; open the result.
- Big or risky work: a builder, an attacker on a different model, and a final verifier.
- Smallest change that fully solves the problem, once you understand it.
- Save to the knowledge base and write a handoff before a session ends.

## Where to look
How-tos `docs/howto/README.md` · fixes by symptom `docs/troubleshooting.md` · gaps `docs/known-limits.md` · what
leaves the machine `docs/security-overview.md` · incidents and offboarding `docs/runbooks.md`.
