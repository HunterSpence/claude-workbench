#!/usr/bin/env python3
"""report.py: the capability report (Python 3.10+, standard library only).

  py -3 bootstrap/report.py run --phase pre|post|refresh [--quick] [--no-bench] [--no-model-call] [--detach]
                               [--out DIR] [--packages FILE] [--git-hosts H1,H2] [--extra-endpoint URL]...
  py -3 bootstrap/report.py diff A.json B.json

`run` probes the machine (read-only), optionally runs the dev-speed bench, rates every kit feature against
features.json plus rows generated from the package table, the MCP template and the model routing table, and writes
capability-<phase>.json / .md / .html (and probe-<phase>.json) under --out. `post` also writes capability-diff.json/.md
against capability-pre.json. Prints a short summary; exit 0 except for a usage error (2).
"""
import sys

sys.dont_write_bytecode = True   # this script writes under --out only, not a __pycache__ next to itself

import argparse  # noqa: E402
import datetime  # noqa: E402
import html  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import devbench  # noqa: E402
import probe  # noqa: E402

KIT = os.path.dirname(HERE)
R, I, N, B, U = "READY", "INSTALLABLE", "NEEDS-IT", "BLOCKED-BY-POLICY", "UNKNOWN"
STATUSES = (R, I, N, B, U)
ASK_PLUGINS = ("Please allow the kit's local plugin marketplace in the managed marketplace allow list "
               "(setting strictKnownMarketplaces).")
# Recommended minimum Claude Code per model: the only home of this number, so no doc repeats it. Source: the model-config page,
# https://code.claude.com/docs/en/model-config ("Use v2.1.293 or later with Haiku 5.5.").
MIN_CLAUDE_CODE = {"claude-haiku-5-5": (2, 1, 293)}
ASK_NODE = "Please allow Node.js on my managed laptop (see the Node.js request): the Playwright CLI installs through npm."
ASK_OUTLOOK_POLICY = ("Please confirm whether scripted read-only access to my own Outlook mailbox (local cache) is permitted "
                      "for a local, on-device search index, and the policy setting that governs it.")


# ── small helpers ─────────────────────────────────────────────────────────────────────────────────────────────
def D(p, name):
    return p["sections"][name]["data"]


def resolve(doc, pointer):
    """JSON pointer -> (found, value)."""
    cur = doc
    for part in pointer.lstrip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


def brief(v):
    s = json.dumps(v, default=str)
    if len(s) <= 200:
        return v
    return "<%d items>" % len(v) if isinstance(v, list) else "<%d keys>" % len(v) if isinstance(v, dict) else s[:200]


def tool(p, n):
    return D(p, "tools").get(n) or {}


def managed(p):
    return D(p, "policies")["managed_claude"]


def endpoints(p):
    return D(p, "network")["endpoints"]


def denies(name, val):
    n = name.lower()
    return (n.startswith(("allow", "enable")) and val == 0) or (n.startswith(("disable", "block", "prevent")) and val == 1)


# ── rules: rule_id -> fn(probe) -> (status, note[, ask]); ask = text, or True to keep the row's own ask_it ────────
RULES = {}


def rule(f):
    RULES[f.__name__] = f
    return f


@rule
def wsl2(p):
    if p["platform"] == "wsl":
        return R, "running inside WSL"
    if p["platform"] != "windows":
        return U, "WSL is a Windows feature"
    v, w, i = D(p, "virtualization"), D(p, "virtualization")["wsl"], D(p, "identity")
    if D(p, "policies")["wsl"].get("AllowWSL") == 0:
        return B, "the WSL policy (AllowWSL) is off"
    if w["installed"] and any(x.get("version") == 2 for x in w["distros"]):
        return R, "WSL2 with a distro"
    if w["installed"]:
        return I, "WSL is present; a distro can be added without admin rights"
    if v["virt_ok"] is False:
        return N, "virtualization is off in the firmware"
    if i["admin_capable"]:
        return I, "one admin prompt at setup adds the WSL component"
    if i["admin_capable"] is False:
        return N, "adding the WSL component needs admin rights"
    return U, "admin rights unknown"


@rule
def find_keyword(p):
    return (R, "search index tool present") if D(p, "knowledge")["find"]["available"] else (I, "installed with the kit")


@rule
def find_hybrid(p):
    f = D(p, "knowledge")["find"]
    if f["mode"] == "hybrid" and (f["vectors"] or 0) > 0:
        return R, "embeddings present"
    eps = [e for e in endpoints(p) if "huggingface" in e["url"]]
    if not eps:
        return U, "model host not in the package table"
    r = eps[0]["result"]
    if r == "ok":
        return I, "model host reachable; one download at setup"
    return (N, "model host not reachable") if r in ("blocked", "proxy-auth") else (U, "model host not tested")


