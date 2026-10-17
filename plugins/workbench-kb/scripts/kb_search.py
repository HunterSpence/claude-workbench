#!/usr/bin/env python3
"""kb_search.py: full-text search over the knowledge base. Prints `path:line  [heading]  snippet`, best first.

  kb_search.py "terms"                 all terms must match; falls back to any term when nothing matches all
  kb_search.py "terms" --domain ops    one domain (ops/...)
  kb_search.py "terms" --limit 5 --json
  kb_search.py "terms" --all-chunks    every matching chunk, best first (one long note may fill the list)
  kb_search.py --related ops/x.md      notes linking to or from that note (one hop); --depth N walks N hops
  kb_search.py "terms" --scope all     also search the journal (inbox.jsonl)

The index rebuilds itself when a note changed since the last build (a few seconds at most; --no-rebuild skips that). When
the rebuild fails (a locked or scanned file, a full disk) the search still answers, exit 0, with ONE warning line: from the
old index ("WARNING: index rebuild failed (...): results may be stale", JSON "mode": "stale-index"), or with no index at all
from a plain scan of the notes ("WARNING: index unavailable (...): grep fallback", "mode": "grep"). Every
link a --related walk reports is re-checked against the note's current text: a link or note that is gone is dropped and
"index stale" is printed. A miss is not evidence of
absence: this is keyword search with stemming, so retry once with the note's own words (a tool name, an error
string, an ID) before concluding the KB has nothing.
The snippet is the chunk line that holds the rarest query words (a number in the query counts extra), with its wrapped
continuation line; a chunk with no such line shows a window at the first word. A hit whose chunk states a
"forbidden" text of a fact in <KB>/_shared/facts.json (outside the fact's owner note, on a line not marked SUPERSEDED) is
tagged [retired - live value in <owner>] (JSON "retired": {"fact", "owner"}) and the owner note is listed just above it.

One hit per note, its best chunk shown. Two rankings are fused with reciprocal rank (k=60): the chunk arm (every
paragraph of every note) and the note arm (title, path words, headings), each cut to a fixed pool of 40 notes and both
asking for every term, or for any term only when neither finds an every-term match, so
--limit only cuts the same ranked list and never reorders it. `score` is the fused value, higher is better. A hit whose
chunk holds a SUPERSEDED, OBSOLETE or CORRECTED marker is tagged [SUPERSEDED] (JSON "superseded": true) and ranks lower;
so do history notes. JSON also says "ranking": "fts5", or "keyword fallback" on a Python without FTS5 (substring match,
ranked by how many terms match), or "grep" (the fallback scan: notes holding every word, else any word, by word count).
"""
import argparse
import json
import math
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_audit  # noqa: E402
import kb_index  # noqa: E402
import savelock  # noqa: E402

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


_TOKEN = re.compile(r"[^\W_]+")
_NEW_LINE = re.compile(r"\s*(?:[-*+]\s|\d+[.)]\s|#|\|)")   # a bullet, numbered item, heading or table row starts a line of its own
NUM_BONUS = 1.0      # a query number found in a line adds this to the line's score


