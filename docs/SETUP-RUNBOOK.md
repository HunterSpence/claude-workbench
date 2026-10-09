# Setup runbook (for the Claude Code session doing the setup)

You are the Claude Code session that sets up claude-workbench on a managed Windows laptop, for the person at the keyboard.
`IMPORT.md` carries the Day-1 prompt that sent you here; this file is the detail behind it. Read sections 0 and 1 first, then
do section 2 in order. For every component you get four things: the exact command, the check that proves it worked and where
the result shows, what to do when something blocks you, and which ask to show. Sections 3 to 6 are what you hand back and how
to undo it all. On Linux or WSL the same flow runs without the Windows-only parts (packages, WSL, the sign-in resume value, the
scheduled task, Edge): setup prints the package-manager commands as asks and runs the report, the knowledge layer and routing.

## 0. Ground rules

1. **The user's Day-1 message authorises every step in this file.** Stop only for: a hash mismatch, a denial (rule 2), a Windows
   UAC prompt (the human clicks it), a reboot.
2. **A denial is a hard stop for that step.** A hook, a permission prompt, a gateway or proxy answer, a managed-settings or
   policy block, a refusal from winget or npm, an HTTP 403 or 407, or a declined UAC prompt means: stop that step, show the
   message to the user word for word, note it for the table in section 3, and carry on with the steps that do not depend on it.
   Never elevate (no "Run as administrator", no machine-scope install of your own), never write a policy key, a managed
   setting or a `.env` file, never change an execution policy, never retry through another tool, shell, mirror or route, and
   never press "request approval" in a consent dialog (it notifies administrators). The remedy is the ask: show its text; the
   user sends it. The kit sends nothing.
3. **Evidence beats exit codes.** A step is done when its verify check passes, not when an installer says it succeeded: a
   tool counts as installed when its own version call prints a version. Decide from exit codes, state files and JSON, never
   from English output. Report only what you measured.
4. **Long work runs detached.** Never run `SETUP run` in the foreground; use `--detach` and poll `SETUP status`.
5. **Words used below.**

| Name | Means |
|---|---|
| `PY` | the Python interpreter: `py -3`, or the full path `IMPORT.md` had you record |
| `<CH>` | `CLAUDE_CONFIG_DIR`, else `~/.claude` |
| `<WB>` | the `workbench` folder inside `<CH>`; `<KIT>` is the `kit` folder inside it, the installed copy of this release |
| `<WB>/state/` | where setup, the report and the checks write (`STATE` below) |
| `SETUP` | `PY <KIT>/bootstrap/setup.py` |
| `KPY` | the knowledge environment's Python: `knowledge_python` in `<WB>/config.json` |
| `ING` | `KPY <KIT>/plugins/workbench-capture/skills/ingest/scripts/ingest.py` (capture only) |

6. **Exit codes.**

| Command | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| `install.py` | done or dry run | unexpected error | environment problem | blocked by your organisation's policy | an apply step failed | |
| `SETUP run`, `resume`, `update` | done | | usage, environment, or already running | done with ask-IT items (update: a denial) | a step failed | waiting for a reboot |
| `SETUP doctor` | all OK | warnings | an error row | | | |
| `SETUP doctor --deep` | no row is FAIL (warnings allowed) | | any row is FAIL | | | |
| `report.py` | done | | usage error | | | |

7. **Where a result shows.** Three kinds of place, all under `<WB>/state/`: a **report row** (an id such as `pkg-node` in
   `capability-<phase>.md` or `.json`), a **doctor row** (a name such as `updates` in the `SETUP doctor` output), or a
   **D-step** (`D1` to `D23` in `knowledge-verify.json`, shown by `SETUP doctor --deep` as rows named `knowledge: <name>`).
   `SETUP status --json` shows the live setup state: `phase`, `running`, `exit_code`, `ask_it` (each with `item` and `text`),
   `failed` (each with `item` and `error`), `notes`, `reboot_pending`, `next`. `setup.log` in the same folder is the full log.
8. **Asks.** The text for a blocked item reaches you in three ways: `ask_it` in `SETUP status --json`, the `ask_it` of a row in
   the capability report, and the `ask_it` of a D-step in `knowledge-verify.json`. `docs/admin-asks.md` holds the long drafts.
   Section 5 maps every ask name to where its text lives. The user reads and sends them (guide 03).

## 1. The order of work

1. Install the kit and choose the profile (2.1).
2. Capability report before anything installs (2.2).
3. Setup plan, then apply it: packages (2.3), WSL (2.4), then the rest of the run, which includes the knowledge layer (2.6),
   the Playwright CLI (2.9), `ctx` (2.10), the StopFailure relay (2.11), capture (2.13) and routing (2.14).
4. Onboarding with the user (2.5).
5. The update phase, looked at and then applied (2.8).
6. The Day-1 knowledge checks (2.7) through `SETUP doctor --deep`.
7. Guards proven (2.12).
8. The final report diff (2.15), the results table (3) and the summary of what we can and cannot do here (4).

## 2. Components

### 2.1 Install and profile choice
**Command.** From the unpacked release folder:
```
PY bootstrap/install.py                                   # dry run: prints the plan, changes nothing
PY bootstrap/install.py --apply --setup plan --with <EXTRAS> --git-hosts <HOSTS>
```
`--setup plan` applies the install, prints the capability report and writes the setup plan, and installs nothing else.
(`--setup auto` runs the report and then starts the whole setup in the background; the Day-1 prompt uses `plan` so you can
read the plan first.) Drop `--with` or `--git-hosts` when the user gave none. The options:

