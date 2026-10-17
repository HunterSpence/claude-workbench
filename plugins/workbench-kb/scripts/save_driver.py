#!/usr/bin/env python3
"""save_driver.py: the mechanical half of the save skill. Safe to run from several sessions at once.

  --pre                 audit + automatic history rollover + a recovery snapshot of active-context.md (its path is
                        printed as ac_base) + the journal window to fold + a hash of every note (the baseline --post
                        compares against). Prints JSON whose `next` list is the steps.
  --inbox-add TEXT      journal one line (append-only, collision-free); the next save folds it into active-context.
  --ac-write DRAFT --base AC_BASE
                        the ONLY writer of active-context.md: a 3-way merge (draft, base, live file) under the lock.
  --post [--domains d1,d2] [--note TEXT] [--files F ...] [--push]
                        credential scan (HARD GATE, exit 3) -> HOT.md caps (HARD GATE, exit 4) -> active-context cap
                        -> daily log -> clear this session's precompact flag -> `updated:` stamp (only notes named by
                        --files whose bytes changed since --pre; never one past its size cap) -> reindex -> git commit
                        (only when the KB folder is a git repository) -> git push (only with --push AND a remote you
                        configured) -> metrics -> a detached refresh of the find index (config.json knowledge_python and
                        knowledge_db; at most every 30 min; off with SAVE_FIND_REFRESH=0) -> advisories (the instruction-
                        surface audit, at most daily, and weekly the legacy scan; off with SAVE_ADVISORIES=0). Neither
                        extra is ever an error: a missing, slow or failing tool reads "skipped: ...".
  --post --skip --note TEXT   record that this save was skipped (nothing significant happened).

All state (the save lock, precompact flags, snapshots, metrics, journal windows) lives in kb_audit.STATE, under the
workbench home and outside the KB. A KB from an earlier kit has it in <KB>/.state/: --pre copies that across once and
leaves it readable (see migrate_state).

Without CLAUDE_CODE_SESSION_ID in the environment, the newest fresh (<= 7 d) precompact flag is this session's
(reported as flag_claimed_without_session_id).

Nothing is ever pushed by default. Exit codes: 0 ok (read `action_required` if present) · 1 unexpected error, or an
--ac-write conflict / busy lock · 2 --ac-write refused (missing draft or base; file untouched) · 3 credentials found ·
4 HOT.md over the hard cap.
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import frontmatter  # noqa: E402
import kb_audit  # noqa: E402  (paths and caps: the one home)
import kb_facts  # noqa: E402  (is_note: which files are notes)
import savelock  # noqa: E402
import secretscan  # noqa: E402

ROOT, STATE, SNAPSHOTS, AC, INBOX = kb_audit.ROOT, kb_audit.STATE, kb_audit.SNAPSHOTS, kb_audit.AC, kb_audit.INBOX
SAVE_LOCK = kb_audit.SAVE_LOCK
OLD_STATE, OLD_SNAPSHOTS, OLD_SAVE_LOCK = kb_audit.OLD_STATE, kb_audit.OLD_SNAPSHOTS, kb_audit.OLD_SAVE_LOCK
METRICS = STATE / "save-metrics.jsonl"
OLD_METRICS = OLD_STATE / "save-metrics.jsonl"
MIGRATED = STATE / "migrated-from-kb.json"
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
ADVISORY_TIMEOUT = float(os.environ.get("SAVE_ADVISORY_TIMEOUT") or 20)   # seconds, per advisory tool
LEGACY_SCAN_DAYS = 7
LEGACY_STAMP = STATE / "legacy-scan.stamp"
ADVISORY_STAMP = STATE / "advisories.stamp"      # the surface audit runs at most daily
FIND_STAMP = STATE / "find-refresh.stamp"
FIND_REFRESH_MIN = 30
FIND_TIMEOUT = float(os.environ.get("SAVE_FIND_TIMEOUT") or 15)   # seconds for the detaching call itself
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


def _flag(sid, state=None):
    """Contract with workbench-core's precompact.py: the flag it raises at compaction."""
    return (state or STATE) / f"precompact-{sid or 'nosession'}.flag"


