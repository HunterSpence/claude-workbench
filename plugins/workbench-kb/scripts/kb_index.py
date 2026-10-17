#!/usr/bin/env python3
"""kb_index.py: the knowledge base's search index, one SQLite file (stdlib sqlite3, FTS5).

  note     path, mtime_ns, size, title, ftitle (staleness: kb_search rebuilds when the disk moved on; ftitle = front-matter title)
  chunk    FTS5 over heading-aware chunks with porter stemming (a long note competes paragraph by paragraph)
  notefts  FTS5 over one row per note: path words, title, every heading (the per-note ranking kb_search fuses with chunk)
  section  path, line, heading, rid per chunk, indexed by path (finds a note's sections without scanning the FTS table)
  link     every wikilink outside code and HTML comments, resolved against the KB root (kb_health reports the dead ones)
  meta     built_at, kb_root, fts (whether FTS5 was available), schema (a cache from an older kit is rebuilt)

  kb_index.py build      full rebuild into a temp file, then an atomic swap (readers keep the old file meanwhile)
A full rebuild is the design: a few seconds for thousands of notes and no incremental state to drift.
ponytail: full rebuild every time; per-note updates by mtime if a KB ever grows past ~20k notes.
"""
import contextlib
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
SCHEMA = "3"             # 3: links resolve ignoring case, by slug and by title (note.ftitle); 2: notefts table added
HEADINGS_MAX = 8000      # characters of headings kept per note in notefts
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_WIKI = re.compile(r"\[\[([^\[\]\n]{1,300})\]\]")
_HEAD = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_FRONT = re.compile(r"\A﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_PLACEHOLDER = re.compile(r"^(?:\.\.\.|…)$|/(?:\.\.\.|…)$|<[^<>]*>")   # a template stand-in, not a link: dots, "dir/...", "<name>"
_MOUNT_POINT = 0xA0000003        # IO_REPARSE_TAG_MOUNT_POINT: an NTFS junction


def fts5_ok():
    if os.environ.get("KB_INDEX_NO_FTS5"):   # test hook: exercise the plain-table fallback on a Python that has FTS5
        return False
    con = sqlite3.connect(":memory:")
    try:
        con.execute("create virtual table t using fts5(x)")
        return True
    except sqlite3.Error:
        return False
    finally:
        con.close()


def is_junction(e):
    """True for an NTFS junction (a mount-point reparse point) among os.scandir entries. A OneDrive placeholder is a
    reparse point too, under another tag, and still holds real notes: it is NOT one. Python 3.12+ answers this itself."""
    if hasattr(e, "is_junction"):
        return e.is_junction()
    st = e.stat(follow_symlinks=False)
    return bool(getattr(st, "st_file_attributes", 0) & 0x400) and getattr(st, "st_reparse_tag", _MOUNT_POINT) == _MOUNT_POINT


def notes():
    """Every Markdown file the index covers (absolute paths, sorted): the whole KB root except hidden folders, daily/
    and any junction or symlink to a folder, which would list its notes twice or read notes from outside the KB."""
    root = kb_audit.ROOT
    out, stack = [], [root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            continue
        for e in entries:
            if e.name.startswith("."):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if not (d == root and e.name == "daily") and not is_junction(e):
                        stack.append(Path(e.path))
                elif e.name.lower().endswith(".md") and e.is_file():
                    out.append(Path(e.path))
            except OSError:
                continue
    return sorted(out)


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


def fm_title(raw):
    """The `title:` line of a note's front matter, else None. A heading is not a title here: a link names a title on
    purpose."""
    m = _FRONT.match(raw[:4000])
    t = m and re.search(r"(?m)^title:[ \t]*[\"']?(.+?)[\"']?[ \t]*$", m.group(1))
    return t.group(1).strip() if t else None


def _uncomment(ln, inside):
    """(the line without HTML-comment text, whether a comment is still open at its end)."""
    out = []
    while ln:
        if inside:
            i = ln.find("-->")
            if i < 0:
                break
            ln, inside = ln[i + 3:], False
        else:
            i = ln.find("<!--")
            if i < 0:
                out.append(ln)
                break
            out.append(ln[:i])
            ln, inside = ln[i + 4:], True
    return "".join(out), inside


def links_for(raw):
    """[(line, raw target)] for every wikilink outside code fences, inline code and HTML comments (one comment may span
    lines). A template stand-in such as dots, 'folder/...' or '<name>' is not a link and is left out."""
    out, fence, comment = [], False, False
    for n, ln in enumerate(raw.split("\n"), 1):
        if not comment and _FENCE.match(ln):
            fence = not fence
            continue
        if fence:
            continue
        ln, comment = _uncomment(re.sub(r"`[^`]*`", "", ln), comment)   # inline code first: a backticked comment opener hides nothing
        for m in _WIKI.finditer(ln):
            if not _PLACEHOLDER.search(m.group(1).split("|", 1)[0].strip()):
                out.append((n, m.group(1)))
    return out


class Names:
    """Index tables over the note paths (and, when given, their front-matter titles), built once so that many links
    resolve against one KB cheaply: file stems and whole paths with case ignored, and titles."""

    def __init__(self, existing, titles=None):
        self.stems, self.lower, self.titles = {}, {}, {}
        for p in existing:
            self.stems.setdefault(Path(p).stem.lower(), []).append(p)
            self.lower.setdefault(p.lower(), []).append(p)
        for p, t in (titles or {}).items():
            if t:
                self.titles.setdefault(" ".join(t.lower().split()), []).append(p)


def stems_of(existing, titles=None):
    """The Names tables for `existing` (note paths), with {path: front-matter title} for the title rule of resolve."""
    return Names(existing, titles)


def resolve(target, src_rel, existing, stems=None):
    """A wikilink target -> the KB-relative path it names, or None. In order: <target>.md from the KB root, beside the
    source and <target>/00-index.md, written exactly, then the same spellings with case ignored and with spaces turned
    into hyphens (My Note -> my-note.md); then a bare name (no folder) that is the file name of exactly ONE note, so a
    link such as bug-cards finds _shared/bug-cards.md; then a front-matter title that exactly ONE note has. A name two
    notes share stays dead at every step: guessing would link to the wrong one. '|alias' and '#heading' parts are
    dropped. Pass `stems` (stems_of(existing, titles)) when resolving many links against one `existing`."""
    t = target.split("|", 1)[0].split("#", 1)[0].strip().replace("\\", "/").strip("/")
    if not t:
        return None
    names = stems if isinstance(stems, Names) else Names(existing)
    src_dir = str(Path(src_rel).parent).replace("\\", "/")
    forms = list(dict.fromkeys((t, re.sub(r"\s+", "-", t))))
    cands = []
    for f in forms:
        base = f if f.lower().endswith(".md") else f + ".md"
        cands += [base, f"{src_dir}/{base}", f"{f}/00-index.md"]
    for cand in cands:
        if cand in existing:
            return cand
    for cand in cands:
        found = names.lower.get(cand.lower(), [])
        if found:
            return found[0] if len(found) == 1 else None
    if "/" not in t:
        for f in forms:
            found = names.stems.get((f[:-3] if f.lower().endswith(".md") else f).lower(), [])
            if found:
                return found[0] if len(found) == 1 else None
    found = names.titles.get(" ".join(t.lower().split()), [])
    return found[0] if len(found) == 1 else None


def disk_rels():
    """The KB-relative paths of every note on disk right now."""
    return {p.relative_to(kb_audit.ROOT).as_posix() for p in notes()}


def live_links(rel, existing, stems=None):
    """The notes that `rel` links to according to its CURRENT text (not the index), resolved against `existing`."""
    raw = savelock.read_text(kb_audit.ROOT / rel)
    stems = stems_of(existing) if stems is None else stems
    return {d for _n, t in links_for(raw) if (d := resolve(t, rel, existing, stems))}


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
            create table note(path text primary key, mtime_ns int, size int, title text, ftitle text);
            create table link(src text, line int, raw text, dst text);
            create table section(path text, line int, heading text, rid int);
            create index section_path on section(path);
            create table meta(k text primary key, v text);
        """ + ("create virtual table chunk using fts5(path unindexed, line unindexed, heading, body, "
               "tokenize='porter unicode61 remove_diacritics 2');"
               "create virtual table notefts using fts5(path unindexed, pathwords, title, headings, "
               "tokenize='porter unicode61 remove_diacritics 2');" if fts else
               "create table chunk(path text, line int, heading text, body text);"
               "create table notefts(path text, pathwords text, title text, headings text);"))
        titles, found = {}, []   # links are resolved once every note (and so every title) is known
        nchunks = 0          # also the rowid of the last chunk: ids are explicit so `section` can point at them
        for rel, p in rels.items():
            try:
                st = p.stat()
                raw = savelock.read_text(p)
            except OSError:
                continue
            title = title_of(raw, rel)
            titles[rel] = fm_title(raw)
            con.execute("insert into note values (?,?,?,?,?)", (rel, st.st_mtime_ns, st.st_size, title, titles[rel]))
            chs = chunks_for(raw)
            rows = [(nchunks + i, rel, line, h, body) for i, (line, h, body) in enumerate(chs, 1)]
            con.executemany("insert into chunk(rowid, path, line, heading, body) values (?,?,?,?,?)", rows)
            con.executemany("insert into section values (?,?,?,?)", [(rel, r[2], r[3], r[0]) for r in rows])
            nchunks += len(rows)
            heads = " | ".join(dict.fromkeys(h for _l, h, _b in chs if h))[:HEADINGS_MAX]
            con.execute("insert into notefts(path, pathwords, title, headings) values (?,?,?,?)",
                        (rel, re.sub(r"[\W_]+", " ", rel.rsplit(".", 1)[0]).strip(), title, heads))
            found.append((rel, links_for(raw)))
        names = stems_of(rels, titles)
        for rel, links in found:
            con.executemany("insert into link values (?,?,?,?)", [(rel, n, t, resolve(t, rel, rels, names)) for n, t in links])
        con.executemany("insert into meta values (?,?)", [("built_at", str(time.time())), ("kb_root", root.as_posix()),
                                                         ("fts", "1" if fts else "0"), ("schema", SCHEMA)])
        con.commit()
    except BaseException:
        con.close()
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
    con.close()
    try:
        savelock.retry_sharing(lambda: os.replace(tmp, db))
    except BaseException:    # a held or scanned index file: keep the old one, leave no half-built copy behind
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
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
            if dict(con.execute("select k, v from meta")).get("schema") != SCHEMA:
                return "index format is older than this kit"
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
