# Set up Claude Code and the kit on your first day

Automates it: /workbench-core:setup

## When to use
You have a managed laptop with Claude Code and want the kit installed and the machine checked, once. `<CH>` is
`CLAUDE_CONFIG_DIR`, else `~/.claude`. `<KIT>` is the unpacked release folder before the install and `<CH>/workbench/kit`
after it.

## Steps
1. Download the tagged release, check its SHA-256 against the release page, unpack it (`IMPORT.md` has the commands).
2. From the unpacked folder, dry run (changes nothing) and read the plan: `py -3 bootstrap/install.py`
3. Apply it: `py -3 bootstrap/install.py --apply`
4. Start Claude Code and run `/workbench-core:setup`. It shows the capability report, installs in the background and
   polls. By hand, the same three steps are:
   ```
   py -3 <KIT>/bootstrap/setup.py report run --phase pre
   py -3 <KIT>/bootstrap/setup.py run --detach
   py -3 <KIT>/bootstrap/setup.py status --json --wait 60
   ```
   Repeat the last command until `"running"` is false. Setup stops only for a UAC prompt (you click), a reboot
   (guide 05) or an item IT must allow (guide 03).
5. Run `/workbench-core:onboard` to fill in your work profile.

## Verify
- `py -3 <KIT>/bootstrap/setup.py status --json` shows phase `done` and `exit_code` 0 (3 means done, with ask-IT items).
- `py -3 <KIT>/bootstrap/setup.py doctor` exits 0 (1 warnings, 2 errors).
- In Claude Code: `/status` lists any managed settings source; `/plugin`, `/agents`, `/skills` and `/hooks` show the kit.
- Rule check: in a scratch git repo ask Claude to run `git push --force origin main`. Claude Code must stop and ask you;
  answer no. The doctor row `hooks heartbeat` turns OK once a session has started.

## Common failures
- **"Microsoft Store Python", exit 2:** install Python from python.org, winget or your organisation's software
  catalogue, then run the installer again.
- **"STOP", exit 3:** your organisation's policy blocked a step. Quote the message and use guide 03. Do not retry another way.
- **Setup exit 5:** waiting for a reboot. Restart and sign in; it resumes by itself (guide 05).
- **Installer refuses your config folder:** `CLAUDE_CONFIG_DIR` is inside OneDrive. Move it out.
- **No `/workbench-core:setup` in the list:** the plugin did not install. Ask for the marketplace route in
  `docs/admin-asks.md`, or re-run with `--no-cli` and run the plugin commands it prints.
