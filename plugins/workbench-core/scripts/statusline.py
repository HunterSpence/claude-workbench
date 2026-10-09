"""Status line: [model] effort, context used, prompt-cache hit % and warm/cold, folder, cost, rate limits, and a fallback warning. Reads the status
JSON on stdin; never throws (degrades to "[Claude]"). No network. The bootstrap copies this file to
<claude home>/workbench/statusline.py, which the settings fragment's statusLine command runs."""
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _norm(s):
    """A model id without its [1m]-style suffix and date stamp."""
    s = (s or "").strip().lower().split("[")[0]
    parts = s.split("-")
    return "-".join(parts[:-1]) if len(parts) > 1 and len(parts[-1]) == 8 and parts[-1].isdigit() else s


def _served(path, tail=262144):
    """The model that actually answered last, from the transcript tail. After a fallback the status JSON can still
    name the primary model; the transcript has the served one."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - tail))
        lines = f.read().decode("utf-8", "ignore").splitlines()
    for line in reversed(lines):
        if '"assistant"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        mm = (e.get("message") or {}).get("model")
        if e.get("type") == "assistant" and not e.get("isSidechain") and mm and mm != "<synthetic>":
            return mm
    return None


def line(j):
    parts = []
    m = j.get("model") or {}
    parts.append(f"[{m.get('display_name') or m.get('id') or 'Claude'}]")
    try:
        home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
        with open(os.path.join(home, "settings.json"), encoding="utf-8-sig") as f:
            pinned = _norm(json.load(f).get("model"))
        tp = j.get("transcript_path")
        actual = (_served(tp) if tp and os.path.exists(tp) else None) or m.get("id")
        a = _norm(actual)
        # ponytail: an alias pin ("opus") only matches by substring, so two versions of one family look the same.
        if pinned and a and (a != pinned if pinned.startswith("claude-") else pinned not in a):
            parts.append("FALLBACK:" + actual)
    except Exception:
        pass
    eff = (j.get("effort") or {}).get("level")
    if eff:
        parts.append(eff)
    pct = (j.get("context_window") or {}).get("used_percentage")
    if pct is not None:
        parts.append(f"ctx:{round(float(pct))}%")
    try:    # prompt_cache.hit_ratio (0-1, null early) and .warm (docs: statusline "Prompt cache fields"); absent = nothing shown
        pc = j.get("prompt_cache")
        hit, warm = pc.get("hit_ratio"), pc.get("warm")
        if pc.get("caching_observed") is not False and (hit is not None or warm is not None):
            parts.append("cache:" + (f"{round(float(hit) * 100)}%" if hit is not None else "")
                         + ("" if warm is None else (" " if hit is not None else "") + ("warm" if warm else "cold")))
    except Exception:
        pass
    cd = (j.get("workspace") or {}).get("current_dir") or j.get("cwd") or ""
    if cd:
        parts.append(os.path.basename(cd.rstrip("\\/")))
    cost = (j.get("cost") or {}).get("total_cost_usd")
    if cost is not None:
        parts.append(f"${float(cost):.2f}")
    rl = j.get("rate_limits") or {}
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        w = rl.get(key) or {}
        if w.get("used_percentage") is None:
            continue
        p = round(float(w["used_percentage"]))
        s = f"{label}:{p}%"
        if key == "five_hour" and w.get("resets_at"):
            mins = int((int(w["resets_at"]) - time.time()) // 60)
            if mins >= 0:
                s += f"~{mins // 60}h{mins % 60}m"
        parts.append(("!" if p >= 80 else "") + s)
    return " ".join(parts)


if __name__ == "__main__":
    try:
        data = json.loads(sys.stdin.read() or "{}")
        print(line(data if isinstance(data, dict) else {}))
    except Exception:
        print("[Claude]")
