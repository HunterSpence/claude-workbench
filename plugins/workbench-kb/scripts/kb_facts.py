#!/usr/bin/env python3
"""kb_facts.py: the fact registry. One fact, one home, and a check that the home still says it.

<KB>/_shared/facts.json holds {"facts": [{"id", "owner", "canonical", "forbidden": [...]}]}:
  owner      the note that states the fact (a path under the KB root; the .md may be left off)
  canonical  the text the owner note must keep stating
  forbidden  texts that mean a stale or competing version of the fact: none may appear in the KB notes or in the
             always-loaded instruction files (CLAUDE.md, its imports and the unconditional rules)

A finding is a forbidden text found, an owner that no longer states its canonical text, a missing owner note, or a
registry entry that cannot be used. Matching ignores case and line breaks inside a phrase, and a text counts only as a
whole phrase (a hyphen or a word character on either side makes it a different word). Exempt: any line that carries
SUPERSEDED (the marked old value), history records (history.md, history/), daily/, inbox/, dot folders, README.md files,
and the owner note itself (it may name the value that misleads).

Usage: kb_facts.py [--json]      exit 1 when there is any finding (kb_health.py facts runs the same check)
       kb_facts.py --self-test   offline, one line, exit 0
"""
import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import frontmatter  # noqa: E402
import savelock  # noqa: E402

SKIP_DIRS = {"daily", "inbox", "history"}
IMPORT_RX = re.compile(r"(?<![\w`])@((?:[~./\\]|[A-Za-z]:)?[^\s`)\]]+\.(?:md|txt))")


def registry_path(root):
    return Path(root) / "_shared" / "facts.json"


def _phrase(text):
    """A regex for `text` as a whole phrase: spaces match any run of whitespace, neighbours may not be word or hyphen."""
    return re.compile(r"(?<![\w-])" + r"\s+".join(map(re.escape, text.split())) + r"(?![\w-])", re.I)


def load(root):
    """(facts, problems): the usable entries of the registry and one line per thing wrong with it. No file -> (None, [])."""
    p = registry_path(root)
    if not p.is_file():
        return None, []
    try:
        data = json.loads(savelock.read_text(p))
        entries = data["facts"]
        if not isinstance(entries, list):
            raise TypeError("facts is not a list")
    except (ValueError, KeyError, TypeError) as e:
        return [], [f"{p.name} is not usable ({type(e).__name__}: {e}); it must be {{\"facts\": [...]}}"]
    facts, problems, seen = [], [], set()
    for n, e in enumerate(entries, 1):
        ok = (isinstance(e, dict) and all(isinstance(e.get(k), str) and e[k].strip() for k in ("id", "owner", "canonical"))
              and isinstance(e.get("forbidden", []), list) and all(isinstance(x, str) and x.strip() for x in e.get("forbidden", [])))
        if not ok:
            problems.append(f"entry {n} needs a text id, owner and canonical, and forbidden as a list of texts")
        elif e["id"] in seen:
            problems.append(f"entry {n}: the id {e['id']!r} is used twice")
        elif any(_phrase(x).search(e["canonical"]) for x in e.get("forbidden", [])):
            problems.append(f"entry {n} ({e['id']}): a forbidden text sits inside the canonical text")
        else:
            seen.add(e["id"])
            facts.append(e)
    return facts, problems


def is_note(parts):
    """True for a curated note, given its path parts under the KB root: Markdown, and neither a record (history.md,
    history/, daily/, inbox/), a README.md (about the folder, not knowledge) nor inside a dot folder."""
    return parts[-1].endswith(".md") and parts[-1] not in ("history.md", "README.md") and not any(
        s.startswith(".") or s in SKIP_DIRS for s in parts[:-1])


def kb_notes(root):
    """[(relative path, text)] of every note the check reads."""
    root = Path(root)
    return [("/".join(parts), savelock.read_text(p)) for p in sorted(root.rglob("*.md"))
            for parts in [p.relative_to(root).parts] if is_note(parts)]


def always_loaded(project=None):
    """[(display name, text)]: the files Claude Code loads at launch for this config dir and project folder."""
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    proj = Path(project) if project is not None else Path.cwd()
    todo = [home / "CLAUDE.md", proj / "CLAUDE.md", proj / ".claude" / "CLAUDE.md", proj / "CLAUDE.local.md"]
    for rules in (home / "rules", proj / ".claude" / "rules"):
        for p in sorted(rules.rglob("*.md")):
            if frontmatter.get(savelock.read_text(p), "paths") is None:     # a path-scoped rule is not always loaded
                todo.append(p)
    seen, out = set(), []
    while todo:
        p = todo.pop(0)
        if not p.is_file() or p.resolve() in seen:
            continue
        seen.add(p.resolve())
        text = savelock.read_text(p)
        out.append((p.as_posix(), text))
        for m in IMPORT_RX.findall(text):
            q = Path(os.path.expanduser(m.replace("\\ ", " ")))
            todo.append(q if q.is_absolute() else p.parent / q)
    return out


