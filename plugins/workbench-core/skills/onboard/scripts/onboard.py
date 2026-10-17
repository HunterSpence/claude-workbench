#!/usr/bin/env python3
"""onboard.py: write the onboarding interview's answers to <workbench home>/USER.md and seed the knowledge base's
_shared/HOT.md. The interview itself is the onboard skill's job; this file only writes what it was given.

  onboard.py --answers answers.json [--dry-run]

answers.json keys (all optional; a missing or empty one is left out):
  name, role_team, timezone_hours, ai_policy                                            strings
  sign_off, greeting, tone, avoid                                                       strings (how I write)
  work_prefs, repos, tools, review_norms, never, facts                                  lists of strings

Refuses any answer that looks like a credential (the kit's secret scanner). The old USER.md is copied to
<workbench home>/backups/onboard-<stamp>/ first. The HOT.md seed sits between onboard markers and is replaced on a
re-run. Standard library only.
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"      # plugins/workbench-core/scripts
sys.path.insert(0, str(SCRIPTS))
import _wb  # noqa: E402
import secretscan  # noqa: E402

START, END = "<!-- onboard:start -->", "<!-- onboard:end -->"
STRINGS = ("name", "role_team", "timezone_hours", "ai_policy", "sign_off", "greeting", "tone", "avoid")
LISTS = ("work_prefs", "repos", "tools", "review_norms", "never", "facts")


def clean(answers):
    out = {}
    for k in STRINGS:
        v = " ".join(str(answers.get(k) or "").split())
        if v:
            out[k] = v
    for k in LISTS:
        v = answers.get(k) or []
        v = [" ".join(str(x).split()) for x in (v if isinstance(v, list) else [v]) if str(x).strip()]
        if v:
            out[k] = v
    bad = [k for k, v in out.items() if secretscan.scan_text(v if isinstance(v, str) else "\n".join(v))]
    if bad:
        raise ValueError("these answers look like credentials and were not written: " + ", ".join(bad)
                         + ". Never write a credential value into USER.md.")
    return out


def user_md(a):
    def line(label, key):
        return [f"- **{label}:** {a[key]}"] if key in a else []

    def items(key):
        return [f"- {x}" for x in a.get(key, [])]
    parts = ["# About me (work identity)", "",
             "<!-- Written by /workbench-core:onboard. Imported into every session: WORK facts only. Re-run the skill",
             "     or edit this file to change it. -->", "",
             "## Who", *line("Name I go by", "name"), *line("Role and team", "role_team"),
             *line("Time zone and working hours", "timezone_hours"), "",
             "## Where the rules live", *line("Organisation policies that apply to AI tools", "ai_policy"), "",
             "## How I like to work", *items("work_prefs"), "",
             "## How I write (draft-reply reads this)", *line("Sign-off name", "sign_off"),
             *line("Greeting style", "greeting"), *line("Tone", "tone"), *line("Phrases to avoid", "avoid"), "",
             "## Repos and tools I use", *items("repos"), *items("tools"), "",
             "## Review and merge norms", *items("review_norms"), "",
             "## Never do", *items("never"), "",
             "## Facts to keep in mind", *items("facts"), ""]
    text = "\n".join(parts)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


def seed(a, today):
    rows = []
    if "role_team" in a or "timezone_hours" in a:
        rows.append("- Team: " + " · ".join(a[k] for k in ("role_team", "timezone_hours") if k in a))
    for key, label in (("repos", "Repos"), ("tools", "Tools"), ("review_norms", "Review and merge norms"),
                       ("never", "Never")):
        if key in a:
            rows.append(f"- {label}: " + "; ".join(a[key]))
    if not rows:
        return None
    return "\n".join([START, f"<!-- seeded {today} by /workbench-core:onboard; USER.md owns these facts -->", *rows, END])


def put_seed(hot, block):
    text = hot.read_text(encoding="utf-8") if hot.exists() else "# _shared: hot facts\n\n## Current state\n"
    if START in text and END in text:
        a, b = text.index(START), text.index(END) + len(END)
        return text[:a] + block + text[b:]
    marker = "## Current state"
    if marker in text:
        i = text.index(marker) + len(marker)
        return text[:i] + "\n" + block + text[i:]
    return text.rstrip("\n") + "\n\n" + marker + "\n" + block + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write onboarding answers to USER.md and seed _shared/HOT.md.")
    ap.add_argument("--answers", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        answers = clean(json.loads(Path(a.answers).read_text(encoding="utf-8-sig")))
    except (OSError, ValueError) as e:
        print(f"not written: {e}", file=sys.stderr)
        return 2
    wb, kb = _wb.workbench_home(), _wb.kb_root()
    user, hot = wb / "USER.md", kb / "_shared" / "HOT.md"
    body, block = user_md(answers), seed(answers, time.strftime("%Y-%m-%d"))
    if a.dry_run:
        print(f"--- {user.as_posix()}\n{body}")
        if block:
            print(f"--- {hot.as_posix()} (onboard block)\n{block}")
        return 0
    if user.exists():
        bak = wb / "backups" / f"onboard-{time.strftime('%Y%m%d-%H%M%S')}"
        bak.mkdir(parents=True, exist_ok=True)
        shutil.copy2(user, bak / "USER.md")
        print(f"backed up the old USER.md to {bak.as_posix()}")
    wb.mkdir(parents=True, exist_ok=True)
    user.write_text(body, encoding="utf-8", newline="\n")
    print(f"wrote {user.as_posix()}")
    if block and kb.is_dir():
        hot.parent.mkdir(parents=True, exist_ok=True)
        hot.write_text(put_seed(hot, block), encoding="utf-8", newline="\n")
        print(f"seeded {hot.as_posix()}")
    elif block:
        print(f"knowledge base not found at {kb.as_posix()}: HOT.md not seeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
