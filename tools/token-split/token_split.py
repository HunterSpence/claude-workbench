#!/usr/bin/env python3
"""token_split.py: where the money in your Claude Code sessions goes, from your own local transcripts.

  py -3 <KIT>/tools/token-split/token_split.py [--days N] [--projects DIR] [--prices FILE] [--json] [--self-test]

Reads the usage fields of each assistant message and the SIZE (character count) of its text and tool-call blocks from
<CH>/projects/**/*.jsonl (<CH> is CLAUDE_CONFIG_DIR or ~/.claude). It never prints, stores or sends any text, tool
argument or path. Claude Code writes one line per content block under the same message id and repeats the usage on
each, so usage is taken as the MAX per message id. Visible output is split into prose and tool-call arguments by
character share; thinking tokens are taken from usage.output_tokens_details.thinking_tokens when the transcript has it.
Prices come from settings/model-evidence.json (the `prices` key: the one home, also rendered in docs/models.md).
A model the table does not list is counted and named, never priced at a neighbour's rate. A one-hour cache write is
priced at twice the input price (the vendor's multiplier, evidence row E32).
"""
import argparse
import json
import os
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
PRICES_FILE = KIT / "settings" / "model-evidence.json"
FIELDS = ("input", "output", "cache_write", "cache_read")
ONE_HOUR_WRITE = 2.0
USAGE = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")


def load_prices(path=PRICES_FILE):
    """{model id: {"base": {...}, "long": {...} | None, "over": tokens}} from the JSON's `prices` key."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))["prices"]
        out = {}
        for model, p in data.items():
            lc = p.get("long_context")
            out[model] = {"base": {k: float(p[k]) for k in FIELDS},
                          "long": {k: float(lc[k]) for k in FIELDS} if lc else None,
                          "over": int(lc["over_tokens"]) if lc else 0}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        raise SystemExit(f"token_split: no usable `prices` in {path} ({type(e).__name__})")
    return out


def price_key(model, prices):
    """The longest listed id the transcript's model string is, or starts with followed by a non-alphanumeric."""
    m = model or ""
    hits = [k for k in prices if m == k or (m.startswith(k) and not m[len(k)].isalnum())]
    return max(hits, key=len) if hits else None


def _int(x):
    try:
        return max(int(x), 0)
    except (TypeError, ValueError):
        return 0


def read_messages(projects, days):
    """({message id: record}, files read). Usage fields are maxed per id; block sizes are summed over distinct blocks."""
    cut = time.time() - days * 86400
    files = [f for f in Path(projects).rglob("*.jsonl") if f.stat().st_mtime >= cut]
    msgs = {}
    for f in files:
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                m = d.get("message") if isinstance(d, dict) else None
                u = m.get("usage") if isinstance(m, dict) else None
                if not isinstance(u, dict) or not m.get("id"):
                    continue
                r = msgs.setdefault(m["id"], {"model": m.get("model"), "in": 0, "read": 0, "write": 0, "w1h": 0, "out": 0,
                                              "think": 0, "text": 0, "tool": 0, "sigs": set(), "thinking_seen": False})
                cc, det = u.get("cache_creation"), u.get("output_tokens_details")
                for k, v in (("in", u.get("input_tokens")), ("read", u.get("cache_read_input_tokens")),
                             ("write", u.get("cache_creation_input_tokens")), ("out", u.get("output_tokens")),
                             ("w1h", cc.get("ephemeral_1h_input_tokens") if isinstance(cc, dict) else 0),
                             ("think", det.get("thinking_tokens") if isinstance(det, dict) else 0)):
                    r[k] = max(r[k], _int(v))
                r["thinking_seen"] |= isinstance(det, dict) and "thinking_tokens" in det
                for b in m.get("content") or []:
                    if not isinstance(b, dict) or b.get("type") not in ("text", "tool_use"):
                        continue
                    sig = hash((b["type"], b.get("id") or b.get("text")))
                    if sig in r["sigs"]:
                        continue
                    r["sigs"].add(sig)
                    if b["type"] == "text":
                        r["text"] += len(b.get("text") or "")
                    else:
                        r["tool"] += len(json.dumps(b.get("input") or {}))
    return msgs, len(files)


