#!/usr/bin/env python3
"""kb_search.py: full-text search over the knowledge base. Prints `path:line  [heading]  snippet`, best first.

  kb_search.py "terms"                 all terms must match; falls back to any term when nothing matches all
  kb_search.py "terms" --domain ops    one domain (ops/...)
  kb_search.py "terms" --limit 5 --json
  kb_search.py --related ops/x.md      notes linking to or from that note (one hop)

The index rebuilds itself when a note changed since the last build (a few seconds at most). A miss is not evidence of
absence: this is keyword search with stemming, so retry once with the note's own words (a tool name, an error
string, an ID) before concluding the KB has nothing. Lines marked SUPERSEDED rank lower but still show.
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_audit  # noqa: E402
import kb_index  # noqa: E402

STOP = frozenset("a an and are as at be by for from how i in is it of on or that the this to was what when where "
                 "which who why with".split())
_SUP = re.compile(r"\b(?:SUPERSEDED|OBSOLETE|CORRECTED)\b", re.I)


def terms_of(q):
    return [t for t in re.findall(r"[^\W_]+", q.lower()) if t not in STOP][:32] or re.findall(r"[^\W_]+", q.lower())[:32]


def ensure_index():
    why = kb_index.stale()
    if why:
        kb_index.build()
    return why


def _snippet(body, terms, width=240):
    flat = " ".join(body.split())
    low = flat.lower()
    pos = min((low.find(t) for t in terms if t in low), default=0)
    a = max(0, pos - width // 3)
    return ("..." if a else "") + flat[a:a + width] + ("..." if a + width < len(flat) else "")


def search(query, domain=None, limit=10):
    terms = terms_of(query)
    if not terms:
        return []
    con = sqlite3.connect(f"file:{kb_audit.index_db().as_posix()}?mode=ro", uri=True)
    try:
        fts = dict(con.execute("select k, v from meta")).get("fts") == "1"
        where, args = "", []
        if domain:
            where, args = " and path like ?", [f"{domain}/%"]
        rows = []
        if fts:
            for op in (" AND ", " OR "):
                q = op.join('"%s"' % t.replace('"', "") for t in terms)
                rows = con.execute(f"select path, line, heading, body, bm25(chunk, 0, 0, 3.0, 1.0) from chunk "
                                   f"where chunk match ?{where} order by 5 limit ?", [q, *args, limit * 4]).fetchall()
                if rows:
                    break
        else:   # no FTS5 in this Python: a plain substring scan, every term required, then any term
            for need_all in (True, False):
                like = (" and " if need_all else " or ").join("lower(body) like ?" for _ in terms)
                rows = con.execute(f"select path, line, heading, body, 0 from chunk where ({like}){where} limit ?",
                                   [*(f"%{t}%" for t in terms), *args, limit * 4]).fetchall()
                if rows:
                    break
    finally:
        con.close()
    hits, seen = [], set()
    for path, line, heading, body, score in rows:
        key = (path, line)
        if key in seen:
            continue
        seen.add(key)
        demoted = bool(_SUP.search(body)) or "/history" in path
        hits.append({"path": path, "line": line, "heading": heading, "snippet": _snippet(body, terms),
                     "score": (score or 0) * (0.85 if demoted else 1.0)})
    hits.sort(key=lambda h: h["score"])   # bm25: lower is better
    return hits[:limit]


def related(rel):
    con = sqlite3.connect(f"file:{kb_audit.index_db().as_posix()}?mode=ro", uri=True)
    try:
        out = [{"path": d, "via": "links to"} for (d,) in con.execute(
            "select distinct dst from link where src = ? and dst is not null", (rel,))]
        out += [{"path": s, "via": "linked from"} for (s,) in con.execute(
            "select distinct src from link where dst = ?", (rel,))]
    finally:
        con.close()
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    p = argparse.ArgumentParser(description="Search the knowledge base.")
    p.add_argument("query", nargs="?")
    p.add_argument("--domain")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--related", metavar="PATH")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    if not kb_audit.ROOT.is_dir():
        print(f"no knowledge base at {kb_audit.ROOT.as_posix()}")
        return 1
    rebuilt = ensure_index()
    if a.related:
        rel = Path(a.related).as_posix()
        rel = rel.split(kb_audit.ROOT.as_posix() + "/", 1)[-1]
        res = related(rel)
        print(json.dumps(res, indent=1) if a.json else "\n".join(f"{r['via']}: {r['path']}" for r in res) or "no links")
        return 0
    if not a.query:
        p.print_help()
        return 1
    hits = search(a.query, a.domain, a.limit)
    if a.json:
        print(json.dumps({"query": a.query, "rebuilt": rebuilt, "hits": hits}, indent=1, ensure_ascii=False))
        return 0
    if rebuilt:
        print(f"(index rebuilt: {rebuilt})")
    if not hits:
        print("no hits. Keyword search: retry once with the note's own words (a tool, host, error or ID).")
    for h in hits:
        print(f"{h['path']}:{h['line']}  [{h['heading']}]  {h['snippet']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
