# Changelog

## 0.2.0
- Instructions: on-demand `work-workflows.md` (fixing and reviewing repos, writing code, building
  UIs, spreadsheets and decks, drafting replies: skills, steps, and what "done" means),
  `judgment.md` (fifteen decision procedures for when no rule fires) and `model-profiles.md`
  (per-tier failure modes and the structure that recovers them), listed in a new "Read on demand"
  section of the core.
- Core: first reply surfaces dated and waiting-on-you items from active-context, and reads the file
  when the injected copy is missing or truncated; credentials seen in chat are flagged the same turn;
  never relay a one-time code; never fabricate or backdate a record; build up to a gated step, then
  name it; escalate only the blocked step; repo-only rules go in the repo; never path-scope a rule
  that must always bind.
- Rules: a marker legend for KB notes; more save triggers; monthly KB health check; workflow
  `agent()` model pairs; `batch-review` for non-interactive review; WebSearch is one shared budget;
  root logins are break-glass; scan a plugin or skill before installing it; bulk transfers are
  rate-capped; the Store Python stub; parallel browser sessions; qualifying conditions and value
  extraction; structured multi-file deliverables; one-line status alerts.
- Agents: every persona points to the judgment procedures; `blue-verify` uses `batch-review` for
  review volume.
- Settings: `permissive` drops the built-in git instructions (`includeGitInstructions: false`);
  the upstream set turns on `frontend-design` (Apache-2.0).
- KB template: a "Waiting on you" section in active-context and a seeded model-routing ledger.
- New skills: `office-docx` (Word output, Markdown and template input, macro formats refused),
  `draft-reply` (reply drafts as text, HTML and threaded .eml, or an opt-in Outlook draft; it never
  sends), `ui-build` (local-only screenshots at desktop and phone widths, light and dark, with an
  accessibility scan) and `repo-fix` (detects a repo's build, lint and test commands; read-only).
- `vdi-drive` (opt-in, runs only when asked): drives a remote desktop drawn into an HTML canvas.
  Every command except `test` and `clean` needs a local authorisation note; keys beyond a safe set
  need naming per run; screenshots and the browser profile stay under the temp folder.
- New tools: `git-credscan` (pre-commit credential check), `memcap` (run a job under a memory
  ceiling) and `redact-settings` (a settings file with values masked, safe to share).
- KB: `kb_eval.py` runs your own known-answer retrieval set; the save skill gains a skip gate, a
  rule for demoting old error-list entries, and an active-context trim rule.
- `fetch-upstream --optional` adds the optional design skills; the installer refuses the Microsoft
  Store Python stub; the guard hook also covers browser MCP tools; THIRD-PARTY lists every enabled
  upstream plugin and the new Node and Python packages.

- Fix round: skills are named as invoked (`/workbench-core:<skill>`, `/workbench-kb:save`); reports
  go to an Artifact link when the organisation's Claude offers Artifacts (own organisation's data
  only), otherwise a Markdown file; the journal and KB search commands are spelled out; the build
  personas ask for one failing test in the repo's own framework; `.env` and every `.env.*`
  (templates included) are denied in both profiles; both profiles carry `permissions.ask` rules for publishing
  and sharing commands, which prompt even in bypass mode; IMPORT adds `/workbench-core:onboard` and
  the upstream-skill fetch.
- repo-fix: monorepo folders to three levels, multi-line CI steps kept whole with their `cd`,
  `working-directory:` honoured, release/deploy/publish workflows skipped, quoted arguments kept,
  `lint:fix` classed as fix, PR template, CODEOWNERS and CONTRIBUTING reported.
- office-pptx: 16:9 by default, long titles shrink and wrap without overlapping the body, horizontal
  bar charts read top-down, one colour per series. office-xlsx: a `risk` check (and `style` refusal)
  when an openpyxl save would drop shapes, threaded comments, pivots or slicers, with an Excel COM
  route for those edits; `_xlfn.` prefixes for newer functions. draft-reply: Reply-To and
  Mail-Followup-To honoured, the quoted date keeps its time zone. ui-build: horizontal-overflow check,
  `--allow-fonts`, service workers blocked, a network-layer block below the request filter, redirect
  chains listed. office-docx and office-pptx: image and template paths must stay inside the outline's
  folder; network paths and URLs are refused unless `--allow-outside`.
- Guards: push rules read two views of each command, the shell statements with provable prose
  blanked (commit messages, `echo`/`grep`/`rg` arguments, PR titles and bodies) and the raw command
  with `python -c`, `node -e`, written-then-run files and decoded PowerShell `-EncodedCommand`
  payloads kept, so a push hidden in an interpreter is caught and a commit message that mentions
  one is not; an `-EncodedCommand` (any spelling pwsh accepts) whose payload cannot be decoded is
  denied; `publish-confirm` also asks about `gcloud storage rsync`/`mv`, and both settings profiles
  carry ask rules for every verb it asks about.
- vdi-drive: `Delete` left the safe key set and needs `--allow-keys`, like Enter and Space.

## 0.1.0
- First release: instructions and rules, agent personas, workflow skills, guard engine with
  generic and corporate rule packs, statusline and session hooks, knowledge-base plugin,
  doc-index (local full-text document search), Office skills (pptx, xlsx, render), a pinned
  upstream-skill fetcher, an MCP template, and a Python installer with dry run and uninstall.