def _my_flag():
    """This session's flag: the local state folder first, then the one an earlier kit wrote in the KB. The hooks name a flag
    by the id in the event; with no CLAUDE_CODE_SESSION_ID in this process's environment the id is unknown, so the newest
    fresh (<= STALE_DAYS) flag is claimed. A stale flag is a dead session's: nobody claims it, --pre's cleanup removes it."""
    if SESSION_ID:
        return next((f for f in (_flag(SESSION_ID, st) for st in (STATE, OLD_STATE)) if f.exists()), None)
    aged = []
    for p in _flag_files():
        try:
            aged.append((p.stat().st_mtime, p))
        except OSError:
            continue
    fresh = [(t, p) for t, p in aged if t >= _now().timestamp() - STALE_DAYS * 86400]
    return max(fresh, key=lambda x: x[0])[1] if fresh else None


def _flag_files():
    """Every pending precompact flag: the local ones, plus legacy ones not copied yet and not stale."""
    seen = {p.name: p for p in STATE.glob("precompact-*.flag")}
    cut = _now().timestamp() - STALE_DAYS * 86400
    for p in OLD_STATE.glob("precompact-*.flag"):
        try:
            if p.name not in seen and p.stat().st_mtime >= cut:
                seen[p.name] = p
        except OSError:
            continue
    return list(seen.values())


@contextlib.contextmanager
def save_lock():
    """THE save lock. While a legacy <KB>/.state/locks/save.lock exists (a session on an earlier kit still takes it),
    hold that one first and the local one second, in that order everywhere, so two holders cannot deadlock. The legacy
    file is never created here. Raises savelock.LockBusy when either is held past LOCK_TIMEOUT."""
    with contextlib.ExitStack() as stack:
        if OLD_SAVE_LOCK.exists():
            try:
                stack.enter_context(savelock.filelock(OLD_SAVE_LOCK, timeout=LOCK_TIMEOUT))
            except OSError:   # a legacy lock file that cannot be opened cannot be contended for either
                pass
        stack.enter_context(savelock.filelock(SAVE_LOCK, timeout=LOCK_TIMEOUT))
        yield


