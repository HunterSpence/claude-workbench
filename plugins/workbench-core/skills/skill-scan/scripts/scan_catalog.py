#!/usr/bin/env python3
"""SkillSpector catalog scan for Claude Code skills (stdlib only).

Scans every skill folder under <config dir>/skills (skipping archive folders) and
<config dir>/plugins/cache, static-only by default. Writes latest.json, latest.md and
scan-<ts>.json, and diffs high-signal counts against baseline.json so only NEW or
INCREASED risk is flagged.

  python scan_catalog.py                       # full static scan
  python scan_catalog.py --skills-dir <path>   # scan one folder of skills only
  python scan_catalog.py --llm-top 8           # + LLM re-pass on the 8 worst
  python scan_catalog.py --update-baseline     # accept current counts after review

Executable: $SKILLSPECTOR_EXE, else `skillspector` on PATH.
"""
import argparse, json, os, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

HIGH_SIGNAL = {"Data Exfiltration", "Prompt Injection", "Supply Chain", "Malicious Code",
               "MCP Tool Poisoning", "Memory Poisoning", "Rogue Agent"}
SKIP = {".git", "node_modules", ".venv", "__pycache__"}
CONFIG = os.path.abspath(os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"))


def skill_dirs(root, label):
    """Every dir holding a SKILL.md whose ancestors (below root) do not: a pack is one target."""
    out = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP and "archive" not in d.lower()]
        if "SKILL.md" in fns and dp != root:
            out[label + "/" + os.path.relpath(dp, root).replace(os.sep, "/")] = dp
            dns[:] = []
    return out


def scan(exe, reports, name, path, llm=False):
    fd = os.path.join(reports, "_raw", name.replace("/", "__") + ".json")
    os.makedirs(os.path.dirname(fd), exist_ok=True)
    cmd = [exe, "scan", path, "--format", "json", "-o", fd] + ([] if llm else ["--no-llm"])
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        subprocess.run(cmd, capture_output=True, timeout=900 if llm else 600, env=env,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        with open(fd, encoding="utf-8") as f:
            d = json.load(f)
    except subprocess.TimeoutExpired:
        return {"skill": name, "status": "TIMEOUT"}
    except Exception as e:
        return {"skill": name, "status": "SCAN_ERROR", "error": str(e)[:200]}
    issues = d.get("issues", [])
    hs = [i for i in issues if i.get("severity") in ("HIGH", "CRITICAL") and i.get("category") in HIGH_SIGNAL]
    ra = d.get("risk_assessment", {})
    return {"skill": name, "status": "OK", "score": ra.get("score"), "severity": ra.get("severity"),
            "issues": len(issues), "high_signal": len(hs),
            "top": [f'{i.get("severity")} {i.get("category")}/{i.get("pattern")} '
                    f'{i.get("location", {}).get("file")}:{i.get("location", {}).get("start_line")}'
                    for i in sorted(issues, key=lambda i: i.get("category") not in HIGH_SIGNAL)[:5]]}


def delta(rows, base):
    """NEW = high-signal findings in a skill the baseline never saw; int = change vs baseline."""
    for r in rows:
        if r["status"] == "OK":
            r["delta"] = r["high_signal"] - base[r["skill"]] if r["skill"] in base else ("NEW" if r["high_signal"] else 0)
    return [r for r in rows if r.get("delta") == "NEW" or (isinstance(r.get("delta"), int) and r["delta"] > 0)]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--skills-dir")
    ap.add_argument("--reports", default=os.path.join(CONFIG, "skill-scan-reports"))
    ap.add_argument("--llm-top", type=int, default=0)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    exe = os.environ.get("SKILLSPECTOR_EXE") or shutil.which("skillspector")
    if not exe or not os.path.exists(exe):
        print("SkillSpector not found: set SKILLSPECTOR_EXE or put skillspector on PATH (see SKILL.md Setup).", file=sys.stderr)
        return 2
    os.makedirs(a.reports, exist_ok=True)
    if a.skills_dir:
        targets = skill_dirs(os.path.abspath(a.skills_dir), "dir")
    else:
        targets = skill_dirs(os.path.join(CONFIG, "skills"), "skills")
        targets.update(skill_dirs(os.path.join(CONFIG, "plugins", "cache"), "plugin"))
    with ThreadPoolExecutor(max(1, a.workers)) as ex:
        rows = list(ex.map(lambda kv: scan(exe, a.reports, *kv), sorted(targets.items())))
    if a.llm_top:
        worst = sorted((r for r in rows if r["status"] == "OK"), key=lambda r: -(r["score"] or 0))[:a.llm_top]
        for r in worst:
            rows[rows.index(r)] = dict(scan(exe, a.reports, r["skill"], targets[r["skill"]], llm=True), llm=True)
    bpath = os.path.join(a.reports, "baseline.json")
    base = {}
    if os.path.exists(bpath):
        with open(bpath, encoding="utf-8") as f:
            base = json.load(f)
    flagged = delta(rows, base)
    ts = time.strftime("%Y%m%d-%H%M%S")
    rep = {"scanned_at": ts, "total": len(rows), "flagged_vs_baseline": [r["skill"] for r in flagged], "rows": rows}
    for fn in ("latest.json", f"scan-{ts}.json"):
        with open(os.path.join(a.reports, fn), "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1)
    md = [f"# SkillSpector catalog scan {ts}", f"{len(rows)} targets · flagged vs baseline: {len(flagged)}", "",
          "| skill | status | score | severity | issues | high-signal | delta |", "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: -(r.get("score") or 0)):
        md.append(f'| {r["skill"]} | {r["status"]} | {r.get("score", "")} | {r.get("severity", "")} | '
                  f'{r.get("issues", "")} | {r.get("high_signal", "")} | {r.get("delta", "")} |')
    with open(os.path.join(a.reports, "latest.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    if a.update_baseline:
        with open(bpath, "w", encoding="utf-8") as f:
            json.dump({r["skill"]: r["high_signal"] for r in rows if r["status"] == "OK"}, f, indent=1)
    errs = [r for r in rows if r["status"] != "OK"]
    print(f"{len(rows)} scanned · {len(errs)} errors/timeouts · {len(flagged)} flagged vs baseline "
          f"({len(base) or 'no'} baselined) -> {os.path.join(a.reports, 'latest.md')}")
    for r in sorted(rows, key=lambda r: -(r.get("score") or 0))[:15]:
        print(f'  {r.get("score", "-"):>4} {r.get("severity", r["status"]):<8} hs={r.get("high_signal", "-")} {r["skill"]}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
