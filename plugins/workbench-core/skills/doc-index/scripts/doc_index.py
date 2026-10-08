#!/usr/bin/env python3
"""doc_index.py: local full-text search over a folder of Office, PDF, HTML and Markdown files.

  python doc_index.py index  <folder>            add or update changed files (never deletes)
  python doc_index.py index  <folder> --rebuild  also delete rows for files no longer present
  python doc_index.py search "<query>" [--limit 10] [--path <substring>] [--json]
  python doc_index.py show   "<file>#p<N>" [--context 2]
  python doc_index.py report                     files that could not be indexed, and why
  python doc_index.py status

Office/PDF/HTML files are converted to Markdown with MarkItDown into a local cache; .md and
.txt are read as-is. Each paragraph becomes one row in a SQLite FTS5 index (BM25 ranking, no
vectors, no network). Changes are detected by size+mtime, then SHA-256. On Windows, OneDrive
"online-only" placeholders are skipped by their file attributes, so indexing never downloads.

The index and cache default to a per-folder directory under %LOCALAPPDATA%\\doc-index (Windows)
or ~/.cache/doc-index, never inside the indexed folder, so a synced library does not sync its
own index. Pass --db to choose; the folder is remembered in the index.
"""
import argparse, datetime, hashlib, json, os, re, shutil, sqlite3, sys, zipfile
import xml.etree.ElementTree as ET

EXTS = {".docx", ".pptx", ".xlsx", ".pdf", ".html", ".htm", ".md", ".markdown", ".txt"}
PLAIN = {".md", ".markdown", ".txt"}
OFFICE = {".docx", ".pptx", ".xlsx"}
# Windows file attributes that mark a cloud placeholder whose content is not on disk.
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # an encrypted or password-protected Office file is an OLE container
MAX_PARA = 1800

SCHEMA = """
create table if not exists meta(k text primary key, v text);
create table if not exists files(path text primary key, size int, mtime real, sha256 text, status text,
  error text, label text, paragraphs int, indexed_at text);
create virtual table if not exists para using fts5(path unindexed, pid unindexed, heading, body,
  tokenize='porter unicode61 remove_diacritics 2');
"""


def default_db(root):
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
    base = base or os.path.join(os.path.expanduser("~"), ".cache")
    key = hashlib.sha1(os.path.abspath(root).lower().encode()).hexdigest()[:12]
    return os.path.join(base, "doc-index", key, "index.sqlite")


