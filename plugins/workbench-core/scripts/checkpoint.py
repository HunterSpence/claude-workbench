"""PostToolUse(Edit|Write|MultiEdit|NotebookEdit): the post-edit hook.

1. Hook self-check: after an edit to a .py file in this scripts folder, compile it, so a typo cannot switch a hook off
   without a sound.
2. Journal cadence: every 25 edits in the main session (15-minute cooldown) remind Claude to journal one line with
   the save skill's `save_driver.py --inbox-add`. The reminder carries the full command (python and driver paths), so a
   long session's state survives compaction without a lookup.
Never blocks a tool call. Always exits 0. Starts no process.
"""
import datetime as dt
import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _wb  # noqa: E402

THRESHOLD = 25
COOLDOWN_MIN = 15
DRIVER = Path("workbench-kb", "scripts", "save_driver.py")


def console_python():
    """config.json `python`, else this interpreter; never pythonw (it would swallow the driver's output)."""
    py = _wb.config().get("python")
    if not (isinstance(py, str) and py):
        py = None
    elif not os.path.isfile(py):
        py = shutil.which(py)            # a bare name ("pythonw") becomes its path, so the console check below sees the file
    p = Path(py or sys.executable or "python")
    if p.stem.lower() == "pythonw" and p.with_name("python" + p.suffix).is_file():
        p = p.with_name("python" + p.suffix)
    return p.as_posix()


def driver_path():
    """save_driver.py: the installed kit first, then the newest plugin-cache copy, then this repo's layout."""
    try:
        cache = sorted((_wb.claude_home() / "plugins" / "cache" / "workbench" / "workbench-kb").glob("*/scripts/save_driver.py"),
                       key=lambda p: p.stat().st_mtime)[-1:]
    except OSError:
        cache = []
    cands = [_wb.workbench_home() / "kit" / "plugins" / DRIVER, *cache, HERE.parents[1] / DRIVER]
    return next((p for p in cands if p.is_file()), None)


def reminder():
    drv = driver_path()
    # ponytail: paths sit in double quotes; a path holding a quote, dollar or backtick is not escaped (Windows paths cannot).
    cmd = f'"{console_python()}" "{drv.as_posix()}" --inbox-add' if drv else "the save skill's save_driver.py --inbox-add"
    return (f"JOURNAL CHECKPOINT ({THRESHOLD} edits). Before your next tool call, journal one line with the Bash tool "
            f"(in PowerShell put & and a space in front): {cmd} "
            "\"<what changed + what is open>\" (under 2 KB, no backticks). Do not edit active-context.md directly. "
            "Then continue the user's task.")


def hooks_gate(d):
    path = str((d.get("tool_input") or {}).get("file_path") or "")
    if not path.endswith(".py"):
        return None
    try:
        Path(path).resolve().relative_to(HERE)
    except (ValueError, OSError):
        return None
    import py_compile
    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as e:
        return f"HOOK EDIT: {path} does not compile: {e.msg}"
    return None


def emit(msg):
    _wb.emit("PostToolUse", additionalContext=msg)


def main():
    d = _wb.read_event()
    gate = hooks_gate(d)
    if d.get("agent_id"):            # subagent: journal nudges belong to the main session
        if gate:
            emit(gate)
        return
    sid = re.sub(r"[^A-Za-z0-9-]", "", str(d.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""))
    state_dir = _wb.workbench_home() / "state"
    state = state_dir / f"checkpoint.{sid or 'nosession'}.json"
    try:
        s = json.loads(state.read_text(encoding="utf-8"))
        count, last = int(s["count"]), s.get("last_fired")
    except Exception:
        count, last = 0, None
    count += 1
    fire = count >= THRESHOLD
    if fire and last:
        try:
            fire = (dt.datetime.now().astimezone() - dt.datetime.fromisoformat(last)).total_seconds() / 60 >= COOLDOWN_MIN
        except ValueError:
            pass
    if fire:
        count, last = 0, dt.datetime.now().astimezone().isoformat()
        week_ago = dt.datetime.now().timestamp() - 7 * 86400   # reap other sessions' counters
        for p in state_dir.glob("checkpoint.*.json"):
            try:
                if p.stat().st_mtime < week_ago:
                    p.unlink()
            except OSError:
                pass
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"count": count, "last_fired": last}), encoding="utf-8")
    except OSError:
        pass
    msgs = [x for x in (gate, reminder() if fire else None) if x]
    if msgs:
        emit("\n\n".join(msgs))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
