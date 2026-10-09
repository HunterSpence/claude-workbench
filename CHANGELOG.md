# Changelog

## 0.3.3

Fixes found while verifying 0.3.2 on locked-down Windows machines.

### Upgrade notes (from 0.3.2)
- Say "check the new stuff and go". Nothing to do by hand; restart Claude Code when the update asks.

### Fixed
- **The doctor's KB machinery row (D3) no longer times out on a laptop with slow process starts.** It ran the whole
  KB test suite, which starts several hundred Python processes. Where endpoint scanning slows every process start, one
  run could exceed D3's 10-minute limit, and setup and the doctor each run it, so the row failed although nothing was
  broken. D3 now runs the tests listed in `plugins/workbench-kb/tests/field-tests.txt`, which cover every part of the KB
  machinery (search, links, journal, locks, the save and its merge, the credential gate, rollover, the secret scanner)
  with a fraction of the process starts. A listed test that does not exist fails the row; it never shrinks it. No
  wall-clock budget runs in the field: timing classes are not listed, and a listed test that measures elapsed time
  skips that budget under the doctor (`WB_FIELD_CHECK=1`), because a budget measures the machine, not the kit. The
  kit's release gate still runs every KB test with every budget, and never passes that flag to a suite.
- **setup parks a tokensave server it cannot start.** A `tokensave` MCP entry that runs the kit's own binary exits until
  a repository is indexed, so the doctor reported it DOWN on every run. setup now parks it, and the report says how to
  bring it back after `tokensave init`, only when all of these hold: tokensave has no indexed repository yet, a health
  check of that one server (30-second limit, no other server started) says it does not start, and setup has never
  parked it before. If setup parked it once, a live entry means you turned it back on, and it stays. Once tokensave has
  indexed a repository, setup leaves the entry on and its note explains why the doctor can still show it DOWN (the
  check starts it in an empty folder). An entry that runs some other program is left alone, and a check that times
  out, answers oddly or cannot read tokensave's registry changes nothing.
- **The KB index warning says what to do.** A dead-links warning now gives the count and the command that lists them
  (`kb_health.py --verbose`). It never prints the names of your notes, so the verify table stays safe to paste.
- **The update verify no longer reports your own KB index or capture state as kit defects** in the "for the kit
  author" box. A FAIL on those rows (the kit's own indexer crashing, say) still goes to the kit author.

## 0.3.2

Fixes for managed Windows 11 laptops, a one-phrase update loop and a quieter guard.

### Upgrade notes (from 0.3.x)
- **Restart every Claude Code window after the update.** The plugins' Python setting and the new `<WB>\bin` PATH entry
  load only when Claude Code starts.
- **Updating is one phrase.** Say "check the new stuff and go" (or "update the kit"): the new `kit-update` skill finds
  the latest release, checks its SHA-256, installs it, runs setup with the opt-ins you chose before, and asks you to
  restart. Your first message after the restart runs a verify that prints one PASS/WARN/FAIL/NEEDS-IT table and a
  "for the kit author" box of kit defects only, with your user, computer, domain and company names scrubbed. The guard
  asks you once before the update installs anything. A machine on 0.3.1 can follow the same steps by hand from
  `IMPORT.md` ("Updating").
- **Libraries an earlier setup indexed** (a whole OneDrive or Documents folder) are no longer added by setup. The setup
  report names the ones already registered and the `remove-root` command for each; nothing is removed for you.
- **The guard is quieter by default.** New `guard_level` (installer `--guard standard|strict`, kept across upgrades).
  `standard`, the new default: a push or upload to a host not on your list and `--no-verify` ask instead of being
  refused, and plain browser navigation runs without a prompt. Everything else is unchanged: force-push or delete of
  main, secrets and key files, `.env`, destructive deletes, guard tampering, public repos and security-control changes
  are still refused, and sends, publishing, kit installs and skill-tier changes still ask. `strict` is 0.3.1's
  behaviour. The post-update verify counts which rules fired, so the next release can tune on data.
