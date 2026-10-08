# Importing claude-workbench

This page is written for two readers: you, and the Claude Code session you ask to do the import.
The import is a one-time, pinned copy of a tagged release. Nothing auto-updates, no git remote to
this repository is configured, and no credentials are used.

## Before you start
- **Check your organisation's policy** on installing third-party or open-source tooling, and get
  whatever approval it requires. Many organisations want a security review of anything that runs
  as a hook, because hooks execute code on every tool call.
- **Managed settings always win.** The installer never edits them and refuses to write any key a
  managed source already sets. If your organisation blocks plugins or user hooks, stop and ask
  your IT team; don't look for a way around it.
- You need Claude Code and Python 3.10+ (`py -3 --version` on Windows, `python3 --version` on
  Linux). Git and Node.js are optional. No admin rights are needed, and no PowerShell script
  execution is needed.

## The one-paragraph version (paste this into Claude Code)
> Import claude-workbench release `<TAG>` from `<RELEASE-ARCHIVE-URL>`. Download the archive over
> HTTPS without credentials. Verify its SHA-256 equals `<SHA256>`; stop if it doesn't. Unpack it
> to a temporary folder. Read `IMPORT.md`. Run `py -3 bootstrap/install.py` (on Linux:
> `python3 bootstrap/install.py`) with no other arguments, which is a dry run, and show me the
> full plan. Wait for my OK before running it again with `--apply`. Do not add this repository as
> a git remote, and do not register it as a plugin marketplace from the network.

The release page lists `<TAG>`, the archive URL and its SHA-256.

## Manual steps, Windows (PowerShell or Command Prompt)
```powershell
Invoke-WebRequest "<RELEASE-ARCHIVE-URL>" -OutFile "$env:TEMP\cw.zip"
(Get-FileHash "$env:TEMP\cw.zip" -Algorithm SHA256).Hash    # must equal <SHA256>
Expand-Archive "$env:TEMP\cw.zip" -DestinationPath "$env:TEMP\cw"
cd (Get-ChildItem "$env:TEMP\cw" -Directory | Select-Object -First 1).FullName
py -3 bootstrap\install.py                 # dry run: prints the plan, changes nothing
py -3 bootstrap\install.py --apply         # after you've read the plan
```

## Manual steps, Linux or WSL
```bash
curl -fsSL "<RELEASE-ARCHIVE-URL-TAR.GZ>" -o /tmp/cw.tgz
sha256sum /tmp/cw.tgz                      # must equal <SHA256-TAR>
mkdir -p /tmp/cw && tar -xzf /tmp/cw.tgz -C /tmp/cw --strip-components=1
cd /tmp/cw
python3 bootstrap/install.py               # dry run
python3 bootstrap/install.py --apply
```
WSL has its own Claude Code configuration, separate from Windows. Install in each place you use.

## What the installer does
- Copies the kit to a stable folder inside your Claude configuration (`<config>/workbench/kit/`),
  so the unpacked download can be deleted afterwards.
- Registers that folder as a local plugin marketplace and installs `workbench-core` (agents,
  skills, hooks) and `workbench-kb` (knowledge-base tools and the `save` skill).
- Adds one `@import` line to your user `CLAUDE.md` for the instruction layer, installs the
  statusline, and merges a settings profile into your user settings. It never overwrites a key
  you already set unless you pass `--force`, and it backs up every file it changes.

### Options
| Option | Effect |
|---|---|
| `--apply` | Make the changes (without it, nothing is written) |
| `--profile corporate` | Default. Normal permission prompts, documented defaults |
| `--profile permissive` | No permission prompts (Claude Code's bypass mode) and broad allow rules. Your organisation can disable bypass mode in its managed settings; if it has, Claude Code won't enter it. Also applies `--upstream-plugins` |
| `--upstream-plugins` | Registers recommended upstream plugin marketplaces (auto-update off) |
| `--upstream-plugins-optional` | Also registers the optional set; see `settings/SETTINGS.md` |
| `--kb-root PATH` | Where your knowledge base lives |
| `--git-hosts host1,host2` | Git hosts the corporate guard pack lets you push to. Until set, pushes are refused |
| `--force` | Overwrite keys you already set |
| `--no-cli` | Don't call the `claude` CLI; print the plugin commands for you to run instead |
| `--uninstall` | Restore every backed-up file and remove what the installer added |
| `--purge-backups` | With `--uninstall`: also delete `<workbench>/backups` once the uninstall succeeded |

## Check that it worked
1. `/status`: look at *Setting sources* and *Organization*. Managed settings, if any, are listed.
2. `/plugin`, `/agents`, `/skills`, `/hooks`: the workbench items appear.
3. `claude doctor`: no new errors.
4. Guard test: in a scratch git repo, ask Claude to run `git push --force origin main`. It must be
   blocked with a message. Hooks fail open silently when misconfigured, so this test is the only
   proof they run.
5. The statusline shows model, effort and context use.
6. Knowledge base: ask Claude to search the knowledge base for any word; it returns hits or says
   the knowledge base is empty.

## After install
1. **Fill in your work profile:** run `/workbench-core:onboard` in Claude Code. It asks a few
   questions and writes `<config>/workbench/USER.md` (who you are at work, where the rules live,
   how you write). You can also edit that file by hand.
2. **Recommended upstream skills** (humanizer for drafts, playwright-cli for browser checks), pinned
   and hash-checked:
   ```
   py -3 <config>/workbench/kit/tools/fetch-upstream/fetch_upstream.py            # dry run: the plan
   py -3 <config>/workbench/kit/tools/fetch-upstream/fetch_upstream.py --apply    # install them
   ```
   Use `python3` instead of `py -3` on Linux and WSL. Add `--optional` for the design set only after your organisation approves it (`THIRD-PARTY.md`).
   The playwright-cli skill also needs its CLI: `npm install -g @playwright/cli@<version>` (the
   version is in `THIRD-PARTY.md`).
3. **Skills are invoked by their plugin name:** `/workbench-core:<skill>` (for example
   `/workbench-core:repo-fix`), and `/workbench-kb:save` for the knowledge base. Claude also uses
   them unasked when a task fits.

## Optional extras
- Python packages for the document-search and Office skills: each skill lists its
  `requirements.txt`; install with `py -3 -m pip install --user -r <file>` or your
  organisation's package mirror.
- Node packages for `ui-build` and `vdi-drive`: `npm install --ignore-scripts` in a copy of the
  skill's `scripts/` folder, as its SKILL.md shows. They drive the Edge or Chrome already installed,
  so no Playwright browser download is needed.
- Other upstream skills and plugins this kit recommends but does not include: see `THIRD-PARTY.md`.
  Each has its own licence; some need approval.

## Updating and removing
- **Update:** download a newer tag, verify it, and run its installer the same way.
- **Remove:** `py -3 bootstrap/install.py --uninstall --apply` restores every backed-up file and
  removes what the installer added.

## What this kit never does
It never phones home, auto-updates, pushes to any remote, sends messages, edits managed settings,
asks for or stores credentials, or bypasses any site's or organisation's controls.
