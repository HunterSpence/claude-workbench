#!/usr/bin/env python3
"""kb_demote.py: move HOT.md line(s) to history.md without losing a word.

When a HOT.md hits its byte cap, shrinking text in place to fit silently destroys detail (an error code, the name of
the stack). Demoting is one command instead:

  kb_demote.py --domain ops --match "proxy certificate error"
  kb_demote.py --domain ops --match "old build flag" --leave-link
  kb_demote.py --over-cap                     # list what to demote, change nothing

Safety: the lines are appended to history.md and READ BACK from disk before they are removed from HOT.md. If the
append cannot be verified, HOT.md is not touched. Both writes are atomic, under the save driver's lock.
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_audit  # noqa: E402  (caps, paths and domains: the one home)
import savelock  # noqa: E402

KB, LOCK = kb_audit.KB, kb_audit.SAVE_LOCK
_read = savelock.read_text
MAX_HITS = 5   # above this, require --force: a loose --match must not gut a file


def demote(domain, match, leave_link=False, dry_run=False, force=False):
    hot, hist = KB / domain / "HOT.md", KB / domain / "history.md"
    if not hot.exists():
        return {"error": f"no HOT.md for domain {domain}"}
    # `--match " "` is truthy, so an argparse presence check lets a stray space through and
    # it matches EVERY line — including the file's own title. Blast radius must be bounded
    # before the lock is taken, not discovered afterwards.
    if not match.strip():
        return {"error": "refusing a whitespace-only --match: it matches every line"}

    with savelock.filelock(LOCK, timeout=120):
        lines = _read(hot).splitlines()
        m = match.lower()
        hits = [i for i, l in enumerate(lines) if m in l.lower()]
        if not hits:
            return {"error": f"no line in {domain}/HOT.md matches {match!r}"}
        moved = [lines[i] for i in hits]
        if len(hits) > MAX_HITS and not force:
            return {"error": f"{match!r} matches {len(hits)} lines (limit {MAX_HITS}) — "
                             f"narrow it, or pass --force if that is really intended",
                    "would_move": [l[:90] for l in moved]}
        # Line-blind removal preserves bytes but can silently wreck document structure:
        # deleting one fence leaves the rest of the file inside an unterminated code block,
        # and deleting a heading re-parents its body under the previous section.
        risky = [l[:60] for l in moved
                 if l.lstrip().startswith(("```", "#", "|--", "|:-")) or l.strip() in ("---", "***")]
        before = kb_audit.lf_bytes(hot)

        if dry_run:
            out = {"dry_run": True, "domain": domain, "would_move": moved,
                   "bytes_freed": sum(len(x.encode()) + 1 for x in moved)}
            if risky:
                out["structure_warning"] = risky
            return out

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        block = (f"\n## {stamp} - demoted from {domain}/HOT.md\n"
                 f"Moved verbatim to keep HOT.md under cap. Retrieve with "
                 f"`kb_search.py \"<terms>\" --domain {domain}`.\n\n"
                 + "\n".join(moved) + "\n")

        # 1. Append to history FIRST.
        savelock.atomic_write(hist, _read(hist) + block)

        # 2. Read it back from disk. Only a verified round-trip authorises the delete —
        #    never remove from HOT on the strength of a write call returning cleanly.
        #    Assert THIS block landed at the end: checking "is each line somewhere in the
        #    file" would pass on a failed append if an identical line already existed from
        #    an earlier demote.
        written = _read(hist)
        if not written.endswith(block):
            missing = [x for x in moved if x.strip() and x not in written]
            return {"error": "history read-back FAILED — HOT.md left untouched",
                    "unverified": missing[:3] or ["appended block not found at EOF"]}

        # 3. Now it is safe to remove from HOT.
        keep = [l for i, l in enumerate(lines) if i not in set(hits)]
        if leave_link:
            # One pointer per moved line — a single link for N entries read as "1 thing was
            # demoted" while N-1 vanished with no trace.
            note = (f"- (demoted {stamp[:10]}, {len(moved)} entr"
                    f"{'y' if len(moved) == 1 else 'ies'}) "
                    + "; ".join(l.lstrip("|-* ").strip()[:60] for l in moved[:3])
                    + ("…" if len(moved) > 3 else "")
                    + f" → {kb_audit.link(domain + '/history.md')}")
            keep.insert(hits[0], note)
        savelock.atomic_write(hot, "\n".join(keep) + "\n")

        after = kb_audit.lf_bytes(hot)
        res = {"domain": domain, "moved": len(moved), "verified": True,
               "hot_bytes": f"{before} -> {after}", "freed": before - after,
               "history": str(hist), "entries": moved}
        if risky:
            res["structure_warning"] = ("removed a fence/heading/table-separator line — "
                                        "check the file still renders: " + "; ".join(risky))
        return res


def over_cap():
    """kb_audit.audit()'s verdict (LF bytes, the /save gate's measurement) + candidate lines to demote."""
    out = []
    for r in kb_audit.audit():
        if not r.get("hot_warn"):
            continue
        lines = [l for l in _read(KB / r["domain"] / "HOT.md").splitlines() if l.strip().startswith(("-", "|"))]
        oldest = sorted((l for l in lines if "20" in l), key=len, reverse=True)[:5]
        out.append({"domain": r["domain"], "bytes": r["hot_bytes"], "warn_cap": r["hot_warn_cap"],
                    "hard_cap": r["hot_hardfail_cap"], "over_hard": r["hot_over_cap"],
                    "longest_dated_rows": [l[:90] for l in oldest]})
    return out


def main():
    # A cp1252 console would raise UnicodeEncodeError while printing AFTER the move succeeded, and the caller would
    # read exit 1 as "the demote failed" on content that is already moved.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    ap = argparse.ArgumentParser(description="Demote a HOT.md entry to history.md, verbatim.")
    ap.add_argument("--domain", choices=kb_audit.domains() or None)
    ap.add_argument("--match", help="substring of the line(s) to demote")
    ap.add_argument("--force", action="store_true",
                    help=f"allow a match that hits more than {MAX_HITS} lines")
    ap.add_argument("--leave-link", action="store_true", help="leave a one-line pointer behind")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--over-cap", action="store_true", help="report only, change nothing")
    a = ap.parse_args()

    if a.over_cap:
        rows = [r for r in over_cap() if not a.domain or r["domain"] == a.domain]
        if not rows:
            print("all HOT.md files within warn cap")
        for r in rows:
            flag = "OVER HARD CAP" if r["over_hard"] else "over warn"
            print(f"{r['domain']:9s} {r['bytes']:6d}B  {flag}")
            for l in r["longest_dated_rows"]:
                print(f"    candidate: {l}")
        return 0
    if not (a.domain and a.match):
        ap.print_help()
        return 1

    import json
    res = demote(a.domain, a.match, a.leave_link, a.dry_run, a.force)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 1 if res.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
