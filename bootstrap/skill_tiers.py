#!/usr/bin/env python3
"""skill_tiers.py: measure Claude Code's whole skill listing on THIS machine and, when it is too full, choose which of
the user's own skills to list by name only (stdlib; pure functions, nothing is written here).

  measure(ch, kit, cwd, env, managed)   every skill the listing holds, by source, with its size in characters
  plan(info, routed, packs, force)      which non-plugin skills to set to "name-only" (K2)
  row(info)                             (status, detail, public detail) for the doctor and the post-update verify

Custom commands (commands/*.md) are skills too and are counted the same way. Sizes are estimates from the SKILL.md files: a listed skill costs its name plus its description and when_to_use text (the
text is cut at ENTRY_CAP); a "name-only" skill costs its name; a skill with disable-model-invocation, or set to
"off" / "user-invocable-only", costs nothing. ALLOWANCE stands for the bundled skills and the list formatting, which no
SKILL.md of ours measures (an estimate of that share, not a constant of the product).
The limit is 30,000 characters at the default skillListingBudgetFraction (0.01) and scales with that setting;
SLASH_COMMAND_TOOL_CHAR_BUDGET, when set, is the limit itself.
Plugin skills are never changed: Claude Code's skillOverrides does not apply to them. Skill NAMES stay on this machine:
`public` details carry numbers only.
"""
import json
import os
import re
from pathlib import Path

LIMIT = 30000                  # characters at the default fraction
BASE_FRACTION = 0.01
ENTRY_CAP = 1536               # the cap on one entry's description + when_to_use text
TARGET = 0.80                  # tier the user's own skills until the listing is at or under this share of the 30,000 default
                               # (never of a raised limit: skillListingBudgetFraction is a ceiling that may not be honoured)
WARN_AT = 0.85                 # the doctor row warns from here
ALLOWANCE = 6600
NAME_ONLY = "name-only"
HIDING = ("user-invocable-only", "off")     # skillOverrides values that take a skill out of the model's listing
MARKETPLACE = "workbench"
GROUPS = ("kit plugins", "other plugins", "user skills", "org-synced skills", "project skills")


def _json(path):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def front(text):
    """{key: scalar} of a SKILL.md frontmatter: plain, quoted, folded or literal block values."""
    m = re.match(r"---\r?\n(.*?)\r?\n---", text, re.S)
    lines, out = (m.group(1).splitlines() if m else []), {}
    for i, line in enumerate(lines):
        k = re.match(r"([A-Za-z_-]+):(.*)$", line)
        if not k:
            continue
        v = k.group(2).strip()
        more = []
        for nxt in lines[i + 1:]:                 # an indented line continues the value (block scalars and wrapped plain ones)
            if not nxt.startswith((" ", "\t")):
                break
            more.append(nxt.strip())
        if v[:1] in "|>":
            v = " ".join(more)
        elif v[:1] == '"':
            try:
                v = json.loads(v)
            except ValueError:
                v = v.strip('"')
        elif v[:1] == "'" and v[-1:] == "'":
            v = v[1:-1].replace("''", "'")
        else:
            v = " ".join([v, *more]).strip()
        out[k.group(1)] = v
    return out


def _skill(path, group, prefix=""):
    try:
        fm = front(Path(path).read_text(encoding="utf-8-sig", errors="replace"))
    except OSError:
        return None
    folder = Path(path).stem if Path(path).name != "SKILL.md" else Path(path).parent.name     # a command file is its own skill
    name = fm.get("name") or folder
    text = (fm.get("description", "") + (" " + fm["when_to_use"] if fm.get("when_to_use") else "")).strip()
    listed = f"{prefix}{name}"
    return {"key": listed, "name": name, "dir": folder, "group": group, "plugin": bool(prefix), "chars": len(text),
            "hidden": fm.get("disable-model-invocation", "").lower() == "true", "path": str(path)}


def enabled_plugins(ch):
    out = []
    for f in ("settings.json", "settings.local.json"):
        out += [k for k, v in (_json(Path(ch) / f).get("enabledPlugins") or {}).items() if v is True]
    return list(dict.fromkeys(out))


