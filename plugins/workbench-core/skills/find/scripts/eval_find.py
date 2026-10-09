#!/usr/bin/env python3
"""eval_find.py: measures the find index. Standard library plus the skill's requirements; nothing is sent anywhere
except the one-time embedding model download.

  eval_find.py --out FILE [--require-vector-arm]      quality: golden corpus, keyword vs hybrid recall@5
  eval_find.py --latency --files N --out FILE         speed: p95 of 20 `files` queries over an N-file name-only tree
  eval_find.py --compare A.json B.json                exit 0 when two eval runs produced the same numbers

Quality run (golden/make_corpus.py + golden/golden.json): builds the corpus in a temporary folder, indexes it, embeds it,
then asks every golden query in four ways: keyword only, hybrid, dense only, and hybrid again over a copy of the index whose
vectors were shuffled between paragraphs (the control: a real gain must beat what noise vectors give). Relevance is
file-level: a query is found when an expected file is among the first five distinct files returned.
PASS needs: hybrid recall@5 > keyword recall@5 on the paraphrase set; the exact-phrase positive control at 0.9 or better
for keyword search; vectors > 0 and at least one relevant hit that only the dense arm found; real gain > shuffled gain.
--require-vector-arm fails the run when the vector arm could not run, instead of reporting keyword-only numbers.
"""
import argparse
import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "golden"))
sys.path.insert(0, os.path.join(HERE, "tests"))
import doc_index as di  # noqa: E402


def peak_working_set_mb():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes as wt

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        k, p = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k.GetCurrentProcess.restype = wt.HANDLE
        p.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(Counters), wt.DWORD]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        p.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return round(c.PeakWorkingSetSize / (1 << 20), 1)
    import resource
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def first_files(res, k=5):
    out = []
    for h in res["hits"]:
        if h["path"] not in out:
            out.append(h["path"])
    return out[:k]


def rank_of(files, expect):
    for i, f in enumerate(files, 1):
        if f in expect:
            return i
    return None


def recall(ranks):
    return round(sum(1 for r in ranks if r is not None) / len(ranks), 4) if ranks else None


def run_arm(con, db, queries, mode):
    ranks, dense_only = [], 0
    for q in queries:
        res = di.search(con, db, q["q"], mode=mode, limit=30, lazy=False, per_file=3)
        files = first_files(res)
        ranks.append(rank_of(files, q["expect"]))
        if mode == "hybrid":
            dense_only += sum(1 for h in res["hits"] if h["path"] in files and h["path"] in q["expect"]
                              and h["arms"]["bm25"] is None and h["arms"]["dense"] is not None)
    return ranks, dense_only, res["mode"], res["mode_reason"]


def dense_ranks(con, queries):
    emb = di.get_embedder(download=False)
    out = []
    for q in queries:
        ids = di.dense_arm(con, di.vec_of(next(iter(emb.query_embed(q["q"])))), None, None, None)
        rows = {r[0]: r[1] for r in con.execute("select p.id, f.name from paras p join files f on f.id=p.file_id where p.id in (%s)"
                                                % ",".join(map(str, ids)))} if ids else {}
        files = []
        for i in ids:
            if rows.get(i) not in files:
                files.append(rows.get(i))
        out.append(rank_of(files[:5], q["expect"]))
    return out


def shuffled_copy(db, dest, seed=1234):
    """A copy of the index whose vectors belong to other paragraphs: same shapes and norms, no meaning."""
    src, dst = sqlite3.connect(db), sqlite3.connect(dest)
    src.backup(dst)
    src.close()
    rows = dst.execute("select para_rowid, blob from vec").fetchall()
    blobs = [b for _i, b in rows]
    random.Random(seed).shuffle(blobs)
    dst.executemany("update vec set blob=? where para_rowid=?", [(b, i) for (i, _o), b in zip(rows, blobs)])
    dst.commit()
    dst.close()


