#!/usr/bin/env python3
"""kb_health.py: one command that checks the knowledge base is actually working.
Run: kb_health.py [facts] [--json] [--eval SET] [--verbose]

  layout        the KB root exists and holds at least one domain (a folder with a HOT.md)
  caps          HOT.md / history.md / active-context.md against kb_audit's caps (over hard cap = FAIL)
  frontmatter   topic notes open with a --- block that parses as key: value lines (WARN)
  dead-links    wikilinks that resolve to no note (WARN)
  index         the search index builds and covers every note
  orphans       topic notes no other note links to (WARN: add a line to the domain's HOT.md or 00-index.md)
  retrieval     search reaches every tier that holds notes: for a sample of HOT, topic and history notes, the rarest
                words of the note must bring the note back in the top ten (FAIL when a whole tier is unreachable,
                WARN when some samples are missed)
  secrets       no credential-shaped value in any KB file (FAIL: the KB is plain text, often synced or committed)
  git           if the KB is a git repository: uncommitted changes and configured remotes (INFO; a save pushes
                only with --push)
  eval          only with --eval SET: kb_eval's known-answer set, FAIL below the set's _floors (INFO without floors)
  facts         the fact registry (<KB>/_shared/facts.json, see kb_facts.py): FAIL when a forbidden text appears in the KB or
                the always-loaded files, or an owner note stops stating its canonical text. Part of a full run once the
                registry holds a fact; `kb_health.py facts` runs only this check (and the layout check before it)
--json prints {"kb_root", "results": [{"check", "status", "detail"}], "exit"} and nothing else.
Exit 1 when any check FAILs.
"""
import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_audit  # noqa: E402
import kb_eval  # noqa: E402
import kb_facts  # noqa: E402
import kb_index  # noqa: E402
import kb_search  # noqa: E402
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
            if p.name not in ("HOT.md", "history.md", "README.md") and p.parent.name != "history"
            and not any(s.startswith(".") for s in p.relative_to(kb_audit.ROOT).parts)]


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


def check_orphans():
    if not kb_audit.index_db().exists():
        return
    con = sqlite3.connect(f"file:{kb_audit.index_db().as_posix()}?mode=ro", uri=True)
    try:
        linked = {d for (d,) in con.execute("select distinct dst from link where dst is not null and dst != src")}
    finally:
        con.close()
    orphans = sorted({p.relative_to(kb_audit.ROOT).as_posix() for p in _topic_notes()} - linked)
    record("orphans", "WARN" if orphans else "PASS", f"{len(orphans)} topic note(s) nothing links to: {orphans[:5]}"
           if orphans else "every topic note has an inbound link")


def _tier(rel):
    parts = Path(rel).parts
    if parts[-1] == "HOT.md":
        return "hot"
    return "history" if parts[-1] == "history.md" or "history" in parts[:-1] else "topic"


_WORD = re.compile(r"[^\W\d_]{4,}")
_FRONT = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n?", re.S)


def check_retrieval():
    """For up to three notes of each tier (first, middle, last by path) search the note's own three rarest words (front
    matter left out) and look for the note in the top ten. A tier whose samples are all missed is unreachable: the index
    leaves it out, or search cannot get to it."""
    if not kb_audit.index_db().exists():
        return
    doms = set(kb_audit.domains())
    texts = {}
    for p in kb_index.notes():
        rel = p.relative_to(kb_audit.ROOT).as_posix()
        if rel.split("/")[0] in doms and p.name != "README.md":
            texts[rel] = set(_WORD.findall(_FRONT.sub("", savelock.read_text(p), count=1).lower()))
    df = {}
    for words in texts.values():
        for w in words:
            df[w] = df.get(w, 0) + 1
    tiers = {}
    for rel in sorted(texts):
        if texts[rel]:
            tiers.setdefault(_tier(rel), []).append(rel)
    if not tiers:
        record("retrieval", "INFO", "no notes with text to sample")
        return
    parts, status = [], "PASS"
    for tier in ("hot", "topic", "history"):
        rels = tiers.get(tier)
        if not rels:
            continue
        sample = sorted({rels[0], rels[len(rels) // 2], rels[-1]})
        found = 0
        for rel in sample:
            words = sorted(texts[rel], key=lambda w: (df[w], -len(w), w))[:3]
            found += any(h["path"] == rel for h in kb_search.search(" ".join(words), None, 10))
        parts.append(f"{tier} {found}/{len(sample)}")
        if found == 0:
            status = "FAIL"
        elif found < len(sample) and status == "PASS":
            status = "WARN"
    record("retrieval", status, "notes reached by search: " + ", ".join(parts))


def check_eval(path):
    try:
        cases, floors = kb_eval.load(path)
    except (OSError, ValueError) as e:
        record("eval", "FAIL", f"no usable eval set at {Path(path).as_posix()}: {e}")
        return
    r = kb_eval.evaluate(cases)
    low = kb_eval.below_floors(r, floors)
    nums = (f"cases {r['cases']}, hit@1 {r['hit@1']}, hit@5 {r['hit@5']}, MRR {r['mrr']}, "
            f"abstain {r['abstain']} of {r['abstain_cases']}, p95 {r['latency_ms']['p95']} ms")
    if low:
        record("eval", "FAIL", f"below the set's floors on {', '.join(f'{k} {r[k]} < {floors[k]}' for k in low)}; {nums}")
    else:
        record("eval", "PASS" if floors else "INFO", nums + ("" if floors else " (the set has no _floors)"))


def check_secrets():
    hits = []
    for p in list(kb_audit.ROOT.rglob("*.md")) + list(kb_audit.ROOT.glob("*.jsonl")):
        if ".state" in p.parts:
            continue
        for f in secretscan.findings(savelock.read_text(p)):
            hits.append(f"{p.relative_to(kb_audit.ROOT).as_posix()}:{f['line']} {f['match']}")
    record("secrets", "FAIL" if hits else "PASS", f"{len(hits)} credential-shaped value(s)" +
           "".join(f"\n    {h}" for h in hits[:10]))


def check_facts():
    record("facts", *kb_facts.summary(kb_facts.check(kb_audit.ROOT)))


def _registry_in_use():
    facts, problems = kb_facts.load(kb_audit.ROOT)
    return bool(facts or problems)


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
    ap.add_argument("only", nargs="?", choices=["facts"], help="facts: run only the fact-registry check")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the result as JSON for a script (nothing else is printed)")
    ap.add_argument("--eval", metavar="SET", help="also run kb_eval's known-answer set and gate on its _floors")
    a = ap.parse_args()
    RESULTS.clear()
    if check_layout():
        checks = [check_caps, check_frontmatter, check_index_and_links, check_orphans, check_retrieval, check_secrets,
                  *([check_facts] if _registry_in_use() else []), check_git]
        if a.eval:
            checks.append(lambda: check_eval(a.eval))
        if a.only == "facts":
            checks = [check_facts]
        for fn in checks:
            try:
                fn()
            except Exception as e:
                record(getattr(fn, "__name__", "check").replace("check_", "").replace("<lambda>", "eval"), "FAIL",
                       f"check crashed: {type(e).__name__}: {e}")
    rc = 1 if any(s == "FAIL" for _, s, _ in RESULTS) else 0
    if a.json:
        print(json.dumps({"kb_root": kb_audit.ROOT.as_posix(), "exit": rc,
                          "results": [{"check": n, "status": s, "detail": d} for n, s, d in RESULTS]}, indent=1))
        return rc
    print(f"knowledge base: {kb_audit.ROOT.as_posix()}")
    for name, status, detail in RESULTS:
        print(f"{status:5s} {name:12s} {detail}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
