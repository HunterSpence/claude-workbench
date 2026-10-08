#!/usr/bin/env python3
"""PreToolUse hook entry point for the workbench guards (see engine.py). Fails open: exit 0 always."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import engine
except Exception:          # a broken engine must never block a tool call
    sys.exit(0)

if __name__ == "__main__":
    try:
        sys.exit(engine.main())
    except SystemExit:
        raise
    except BaseException:  # noqa: B036 - fail open on anything, including a stray BaseException
        sys.exit(0)
