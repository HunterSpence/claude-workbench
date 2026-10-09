# Asks for IT, and known limits

Ingest works with the organisation's controls, never around them. When a control says no, the run stops (exit 3) and the
report carries one of the texts below. Nothing is retried by another route.

## Texts the run report carries

**Outlook blocks or prompts for a protected property**
Outlook refused or prompted for a protected mail property while a read-only script read my own cached mailbox. Please tell me whether a local read-only script may read my own cached mailbox through classic Outlook, and what the programmatic-access (Object Model Guard) policy is on this device. Nothing was changed and the run did not try another way.

**Graph access to meeting transcripts is off**
Please ask the Teams administrator to turn on Microsoft Graph access to meeting transcripts (Teams admin center, Meetings, Meeting settings, Transcript API access; or the EnableGraphTranscriptAccess setting of the Teams meeting configuration) and, if wanted, speaker attribution (EnableAttributedTranscripts). To see the tenant setting: Get-CsTeamsMeetingConfiguration | Select EnableGraphTranscriptAccess, EnableAttributedTranscripts. Until then, download the transcript from the meeting recap yourself and drop it in the drop folder.

**The tenant needs administrator approval for the app**
Please ask the Entra administrator to approve a read-only public-client app registration for me only, with the delegated permissions User.Read, offline_access, Calendars.Read, OnlineMeetings.Read, OnlineMeetingTranscript.Read.All (and Mail.Read for mail) and the redirect address http://localhost. And, if I hold a Microsoft 365 Copilot licence, also the delegated permission OnlineMeetingAiInsight.Read.All for meeting AI insights (admin consent).

## Why these texts carry what they carry
- The permissions are delegated, so the app acts as the signed-in user only. Microsoft's permissions reference says both `OnlineMeetingTranscript.Read.All` and `OnlineMeetingAiInsight.Read.All` need administrator consent in their delegated form.
- The tenant switch is off by default. The Teams documentation says that with it off, apps cannot read transcripts "regardless of app-level permissions", so the app approval alone never opens the route.
- The insights permission is asked in the same round so IT is not asked twice. Ingest reads transcripts only and never calls the insights route; that route needs a Microsoft 365 Copilot licence for every user of the app.
- The tenant check shows the current value of both switches before anyone changes one.
- If the answer is no, the fallback needs no change at all: download the transcript from the meeting recap, if you may, and save it in the drop folder.

## Other questions worth asking before a full run
- Licensing: does the user hold a Microsoft 365 Copilot licence (a prerequisite of the insights permission above; ingest itself does not use that route)?
- Meeting policy: may the user download transcripts of meetings they attend, and is any copy restriction set?
- Outlook: will classic Outlook stay on this device, and is a local read-only script reading the user's own cached mailbox permitted?
- InfoSec: sign-off for an own-access local copy on this device (never a personal cloud), the expected volume of mailbox
  reads for a Graph backfill, and how labelled or encrypted items are to be handled.
- Claude: may the user's approved Claude sign-in process their mail and meeting transcripts, including the speech of
  participants from other organisations, and what are the retention terms?
- If a community Microsoft 365 server is enabled in the catalog: a security review of its pinned version.

## Known limits
- The Teams on the web Recap Download step is deferred: the page reads its data with POST requests, which capture's no-non-GET rule stops. The user downloads the transcript by hand and drops it in the folder.
- Mail from classic Outlook covers the cached window only (online archives and public folders are never read, and the sync window is never changed); the new Outlook has no object model, so use Graph or capture's web source.
- A transcript can be fetched through Graph only for meetings the signed-in user may read and only while the tenant allows it; the organiser's download controls are not worked around, and a view-only transcript is never extracted.
- The `.docx` reader expects the Teams layout (a title paragraph, then a speaker line with an offset and the spoken text beneath); anything else goes to `failed/`. A `.vtt` is always the better input.
- Two files of one meeting merge only when title, start time and organiser agree (a sidecar or a Teams-style file name provides them).
- Hidden text is dropped by style (display none, zero size, hidden attribute); text coloured like its background cannot be detected.
- Recipients from classic Outlook are display names; senders are addresses where Exchange resolves them.
- Graph mail reads labels from message headers when the service returns them; where it does not, labelled mail can only be told apart by its content, so keep the Graph mail route for folders without labelled mail.
