---
name: skill-scan
description: "Security-scan installed Claude Code skills (or any folder) with NVIDIA SkillSpector and report per-skill risk. Use when a skill or plugin was just installed or written, or before trusting third-party skill code."
when_to_use: "ALWAYS load before installing or trusting a third-party skill or plugin."
---

# skill-scan

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it
> appears unreplaced (the skill was copied in without the plugin), use `py -3` on Windows and
> `python3` on Linux, macOS and WSL, never the Microsoft Store `python` stub.

A wrapper (`scripts/scan_catalog.py`, stdlib only) that runs SkillSpector on every skill folder,
writes `latest.json` / `latest.md` reports, and diffs high-signal findings against a baseline so
only NEW or INCREASED risk is flagged.

## Setup (once; ask before installing)
SkillSpector is Apache-2.0 (`NVIDIA/skillspector`). Install a pinned tag from source into its own
virtual environment, then tell the wrapper where the executable is:
```bash
git clone --depth 1 --branch <tag> https://github.com/NVIDIA/skillspector <dir>
cd <dir> && uv sync            # or: <python> -m venv .venv && .venv/bin/pip install -e .
export SKILLSPECTOR_EXE=<dir>/.venv/bin/skillspector      # Windows: <dir>\.venv\Scripts\skillspector.exe
```
If `skillspector` is already on PATH, no variable is needed.

## Run
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/scan_catalog.py"                  # all user + plugin-cache skills, static
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/scan_catalog.py" --skills-dir <path>   # vet a folder before adopting it
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/scan_catalog.py" --llm-top 8      # re-scan the 8 worst with the LLM analyzer
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/scan_catalog.py" --update-baseline   # accept current counts after review
```
Reports go to `--reports` (default `<config dir>/skill-scan-reports/`). For "did anything change",
read `latest.md` before re-scanning. Default is 2 parallel workers; raise `--workers` only on a
machine with memory to spare.

The `--llm-top` pass uses whatever model provider SkillSpector is configured for (see its README;
`SKILLSPECTOR_PROVIDER`). It sends skill content to that provider, so check that is allowed for
the skills you scan. The static pass makes no network calls of its own.

## Interpreting results
- A HIGH or CRITICAL finding in a high-signal category (Data Exfiltration, Prompt Injection, Supply
  Chain, Malicious Code, MCP Tool Poisoning, Memory Poisoning, Rogue Agent): re-run with
  `--llm-top` before calling it actionable. The static pass alone has many false positives.
- Outside those categories, in a skill you wrote: usually by-design autonomy (a skill that runs
  shell commands on purpose). Note it; do not escalate.
- Third-party skills: take findings at face value; scan a new plugin BEFORE its first use.
- `SCAN_ERROR` / `TIMEOUT` means the scan failed on that skill, not that it is clean. Report them.
- Typical false positives: `__pycache__`/`.pyc` files ("concealed executable"), HTML comments
  ("hidden instructions"), copying `os.environ` for a subprocess ("env harvesting"), XML schema
  files, and skills that write skills ("self-modification"). Accept reviewed ones into the baseline.

## Output
Report: total scanned, deltas versus the previous report, the HIGH/CRITICAL list with category and
a one-line why, and a verdict per item (act / ignore as noise). Do not paste raw JSON.
