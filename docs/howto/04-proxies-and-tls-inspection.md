# Work behind a proxy that re-signs HTTPS

Automates it: `py -3 <KIT>/bootstrap/probe.py --only tls,network --json`

## When to use
The browser works but Node, Python, pip, git or curl fail with "unable to get local issuer certificate",
"self-signed certificate in chain" or "certificate verify failed". Your network inspects encrypted traffic.
`<KIT>` is the kit folder (guide 01).

## Steps
1. Measure first. This is read-only and takes at most 45 seconds of network checks:
   `py -3 <KIT>/bootstrap/setup.py doctor`
   The "TLS + network" row names each runtime that fails. The raw data is `py -3 <KIT>/bootstrap/probe.py --only tls,network --json`:
   look at `runtimes[].ok` and `hosts[].inspected`.
2. Native Windows: Claude Code trusts the Windows certificate store, so it works once your organisation's root
   certificate is installed (it is on a managed laptop). When the probe sees inspection, `py -3 <KIT>/bootstrap/setup.py run --detach` sets the user variables `NODE_USE_SYSTEM_CA=1` and
   `UV_SYSTEM_CERTS=true` and tells git to use `schannel`.
3. Inside WSL, Linux has its own store (guide 05). Get the proxy's root certificate (PEM, public part) from IT using the
   proxy text in `docs/admin-asks.md`, copy it to `/usr/local/share/ca-certificates/` with a `.crt` name, run
   `sudo update-ca-certificates`, then set `NODE_EXTRA_CA_CERTS` to that file. Python tools may also need
   `REQUESTS_CA_BUNDLE` or `pip config set global.cert <file>`.
4. If the proxy mishandles compressed request bodies, set `CLAUDE_CODE_GZIP_REQUEST_BODIES=0`.

## Verify
- `py -3 <KIT>/bootstrap/setup.py doctor` shows "TLS + network" as OK.
- The tool that failed now runs its normal command (for example `pip download` of a small package, or `git ls-remote`
  on your git host).

## Common failures
- **HTTP 407 on a host:** the proxy wants sign-in; the probe reports it as `proxy-auth`, not blocked. Ask IT how
  command-line tools should authenticate.
- **Tempted to turn verification off** (`NODE_TLS_REJECT_UNAUTHORIZED=0`, `GIT_SSL_NO_VERIFY`, `curl -k`, `pip --trusted-host`):
  never. It defeats the proxy and the guard denies it. Install the certificate instead.
- **Works in PowerShell, fails in WSL:** the certificate was added to Windows only. Repeat step 3 in the distribution.
- **IT will not share the certificate:** ask which route they support, and use only that.
