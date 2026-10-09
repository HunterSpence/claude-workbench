#!/usr/bin/env python3
"""devbench.py: a short, no-admin, memory-capped developer-speed bench (Python 3.10+, standard library only).

  py -3 bootstrap/devbench.py run [--budget-s 170] [--mb 1024] [--no-network] [--no-model-call] [--model ID] [--json]

Measures small-file create/delete (also inside the WSL home when a distro exists), git status and a local clone on a
generated 500-file repository, interpreter start-up, package-index lookups, Dev Drive presence and one model round
trip, then prints numbers and a plain verdict (fast / OK / slow, with the cause and the fix). Everything is created in
one temp directory that is deleted in `finally`; nothing else is written. `run` starts the measurement under
tools/memcap/memcap.py (Windows) so the peak memory is capped and reported.
"""
import argparse
import json
import os
import re
import shutil
import stat
import statistics
import subprocess
import sys
import tempfile
import time

IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0
OK_EXES = ("git", "py", "python", "python3", "node", "npm", "fsutil", "claude", "wsl")

# Verdict thresholds, the one table: metric -> (label, fast up to, OK up to [ms]); above the second is slow.
# then: why a slow value happens and what to ask for.
THRESHOLDS = {
    "small_files_ms": ("2,000 small files created and deleted", 2000, 8000),
    "wsl_small_files_ms": ("2,000 small files in the WSL home", 1500, 6000),
    "git_status_ms": ("git status, 500 files (median of 5)", 200, 800),
    "git_clone_ms": ("local git clone, 500 files", 2500, 9000),
    "python_start_ms": ("Python start-up (median of 5)", 120, 450),
    "node_start_ms": ("Node start-up (median of 5)", 100, 400),
    "pip_resolve_ms": ("pip index lookup", 3000, 10000),
    "npm_resolve_ms": ("npm registry lookup", 3000, 10000),
    "model_rtt_ms": ("model round trip, one short prompt", 6000, 20000),
}
CAUSES = {
    "small_files_ms": ("real-time scanning of new files is slow on this drive",
                       "ask IT for a Dev Drive or a scan exclusion for one dev folder"),
    "git_status_ms": ("many small file reads are being scanned",
                      "ask IT for a scan exclusion for the dev folder, or keep repositories inside WSL"),
    "git_clone_ms": ("many small file writes are being scanned",
                     "ask IT for a scan exclusion for the dev folder, or keep repositories inside WSL"),
    "python_start_ms": ("each process start is being scanned",
                        "ask IT to exclude the interpreter and tool folders from process-start scanning"),
    "node_start_ms": ("each process start is being scanned",
                      "ask IT to exclude the interpreter and tool folders from process-start scanning"),
    "pip_resolve_ms": ("the path to the package index is slow (proxy or traffic inspection)",
                       "ask IT about a proxy bypass for the package hosts or an internal package mirror"),
    "npm_resolve_ms": ("the path to the package registry is slow (proxy or traffic inspection)",
                       "ask IT about a proxy bypass for the package hosts or an internal package mirror"),
    "model_rtt_ms": ("the route to the model API is slow",
                     "check the proxy or VPN route to the model API with IT"),
    "wsl_small_files_ms": ("the WSL disk is slow",
                           "check the WSL disk location and memory settings"),
}


