"""Auto-ponytail: inject the ponytail skill's ruleset into a session once, when build work starts, so nobody has to
type /ponytail. Triggers once per agent context:
  - PostToolUse: the first Write/Edit/MultiEdit/NotebookEdit of a code file;
  - UserPromptSubmit: a prompt with clear build intent ("implement", "refactor", "add an endpoint", ...).
SessionStart(compact) re-arms it, because compaction can drop the injected text. An agent whose own definition
already carries the ruleset is skipped. Text source: skills/ponytail/SKILL.md in this plugin (its marker block
<!-- ponytail:full ... --> ... <!-- /ponytail --> if present, else the body). No skill file, no injection. Exits 0."""
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _wb  # noqa: E402

SRC = HERE.parent / "skills" / "ponytail" / "SKILL.md"
CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs",
            ".c", ".cc", ".cpp", ".h", ".hpp", ".swift", ".sql", ".sh", ".ps1", ".css", ".scss", ".html", ".vue",
            ".svelte", ".ipynb"}
INTENT = re.compile(
    r"\b(implement(?:s|ing)?\b|refactor(?:s|ing)?\b|fix (?:the |this |that |a )?(?:bug|test|error|crash|build|endpoint|function)"
    r"|add (?:an? |the |new )?(?:endpoint|component|feature|function|method|route|test|page|api|column|migration)"
    r"|write (?:an? |the )?(?:script|function|test|class|module|endpoint|component)"
    r"|build (?:an? |the |me an? )?(?:app|feature|component|endpoint|api|script|tool|page|service|cli|bot|site))",
    re.I)


def ruleset():
    try:
        s = SRC.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"<!-- ponytail:full.*?-->\n(.*?)\n<!-- /ponytail -->", s, re.S)
    if m:
        return m.group(1)
    body = re.sub(r"\A---\r?\n.*?\r?\n---\r?\n", "", s, flags=re.S).strip()
    return body or None


def carries_it(agent_type):
    name = (agent_type or "").split(":")[-1]
    try:
        return bool(name) and "PONYTAIL MODE" in (HERE.parent / "agents" / f"{name}.md").read_text(encoding="utf-8")
    except OSError:
        return False


def main():
    d = _wb.read_event()
    ev, sid = d.get("hook_event_name"), re.sub(r"[^A-Za-z0-9-]", "", str(d.get("session_id") or "nosid"))
    state = _wb.workbench_home() / "state" / "ponytail-auto"
    key = state / f"{sid}__{re.sub(r'[^A-Za-z0-9-]', '', str(d.get('agent_id') or 'main'))}"
    state.mkdir(parents=True, exist_ok=True)
    if ev == "SessionStart":
        if d.get("source") == "compact":
            for f in state.glob(f"{sid}__*"):
                f.unlink(missing_ok=True)
        now = time.time()   # forget sessions older than a week
        for f in state.glob("*__*"):
            if now - f.stat().st_mtime > 7 * 86400:
                f.unlink(missing_ok=True)
        return
    if key.exists() or carries_it(d.get("agent_type")):
        return
    if ev == "PostToolUse":
        ti = d.get("tool_input") or {}
        if Path(str(ti.get("file_path") or ti.get("notebook_path") or "")).suffix.lower() not in CODE_EXT:
            return
    elif ev != "UserPromptSubmit" or not INTENT.search(str(d.get("prompt") or "")):
        return
    text = ruleset()
    if not text:
        return
    key.write_text(ev, encoding="utf-8")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": ev, "additionalContext":
                      "Build work started, so ponytail (full) is now on for this session:\n\n" + text}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