def check(root, project=None):
    """{"registered": bool, "facts": int, "findings": [{"fact", "kind", "file", "line", "text"}]}"""
    facts, problems = load(root)
    res = {"registered": facts is not None, "facts": len(facts or []), "findings": []}
    add = lambda fact, kind, file="", line=0, text="": res["findings"].append(   # noqa: E731
        {"fact": fact, "kind": kind, "file": file, "line": line, "text": text})
    for msg in problems:
        add("", "registry", registry_path(root).name, 0, msg)
    if not facts:
        return res
    kb = kb_notes(root)
    by_path, notes = dict(kb), kb + always_loaded(project)
    for f in facts:
        rel = f["owner"].strip().strip("[]").replace("\\", "/").removeprefix("./").lstrip("/").removesuffix(".md") + ".md"
        if rel not in by_path:
            add(f["id"], "owner", rel, 0, "the owner note does not exist (or sits where the check does not read)")
        elif not _phrase(f["canonical"]).search(by_path[rel]):
            add(f["id"], "canonical", rel, 0, f"the owner note no longer states: {f['canonical']}")
        for x in f.get("forbidden", []):
            rx = _phrase(x)
            for name, text in notes:
                if name == rel:   # the owner may say which value misleads
                    continue
                for m in rx.finditer(text):
                    a = text.rfind("\n", 0, m.start()) + 1
                    b = text.find("\n", m.start())
                    if "superseded" not in text[a:b if b >= 0 else len(text)].lower():
                        add(f["id"], "forbidden", name, text.count("\n", 0, m.start()) + 1, x)
    return res


def summary(res):
    """(status, detail) for kb_health: INFO when nothing is registered, FAIL on any finding, else PASS."""
    if not res["registered"]:
        return "INFO", "no registry (_shared/facts.json): nothing to check"
    if not res["findings"]:
        return ("PASS", f"{res['facts']} fact(s): every owner states its canonical text, no forbidden text found") \
            if res["facts"] else ("INFO", "the registry holds no facts yet")
    where = lambda f: f["file"] + (f":{f['line']}" if f["line"] else "")   # noqa: E731
    return "FAIL", f"{len(res['findings'])} finding(s)" + "".join(
        f"\n    {f['fact']}: forbidden text {f['text']!r} at {where(f)}" if f["kind"] == "forbidden"
        else f"\n    {f['fact'] or 'registry'}: {f['text']} ({where(f)})" for f in res["findings"][:10])


def self_test():
    """Offline, in a temporary folder: a clean registry passes; each kind of drift is found and the exempt lines are not."""
    saved = os.environ.get("CLAUDE_CONFIG_DIR")
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        kb, home = base / "kb", base / "home"
        os.environ["CLAUDE_CONFIG_DIR"] = str(home)
        try:
            def put(path, text):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="\n")
            put(kb / "infra" / "builder.md", "---\ntitle: builder\n---\nThe build server runs in region east-a.\n")
            put(kb / "infra" / "history.md", "## old\nThe build server ran in region west-b.\n")
            put(kb / "ops" / "note.md", "SUPERSEDED: was region west-b, now region east-a.\n")
            put(home / "rules" / "env.md", "Builds run in region EAST-A.\n")
            reg = {"facts": [{"id": "builder-region", "owner": "infra/builder", "canonical": "region east-a",
                              "forbidden": ["region west-b"]}]}
            put(registry_path(kb), json.dumps(reg))
            res = check(kb, project=base / "proj")
            assert res["facts"] == 1 and not res["findings"], res
            put(home / "rules" / "env.md", "Builds run in region west-b.\n")
            assert [(f["kind"], f["file"].rsplit("/", 1)[-1], f["line"]) for f in check(kb, base)["findings"]] == [("forbidden", "env.md", 1)]
            put(home / "rules" / "env.md", "Nothing here.\n")
            put(kb / "infra" / "builder.md", "The build server moved.\n")
            assert [f["kind"] for f in check(kb, base)["findings"]] == ["canonical"]
        finally:
            if saved is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = saved
    print("kb_facts self-test ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        self_test()
        return 0
    import kb_audit
    res = check(kb_audit.ROOT)
    status, detail = summary(res)
    if a.json:
        print(json.dumps({**res, "status": status, "exit": 1 if status == "FAIL" else 0}, indent=1))
    else:
        print(f"{status} facts {detail}")
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
