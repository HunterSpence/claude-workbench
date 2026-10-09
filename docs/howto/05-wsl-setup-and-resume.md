# Set up WSL2 and resume after the reboot

Automates it: /workbench-core:setup

## When to use
You want a Linux environment on the managed laptop to run unfamiliar code in a sandbox, or setup reached its WSL
step and is waiting for a restart. `<KIT>` is the kit folder (guide 01).

## Steps
1. Ask first when needed. If the report shows `wsl2` as NEEDS-IT or BLOCKED-BY-POLICY, send the "Developer features"
   text from `docs/admin-asks.md` and stop here until IT answers.
2. Run setup as in guide 01. For WSL it runs `wsl --install --no-distribution`, which shows one UAC prompt: you click it.
3. If a restart is needed, setup records a one-shot "resume" value, writes phase `reboot-wait` and exit code 5, and
   prints the command to run by hand. Restart Windows and sign in; setup resumes by itself. By hand:
   `py -3 <KIT>/bootstrap/setup.py resume`
4. Setup then installs the pinned Ubuntu 24.04 distribution. Open a terminal and run `wsl -d Ubuntu-24.04` once to create
   your Linux user. That step is yours.
5. If you have no `.wslconfig`, setup writes one that caps memory at 6 GB, swap at 4 GB and 4 processors. Change it,
   then apply with `wsl --shutdown`.
6. WSL has its own Claude Code configuration. Inside the distribution, install the kit again:
   `python3 bootstrap/install.py` (dry run), then `--apply`.
7. Keep repositories in the Linux filesystem (`~/src/...`), not under `/mnt/c`: crossing the two is much slower.

## Verify
- `wsl -l -v` lists `Ubuntu-24.04` with version 2.
- `py -3 <KIT>/bootstrap/setup.py status --json` shows `"reboot_pending": false` and, at the end, phase `done`.
- Inside WSL, `python3 --version` prints a version and the kit's guard test from guide 01 is blocked.

## Common failures
- **Nothing happens after the restart:** run the `resume` command above; the automatic value only fires at sign-in.
- **UAC declined or a policy denial:** setup stops and records an ask-IT item. It does not retry another way.
- **WSL is slow or eats memory:** lower `memory=` in `.wslconfig`, then `wsl --shutdown`.
- **Downloads fail inside WSL with certificate errors:** add the proxy certificate in the distribution (guide 04).
- **A VPN breaks DNS inside WSL:** tell IT which VPN you use and ask for their supported DNS setting.
