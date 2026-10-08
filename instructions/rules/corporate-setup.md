# Corporate setup reference (read on demand; not imported)

The rules live in `corporate-environment.md`. This file holds the how-to steps.

## WSL2 limits
On a 16 GB machine, cap WSL in `%UserProfile%\.wslconfig`, then apply it with `wsl --shutdown`:
```ini
[wsl2]
memory=6GB
swap=4GB

[experimental]
autoMemoryReclaim=gradual
sparseVhd=true
```
If Intune manages WSL settings, its values win. Keep repos inside the Linux filesystem
(`~/src/...`), not under `/mnt/c`: working across the two filesystems is much slower. WSL has its
own Claude Code configuration, so install the kit there separately.

## TLS-inspecting proxy
- **Native Windows:** Claude Code trusts the Windows certificate store by default, so it works once
  IT's root certificate is installed, which it is on a managed machine.
- **Inside WSL:** Linux has its own store. Get the proxy's root certificate (PEM) from IT, add it to
  the distribution's store (Debian/Ubuntu: copy it to `/usr/local/share/ca-certificates/` as
  `.crt`, then `sudo update-ca-certificates`), and set `NODE_EXTRA_CA_CERTS` to that file for
  Claude Code and other Node tools. Python tools that bundle their own CA list may also need
  `REQUESTS_CA_BUNDLE` or `pip config set global.cert <file>`.
- If the proxy mishandles compressed request bodies, set `CLAUDE_CODE_GZIP_REQUEST_BODIES=0`.

## GitHub Enterprise sign-in
`gh auth login --hostname <your-host>` (for example `<tenant>.ghe.com` or `github.example.com`).
Use the organisation's SSO and credential manager. Never sign a personal GitHub account or a
personal token into `gh` or git on this machine.

## Day-1 checks
1. `/status`: the account and organisation are your organisation's, and `Setting sources` names any
   managed source.
2. `/usage`: the plan and its limits are the ones you expect.
3. `claude doctor`: no errors.
4. The guard test in `{{WORKBENCH_HOME}}/kit/IMPORT.md` is blocked with a message (hooks fail open
   silently, so this is the only proof they run).
