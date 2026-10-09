"""Doc and knowledge-pack checkers for the kit (interface I21), with their tests.

  py -3 tools/test_docs.py --deny PATH...    shape and privacy rules P1-P5 over the doc scope (exit 1 on a finding)
  py -3 tools/test_docs.py --paths MD...     backticked kit paths that do not exist (G8)
  py -3 tools/test_docs.py --budget          always-loaded bytes (G9), the skill description + when_to_use total, each
                                             when_to_use line (at most WHEN_MAX characters) and the estimated whole listing
  py -3 tools/test_docs.py --render-routing  rewrite docs/model-routing.md from settings/model-*.json
Tests: python -m unittest discover -s tools -p "test_docs.py"   (WB_REQUIRE_ALL=1 makes a missing dependency fail)

Deny rules: P1 a line starting `Seen:`, P3 a hex run of 7 or more characters, P4 an ISO date,
P5 a number of 2 or more digits (knowledge files only: kb-template/**, settings/model-*.json, docs/model-routing.md).
Structural ids are not numbers: the number of a numbered heading, a detector's "card" value and an `NN-index` file
name. Scope: kb-template/, docs/, settings/, every SKILL.md and references/*.md under plugins/. A finding is excused
only through tools/publish-allow.json. Private tool names are the private denylist's job (tools/scrub_scan.py).
"""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: no test below skips, a missing file fails

import argparse  # noqa: E402
import fnmatch  # noqa: E402
import glob  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path, PurePosixPath  # noqa: E402

KIT = Path(__file__).resolve().parent.parent
ALLOW_FILE = "tools/publish-allow.json"
ALWAYS_LOADED_LIMIT = 36000
ALWAYS_LOADED_MARGIN = 500   # the real set stays this far under the limit, so the next rule costs a demotion
SKILL_DESC_LIMIT = 11000   # every kit skill's description plus its when_to_use, together (K3; was 15,511 in v0.3.1)
WHEN_MAX = 90              # one when_to_use line: it is appended to the description in the skill listing
# The whole skill listing (what Claude Code puts in front of the model each turn), estimated. The kit controls only its own part.
LISTING_BUDGET = 30000     # characters: Claude Code's skill-listing budget at the default listing fraction
KIT_SHARE_MAX = 0.4        # the kit may take at most this share; the rest is other plugins, bundled and organisation skills
                           # (40, not 50: the v0.3.1 kit's share was 49 percent and would not have tripped 50)
LISTING_ENTRY = 4          # "- " and ": " around each entry
# Allowances, not measurements: room for bundled Claude Code skills plus organisation-synced skills.
BUNDLED_ORG_ALLOWANCE = 12400
# Opt-in text the kit puts next to its own: the opt-in skill pack and the standalone skills its hints
# name, such as humanizer and playwright-cli (about 417).
OPTIN_PACKS = 2679
# Listing text of the upstream plugins the kit enables (settings/upstream-plugins*.fragment.json), rounded up; an enabled plugin
# that is not named here counts UPSTREAM_DEFAULT. Refresh when an upstream plugin changes its skills.
UPSTREAM_CHARS = {"frontend-design": 250, "adamsreview": 1100}
UPSTREAM_DEFAULT = 600
MIN_CARDS = 40

# ---- P1-P5: shape and privacy rules -----------------------------------------------------------------------------
DENY = {
    "P1": re.compile(r"^[\s>*-]*Seen:", re.I),
    "P3": re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{7,}(?![0-9A-Za-z])"),
    "P4": re.compile(r"(?<![0-9])20\d\d-\d\d-\d\d(?![0-9])"),
    "P5": re.compile(r"(?<![A-Za-z_\d])\d{2,}"),
}
STRUCTURAL_ID = re.compile(r'^\s*#{1,6}\s+\d+\.|"card":\s*\d+|\b\d\d-index\b')
TEXT_EXT = {".md", ".json", ".txt", ".yaml", ".yml", ".toml", ".csv"}
KNOWLEDGE = ("kb-template/*", "settings/model-*.json", "docs/model-routing.md")


def in_scope(rel):
    p = PurePosixPath(rel)
    if rel.startswith(("kb-template/", "docs/", "settings/")):
        return p.suffix.lower() in TEXT_EXT
    if rel.startswith("plugins/"):
        return p.name == "SKILL.md" or (p.parent.name == "references" and p.suffix.lower() == ".md")
    return False


def _scoped_files(paths, root):
    """[(rel posix path, Path)] of the in-scope files under paths. A missing path raises: it must never pass."""
    root = Path(root).resolve()
    out = []
    for p in map(Path, paths):
        p = (p if p.is_absolute() else Path.cwd() / p)
        if not p.exists():
            raise FileNotFoundError(f"no such path: {p}")
        for f in ([p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file())):
            try:
                rel = f.resolve().relative_to(root).as_posix()
            except ValueError:                  # a link (e.g. a node_modules junction) that resolves outside the kit
                continue
            if any(part.startswith(".") or part in ("__pycache__", "node_modules") for part in rel.split("/")):
                continue
            if in_scope(rel):
                out.append((rel, f))
    return out


def _load_allow(root):
    f = Path(root) / ALLOW_FILE
    if not f.is_file():
        return []
    entries = json.loads(f.read_text(encoding="utf-8")).get("allow", [])
    for e in entries:
        if not e.get("glob") or not e.get("reason"):
            raise ValueError(f"{ALLOW_FILE}: every entry needs a glob and a reason")
    return entries


def deny_scan(paths, root=KIT):
    """[(file, line, rule)] for P1-P5 over the in-scope files under paths (file = path relative to the kit root)."""
    root = Path(root)
    allow = _load_allow(root)
    out = []
    for rel, f in _scoped_files(paths, root):
        rules = ["P1", "P3", "P4"] + (["P5"] if any(fnmatch.fnmatch(rel, g) for g in KNOWLEDGE) else [])
        hit = [e for e in allow if fnmatch.fnmatch(rel, e["glob"])]
        skip_rules = {r for e in hit for r in e.get("rules", [])}
        ok_numbers = {n for e in hit for n in e.get("numbers", [])}
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for r in rules:
                if r in skip_rules:
                    continue
                text = STRUCTURAL_ID.sub(lambda m: " " * len(m.group(0)), line) if r == "P5" else line
                if any(not (r == "P5" and m.group(0) in ok_numbers) for m in DENY[r].finditer(text)):
                    out.append((rel, n, r))
    return out


# ---- G8: backticked kit paths exist -----------------------------------------------------------------------------
# The initial runtime paths of bootstrap/layout.json (interface I16), used until that file exists.
LAYOUT_FALLBACK = [
    "<WB>/state/", "<WB>/config.json", "<WB>/profiles.json", "<WB>/venv/", "<WB>/bin/", "<WB>/knowledge/captured/",
    "<WB>/capture/app/", "<WB>/capture/profile/", "<WB>/capture/scope.json", "<WB>/capture/runs/",
    "<LAD>/doc-index/knowledge/", "<LAD>/doc-index/models/", "<LAD>/wb-review/", "<HOME>/.claude-profiles/",
    "<DATA>/", "<DATA>/captured/", "<DATA>/backup/", "<SRC>/", "<KB>/inbox/",
]
_FENCE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.S | re.M)
_SPAN = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")


