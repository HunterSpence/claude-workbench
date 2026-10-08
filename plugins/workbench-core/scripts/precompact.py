"""PreCompact hook: snapshot the KB's active-context.md, then raise this session's precompact flag, so the next start
of this session tells Claude to run the save skill (compaction drops what the session knew). Prints nothing:
PreCompact stdout would become instructions for the compaction summary. Always exits 0.

Contract shared with workbench-kb's save_driver.py (it reads and clears the flag):
  <kb>/.state/precompact-<session id>.flag     the flag
  <kb>/.state/snapshots/active-context-<YYYYmmdd-HHMMSS>-<pid>.md   the snapshot (pruned after 14 days)
"""
import os
import re
import shutil
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _wb  # noqa: E402

KEEP_DAYS = 14


def flag_path(kb, sid):
    return kb / ".state" / f"precompact-{sid or 'nosession'}.flag"


def main():
    d = _wb.read_event()
    kb = _wb.kb_root()
    if not kb.is_dir():
        return
    sid = re.sub(r"[^A-Za-z0-9-]", "", str(d.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""))
    now = datetime.now()
    snaps = kb / ".state" / "snapshots"
    ac = kb / "active-context.md"
    try:
        if ac.exists():
            snaps.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ac, snaps / f"active-context-{now:%Y%m%d-%H%M%S}-{os.getpid()}.md")
    except OSError:
        pass
    try:
        f = flag_path(kb, sid)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"precompact_fired: {now:%Y-%m-%d %H:%M:%S}\ntrigger: {d.get('trigger') or 'unknown'}\n"
                     "action: run the save skill at the next start of this session\n", encoding="utf-8")
    except OSError:
        pass
    cutoff = f"{now - timedelta(days=KEEP_DAYS):%Y%m%d}"
    for p in snaps.glob("active-context-*.md") if snaps.is_dir() else ():
        m = re.search(r"-(\d{8})-\d{6}-", p.name)
        if m and m.group(1) < cutoff:
            try:
                p.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
