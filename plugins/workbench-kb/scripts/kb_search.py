#!/usr/bin/env python3
"""kb_search.py: full-text search over the knowledge base. Prints `path:line  [heading]  snippet`, best first.

  kb_search.py "terms"                 all terms must match; falls back to any term when nothing matches all
  kb_search.py "terms" --domain ops    one domain (ops/...)
  kb_search.py "terms" --limit 5 --json
  kb_search.py "terms" --all-chunks    every matching chunk, best first (one long note may fill the list)
  kb_search.py --related ops/x.md      notes linking to or from that note (one hop); --depth N walks N hops
  kb_search.py "terms" --scope all     also search the journal (inbox.jsonl)

The index rebuilds itself when a note changed since the last build (a few seconds at most; --no-rebuild skips that). Every
link a --related walk reports is re-checked against the note's current text: a link or note that is gone is dropped and
"index stale" is printed. A miss is not evidence of
absence: this is keyword search with stemming, so retry once with the note's own words (a tool name, an error
string, an ID) before concluding the KB has nothing.

One hit per note, its best chunk shown. Two rankings are fused with reciprocal rank (k=60): the chunk arm (every
paragraph of every note) and the note arm (title, path words, headings), each cut to a fixed pool of 40 notes and both
asking for every term, or for any term only when neither finds an every-term match, so
--limit only cuts the same ranked list and never reorders it. `score` is the fused value, higher is better. A hit whose
chunk holds a SUPERSEDED, OBSOLETE or CORRECTED marker is tagged [SUPERSEDED] (JSON "superseded": true) and ranks lower;
so do history notes. JSON also says "mode": "fts5", or "keyword fallback" on a Python without FTS5 (substring match,
ranked by how many terms match).
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
POOL = 40            # notes kept from each arm: fixed, so --limit only cuts the ranked list
RAW_CHUNKS = 800     # chunk rows read to find POOL distinct notes (one long note can hold many of them)
RRF_K = 60
DEMOTE = 0.85        # a superseded chunk or a history note keeps this share of its score


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


def _chunk_rows(con, fts, terms, every, where, args, n):
    """(path, line, heading, body, score) chunk rows, best first (lower score is better): every term, or any term."""
    if fts:
        q = (" AND " if every else " OR ").join('"%s"' % t.replace('"', "") for t in terms)
        return con.execute(f"select path, line, heading, body, bm25(chunk, 0, 0, 3.0, 1.0) as s from chunk "
                           f"where chunk match ?{where} order by s, rowid limit ?", [q, *args, n]).fetchall()
    pats = [f"%{t}%" for t in terms]    # no FTS5 in this Python: substring match, ranked by how many terms the chunk holds
    return con.execute(f"select path, line, heading, body, -({' + '.join('(lower(body) like ?)' for _ in terms)}) as s "
                       f"from chunk where ({(' and ' if every else ' or ').join('lower(body) like ?' for _ in terms)}){where} "
                       f"order by s, path, line limit ?", [*pats, *pats, *args, n]).fetchall()


def _note_rows(con, fts, terms, every, where, args, n):
    """(path, score) note rows over path words, title and headings, best first: every term, or any term."""
    if fts:
        q = (" AND " if every else " OR ").join('"%s"' % t.replace('"', "") for t in terms)
        return con.execute(f"select path, bm25(notefts, 0, 4.0, 5.0, 2.0) as s from notefts "
                           f"where notefts match ?{where} order by s, rowid limit ?", [q, *args, n]).fetchall()
    hay, pats = "lower(pathwords || ' ' || title || ' ' || headings)", [f"%{t}%" for t in terms]
    return con.execute(f"select path, -({' + '.join(f'({hay} like ?)' for _ in terms)}) as s from notefts "
                       f"where ({(' and ' if every else ' or ').join(f'{hay} like ?' for _ in terms)}){where} "
                       f"order by s, path limit ?", [*pats, *pats, *args, n]).fetchall()


def _demoted(body, path):
    return bool(_SUP.search(body)) or "/history" in path


def _hit(path, line, heading, body, terms, score):
    return {"path": path, "line": line, "heading": heading, "snippet": _snippet(body, terms), "score": score,
            "superseded": bool(_SUP.search(body))}


def search(query, domain=None, limit=10, all_chunks=False):
    """Hits for a query, best first: one per note (its best chunk), or with all_chunks every chunk by its own score."""
    terms = terms_of(query)
    if not terms:
        return []
    con = sqlite3.connect(f"file:{kb_audit.index_db().as_posix()}?mode=ro", uri=True)
    try:
        fts = dict(con.execute("select k, v from meta")).get("fts") == "1"
        where, args = ("", []) if not domain else (" and path like ?", [f"{domain}/%"])
        if all_chunks:
            hits, seen = [], set()
            for every in (True, False):
                for path, line, heading, body, score in _chunk_rows(con, fts, terms, every, where, args, limit * 4):
                    if (path, line) not in seen:
                        seen.add((path, line))
                        hits.append(_hit(path, line, heading, body, terms, (score or 0) * (DEMOTE if _demoted(body, path) else 1.0)))
                if hits:
                    break
            hits.sort(key=lambda h: (h["score"], h["path"], h["line"]))   # bm25: lower is better
            return hits[:limit]
        for every in (True, False):   # one operator for both arms: the any-term fallback runs only when NO arm has an all-terms match
            chunk_rows = _chunk_rows(con, fts, terms, every, where, args, RAW_CHUNKS)   # best first
            note_rows = _note_rows(con, fts, terms, every, where, args, POOL)
            if chunk_rows or note_rows:
                break
        best = {}
        for row in chunk_rows:   # a note's first row is its best chunk
            best.setdefault(row[0], row)
        chunk_pool = list(best.values())[:POOL]
        fused = {}
        for rank, row in enumerate(chunk_pool, 1):
            fused[row[0]] = 1.0 / (RRF_K + rank)
        for rank, (path, _s) in enumerate(note_rows, 1):
            fused[path] = fused.get(path, 0.0) + 1.0 / (RRF_K + rank)
        rows = {r[0]: r for r in chunk_pool}
        for path in fused:
            if path not in rows:   # found by title, path words or headings only: show the section whose heading matches,
                # else the first one under a heading (skipping the front matter)
                secs = con.execute("select line, heading, rid from section where path = ? order by line", (path,)).fetchall()
                pick = next((x for x in secs if any(t in (x[1] or "").lower() for t in terms)),
                            next((x for x in secs if x[1]), secs[0] if secs else None))
                if pick:
                    rows[path] = (path, pick[0], pick[1], con.execute("select body from chunk where rowid = ?", (pick[2],)).fetchone()[0], 0)
    finally:
        con.close()
    hits = [_hit(*rows[p][:4], terms, rrf * (DEMOTE if _demoted(rows[p][3], p) else 1.0))
            for p, rrf in fused.items() if rows.get(p)]
    hits.sort(key=lambda h: (-h["score"], h["path"], h["line"]))
    for h in hits:
        h["score"] = round(h["score"], 6)
    return hits[:limit]


def index_mode():
    """'fts5', or 'keyword fallback' when this Python had no FTS5 when the index was built."""
    con = sqlite3.connect(f"file:{kb_audit.index_db().as_posix()}?mode=ro", uri=True)
    try:
        return "fts5" if dict(con.execute("select k, v from meta")).get("fts") == "1" else "keyword fallback"
    finally:
        con.close()


def related(rel, depth=1):
    """(neighbours, dead): breadth-first over the link table, both directions, `depth` hops. Each edge is re-read from the
    note's current text; one that no longer holds is dropped and counted in `dead`."""
    existing = kb_index.disk_rels()
    stems = kb_index.stems_of(existing)
    live = {}

    def holds(src, dst):
        if src not in live:
            live[src] = kb_index.live_links(src, existing, stems) if src in existing else set()
        return dst in live[src] and dst in existing
    con = sqlite3.connect(f"file:{kb_audit.index_db().as_posix()}?mode=ro", uri=True)
    seen, frontier, out, dead = {rel}, [rel], [], 0
    try:
        for hop in range(1, max(1, depth) + 1):
            nxt = []
            for cur in frontier:
                edges = [(d, "links to", cur, d) for (d,) in con.execute("select distinct dst from link where src = ? and dst is not null", (cur,))]
                edges += [(s, "linked from", s, cur) for (s,) in con.execute("select distinct src from link where dst = ?", (cur,))]
                for other, via, src, dst in edges:
                    if other in seen:
                        continue
                    if not holds(src, dst):
                        dead += 1
                        continue
                    seen.add(other)
                    nxt.append(other)
                    out.append({"path": other, "via": via, "depth": hop})
            frontier = nxt
    finally:
        con.close()
    return out, dead