# ── process runner (the only child-process call; allowlisted by program name, always with a timeout) ──────────
def real_runner(argv, timeout=60, cwd=None, env=None):
    """-> (exit code, output bytes); exit code None = not found / timed out / could not start."""
    if os.path.splitext(os.path.basename(argv[0]))[0].lower() not in OK_EXES:
        raise ValueError("program not allowed: " + argv[0])
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from probe import resolve   # the same System32-first lookup the probe uses
    exe = resolve(argv[0])
    if not exe:
        return None, b""
    e = dict(os.environ, GIT_TERMINAL_PROMPT="0", PIP_NO_CACHE_DIR="1", PIP_DISABLE_PIP_VERSION_CHECK="1",
             npm_config_update_notifier="false", npm_config_logs_max="0", npm_config_audit="false",
             NODE_DISABLE_COMPILE_CACHE="1")
    e.update(env or {})
    try:
        p = subprocess.run([exe] + list(argv[1:]), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, timeout=timeout, cwd=cwd, env=e, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None, b""
    return p.returncode, p.stdout


def _rmtree(path):
    """Delete a folder tree; read-only files (git objects) are made writable first, as Windows requires."""
    def fix(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, **({"onexc": fix} if sys.version_info >= (3, 12) else {"onerror": fix}))


def _write_files(d, n):
    os.makedirs(d, exist_ok=True)
    for i in range(n):
        with open(os.path.join(d, "f%d.txt" % i), "w", encoding="utf-8") as f:
            f.write("line %d\n" % i * 4)


def _remove_files(d, n):
    for i in range(n):
        os.remove(os.path.join(d, "f%d.txt" % i))


def pick_model(denied=(), available=None):
    """Cheapest allowed alias: haiku, then sonnet, then opus; None when policy names none of them."""
    for alias in ("haiku", "sonnet", "opus"):
        if isinstance(available, list) and available:
            if any(alias in str(x).lower() for x in available):
                return alias
        elif not any(alias in str(x).lower() for x in denied):
            return alias
    return None


def judge(metrics, facts):
    """-> (verdict, because, fix) from the threshold table."""
    level, because, fix = 0, [], []
    by = {m["name"]: m["value"] for m in metrics}
    for m in metrics:
        t = THRESHOLDS.get(m["name"])
        if not t:
            continue
        lv = 2 if m["value"] > t[2] else 1 if m["value"] > t[1] else 0
        level = max(level, lv)
        if lv == 2 and m["name"] in CAUSES:
            cause, f = CAUSES[m["name"]]
            because.append("%s took %d ms (slow above %d): %s" % (t[0], m["value"], t[2], cause))
            if f not in fix:
                fix.append(f)
    w, s = by.get("wsl_small_files_ms"), by.get("small_files_ms")
    if level == 2 and w is not None and s is not None and w * 2 < s:
        because.append("the WSL file system is more than twice as fast as the Windows one")
        fix.append("keep repositories inside the WSL home")
    if level == 2 and "small_files_ms" in by and by["small_files_ms"] > THRESHOLDS["small_files_ms"][2] \
            and facts.get("dev_drive_query") != "ok":
        fix.append("a Dev Drive (performance-mode scanning) would help: ask IT")
    return ("fast", "OK", "slow")[level], because, fix


def run_bench(runner=real_runner, clock=time.monotonic, tmp_root=None, network=True, model_call=True, model=None,
              budget_s=170, n_files=2000, repo_files=500, reps=5):
    start = clock()
    metrics, skipped, facts = [], [], {}
    tmp = tempfile.mkdtemp(prefix="wb-bench-", dir=tmp_root)
    wsl_used = False
    py = ["py", "-3"] if IS_WIN else ["python3"]

    def left():
        return budget_s - (clock() - start)

    def add(name, vals, unit="ms"):
        metrics.append({"name": name, "value": int(round(statistics.median(vals))), "unit": unit, "n": len(vals)})

    def skip(name, why):
        skipped.append({"name": name, "why": why})

    def timed(fn):
        t = clock()
        fn()
        return (clock() - t) * 1000

    def repeat(name, argv, cwd=None):
        vals = []
        for _ in range(reps):
            if left() < 5:
                break
            t = clock()
            rc, _o = runner(argv, min(30, left()), cwd)
            if rc != 0:
                return skip(name, "command failed (exit %s)" % rc)
            vals.append((clock() - t) * 1000)
        if vals:
            add(name, vals)
        else:
            skip(name, "budget")

    try:
        add("small_files_ms", [timed(lambda: (_write_files(os.path.join(tmp, "files"), n_files),
                                              _remove_files(os.path.join(tmp, "files"), n_files)))])
        if IS_WIN and left() > 20:
            rc, out = runner(["wsl", "-l", "-q"], 10)
            names = [x for x in (out or b"").decode("utf-16-le", "replace").replace("\x00", "").split() if x]
            if rc == 0 and names and runner(["wsl", "-e", "true"], min(40, left()))[0] == 0:
                wsl_used = True
                sh = ("d=$(mktemp -d ~/wb-bench-XXXXXX); i=0; while [ $i -lt %d ]; do echo x > $d/f$i; i=$((i+1)); done; "
                      "rm -rf $d" % n_files)
                t = clock()
                rc, _o = runner(["wsl", "-e", "sh", "-c", sh], min(60, left()))
                if rc == 0:
                    add("wsl_small_files_ms", [(clock() - t) * 1000])
                else:
                    skip("wsl_small_files_ms", "command failed (exit %s)" % rc)
            else:
                facts["wsl_distro"] = False
        if left() > 15:
            repo = os.path.join(tmp, "repo")
            _write_files(repo, repo_files)
            g = ["git", "-c", "user.name=bench", "-c", "user.email=bench@example.com", "-c", "core.autocrlf=false",
                 "-c", "commit.gpgsign=false", "-c", "gc.auto=0"]
            if all(runner(g + a, 60, repo)[0] == 0 for a in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "bench"])):
                repeat("git_status_ms", ["git", "status", "--porcelain"], repo)
                if left() > 5:
                    t = clock()
                    rc, _o = runner(["git", "clone", "-q", repo, os.path.join(tmp, "clone")], min(60, left()), tmp)
                    add("git_clone_ms", [(clock() - t) * 1000]) if rc == 0 else skip("git_clone_ms", "command failed (exit %s)" % rc)
            else:
                skip("git_status_ms", "git unavailable or failed")
                skip("git_clone_ms", "git unavailable or failed")
        repeat("python_start_ms", py + ["-c", "pass"])
        repeat("node_start_ms", ["node", "-e", "0"])
        if network and left() > 10:
            t = clock()
            rc, _o = runner(py + ["-m", "pip", "--disable-pip-version-check", "--timeout", "5", "--retries", "0", "index",
                                  "versions", "pip"], min(40, left()))
            add("pip_resolve_ms", [(clock() - t) * 1000]) if rc == 0 else skip("pip_resolve_ms", "failed (exit %s)" % rc)
            t = clock()
            rc, _o = runner(["npm", "view", "npm", "version", "--fetch-timeout=5000", "--fetch-retries=0"], min(40, left()),
                            None, {"npm_config_cache": os.path.join(tmp, "npm")})
            add("npm_resolve_ms", [(clock() - t) * 1000]) if rc == 0 else skip("npm_resolve_ms", "failed (exit %s)" % rc)
        elif not network:
            skip("pip_resolve_ms", "--no-network")
            skip("npm_resolve_ms", "--no-network")
        else:
            skip("pip_resolve_ms", "budget")
        rc, _o = runner(["fsutil", "devdrv", "query"], 10)
        facts["dev_drive_query"] = "unknown" if rc is None else "ok" if rc == 0 else "failed"
        if not model_call:
            skip("model_rtt_ms", "--no-model-call")
        elif not model:
            skip("model_rtt_ms", "no allowed model alias")
        elif left() > 20:
            t = clock()
            rc, out = runner(["claude", "-p", "Reply with OK", "--model", model, "--output-format", "json", "--max-turns", "1",
                              "--strict-mcp-config", "--no-session-persistence"], min(90, left()))
            try:
                good = rc == 0 and json.loads((out or b"").decode("utf-8", "replace")).get("is_error") is False
            except (ValueError, AttributeError):
                good = False
            add("model_rtt_ms", [(clock() - t) * 1000]) if good else skip("model_rtt_ms", "call failed (exit %s)" % rc)
        else:
            skip("model_rtt_ms", "budget")
    finally:
        _rmtree(tmp)
        if wsl_used:
            runner(["wsl", "-e", "sh", "-c", "rm -rf ~/wb-bench-*"], 20)
    verdict, because, fix = judge(metrics, facts)
    return {"metrics": metrics, "verdict": verdict, "because": because, "fix": fix, "peak_mb": None, "skipped": skipped,
            "facts": facts, "duration_s": round(clock() - start, 1), "tmp_removed": not os.path.exists(tmp)}


