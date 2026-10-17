# Run Claude Code on a virtual desktop

Automates it: none (this guide only reads; the changes it names are IT's)

## When to use
You reach a managed Windows desktop in the cloud (Azure Virtual Desktop, or a Windows 365 Cloud PC) and want Claude Code and
the kit to run inside it, or a session there ends by itself, loses files, cannot start WSL2 or drops a connection. Everything
stated as a fact below is quoted from Microsoft Learn (read in October 2026); where Microsoft says nothing, this guide tells
you to ask IT instead of guessing. `<CH>` is `CLAUDE_CONFIG_DIR`, else `~/.claude`; `<WB>` is its `workbench` folder; `<KIT>`
is the installed kit (guide 01).

## Steps
1. **Find out which desktop you have.** Ask IT if you are not sure. Microsoft defines the two Azure Virtual Desktop host pool
   types: "Personal, where each session host is assigned to an individual user" and "Pooled, where user sessions can be load
   balanced to any session host in the host pool". A Windows 365 Enterprise Cloud PC is like the first: "end users have a 1:1
   relationship with their Cloud PC". On a pooled desktop your next sign-in can land on a different session host, so treat
   nothing outside your profile and your data folder as kept.
2. **Know where the kit keeps its state.** Under your user profile unless you chose another data root: `<CH>` (Claude Code's
   own configuration), `<WB>` (the kit copy, `<WB>/state/`, the ledger, backups, the knowledge environment `<WB>/venv/`),
   `%LOCALAPPDATA%` (`<LAD>`: the search index in `<LAD>/doc-index/knowledge/` and the embedding model cache in
   `<LAD>/doc-index/models/`), `<DATA>/` (knowledge base, captured copies, backup zips) and `<SRC>/` (git repositories).
   Where a profile container is used, Microsoft says: "A profile container is all the data related to a user's profile,
   which is directly stored in the VHD(x)", and "Nearly all the files and folders found under this location would be
   included" in it. So these folders roam with you and count against its size. The container's size setting "Specifies the
   maximum size of the user's container in megabytes" (default 30000), and "You can increase this value at any time, but
   can't decrease it." The Python environment, the model cache and the index are the big parts.
   - Ask IT whether your profile follows you between session hosts, and the container's maximum size (ask in `docs/admin-asks.md`,
     "Virtual desktop").
   - If space is short, IT can exclude folders: a `redirections.xml` file "provides functionality that allows some parts of a
     user's profile to be excluded from a user's container." Only rebuildable folders qualify: `<WB>/cache/` and
     `<LAD>/wb-review/` cost nothing to lose; the index and the model cache cost a rebuild and a download every session.
     Never `<CH>`, `<WB>/state/`, `<WB>/kb-state/`, `<DATA>/` or `<KB>/`.
   - Concurrent sign-ins: "All sessions trying to use the VHD concurrently should have a matching ProfileType setting for the
     best experience." If you use two desktops at once, ask IT how that is set.
   - The kit refuses a `<CH>` inside OneDrive and the doctor fails a knowledge index or a git repository there; a redirected
     Documents folder does not change that.
3. **Learn the session limits before a long run.** An idle limit counts time without keyboard or mouse: a session "can be
   idle (without user input) before the session is automatically disconnected or ended", and a Claude Code task that runs for
   an hour with nobody typing is idle to the desktop. The limits are Windows policies under "Session Time Limits"
   ("Idle session limit", "Set time limit for disconnected sessions"). Windows 365 documents defaults for Flex Cloud PCs: in
   Shared mode "The Cloud PC is idle for 15 minutes (default value)." and "The user session remains disconnected for over 30
   minutes (default value)."; in Dedicated mode "The Cloud PC is idle for 30 minutes (default value)." Other desktops have
   whatever IT set.
   - A disconnect is not a sign-out: "When a session is in a disconnected state, running programs are kept active even though
     the user is no longer actively connected." (an archived Windows Server page). The disconnected-session limit then ends it:
     "When a Windows 365 Flex Cloud PC is disconnected for this period of time, the user is automatically signed out from the
     Cloud PC." For host pools, "You can configure a time limit policy that signs out all disconnected users once a set time is
     reached". A signed-out session takes everything running in it along, Claude Code included.
   - Scaling plans act on the whole machine. For a personal host pool, after a disconnect or sign-out lasting between 0 and 360
     minutes, "The options are to either deallocate (shut down) the VMs, hibernate the personal desktop, or do nothing." For a
     pooled one, ramp-down "signs out those users after the specified wait time is over". Ask IT which applies to you.
   - Keep work resumable: commit or save before you step away, and let `/workbench-kb:save` journal the session (guide 10).
     Microsoft warns IT against a short disconnect limit for the same reason: "A low time limit can cause users' sessions to end
     if their network loses connection for too long, resulting in lost work."
