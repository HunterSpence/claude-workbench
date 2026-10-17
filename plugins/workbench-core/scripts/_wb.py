"""Shared paths and IO for the workbench-core hooks. Stdlib only; nothing here raises on a missing file.

Path resolution (every hook uses these, so a value is decided in one place):
  claude_home()     CLAUDE_CONFIG_DIR, else ~/.claude
  workbench_home()  <claude_home>/workbench, always (no override: a project's settings could otherwise point the
                    hooks at a different folder)
  kb_root()         WORKBENCH_KB_ROOT (the user settings env the installer writes), else config.json "kb_root",
                    else ~/claude-kb
  log_dir()         WORKBENCH_LOG_DIR, else <workbench_home>/logs
  kb_state_dir(kb)  where a KB's locks, precompact flags and snapshots live: <workbench_home>/kb-state/<key>, never
                    inside the (possibly synced) KB. <key> = 8 hex digits of the KB root path. A copy of
                    workbench-kb's kb_audit.state_dir (plugins never import each other); a test asserts they agree.
  legacy_kb_state_dir(kb)  <kb>/.state, where an earlier kit kept all of it (readable for one release)
  redact(text)      text with credential-shaped spans replaced by [REDACTED] (the issues log uses it)
  heartbeat(stamp)  stamp "last_start" or "last_precompact" to now in <workbench home>/state/hooks-heartbeat.json (proof the
                    plugin hooks run; best-effort, atomic, never raises)
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

try:
    import msvcrt  # Windows
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None
    import fcntl


def claude_home():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def workbench_home():
    return claude_home() / "workbench"


def heartbeat(stamp):
    """Set `stamp` ("last_start" or "last_precompact") to now in <workbench home>/state/hooks-heartbeat.json. Other keys are
    kept. Returns the new dict, or None when the state folder cannot be written.
    ponytail: read-modify-write without a lock; two hooks at once can lose a stamp."""
    try:
        from datetime import datetime, timezone
        p = workbench_home() / "state" / "hooks-heartbeat.json"
        try:
            with open(p, encoding="utf-8-sig") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        d = dict(d) if isinstance(d, dict) else {}
        d[stamp] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, p)
        return d
    except Exception:
        return None


def redact(text):
    """text with every credential-shaped value (secretscan's one pattern set, which also takes a private key block whole)
    replaced by [REDACTED]; the name before a value stays ("API_TOKEN=[REDACTED]"). Raises when the scanner cannot load: a
    caller that must not leak (the issues log) then writes nothing."""
    import secretscan
    for a, b in reversed(secretscan.scan_text(text, values_only=True)):
        text = text[:a] + "[REDACTED]" + text[b:]
    return text


def config():
    try:
        with open(workbench_home() / "config.json", encoding="utf-8-sig") as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def kb_root():
    v = os.environ.get("WORKBENCH_KB_ROOT") or config().get("kb_root")
    return Path(os.path.expanduser(v)) if v else Path.home() / "claude-kb"


def kb_state_dir(kb=None):
    kb = Path(kb) if kb else kb_root()
    return workbench_home() / "kb-state" / hashlib.sha256(kb.resolve().as_posix().lower().encode()).hexdigest()[:8]


def legacy_kb_state_dir(kb=None):
    return (Path(kb) if kb else kb_root()) / ".state"


def log_dir():
    return Path(os.environ.get("WORKBENCH_LOG_DIR") or workbench_home() / "logs")


def read_event():
    """The hook's stdin JSON as a dict ({} on anything else). utf-8-sig on the raw bytes: a hook launched
    through PowerShell can receive a BOM, and a text-mode read would decode with the console code page."""
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        d = json.loads(raw) if raw.strip() else {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def emit(event, **fields):
    """Print one hookSpecificOutput object."""
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, **fields}}, ensure_ascii=False))


def append_line(path, line, timeout=5.0, max_bytes=1_048_576):
    """Append one line under an OS lock on a sibling .lock file (a plain append on Windows is seek-to-end plus
    write, so two hooks firing at once can tear or lose a line). Past max_bytes the file rotates to <name>.1.
    Never raises."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path.with_name(path.name + ".lock"), "a+b") as lk:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    lk.seek(0)
                    if msvcrt:
                        msvcrt.locking(lk.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        break  # ponytail: append unlocked after the timeout rather than drop the line
                    time.sleep(0.02)
            if path.exists() and path.stat().st_size > max_bytes:
                os.replace(path, path.with_name(path.name + ".1"))
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line.rstrip("\n") + "\n")
    except Exception:
        pass
