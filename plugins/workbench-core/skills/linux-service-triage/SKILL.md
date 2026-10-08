---
name: linux-service-triage
description: Diagnose a failing Linux service from evidence - systemd or PM2 status and logs, ports, permissions, disk and memory, Nginx reverse proxy, DNS and TLS - and propose the minimal fix with verification and rollback. Use when a server app, container or site is down, erroring, slow or unreachable, before ad-hoc debugging.
---

# Linux service triage

Read-only by default. Gather evidence, classify, then propose. Run anything that changes state
(restart, chmod, config edit, reload) only after the user approves that exact command, and only on
hosts they are allowed to change.

## 1. Scope
- Host (and how you reach it), service name (systemd unit, PM2 process, container), the symptom
  verbatim, and when it started.
- Can you run commands, or only read output the user pastes? Do you have sudo? Say which.
- WSL2 is not a server: systemd may be off (`ps -p 1 -o comm=` shows `init` instead of `systemd`),
  ports are forwarded through Windows, and DNS and proxy come from the Windows side or the VPN.

## 2. Evidence, cheapest first
Use `references/triage-commands.md`. In order:
1. Service state and the last 200 log lines (`systemctl status`, `journalctl -u`, `pm2 logs`,
   `docker logs --tail 200`).
2. Is anything listening where expected? (`ss -ltnp`)
3. Resource pressure: disk full, inodes, memory, OOM kills (`df -h`, `df -i`, `free -h`,
   `journalctl -k | grep -i oom`).
4. Permissions on every path the service touches, as the service's user (`namei -l`, `sudo -u`).
5. The network path for web services: app port -> proxy -> DNS -> TLS.

## 3. Classify
| Class | Typical evidence |
|---|---|
| Config error | parse error in logs, `nginx -t` fails, unit `ExecStart` wrong |
| Missing dependency | `ModuleNotFoundError`, `command not found`, missing env var, unreachable DB |
| Permission denied | `EACCES`, `Permission denied`, wrong owner after deploy, SELinux/AppArmor denial |
| Port conflict | `EADDRINUSE`, another PID in `ss -ltnp` |
| Upstream unreachable | 502/504 from the proxy, `connect() failed` in the proxy error log |
| Resource exhaustion | disk 100%, inode 100%, OOM killer lines, restart loop |
| DNS or TLS | name resolves elsewhere, expired or mismatched certificate |
| Environment drift | works by hand, fails under systemd: different user, cwd, PATH or env |

Hangs only under systemd usually mean environment, not code. Death exactly at a timeout with low
CPU usually means blocked on I/O, a lock or a prompt.

## 4. Report
```text
TRIAGE REPORT
- Symptom:
- Evidence (command -> output line):
- Most likely cause (and what was ruled out):
- Fix plan (minimal steps):
- Exact commands (only after approval):
- Verification (what proves it worked):
- Rollback:
```

## Safety
- Validate before reload: `nginx -t`, `systemd-analyze verify <unit>`, `docker compose config`.
- Back up a file before editing it (`cp -a file file.bak-$(date +%F)`), and remove the backup
  once verified so it does not shadow the live file.
- Never `chmod -R 777`, never disable SELinux/AppArmor or a firewall as a "fix", never kill
  processes you did not identify.
- Production or shared hosts: follow your team's change process; deploy code through its pipeline,
  not by building on the box.
- Stop and ask when logs are missing, privileges are unclear, or certificate management is involved
  and you do not know how it is set up.
