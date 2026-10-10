# Importing claude-workbench

This page is written for two readers: you, and the Claude Code session you ask to do the import. The session's detailed
guide, with every command, check, denial step and ask, is `docs/SETUP-RUNBOOK.md`.
The import is a one-time, pinned copy of a tagged release. Nothing auto-updates, no git remote to
this repository is configured, and no credentials are used.

## Before you start
- **Check your organisation's policy** on installing third-party or open-source tooling, and get
  whatever approval it requires. Many organisations want a security review of anything that runs
  as a hook, because hooks execute code on every tool call. Give your security team
  `docs/security-overview.md` (what runs, what leaves the machine) and the heads-up text in
  section 1 of `docs/admin-asks.md`.
- **Managed settings always win.** The installer never edits them and refuses to write any key a
  managed source already sets. If your organisation blocks plugins or user hooks, stop and ask
  your IT team; don't look for a way around it.
- You need Claude Code and Python 3.10+ (`py -3 --version` on Windows, `python3 --version` on
  Linux). Setup installs the rest it can without admin rights and drafts an ask-IT text for the
  rest. No PowerShell script execution is needed.

## Tiers: pick what your machine allows
| Tier | What you get | How |
|---|---|---|
| 0. Skills only | The business skills on Claude web or desktop; or agents and skills in Claude Code without hooks, when policy allows only managed hooks | Upload the skills from `plugins/workbench-biz/skills/` (`docs/howto/25-package-a-skill-for-the-web.md`), or install as in tier 1: the installer warns that hooks will not run until IT enables them |
| 1. Kit | Instructions, settings profile, plugins, guards and the knowledge base; no network, no admin | `install.py --apply` |
| 2. Kit + machine setup | Tier 1 plus the capability report, user-scope packages, the knowledge index over your libraries and model routing for your organisation's allowed models | `install.py --apply --setup auto` (the paste prompt below) |
| 3. Tier 2 + WSL | A sandboxed Linux shell for unfamiliar code; one UAC prompt and one reboot | Same command; setup does it when WSL is allowed, otherwise it drafts the ask |

## The Day-1 paste prompt (paste this into Claude Code)
The release page fills in `<ZIP-URL>`, `<SHA256>`, `<TGZ-URL>` and `<SHA256-TGZ>` (the hashes are computed when the
release is tagged). `<EXTRAS>` is a comma-separated list of opt-ins (for example `tokensave,pm-pack,capture,nightly,ctx`)
or empty; `<GIT-HOSTS>` is your organisation's git hosts, comma-separated, or empty. The prompt drives
`docs/SETUP-RUNBOOK.md`, which gives the session the exact command, check, denial step and ask for every component.