@rule
def refresh_task(p):
    k = D(p, "knowledge")
    if k["refresh_task"]:
        return R, "the kit's task exists"
    if k["schedule_service"] == "Running":
        return I, "Task Scheduler is running; the task is created at setup"
    return (N, "Task Scheduler is not running") if k["schedule_service"] else (U, "Task Scheduler state unknown")


@rule
def scheduled_tasks(p):
    return refresh_task(p)


@rule
def capture_browser(p):
    c = D(p, "capture")
    if p["platform"] != "windows":
        return U, "the Edge route is Windows-only"
    if c["automation_allowed"] is False:
        return B, "Edge remote debugging is off by policy (RemoteDebuggingAllowed)"
    if c["app_installed"]:
        return R, "capture app installed"
    if not c["edge_path"]:
        return U, "Edge not found"
    if c["automation_allowed"] is None:
        return U, "Edge policy could not be read"
    return I, "needs the capture add-on and one interactive sign-in" + (
        "; headless mode is off by policy, a visible window is used" if c["headless_allowed"] is False else "")


@rule
def capture_deferred(p):
    return U, "deferred in this release: these web apps read data with POST requests, which capture blocks"


@rule
def capture_shared(p):
    kinds = {x.get("kind") for x in D(p, "knowledge")["libraries"]}
    if kinds & {"onedrive-business", "sharepoint-sync"}:
        return R, "synced libraries found: no capture needed"
    return capture_browser(p)


@rule
def capture_mail_full(p):
    c = D(p, "capture")
    oc, win = c["outlook_client"], c["outlook_cache_window"]
    if oc in ("classic", "both"):
        seen = "; sees only the cached window (%s)" % (win or "not set")
        om = c["outlook_object_model_policy"]
        if any(k in om and om[k] != 1 for k in ("PromptOOMAddressBookAccess", "PromptOOMAddressInformationAccess")):
            return B, "Outlook policy blocks or prompts scripted reads" + seen, ASK_OUTLOOK_POLICY
        return I, "local-cache route, InfoSec note first" + seen
    if oc == "new":
        return N, "the new Outlook keeps no local cache to read"
    return U, "no Outlook client found" if oc == "none" else "Outlook client not detected"


@rule
def knowledge_verified(p):
    """The Day-1 check of the whole knowledge chain (IK2), as the probe read it. No ask: a failing step has its own."""
    v = D(p, "knowledge").get("verify")
    if not isinstance(v, dict):
        return U, "not run yet: setup.py doctor --deep runs the Day-1 check of the knowledge chain"
    ok, warn, fail = v.get("pass", 0), v.get("warn", 0), v.get("fail", 0)
    total = ok + warn + fail
    if not total:
        return U, "the Day-1 check ran no step"
    if fail:
        return I, "%d/%d PASS, failing: %s; setup.py doctor --deep says why" % (ok, total, ", ".join(v.get("failing") or []) or "?")
    return R, "%d/%d PASS" % (ok, total) + (", %d warning(s)" % warn if warn else "")


@rule
def find_mcp(p):
    m = managed(p)
    if "find" in m["mcp_deny"] or (m["mcp_managed_only"] and "find" not in (m["mcp_allow"] or [])):
        return B, "managed MCP policy does not allow the local find server"
    return I, "registered by setup; a local stdio server, no network egress"


@rule
def capture_meeting_transcripts(p):
    return N, "needs read access to the user's own transcripts; nothing here proves it"


@rule
def ai_digests(p):
    return U, "a policy decision, not something a probe can show", True


@rule
def storage_work_cloud(p):
    w = D(p, "knowledge")["work_cloud"]
    if w["accounts"] == 1:
        return R, "knowledge Markdown can live in the work cloud"
    if w["accounts"] > 1:
        return U, "several work accounts: setup will ask which one"
    return U, "local-only fallback"


def _gh(kind, none_note):
    def f(p):
        hs = [h for h in D(p, "github")["hosts"] if h["kind"] == kind]
        if not hs:
            return U, none_note
        h, git = hs[0], tool(p, "git")
        if h["result"] == "ok":
            return (R, "host reachable") if git.get("works") else (I, "host reachable; git is installed by setup")
        if h["result"] in ("blocked", "proxy-auth"):
            return N, "%s is not reachable from here" % h["host"]
        return U, "not tested"
    return f


RULES["github_com"] = _gh("github.com", "github.com not tested")
RULES["github_ghe"] = _gh("ghe.com", "no host given: pass --git-hosts <tenant>.ghe.com")
RULES["github_ghes"] = _gh("ghes", "no host given: pass --git-hosts <your server>")


