# Capture limits

Each rule below is enforced in code and covered by a test in `plugins/workbench-capture/tests/`. The known limits are listed at the end; read them.

## What it may do
- **Read only.** A source module never touches the page. It gets a small set of calls (`goto`, `click`, `search`,
  `download`, `text`, `snapshot`) and each one passes four checks.
  1. **Allowlist.** A module declares named selectors (search box, result link, next page, a download). A click on any
     other name, or on a raw selector, is refused. The names are the only way to reach the page.
  2. **Element check.** Even an allowlisted selector is refused when the element it finds looks like a write control:
     a label, id, class or icon name that means send, post, reply, react, accept, edit, delete, share, save, submit and
     the like (English and many other languages), a button with no readable label, a form control, a submit of a
     non-GET form, a link with a script, mail or other non-web scheme, a link outside the scope, a denied address, or
     a download link used outside `download()`.
  3. **No non-GET request.** The browser context aborts every request that is not GET or HEAD and records it. The first
     one stops the run (exit 3, kind `non-get`).
  4. **Pacing.** Every load, click, search, download and file read is one paced action: at most 10 in any 60 seconds
     and 200 in any hour, with a random pause of about one to two and a half seconds between actions. The cap can be
     lowered with `--max-per-hour`, never raised. The hourly cap stops the run with a report; run again later.
- **Scope.** `scope.json` lists what may be captured, per source, and a `deny` list per source. The browser may only
  navigate to the hosts of the scope's URL entries; a deny entry that appears in an address or path is never visited.
- **Tenant.** For sources that show the signed-in account (the Microsoft 365 web apps), the account's e-mail domain must
  equal `tenant` in `scope.json`, or the run stops. A plain intranet site shows no account, so only the host list applies.
- **Labels.** A page whose label badge is in the DOM, and a file that `find convert` reports a label for, is skipped and
  named in the report unless the run has `--include-labelled`.
- **Stored addresses** lose their query string and fragment, in files, reports and logs.

## What it must never do
- Read cookies, saved sign-in state, browser storage or request authentication headers; there is no code for it and a
  static test fails the build if any appears in `scripts/`.
- Attach to the user's own Edge or to any running browser. It starts its own Edge with `channel: "msedge"` and a
  dedicated profile folder, `<WB>/capture/profile/`, and refuses a profile folder inside Edge's own user-data folder.
- Sign in, accept consent, answer a second step, solve a challenge or retry a blocked page. The user signs in once, by
  hand, through `login`.
- Open pop-ups, follow a link out of the scope, or make a network request from Node (a static test forbids it).

## Stops (exit 3, report written, no retry, no further navigation)
sign-in page, second sign-in step, consent or admin-approval page, conditional-access block, data-protection banner,
block or throttle page (HTTP 401, 403, 429, 451, 503), a main-frame navigation to a host outside the scope, a non-GET
request, a tenant mismatch, the hourly cap, a browser policy, and a module calling `stop()`. The report names the kind,
a short reason, the address without its query, and the text to send to IT. It never contains page content.

## Edge policies
Capture reads `RemoteDebuggingAllowed` and `HeadlessModeEnabled` (machine and user policy keys). Unset means allowed.
`RemoteDebuggingAllowed` off: capture stops with the ask for IT; it does not look for another way in.
`HeadlessModeEnabled` off: runs are headed (a visible window), which still works. The IT ask is in `docs/admin-asks.md`.

## Where files go
`<DATA>/captured/<source>/...` by default (the data folder, which may be on the work OneDrive). A source can be kept on
this machine only with `scope set placement.<source> local`, which writes to `<WB>/capture/local/<source>/`.

## Known limits (read before relying on it)
- A server redirect to another host is followed by the browser inside its own network stack, before any script can stop
  it. Capture sees the navigation, stops at once and keeps nothing from that page, but that one GET has already been
  made. A redirect to a sign-in host is the usual case and is a stop anyway.
- A web app that reads data with POST requests (some mail and chat web apps do) fails the non-GET rule on its first
  load. That is deliberate and is not worked around; it is why the mail and chat web sources are not shipped here.
- DOM label badges are found by common attributes (`data-sensitivity-label`, `data-label-name`, an `aria-label` that
  starts with "Sensitivity label", a `sensitivity-label` class). A site that shows its label another way is not
  detected; use the deny list for those areas.
- The element check is a safety net with a vocabulary, not a proof. The allowlist is the real boundary: a module that
  names a selector which matches something harmful with an innocent label would get through the second check, which
  is why modules are reviewed and why check 3 exists.
- `login` opens a visible window and waits for the user to close it; it cannot be tested without a person.
