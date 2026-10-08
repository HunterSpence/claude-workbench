#!/usr/bin/env python3
"""save_driver.py: the mechanical half of the save skill. Safe to run from several sessions at once.

  --pre                 audit + automatic history rollover + a recovery snapshot of active-context.md (its path is
                        printed as ac_base) + the journal window to fold. Prints JSON whose `next` list is the steps.
  --inbox-add TEXT      journal one line (append-only, collision-free); the next save folds it into active-context.
  --ac-write DRAFT --base AC_BASE
                        the ONLY writer of active-context.md: a 3-way merge (draft, base, live file) under the lock.
  --post [--domains d1,d2] [--note TEXT] [--files F ...] [--push]
                        credential scan (HARD GATE, exit 3) -> HOT.md caps (HARD GATE, exit 4) -> active-context cap
                        -> daily log -> clear this session's precompact flag -> reindex -> git commit (only when the
                        KB folder is a git repository) -> git push (only with --push AND a remote you configured)
                        -> metrics.
  --post --skip --note TEXT   record that this save was skipped (nothing significant happened).

Nothing is ever pushed by default. Exit codes: 0 ok (read `action_required` if present) · 1 unexpected error, or an
--ac-write conflict / busy lock · 2 --ac-write refused (missing draft or base; file untouched) · 3 credentials found ·
4 HOT.md over the hard cap.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_audit  # noqa: E402  (paths and caps: the one home)
import savelock  # noqa: E402
import secretscan  # noqa: E402

ROOT, STATE, SNAPSHOTS, AC, INBOX = kb_audit.ROOT, kb_audit.STATE, kb_audit.SNAPSHOTS, kb_audit.AC, kb_audit.INBOX
SAVE_LOCK = kb_audit.SAVE_LOCK
METRICS = STATE / "save-metrics.jsonl"
SESSION_ID = re.sub(r"[^A-Za-z0-9-]", "", os.environ.get("CLAUDE_CODE_SESSION_ID") or "")
LOCK_TIMEOUT = float(os.environ.get("SAVE_LOCK_TIMEOUT") or 120)
AC_GRACE_BYTES = 512        # a small overage completes the save and owes the trim to the next one
DAILY_CAP_LINES = 30
INBOX_WINDOW_H = 24         # every --pre re-offers everything since the last completed save (at least this long)
INBOX_OVERLAP_H = 6
INBOX_RETAIN_DAYS = 7
INBOX_FOLD_CAP_BYTES = 32_768
INBOX_MAX_CHARS = 8000
RECENT_SAVE_MIN = 15
STALE_DAYS = 7
_read = savelock.read_text


def _now():
    return datetime.now(timezone.utc)


def _h(text, n):
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:n]


def _ac_hash():
    return _h(_read(AC), 6) if AC.exists() else "noac00"


def _winpath(s):
    """Git Bash passes /c/dir/file; Windows Python needs C:/dir/file."""
    m = re.match(r"^/([a-zA-Z])/(.*)$", s or "")
    return f"{m.group(1).upper()}:/{m.group(2)}" if m and os.name == "nt" else s


def _flag(sid):
    """Contract with workbench-core's precompact.py: the flag it raises at compaction."""
    return STATE / f"precompact-{sid or 'nosession'}.flag"


def _my_flag():
    f = _flag(SESSION_ID)
    return f if SESSION_ID and f.exists() else None


def _need(report, msg):
    prev = report.get("action_required")
    report["action_required"] = f"{prev}  ALSO: {msg}" if prev else msg


def _run(cmd, timeout=120):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as e:
        return 1, "", str(e)[-200:]


# ── metrics ──────────────────────────────────────────────────────────────────────────────────────────────────
def _metric_rows():
    rows = []
    for line in _read(METRICS).splitlines():
        try:
            r = json.loads(line)
            if isinstance(r, dict):
                rows.append(r)
        except ValueError:
            continue
    return rows


