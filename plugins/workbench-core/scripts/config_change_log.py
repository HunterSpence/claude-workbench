"""ConfigChange hook: one timestamped line per settings change (which source, which file), so a silent mid-session
change, such as a model pin flipping, can be traced afterwards. Useful evidence for a security review.
Never exits non-zero: exit 2 on this event would BLOCK the change."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wb  # noqa: E402

if __name__ == "__main__":
    try:
        d = _wb.read_event()
        _wb.append_line(_wb.log_dir() / "config-change.log",
                        f"{time.strftime('%Y-%m-%dT%H:%M:%S')} source={d.get('source') or 'unknown'} "
                        f"file={d.get('file_path')}")
    except Exception:
        pass
    sys.exit(0)
