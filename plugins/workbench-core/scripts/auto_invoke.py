"""Auto-invoke: nudge the kit's skills at the moments people forget them.
  UserPromptSubmit  wrap-up phrasing ("we done?", "wrap up", "done for today", "new session") -> run /workbench-kb:save
                    (and a handoff note if work is mid-flight); build intent (ponytail_auto.INTENT, one home) -> cascade;
                    otherwise SKILLS below: the first few skills whose trigger matches are named, with why.
                    User-invoked skills (USER_ONLY) are only mentioned, never started.
  PreToolUse        installing a plugin or skill: no scanner installed -> ask; scanner installed -> deny until the
                    command carries the scanned marker, then ask (the self-attested marker never passes alone)
Prints at most one hookSpecificOutput. Always exits 0. Every kit skill has a row (a test checks this)."""
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _wb  # noqa: E402
from ponytail_auto import INTENT as BUILD  # noqa: E402

WRAPUP = re.compile(
    r"\b(?:(?:are |r )?we(?:'?re| are)? done\b(?:\W+\w+)?\s*(?:[?.!]|$)|that'?s (?:all|it) for (?:now|today|tonight)\b"
    r"|(?:i'?m |we'?re )?done for (?:today|the day|tonight|now)\b"
    r"|wrap(?:ping)? (?:it |this |things )?up\b|call it a (?:day|night)\b|signing off\b"
    r"|(?:start(?:ing)?|open(?:ing)?|move to|switch(?:ing)? to) (?:a )?(?:new|fresh) session\b"
    r"|i'?m (?:heading out|logging off|out for (?:now|today|the night))\b|hand (?:this |it )?off\b"
    r"|(?:write|make|do|need|want|create) (?:a |the |me a )?handoff\b)", re.I | re.M)
INSTALL = re.compile(
    r"claude\s+plugins?\s+(?:install|marketplace\s+add)\b|npx\s+(?:-y\s+)?skills?\s+add\b"
    r"|git\s+clone\b[^\n|;&]*(?:skills?|plugins?)\b|(?:cp|copy-item|robocopy|mv|move-item)\b[^\n|;&]*\.claude[\\/](?:skills|plugins)\b",
    re.I)
SCANNED = "# skill-scanned"
_W = r"[^.?!\n]{0,40}"   # same sentence, a few words apart