def layout_paths(kit_root=KIT):
    f = Path(kit_root) / "bootstrap" / "layout.json"
    if f.is_file():
        return [e["path"] for e in json.loads(f.read_text(encoding="utf-8")).get("paths", [])]
    return LAYOUT_FALLBACK


def _exists(root, rel):
    rel = rel.rstrip("/")
    return bool(glob.glob(str(root / rel))) if "*" in rel else (root / rel).exists()


def check_paths(md_file, kit_root=KIT, layout=None):
    """Backticked paths in md_file that do not exist. Only inline code spans are read (fenced blocks are skipped).
    A kit path starts with one of the kit's top-level names or <KIT>/; a runtime path (<WB>/, <LAD>/, <HOME>/,
    <DATA>/, <KB>/, <SRC>/) counts as existing when it starts with a layout.json entry; <CH>/ paths belong to
    Claude Code and are not checked."""
    kit_root = Path(kit_root)
    layout = layout_paths(kit_root) if layout is None else layout
    tops = {p.name for p in kit_root.iterdir()}
    text = _FENCE.sub("", Path(md_file).read_text(encoding="utf-8"))
    missing = []
    for raw in dict.fromkeys(m.group(1).strip() for m in _SPAN.finditer(text)):
        s = re.sub(r"(#[\w-]+|:\d+(-\d+)?)$", "", raw)
        if " " in s or "://" in s or s[:1] in "-~%$":
            continue
        m = re.match(r"<([A-Z_]+)>/", s)
        if m:
            tok = m.group(1)
            ok = (_exists(kit_root, s[len(m.group(0)):]) if tok == "KIT" else tok == "CH" or
                  any((s.rstrip("/") + "/").startswith(e.rstrip("/") + "/") for e in layout))
        elif "/" in s and s.split("/", 1)[0] in tops:
            ok = _exists(kit_root, s)
        else:
            continue
        if not ok:
            missing.append(raw)
    return missing


# ---- G9 and the skill-description budget -------------------------------------------------------------------------
def lf_bytes(path):
    return len(Path(path).read_bytes().replace(b"\r\n", b"\n"))


def always_loaded(kit_root=KIT):
    """instructions/CLAUDE.md plus everything it imports with an @ line (the USER.md import is templates/USER.md)."""
    kit_root, order = Path(kit_root), []

    def walk(f):
        if f in order:
            return
        order.append(f)
        for m in re.finditer(r"^@(\S+)[ \t]*$", f.read_text(encoding="utf-8"), re.M):
            t = (f.parent / m.group(1)).resolve()
            walk((kit_root / "templates" / "USER.md").resolve() if not t.exists() and t.name == "USER.md" else t)
    walk((kit_root / "instructions" / "CLAUDE.md").resolve())
    return order


def check_budget(sizes, limit=ALWAYS_LOADED_LIMIT):
    total = sum(sizes.values())
    return [f"the always-loaded set is {total} bytes; the limit is {limit}"] if total > limit else []


def front_field(text, key):
    """One scalar from a SKILL.md frontmatter: plain, quoted, or a folded/literal block. "" when absent."""
    m = re.match(r"---\r?\n(.*?)\r?\n---", text, re.S)
    lines = m.group(1).splitlines() if m else []
    for i, line in enumerate(lines):
        if line.startswith(key + ":"):
            v = line[len(key) + 1:].strip()
            if v[:1] in "|>":
                block = []
                for nxt in lines[i + 1:]:
                    if not nxt.startswith((" ", "\t")):
                        break
                    block.append(nxt.strip())
                return " ".join(block)
            if v[:1] == '"':
                try:
                    return json.loads(v)
                except ValueError:
                    return v.strip('"')
            return v[1:-1].replace("''", "'") if v[:1] == "'" and v[-1:] == "'" else v
    return ""


def front_description(text):
    return front_field(text, "description")


def _skill_files(kit_root):
    return sorted(Path(kit_root).glob("plugins/*/skills/*/SKILL.md"))


def skill_descriptions(kit_root=KIT):
    return {p.relative_to(kit_root).as_posix(): front_description(p.read_text(encoding="utf-8"))
            for p in _skill_files(kit_root)}


def skill_when(kit_root=KIT):
    """{SKILL.md path: when_to_use} for the skills that carry one."""
    out = {p.relative_to(kit_root).as_posix(): front_field(p.read_text(encoding="utf-8"), "when_to_use")
           for p in _skill_files(kit_root)}
    return {k: v for k, v in out.items() if v}


def check_descriptions(descs, limit=SKILL_DESC_LIMIT, when=None, when_max=WHEN_MAX):
    """Errors: any when_to_use over when_max characters, and descriptions + when_to_use over limit in total."""
    when = when or {}
    errs = [f"{k}: when_to_use is {len(v)} characters; the limit is {when_max}" for k, v in sorted(when.items())
            if len(v) > when_max]
    total = sum(len(v) for v in descs.values()) + sum(len(v) for v in when.values())
    if total > limit:
        errs.append(f"skill descriptions + when_to_use total {total} characters; the limit is {limit}")
    return errs


def skill_entries(kit_root=KIT):
    """[(plugin:skill, description, when_to_use, user_only)] for every kit skill. user_only = disable-model-invocation: true,
    which keeps the description out of the model's context (Claude Code skills reference, 'Control who invokes a skill')."""
    out = []
    for p in _skill_files(kit_root):
        text = p.read_text(encoding="utf-8")
        out.append((f"{p.parents[2].name}:{p.parent.name}", front_description(text), front_field(text, "when_to_use"),
                    front_field(text, "disable-model-invocation").lower() == "true"))
    return out


def listing_estimate(kit_root=KIT):
    """Estimated characters in the skill listing: the kit's listed skills (name + description + when_to_use), the names of its
    user-only skills (counted as a margin), the enabled upstream plugins, and a stated allowance for bundled and
    organisation skills. {"kit", "user_only", "upstream", "plugins", "optin", "allowance", "total", "listed", "hidden"}."""
    listed = hidden = kit = names = 0
    for name, desc, when, user_only in skill_entries(kit_root):
        if user_only:
            hidden += 1
            names += len(name) + LISTING_ENTRY
        else:
            listed += 1
            kit += len(name) + LISTING_ENTRY + len(desc) + (len(when) + 1 if when else 0)
    plugins = set()
    for f in sorted(Path(kit_root).glob("settings/upstream-plugins*.fragment.json")):
        plugins |= {k.split("@")[0] for k, v in json.loads(f.read_text(encoding="utf-8")).get("enabledPlugins", {}).items() if v is True}
    upstream = sum(UPSTREAM_CHARS.get(k, UPSTREAM_DEFAULT) for k in plugins)
    return {"kit": kit + names, "user_only": names, "upstream": upstream, "plugins": len(plugins), "optin": OPTIN_PACKS,
            "allowance": BUNDLED_ORG_ALLOWANCE, "total": kit + names + upstream + OPTIN_PACKS + BUNDLED_ORG_ALLOWANCE,
            "listed": listed, "hidden": hidden}


