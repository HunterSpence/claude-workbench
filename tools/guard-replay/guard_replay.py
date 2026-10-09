#!/usr/bin/env python3
"""guard_replay.py: before you ship a guard rule change, replay the tool calls in your own Claude Code transcripts
through the guard engine twice, once with the shipped rule packs (baseline) and once with your candidate pack, and see
which calls would be decided differently.

  py -3 <KIT>/tools/guard-replay/guard_replay.py --rules my_corporate.py [--transcripts DIR] [--strict] [--json]
  py -3 <KIT>/tools/guard-replay/guard_replay.py --self-test

--rules FILE.py   a candidate rule pack. A file named like a shipped pack (generic.py, corporate.py) REPLACES that pack
                  for the candidate run; any other name is ADDED to the shipped packs. The file's code is run.
--transcripts DIR the folder to read *.jsonl transcripts from (default <Claude config dir>/projects). Newest files first,
                  each tool_use id counted once, at most --max-calls calls (default 1000) from --max-files files (200).
--strict          exit 1 when the candidate lets through anything the baseline asked about or denied (looser).
--json            print every changed id instead of the first 40.

Safe by construction: the engine's log goes to a temporary folder (GUARDS_LOG_DIR is set before the engine loads and the
folder is deleted afterwards), so the live guard log is never written; events carry no session id, so no rule can touch
a session's task files; nothing is executed, the calls are only judged. The corporate pack reads your live allowlist,
read only. Output is counts, tool_use ids and guard ids. Command text, paths and prompts are never printed.
Exit 0 = replay done, 1 = --strict and a call got looser, 2 = unusable input (no transcripts, bad candidate).
"""
import argparse
import contextlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
GUARDS = KIT / "plugins" / "workbench-core" / "scripts" / "guards"
ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
GID = re.compile(r"\[workbench guard: ([A-Za-z0-9_.-]{1,40})\]")
RANK = {"pass": 0, "ask": 1, "deny": 2}


