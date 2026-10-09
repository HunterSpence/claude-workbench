#!/usr/bin/env python3
"""token_split.py: where the money in your Claude Code sessions goes, from your own local transcripts.

  py -3 <KIT>/tools/token-split/token_split.py [--days N] [--projects DIR] [--prices FILE] [--json] [--self-test]
  py -3 <KIT>/tools/token-split/token_split.py startup [--json] [--timeout SECONDS]

Reads the usage fields of each assistant message and the SIZE (character count) of its text and tool-call blocks from
<CH>/projects/**/*.jsonl (<CH> is CLAUDE_CONFIG_DIR or ~/.claude). It never prints, stores or sends any text, tool
argument or path. Claude Code writes one line per content block under the same message id and repeats the usage on
each, so usage is taken as the MAX per message id. Visible output is split into prose and tool-call arguments by
character share; thinking tokens are taken from usage.output_tokens_details.thinking_tokens when the transcript has it.
Prices come from settings/model-evidence.json (the `prices` key: the one home, also rendered in docs/models.md).
A model the table does not list is counted and named, never priced at a neighbour's rate. A one-hour cache write is
priced at twice the input price (the vendor's multiplier, evidence row E32).

`startup` measures the opening context instead of the spend: it runs `claude -p --output-format json` twice on one fixed
trivial prompt, once with your current settings and once with `--safe-mode` (every customisation off), and prints the
prompt tokens of each and the difference. It makes two real (tiny) model calls with your own sign-in.
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
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


# ---- startup: the context a session opens with, with and without your customisations -------------------------------
STARTUP_PROMPT = "Reply with the single word OK."          # fixed and trivial: the same bytes on both runs, no tool needed
SAFE_FLAG = "--safe-mode"
STARTUP_USAGE = (("input", "input_tokens"), ("cache_write", "cache_creation_input_tokens"), ("cache_read", "cache_read_input_tokens"))


def lists_flag(help_text, flag):
    return re.search(r"(?m)^\s*(?:-\w, )?" + re.escape(flag) + r"(?![\w-])", help_text) is not None


def _failed(why):
    print(f"token_split startup: {why}", file=sys.stderr)
    raise SystemExit(2)


def _kill_tree(p):
    """Stop p and everything it started. npm installs Claude Code behind a .cmd shim that runs claude as a child holding the
    pipes open: killing only the shim leaves the call waiting for the child."""
    try:
        if os.name == "nt":
            subprocess.run([os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe"), "/T", "/F", "/PID", str(p.pid)],
                           capture_output=True, timeout=30)
        else:
            os.killpg(p.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        p.kill()


def run_tree(argv, timeout, stdin_text=None):
    """(return code, stdout, stderr). Past the timeout the whole process tree is killed and reaped, then TimeoutExpired is raised."""
    kw = {} if os.name == "nt" else {"start_new_session": True}
    p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                         errors="replace", **kw)
    try:
        out, err = p.communicate(stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(p)
        try:
            p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        raise
    return p.returncode, out, err


def startup_call(claude, extra, timeout):
    """One headless turn: {input, cache_write, cache_read, context, turns}. Reads only the usage numbers, never the reply."""
    argv = [claude, "-p", "--output-format", "json", "--no-session-persistence", "--max-turns", "1", *extra]
    label = " ".join(["claude -p", *extra])
    try:
        code, stdout, stderr = run_tree(argv, timeout, STARTUP_PROMPT)
    except subprocess.TimeoutExpired:
        _failed(f"`{label}` timed out after {timeout} s and was stopped")
    except OSError as e:
        _failed(f"could not start claude ({type(e).__name__})")
    try:
        d = json.loads(stdout)
        if isinstance(d, list):
            d = next(x for x in reversed(d) if isinstance(x, dict) and x.get("type") == "result")
        u = d["usage"]
        out = {k: _int(u.get(src)) for k, src in STARTUP_USAGE}
        limit = d.get("subtype") == "error_max_turns"          # --max-turns 1 and the model called a tool: the first turn's usage is still real
        bad = (code or d.get("is_error")) and not limit
        if limit:
            out["turn_limit"] = True
    except (ValueError, KeyError, TypeError, StopIteration, AttributeError):
        out, bad = None, True
    if bad or out is None:
        first = next((ln.strip() for ln in stderr.splitlines() if ln.strip()), "")[:200]
        _failed(f"`{label}` gave no usable usage numbers (exit {code})" + (f": {first}" if first else ""))
    out["context"] = sum(out.values())
    out["turns"] = _int(d.get("num_turns")) or 1
    return out


def startup(timeout=180, as_json=False):
    claude = shutil.which("claude")
    if not claude:
        _failed("the claude command was not found on PATH")
    help_wait = min(60, timeout)
    try:
        _, out, err = run_tree([claude, "--help"], help_wait)
    except subprocess.TimeoutExpired:
        _failed(f"`claude --help` timed out after {help_wait} s and was stopped, so it is not known whether {SAFE_FLAG} exists")
    except OSError as e:
        _failed(f"could not start claude ({type(e).__name__})")
    help_text = out + err
    cur = startup_call(claude, [], timeout)
    if not lists_flag(help_text, SAFE_FLAG):
        print(_startup_table(cur, None))
        print(f"no baseline: this Claude Code does not list {SAFE_FLAG} in `claude --help`; update Claude Code to compare.", file=sys.stderr)
        return 2
    safe = startup_call(claude, [SAFE_FLAG], timeout)
    diff = cur["context"] - safe["context"]
    if as_json:
        res = {"current": cur, "safe_mode": safe, "difference": diff}
        if diff < 0:
            res["note"] = NEGATIVE
        print(json.dumps(res, indent=1))
    else:
        print(_startup_table(cur, safe))
    return 0


NEGATIVE = (f"the difference is negative: the current-settings run was smaller than the {SAFE_FLAG} run. That should not happen; "
            "run it again, and if it repeats do not rely on the number.")


def _startup_table(cur, safe):
    rows = [("current settings", cur)] + ([(SAFE_FLAG, safe)] if safe else [])
    L = ["startup context, one headless turn on a fixed prompt (tokens)",
         f"  {'':18s}{'input':>9s}{'cache write':>13s}{'cache read':>12s}{'context':>10s}"]
    L += [f"  {n:18s}{r['input']:9,d}{r['cache_write']:13,d}{r['cache_read']:12,d}{r['context']:10,d}" for n, r in rows]
    if safe:
        L.append(f"  {'difference':18s}{'':34s}{cur['context'] - safe['context']:10,d}   <- what your customisations add before you type")
    L.append("  context = input + cache write + cache read. A prefix an earlier run cached is billed as a cache read, so compare context.")
    if safe and cur["context"] < safe["context"]:
        L.append("  note: " + NEGATIVE)
    if any(r.get("turn_limit") for _, r in rows):
        L.append("  note: a run stopped at the one-turn limit because the model called a tool; its numbers cover that call, not only the opening context. Run it again.")
    if any(r["turns"] > 1 for _, r in rows):
        L.append("  note: a run used more than one turn (the model called a tool), so its numbers include later turns; run it again.")
    return "\n".join(L)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["startup"]:
        sp = argparse.ArgumentParser(prog="token_split.py startup", description="Opening context with your settings vs --safe-mode (two real, tiny model calls).")
        sp.add_argument("--json", action="store_true")
        sp.add_argument("--timeout", type=int, default=180, help="seconds allowed for each call")
        b = sp.parse_args(argv[1:])
        return startup(b.timeout, b.json)
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
