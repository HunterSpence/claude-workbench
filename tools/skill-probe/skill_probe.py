#!/usr/bin/env python3
"""skill_probe.py: does a skill fire when it should, and stay quiet when it should not? Offline: it reads the Claude Code
transcripts you already have and counts, per skill, how often a prompt matching your "should" list and your "should not"
list was followed by a `Skill` tool call for that skill.

  py -3 <KIT>/tools/skill-probe/skill_probe.py --spec probe.json [--transcripts DIR] [--json]
  py -3 <KIT>/tools/skill-probe/skill_probe.py --self-test

probe.json:  {"version": 1, "skills": {"<skill name>": {"should": ["<regex>", ...], "should_not": ["<regex>", ...]}}}
Patterns are Python regular expressions, matched case-insensitively against the text of each prompt. Write the near
misses you want left alone under should_not. A plugin-qualified call (plugin:skill) counts for the bare skill name.

A prompt "led to" a skill call when a `Skill` tool_use naming that skill appears between that prompt and the next real
prompt of the same transcript. Any other tool call (Read, Bash, Task ...) never counts, whatever it touches. Subagent
traffic, tool results, slash-command wrappers and system notes are not prompts. A skill you ran yourself with a slash
command is not a model decision and is not counted.

Output is counts, rates and prompt ids (the transcript line's uuid): for "should" the prompts that did not fire it,
for "should_not" the ones that did. Prompt text is never printed. With fewer than 5 matching prompts a rate is not a
verdict. Exit 0 = report printed, 2 = unusable input.
"""
import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

MIN_N, FIRE_MIN, FIRE_MAX = 5, 0.8, 0.2     # prompts needed to judge; should-rate floor; should-not-rate ceiling
ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
MAX_LINE = 2_000_000                        # a longer line is a tool result, not a prompt
SKIP_TEXT = ("<command-", "<local-command", "<system-reminder", "<task-notification")


