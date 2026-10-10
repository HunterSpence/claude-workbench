"""Auto-invoke: nudge the kit's skills at the moments people forget them.
  UserPromptSubmit  wrap-up phrasing ("wrap up", "done for today", "new session", "handoff") -> run /workbench-kb:save
                    (and a handoff note if work is mid-flight); build intent (ponytail_auto.INTENT, one home) -> cascade;
                    otherwise SKILLS below: the first few skills whose trigger matches are named, with why.
                    User-invoked skills (USER_ONLY) are only mentioned, never started. A row for a skill the kit does not
                    ship (INSTALLED_ONLY) is named only when that skill exists on this machine.
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
    r"\b(?:(?:are )?we(?:'?re| are)? done\b(?:\W+\w+)?\s*(?:[?.!]|$)|that'?s (?:all|it) for (?:now|today|tonight)\b"
    r"|(?:i'?m |we'?re )?done for (?:today|the day|tonight|now)\b"
    r"|wrap(?:ping)? (?:it |this |things )?up\b|call it a (?:day|night)\b|signing off\b"
    r"|(?:start(?:ing)?|open(?:ing)?|move to|switch(?:ing)? to) (?:a )?(?:new|fresh) session\b"
    r"|i'?m (?:heading out|logging off|out for (?:now|today|the night))\b"
    r"|(?:write|make|do|need|want|create) (?:a |the |me a )?handoff\b|good ?night\b|hand (?:this|it) off\b)", re.I | re.M)
INSTALL = re.compile(
    r"claude\s+plugins?\s+(?:install|marketplace\s+add)\b|npx\s+(?:-y\s+)?skills?\s+add\b"
    r"|git\s+clone\b[^\n|;&]*(?:skills?|plugins?)\b|(?:cp|copy-item|robocopy|mv|move-item)\b[^\n|;&]*\.claude[\\/](?:skills|plugins)\b",
    re.I)
SCANNED = "# skill-scanned"
_W = r"[^.?!\n]{0,40}"   # same sentence, a few words apart

# (skill, trigger, what to do). Order = priority; at most MAX_HINTS are named per prompt.
SKILLS = [
    ("repo-review", rf"\b(?:read-?only|no[- ]clone|without cloning|review[- ]only|just review){_W}\b(?:repo|repository|codebase|code)\b"
                    rf"|\b(?:repo|repository|codebase)\b{_W}\b(?:read-?only|without cloning|no[- ]clone)\b|\b(?:repo|repository|codebase) review\b",
     "read-only review of a repository, no changes made"),
    ("repo-fix", rf"\b(?:fix|review|clean ?up|audit|look (?:over|at|through)|go through|harden){_W}\b(?:repo|repository|codebase)\b"
                 r"|github\.com/[\w.-]+/[\w.-]+|\bfix (?:the |all (?:the )?|these |our )?(?:failing|broken|red|flaky) "
                 r"(?:tests?|specs?|builds?|ci|checks?)\b", "clone to scratch, baseline, review, test-first fixes, PR.md"),
    ("ui-build", rf"\b(?:build|design|redesign|style|fix|polish|implement|make|create|change|update|improve){_W}"
                 r"\b(?:ui|ux|frontend|front-end|css|layout|responsive|dark mode|design system|component|page|screen|"
                 r"landing page|dashboard|form|navbar|modal)s?\b|\b(?:ui|ux|frontend|front-end) (?:work|change|bug|review)\b",
     "find the design system, run locally, screenshot 1440/390 light+dark, a11y check, before/after pairs"),
    ("brand-spec", r"\b(?:brand[- ](?:spec|interview|intake|guide(?:lines)?|identity|voice)|brand_spec|style guide for (?:a |the |our )?(?:new )?"
                        r"(?:product|brand|app)|what should (?:this|it|the \w+|our \w+) look(?: and |-and-| & )feel like"
                        r"|(?:new|this|our) (?:product|app)\b[^.?!\n]{0,40}\bno (?:brand|style) ?guide)\b",
     "one question at a time, then BRAND_SPEC.md with locked tokens"),
    ("draft-reply", rf"\b(?:reply|respond|response|answer|write back|get back){_W}\b(?:e-?mail|mail|message|thread|chat|him|her|"
                    r"them|this|team)\b|\bdraft (?:a |an |the |my )?(?:reply|response|e-?mail|message|answer)\b|\.(?:eml|msg)\b",
     "answer first, then asks with owners and dates; drafts only, never sends"),
    ("office-docx", rf"\b(?:word (?:doc|document|file)|docx|memo|write-?up)\b|\b(?:write|draft|make|create|build|format|turn)"
                    rf"{_W}\b(?:document|doc|report|memo|proposal|brief)\b", "outline or Markdown to .docx, then render and look"),
    ("office-pptx", r"\b(?:deck|slides?|power ?point|pptx|presentation)\b", "outline to .pptx on the template, then render and look"),
    ("office-xlsx", r"\b(?:excel|spreadsheet|xlsx|workbook|pivot table)\b", "live formulas, styles, recalc and error check"),
    ("office-render", r"\b(?:render|preview){_W}\b(?:deck|doc|document|pdf|workbook|slides?)\b|\bdoes (?:the|this|it) "
                      r"(?:deck|doc|document|slide) look\b".replace("{_W}", _W), "one PNG per page, read every one"),
    ("diagram", r"\b(?:diagrams?|flow ?charts?|mermaid|excalidraw|sequence chart|(?:architecture|system|data[- ]flow) (?:sketch|map|chart))\b",
     "English or Mermaid in; .mmd, .excalidraw, SVG and PNG out, rendered offline"),
    ("github", r"\b(?:pull requests?|PR ?#?\d+|github|gh cli|actions? runs?|workflow runs?|ci (?:is )?(?:red|failing|failed))\b",
     "gh CLI, Enterprise hosts included"),
    ("investigate", r"\b(?:debug|root cause|stack ?trace|traceback|flaky|regression|not working|it'?s broken)\b|\bwhy (?:is|does|did)"
                    rf"{_W}\b(?:fail|failing|broken|crash|slow|wrong|error)", "no fix before a proven root cause"),
    ("ratchet", r"\b(?:ratchet|(?:audit|review|harden) (?:it|this) in rounds|until (?:there are )?no new (?:findings|defects|bugs)"
                r"|fix (?:the |all (?:the )?|these )?(?:failing|broken|red|flaky) (?:tests?|specs?|checks?))\b",
     "rounds until two find nothing new"),
    ("deep-research", r"\b(?:deep research|research (?:thoroughly|in depth)|should we (?:adopt|use|switch to)|"
                      r"compare (?:the )?(?:vendors|tools|options|libraries)|evaluate (?:the )?(?:vendors|tools|options))\b",
     "many sources, adversarial check, decision list"),
    ("claude-api", r"\b(?:anthropic|claude[- ](?:api|sdk|models?|opus|sonnet|haiku)|(?:opus|sonnet|haiku)[- ]?\d|(?:model|token) (?:ids?|prices?|pricing|limits)"
                   r"|context window|prompt caching|batch api|build[- ]eval|hillclimb|(?:build|write|design|run) (?:an? |our |the )?evals?)\b",
     "model facts, pricing, evals: never from memory"),
    ("humanizer", rf"\b(?:humani[sz]e|de-?ai\b|ai[- ]sounding|(?:sounds?|reads?) (?:like (?:an? )?(?:ai|robot|chatgpt)|more (?:natural|human))"
                  rf"|(?:rewrite|edit|proofread|polish) (?:this|the|my) (?:text|prose|draft|post|bio|paragraph|article|essay|copy)"
                  rf"|before (?:finali[sz]ing|publishing){_W}\b(?:e-?mail|post|report|bio))\b",
     "rewrite so it reads like the writer, before a human reads it"),
    ("playwright-cli", r"\b(?:playwright|browser (?:automation|test(?:s|ing)?)|drive (?:a |the )?browser|(?:screenshot|screenshots? of|click through|smoke[- ]test) "
                       r"(?:this|the|that|our) (?:page|site|web ?site|flow|app))\b", "drive and screenshot a page in a real browser"),
    ("grilling", r"\b(?:grill me|stress[- ]test (?:my|the|this|our) (?:plan|idea|decision|design|approach)|poke holes|pressure[- ]test "
                 r"(?:my|the|this|our) (?:plan|idea|decision))\b", "stress-test a plan, one hard question at a time"),
    ("find", r"\b(?:search|find|look up){_W}\b(?:our|my|the team'?s|shared) (?:docs|documents|files|sharepoint|onedrive|"
             r"library)\b|\bwhat do (?:our|the) docs say\b|\blatest version of\b".replace("{_W}", _W),
     "local file catalog and search, cited answers"),
    ("plugin-factory", rf"\b(?:build|create|make|scaffold|write){_W}\b(?:a |an |my |new )?(?:claude )?(?:plugin|skill|marketplace)\b"
                       rf"|\bpackage (?:this|it|these|my|our) (?:skill|plugin|extension)s? for (?:the |my |our )?(?:team|colleagues|others|everyone)\b"
                       rf"|\bpackage{_W}\bas an? (?:claude )?(?:plugin|skill)\b",
     "scaffold a plugin or skill that passes the review rules"),
    ("plugin-review", rf"\b(?:review|audit|vet|check|assess){_W}\b(?:plugin|skill|marketplace|\.skill)s?\b",
     "check a plugin against the kit's rules"),
    ("app-navigator", r"\b(?:in-app (?:assistant|help)|navigation assistant|help (?:users|people) find (?:pages|features)|"
                      r"ask (?:and|then) (?:get )?(?:navigated|taken) to)\b", "add an ask-and-navigate assistant to a web app"),
    ("web-packager", rf"\b(?:package|bundle|port|convert){_W}\b(?:web ?app|website|static site|html app)\b|\bportable (?:web|html)\b"
                     r"|\bsingle[- ]file (?:web|html)\b|\bcan (?:web|browser|claude\.ai) users (?:use|run|open)\b"
                     rf"|\b(?:package|bundle|zip|upload){_W}\b(?:for|to|on) claude\.ai\b|\bclaude\.ai upload\b",
     "check and package a web app, skill or plugin for upload to claude.ai"),
    ("mcp-builder", rf"\b(?:build|create|write|make|scaffold){_W}\bmcp (?:server|tool)s?\b|\bmcp server (?:for|that|to)\b"
                    rf"|\b(?:build|create|write|make|scaffold|need|want)\b{_W}\ban? (?:mcp |claude )?connector for\b|\b(?:mcp|claude) connector\b",
     "build a small, tested MCP server"),
    ("api-bridge", rf"\b(?:wrap|bridge|expose|connect){_W}\b(?:rest |http |internal |openapi )?api\b{_W}\b(?:as |into |to )?(?:an? )?"
                   r"(?:mcp|tool|skill)\b|\bopenapi (?:spec|file)\b|\bapi bridge\b"
                   r"|\blet (?:claude|the agent|the model|ai) use (?:this|our|the|that) (?:rest |http |internal |openapi )?api\b"
                   r"(?!\s*(?:keys?|tokens?|secrets?|calls?|version))",
     "turn an HTTP API into a tool the agent can call"),
    ("setup", r"\bworkbench setup\b|\b(?:run|start|resume|finish|continue)(?: the)? (?:kit|workbench) setup\b|\bsetup\.py\b|\bsetup (?:status|doctor)\b",
     "guided install, probe and verification of the kit"),
    ("capture", rf"\b(?:capture|harvest|crawl|scrape){_W}\b(?:intranet|sharepoint|onedrive|shared files|wiki)\b",
     "read-only, paced capture of pages and shared files into the knowledge layer"),
    ("ingest", rf"\b(?:ingest|import|index){_W}\b(?:meetings?|transcripts?|mail|e-?mails?|outlook|inbox)\b|\bmeeting transcripts?\b",
     "bring meeting transcripts and mail into the knowledge layer"),
    ("ctx-agent-history-search", r"\b(?:what did we (?:do|decide|try)|last session|previous session|earlier session|which session|"
                                 r"agent history|past transcripts?)\b", "search earlier sessions before redoing work"),
    ("spawn", r"\b(?:subagents?|spawn|delegate|in parallel|fan[- ]out)\b", "pick the persona, write a self-contained prompt"),
    ("batch-review", r"\b(?:batch (?:api|review)|bulk (?:review|grade|judge|score)|(?:grade|score|judge) (?:all|every|these))\b",
     "non-interactive passes at batch price"),
    ("brain-audit", r"\b(?:kb health|(?:check|audit) (?:the )?(?:kb|knowledge base|config|setup) for problems)\b",
     "read-only health check, ranked fix list"),
    ("skill-scan", r"\b(?:scan (?:a|this) (?:skill|plugin) before (?:installing|trusting)|skillspector)\b",
     "scan before trusting third-party skill code"),
    ("mcp-heal", rf"\bmcp{_W}\b(?:broken|down|failed|failing|not (?:working|connecting|loading)|heal|check)\b|\bfailed to connect\b"
                 rf"|\bmcp (?:tools?|servers?)\b{_W}\b(?:missing|gone|disappeared|not (?:showing|available|found))\b"
                 rf"|\b(?:check|probe|test|verify|heal){_W}\bmcp servers?\b",
     "probe every server, report OK/DEGRADED/DOWN"),
    ("linux-service-triage", r"\b(?:systemd|systemctl|journalctl|nginx|pm2|50[23] (?:error|bad gateway)|server (?:is )?down|"
                             r"service (?:is )?(?:down|failing|crashing)|container (?:keeps )?(?:crash|restart)\w*)\b",
     "evidence first, minimal fix, rollback"),
    ("handoff", r"\b(?:resume note|usage limit|out of (?:context|tokens)|session (?:is )?(?:running out|almost full))\b",
     "self-contained handoff or resume note"),
    ("ponytail", r"\b(?:ponytail|over-?engineer(?:ed|ing)?|simplify (?:this|it)|too much code|smallest diff)\b",
     "simplest code that works"),
    ("cascade", r"\bcascade\b", "diagnose, plan, implement, verify"),
    ("save", r"\b(?:save (?:this|the session|to (?:the )?kb)|remember this)\b", "journal and KB write"),
    ("cleanup", r"\b(?:dead code|unused (?:code|files|modules)|archive (?:old|legacy|dead))\b", "confirm-gated archival"),
    ("pc-checkup", rf"\b(?:laptop|pc|computer|machine){_W}\b(?:slow|crash\w*|freez\w*|blue screen|bsod|overheat\w*)|\bpc checkup\b",
     "read-only health check"),
    ("onboard", r"\b(?:onboard(?:ing)?|set me up|fill in (?:my )?user\.md|who i am|my work identity)\b",
     "a short interview that fills in USER.md"),
    ("kit-update", r"\b(?:check (?:for )?(?:the )?new stuff|(?:update|upgrade) the (?:workbench )?kit|check for kit updates|"
                   r"(?:turn|switch) (?:off|on) (?:the |all )?(?:bash |command )?approvals|"
                   r"(?:turn|set) (?:the )?(?:workbench )?guard (?:way )?(?:down|to minimal)|minimal guard)\b",
     "updates the kit from its latest release and verifies it after the restart, or sets fewer prompts (approvals, guard level)"),
    ("vdi-drive", r"\b(?:remote desktop|vdi|citrix|horizon client|virtual desktop|novnc|guacamole)\b",
     "needs the desktop owner's written authorisation and an authorisation note"),
]
EXTERNAL = {"claude-api", "humanizer", "playwright-cli", "grilling"}   # not kit skills: the bare /name, no plugin prefix
INSTALLED_ONLY = {"humanizer", "playwright-cli", "grilling"}          # named only when the skill is on this machine
# disable-model-invocation: true (the model cannot start them): mention, never start. The first seven are typed on demand;
# the nine after them are authoring and admin skills, hidden from the model to keep the skill listing short.
USER_ONLY = {"cleanup", "pc-checkup", "vdi-drive", "onboard", "setup", "capture", "ingest",
             "batch-review", "mcp-heal", "plugin-factory", "plugin-review", "web-packager", "mcp-builder", "api-bridge",
             "app-navigator", "brand-spec"}
MAX_HINTS = 3
_COMPILED = [(n, re.compile(rx, re.I), why) for n, rx, why in SKILLS]


def cmd(name):
    """The namespaced slash name the user (and the Skill tool) uses for a kit skill."""
    return f"/{name}" if name in EXTERNAL else f"/workbench-kb:{name}" if name == "save" else f"/workbench-capture:{name}" if name in ("capture", "ingest") \
        else f"/workbench-core:{name}"


def _dirs(path):
    try:
        with os.scandir(path) as it:
            return [e.path for e in it if e.is_dir()]
    except OSError:
        return []


def installed(name):
    """True when skill `name` is on this machine: <config dir>/skills/<name>/SKILL.md, or a plugin-cache copy
    (<config dir>/plugins/cache/<marketplace>/<plugin>/<version>/skills/<name>/SKILL.md). One scandir per level, no
    recursion; it runs only for a row whose trigger already matched."""
    home = _wb.claude_home()
    if os.path.isfile(home / "skills" / name / "SKILL.md"):
        return True
    return any(os.path.isfile(os.path.join(v, "skills", name, "SKILL.md"))     # temp_*: half-finished clones, not installs
               for m in _dirs(home / "plugins" / "cache") if not os.path.basename(m).startswith("temp_")
               for p in _dirs(m) for v in _dirs(p))


def skill_hints(prompt, skip=()):
    hints = []
    for name, rx, why in _COMPILED:
        if name in skip or not rx.search(prompt) or (name in INSTALLED_ONLY and not installed(name)):
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
