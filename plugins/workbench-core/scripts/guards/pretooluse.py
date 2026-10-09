#!/usr/bin/env python3
"""PreToolUse hook entry point for the workbench guards (see engine.py). Fails open: exit 0 always.
Every invocation first stamps the guard heartbeat (_wb.heartbeat), so SessionStart can tell when the guards stop running."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import engine
except Exception:          # a broken engine must never block a tool call
    engine = None

if __name__ == "__main__":
    try:
        sys.path.insert(1, os.path.dirname(HERE))   # scripts/ (engine puts it there too)
        import _wb
        _wb.heartbeat(True)    # best-effort: an unwritable state folder changes nothing
    except BaseException:  # noqa: B036
        pass
    try:
        sys.exit(engine.main() if engine else 0)
    except SystemExit:
        raise
    except BaseException:  # noqa: B036 - fail open on anything, including a stray BaseException
        sys.exit(0)