def _window(text, terms, width):
    flat = " ".join(text.split())
    low = flat.lower()
    pos = min((low.find(t) for t in terms if t in low), default=0)
    a = max(0, pos - width // 3)
    return ("..." if a else "") + flat[a:a + width] + ("..." if a + width < len(flat) else "")


def _wraps(lines, i):
    """Line i+1 continues line i (hard-wrapped prose), not a blank line or a new bullet, heading or table row."""
    return i + 1 < len(lines) and bool(lines[i + 1].strip()) and not _NEW_LINE.match(lines[i + 1])


def _snippet(body, terms, width=240):
    """The line of the chunk that answers the query, plus the line it wraps onto. A line scores the sum of the
    inverse document frequency (lines of this chunk are the documents) of the query words it holds as whole words,
    so the line with the rare word beats the many lines with the common one; a query number in the line adds
    NUM_BONUS, a heading counts half, a word only on the wrapped next line counts half. A word of 4+ letters also
    matches a longer word it starts. Front matter is never the answer. No line holds a word (a stem-only match, a hit found
    by title): the window of `width` characters at the first word, as before."""
    lines = body.replace("\r\n", "\n").split("\n")
    first = next((i + 1 for i in range(1, len(lines)) if lines[i].strip() == "---"), 0) if lines[0].strip() == "---" else 0
    want = set(terms)
    toks = [set(_TOKEN.findall(ln.lower())) for ln in lines]
    has = [frozenset(t for t in want if t in w or (len(t) >= 4 and any(x.startswith(t) for x in w))) for w in toks]
    n = max(1, len(lines) - first)
    idf = {t: math.log(1 + n / (1 + sum(t in h for h in has[first:]))) for t in want}
    nums = {t for t in want if t.isdigit()}
    best, best_s = None, 0.0
    for i in range(first, len(lines)):
        nxt = _wraps(lines, i)
        s = sum(idf[t] for t in has[i]) + (0.5 * sum(idf[t] for t in has[i + 1] - has[i]) if nxt else 0.0)
        if not s:
            continue
        if lines[i].lstrip().startswith("#"):
            s *= 0.5
        if nums & toks[i]:
            s += NUM_BONUS
        if s > best_s:       # a tie keeps the earlier line
            best, best_s = i, s
    if best is None:
        return _window(body, terms, width)
    return _window(" ".join(lines[best:best + 2] if _wraps(lines, best) else lines[best:best + 1]), terms, width)


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


def _rules():
    """[(fact id, owner path, canonical text, [phrase regexes of its forbidden texts])] from <KB>/_shared/facts.json
    (kb_facts.load), or [] when there is no registry, it is unusable or locked, or no fact lists a forbidden text."""
    if not (kb_audit.ROOT / "_shared" / "facts.json").is_file():
        return []
    import kb_facts
    try:
        facts = kb_facts.load(kb_audit.ROOT)[0] or []
    except OSError:      # a registry still locked after savelock's retries: search without retired flags rather than not at all
        return []
    return [(f["id"], f["owner"].strip().strip("[]").replace("\\", "/").removeprefix("./").lstrip("/").removesuffix(".md") + ".md",
             f["canonical"], [kb_facts._phrase(x) for x in f["forbidden"]]) for f in facts if f.get("forbidden")]


def _retired(body, path, rules):
    """{"fact", "owner"} when the chunk states a forbidden text of a fact whose owner note this is not, on a line that
    does not carry SUPERSEDED (the same exemption kb_facts applies), else None."""
    for fid, owner, _canon, rxs in rules:
        if path != owner:
            for rx in rxs:
                for m in rx.finditer(body):
                    b = body.find("\n", m.start())
                    if "superseded" not in body[body.rfind("\n", 0, m.start()) + 1:b if b >= 0 else len(body)].lower():
                        return {"fact": fid, "owner": owner}
    return None


def _pin_owners(hits, limit, rules):
    """The owner note of every retired value goes directly above the first hit that states it, unless it is listed
    already; the list is cut to `limit` again. No retired hit, or none whose owner states the canonical text: no change."""
    if not any(h.get("retired") for h in hits):
        return hits
    import kb_facts
    canon = {r[0]: r[2] for r in rules}
    listed, out = {h["path"] for h in hits}, []
    for h in hits:
        r = h.get("retired")
        if r and r["owner"] not in listed:
            listed.add(r["owner"])
            try:
                raw = savelock.read_text(kb_audit.ROOT / r["owner"])
            except OSError:
                raw = ""
            m = kb_facts._phrase(canon[r["fact"]]).search(raw)
            if m:
                n = raw.count("\n", 0, m.start()) + 1
                head = next((x.group(2) for x in map(kb_index._HEAD.match, reversed(raw[:m.start()].split("\n"))) if x), "")
                out.append({"path": r["owner"], "line": n, "heading": head, "snippet": _window(raw.split("\n")[n - 1], [], 240),
                            "score": h["score"], "superseded": False, "pinned_for": r["fact"]})
        out.append(h)
    return out[:limit]


def _hit(path, line, heading, body, terms, score, rules=()):
    h = {"path": path, "line": line, "heading": heading, "snippet": _snippet(body, terms), "score": score,
         "superseded": bool(_SUP.search(body))}
    r = _retired(body, path, rules)
    if r:
        h["retired"] = r
    return h


def search(query, domain=None, limit=10, all_chunks=False):
    """Hits for a query, best first: one per note (its best chunk), or with all_chunks every chunk by its own score."""
    terms = terms_of(query)
    if not terms:
        return []
    rules = _rules()
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
                        hits.append(_hit(path, line, heading, body, terms, (score or 0) * (DEMOTE if _demoted(body, path) else 1.0), rules))
                if hits:
                    break
            hits.sort(key=lambda h: (h["score"], h["path"], h["line"]))   # bm25: lower is better
            return _pin_owners(hits[:limit], limit, rules)
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
    hits = [_hit(*rows[p][:4], terms, rrf * (DEMOTE if _demoted(rows[p][3], p) else 1.0), rules)
            for p, rrf in fused.items() if rows.get(p)]
    hits.sort(key=lambda h: (-h["score"], h["path"], h["line"]))
    for h in hits:
        h["score"] = round(h["score"], 6)
    return _pin_owners(hits[:limit], limit, rules)


def grep_search(query, domain=None, limit=10):
    """Search with no index: a scan of the notes (this process only, no subprocess). A note holding every word is a hit; only
    when none does, a note holding any word is. Ranked by how often the words occur (score = that count, higher is
    better); the chunk with the most occurrences supplies the snippet. Same hit shape as search()."""
    terms = terms_of(query)
    rules = _rules()
    found = []
    for p in kb_index.notes() if terms else []:
        rel = p.relative_to(kb_audit.ROOT).as_posix()
        if domain and not rel.startswith(f"{domain}/"):
            continue
        try:
            raw = savelock.read_text(p)
        except OSError:
            continue
        low = raw.lower()
        counts = [low.count(t) for t in terms]
        if any(counts):
            found.append((all(counts), sum(counts), rel, raw))
    pool = [f for f in found if f[0]] or found
    pool.sort(key=lambda f: (-f[1], f[2]))
    hits = []
    for _every, n, rel, raw in pool[:limit]:
        line, heading, body = max(kb_index.chunks_for(raw), key=lambda c: sum(c[2].lower().count(t) for t in terms))
        hits.append(_hit(rel, line, heading, body, terms, float(n), rules))
    return _pin_owners(hits, limit, rules)


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
    live = {}

    def holds(src, dst):
        if src not in live:
            live[src] = kb_index.live_links(src, existing, stems) if src in existing else set()
        return dst in live[src] and dst in existing
    con = sqlite3.connect(f"file:{kb_audit.index_db().as_posix()}?mode=ro", uri=True)
    seen, frontier, out, dead = {rel}, [rel], [], 0
    try:
        try:
            titles = dict(con.execute("select path, ftitle from note"))
        except sqlite3.Error:   # an index an older kit built: links resolve without the title rule
            titles = {}
        stems = kb_index.stems_of(existing, titles)
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
    db = kb_audit.index_db()
    mode, rebuilt, warn = "index", None, None   # warn: the ONE warning line when the index could not be brought up to date

    def say(msg):    # beside --json the warning goes to stderr, so stdout stays one JSON document
        print(msg, file=sys.stderr if a.json else sys.stdout)

    def oneline(e):
        return " ".join(f"{type(e).__name__}: {e}".split())[:160]
    try:
        rebuilt = ensure_index() if not a.no_rebuild or not db.exists() else None
    except Exception as e:   # noqa: BLE001  a held or scanned file, a full disk: answer anyway, never a traceback
        mode, warn = ("stale-index", f"WARNING: index rebuild failed ({oneline(e)}): results may be stale") if db.exists() \
            else ("grep", f"WARNING: index unavailable ({oneline(e)}): grep fallback")
    if a.related:
        rel = Path(a.related).as_posix()
        rel = rel.split(kb_audit.ROOT.as_posix() + "/", 1)[-1]
        try:
            res, dead = related(rel, a.depth) if mode != "grep" else ([], 0)
        except sqlite3.Error as e:   # the old index is unreadable too
            res, dead, warn = [], 0, f"WARNING: index unavailable ({oneline(e)}): no link data"
        if warn:
            say(warn)
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
    if mode != "grep":
        try:
            hits = search(a.query, a.domain, a.limit, a.all_chunks)
            ranking = index_mode()
        except sqlite3.Error as e:   # corrupt, or an index an older kit built that --no-rebuild left in place
            mode, warn = "grep", f"WARNING: index unavailable ({oneline(e)}): grep fallback"
    if mode == "grep":
        hits, ranking = grep_search(a.query, a.domain, a.limit), "grep"
    if a.scope == "all":
        hits += journal_hits(a.query, a.limit)
    if a.json:
        print(json.dumps({"query": a.query, "rebuilt": rebuilt, "mode": mode, "ranking": ranking, **({"warning": warn} if warn else {}),
                          "hits": hits}, indent=1, ensure_ascii=False))
        if warn:
            say(warn)
        return 0
    if warn:
        say(warn)
    if rebuilt:
        print(f"(index rebuilt: {rebuilt})")
    if not hits:
        print("no hits. Keyword search: retry once with the note's own words (a tool, host, error or ID).")
    for h in hits:
        tags = ("[SUPERSEDED] " if h.get("superseded") else "") + (f"[retired - live value in {h['retired']['owner']}] " if h.get("retired") else "") \
            + (f"[live value of {h['pinned_for']}] " if h.get("pinned_for") else "")
        print(f"{h['path']}:{h['line']}  [{h['heading']}]  {tags}{h['snippet']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