4. **WSL2 needs nested virtualization.** Microsoft: "You need to make sure that the virtual machine has nested virtualization
   enabled." On Windows 365 Enterprise it is documented as "4vCPU or higher Cloud PC (Downsizing to 2vCPU Cloud PCs will disable
   nested virtualization)." and "GPU Cloud PCs don't support nested virtualization."; Windows Subsystem for Linux is on its list
   of supported workloads. For Azure Virtual Desktop the documentation says of a nested workload: "Your session hosts need to
   use a virtual machine (VM) size that supports nested virtualization" (the VM series' own page lists it). Check what the kit
   sees: `py -3 <KIT>/bootstrap/report.py run --phase refresh --quick`, then read the rows `wsl2` and `sandbox` in
   `<WB>/state/capability-refresh.md`. If they say NEEDS-IT, send "Developer features: WSL2, virtualization, long paths" and the
   nested-virtualization point of "Virtual desktop" from `docs/admin-asks.md`. Without WSL2 the kit still sets up everything
   else; only the sandboxed Linux shell (the `sandbox` row) stays unavailable (guide 05).
5. **Do not rely on a quiet connection.** If your desktop's traffic leaves through Azure Firewall: "Azure Firewall TCP Idle
   Timeout is four minutes." Microsoft adds: "If a period of inactivity is longer than the timeout value, there's no guarantee
   that the TCP or HTTP session is maintained." and "A common practice is to use a TCP keep-alive." The setting "isn't user
   configurable"; "you can contact Azure Support to increase the Idle Timeout for inbound and outbound connections up to 15
   minutes", which only IT can do. So prefer commands and tools that send keep-alives at an interval under four minutes, and
   split a long silent command into steps that print progress. A connection that sat idle ends with a reset: "Azure Firewall
   gracefully terminates the connection by sending a TCP RST packet."
6. **Office automation belongs to the session that runs Office.** Microsoft: the Outlook object model is "designed to run in a
   logged-on user's session in which a user can respond to dialog boxes", and it is unsuitable for "applications that run
   together with the AT Scheduler or Task Scheduler services". So run Claude Code, and the classic-Outlook route of guide 41
   (`ING mail probe`), inside the same desktop session as Outlook, not on the laptop that only displays it; and never expect
   a scheduled task, including the kit's nightly refresh, to read Outlook. On a shared host Office must be installed with
   shared computer activation: "you have to use the Office Deployment Tool and enable shared computer activation to do the
   installation." The new Outlook has no object model; use the Graph route (guide 41).
7. **Install the kit inside the desktop** as on any managed laptop (guide 01 or `docs/SETUP-RUNBOOK.md`), then keep a backup
   you have restored once (guide 13): `py -3 <KIT>/bootstrap/setup.py backup` writes a zip to `<DATA>/backup/`; keep a copy
   off the desktop.

## Verify
- `py -3 <KIT>/bootstrap/setup.py doctor --deep` exits 0, and the placement row reads OK.
- `wsl --status` exits 0, or the `wsl2` row names what is missing and carries the ask.
- Disconnect test: close the remote window without signing out, wait a minute, reconnect. Claude Code is still running in
  the session unless a limit ended it; if it did not survive, you now know to ask IT for the values in step 3.
- You hold IT's answers to the "Virtual desktop" ask: pool type, the idle and disconnect limits, the scaling-plan action, the
  profile size, nested virtualization and the firewall timeout.

## Common failures
- **The session was gone after lunch:** an idle or disconnected-session limit signed it out, or a scaling plan shut the
  machine down (step 3). Get the values and save before you leave.
- **Yesterday's files or settings are missing:** a pooled desktop sent you to another session host and no profile container
  carries your profile (step 1 and 2). Restore from your backup (guide 13) and ask IT.
- **Sign-in is slow, or the profile is full:** the container reached its maximum size (step 2). Only IT can raise it.
- **`wsl --install` fails or the `wsl2` row says NEEDS-IT:** the virtual machine lacks nested virtualization (step 4).
- **A request resets after a quiet period:** the four-minute firewall timeout (step 5); guide 43 covers Claude Code's own
  network errors.
- **An Outlook read from a scheduled task finds nothing:** automation belongs to the logged-on session (step 6).
- **Tempted to switch a limit off yourself:** do not. Send the ask; a refusal is the answer (guide 03).

## Sources
Microsoft Learn pages, read in October 2026: Azure Virtual Desktop terminology; Autoscale scaling plans for Azure Virtual
Desktop; Start VM on Connect FAQ; Set session time limits for Windows 365 Flex Cloud PCs; the archived Windows Server page on
timeout and reconnection settings; Windows 365 overview; Set up virtualization-based workloads on your Windows 365 Cloud PC; FAQ
about Windows Subsystem for Linux; Publish applications with RemoteApp in Azure Virtual Desktop; the profile-container pages
(container types, the `redirections.xml` tutorial, the configuration settings reference); Azure Firewall FAQ; The Outlook Object
Model is unsuitable to run in a Windows service; the Microsoft 365 Apps deployment page for shared session hosts.