def plugin_rule(pid):
    def f(p):
        m, cl = managed(p), D(p, "claude")
        if any(x.startswith(pid + "@") for x in cl["plugins_installed"]):
            return R, "installed"
        if m["marketplaces_strict"]:
            return B, "managed marketplace allow list", ASK_PLUGINS
        return (I, "installed by setup") if tool(p, "claude").get("works") else (U, "Claude Code not found")
    return f


for _k, _pid in (("core", "workbench-core"), ("kb", "workbench-kb"), ("biz", "workbench-biz"), ("capture", "workbench-capture")):
    RULES["plugin_" + _k] = plugin_rule(_pid)
    RULES["skill_" + _k] = RULES["plugin_" + _k]


@rule
def hooks_guards(p):
    m = managed(p)
    if m["hooks_managed_only"] is True or m["disable_all_hooks"] is True:
        return B, "managed settings allow only managed hooks"
    if any(x.startswith("workbench-core@") for x in D(p, "claude")["plugins_installed"]):
        return R, "hooks installed with the core plugin"
    return (I, "installed with the core plugin") if tool(p, "claude").get("works") else (U, "Claude Code not found")


@rule
def sandbox(p):
    if p["platform"] in ("linux", "wsl"):
        return (R, "bubblewrap found") if tool(p, "bwrap").get("found") else (I, "install bubblewrap with the package manager")
    if p["platform"] == "windows" and wsl2(p)[0] in (R, I):
        return I, "needs WSL2 and bubblewrap inside the distro"
    return U, "no native Windows sandbox"


@rule
def powershell(p):
    """PowerShell as the probe's own session sees it, which is the session Claude Code's PowerShell tool gets too."""
    ps = D(p, "app_control").get("powershell") or {}
    mode = ps.get("language_mode") or "unknown"
    if mode in ("ConstrainedLanguage", "RestrictedLanguage", "NoLanguage"):
        return B, ("PowerShell runs in %s mode, so commands Claude runs and the kit's scripts may fail; "
                   "WSL or Git Bash are the fallback" % mode)
    if mode != "FullLanguage":
        return U, "the PowerShell language mode could not be read"
    hard = [("machine group policy", ps.get("gpo_machine")), ("user group policy", ps.get("gpo_user"))]
    hard = ["%s sets %s" % (src, v) for src, v in hard if v in ("Restricted", "AllSigned")]
    if hard:
        return N, ("Full Language mode, so commands work, but " + " and ".join(hard) +
                   " as the script policy, so .ps1 files will not run (the kit's scripts included)")
    eff = ps.get("execution_policy")
    if eff in ("Restricted", "AllSigned"):
        return R, ("Full Language mode and no group-policy script restriction; the effective script policy is %s (set on this "
                   "machine, not by group policy), so .ps1 files will not run until you change it for your user" % eff)
    return R, "Full Language mode and no group-policy script restriction"


@rule
def browser_automation(p):
    c = D(p, "capture")
    if c["automation_allowed"] is False:
        return B, "Edge remote debugging is off by policy (RemoteDebuggingAllowed)"
    node = tool(p, "node").get("works")
    cli = D(p, "tools")["packages"].get("playwright-cli") or {}
    named = ("; playwright-cli " + str(cli.get("version"))) if cli.get("works") else "; setup installs playwright-cli (npm)"
    if c["edge_path"] and c["automation_allowed"] and node:
        return R, "Edge and Node present, remote debugging allowed" + named + (
            "; Edge's HeadlessModeEnabled policy is off, so it opens a visible window" if c["headless_allowed"] is False else "")
    if c["edge_path"] and c["automation_allowed"] is None:
        return U, "Edge policy could not be read"
    return I, "missing: " + ", ".join(x for x, ok in (("Node", node), ("a browser", c["edge_path"])) if not ok)


def package_rule(pkg):
    def f(p):
        t = D(p, "tools")["packages"].get(pkg["id"])
        if t is None:
            return U, "not probed"
        if t["works"]:
            return R, "version %s" % t["version"]
        pol = D(p, "policies")
        for k in pkg.get("policy_keys") or []:
            if any(denies(n, v) for n, v in (pol["package_keys"].get(k) or {}).items() if isinstance(v, int)):
                return B, "policy key %s denies it" % k.rsplit("\\", 1)[-1]
        if pkg.get("source") == "winget" and pol["winget"].get("EnableAppInstaller") == 0:
            return B, "winget is switched off by policy"
        if pkg.get("source") == "msstore" and pol["store"].get("RemoveWindowsStore") == 1:
            return B, "the Store is switched off by policy"
        if pkg.get("source") == "npm" and not tool(p, "node").get("works"):
            return N, "needs Node.js, which is not available", ASK_NODE
        hosts = set(pkg.get("hosts") or [])
        bad = [e for e in endpoints(p) if probe.host_of(e["url"]) in hosts and e["result"] in ("blocked", "proxy-auth")]
        if bad:
            return N, "%s is not reachable from here" % probe.host_of(bad[0]["url"])
        if pkg.get("source") == "winget" and not tool(p, "winget").get("works"):
            return N, "winget is not available"
        if pkg.get("admin") or pkg.get("scope") == "machine":
            i = D(p, "identity")["admin_capable"]
            return (I, "one admin prompt at setup") if i else (N, "needs admin rights") if i is False else (U, "admin rights unknown")
        return I, "found but its version check failed" if t["found"] else "installs for this user without admin rights"
    return f