def check_listing(est, budget=LISTING_BUDGET, share=KIT_SHARE_MAX):
    """An error when the kit's own part of the estimated listing is over its share of the budget."""
    return [f"the kit's part of the skill listing is about {est['kit']} characters; its share of {budget} is {int(budget * share)}"] \
        if est["kit"] > budget * share else []


def listing_line(est, budget=LISTING_BUDGET):
    return (f"estimated listing: about {est['total']} of {budget} characters = kit {est['kit']} ({est['listed']} listed skills, "
            f"{est['hidden']} user-only names) + {est['plugins']} upstream plugins {est['upstream']} + opt-in packs {est['optin']} "
            f"+ bundled and organisation allowance {est['allowance']}; the kit's share is {round(100 * est['kit'] / budget)} percent "
            f"(limit {round(100 * KIT_SHARE_MAX)})")


# ---- G13: routing and evidence data -----------------------------------------------------------------------------
KINDS = {"vendor", "independent", "kit-bench", "internal-run"}
TIERS = {"R0", "R1", "R2"}
DIRECTIONS = {"better", "worse", "same", None}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
MODEL_ID = re.compile(r"claude-[a-z]+-\d+(?:-\d+)*")


def check_routing(routing, evidence):
    errs, ev = [], {}
    for r in evidence.get("rows", []):
        i = r.get("id")
        if not i or i in ev:
            errs.append(f"evidence id missing or repeated: {i!r}")
            continue
        ev[i] = r
        date, internal = str(r.get("date", "")), r.get("kind") == "internal-run"
        if r.get("kind") not in KINDS:
            errs.append(f"{i}: kind {r.get('kind')!r}")
        if not str(r.get("source", "")).strip():
            errs.append(f"{i}: no source")
        if not str(r.get("claim", "")).strip():
            errs.append(f"{i}: no claim")
        if r.get("tier") not in TIERS:
            errs.append(f"{i}: tier {r.get('tier')!r}")
        if r.get("direction") not in DIRECTIONS:
            errs.append(f"{i}: direction {r.get('direction')!r}")
        if not isinstance(r.get("n"), (int, type(None))) or isinstance(r.get("n"), bool):
            errs.append(f"{i}: n must be an integer or null")
        if internal:
            if r.get("value") is not None:
                errs.append(f"{i}: an internal-run row carries value null")
            if not re.fullmatch(r"20\d\d-\d\d", date):
                errs.append(f"{i}: an internal-run row dates to the month (YYYY-MM)")
            if re.search(r"[\d$%]|\b(?:half|thirds?|quarters?|tenths?|fraction|percent|twice|double|triple)\b",
                         str(r.get("claim", "")), re.I):
                errs.append(f"{i}: an internal-run claim carries no digits, costs, scores or sizes (direction only)")
        elif not re.fullmatch(r"20\d\d-\d\d-\d\d", date):
            errs.append(f"{i}: date must be YYYY-MM-DD")
    known_models, seen = set(routing.get("provider_ids", {})), set()
    for row in routing.get("rows", []):
        rid = row.get("id")
        if not rid or rid in seen:
            errs.append(f"routing id missing or repeated: {rid!r}")
        seen.add(rid)
        if not row.get("evidence"):
            errs.append(f"{rid}: cites no evidence")
        errs += [f"{rid}: unknown evidence id {e!r}" for e in row.get("evidence", []) if e not in ev]
        if not row.get("chain"):
            errs.append(f"{rid}: empty chain")
        for step in row.get("chain", []):
            if step.get("model") not in known_models:
                errs.append(f"{rid}: model {step.get('model')!r} has no provider_ids entry")
            if step.get("effort") not in EFFORTS:
                errs.append(f"{rid}: effort {step.get('effort')!r}")
        text = " ".join([row.get("task_shape", ""), row.get("persona", "")] + list(row.get("never", [])))
        if re.search(r"\d", MODEL_ID.sub("", text)):
            errs.append(f"{rid}: a digit outside ids and model names")
    return errs


# ---- G15: bug cards and detectors ---------------------------------------------------------------------------------
FIELDS = ("Symptom", "Root cause", "Fix", "Verifying test", "Spot it fast")
UNRELATED = [
    "ValueError: invalid literal for int() with base 10: 'abc'",
    "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
    "SyntaxError: invalid syntax",
    "AssertionError: expected 3 but got 4",
    "ZeroDivisionError: division by zero",
    "error TS2304: Cannot find name 'widget'.",
    "FAILED tests/test_sample.py::test_total - assert 1 == 2",
    "npm ERR! missing script: build",
    "fatal: pathspec 'docs/x.md' did not match any files",
    "RuntimeError: dictionary changed size during iteration",
]
SEED_CLASSES = {  # title pattern of each enterprise-laptop seed card: it must exist and have a detector
    "proxy CA per runtime": r"(?i)certificate authority|root CA|trust store",
    "path length": r"(?i)path length|long path",
    "line endings": r"(?i)line ending",
    "OneDrive file lock": r"(?i)onedrive",
    "Git Bash vs PowerShell quoting": r"(?i)powershell.*quot|quot.*powershell",
    "WSL DNS under VPN": r"(?i)wsl.*dns|dns.*vpn",
    "unpinned npx/uvx": r"(?i)unpinned",
}


def parse_cards(md):
    parts = re.split(r"(?m)^### (\d+)\. (.+)$", md)
    return [{"n": int(parts[i]), "title": parts[i + 1].strip(), "body": parts[i + 2]} for i in range(1, len(parts), 3)]


def _field(body, name):
    nxt = "|".join(re.escape(f) for f in FIELDS)
    m = re.search(rf"\*\*{re.escape(name)}:?\*\*:?\s*(.*?)(?=\n\s*[-*]?\s*\*\*(?:{nxt}):?\*\*|\Z)", body, re.S)
    return m.group(1).strip() if m else ""


def check_cards(md, detectors, minimum=MIN_CARDS, unrelated=UNRELATED):
    errs, cards = [], parse_cards(md)
    if len(cards) < minimum:
        errs.append(f"{len(cards)} cards; need at least {minimum}")
    nums = [c["n"] for c in cards]
    if len(set(nums)) != len(nums):
        errs.append("a card number is repeated")
    for c in cards:
        errs += [f"card {c['n']}: no {f}" for f in FIELDS if len(_field(c["body"], f)) < 15]
    if detectors.get("version") != 1:
        errs.append("detectors: version must be 1")
    for d in detectors.get("detectors", []):
        tag = f"detector for card {d.get('card')}"
        if d.get("card") not in nums:
            errs.append(f"{tag}: no such card")
        if not str(d.get("title", "")).strip():
            errs.append(f"{tag}: no title")
        else:
            heading = next((c["title"] for c in cards if c["n"] == d.get("card")), None)
            if heading is not None and str(d["title"]).strip() != heading:
                errs.append(f"{tag}: title differs from the heading of card {d.get('card')} (a swapped card number?)")
        if not str(d.get("repro", "")).strip():
            errs.append(f"{tag}: no repro")
            continue
        try:
            rx = re.compile(d.get("pattern") or "", re.I)
        except re.error as e:
            errs.append(f"{tag}: pattern does not compile ({e})")
            continue
        if not d.get("pattern"):
            errs.append(f"{tag}: empty pattern")
        elif not rx.search(d["repro"][:4096]):
            errs.append(f"{tag}: pattern does not match its repro")
        errs += [f"{tag}: also matches an unrelated error ({u[:30]!r})" for u in unrelated if rx.search(u[:4096])]
    return errs


