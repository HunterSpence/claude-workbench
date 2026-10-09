# Quarantine: how meeting and mail text is handled

Transcripts and mail bodies are untrusted text. Anything a speaker or sender wrote, including hidden text, can try to give
instructions to a model. Ingest treats it as data at every step.

## Before anything is stored
`common.sanitize` runs on every body and attachment text:
- HTML becomes text; hidden elements (display none, visibility hidden, zero font size, the hidden attribute, scripts,
  styles, comments) are dropped, and quoted-history blocks are dropped from mail.
- Zero-width and bidirectional control characters, soft hyphens and Unicode tag characters are removed, and control
  characters are removed.
- Every web address becomes `[link: host]`; nothing clickable and no query string is kept.
- Text that could forge our own structure is defused: an HTML comment opener, a line that starts with the digest
  heading, and any opening or closing `untrusted` tag.

## Files: check for hidden text before they enter
`sanitize` sees text, not layout, so a document file can still hide text in ways it cannot see: white or covered text,
text off the page, 1 pt text, hidden Word runs, instructions in the document properties. Ingest does not run a layout
check itself. Before a file enters the flow (a `.docx` or `.vtt` transcript going into `_drop/meetings/`, a PDF or Word
attachment you are about to convert, anything you will index), run the hidden-text check from the office-render skill
in the core plugin (`scripts/hidden_text.py scan <file>`; how-to guide 52):
- exit 0: carry on;
- exit 1, flagged: move the file into a review folder outside every drop and index folder and leave it there. A person
  reads the findings and the document, then deletes it, asks the sender for a clean copy, or releases it knowing what
  it carries. Nothing is released automatically, and the check never moves, edits or rejects a file by itself;
- exit 2, not scanned (unsupported type, unreadable or encrypted, over a cap): treat it as flagged.
The excerpts in a finding are text from the file: they are data like everything else here.

## The digest call
One `claude -p` call per item, built in `scripts/digest.py`:
- no tools (`--tools ""`), an empty strict MCP configuration, no session saved, one turn, run in an empty temporary
  directory; the model option is passed only when the `digest_model` setting is set, or else when the setup routing table
  (`<WB>/state/routing.effective.json`, row `R-read`) names a usable model; otherwise Claude Code's own model is used;
- the child environment has no `ANTHROPIC_API_KEY`; the user's own Claude Code sign-in is used;
- the prompt goes in on standard input: a fixed instruction, then the item inside `<untrusted-meeting>` or
  `<untrusted-email>` tags with a statement that it is data, then a fixed reminder;
- the reply must be one JSON object that validates against `scripts/digest.schema.json` (no extra keys, bounded lengths,
  dates as `YYYY-MM-DD`). Anything else is rejected, logged without content to `<WB>/state/ingest/digest-rejects.log`
  and not appended; the call is not retried;
- labelled items, items outside the window, the first pass over a folder and everything past the daily cap make no call.

## What the digest is
A proposal. It is appended under `## Digest (AI)` with the model name and time, the rollup lists the day's decisions,
action items and changes with a link to each item, and nothing is promoted to any other file automatically.

## Limits
The schema checks shape, not truth: a clever text can still bend a synopsis. That is why the output only ever lands in
a text file that the user reads, never in a command, a message or a tool call. In a mail body, text coloured like its
background is not detected; in PDF and Word files the check above looks for it. A transcript may contain the speech of
people outside the organisation; the InfoSec note says so.