def connect(db):
    os.makedirs(os.path.dirname(os.path.abspath(db)), exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("pragma journal_mode=wal")
    con.executescript(SCHEMA)
    return con


def is_cloud_only(st):
    return bool(getattr(st, "st_file_attributes", 0) & CLOUD_ONLY)


def walk(root):
    """(relpath, stat) for supported files. DirEntry.stat() reads cached attributes on Windows,
    so it never opens (and never hydrates) a placeholder."""
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if e.name.startswith((".", "~$")):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                elif os.path.splitext(e.name)[1].lower() in EXTS:
                    yield os.path.relpath(e.path, root).replace(os.sep, "/"), e.stat(follow_symlinks=False)
            except OSError:
                continue


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


MIP_NS = "{http://schemas.microsoft.com/office/2020/mipLabelMetadata}"   # [MS-OFFCRYPTO] section 2.6.4, Namespaces


def _xsd_true(v):
    return str(v).strip().lower() in ("1", "true")


LABEL_PART_CAP = 1024 * 1024   # label parts are a few hundred bytes; anything bigger is suspect


def _read_part(z, info):
    """A part's bytes, or None when it is larger than LABEL_PART_CAP. The size is checked before any
    decompression, and the read itself is bounded too, so a zip bomb cannot exhaust memory."""
    if info.file_size > LABEL_PART_CAP:
        return None
    with z.open(info) as f:
        data = f.read(LABEL_PART_CAP + 1)
    return None if len(data) > LABEL_PART_CAP else data


def sensitivity_label(path):
    """The file's sensitivity label, or None. Reads exactly two parts, matched case-insensitively:
    - docProps/custom.xml: MSIP_Label_<id>_Name (classic custom properties);
    - docMetadata/LabelInfo.xml (written when the tenant enables co-authoring for labelled files;
      [MS-OFFCRYPTO] 2.6.2-2.6.5): any label element with enabled true and removed not true counts,
      reported as "label <id>" when no name is available.
    Missing parts are normal. An oversized or unreadable part fails closed (counts as labelled)."""
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        return None
    with z:
        parts = {i.filename.lower(): i for i in z.infolist()}
        name = None
        info = parts.get("docprops/custom.xml")
        if info is not None:
            data = _read_part(z, info)
            if data is None:
                return "label (oversized custom properties part)"
            m = re.search(r'name="MSIP_Label_[0-9a-fA-F-]+_Name"[^>]*>\s*<vt:lpwstr>([^<]*)<', data.decode("utf-8", "replace"))
            name = m.group(1) if m else None
        info = parts.get("docmetadata/labelinfo.xml")
        if info is not None:
            data = _read_part(z, info)
            if data is None:
                return name or "label (oversized LabelInfo part)"
            try:
                root = ET.fromstring(data)
            except ET.ParseError:
                return name or "label (unreadable LabelInfo part)"
            for el in root.iter(MIP_NS + "label"):
                if _xsd_true(el.get("enabled")) and not _xsd_true(el.get("removed")):
                    return name or f"label {el.get('id') or '?'}"
        return name


_md = None


MAX_ZIP_MEMBERS = 10_000


def unzipped_too_big(path, cap_mb):
    """Reason string if an Office zip would expand past cap_mb or lists too many parts, else None.
    Uses the sizes in the zip directory only; nothing is decompressed."""
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
    except (OSError, zipfile.BadZipFile):
        return None   # not a readable zip: conversion reports the real error
    total = sum(i.file_size for i in infos)
    if total > cap_mb * 1024 * 1024 or len(infos) > MAX_ZIP_MEMBERS:
        return f"too large when uncompressed ({total // (1024 * 1024)} MB in {len(infos)} parts; cap {cap_mb} MB, {MAX_ZIP_MEMBERS} parts)"
    return None


def to_markdown(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in PLAIN:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    with open(path, "rb") as f:
        head = f.read(8)
    if ext in OFFICE and head == OLE_MAGIC:
        raise ValueError("encrypted, password-protected or rights-managed (OLE container, not an Office zip)")
    global _md
    if _md is None:
        try:
            from markitdown import MarkItDown
        except ImportError:
            raise RuntimeError("markitdown is not installed: pip install -r requirements.txt")
        _md = MarkItDown()
    return _md.convert(path).text_content or ""


def paragraphs(md):
    """[(heading, text)]: blank-line blocks; the latest Markdown heading travels with each block;
    blocks longer than MAX_PARA are split on line boundaries."""
    out, heading = [], ""
    for block in re.split(r"\n\s*\n", md.replace("\r\n", "\n")):
        block = block.strip()
        if not block:
            continue
        m = re.match(r"^(#{1,6})\s+(.+)$", block.splitlines()[0])
        if m:
            heading = m.group(2).strip()
        buf = ""
        for line in block.splitlines():
            if buf and len(buf) + len(line) > MAX_PARA:
                out.append((heading, buf.strip()))
                buf = ""
            buf += line + "\n"
        if buf.strip():
            out.append((heading, buf.strip()))
    return out


def cache_file(db, rel):
    return os.path.join(os.path.dirname(os.path.abspath(db)), "cache", hashlib.sha1(rel.encode()).hexdigest() + ".md")


def index(root, db, rebuild=False, max_mb=50, force=False, log=print, include_labelled=False, max_unzipped_mb=200):
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise SystemExit(f"not a folder: {root}")
    con = connect(db)
    con.execute("insert or replace into meta values('root', ?)", (root,))
    known = {r[0]: r for r in con.execute("select path, size, mtime, sha256, status from files")}
    seen, stats = set(), dict(new=0, updated=0, unchanged=0, failed=0, labelled=0, cloud_only=0, removed=0)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for rel, st in walk(root):
        seen.add(rel)
        full = os.path.join(root, rel)
        old = known.get(rel)
        if is_cloud_only(st):
            if not old:   # never indexed and not on disk: record why, keep going
                con.execute("insert or replace into files values(?,?,?,?,?,?,?,?,?)",
                            (rel, st.st_size, st.st_mtime, None, "cloud-only", "online-only placeholder; make it available offline to index it", None, 0, now))
            stats["cloud_only"] += 1
            continue
        done = ("ok", "failed", "skipped") + (() if include_labelled else ("labelled",))
        if old and not force and old[1] == st.st_size and old[2] == st.st_mtime and old[4] in done:
            # unchanged; a file that failed stays failed until it changes or --force retries it
            stats["labelled" if old[4] == "labelled" else "unchanged"] += 1
            continue
        bomb = unzipped_too_big(full, max_unzipped_mb) if os.path.splitext(rel)[1].lower() in OFFICE else None
        if bomb:   # checked before any part is decompressed or handed to the converter
            con.execute("delete from para where path=?", (rel,))
            con.execute("insert or replace into files values(?,?,?,?,?,?,?,?,?)",
                        (rel, st.st_size, st.st_mtime, None, "skipped", bomb, None, 0, now))
            stats["failed"] += 1
            continue
        label = sensitivity_label(full) if os.path.splitext(rel)[1].lower() in OFFICE else None
        if label and not include_labelled:   # never copy labelled content into the plaintext index by default
            con.execute("delete from para where path=?", (rel,))
            con.execute("insert or replace into files values(?,?,?,?,?,?,?,?,?)",
                        (rel, st.st_size, st.st_mtime, None, "labelled",
                         f"sensitivity label '{label}': skipped (index it only with --include-labelled, where policy allows)", label, 0, now))
            try:
                os.remove(cache_file(db, rel))
            except OSError:
                pass
            stats["labelled"] += 1
            continue
        if st.st_size > max_mb * 1024 * 1024:
            con.execute("insert or replace into files values(?,?,?,?,?,?,?,?,?)",
                        (rel, st.st_size, st.st_mtime, None, "skipped", f"larger than {max_mb} MB", None, 0, now))
            stats["failed"] += 1
            continue
        try:
            digest = sha256(full)
            if old and not force and old[3] == digest and old[4] == "ok":
                con.execute("update files set size=?, mtime=? where path=?", (st.st_size, st.st_mtime, rel))
                stats["unchanged"] += 1
                continue
            md = to_markdown(full)
        except Exception as e:   # one bad file must never stop the run
            con.execute("delete from para where path=?", (rel,))
            con.execute("insert or replace into files values(?,?,?,?,?,?,?,?,?)",
                        (rel, st.st_size, st.st_mtime, None, "failed", f"{type(e).__name__}: {str(e)[:300]}", None, 0, now))
            stats["failed"] += 1
            continue
        paras = paragraphs(md)
        cf = cache_file(db, rel)
        os.makedirs(os.path.dirname(cf), exist_ok=True)
        with open(cf, "w", encoding="utf-8") as f:
            f.write(md)
        con.execute("delete from para where path=?", (rel,))
        con.executemany("insert into para(path, pid, heading, body) values(?,?,?,?)",
                        [(rel, f"p{i}", h, t) for i, (h, t) in enumerate(paras, 1)])
        con.execute("insert or replace into files values(?,?,?,?,?,?,?,?,?)",
                    (rel, st.st_size, st.st_mtime, digest, "ok", None, label, len(paras), now))
        stats["updated" if old else "new"] += 1
        con.commit()
    gone = [p for p in known if p not in seen]
    if rebuild:
        if not seen and known:
            log("refusing to prune: no supported files found (is the folder offline or unmounted?)")
        else:
            for p in gone:
                con.execute("delete from para where path=?", (p,))
                con.execute("delete from files where path=?", (p,))
                try:
                    os.remove(cache_file(db, p))
                except OSError:
                    pass
            stats["removed"] = len(gone)
    elif gone:
        log(f"{len(gone)} indexed file(s) no longer present; run with --rebuild to remove them")
    con.commit()
    con.close()
    log(" · ".join(f"{k} {v}" for k, v in stats.items()) + f"  (index: {db})")
    return stats


def fts_query(q, op):
    terms = re.findall(r"\w+", q, re.UNICODE)
    return f" {op} ".join('"' + t.replace('"', "") + '"' for t in terms)


def search(db, query, limit=10, path_filter=None, per_file=3):
    con = connect(db)
    rows = []
    for op in ("AND", "OR"):   # all terms first; any term only if that finds nothing
        q = fts_query(query, op)
        if not q:
            con.close()
            return []
        rows = con.execute(
            "select path, pid, heading, snippet(para, 3, '[', ']', ' ... ', 24), bm25(para, 0, 0, 2.0, 1.0) as r "
            "from para where para match ? order by r limit ?", (q, limit * 10)).fetchall()
        if path_filter:
            rows = [r for r in rows if path_filter.lower() in r[0].lower()]
        if rows:
            break
    out, count = [], {}
    labels = dict(con.execute("select path, label from files"))
    con.close()
    for path, pid, heading, snip, rank in rows:
        if count.get(path, 0) >= per_file:
            continue
        count[path] = count.get(path, 0) + 1
        out.append({"ref": f"{path}#{pid}", "heading": heading, "snippet": " ".join(snip.split()),
                    "score": round(-rank, 3), "label": labels.get(path)})
        if len(out) >= limit:
            break
    return out


def show(db, ref, context=2):
    path, _, pid = ref.rpartition("#")
    if not path or not pid.startswith("p"):
        raise SystemExit("ref must look like <file>#p<N>")
    n = int(pid[1:])
    con = connect(db)
    root = dict(con.execute("select k, v from meta")).get("root", "")
    rows = con.execute("select pid, heading, body from para where path=?", (path,)).fetchall()
    con.close()
    rows = {int(p[1:]): (h, b) for p, h, b in rows}
    if n not in rows:
        raise SystemExit(f"no paragraph {pid} in {path}")
    lines = [f"source: {os.path.join(root, path)}"]
    for i in range(max(1, n - context), n + context + 1):
        if i in rows:
            lines.append(f"{'>>' if i == n else '  '} {path}#p{i} [{rows[i][0]}]\n{rows[i][1]}\n")
    return "\n".join(lines)


def purge(db, log=print):
    """Delete the index and its plaintext cache: the only copies doc-index ever made."""
    removed = []
    for f in (db, db + "-wal", db + "-shm"):
        if os.path.exists(f):
            os.remove(f)
            removed.append(f)
    cache = os.path.join(os.path.dirname(os.path.abspath(db)), "cache")
    if os.path.isdir(cache):
        shutil.rmtree(cache)
        removed.append(cache)
    try:
        os.rmdir(os.path.dirname(os.path.abspath(db)))   # only if now empty
    except OSError:
        pass
    log(f"purged {len(removed)} item(s) for index {db}" if removed else f"nothing to purge at {db}")
    return removed


def report(db):
    con = connect(db)
    rows = con.execute("select path, status, error from files where status != 'ok' order by status, path").fetchall()
    con.close()
    return rows


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="index file (default: per-folder under the local cache dir)")
    ap.add_argument("--purge", action="store_true", help="delete the index and its plaintext cache (with --folder or --db)")
    ap.add_argument("--folder", dest="purge_folder", help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("index")
    p.add_argument("folder")
    p.add_argument("--rebuild", action="store_true", help="also delete rows for files no longer present")
    p.add_argument("--force", action="store_true", help="re-convert every file")
    p.add_argument("--max-mb", type=int, default=50, help="skip files larger than this on disk")
    p.add_argument("--max-unzipped-mb", type=int, default=200,
                   help="skip Office files whose parts add up to more than this when uncompressed")
    p.add_argument("--include-labelled", action="store_true",
                   help="also index files carrying a sensitivity label (off by default)")
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--path", help="only results whose path contains this text")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("show")
    p.add_argument("ref")
    p.add_argument("--context", type=int, default=2)
    sub.add_parser("report")
    sub.add_parser("status")
    for name in ("search", "show", "report", "status"):
        sub.choices[name].add_argument("--folder", help="the indexed folder (to find its default index)")
    a = ap.parse_args(argv)
    folder = getattr(a, "folder", None) or a.purge_folder
    db = a.db or (default_db(folder) if folder else None)
    if not db:
        raise SystemExit("pass --db or --folder")
    if a.purge:
        purge(db)
        return 0
    if not a.cmd:
        ap.error("a command is required (index, search, show, report, status) unless --purge")
    if a.cmd == "index":
        index(a.folder, db, a.rebuild, a.max_mb, a.force, include_labelled=a.include_labelled,
              max_unzipped_mb=a.max_unzipped_mb)
    elif a.cmd == "search":
        res = search(db, a.query, a.limit, a.path)
        if a.json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
        else:
            for r in res:
                print(f"{r['ref']}  [{r['heading'] or '-'}]{'  label=' + r['label'] if r['label'] else ''}\n    {r['snippet']}")
            if not res:
                print("no matches (try fewer or different words; keyword search, not semantic)")
    elif a.cmd == "show":
        print(show(db, a.ref, a.context))
    elif a.cmd == "report":
        rows = report(db)
        for path, status, err in rows:
            print(f"{status:<11}{path}  {err or ''}")
        print(f"{len(rows)} file(s) not indexed")
    else:
        con = connect(db)
        meta = dict(con.execute("select k, v from meta"))
        print(f"root: {meta.get('root')}\nindex: {db}")
        for status, n in con.execute("select status, count(*) from files group by status"):
            print(f"{status:<11}{n}")
        print(f"paragraphs {con.execute('select count(*) from para').fetchone()[0]}")
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
