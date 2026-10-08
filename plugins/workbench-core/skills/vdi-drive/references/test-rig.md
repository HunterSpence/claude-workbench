# Test rig: a disposable remote desktop you own

Use it to measure the harness without touching anyone's real desktop. Run it on a machine you
control (a local Docker host or WSL2 with Docker), never on shared or production infrastructure,
and only if your organisation allows running containers there.

## Image choice (verify before trusting)
- **`consol/debian-xfce-vnc`**: recommended. One `docker run`, TigerVNC plus noVNC. noVNC really
  draws the framebuffer into an HTML5 `<canvas>` over a WebSocket, the same shape as a remote
  desktop web client (keydown, encode, socket, remote, repaint).
- **`linuxserver/webtop`**: do not use as a stand-in. Its current base streams WebRTC video rather
  than drawing into a canvas, so it has a different loss profile.
- **Guacamole + xrdp**: closest architecturally (real RDP, canvas compositing) but three containers.
  Worth it only if VNC results look surprising.

noVNC's canvas may carry no id and no class: query the bare `canvas` element and check its size.

## Standing it up
Bind to the IPv4 loopback address only (write it in place of `<loopback>` below). Never publish the port to a
network.
```bash
docker run -d --name vnc-target --cap-add=NET_ADMIN \
  -p <loopback>:6901:6901 -e VNC_PW='<random>' consol/debian-xfce-vnc

# a text sink inside the session (the container runs as uid 1000, so write under /tmp)
docker exec -d vnc-target env DISPLAY=:1 xterm -geometry 200x50+0+0 \
  -e bash -c 'while IFS= read -r l; do printf "%s\n" "$l" >> /tmp/trials.txt; done'
```
If Docker runs on another machine you own, reach it through an SSH tunnel
(`ssh -N -L 6901:localhost:6901 <user>@<rig-host>`), then open
`http://localhost:6901/vnc.html?password=<pw>&autoconnect=1`.

## Ground truth
Read what the remote side received from its **filesystem**, never from the screen:
`docker exec vnc-target cat /tmp/trials.txt`. A line-buffered `read` loop appends on every Enter,
so the file can be read mid-run. Use random strings with no repeated neighbours, so a dropped key
and a doubled key give different diffs, and score with the longest common subsequence rather
than a length comparison. `scripts/rttsweep.mjs` does all of this.

## Simulating a degraded link
Apply `tc` **inside the container's network namespace only**, never on the host interface.
```bash
docker exec -u 0 vnc-target bash -c 'apt-get update -qq && apt-get install -y -qq iproute2'
docker exec -u 0 vnc-target tc qdisc add dev eth0 root netem delay <ms>ms <jitter>ms loss <percent>%
tc qdisc show            # on the host: confirm the host qdisc is untouched
```

Pick delay, jitter and loss values that resemble the worst link you expect to work over.

## What to expect
On a TCP-based protocol, expect delay rather than character loss; the sweep tells you for your own
link. Tear the rig down afterwards: container, image, tunnel.
