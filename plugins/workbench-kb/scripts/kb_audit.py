#!/usr/bin/env python3
"""Knowledge-base layout, caps and history rollover. THE single source of truth for paths and caps: save_driver,
kb_index, kb_search, kb_health and kb_demote import from here and never re-type a number.

Layout under the KB root (see kb-template/README.md):
  active-context.md            in-flight state; written only by save_driver.py --ac-write
  inbox.jsonl                  append-only journal (save_driver.py --inbox-add)
  <domain>/HOT.md              current facts, heuristics, error blacklist (byte-capped)
  <domain>/history.md          session records (rolled into <domain>/history/YYYY-MM.md past the cap)
  <domain>/<topic>.md          topic notes with frontmatter
  daily/YYYY-MM-DD.md          one line per save
  .state/                      locks, flags, snapshots, metrics (derived; keep it out of git)
The search index is NOT in the KB (a synced folder such as OneDrive can corrupt a live SQLite file): it lives in
<workbench home>/cache/kb-<hash>.db.

KB root: WORKBENCH_KB_ROOT, else <workbench home>/config.json "kb_root", else ~/claude-kb.
Domains: every folder of the KB root that holds a HOT.md (the template ships _shared, platform, infra, data, ai,
security, ops, projects).

Usage: kb_audit.py --audit | --caps-json
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from savelock import atomic_write, read_text as _read, retry_sharing  # noqa: E402


def _claude_home():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def workbench_home():
    return _claude_home() / "workbench"


def kb_root():
    v = os.environ.get("WORKBENCH_KB_ROOT")
    if not v:
        try:
            with open(workbench_home() / "config.json", encoding="utf-8-sig") as f:
                v = json.load(f).get("kb_root")
        except (OSError, ValueError, AttributeError):
            v = None
    return Path(os.path.expanduser(v)) if v else Path.home() / "claude-kb"


ROOT = kb_root()
KB = ROOT                      # domain folders sit directly under the root
STATE = ROOT / ".state"
SNAPSHOTS = STATE / "snapshots"
SAVE_LOCK = STATE / "locks" / "save.lock"
AC = ROOT / "active-context.md"
INBOX = ROOT / "inbox.jsonl"
DAILY = ROOT / "daily"


def index_db():
    """The FTS index file, keyed by the KB root so two KBs never share one. KB_INDEX_DB overrides (tests)."""
    if os.environ.get("KB_INDEX_DB"):
        return Path(os.environ["KB_INDEX_DB"])
    key = hashlib.sha256(ROOT.resolve().as_posix().lower().encode()).hexdigest()[:8]
    return workbench_home() / "cache" / f"kb-{key}.db"


# Caps. HOT.md is byte-capped, not line-capped (a line cap is gamed by long lines). Over the warn cap: demote with
# kb_demote.py (a verbatim move, read back before the delete). Over the hard cap in a domain a save touched: the
# save stops (exit 4) until it is demoted. Never compress text in place to fit: that silently destroys detail.
HOT_WARN_BYTES = 15_360
HOT_HARDFAIL_BYTES = 20_480
SHARED_HOT_WARN_BYTES = 6_144     # _shared is read for every task, so it stays tight
HIST_BYTES_CAP = 40_000
# The KB's link syntax: the note path between two opening and two closing square brackets. Built here once so no
# source file carries a literal link (the publish scanner flags those).
LINK_OPEN, LINK_CLOSE = "[" * 2, "]" * 2


def link(target):
    return f"{LINK_OPEN}{target}{LINK_CLOSE}"


AC_BYTES_CAP = 8_192              # active-context.md: the one hard gate is bytes
AC_LINES_ADVISORY = 60
AC_LINE_BYTES_ADVISORY = 320      # a line over this is a compound line: split it
KEEP_DAYS = 7
MIN_KEEP_ENTRIES = 5


def domains():
    if not KB.is_dir():
        return []
    return sorted(p.name for p in KB.iterdir() if p.is_dir() and not p.name.startswith(".") and (p / "HOT.md").exists())


def current_month():
    return datetime.now().strftime("%Y-%m")


def lf_bytes(p):
    """Size as git stores it (CRLF counted as LF), so a cap reads the same on every checkout. Missing -> 0."""
    try:
        b = retry_sharing(Path(p).read_bytes)
    except OSError:
        return 0
    return len(b) - b.count(b"\r\n")


def ac_report(text):
    """active-context advisories. None blocks: the byte cap is the only gate."""
    lines = text.split("\n")
    long_ = [i + 1 for i, ln in enumerate(lines) if len(ln.encode("utf-8")) > AC_LINE_BYTES_ADVISORY]
    adv = {}
    if len(lines) > AC_LINES_ADVISORY:
        adv["lines"] = f"{len(lines)} lines (advisory {AC_LINES_ADVISORY}). Facts belong in <domain>/ notes."
    if long_:
        adv["line-len"] = f"{len(long_)} line(s) over {AC_LINE_BYTES_ADVISORY} B (lines {long_[:5]}): split, don't golf."
    return {"lines": len(lines), "advisories": adv}


def _append(path, body):
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(body)


def audit():
    out = []
    for d in domains():
        dd = KB / d
        hot, hist = dd / "HOT.md", dd / "history.md"
        hot_bytes, hist_bytes = lf_bytes(hot), lf_bytes(hist)
        warn_cap = SHARED_HOT_WARN_BYTES if d == "_shared" else HOT_WARN_BYTES
        prev_month = 0
        if hist.exists():
            cur = current_month()
            prev_month = sum(1 for m in re.findall(r"^## (\d{4}-\d{2})-\d{2}", _read(hist), re.M) if m < cur)
        out.append({"domain": d, "hot_bytes": hot_bytes, "hot_warn_cap": warn_cap, "hot_hardfail_cap": HOT_HARDFAIL_BYTES,
                    "hot_warn": hot_bytes > warn_cap, "hot_over_cap": hot_bytes > HOT_HARDFAIL_BYTES,
                    "history_kb": round(hist_bytes / 1024, 1), "history_over_cap": hist_bytes > HIST_BYTES_CAP,
                    "history_prev_month_entries": prev_month,
                    "topic_notes": len([p for p in dd.glob("*.md") if p.name not in ("HOT.md", "history.md")])})
    return out


def _split_entries(hist):
    """(header, [(date, text), ...]): the one heading splitter for every rollover."""
    lines = _read(hist).splitlines(keepends=True)
    head_end = next((i for i, ln in enumerate(lines) if re.match(r"^## \d{4}-\d{2}-\d{2}", ln)), len(lines))
    header, entries, cur, cur_date = "".join(lines[:head_end]), [], [], None
    for ln in lines[head_end:]:
        m = re.match(r"^## (\d{4}-\d{2}-\d{2})", ln)
        if m:
            if cur and cur_date:
                entries.append((cur_date, "".join(cur)))
            cur, cur_date = [ln], m.group(1)
        else:
            cur.append(ln)
    if cur and cur_date:
        entries.append((cur_date, "".join(cur)))
    return header, entries


def _archive(domain, header, keep, moved, ptr, why):
    """Append `moved` to history/YYYY-MM.md (append-only), then rewrite history.md as header + ptr + keep."""
    adir = KB / domain / "history"
    adir.mkdir(exist_ok=True)
    by = {}
    for d, e in moved:
        by.setdefault(d[:7], []).append(e)
    for m, es in sorted(by.items()):
        p = adir / f"{m}.md"
        if not p.exists():
            _append(p, f"# History archive: {m}\n\n_Archived by the save driver ({why})._\n\n---\n\n")
        _append(p, "\n" + "".join(es))
    atomic_write(KB / domain / "history.md", header + ptr + "".join(e for _, e in keep))
    return [{"month": m, "entries": len(es)} for m, es in sorted(by.items())]


def _by_cutoff(domain, cutoff, action, why):
    hist = KB / domain / "history.md"
    if not hist.exists():
        return {"domain": domain, "action": action, "result": "no-history"}
    header, ents = _split_entries(hist)
    old = [x for x in ents if x[0] < cutoff]
    if not old:
        return {"domain": domain, "action": action, "result": "nothing-older-than-cutoff", "cutoff": cutoff}
    keep = [x for x in ents if x[0] >= cutoff]
    ptr = f"\n_Entries before {cutoff} archived to `history/YYYY-MM.md`._\n\n---\n\n"
    return {"domain": domain, "action": action, "cutoff": cutoff, "kept_entries": len(keep),
            "archived": _archive(domain, header, keep, old, ptr, why)}


def rollover(domain):
    """Monthly: archive every entry dated before the current month."""
    return _by_cutoff(domain, current_month() + "-01", "rollover", "monthly")


def rollover_age(domain, keep_days=KEEP_DAYS):
    return _by_cutoff(domain, (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d"),
                      "rollover-age", f"age rollover, kept last {keep_days}d")


def rollover_size(domain, min_keep=MIN_KEEP_ENTRIES):
    """Last resort: archive oldest-first by position until under cap, always keeping the newest min_keep entries."""
    hist = KB / domain / "history.md"
    if not hist.exists():
        return {"domain": domain, "action": "rollover-size", "result": "no-history"}
    header, entries = _split_entries(hist)
    if len(entries) <= min_keep:
        return {"domain": domain, "action": "rollover-size", "result": "irreducible", "entries": len(entries)}
    keep, moved, cur = list(entries), [], current_month()
    while len(keep) > min_keep:
        if len(header.encode("utf-8")) + sum(len(e.encode("utf-8")) for _, e in keep) <= HIST_BYTES_CAP:
            break
        i = next((i for i, (d, _) in enumerate(keep) if d[:7] <= cur), None)
        if i is None:
            break
        moved.append(keep.pop(i))
    if not moved:
        return {"domain": domain, "action": "rollover-size", "result": "already-under-cap"}
    ptr = f"\n_{len(moved)} older entries archived to `history/YYYY-MM.md` (size rollover)._\n\n---\n\n"
    return {"domain": domain, "action": "rollover-size", "moved": len(moved), "kept_entries": len(keep),
            "archived": _archive(domain, header, keep, moved, ptr, "size rollover")}


def rollover_age_adaptive(domain):
    """Shrinking keep windows (7 -> 3 -> 1 days), then the size rollover that always makes progress."""
    results, hist = [], KB / domain / "history.md"
    for days in (KEEP_DAYS, 3, 1):
        results.append(rollover_age(domain, keep_days=days))
        if lf_bytes(hist) <= HIST_BYTES_CAP:
            break
    if lf_bytes(hist) > HIST_BYTES_CAP:
        results.append(rollover_size(domain))
    return {"domain": domain, "action": "rollover-age-adaptive", "passes": results,
            "final_kb": round(lf_bytes(hist) / 1024, 1)}


def caps():
    return {"hot_warn": HOT_WARN_BYTES, "hot_hard": HOT_HARDFAIL_BYTES, "shared_hot_warn": SHARED_HOT_WARN_BYTES,
            "hist": HIST_BYTES_CAP, "ac_bytes": AC_BYTES_CAP, "ac_lines": AC_LINES_ADVISORY,
            "ac_line_bytes": AC_LINE_BYTES_ADVISORY, "kb_root": ROOT.as_posix(), "domains": domains()}


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--audit", action="store_true")
    p.add_argument("--caps-json", action="store_true")
    a = p.parse_args()
    if a.caps_json:
        print(json.dumps(caps()))
    elif a.audit:
        print(json.dumps(audit(), indent=2))
    else:
        p.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
