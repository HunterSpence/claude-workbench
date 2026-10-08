"""Auto-invoke: nudge the kit's skills at the moments people forget them.
  UserPromptSubmit  wrap-up phrasing ("we done?", "wrap up", "new session") -> run the save skill (and a handoff
                    note if work is mid-flight); build intent (ponytail_auto.INTENT, one home) -> the cascade skill
  PreToolUse        installing a plugin or skill without a prior skill-scan -> deny once, with the instruction
Prints at most one hookSpecificOutput. Always exits 0."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wb  # noqa: E402
from ponytail_auto import INTENT as BUILD  # noqa: E402

WRAPUP = re.compile(
    r"\b(?:(?:are |r )?we(?:'?re| are)? done\b(?:\W+\w+)?\s*(?:[?.!]|$)|that'?s (?:all|it) for (?:now|today|tonight)\b"
    r"|wrap(?:ping)? (?:it |this |things )?up\b|call it a (?:day|night)\b|signing off\b"
    r"|(?:start(?:ing)?|open(?:ing)?|move to|switch(?:ing)? to) (?:a )?(?:new|fresh) session\b"
    r"|i'?m (?:heading out|logging off|out for (?:now|today|the night))\b|hand (?:this |it )?off\b"
    r"|(?:write|make|do|need|want|create) (?:a |the |me a )?handoff\b)", re.I | re.M)
INSTALL = re.compile(
    r"claude\s+plugins?\s+(?:install|marketplace\s+add)\b|npx\s+(?:-y\s+)?skills?\s+add\b"
    r"|git\s+clone\b[^\n|;&]*(?:skills?|plugins?)\b|(?:cp|copy-item|robocopy|mv|move-item)\b[^\n|;&]*\.claude[\\/](?:skills|plugins)\b",
    re.I)
SCANNED = "# skill-scanned"


def main():
    d = _wb.read_event()
    ev = d.get("hook_event_name")
    if ev == "UserPromptSubmit":
        p = str(d.get("prompt") or "")
        notes = []
        if WRAPUP.search(p):
            notes.append("The user is wrapping up. Before you answer, run the save skill so this session's knowledge "
                         "reaches the knowledge base; if work is still mid-flight, also write a resume note with the "
                         "handoff skill. Then answer.")
        if BUILD.search(p):
            notes.append("This is build work: for a multi-file fix, build, refactor or migration, use the cascade "
                         "skill (diagnose, plan, implement, verify). A one-file or trivial change does not need it.")
        if notes:
            _wb.emit(ev, additionalContext="Auto-invoke: " + " ".join(notes))
    elif ev == "PreToolUse" and d.get("tool_name") in ("Bash", "PowerShell"):
        cmd = str((d.get("tool_input") or {}).get("command") or "")
        if INSTALL.search(cmd) and SCANNED not in cmd:
            _wb.emit(ev, permissionDecision="deny", permissionDecisionReason=(
                "Installing a plugin or skill: scan the source with the skill-scan skill first, and check that your "
                "organisation allows it. If the scan passes, re-run the same command with "
                f"`{SCANNED}` appended as a trailing comment."))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
