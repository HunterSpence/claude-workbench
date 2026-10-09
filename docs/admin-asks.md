# Admin asks: what to tell your security team and what to ask IT

Ready-to-send texts for the moments when the kit cannot proceed alone. They are drafts: **you** send them, the kit never
does. Fill the `<...>` placeholders, delete what does not apply, and keep the answer you get; setup reads your managed
settings again later and tells you what changed.

Rules for every ask:
- Ask for the smallest thing that unlocks the step, and name the exact setting, folder or host.
- Offer the alternative that needs no change ("or we skip this feature").
- Never ask for, and never accept, a workaround that disables a control. A denial is a decision; when one blocks a step the
  kit stops and reports it, then continues with the work that is not blocked.
- The capability report prints the matching text beside every row that is NEEDS-IT or BLOCKED-BY-POLICY.

## 1. Heads-up to your security team (send before the first run)

> **Subject:** Heads-up: an open-source kit that sets up Claude Code on my managed laptop
>
> Hi <security contact>,
>
> Before I run it, I want you to know about a setup kit I plan to use with the Claude Code seat <org> provides to me. It
> is open source (MIT licence), needs no administrator rights, never edits managed settings and never tries to elevate.
> This is everything it reads, writes and schedules.
>
> **Reads (read-only; nothing is changed):** the Windows version and edition, CPU, memory and disk type; whether the
> machine is domain or cloud joined; proxy settings and whether HTTPS is re-signed; the policy keys that govern Claude
> Code, the browser, WSL and the antivirus (read, never written); which developer tools are installed; and whether the
> hosts it needs (the model API, the git host, package sources) answer. The results go to a report in my own profile.
>
> **Writes (my user account only):** files under my Claude configuration folder (the kit copy, backups, state and logs);
> an import line in my user instruction file and merged keys in my user settings (never a key a managed source sets);
> user-level environment variables for certificate trust and text encoding; my user PATH, for the kit's own bin folder;
> a one-shot "resume after restart" value under my user's RunOnce key, removed once it has run; and tools installed
> through winget or the Microsoft Store, PyPI or npm in per-user scope where the vendor offers it.
>
> **Scheduled task:** one per-user task (no elevation) that refreshes a local search index of documents I choose. It is
> optional and off unless I enable it.
>
> **Network:** downloads from the official sources only (winget and the Store, PyPI, npm, the vendors' own release
> pages), paced to stay light on the shared link; model calls to the Claude endpoint <org> approved. Nothing else leaves
> the machine. No telemetry is switched on by the kit.
>
> **Data:** indexed documents and notes stay on this laptop or in <org>'s own work cloud. Files carrying a sensitivity
> label are skipped by default. Anything copied into the work cloud falls under <org>'s retention, data-loss-prevention
> and discovery policies. If I ever enable mail or meeting digests, the summaries run through my own approved Claude
> login, and external participants' speech appears in meeting transcripts.
>
> **Removal:** one command restores every file it changed and removes what it added; a second command purges the index.
>
> If any item conflicts with a policy, tell me which and I will skip that part.
>
> Thanks, <name>

## 2. One ask per policy-change class

Setup saves a snapshot of which kinds of managed policy apply and compares it at every session start. When a class
changes it names it ("policy changed: hooks locked"); this is the text for each. The kit never edits or works around a
managed setting, so each ask is a request for a decision, with a no-change alternative.

### Hooks locked (managed settings allow only managed hooks)
> **Subject:** Request: allow the guard and session hooks of an open-source Claude Code plugin
>
> Hi <IT contact>, user and plugin hooks are currently blocked on my laptop (a managed-hooks-only setting such as
> `allowManagedHooksOnly`). The plugin I would like to use ships a small set of Python hooks: a command guard that denies
> or asks before risky shell commands, a session-start notice, a statusline and a credential check on the files I write.
> They run locally, read stdin, write only to my profile and make no network calls. I can send the scripts for review.
> Could you either (a) allow this plugin's hooks, or (b) tell me that hooks stay blocked? If (b), I will run without them
> and rely on permission prompts only. Thanks, <name>

### Marketplaces closed (only approved plugin sources may be added)
> **Subject:** Request: a route to install a reviewed Claude Code plugin
>
> Hi <IT contact>, plugin marketplaces are restricted on my laptop (for example a strict known-marketplaces setting). I
> would like to install one open-source plugin set, reviewed by <security contact> if you wish. Could you either (a) add
> our internal mirror <internal plugin repo> to the allowed sources, or (b) install the reviewed copy centrally, or (c) tell
> me which approved source to use? Without one of these I will not install it. Thanks, <name>

