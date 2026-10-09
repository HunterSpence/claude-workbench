# Unlock meeting transcripts and mail

Automates it: /workbench-capture:ingest

## When to use
You want your meetings and your mail searchable and summarised, so you can ask "what did we decide about the rollout?" or
"find the email thread about the budget" and get a cited answer. There are four routes; try them in the order below. All
are opt-in, experimental and read-only, and each needs the InfoSec acknowledgement first (step 9). `<KIT>` is the kit
folder (guide 01). Below, `ING` means your knowledge Python (`knowledge_python` in `<WB>/config.json`) running `ingest.py`
from `<KIT>/plugins/workbench-capture/skills/ingest/scripts/`. Install the add-on once with
`py -3 <KIT>/bootstrap/setup.py run --detach --with capture`, then `ING setup --apply`.

## Steps
Hard stop rule: any hook, permission, gateway or policy denial, and any exit code 3, means stop. Report `stop.reason` and
`stop.ask` from the run report word for word. Never retry another way, change an Outlook, registry or tenant setting, or click a prompt.

1. **Route 1, the drop folder (no IT change).** In Teams open the past meeting, go to its Recap and use Download on the
   transcript. Whether you may depends on the meeting's organiser and your organisation's policy (an administrator can leave
   users view-only in the browser); if you can only view it, do not extract it another way. Save
   the `.vtt` (better) or `.docx` into `<DATA>/captured/_drop/meetings/` and run `ING meetings run`. One file per meeting lands
   in `<DATA>/captured/meetings/`; originals move to `<WB>/capture/drop-done/`. The automated Recap download is deferred.
2. **Route 2, your own Graph app (needs IT).** After IT enables transcript access (ask 1) and approves a read-only app registered
   in your own tenant (ask 2): `ING config set graph_client_id <app id>`, `ING config set graph_tenant_id <tenant>`, then
   `ING meetings run --graph`. The first run prints a device code you enter yourself. With `Mail.Read` approved, the same app
   reads mail: `ING mail run --experimental --source graph`.
3. **Route 3, classic Outlook, read-only over the local cache.** `ING mail probe`, then
   `ING mail run --experimental --source com --folders "Inbox,Sent Items" --since <YYYY-MM-DD> --max-items 200`. It reads the
   cached window only, one file per conversation under `<DATA>/captured/outlook/`. The new Outlook keeps no cache; use route 2.
4. **Route 4, Outlook on the web for selected folders: deferred.** That web app reads mail with POST requests, and capture blocks
   every non-GET request. The Teams chat source is deferred for the same reason.
5. **The asks** (section 4 of `docs/admin-asks.md`, which also holds the whole text the capability report prints for the row
   `capture-meeting-transcripts`; send, yourself, only those the capability report flags; guide 03):
   (1) Teams admin: Graph access to transcripts. Microsoft documents that "By default, Microsoft Graph access is off, so agents
   and apps can't access meeting transcripts, regardless of app-level permissions", so an approved app alone opens nothing.
   (2) Identity admin: tenant consent, or a read-only app assigned to you with the delegated permission
   OnlineMeetingTranscript.Read.All, which in its delegated form needs administrator consent.
   (3) Licensing and preview limits. (4) Meeting policy: transcription, attendee download, copy restrictions. (5) Outlook: classic
   staying, the object-model guard policy, a local read-only script allowed. (6) Security team: sign-off for an own-access local
   index. (7) Claude data route: your seat may process mail and transcripts, including external participants' speech. (8) Only if
   the community Microsoft 365 MCP server is enabled (guide 26): a security review of its pinned version.
   Two parts of the first-person ask read word for word the same in the capability report, in `docs/admin-asks.md` and in the
   text a stopped run prints (`references/asks.md` of the ingest skill holds it too):
   > (4) if I hold a Microsoft 365 Copilot licence, also the delegated permission OnlineMeetingAiInsight.Read.All for meeting AI insights (admin consent).
   > To see the tenant setting: Get-CsTeamsMeetingConfiguration | Select EnableGraphTranscriptAccess, EnableAttributedTranscripts

   The tenant check is for the Teams administrator to run (it belongs to the MicrosoftTeams PowerShell module; the kit never
   runs it). `EnableGraphTranscriptAccess` False means ask (1) is still open; `EnableAttributedTranscripts` decides whether
   Graph transcripts carry speaker names. The insights permission is for the optional route in step 7; ingest itself reads
   transcripts only. If IT says no, the fallback is route 1: download the transcript from the meeting Recap, if you may, and
   save it in the drop folder.
6. **Probes that show each gate.** `ING mail probe` checks classic Outlook, reads the policy values, counts the Inbox and reads one
   subject and one body in a child process with a 20 second timeout; exit 3 means Outlook refused, prompted or timed out (ask 5).
   `py -3 <KIT>/bootstrap/report.py run --phase refresh --quick` writes the capability report, `<WB>/state/capability-refresh.md`,
   with the rows "Capture: full mail ingest" (`capture-mail-full`: is there a classic cache, does policy block scripted reads) and
   "Capture: meeting transcripts" (`capture-meeting-transcripts`: NEEDS-IT until IT enables access).
7. **Documented only; the kit does not set up or test these.** The claude.ai Microsoft 365 connector (needs tenant consent, ask 2)
   and Work IQ, Microsoft's own MCP servers for Microsoft 365 data, which when this guide was written needed a Copilot licence and
   your own app registration. Both read through the same Graph gate, so ask 1 still applies. Check the vendor's current documentation
   and your security team before relying on either. Meeting AI insights (summaries and notes that Teams generates) are a third
   route: Microsoft says "You can only fetch insights on behalf of a Microsoft 365 Copilot licensed user", which is why the
   insights permission in step 5 is asked only for people who hold that licence. The kit does not call it.
8. **Digests.** New items from the last 14 days get one quarantined AI summary each, at most 30 a day, never for a labelled item.
   It is a proposal under `## Digest (AI)`; nothing is promoted. `--no-digest` skips it.
9. **InfoSec acknowledgement.** Tell your security team first (section 1 of `docs/admin-asks.md`, then ask 6), then run
   `ING ack-infosec`: it prints the note and records the acknowledgement. Without it every run exits 5.

## Verify
- `ING status --json` shows `infosec_ack` true, and after a run `meetings_files` or `outlook_files` above 0 (`drop_failed` counts unreadable files).
- After `refresh --root captured` (guide 29), a search for a phrase from one meeting finds its file (guide 27).

## Common failures
- **Exit 5:** the acknowledgement is missing (step 9).
- **Exit 3 from Outlook:** a security prompt or a programmatic-access block. That is the policy; report it and use ask 5.
- **Exit 3 from Graph, transcripts disabled (403):** the tenant has the setting off (ask 1; the Teams administrator can read it
  with the tenant check in step 5). Use route 1 meanwhile.
- **A transcript landed in `failed` beside the drop folder:** a `.docx` must follow the Teams layout; the `.vtt` is the better input.
- **Two files of one meeting stayed separate:** they merge only when title, start time and organiser agree; add a `.meta.json` sidecar.
- **Old mail is missing:** classic Outlook covers its cached window only, and ingest never changes the sync window.