# (skill, trigger, what to do). Order = priority; at most MAX_HINTS are named per prompt.
SKILLS = [
    ("repo-fix", rf"\b(?:fix|review|clean ?up|audit|look (?:over|at|through)|go through|harden){_W}\b(?:repo|repository|codebase)\b"
                 r"|github\.com/[\w.-]+/[\w.-]+|\bfix (?:the |all (?:the )?|these |our )?(?:failing|broken|red|flaky) "
                 r"(?:tests?|specs?|builds?|ci|checks?)\b", "clone to scratch, baseline, review, test-first fixes, PR.md"),
    ("ui-build", rf"\b(?:build|design|redesign|style|fix|polish|implement|make|create|change|update|improve){_W}"
                 r"\b(?:ui|ux|frontend|front-end|css|layout|responsive|dark mode|design system|component|page|screen|"
                 r"landing page|dashboard|form|navbar|modal)s?\b|\b(?:ui|ux|frontend|front-end) (?:work|change|bug|review)\b",
     "find the design system, run locally, screenshot 1440/390 light+dark, a11y check, before/after pairs"),
    ("draft-reply", rf"\b(?:reply|respond|response|answer|write back|get back){_W}\b(?:e-?mail|mail|message|thread|chat|him|her|"
                    r"them|this|team)\b|\bdraft (?:a |an |the |my )?(?:reply|response|e-?mail|message|answer)\b|\.(?:eml|msg)\b",
     "answer first, then asks with owners and dates; drafts only, never sends"),
    ("office-docx", rf"\b(?:word (?:doc|document|file)|docx|memo|write-?up)\b|\b(?:write|draft|make|create|build|format|turn)"
                    rf"{_W}\b(?:document|doc|report|memo|proposal|brief)\b", "outline or Markdown to .docx, then render and look"),
    ("office-pptx", r"\b(?:deck|slides?|power ?point|pptx|presentation)\b", "outline to .pptx on the template, then render and look"),
    ("office-xlsx", r"\b(?:excel|spreadsheet|xlsx|workbook|pivot table)\b", "live formulas, styles, recalc and error check"),
    ("office-render", r"\b(?:render|preview){_W}\b(?:deck|doc|document|pdf|workbook|slides?)\b|\bdoes (?:the|this|it) "
                      r"(?:deck|doc|document|slide) look\b".replace("{_W}", _W), "one PNG per page, read every one"),
    ("github", r"\b(?:pull requests?|PR ?#?\d+|github|gh cli|actions? runs?|workflow runs?|ci (?:is )?(?:red|failing|failed))\b",
     "gh CLI, Enterprise hosts included"),
    ("investigate", r"\b(?:debug|root cause|stack ?trace|traceback|flaky|regression|not working|it'?s broken)\b|\bwhy (?:is|does|did)"
                    rf"{_W}\b(?:fail|failing|broken|crash|slow|wrong|error)", "no fix before a proven root cause"),
    ("ratchet", r"\b(?:ratchet|keep going until (?:it'?s )?clean|find everything|don'?t stop at the first pass|harden (?:this|it) properly"
                r"|fix (?:the |all (?:the )?|these )?(?:failing|broken|red|flaky) (?:tests?|specs?|checks?))\b",
     "rounds until two find nothing new"),
    ("deep-research", r"\b(?:deep research|research (?:everything|thoroughly|this properly)|should we (?:adopt|use|switch to)|"
                      r"compare (?:the )?(?:vendors|tools|options|libraries)|evaluate (?:the )?(?:vendors|tools|options))\b",
     "many sources, adversarial check, decision list"),
    ("doc-index", r"\b(?:search|find|look up){_W}\b(?:our|my|the team'?s|shared) (?:docs|documents|files|sharepoint|onedrive|"
                  r"library)\b|\bwhat do (?:our|the) docs say\b".replace("{_W}", _W), "local full-text search, cited answers"),
    ("ctx-agent-history-search", r"\b(?:what did we (?:do|decide|try)|last session|previous session|earlier session|which session|"
                                 r"agent history|past transcripts?)\b", "search earlier sessions before redoing work"),
    ("spawn", r"\b(?:subagents?|spawn|delegate|in parallel|fan[- ]out)\b", "pick the persona, write a self-contained prompt"),
    ("batch-review", r"\b(?:batch (?:api|review)|bulk (?:review|grade|judge|score)|(?:grade|score|judge) (?:all|every|these))\b",
     "non-interactive passes at batch price"),
    ("brain-audit", r"\b(?:audit (?:the )?(?:kb|knowledge base|memory|brain|instructions|config)|kb health|is the (?:kb|memory) clean)\b",
     "read-only health check, ranked fix list"),
    ("skill-scan", r"\b(?:is (?:this|the|that) (?:skill|plugin) safe|scan (?:the |this |all )?(?:skills?|plugins?)|skillspector)\b",
     "scan before trusting third-party skill code"),
    ("mcp-heal", rf"\bmcp{_W}\b(?:broken|down|failed|failing|not (?:working|connecting|loading)|heal|check)\b|\bfailed to connect\b",
     "probe every server, report OK/DEGRADED/DOWN"),
    ("linux-service-triage", r"\b(?:systemd|systemctl|journalctl|nginx|pm2|50[23] (?:error|bad gateway)|server (?:is )?down|"
                             r"service (?:is )?(?:down|failing|crashing)|container (?:keeps )?(?:crash|restart)\w*)\b",
     "evidence first, minimal fix, rollback"),
    ("handoff", r"\b(?:resume card|usage limit|out of (?:context|tokens)|session (?:is )?(?:running out|almost full))\b",
     "self-contained handoff or resume card"),
    ("ponytail", r"\b(?:ponytail|over-?engineer(?:ed|ing)?|simplify (?:this|it)|too much code|smallest diff)\b",
     "simplest code that works"),
    ("cascade", r"\bcascade\b", "diagnose, plan, implement, verify"),
    ("save", r"\b(?:save (?:this|the session|to (?:the )?kb)|remember this)\b", "journal and KB write"),
    ("cleanup", r"\b(?:dead code|unused (?:code|files|modules)|archive (?:old|legacy|dead))\b", "confirm-gated archival"),
    ("pc-checkup", rf"\b(?:laptop|pc|computer|machine){_W}\b(?:slow|crash\w*|freez\w*|blue screen|bsod|overheat\w*)|\bpc checkup\b",
     "read-only health check"),
    ("onboard", r"\b(?:onboard(?:ing)?|set me up|fill in (?:my )?user\.md|who i am|my work identity)\b",
     "a short interview that fills in USER.md"),
    ("vdi-drive", r"\b(?:remote desktop|vdi|citrix|horizon client|virtual desktop|novnc|guacamole)\b",
     "needs the desktop owner's written authorisation and an authorisation note"),
]
USER_ONLY = {"cleanup", "pc-checkup", "vdi-drive", "onboard"}   # disable-model-invocation: mention, never start
MAX_HINTS = 3
_COMPILED = [(n, re.compile(rx, re.I), why) for n, rx, why in SKILLS]