def mcp_rule(name, cfg):
    def f(p):
        m = managed(p)
        if name in m["mcp_deny"] or (m["mcp_managed_only"] and name not in (m["mcp_allow"] or [])):
            return B, "managed MCP policy does not allow it", "Please allow the MCP server '%s' in the managed MCP settings." % name
        if cfg.get("type") in ("http", "sse") or cfg.get("url"):
            return U, "hosted endpoint: not tested"
        cmd = str(cfg.get("command", ""))
        if cmd in ("npx", "node"):
            return (R, "runtime present") if tool(p, "node").get("works") else (I, "needs Node, installed by setup")
        if cmd.startswith("{{"):
            return (R, "binary found") if tool(p, name).get("found") else (I, "binary installed by setup")
        return U, "runtime not checked"
    return f


def claude_version(p):
    """The probed Claude Code version as (major, minor, patch), or None when it is missing or unparsable."""
    v = str(((p["sections"].get("claude") or {}).get("data") or {}).get("version") or "")[:200]   # cap what the regexes scan
    # a banner line may come first: prefer the token the tool labels as Claude Code, else the first x.y.z
    m = (re.search(r"(\d+)\.(\d+)\.(\d+)\s*\(Claude Code\)", v) or re.search(r"Claude Code\s+v?(\d+)\.(\d+)\.(\d+)", v, re.I)
         or re.search(r"(\d+)\.(\d+)\.(\d+)", v))
    return tuple(int(x) for x in m.groups()) if m else None


def model_rule(model, ids):
    def f(p):
        m = D(p, "models")
        mid = (ids.get(model) or {}).get(m["provider"]) or model
        ask = "Please allow the model %s in the managed model settings." % mid
        if any(mid.startswith(x) for x in m["denied"]):
            return B, "denied by managed settings", ask
        if isinstance(m["available"], list):
            if not any(mid.startswith(x) or x.startswith(mid) for x in m["available"]):
                return B, "not in the managed allow list", ask
            res = R, "named in the managed allow list"
        else:
            res = U, "not verified: no managed allow list"
        # The version check runs after every policy check (a blocked model stays blocked) and is advice only: setup never
        # runs `claude update`, so the status stays what policy and the install check decided and only the note changes.
        floor, have = MIN_CLAUDE_CODE.get(model), claude_version(p)
        if floor and have and have < floor:
            return res[0], ("%s. Claude Code %s found; v%s or later is recommended for %s: run claude update, or ask IT if the "
                            "version is pinned" % (res[1], ".".join(map(str, have)), ".".join(map(str, floor)), model))
        return res
    return f


