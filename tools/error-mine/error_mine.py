#!/usr/bin/env python3
"""error_mine.py: mine Claude Code transcripts for failed tool calls and cluster them by root cause.

  python error_mine.py                     # mine + cluster, print the top clusters
  python error_mine.py --since 2026-01-01  # rank clusters by errors on/after a date
  python error_mine.py --out <dir>         # where errors_raw.json and clusters.json go

An error is a tool_result block with is_error == true, joined to its tool_use block (same id,
same file) for the tool name and input. Subagent transcripts are included. Clustering: exact
match after normalising numbers, ids and paths, then 5-gram Jaccard union-find at 0.55.

PRIVATE OUTPUT: the JSON files hold transcript excerpts, which can include file contents and
credentials. They are written outside the repo by default; never commit or share them.
Stdlib only.
"""
import argparse, glob, json, os, re, sys, tempfile
from collections import defaultdict

CONFIG = os.path.abspath(os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"))


def block_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content
                         if isinstance(c, str) or (isinstance(c, dict) and c.get("type") == "text"))
    return str(content)


def input_summary(inp):
    if not isinstance(inp, dict):
        return ""
    for k in ("command", "file_path", "pattern", "url", "query", "skill", "prompt"):
        if k in inp:
            return (k + "=" + str(inp[k]))[:400]
    return str(inp)[:200]


def mine(root, last=5000):
    errors = []
    for f in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        uses = {}
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"tool_use"' not in line and '"is_error"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                content = (rec.get("message") or {}).get("content") if isinstance(rec, dict) else None
                if not isinstance(content, list):
                    continue
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") == "tool_use":
                        uses[blk.get("id")] = (blk.get("name", "?"), blk.get("input"))
                    elif blk.get("type") == "tool_result" and blk.get("is_error"):
                        name, inp = uses.get(blk.get("tool_use_id"), ("?", None))
                        errors.append({"ts": rec.get("timestamp") or "", "tool": name, "input": input_summary(inp),
                                       "text": block_text(blk.get("content"))[:1500],
                                       "project": os.path.relpath(f, root).split(os.sep)[0],
                                       "subagent": os.sep + "subagents" + os.sep in f})
    errors.sort(key=lambda e: e["ts"])
    return len(errors), errors[-last:]


def normalize(t):
    t = t.lower()
    # Keep network-host identity before digits go, or one "connection refused" cluster swallows every host.
    hosts = [a or b for a, b in re.findall(r"(?:enotfound|econnrefused|etimedout|econnreset)\s+([a-z0-9.:\-]+)|https?://([a-z0-9.\-]+)", t)][:2]
    t = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>", t)
    t = re.sub(r"0x[0-9a-f]+", "<hex>", t)
    t = re.sub(r"\d+", "#", t)
    t = re.sub(r"[a-z]:[\\/][^\s'\"]+", "<path>", t)
    t = re.sub(r"/[^\s'\"]+", "<path>", t)
    t = re.sub(r"\s+", " ", t).strip()
    return ("h:" + ",".join(hosts) + " " if hosts else "") + t[:600]


def shingles(t, k=5):
    w = t.split()
    return {tuple(w)} if 0 < len(w) < k else {tuple(w[i:i + k]) for i in range(len(w) - k + 1)}


def cluster(errors, since="", threshold=0.55):
    groups = defaultdict(list)
    for i, e in enumerate(errors):
        groups[normalize(e["text"])].append(i)
    sigs = list(groups)
    sh = [shingles(s) for s in sigs]
    parent = list(range(len(sigs)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # ponytail: O(n^2) over unique signatures; fine for thousands, MinHash/LSH if it ever gets slow
    for i in range(len(sigs)):
        for j in range(i + 1, len(sigs)):
            inter = len(sh[i] & sh[j])
            if inter and inter / (len(sh[i]) + len(sh[j]) - inter) >= threshold:
                parent[find(j)] = find(i)
    members = defaultdict(list)
    for i, s in enumerate(sigs):
        members[find(i)].extend(groups[s])
    out = []
    for idxs in members.values():
        es = sorted((errors[i] for i in idxs), key=lambda e: e["ts"])
        tools = defaultdict(int)
        for e in es:
            tools[e["tool"]] += 1
        out.append({"count": len(es), "recent": sum(1 for e in es if e["ts"] >= since),
                    "first_seen": es[0]["ts"], "last_seen": es[-1]["ts"],
                    "tools": dict(sorted(tools.items(), key=lambda kv: -kv[1])),
                    "sample_text": es[-1]["text"][:800], "sample_input": es[-1]["input"][:300],
                    "older_inputs": [e["input"][:200] for e in es[:3]],
                    "projects": sorted({e["project"] for e in es})[:6],
                    "subagent": sum(1 for e in es if e["subagent"])})
    out.sort(key=lambda c: (-c["recent"], -c["count"]))
    return out


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--transcripts", default=os.path.join(CONFIG, "projects"))
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "error-mine"))
    ap.add_argument("--last", type=int, default=5000, help="keep the newest N errors")
    ap.add_argument("--since", default="", help="ISO date; clusters rank by errors on/after it")
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args(argv)
    total, errors = mine(a.transcripts, a.last)
    clusters = cluster(errors, a.since)
    os.makedirs(a.out, exist_ok=True)
    for name, data in (("errors_raw.json", {"total_all_time": total, "errors": errors}), ("clusters.json", clusters)):
        with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{total} errors all time; {len(errors)} analysed -> {len(clusters)} clusters (private output in {a.out})")
    for c in clusters[:a.top]:
        top_tool = next(iter(c["tools"]), "?")
        print(f"{c['count']:>5} recent={c['recent']:<4} {top_tool:<12} last={c['last_seen'][:10]}  {c['sample_text'][:90]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