def overrides_in(ch, cwd):
    """The skillOverrides the user's own settings files set (later files win); {name: value}."""
    out = {}
    for f in (Path(ch) / "settings.json", Path(ch) / "settings.local.json", Path(cwd) / ".claude" / "settings.json",
              Path(cwd) / ".claude" / "settings.local.json"):
        o = _json(f).get("skillOverrides")
        if isinstance(o, dict):
            out.update({k: v for k, v in o.items() if isinstance(v, str)})
    return out


def discover(ch, kit, cwd):
    ch, kit, cwd = Path(ch), Path(kit), Path(cwd)
    found = []
    installed = _json(ch / "plugins" / "installed_plugins.json").get("plugins") or {}
    for pid in enabled_plugins(ch):
        name, _, market = pid.partition("@")
        root = None
        for e in installed.get(pid) or []:
            if isinstance(e, dict) and isinstance(e.get("installPath"), str) and Path(e["installPath"]).is_dir():
                root = Path(e["installPath"])
        if root is None and market == MARKETPLACE and (kit / "plugins" / name).is_dir():
            root = kit / "plugins" / name
        if root is not None:
            group = "kit plugins" if market == MARKETPLACE else "other plugins"
            found += [_skill(p, group, name + ":") for p in sorted((root / "skills").glob("*/SKILL.md"))
                      + sorted((root / "commands").glob("*.md"))]
    skills = ch / "skills"
    found += [_skill(p, "user skills") for p in sorted(skills.glob("*/SKILL.md")) + sorted((ch / "commands").rglob("*.md"))
              if p.parent.name != "synced"]
    found += [_skill(p, "org-synced skills") for p in sorted((skills / "synced").glob("*/*/SKILL.md"))
              + sorted((skills / "synced").glob("*/SKILL.md"))]
    if (cwd / ".claude").resolve() != ch.resolve():
        found += [_skill(p, "project skills") for p in sorted((cwd / ".claude" / "skills").glob("*/SKILL.md"))
                  + sorted((cwd / ".claude" / "commands").rglob("*.md"))]
    return [s for s in found if s]


def limit_chars(ch, env, managed=None):
    """(characters, where it comes from). Managed settings win, then local, then user settings; the process env var."""
    envs = [env] + [(_json(Path(ch) / f).get("env") or {}) for f in ("settings.local.json", "settings.json")]
    for e in envs:
        v = str(e.get("SLASH_COMMAND_TOOL_CHAR_BUDGET") or "")
        if v.isdigit() and int(v) > 0:
            return int(v), "SLASH_COMMAND_TOOL_CHAR_BUDGET"
    for d in [managed or {}, _json(Path(ch) / "settings.local.json"), _json(Path(ch) / "settings.json")]:
        f = d.get("skillListingBudgetFraction")
        if isinstance(f, (int, float)) and not isinstance(f, bool) and 0 < f <= 1:
            return round(LIMIT * f / BASE_FRACTION), f"skillListingBudgetFraction {f}"
    return LIMIT, "default (1% of the context window)"


def cost(s, tier):
    """Characters one skill takes in the listing under a tier ("on" when tier is None)."""
    if s["hidden"] or tier in HIDING:
        return 0
    return len(s["key"]) if tier == NAME_ONLY else len(s["key"]) + min(s["chars"], ENTRY_CAP)


def measure(ch, kit, cwd=None, env=None, managed=None, allowance=None):
    cwd = Path(cwd) if cwd else Path.cwd()
    allowance = ALLOWANCE if allowance is None else allowance
    over = overrides_in(ch, cwd)
    skills = discover(ch, kit, cwd)
    for s in skills:
        s["tier"] = None if s["plugin"] else over.get(s["name"])
        s["size"] = cost(s, s["tier"])
    limit, where = limit_chars(ch, os.environ if env is None else env, managed)
    groups = {g: sum(s["size"] for s in skills if s["group"] == g) for g in GROUPS}
    total = sum(groups.values()) + allowance
    return {"skills": skills, "overrides": over, "groups": groups, "allowance": allowance, "total": total,
            "limit": limit, "limit_from": where, "pct": round(100 * total / limit, 1) if limit else 0.0}


