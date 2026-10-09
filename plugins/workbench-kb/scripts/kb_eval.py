#!/usr/bin/env python3
"""kb_eval.py: known-answer retrieval check for the knowledge base. Does kb_search find the note that holds the
answer, near the top, and does it stay quiet about what the KB does not hold?

  kb_eval.py                      run <kb root>/kb_eval_set.json
  kb_eval.py --set FILE [--json]  another set; --json prints the summary as JSON
  kb_eval.py --set FILE --per-query   the summary plus one row per case (rank, top hit, milliseconds): for before/after diffs
  kb_eval.py --init               write a starter set to <kb root>/kb_eval_set.json (never overwrites)

A set is {"cases": [...], "_floors": {...}}. An answerable case is
  {"q": "how do we rotate the proxy cert", "expect": ["infra/proxy-cert.md"], "domain": null, "heading": "Rollover"}
`expect` lists the notes that answer it; `heading` (optional) is part of the heading of the section that must be the
hit shown, for a note that holds many answers; `domain` (optional) restricts the search. An abstain case is
  {"q": "a question about something the KB never mentions", "abstain": true}
and passes only when the search returns NOTHING: it checks the search does not invent a match. Use words that appear
nowhere in the KB; a query that shares even one word with some note falls back to that word and returns a weak hit.
Write cases from questions you really ask.

Reported: hit@1, hit@5 and MRR over the answerable cases (a hit is an expected note among the top K=10 rows, rank
counted from 1), `abstain` (the share of abstain cases that returned nothing), and p50 / p95 / mean search latency in
milliseconds over every case. Everything except latency_ms and the per-row "ms" is deterministic: two runs on one KB agree exactly.
`_floors` (optional) holds the least acceptable value of cases, abstain_cases, hit@1, hit@5, mrr and abstain; a result
below any of them is listed under "below_floors" and the exit code is 1. Exit 0 otherwise, or 2 when the set is
missing or invalid.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_audit  # noqa: E402

K = 10
FLOOR_KEYS = ("cases", "abstain_cases", "hit@1", "hit@5", "mrr", "abstain")
STARTER = {"cases": [{"q": "<a question you ask often>", "expect": ["<domain>/<note-that-answers-it>.md"],
                      "domain": None},
                     {"q": "<a question about something the KB never mentions>", "abstain": True}]}


def norm(p):
    return str(p or "").replace("\\", "/").lower()


def pct(values, p):
    """Percentile by the nearest-rank rule (0 for no values)."""
    s = sorted(values)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)] if s else 0.0


def evaluate(cases):
    import kb_search
    kb_search.ensure_index()
    rows = []
    for c in cases:
        t0 = time.perf_counter()
        hits = kb_search.search(c["q"], c.get("domain"), K)
        ms = round((time.perf_counter() - t0) * 1000, 2)
        top = hits[0]["path"] if hits else None
        if c.get("abstain"):
            rows.append({"q": c["q"], "kind": "abstain", "ok": not hits, "returned": len(hits), "top": top, "ms": ms})
            continue
        want = {norm(e) for e in c["expect"]}
        head = str(c.get("heading") or "").lower()
        rank = next((i + 1 for i, h in enumerate(hits)
                     if norm(h["path"]) in want and head in str(h["heading"] or "").lower()), None)
        rows.append({"q": c["q"], "kind": "answer", "rank": rank, "ms": ms, "top": top})
    ans = [r for r in rows if r["kind"] == "answer"]
    ab = [r for r in rows if r["kind"] == "abstain"]
    n = len(ans) or 1
    ms = [r["ms"] for r in rows]
    return {"cases": len(ans),
            "hit@1": round(sum(1 for r in ans if r["rank"] == 1) / n, 3),
            "hit@5": round(sum(1 for r in ans if r["rank"] and r["rank"] <= 5) / n, 3),
            "mrr": round(sum(1 / r["rank"] for r in ans if r["rank"]) / n, 3),
            "abstain_cases": len(ab),
            "abstain": round(sum(1 for r in ab if r["ok"]) / len(ab), 3) if ab else None,
            "latency_ms": {"p50": pct(ms, 50), "p95": pct(ms, 95), "mean": round(sum(ms) / (len(ms) or 1), 2)},
            "misses": [{k: v for k, v in r.items() if k != "ms"} for r in ans if not r["rank"] or r["rank"] > 5],
            "false_hits": [{k: v for k, v in r.items() if k != "ms"} for r in ab if not r["ok"]], "rows": rows}


def below_floors(result, floors):
    """The floor names the result falls under. A metric the result lacks (no abstain cases) counts as under."""
    return [k for k in FLOOR_KEYS if k in floors and (result.get(k) is None or result[k] < floors[k])]


def load(path):
    """(cases, floors) from a set file; ValueError when it is unusable."""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    cases = data.get("cases") if isinstance(data, dict) else None
    if not cases or not all(isinstance(c, dict) and isinstance(c.get("q"), str) and c["q"].strip()
                            and (c.get("abstain") is True or c.get("expect")) for c in cases):
        raise ValueError("a set needs cases, each with q and either expect or abstain: true")
    if any(c["q"].startswith("<") for c in cases):
        raise ValueError("the set still holds the starter placeholder: write real cases first")
    for c in cases:
        if isinstance(c.get("expect"), str):
            c["expect"] = [c["expect"]]
    floors = data.get("_floors") or {}
    if not isinstance(floors, dict) or not all(isinstance(v, (int, float)) for v in floors.values()):
        raise ValueError("_floors must map metric names to numbers")
    return cases, floors


def main(argv=None):
    ap = argparse.ArgumentParser(description="Known-answer retrieval check for the knowledge base.")
    ap.add_argument("--set")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--per-query", action="store_true", help="JSON with one row per case")
    ap.add_argument("--init", action="store_true")
    a = ap.parse_args(argv)
    path = Path(a.set) if a.set else kb_audit.kb_root() / "kb_eval_set.json"
    if a.init:
        if path.exists():
            print(f"exists, left alone: {path.as_posix()}")
            return 0
        path.write_text(json.dumps(STARTER, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.as_posix()}: replace the placeholders with 10-30 real questions and the notes that answer them")
        return 0
    try:
        cases, floors = load(path)
    except (OSError, ValueError) as e:
        print(f"no usable eval set at {path.as_posix()}: {e}. Create one with --init.", file=sys.stderr)
        return 2
    r = evaluate(cases)
    low = below_floors(r, floors)
    rc = 1 if low else 0
    if a.json or a.per_query:
        out = {k: v for k, v in r.items() if a.per_query or k != "rows"}
        out["floors"], out["below_floors"] = floors, low
        print(json.dumps(out, indent=2))
        return rc
    lat = r["latency_ms"]
    print(f"cases {r['cases']}  hit@1 {r['hit@1']}  hit@5 {r['hit@5']}  MRR {r['mrr']}  "
          f"abstain {r['abstain']} of {r['abstain_cases']}  p50 {lat['p50']} ms  p95 {lat['p95']} ms")
    for m in r["misses"]:
        print(f"  MISS (rank {m['rank'] or '>' + str(K)}): {m['q']}  -> top hit {m['top']}")
    for m in r["false_hits"]:
        print(f"  NOT QUIET ({m['returned']} hit(s)): {m['q']}  -> top hit {m['top']}")
    if low:
        print(f"  BELOW FLOORS: {', '.join(f'{k} {r[k]} < {floors[k]}' for k in low)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