def migrate_state():
    """COPY (never move) an earlier kit's <KB>/.state/ into the local state folder, once, holding BOTH save locks.
    Files already present in the new folder win; the old folder is left as it is and stays readable for one release
    (readers fall back to it). Returns None when there is nothing to do, else one line for the --pre report.
    ponytail: the copy is by name, so the journal windows and snapshots of a half-upgraded KB travel too."""
    if MIGRATED.exists() or not OLD_STATE.is_dir():
        return None
    try:
        with save_lock():
            if MIGRATED.exists():   # another process finished while this one waited
                return None
            copied = 0
            for src in sorted(OLD_STATE.rglob("*")):
                rel = src.relative_to(OLD_STATE)
                if rel.parts[0] == "locks" or src.suffix == ".tmp" or not src.is_file():
                    continue
                dst = STATE / rel
                if dst.exists():
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_name(f"{dst.name}.{os.getpid()}.tmp")
                shutil.copy2(src, tmp)
                os.replace(tmp, dst)
                copied += 1
            savelock.atomic_write(MIGRATED, json.dumps({"copied": copied, "from": OLD_STATE.as_posix(),
                                                        "at": _now().strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
            return f"copied {copied} file(s) from {OLD_STATE.as_posix()}; the old folder is kept for one release"
    except savelock.LockBusy:
        return "skipped: another session holds the save lock; the next --pre retries"
    except OSError as e:
        return f"skipped: {type(e).__name__}: {e}"[:200]


def _resolve_base(path):
    """The --base file as given, else the same file name in the local snapshots or the legacy ones (an older kit's
    --pre printed a <KB>/.state path that may since have been cleaned up; migrate_state copied the file)."""
    if not path:
        return None
    p = Path(_winpath(path))
    if p.exists():
        return p
    return next((d / p.name for d in (SNAPSHOTS, OLD_SNAPSHOTS) if (d / p.name).exists()), None)


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


def _stamp_age(f):
    """How long ago a stamp file (a UTC timestamp line, then optionally the signature of a tool that failed) was written;
    None when it is missing or unreadable."""
    try:
        return _now() - datetime.strptime((_read(f).strip().splitlines() or [""])[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _within(age, window):
    """True when a stamp of this age is still inside `window`. A stamp from the future (a clock set back) is not."""
    return age is not None and timedelta(0) <= age < window


def _touch(f, failed_sig=None):
    """Stamp `f` with now (and, for a run that failed, the signature of the tool as it was). Never raises: a stamp only
    saves the next save some work."""
    try:
        savelock.atomic_write(f, _now().strftime("%Y-%m-%dT%H:%M:%SZ") + "\n" + (f"{failed_sig}\n" if failed_sig else ""))
    except OSError:
        pass


def _tool_sig(tool):
    """Size and mtime of an advisory tool: a failure stamped under one signature is not held against a changed tool."""
    try:
        st = tool.stat()
        return f"{st.st_size}-{st.st_mtime_ns}"
    except (OSError, AttributeError):
        return "unknown"


def _not_due(f, window, tool):
    """(age, failed) while the stamp still stands for this period's run: inside `window` and, if that run failed, with the
    tool unchanged since (a tool the kit updated is tried again at once). Else None."""
    age = _stamp_age(f)
    if not _within(age, window):
        return None
    sig = _read(f).strip().splitlines()[1:2]
    return (age, bool(sig)) if not sig or sig[0] == _tool_sig(tool) else None


# ── metrics ──────────────────────────────────────────────────────────────────────────────────────────────────
def _metric_rows():
    """Local rows first, then legacy ones whose key the local file lacks (written by a session on an earlier kit)."""
    rows, seen = [], set()
    for f in (METRICS, OLD_METRICS):
        for line in _read(f).splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and (r.get("key") is None or r["key"] not in seen):
                seen.add(r.get("key"))
                rows.append(r)
    return rows


def _ts(r, fmt="%Y-%m-%dT%H:%MZ"):
    try:
        return datetime.strptime(r.get("ts", ""), fmt).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _last_full_save():
    ts = [t for r in _metric_rows() if r.get("mode") != "skip" for t in [_ts(r)] if t]
    return max(ts) if ts else None


def _recent_saves(now, rows):
    """Saves recorded in the last RECENT_SAVE_MIN minutes, by any session: [{ts, domains}], at most 5, newest last."""
    cut = now - timedelta(minutes=RECENT_SAVE_MIN)
    return [{"ts": r.get("ts"), "domains": r.get("domains")} for r in rows if (_ts(r) or now - timedelta(days=1)) >= cut][-5:]


def _append_metric(row):
    """Read-decide-append ONE metrics row in one critical section -> 'recorded' | 'already' | 'busy'."""
    try:
        with savelock.filelock(savelock.lock_for(METRICS), timeout=LOCK_TIMEOUT):
            if any(r.get("key") == row["key"] for r in _metric_rows()):
                return "already"
            METRICS.parent.mkdir(parents=True, exist_ok=True)
            torn = METRICS.exists() and METRICS.stat().st_size > 0 and not METRICS.read_bytes().endswith(b"\n")
            with METRICS.open("a", encoding="utf-8", newline="\n") as f:
                f.write(("\n" if torn else "") + json.dumps(row, ensure_ascii=True) + "\n")   # a cut-off last line must not swallow this row
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
    if "`" in text:   # a shell runs what sits between two backticks BEFORE this driver sees the text
        warns.append("entry holds a backtick: a shell may already have run, and dropped, what sat between two of them; "
                     "check the text and quote with single quotes")
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
    sweep = [(p, STALE_DAYS) for p in STATE.glob("precompact-*.flag") if not (keep and p.name == keep.name)]
    sweep += [(p, 1) for p in ROOT.rglob("*.tmp") if re.search(r"\.\d+\.tmp$", p.name)]
    sweep += [(p, 7) for p in STATE.glob("inbox-window.*.jsonl") if not (SESSION_ID and SESSION_ID in p.name)]
    sweep += [(p, 7) for p in STATE.glob("note-hashes.*.json") if not (SESSION_ID and SESSION_ID in p.name)]
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


# ── the `updated:` stamp ─────────────────────────────────────────────────────────────────────────────────────
def _stampable(rel):
    """A curated note a save may stamp: not a record (history, daily, inbox), not active-context (--ac-write owns it)."""
    parts = rel.split("/")
    return kb_facts.is_note(parts) and parts[-1] != "active-context.md"


def _baseline_file():
    return STATE / f"note-hashes.{SESSION_ID or 'nosession'}.json"


def _note_hashes():
    out = {}
    for p in ROOT.rglob("*.md"):
        rel = p.relative_to(ROOT).as_posix()
        if _stampable(rel):
            try:
                out[rel] = hashlib.sha1(p.read_bytes()).hexdigest()
            except OSError:
                continue
    return out


def _stamp(files, rows):
    """Set `updated:` to today on each note in `files` whose bytes differ from the --pre baseline. Nothing else in the
    note moves, and a note that would end past its HOT.md cap is left alone. -> (stamped, {note: why not})."""
    try:
        base = json.loads(_read(_baseline_file()))
    except ValueError:
        base = None
    if not isinstance(base, dict):
        return [], {"*": "no --pre baseline for this session: run --pre first"}
    caps = {f"{r['domain']}/HOT.md": r["hot_warn_cap"] for r in rows}
    today, root, stamped, skipped = datetime.now().strftime("%Y-%m-%d"), ROOT.resolve(), [], {}
    for f in files:
        try:
            rel = Path(f).resolve().relative_to(root).as_posix()
        except (ValueError, OSError):
            continue
        if not _stampable(rel) or rel in stamped or rel in skipped:
            continue
        try:
            raw = (root / rel).read_bytes()
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped[rel] = "not UTF-8"
            continue
        except OSError:
            continue
        if base.get(rel) == hashlib.sha1(raw).hexdigest():
            continue                                         # not changed since --pre
        new = frontmatter.set_key(text, "updated", today)
        if new is None:
            skipped[rel] = "no front matter"
        elif new != text:
            if rel in caps and len(new.encode("utf-8")) - new.count("\r\n") > caps[rel]:
                skipped[rel] = "over its size cap"
                continue
            try:
                savelock.atomic_write(root / rel, new, newline="")
            except OSError:
                skipped[rel] = "could not be written (held open?)"
                continue
            stamped.append(rel)
    return stamped, skipped


# ── --post advisories ────────────────────────────────────────────────────────────────────────────────────────
# Each runs a script of the workbench-core plugin (see _core_tool), in a subprocess with a timeout. None can fail the
# save: a missing, slow, crashing or garbled tool reads "skipped: ..." and nothing else changes.
def _core_tool(*parts):
    """A file of the workbench-core plugin: the installed kit first, then its newest plugin-cache copy (a cached plugin
    sits in its own versioned folder, so this plugin's sibling is not there), then the folder beside this plugin (a checkout)."""
    cache = kb_audit.workbench_home().parent / "plugins" / "cache" / "workbench" / "workbench-core"
    try:
        newest = sorted((d for d in cache.glob("*") if d.is_dir()), key=lambda d: d.stat().st_mtime)[-1:]
    except OSError:
        newest = []
    for base in (kb_audit.workbench_home() / "kit" / "plugins" / "workbench-core", *newest,
                 Path(__file__).resolve().parents[2] / "workbench-core"):
        if (base / Path(*parts)).is_file():
            return base / Path(*parts)
    return None


def _advise(tool, *args, py=None, timeout=ADVISORY_TIMEOUT):
    """(parsed JSON, None) from running `tool` (under `py`, else this Python), else (None, 'skipped: <why>'). A non-zero exit
    still counts when it printed JSON."""
    if tool is None:
        return None, "skipped: not found"
    try:
        p = subprocess.run([py or sys.executable, str(tool), *args], capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return None, f"skipped: timed out after {timeout:g} s"
    except OSError as e:
        return None, f"skipped: could not start ({type(e).__name__})"
    try:
        return json.loads(p.stdout), None
    except ValueError:
        return None, f"skipped: no usable answer (exit {p.returncode})"


def _advise_surface():
    """At most one run a day, whether it answered, failed or timed out: every run costs a process start (seconds on a slow
    machine). A failed run is tried again at once only when the tool itself changed. A tool that is not there costs nothing."""
    tool = _core_tool("skills", "brain-audit", "scripts", "audit.py")
    held = _not_due(ADVISORY_STAMP, timedelta(days=1), tool)
    if held:
        return f"not due (ran {int(held[0].total_seconds() // 3600)} h ago{', and failed' if held[1] else ''}; once a day)"
    data, why = _advise(tool, "--surface", "--json")
    if tool is not None and not (why or "").startswith("skipped: could not start"):
        _touch(ADVISORY_STAMP, _tool_sig(tool))   # a failure stamp until the answer proves usable
    if why:
        return why
    sf = data["surface"]
    n = sum(len(sf[k]) for k in ("rules_over_cap", "duplicates", "dead_refs", "generated_drift", "hidden_skills"))
    _touch(ADVISORY_STAMP)
    return f"{sf['bytes']} B always loaded, {n} finding(s)" + ("; the brain-audit skill lists them" if n else "")


def _advise_legacy():
    tool = _core_tool("skills", "cleanup", "scripts", "scan_legacy.py")
    if tool is None:
        return "skipped: not found"
    held = _not_due(LEGACY_STAMP, timedelta(days=LEGACY_SCAN_DAYS), tool)
    if held:
        return f"not due (ran {held[0].days} day(s) ago{', and failed' if held[1] else ''})"
    data, why = _advise(tool, "--root", str(ROOT), "--json")
    if not (why or "").startswith("skipped: could not start"):
        _touch(LEGACY_STAMP, _tool_sig(tool))   # a run that failed or timed out counts too, until the tool changes
    if why:
        return why
    _touch(LEGACY_STAMP)
    # status: archived is how this KB retires a note on purpose, so it is not a finding
    n = sum(1 for c in data["candidates"] if "status: archived" not in c["reason"])
    return f"{n} note(s) marked deprecated, obsolete or similar" + ("; the cleanup skill reviews them (report only)" if n else "")


def _advisories():
    if os.environ.get("SAVE_ADVISORIES") == "0":
        return {name: "skipped: SAVE_ADVISORIES=0" for name in ("surface", "legacy_scan")}
    out = {}
    for name, fn in (("surface", _advise_surface), ("legacy_scan", _advise_legacy)):
        try:
            out[name] = fn()
        except Exception as e:   # noqa: BLE001  an advisory can never fail the save
            out[name] = f"skipped: {type(e).__name__}"
    return out


def _find_refresh():
    """Ask the find index to pick up the notes just saved: one detached, memory-capped refresh of the `kb` root, started at
    most once per FIND_REFRESH_MIN minutes. -> 'started' | 'skipped: <why>'. The stamp is written before the attempt, so a
    start that hangs or fails is not retried by the next save either."""
    if os.environ.get("SAVE_FIND_REFRESH") == "0":
        return "skipped: SAVE_FIND_REFRESH=0"
    try:
        with open(kb_audit.workbench_home() / "config.json", encoding="utf-8-sig") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = None
    py, db = (cfg.get("knowledge_python"), cfg.get("knowledge_db")) if isinstance(cfg, dict) else (None, None)
    if not (py and db):
        return "skipped: config.json has no knowledge_python and knowledge_db"
    tool = kb_audit.workbench_home() / "kit" / "plugins" / "workbench-core" / "skills" / "find" / "scripts" / "doc_index.py"
    if not tool.is_file():
        return "skipped: the find script is not installed"
    age = _stamp_age(FIND_STAMP)
    if _within(age, timedelta(minutes=FIND_REFRESH_MIN)):
        return f"skipped: a refresh was started {int(age.total_seconds() // 60)} min ago (at most one per {FIND_REFRESH_MIN} min)"
    _touch(FIND_STAMP)
    data, why = _advise(tool, "--db", str(db), "refresh", "--root", "kb", "--detach", "--json", py=str(py), timeout=FIND_TIMEOUT)
    if why:
        return why
    return "started" if data.get("started") is True else "skipped: not started (a refresh is already running, or memcap is missing)"


# ── --pre ────────────────────────────────────────────────────────────────────────────────────────────────────
def pre(verbose=False):
    if not kb_audit.domains():
        print(json.dumps({"error": f"no knowledge base at {ROOT.as_posix()} (no domain folder with a HOT.md)",
                          "action_required": "run the workbench bootstrap, or copy kb-template/ to that folder"}))
        return 1
    out = {"driver": "workbench-1", "session": SESSION_ID or "unknown", "kb_root": ROOT.as_posix(),
           "state_dir": STATE.as_posix()}
    moved = migrate_state()
    if moved:
        out["state_migration"] = moved
    mine = _my_flag()
    _reap(out, keep=mine)
    out["resume_pending"] = mine is not None
    if mine and not SESSION_ID:
        out["flag_claimed_without_session_id"] = True
    out["mode_hint"] = "precompact-resume" if mine else "inline"
    out["stamp"] = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")   # the clock for history headings
    others = [p.name for p in _flag_files() if not (mine and p.name == mine.name)]
    if others:
        out["other_sessions_pending"] = others
    out["concurrent_save_active"] = savelock.is_locked(SAVE_LOCK) or (OLD_SAVE_LOCK.exists() and savelock.is_locked(OLD_SAVE_LOCK))

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
    body = "".join(marker + folded[omitted:] + new)
    try:
        savelock.atomic_write(win, body)
    except OSError:   # the usual name is held open (an editor, a scanner): write a name of this process's own instead
        win = STATE / f"inbox-window.{SESSION_ID or 'nosession'}.{os.getpid()}.jsonl"
        try:
            savelock.atomic_write(win, body)
        except OSError as e:
            _need(out, f"the journal window could not be written ({type(e).__name__}): re-run --pre")
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
    try:   # what --post compares against to stamp `updated:` only on notes whose bytes changed
        savelock.atomic_write(_baseline_file(), json.dumps(_note_hashes()))
    except OSError:
        pass

    rolled = []
    try:   # rollovers rewrite history.md whole: one writer at a time, audit re-read inside the lock
        with save_lock():
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
    out["recent_other_saves"] = _recent_saves(now, mrows)
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
        snap = max([*SNAPSHOTS.glob("active-context-2*.md"), *OLD_SNAPSHOTS.glob("active-context-2*.md")],
                   key=lambda p: p.stat().st_mtime, default=None)
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
    base = _resolve_base(base_path)
    if base is None:
        print(json.dumps({"status": "error", "error": "--base is required and must exist: pass the ac_base that --pre "
                          "(or your previous --ac-write) printed. Without it this write would overwrite other sessions."}))
        return 2
    out = {"draft": draft.as_posix(), "base": base.as_posix()}
    try:
        with save_lock():
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
    if mine and not SESSION_ID:
        report["flag_claimed_without_session_id"] = True

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

    rows = kb_audit.audit()
    over = [r["domain"] for r in rows if r.get("hot_over_cap")]   # 2. HARD GATE (touched domains)
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
        with save_lock():
            report["daily_log"] = _daily_log(domains, args.note or "session save")
            report["stamped"], skipped = _stamp(files, rows)
            if skipped:
                report["stamp_skipped"] = skipped
            if mine:
                for state in (STATE, OLD_STATE):   # the legacy copy too, or the next start would raise it again
                    (state / mine.name).unlink(missing_ok=True)
                report["flag_cleared"] = mine.name
    except savelock.LockBusy:
        report["daily_log"], report["stamped"] = "skipped: lock busy", []
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

    report["recent_other_saves"] = _recent_saves(ts, _metric_rows())   # before this save's own row, so they are the others
    key = f"{ts:%Y%m%d}-{domains[0]}-{_ac_hash()}-{_h(args.note or '', 4)}"   # 7. metrics
    res = _append_metric({"ts": report["ts"], "key": key, "mode": report["mode"], "domains": domains,
                          "ac_hash": _ac_hash(), "reindex": str(report["reindex"])[:80], "note": (args.note or "")[:400]})
    report["metrics"] = {"busy": "NOT recorded (lock busy): re-run --post", "already": "already recorded"}.get(res, "recorded")
    try:                                                                # 8. find index: detached, bounded, never an error
        report["find_refresh"] = _find_refresh()
    except Exception as e:   # noqa: BLE001  a refresh can never fail the save
        report["find_refresh"] = f"skipped: {type(e).__name__}"
    report["advisories"] = _advisories()                                # 9. never an action, never an error
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
