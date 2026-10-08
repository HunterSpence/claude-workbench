"""PreToolUse(Read): stop reads that flood the context or always fail.

  - A whole-file Read of a text file over 80 KB is denied: Read itself fails at 25,000 tokens, and below that it
    still floods context. A chunked Read (offset/limit) is judged on an estimate of the window's tokens instead,
    because a few long lines (minified HTML, JSON dumps) can blow the limit at a small line count.
  - A Read of a directory always fails (EISDIR): denied with the right tool to use.
  - A Git Bash path (/tmp/x, /c/x) does not resolve for the Read tool on Windows: denied, naming the Windows path
    to use (Git Bash /tmp is %TEMP%, /c/ is C:/).
It only ever denies or says nothing: it never allows or rewrites a call. Images, PDFs and notebooks pass. Any internal
error says nothing. Always exits 0.
"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _wb  # noqa: E402

WHOLE_FILE_BYTES = 81_920     # under 25,000 tokens for every mix of code and prose
SMALL_FILE_BYTES = 40_960     # a chunk of a file this small always fits
WINDOW_TOKEN_CAP = 28_000     # estimate threshold; the estimator runs slightly high on dense text


def log(msg):
    _wb.append_line(_wb.log_dir() / "guards.log", f"READFLOOD {' '.join(str(msg).split())}")


def est_tokens(text):
    """Token estimate by character class: ASCII alphanumerics ~2.5 chars/token, punctuation ~1 token each, non-ASCII
    ~2 chars/token, whitespace ~0.3. Plain prose lands near 4 chars/token."""
    al = ws = na = 0
    for c in text:
        if c.isascii():
            if c.isalnum():
                al += 1
            elif c.isspace():
                ws += 1
        else:
            na += 1
    return al / 2.5 + (len(text) - al - ws - na) + na * 0.5 + ws * 0.3


def window_tokens(fp, offset, limit):
    """Estimated tokens a Read(offset, limit) returns (defaults: line 1, 2000 lines; long lines count in full)."""
    try:
        start, n = max(int(offset or 1), 1), int(limit or 2000)
    except (TypeError, ValueError):
        return 0
    total = 0.0
    with open(fp, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            if i < start:
                continue
            if i >= start + n or total > WINDOW_TOKEN_CAP:
                break
            total += est_tokens(line)
    return total


def deny(reason):
    _wb.emit("PreToolUse", permissionDecision="deny", permissionDecisionReason="read-flood-guard: " + reason)


def main():
    inp = _wb.read_event()
    ti = inp.get("tool_input") if isinstance(inp.get("tool_input"), dict) else {}
    fp = ti.get("file_path")
    if not fp or not isinstance(fp, str):
        return
    if os.name == "nt":
        m = re.match(r"^/(tmp|[A-Za-z])(/|$)", fp.replace("\\", "/"), re.I)
        if m and not os.path.exists(fp):
            p = fp.replace("\\", "/")
            win = (tempfile.gettempdir().replace("\\", "/") + p[4:] if m.group(1).lower() == "tmp"
                   else m.group(1).upper() + ":" + p[2:])
            return deny(f"'{fp}' is a Git Bash path; the Read tool resolves it as a Windows path and fails. "
                        + (f"Re-run the Read with file_path {win}" if os.path.exists(win) else
                           f"Git Bash /tmp is {tempfile.gettempdir()} and /c/... is C:/...: use the Windows form."))
    if os.path.isdir(fp):
        return deny(f"'{fp}' is a directory; Read always fails on it. Use the Glob tool or `ls` to list it.")

    def ok():
        return None

    if re.search(r"\.(png|jpe?g|gif|webp|bmp|ico|svg|pdf|ipynb)$", fp, re.I):
        return ok()
    try:
        size = os.path.getsize(fp)
    except OSError:
        return ok()
    if ti.get("limit") or ti.get("offset"):
        if size <= SMALL_FILE_BYTES:
            return ok()
        win = window_tokens(fp, ti.get("offset"), ti.get("limit"))
        if win <= WINDOW_TOKEN_CAP:
            return ok()
        return deny(f"the requested window (offset={ti.get('offset') or 1}, limit={ti.get('limit') or 2000}) is an "
                    f"estimated {round(win / 1000)}k+ tokens; Read fails at 25,000. Use a smaller limit, Grep for the "
                    "part you need, or cut long lines in the shell (cut -c1-300).")
    if size <= WHOLE_FILE_BYTES:
        return ok()
    deny(f"the file is {round(size / 1024)} KB, past what a whole-file Read can return. Use Grep to find the "
         "relevant part, Read with offset/limit, or delegate to a subagent that returns a short summary.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"unhandled exception (no decision): {e!r}")
    sys.exit(0)