- **Permissions:** an upgrade removes allow entries an earlier kit install added and the new profile no longer has
  (the permissive profile's server-wide `mcp__tokensave` allow). Deny and ask entries, and anything you added, are kept.

### Fixed
- **The hooks, guards included, could stop running after an upgrade.** The installer wrote the plugins' `python`
  option, then reinstalled the plugins, which cleared it; every hook then failed with `Plugin option "python" isn't
  set` and the guards failed open. The installer now passes `--config python=<path>` to `claude plugin install`,
  writes the option again if it is missing, and fails loudly if it still is. The doctor has a row that fails when a
  workbench plugin's Python is unset or does not run, and the guard heartbeat ignores the installer's self-test.
- **Each document is indexed once.** A folder that is a find root of its own inside another root was indexed twice;
  it now belongs to the innermost root, `--root <outer>` still covers the roots nested under it, and Windows 8.3
  short names (`PROGRA~1`) no longer split one folder in two.
- **A blocked embedding-model download is remembered for 24 hours.** Every refresh used to retry it with three
  sleeps (about 40 seconds) and red ERROR lines; now one attempt, one plain line, and `mode_reason` names the host
  and the error.
- **Reports agree with the doctor.** Rows a passing Day-1 check proves are READY; a blocked model host reads NEEDS-IT;
  IT asks come from one deduplicated list shared by setup, the doctor and the report.
- **Smaller:** `kit_version` in setup's state, the doctor's MCP row when the health check itself fails, D17's
  explanation of exit 5, `python-docx` in the knowledge environment (the hidden-text and label tests now run),
  `find` coverage and column widths, guide 45's browser check.

### Added
- **Skill listing kept lean.** The kit's own skill descriptions are about 30% shorter (15,511 to 10,913
  characters, the new `kit-update` skill included); nine authoring and admin skills are now started by you (`/workbench-core:<name>`), with hints when a
  request matches them. Setup measures the whole listing on the machine and, past 80% of Claude Code's default
  budget, sets `skillOverrides` to `name-only` for skills outside plugins (packs first, then largest; skills the kit
  routes to stay on; values you set are kept). The doctor warns at 85%. `skillListingBudgetFraction` 0.02 is set as a
  ceiling against truncation, not a target.
- **Claude may change harmless settings with your approval.** An edit of your own `settings.json` that changes only
  `skillOverrides` now asks instead of being refused; every other key is still refused.
- **Automatic issues log.** Every failed tool call is appended, redacted, to `<WB>/state/issues.jsonl`;
  `issues.py show` prints it as a table.