def check_seed_cards(md, detectors):
    cards, covered = parse_cards(md), {d.get("card") for d in detectors.get("detectors", [])}
    return [f"seed class {name}: no card with a detector" for name, pat in SEED_CLASSES.items()
            if not any(re.search(pat, c["title"]) and c["n"] in covered for c in cards)]


# ---- docs/model-routing.md, rendered from the two JSON files -------------------------------------------------------
def render_routing(routing, evidence):
    ev = {r["id"]: r for r in evidence["rows"]}
    L = ["# Model routing", "",
         "<!-- Generated by `py -3 tools/test_docs.py --render-routing` from `settings/model-routing.json` and "
         "`settings/model-evidence.json`. Edit the JSON, never this page. -->", "",
         "Which model, at which effort, for which kind of work, and the evidence behind each choice. Setup reads "
         "`settings/model-routing.json`, drops every model your organisation does not allow and keeps the first "
         "allowed entry of each row's preference order; SessionStart shows the first five rows, which are the most "
         "common task shapes (the table is in that order). Spawn the persona named in the row (see `docs/HOW-WE-WORK.md`).", "",
         "How to read the evidence: `vendor` = published by the model maker; `independent` = measured by a third "
         "party; `kit-bench` = a re-run with this kit's neutral task packs; `internal-run` = a small run by the kit's "
         "authors, shown by direction and month only; internal rows never rank a routing pick. Tier R0 = one party measured it, R1 = one independent "
         "replication, R2 = two or more. A row with only R0 evidence is a starting point: run your own task pack "
         "before relying on it. Dates, exact values and sample sizes are in `settings/model-evidence.json`.", "",
         "## Routing table", "",
         "| Row | Task shape | Persona | Preference order | Never | Evidence |", "|---|---|---|---|---|---|"]
    for r in routing["rows"]:
        chain = " > ".join(f"{s['model']} ({s['effort']})" for s in r["chain"])
        L.append(f"| {r['id']} | {r['task_shape']} | {r['persona']} | {chain} | {'<br>'.join(r.get('never', [])) or '-'} | "
                 f"{', '.join(r['evidence'])} |")
    L += ["", "## Evidence", "", "| Id | Kind | Tier | Source | Finding |", "|---|---|---|---|---|"]
    for r in evidence["rows"]:
        L.append(f"| {r['id']} | {r['kind']} | {r['tier']} | {r['source']} | {r['claim']} |")
    L += ["", "## Model ids per provider", "", "| Model | Anthropic API | Bedrock | Vertex | Foundry |", "|---|---|---|---|---|"]
    for m, p in routing["provider_ids"].items():
        L.append(f"| {m} | {p['anthropic']} | {p['bedrock']} | {p['vertex']} | {p['foundry']} |")
    L += ["", "Unpinned aliases such as `opus`, `sonnet` and `haiku` resolve to older generations on some providers; "
          "pin the full ids above in settings and in persona frontmatter.", ""]
    return "\n".join(L)


def _load(rel, root=KIT):
    return json.loads((Path(root) / rel).read_text(encoding="utf-8"))