| Option | Effect |
|---|---|
| `--apply` | write the plan (without it nothing is written) |
| `--profile corporate\|permissive` | settings profile, default `corporate` |
| `--upstream-plugins`, `--upstream-plugins-optional` | register upstream plugin marketplaces (the optional set is never implied) |
| `--kb-root PATH`, `--data-root PATH` | where the knowledge base and the data folder live |
| `--git-hosts a,b` | git hosts company code may be pushed to; until set, a push to another host asks first (refused at the strict guard level) |
| `--guard standard\|strict` | guard level, default `standard` (asks instead of refusing for unlisted push or upload hosts and `--no-verify`; plain browser navigation runs); `strict` refuses; kept across upgrades |
| `--with LIST` | opt-ins, below |
| `--no-nightly`, `--no-update` | no nightly refresh task (permissive profile); skip the update phase |
| `--force`, `--no-cli` | replace settings keys the user set; print the `claude` plugin commands instead of running them |
| `--uninstall`, `--purge-backups` | undo (section 6) |

The opt-ins, all off until asked for: `tokensave` (code graph, release zip checked by SHA-256, its upload counter switched
off before first use), `pm-pack` and `upstream-skills` (pinned upstream skills, fetched with
`tools/fetch-upstream/fetch_upstream.py`), `capture` (2.13), `nightly` (2.6), `claude-winget` (Claude Code from winget),
`claude-autoupdate` (2.8), `ctx` (2.10) and `update-latest` (2.8). Add one only when the user named it.

**Profile.** The default is `corporate`: normal permission prompts and no nightly task unless `--with nightly`.
`--profile permissive` is for a machine the user fully controls: it starts in bypass mode with broad allow rules, registers the
upstream plugins and keeps the nightly task on (`--no-nightly` turns it off). Your organisation can disable bypass mode in
managed settings, and then Claude Code will not enter it. Neither profile touches the corporate guard pack (a push allowlist
and asks around the browser CLI): it is on in both, and only `"enabled": false` in `<WB>/corporate-allowlist.json`, the user's
own edit, turns it off; never edit that file yourself. **The user decides the profile, after reading the capability report and
guide 08. Never pass `--profile permissive` on your own.**

**Verify.** Exit 0. The output ends with `Next:` lines. `<KIT>` and `<WB>/config.json` exist. After a restart of Claude Code (close every
Claude Code window and start a new one from a fresh terminal: the `Path` change and the plugins' options, the hook interpreter
among them, are read only when it starts), `/status`, `/plugin`, `/agents`, `/skills` and `/hooks` list the kit, and report rows `plugin-core`, `plugin-kb` and
`plugin-biz` read READY (D14 and the doctor `setup` row repeat the check later).

**If blocked.** Exit 3, or a line starting `STOP`, means managed settings or policy refused a step. The installer never edits
managed settings and refuses to write a key a managed source sets. Quote it and stop that step.
**Ask.** Before the first run, the heads-up text (`docs/admin-asks.md`, section 1). Plugins refused: rows `plugin-core`,
`plugin-kb`, `plugin-biz` and `plugin-capture` carry the marketplace ask; admin-asks "Marketplaces closed". User hooks refused:
row `hooks-guards`; admin-asks "Hooks locked".

