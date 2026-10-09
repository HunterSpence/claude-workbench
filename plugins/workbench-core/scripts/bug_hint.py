"""Hook script that names the matching bug card in one short line. Detectors: <KB root>/_shared/bug-detectors.json, else
the workbench kit copy, else this kit's kb-template (first readable file wins). Format:
{"detectors": [{"card": n, "title": "...", "pattern": "<regex>"}]}. Only the first 4 KB of the text is matched; at most ONE
card is named (<= 300 characters); no match, a bad file or any error prints nothing. Always exits 0.

  PostToolUseFailure  (no argument)  match the failed tool's `error` text and inject the card line.
  StopFailure         (no argument)  the turn ended on an API error and Claude Code discards a StopFailure hook's output
                      (only `terminalSequence` is honoured), so nothing can be injected now. Match `last_assistant_message`
                      (the API error string), else the `error` type through ENUM_CARD, queue the line in
                      <workbench home>/state/pending-hint-<session_id>.json (atomic) and print one bell as terminalSequence.
  UserPromptSubmit    (--pending)  inject this session's queued line once, then delete the file. Another session's file is
                      never read. Files older than 24 hours are removed. Installed by setup only at or above
                      STOPFAILURE_MIN_CC; never from the static hooks.json.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wb  # noqa: E402

LIMIT, MAX_CHARS = 4096, 300
# The Claude Code release that added the StopFailure event (official changelog, 2.1.78: "Added `StopFailure` hook event
# that fires when the turn ends due to an API error"). Setup reads this literal by path; keep it a plain 3-tuple.
STOPFAILURE_MIN_CC = (2, 1, 78)
# StopFailure `error` types (hooks documentation) -> the card for that class, used when the message text matches no
# detector. A type with no entry (invalid_request, max_output_tokens, unknown) has no card that covers it.
ENUM_CARD = {"rate_limit": 19, "overloaded": 67, "server_error": 67, "authentication_failed": 70,
             "oauth_org_not_allowed": 71, "account_on_hold": 71, "billing_error": 69, "model_not_found": 76,
             "cloud_credential_error": 69}
STALE_S = 24 * 3600
BELL = "\a"                                    # a bare BEL is on the documented terminalSequence allowlist
SID = re.compile(r"[A-Za-z0-9_-]{1,80}")       # a session id becomes part of a file name: nothing else gets through
LEAD = "The last turn ended on an API error. "


def detectors():
    kit = Path(__file__).resolve().parents[3]
    for base in (_wb.kb_root(), _wb.workbench_home() / "kit" / "kb-template", kit / "kb-template"):
        try:
            with open(base / "_shared" / "bug-detectors.json", encoding="utf-8-sig") as f:
                rows = json.load(f)["detectors"]
            return rows if isinstance(rows, list) else []
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return []


def match(text):
    """(card, title) of the first detector whose pattern is found in the first 4 KB of text, else None."""
    text = text[:LIMIT]
    for d in detectors():
        try:
            if re.search(d["pattern"], text, re.I):
                return int(d["card"]), " ".join(str(d["title"]).split())
        except (KeyError, TypeError, ValueError, re.error):
            continue
    return None


def title_of(card):
    for d in detectors():
        try:
            if int(d["card"]) == card:
                return " ".join(str(d["title"]).split())
        except (KeyError, TypeError, ValueError):
            continue
    return None


def render(card, title, lead=""):
    head = f"{lead}Known bug, card {int(card)}: "
    tail = " (see _shared/bug-cards.md)"
    return head + str(title)[:max(0, MAX_CHARS - len(head) - len(tail))] + tail


def hint(error):
    hit = match(error)
    return render(*hit) if hit else None


# ── StopFailure relay ─────────────────────────────────────────────────────────────────────────────────────────
def state_dir():
    return _wb.workbench_home() / "state"


def pending_path(sid):
    return state_dir() / f"pending-hint-{sid}.json" if isinstance(sid, str) and SID.fullmatch(sid) else None


def prune():
    """Remove queued hints (and orphaned temp files) untouched for 24 hours."""
    for p in state_dir().glob("pending-hint-*"):
        try:
            if time.time() - p.stat().st_mtime > STALE_S:
                p.unlink()
        except OSError:
            pass


def queue(ev):
    """StopFailure: queue this session's hint. The message text wins; the error type is the fallback."""
    p = pending_path(ev.get("session_id"))
    if not p:
        return
    msg, err = ev.get("last_assistant_message"), ev.get("error")
    hit, source = (match(msg) if isinstance(msg, str) else None), "message"
    if not hit and isinstance(err, str) and err in ENUM_CARD:
        title = title_of(ENUM_CARD[err])
        hit, source = ((ENUM_CARD[err], title) if title else None), "error"
    if not hit:
        return
    row = {"card": hit[0], "title": hit[1], "source": source,
           "created": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(row), encoding="utf-8")
    os.replace(tmp, p)


def deliver(ev):
    """UserPromptSubmit --pending: this session's queued line, consumed. If the file cannot be deleted nothing is
    injected, so a stuck file can never repeat the hint on every prompt."""
    p = pending_path(ev.get("session_id"))
    if not p:
        return None
    try:
        row = json.loads(p.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        row = None                                  # unreadable or corrupt: consume it, say nothing
    try:
        p.unlink()
    except OSError:
        return None
    try:
        return render(row["card"], row["title"], LEAD)
    except (KeyError, TypeError, ValueError):
        return None


if __name__ == "__main__":
    try:
        ev = _wb.read_event()
        if "--pending" in sys.argv[1:]:
            try:
                prune()
            except Exception:
                pass
            msg = deliver(ev)
            if msg:
                _wb.emit("UserPromptSubmit", additionalContext=msg)
        elif ev.get("hook_event_name") == "StopFailure":
            try:
                prune()
                queue(ev)
            except Exception:
                pass
            print(json.dumps({"terminalSequence": BELL}))
        else:
            err = ev.get("error")
            msg = hint(err) if isinstance(err, str) and not ev.get("is_interrupt") else None
            if msg:
                _wb.emit("PostToolUseFailure", additionalContext=msg)
    except Exception:
        pass
    sys.exit(0)