# ── rows ──────────────────────────────────────────────────────────────────────────────────────────────────────
def load_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def row_defs(kit, packages_path=None, features=None):
    """Static rows from features.json plus rows generated from the package table, MCP template, routing and skills."""
    rows = [dict(r) for r in (features or load_json(os.path.join(HERE, "features.json")) or {}).get("rows", [])]
    ids = {r["id"] for r in rows}

    def add(r):
        if r["id"] not in ids:
            ids.add(r["id"])
            rows.append(r)
    pk = (load_json(packages_path or os.path.join(kit, "bootstrap", "packages.json")) or {}).get("packages") or []
    for x in pk:
        if isinstance(x, dict) and x.get("id"):
            add({"id": "pkg-" + x["id"], "group": "provision", "feature": "Install " + str(x.get("name") or x["id"]),
                 "evidence": ["/sections/tools/data/packages/" + x["id"].replace("~", "~0").replace("/", "~1"),
                              "/sections/identity/data/admin_capable"],
                 "ask_it": x.get("ask_it"), "unlocks": [], "_fn": package_rule(x)})
    for name, cfg in ((load_json(os.path.join(kit, "mcp", "golden-config.template.json")) or {}).get("servers") or {}).items():
        add({"id": "mcp-" + name, "group": "mcp", "feature": "MCP server: " + name,
             "evidence": ["/sections/tools/data/node", "/sections/policies/data/managed_claude"], "ask_it": None,
             "unlocks": [], "_fn": mcp_rule(name, cfg if isinstance(cfg, dict) else {})})
    routing = load_json(os.path.join(kit, "settings", "model-routing.json")) or {}
    for rw in routing.get("rows") or []:
        for ent in rw.get("chain") or []:
            mdl = ent.get("model")
            if mdl:
                add({"id": "model-%s-%s" % (rw.get("persona") or rw.get("id"), mdl), "group": "models",
                     "feature": "Model %s for %s" % (mdl, rw.get("persona") or rw.get("id")),
                     "evidence": ["/sections/models/data"] + (["/sections/claude/data/version"] if mdl in MIN_CLAUDE_CODE else []),
                     "ask_it": None, "unlocks": [],
                     "_fn": model_rule(mdl, routing.get("provider_ids") or {})})
    pdir = os.path.join(kit, "plugins")
    for plug in sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []:
        sdir = os.path.join(pdir, plug, "skills")
        for sk in sorted(os.listdir(sdir)) if os.path.isdir(sdir) else []:
            if os.path.isdir(os.path.join(sdir, sk)):
                add({"id": "skill-" + sk, "group": "skills", "feature": "Skill: " + sk,
                     "evidence": ["/sections/claude/data/plugins_installed"], "ask_it": None, "unlocks": [],
                     "_fn": plugin_rule(plug)})
    return rows


def evaluate(p, kit=KIT, packages_path=None, features=None, rules=None):
    rules = RULES if rules is None else rules
    out = []
    for r in row_defs(kit, packages_path, features):
        fn = r.get("_fn") or rules.get(r.get("rule"))
        try:
            res = fn(p) if fn else (U, "no rule '%s'" % r.get("rule"))
        except Exception as e:   # noqa: BLE001
            res = (U, "rule failed: %s" % type(e).__name__)
        status, note = res[0], res[1]
        ask_over = res[2] if len(res) > 2 else None
        ask = ask_over if isinstance(ask_over, str) else r.get("ask_it") if (status in (N, B) or ask_over is True) else None
        if status in (N, B) and not ask:
            ask = "Please help with: %s. %s" % (r["feature"], note)
        ev = []
        for q in r.get("evidence") or []:
            ok, v = resolve(p, q)
            ev.append({"pointer": q, "value": brief(v) if ok else None})
        out.append({"id": r["id"], "group": r["group"], "feature": r["feature"], "status": status, "evidence": ev,
                    "ask_it": ask, "note": note, "unlocks": list(r.get("unlocks") or [])})
    return out


def roadmap(rows):
    ids = {r["id"] for r in rows}
    groups = {}
    for r in rows:
        if r["status"] in (N, B) and r["ask_it"]:
            groups.setdefault(r["ask_it"], set()).update([r["id"]] + [u for u in r["unlocks"] if u in ids])
    ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [{"rank": i + 1, "ask": ask, "unlocks": sorted(s)} for i, (ask, s) in enumerate(ranked)]


def ep_ms(p, pred):
    for e in endpoints(p):
        if pred(e) and e["result"] == "ok":
            return e["ms"]
    return None


def specs(p):
    h = D(p, "hardware")
    return {"cpu": h["cpu"], "cores": h["cores"], "ram_gb": h["ram_gb"], "gpu": h["gpu"], "npu": h["npu"], "disks": h["disks"],
            "os": {"build": D(p, "os")["build"], "edition": D(p, "os")["edition"]},
            "power": {"battery": h["battery"], "plan": h["power_plan"]},
            "latency_ms": {"model_api": ep_ms(p, lambda e: e["name"] == "model_api"),
                           "git_host": ep_ms(p, lambda e: e["name"] == "github.com" or e["name"].startswith("git:"))}}


def posture(p):
    ac, sec, cap, th = D(p, "app_control"), D(p, "security"), D(p, "capture"), D(p, "tls")["hosts"]
    states = {ac["wdac"], ac["applocker"]}
    return {"managed_claude": managed(p), "intune": D(p, "management")["mdm_enrolled"], "epm": D(p, "identity")["epm_present"],
            "defender": {"realtime": sec["defender_realtime"], "exclusions": sec["defender_exclusions"]},
            "app_control": "enforced" if "enforced" in states else "audit" if "audit" in states else
            "none" if states <= {"off", "none"} else "unknown",
            "edge": {"automation_allowed": cap["automation_allowed"], "headless_allowed": cap["headless_allowed"],
                     "policy_keys": cap["policy_keys"]},
            "wsl_policy": D(p, "policies")["wsl"], "proxy": D(p, "network")["proxy"],
            "tls_inspection": "unknown" if not th else "yes" if any(x["inspected"] == "yes" for x in th) else
            "no" if all(x["inspected"] == "no" for x in th) else "unknown",
            "dlp": sec["dlp_agent"], "labels": sec["label_client"]}


