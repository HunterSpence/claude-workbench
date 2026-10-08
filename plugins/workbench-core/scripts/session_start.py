"""SessionStart hook: a short banner, the model pins from the USER settings file, the guard status, a pending
precompact save, and the knowledge base's active-context.md (re-read on every start, resume, clear and compact).

The pins come from <claude home>/settings.json only. Managed policy, server-managed settings and /model can
override them, so the line says so; /status shows what is actually in force. No network, no health probes.
Output is capped at 10,000 characters (UTF-16 units): the pins go first, then trailing active-context lines
behind a visible TRUNCATED marker. Always exits 0.
"""
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _wb  # noqa: E402
import precompact  # noqa: E402

CAP = 10_000


def u16(s):
    return len(s.encode("utf-16-le")) // 2


def _fm(path):
    m = re.match(r"---\r?\n(.*?)\r?\n---", path.read_text(encoding="utf-8-sig", errors="replace"), re.S)
    fm, v = m.group(1) if m else "", {}
    for k in ("name", "model", "effort"):
        hit = re.search(rf"(?m)^{k}:\s*[\"']?([^\"'\r\n]+)", fm)
        v[k] = hit.group(1).strip() if hit else "inherit"
    return v


def pins():
    try:
        st = json.loads((_wb.claude_home() / "settings.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        st = {}
    env = st.get("env") or {}
    agents = []
    for f in sorted((HERE.parent / "agents").glob("*.md"), key=lambda p: p.name.lower()):
        try:
            v = _fm(f)
        except OSError:
            continue
        agents.append(f"{f.stem if v['name'] == 'inherit' else v['name']}={re.sub('^claude-', '', v['model'])}/{v['effort']}")
    fb = st.get("fallbackModel")
    line = (f"PINS (user settings; managed policy may override, /status shows what is in force): "
            f"main={st.get('model') or 'default'}/{st.get('effortLevel') or 'default'} "
            f"fallback={','.join(fb) if isinstance(fb, list) else fb or 'none'} "
            f"subagents={env.get('CLAUDE_CODE_SUBAGENT_MODEL') or 'inherit'}"
            + (f" · agents: {' '.join(agents)}" if agents else ""))
    return line if len(line) <= 450 else line[:449] + "…"


def guard_status():
    """Mirrors rulepacks/corporate.cfg(): no file or an unreadable one means ON with no approved hosts."""
    c = {}
    try:
        with open(_wb.workbench_home() / "corporate-allowlist.json", encoding="utf-8-sig") as f:
            c = json.load(f)
    except (OSError, ValueError):
        pass
    c = c if isinstance(c, dict) else {}
    if c.get("enabled") is False:
        return "Guards: generic only (the corporate pack is turned off in corporate-allowlist.json)."
    n = len(c.get("git_remote_hosts") or [])
    return (f"Guards: generic + corporate ({n} approved git host(s)" +
            ("; every push to a remote host is refused until the user adds hosts)." if not n else ")."))


def build(data):
    kb = _wb.kb_root()
    how = str(data.get("source") or "startup")
    sid = re.sub(r"[^A-Za-z0-9-]", "", str(data.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""))
    lines = [f"### Ready {date.today().isoformat()} ({how}). Knowledge base: {kb.as_posix()}", guard_status()]
    if not kb.is_dir():
        lines.append("NOTE: the knowledge base folder does not exist. Run the workbench bootstrap, or copy "
                     "kb-template/ there. Until then the save skill has nowhere to write.")
    else:
        mine = precompact.flag_path(kb, sid)
        if sid and mine.exists():
            lines += ["", "!! PRECOMPACT SAVE PENDING: this session was compacted and what it knew is not yet in the "
                      "knowledge base. Before answering, run the save skill (it reads the pre-compaction snapshot "
                      "and clears this flag).", ""]
        others = [p for p in (kb / ".state").glob("precompact-*.flag") if p != mine]
        if others:
            lines.append(f"NOTE: {len(others)} other session(s) owe a save after compaction (not yours to clear).")
    head = "\n".join(lines)
    try:
        pin = pins()
    except Exception:
        pin = None
    try:
        ac = (kb / "active-context.md").read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    except OSError:
        ac = ""
    ac_head = "--- active-context.md (live; its only writer is the save driver) ---\n"
    marker = f"\n[TRUNCATED: Read {(kb / 'active-context.md').as_posix()} for the rest]"

    def out(h, body):
        return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                  "additionalContext": h + ("\n\n" + body if body else "")}},
                          ensure_ascii=False)

    body = ac_head + ac if ac.strip() else ""
    s = out(f"{head}\n{pin}" if pin else head, body)
    if u16(s) > CAP - 500:   # pins go first; active-context wins the budget
        s = out(head, body)
    if u16(s) > CAP:
        acl = ac.split("\n")
        for n in range(len(acl) - 1, 0, -1):
            s = out(head, ac_head + "\n".join(acl[:n]) + marker)
            if u16(s) <= CAP:
                break
        else:
            s = out(head, f"[active-context.md too large to inline: Read {(kb / 'active-context.md').as_posix()}]")
    return s


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        sys.stdout.write(build(_wb.read_event()))
    except Exception:
        pass
    sys.exit(0)
