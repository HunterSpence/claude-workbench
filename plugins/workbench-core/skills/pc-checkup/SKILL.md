---
name: pc-checkup
description: Read-only health check of this Windows PC - blue screens, crashes and freezes, hardware and disk errors, disk and battery wear, broken drivers, memory pressure, startup load - then a ranked list of problems and who should fix each. Run only when the user asks for it ("/workbench-core:pc-checkup", "check this computer", "why is my laptop crashing").
disable-model-invocation: true
---

# pc-checkup

Collect, diagnose, report. Change nothing unless the user says yes to a specific fix that is theirs
to make. This is a health check, not a security review: it does not inspect security software or
policy settings, and it never changes them.

## On a work (managed) laptop
- Never change anything IT manages: security tools, encryption, firewall, update settings, proxy,
  certificates, VPN, drivers or firmware that IT deploys, policy or registry policy keys.
- Do not run admin tools, do not ask the user to elevate, do not install utilities.
- The deliverable is a findings table the user can hand to their IT helpdesk.

## 1. Collect (read-only, about a minute)
```
powershell -NoProfile -File "${CLAUDE_SKILL_DIR}/scripts/collect.ps1"
```
If script execution is blocked by policy, say so and stop; do not change the execution policy or
work around it. Read the report it prints (`%USERPROFILE%\pc-checkup\report-*.txt`). Sections that
need admin rights say so. Use the event provider, ID and counts as evidence.

## 2. Diagnose
- **BSOD stop codes**: 0x116/0x117 graphics driver; 0x124 hardware (WHEA); 0x1A/0x50/0x3B RAM or a
  driver; 0x9F a driver's power state; 0xEF/0x7E system files or a driver. Repeated BSODs are top priority.
- **Kernel-Power 41 / 6008** with no BSOD: a hard freeze, power loss, or the power button held. Ask
  the user what happened before calling it a fault.
- **WHEA**: hardware (CPU, RAM, PCIe). Hardware support, not a software fix.
- **Disk**: errors, health not Healthy, uncorrected errors, wear over 70%: tell the user to make
  sure their work is synced or backed up now, then report it. **Ntfs 55**: file-system corruption.
  Free space under 10%: cleanup.
- **Display 4101, nvlddmkm, amdkmdag, LiveKernelEvent 141/117**: graphics driver hang.
- **Kernel-Processor-Power 37, many times**: heat or power-limit throttling: vents, hard surface,
  power plan, charger.
- **The same app crashing or freezing repeatedly**: update or repair that app; if many apps or the
  shell crash, system files may be damaged (an IT task).
- **Devices with an error code** (except 22 = disabled on purpose): missing or broken driver.
- **Pending reboot**: reboot first. It is the cheapest fix and often clears other errors.
- **Battery** health under 80% is worn, under 60% should be replaced.
- **Out of memory**: Resource-Exhaustion-Detector 2004 or "paging file too small": find the process
  that used the memory (busiest processes) rather than chasing drivers. Browsers, chat and mail
  clients, containers, WSL and local models are common causes.
- **Startup programs**: flag heavy or unknown user-level items; leave IT-deployed agents alone.

## 3. Report
One ranked table, worst first: `# | problem | evidence (count, newest date) | how serious | fix | who`.
`who` is one of **user can do it** · **IT helpdesk** · **needs hardware service** · **leave it**.
End with the two or three things to do today. Save it next to the raw report as
`findings-<date>.md`. The report holds device details: share it with IT only.

## 4. Fixes the user may approve (one at a time, each after an explicit yes)
Only things a standard user owns: reboot; closing or uninstalling apps the user installed (if
allowed); clearing the user's own temp folder; moving large personal files to the synced work
folder; disabling user-level startup items the user names; installing updates already offered in
Settings. After each fix, re-check its evidence and say what changed.

**Never**: firmware or BIOS flashes; anything touching security or policy settings; registry
cleaners, "driver updaters", "PC boosters" or other utilities; deleting the user's files; anything
that needs admin rights on a managed device. Those go to IT.