def _ts(r, fmt="%Y-%m-%dT%H:%MZ"):
    try:
        return datetime.strptime(r.get("ts", ""), fmt).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _last_full_save():
    ts = [t for r in _metric_rows() if r.get("mode") != "skip" for t in [_ts(r)] if t]
    return max(ts) if ts else None


def _append_metric(row):
    """Read-decide-append ONE metrics row in one critical section -> 'recorded' | 'already' | 'busy'."""
    try:
        with savelock.filelock(savelock.lock_for(METRICS), timeout=LOCK_TIMEOUT):
            if any(r.get("key") == row["key"] for r in _metric_rows()):
                return "already"
            METRICS.parent.mkdir(parents=True, exist_ok=True)
            with METRICS.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(row, ensure_ascii=True) + "\n")
            return "recorded"
    except savelock.LockBusy:
        return "busy"


# ── the journal ──────────────────────────────────────────────────────────────────────────────────────────────
# active-context.md is rewritten whole by the model across several turns, and no lock can span a model turn. So
# sessions never edit it between saves: they append here, and appends cannot collide. Nothing is "consumed": every
# --pre re-offers the whole window since the last completed save, so an entry a lost race dropped comes back.
def _inbox_rows():
    out = []
    for line in _read(INBOX).splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("text"):
            out.append(r)
    return out


def inbox_add(text):
    text = " ".join((text or "").split())
    if not text:
        print(json.dumps({"error": "--inbox-add needs non-empty text"}))
        return 1
    warns = []
    spans = secretscan.scan_text(text, values_only=True)   # mask, never reject: a refused entry is lost work
    for a, b in reversed(spans):
        text = text[:a] + "[REDACTED: credential shape; refer to it by name]" + text[b:]
    if spans:
        warns.append(f"{len(spans)} credential-shaped value(s) masked before journalling")
    if len(text) > INBOX_MAX_CHARS:
        text = text[:INBOX_MAX_CHARS] + f" ...[TRUNCATED {len(text) - INBOX_MAX_CHARS} chars]"
    nbytes = len(text.encode("utf-8"))
    if nbytes > 2048:
        warns.append(f"entry is {nbytes} B (>2 KB): every --pre re-offers it until it ages out")
    entry = {"ts": _now().strftime("%Y-%m-%dT%H:%M:%SZ"), "session": SESSION_ID or "unknown", "pid": os.getpid(),
             "text": text}
    INBOX.parent.mkdir(parents=True, exist_ok=True)
    savelock.append_line(INBOX, json.dumps(entry, ensure_ascii=True))
    out = {"result": "journalled", "ts": entry["ts"], "bytes": nbytes}
    if warns:
        out["warnings"] = warns
    print(json.dumps(out, indent=1))
    return 0


def _inbox_survey(now):
    """Prune aged-out entries (never one inside the window) and return (window entries, pruned, window start)."""
    last = _last_full_save()
    win_cut = (min(now - timedelta(hours=INBOX_WINDOW_H), last - timedelta(hours=INBOX_OVERLAP_H)) if last
               else now - timedelta(days=INBOX_RETAIN_DAYS))
    keep_cut = min(now - timedelta(days=INBOX_RETAIN_DAYS), win_cut)
    if not INBOX.exists():
        return [], 0, win_cut
    pruned = 0
    try:
        with savelock.filelock(savelock.lock_for(INBOX), timeout=LOCK_TIMEOUT):
            rows = _inbox_rows()
            keep = [r for r in rows if (_ts(r, "%Y-%m-%dT%H:%M:%SZ") or now) >= keep_cut]
            pruned = len(rows) - len(keep)
            if pruned:
                savelock.atomic_write(INBOX, "".join(json.dumps(r, ensure_ascii=True) + "\n" for r in keep))
    except savelock.LockBusy:
        keep = _inbox_rows()
    fold_cut = last - timedelta(hours=INBOX_OVERLAP_H) if last else win_cut
    out = []
    for r in keep:
        t = _ts(r, "%Y-%m-%dT%H:%M:%SZ")
        if t is not None and t < win_cut:
            continue
        out.append({"ts": r.get("ts"), "session": str(r.get("session") or "?")[:8], "text": r.get("text"),
                    "mine": bool(SESSION_ID) and r.get("session") == SESSION_ID,
                    "folded": t is not None and t < fold_cut})
    out.sort(key=lambda e: e["ts"] or "")
    return out, pruned, win_cut


