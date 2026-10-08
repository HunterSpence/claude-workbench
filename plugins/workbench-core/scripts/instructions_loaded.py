"""InstructionsLoaded hook (observability only: the event takes no decision). OFF unless WORKBENCH_LOG_INSTRUCTIONS=1,
because it fires for every instruction file of every session. When on, it writes one JSON line per KIT-owned
instruction file (under the workbench folder or this plugin) to <workbench home>/logs/instructions-loaded.jsonl
(newest 2,000 kept): which file, why it loaded, its size as git stores it. The user's own instruction files are
never logged. Prints nothing; never raises."""
import datetime
import json
import os
import sys
from pathlib import Path

if os.environ.get("WORKBENCH_LOG_INSTRUCTIONS") != "1":
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wb  # noqa: E402

KEEP = 2000


def _kit_owned(path):
    try:
        p = Path(path).resolve()
    except OSError:
        return False
    for root in (_wb.workbench_home(), Path(__file__).resolve().parents[1]):
        try:
            p.relative_to(Path(root).resolve())
            return True
        except ValueError:
            continue
    return False


def main():
    d = _wb.read_event()
    path = str(d.get("file_path") or "")
    if not path or not _kit_owned(path):
        return
    size = None
    if os.path.isfile(path):
        b = Path(path).read_bytes()
        size = len(b) - b.count(b"\r\n")
    row = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "session_id": d.get("session_id"),
           "file_path": Path(path).as_posix(), "memory_type": d.get("memory_type"), "load_reason": d.get("load_reason"),
           "bytes": size}
    log = _wb.log_dir() / "instructions-loaded.jsonl"
    _wb.append_line(log, json.dumps(row))
    if log.stat().st_size > KEEP * 400:   # trim with 10% hysteresis
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        if len(lines) > KEEP * 1.1:
            tmp = log.with_name(log.name + f".{os.getpid()}.tmp")
            tmp.write_text("".join(lines[-KEEP:]), encoding="utf-8")
            os.replace(tmp, log)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