> Set up claude-workbench `v0.3.4` on this machine, end to end, following `docs\SETUP-RUNBOOK.md` from the release. This
> message is my authorisation for every step in it; do not stop to ask me except where step 11 says.
> 1. Download `<ZIP-URL>` over HTTPS, without credentials, into a new empty temp folder. Check its SHA-256 with
>    `(Get-FileHash <file> -Algorithm SHA256).Hash`. If it is not `<SHA256>`, stop and tell me. Unpack it with
>    `Expand-Archive`, then read `IMPORT.md` and `docs\SETUP-RUNBOOK.md`.
> 2. Find Python: `py -3 --version`. If it fails, is older than 3.10, or resolves to the Microsoft Store stub, install
>    Python 3.13 for my user only: `winget install -e --id Python.Python.3.13 --scope user --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity`.
>    Then write down the FULL path of the interpreter (for example
>    `%LOCALAPPDATA%\Programs\Python\Python313\python.exe`) and use that full path, called PY below, for every later
>    step. If winget is missing or blocked, stop and give me the "ask IT" line.
> 3. Install and plan. From the unpacked folder run
>    `PY bootstrap\install.py --apply --setup plan --with <EXTRAS> --git-hosts <GIT-HOSTS>` (drop an option whose value is
>    empty). Keep the default corporate profile; never pass `--profile permissive` (that is my decision, after I have read
>    the report). It installs the kit, prints the capability report and writes the setup plan, and installs nothing else.
>    Show me the capability report summary it printed, in full, then the plan table
>    (`%USERPROFILE%\.claude\workbench\state\plan.md`). Do not add this repository as a git remote or register it as a
>    marketplace from the network.
> 4. Apply the plan. SETUP below means `PY %USERPROFILE%\.claude\workbench\kit\bootstrap\setup.py`. Run
>    `SETUP run --detach --no-update --with <EXTRAS>` (the same `--with` as in step 3), then follow it with
>    `SETUP status --json --wait 120`, repeated until `running` is false. Tell me each new phase in one line. Exit code 5
>    means a reboot is needed (step 11).
> 5. Update. Run `SETUP update --check` and show me its table; then `SETUP update`. Never add `--with update-latest`
>    unless I ask. Tools in use (git, PowerShell, Node.js, Claude Code) stay `deferred`: show me each command, never close my
>    programs and never run `claude update` yourself.
> 6. Onboarding is not part of the run: interview me by following
>    `%USERPROFILE%\.claude\workbench\kit\plugins\workbench-core\skills\onboard\SKILL.md` (write USER.md with its script).
> 7. Check. Run `SETUP doctor --deep --json`. Exit 0 with warnings is acceptable; exit 2 means a FAIL: show me the row's
>    detail word for word and do not fix it by hand. Read `state\knowledge-verify.json` and tell me any step that is not PASS.
> 8. Asks. For `exit_code` 3, for every `ask_it` in `SETUP status --json`, and for every check that carries one, show me the
>    ask text (the runbook, section 5, says where each lives). I send them; you never do.
> 9. Finish with three things. First, a table with one row per component (columns: component, command run, result, evidence,
>    pending ask) as in the runbook, section 3. Second, the capability report diff (`state\capability-diff.md`, before vs
>    after). Third, the runbook's section 4, "what we can and cannot do here" (capabilities, blocked items, pending asks),
>    filled in from the report, then the "first 10 minutes" from IMPORT.md, and tell me to restart Claude Code so the plugins
>    load and to run the guard test.
> 10. Hard stop rule: if any hook, permission prompt, gateway, proxy or policy DENIES something, stop that step and show me
>    the denial verbatim. Never retry it another way, with another tool, shell or route, and never elevate.
> 11. Stop only for: a hash mismatch; a denial (step 10); a Windows UAC prompt (tell me to click it; never elevate anything
>    yourself); a reboot (tell me to save my work and restart; after I sign in a console window resumes setup; I then
>    restart Claude Code and type `/workbench-core:setup resume`).

**Profile.** The prompt keeps the default `corporate` profile: normal permission prompts. `--profile permissive` (no
permission prompts, broad allow rules) is the option for a machine you fully control. The guard pack that limits pushes to
your approved git hosts is on under both profiles. The decision is yours, after you have read the capability report and
`docs/howto/08-permission-modes-and-prompts.md`; the session must not choose it. To change it later, run the installer again
with the other profile (`--force` replaces keys you already set).

Linux/WSL: `<TGZ-URL>`, `sha256sum` must equal `<SHA256-TGZ>`, `tar -xzf`, `python3 bootstrap/install.py --apply --setup auto`;
setup there runs the report, plan, venv and knowledge build and prints system-package commands as asks (no sudo).

If your `CLAUDE_CONFIG_DIR` is set, the paths in steps 3 to 7 start there instead of `%USERPROFILE%\.claude`.

## Manual steps, Windows (PowerShell or Command Prompt)
```powershell
Invoke-WebRequest "<ZIP-URL>" -OutFile "$env:TEMP\cw.zip"
(Get-FileHash "$env:TEMP\cw.zip" -Algorithm SHA256).Hash    # must equal <SHA256>
Expand-Archive "$env:TEMP\cw.zip" -DestinationPath "$env:TEMP\cw"
cd (Get-ChildItem "$env:TEMP\cw" -Directory | Select-Object -First 1).FullName
py -3 bootstrap\install.py                       # dry run: prints the plan, changes nothing
py -3 bootstrap\install.py --apply --setup auto  # after you've read the plan (drop --setup auto for tier 1; --setup plan stops after the plan)
```

