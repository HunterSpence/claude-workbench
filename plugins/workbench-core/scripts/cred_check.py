"""Stop hook: if Claude's last message contains a credential-shaped value, block the stop once and ask it to say so
plainly (the value is now in the transcript and should be rotated) without repeating the value. Generic secret
shapes only (secretscan.py). Fail-open: any error exits 0 with no output."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _wb  # noqa: E402
import secretscan  # noqa: E402

TAIL = 262_144   # only the transcript tail: it grows without bound and this runs on every stop


def last_assistant_text(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > TAIL:
            f.seek(size - TAIL)
            f.readline()   # drop the partial line at the seek point
        lines = [ln for ln in f.read().decode("utf-8", errors="ignore").splitlines() if ln.strip()]
    for ln in reversed(lines):
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        if e.get("type") != "assistant" and msg.get("role") != "assistant":
            continue
        c = msg.get("content", e.get("content"))
        parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"] \
            if isinstance(c, list) else [c] if isinstance(c, str) else []
        text = "\n".join(parts).strip()
        if text:
            return text
    return ""


def main():
    d = _wb.read_event()
    if d.get("stop_hook_active"):   # never block the same stop twice
        return
    tp = d.get("transcript_path") or ""
    if not (isinstance(tp, str) and os.path.isfile(tp)):
        return
    found = secretscan.findings(last_assistant_text(tp))
    if found:
        where = ", ".join(f"line {f['line']} ({f['match']})" for f in found[:3])
        print(json.dumps({"decision": "block", "reason": (
            f"Your last message contains what looks like a credential value: {where}. Do not repeat it. Tell the user "
            "plainly that a secret appeared in this conversation and should be rotated, and refer to credentials by "
            "name from now on. If it is not a real secret (an example or a test value), say so in one line.")}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