def claude_home():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def load_spec(path):
    """{skill: {"should": [regex], "should_not": [regex]}} compiled; ValueError with a plain message when unusable."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        skills = raw["skills"]
        assert isinstance(skills, dict) and skills
    except (OSError, ValueError, KeyError, AssertionError, TypeError):
        raise ValueError('the spec must be a JSON file shaped {"skills": {"<name>": {"should": [...], "should_not": [...]}}}')
    out = {}
    for name, lists in skills.items():
        if not (isinstance(lists, dict) and all(isinstance(lists.get(k, []), list) for k in ("should", "should_not"))):
            raise ValueError(f"skill {name!r}: should and should_not must be lists of patterns")
        try:
            out[name] = {k: [re.compile(p, re.I) for p in lists.get(k, [])] for k in ("should", "should_not")}
        except (re.error, TypeError) as e:
            raise ValueError(f"skill {name!r}: bad pattern ({e})")
        if not (out[name]["should"] or out[name]["should_not"]):
            raise ValueError(f"skill {name!r}: give at least one pattern")
    return out


def content(d):
    m = d.get("message")
    return m.get("content") if isinstance(m, dict) else None


def prompt_text(d):
    """The text of a real user prompt, else None."""
    if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain"):
        return None
    c = content(d)
    if isinstance(c, list):
        c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(c, str) or not c.strip() or c.lstrip().startswith(SKIP_TEXT):
        return None
    return c


def skills_called(d):
    """Skill names in the Skill tool_use blocks of an assistant line (and nothing else)."""
    if d.get("type") != "assistant" or d.get("isSidechain"):
        return set()
    c = content(d)
    return {b["input"]["skill"] for b in c if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Skill"
            and isinstance(b.get("input"), dict) and isinstance(b["input"].get("skill"), str)} if isinstance(c, list) else set()


def read_prompts(root, max_files=500):
    """[(prompt id, text, {skill names called before the next prompt})] over every transcript under root."""
    files = sorted((p for p in Path(root).rglob("*.jsonl") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files[:max_files]:
        cur = None
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if len(line) > MAX_LINE or ('"user"' not in line and '"Skill"' not in line):
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                text = prompt_text(d)
                if text is not None:
                    uid = d.get("uuid") if isinstance(d.get("uuid"), str) and ID.fullmatch(d["uuid"]) else f"p{len(out) + 1}"
                    cur = (uid, text, set())
                    out.append(cur)
                elif cur is not None:
                    cur[2].update(skills_called(d))
    return out


def probe(spec, prompts):
    norm = lambda s: s.rsplit(":", 1)[-1]   # noqa: E731
    result = {}
    for name, lists in spec.items():
        row = {}
        for kind in ("should", "should_not"):
            hits = [(uid, any(norm(c) == norm(name) for c in called))
                    for uid, text, called in prompts if any(rx.search(text) for rx in lists[kind])]
            fired = sum(1 for _, f in hits if f)
            row[kind] = {"prompts": len(hits), "fired": fired, "rate": round(fired / len(hits), 3) if hits else None,
                         "ids": [u for u, f in hits if not f] if kind == "should" else [u for u, f in hits if f]}
        s, n = row["should"], row["should_not"]
        if s["prompts"] < MIN_N and n["prompts"] < MIN_N:
            row["verdict"] = "too few matching prompts to judge"
        else:
            notes = []
            if s["prompts"] >= MIN_N and s["rate"] < FIRE_MIN:
                notes.append("reword the description: it fires too rarely on the prompts it should catch")
            if n["prompts"] >= MIN_N and n["rate"] > FIRE_MAX:
                notes.append("narrow the description: it fires on near misses")
            row["verdict"] = "; ".join(notes) or "ok"
        result[name] = row
    return result


def render(result, n_prompts):
    out = [f"skill-probe: {n_prompts} prompts read"]
    for name, row in result.items():
        out.append(name)
        for kind, label in (("should", "should    "), ("should_not", "should_not")):
            r = row[kind]
            pct = "n/a" if r["rate"] is None else f"{round(100 * r['rate'])}%"
            ids = r["ids"][:10]
            what = "missed ids" if kind == "should" else "fired-on ids"
            out.append(f"  {label}  prompts {r['prompts']}  fired {r['fired']}  rate {pct}" + (f"  {what}: {', '.join(ids)}" if ids else ""))
        out.append(f"  verdict: {row['verdict']}")
    return "\n".join(out)


def run(a, out=sys.stdout, err=sys.stderr):
    try:
        spec = load_spec(a.spec)
    except ValueError as e:
        print(f"skill-probe: {e}", file=err)
        return 2
    root = Path(a.transcripts) if a.transcripts else claude_home() / "projects"
    if not root.is_dir():
        print(f"skill-probe: no transcripts folder at {root}", file=err)
        return 2
    prompts = read_prompts(root, a.max_files)
    if not prompts:
        print("skill-probe: no prompts found in the transcripts", file=err)
        return 2
    result = probe(spec, prompts)
    print(json.dumps({"prompts": len(prompts), "skills": result}) if a.json else render(result, len(prompts)), file=out)
    return 0


def self_test():
    def user(uid, text):
        return json.dumps({"type": "user", "uuid": uid, "message": {"role": "user", "content": text}})

    def call(name, **inp):
        return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t", "name": name, "input": inp}]}})
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "t").mkdir()
        (tmp / "t" / "s.jsonl").write_text("\n".join([
            user("u1", "please draw a flowchart of the login"), call("Skill", skill="plugin:chart"),
            user("u2", "draw a flowchart of billing"), call("Read", file_path="chart/SKILL.md"),
            user("u3", "what is a flowchart")]) + "\n", encoding="utf-8")
        spec = tmp / "p.json"
        spec.write_text(json.dumps({"skills": {"chart": {"should": ["draw a flowchart"], "should_not": ["what is a"]}}}), encoding="utf-8")
        r = probe(load_spec(spec), read_prompts(tmp / "t"))["chart"]
        assert (r["should"]["prompts"], r["should"]["fired"], r["should_not"]["prompts"], r["should_not"]["fired"]) == (2, 1, 1, 0), r
        assert r["should"]["ids"] == ["u2"], r
    print("skill_probe self-test ok")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Count how often prompts that should and should not trigger a skill led to a Skill call.")
    ap.add_argument("--spec", help="probe.json with the should / should_not patterns per skill")
    ap.add_argument("--transcripts", help="folder of *.jsonl transcripts (default <Claude config dir>/projects)")
    ap.add_argument("--max-files", type=int, default=500)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    if not a.spec:
        ap.error("--spec is required")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
