"""PostToolUse(Edit|Write|MultiEdit|NotebookEdit): the post-edit hook.

1. Hook self-check: after an edit to a .py file in this scripts folder, compile it and run the guard on two benign
   calls. The guards fail open, so a typo would otherwise switch a check off without a sound.
2. Journal cadence: every 25 edits in the main session (15-minute cooldown) remind Claude to journal one line with
   the save skill's `save_driver.py --inbox-add`, so a long session's state survives compaction.
Never blocks a tool call. Always exits 0.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _wb  # noqa: E402

THRESHOLD = 25
COOLDOWN_MIN = 15
REMINDER = (f"JOURNAL CHECKPOINT ({THRESHOLD} edits). Before your next tool call, journal one line with the save "
            "skill's journal command: save_driver.py --inbox-add \"<what changed + what is open>\" (under 2 KB, no "
            "backticks). Do not edit active-context.md directly. Then continue the user's task.")
SMOKE = ({"tool_name": "Bash", "tool_input": {"command": "ls"}},
         {"tool_name": "Write", "tool_input": {"file_path": os.path.join(tempfile.gettempdir(), "wb-smoke.txt"),
                                               "content": "x"}})


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
        return f"HOOK EDIT BROKE {path}: {e.msg}"
    with tempfile.TemporaryDirectory() as logs:
        for p in SMOKE:
            r = subprocess.run([sys.executable, str(HERE / "guards" / "pretooluse.py")], capture_output=True,
                               timeout=30, input=json.dumps({**p, "session_id": "smoke", "cwd": str(HERE)}).encode(),
                               env={**os.environ, "GUARDS_LOG_DIR": logs})
            if r.returncode or b'"deny"' in r.stdout:
                return f"HOOK EDIT: the guard rejects a benign {p['tool_name']} call: {(r.stdout + r.stderr)[:300]!r}"
        logf = Path(logs) / "guards.log"
        bad = [ln for ln in (logf.read_text(encoding="utf-8").splitlines() if logf.exists() else [])
               if "skipped" in ln or "ERROR" in ln]
        if bad:
            return f"HOOK EDIT: a guard rule crashed on a benign call, so that check is OFF: {bad[0][:300]}"
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
    msgs = [x for x in (gate, REMINDER if fire else None) if x]
    if msgs:
        emit("\n\n".join(msgs))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
