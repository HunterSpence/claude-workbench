# Triage commands

Read-only unless marked. Replace `<unit>`, `<name>`, `<port>`, `<path>`, `<domain>`.

## systemd
```bash
systemctl status <unit> --no-pager -l          # state, main PID, last log lines
systemctl is-enabled <unit>; systemctl is-active <unit>
journalctl -u <unit> -n 200 --no-pager          # last 200 lines
journalctl -u <unit> --since "15 min ago" --no-pager
journalctl -u <unit> -p warning --no-pager      # warnings and worse
systemctl cat <unit>                            # the unit file actually in use, with drop-ins
systemctl show <unit> -p User -p WorkingDirectory -p Environment -p ExecStart -p Restart
systemd-analyze verify /etc/systemd/system/<unit>.service
```

## PM2 and containers
```bash
pm2 status; pm2 describe <name>                 # restarts, uptime, cwd, env file
pm2 logs <name> --lines 200 --nostream
docker ps -a --format '{{.Names}}\t{{.Status}}'
docker logs --tail 200 <container>
docker inspect --format '{{.State.ExitCode}} {{.State.OOMKilled}}' <container>
```

## Ports and connectivity
```bash
ss -ltnp                                        # listening sockets and owning process
ss -tnp state established '( sport = :<port> )'
curl -sS -o /dev/null -w '%{http_code} %{time_total}s\n' http://localhost:<port>/health
```

## Resources
```bash
df -h; df -i                                    # space and inodes
free -h; uptime
journalctl -k --since "1 hour ago" | grep -i -E 'oom|killed process'
du -xh --max-depth=1 /var/log | sort -h | tail
```

## Permissions
```bash
namei -l <path>                                 # every directory on the way, with owner and mode
stat <path>
id <service-user>
sudo -u <service-user> test -r <path> && echo readable
ausearch -m avc -ts recent 2>/dev/null | tail   # SELinux denials, if SELinux is on
```

## Nginx
```bash
nginx -t                                        # syntax check; does not reload
nginx -T | less                                 # full merged config
tail -n 100 /var/log/nginx/error.log
```
Change (after approval): `nginx -t && systemctl reload nginx`.

## DNS and TLS
```bash
dig +short <domain>
dig +short <domain> @<public-resolver>          # bypass the local resolver
getent hosts <domain>                           # what this host resolves
curl -svI https://<domain>/ 2>&1 | grep -E 'subject:|expire date:|issuer:|HTTP/'
openssl s_client -connect <domain>:443 -servername <domain> </dev/null 2>/dev/null | openssl x509 -noout -dates -subject
```