### Models restricted (an allow-list limits which models can be used)
> **Subject:** Question: which Claude models and effort levels are approved for me?
>
> Hi <IT contact>, my Claude Code seat is limited to an allow-list of models. To route work sensibly I need the exact
> list for my account and the provider route (<provider>), and whether an effort cap applies. The kit steps down to the
> next allowed model on its own and will never try a blocked one. If a larger or smaller model than the ones listed would
> help for specific work (long reviews, bulk extraction), I can send the use case. Thanks, <name>

### MCP restricted (only approved MCP servers may run)
> **Subject:** Request: approve a named set of read-only MCP servers
>
> Hi <IT contact>, MCP servers are limited to a managed list on my laptop. I would like <server names> added for my
> account, each pinned to an exact version, read-only where the server supports it, started from <approved source>. For
> each I can send what it reads, which host it contacts and where its data goes. If this is not possible I will use
> command-line tools instead. Thanks, <name>

### Permissions locked (managed rules fix what may run without a prompt)
> **Subject:** Question: can read-only commands run without a prompt?
>
> Hi <IT contact>, managed permission rules apply to my Claude Code sessions (including a block on the no-prompt mode). I
> will keep every prompt for writes, publishing and anything outward. Would you allow a short list of read-only commands
> to run without a prompt (listing files, `git status`, `git diff`, `git log`, reading logs)? If not, I will keep the
> defaults and accept the prompts. Thanks, <name>

## 3. Other common asks

### The proxy re-signs HTTPS and a runtime rejects it
> Hi <IT contact>, Node, Python, pip and git on my laptop fail TLS verification behind the proxy, while the browser works.
> Could you send me the organisation's root certificate (public part only) and its recommended install location? I will
> point each tool at it; I will not turn verification off. Thanks, <name>

### Browser automation for the capture plugin (only if you use it)
> Hi <IT contact>, I would like to use a read-only capture tool that opens intranet pages in a dedicated Microsoft Edge
> profile on my laptop: GET requests only, hosts from a scope list I keep, paced like a person, and it stops on any
> sign-in, consent or policy page. It needs the Edge policy `RemoteDebuggingAllowed` left enabled for my user (it is on
> unless a policy turns it off). `HeadlessModeEnabled` can stay off; the tool then runs in a visible window. Could you
> confirm this is allowed, or tell me which policy forbids it? Thanks, <name>

### Headless Edge for the command-line browser tool (only if you use it)
> Hi <IT contact>, I use a command-line browser tool (the Playwright CLI, installed for my user only) that drives the
> Microsoft Edge already on my laptop, on pages I open myself, with no browser download. It needs the Edge policy
> `RemoteDebuggingAllowed` left enabled for my user and, so that checks run without a window in the way,
> `HeadlessModeEnabled` allowed. Could you confirm both are allowed, or tell me which policy forbids them? If headless
> stays off, the tool opens a visible window instead. Thanks, <name>

### Developer features: WSL2, virtualization, long paths
> Hi <IT contact>, could you enable (or confirm I may enable) Windows Subsystem for Linux with WSL2, the virtualization
> setting it needs, and long-path support in the operating system? I need them to run unfamiliar code in a sandboxed
> Linux environment and to check out deep source trees. Thanks, <name>

### Virtual desktop: session limits, profile size, nested virtualization (only if you work on one)
> Hi <IT contact>, I run my development work, including Claude Code, inside <a managed virtual desktop>. To plan long-running
> sessions, please tell me: (a) whether my desktop is in a personal or a pooled host pool, or is a dedicated Cloud PC; (b)
> the idle-session limit, the disconnected-session limit and the scaling-plan action (deallocate, hibernate or sign out)
> that apply to it; (c) whether my profile follows me between session hosts, and the maximum size of my profile container,
> because the tools I use keep a few gigabytes under my profile; (d) whether the desktop's virtual machine size supports
> nested virtualization, which WSL2 needs; (e) the firewall's TCP idle timeout for outbound connections. If a value is
> fixed I will plan around it; I am not asking to switch any limit off. Thanks, <name>

### PowerShell language mode and script policy
> Hi <IT contact>, could you confirm whether PowerShell on my laptop runs in Full Language mode for my user, and whether
> group policy enforces a script execution policy (Restricted or AllSigned)? Claude Code's PowerShell tool and a few local
> scripts of the kit need Full Language mode and scripts that may run. If Constrained Language mode is required, I will use
> WSL or Git Bash for those steps instead. Thanks, <name>

### Package sources
> Hi <IT contact>, which sources may I install developer tools from (winget, the Store, an internal mirror for PyPI and
> npm)? If a mirror exists, please send its URL and any credentials process. Thanks, <name>

### Git host and sign-in
> Hi <IT contact>, please confirm the enterprise git host <host>, how I authorise a command-line token for single sign-on,
> and which repositories are internal versus private. Thanks, <name>