def journal_hits(query, limit):
    """Lines of the journal (inbox.jsonl) that contain every search term."""
    terms = terms_of(query)
    hits = []
    try:
        lines = kb_audit.INBOX.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return hits
    for n, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        text = str(row.get("text", "")) if isinstance(row, dict) else ""
        if terms and all(t in text.lower() for t in terms):
            hits.append({"path": kb_audit.INBOX.name, "line": n, "heading": f"journal {row.get('ts', '')}".strip(),
                         "snippet": _snippet(text, terms), "score": 0.0, "superseded": False})
    return hits[-limit:]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    p = argparse.ArgumentParser(description="Search the knowledge base.")
    p.add_argument("query", nargs="?")
    p.add_argument("--domain")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--all-chunks", action="store_true", help="every matching chunk, not one hit per note")
    p.add_argument("--related", metavar="PATH")
    p.add_argument("--depth", type=int, default=1, help="hops for --related (default 1)")
    p.add_argument("--scope", choices=["kb", "all"], default="kb", help="all: also search the journal (inbox.jsonl)")
    p.add_argument("--no-rebuild", action="store_true", help="use the index as it is (--related still re-checks every link)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    if not kb_audit.ROOT.is_dir():
        print(f"no knowledge base at {kb_audit.ROOT.as_posix()}")
        return 1
    rebuilt = ensure_index() if not a.no_rebuild or not kb_audit.index_db().exists() else None
    if a.related:
        rel = Path(a.related).as_posix()
        rel = rel.split(kb_audit.ROOT.as_posix() + "/", 1)[-1]
        res, dead = related(rel, a.depth)
        if a.json:
            print(json.dumps(res, indent=1))
        else:
            print("\n".join(f"{r['via']}: {r['path']}" + (f" (hop {r['depth']})" if a.depth > 1 else "") for r in res) or "no links")
        if dead:
            print(f"index stale: {dead} link(s) in the index no longer hold in the notes and were dropped; the next search rebuilds it",
                  file=sys.stderr if a.json else sys.stdout)
        return 0
    if not a.query:
        p.print_help()
        return 1
    try:
        hits = search(a.query, a.domain, a.limit, a.all_chunks)
        mode = index_mode()
    except sqlite3.Error as e:   # --no-rebuild on an index an older kit built
        print(f"the index cannot be read ({e}); search again without --no-rebuild", file=sys.stderr)
        return 1
    if a.scope == "all":
        hits += journal_hits(a.query, a.limit)
    if a.json:
        print(json.dumps({"query": a.query, "rebuilt": rebuilt, "mode": mode, "hits": hits}, indent=1, ensure_ascii=False))
        return 0
    if rebuilt:
        print(f"(index rebuilt: {rebuilt})")
    if not hits:
        print("no hits. Keyword search: retry once with the note's own words (a tool, host, error or ID).")
    for h in hits:
        print(f"{h['path']}:{h['line']}  [{h['heading']}]  " + ("[SUPERSEDED] " if h.get("superseded") else "") + h["snippet"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