# ---- CLI -----------------------------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Doc and knowledge-pack checks (see the module docstring).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--deny", nargs="+", metavar="PATH")
    g.add_argument("--paths", nargs="+", metavar="MD")
    g.add_argument("--budget", action="store_true")
    g.add_argument("--render-routing", action="store_true")
    ap.add_argument("--root", default=str(KIT))
    a = ap.parse_args(argv)
    root = Path(a.root)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    if a.deny:
        try:
            files = _scoped_files(a.deny, root)
            hits = deny_scan(a.deny, root)
        except (OSError, ValueError) as e:
            print(f"error: {e}")
            return 2
        for rel, n, rule in hits:
            print(f"{rel}:{n}  {rule}")
        print(f"scanned {len(files)} in-scope files: {len(hits)} finding(s)")
        if not files:
            print("FAIL: no in-scope file was scanned (kb-template/, docs/, settings/, SKILL.md, references/*.md)")
        return 1 if hits or not files else 0
    if a.paths:
        bad = 0
        for md in a.paths:
            for p in check_paths(md, root):
                print(f"{md}: missing {p}")
                bad += 1
        print(f"{bad} missing path(s)")
        return 1 if bad else 0
    if a.budget:
        sizes = {p.relative_to(root.resolve()).as_posix(): lf_bytes(p) for p in always_loaded(root)}
        descs, when = skill_descriptions(root), skill_when(root)
        est = listing_estimate(root)
        errs = check_budget(sizes) + check_descriptions(descs, when=when) + check_listing(est)
        print(f"always-loaded: {sum(sizes.values())} bytes in {len(sizes)} files (limit {ALWAYS_LOADED_LIMIT})")
        print(f"skill descriptions + when_to_use: {sum(map(len, descs.values())) + sum(map(len, when.values()))} characters "
              f"in {len(descs)} skills, {len(when)} with when_to_use (limit {SKILL_DESC_LIMIT}, each line {WHEN_MAX})")
        print(listing_line(est))
        print("\n".join(errs))
        return 1 if errs else 0
    out = root / "docs" / "model-routing.md"
    out.write_text(render_routing(_load("settings/model-routing.json", root), _load("settings/model-evidence.json", root)),
                   encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


# ---- tests ---------------------------------------------------------------------------------------------------------
KB_DOCS = ["docs/HOW-WE-WORK.md", "docs/AUTHORING.md", "docs/admin-asks.md", "docs/headless-and-scheduling.md",
           "docs/model-routing.md", "kb-template/README.md", "docs/security-overview.md", "docs/known-limits.md",
           "docs/troubleshooting.md", "docs/rules-card.md", "docs/runbooks.md", "docs/token-diet.md", "README.md",
           "IMPORT.md", "plugins/workbench-core/README.md"]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-docs-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def put(self, rel, text):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
        return p


class DenyScan(Fixture):
    def rules(self, rel, text, allow=None):
        self.put(rel, text)
        if allow:
            self.put(ALLOW_FILE, json.dumps({"version": 1, "allow": allow}))
        return sorted({r for _, _, r in deny_scan([self.tmp / rel], self.tmp)})

    def test_each_rule_fires_on_a_bad_fixture(self):
        self.assertEqual(self.rules("kb-template/a.md", "- " + "Seen" + ": three notes\n"), ["P1"])
        self.assertEqual(self.rules("docs/b.md", "commit " + "deadbeef" + "1 fixed it\n"), ["P3"])
        self.assertEqual(self.rules("docs/c.md", "on 20" + "26-01-02 it broke\n"), ["P4"])
        self.assertEqual(self.rules("kb-template/n.md", "waited 20" + "0 ms\n"), ["P5"])

    def test_numbers_only_matter_in_knowledge_files_and_clean_text_passes(self):
        self.assertEqual(self.rules("docs/howto.md", "limit is 36" + "000 bytes\n"), [])
        self.assertEqual(self.rules("kb-template/ok.md", "Opus 5.5, sha256, cp1252, E14, step 3.\n"), [])
        self.assertEqual(self.rules("settings/model-routing.json", '{"a": "claude-opus-5-5 and I10"}\n'), [])

    def test_scope_and_missing_paths(self):
        self.assertEqual(self.rules("tools/x.md", "- " + "Seen" + ": here\n"), [])           # out of scope
        self.assertEqual(self.rules("plugins/p/skills/s/SKILL.md", "on 20" + "26-01-02\n"), ["P4"])
        self.assertEqual(self.rules("plugins/p/skills/s/scripts/t.md", "on 20" + "26-01-02\n"), [])
        with self.assertRaises(FileNotFoundError):
            deny_scan([self.tmp / "docs" / "no-such-file.md"], self.tmp)

    def test_allowance_is_file_level_and_rule_level(self):
        allow = [{"glob": "settings/model-evidence.json", "rules": ["P4", "P5"], "reason": "test"}]
        text = '{"date": "20' + '26-01-02", "v": 99}\n'
        self.assertEqual(self.rules("settings/model-evidence.json", text, allow), [])
        self.assertEqual(self.rules("settings/model-other.json", text, allow), ["P4", "P5"])
        self.assertEqual(self.rules("settings/model-evidence.json", "id deadbeef" + "1\n", allow), ["P3"])
        self.put(ALLOW_FILE, json.dumps({"version": 1, "allow": [{"glob": "docs/*.md", "rules": ["P4"]}]}))
        with self.assertRaises(ValueError):
            deny_scan([self.tmp / "docs"], self.tmp)

    def test_the_real_knowledge_and_doc_trees_are_clean(self):
        self.assertEqual(deny_scan([KIT / "kb-template", KIT / "docs", KIT / "settings"]), [])
        self.assertEqual(deny_scan([KIT / "plugins"]), [])

    def test_publish_allow_allows_only_the_evidence_file(self):
        allow = _load_allow(KIT)
        self.assertEqual([e["glob"] for e in allow], ["settings/model-evidence.json"])
        self.assertEqual(allow[0]["rules"], ["P4", "P5"])
        self.assertEqual(allow[0]["reason"], "every row cites a source; the G13 test enforces it")
        self.assertNotIn("numbers", allow[0])

    def test_cli_exit_codes(self):
        self.put("docs/a.md", "clean\n")
        self.assertEqual(main(["--deny", str(self.tmp / "docs"), "--root", str(self.tmp)]), 0)
        self.put("docs/b.md", "on 20" + "26-01-02\n")
        self.assertEqual(main(["--deny", str(self.tmp / "docs"), "--root", str(self.tmp)]), 1)
        self.assertEqual(main(["--deny", str(self.tmp / "tools"), "--root", str(self.tmp)]), 2)
        self.put("tools/t.md", "x\n")
        self.assertEqual(main(["--deny", str(self.tmp / "tools"), "--root", str(self.tmp)]), 1, "nothing in scope")


class PathCheck(Fixture):
    def test_missing_existing_fenced_and_runtime_paths(self):
        self.put("docs/real.md", "x")
        self.put("plugins/p/real.txt", "x")
        self.put("bootstrap/layout.json", json.dumps({"version": 1, "paths": [{"path": "<WB>/state/"}]}))
        md = self.put("docs/g.md", "`docs/real.md` `docs/gone.md` `<KIT>/docs/real.md` `<KIT>/docs/gone.md` "
                      "`<WB>/state/log.txt` `<WB>/nowhere/` `<CH>/rules/` `docs/*.md` `plugins/*/gone` `a b/c` "
                      "`docs/real.md#top` `x.py` `https://example.com/docs/x`\n```\n`docs/fenced-gone.md`\n```\n")
        self.assertEqual(check_paths(md, self.tmp),
                         ["docs/gone.md", "<KIT>/docs/gone.md", "<WB>/nowhere/", "plugins/*/gone"])

    def test_layout_fallback_without_layout_json(self):
        self.put("docs/real.md", "x")
        md = self.put("docs/g.md", "`<WB>/config.json` `<DATA>/captured/x/` `<WB>/other/`\n")
        self.assertEqual(check_paths(md, self.tmp), ["<WB>/other/"])

    def test_the_real_docs_name_only_existing_paths(self):
        for rel in KB_DOCS:
            self.assertEqual(check_paths(KIT / rel, KIT), [], rel)


class Budget(Fixture):
    def test_limit_is_inclusive_and_one_byte_over_fails(self):
        self.assertEqual(check_budget({"a": 20000, "b": 16000}), [])
        self.assertEqual(len(check_budget({"a": 20000, "b": 16001})), 1)

    def test_always_loaded_follows_imports_and_maps_user_md(self):
        at = "@"
        self.put("instructions/CLAUDE.md", "\n".join(["core", "## Imports", at + "rules/a.md", at + "working-style.md",
                                                       at + "../USER.md", ""]))
        self.put("instructions/rules/a.md", "\n".join(["a", at + "b.md", ""]))
        self.put("instructions/rules/b.md", "b\n")
        self.put("instructions/working-style.md", "w\n")
        self.put("templates/USER.md", "u\r\nu\r\n")
        names = [p.relative_to(self.tmp.resolve()).as_posix() for p in always_loaded(self.tmp)]
        self.assertEqual(names, ["instructions/CLAUDE.md", "instructions/rules/a.md", "instructions/rules/b.md",
                                 "instructions/working-style.md", "templates/USER.md"])
        self.assertEqual(lf_bytes(self.tmp / "templates" / "USER.md"), 4, "CRLF counts as LF")

    def test_the_real_always_loaded_set_is_within_budget_with_a_margin(self):
        sizes = {p.relative_to(KIT.resolve()).as_posix(): lf_bytes(p) for p in always_loaded(KIT)}
        total = sum(sizes.values())
        print(f"\nalways-loaded: {total} bytes in {len(sizes)} files (limit {ALWAYS_LOADED_LIMIT}, "
              f"margin {ALWAYS_LOADED_LIMIT - total})", file=sys.stderr)
        self.assertIn("templates/USER.md", sizes, "the @ import chain must reach USER.md")
        self.assertGreater(len(sizes), 2, "the @ import chain must reach the rules")
        self.assertEqual(check_budget(sizes), [])
        self.assertLessEqual(total, ALWAYS_LOADED_LIMIT - ALWAYS_LOADED_MARGIN)

    def test_description_budget(self):
        """The cap is 11,000 (K3: the kit's own skill text was 15,511); literal numbers, so raising the constant fails here."""
        self.assertEqual(check_descriptions({"a": "x" * 5500, "b": "y" * 5500}), [])
        self.assertEqual(len(check_descriptions({"a": "x" * 5500, "b": "y" * 5501})), 1)
        self.assertEqual(len(check_descriptions({"a": "x" * 11332})), 1, "11,332 characters (the 10,932 text plus kit-update and more) must fail")
        self.assertEqual(len(check_descriptions({"a": "x" * 12000})), 1, "the old 15,800 cap no longer applies")

    def test_description_parsing(self):
        for fm, want in (('description: "a \\"b\\" c"', 'a "b" c'), ("description: plain text: yes", "plain text: yes"),
                         ("description: 'it''s'", "it's"), ("description: >\n  folded\n  text\nname: x", "folded text")):
            self.assertEqual(front_description(f"---\n{fm}\n---\nbody"), want)

    def test_when_to_use_parsing(self):
        for fm, want in (("when_to_use: ALWAYS load this, even then.", "ALWAYS load this, even then."),
                         ('when_to_use: "quoted: yes"', "quoted: yes"), ("when_to_use: >\n  folded\n  text\nname: x", "folded text"),
                         ("name: x", "")):
            self.assertEqual(front_field(f"---\n{fm}\n---\nbody", "when_to_use"), want)
        both = "---\ndescription: d1\nwhen_to_use: w1\n---\n"
        self.assertEqual((front_description(both), front_field(both, "when_to_use")), ("d1", "w1"))

    def test_when_to_use_counts_toward_the_total(self):
        d = {"a": "x" * 10950}
        self.assertEqual(check_descriptions(d, when={"a": "y" * 50}), [], "11,000 exactly is inside the limit")
        self.assertEqual(len(check_descriptions(d, when={"a": "y" * 51})), 1, "the when_to_use text is part of the sum")
        self.assertEqual(check_descriptions(d), [], "no when_to_use, no extra characters")

    def test_each_when_to_use_line_is_at_most_90_characters(self):
        self.assertEqual(check_descriptions({"a": "d"}, when={"a": "y" * 90}), [])
        errs = check_descriptions({"a": "d"}, when={"a": "y" * 91, "b": "ok"})
        self.assertEqual(len(errs), 1)
        self.assertIn("a: when_to_use is 91 characters", errs[0])

    def test_budget_cli_reads_when_to_use(self):
        self.put("instructions/CLAUDE.md", "core\n")
        skill = lambda w: f"---\nname: s\ndescription: d\nwhen_to_use: {w}\n---\nbody\n"   # noqa: E731
        self.put("plugins/p/skills/s/SKILL.md", skill("y" * 90))
        self.assertEqual(main(["--budget", "--root", str(self.tmp)]), 0)
        self.put("plugins/p/skills/s/SKILL.md", skill("y" * 91))
        self.assertEqual(main(["--budget", "--root", str(self.tmp)]), 1, "a 91-character line fails the real CLI")
        self.assertEqual(skill_when(self.tmp), {"plugins/p/skills/s/SKILL.md": "y" * 91})

    def test_the_real_skill_descriptions_are_within_budget(self):
        descs, when = skill_descriptions(KIT), skill_when(KIT)
        print(f"\nskill descriptions + when_to_use: {sum(map(len, descs.values())) + sum(map(len, when.values()))} characters "
              f"in {len(descs)} skills, {len(when)} with when_to_use", file=sys.stderr)
        self.assertEqual(check_descriptions(descs, when=when), [])

    def test_unquoted_frontmatter_values_are_valid_yaml_scalars(self):
        """A plain YAML scalar cannot hold ': ' or ' #': the skill would load with a broken or cut description."""
        bad = []
        for f in _skill_files(KIT):
            fm = re.match(r"---\r?\n(.*?)\r?\n---", f.read_text(encoding="utf-8"), re.S).group(1)
            for line in fm.splitlines():
                m = re.match(r"(description|when_to_use):\s*(\S.*)$", line)
                if m and m.group(2)[:1] not in "\"'|>" and (": " in m.group(2) or " #" in m.group(2)):
                    bad.append(f"{f.relative_to(KIT).as_posix()}: {m.group(1)}")
        excused = set()   # add "<path>: <key>" here only with a dated reason; a fixed file must leave it
        self.assertEqual(sorted(set(bad) - excused), [])
        self.assertEqual(sorted(excused - set(bad)), [], "a fixed file must leave the excuse list")

    def test_the_frozen_when_to_use_lines_are_in_place(self):
        """IW1: A4 writes these in the skills' frontmatter; the line text is frozen, so a drift fails here. IW2 are the seven
        'memory is enough' skills of v0.3.2 (calibration audit row 7): their text is fixed too."""
        when = skill_when(KIT)
        for name, line in {**IW1, **IW2}.items():
            plugin_skill = f"plugins/workbench-core/skills/{name}/SKILL.md"
            self.assertEqual(when.get(plugin_skill), line, name)
            self.assertLessEqual(len(line), WHEN_MAX, name)
        for name, line in IW2.items():
            self.assertTrue(line.startswith("ALWAYS load before "), name)

    def test_user_only_skills_carry_no_when_to_use_and_the_authoring_nine_are_user_only(self):
        """A skill with disable-model-invocation: true is not in the model's listing, so a when_to_use line on it is dead text."""
        entries = {n.split(":")[1]: (w, u) for n, _, w, u in skill_entries(KIT)}
        for name, (w, user_only) in entries.items():
            if user_only:
                self.assertEqual(w, "", f"{name}: user-only, so when_to_use is never shown")
        for name in ("batch-review", "mcp-heal", "plugin-factory", "plugin-review", "web-packager", "mcp-builder", "api-bridge",
                     "app-navigator", "brand-spec", "cleanup", "onboard", "pc-checkup", "setup", "vdi-drive", "capture", "ingest"):
            self.assertTrue(entries[name][1], f"{name} must carry disable-model-invocation: true")

    def test_cleanup_and_cascade_carry_the_data_loss_lines_of_audit_row_35(self):
        """Removing a worktree through a Windows junction deleted real files; a bulk replace hit binaries; a restart kept old env."""
        skills = KIT / "plugins" / "workbench-core" / "skills"
        cleanup = (skills / "cleanup" / "SKILL.md").read_text(encoding="utf-8")
        cascade = (skills / "cascade" / "SKILL.md").read_text(encoding="utf-8")
        for name, text in (("cleanup", cleanup), ("cascade", cascade)):
            for want in ("dir /AL", "rmdir", "rm -rf"):
                self.assertIn(want, text, f"{name}: junction line")
        self.assertIn("Filter to text files before any bulk replace", cascade)
        self.assertIn("A container restart keeps its old environment", cascade)

    def put_skill(self, plugin, name, desc, when="", user_only=False):
        extra = (f"when_to_use: {when}\n" if when else "") + ("disable-model-invocation: true\n" if user_only else "")
        self.put(f"plugins/{plugin}/skills/{name}/SKILL.md", f"---\nname: {name}\ndescription: {desc}\n{extra}---\nbody\n")

    def test_listing_estimate_counts_listed_text_user_only_names_upstream_and_the_allowance(self):
        self.put("instructions/CLAUDE.md", "core\n")
        self.put_skill("p", "alpha", "d" * 100, when="w" * 10)
        self.put_skill("p", "beta", "e" * 500, user_only=True)           # not listed: only its name counts
        self.put("settings/upstream-plugins.fragment.json", json.dumps({"enabledPlugins": {
            "frontend-design@m": True, "unknown-one@m": True, "off-one@m": False}}))
        self.put("settings/upstream-plugins.optional.fragment.json", json.dumps({"enabledPlugins": {"x@m": False}}))
        est = listing_estimate(self.tmp)
        self.assertEqual(est["kit"], (len("p:alpha") + LISTING_ENTRY + 100 + 11) + (len("p:beta") + LISTING_ENTRY))
        self.assertEqual((est["listed"], est["hidden"], est["plugins"]), (1, 1, 2))
        self.assertEqual(est["upstream"], UPSTREAM_CHARS["frontend-design"] + UPSTREAM_DEFAULT)
        self.assertEqual(est["optin"], 2679, "the opt-in skill pack (about 2,262) and humanizer/playwright-cli (about 417)")
        self.assertEqual(est["total"], est["kit"] + est["upstream"] + est["optin"] + BUNDLED_ORG_ALLOWANCE)
        self.assertEqual(listing_estimate(self.tmp / "nowhere")["plugins"], 0, "no settings folder, no upstream plugins")

    def test_the_kit_share_of_the_listing_fails_above_40_percent_of_30000(self):
        self.assertEqual(check_listing({"kit": 12000}), [])
        self.assertEqual(len(check_listing({"kit": 12001})), 1)
        self.assertEqual(len(check_listing({"kit": 14700})), 1, "49 percent, the v0.3.1 kit share, must trip")
        self.assertEqual(len(check_listing({"kit": 6500}, budget=16000)), 1, "40 percent of a smaller budget")
        self.put_skill("p", "huge", "h" * 12100)
        self.assertEqual(len(check_listing(listing_estimate(self.tmp))), 1, "a kit that lists over half the budget fails")
        self.put_skill("p", "huge", "h" * 100)
        self.assertEqual(check_listing(listing_estimate(self.tmp)), [])

    def test_budget_prints_the_estimated_listing_line(self):
        import contextlib
        import io
        self.put("instructions/CLAUDE.md", "core\n")
        self.put_skill("p", "alpha", "d" * 100)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["--budget", "--root", str(self.tmp)])
        self.assertEqual(code, 0)
        self.assertIn("estimated listing: about ", buf.getvalue())
        self.assertIn("bundled and organisation allowance", buf.getvalue())
        self.assertIn("opt-in packs 2679", buf.getvalue())

    def test_user_only_text_is_not_in_the_listing_but_still_in_the_cap(self):
        self.put("instructions/CLAUDE.md", "core\n")
        self.put_skill("p", "only", "u" * 11100, user_only=True)
        self.assertEqual(main(["--budget", "--root", str(self.tmp)]), 1, "the 11,000 cap counts every kit skill, as 15,511 did")
        self.assertEqual(check_listing(listing_estimate(self.tmp)), [], "but the model never sees that text")

    def test_the_real_listing_estimate_is_within_the_kit_share(self):
        est = listing_estimate(KIT)
        print(f"\n{listing_line(est)}", file=sys.stderr)
        self.assertEqual(check_listing(est), [])
        self.assertGreaterEqual(est["hidden"], 16, "the authoring nine plus the user-typed skills are hidden from the model")