## Manual steps, Linux or WSL
```bash
curl -fsSL "<TGZ-URL>" -o /tmp/cw.tgz
sha256sum /tmp/cw.tgz                      # must equal <SHA256-TGZ>
mkdir -p /tmp/cw && tar -xzf /tmp/cw.tgz -C /tmp/cw --strip-components=1
cd /tmp/cw
python3 bootstrap/install.py               # dry run
python3 bootstrap/install.py --apply --setup auto
```
WSL has its own Claude Code configuration, separate from Windows. Install in each place you use.

Paths below use tokens: `<WB>` is the `workbench` folder inside your Claude configuration folder (`%USERPROFILE%\.claude`
unless `CLAUDE_CONFIG_DIR` is set), `<KIT>` is its `kit` folder (the installed copy of this release), `<DATA>` is your
data folder and `<HOME>` your user profile.

## What the capability report shows
Right after the import, the installer runs `bootstrap/report.py run --phase pre`. It changes nothing on the machine.
It writes a Markdown file, a JSON file and one offline HTML page under `<WB>/state/`, and prints a short summary:
- the hardware, and the security settings that affect the kit (managed Claude settings, endpoint protection, app
  control, the proxy and TLS inspection, WSL and package policy, data-loss and labelling agents);
- every kit feature as READY, INSTALLABLE, NEEDS-IT, BLOCKED-BY-POLICY or UNKNOWN, with the evidence behind it and, for
  each NEEDS-IT or BLOCKED-BY-POLICY row, a ready ask-IT text;
- a short developer-speed test with a verdict (fast, OK or slow), the likely cause and a fix. When you are signed in,
  it includes one tiny prompt ("Reply with OK") through your own Claude login to time the model API; add
  `--no-model-call` to skip it.

`--quick` runs in under 20 seconds with no network. `claude doctor` runs only with `--with-doctor`, because it rewrites
Claude Code's own config files. After setup, `--phase post` also writes `capability-diff.md` (before and after).
Guide `docs/howto/02-read-the-capability-report.md` walks through it.

## What the installer and setup do
- **Installer (no network, no admin):** copies the kit to `<KIT>` so the download can be deleted; registers that
  folder as a local plugin marketplace and installs `workbench-core`, `workbench-kb`, `workbench-biz` and, with
  `--with capture`, `workbench-capture`; adds one `@import` line to your user `CLAUDE.md`; installs the statusline;
  merges a settings profile into your user settings; seeds the knowledge base. It never overwrites a key you already
  set unless you pass `--force`, and it backs up every file it changes.
- **Setup (in the background):** report, plan (with an ask-IT text per blocked item), user-scope packages from winget
  and the Playwright CLI from npm (one UAC prompt only where a package needs it and you are allowed), WSL, a version check
  per package, an update phase that moves only the tools setup installed to the versions tested for this release (a tool
  in use, Claude Code included, is left with the command to run), the knowledge layer (its own Python environment, then
  one index over your work libraries, captured files and the how-to library; the first build is memory-capped), the
  `find` MCP server, the StopFailure relay hooks when Claude Code is new enough, the Day-1 knowledge checks D1 to D23,
  the capture runtime when asked for, model routing for the models your organisation allows, and the report diff.
  Setup registers `<KIT>/docs/howto` as the search root `howto`. It stops only for a UAC prompt, a reboot or a policy
  block. The onboarding interview is yours to start afterwards (`/workbench-core:onboard`).