def build(p, phase, bench=None, quick=False, kit=KIT, packages_path=None, probe_path=None, features=None, rules=None):
    rows = evaluate(p, kit, packages_path, features, rules)
    return {"version": 1, "kit_version": probe.KIT_VERSION, "phase": phase,
            "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_s": p["duration_s"], "quick": quick, "specs": specs(p), "features": rows, "posture": posture(p),
            "devspeed": bench or {"metrics": [], "verdict": None, "because": ["not run"], "fix": [], "peak_mb": None},
            "roadmap": roadmap(rows), "probe": probe_path}


# ── diff ──────────────────────────────────────────────────────────────────────────────────────────────────────
def diff(a, b):
    ra, rb = {r["id"]: r for r in a["features"]}, {r["id"]: r for r in b["features"]}
    counts = lambda d: {s: sum(1 for r in d["features"] if r["status"] == s) for s in STATUSES}   # noqa: E731
    return {"version": 1, "from": a["phase"], "to": b["phase"],
            "changed": [{"id": i, "feature": rb[i]["feature"], "before": ra[i]["status"], "after": rb[i]["status"],
                         "note": rb[i]["note"]} for i in rb if i in ra and ra[i]["status"] != rb[i]["status"]],
            "added": [i for i in rb if i not in ra], "removed": [i for i in ra if i not in rb],
            "counts": {"before": counts(a), "after": counts(b)},
            "devspeed": {"before": a["devspeed"].get("verdict"), "after": b["devspeed"].get("verdict")}}


def diff_md(d):
    L = ["# Capability change: %s to %s" % (d["from"], d["to"]), ""]
    L += ["%s: %d to %d" % (s, d["counts"]["before"][s], d["counts"]["after"][s]) + "  " for s in STATUSES] + [""]
    L += ["## Rows that changed (%d)" % len(d["changed"]), ""] if d["changed"] else ["No row changed status.", ""]
    L += ["- `%s`: %s to %s (%s)" % (c["id"], c["before"], c["after"], c["note"]) for c in d["changed"]]
    L += ["", "Added: " + (", ".join(d["added"]) or "none"), "Removed: " + (", ".join(d["removed"]) or "none"),
          "Dev speed: %s to %s" % (d["devspeed"]["before"], d["devspeed"]["after"])]
    return "\n".join(L) + "\n"


# ── rendering ─────────────────────────────────────────────────────────────────────────────────────────────────
def to_md(c):
    s = c["specs"]
    L = ["# Capability report (%s)" % c["phase"], "", "Generated %s, %ss%s." % (c["generated"], c["duration_s"], ", quick" if c["quick"] else ""), "",
         "## Machine", "", "- CPU: %s, %s cores, %s GB RAM" % (s["cpu"], s["cores"], s["ram_gb"]),
         "- GPU: %s; NPU: %s" % (", ".join(s["gpu"]) or "none seen", ", ".join(s["npu"]) or "none seen"),
         "- OS build %s, edition %s; battery %s, plan %s" % (s["os"]["build"], s["os"]["edition"], s["power"]["battery"], s["power"]["plan"]),
         "- Disks: " + ", ".join("%s %s %s GB free" % (d["mount"], d["type"], d["free_gb"]) for d in s["disks"]),
         "- Latency to the model API: %s ms; to the git host: %s ms" % (s["latency_ms"]["model_api"], s["latency_ms"]["git_host"]), ""]
    cnt = {x: sum(1 for r in c["features"] if r["status"] == x) for x in STATUSES}
    L += ["## Features", "", " | ".join("%s %d" % (k, v) for k, v in cnt.items()), "", "| Feature | Status | Why |", "|---|---|---|"]
    L += ["| %s | %s | %s |" % (r["feature"], r["status"], r["note"].replace("|", "/")) for r in c["features"]]
    L += ["", "## Security posture", ""] + ["- %s: `%s`" % (k, json.dumps(v, default=str)[:200]) for k, v in c["posture"].items()]
    d = c["devspeed"]
    L += ["", "## Dev speed: %s" % d.get("verdict")] + ["", "| Measure | Value |", "|---|---|"]
    L += ["| %s | %s %s |" % (m["name"], m["value"], m["unit"]) for m in d["metrics"]]
    L += [""] + ["- Because: " + x for x in d["because"]] + ["- Fix: " + x for x in d["fix"]]
    L += ["", "## Roadmap: what each IT ask unlocks", ""]
    L += ["%d. %s (unlocks %d: %s)" % (r["rank"], r["ask"], len(r["unlocks"]), ", ".join(r["unlocks"])) for r in c["roadmap"]] or ["Nothing to ask."]
    return "\n".join(L) + "\n"