### Antivirus exclusion for a build folder (only if builds are unusably slow)
> Hi <IT contact>, builds in <folder> take <n> times longer with real-time scanning. Could you add a path exclusion for
> that folder for my device, or suggest a faster approved location (a Dev Drive)? I will not change antivirus settings
> myself. Thanks, <name>

### Usage limits on a Team or Enterprise seat
> **Subject:** Question: my Claude seat tier and usage credits
>
> Hi <IT contact>, my Claude Code sessions sometimes stop at the five-hour or weekly usage limit of my seat, and long
> parallel runs reach it first. Could you tell me (a) which seat tier I hold, standard or premium, (b) whether usage
> credits are enabled for our organisation, and (c) what spend limit applies to me or to my group? If credits stay off, I
> will plan my work around the usage windows. Thanks, <name>

## 4. Meeting transcripts and mail

Needed only if you choose the optional digests of meetings and mail. The setup probes each gate read-only and prints the
matching ask. Send only the asks the report flags.

The capability report prints this text beside the row `capture-meeting-transcripts`; send it as it stands, or pick the
numbered asks below that apply to you:

> Please (1) enable Graph API access to meeting transcripts for my account (Teams meeting configuration setting EnableGraphTranscriptAccess), (2) approve a read-only connector or tenant app with Calendars.Read, OnlineMeetings.Read and OnlineMeetingTranscript.Read.All for my own meetings, (3) confirm whether attendees may download transcripts from the meeting Recap, and (4) if I hold a Microsoft 365 Copilot licence, also the delegated permission OnlineMeetingAiInsight.Read.All for meeting AI insights (admin consent). Purpose: a local, on-device meeting-notes index. To see the tenant setting: Get-CsTeamsMeetingConfiguration | Select EnableGraphTranscriptAccess, EnableAttributedTranscripts

1. **Teams admin:** turn on transcript access through the Graph API (in PowerShell,
   `Set-CsTeamsMeetingConfiguration -Identity Global -EnableGraphTranscriptAccess $true`, or the Teams admin centre,
   Meetings, Meeting settings, Transcript API access, Microsoft Graph access). Microsoft documents the default: "By default,
   Microsoft Graph access is off, so agents and apps can't access meeting transcripts, regardless of app-level permissions."
   Without it the transcript routes return a forbidden status. To see the current value of the switch and of speaker
   attribution before anyone changes them: `Get-CsTeamsMeetingConfiguration | Select EnableGraphTranscriptAccess, EnableAttributedTranscripts`
2. **Identity admin, either:** (a) tenant consent for the Microsoft 365 connector including the online-meeting scopes, or
   (b) a tenant-registered, read-only public-client app assigned to me only, with delegated `User.Read`,
   `offline_access`, `Calendars.Read`, `OnlineMeetings.Read`, `OnlineMeetingTranscript.Read.All` (its delegated form
   needs administrator consent) and `Mail.Read` (or `Mail.ReadBasic` for a catalogue only), redirect `http://localhost`.
   And, if I hold a Microsoft 365 Copilot licence, also the delegated permission OnlineMeetingAiInsight.Read.All for meeting AI insights (admin consent).
   The kit's ingest reads transcripts only and never calls the insights route; the permission is asked for in the same
   round so that IT is not asked twice.
3. **Licensing:** do I hold a Microsoft 365 Copilot licence (Microsoft: "All users of applications that use this API must
   have a Microsoft 365 Copilot license."), and are preview features allowed for me?
4. **Meeting policy:** is transcription allowed for me as organiser; may attendees download transcripts for meetings I
   attend; is there a copy restriction default I must respect? An administrator can also make transcripts view-only in
   the browser, in which case the fallback below is closed too.
5. **Outlook:** is classic Outlook staying on this image and for how long; what is the object-model guard policy; may a
   local, read-only script read my own cached mailbox?
6. **Security team:** sign-off for an own-access local index on this managed laptop (never a personal cloud), the audit
   volume to expect from a mailbox backfill, and how labelled or encrypted items are handled.
7. **Claude data route:** confirm my seat may process my own mail and meeting transcripts, including external
   participants' speech, and what retention or zero-retention terms apply.
8. **Only if the community Microsoft 365 MCP server in the kit's catalogue is enabled:** a security review of the pinned
   version in bring-your-own-app mode, or approval of the kit's own read-only Graph client instead.

Never press "request approval" in a consent dialog on someone's behalf: it notifies administrators. The kit asks you to
decide.

**If the answer is no, or nothing yet:** the fallback needs no change from IT. Download the transcript from the meeting
Recap, if you are allowed to, and save it in the drop folder (guide 41, route 1). If the Recap only lets you view it, do
not extract it another way. Microsoft documents that an administrator can leave users "browser-only access to play the
meeting recordings or view transcripts with no ability to download or sync files".