def run_quality(out, require_vec):
    import make_corpus
    with open(os.path.join(HERE, "golden", "golden.json"), encoding="utf-8") as f:
        golden = json.load(f)
    work = tempfile.mkdtemp(prefix="wb-eval-")
    t0 = time.time()
    try:
        corpus = os.path.join(work, "corpus")
        names = make_corpus.build(corpus)
        db = os.path.join(work, "eval.sqlite")
        con = di.connect(db)
        label = di.add_root(con, corpus, "golden")
        stats = di.index_root(con, con.execute("select id, label, path from roots where label=?", (label,)).fetchone(), log=lambda *_: None)
        emb = di.embed_cmd(con, download=True)
        nvec = con.execute("select count(*) from vec").fetchone()[0]
        para, exact = golden["paraphrase"], golden["exact"]
        result = {"corpus": {"files": len(names), "indexed": stats["new"], "paragraphs": con.execute("select count(*) from paras").fetchone()[0]},
                  "vectors": nvec, "model": emb["model"], "vector_arm_reason": emb["mode_reason"]}
        arms = {}
        for name, qs in (("paraphrase", para), ("exact", exact)):
            kw, _d, _m, _r = run_arm(con, db, qs, "keyword")
            hy, dense_only, mode, reason = run_arm(con, db, qs, "hybrid")
            arms[name] = {"queries": len(qs), "keyword_ranks": kw, "hybrid_ranks": hy, "hybrid_mode": mode,
                          "keyword_recall5": recall(kw), "hybrid_recall5": recall(hy), "dense_only_hits": dense_only}
            if nvec and mode == "hybrid":
                arms[name]["dense_ranks"] = dense_ranks(con, qs)
                arms[name]["dense_recall5"] = recall(arms[name]["dense_ranks"])
        shuf = None
        if nvec:
            sdb = os.path.join(work, "shuffled.sqlite")
            shuffled_copy(db, sdb)
            scon = di.connect(sdb)
            sh, _d, smode, _r = run_arm(scon, sdb, para, "hybrid")
            scon.close()
            shuf = {"hybrid_ranks": sh, "hybrid_recall5": recall(sh), "mode": smode}
        con.close()
        p, e = arms["paraphrase"], arms["exact"]
        gain_real = round(p["hybrid_recall5"] - p["keyword_recall5"], 4)
        gain_shuf = round(shuf["hybrid_recall5"] - p["keyword_recall5"], 4) if shuf else None
        checks = {"hybrid_beats_keyword_on_paraphrase": p["hybrid_recall5"] > p["keyword_recall5"] and p["hybrid_mode"] == "hybrid",
                  "exact_control_keyword_recall5_ge_0.9": e["keyword_recall5"] >= 0.9,
                  "vectors_present": nvec > 0, "dense_only_hit_present": p["dense_only_hits"] >= 1,
                  "real_gain_beats_shuffled_gain": shuf is not None and gain_real > gain_shuf}
        result.update(metrics={"paraphrase": p, "exact": e, "shuffled": shuf, "gain_real": gain_real, "gain_shuffled": gain_shuf,
                               "dense_only_hits": p["dense_only_hits"]}, checks=checks)
        peak = peak_working_set_mb()
        checks["peak_working_set_below_3072_mb"] = peak < 3072
        result.update(peak_working_set_mb=peak, seconds=round(time.time() - t0, 1))
        result["pass"] = all(checks.values()) and (nvec > 0 or not require_vec)
        if require_vec and not nvec:
            result["pass"] = False
            result["error"] = f"the vector arm did not run: {emb['mode_reason']}"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    write(out, result)
    print(json.dumps({k: result[k] for k in ("vectors", "checks", "pass", "peak_working_set_mb")}, indent=1))
    print("paraphrase recall@5  keyword", result["metrics"]["paraphrase"]["keyword_recall5"], " hybrid", result["metrics"]["paraphrase"]["hybrid_recall5"],
          " shuffled", (result["metrics"]["shuffled"] or {}).get("hybrid_recall5"), " dense", result["metrics"]["paraphrase"].get("dense_recall5"))
    print("exact recall@5       keyword", result["metrics"]["exact"]["keyword_recall5"], " hybrid", result["metrics"]["exact"]["hybrid_recall5"],
          " dense_only_hits", result["metrics"]["dense_only_hits"])
    return 0 if result["pass"] else 1