CSS = """:root{--bg:#fafafa;--fg:#1d2129;--mut:#5b6573;--card:#fff;--line:#d9dde3;--ready:#0b6b3a;--inst:#0b5a8f;--need:#8a5a00;--block:#a3281f;--unk:#5b6573}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e6e9ee;--mut:#9aa4b2;--card:#1c2027;--line:#323944;--ready:#5fd194;--inst:#6cb8f0;--need:#f0c060;--block:#ff8c82;--unk:#9aa4b2}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1000px;margin:0 auto;padding:20px 16px}h1{font-size:1.5rem}h2{font-size:1.15rem;margin-top:2rem}
table{border-collapse:collapse;width:100%;background:var(--card);display:block;overflow-x:auto}th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
.s{font-weight:600;white-space:nowrap}.READY{color:var(--ready)}.INSTALLABLE{color:var(--inst)}.NEEDS-IT{color:var(--need)}.BLOCKED-BY-POLICY{color:var(--block)}.UNKNOWN{color:var(--unk)}
.mut{color:var(--mut)}code{font-size:.85em;word-break:break-all}details{margin:2px 0}"""


def to_html(c):
    e = html.escape
    s, d = c["specs"], c["devspeed"]
    cnt = {x: sum(1 for r in c["features"] if r["status"] == x) for x in STATUSES}
    h = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
         "<title>Capability report</title><style>%s</style></head><body><main>" % CSS,
         "<h1>Capability report (%s)</h1><p class=mut>Generated %s, %ss%s. Read-only: nothing was changed on this machine.</p>"
         % (e(c["phase"]), e(c["generated"]), c["duration_s"], ", quick mode" if c["quick"] else ""),
         "<p>" + " &middot; ".join('<span class="s %s">%s %d</span>' % (k, k, v) for k, v in cnt.items()) + "</p>",
         "<h2>Machine</h2><table><tr><th>CPU</th><td>%s, %s cores, %s GB RAM</td></tr>" % (e(str(s["cpu"])), s["cores"], s["ram_gb"]),
         "<tr><th>GPU / NPU</th><td>%s / %s</td></tr>" % (e(", ".join(s["gpu"]) or "none seen"), e(", ".join(s["npu"]) or "none seen")),
         "<tr><th>OS</th><td>build %s, edition %s</td></tr>" % (e(str(s["os"]["build"])), e(str(s["os"]["edition"]))),
         "<tr><th>Power</th><td>battery %s, plan %s</td></tr>" % (s["power"]["battery"], e(str(s["power"]["plan"]))),
         "<tr><th>Disks</th><td>%s</td></tr>" % e(", ".join("%s %s %s GB free" % (x["mount"], x["type"], x["free_gb"]) for x in s["disks"])),
         "<tr><th>Latency</th><td>model API %s ms, git host %s ms</td></tr></table>" % (s["latency_ms"]["model_api"], s["latency_ms"]["git_host"]),
         "<h2>Features</h2><table><tr><th>Feature</th><th>Status</th><th>Why and evidence</th></tr>"]
    for r in c["features"]:
        ev = "".join("<div><code>%s</code> = <code>%s</code></div>" % (e(x["pointer"]), e(json.dumps(x["value"], default=str))) for x in r["evidence"])
        ask = "<div><b>Ask IT:</b> %s</div>" % e(r["ask_it"]) if r["ask_it"] else ""
        h.append('<tr><td>%s<div class=mut>%s</div></td><td class="s %s">%s</td><td>%s%s<details><summary>evidence</summary>%s</details></td></tr>'
                 % (e(r["feature"]), e(r["id"]), r["status"], r["status"], e(r["note"]), ask, ev))
    h.append("</table><h2>Security posture</h2><table>")
    h += ["<tr><th>%s</th><td><code>%s</code></td></tr>" % (e(k), e(json.dumps(v, default=str)[:300])) for k, v in c["posture"].items()]
    h.append("</table><h2>Dev speed: %s</h2><table><tr><th>Measure</th><th>Value</th></tr>" % e(str(d.get("verdict"))))
    h += ["<tr><td>%s</td><td>%s %s</td></tr>" % (e(m["name"]), m["value"], e(m["unit"])) for m in d["metrics"]]
    h.append("</table>")
    h += ["<p>Because: %s</p>" % e(x) for x in d["because"]] + ["<p>Fix: %s</p>" % e(x) for x in d["fix"]]
    h.append("<h2>Roadmap: what each IT ask unlocks</h2><ol>")
    h += ["<li>%s <span class=mut>(unlocks %d: %s)</span></li>" % (e(r["ask"]), len(r["unlocks"]), e(", ".join(r["unlocks"]))) for r in c["roadmap"]]
    h.append("</ol></main></body></html>")
    return "\n".join(h)


