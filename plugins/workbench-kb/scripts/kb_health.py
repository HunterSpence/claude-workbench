#!/usr/bin/env python3
"""kb_health.py: one command that checks the knowledge base is actually working. Run: kb_health.py [--verbose]

  layout        the KB root exists and holds at least one domain (a folder with a HOT.md)
  caps          HOT.md / history.md / active-context.md against kb_audit's caps (over hard cap = FAIL)
  frontmatter   topic notes open with a --- block that parses as key: value lines (WARN)
  dead-links    wikilinks that resolve to no note (WARN)
  index         the search index builds and covers every note
  secrets       no credential-shaped value in any KB file (FAIL: the KB is plain text, often synced or committed)
  git           if the KB is a git repository: uncommitted changes and configured remotes (INFO; a save pushes
                only with --push)
Exit 1 when any check FAILs.
"""
import argparse
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_audit  # noqa: E402
import kb_index  # noqa: E402
import savelock  # noqa: E402
import secretscan  # noqa: E402

RESULTS = []


def record(name, status, detail=""):
    RESULTS.append((name, status, detail))


def check_layout():
    root = kb_audit.ROOT
    if not root.is_dir():
        record("layout", "FAIL", f"{root.as_posix()} does not exist: run the bootstrap or copy kb-template/")
        return False
    ds = kb_audit.domains()
    record("layout", "PASS" if ds else "WARN", f"{len(ds)} domain(s): {ds}" if ds else "no domain folder with a HOT.md")
    return True


def check_caps():
    rows = kb_audit.audit()
    hard = [r["domain"] for r in rows if r["hot_over_cap"]]
    warn = [r["domain"] for r in rows if r["hot_warn"] and not r["hot_over_cap"]]
    hist = [r["domain"] for r in rows if r["history_over_cap"]]
    ac = kb_audit.lf_bytes(kb_audit.AC)
    detail = f"HOT over hard cap {hard}, over warn {warn}, history over cap {hist}, active-context {ac}/{kb_audit.AC_BYTES_CAP} B"
    record("caps", "FAIL" if hard else "WARN" if warn or hist or ac > kb_audit.AC_BYTES_CAP else "PASS", detail)


def _topic_notes():
    return [p for d in kb_audit.domains() for p in (kb_audit.KB / d).rglob("*.md")
            if p.name not in ("HOT.md", "history.md", "README.md") and p.parent.name != "history"]


def check_frontmatter():
    bad = []
    for p in _topic_notes():
        t = savelock.read_text(p)
        m = re.match(r"---\r?\n(.*?)\r?\n---", t, re.S)
        if not m or any(ln.strip() and not re.match(r"^[\w-]+\s*:|^\s*-\s|^\s+", ln) for ln in m.group(1).splitlines()):
            bad.append(p.relative_to(kb_audit.ROOT).as_posix())
    record("frontmatter", "WARN" if bad else "PASS", f"{len(bad)} note(s) without parseable frontmatter: {bad[:5]}")


def check_index_and_links():
    try:
        res = kb_index.build()
    except Exception as e:
        record("index", "FAIL", f"build failed: {type(e).__name__}: {e}")
        return
    record("index", "PASS", res)
    con = sqlite3.connect(f"file:{kb_audit.index_db().as_posix()}?mode=ro", uri=True)
    try:
        dead = con.execute("select src, line, raw from link where dst is null").fetchall()
    finally:
        con.close()
    record("dead-links", "WARN" if dead else "PASS",
           f"{len(dead)} dead link(s)" + "".join(f"\n    {s}:{n} {kb_audit.link(r)}" for s, n, r in dead[:10]))


def check_secrets():
    hits = []
    for p in list(kb_audit.ROOT.rglob("*.md")) + list(kb_audit.ROOT.glob("*.jsonl")):
        if ".state" in p.parts:
            continue
        for f in secretscan.findings(savelock.read_text(p)):
            hits.append(f"{p.relative_to(kb_audit.ROOT).as_posix()}:{f['line']} {f['match']}")
    record("secrets", "FAIL" if hits else "PASS", f"{len(hits)} credential-shaped value(s)" +
           "".join(f"\n    {h}" for h in hits[:10]))


def check_git():
    root = kb_audit.ROOT
    if not (root / ".git").exists():
        record("git", "INFO", "not a git repository (history of HOT.md edits is not kept)")
        return
    def git(*a):
        try:
            return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, timeout=15).stdout
        except Exception as e:
            return f"<git failed: {e}>"
    dirty = len([ln for ln in git("status", "--porcelain").splitlines() if ln.strip()])
    remotes = git("remote", "-v").split()
    record("git", "INFO", f"{dirty} uncommitted change(s); remotes: {sorted(set(remotes[1::3])) or 'none'} "
                          "(a save pushes only with --push)")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="Check the knowledge base.")
    ap.add_argument("--verbose", action="store_true")
    ap.parse_args()
    print(f"knowledge base: {kb_audit.ROOT.as_posix()}")
    if check_layout():
        for fn in (check_caps, check_frontmatter, check_index_and_links, check_secrets, check_git):
            try:
                fn()
            except Exception as e:
                record(fn.__name__.replace("check_", ""), "FAIL", f"check crashed: {type(e).__name__}: {e}")
    for name, status, detail in RESULTS:
        print(f"{status:5s} {name:12s} {detail}")
    return 1 if any(s == "FAIL" for _, s, _ in RESULTS) else 0


if __name__ == "__main__":
    sys.exit(main())
