"""Shared paths and IO for the workbench-core hooks. Stdlib only; nothing here raises on a missing file.

Path resolution (every hook uses these, so a value is decided in one place):
  claude_home()     CLAUDE_CONFIG_DIR, else ~/.claude
  workbench_home()  <claude_home>/workbench, always (no override: a project's settings could otherwise point the
                    guards at a different allowlist)
  kb_root()         WORKBENCH_KB_ROOT (the user settings env the installer writes), else config.json "kb_root",
                    else ~/claude-kb
  log_dir()         WORKBENCH_LOG_DIR, else <workbench_home>/logs
  kb_state_dir(kb)  where a KB's locks, precompact flags and snapshots live: <workbench_home>/kb-state/<key>, never
                    inside the (possibly synced) KB. <key> = 8 hex digits of the KB root path. A copy of
                    workbench-kb's kb_audit.state_dir (plugins never import each other); a test asserts they agree.
  legacy_kb_state_dir(kb)  <kb>/.state, where an earlier kit kept all of it (readable for one release)
  config_redirected()  True when CLAUDE_CONFIG_DIR now names a different folder from the one the installer recorded
                    in installed-config.json next to this file (a changed env var must not point the guards at a
                    different, absent allowlist: the corporate pack then fails closed). A config dir registered in the
                    main install's profiles.json (per-client profiles) is not "redirected".
  redact(text)      text with credential-shaped spans replaced by [REDACTED] (the guard log and the issues log use it)
  heartbeat(fired, stamp)  the guard heartbeat <workbench home>/state/guard-heartbeat.json (best-effort, atomic, never
                    raises); stamp names a timestamp key to set (last_start, last_precompact)
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


def registered_profiles(rec):
    """Config dirs listed in <recorded claude home>/workbench/profiles.json (written only by the profile launcher)."""
    try:
        with open(rec / "workbench" / "profiles.json", encoding="utf-8-sig") as f:
            rows = json.load(f).get("profiles") or []
        return [r["config_dir"] for r in rows if isinstance(r, dict) and isinstance(r.get("config_dir"), str)]
    except (OSError, ValueError, AttributeError):
        return []


def config_redirected():
    rec = installed_claude_home()
    return bool(rec) and not any(_same(d, claude_home()) for d in [rec, *registered_profiles(rec)])


def heartbeat(fired, stamp=None):
    """Guard heartbeat. fired=True (the PreToolUse guard ran): last_fired now, sessions_since_fire 0, fired_total + 1.
    fired=False (a session started): sessions_since_fire + 1. fired=None: counters untouched. stamp="last_start" or
    "last_precompact" also sets that key to now (proof that SessionStart or PreCompact ran). With env WB_SELF_TEST=1 (the
    installer's self-test) only self_test_at is set and every counter and stamp stays as it was. Keys it does not know are
    kept. Returns the new dict, or None when the state folder cannot be written.
    ponytail: read-modify-write without a lock; two hooks at once can lose a count."""
    try:
        from datetime import datetime, timezone
        p = workbench_home() / "state" / "guard-heartbeat.json"
        try:
            with open(p, encoding="utf-8-sig") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        d = d if isinstance(d, dict) else {}
        n = lambda k: d[k] if isinstance(d.get(k), int) and d[k] >= 0 else 0  # noqa: E731
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        d = {**d, "version": 1, "last_fired": d.get("last_fired") if isinstance(d.get("last_fired"), str) else None,
             "sessions_since_fire": n("sessions_since_fire"), "fired_total": n("fired_total")}
        if os.environ.get("WB_SELF_TEST") == "1":      # the installer's self-test: proves nothing about a real session
            d["self_test_at"] = now
        else:
            if fired:
                d.update(last_fired=now, sessions_since_fire=0, fired_total=d["fired_total"] + 1)
            elif fired is False:
                d["sessions_since_fire"] += 1
            if stamp:
                d[stamp] = now
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
