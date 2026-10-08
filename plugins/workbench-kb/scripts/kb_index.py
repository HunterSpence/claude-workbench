#!/usr/bin/env python3
"""kb_index.py: the knowledge base's search index, one SQLite file (stdlib sqlite3, FTS5).

  note   path, mtime_ns, size, title           (staleness: kb_search rebuilds when the disk moved on)
  chunk  FTS5 over heading-aware chunks with porter stemming (a long note competes paragraph by paragraph)
  link   every wikilink outside code, resolved against the KB root (kb_health reports the dead ones)
  meta   built_at, kb_root, fts (whether FTS5 was available)

  kb_index.py build      full rebuild into a temp file, then an atomic swap (readers keep the old file meanwhile)
A full rebuild is the design: a few seconds for thousands of notes and no incremental state to drift.
ponytail: full rebuild every time; per-note updates by mtime if a KB ever grows past ~20k notes.
"""
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_audit  # noqa: E402
import savelock  # noqa: E402

MAX_CHARS, OVERLAP = 1000, 150
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_WIKI = re.compile(r"\[\[([^\[\]\n]{1,300})\]\]")
_HEAD = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def fts5_ok():
    try:
        sqlite3.connect(":memory:").execute("create virtual table t using fts5(x)")
        return True
    except sqlite3.Error:
        return False


def notes():
    """Every Markdown file the index covers: the whole KB root except hidden folders and daily/ (paths relative to
    the KB root)."""
    root = kb_audit.ROOT
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.md")
                  if not any(s.startswith(".") for s in p.relative_to(root).parts) and p.relative_to(root).parts[0] != "daily")


def chunks_for(raw):
    """[(line, heading, body)]: split at headings, then into ~MAX_CHARS windows with OVERLAP, code fences kept whole
    inside a section."""
    out, sec, start, heading, fence = [], [], 1, "", False
    lines = raw.replace("\r\n", "\n").split("\n")

    def flush():
        text = "\n".join(sec).strip()
        i = 0
        while text and i < len(text):
            piece = text[i:i + MAX_CHARS]
            line = start + text[:i].count("\n")
            out.append((line, heading, piece))
            if i + MAX_CHARS >= len(text):
                break
            i += MAX_CHARS - OVERLAP
    for n, ln in enumerate(lines, 1):
        if _FENCE.match(ln):
            fence = not fence
        m = None if fence else _HEAD.match(ln)
        if m:
            flush()
            sec, start, heading = [ln], n, m.group(2)
        else:
            sec.append(ln)
    flush()
    return out


def title_of(raw, path):
    m = re.search(r"(?m)^title:\s*[\"']?([^\"'\n]+)", raw[:2000]) or re.search(r"(?m)^#\s+(.+)$", raw)
    return m.group(1).strip() if m else Path(path).stem


def links_for(raw):
    """[(line, raw target)] for every wikilink outside code fences and inline code."""
    out, fence = [], False
    for n, ln in enumerate(raw.split("\n"), 1):
        if _FENCE.match(ln):
            fence = not fence
            continue
        if fence:
            continue
        for m in _WIKI.finditer(re.sub(r"`[^`]*`", "", ln)):
            out.append((n, m.group(1)))
    return out


def resolve(target, src_rel, existing):
    """A wikilink target -> the KB-relative path it names, or None. Tries <target>.md from the KB root, beside the
    source, and <target>/00-index.md. '|alias' and '#heading' parts are dropped."""
    t = target.split("|", 1)[0].split("#", 1)[0].strip().replace("\\", "/").strip("/")
    if not t:
        return None
    base = t if t.endswith(".md") else t + ".md"
    src_dir = str(Path(src_rel).parent).replace("\\", "/")
    for cand in (base, f"{src_dir}/{base}", f"{t}/00-index.md"):
        if cand in existing:
            return cand
    return None


def build(db=None):
    """Rebuild the index. Returns a short status string; never leaves a half-built file in place."""
    t0 = time.monotonic()
    db = Path(db or kb_audit.index_db())
    db.parent.mkdir(parents=True, exist_ok=True)
    root = kb_audit.ROOT
    files = notes()
    rels = {p.relative_to(root).as_posix(): p for p in files}
    fts = fts5_ok()
    tmp = db.with_name(f"{db.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript("""
            create table note(path text primary key, mtime_ns int, size int, title text);
            create table link(src text, line int, raw text, dst text);
            create table meta(k text primary key, v text);
        """ + ("create virtual table chunk using fts5(path unindexed, line unindexed, heading, body, "
               "tokenize='porter unicode61 remove_diacritics 2');" if fts else
               "create table chunk(path text, line int, heading text, body text);"))
        nchunks = 0
        for rel, p in rels.items():
            try:
                st = p.stat()
                raw = savelock.read_text(p)
            except OSError:
                continue
            con.execute("insert into note values (?,?,?,?)", (rel, st.st_mtime_ns, st.st_size, title_of(raw, rel)))
            rows = [(rel, line, h, body) for line, h, body in chunks_for(raw)]
            con.executemany("insert into chunk(path, line, heading, body) values (?,?,?,?)", rows)
            nchunks += len(rows)
            con.executemany("insert into link values (?,?,?,?)",
                            [(rel, n, t, resolve(t, rel, rels)) for n, t in links_for(raw)])
        con.executemany("insert into meta values (?,?)", [("built_at", str(time.time())), ("kb_root", root.as_posix()),
                                                         ("fts", "1" if fts else "0")])
        con.commit()
    finally:
        con.close()
    savelock.retry_sharing(lambda: os.replace(tmp, db))
    return f"ok ({len(rels)} notes, {nchunks} chunks, {'fts5' if fts else 'plain table: no FTS5 in this Python'}, " \
           f"{time.monotonic() - t0:.1f}s)"


def stale(db=None):
    """None when the index matches the disk, else the reason it does not."""
    db = Path(db or kb_audit.index_db())
    if not db.exists():
        return "no index"
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            known = dict(con.execute("select path, mtime_ns from note"))
        finally:
            con.close()
    except sqlite3.Error as e:
        return f"unreadable index ({e})"
    root = kb_audit.ROOT
    disk = {}
    for p in notes():
        try:
            disk[p.relative_to(root).as_posix()] = p.stat().st_mtime_ns
        except OSError:
            continue
    if disk != known:
        changed = len(set(disk.items()) ^ set(known.items()))
        return f"{changed} note change(s) since the last build"
    return None


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        print(json.dumps({"index": kb_audit.index_db().as_posix(), "result": build()}))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