def run_capped(budget_s=170, mb=1024, network=True, model_call=True, model=None):
    """Run the bench in a child process under tools/memcap/memcap.py; -> the bench dict plus peak_mb and cap_mb."""
    here = os.path.dirname(os.path.abspath(__file__))
    memcap = os.path.join(os.path.dirname(here), "tools", "memcap", "memcap.py")
    inner = [sys.executable, os.path.abspath(__file__), "inner", "--budget-s", str(budget_s)]
    inner += (["--no-network"] if not network else []) + (["--no-model-call"] if not model_call else [])
    inner += ["--model", model] if model else []
    capped = IS_WIN and os.path.isfile(memcap)   # ponytail: the address-space cap would break Node on Linux; Windows only
    cmd = [sys.executable, memcap, "--mb", str(mb), "--"] + inner if capped else inner
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                           timeout=budget_s + 40, creationflags=NO_WINDOW)
        doc = json.loads(next(ln for ln in reversed(p.stdout.splitlines()) if ln.startswith("{")))
        m = re.search(r"peak process memory (\d+) MB", p.stderr)
        doc["peak_mb"], doc["cap_mb"] = (int(m.group(1)) if m else None), (mb if capped else None)
        return doc
    except (OSError, subprocess.SubprocessError, StopIteration, ValueError) as e:
        return {"metrics": [], "verdict": None, "because": ["bench did not finish: %s" % type(e).__name__], "fix": [],
                "peak_mb": None, "cap_mb": mb, "skipped": [], "facts": {}}


def render(doc):
    lines = ["%-34s %8s %s (n=%d)" % (m["name"], m["value"], m["unit"], m["n"]) for m in doc["metrics"]]
    lines += ["skipped %s: %s" % (s["name"], s["why"]) for s in doc.get("skipped", [])]
    lines.append("verdict: %s" % doc["verdict"])
    lines += ["because: " + b for b in doc["because"]] + ["fix: " + f for f in doc["fix"]]
    if doc.get("peak_mb") is not None:
        lines.append("peak memory: %s MB (cap %s MB)" % (doc["peak_mb"], doc.get("cap_mb")))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Developer-speed micro-bench.")
    ap.add_argument("cmd", choices=("run", "inner"))
    ap.add_argument("--budget-s", type=int, default=170)
    ap.add_argument("--mb", type=int, default=1024)
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--no-model-call", action="store_true")
    ap.add_argument("--model")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "inner":
        print(json.dumps(run_bench(network=not a.no_network, model_call=not a.no_model_call, model=a.model,
                                   budget_s=a.budget_s)))
        return 0
    doc = run_capped(a.budget_s, a.mb, not a.no_network, not a.no_model_call, a.model or pick_model())
    print(json.dumps(doc) if a.json else render(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
