---
name: vdi-drive
description: "OPT-IN. Drive a remote desktop shown as an image in a browser (Citrix, Horizon, Azure Virtual Desktop, noVNC). Needs written authorisation."
disable-model-invocation: true
---

# vdi-drive (opt-in)

## STOP: authorization gate (read before anything else)
Use this skill only when **all** of these hold. If any is unknown, ask the user and stop.
1. **Authorisation.** The owner of the remote desktop has authorised automated input for this task.
2. **An authorisation note on disk.** Write a short local note: who authorised it, which desktop,
   which task, until when. `drive.mjs` refuses every command that touches a desktop unless it is
   given that file (`--auth=<file>` or `VDI_AUTH_NOTE`). The note is checked for presence only;
   its text is never printed or sent.
3. **No credentials, ever.** The human launches the browser, signs in and completes MFA. You attach
   afterwards. Never type, read, read back, screenshot on purpose, store or export a password,
   token, one-time code or secret, and never export browser storage state (`storageState` is a
   portable login). If a credential prompt appears, stop and hand control back.
4. **Human commits.** Save, Submit, Delete, Approve and similar buttons are clicked by the human.
   `drive.mjs` sends Enter, Space and shortcuts, and types text holding a space, tab or newline,
   only when the human names those keys for that run (`--allow-keys=Enter,Space`);
   `scripts/limits.mjs` makes the rest structural.

Prefer, in order: an API or CLI the owner provides; a normal web UI driven through the DOM; this.

## What it is
Pixel-driving a remote session through a browser. The behaviours listed below are things to check
on your own setup, not guarantees; `references/test-rig.md` describes a disposable desktop to check
them against.

Setup (once, in a working folder you own):
```bash
cp -r "${CLAUDE_SKILL_DIR}/scripts" ./vdi-work && cd vdi-work && npm install --ignore-scripts   # playwright-core only, no browser download
```
Edge is preferred (installed on managed Windows, native single sign-on); Chrome works; set
`VDI_BROWSER` to override. Firefox cannot be used (no CDP). The browser profile and every
screenshot live under the system temp folder (`<temp>/vdi-drive/`), never in the working folder.

## Core workflow
Every command below takes `--auth=<note>`; it is left out here for brevity.
1. `node drive.mjs launch`: opens the browser on-screen with a dedicated profile on port 9222.
   The human connects to the desktop and signs in. You do not watch them sign in.
2. `node drive.mjs canary --allow-keys=Space` into a scratch text field inside the session (an empty editor), then
   compare every character with the printed expectation. The remote side maps physical keys with
   ITS keyboard layout; a mismatch rewrites symbols with no error.
3. `node drive.mjs shot` (half-scale JPEG by default; `--crop=x,y,w,h` to zoom; `--full` only to
   read a specific character). Find the target by its pixels.
4. Act in ONE invocation: `node drive.mjs seq --allow-keys=Enter click:X,Y type:"text" key:Enter`
   (only when the human agreed that Enter is safe on that screen; text with spaces also needs
   `Space` in the list). The remote canvas can lose
   keyboard focus between separate invocations, so click-to-focus, typing and Enter belong together.
5. Verify what landed, never what you sent: a fresh screenshot, a file on the remote side, or an
   API response. A "typed OK" return proves nothing.
6. When the task ends: close the browser, then `node drive.mjs clean` deletes the screenshots and
   the profile.

## Observed behaviours: verify on your own setup
- **ASCII only.** `keyboard.type()` falls back to CDP `Input.insertText` for characters without a
  physical key, and that raises no keydown, so a remote canvas never receives them: dashes, curly
  quotes, accents, non-breaking spaces and emoji can vanish silently (`node charfidelity.mjs`
  shows what your browser does). `drive.mjs` refuses non-ASCII.
- **Speed is rarely the problem.** VNC and RDP run over TCP, which retransmits in order, so slow
  links delay keystrokes rather than drop them; loss tends to come with a disconnection, which is
  visible. Watch for disconnects instead of pacing, and run `node rttsweep.mjs` against a rig you
  own to check your link.
- **Image cost follows pixel dimensions, not file size** (roughly width x height / 750 tokens).
  Crop and scale by default; full resolution only to read one character.
- **A crop pixel-diff is a cheap "did anything happen" check.** Compare the target region before
  and after an action: unchanged means the input went nowhere. It detects change, not correctness.
- **Coordinates come from live canvas geometry**, not from a number read off a downscaled image:
  use the element's bounding box and its width/height ratio. Hard-coded coordinates break when the
  window, zoom or browser changes.
- **Buffered clicks land late.** A click that "did nothing" may be queued and fire after the screen
  changed, hitting whatever is there now. Re-screenshot before repeating any click.
- **Screenshots can be stale** on an idle session. Before concluding an action failed, check
  something that always changes (a clock) or wait and re-shoot.
- **Client overlays steal focus.** A web client's own panels (connection info, toolbars) take
  keyboard focus; close them before typing into the session.
- **Ctrl+C may arrive as a literal "c".** Modifier combinations do not always survive the canvas
  key path. `Escape` reliably clears a command line; if a line is already corrupted, discard it and
  retype in a fresh window.
- **Clicking inside a console between typing and Enter discards the typed input.** Sequence is
  click, type, Enter.
- **Ping is not a latency probe** inside many cloud desktops (outbound ICMP is often blocked). Time
  a TCP connect instead.

## Known blockers
- **Policy can disable remote debugging** (`RemoteDebuggingAllowed` and equivalents). It fails as a
  bare connection refusal. That is the organisation's decision: stop, do not work around it.
- Chrome and Edge refuse remote debugging on the default profile; that is why a dedicated profile
  is launched cold. You cannot attach to an already-open normal window.
- Never force-kill the browser: a stale profile lock blocks the next launch with no clear error.
- **Clipboard redirection** is a server-side setting. If the owner enabled it, pasting is simpler.
- The native desktop clients are opaque OS windows: none of this applies to them. UI-automation
  tools cannot see inside a remote desktop window either; it is one bitmap from the outside.

## Limits: `scripts/limits.mjs` (Node stdlib; `node limits.mjs` self-checks)
- `loadScreenMap` / `SAFE_KEYS` / `assertKeyAllowed` / `assertTypeAllowed`: commit controls are
  never wired into the agent's actions. A screen map (for example a form with fields A, B and C)
  that even declares Save/Submit/Delete throws; coordinates must be anchor-relative; Enter, Space,
  Delete and shortcuts, and typed spaces, tabs and newlines, need the human's per-run `--allow-keys`.
- `authNotePath` / `shotPath`: the authorisation-note check and the temp-only screenshot path.

The principle: **a control that depends on the agent reading a screen correctly is not a control.**

## Verifying the harness
- `node limits.mjs`: the limit self-checks (no browser, no install needed).
- `node drive.mjs test`: off-screen self-check against `canvas-test.html` (click, exact keystrokes,
  non-ASCII refusal, Enter and typed spaces refused without `--allow-keys`, the CLI refusing to run
  without a note).
- `node charfidelity.mjs`: which characters reach a keydown-only surface.
- `node rttsweep.mjs`: keystroke loss against a rig you own (`references/test-rig.md`).

## References
- `references/test-rig.md`: a disposable remote desktop to measure against.
- `references/reading-the-screen.md`: OCR read-back when eyes on a screenshot are not enough.
