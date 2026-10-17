"""SessionStart hook: a short banner, the model pins from the USER settings file, generic health
warnings, a pending precompact save, dated active-context items that are due, and the knowledge base's
active-context.md (re-read on every start, resume, clear and compact). Also, from <workbench home>/state/: setup pending,
a post-update verify pending (post-update-verify.json; one line, gone once `kit_update.py verify` has run), the first five routing rows, "managed policy changed", "knowledge verify: N failing"
(or a result older than 30 days) and, when the capability report is stale, a detached quick refresh (see extras()). It
stamps last_start in the hooks heartbeat. A pending precompact flag is looked up in the local KB state folder first,
then in <KB>/.state (an earlier kit's).

The pins come from <claude home>/settings.json only. Managed policy, server-managed settings and /model can
override them, so the line says so; /status shows what is actually in force. Effort per model comes from
modelSettings.<model>.effortLevel first, then the top-level effortLevel. No network, no probes: health
warnings read local files only (instruction import, a missing active-context).
Output is capped at 10,000 characters (UTF-16 units): the pins go first, then trailing active-context lines
behind a visible TRUNCATED marker. Always exits 0.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _wb  # noqa: E402
import precompact  # noqa: E402
try:
    import policy_snapshot  # noqa: E402
except Exception:    # the banner must survive a broken snapshot module; extras() then skips the policy line
    policy_snapshot = None

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


def _state(name):
    try:
        with open(_wb.workbench_home() / "state" / name, encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _flags(folder, fresh_days=None):
    """Names of the precompact flags in a folder (only those touched within fresh_days when given). Never raises."""
    names = set()
    try:
        for p in folder.glob("precompact-*.flag"):
            try:
                if fresh_days is None or time.time() - p.stat().st_mtime < fresh_days * 86400:
                    names.add(p.name)
            except OSError:
                continue
    except OSError:
        pass
    return names


def _short(x, n=40):
    return " ".join(str(x).split())[:n]


def start_report():
    """Start `report.py run --phase refresh --quick --detach` (WORKBENCH_REPORT_CLI = a stand-in script, for tests).
    True when something was started. report.py re-launches itself in the background, so this returns at once."""
    kit = Path(__file__).resolve().parents[3]
    stub = os.environ.get("WORKBENCH_REPORT_CLI")
    script = Path(stub) if stub else next((p for p in (kit / "bootstrap" / "report.py",
                                                       _wb.workbench_home() / "kit" / "bootstrap" / "report.py") if p.is_file()), None)
    if not script or not script.is_file():
        return False
    kw = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}   # detached
    subprocess.Popen([sys.executable, str(script), "run", "--phase", "refresh", "--quick", "--detach"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **kw)
    return True


def extras():
    """The runtime-assurance lines, each capped: setup pending (I2), the first five routing rows (I3b), managed policy
    changed (I20), the hooks heartbeat stamp (no line), a failing or
    30-day-old knowledge-verify result and a stale capability report (older than 7 days, or the policy changed and no
    refresh in a day) -> a detached quick refresh. Every part is best-effort: one failing never hides the others.
    ponytail: a refresh that keeps failing restarts every session."""
    out, changed = [], []
    try:
        st = _state("setup-state.json")
        if st and not (st.get("phase") == "done" and st.get("exit_code") in (None, 0)):
            it, bad = len(st.get("ask_it") or []), len(st.get("failed") or [])
            out.append(f"Setup pending: phase {_short(st.get('phase') or 'unknown')}" + (f", {it} item(s) for IT" if it else "")
                       + (f", {bad} failed" if bad else "") + (f". Next: {_short(st['next'], 160)}" if st.get("next") else ""))
    except Exception:
        pass
    try:   # post-update-verify.json (written by setup / kit_update.py, deleted by `kit_update.py verify`): ONE line, until the verify has run
        mk = _state("post-update-verify.json")
        if mk:
            cli = _wb.workbench_home() / "kit" / "bootstrap" / "kit_update.py"
            out.append(f"A post-update verify is pending (kit {_short(mk.get('version') or 'unknown', 20)}): on the user's next message, before "
                       f"anything else, run `{sys.executable} {cli.as_posix()} verify` (Bash timeout 600000 ms; on exit 6 run it again), show its "
                       "table.")
    except Exception:
        pass
    try:
        rows = [r for r in (_state("routing.effective.json").get("rows") or [])[:5] if isinstance(r, dict)]
        if rows:
            out.append("Model routing, first rows (* = a fallback model is in use):")
            out += [f"  {_short(r.get('id'))} {_short(r.get('persona'))} {re.sub('^claude-', '', _short(r.get('model')))}/"
                    f"{_short(r.get('effort'), 12)}{'*' if r.get('fallback_used') else ''}" for r in rows]
    except Exception:
        pass
    try:
        changed = policy_snapshot.status()["changed"]
        if changed:
            out.append(f"WARNING: managed policy changed since setup: {', '.join(changed)}; run setup.py doctor.")
    except Exception:
        pass
    _wb.heartbeat("last_start")        # every source (startup, resume, clear, compact); best-effort, never raises
    try:   # knowledge-verify.json (written by setup): a failing step, or a result gone stale
        kv = _state("knowledge-verify.json")
        failing = [_short(x, 24) for x in ((kv.get("summary") or {}).get("failing") or [])[:6]]
        if failing:
            out.append(f"WARNING: knowledge verify: {len(failing)} failing ({', '.join(failing)}); run setup.py doctor --deep.")
        elif kv:
            gen = datetime.fromisoformat(str(kv.get("generated") or "").replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - (gen if gen.tzinfo else gen.replace(tzinfo=timezone.utc))) > timedelta(days=30):
                out.append("NOTE: knowledge verify is older than 30 days; run setup.py doctor --deep.")
    except Exception:
        pass
    try:
        state, now = _wb.workbench_home() / "state", time.time()
        caps = [state / f"capability-{ph}.json" for ph in ("pre", "post", "refresh")]
        age = lambda f: now - f.stat().st_mtime if f.is_file() else float("inf")  # noqa: E731
        newest = min(age(f) for f in caps)
        if newest != float("inf") and (newest > 7 * 86400 or (changed and age(caps[2]) > 86400)) and start_report():
            out.append("The capability report is " + (f"{int(newest // 86400)} days old" if newest > 7 * 86400 else "out of date after the "
                       "policy change") + ": a quick refresh was started in the background.")
    except Exception:
        pass
    return out


def build(data):
    kb = _wb.kb_root()
    how = str(data.get("source") or "startup")
    sid = re.sub(r"[^A-Za-z0-9-]", "", str(data.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""))
    lines = [f"### Ready {date.today().isoformat()} ({how}). Knowledge base: {kb.as_posix()}"]
    if not kb.is_dir():
        lines.append("NOTE: the knowledge base folder does not exist. Run the workbench bootstrap, or copy "
                     "kb-template/ there. Until then /workbench-kb:save has nowhere to write.")
    else:
        mine = precompact.flag_path(kb, sid)
        legacy = _wb.legacy_kb_state_dir(kb)
        if sid and (mine.exists() or (legacy / mine.name).exists()):
            lines += ["", "!! PRECOMPACT SAVE PENDING: this session was compacted and what it knew is not yet in the "
                      "knowledge base. Before answering, run /workbench-kb:save (it reads the pre-compaction snapshot "
                      "and clears this flag).", ""]
        others = (_flags(mine.parent) | _flags(legacy, fresh_days=7)) - {mine.name}   # legacy: an earlier kit's
        if others:
            lines.append(f"NOTE: {len(others)} other session(s) owe a save after compaction (not yours to clear).")
    try:
        lines += health(kb)
    except Exception:
        pass
    lines += extras()
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