- **Guard:** blocks tokensave's `install`, `upgrade`, `doctor`, `reinstall`, `uninstall`, `claude-install` and
  `claude-uninstall` (each rewrites Claude Code settings or hooks), wherever the command sits in the line; covers
  tokensave's edit tools like Edit and Write; blocks deleting the kit's plugin folder; reads hard links, junctions
  and `\\?\` spellings of protected files as the files they are.
- **Settings:** `MSYS2_ARG_CONV_EXCL` (both profiles; Git Bash no longer rewrites `origin/main:/path`), `MCP_TIMEOUT`
  60 s (corporate).
- **Headless prompts:** an `@` that would make `claude -p` read a file is neutralised in text the kit did not write.
- **ctx:** setup writes the analytics opt-out and Claude-Code-only sources into ctx's own config file.
- **tokensave** is registered parked until you initialise a repository.
- **Tools:** `token_split.py startup` measures a session's opening context; a default trigger-probe spec for the kit's
  skills; three new bug cards (junction deletes, container restarts, bulk replaces on binary files).

### Deferred
- A guard for Windows command-line truncation of long Bash commands (needs a fresh reproduction first).
- Hash-pinned requirements for the knowledge environment.
- Lower-priority tuning items found in the same review.

## 0.3.1

Fixes for installs on managed Windows 11 laptops.

- **Python 3.14 is accepted.** An installed Python 3.13 or 3.14 now meets the setup's Python requirement and builds the
  knowledge environment (3.13 is preferred when both exist). Setup installs 3.13 only when neither is found, so a
  laptop that already has 3.14 no longer fails the run trying to install 3.13. The accepted versions are listed once,
  in `bootstrap/packages.json` (`python313`, `accept`).
- **Background setup runs pass the knowledge-base check.** `setup.py run --detach` runs without a console, and the
  knowledge-base test run (D3) failed only there: its tests lost their output.
  Every Python program setup starts and reads now uses the console interpreter. When D3 fails, its detail names up to
  ten failing tests.
- **Downloads through a TLS-inspecting proxy.** When Windows cannot check a re-signed certificate's revocation
  (curl exit 35 with `CRYPT_E_NO_REVOCATION_CHECK` or `CRYPT_E_REVOCATION_OFFLINE`), setup retries the download once
  with curl's `--ssl-revoke-best-effort` and logs it. Only those two errors are ignored: a revoked certificate still
  fails, and the pinned SHA-256 check still decides. The doctor's `TLS + network` row now names the condition.
- **The nightly-task check (D15) no longer warns about a task that exists.** It compared the task file with
  different line endings from the ones setup recorded.
- **The after-install capability report is current.** It now reads PATH from the registry, so tools the same run
  installed (Git, Node.js, the Playwright CLI and others) show as ready instead of installable, and no needless
  "allow Node.js" request is drafted.

## 0.3.0

### Upgrade notes (from 0.2.0)
- **Skill renamed:** `doc-index` is now `find` (`/workbench-core:find`). The first open of the shared index registers
  every 0.2.0 index whose folder still exists and re-indexes it on the next refresh; the old files stay where they
  were, and `find`'s status prints the command that removes them. `WB_FIND_LAZY=0` turns off the lazy refresh.
- **Variable renamed:** `GITHUB_MCP_PAT` is now `WB_GITHUB_MCP_PAT`. New variables: `WB_GOOGLE_OAUTH_CLIENT_ID`,
  `WB_MS365_CLIENT_ID`, `WB_MS365_TENANT_ID`, `WB_REVIEW_TOKEN`, `WB_REVIEW_ALLOWLIST`, `WB_CLAUDE_BIN`, `WB_GH_MCP_BIN`.
- **Capture is its own opt-in plugin,** `workbench-capture`, installed only with `--with capture`, so IT can allow or
  deny it separately.
- **The nightly index refresh is opt-in on the corporate profile** (`--with nightly`) and on by default on the
  permissive profile (`--no-nightly` turns it off). `find` refreshes lazily either way.
- **Effort defaults:** Sonnet 5.5 is now `xhigh` (was `high`), matching the routing table, and Haiku 5.5 gets `medium`, the
  vendor's recommended starting level for most work; it applies where no persona pins a level (`scout` pins `high`).
  An upgrade changes only values you left as the kit wrote them; unpinned Sonnet work costs somewhat more at `xhigh`.
- An upgrade keeps your knowledge-base folder. A fresh install puts data under `<DATA>` (the work OneDrive's
  `Workbench` folder when exactly one verified work OneDrive exists, else `Workbench` in your profile).
- **Knowledge-base state moved** out of the KB folder to `<CH>/workbench/kb-state/<key>/` (save lock, precompact flags,
  snapshots, metrics, journal windows), so a synced KB folder never holds a lock. The first `save_driver.py --pre` copies
  an earlier `.state/` across under both locks and leaves it readable for one release.

### Install and setup
- `install.py --apply --setup auto` runs the capability report, then provisions the machine in the background:
  user-scope packages from winget, WSL (one UAC prompt and a reboot), a version check per package, the onboarding
  interview, the knowledge layer, the capture runtime when asked for, model routing for the models your organisation
  allows, and a before/after report diff. `--setup plan` stops after the plan. Opt-ins: `--with tokensave, pm-pack,
  upstream-skills, capture, nightly, claude-winget, claude-autoupdate`; `--data-root` sets the data folder.
- Read-only capability report (`bootstrap/report.py`): hardware, the security settings that affect the kit, every
  feature rated READY / INSTALLABLE / NEEDS-IT / BLOCKED-BY-POLICY / UNKNOWN with a ready ask-IT text, and a
  developer-speed test with a verdict, cause and fix. It also reads PowerShell's language mode and any
  group-policy script restriction, so a constrained session is reported before Claude runs a command. Meeting and mail capture rows are marked experimental.
- `setup.py` gains `status --wait`, `doctor` (with a redacted `--bundle`), `backup`, `restore` (settings only with
  `--restore-settings`), `undo-config` and `resume`. Per-client profiles: `bootstrap/profile.py`.
- The Day-1 paste prompt in `IMPORT.md` drives the whole chain through `docs/SETUP-RUNBOOK.md` (per component: the
  command, the check and where it shows, the denial step and the IT ask), with a hard stop on any denial, and ends with a
  results table, the report diff and a "what we can and cannot do here" summary. Two more IT asks: a virtual desktop, and
  headless Edge for the command-line browser.
- `setup.py update [--check] [--json]`, also run as a phase after verify: only the tools this kit installed move to the
  tested pins in `bootstrap/packages.json`; success is the version the tool reports afterwards, never the exit code; a tool
  in use is deferred with its one command; a policy refusal becomes an IT ask, never a retry; anything IT installed is
  reported only. `--no-update` skips it, `--with update-latest` targets the newest release. Claude Code updates through
  `claude update` (its winget package lags its releases). Guide 44.
- Day-1 knowledge checks: `setup.py run` gains the phase `knowledge-verify` (D1-D23 in `bootstrap/knowledge_verify.py`,
  expectations pre-registered in `bootstrap/knowledge-checks.json`), so the knowledge base, journal, index, retrieval,
  link graph, keyword search, hooks and kit tools are proven working on the first run. `setup.py doctor --deep [--json]`
  re-runs them without changing the live profile; it exits 2 when any row FAILs and 0 on warnings.
- The Playwright CLI (`@playwright/cli`, npm, user prefix, `--ignore-scripts`) on the installed Edge, headless by default;
  with `--with ctx`, ctx (local agent-history search; release asset checked by SHA-256; analytics, daemon and self-upgrade
  off). The
  knowledge base becomes the find root `kb`, the office renderer's requirements join the knowledge venv, and the find MCP
  server is registered (undo-config removes it). The nightly task also keeps a weekly backup (`backup --if-older-days 7`)
  and refreshes ctx; backups include the journal. Doctor rows `updates` and `claude startup warnings` (the output of
  `claude doctor` matched against the bug detectors). Guide 45.
- The meeting-transcript IT ask adds the Copilot meeting-insights permission (`OnlineMeetingAiInsight.Read.All`, a Copilot
  licence per user) and a one-line tenant check.

### Knowledge
- `find`: one index over work libraries, captured pages and the how-to library; file catalog, keyword and
  meaning-based search, related files and the newest version; a coverage report lists what was not searched; purge
  zeroes deleted text.
- `workbench-capture` 0.3.0 (opt-in): `capture` reads intranet pages through a dedicated signed-in Edge profile and
  listed OneDrive files, paced and scoped, and stops on any sign-in, consent or policy page; `ingest` (experimental)
  turns downloaded meeting transcripts and cached mail into one knowledge file each, with a quarantined AI digest and
  a daily rollup. Teams and Outlook on the web sources and Recap download automation are deferred
  (`docs/known-limits.md`).
- 55 how-to guides in `docs/howto/`, indexed by `find` as the root `howto`; guide 54 says which knowledge tool answers
  which question, guide 55 covers Claude Code on a virtual desktop.
- Six new bug cards for model changes and API calls (rejected parameters, blank or cut-off replies, tool loops with
  thinking on, tables keyed by model id, searches over stale clones, code defaults that the deployment overrides), with
  detectors and troubleshooting rows. Digest lessons on migrations across many repositories, mocking at the lowest level,
  bulk edits, rollback and knowledge-base evaluations.
- 28 more bug cards (67-94) for Claude Code's own red error messages (overloaded and limit errors, sign-in and gateway
  refusals, proxies, context and request size, model ids, MCP connections, managed settings, hooks, the shell, the
  installer, transcript writes), with detectors that run before the older ones and a troubleshooting section. Guide 43.
- `kb_search` returns one hit per note (a ranking of whole notes fused with the paragraph ranking), tags superseded text,
  resolves a bare link name when one note has it, and falls back to plain matching without FTS5. `kb_health` gains
  `--json`, orphan and retrieval checks and `--eval`; `kb_eval` reports hit@1, hit@5, MRR, p50/p95 latency and
  abstention against pre-registered floors. The template ships `00-index.md`, and every `HOT.md` links back to it.
  `kb_demote` takes the same two locks as a save. `find` searches the knowledge base too and gains `related`.
- `--inbox-add` warns on a backtick, the journal window falls back to a per-process file when the usual one is held open,
  and `--post` advises when more than ten items wait on you.
- A fact registry: `<KB>/_shared/facts.json` pins a fact to one owner note; `kb_health.py facts` fails when a stale or
  competing version appears elsewhere in the KB or the always-loaded files, or the owner stops stating it. `--post`
  stamps `updated:` only on the notes it was named whose bytes changed since `--pre` (never an over-cap HOT.md), runs
  the instruction-surface audit (and weekly the legacy scan) as advisories that can never fail a save, and no longer
  loses a metrics row after a torn last line.
- office-render `hidden_text.py scan FILE... [--json]`: text a reader cannot see but a model reading the file would (flat
  glyph boxes, invisible text over different visible text, off-page or tiny text, hidden Word runs, invisible and bidi
  characters, mixed-script words, forged chat turns, metadata prose), parsed under size, page, memory and time caps,
  report-only, no copyleft code. The ingest quarantine step uses it. Guide 52.

### Skills, plugins and MCP
- New core skills: `setup` (user-invoked), `find`, `repo-review` (allowlisted, read-only review of a foreign
  repository or folder), `plugin-factory`, `plugin-review` (68 rules in nine groups, batch scorecards),
  `web-packager`, `mcp-builder` (Python and TypeScript scaffolds with lint and tests) and `api-bridge` (a curated REST
  or OpenAPI surface as an MCP server). `app-navigator`: an in-app assistant that answers only from the app's help pages
  and links the right page (route inventory, Python and TypeScript backends, a widget that allows only in-app links, an eval
  runner). Guides: `docs/plugins-playbook.md` and `docs/engineering/`.
- `workbench-biz` 0.3.0, installed by default: eight portable business skills for Claude web, desktop and CLI
  (`docs/business-catalog.md`). office-render gains `scrub.py` and `--lint`; office-xlsx builds workbooks from a spec
  and starter workbooks; office-docx takes outlines.
- MCP catalog (every entry off): GitHub hosted, by token, GitHub Enterprise Cloud and local; `find`; Microsoft Learn;
  Azure and Azure DevOps; Atlassian; BigQuery and the gcloud preview; a read-only Microsoft Graph server. A rejected
  list with reasons is in `mcp/README.md`. GitHub Actions templates in `templates/github-actions/`.
- New persona `scout`: a small-model reader for text it is handed.
- repo-fix and investigate search the bug cards first.
- New skills `diagram` (offline diagrams for documents, decks and pull requests) and `brand-spec` (lock a brand spec, then
  build and review a UI against it); nine skills gain a `when_to_use` line. Guides 46 to 48 (diagram, brand spec, build an
  eval).
- brain-audit `audit.py --surface [--json]`: instruction-surface size, over-long or path-scoped rules, repeated lines, dead
  references and hidden skills. cleanup `scan_legacy.py`: report-only, dead documents and unreferenced scripts. handoff:
  client or tenant files stay in a folder that is never pushed, and "pushed" needs `git log origin/<branch> -1 -- <file>`.
  secretscan: more vendor-neutral credential shapes and a command line (exit 0 clean, 1 findings, 2 not scanned). Guide 53.
- Tools: `tools/model-sweep` (gate a retiring model id across repositories), `tools/token-split` (spend by token class from
  local transcripts), `tools/mcp-nowin` (start stdio MCP servers without console windows on Windows),
  `tools/guard-replay`, `tools/skill-probe` and `tools/rules-quiz` (offline checks that rules hold and skills fire). Every
  new tool answers `--self-test`. Guides 49 to 51.
- The `@playwright/mcp` entry ships off: the Playwright CLI is the preferred browser path.

### Guards, hooks and settings
- Corporate guard ids `prod-build`, `protected-db-write` and `security-tooling-change`; `publish-confirm` also asks
  about `gh api` writes. Allowlist keys `production_hosts` and `protected_db_tables`. One list of GitHub write verbs
  (`plugins/workbench-core/scripts/guards/gh_write_verbs.json`), with matching ask rules in both profiles.
- Both profiles: `crossSessionInbound: "hold"`, a subagent concurrency cap (8 corporate, 12 permissive) and the
  telemetry variables `HF_HUB_DISABLE_TELEMETRY`, `PIP_DISABLE_PIP_VERSION_CHECK`, `NPM_CONFIG_UPDATE_NOTIFIER`
  (`DO_NOT_TRACK` only for the tools setup runs: in Claude Code it would also turn off feature flags). The permissive Haiku alias is `claude-haiku-5-5`.
- Statusline shows cache state beside context use. SessionStart reports pending setup, the first five routing rows,
  a managed-policy change since setup and guards that have stopped firing. A failed tool call gets one bug-card hint.
- Corporate guard id `browser-cli`: `playwright-cli` asks before uploads, code run in the page, navigation outside
  localhost and the approved hosts, `attach`, `state-load`, `webmcp-call`, any call with `--profile`, `--persistent`,
  `--extension` or a `--cdp` target that is not localhost, and the commands that print, change or save cookies and
  storage. `route` passes.
- StopFailure relay: when a turn ends on an API error, `bug_hint.py` queues the matching bug card and injects it once on the
  next prompt of that session. Setup adds the two hooks to the user settings only at Claude Code 2.1.78 or later and
  never into the plugin's hooks file; skipped under managed `allowManagedHooksOnly`.
- SessionStart shows a failing or 30-day-old knowledge-verify result.

### Routing, instructions and docs
- Model routing by task type (`docs/model-routing.md`, rendered from `settings/model-routing.json`): 12 rows, quality
  evidence from published benchmarks only. `model-policy.md` points to it; on "model not allowed" step down the chain.
  Internal runs appear as direction-only rows that never rank a pick.
- Both profiles set Sonnet 5.5 to `xhigh` (matching the routing table) and Haiku 5.5 to `medium` (for unpinned use);
  the permissive profile also sets the default subagent model. The capability report recommends a minimum Claude Code version for Haiku 5.5.
- `docs/token-diet.md` compares model prices per token class (cache reads differ) and explains why lowering effort, not
  turning thinking off, is the lever. `docs/known-limits.md` lists what scripts calling the API must change for Haiku 5.5.
- Authoring: a hook cannot overrule a permission rule (`docs/plugins-playbook.md`), `@` imports are written without quotes,
  and the test-validity checklist adds fail-first by mutation and live checks that prove their path. A guide and an IT ask
  for seat usage limits and usage credits.
- The always-loaded instructions stay under the size budget, now checked by a test on the real tree.
- Approver and coworker bundle: `docs/security-overview.md`, `docs/known-limits.md`, `docs/troubleshooting.md`,
  `docs/rules-card.md`, `docs/runbooks.md`.
- Tools: `tools/run_suites.py` (one-command regression run), `tools/skips.allow` (the honest skip list) and
  `tools/skill-bench/` (cost and configuration bench for skills; it never ranks quality).

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
  rate-capped; the Store Python stub; parallel browser sessions.
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