### Installer options
| Option | Effect |
|---|---|
| `--apply` | Make the changes (without it, nothing is written) |
| `--setup auto` | After `--apply`: the capability report, then setup in the background. `--setup plan` stops after the plan (`setup.py plan`) |
| `--with LIST` | Opt-ins, comma-separated: `tokensave` (code graph), `pm-pack` (product-management skills), `upstream-skills` (pinned upstream skills), `capture` (the capture plugin and its runtime), `nightly` (a nightly index refresh task), `claude-winget` (Claude Code from winget), `claude-autoupdate` (sets the variable that lets a winget-installed Claude Code upgrade itself), `ctx` (local search over your own coding-agent history), `update-latest` (the update phase moves tools to the newest version, not the tested one) |
| `--no-nightly` | Permissive profile: no nightly refresh task (on the corporate profile it is off unless `--with nightly`) |
| `--no-update` | Passed on to setup: skip its update phase |
| `--profile corporate` | Default. Normal permission prompts, documented defaults |
| `--profile permissive` | No permission prompts (Claude Code's bypass mode) and broad allow rules. Your organisation can disable bypass mode in managed settings; if it has, Claude Code won't enter it. Also applies `--upstream-plugins` |
| `--upstream-plugins` | Registers recommended upstream plugin marketplaces (auto-update off) |
| `--upstream-plugins-optional` | Also registers the optional set; see `settings/SETTINGS.md` |
| `--data-root PATH` | Your data folder (`<DATA>`): default the work OneDrive's `Workbench` folder when exactly one verified work OneDrive exists, else `Workbench` in your profile |
| `--kb-root PATH` | Where your knowledge base lives (default `<DATA>/kb`; an upgrade keeps the previous one) |
| `--git-hosts host1,host2` | Git hosts the corporate guard pack lets you push to. Until set, a push to another host asks you first (refused at the strict guard level) |
| `--guard minimal\|standard\|strict` | Guard level. `standard` (default): a push or upload to an unlisted host and `--no-verify` ask instead of being refused, and plain browser navigation runs without a prompt; `strict` refuses them; `minimal` refuses nothing and asks only before irreversible, outward, credential and guard-control steps. Kept across upgrades; `settings/SETTINGS.md` lists what each level does |
| `--approvals ask\|off` | Corporate profile: `off` runs ordinary commands without a prompt (new windows start in bypass mode; the kit's own ask rules are lifted, deny rules and the guard stay). Kept across upgrades |
| `--force` | Overwrite keys you already set |
| `--no-cli` | Don't call the `claude` CLI; print the plugin commands for you to run instead |
| `--uninstall` | Undo everything the installer and setup recorded, newest first (dry run unless `--apply`) |
| `--purge-backups` | With `--uninstall`: also delete `<WB>/backups/` once the uninstall succeeded |

### Setup commands (`<KIT>/bootstrap/setup.py`)
| Command | Effect |
|---|---|
| `plan [--with LIST]` | Write the plan (`plan.md`, `plan.json`, `workbench.winget`); installs nothing |
| `run [--detach] [--with LIST] [--no-nightly] [--no-update]` | The whole setup; always `--detach` from a session |
| `status --json [--wait N]` | The state object; `--wait` returns early on a phase change |
| `verify` | Version-probe every package |
| `update [--check] [--json] [--with update-latest]` | Move the tools setup installed to the tested versions; `--check` changes nothing. Writes `update.json` and `update.md` |
| `routing` | Rewrite the model routing table for the models your organisation allows |
| `resume` | Continue after the WSL reboot (a RunOnce entry runs it once at sign-in) |
| `doctor [--deep] [--json] [--bundle OUT.zip]` | Health check, exit 0 ok, 1 warnings, 2 errors. `--deep` also runs the Day-1 knowledge checks D1 to D23 (written to `knowledge-verify.json`) and exits 2 only when a row is a FAIL, never for a warning. It fails on a config folder, index or git repository inside OneDrive, work data in a personal OneDrive, or guards that have not run for three sessions. `--bundle` writes a redacted support zip |
| `backup [--out ZIP]` | KB notes and curated config into `<DATA>/backup/` |
| `restore ZIP [--to DIR] [--apply] [--force] [--restore-settings]` | Hashes and paths are checked first; settings files (whose hooks run code) only with `--restore-settings` |
| `undo-config [--apply]` | Undo the machine changes setup recorded (user env vars, Path entries, the scheduled task, the RunOnce value, the Playwright CLI, the StopFailure relay hooks, the `find` MCP registration) |

Setup exit codes: 0 done, 2 usage or already running, 3 done with ask-IT items, 4 a step failed, 5 waiting on a human
(a reboot). Separate profiles per client or project:
`bootstrap/profile.py create|list|launch|remove NAME [--kb DIR] [--purge-kb]` (guide `docs/howto/07-client-profiles.md`).

## Check that it worked
1. `/status`: look at *Setting sources* and *Organization*. Managed settings, if any, are listed.
2. `/plugin`, `/agents`, `/skills`, `/hooks`: the workbench items appear.
3. `py -3 <KIT>/bootstrap/setup.py doctor --deep` exits 0 (warnings are allowed; `<WB>/state/knowledge-verify.json` lists D1 to D23).
4. Guard test: in a scratch git repo, ask Claude to run `git push --force origin main`. It must be
   blocked with a message. Hooks fail open silently when misconfigured, so this test is the only
   proof they run.
5. The statusline shows model, effort, context use and cache state.
6. Knowledge base: ask Claude to search the knowledge base for any word; it returns hits or says
   the knowledge base is empty.

## The first 10 minutes
Restart Claude Code, then try three tasks:
1. **Find something you own.** "Find the latest version of <a document you know> and summarise it with the file path."
   The `find` skill searches the index over your libraries and cites the original file. The first build may still be
   running; `find`'s status says how far it is.
2. **Turn notes into actions.** Paste the notes of a recent meeting and ask for the decisions and action items. The
   `meeting-to-actions` skill answers with a table and flags items without an owner.
3. **Prove the guards run.** The guard test above: ask Claude to force-push `main` in a scratch repository.

What not to do in the first week:
- Don't run Claude Code as administrator, and don't switch to the permissive profile on a managed laptop without
  approval.
- Don't add a whole tenant or every synced library to `find`, and don't start capture or mail ingest before you have
  told your security team (`docs/admin-asks.md`).
- Don't enable MCP servers you don't need, and never paste a password, key or one-time code into a prompt.
- Don't retry a blocked action another way; follow the hard stop rule and ask IT with the text the report gives you.
- Don't edit files under `<KIT>`: the next release replaces them. Your own changes go in your user folder.

## After install
1. **Fill in your work profile:** `/workbench-core:onboard` asks a few questions and writes `<WB>/USER.md`. You can
   also edit that file by hand.
2. **Upstream skills** (humanizer for drafts, playwright-cli for browser checks) are pinned and hash-checked:
   `--with upstream-skills`, or by hand:
   `py -3 <KIT>/tools/fetch-upstream/fetch_upstream.py` (dry run) and again with `--apply`; with `--pm` it fetches
   the product-management pack instead (same as `--with pm-pack`). Add `--optional` for the design set only after your
   organisation approves it (`THIRD-PARTY.md`). Use `python3` instead of `py -3` on Linux and WSL.
3. **Skills are invoked by their plugin name:** `/workbench-core:<skill>`, `/workbench-kb:save`,
   `/workbench-biz:<skill>` and `/workbench-capture:<skill>`. Claude also uses them unasked when a task fits, except
   the user-invoked ones (`setup`, `cleanup`, `pc-checkup`, `vdi-drive`, `capture`, `ingest`).
4. **How-to guides** for common tasks: `docs/howto/README.md`. When something fails: `docs/troubleshooting.md`.

## Updating
The kit updates only when you ask. On a machine that already has this kit, say **"check the new stuff and go"** (or "update the kit",
"check for kit updates") to Claude Code. The `kit-update` skill (`plugins/workbench-core/skills/kit-update/SKILL.md`) runs ONE script,
`py -3 <KIT>/bootstrap/kit_update.py`, in short stages (each call is bounded; when it says "Run the same command again", Claude runs
the same command again, with an explicit 10-minute timeout, until it prints the table):
1. asks GitHub for the latest release of this kit (anonymous HTTPS, no credentials) and compares it with the installed version;
2. when a newer one is out, downloads its zip, checks the SHA-256 the release publishes before and after the download (a mismatch
   stops everything, nothing is installed), unpacks it to a fresh folder under `<WB>/state/kit-update/` and runs that release's
   `install.py --apply`, then `setup.py run --detach` with the profile and opt-ins your last setup remembered
   (`<WB>/state/setup-state.json` and `<WB>/config.json`; nothing new is turned on);
3. waits for the background setup, which also applies the parts only your own user may change (the plugin Python option, `<WB>\bin` on
   your Path, and, when the whole skill listing is over 80% of the 30,000-character default limit, your own skills listed by name only;
   see `py -3 <KIT>/bootstrap/setup.py skills --dry-run` and guide `docs/howto/53-audit-and-clean-up.md`), then runs `setup.py doctor
   --deep` as a background job of its own, writes `<WB>/state/post-update-verify.json` and prints one table with the line **Restart every
   Claude Code window, then type: go**;
4. after the restart, the first message you type (any message, "go" is enough) starts the pending verify: every check as
   PASS, WARN, FAIL or NEEDS-IT in one table (plugin Python options, hook errors in the newest debug log, whether the guard fired in a
   session that started after the update, the guard's denies and asks since then as counts per rule, the Path, the `doctor --deep` rows, the skill listing against its limit, failures logged since
   the update), the live guard test in a scratch repository, your IT asks once, and a box **FOR THE KIT AUTHOR** with only the kit's own
   defects: an id, the command, the first three error lines, the kit and Claude Code versions. User, computer, domain and company names,
   unknown hosts and credentials are scrubbed from the box and from the report saved as `<WB>/state/field-report.md`.
If the kit is already current it says so and runs the verify. It never elevates, never changes policy or managed settings and never
runs `claude update`. Where the releases live: the repository the kit remembers (`kit_repo` in `<WB>/config.json`), else the environment
variable `WB_KIT_REPO`, else `plugins/workbench-core/skills/kit-update/release-source.json` (empty on purpose). The first time, name the
repository in your message (`--repo OWNER/REPO`); it is remembered, and naming another repository later needs `--new-repo` and asks you
first. That first choice is trusted as given, and the SHA-256 comes from the same release: it shows the download is intact, not who
published it (release signing is deferred).

### Paste this to say "check the new stuff and go" on a kit without the skill
A kit older than 0.3.2 (no `kit-update` skill) does the same by hand. Paste this into Claude Code. `<REPO>` is the OWNER/REPO of the
release page the kit came from: take it from my message (the release page fills it in), else from `kit_repo` in `<WB>\config.json`,
else ask me once. `<PY>` is the `python` in `<WB>\config.json` (the installer wrote it).

> Update claude-workbench on this machine and check it, end to end. This message is my authorisation for every step below; do not
> stop to ask me except where step 9 says. `<WB>` is `%USERPROFILE%\.claude\workbench` (or under `CLAUDE_CONFIG_DIR`), `<KIT>` is
> `<WB>\kit`. Give every command below an explicit timeout of 10 minutes.
> 1. Latest release: `curl.exe -fsSL -H "Accept: application/vnd.github+json" https://api.github.com/repos/<REPO>/releases/latest`.
>    Read `tag_name` and the asset named `claude-workbench-<tag_name>.zip` (its `browser_download_url`, its `digest`, and the checksum
>    table in `body`). The installed version is the `VERSION = "..."` line of `<KIT>\bootstrap\install.py`. Not newer: tell me the
>    kit is current and stop (when `<KIT>\bootstrap\kit_update.py` exists, run its `verify` as in the last paragraph).
> 2. Download that URL (HTTPS only, no credentials) into a new empty temp folder with
>    `curl.exe --fail --location --silent --show-error --proto =https --proto-redir =https -o <file> <url>`. Its SHA-256
>    (`(Get-FileHash <file> -Algorithm SHA256).Hash`) must equal the SHA-256 the release publishes: the asset's `digest` (after
>    `sha256:`) or the value in the checksum table of `body`; either one is enough. Neither given, or two different values: delete the
>    file and stop, and tell me.
> 3. Unpack with `Expand-Archive` into a new folder. The kit is the nested folder `claude-workbench-v<ver>` (for example
>    `claude-workbench-v0.3.4`); call it `<unpacked>`. Its `bootstrap\install.py` must hold `VERSION = "<ver>"`, the `tag_name` without
>    the `v`; if not, delete everything and stop. Read `<unpacked>\IMPORT.md`, section "Updating": if it says more than this list,
>    follow that one.
> 4. Remember my choices; do not add or change any: `with`, `no_nightly` and `no_update` in `<WB>\state\setup-state.json`
>    (`options`), and `profile` in `<WB>\config.json`.
> 5. Install: `<PY> <unpacked>\bootstrap\install.py --apply --profile <profile> --with <with>` (drop `--with` when it is empty). Never
>    `--force`; never `--profile permissive` unless that is the remembered profile. Exit 3 is my organisation's policy: stop and show
>    me the message word for word.
> 6. Setup: `<PY> <KIT>\bootstrap\setup.py run --detach --with <with>` (plus `--no-nightly` / `--no-update` when remembered), then
>    `<PY> <KIT>\bootstrap\setup.py status --json --wait 60` until `running` is false; tell me each new phase in one line. `setup.py
>    run` ends with exit code 5 when a reboot is needed (`status --json` shows `reboot_pending`): tell me to save my work and restart;
>    setup resumes at sign-in.
> 7. `<PY> <KIT>\bootstrap\setup.py doctor --deep`. Show me every FAIL row word for word; do not fix a row by hand.
> 8. If something was installed, tell me exactly this and nothing else: "Restart every Claude Code window, then type: go." Setup has
>    written `<WB>\state\post-update-verify.json`, so the first session after the restart is told to run the verify.
> 9. Stop only for: a hash mismatch, a denial (show it, never retry another way, never elevate), a UAC prompt, a reboot, and step 8.
> After the restart, on my first message: run `<PY> <KIT>\bootstrap\kit_update.py --repo <REPO>` (it reports that the kit is current,
> remembers the repository and runs the verify; if it says "Run the same command again", run the same command again; if it refuses
> `--repo` because the kit remembers another repository, stop and show me, and do not add `--new-repo` yourself). Show me the table,
> then try `git push --force origin main` in a scratch git repository under the temp folder (its only remote is
> `https://example.invalid/scratch.git`): the workbench guard must block it. Record the result with
> `<PY> <KIT>\bootstrap\kit_update.py record guard-live PASS "<text>"` (or FAIL), delete the scratch repository, and show me the box FOR
> THE KIT AUTHOR as printed.

From 0.3.2 on, the same update is one sentence. Upgrading from 0.2.0: read the upgrade notes in `CHANGELOG.md` first (a renamed skill, a
renamed variable and an index that migrates by itself). The tools setup installed move between releases with `setup.py update --check`,
then `setup.py update`.

## Removing everything
1. `py -3 <KIT>/bootstrap/install.py --uninstall` (dry run), then again with `--apply`. It uninstalls the plugins, restores
   every backed-up file, removes what the installer added and undoes the machine changes setup recorded (user env
   vars, Path entries, the scheduled task, the RunOnce value, the Playwright CLI, the StopFailure relay hooks, the `find`
   MCP registration, the capture browser profile). Add `--purge-backups` to
   delete `<WB>/backups/` afterwards.
2. What stays, because it is yours: `<DATA>/` (the knowledge base, captured copies, backups), `<WB>/USER.md`, your
   profiles under `<HOME>/.claude-profiles/` (`bootstrap/profile.py remove NAME --purge-kb` removes one), and the
   packages setup installed (they are ordinary tools: remove them with `winget uninstall` if you no longer want them).
3. To delete indexed and captured data first, use guide `docs/howto/32-purge-indexed-or-captured-data.md`, then delete
   `<DATA>/` yourself. Leaving the company or under a legal hold: `docs/runbooks.md` first.

## What this kit never does
It never sends telemetry of its own, pushes to any remote, sends messages, edits managed settings, asks for or stores
credentials, or bypasses any site's or organisation's controls, and it updates only when you ask (the `kit-update` skill for the
kit; setup's update phase for the tools it installed). What does leave the machine, and why, is listed in `docs/security-overview.md`.
