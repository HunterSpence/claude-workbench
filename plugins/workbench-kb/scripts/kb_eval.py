#!/usr/bin/env python3
"""kb_eval.py: known-answer retrieval check for the knowledge base. Does kb_search find the note that holds the
answer, near the top?

  kb_eval.py                      run <kb root>/kb_eval_set.json
  kb_eval.py --set FILE [--json]  another set; --json prints per-case ranks (for before/after diffs)
  kb_eval.py --init               write a starter set to <kb root>/kb_eval_set.json (never overwrites)

A set is {"cases": [{"q": "how do we rotate the proxy cert", "expect": ["infra/proxy-cert.md"], "domain": null}]}.
Write cases from questions you really ask, with the note that answers each. A hit is the expected note among the top
K rows a reader sees. Reports hit@1, hit@5, MRR and the misses. Exit 0, or 2 when the set is missing or invalid.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_audit  # noqa: E402

K = 10
STARTER = {"cases": [{"q": "<a question you ask often>", "expect": ["<domain>/<note-that-answers-it>.md"],
                      "domain": None}]}


def norm(p):
    return str(p or "").replace("\\", "/").lower()


def evaluate(cases):
    import kb_search
    kb_search.ensure_index()
    rows = []
    for c in cases:
        t0 = time.perf_counter()
        hits = kb_search.search(c["q"], c.get("domain"), K)
        ms = (time.perf_counter() - t0) * 1000
        want = {norm(e) for e in c["expect"]}
        rank = next((i + 1 for i, h in enumerate(hits) if norm(h["path"]) in want), None)
        rows.append({"q": c["q"], "rank": rank, "ms": round(ms, 1), "top": hits[0]["path"] if hits else None})
    n = len(rows) or 1
    return {"cases": len(rows),
            "hit@1": round(sum(1 for r in rows if r["rank"] == 1) / n, 3),
            "hit@5": round(sum(1 for r in rows if r["rank"] and r["rank"] <= 5) / n, 3),
            "mrr": round(sum(1 / r["rank"] for r in rows if r["rank"]) / n, 3),
            "mean_ms": round(sum(r["ms"] for r in rows) / n, 1),
            "misses": [r for r in rows if not r["rank"] or r["rank"] > 5], "rows": rows}


def load(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    cases = data.get("cases") if isinstance(data, dict) else None
    if not cases or not all(isinstance(c, dict) and c.get("q") and c.get("expect") for c in cases):
        raise ValueError("a set needs cases, each with q and expect")
    if any(c["q"].startswith("<") for c in cases):
        raise ValueError("the set still holds the starter placeholder: write real cases first")
    return cases


def main(argv=None):
    ap = argparse.ArgumentParser(description="Known-answer retrieval check for the knowledge base.")
    ap.add_argument("--set")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--init", action="store_true")
    a = ap.parse_args(argv)
    path = Path(a.set) if a.set else kb_audit.kb_root() / "kb_eval_set.json"
    if a.init:
        if path.exists():
            print(f"exists, left alone: {path.as_posix()}")
            return 0
        path.write_text(json.dumps(STARTER, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.as_posix()}: replace the placeholder with 10-30 real questions and the notes that answer them")
        return 0
    try:
        cases = load(path)
    except (OSError, ValueError) as e:
        print(f"no usable eval set at {path.as_posix()}: {e}. Create one with --init.", file=sys.stderr)
        return 2
    r = evaluate(cases)
    if a.json:
        print(json.dumps(r, indent=2))
        return 0
    print(f"cases {r['cases']}  hit@1 {r['hit@1']}  hit@5 {r['hit@5']}  MRR {r['mrr']}  mean {r['mean_ms']} ms")
    for m in r["misses"]:
        print(f"  MISS (rank {m['rank'] or '>' + str(K)}): {m['q']}  -> top hit {m['top']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
