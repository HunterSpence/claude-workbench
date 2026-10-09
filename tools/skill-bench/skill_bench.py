#!/usr/bin/env python3
"""skill_bench.py: what does a skill ("arm") cost, and was it really applied? Cost and configuration only; this tool
never ranks model quality (that comes from published benchmarks: settings/model-evidence.json).

  skill_bench.py run      --runner claude|mock --model ID --arms baseline,ARM --pack PACK --reps N --out DIR
  skill_bench.py score    --out DIR [--json]
  skill_bench.py selftest --pack PACK

An arm is the text in arms/<name>.md appended to the system prompt; `baseline` adds none. Every arm also carries a
one-line trailer instruction whose code is the hash of the arm text. A run whose reply does not end with that trailer
had no arm proof: it is excluded and counted. Exit: 0 ok, 1 failed check, 2 usage or config error, 3 criteria changed
since the run started (scoring aborts), 4 usage limit (run stopped; rerun to resume).
"""
import argparse
import hashlib
import json
import math
import random
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import runner_claude  # noqa: E402
import runner_mock  # noqa: E402

PACK_FILES = ("criteria.md", "keys.json", "tasks.json")
NAME = re.compile(r"^[A-Za-z0-9_-]+$")
# Student t quantiles, index = degrees of freedom: 0.975 (two-sided 95% interval) and 0.80 (80% power).
T975 = [0, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.16, 2.145, 2.131,
        2.12, 2.11, 2.101, 2.093, 2.086, 2.08, 2.074, 2.069, 2.064, 2.06, 2.056, 2.052, 2.048, 2.045, 2.042]
T80 = [0, 1.376, 1.061, 0.978, 0.941, 0.92, 0.906, 0.896, 0.889, 0.883, 0.879, 0.876, 0.873, 0.87, 0.868, 0.866, 0.865,
       0.863, 0.862, 0.861, 0.86, 0.859, 0.858, 0.858, 0.857, 0.856, 0.856, 0.855, 0.855, 0.854, 0.854]


class Tamper(Exception):
    pass


def die(msg):
    print(f"skill_bench: {msg}")
    raise SystemExit(2)