def packs(kit):
    """Folder names of the skills the opt-in packs (pm-pack, upstream, optional) install, from their lock files."""
    out = set()
    for f in ("upstream.pm.lock.json", "upstream.lock.json", "upstream.optional.lock.json"):
        for src in _json(Path(kit) / "tools" / "fetch-upstream" / f).get("sources") or []:
            for row in src.get("files") or []:
                if isinstance(row, list) and len(row) > 1 and str(row[1]).endswith("/SKILL.md"):
                    out.add(str(row[1]).split("/")[0])
    return out


def goal(info):
    """The size the tiers aim for: TARGET of the default limit, or of a lower effective limit; a raised limit does not raise it."""
    return TARGET * min(LIMIT, info["limit"])


def routed(kit, names):
    """The names among `names` that the kit's instructions call as a skill: `name`, /name or /plugin:name, never a plain word
    (the rules say "QA" without meaning the skill `qa`)."""
    text = ""
    for p in sorted((Path(kit) / "instructions").rglob("*.md")):
        try:
            text += p.read_text(encoding="utf-8-sig", errors="replace") + "\n"
        except OSError:
            continue
    return {n for n in names if re.search(rf"(?<![\w-])[`/](?:[\w-]+:)?{re.escape(n)}(?![\w-])", text)}


def plan(info, kit, force=False):
    """What to change so the listing falls to TARGET of the limit, touching only the user's own skills (never a plugin's):
    1. a skill the kit routes to stays on;  2. pack skills go name-only;  3. then the others, largest first, until under.
    A value the user set is kept unless force. {"changes": {name: "name-only"}, "kept_on": [...], "user_set": [...],
    "before": n, "after": n, "reached": bool}"""
    mine = [s for s in info["skills"] if not s["plugin"]]
    keep = routed(kit, {s["name"] for s in mine} | {s["dir"] for s in mine})
    pk, aim, total = packs(kit), goal(info), info["total"]
    out = {"changes": {}, "kept_on": sorted({s["name"] for s in mine if s["name"] in keep or s["dir"] in keep}),
           "user_set": [], "before": total, "after": total, "reached": total <= aim, "goal": round(aim)}
    if total <= aim:
        return out

    def take(s):
        nonlocal total
        gain = s["size"] - cost(s, NAME_ONLY)
        if gain <= 0 or s["name"] in out["changes"]:
            return
        if s["tier"] is not None and s["tier"] != NAME_ONLY and not force:
            out["user_set"].append(s["name"])
            return
        out["changes"][s["name"]] = NAME_ONLY
        total -= gain
    free = [s for s in mine if s["name"] not in keep and s["dir"] not in keep]
    for s in free:
        if s["name"] in pk or s["dir"] in pk:
            take(s)
    for s in sorted(free, key=lambda s: -s["size"]):
        if total <= aim:
            break
        take(s)
    out.update(after=total, reached=total <= aim)
    return out


def row(info):
    """(status, detail, public detail) for the doctor's `skill listing` row. WARN from WARN_AT of the limit."""
    n = len(info["skills"])
    share = [f"{g} {info['groups'][g]:,}" for g in GROUPS if info["groups"][g]] + [f"bundled-skill allowance {info['allowance']:,}, an estimate"]
    pub = f"about {info['total']:,} of {info['limit']:,} characters ({info['pct']}%) from {n} skill(s): " + "; ".join(share)
    top = sorted(info["skills"], key=lambda s: -s["size"])[:5]
    status = "WARN" if info["total"] >= WARN_AT * info["limit"] else "OK"
    tail = ""
    if status == "WARN":
        tail = ("; Claude Code cuts descriptions past the limit. Fix: py -3 <KIT>/bootstrap/setup.py skills (lists the user's own "
                "skills by name only; plugin skills cannot be tiered)")
    return (status, pub + ("; top: " + ", ".join(f"{s['key']} {s['size']:,}" for s in top) if top else "") + tail, pub + tail)