### 2.2 Capability report and what each rating means
**Command.**
```
PY <KIT>/bootstrap/report.py run --phase pre             # before setup; the installer already ran it
PY <KIT>/bootstrap/report.py run --phase refresh --quick # under 20 seconds, no network, no model call
PY <KIT>/bootstrap/report.py run --phase post            # after setup; also writes the diff against pre
PY <KIT>/bootstrap/report.py diff <old>.json <new>.json
```
`SETUP report ...` passes its arguments to `report.py`. Other flags: `--no-bench`, `--no-model-call` (skip the one tiny prompt through the user's own login), `--with-doctor` (also
runs `claude doctor`, which rewrites Claude Code's own config files), `--detach`, `--out DIR`, `--packages FILE`,
`--git-hosts H1,H2`, `--extra-endpoint URL`. It changes nothing on the machine.

| Rating | Meaning | You do |
|---|---|---|
| `READY` | works now | nothing |
| `INSTALLABLE` | setup can do it without help | let the run do it |
| `NEEDS-IT` | someone with admin rights must allow or install it | show the row's ask; the user sends it |
| `BLOCKED-BY-POLICY` | the organisation's policy forbids it today | show the ask; a refusal is a decision, work without it |
| `UNKNOWN` | the probe could not tell | read the row's evidence; a `--quick` run leaves many |

**Verify.** `capability-<phase>.md`, `.json` and `.html` exist in `<WB>/state/`, with `probe-<phase>.json`; the Features section
opens with a count per rating; the `.html` shows an "Ask IT" text under every NEEDS-IT and BLOCKED-BY-POLICY row and ends with
a ranked Roadmap of asks. Row families: `pkg-<package id>`, `mcp-<server>`, `model-<persona>-<model>`, `skill-<name>`, and the
fixed rows of `bootstrap/features.json` (platform, knowledge, mcp, capture, storage, github, plugins, safety, tools).
**If blocked.** Rows `blocked` or `proxy-auth` on a host mean a proxy sits in the way (guide 04); nothing here needs a workaround.
**Ask.** admin-asks "The proxy re-signs HTTPS and a runtime rejects it", "Package sources"; row `github-com`, `github-ghe-com`
or `github-ghes` for the git host.

### 2.3 Packages
**Command.**
```
SETUP plan [--with LIST]          # writes plan.json, plan.md and workbench.winget; installs nothing
SETUP run --detach --no-update [--with LIST]   # the same --with as at install: install passes it to the plan only
SETUP status --json --wait 120    # repeat until "running" is false; tell the user each new phase in one line
SETUP verify                      # prints "<id> <status> <version>" for every package; exit 4 if one does not answer
```
Read `<WB>/state/plan.md` before applying and show its table. Each plan item carries a tag: `works` (nothing to do), `found`
(on disk but its version call fails; reinstalled at the same scope), `no-admin`, `one-admin-prompt` (a UAC prompt the human
clicks), `ask-IT` (the text is in the state) or `opt-in-off`. Besides the packages the plan lists `winget-configure`, `wsl`,
`tls-fixes` (only when the probe saw TLS inspection), `claude-autoupdate`, `pm-pack`, `upstream-skills`, `update`, `nightly`
and `capture-runtime`.

| Package id | What it is | Comes from |
|---|---|---|
| `git` | Git for Windows, the shell Claude Code uses | winget, user scope |
| `gh` | GitHub CLI | winget, user scope |
| `python313` | Python for the knowledge environment: an installed 3.13, else 3.14, counts (the one list is `accept` in `bootstrap/packages.json`); 3.13 is installed only when neither is found | winget, user scope |
| `uv` | Python package manager | winget, user scope |
| `pwsh` | PowerShell 7 | winget; user scope needs non-admin packaged-app installs, else one UAC prompt |
| `rg`, `fd`, `jq` | ripgrep, fd, jq | winget, user scope |
| `code` | Visual Studio Code | winget, user scope |
| `node` | Node.js LTS (npm, npx) | winget machine-wide installer: one UAC prompt; without admin rights the `fnm` route |
| `fnm` | user-scope Node.js manager, setup's route for `node` without admin | winget, user scope |
| `claude` | Claude Code | winget, only with `--with claude-winget` |
| `playwright-cli` | Playwright CLI (2.9) | npm, needs Node.js |
| `tokensave` | optional code graph | release zip, only with `--with tokensave` |
| `ctx` | local agent-history search (2.10) | release asset, only with `--with ctx` |

`tokensave` is registered in the machine's MCP configuration **parked**: the healer reports it as PARKED, not DOWN, and the
doctor does not warn, until a repository is initialised (`tokensave init`, `mcp/README.md`). Never run `tokensave install`,
`reinstall`, `upgrade`, `doctor`, `uninstall`, `claude-install` or `claude-uninstall` (`doctor` adds hooks to the user's
settings on its own; the others rewrite or remove its settings, permissions, hooks and rules); the guard blocks all seven.

Every package row has a tested `pin` in `bootstrap/packages.json`. Setup installs through `winget configure` when it is allowed
and one package at a time otherwise (`winget install --id <id> -e --source winget --scope user ...`).
**Verify.** `SETUP verify` prints a version for each package; report row `pkg-<id>` is READY; `plan.md` shows `works`; the doctor
row `setup` is OK. A package is installed only when the version call named in `packages.json` prints a version.
**If blocked.** A winget policy value or an exit code that means "denied" turns the item into an ask-IT entry and nothing is
retried. A declined UAC prompt is recorded as a failure; the user can run setup again and approve it. Setup never elevates on
its own: the only elevation is winget's own UAC prompt for a machine-wide package, which the human clicks.
**Ask.** The package's own `ask_it` in `bootstrap/packages.json` (shown by `SETUP status --json` and under its `pkg-<id>` row);
`winget-configure` for configuration files; admin-asks "Package sources". Node.js missing blocks `playwright-cli`: show the
`node` ask.

### 2.4 WSL
**Command.** Part of `SETUP run`: the plan item `wsl`. When WSL is not installed and the user can elevate, it runs
`wsl --install --no-distribution` (one UAC prompt, then a reboot); it then runs `wsl --install -d Ubuntu-24.04 --no-launch`
(no prompt when WSL is already on), and writes a `.wslconfig` when the user has none (6 GB memory, 4 GB swap, 4 processors;
mirrored networking only if policy allows). A user who cannot elevate gets the item as `ask-IT`. When a restart is needed the state shows phase
`reboot-wait`, exit code 5 and `reboot_pending` true. Tell the user to save their work and restart Windows; a one-shot
sign-in value resumes setup, and by hand it is `SETUP resume`. Afterwards the user restarts Claude Code. Creating the Linux user
(`wsl -d Ubuntu-24.04`, once) is the user's step.
**Verify.** `wsl -l -v` lists `Ubuntu-24.04` at version 2; `SETUP status --json` shows `reboot_pending` false; report rows
`wsl2` and `sandbox` move toward READY.
**If blocked.** The WSL policy `AllowWSL` set to 0 makes the plan item `ask-IT`; a refused or declined install is recorded and
not retried. On a virtual desktop the machine also needs nested virtualization (guide 55).
**Ask.** Row `wsl2` (admin-asks "Developer features: WSL2, virtualization, long paths"); row `sandbox` points at the same ask.

### 2.5 Onboarding
**Command.** No command: interview the user by following `<KIT>/plugins/workbench-core/skills/onboard/SKILL.md` (it is
`/workbench-core:onboard` in a session). Setup never waits for it; its phase `onboard` only adds the note "onboarding: run
/workbench-core:onboard to fill in USER.md" while `<WB>/USER.md` is still the template, and `next` in the state names it.
Run it after the setup finishes. Work facts only; never ask for passwords, tokens, keys or one-time codes.
**Verify.** `<WB>/USER.md` no longer equals `<KIT>/templates/USER.md`; the note is gone from `SETUP status --json`.
**If blocked.** Nothing here can be denied. If the user skips a question, leave it empty.
**Ask.** None.

### 2.6 Knowledge layer and the find MCP
**Command.** The run's phase `knowledge`: it shows `<KIT>/bootstrap/infosec-note.txt` once (read it to the user), creates the
knowledge environment `<WB>/venv/` with Python 3.13 or 3.14 (the `python313` row in 2.3), installs the pinned requirements of the `find` and `office-render` skills
into it, writes `knowledge_python` and `knowledge_db` into `<WB>/config.json`, runs `find discover`, and registers the roots
(the user's work libraries, `captured`, `howto`, `kb`). The phase `knowledge-verify` then runs D1 to D23 (2.7) and registers
the find MCP server (D13). Last, with `--with nightly` (or on the permissive profile) a per-user task
`\claude-workbench\knowledge-refresh` is created and run; otherwise one detached `refresh --all` starts. By hand:
```
KPY <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py status --json
KPY <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py roots --json
KPY <KIT>/plugins/workbench-core/skills/find/scripts/doc_index.py search "<words>" --limit 5 --json
PY <KIT>/plugins/workbench-kb/scripts/kb_health.py --json
PY <KIT>/tools/mcp-healer/mcp_healer.py check
SETUP backup
```
The find MCP server is a local stdio server named `find` with three tools (`search`, `show`, `related`); setup writes it to the
user's `.claude.json` (in `<CH>` when `CLAUDE_CONFIG_DIR` is set) through the MCP healer, records it so `undo-config` removes it,
and every result it returns is marked `untrusted`. If `.claude.json` does not exist yet, start Claude Code once and run
`SETUP run --detach` again.
**Verify.** D1 to D13 and D19 in `knowledge-verify.json`; doctor rows `knowledge index` (OK when the last full refresh is under
48 hours old), `MCP servers` and `backup`; report rows `find-keyword`, `find-hybrid`, `find-mcp`, `knowledge-verified`,
`knowledge-refresh-task`, `scheduled-tasks` and `storage-work-cloud`.
**If blocked.** Hybrid search downloads one embedding model from huggingface.co; if that is blocked the index stays
keyword-only (D9 and D11 WARN) and everything else works. A managed MCP policy stops the `find` registration (D13 WARN). A doctor
`placement` FAIL means the config folder, the index or a git repository sits inside OneDrive: move it, no ask is involved.
**Ask.** Row `find-hybrid` (huggingface.co downloads); row `find-mcp` (admin-asks "MCP restricted"); rows `knowledge-refresh-task`
and `scheduled-tasks` (Task Scheduler not running).

### 2.7 The Day-1 knowledge checks, D1 to D23
**Command.** Setup runs them as phase `knowledge-verify` (it may create in the live profile: the KB index, one journal line, the
find MCP registration, the first backup). To run them again at any time:
```
SETUP doctor --deep [--json]
```
In that mode every check that writes does so in a sandbox; the only file written is `<WB>/state/knowledge-verify.json`, with
one step per check: `id`, `name`, `status` (`PASS`, `WARN`, `FAIL`, `SKIP`, `OPT-IN-OFF`), `detail`, `ms`, `ask_it`; and a
`summary` with `pass`, `warn`, `fail`, `failing`. A check that runs past its timeout is a WARN.

Named FAIL list: D1, D2, D3, D4, D5, D6, D7, D10, D14, D20, D21

Only those checks can FAIL; a failure in any other is capped at WARN because it depends on the environment. `SETUP doctor
--deep` exits 2 when any row is FAIL (a doctor row or a named check) and 0 otherwise. A named FAIL during `SETUP run` becomes
the failed item `knowledge-verify` and exit 4; a WARN that carries an ask becomes an ask-IT item.

| Id | Name | What it proves | Status rule |
|---|---|---|---|
| `D1` | `kb-seeded` | the KB has its domain folders with a `HOT.md`, `active-context.md`, `00-index.md` | FAIL: run `install.py --apply` again |
| `D2` | `kb-state` | the KB state folder is local, outside the KB and not in OneDrive; its lock is free | FAIL |
| `D3` | `kb-machinery` | the KB unit tests pass under a 1 GB memory cap; skips only if listed in `tools/skips.allow` | FAIL |
| `D4` | `journal` | one journal line is written and `kb_search.py --scope all` finds it | FAIL |
| `D5` | `kb-index` | `kb_index.py build` works (FTS5) and `kb_health.py` caps, frontmatter and secrets pass | FAIL; WARN without FTS5 |
| `D6` | `kb-retrieval` | the canned retrieval cases pass their floors on a sandbox KB | FAIL |
| `D7` | `kb-graph` | `kb_search.py --related` reaches `00-index.md` and `_shared/HOT.md` in two hops | FAIL |
| `D8` | `find-roots` | roots `captured`, `howto`, `kb` are registered | WARN |
| `D9` | `find-build` | a sandbox index of `howto` and `kb` builds, with vectors if the model is available | WARN; keyword-only carries `find-hybrid` |
| `D10` | `find-keyword` | the pre-registered how-to questions (`docs/howto/questions.json`) find their guide in the first 3 files; the bar is in `bootstrap/knowledge-checks.json` | FAIL |
| `D11` | `find-meaning` | hybrid search does at least as well as keyword | WARN; carries `find-hybrid` |
| `D12` | `find-graph` | `related` and `newest` work over the how-to library | WARN |
| `D13` | `find-mcp` | the `find` server is registered, answers the MCP handshake and a search, results marked `untrusted` | WARN; carries `find-mcp` |
| `D14` | `hooks` | session start emits `active-context.md`; precompact writes its flag and snapshot outside the KB; the StopFailure relay dry run passes when the kit ships it | FAIL; WARN while plugins are not yet enabled or no session has fired the hooks |
| `D15` | `schedule` | the nightly task exists as recorded | WARN when off (corporate profile without `--with nightly`) |
| `D16` | `backup` | `SETUP backup`, then a restore drill into a temp folder with hashes checked | WARN |
| `D17` | `capture` | capture runtime answers and a fixture transcript becomes one meeting file in a sandbox | `OPT-IN-OFF` unless `--with capture` |
| `D18` | `opt-ins` | `tokensave` and `ctx` answer their version call when installed | `OPT-IN-OFF` when neither is |
| `D19` | `full-refresh` | the last full index refresh is under 48 hours old | `SKIP` during setup; WARN later |
| `D20` | `record` | `knowledge-verify.json` was written atomically and reads back equal | FAIL |
| `D21` | `kit-tools` | every kit tool listed in `knowledge_verify.py` answers `--self-test` offline | FAIL only for a tool that is present and fails |
| `D22` | `updates` | the update record (2.8) is summarised | `SKIP` with `--no-update` |
| `D23` | `browser-cli` | `playwright-cli --version`, then headless Edge opens `about:blank` and closes | WARN; carries `browser-automation` or the headless ask |

**Verify.** `knowledge-verify.json` exists and its `summary.failing` is empty; report row `knowledge-verified` reads READY
("N/M PASS"). **If blocked.** A FAIL is a fault in the machine or the kit, not a policy: show its `detail` word for word, fix
nothing by hand, run `SETUP doctor --deep` again after the user or IT acts. A FAIL caused by a hook or permission denial is a
denial (rule 2). **Ask.** The `ask_it` field of the WARN step, if any; see section 5.

### 2.8 The update phase
**Command.**
```
SETUP update --check [--json]            # changes nothing; writes update.json and update.md
SETUP update [--with update-latest]      # applies; --with update-latest moves to the newest instead of the tested pin
SETUP run --no-update                    # a run without the phase
```
A normal run also does this after `verify`. The Day-1 prompt skips it there and runs `--check` and then the apply by hand, so
the user sees the table before anything moves. Exit 0, 3 when something was denied, 4 when something failed.

Rules the command enforces, so do not do them yourself: only tools this kit installed (the ledger) are touched, and only to the
`pin` in `bootstrap/packages.json`; a tool IT or the user installed is `it-managed` and only reported; a newer tool than the
pin is left alone; success is judged by the version call after the update, never by the exit code; a tool in use (`git`,
`pwsh`, `node`, `claude`) is `deferred` and its command is printed for the user to run after closing everything that uses it;
a machine-wide tool is `deferred` too (setup never elevates). winget runs `winget upgrade --id <id> -e --source winget
--version <pin> --scope user ...`; npm runs `npm install -g <package>@<pin> --ignore-scripts --no-audit --no-fund`; release
downloads are re-fetched with the SHA-256 check. The knowledge environment is put back on the pins in the `find` skill's
`requirements.txt`; newer releases there are report-only rows `pip:<name>`.

**Claude Code** is the process running you, so setup never replaces it: its row is `deferred` with the command `claude update`.
Tell the user to run that from a plain terminal with no Claude Code session open, then restart. `--with claude-winget` installs
Claude Code from winget; `--with claude-autoupdate` sets the user variable `CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE` to `1`,
which makes a winget-installed Claude Code run its own upgrade in the background (Claude Code's setup documentation).

`update.json` rows: `id`, `before`, `target`, `after`, `action`, `command`, `note`; `action` is one of `upgraded`, `current`,
`deferred`, `it-managed`, `skipped-policy`, `denied`, `failed`.
**Verify.** `update.md` lists every installed tool with an action; after an `upgraded` row `after` equals `target`; doctor row
`updates` is OK (or WARN naming the deferred and failed tools, INFO before the first record); D22.
**If blocked.** `denied` is a refusal: the ask is in `SETUP status --json`, nothing is retried. `skipped-policy` means an App
Installer policy value blocks winget. `failed` with "reports X, not Y" means the installer exited 0 and the version did not move:
show the printed command to the user. **Ask.** The package's `ask_it`; admin-asks "Package sources".

### 2.9 The Playwright CLI with Edge, headless
**Command.** The package `playwright-cli` installs in the run's install phase when Node.js works:
`npm install -g @playwright/cli@<pin> --ignore-scripts --no-audit --no-fund` into the user's own npm prefix, else into `<WB>/npm/`
(a prefix that is not on the user Path yet is appended to it), with `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`: no browser is downloaded, the browser is the Edge that is
already there. Setup writes `<WB>/state/playwright-cli.config.json` (Edge channel, headless unless Edge's `HeadlessModeEnabled`
policy is off) and points the user variable `PLAYWRIGHT_MCP_CONFIG` at it (an existing value is kept and noted). It runs
`playwright-cli install --skills --global` only when the installed version equals the pin. By hand:
```
playwright-cli --version
playwright-cli -s=check open about:blank --browser=msedge
playwright-cli -s=check close
```
The corporate guard pack asks before `upload` and `drop`, before `eval` and `run-code`, and before `open`, `goto` or `tab-new`
to any address that is not localhost or a loopback address and not a host in `git_remote_hosts` or `upload_hosts` of
`<WB>/corporate-allowlist.json`; the pack's `enabled` key in that file switches it. The `playwright` MCP entry stays off: the CLI
is preferred (guide 45).
**Verify.** `playwright-cli --version` prints a version; report rows `pkg-playwright-cli` and `browser-automation` are READY; D23
is PASS; `SETUP verify` lists it.
**If blocked.** No Node.js: the item is `ask-IT` (rows `pkg-node`). npm refusing the install (E403 or E407) is a denial. Edge's
`RemoteDebuggingAllowed` policy off makes `browser-automation` BLOCKED-BY-POLICY and D23 skips the launch. Edge's
`HeadlessModeEnabled` off means the CLI would open a visible window: D23 does not launch it; do not open a window on the user's
screen unasked. Never run `npx playwright install` or download a browser.
**Ask.** Row `browser-automation` (admin-asks "Headless Edge for the command-line browser tool"); the headless ask in D23's
`ask_it`; the package's `ask_it` for the npm install.

### 2.10 ctx (local agent-history search)
**Command.** Opt-in: `--with ctx`. Setup downloads the pinned release asset (about 200 MB) over HTTPS, checks its SHA-256 against
`bootstrap/packages.json`, and puts it in `<WB>/bin/`. Before its first run it sets the user variables `CTX_ANALYTICS_ENABLED=false`,
`CTX_DAEMON_ENABLED=false` and `CTX_UPGRADE_AUTO=off`, then runs `ctx index mode manual`; if that fails the binary is removed
unused. Setup also writes the analytics opt-out and limits the sources to Claude Code in ctx's own configuration file, so a coding
agent that is not installed here does not fail the nightly import; a real ctx failure still does. The nightly task, when it exists, adds `ctx import --all`. By hand, after the user agreed:
```
ctx --version
ctx status
ctx import --all
```
Do not run `ctx integrations install`, `ctx index mode auto`, or anything that enables a hosted embedding service. ctx indexes
the user's own coding-agent transcripts on this laptop, so ask before you search them (the skill is
`ctx-agent-history-search`).
**Verify.** `ctx --version` prints a version; report row `pkg-ctx` is READY; D18 is PASS; a new shell shows
`CTX_DAEMON_ENABLED` as `false`.
**If blocked.** A refused download (HTTP 403 or 407) is a denial; a SHA-256 mismatch deletes the download and is a failure: report
it, do not use the file. **Ask.** The `ctx` package's `ask_it`.

### 2.11 The StopFailure relay
**Command.** None to run. After the knowledge phase `SETUP run` adds two hook entries to the user's `<CH>/settings.json`:
`StopFailure` runs `bug_hint.py`, which writes `<WB>/state/pending-hint-<session id>.json` and prints one bell; `UserPromptSubmit`
runs `bug_hint.py --pending`, which injects that session's queued line once and deletes the file. Setup installs them only when
all of these hold: the kit's `bug_hint.py` defines `STOPFAILURE_MIN_CC` (2.1.78 in this release), `claude --version` is at or above
it, and managed settings do not set `allowManagedHooksOnly`. Otherwise nothing is installed and `notes` in `SETUP status --json`
says why; after Claude Code is updated, run `SETUP run --detach` again. The entries are recorded in the ledger (key
`settings:stopfailure-relay`), replaced as a pair on each run, and removed by `undo-config`. They are never in the plugin's static
`hooks.json`.
**Verify.** `claude --version`; both entries in `<CH>/settings.json` (read it, never edit it); D14 says "StopFailure relay dry
run ok"; after a failed turn the next prompt shows one line naming a bug card.
**If blocked.** Managed `allowManagedHooksOnly` means user hooks never run; the note says so. **Ask.** Row `hooks-guards`
(admin-asks "Hooks locked").

### 2.12 Guards
**Command.** The guards ship with the `workbench-core` plugin: a command guard with a generic rule pack and the corporate pack
(on by default in both profiles), a credential check on written files, session notices and a statusline. Restart every Claude Code window after the install (close them all and start a new one from a fresh terminal) so the plugins
load with their options, run any tool, then prove they run:
in a scratch git repository ask Claude to run `git push --force origin main`. It must be blocked with a message. Hooks fail open
silently when misconfigured, so this is the only proof. Pushes are refused to any host not in `--git-hosts` (the allowlist is
`<WB>/corporate-allowlist.json`); that is expected until the user names theirs (guide 20).
**Verify.** The block message appears; the doctor row `guard heartbeat` is OK (WARN until a session ran a tool, FAIL after three
sessions without a guard firing); D14; report rows `hooks-guards` and `plugin-core`. The installer's own self-test does not count
as a guard firing: it is recorded apart (`self_test_at` in `<WB>/state/guard-heartbeat.json`) and leaves `last_fired` alone.
**The issues log.** The failure hook also appends every failed tool call (not one the user interrupted) to
`<WB>/state/issues.jsonl`: UTC time, tool, session id and the first ten error lines, with credential-shaped values replaced by
`[REDACTED]`. At 5 MB the file rotates (one `issues.jsonl.1` is kept) and a write problem never stops the hook. List it, or hand
it over to be fixed, with `PY <KIT>/plugins/workbench-core/scripts/issues.py show [--since YYYY-MM-DD]`: a numbered markdown table
of number, time, tool and first error line. It stays empty while the plugins' hooks do not run (troubleshooting: `Plugin option
"python" isn't set`).
**If blocked.** A block of your own command is a denial: show it, never rephrase the command to slip past it. Hooks locked by
managed settings: the kit then runs without them, on permission prompts only. **Ask.** Row `hooks-guards` (admin-asks "Hooks
locked"); rows `plugin-*` for a closed marketplace.

### 2.13 Capture (opt-in)
**Command.** Only if the user asked for it. First the security heads-up (`docs/admin-asks.md`, section 1) and the pre-clearance
note (`plugins/workbench-capture/skills/capture/references/pre-clearance.md`). Then `SETUP run --detach --with capture`: it copies the
runtime to `<WB>/capture/app/`, runs `npm install --ignore-scripts` there and checks that `node capture.mjs --version` prints
`capture <version>`. The signed-in browser profile `<WB>/capture/profile/` needs one interactive sign-in by the human; never type
credentials for them. Meetings and mail (experimental) go through guide 41:
```
ING setup --apply
ING ack-infosec                 # prints the note and records the acknowledgement; without it every run exits 5
ING status --json
ING meetings run
```
**Verify.** D17 is PASS; `ING status --json` shows `infosec_ack` true; report rows `capture-intranet`, `capture-shared-files`,
`capture-mail-full` and `capture-meeting-transcripts` (`capture-teams` and `capture-outlook` are deferred in this release and
read UNKNOWN).
**If blocked.** Ingest exit 3 is a stop by a guard, policy or tenant gate: report `stop.reason` and `stop.ask` word for word and
do not retry another way. A transcript download denied by the meeting's organiser is the answer: the Recap fallback applies only
if the user may download. **Ask.** Rows `capture-intranet` and `capture-shared-files` (admin-asks "Browser automation for the
capture plugin"); `capture-meeting-transcripts` (it carries `OnlineMeetingTranscript.Read.All`, the Copilot insights permission
`OnlineMeetingAiInsight.Read.All` and the tenant check; section 4 of admin-asks and guide 41); `capture-mail-full`; `ai-digests`.

### 2.14 Routing
**Command.**
```
SETUP routing
```
It runs in every `SETUP run`, and any time later: it rewrites `<WB>/state/routing.effective.json` from
`settings/model-routing.json` and the models the probe found allowed, and prints it. Exit 0, or 4 when the routing table is
missing from the kit.
**Verify.** `routing.effective.json` exists; report rows `model-<persona>-<model>` read READY (named in the managed allow list),
UNKNOWN (no allow list to check) or BLOCKED-BY-POLICY (denied or not allowed); a row for a model that needs a newer Claude Code
says which version.
**If blocked.** A managed model allow list narrows the table by itself: the kit steps down to the next allowed model and never
tries a blocked one. **Ask.** admin-asks "Models restricted".

### 2.15 The final report diff, and how to read it
**Command.** The run's last phase writes `capability-post.*` and `capability-diff.*`. If they are missing:
```
PY <KIT>/bootstrap/report.py run --phase post --packages <KIT>/bootstrap/packages.json
```
**Read `capability-diff.md`.** It opens with the count per rating before and after, then "Rows that changed", then rows added or
removed and the dev-speed verdict. Read it like this: INSTALLABLE to READY is what setup was for; a row still NEEDS-IT or
BLOCKED-BY-POLICY is a pending ask; READY to anything else is a regression, so look at `setup.log` and the doctor before you
report; a row only added or removed means the kit changed between the two runs.
**Verify.** The diff file exists and its counts add up to the number of rows in `capability-post.json`.
**If blocked.** Nothing to deny. **Ask.** The Roadmap in `capability-post.html` ranks the asks by what each unlocks.

### 2.16 Updating the kit itself
**Command.** The user says "check the new stuff and go", "update the kit" or "check for kit updates"; the `kit-update` skill runs
```
PY <KIT>/bootstrap/kit_update.py                     # update (or "already current" + the verify); --check changes nothing
PY <KIT>/bootstrap/kit_update.py verify              # the pending post-update verify (also runnable alone)
PY <KIT>/bootstrap/kit_update.py record guard-live PASS|WARN|FAIL "<text>"     # the live guard test row, see below
```
The update asks GitHub for the latest release (anonymous HTTPS through setup's own `curl` helper, so the Windows revocation retry
applies), requires a published SHA-256 for the zip (the release's digest and its checksum table; two values that differ, or none, stop
it before any download), compares the download with it, unpacks into a fresh folder under `<WB>/state/kit-update/`, refuses an
archive entry outside that folder or a package whose `VERSION` is not the release's, runs that release's `install.py --apply
--profile <the recorded profile> --with <the remembered opt-ins>`, then `setup.py run --detach` with the same opt-ins (read from
`<WB>/state/setup-state.json`, nothing added) and waits for it with `status --json --wait 60`. The tool that runs you has a timeout
(2 minutes by default), so the update is a chain of short stages kept in `<WB>/state/kit-update.json`: give every call an explicit
10-minute timeout, and whenever the output says "Run the same command again" (exit 6) run the SAME command again. A call waits at most
`--wait` seconds (90 by default); setup is waited for first, then `doctor --deep` runs as a background job of its own (the next call
collects it), then the marker `<WB>/state/post-update-verify.json`, one table and the line "Restart every Claude Code window, then type:
go". Exit 3 is a proxy or policy block (show it, ask IT), 4 a failed step, 5 a reboot. Where the releases live: the repository the kit
remembers (`config.json` `kit_repo`), else env `WB_KIT_REPO`, else `plugins/workbench-core/skills/kit-update/release-source.json` (empty on
purpose); the first time the repository the user names in their message (`--repo OWNER/REPO`), and a `--repo` that differs from the remembered one is refused unless `--new-repo` is given (never add it
yourself). The guard asks the user before any `kit_update.py` call except `verify`, `record` and `--check`.
Setup (not you) also applies the user-only parts: the plugin python option, `<WB>\bin` on the Path, and the skill tiers
(`SETUP skills [--dry-run] [--force]`: over 80% of the listing limit, the user's own skills go name-only, largest first; skills the kit
routes to stay on; a value the user set stays unless `--force`; `settings.json` is backed up first; plugin skills are never changed).
**Verify.** After the restart the session start line "a post-update verify is pending" tells you to run `verify`: PASS / WARN / FAIL /
NEEDS-IT per check, the IT asks once, and the box FOR THE KIT AUTHOR (kit defects only, scrubbed), saved as
`<WB>/state/field-report.md`; the marker is cleared. Then do the live guard test no script can do: in a scratch repository under the
temp folder (remote `https://example.invalid/scratch.git`) try `git push --force origin main`; the workbench guard must block it; run
`record guard-live PASS|FAIL` and delete the scratch repository.
**If blocked.** A hash mismatch, a denial or a declined UAC prompt is a hard stop. **Ask.** admin-asks: the release hosts
(`api.github.com`, `github.com`, `release-assets.githubusercontent.com`).

## 3. What you hand back: the results table
Finish with a table, one row per component of section 2 (and one per opt-in the user chose):

| Component | Command run | Result | Evidence | Pending ask |
|---|---|---|---|---|
| e.g. Packages | `SETUP run --detach --no-update` | DONE | `SETUP verify`: every package answers; rows `pkg-*` READY | none |
| e.g. Playwright CLI | in the run | WARN | D23 detail: Edge policy blocks headless mode | `browser-automation` |

Result is `DONE`, `WARN`, `BLOCKED` (a denial), `FAILED`, `DEFERRED` (needs the user) or `OFF` (opt-in not chosen). Evidence is a
state-file field, a row id or an exit code, never a sentence of your own. The rows are your measurements, not a template to copy.

## 4. What we can and cannot do here
Fill this in from `capability-post.json`, `SETUP status --json`, `update.md` and `knowledge-verify.json`; do not write it from
memory. A starting point that lists every row that is not READY:
```python
import json, os
state = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"), "workbench", "state")
c = json.load(open(os.path.join(state, "capability-post.json"), encoding="utf-8"))
for r in c["features"]:
    if r["status"] != "READY":
        print(r["status"], r["id"], "|", r["note"], "|", "ask" if r["ask_it"] else "")
```
Then write four short lists:
- **We can:** the READY and INSTALLABLE groups in words (for example "search my documents and notes, keyword and meaning",
  "drive Edge from the command line, headless", "guards on every command"), each backed by a row or a D-step.
- **We cannot, yet:** every NEEDS-IT and BLOCKED-BY-POLICY row, with the reason from its `note` and the ask name.
- **Pending asks:** every `ask_it` entry of `SETUP status --json`, every D-step `ask_it`, with the ask name from section 5. The
  user sends them; offer to open the text, never send it.
- **Waiting on the user:** deferred update commands (including `claude update`), a restart of every Claude Code window so the plugins and the `Path` change load (a fresh terminal),
  onboarding, the guard test, a reboot, and any opt-in they did not choose.

## 5. Ask index: which ask to show
Each name is a row id in `bootstrap/features.json` or a plan item; its text is in the capability report beside the row, in
`SETUP status --json`, or in the `ask_it` field named below. The long drafts are in `docs/admin-asks.md`.

| Ask name | Show it when | Where the text lives |
|---|---|---|
| `wsl2`, `sandbox` | WSL2 is NEEDS-IT or `AllowWSL` is 0 | features.json; admin-asks "Developer features" |
| `powershell` | PowerShell is in a restricted language mode or script policy | features.json; admin-asks "PowerShell language mode" |
| `hooks-guards` | user hooks are refused (`allowManagedHooksOnly`) | features.json; admin-asks "Hooks locked" |
| `plugin-core`, `plugin-kb`, `plugin-biz`, `plugin-capture` | the marketplace is closed | report row (marketplace allow list); admin-asks "Marketplaces closed" |
| `find-mcp` | a managed MCP policy blocks the local `find` server | features.json; admin-asks "MCP restricted" |
| `find-hybrid` | the embedding model host is blocked (D9, D11) | features.json |
| `knowledge-refresh-task`, `scheduled-tasks` | Task Scheduler is not running | features.json |
| `browser-automation` | Edge remote debugging is off (the Playwright CLI, D23) | features.json; admin-asks "Headless Edge for the command-line browser tool" |
| `capture-intranet`, `capture-shared-files` | Edge remote debugging is off (capture) | features.json; admin-asks "Browser automation for the capture plugin" |
| `capture-mail-full` | classic Outlook policy blocks scripted reads | features.json; admin-asks section 4 |
| `capture-meeting-transcripts` | meeting transcripts and the Copilot insights permission | features.json; admin-asks section 4; guide 41 |
| `ai-digests` | summarising mail or transcripts through the Claude login | features.json |
| `github-com`, `github-ghe-com`, `github-ghes` | the git host is not reachable | features.json; admin-asks "Git host and sign-in" |
| `pkg-<package id>` | a package is NEEDS-IT or ask-IT | `ask_it` in `bootstrap/packages.json`; admin-asks "Package sources" |
| `winget-configure` | winget configuration is switched off | `SETUP status --json` |
| models | a model is denied or not allowed | admin-asks "Models restricted" |
| virtual desktop | session limits, profile size, nested virtualization | admin-asks "Virtual desktop"; guide 55 |

## 6. Rollback
```
SETUP undo-config                       # dry run: lists what it would undo
SETUP undo-config --apply
PY <KIT>/bootstrap/install.py --uninstall            # dry run
PY <KIT>/bootstrap/install.py --uninstall --apply [--purge-backups]
```
`undo-config` replays setup's ledger, newest first: the user variables it set (certificate trust, the Playwright CLI
configuration, the three `ctx` variables, `CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE`), the Path entries it added, the Git setting
it changed, files it wrote and the folders under `<WB>` it created, the scheduled task, the sign-in resume value, the StopFailure
relay hooks, the `find` MCP registration, the npm package `@playwright/cli` (`npm uninstall -g`) and the capture browser profile.
A value changed since setup wrote it is left. `install.py --uninstall` uninstalls the plugins, restores every backed-up file,
removes what the installer added and runs the same undo; `--purge-backups` also deletes `<WB>/backups/` afterwards. Exit 4 means
something could not be undone and stays in the ledger.

What stays because it is the user's: `<DATA>/` (knowledge base, captured copies, backups), `<WB>/USER.md`, profiles under
`~/.claude-profiles/`, the skill folders that `upstream-skills` and the Playwright CLI installed (delete by hand), and the packages
(remove with `winget uninstall` if wanted). To bring back configuration from a backup: `SETUP restore <zip> --to <empty folder>`
(a dry run by default; `--apply` writes, settings files only with `--restore-settings`). Purging indexed or captured data:
guide 32. A redacted support bundle for IT: `SETUP doctor --bundle support.zip`.
