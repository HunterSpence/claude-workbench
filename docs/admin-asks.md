# Admin asks: what to ask IT

Ready-to-send texts for the moments when the kit cannot proceed alone. Fill the `<...>` placeholders, delete what does not apply, and keep the answer you get; setup reads your managed
settings again later and tells you what changed.

Rules for every ask:
- Ask for the smallest thing that unlocks the step, and name the exact setting, folder or host.
- Offer the alternative that needs no change ("or we skip this feature").
- When a denial blocks a step the kit stops and reports it, then continues with the work that is not blocked.
- The capability report prints the matching text beside every row that is NEEDS-IT or BLOCKED-BY-POLICY.

## 1. One ask per policy-change class

Setup saves a snapshot of which kinds of managed policy apply and compares it at every session start. When a class
changes it names it ("policy changed: hooks locked"); this is the text for each, with a no-change alternative.

### Hooks locked (managed settings allow only managed hooks)
> **Subject:** Request: allow the session hooks of an open-source Claude Code plugin
>
> Hi <IT contact>, user and plugin hooks are currently blocked on my laptop (a managed-hooks-only setting such as
> `allowManagedHooksOnly`). The plugin I would like to use ships a small set of Python hooks: a session-start notice, a
> statusline, a check that stops oversized file reads and a credential check on the files I write.
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
> Hi <IT contact>, managed permission rules apply to my Claude Code sessions (including a block on the no-prompt mode).
> Would you allow a short list of read-only commands
> to run without a prompt (listing files, `git status`, `git diff`, `git log`, reading logs)? If not, I will keep the
> defaults and accept the prompts. Thanks, <name>

## 2. Other common asks

### The proxy re-signs HTTPS and a runtime rejects it
> Hi <IT contact>, Node, Python, pip and git on my laptop fail TLS verification behind the proxy, while the browser works.
> Could you send me the organisation's root certificate (public part only) and its recommended install location? I will
> point each tool at it. Thanks, <name>

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
> that folder for my device, or suggest a faster location (a Dev Drive)? Thanks, <name>

### Usage limits on a Team or Enterprise seat
> **Subject:** Question: my Claude seat tier and usage credits
>
> Hi <IT contact>, my Claude Code sessions sometimes stop at the five-hour or weekly usage limit of my seat, and long
> parallel runs reach it first. Could you tell me (a) which seat tier I hold, standard or premium, (b) whether usage
> credits are enabled for our organisation, and (c) what spend limit applies to me or to my group? If credits stay off, I
> will plan my work around the usage windows. Thanks, <name>

## 3. Meeting transcripts and mail

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
5. **Outlook:** is classic Outlook staying on this image and for how long; what is the programmatic-access policy for Outlook's object model; may a
   local, read-only script read my own cached mailbox?
Never press "request approval" in a consent dialog on someone's behalf: it notifies administrators.

**If the answer is no, or nothing yet:** the fallback needs no change from IT. Download the transcript from the meeting
Recap, if you are allowed to, and save it in the drop folder (guide 41, route 1). Microsoft documents that an administrator can leave users "browser-only access to play the
meeting recordings or view transcripts with no ability to download or sync files".