# IW1 (the frozen table): skill -> when_to_use
IW1 = {
    "find": "ALWAYS load before answering from work documents, even if memory seems enough.",
    "ui-build": "ALWAYS load before changing or reviewing any page, component or style.",
    "repo-review": "ALWAYS load before reading a repository you did not write, even just to look.",
    "draft-reply": "ALWAYS load before drafting any email, chat reply or message for the user.",
    "skill-scan": "ALWAYS load before installing or trusting a third-party skill or plugin.",
    "handoff": "ALWAYS load when a session nears its limit or work must continue elsewhere.",
    "brain-audit": "ALWAYS load when instructions, hooks or the KB seem stale, ignored or contradictory.",
    "diagram": "ALWAYS load when a diagram, flowchart or architecture sketch is requested.",
}
# IW2: the seven skills a model skips because it believes memory is enough (calibration audit row 7)
IW2 = {
    "github": "ALWAYS load before any gh command, issue or CI task; review a foreign PR with repo-review.",
    "linux-service-triage": "ALWAYS load before debugging a server, service or site that is down or erroring.",
    "deep-research": "ALWAYS load before answering a vendor, tool or \"should we adopt\" question from memory.",
    "office-docx": "ALWAYS load before creating or editing a Word document, even a short memo.",
    "office-pptx": "ALWAYS load before creating or editing a PowerPoint deck, even a small one.",
    "office-xlsx": "ALWAYS load before creating or editing an Excel workbook, even a small one.",
    "repo-fix": "ALWAYS load before reviewing or fixing a whole repository, even if the steps seem clear.",
}