def write(out, obj):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)


def latency_queries(n):
    """20 queries that exist in the tree (ten words, five word+number pairs, two folders, a number, a folder+word) and one that does not."""
    import fixtures
    qs = list(fixtures.TREE_WORDS)
    for k in (0, 1234, 20000, 31337, n - 1):
        qs.append(fixtures.tree_name(k)[1].rsplit(".", 1)[0].replace("-", " "))   # e.g. "review 000009"
    folder, name = fixtures.tree_name(777)
    qs += [fixtures.tree_name(42)[0], fixtures.tree_name(n // 2)[0], f"{folder} {name.split('-')[0]}"]
    qs += [f"{n - 1:06d}", "zzznomatch"]
    return qs
SNIPPET = ("import sys, json; sys.path.insert(0, %r); import doc_index as di\n"
           "di.main(['--db', %r, 'files', %r, '--json'])\n"
           "print('HEAVY=' + json.dumps([m for m in ('markitdown', 'numpy', 'fastembed') if m in sys.modules]))\n")


def run_latency(n, out):
    import fixtures
    work = tempfile.mkdtemp(prefix="wb-lat-")
    try:
        tree, db = os.path.join(work, "tree"), os.path.join(work, "lat.sqlite")
        t0 = time.time()
        made = fixtures.make_tree(tree, n)
        t1 = time.time()
        r = subprocess.run([sys.executable, os.path.join(HERE, "doc_index.py"), "--db", db, "index", tree], capture_output=True, text=True, encoding="utf-8")
        t2 = time.time()
        if r.returncode:
            print(r.stderr, file=sys.stderr)
            return 1
        rows = sqlite3.connect(db).execute("select count(*) from files").fetchone()[0]
        times, heavy, found = [], set(), []
        queries = latency_queries(made)
        for q in queries:
            s = time.perf_counter()
            p = subprocess.run([sys.executable, "-c", SNIPPET % (HERE, db, q)], capture_output=True, text=True, encoding="utf-8")
            times.append(round((time.perf_counter() - s) * 1000, 1))
            line = [ln for ln in p.stdout.splitlines() if ln.startswith("HEAVY=")]
            if p.returncode or not line:
                print(p.stderr, file=sys.stderr)
                return 1
            heavy.update(json.loads(line[0][6:]))
            found.append(len(json.loads("\n".join(p.stdout.splitlines()[:-1]))["files"]))
        srt = sorted(times)
        p95 = srt[int(0.95 * len(srt) + 0.999999) - 1]   # nearest rank: the 19th of 20
        res = {"files": made, "catalogued": rows, "queries_used": queries, "hits_per_query": found, "queries": len(times), "p95_ms": p95, "median_ms": srt[len(srt) // 2], "max_ms": srt[-1], "times_ms": times,
               "threshold_ms": 1000, "heavy_modules_imported": sorted(heavy), "tree_seconds": round(t1 - t0, 1), "index_seconds": round(t2 - t1, 1),
               "peak_working_set_mb": peak_working_set_mb()}
        real = [n for q, n in zip(queries, found) if q != "zzznomatch"]
        res["pass"] = p95 <= 1000 and not heavy and rows == made and all(real) and found[-1] == 0   # the queries must really find rows
        write(out, res)
        print(json.dumps({k: v for k, v in res.items() if k != "times_ms"}, indent=1))
        return 0 if res["pass"] else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


def compare(a, b):
    with open(a, encoding="utf-8") as fa, open(b, encoding="utf-8") as fb:
        ma, mb = json.load(fa)["metrics"], json.load(fb)["metrics"]
    same = ma == mb
    print("identical metrics" if same else "metrics differ")
    return 0 if same else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out")
    ap.add_argument("--latency", action="store_true")
    ap.add_argument("--files", type=int, default=50000)
    ap.add_argument("--require-vector-arm", action="store_true")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    a = ap.parse_args()
    if a.compare:
        return compare(*a.compare)
    if not a.out:
        ap.error("--out is required")
    return run_latency(a.files, a.out) if a.latency else run_quality(a.out, a.require_vector_arm)


if __name__ == "__main__":
    sys.exit(main())
