"""SessionStart hook: a short banner, the model pins from the USER settings file, the guard status, generic health
warnings, a pending precompact save, dated active-context items that are due, and the knowledge base's
active-context.md (re-read on every start, resume, clear and compact).

The pins come from <claude home>/settings.json only. Managed policy, server-managed settings and /model can
override them, so the line says so; /status shows what is actually in force. Effort per model comes from
modelSettings.<model>.effortLevel first, then the top-level effortLevel. No network, no probes: health
warnings read local files only (instruction import, guard errors in the last day, a missing active-context).
Output is capped at 10,000 characters (UTF-16 units): the pins go first, then trailing active-context lines
behind a visible TRUNCATED marker. Always exits 0.
"""
import json
import os
import re
import sys
import time
from datetime import date, timedelta
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
    env, ms = st.get("env") or {}, st.get("modelSettings") or {}
    eff = lambda m: ((ms.get(m) or {}) if isinstance(ms, dict) and m else {}).get("effortLevel")  # noqa: E731
    main, worker = st.get("model"), env.get("CLAUDE_CODE_SUBAGENT_MODEL")
    agents = []
    for f in sorted((HERE.parent / "agents").glob("*.md"), key=lambda p: p.name.lower()):
        try:
            v = _fm(f)
        except OSError:
            continue
        agents.append(f"{f.stem if v['name'] == 'inherit' else v['name']}={re.sub('^claude-', '', v['model'])}/{v['effort']}")
    fb = st.get("fallbackModel")
    line = (f"PINS (user settings; managed policy may override, /status shows what is in force): "
            f"main={main or 'default'}/{eff(main) or st.get('effortLevel') or 'default'} "
            f"fallback={','.join(fb) if isinstance(fb, list) else fb or 'none'} "
            f"worker={worker or 'inherit'}/{eff(worker) or 'default'} "
            f"haiku={env.get('ANTHROPIC_DEFAULT_HAIKU_MODEL') or env.get('ANTHROPIC_SMALL_FAST_MODEL') or 'default'}"
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


def health(kb):
    """Generic, actionable warnings from local files only."""
    w = []
    home = _wb.claude_home()
    if (_wb.workbench_home() / "instructions" / "CLAUDE.md").exists():
        try:
            imported = "@workbench/instructions/CLAUDE.md" in (home / "CLAUDE.md").read_text(encoding="utf-8-sig")
        except OSError:
            imported = False
        if not imported:
            w.append(f"WARNING: {(home / 'CLAUDE.md').as_posix()} no longer imports the workbench instructions "
                     "(@workbench/instructions/CLAUDE.md); re-run the installer or add the line back.")
    log = Path(os.environ.get("GUARDS_LOG_DIR") or _wb.log_dir()) / "guards.log"
    try:
        if time.time() - log.stat().st_mtime < 86400 and log.stat().st_size < 4_000_000:
            cut = (date.today() - timedelta(days=1)).isoformat()
            n = sum(1 for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()
                    if " ERROR " in ln and ln[:10] >= cut)
            if n:
                w.append(f"WARNING: {n} guard error(s) since yesterday (the guards failed open for those calls): "
                         f"see {log.as_posix()}")
    except OSError:
        pass
    try:
        user = (_wb.workbench_home() / "USER.md").read_text(encoding="utf-8-sig")
    except OSError:
        user = None
    if user is None or re.search(r"<(?:first name|e\.g\.)|<fact>", user):
        w.append("NOTE: USER.md is " + ("missing" if user is None else "still the blank template") + ": suggest the "
                 "user run /workbench-core:onboard (a five-minute interview that fills it in).")
    if kb.is_dir() and not (kb / "active-context.md").exists():
        w.append("NOTE: active-context.md is missing from the knowledge base; /workbench-kb:save recreates it.")
    return w


DATE = re.compile(r"\b(20\d\d-[01]\d-[0-3]\d)\b")
DONE = re.compile(r"(?i)~~|\[x\]|\bdone\b|\bclosed\b|\bresolved\b|\bsuperseded\b|\u2705")


def due_items(ac, today=None, days=2, cap=6):
    """Open active-context lines carrying a date no later than today + days: surfaced at the top."""
    today = today or date.today()
    limit = (today + timedelta(days=days)).isoformat()
    hits = []
    for ln in ac.splitlines():
        ds = DATE.findall(ln)
        if ds and min(ds) <= limit and not DONE.search(ln) and not ln.lstrip().startswith("#"):
            tag = "OVERDUE" if min(ds) < today.isoformat() else "DUE"
            hits.append(f"  {tag} {' '.join(ln.split())[:160]}")
    return hits[:cap]


def build(data):
    kb = _wb.kb_root()
    how = str(data.get("source") or "startup")
    sid = re.sub(r"[^A-Za-z0-9-]", "", str(data.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""))
    lines = [f"### Ready {date.today().isoformat()} ({how}). Knowledge base: {kb.as_posix()}", guard_status()]
    if not kb.is_dir():
        lines.append("NOTE: the knowledge base folder does not exist. Run the workbench bootstrap, or copy "
                     "kb-template/ there. Until then /workbench-kb:save has nowhere to write.")
    else:
        mine = precompact.flag_path(kb, sid)
        if sid and mine.exists():
            lines += ["", "!! PRECOMPACT SAVE PENDING: this session was compacted and what it knew is not yet in the "
                      "knowledge base. Before answering, run /workbench-kb:save (it reads the pre-compaction snapshot "
                      "and clears this flag).", ""]
        others = [p for p in (kb / ".state").glob("precompact-*.flag") if p != mine]
        if others:
            lines.append(f"NOTE: {len(others)} other session(s) owe a save after compaction (not yours to clear).")
    try:
        lines += health(kb)
    except Exception:
        pass
    head = "\n".join(lines)
    try:
        pin = pins()
    except Exception:
        pin = None
    try:
        ac = (kb / "active-context.md").read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    except OSError:
        ac = ""
    try:
        due = due_items(ac)
    except Exception:
        due = []
    if due:
        head += "\nDated items due within two days or overdue (mention them in your first reply):\n" + "\n".join(due)
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