def _reap(report, keep=None):
    """Sweep what dead sessions leave behind; never this session's own files."""
    now = _now().timestamp()
    sweep = [(p, STALE_DAYS) for p in STATE.glob("precompact-*.flag") if p != keep]
    sweep += [(p, 1) for p in ROOT.rglob("*.tmp") if re.search(r"\.\d+\.tmp$", p.name)]
    sweep += [(p, 7) for p in STATE.glob("inbox-window.*.jsonl") if not (SESSION_ID and SESSION_ID in p.name)]
    sweep += [(p, 14) for p in SNAPSHOTS.glob("*.md")]
    reaped = []
    for p, days in sweep:
        try:
            if p.stat().st_mtime < now - days * 86400:
                p.unlink()
                reaped.append(p.name)
        except OSError:
            continue
    if reaped:
        report["reaped"] = reaped[:20]


# ── --pre ────────────────────────────────────────────────────────────────────────────────────────────────────
def pre(verbose=False):
    if not kb_audit.domains():
        print(json.dumps({"error": f"no knowledge base at {ROOT.as_posix()} (no domain folder with a HOT.md)",
                          "action_required": "run the workbench bootstrap, or copy kb-template/ to that folder"}))
        return 1
    out = {"driver": "workbench-1", "session": SESSION_ID or "unknown", "kb_root": ROOT.as_posix()}
    mine = _my_flag()
    _reap(out, keep=mine)
    out["resume_pending"] = mine is not None
    out["mode_hint"] = "precompact-resume" if mine else "inline"
    out["stamp"] = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")   # the clock for history headings
    others = [p.name for p in STATE.glob("precompact-*.flag") if p != mine]
    if others:
        out["other_sessions_pending"] = others
    out["concurrent_save_active"] = savelock.is_locked(SAVE_LOCK)

    now = _now()
    inbox, pruned, win_cut = _inbox_survey(now)
    win = STATE / f"inbox-window.{SESSION_ID or os.getpid()}.jsonl"
    new = [json.dumps(e, ensure_ascii=False) + "\n" for e in inbox if not e["folded"]]
    folded = [json.dumps(e, ensure_ascii=False) + "\n" for e in inbox if e["folded"]]
    room, shown = INBOX_FOLD_CAP_BYTES - sum(len(x.encode("utf-8")) for x in new), 0
    for x in reversed(folded):   # newest folded first, while the cap has room
        room -= len(x.encode("utf-8"))
        if room < 0:
            break
        shown += 1
    omitted = len(folded) - shown
    marker = [json.dumps({"ts": None, "marker": True, "text": f"[{omitted} older, already-folded entries not shown; "
                          f"all are still in {INBOX.as_posix()}]"}) + "\n"] if omitted else []
    savelock.atomic_write(win, "".join(marker + folded[omitted:] + new))
    out.update(inbox_file=win.as_posix(), inbox_pending=len(new), inbox_folded=len(folded),
               inbox_window_from=win_cut.strftime("%Y-%m-%dT%H:%M:%SZ"))
    if pruned:
        out["inbox_pruned"] = pruned

    try:   # the 3-way merge ancestor for --ac-write; a missing file snapshots as EMPTY (a real ancestor)
        snap = SNAPSHOTS / f"active-context-presave-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}.md"
        savelock.atomic_write(snap, _read(AC))
        out["ac_base"] = snap.as_posix()
    except OSError as e:
        _need(out, f"active-context snapshot failed ({e}): re-run --pre")

    rolled = []
    try:   # rollovers rewrite history.md whole: one writer at a time, audit re-read inside the lock
        with savelock.filelock(SAVE_LOCK, timeout=LOCK_TIMEOUT):
            rows = kb_audit.audit()
            for r in rows:
                if not r.get("history_over_cap"):
                    continue
                if r.get("history_prev_month_entries", 0) > 0:
                    rolled.append(kb_audit.rollover(r["domain"]))
                    if kb_audit.lf_bytes(kb_audit.KB / r["domain"] / "history.md") <= kb_audit.HIST_BYTES_CAP:
                        continue
                rolled.append(kb_audit.rollover_age_adaptive(r["domain"]))
            if rolled:
                rows = kb_audit.audit()
    except savelock.LockBusy:
        rows = kb_audit.audit()
        out["rollover"] = "skipped: another save held the lock"
    out["rollovers_run"] = rolled
    out["over_cap_hot"] = [r["domain"] for r in rows if r.get("hot_over_cap")]
    out["warn_hot"] = [r["domain"] for r in rows if r.get("hot_warn") and not r.get("hot_over_cap")]
    out["history_still_over_cap"] = [r["domain"] for r in rows if r.get("history_over_cap")]
    out["domains"] = kb_audit.domains()
    if verbose:
        out["audit"] = rows

    mrows = _metric_rows()
    recent = [r for r in mrows if (_ts(r) or now - timedelta(days=1)) >= now - timedelta(minutes=RECENT_SAVE_MIN)]
    out["recent_other_saves"] = [{"ts": r.get("ts"), "domains": r.get("domains")} for r in recent][-5:]
    last = _last_full_save()
    out["last_save_minutes_ago"] = int((now - last).total_seconds() // 60) if last else None   # the skip gate reads it
    out["ac_hash"] = _ac_hash()
    today = now.strftime("%Y-%m-%d")
    out["ac_hash_already_saved"] = any(str(r.get("ts", "")).startswith(today) and r.get("ac_hash") == out["ac_hash"]
                                       for r in mrows)
    out["ac_bytes"] = kb_audit.lf_bytes(AC)
    out["ac_cap"] = kb_audit.AC_BYTES_CAP
    out["ac_bytes_left"] = kb_audit.AC_BYTES_CAP - out["ac_bytes"]

    nxt = []
    if mine:
        snap = max(SNAPSHOTS.glob("active-context-2*.md"), key=lambda p: p.stat().st_mtime, default=None)
        nxt.append(f"this session was compacted: read {(snap or AC).as_posix()} (the pre-compaction snapshot) and write "
                   "what it knew to the KB; --post then clears the flag")
    if out["ac_hash_already_saved"]:
        nxt.append("active-context is unchanged since a save today: if nothing new happened, run --post --skip --note "
                   "'<why>' and stop")
    if inbox:
        nxt.append(f"fold the {len(new)} new journal entries in {win.as_posix()} into your active-context draft"
                   + (f"; the {shown} folded:true ones were offered before: re-add one only if active-context lost it"
                      if shown else ""))
    if out["ac_bytes_left"] < 0:
        nxt.append(f"trim {-out['ac_bytes_left']} B from active-context in this same rewrite")
    for d in out["over_cap_hot"]:
        nxt.append(f"demote from {d}/HOT.md before --post (over the hard cap): kb_demote.py --domain {d} --match \"<text>\"")
    if out["concurrent_save_active"] or out["recent_other_saves"]:
        nxt.append("another session is saving or just saved: --ac-write merges its lines; mention it")
    nxt.append(f"KB writes (history headings use {out['stamp']!r}), then --ac-write <draft> --base <ac_base>, then --post")
    out["next"] = nxt
    first = ("driver", "session", "mode_hint", "resume_pending", "ac_base", "ac_bytes_left", "ac_cap", "ac_bytes",
             "inbox_file", "inbox_pending", "next")
    print(json.dumps({**{k: out[k] for k in first if k in out}, **out}, indent=1))
    return 0


# ── --ac-write ───────────────────────────────────────────────────────────────────────────────────────────────
_SEP = "\x1f"   # a separator line between every line, so edits to NEIGHBOURING lines never conflict


def _merge3(ours, base, theirs):
    """(merged, n_conflicts) via `git merge-file`. Without git, a changed file is reported as one conflict holding
    both versions, for the model to merge by hand."""
    def spaced(text):
        return "\n".join(x for line in text.split("\n") for x in (line, _SEP)) + "\n"
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, text in (("ours", ours), ("base", base), ("theirs", theirs)):
            p = Path(d) / name
            p.write_bytes(spaced(text).encode("utf-8"))
            paths.append(str(p))
        try:
            r = subprocess.run(["git", "merge-file", "-p", "-L", "MY DRAFT", "-L", "BASE", "-L", "OTHER SESSION", *paths],
                               capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            return f"<<<<<<< MY DRAFT\n{ours}\n=======\n{theirs}\n>>>>>>> OTHER SESSION", 1
        if r.returncode < 0 or r.returncode > 127:
            raise RuntimeError(f"git merge-file failed: {r.stderr.decode(errors='replace').strip()}")
        lines = [ln for ln in r.stdout.decode("utf-8", errors="replace").split("\n") if ln != _SEP]
        if lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines), r.returncode


def ac_write(draft_path, base_path):
    draft = Path(_winpath(draft_path))
    ours = _read(draft) if draft.exists() else ""
    if not ours.strip():
        print(json.dumps({"status": "error", "error": f"draft missing or empty: {draft}"}))
        return 2
    if not base_path or not Path(_winpath(base_path)).exists():
        print(json.dumps({"status": "error", "error": "--base is required and must exist: pass the ac_base that --pre "
                          "(or your previous --ac-write) printed. Without it this write would overwrite other sessions."}))
        return 2
    base = Path(_winpath(base_path))
    out = {"draft": draft.as_posix(), "base": base.as_posix()}
    try:
        with savelock.filelock(SAVE_LOCK, timeout=LOCK_TIMEOUT):
            theirs, base_text = _read(AC), _read(base)
            if theirs == base_text or theirs == ours:
                merged, conflicts, out["merge"] = ours, 0, "direct"
            else:
                merged, conflicts = _merge3(ours, base_text, theirs)
                out["merge"] = "3-way (another session wrote since your --pre)"
            stamp = f"{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}"
            if conflicts:
                cpath, nbase = SNAPSHOTS / f"ac-merge-conflict-{stamp}.md", SNAPSHOTS / f"active-context-presave-{stamp}.md"
                savelock.atomic_write(cpath, merged)
                savelock.atomic_write(nbase, theirs)
                out.update(status="conflict", conflicts=conflicts, conflict_file=cpath.as_posix(), base=nbase.as_posix(),
                           action_required=f"Resolve the <<<<<<< / >>>>>>> markers in {cpath.as_posix()} (keep both "
                                           f"sessions' facts), then: --ac-write {cpath.as_posix()} --base {nbase.as_posix()}")
                print(json.dumps(out, indent=1))
                return 1
            savelock.atomic_write(AC, merged, newline="\n")
            nbase = SNAPSHOTS / f"active-context-presave-{stamp}.md"   # pass THIS to any further --ac-write
            savelock.atomic_write(nbase, merged, newline="\n")
            out["ac_base"] = nbase.as_posix()
    except savelock.LockBusy:
        out.update(status="busy", action_required="another session held the save lock: re-run --ac-write")
        print(json.dumps(out, indent=1))
        return 1
    n = len(merged.encode("utf-8"))
    out.update(status="written", ac_bytes=n, ac_cap=kb_audit.AC_BYTES_CAP, ac_bytes_left=kb_audit.AC_BYTES_CAP - n)
    print(json.dumps(out, indent=1))
    return 0


# ── --post ───────────────────────────────────────────────────────────────────────────────────────────────────
def _daily_log(domains, note):
    ts = datetime.now()
    daily = kb_audit.DAILY / f"{ts:%Y-%m-%d}.md"
    suffix = f"[{','.join(domains)}] {' '.join(note.split())[:220]}"
    lines = _read(daily).splitlines() if daily.exists() else [f"# {ts:%Y-%m-%d}"]
    if any(ln.endswith(suffix) for ln in lines):   # re-runs of one save log once
        return f"{daily.as_posix()} (already logged)"
    lines.append(f"- {ts:%H:%M} {suffix}")
    if len(lines) > DAILY_CAP_LINES:
        lines = [lines[0]] + lines[-(DAILY_CAP_LINES - 1):]
    savelock.atomic_write(daily, "\n".join(lines) + "\n")
    return daily.as_posix()


def _cred_scan(files):
    res = {"findings": [], "missing": []}
    for f in files:
        p = Path(f)
        if not p.is_file():
            res["missing"].append(f)
            continue
        for x in secretscan.findings(_read(p)):
            res["findings"].append({"file": p.as_posix(), **x})
    return res


def _git_commit(note, push):
    """Commit the KB folder if it is a git repository. Push only when asked AND a remote is configured."""
    if not (ROOT / ".git").exists():
        return "skipped (the KB folder is not a git repository)", None
    rc, out, err = _run(["git", "-C", str(ROOT), "add", "-A"])
    if rc:
        return f"failed: git add: {(err or out)[:120]}", None
    rc, out, err = _run(["git", "-C", str(ROOT), "commit", "-q", "-m", f"kb save: {' '.join(note.split())[:120]}"])
    commit = "ok" if rc == 0 else "nothing to commit" if "nothing" in (out + err).lower() else f"failed: {(err or out)[:160]}"
    if not push:
        return commit, "skipped (no --push)"
    rc, remotes, _ = _run(["git", "-C", str(ROOT), "remote"])
    if not remotes.strip():
        return commit, "skipped (--push given but no remote is configured)"
    rc, out, err = _run(["git", "-C", str(ROOT), "push"], timeout=180)
    return commit, ("ok" if rc == 0 else f"failed: {(err or out).splitlines()[-1][:160] if (err or out) else rc}")


def post(args):
    ts = _now()
    report = {"driver": "workbench-1", "ts": ts.strftime("%Y-%m-%dT%H:%MZ"), "kb_root": ROOT.as_posix()}
    domains = [d.strip() for d in (args.domains or "ops").split(",") if d.strip()]
    if args.skip:
        key = f"{ts:%Y%m%d-%H%M}-skip-{_h(args.note or '', 4)}"
        res = _append_metric({"ts": report["ts"], "key": key, "mode": "skip", "domains": domains,
                              "ac_hash": _ac_hash(), "note": (args.note or "")[:200]})
        print(json.dumps({"result": {"busy": "skip NOT recorded (metrics lock busy)", "already": "skip already recorded"}
                          .get(res, "skip recorded"), "key": key}, indent=1))
        return 1 if res == "busy" else 0
    mine = _my_flag()
    report["mode"] = "precompact-resume" if mine else "inline"

    files = [_winpath(x) for a in (args.files or []) for x in ([a] if Path(_winpath(a)).exists() else a.split())]
    if AC.exists() and AC.as_posix() not in [Path(f).as_posix() for f in files]:
        files.append(str(AC))
    cred = _cred_scan(files)                                            # 1. HARD GATE
    report["cred_scan"] = "FINDINGS" if cred["findings"] else "CLEAN"
    if cred["missing"]:
        report["cred_unscanned"] = cred["missing"][:6]
        _need(report, f"{len(cred['missing'])} --files path(s) not found, so NOT scanned: pass real paths")
    if cred["findings"]:
        report["cred_findings"] = cred["findings"][:20]
        _need(report, "Replace each finding with [REDACTED] and refer to the credential by name, then re-run --post.")
        print(json.dumps(report, indent=1))
        return 3

    over = [r["domain"] for r in kb_audit.audit() if r.get("hot_over_cap")]   # 2. HARD GATE (touched domains)
    report["hot_over_cap_all"] = over
    blocking = [d for d in over if d in domains]
    if blocking:
        _need(report, f"HOT.md over the {kb_audit.HOT_HARDFAIL_BYTES // 1024} KB hard cap in {blocking}: run "
                      "kb_demote.py (a verbatim move), never compress in place, then re-run --post.")
        print(json.dumps(report, indent=1))
        return 4

    ac_bytes = kb_audit.lf_bytes(AC)                                    # 3. active-context cap (grace band)
    report["ac_bytes"], report["ac_cap"] = ac_bytes, kb_audit.AC_BYTES_CAP
    for msg in kb_audit.ac_report(_read(AC))["advisories"].values():
        _need(report, "active-context.md: " + msg)
    if ac_bytes > kb_audit.AC_BYTES_CAP + AC_GRACE_BYTES:
        _need(report, f"active-context.md is {ac_bytes} B, past the cap plus the {AC_GRACE_BYTES} B grace band. Move "
                      "detail into KB notes, --ac-write again, re-run --post. THIS SAVE DID NOT COMPLETE.")
        print(json.dumps(report, indent=1))
        return 0
    if ac_bytes > kb_audit.AC_BYTES_CAP:
        report["ac_trim_owed"] = ac_bytes - kb_audit.AC_BYTES_CAP
        _need(report, "active-context.md is over its cap but inside the grace band, so THIS SAVE COMPLETED; trim it "
                      "on the next save.")

    try:                                                                # 4. daily log + this session's flag
        with savelock.filelock(SAVE_LOCK, timeout=LOCK_TIMEOUT):
            report["daily_log"] = _daily_log(domains, args.note or "session save")
            if mine:
                mine.unlink(missing_ok=True)
                report["flag_cleared"] = mine.name
    except savelock.LockBusy:
        report["daily_log"] = "skipped: lock busy"
        _need(report, "daily log and flag clear skipped under lock contention: re-run --post when the other save ends")

    try:                                                                # 5. search index
        import kb_index
        report["reindex"] = kb_index.build()
    except Exception as e:
        report["reindex"] = f"failed ({type(e).__name__}: {e})"[:200]
        _need(report, "reindex failed: kb_search.py rebuilds the index on its next run")

    report["git_commit"], report["git_push"] = _git_commit(args.note or "session save", args.push)   # 6. git
    if str(report["git_push"]).startswith("failed"):
        _need(report, "git push failed: the commit is local only")

    key = f"{ts:%Y%m%d}-{domains[0]}-{_ac_hash()}-{_h(args.note or '', 4)}"   # 7. metrics
    res = _append_metric({"ts": report["ts"], "key": key, "mode": report["mode"], "domains": domains,
                          "ac_hash": _ac_hash(), "reindex": str(report["reindex"])[:80], "note": (args.note or "")[:400]})
    report["metrics"] = {"busy": "NOT recorded (lock busy): re-run --post", "already": "already recorded"}.get(res, "recorded")
    print(json.dumps(report, indent=1))
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    p = argparse.ArgumentParser(description="The /workbench-kb:save skill's driver (see the module docstring).")
    p.add_argument("--pre", action="store_true")
    p.add_argument("--post", action="store_true")
    p.add_argument("--inbox-add", metavar="TEXT")
    p.add_argument("--ac-write", metavar="DRAFT")
    p.add_argument("--base", metavar="AC_BASE")
    p.add_argument("--skip", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--domains")
    p.add_argument("--note")
    p.add_argument("--files", nargs="*")
    p.add_argument("--push", action="store_true", help="with --post: also git push (needs a remote you configured)")
    a = p.parse_args()
    try:
        if a.inbox_add is not None:
            return inbox_add(a.inbox_add)
        if a.ac_write:
            return ac_write(a.ac_write, a.base)
        if a.pre:
            return pre(a.verbose)
        if a.post:
            return post(a)
    except PermissionError as e:
        print(json.dumps({"status": "error", "error": f"file held open by another process: {e}"[:300],
                          "action_required": "re-run the same command (writes are atomic, re-runs idempotent)"}))
        return 1
    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
