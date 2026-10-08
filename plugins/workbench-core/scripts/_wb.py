"""Shared paths and IO for the workbench-core hooks. Stdlib only; nothing here raises on a missing file.

Path resolution (every hook uses these, so a value is decided in one place):
  claude_home()     CLAUDE_CONFIG_DIR, else ~/.claude
  workbench_home()  <claude_home>/workbench, always (no override: a project's settings could otherwise point the
                    guards at a different allowlist)
  kb_root()         WORKBENCH_KB_ROOT (the user settings env the installer writes), else config.json "kb_root",
                    else ~/claude-kb
  log_dir()         WORKBENCH_LOG_DIR, else <workbench_home>/logs
  config_redirected()  True when CLAUDE_CONFIG_DIR now names a different folder from the one the installer recorded
                    in installed-config.json next to this file (a changed env var must not point the guards at a
                    different, absent allowlist: the corporate pack then fails closed)
"""
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


RECORD = Path(__file__).with_name("installed-config.json")   # written by the installer into its kit copy


def installed_claude_home():
    """The config dir this copy of the plugin was installed into, or None (not installed by the workbench installer)."""
    try:
        with open(RECORD, encoding="utf-8-sig") as f:
            v = json.load(f).get("claude_home")
        return Path(v) if isinstance(v, str) and v else None
    except (OSError, ValueError, AttributeError):
        return None


def _same(a, b):
    k = lambda p: os.path.normcase(os.path.realpath(os.path.expanduser(str(p))))  # noqa: E731
    return k(a) == k(b)


def config_redirected():
    rec = installed_claude_home()
    return bool(rec) and not _same(rec, claude_home())


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