# ---- pack, arms, proof ------------------------------------------------------------------------------------------
def criteria_sha256(pack):
    h = hashlib.sha256()
    for n in PACK_FILES:
        h.update(n.encode() + b"\0" + (pack / n).read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def check_criteria(meta, pack):
    if criteria_sha256(pack) != meta["criteria_sha256"]:
        raise Tamper(f"criteria, keys or tasks of pack {meta['pack']} changed since the run started")


def load_pack(packs_dir, name):
    if not NAME.match(name) or not (Path(packs_dir) / name / "tasks.json").is_file():
        die(f"no pack {name!r} in {packs_dir}")
    pack = Path(packs_dir) / name
    return pack, json.loads((pack / "tasks.json").read_text("utf-8")), json.loads((pack / "keys.json").read_text("utf-8"))


def grade(key, text):
    return all(re.search(p, text, re.I) for p in key.get("all", [])) and \
        not any(re.search(p, text, re.I) for p in key.get("none", []))


def selftest(tasks, keys):
    """The grader's own positive and negative control: the good reference passes, the bad one fails."""
    return [t["id"] for t in tasks if not (t["id"] in keys and grade(keys[t["id"]], keys[t["id"]]["good"])
                                           and not grade(keys[t["id"]], keys[t["id"]]["bad"]))]


def load_arms(names, arms_dir):
    arms = []
    for n in names:
        if not NAME.match(n):
            die(f"bad arm name {n!r}")
        f = Path(arms_dir) / f"{n}.md"
        if n != "baseline" and not f.is_file():
            die(f"no arm text {f}")
        text = "" if n == "baseline" else f.read_text("utf-8").replace("\r\n", "\n").strip()
        code = hashlib.sha256(text.encode()).hexdigest()[:10]
        stanza = f"Bench trailer: end every reply with one final line that is exactly [bench:{code}] and nothing else."
        arms.append({"name": n, "code": code, "system": (text + "\n\n" if text else "") + stanza})
    return arms


def split_trailer(text, code):
    """(proof, answer): proof is true when the last line of the reply is this arm's trailer."""
    lines = (text or "").rstrip().splitlines()
    if lines and lines[-1].strip().strip("`*_ ") == f"[bench:{code}]":
        return True, "\n".join(lines[:-1]).rstrip()
    return False, text or ""


# ---- statistics -------------------------------------------------------------------------------------------------
def t975(df):
    return T975[df] if df < len(T975) else 2.0 if df <= 60 else 1.98 if df <= 120 else 1.96


def t80(df):
    return T80[df] if df < len(T80) else 0.85 if df <= 60 else 0.842


def summarize(xs):
    n = len(xs)
    out = {"n": n, "mean": sum(xs) / n if n else None, "ci95": None, "mde": None, "verdict": "UNTESTED"}
    if n >= 2:
        se = statistics.stdev(xs) / math.sqrt(n)
        out["ci95"] = [out["mean"] - t975(n - 1) * se, out["mean"] + t975(n - 1) * se]
        out["mde"] = (t975(n - 1) + t80(n - 1)) * se
        if out["ci95"][0] > 0 or out["ci95"][1] < 0:
            out["verdict"] = "DETECTED"
    return out


def metrics(rec):
    u = rec["usage"]
    return {"output_tokens": u["output_tokens"], "total_tokens": sum(u.values()), "cost_usd": rec.get("cost_usd"),
            "wall_s": rec["wall_s"]}


def fmt(x):
    return "n/a" if x is None else f"{x:.4g}"


def fmt_ci(s):
    return "n/a" if not s["ci95"] else f"[{fmt(s['ci95'][0])}, {fmt(s['ci95'][1])}]"


# ---- run --------------------------------------------------------------------------------------------------------
def cmd_run(a):
    pack, tasks, keys = load_pack(a.packs_dir, a.pack)
    bad = selftest(tasks, keys)
    if bad:
        print(f"skill_bench: answer keys fail their own control for {bad}; a broken key would read as a broken model")
        return 2
    names = a.arms.split(",")
    arms = load_arms(names, a.arms_dir)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    meta = {"tool": "skill-bench", "runner": a.runner, "model": a.model, "pack": a.pack, "reps": a.reps,
            "packs_dir": str(Path(a.packs_dir).resolve()), "criteria_sha256": criteria_sha256(pack),
            "arms": {x["name"]: x["code"] for x in arms}, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    mf = out / "run.json"
    if mf.is_file():
        old = json.loads(mf.read_text("utf-8"))
        for k in ("runner", "model", "pack", "criteria_sha256", "arms"):
            if old[k] != meta[k]:
                print(f"skill_bench: {out} holds a different run ({k} differs); one directory holds one model and "
                      "one pack")
                return 2
        meta["started"], meta["reps"] = old["started"], max(old["reps"], a.reps)
    mf.write_text(json.dumps(meta, indent=1), encoding="utf-8", newline="\n")
    runner = runner_mock.MockRunner() if a.runner == "mock" else runner_claude.ClaudeRunner(keep_api_key=a.keep_api_key)
    jobs = []
    for rep in range(1, a.reps + 1):                    # rep-major, shuffled inside a rep: a partial run stays balanced
        block = [(x, t) for t in tasks for x in arms]
        random.Random(rep).shuffle(block)
        jobs += [(x, t, rep) for x, t in block]
    done = err = 0
    try:
        for x, t, rep in jobs:
            f = out / "runs" / x["name"] / f"{t['id']}__r{rep}.json"
            if f.exists():
                continue
            t0 = time.perf_counter()
            try:
                r = runner.call(a.model, x["system"], t["prompt"], ref=keys[t["id"]], arm=x["name"], rep=rep)
            except runner_claude.UsageLimit as e:
                print(f"STOPPED: usage limit after {done} new runs ({str(e)[:120]}); rerun the same command to resume")
                return 4
            wall = time.perf_counter() - t0
            tag = f"{x['name']}/{t['id']}/r{rep}"
            if r.get("is_error"):
                err += 1
                with (out / "errors.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(json.dumps({"run": tag, "error": r.get("error")}) + "\n")
                print(f"{tag}: ERROR {str(r.get('error'))[:100]}")
                continue
            proof, _ = split_trailer(r["result"], x["code"])
            rec = {"arm": x["name"], "task": t["id"], "rep": rep, "model": a.model, "runner": a.runner,
                   "wall_s": round(wall, 2), "arm_applied": proof, "proof": {"kind": "trailer", "arm_code": x["code"]},
                   "result": r["result"], "usage": r["usage"], "cost_usd": r.get("cost_usd"),
                   "duration_ms": r.get("duration_ms")}
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
            done += 1
            print(f"{tag}: ok out={r['usage']['output_tokens']} tok cost={fmt(r.get('cost_usd'))} usd "
                  f"wall={wall:.1f}s arm_applied={str(proof).lower()}")
    finally:
        runner.close()
    print(f"FINISHED new={done} errors={err} out={out}")
    return 1 if err else 0


# ---- score ------------------------------------------------------------------------------------------------------
def cmd_score(a):
    out = Path(a.out)
    meta = json.loads((out / "run.json").read_text("utf-8"))
    pack, tasks, keys = load_pack(a.packs_dir or Path(meta["packs_dir"]), meta["pack"])
    try:
        check_criteria(meta, pack)
    except Tamper as e:
        print(f"ABORT: {e}")
        return 3
    errored = len((out / "errors.jsonl").read_text("utf-8").splitlines()) if (out / "errors.jsonl").is_file() else 0
    expected = len(tasks) * len(meta["arms"]) * meta["reps"]
    scored, runs, excluded = {n: {} for n in meta["arms"]}, [], {n: 0 for n in meta["arms"]}
    for f in sorted((out / "runs").glob("*/*.json")):
        rec = json.loads(f.read_text("utf-8"))
        proof, answer = split_trailer(rec["result"], meta["arms"][rec["arm"]])
        runs.append({"arm": rec["arm"], "task": rec["task"], "rep": rec["rep"], "arm_applied": proof})
        if proof:
            rec["pass"] = grade(keys[rec["task"]], answer)
            scored[rec["arm"]][(rec["task"], rec["rep"])] = rec
        else:
            excluded[rec["arm"]] += 1
    res = {"tool": "skill-bench", "model": meta["model"], "pack": meta["pack"], "runner": meta["runner"],
           "criteria_sha256": meta["criteria_sha256"], "expected_runs": expected, "present_runs": len(runs),
           "errored_runs": errored, "excluded_no_proof": excluded, "arms": {}, "paired": {}, "runs": runs}
    base = scored.get("baseline", {})
    for n, recs in scored.items():
        cols = {m: [metrics(r)[m] for r in recs.values() if metrics(r)[m] is not None] for m in
                ("output_tokens", "total_tokens", "cost_usd", "wall_s")}
        k = sum(r["pass"] for r in recs.values())
        res["arms"][n] = {"n": len(recs), "metrics": {m: summarize(v) for m, v in cols.items()},
                          "answer_key_pass": {"pass": k, "of": len(recs)}}
        if n == "baseline" or not recs or not base:
            continue
        pairs = sorted(set(recs) & set(base))
        p = {"n_pairs": len(pairs), "metrics": {}, "broke": sum(base[q]["pass"] and not recs[q]["pass"] for q in pairs),
             "fixed": sum(recs[q]["pass"] and not base[q]["pass"] for q in pairs)}
        for m in ("output_tokens", "total_tokens", "cost_usd", "wall_s"):
            ab = [(metrics(recs[q])[m], metrics(base[q])[m]) for q in pairs]
            ab = [(x, y) for x, y in ab if x is not None and y is not None]
            s = summarize([x - y for x, y in ab])
            s["baseline_mean"] = sum(y for _, y in ab) / len(ab) if ab else None
            p["metrics"][m] = s
        res["paired"][n] = p
    (out / "score.json").write_text(json.dumps(res, indent=1), encoding="utf-8", newline="\n")
    if a.json:
        print(json.dumps(res, indent=1))
        return 0
    print(f"skill-bench score  model={meta['model']}  pack={meta['pack']}  runner={meta['runner']}")
    print(f"criteria_sha256 {meta['criteria_sha256']} (re-checked, unchanged)")
    print("cost and configuration only; no model quality ranking is produced (quality: published benchmarks)")
    print(f"runs: expected {expected}, present {len(runs)}, errored {errored}, "
          f"excluded for no arm proof {sum(excluded.values())}")
    for n, r in res["arms"].items():
        if excluded[n]:
            print(f"arm {n}: {excluded[n]} run(s) EXCLUDED, no arm proof" + ("; NO PROVEN RUNS" if not r["n"] else ""))
        print(f"arm {n}  n={r['n']}  answer-key control {r['answer_key_pass']['pass']}/{r['answer_key_pass']['of']}")
        for m, s in r["metrics"].items():
            print(f"  {m:14} mean {fmt(s['mean'])}  95% CI {fmt_ci(s)}")
        k = r["answer_key_pass"]
        if n == "baseline" and k["of"] and k["pass"] in (0, k["of"]):
            print("  note: baseline answer-key result is at the floor or ceiling; the key cannot separate arms")
    for n, p in res["paired"].items():
        print(f"paired {n} vs baseline  pairs={p['n_pairs']}  broke={p['broke']} fixed={p['fixed']} (answer-key flips)")
        for m, s in p["metrics"].items():
            if s["verdict"] == "DETECTED":
                rel = f" ({100 * s['mean'] / s['baseline_mean']:+.1f}% of baseline)" if s["baseline_mean"] else ""
                v = f"DETECTED{rel}"
            else:
                v = "UNTESTED" + (": fewer than 2 pairs" if s["mde"] is None else
                                  ": every pair was identical, so the MDE is not estimable" if s["mde"] == 0 else
                                  f": only differences of {fmt(s['mde'])} or more were detectable here")
            print(f"  {m:14} diff {fmt(s['mean'])}  95% CI {fmt_ci(s)}  MDE {fmt(s['mde'])}  {v}")
    for n in meta["arms"]:
        if n != "baseline" and base and n not in res["paired"]:
            print(f"paired {n} vs baseline: UNTESTED, no proven runs to pair")
    return 0


def cmd_selftest(a):
    _, tasks, keys = load_pack(a.packs_dir, a.pack)
    bad = selftest(tasks, keys)
    print("selftest FAIL " + ",".join(bad) if bad else f"selftest ok: {len(tasks)} key(s), good passes and bad fails")
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "score", "selftest"):
        p = sub.add_parser(name)
        p.add_argument("--packs-dir", default=str(HERE / "packs") if name != "score" else None)
        if name == "run":
            p.add_argument("--runner", choices=("claude", "mock"), required=True)
            p.add_argument("--model", required=True)
            p.add_argument("--arms", required=True, help="comma list; baseline adds no text")
            p.add_argument("--pack", required=True)
            p.add_argument("--reps", type=int, default=1)
            p.add_argument("--out", required=True)
            p.add_argument("--arms-dir", default=str(HERE / "arms"))
            p.add_argument("--keep-api-key", action="store_true", help="leave API-key variables in the child env")
        elif name == "score":
            p.add_argument("--out", required=True)
            p.add_argument("--json", action="store_true")
        else:
            p.add_argument("--pack", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "run" and a.reps < 1:
        ap.error("--reps must be >= 1")
    return {"run": cmd_run, "score": cmd_score, "selftest": cmd_selftest}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