def summary(c, out):
    cnt = {x: sum(1 for r in c["features"] if r["status"] == x) for x in STATUSES}
    L = ["capability report (%s): %d features in %ss" % (c["phase"], len(c["features"]), c["duration_s"]),
         "  " + ", ".join("%s %d" % kv for kv in cnt.items()),
         "  dev speed: %s" % c["devspeed"].get("verdict")]
    L += ["  ask %d: %s (unlocks %d)" % (r["rank"], r["ask"][:90], len(r["unlocks"])) for r in c["roadmap"][:5]]
    L.append("  written to " + out)
    return L[:40]


# ── run ───────────────────────────────────────────────────────────────────────────────────────────────────────
def run_report(phase, out, quick=False, no_bench=False, no_model_call=False, packages=None, git_hosts=(), extras=(),
               kit=KIT, probe_kw=None, bench_fn=None, features=None, rules=None, doctor=False):
    t0 = time.monotonic()
    p = probe.collect(**dict(dict(packages=packages, git_hosts=list(git_hosts), extras=list(extras), network=not quick,
                                  quick=quick, kit=kit, doctor=doctor), **(probe_kw or {})))
    bench = None
    if not quick and not no_bench:
        m, cl = D(p, "models"), D(p, "claude")
        call = not no_model_call and cl["logged_in"] is True
        left = max(30, min(170, int(230 - (time.monotonic() - t0) - 15)))
        bench = (bench_fn or devbench.run_capped)(budget_s=left, mb=1024, network=True, model_call=call,
                                                  model=devbench.pick_model(m["denied"], m["available"]) if call else None)
    probe_path = os.path.join(out, "probe-%s.json" % phase)
    c = build(p, phase, bench, quick, kit, packages, probe_path, features, rules)
    c["duration_s"] = round(time.monotonic() - t0, 1)
    probe.write_atomic(probe_path, json.dumps(p, indent=1))
    probe.write_atomic(os.path.join(out, "capability-%s.json" % phase), json.dumps(c, indent=1))
    probe.write_atomic(os.path.join(out, "capability-%s.md" % phase), to_md(c))
    probe.write_atomic(os.path.join(out, "capability-%s.html" % phase), to_html(c))
    pre = load_json(os.path.join(out, "capability-pre.json")) if phase == "post" else None
    if pre:
        dd = diff(pre, c)
        probe.write_atomic(os.path.join(out, "capability-diff.json"), json.dumps(dd, indent=1))
        probe.write_atomic(os.path.join(out, "capability-diff.md"), diff_md(dd))
    return c


def detach(argv):
    """Re-launch this script in the background (pythonw on Windows) and return at once."""
    exe = sys.executable
    pw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if probe.IS_WIN and os.path.isfile(pw):
        exe = pw
    kw = {"creationflags": 0x00000008 | 0x00000200} if probe.IS_WIN else {"start_new_session": True}   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    pr = subprocess.Popen([exe, os.path.abspath(__file__)] + [a for a in argv if a != "--detach"], stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **kw)
    return pr.pid


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    ap = argparse.ArgumentParser(description="Capability report.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--phase", choices=("pre", "post", "refresh"), required=True)
    r.add_argument("--quick", action="store_true")
    r.add_argument("--no-bench", action="store_true")
    r.add_argument("--no-model-call", action="store_true")
    r.add_argument("--with-doctor", action="store_true", help="also run `claude doctor` (it rewrites the CLI's own config files)")
    r.add_argument("--detach", action="store_true")
    r.add_argument("--out")
    r.add_argument("--packages")
    r.add_argument("--git-hosts", default="")
    r.add_argument("--extra-endpoint", action="append", default=[])
    d = sub.add_parser("diff")
    d.add_argument("a")
    d.add_argument("b")
    a = ap.parse_args(argv)
    if a.cmd == "diff":
        ca, cb = load_json(a.a), load_json(a.b)
        if not ca or not cb:
            ap.error("cannot read both capability files")
        print(diff_md(diff(ca, cb)), end="")
        return 0
    if a.detach:
        print("capability report started in the background (pid %d)" % detach(argv))
        return 0
    out = a.out or probe.default_out()
    c = run_report(a.phase, out, a.quick, a.no_bench, a.no_model_call, a.packages, [h for h in a.git_hosts.split(",") if h],
                   a.extra_endpoint, doctor=a.with_doctor)
    print("\n".join(summary(c, out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