def split(msgs, prices):
    """Aggregate cost by class. Returns the report dict (no content, only numbers and model ids)."""
    cost, unpriced, by_model = defaultdict(float), defaultdict(int), defaultdict(lambda: defaultdict(float))
    priced = 0
    for r in msgs.values():
        key = price_key(r["model"], prices)
        if key is None:
            unpriced[str(r["model"])[:60]] += 1
            continue
        p = prices[key]
        w5m, prompt = max(r["write"] - r["w1h"], 0), r["in"] + r["read"] + r["write"]
        t = p["long"] if p["long"] and prompt > p["over"] else p["base"]
        think = min(r["think"], r["out"])
        vis, chars = r["out"] - think, r["text"] + r["tool"]
        prose = vis * r["text"] / chars if chars else 0.0
        tool = vis * r["tool"] / chars if chars else 0.0
        parts = {"input": r["in"] * t["input"], "cache_write": w5m * t["cache_write"] + r["w1h"] * ONE_HOUR_WRITE * t["input"],
                 "cache_read": r["read"] * t["cache_read"], "output_thinking": think * t["output"],
                 "output_prose": prose * t["output"], "output_tool_args": tool * t["output"],
                 "output_other": (vis - prose - tool) * t["output"]}
        priced += 1
        for k, v in parts.items():
            cost[k] += v / 1e6
            by_model[key][k] += v / 1e6
        by_model[key]["messages"] += 1
    total = sum(cost.values())
    return {"messages": len(msgs), "priced_messages": priced, "unpriced_messages": dict(unpriced),
            "api_equivalent_usd": round(total, 4),
            "share": {k: round(v / total, 4) for k, v in sorted(cost.items())} if total else {},
            "by_model": {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in by_model.items()}}


def report(projects, days, prices):
    msgs, files = read_messages(projects, days)
    out = split(msgs, prices)
    out.update({"days": days, "files": files,
                "thinking_reported": any(r["thinking_seen"] for r in msgs.values())})
    return out


def self_test():
    """Offline fixture: max per id, tier by prompt size, the char split, an unpriced model, no content in the output."""
    prices = load_prices()
    haiku = next(k for k in prices if prices[k]["long"])
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp, "p")
        proj.mkdir()
        sentinel = "SENTINEL-" + "x" * 20
        mk = lambda mid, model, u, content: json.dumps({"type": "assistant", "message": {  # noqa: E731
            "id": mid, "model": model, "usage": u, "content": content}})
        lines = [mk("a", haiku, {"input_tokens": 50_000, "output_tokens": 4_000}, [{"type": "text", "text": sentinel}]),
                 mk("a", haiku, {"input_tokens": 50_000, "output_tokens": 10_000},
                    [{"type": "tool_use", "id": "t1", "input": {"k": sentinel}}]),
                 mk("b", haiku, {"input_tokens": 200_000, "output_tokens": 10_000}, []),
                 mk("c", "claude-unlisted-1", {"input_tokens": 5, "output_tokens": 5}, [])]
        proj.joinpath("s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        got = report(proj, 1, prices)
        p = prices[haiku]
        want = (50_000 * p["base"]["input"] + 10_000 * p["base"]["output"]
                + 200_000 * p["long"]["input"] + 10_000 * p["long"]["output"]) / 1e6
        assert abs(got["api_equivalent_usd"] - want) < 1e-3, (got["api_equivalent_usd"], want)
        assert got["messages"] == 3 and got["priced_messages"] == 2 and list(got["unpriced_messages"]) == ["claude-unlisted-1"]
        assert sentinel not in json.dumps(got)
    print("token_split self-test ok")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Split Claude Code spend by token class from local transcripts (no content read).")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--projects", default=str(Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"))
    ap.add_argument("--prices", default=str(PRICES_FILE))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    if not Path(a.projects).is_dir():
        print(f"token_split: no transcript folder at {a.projects}", file=sys.stderr)
        return 2
    res = report(a.projects, a.days, load_prices(a.prices))
    if a.json:
        print(json.dumps(res, indent=1))
        return 0
    print(f"last {res['days']} days: {res['messages']} messages in {res['files']} files, "
          f"{res['priced_messages']} priced; API-equivalent total {res['api_equivalent_usd']} USD")
    for k, v in res["share"].items():
        print(f"  {k:18s}{v * 100:6.1f}%")
    for m, n in res["unpriced_messages"].items():
        print(f"  not priced: {m} ({n} messages): add it to `prices` in settings/model-evidence.json")
    if not res["thinking_reported"]:
        print("  note: these transcripts report no thinking-token count, so thinking sits inside the output classes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