def claude_home():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def read_calls(root, max_files=200, max_calls=1000):
    """([(id, tool name, tool input, cwd)], capped): the tool_use blocks in the *.jsonl files under root."""
    files = sorted((p for p in Path(root).rglob("*.jsonl") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    calls, seen = [], set()
    for f in files[:max_files]:
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"tool_use"' not in line:
                    continue
                try:
                    d = json.loads(line)
                    blocks = d["message"]["content"]
                except (ValueError, KeyError, TypeError):
                    continue
                for b in blocks if isinstance(blocks, list) else ():
                    if not (isinstance(b, dict) and b.get("type") == "tool_use" and isinstance(b.get("input"), dict)
                            and isinstance(b.get("name"), str)):
                        continue
                    cid = b.get("id") if isinstance(b.get("id"), str) and ID.fullmatch(b["id"]) else f"call{len(calls) + 1}"
                    if cid in seen:
                        continue
                    seen.add(cid)
                    cwd = d.get("cwd") if isinstance(d, dict) and isinstance(d.get("cwd"), str) else ""
                    calls.append((cid, b["name"], b["input"], cwd))
                    if len(calls) >= max_calls:
                        return calls, True
    return calls, False


def decide(engine, name, ti, cwd):
    """("pass"|"ask"|"deny", [guard ids]) for one call. No session id on purpose (see the module doc)."""
    data = {"tool_name": name, "tool_input": ti}
    if cwd:
        data["cwd"] = cwd
    hs = (engine.evaluate(data) or {}).get("hookSpecificOutput") or {}
    d = hs.get("permissionDecision")
    return (d if d in ("ask", "deny") else "pass"), sorted(set(GID.findall(str(hs.get("permissionDecisionReason") or ""))))


@contextlib.contextmanager
def candidate_pack(engine, path):
    """The candidate pack installed in the engine for the duration; yields "replaces" or "adds"."""
    name = Path(path).stem
    key = "rulepacks." + name
    spec = importlib.util.spec_from_file_location(key, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    old_mod, old_packs = sys.modules.get(key), engine.PACKS
    sys.modules[key] = mod
    if name not in engine.PACKS:
        engine.PACKS = engine.PACKS + (name,)
    try:
        yield "replaces" if name in old_packs else "adds"
    finally:
        engine.PACKS = old_packs
        if old_mod is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = old_mod


def replay(engine, calls, rules):
    """The result dict: counts per phase and the calls whose decision changed. Raises on a candidate that will not load."""
    base = [decide(engine, n, ti, cwd) for _, n, ti, cwd in calls]
    packs = "+".join(engine.PACKS)
    with candidate_pack(engine, rules) as how:
        cand = [decide(engine, n, ti, cwd) for _, n, ti, cwd in calls]
    count = lambda rows: {k: sum(1 for r in rows if r[0] == k) for k in RANK}   # noqa: E731
    changed = [{"id": c[0], "baseline": b[0], "candidate": d[0], "guards": sorted(set(b[1]) | set(d[1]))}
               for c, b, d in zip(calls, base, cand) if b[0] != d[0]]
    for row in changed:
        row["direction"] = "looser" if RANK[row["candidate"]] < RANK[row["baseline"]] else "stricter"
    return {"calls": len(calls), "baseline_packs": packs, "candidate": f"{Path(rules).name} {how}", "baseline": count(base),
            "candidate_counts": count(cand), "changed": changed,
            "looser": sum(r["direction"] == "looser" for r in changed),
            "stricter": sum(r["direction"] == "stricter" for r in changed)}


def render(r, files_note):
    out = [f"guard-replay: {r['calls']} tool calls{files_note}; baseline = {r['baseline_packs']}; candidate = {r['candidate']}"]
    for label, k in (("baseline ", "baseline"), ("candidate", "candidate_counts")):
        c = r[k]
        out.append(f"{label}: pass {c['pass']}  ask {c['ask']}  deny {c['deny']}")
    out.append(f"changed: {len(r['changed'])}  (looser {r['looser']}, stricter {r['stricter']})")
    shown = r["changed"][:40]
    out += [f"  {x['id']}  {x['baseline']} -> {x['candidate']}  {x['direction']}  [{', '.join(x['guards']) or '-'}]" for x in shown]
    if len(shown) < len(r["changed"]):
        out.append(f"  ... and {len(r['changed']) - len(shown)} more (--json lists all)")
    return "\n".join(out)


def run(a, out=sys.stdout, err=sys.stderr):
    rules = Path(a.rules)
    if not (rules.is_file() and rules.suffix == ".py" and re.fullmatch(r"[A-Za-z_]\w*", rules.stem)):
        print("guard-replay: --rules must be an existing FILE.py whose name is a plain identifier", file=err)
        return 2
    root = Path(a.transcripts) if a.transcripts else claude_home() / "projects"
    if not root.is_dir():
        print(f"guard-replay: no transcripts folder at {root}", file=err)
        return 2
    calls, capped = read_calls(root, a.max_files, a.max_calls)
    if not calls:
        print("guard-replay: no tool calls found in the transcripts", file=err)
        return 2
    logdir = tempfile.mkdtemp(prefix="wb-guard-replay-")
    os.environ["GUARDS_LOG_DIR"] = logdir            # before the engine loads: the live log is never written
    try:
        sys.path.insert(0, str(GUARDS))
        import engine
        try:
            r = replay(engine, calls, rules)
        except Exception as e:
            print(f"guard-replay: the candidate pack failed to load or run ({type(e).__name__})", file=err)
            return 2
    finally:
        shutil.rmtree(logdir, ignore_errors=True)
    if a.json:
        print(json.dumps({**r, "capped": capped}), file=out)
    else:
        print(render(r, " (capped at --max-calls)" if capped else ""), file=out)
    return 1 if a.strict and r["looser"] else 0


def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        os.environ["CLAUDE_CONFIG_DIR"] = str(tmp / "claude")          # hermetic: no live allowlist, no live log
        os.environ["WORKBENCH_LOG_DIR"] = str(tmp / "live-logs")
        tr = tmp / "tr"
        tr.mkdir()
        rows = [("t1", "git push --force origin main"), ("t2", "echo hi"), ("t3", "echo selftest-marker")]
        (tr / "s.jsonl").write_text("\n".join(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": i, "name": "Bash", "input": {"command": c}}]}}) for i, c in rows) + "\n", encoding="utf-8")
        pack = tmp / "selftest_extra.py"
        pack.write_text("import engine as E\n\n\ndef marker(c):\n    if 'selftest-marker' in c.cmd:\n"
                        "        E.ask('x', 'selftest-rule')\n\n\nSHELL = (marker,)\n", encoding="utf-8")
        ns = argparse.Namespace(rules=str(pack), transcripts=str(tr), max_files=10, max_calls=100, strict=False, json=True)
        import io
        buf = io.StringIO()
        assert run(ns, buf) == 0
        r = json.loads(buf.getvalue())
        assert (r["baseline"], r["candidate_counts"]) == ({"pass": 2, "ask": 0, "deny": 1}, {"pass": 1, "ask": 1, "deny": 1}), r
        assert [(x["id"], x["direction"]) for x in r["changed"]] == [("t3", "stricter")], r
        assert not (tmp / "live-logs").exists()
    print("guard_replay self-test ok")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Replay transcript tool calls through the guards: shipped packs vs a candidate pack.")
    ap.add_argument("--rules", help="candidate rule pack: FILE.py")
    ap.add_argument("--transcripts", help="folder of *.jsonl transcripts (default <Claude config dir>/projects)")
    ap.add_argument("--max-files", type=int, default=200)
    ap.add_argument("--max-calls", type=int, default=1000)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    if not a.rules:
        ap.error("--rules is required")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
