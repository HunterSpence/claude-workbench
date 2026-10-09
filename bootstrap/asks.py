"""asks.py: the ONE list of IT asks that setup, the doctor and the capability report all show (stdlib only).

The same blocked host used to produce an ask in the capability report, two in the doctor (two Day-1 checks, one embedding
model download) and two in the setup state. An ask is now identified by its text, compared case- and whitespace-
insensitively, and listed once with every place that raised it:

  key(text)              the comparison key
  merge(pairs)           [(text, source)] -> [{"ask", "sources"}], first wording kept, first-seen order
  gather(state_dir, report=None)
                         the deduplicated asks recorded in a state folder: setup-state.json (ask_it), knowledge-verify.json
                         (the asks of steps that are WARN or FAIL) and the capability report (the rows that are NEEDS-IT or
                         BLOCKED-BY-POLICY; `report` = a freshly built capability dict, else the newest capability-*.json)
"""
import glob
import json
import os


def key(text):
    return " ".join(str(text or "").lower().split())


def merge(pairs):
    out = {}
    for text, source in pairs:
        k = key(text)
        if k:
            e = out.setdefault(k, {"ask": " ".join(str(text).split()), "sources": []})
            if source not in e["sources"]:
                e["sources"].append(source)
    return list(out.values())


def _load(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def gather(state_dir, report=None):
    pairs = []
    for x in _load(os.path.join(state_dir, "setup-state.json")).get("ask_it") or []:
        if isinstance(x, dict):
            pairs.append((x.get("text"), "setup"))
    for s in _load(os.path.join(state_dir, "knowledge-verify.json")).get("steps") or []:
        if isinstance(s, dict) and s.get("status") in ("WARN", "FAIL"):
            pairs.append((s.get("ask_it"), "day-1 check " + str(s.get("id"))))
    if report is None:
        files = glob.glob(os.path.join(state_dir, "capability-*.json"))
        files = [f for f in files if os.path.basename(f) not in ("capability-diff.json",)]
        report = _load(max(files, key=os.path.getmtime)) if files else {}
    for r in report.get("features") or []:
        if isinstance(r, dict) and r.get("status") in ("NEEDS-IT", "BLOCKED-BY-POLICY"):
            pairs.append((r.get("ask_it"), "report " + str(r.get("id"))))
    return merge(pairs)