def egress_missing(text, kit_root=KIT):
    """MCP servers and setup hosts that docs/security-overview.md does not name in backticks."""
    servers = _load("mcp/golden-config.template.json", kit_root)["servers"]
    hosts = sorted({h for p in _load("bootstrap/packages.json", kit_root)["packages"] for h in p.get("hosts", [])})
    return ([f"server {k}" for k in servers if f"`{k}`" not in text] +
            [f"host {h}" for h in hosts if f"`{h}`" not in text])


class Version(Fixture):
    def test_one_version_everywhere(self):
        """The installer, the probe, the four plugins, the marketplace, IMPORT.md and the newest CHANGELOG heading agree."""
        v = re.search(r'^VERSION = "([^"]+)"', (KIT / "bootstrap" / "install.py").read_text(encoding="utf-8"), re.M).group(1)
        self.assertIn(f'KIT_VERSION = "{v}"', (KIT / "bootstrap" / "probe.py").read_text(encoding="utf-8"))
        manifests = [KIT / ".claude-plugin" / "marketplace.json", *sorted(KIT.glob("plugins/*/.claude-plugin/plugin.json"))]
        self.assertEqual(len(manifests), 5)
        for m in manifests:
            j = json.loads(m.read_text(encoding="utf-8"))
            self.assertEqual(j.get("version") or j["metadata"]["version"], v, m)
        self.assertIn(f"claude-workbench `v{v}`", (KIT / "IMPORT.md").read_text(encoding="utf-8"))
        self.assertEqual(re.search(r"^## (\S+)", (KIT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M).group(1), v)


class Egress(Fixture):
    def test_the_security_overview_names_every_server_and_setup_host(self):
        text = (KIT / "docs" / "security-overview.md").read_text(encoding="utf-8")
        self.assertEqual(egress_missing(text), [])

    def test_a_missing_server_or_host_is_reported(self):
        text = (KIT / "docs" / "security-overview.md").read_text(encoding="utf-8")
        self.assertEqual(egress_missing(text.replace("`find`", "find")), ["server find"])
        self.assertIn("host nodejs.org", egress_missing(text.replace("`nodejs.org`", "nodejs")))


class Routing(Fixture):
    def setUp(self):
        super().setUp()
        self.routing, self.evidence = _load("settings/model-routing.json"), _load("settings/model-evidence.json")

    def bad(self, mutate):
        routing, evidence = json.loads(json.dumps(self.routing)), json.loads(json.dumps(self.evidence))
        mutate(routing, evidence)
        return check_routing(routing, evidence)

    def test_the_real_data_passes(self):
        self.assertEqual(check_routing(self.routing, self.evidence), [])
        self.assertGreaterEqual(len(self.routing["rows"]), 12)
        self.assertEqual(len(self.routing["rows"]) and len({r["id"] for r in self.routing["rows"]}),
                         len(self.routing["rows"]))

    def test_internal_runs_are_direction_n_tier_month_only(self):
        internal = [r for r in self.evidence["rows"] if r["kind"] == "internal-run"]
        self.assertGreaterEqual(len(internal), 4)
        for r in internal:
            self.assertIsNone(r["value"])
            self.assertRegex(r["date"], r"^20\d\d-\d\d$")

    def test_an_evidence_less_row_fails(self):
        self.assertTrue(self.bad(lambda r, e: r["rows"][0].update(evidence=[])))
        self.assertTrue(self.bad(lambda r, e: r["rows"][0].update(evidence=["E-nope"])))

    def test_evidence_rows_without_source_or_date_fail(self):
        self.assertTrue(self.bad(lambda r, e: e["rows"][0].update(source="")))
        self.assertTrue(self.bad(lambda r, e: e["rows"][0].update(date="")))
        self.assertTrue(self.bad(lambda r, e: e["rows"][0].update(date="2026-10")))

    def test_internal_run_rows_fail_on_value_date_or_numbers(self):
        def idx(e):
            return next(i for i, x in enumerate(e["rows"]) if x["kind"] == "internal-run")
        self.assertTrue(self.bad(lambda r, e: e["rows"][idx(e)].update(value="1")))
        self.assertTrue(self.bad(lambda r, e: e["rows"][idx(e)].update(date="2026-10-01")))
        self.assertTrue(self.bad(lambda r, e: e["rows"][idx(e)].update(claim="scored 9 of 10")))
        self.assertTrue(self.bad(lambda r, e: e["rows"][idx(e)].update(claim="saved $ on every run")))

    def test_a_digit_in_a_routing_row_fails_but_model_names_are_fine(self):
        self.assertTrue(self.bad(lambda r, e: r["rows"][0].update(task_shape="at most 3 files")))
        self.assertTrue(self.bad(lambda r, e: r["rows"][0].update(never=["claude-opus-5-5: after 2 failures"])))
        self.assertEqual(self.bad(lambda r, e: r["rows"][0].update(never=["claude-opus-5-5: not allowed"])), [])

    def test_unknown_model_or_effort_fails(self):
        self.assertTrue(self.bad(lambda r, e: r["rows"][0]["chain"].append({"model": "claude-x-1", "effort": "high"})))
        self.assertTrue(self.bad(lambda r, e: r["rows"][0]["chain"][0].update(effort="turbo")))

    def test_the_rendered_page_is_current(self):
        want = render_routing(self.routing, self.evidence)
        have = (KIT / "docs" / "model-routing.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertEqual(have, want, "run: py -3 tools/test_docs.py --render-routing")


class Cards(Fixture):
    def setUp(self):
        super().setUp()
        self.md = (KIT / "kb-template/_shared/bug-cards.md").read_text(encoding="utf-8")
        self.det = _load("kb-template/_shared/bug-detectors.json")

    def test_the_real_pack_passes(self):
        self.assertEqual(check_cards(self.md, self.det), [])
        self.assertEqual(check_seed_cards(self.md, self.det), [])
        print(f"\ncards: {len(parse_cards(self.md))}, detectors: {len(self.det['detectors'])}", file=sys.stderr)

    def test_every_detector_matches_its_repro_and_no_unrelated_string(self):
        self.assertEqual(len(UNRELATED), 10)
        for d in self.det["detectors"]:
            rx = re.compile(d["pattern"], re.I)
            self.assertTrue(rx.search(d["repro"][:4096]), d["card"])
            self.assertFalse([u for u in UNRELATED if rx.search(u)], d["card"])

    def test_no_detector_matches_another_detectors_repro(self):
        for a in self.det["detectors"]:
            rx = re.compile(a["pattern"], re.I)
            for b in self.det["detectors"]:
                if a is not b:
                    self.assertFalse(rx.search(b["repro"]), f"card {a['card']} also matches the repro of card {b['card']}")

    def test_the_six_digests_exist(self):
        for name in ("windows-shell", "git-ci", "claude-code-mechanics", "mcp", "testing", "orchestration"):
            text = (KIT / "kb-template" / "_shared" / "digests" / f"{name}.md").read_text(encoding="utf-8")
            self.assertGreater(len(text), 1500, name)
            self.assertTrue(text.startswith("---\ntitle: "), name)

    def card(self, n=1, drop=None):
        fields = [f"**{f}:** {f} text that is long enough" for f in FIELDS if f != drop]
        return f"### {n}. Title {n}\n" + "\n".join(fields) + "\n\n"

    def test_a_card_without_fix_fails(self):
        none = {"version": 1, "detectors": []}
        good = "".join(self.card(i) for i in range(1, 6))
        self.assertEqual(check_cards(good, none, minimum=5), [])
        bad = "".join(self.card(i) for i in range(1, 5)) + self.card(5, drop="Fix")
        self.assertEqual(check_cards(bad, none, minimum=5), ["card 5: no Fix"])

    def test_too_few_cards_fail(self):
        self.assertTrue(check_cards(self.card(1), {"version": 1, "detectors": []}))

    def test_bad_detectors_fail(self):
        md = self.card(1)
        ok = {"card": 1, "title": "Title 1", "pattern": "boom", "repro": "a boom happened"}
        run = lambda **kw: check_cards(md, {"version": 1, "detectors": [{**ok, **kw}]}, minimum=1)  # noqa: E731
        self.assertEqual(run(), [])
        self.assertTrue(run(repro=""))
        self.assertTrue(run(repro="nothing here"))
        self.assertTrue(run(pattern="("))
        self.assertTrue(run(pattern=".*"))
        self.assertTrue(run(card=9))
        self.assertTrue(run(title="Another card's title"))   # a detector whose card number was swapped no longer matches its heading

    def test_a_seen_line_in_a_card_file_fails_the_deny_scan(self):
        self.put("kb-template/_shared/bug-cards.md", self.card(1) + "- " + "Seen" + ": private evidence\n")
        self.assertEqual([r for _, _, r in deny_scan([self.tmp / "kb-template"], self.tmp)], ["P1"])


if __name__ == "__main__":
    sys.exit(main() if len(sys.argv) > 1 else unittest.main())