def cmd(name):
    """The namespaced slash name the user (and the Skill tool) uses for a kit skill."""
    return f"/workbench-kb:{name}" if name == "save" else f"/workbench-core:{name}"


def skill_hints(prompt, skip=()):
    hints = []
    for name, rx, why in _COMPILED:
        if name in skip or not rx.search(prompt):
            continue
        hints.append(f"{cmd(name)} is user-invoked only: if it fits, tell the user they can run it ({why}); do not start it."
                     if name in USER_ONLY else f"{cmd(name)} ({why})")
        if len(hints) == MAX_HINTS:
            break
    return hints


def scanner():
    """True when SkillSpector is installed the way the skill-scan skill finds it."""
    exe = os.environ.get("SKILLSPECTOR_EXE") or shutil.which("skillspector")
    return bool(exe and os.path.exists(exe))


def main():
    d = _wb.read_event()
    ev = d.get("hook_event_name")
    if ev == "UserPromptSubmit":
        p = str(d.get("prompt") or "")
        notes = []
        if WRAPUP.search(p):
            notes.append("The user is wrapping up. Before you answer, run /workbench-kb:save so this session's knowledge "
                         "reaches the knowledge base; if work is still mid-flight, also write a resume note with "
                         "/workbench-core:handoff. Then answer.")
        build = bool(BUILD.search(p))
        if build:
            notes.append("This is build work: for a multi-file fix, build, refactor or migration, use "
                         "/workbench-core:cascade (diagnose, plan, implement, verify). A one-file or trivial change does "
                         "not need it.")
        hints = skill_hints(p, skip={"save", "handoff"} if notes else ({"cascade"} if build else ()))
        if hints:
            notes.append("Skills that fit this request (use them unless they clearly do not apply): " + "; ".join(hints) + ".")
        if notes:
            _wb.emit(ev, additionalContext="Auto-invoke: " + " ".join(notes))
    elif ev == "PreToolUse" and d.get("tool_name") in ("Bash", "PowerShell"):
        command = str((d.get("tool_input") or {}).get("command") or "")
        if not INSTALL.search(command):
            return
        if not scanner():
            _wb.emit(ev, permissionDecision="ask", permissionDecisionReason=(
                "Installing a plugin or skill, and no skill scanner (SkillSpector) is installed, so the source cannot be "
                "scanned first. Approve only if your organisation allows this source and you have read what it runs."))
        elif SCANNED not in command:
            _wb.emit(ev, permissionDecision="deny", permissionDecisionReason=(
                "Installing a plugin or skill: scan the source with /workbench-core:skill-scan first and show the user "
                f"the result. Then re-run the same command with `{SCANNED}` appended as a trailing comment; the user "
                "is still asked to confirm."))
        else:
            _wb.emit(ev, permissionDecision="ask", permissionDecisionReason=(
                "Installing a plugin or skill marked as scanned. The marker is not proof: approve only if you saw the "
                "skill-scan result pass and your organisation allows this source."))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
