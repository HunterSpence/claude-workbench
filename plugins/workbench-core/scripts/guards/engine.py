#!/usr/bin/env python3
"""PreToolUse guard engine: one shell parse, two rule packs, fail-open.

Contract (pretooluse.py is the hook entry point):
  - stdin: the PreToolUse JSON. stdout: nothing (no opinion: the normal permission flow decides), or ONE
    hookSpecificOutput object whose permissionDecision is "deny" or "ask". This engine never answers "allow" and
    never rewrites a tool's input: an allow skips the prompt for a call no rule covers (deny and ask rules still
    apply), which a guard must never grant, and a rewritten input would be judged by those rules in its new form. A fixable call is denied with the exact command to re-run.
  - Exit code is always 0. Fail open: a crash anywhere says nothing and logs an ERROR line. One exception: past
    the nesting / size caps a command cannot be judged in bounded time, so it is denied (guard id nest-cap).
  - Every shell rule judges ONE parse of the command (lex()): heredocs and what runs them, statements, runner
    strings (ssh '...', bash -c "...", pwsh -c "..."), with quoted prose blanked (blank_prose()), so a commit message
    that MENTIONS `git push --force` is prose, not a push.
  - Rule packs: rulepacks/generic.py and rulepacks/corporate.py, each with optional tuples SHELL (Bash/PowerShell),
    WRITE (Edit/Write/MultiEdit/NotebookEdit), READ (Read/Grep/Glob) and TOOL (WebFetch/Agent) of functions f(c).
    Each rule is its own unit: a crash in one skips only that rule. A deny stops at once; an "ask" is collected
    and returned only when no rule denies (deny outranks ask).
  - No log-only mode and no switches the agent could reach: the packs are fixed, and the guards' own configuration
    (the workbench home, the corporate allowlist, the plugin folders, every .claude/settings*.json) is
    write-protected here, whatever pack is loaded. A rule that misfires is turned off by disabling the plugin.
  - Log: <claude config dir>/workbench/logs/guards.log (GUARDS_LOG_DIR overrides), credential shapes redacted,
    rotated at 1 MB. Every BLOCK and ASK names its guard id.
"""
import bisect
import datetime
import glob
import importlib
import itertools
import json
import os
import re
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))   # scripts/ (for _wb and secretscan)
import _wb  # noqa: E402


class _Lazy:
    """shlex / shutil / subprocess / tempfile load on first use (they cost milliseconds on every hook run)."""
    def __init__(self, name):
        self._name = name

    def __getattr__(self, a):
        return getattr(__import__(self._name), a)


shlex, shutil, subprocess, tempfile = map(_Lazy, ("shlex", "shutil", "subprocess", "tempfile"))


def _tmpdir():
    d = next((os.environ[k] for k in ("TMPDIR", "TEMP", "TMP") if os.environ.get(k)), None)
    return os.path.abspath(d) if d else tempfile.gettempdir()


BASH_N_TIMEOUT = 5         # seconds per `bash -n` call; the hook timeout in hooks.json is 30 s
PACKS = ("generic", "corporate")
LOG_MAX_BYTES = 1_048_576

# ── decisions and logging ────────────────────────────────────────────────────────────────────────────────────
CTX = {"sid": "-", "tool": "-", "cwd": "-", "level": "standard"}
_ASKS = []

# ── guard level (H7) ─────────────────────────────────────────────────────────────────────────────────────────
# `guard_level` in <workbench home>/corporate-allowlist.json (the file the corporate pack reads its "enabled" from):
#   standard  the default, also when the file or the key is missing, or the key holds another value
#   strict    every rule below refuses, as 0.3.1 did; also when the file exists but cannot be read or parsed, or is not a JSON
#             object (fail closed, logged), and when CLAUDE_CONFIG_DIR differs from the installed one
# Under standard only the rules in SOFT_RULES ask instead of refusing, and browser-cli plain navigation passes (logged). Every
# other deny stays a deny at both levels: the list is short on purpose, and a rule joins it only with a test that names it.
LEVELS = ("standard", "strict")
SOFT_RULES = frozenset({"remote-not-allowlisted", "upload-not-allowlisted", "no-verify"})
SOFT_LEAD = "Standard guard level: this asks instead of refusing (the strict level refuses it). "


def guard_level():
    """"standard" or "strict". A missing file, a missing key and any other value of the key give "standard". A file that exists but
    cannot be read or parsed, or holds something other than a JSON object, gives "strict" (logged): a damaged file must not quieten
    the guard. So does a CLAUDE_CONFIG_DIR that differs from the installed one (the corporate pack fails closed there too)."""
    try:
        if _wb.config_redirected():
            return "strict"
        with open(_wb.workbench_home() / "corporate-allowlist.json", encoding="utf-8-sig") as f:
            conf = json.load(f)
    except (FileNotFoundError, NotADirectoryError):
        return "standard"
    except (OSError, ValueError) as e:
        log(f"ERROR corporate-allowlist.json exists but cannot be read ({type(e).__name__}): guard level strict")
        return "strict"
    if not isinstance(conf, dict):
        log("ERROR corporate-allowlist.json is not a JSON object: guard level strict")
        return "strict"
    v = conf.get("guard_level")
    if v is None:
        return "standard"
    if isinstance(v, str) and v.strip().lower() in LEVELS:
        return v.strip().lower()
    log(f"ERROR guard_level {str(v)[:40]!r} is not standard or strict: using standard")
    return "standard"


class _Soft(BaseException):
    """A SOFT_RULES rule found something: it asked instead of refusing, and the rule stops here. A BaseException, like Decision."""


class Decision(BaseException):
    """Raised by block(). A BaseException, so no rule's fail-open `except Exception` swallows it."""
    def __init__(self, out):
        super().__init__("decision")
        self.out = out


REDACT_FAILED = "[log text withheld: the credential scanner could not load]"


def _redact(text):
    try:
        return _wb.redact(text)
    except Exception:
        return REDACT_FAILED   # never the raw text: it may hold the credential this step exists to hide


def log(msg):
    try:
        d = os.environ.get("GUARDS_LOG_DIR") or str(_wb.log_dir())
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "guards.log")
        if os.path.exists(p) and os.path.getsize(p) > LOG_MAX_BYTES:
            os.replace(p, p + ".1")   # keep one previous file
        with open(p, "a", encoding="utf-8") as f:
            f.write(datetime.datetime.now().isoformat(timespec="seconds") + " " +
                    _redact(f"sid={CTX['sid']} tool={CTX['tool']} cwd={CTX['cwd']} level={CTX['level']} "
                            f"{' '.join(str(msg).split())}") + "\n")
    except Exception:
        pass


def _out(decision, reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                   "permissionDecisionReason": reason}}


def block(reason, gid, detail=""):
    """Deny the call now (a SOFT_RULES rule at the standard level asks instead and ends its own run)."""
    if gid in SOFT_RULES and CTX["level"] == "standard":
        log(f"ASK [{gid}] (relaxed from deny at the standard level) {(detail + ' | ' if detail else '')}{reason}"[:600])
        _ASKS.append(f"[workbench guard: {gid}] {SOFT_LEAD}{reason}")
        raise _Soft()
    log(f"BLOCK [{gid}] {(detail + ' | ' if detail else '')}{reason}"[:600])
    raise Decision(_out("deny", f"[workbench guard: {gid}] {reason}"))


def relaxed(gid, detail=""):
    """Log a call a rule would have asked about at the strict level and lets through at the standard one."""
    log(f"PASS [{gid}] (relaxed from ask at the standard level) {detail}"[:600])


def ask(reason, gid, detail=""):
    """Ask the user to confirm. Collected: it is returned only if no rule denies the call."""
    msg = f"[workbench guard: {gid}] {reason}"
    if msg in _ASKS:   # the same ask again (a statement repeated thousands of times): said and logged once
        return
    log(f"ASK [{gid}] {(detail + ' | ' if detail else '')}{reason}"[:600])
    _ASKS.append(msg)


def _win_forms(p):
    """p plus the file Windows really opens: a trailing $VAR (empty when unset), an NTFS stream suffix (x::$DATA,
    x:s) and trailing dots/spaces dropped. Judged alongside p, so it only adds denies."""
    c = re.sub(r"(?:\$\{[^}]*\}|\$\w+)+$", "", p)
    c = re.sub(r"(?<=[^/\\:]):[^/\\]*$", "", c)
    return {p, re.sub(r"[\s.]+$", "", c)} - {""}


# ── the lexer: ONE parse per command. lex(cmd, ps) -> Lex; every shell rule judges a view of it:
#   L.hd          heredocs, each with what RUNS its body (decided from the opener pipeline, or from a later
#                 statement that executes the file the heredoc writes);
#   L.text(drop)  the command minus the bodies drop(h) selects; L.top drops them all; L.bodies = shell-run bodies;
#   _walk(text)   statements split on unquoted ; & | && || newline, top-level indices, the substitutions bash runs;
#   blank_prose() quoted prose blanked; the strings a runner executes (ssh '...', bash -c "...") returned for re-lexing.
_HD_OPEN = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_]\w*)\1")
_SHELLS = r"(?:ba|z|da|k|c|tc|fi)?sh|pwsh|powershell|wsl|cmd"
_INTERP = r"python[\d.]*|py|node|nodejs|deno|bun|perl|ruby|php"
_PIPE_WRAP = (r"\|&?\s*[({]?\s*(?:(?:[^\s|;&]*/)?(?:sudo|doas|env|timeout|nice|ionice|nohup|command|exec|stdbuf|time|"
              r"setsid|xargs|busybox|chrt|taskset|unbuffer)(?:\s+[^\s|;&]+)*?\s+)?(?:[^\s|;&]*[/\\])?")
_TO_RUN = re.compile(r"(?i)" + _PIPE_WRAP + r"(?P<w>ssh|eval|source|iex|invoke-expression|" + _SHELLS + "|" + _INTERP +
                     r")(?:\.exe)?(?![^\s|;&)])")
_SUBST_RUN = re.compile(r"""(?i)(?<![\w.-])(?P<w>ssh|eval|source|\.|""" + _SHELLS + "|" + _INTERP + r""")(?:\.exe)?"""
                        r"""(?:\s+[^\s<$"'`|;&]+)*\s+(?:<\s*)?(?:["']?\$\(|<\()\s*(?:cat|tee)(?![\w.-])[^()]*$""")
_CAT_TEE = re.compile(r"(?<![\w.-])(?:cat|tee)(?![\w.-])")
_DATA_CONSUMER = re.compile(r"(?i)(?<![\w.-])(python[\d.]*|py|node|deno|psql|mysql|sqlite3|cat|tee|jq|awk|"
                            r"perl|ruby|php|git)(?![\w.-])")
_CODE_HEAD = re.compile(r"(?i)(?<![\w.-])(?:" + _INTERP + r")(?:\.exe)?(?![\w.-])")
_EXEC_HEAD = re.compile(r"(?i)(?:" + _SHELLS + r"|ssh|source|\.|eval|" + _INTERP + r")$")
_RUNNER = re.compile(r"(?i)(?<![\w.$-])(ssh|bash|sh|zsh|dash|ksh|eval|su|pwsh|powershell|cmd|wsl|iex|"
                     r"invoke-expression)(?:\.exe)?(?![\w.-])")
_JOINER = re.compile(r"(?i)(?<![\w.$-])(ssh|wsl|eval|pwsh|powershell|cmd)(?:\.exe)?(?![\w.-])")  # re-parse ALL their args
_SSH_WORD = re.compile(r"(?i)(?<![\w.$-])ssh(?![\w.-])")   # a $ssh variable is no runner word
_VAR_HEAD = re.compile(r"""["']?(\$\{?\w+\}?)["']?(?=\s)(?!\s*=)""")   # `$RUN '...'`: a command held in a variable
_GIT_HOOK_NAME = (r"(?:pre-[\w-]+|post-[\w-]+|prepare-commit-msg|commit-msg|update|applypatch-msg|proc-receive|"
                  r"reference-transaction|push-to-checkout|sendemail-validate|fsmonitor-watchman|p4-[\w-]+)$")
_GIT_HOOK = re.compile(r"(?i)(?:^|[/\\])hooks[/\\]" + _GIT_HOOK_NAME)
_FS_WTGT = r"""(?:(?<![\d&<>])>>?|\btee\s+(?:-a\s+)?)\s*["']?([^\s"';&|<>()]+)"""   # a file the statement writes
_FS_PARSE_ONLY = re.compile(r"^\s*(?:ba|z|da)?sh\s+-n\b")
_HEAD_SKIP = re.compile(r"""^\s*[({!]*\s*(?:(?:\w+=(?:"[^"]*"|'[^']*'|\S*)\s*)|(?:sudo|time|nohup|exec|command|env|"""
                        r"""then|do|else|elif|if|while|until)\s+|timeout\s+(?:-\S+\s+)*\S+\s+)*""")
_LEXED, _WALKED, _PROSED, _LEX_NEST = {}, {}, {}, [0]
# Work limits for one evaluate(). _MEMO holds the answers of the file system lookups that repeat once per target (norm, _as_written,
# _kit_anchors): outside evaluate() it is None and nothing is remembered, so a direct call always looks at the disk. _WORK counts the
# characters a loop that is quadratic in the worst case has re-read; past _WORK_MAX the command cannot be judged in bounded time and
# is denied (nest-cap). _MAX_TARGETS is the same for the paths a command deletes, moves, links or writes.
_MEMO, _WORK = [None], [0]
_WORK_MAX, _MAX_TARGETS = 2_000_000, 2000


def _memo(fn):
    def wrapper(*a):
        m = _MEMO[0]
        if m is None:
            return fn(*a)
        k = (fn.__name__, a)
        if k not in m:
            m[k] = fn(*a)
        return m[k]
    wrapper.__name__, wrapper.__doc__ = fn.__name__, fn.__doc__
    return wrapper


def _work(n):
    """Count n characters of rescanning against the command's budget."""
    _WORK[0] += n
    if _WORK[0] > _WORK_MAX:
        raise _TooDeep("more than %d characters rescanned" % _WORK_MAX)
# Past this nesting (quotes / $( ) per walk, heredoc and runner-string re-lex levels), length or heredoc count the
# guard cannot judge a command in bounded time or stack, so it DENIES. Real commands sit far below these limits.
_MAX_NEST, _MAX_CMD, _MAX_HD = 32, 256_000, 64
DEEP_MSG = ("This command is too large or too deeply nested for the guard to judge (limits: %d nesting levels of quotes "
            "/ $( ) / heredocs / runner strings, %d KB, %d heredocs). Flatten it: write the script with the Write tool "
            "and run the file." % (_MAX_NEST, _MAX_CMD // 1000, _MAX_HD))


_RUN_MIN, _RUN_KEEP = 2000, 256


def squash_runs(s):
    """s with every run of 2,000 or more of one character cut to 256 of them (plus its length mod 4, which keeps a base64 payload's
    alignment). No rule reads the length of such a run (base64 of zero-filled data, a filler of spaces or ; or A), and a regex
    that backtracks over one is quadratic in it. A run of anything else (a repeated word) is not touched."""
    if len(s) < _RUN_MIN:
        return s
    out = []
    for ch, grp in itertools.groupby(s):
        n = sum(1 for _ in grp)
        out.append(ch * (_RUN_KEEP + n % 4 if n >= _RUN_MIN else n))
    return "".join(out)


class _TooDeep(BaseException):
    """Raised past _MAX_NEST and turned into a deny. A BaseException, so a rule's `except Exception` cannot
    swallow it (a RecursionError swallowed there would let the call through unjudged)."""


def _deeper(depth):
    if depth >= _MAX_NEST:
        raise _TooDeep(depth)
    return depth + 1


def _fs_wtargets(text):
    """Files a statement writes (> / >> / tee). A `>` that closes an HTML tag is markup."""
    return [m.group(1) for m in re.finditer(_FS_WTGT, text)
            if not (m.group(0).startswith(">") and re.search(r"<[A-Za-z/][^<>\s]*$", text[:m.start()]))]


def _head(seg):
    """The command word of a statement past ( { !, keywords, VAR=... and sudo / time / nohup / exec / command / env /
    timeout N: basename, lower case, .exe dropped."""
    m = re.match(r"""["'&\s]*([^\s"']+)""", _HEAD_SKIP.sub("", seg, 1))
    return os.path.basename(m.group(1)).lower().removesuffix(".exe") if m else ""


class _H:
    """One heredoc: term, quoted, line (opener line), head (the command that opened it), a / b (body = lines a..b-1,
    b = terminator line, None = unterminated), run ('sh' | 'ssh' | 'code' | None = nothing here runs it), cat (cat or
    tee opened it), py ('fed' | 'written' | None), writes (files its opener line writes), body."""
    __slots__ = ("term", "quoted", "line", "head", "a", "b", "run", "cat", "py", "writes", "body")


class Lex:
    """One parse of a shell command (see lex())."""
    def __init__(self, cmd, ps=False):
        self.cmd, self.ps, self.hd, self.lines, self._top = cmd, ps, [], cmd.split("\n"), None
        pend, st, need = [], None, not ps and "<<" in cmd     # PowerShell has no heredoc: a `<<` there is text
        for i, ln in enumerate(self.lines):
            if pend:
                if ln.strip() == pend[0].term:
                    pend.pop(0).b = i
                    if pend:
                        pend[0].a = i + 1
                continue
            if not need:
                continue
            # An opener counts only where bash sees one: the command lines are walked in order, so `cat '<<EOF'`,
            # `ls # <<EOF`, `\<<EOF` and `$((a<<b))` hide no line after them.
            ms = list(_HD_OPEN.finditer(ln)) if "<<" in ln else []
            probe = {m.start(): None for m in ms}
            st = _walk1(ln, ps, st0=st, probe=probe).st
            for m in ms:
                if probe[m.start()] in ("sh", "(") and not re.search(r"\(\((?:(?!\)\)).)*$", ln[:m.start()]):
                    if len(self.hd) >= _MAX_HD:
                        raise _TooDeep("%d+ heredocs" % (len(self.hd) + 1))
                    pend.append(self._opener(ln, m, i))
        if len(self.hd) > _MAX_HD:
            raise _TooDeep("%d heredocs" % len(self.hd))
        for h in self.hd:
            h.body = "\n".join(self.lines[h.a:h.b])
        if any(h.cat and h.run is None and h.writes for h in self.hd):
            v = _shell_vars(cmd)
            segs = [(s, {os.path.basename(f) for f in _fs_wtargets(s)} if "<<" in s else set(), _head(s))
                    for s in _walk(self.text(lambda h: h.run is None), ps).segs if s.strip()]
            segs = [(s, own, _head(v.get(hd.strip("${}"), "sh")) if hd.startswith("$") else hd) for s, own, hd in segs]
            for h in self.hd:
                if h.cat and h.run is None and h.writes:
                    h.run = _ran(h.writes, segs, cmd)

    def _opener(self, ln, m, i):
        h, pre, post = _H(), ln[:m.start()], ln[m.end():]
        h.term, h.quoted, h.line, h.a, h.b = m.group(2), bool(m.group(1)), i, i + 1, None
        h.head = re.split(r"[;|(]|(?<![<>])&(?!>)", pre)[-1]     # `2>&1` is a redirect
        h.cat = bool(_CAT_TEE.search(h.head))
        h.writes = [f.strip("\"'") for f in _fs_wtargets(ln) if not f.startswith("/dev/")]
        w = ""
        if h.cat:      # a cat / tee body is data unless the opener pipeline hands it to a runner
            r = _TO_RUN.search(post) or _SUBST_RUN.search(pre)
            w = r.group("w").lower() if r else ""
            h.run = w and ("ssh" if w == "ssh" else "code" if re.fullmatch(_INTERP, w) else "sh") or None
        elif _DATA_CONSUMER.search(h.head):
            h.run = "code" if _CODE_HEAD.search(h.head) else None
        else:
            h.run = "ssh" if _SSH_WORD.search(h.head) else "sh"
        h.py = ("fed" if re.search(r"\bpython[\d.]*(\.exe)?\b[^|;&]*$", pre) or w.startswith("py") else
                "written" if re.search(r">\s*[\"']?[^\s;&|]+\.py[\"']?\s*$", pre) or
                any(f.endswith(".py") for f in h.writes) else None)
        self.hd.append(h)
        return h

    def text(self, drop, depth=0):
        """The command minus the bodies (and terminators) of the heredocs drop(h) selects; a kept shell body is lexed
        too, so a doc nested in `ssh h bash -s <<'E'` drops with the rest. An unterminated body always stays. A dropped
        UNQUOTED body leaves its $( ... ) and `...` behind, one per line: the shell runs them while it expands the body."""
        out, at, i = [], {h.a: h for h in self.hd if h.b is not None}, 0
        if at:
            depth = _deeper(depth)
        while i < len(self.lines):
            h = at.get(i)
            if h is None:
                out.append(self.lines[i])
                i += 1
                continue
            if not drop(h):
                if h.b > h.a:
                    out.append(lex(h.body, self.ps).text(drop, depth) if h.run in ("sh", "ssh") else h.body)
                out.append(self.lines[h.b])
            elif not h.quoted and ("$(" in h.body or "`" in h.body):
                out += ["$(%s)" % b if k == "$(" else "`%s`" % b for k, b in _walk(h.body, self.ps, True).subs]
            i = h.b + 1
        return "\n".join(out)

    @property
    def top(self):
        if self._top is None:
            self._top = self.text(lambda h: True)
        return self._top

    @property
    def bodies(self):
        """[(body, remote?)] of the terminated heredocs a shell runs."""
        return [(h.body, h.run == "ssh") for h in self.hd if h.b is not None and h.run in ("sh", "ssh")]

    def shell_view(self):
        """The text a shell runs: data bodies out (their substitutions stay), shell-run bodies inline."""
        return self.text(lambda h: h.run not in ("sh", "ssh"))

    def shell_texts(self):
        """[(text, remote?)]: the top text and the shell view of each heredoc body a shell runs."""
        return [(self.top, False)] + [(lex(b, self.ps).shell_view(), r) for b, r in self.bodies]


def lex(cmd, ps=False):
    """THE parse of a shell command, once per (text, shell)."""
    L = _LEXED.get((cmd, ps))
    if L is None:   # Lex() lexes a kept body while it is built, so building nests: cap it
        _LEX_NEST[0] = _deeper(_LEX_NEST[0])
        try:
            L = _LEXED[(cmd, ps)] = Lex(cmd, ps)
        finally:
            _LEX_NEST[0] -= 1
    return L


def _doc(h):
    """A cat / tee heredoc body nothing in this command runs: file content, not shell."""
    return h.cat and not h.run


_INERT = {"git", "grep", "egrep", "fgrep", "rg", "cat", "head", "tail", "less", "more", "wc", "ls", "diff", "file",
          "stat", "md5sum", "sha256sum", "echo", "printf", "gh", "findstr", "select-string", "get-content", "type",
          "test", "[", "sed", "sort", "uniq", "cut", "tr", "basename", "dirname", "realpath", "readlink", "which"}


def _inert(seg):
    """A statement that only reads / prints / searches (no redirect, no substitution, no git that runs a shell
    string, no sed -i)."""
    h = _head(seg)
    if h not in _INERT or (h == "sed" and re.search(r"\s-\w*i\b|--in-place", seg)) or \
            (h == "rg" and re.search(r"\s--pre(?:-glob)?(?:=|\s|$)", seg)) or \
            (h == "git" and re.search(r"\s(?:-x|--exec(?:=|\s)|foreach|filter-branch|bisect\s+run)", seg)):
        return False
    return not re.search(r"\$\(|`", seg) and not re.search(r"(?<![<>=&\d-])>>?", seg)


def _ran(writes, segs, cmd):   # segs: [(statement, files it writes by heredoc, head with a $VAR head resolved)]
    """What runs a file this command writes: git, for a hook; a later statement that executes it (`bash x.txt`,
    `python x.py`, `pwsh -File x.ps1`, `./x`, `sh < x`, anything over ssh); or, for a shell script (.sh / .bash /
    no extension), any live statement naming it but `bash -n` and the one writing it."""
    names = {os.path.basename(f) for f in writes}
    hp = re.search(r"(?i)hookspath", cmd)
    if any(_GIT_HOOK.search(f) or (hp and re.match(r"(?i)" + _GIT_HOOK_NAME, os.path.basename(f))) for f in writes) \
            and any(hd == "git" for _, _, hd in segs):
        return "sh"
    for s, own, hd in segs:
        for n in names - own:
            if n not in s or _FS_PARSE_ONLY.match(s):
                continue
            arg = r"""["']?(?:[^\s"']*[/\\])?""" + re.escape(n) + r"""["']?(?:\s|$)"""
            rest = _HEAD_SKIP.sub("", s, 1).split(None, 1)[1:] or [""]
            if hd == n.lower() or hd == "ssh" or _EXEC_HEAD.match(hd) and (
                    re.match(r"(?:(?:-\S+)(?:\s+(?!-)\S+)?\s+)*?" + arg, rest[0]) or re.search(r"<\s*" + arg, s)):
                return "code" if re.fullmatch(_INTERP, hd) else "ssh" if hd == "ssh" else "sh"
            if re.search(r"(?i)\.(?:sh|bash)$|^[^.]+$", n) and not _inert(s):
                return "sh"
        for n in names - own:          # `cat > rows.py ...; python main.py rows` imports it
            if n.endswith(".py") and re.fullmatch(_INTERP, hd) and \
                    re.search(r"(?<![\w.-])" + re.escape(n[:-3]) + r"(?![\w-])", s):
                return "code"
    return None


class _Walk:
    __slots__ = ("segs", "bounds", "top", "subs", "spans", "tsubs", "notes", "st", "starts")


def _walk(s, ps=False, hd=False):
    w = _WALKED.get((s, ps, hd))
    if w is None:
        w = _WALKED[(s, ps, hd)] = _walk1(s, ps, hd=hd)
    return w


def _walk1(s, ps=False, first=False, hd=False, st0=None, probe=None):
    """Shell quoting in one pass (ps: PowerShell). .segs / .bounds: statements split on ; & | && || |& newline outside
    quotes, comments and substitutions (`2>&1`, `&>`, `>&` are redirects); .top: a bytearray mask, 1 where an index is
    outside every quote, comment and substitution; .subs: [(kind, body)] of the DIRECT $( ... ) and `...` children the
    shell RUNS (_subs() for every level); .spans: [(start, end, statement start)] of each top-level quoted string
    ($'...' and $"..." from the $); .tsubs / .notes: top-level $( ... ) bodies and comments. '...' and $'...' are literal,
    "..." keeps $( ) and backticks live, a word-initial # comments out the line, \\ (PowerShell `) escapes.
    hd: an unquoted heredoc body, where a top-level quote or # is a plain character. st0 / .st: the quote stack to start
    from / at the end (Lex walks a command line by line); probe {pos: None}: filled with the innermost frame at each pos.
    ponytail: `case x in a)` inside $( ) closes it early; ${ ... } nesting is not modelled."""
    w = _Walk()
    root = ["sh", 0, 0]
    esc, st, seg0, cut, i, n = "`" if ps else "\\", st0 or [root], 0, None, 0, len(s)
    np = sum(f[0] == "(" for f in st)                                    # open $( frames
    w.segs, w.bounds, w.top, w.subs, w.spans, w.tsubs, w.notes = [], [], bytearray(n), [], [], [], []
    w.st = st
    while i < n:
        c, k = s[i], st[-1][0]
        if probe is not None and i in probe:
            probe[i] = k
        if len(st) == 1:
            w.top[i] = 1
        if k in ("'", "$'"):
            if c == "\\" and k == "$'":
                i += 2
                continue
            if c == "'":
                f = st.pop()
                if len(st) == 1:
                    w.spans.append((f[2], i + 1, seg0))
        elif c == esc:
            i += 2
            continue
        elif c == "`" and not ps:
            j = i + 1
            while j < n and s[j] != "`":
                j += 2 if s[j] == "\\" else 1
            if not np:
                w.subs.append(("`", s[i + 1:j]))
            i = j + 1
            continue
        elif s.startswith("$(", i):
            _deeper(len(st))
            st.append(["(", 0, i + 2])
            np += 1
            i += 2
            continue
        elif k == '"':
            if c == '"':
                f = st.pop()
                if len(st) == 1:
                    w.spans.append((f[2], i + 1, seg0))
        elif c in "\"'" and not (hd and len(st) == 1):
            _deeper(len(st))   # a $'...' / $"..." span starts at its $
            d = not ps and s[i - 1:i] == "$"
            st.append(["$'" if c == "'" and d else c, 0, i - d])
        elif c == "#" and (i == 0 or s[i - 1] in " \t\n;&|()<>") and not (hd and len(st) == 1):
            j = s.find("\n", i)
            j = n if j < 0 else j
            if len(st) == 1:
                w.notes.append((i, j))
                cut = i if cut is None else cut
            i = j
            continue
        elif k == "(":
            if c == "(":
                st[-1][1] += 1
            elif c == ")":
                if st[-1][1]:
                    st[-1][1] -= 1
                else:
                    f, np = st.pop(), np - 1
                    if not np:
                        w.subs.append(("$(", s[f[2]:i]))
                    if len(st) == 1:
                        w.tsubs.append((f[2], i))
        elif c in ";|&\n" and not (c == "&" and ((i and s[i - 1] in "<>") or s[i + 1:i + 2] == ">")):
            w.segs.append(s[seg0:i if cut is None else cut])
            w.bounds.append((seg0, i if cut is None else cut))
            if first:
                return w
            i += 2 if s[i:i + 2] in ("&&", "||", "|&") else 1
            seg0, cut = i, None
            continue
        i += 1
    w.segs.append(s[seg0:n if cut is None else cut])
    w.bounds.append((seg0, n if cut is None else cut))
    return w


def _subs(s, ps=False, hd=False):
    """[(kind, body)] of every $( ... ) and `...` in s at any depth, innermost first, from the cached walk of each body."""
    out = []
    for k, b in _walk(s, ps, hd).subs:
        if k == "$(":
            out += _subs(b, ps)
        out.append((k, b))
    return out


def _stmt(text, i, ps=False):
    """The statement that starts at text[i], up to its first unquoted separator."""
    return _walk1(text[i:], ps, True).segs[0]


def _stage(text, pos, ps=False):
    """(start, end) of the innermost statement holding text[pos] (a top-level $( ... ) body is its own statement)."""
    w = _walk(text, ps)
    for a, b in w.tsubs:
        if a <= pos < b:
            s, e = _stage(text[a:b], pos - a, ps)
            return s + a, e + a
    if getattr(w, "starts", None) is None:   # the bounds are in order and do not overlap: look the statement up by bisection
        w.starts = [a for a, _ in w.bounds]
    i = bisect.bisect_right(w.starts, pos) - 1
    return w.bounds[i] if i >= 0 and w.bounds[i][0] <= pos < w.bounds[i][1] else (pos, pos)


_ANSI_ESC = re.compile(r"\\(x[0-9A-Fa-f]{1,2}|u[0-9A-Fa-f]{1,4}|U[0-9A-Fa-f]{1,8}|[0-7]{1,3}|c.|.)", re.S)
_ANSI_CHR = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v",
             "\\": "\\", "'": "'", '"': '"', "?": "?"}


def _ansi(m):
    e = m.group(1)
    if e[0] in "xuU" and len(e) > 1:
        n = int(e[1:], 16)
        return chr(n) if n <= 0x10FFFF and not 0xD800 <= n <= 0xDFFF else "\ufffd"
    if e[0] in "01234567":
        return chr(int(e, 8) & 255)
    return chr(ord(e[1]) & 31) if e[0] == "c" else _ANSI_CHR.get(e, "\\" + e)


def _unquote(q, ps=False):
    """The value bash gives one quoted string: '...' as is, $'...' with its C escapes decoded and cut at a NUL, "..." and
    $"..." with \\$ \\` \\" \\\\ and \\newline unescaped. PowerShell: the text between."""
    if ps:
        return q[1:-1]
    if q[:2] == "$'":
        return _ANSI_ESC.sub(_ansi, q[2:-1]).split("\0")[0]
    if q[0] == '"' or q[:2] == '$"':
        return re.sub(r'\\([$`"\\\n])', lambda m: "" if m.group(1) == "\n" else m.group(1), q[q.index('"') + 1:-1])
    return q[1:-1]


def _dequote(text, ps=False):
    """text after bash's quote removal: top-level quoted strings unquoted and top-level backslash escapes removed, so
    adjacent pieces join (`ma""in` is main). PowerShell: the quotes only."""
    w, out, last = _walk(text, ps), [], 0

    def plain(x, y):
        if ps or "\\" not in text[x:y]:
            return text[x:y]
        return re.sub(r"\\(.)?", lambda m: m.group(0) if not w.top[x + m.start()] or m.group(1) is None else
                      "" if m.group(1) == "\n" else m.group(1), text[x:y], flags=re.S)
    for a, b, _ in w.spans:
        out += [plain(last, a), _unquote(text[a:b], ps)]
        last = b
    return "".join(out + [plain(last, len(text))])


_SH_W = r"""(?:"(?:\\.|[^"\\])*"|\$'(?:\\.|[^'\\])*'|'[^']*'|\\.|\$(?!')|[^\s"'\\$])+"""   # one shell word
_SSH_HOST = re.compile(r"\s*(?:-[BbcDEeFIiJLlmOoPpQRSWw]\s+" + _SH_W + r"\s+|-" + _SH_W + r"\s+)*" + _SH_W)
_WORD_END = " \t\n;&|()<>"


def blank_prose(text, ps=False, prose=True):
    """The one quote blanker -> (flat, inner). A quoted string a runner executes is blanked and returned in inner as
    (shell text, via ssh?, PowerShell?) to re-lex: ssh / wsl / eval / pwsh JOIN their args, so their inner is the rest
    of the statement after quote removal (ssh's options and host dropped, the host kept in flat); bash -c gets the word
    its string is in. With prose: "..." holding $( or a backtick runs and stays, comments go, top-level $( ... ) bodies
    are blanked the same way, and every other quoted string is part of a shell WORD: it is prose -> "" only when it IS
    the whole word, holds whitespace and is no option; else it is its value (_unquote) with whitespace and
    ; & | < > ( ) # ' " ` made inert, so the word reads as bash builds it (`git commit "--date=..."`, `--da""te=`).
    prose="words": every such string is a word (a write target with a space in it is still a path)."""
    key = (text, ps, prose)
    if key in _PROSED:
        return _PROSED[key]
    w = _walk(text, ps)
    edits, inner, joined, ends, seg, host, words, cur = [], [], set(), dict(w.bounds), {}, {}, set(), (-1, -1)
    inert = lambda v: re.sub(r"[\s;&|<>()#'\"`]", "_", v)  # noqa: E731
    for a, b, s0 in w.spans:
        q = text[a:b]
        if re.search(r"<<-?\s*$", text[max(s0, a - 12):a]):
            continue                           # a heredoc delimiter, not an argument
        if s0 not in seg:                      # runner words of the statement, found once
            st = text[s0:ends[s0]]
            hs = _HEAD_SKIP.sub("", st, 1)
            v = _VAR_HEAD.match(hs)
            seg[s0] = ([(s0 + m.end(), m.group(1).lower()) for m in _RUNNER.finditer(st)],
                       [(s0 + m.end(), m.group(1).lower()) for m in _JOINER.finditer(st)],
                       v and (s0 + len(st) - len(hs) + v.end(), v.group(1).lower()))
        rs, js, vh = seg[s0]
        r = next((x for x in rs if x[0] <= a), None)
        j = next((x for x in js if x[0] <= a), None)
        if not r and vh and vh[0] <= a:        # `$RUN '...'`: a command held in a variable may be ssh / bash
            r = j = vh
        if a >= cur[1]:                        # the shell word holding this string: glued pieces are one word
            wa, wb = a, b
            while wa > max(s0, cur[1]) and not (w.top[wa - 1] and text[wa - 1] in _WORD_END):
                wa -= 1
            while wb < ends[s0] and not (w.top[wb] and text[wb] in _WORD_END):
                wb += 1
            cur = (wa, wb)
        wa, wb = cur
        if r:
            word = (j or r)[1]
            ips = word in ("pwsh", "powershell", "iex", "invoke-expression")
            if not j:
                if wa not in words:
                    words.add(wa)
                    inner.append((_dequote(text[wa:wb], ps), False, ips))
            elif s0 not in joined:
                joined.add(s0)
                rest = text[j[0]:ends[s0]]
                m = _SSH_HOST.match(rest) if word == "ssh" else None
                host[s0] = j[0] + (m.end() if m else 0)
                inner.append((_dequote(rest[m.end() if m else 0:], ps), word == "ssh" or word.startswith("$"), ips))
            if j and a < host[s0]:         # an ssh option value runs LOCALLY too (-o "ProxyCommand ...")
                inner.append((_unquote(q, ps), False, ips))
            edits.append((a, b, inert(_unquote(q, ps)) if j and a < host[s0] else '""'))   # ssh's host stays a word
        elif prose and not (q[0] in '"$' and q[-1] == '"' and re.search(r"\$\(|`", q)):
            val = _unquote(q, ps)
            edits.append((a, b, '""' if prose != "words" and (wa, wb) == (a, b) and re.search(r"\s", val)
                          and not val.startswith("-") and "://" not in val else inert(val)))
    if prose:
        for a, b in w.tsubs:
            f, i2 = blank_prose(text[a:b], ps, prose)
            edits.append((a, b, f))
            inner += i2
        edits += [(a, b, "") for a, b in w.notes]
    out, last = [], 0
    for a, b, rep in sorted(edits):
        out += [text[last:a], rep]
        last = b
    _PROSED[key] = "".join(out) + text[last:], inner
    return _PROSED[key]


def _prose_texts(text, ps=False, remote=False, depth=0, prose=True):
    """[(flat, remote?)] for text and, re-lexed recursively, every runner string in it (ssh '...' runs remotely)."""
    flat, inner = blank_prose(text, ps, prose)
    out = [(flat, remote)]
    for s, r, p in inner:
        out += _prose_texts(s, p, remote or r, _deeper(depth), prose)
    return out


def statements(c, prose=True):
    """Every statement a shell runs in this command, prose blanked: [(statement, remote?)] across the top text,
    shell-run heredoc bodies and runner strings (ssh '...' is remote). prose="words": a quoted word with a space in it
    (a path under "C:\\Program Files") stays one word instead of becoming "" (see blank_prose)."""
    out = []
    for t, rem in c.L.shell_texts():
        for flat, r in _prose_texts(t, c.ps, rem, prose=prose):
            out += [(s, r) for s in _walk(flat, c.ps).segs if s.strip()]
    for d in decoded_payloads(c):   # powershell -EncodedCommand <base64 of "tokensave doctor"> runs that text
        for flat, r in _prose_texts(d, True, False, prose=prose):
            out += [(s, r) for s in _walk(flat, True).segs if s.strip()]
    return out


ENC_MSG = ("This runs a PowerShell -EncodedCommand (or a prefix of it) whose payload the guard cannot decode. "
           "Run the command as plain text so it can be checked.")


def decoded_payloads(c):
    """The decoded text of every -EncodedCommand this command runs (the prose-blanked view, nested ones up to three deep).
    An undecodable payload on the command line itself is the encoded-command rule's (it refuses it); one inside a decoded
    payload, or a payload that still holds an encoded command after the third level, is refused here (encoded-command, and
    nest-cap): both are text the guard cannot judge, and passing them silently would be a way round it."""
    if not _PWSH.search(c.cmd):
        return []
    out, todo = [], [_raw_body(c)]
    for depth in range(3):
        found = [d for t in todo for d in encoded_commands(t)]
        if depth and None in found:
            block(ENC_MSG, "encoded-command", c.cmd[:120])
        todo = [squash_runs(d) for d in found if d]
        out += todo
    if any(encoded_commands(t) for t in todo):
        raise _TooDeep("-EncodedCommand nested more than 3 levels")
    return out


_CMD_SPLIT = re.compile(r"\$\(|[(){}`;&|]")
_PS_ASSIGN = re.compile(r"(\$[\w:]+(?:\[[^\]\n]*\])?)[ \t]*[-+*/]?=(?!=)")   # $out = cmd, $env:X=cmd, $a[0] += cmd
_PS_HOSTS = ("pwsh", "powershell")


def cmd_starts(seg, names):
    """The suffixes of one statement that start at a command word whose basename (lower case, no .exe) is in `names`: the
    statement's own command word, and one after $( ( ) { } ` ; & | or a PowerShell assignment (a substitution, a block, a call
    operator: `out=$(tokensave doctor)`, `$out = tokensave doctor`, `try { git commit -n } catch {}`), and one past the
    switches of a PowerShell host (`pwsh -NonInteractive -c tokensave install`, or the payload ` -NoProfile -Command ...`).
    A `NAME=value` word is no assignment (`make TOOL=tokensave install`), and prose is already blanked in `seg`, so `echo
    tokensave doctor` has no command word of that name."""
    out = []
    seg = _PS_ASSIGN.sub(r"\1;", seg)   # the variable's own statement ends at the =; the command follows
    for part in [seg] + _CMD_SPLIT.split(seg):
        toks = _cmd_toks(part)
        j = 0
        if toks and re.split(r"[\\/]", toks[0].strip("\"'"))[-1].lower().removesuffix(".exe") in _PS_HOSTS:
            if len(toks) < 2 or not toks[1].startswith("-"):
                continue                                   # `pwsh script.ps1 ...` runs a file, not a command word
            j = 1
        while j < len(toks):
            if re.split(r"[\\/]", toks[j].strip("\"'"))[-1].lower().removesuffix(".exe") in names:
                out.append(" ".join(toks[j:]))
                break
            if toks[j].startswith("-") or (j and toks[j - 1].startswith("-")):   # a leading switch, or its value
                j += 1
            else:
                break
    return list(dict.fromkeys(out))


def git_sub(seg):
    """(tokens, index of the git subcommand) for a git statement, past git's own options (-C dir, -c k=v, --git-dir
    ...); index None when there is none. tokens[0] is the git word."""
    toks = _HEAD_SKIP.sub("", seg, 1).split()
    k = 1
    while k < len(toks):
        t = toks[k]
        if t in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"):
            k += 2
        elif t.startswith("-"):
            k += 1
        else:
            return toks, k
    return toks, None


def _shell_vars(text):
    """NAME -> value for the plain assignments in text (`D=/srv/app`, `$d = "C:\\work"`)."""
    return {m.group(1).lower(): next(g for g in m.groups()[1:] if g is not None) for m in re.finditer(
        r"""(?:^|[\s;&(])\$?([A-Za-z_]\w*)\s*=\s*(?:"([^"\n]*)"|'([^'\n]*)'|([^\s;&|"'`]+))""", text)}


def expand_vars(text):
    """text with $NAME / ${NAME} replaced by the value this same command assigned it (a path held in a variable)."""
    v = _shell_vars(text)
    return re.sub(r"\$\{?([A-Za-z_]\w*)\}?", lambda m: v.get(m.group(1).lower(), m.group(0)), text) if v else text


def _winpath(p):
    p = os.path.expanduser(p)
    mm = re.match(r"^/([A-Za-z])/(.*)$", p)
    return f"{mm.group(1)}:/{mm.group(2)}" if mm and os.name == "nt" else p


def local_files(text, cwd, rels, cap=200_000):
    """(path, content) of each existing local file in rels under cap bytes; a relative one resolves against cwd and
    every `cd` target in text."""
    bases = [b for b in [cwd] + [_winpath(c[1]) for c in re.findall(r"\bcd\s+([\"']?)([^\s;&|\"']+)\1", text)] if b]
    for rel in rels:
        p = _winpath(rel)
        for f in ([p] if os.path.isabs(p) else [os.path.join(b, p) for b in bases]):
            try:
                if os.path.isfile(f) and os.path.getsize(f) < cap:
                    with open(f, encoding="utf-8", errors="replace") as fh:
                        yield f, fh.read()
            except OSError:
                pass


# ── the files a shell write targets ──────────────────────────────────────────────────────────────────────────
_MARKUP = re.compile(r"<[A-Za-z/][^<>\s]*$")
_WT = {}   # write_targets answers for this evaluate() (it is called by several rules with the same command)
_REDIRECT = re.compile(r'(?<![<>=\-])>>?\|?\s*([^\s;&|<>()]+)')
_WRITER = re.compile(r'(?i)(?:^|[\s"\'(;&|`])(tee|tee-object|sed|perl|cp|mv|install|scp|rsync|copy-item|move-item|'
                     r'set-content|add-content|out-file|clear-content|dd)(?=\s)')
_PY_WRITE = re.compile(r"""(?i)\bopen\(\s*[rbuf]*["']([^"'\n]+)["']\s*,\s*(?:mode\s*=\s*)?[rbuf]*["'][rbt]*[wax+]"""
                       r"""|\(\s*[rbuf]*["']([^"'\n]+)["']\s*\)\s*\.\s*write_(?:text|bytes)\("""
                       r"""|\b(?:shutil\.(?:copy\w*|move)|os\.(?:replace|rename))\([^)\n]*,\s*[rbuf]*["']([^"'\n]+)["']""")


def write_targets(cmd, ps=False, remote=False, depth=0):
    """[(path, remote?)] for every file a shell write targets: redirects, tee / sed -i / perl -i / cp /
    mv / install / scp / rsync / dd of= / Set-Content / Add-Content / Out-File / Clear-Content / Copy-Item / Move-Item
    (-Destination), python open(<literal>, 'w') / Path(<literal>).write_text. Quoted prose writes nothing; runner
    strings and shell-run heredoc bodies are judged, remote when ssh carries them. Every writer word re-reads the rest of its
    statement, so a command that repeats one thousands of times is denied past a budget (nest-cap)."""
    key = (cmd, ps, remote, depth)
    if key in _WT:
        return _WT[key]
    L, out = lex(cmd, ps), []
    for body, rem in L.bodies:
        out += write_targets(body, ps, remote or rem, _deeper(depth))
    flat, inner = blank_prose(L.top, ps, "words")      # a quoted path with a space in it is still a path
    for s, rem, p in inner:
        out += write_targets(s, p, remote or rem, _deeper(depth))
    cands = [(m.group(1), m.start()) for m in _REDIRECT.finditer(flat)
             if not _MARKUP.search(flat, 0, m.start())]   # `<code>.env</code>` is markup
    for m in _WRITER.finditer(flat):
        rest = re.split(r"&&|\|\||[;\n|()]", flat[m.end():], maxsplit=1)[0]
        _work(len(rest))
        try:  # a quoted sed script stays ONE token; posix=False keeps Windows backslashes
            lx = shlex.shlex(rest, posix=False)
            lx.whitespace_split = True
            toks = [t.strip("\"'") for t in lx]
        except ValueError:
            toks = [t.strip("\"'") for t in rest.split()]
        args = [t for t in toks if not t.startswith("-")]
        verb, targets = m.group(1).lower(), []
        if verb in ("sed", "perl"):
            if any(re.match(r"-\w*i", t) or t == "--in-place" for t in toks):
                targets = args if any(t in ("-e", "-f") for t in toks) else args[1:]   # else arg 1 is the script
        elif verb in ("cp", "mv", "install", "scp", "rsync", "copy-item", "move-item"):
            dest = next((toks[i + 1] for i, t in enumerate(toks[:-1]) if t.lower() == "-destination"), None)
            targets = [dest] if dest else args[-1:]
        elif verb == "dd":
            targets = [t[3:] for t in toks if t.lower().startswith("of=")]
        else:  # tee / Tee-Object / Set-Content / Add-Content / Out-File / Clear-Content
            targets = args
        cands += [(t, m.start()) for t in targets if t]
    out += [(x, remote) for t, pos in cands
            for x in {t.strip("\"'`"), re.sub(r"[\s._]+$", "", t.strip("\"'`"))} if x]
    if depth == 0:
        x = expand_vars(cmd)
        out += [(m.group(1) or m.group(2) or m.group(3), remote) for m in _PY_WRITE.finditer(x)]
    _WT[key] = out
    return out


# ── data arguments: a journal line or a commit message is data, not shell ─────────────────────────────────────
_TO_SHELL = re.compile(r"(?i)" + _PIPE_WRAP + r"(?:(?:ba|z|da|k)?sh|pwsh|powershell|iex|invoke-expression|"
                       r"python[\d.]*|node|xargs)\b|(?<![\w.-])(?:eval|source)\s|(?:^|[;&|(]\s*)\.\s+\S")
# The gap between `commit` and `-m` is bounded: an unbounded one is quadratic on a line that repeats `git commit`, and a message past the
# bound is simply not blanked (judged as text), which can only add findings.
_DATA_ARG = re.compile(r"""(?:save_driver\.py["']?\s+(?P<f>--inbox-add)|"""
                       r"""(?<![\w.-])git\s+commit\b[^\n;&|"'#]{0,400}?\s(?P<g>-[A-Za-z]*m))\s*"""
                       r"""(?P<v>"(?:\\.|[^"\\])*"|'[^']*')""")


def blank_data(text, ps=False):
    """Blank the quoted value of `save_driver.py --inbox-add "..."` / `git commit -m "..."` where the quoting is
    unambiguous: nothing piped into a shell, no ${ or $' anywhere, no $( or backtick in the value, flag and opening
    quote outside every quote and comment, and no runner before it in the statement unless the value holds no
    separator (ssh / pwsh -c / wsl re-parse their args). A backslash is ambiguous only in PowerShell."""
    if _TO_SHELL.search(text) or re.search(r"\$[{']" + (r"|\\" if ps else ""), text):
        return text
    top = _walk(text, ps).top

    def blank(m):
        v = m.group("v")[1:-1]
        if top[m.start("f" if m.group("f") else "g")] and top[m.start("v")] and not re.search(r"\$\(|`", v) and \
                (not _RUNNER.search(text[_stage(text, m.start(), ps)[0]:m.start()]) or
                 not re.search(r"[;&|<>`$()\\\n]", v)):
            return m.group(0)[:m.start("v") - m.start()] + '""'
        return m.group(0)
    return _DATA_ARG.sub(blank, text)


# ── the raw view: everything a command could execute, minus what is provably prose ───────────────────────────
# Rules that must not miss a push or a force-push judge BOTH the prose-blanked statements (statements()) and this
# view. statements() blanks every quoted string a known runner does not execute, which also blanks code handed to
# python -c / node -e and the like; this view keeps all of it and blanks only arguments that provably never run:
# echo / printf / grep-family arguments (no substitution, not piped onward, not redirected into a file this command
# executes), git commit / tag messages, gh pr|issue create titles and bodies, journal lines, and cat/tee heredocs to
# a file nothing here runs. Interpreter and shell payloads are never blanked. A pwsh -EncodedCommand payload is
# decoded and appended.
_PROSE_HEADS = {"echo", "printf", "grep", "egrep", "fgrep", "rg", "findstr", "select-string", "sls", "write-host",
                "write-output"}
_GIT_MSG = re.compile(r"""((?:\s-[A-Za-z]*m|\s--message)(?:=|\s+))("(?:\\.|[^"\\])*"|'[^']*')""")
_GH_TEXT = re.compile(r"""((?:\s--title|\s-t|\s--body|\s-b)(?:=|\s+))("(?:\\.|[^"\\])*"|'[^']*')""")
_PWSH = re.compile(r"(?i)(?<![\w.-])(?:pwsh|powershell)(?:\.exe)?[\"']?(?=\s|$)")


def _enc_switch(tok):
    """True for a pwsh switch that means -EncodedCommand: any prefix of it (or of -EncodedArguments), or -ec, with a
    -, -- or / prefix."""
    name = re.sub(r"^(?:--|-|/)", "", tok).split(":", 1)[0].lower()
    return bool(name) and tok[:1] in "-/" and ("encodedcommand".startswith(name) or "encodedarguments".startswith(name)
                                               or name == "ec")


def encoded_commands(text):
    """[decoded text, or None when it cannot be resolved] for every encoded-command switch in every pwsh / powershell
    argument list in text. Decoding follows .NET: strict base64, then UTF-16LE with replacement (odd length is fine)."""
    import base64
    out = []
    for m in _PWSH.finditer(text):
        toks = [t.strip("\"'") for t in re.split(r"\s+", re.split(r"[;|&\n]", text[m.end():], maxsplit=1)[0].strip()) if t]
        for i, t in enumerate(toks):
            if not _enc_switch(t):
                continue
            val = t.split(":", 1)[1] if ":" in t else (toks[i + 1] if i + 1 < len(toks) else "")
            try:
                out.append(base64.b64decode(val, validate=True).decode("utf-16-le", errors="replace") if val else None)
            except ValueError:
                out.append(None)
    return out


_RAWB = {}   # _raw_body answers for this evaluate() (a dozen rules read it)


def _raw_body(c):
    """The raw command minus provable prose (see raw_view)."""
    key = (c.doc, c.ps)
    if key not in _RAWB:
        _RAWB[key] = _raw_body_of(c)
    return _RAWB[key]


def _raw_body_of(c):
    text = blank_data(c.doc, c.ps)
    w = _walk(text, c.ps)
    bounds = [(a, b) for a, b in w.bounds if text[a:b].strip()]
    segs = [(text[a:b], {os.path.basename(f.strip("\"'")) for f in _fs_wtargets(text[a:b])}, _head(text[a:b]))
            for a, b in bounds]
    edits, ran = [], {}
    for a, b in bounds:
        seg, h = text[a:b], _head(text[a:b])
        if re.search(r"\$\(|`|<\(", seg):
            continue                                   # a substitution runs: keep it all
        if h in _PROSE_HEADS and not (h == "rg" and re.search(r"\s--pre(?:-glob)?(?:=|\s|$)", seg)) \
                and not (h == "printf" and re.search(r"(?<![\w-])-v(?![\w-])", seg)):   # rg --pre runs a program
            nxt = text[b:b + 3].lstrip(" \t")
            targets = [f.strip("\"'") for f in _fs_wtargets(seg)]
            if targets and tuple(targets) not in ran:      # _ran reads every statement: once per set of files, and counted
                _work(len(segs))
                ran[tuple(targets)] = _ran(targets, segs, text)
            if (nxt.startswith("|") and not nxt.startswith("||")) or (targets and ran[tuple(targets)]):
                continue                               # piped onward, or written to a file this command runs
            edits.append((a, b, h))
        elif h == "git" and re.search(r"(?<![\w.-])git\s+(?:commit|tag)\b", seg):
            edits.append((a, b, _GIT_MSG.sub(r'\1""', seg)))
        elif h == "gh" and re.search(r"(?<![\w.-])gh\s+(?:pr|issue)\s+create\b", seg):
            edits.append((a, b, _GH_TEXT.sub(r'\1""', seg)))
    out, last = [], 0
    for a, b, rep in edits:
        out += [text[last:a], rep]
        last = b
    return "".join(out) + text[last:]


def live_encoded(c):
    """encoded_commands over the prose-blanked view: a commit message or echo that names `pwsh -ec` runs nothing."""
    return encoded_commands(_raw_body(c))


def raw_view(c):
    view = _raw_body(c)
    dec = [d for d in encoded_commands(view) if d]
    return view + ("\n" + "\n".join(dec) if dec else "")


# ── git config values: git runs many of them as shell (-c, `git config`, GIT_CONFIG_PARAMETERS, GIT_CONFIG_KEY_n /
# VALUE_n, the GIT_* exec env). Normalise all to (key, value); rules scan every value except identity / color keys.
GIT_NONEXEC = re.compile(r"(?ix)^(?:(?:user|author|committer)\.|color(?:\.|$))")
_GIT_EXEC_ENV = re.compile(r"(?i)^GIT_(?:SSH_COMMAND|EDITOR|PAGER|EXTERNAL_DIFF|SEQUENCE_EDITOR|ASKPASS|SSH|PROXY_COMMAND|"
                           r"TEMPLATE_DIR)$")
_VAL = r"""(?:"(?:\\.|[^"])*"|'[^']*'|[^\s;&|)]*)"""
_GIT_C = re.compile(r"""(?x)(?<![\w.-])-c\s+([A-Za-z][^\s=]*)=(""" + _VAL + r""")""")   # a key can hold a URL
_PS_ENV = r"(?:^|[\s;&|(]|(?i:\$env:|\$\{env:))"
_GIT_ENVP = re.compile(r"""(?x)""" + _PS_ENV + r"""([A-Za-z_]\w*)\}?(?:\s*=\s*(?=["'])|=)(""" + _VAL + r""")""")
_GIT_CONFIG = re.compile(r"""(?ix)(?<![\w.-])git\s+(?:-\S+\s+|--\S+\s+)*config\b((?:\s+(?:--\S+|-f\s+\S+|\S+))*)""")
_GIT_KV = re.compile(r"""(?x)""" + _PS_ENV + r"""((?i:GIT_CONFIG_(?:KEY|VALUE))_(\d+))\}?(?:\s*=\s*(?=["'])|=)(""" +
                     _VAL + r""")""")
_GIT_PARAMS = re.compile(r"""(?x)""" + _PS_ENV + r"""((?i:GIT_CONFIG_PARAMETERS))\}?(?:\s*=\s*(?=["'])|=)(""" + _VAL +
                         r""")""")
_PARAM_PAIR = re.compile(r"""'([^'=]+)=((?:[^']|'\\'')*)'|"([^"=]+)=((?:\\.|[^"])*)"|(\S+?)=(\S+)""")


def _unq(v):
    v = v.strip()
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        v = v[1:-1]
    return v[1:] if v.startswith("!") else v    # a git alias / credential.helper shell value leads with '!'


def git_config_pairs(cmd, ps=False):
    """Every (key, value) a git config entry point sets, from EXECUTED shell only. Values unquoted, leading '!' off."""
    pairs = []
    for t, _ in lex(cmd, ps).shell_texts():
        tset = _walk(t, ps).top
        for m in _GIT_C.finditer(t):
            if tset[m.start()]:
                pairs.append((m.group(1), _unq(m.group(2))))
        for m in _GIT_ENVP.finditer(t):
            if tset[m.start(1)] and _GIT_EXEC_ENV.match(m.group(1)):
                pairs.append((m.group(1), _unq(m.group(2))))
        keys, vals = {}, {}
        for m in _GIT_KV.finditer(t):
            if tset[m.start(1)]:
                (keys if "KEY" in m.group(1).upper() else vals)[m.group(2)] = _unq(m.group(3))
        pairs += [(keys[i], vals[i]) for i in keys if i in vals]
        for m in _GIT_PARAMS.finditer(t):
            if tset[m.start(1)]:
                for pm in _PARAM_PAIR.finditer(_unq(m.group(2))):
                    k = pm.group(1) or pm.group(3) or pm.group(5)
                    if k:
                        pairs.append((k, _unq(pm.group(2) or pm.group(4) or pm.group(6) or "")))
        for m in _GIT_CONFIG.finditer(t):
            if not tset[m.start()]:
                continue
            try:
                toks = [x for x in shlex.split(m.group(1)) if x.strip()]
            except ValueError:
                toks = [x for x in re.findall(_VAL, m.group(1)) if x.strip()]
            args = [x for x in toks if not x.startswith("-")]
            if args[:1] == ["set"]:          # git 2.46+: `git config set <key> <value>`
                args = args[1:]
            if args and "=" in args[0] and not args[0].startswith("="):
                k, v = args[0].split("=", 1)
                pairs.append((k, _unq(v)))
            elif len(args) >= 2:
                pairs.append((args[0], _unq(args[1])))
    return [p for p in dict.fromkeys(pairs) if p[1] != cmd]


# ── the guards' own configuration: write-protected whatever pack is loaded ───────────────────────────────────
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
# MCP tools that edit files on disk by path: tokensave's edit tools (mcp__tokensave__tokensave_<verb>). They are not Edit or Write,
# so without this they skip every write check (secret files, .env, the kit's own configuration, settings). The server key
# varies by registration, so any mcp__ tool ending in one of these verbs counts; over-matching only runs a path check. The
# PreToolUse matcher in hooks/hooks.json names the same verbs (a test compares them). A verb a newer tokensave adds goes here.
EDIT_MCP_VERBS = ("str_replace", "multi_str_replace", "insert_at", "insert_at_symbol", "replace_symbol", "ast_grep_rewrite",
                  "replace_lines", "delete_symbol")
EDIT_MCP = re.compile(r"mcp__.*_(?:" + "|".join(EDIT_MCP_VERBS) + ")")
_PATH_KEYS = ("path", "file_path", "file", "filepath")
READ_TOOLS = ("Read", "Grep", "Glob")
OTHER_TOOLS = ("WebFetch", "Agent")
# Browser MCP servers (playwright, chrome-devtools, puppeteer, plugin-namespaced ones): their URL inputs go to TOOL rules.
BROWSER_MCP = re.compile(r"mcp__.*([Pp]laywright|[Cc]hrome|[Pp]uppeteer|[Bb]rowser).*")
# Database MCP servers (postgres, mysql, sqlite, mssql ...): their inputs go to TOOL rules. The classes are spelled out
# letter by letter, exactly as in the hooks.json matcher, so a server name in any letter case is seen.
DB_MCP = re.compile(r"mcp__.*([Pp][Oo][Ss][Tt][Gg][Rr][Ee][Ss]|[Ss][Qq][Ll]|[Dd][Aa][Tt][Aa][Bb][Aa][Ss][Ee]).*")
_RM_HEADS = {"rm", "rmdir", "remove-item", "ri", "rd", "del", "erase", "unlink", "mv", "move-item", "rename-item"}
_KIT_RAW = re.compile(r"(?i)(?:^|[/\\])\.claude[/\\]+(?:settings(?:\.local)?\.json$|workbench(?:[/\\]|$)|"
                      r"plugins[/\\].*workbench)")
KIT_MSG = ("{path} configures Claude Code or the workbench guards (settings files, the workbench folder, the "
           "corporate allowlist, the installed plugins). The agent does not change the controls that apply to it: "
           "the user edits these by hand, with /config or /permissions, or re-runs the workbench installer.")


def _win_unprefix(p):
    r"""The plain spelling of a Windows path: \\?\C:\x and \\.\C:\x are C:\x, \\?\UNC\srv\share\x is \\srv\share\x, and
    \\localhost\C$\x (this machine's own admin share, also by the loopback address or its name) is C:\x. Either slash. \\?\Volume{id}\
    and \\?\GLOBALROOT\Device\... are left whole: realpath resolves them to \\?\C:\..., which is then unprefixed (norm())."""
    m = re.match(r"^[\\/]{2}[?.][\\/](?:(UNC)[\\/]|(?=[A-Za-z]:))", p, re.I)   # only before a drive letter or UNC\
    if m:
        p = ("\\\\" if m.group(1) else "") + p[m.end():]
    hosts = [h for h in ("localhost", "127" + ".0.0.1", os.environ.get("COMPUTERNAME", "")) if h]   # no address literal here
    m = re.match(r"^[\\/]{2}(?:" + "|".join(re.escape(h) for h in hosts) + r")[\\/]([A-Za-z])\$(?=[\\/]|$)", p, re.I)
    return f"{m.group(1)}:{p[m.end():] or chr(92)}" if m else p


_ENV_REF = re.compile(r"(?i)\$\{(?:env:)?(HOME|USERPROFILE|CLAUDE_CONFIG_DIR)\}|\$env:(HOME|USERPROFILE|CLAUDE_CONFIG_DIR)(?!\w)|"
                      r"%(HOME|USERPROFILE|CLAUDE_CONFIG_DIR)%|\$(HOME|USERPROFILE|CLAUDE_CONFIG_DIR)(?!\w)")


def expand_env(p):
    """p with $HOME, ${HOME}, $env:HOME, $env:USERPROFILE, %USERPROFILE% (and the same spellings of CLAUDE_CONFIG_DIR) replaced by
    what they are for this session: the shell would expand them before the command ran, and a path to the guards' folders is the
    same path in either spelling. HOME and USERPROFILE fall back to the home folder (~) when unset; CLAUDE_CONFIG_DIR to the config
    dir the guards use. Other variables are left as written (known-limits)."""
    if "$" not in p and "%" not in p:
        return p

    def val(m):
        name = next(g for g in m.groups() if g).upper()
        return str(_wb.claude_home()) if name == "CLAUDE_CONFIG_DIR" else os.environ.get(name) or os.path.expanduser("~")
    return _ENV_REF.sub(val, p)


@_memo
def norm(p, cwd=""):
    """An absolute, normalised, case-folded path for comparisons; a Git Bash /tmp or /c/ path is mapped first. $HOME and the like
    are expanded first (expand_env)."""
    p = _win_unprefix(os.path.expanduser(expand_env(str(p).strip("\"'"))))
    if os.name == "nt":
        m = re.match(r"^/([A-Za-z])(/.*)?$", p)
        if re.match(r"^/tmp(/|$)", p):
            p = _tmpdir() + p[4:]
        elif m:
            p = f"{m.group(1)}:{m.group(2) or '/'}"
    if cwd and not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.normcase(_win_unprefix(os.path.realpath(os.path.abspath(p)))).replace("\\", "/")


def under(path, root):
    """True when path (normalised) is root or inside it: a directory prefix, never a substring."""
    return path == root or path.startswith(root.rstrip("/") + "/")


@_memo
def _as_written(p, cwd=""):
    """norm() without following symlinks: the path as the command names it."""
    p = _win_unprefix(os.path.expanduser(expand_env(str(p).strip("\"'"))))
    if cwd and not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.normcase(os.path.abspath(p)).replace("\\", "/")


def kit_protected(path, cwd=""):
    """True when writing, linking or deleting `path` would change the guards' own configuration. Judged on the path as
    written AND as resolved (symlinks followed): either one inside a protected place denies. The raw-name regex can
    only add a reason to deny, never allow. The one exception, <workbench home>/USER.md, holds only for a real file
    reached without a symlink."""
    if not path:
        return False
    raw = str(path).strip("\"'").rstrip("/\\")
    raw_hit = bool(_KIT_RAW.search(raw))
    try:
        unresolved = _as_written(raw, cwd)
        cands = {norm(raw, cwd), unresolved}
        homes = [_wb.claude_home()] + [h for h in [_wb.installed_claude_home()] if h]   # a redirected env var too
        chs = {f(h) for h in homes for f in (norm, _as_written)}
        wbs = {f(h / "workbench") for h in homes for f in (norm, _as_written)}
    except (OSError, ValueError):
        return True if raw_hit else False
    user_md = {w + "/user.md" for w in wbs}
    for q in cands - user_md:
        if any(under(q, w) for w in wbs) or any(q in (c + "/settings.json", c + "/settings.local.json") or
                                                (under(q, c + "/plugins") and "workbench" in q[len(c) + 9:])
                                                for c in chs):
            return True
    if cands & user_md:
        return os.path.islink(unresolved) or norm(raw, cwd) not in user_md
    return raw_hit


_LINK_HEADS = {"ln", "mklink", "new-item", "ni", "cp", "fsutil"}


def _cmd_toks(seg):
    """The words of a statement past VAR=, sudo and the like, and past `cmd /c` (cmd runs the rest as a command)."""
    toks = _HEAD_SKIP.sub("", seg, 1).split()
    if len(toks) > 1 and os.path.basename(toks[0]).lower() in ("cmd", "cmd.exe") and re.fullmatch(r"(?i)/[cks]", toks[1]):
        toks = toks[1:]
    while toks and re.fullmatch(r"(?i)/[cks]", toks[0]):
        toks.pop(0)
    return toks


def _link_targets(toks):
    """Every path a link-making command names: a link at a harmless name that points into a protected folder is a
    write into that folder for every later command."""
    h = os.path.basename(toks[0]).lower().removesuffix(".exe") if toks else ""
    args = toks[1:]
    if h == "cp":   # cp -s / -l / --symbolic-link / --link makes links instead of copies
        if not any((re.fullmatch(r"-[a-zA-Z]{1,5}", a) and re.search("[sl]", a)) or a in ("--symbolic-link", "--link")
                   for a in args):
            return []
        return [a for a in args if not a.startswith("-")]
    if h in ("new-item", "ni"):
        if not re.search(r"(?i)-ItemType\s+['\"]?(?:SymbolicLink|HardLink|Junction)", " ".join(args)):
            return []
        return [a for a in args if not a.startswith("-") and not re.fullmatch(r"(?i)['\"]?(?:SymbolicLink|HardLink|"
                                                                               r"Junction)['\"]?", a)]
    if h == "mklink":
        return [a for a in args if not a.startswith("/")]
    if h == "fsutil":   # fsutil hardlink create <new file> <existing file>
        return args[2:] if [a.lower() for a in args[:2]] == ["hardlink", "create"] else []
    if h == "ln":
        return [a for a in args if not a.startswith("-")]
    return []


# A script that makes a link (Python, Node, PowerShell / .NET, ctypes): its string literals are judged as link targets. A path
# built at run time (os.path.join(home, ".claude", ...)) is not visible to a reader of the text.
_LINK_CALL = re.compile(r"\bos\.(?:link|symlink)\b|\.(?:hardlink_to|symlink_to|link_to)\s*\(|\bshutil\.\w*link\w*|"
                        r"\bCreate(?:Hard|Symbolic)Link\w*|\.(?:link|symlink)(?:Sync)?\s*\(")
_STR_LIT = re.compile(r"""[rRbBuU]{0,2}(["'])((?:\\.|(?!\1)[^\\\n])*)\1""")


def _code_link_targets(c):
    view = raw_view(c)
    if not _LINK_CALL.search(view):
        return []
    out, texts = [], [view]
    for _ in range(3):   # a literal inside a literal: python -c "os.link('a', 'b')"
        texts = [m.group(2) for t in texts for m in _STR_LIT.finditer(t)]
        out += texts
    return [t.replace("\\\\", "\\") for t in out]


# The installer and the kit updater (kit_update.py downloads and installs a release from the repository it is given). The updater's
# read-only verbs need no approval: `verify` or `record` as its first argument, or a statement that is nothing but plain `--check`
# options (_CHECK_ONLY): a `--check` after a `#`, a redirection or a substitution is not an option. `rest` is a lookahead so a
# second kit_update.py inside a `$( )` of the first is found too.
_INSTALLER = re.compile(r"(?i)bootstrap[/\\]+(?:un)?install\.(?:py|sh)\b|kit_update\.py\b(?=(?P<rest>[^\n;&|]*))")
_CHECK_ONLY = re.compile(r"\s*(?:update\s+)?(?:(?:--check|--repo(?:\s+|=)[\w.-]+/[\w.-]+|--wait(?:\s+|=)\d+(?:\.\d+)?)(?:\s+|$))+")


def _installer_run(cmd):
    for m in _INSTALLER.finditer(cmd):
        rest = m.group("rest")
        if rest is None:
            return True
        rest = rest.replace('"', " ").replace("'", " ")
        args = rest.split()
        if not (args[:1] in (["verify"], ["record"]) or ("--check" in args and _CHECK_ONLY.fullmatch(rest))):
            return True
    return False


_LIST_HEADS = {"get-childitem", "gci", "ls", "dir", "get-item", "gi", "find", "fd"}
_DEL_HEADS = {"remove-item", "ri", "rm", "rmdir", "rd", "del", "erase", "unlink"}


def _glob_targets(t, cwd=""):
    """What a delete target names: itself, or - when it holds *, ? or [ - what glob finds (the shell would expand it before rm
    ran). More than 500 matches: the first 500 and the folder the pattern lists. No match: the pattern itself."""
    if not re.search(r"[*?\[]", t):
        return [t]
    pat = os.path.expanduser(expand_env(t.strip("\"'")))
    if cwd and not os.path.isabs(pat):
        pat = os.path.join(cwd, pat)
    try:
        hits = glob.glob(pat)
    except Exception:
        hits = []
    return (hits[:500] + ([os.path.dirname(pat)] if len(hits) > 500 else [])) or [t]


def _find_roots(toks):
    """The folders a `find` statement lists, when it deletes what it finds (-delete, or -exec rm / rmdir / unlink)."""
    low = [t.lower() for t in toks]
    deletes = "-delete" in low or any(low[i] in ("-exec", "-execdir", "-ok") and low[i + 1:i + 2]
                                       and os.path.basename(low[i + 1]).removesuffix(".exe") in _DEL_HEADS for i in range(len(low)))
    roots = []
    for t in toks[1:]:
        if t.startswith(("-", "(", "!", ")")):
            break
        roots.append(t)
    return roots if deletes else []


def _pipeline_delete_roots(c):
    """The folders whose contents a pipeline deletes: `Get-ChildItem <dir> | Remove-Item -Recurse`, `ls <dir> | xargs rm -rf`,
    `find <dir> | xargs rm`. Without a folder named it is the session folder."""
    out = []
    texts = [(t, c.ps, rem) for t, rem in c.L.shell_texts()] + [(d, True, False) for d in decoded_payloads(c)]
    for t, ps, rem in texts:
        for flat, _r in _prose_texts(t, ps, rem, prose="words"):
            for chain in re.split(r";|&&|\|\||\n", flat):
                stages = re.split(r"(?<!\|)\|(?!\|)", chain)
                if len(stages) < 2:
                    continue
                first = _cmd_toks(re.split(r"[{(]|\$\(", stages[0])[-1])        # `try { Get-ChildItem x | ...` starts after the {
                if not first or os.path.basename(first[0]).lower().removesuffix(".exe") not in _LIST_HEADS:
                    continue
                if not any(_deletes_stage(_cmd_toks(st)) for st in stages[1:]):
                    continue
                roots = [t for t in first[1:] if not t.startswith(("-", "|"))]
                out += roots or [c.cwd or "."]
    return out


def _deletes_stage(toks):
    head = os.path.basename(toks[0]).lower().removesuffix(".exe") if toks else ""
    if head == "xargs":
        rest = [t for t in toks[1:] if not t.startswith("-")]
        head = os.path.basename(rest[0]).lower().removesuffix(".exe") if rest else ""
    return head in _DEL_HEADS


def _kit_shell(c):
    if _installer_run(c.cmd):   # it rewrites settings, the allowlist and the plugins: only with the user's OK
        ask("This runs the workbench installer or kit updater, which changes the controls that apply to the agent (settings, the "
            "approved git hosts, the plugins) and may download code from the repository it names. Approve only if you asked for "
            "this install or update, and read its options.", "installer-run")
    targets = [(t, False) for t, rem in write_targets(c.cmd, c.ps) if not rem] + [(t, False) for t in _code_link_targets(c)]
    for seg, rem in statements(c):
        if rem:
            continue
        for start in cmd_starts(seg, _RM_HEADS | _LINK_HEADS | {"find"}):   # also `x=$(ln -s ...)` and `try { mklink ... } catch {}`
            toks = start.split()
            head = os.path.basename(toks[0]).lower().removesuffix(".exe")
            if head in _RM_HEADS:
                targets += [(t, True) for t in toks[1:] if not t.startswith("-")]
            if head in _LINK_HEADS:
                targets += [(t, False) for t in _link_targets(toks)]
            if head == "find":
                targets += [(t, True) for t in _find_roots(toks)]
    targets += [(t, True) for t in _pipeline_delete_roots(c)]
    targets = list(dict.fromkeys(targets))
    if len(targets) > _MAX_TARGETS:   # each is looked up on disk: a list this long is not judged in bounded time
        raise _TooDeep("%d paths to delete, move, link or write" % len(targets))
    judged = set()
    for t0, deleting in targets:
        for t1 in (_glob_targets(t0, c.cwd) if deleting else [t0]):
            if (t1, deleting) in judged:
                continue
            judged.add((t1, deleting))
            if len(judged) > 2 * _MAX_TARGETS:
                raise _TooDeep("%d paths after globbing" % len(judged))
            for t in _win_forms(t1):
                if kit_protected(t, c.cwd):
                    block(KIT_MSG.format(path=t), "guard-config-write", t)
                elif kit_hardlinked(t, c.cwd):
                    block(KIT_LINK_MSG.format(path=t), "guard-config-write", t)
                elif deleting and _in_config_dir(t, c.cwd) and kit_contains(t, c.cwd):   # rm -rf <config dir>/plugins deletes the guards
                    block(KIT_GONE_MSG.format(path=t), "guard-config-write", t)


# H5: the top-level keys of the USER's settings.json / settings.local.json that the agent may change once the user approves
# the edit (ASK instead of DENY). Each is plain data that cannot run or load code, grant or remove a permission, or touch
# hooks, plugins, plugin options, env, MCP servers, the status line, API key helpers or hook policy. skillOverrides maps a
# skill name to a visibility state. Add a key only when the same is true of it; when in doubt, leave it out (outputStyle,
# theme, language and model are out: they change what the agent is told or which model judges, which is part of its controls).
SAFE_SETTINGS_KEYS = frozenset({"skillOverrides"})
SETTINGS_ASK_MSG = ("{path} is a Claude Code settings file, which the agent does not change on its own. This edit changes "
                    "{what}, which cannot run or load code or touch permissions, hooks, plugins, environment, MCP servers "
                    "or the status line. Approve it only if you asked for this change; everything else in the file you "
                    "edit by hand, with /config or /permissions.")
_SETTINGS_MAX = 1_000_000


def _strict_json(text):
    """json.loads that refuses what another parser might read differently: a repeated key (at any depth) and NaN / Infinity."""
    def pairs(items):
        d = {}
        for k, v in items:
            if k in d:
                raise ValueError("duplicate key")
            d[k] = v
        return d

    def const(x):
        raise ValueError(x)
    return json.loads(text, object_pairs_hook=pairs, parse_constant=const)


def _edited(text, old, new, replace_all):
    """text with one Edit applied as the Edit tool does (old must be found, once unless replace_all), else None."""
    if not (isinstance(old, str) and isinstance(new, str)) or not old or old == new:
        return None
    n = text.count(old)
    return text.replace(old, new) if n == 1 or (n > 1 and replace_all is True) else None


def _safe_settings_change(c, path):
    """The set of top-level keys this Edit / MultiEdit / Write changes in the user's settings file, when every one is in
    SAFE_SETTINGS_KEYS and both the current file and the resulting text are valid JSON objects; else None (DENY, as before).
    Only <claude config dir>/settings.json and settings.local.json qualify, reached without a symlink: a project's own
    .claude folder, the workbench folder, the corporate allowlist and the installed plugins never do. Never raises."""
    try:
        if c.tool not in ("Edit", "Write", "MultiEdit"):
            return None
        homes = [_wb.claude_home()] + [h for h in [_wb.installed_claude_home()] if h]
        files = {f(h) + "/" + n for h in homes for f in (norm, _as_written) for n in ("settings.json", "settings.local.json")}
        if norm(path, c.cwd) not in files or _as_written(path, c.cwd) not in files:
            return None
        real = os.path.realpath(os.path.abspath(os.path.expanduser(str(path).strip("\"'"))))
        if os.path.getsize(real) > _SETTINGS_MAX:
            return None
        with open(real, encoding="utf-8-sig") as fh:
            cur = fh.read().replace("\r\n", "\n")
        nl = lambda x: x.replace("\r\n", "\n") if isinstance(x, str) else x  # noqa: E731 - JSON ignores line endings
        ti = c.ti
        if c.tool == "Write":
            res = nl(ti.get("content"))
        else:
            edits = [ti] if c.tool == "Edit" else ti.get("edits")
            if not isinstance(edits, list) or not edits:
                return None
            res = cur
            for e in edits:
                if not isinstance(e, dict) or res is None:
                    return None
                res = _edited(res, nl(e.get("old_string")), nl(e.get("new_string")), e.get("replace_all"))
        if not isinstance(res, str):
            return None
        old, new = _strict_json(cur), _strict_json(res)
        if not (isinstance(old, dict) and isinstance(new, dict)):
            return None
        canon = lambda d, k: json.dumps(d[k], sort_keys=True) if k in d else None  # noqa: E731 - true != 1, unlike ==
        changed = {k for k in old.keys() | new.keys() if canon(old, k) != canon(new, k)}
        return changed if changed <= SAFE_SETTINGS_KEYS else None
    except Exception as e:
        log(f"settings change not judged safe: {e!r}"[:200])
        return None


KIT_DIR_MSG = ("{path} is a folder that holds the guards' own configuration (the settings files, the workbench folder or the "
               "installed plugins), and a tool that rewrites a whole tree would reach them. Name the files or the subfolder you mean.")


@_memo
def _kit_anchors():
    """The places kit_protected guards that can sit inside a folder: each config dir's settings files and workbench folder, and
    the workbench plugin folders found up to four levels under its plugins folder."""
    out = set()
    for h in [_wb.claude_home()] + [x for x in [_wb.installed_claude_home()] if x]:
        for f in (norm, _as_written):
            c = f(h)
            out |= {c + "/settings.json", c + "/settings.local.json", f(h / "workbench")}
            stack = [(c + "/plugins", 0)]
            while stack and len(out) < 400:
                d, depth = stack.pop()
                try:
                    entries = list(os.scandir(d))[:300]
                except OSError:
                    continue
                for e in entries:
                    if "workbench" in e.name.lower():
                        out.add(d + "/" + e.name)
                    elif depth < 3 and e.is_dir(follow_symlinks=False):
                        stack.append((d + "/" + e.name, depth + 1))
    return {norm(a) for a in out}


KIT_LINK_MSG = ("{path} is another name (a hard link) for one of the guards' own files, so writing it changes that file. "
                "The user edits those by hand, with /config or /permissions, or re-runs the workbench installer.")


KIT_GONE_MSG = ("{path} holds the guards' own files (the workbench plugins, the workbench folder or the settings files), and deleting or "
                "moving it switches the guards off. To refresh a stale plugin cache, use the `claude plugin` commands (update, or "
                "remove the plugin and add it again) or re-run the workbench installer, then restart Claude Code.")


def _kit_files():
    """The files that exist among the protected places: the settings files, and the files under the workbench folder and the
    workbench plugin folders (at most 5000)."""
    out = []
    for a in _kit_anchors():
        if os.path.isfile(a):
            out.append(a)
        for root, _dirs, names in os.walk(a):
            out += [os.path.join(root, n) for n in names]
            if len(out) > 5000:
                return out
    return out


def kit_hardlinked(path, cwd=""):
    r"""True when `path` is an existing file whose (device, inode) is a protected file's, whatever its spelling: a hard link made
    before this guard looked, \\?\Volume{id}\..., \\?\GLOBALROOT\..., an 8.3 short name. The settings files are compared on
    every write; the workbench folder and plugins (a walk) only when the file has a second name."""
    try:
        real = norm(path, cwd)
        st = os.stat(real)
        if not st.st_ino or not os.path.isfile(real):
            return False
        key = (st.st_dev, st.st_ino)
        same = lambda files: any((s.st_dev, s.st_ino) == key for s in (os.stat(f) for f in files if os.path.exists(f)))  # noqa: E731
        homes = [_wb.claude_home()] + [h for h in [_wb.installed_claude_home()] if h]
        if same(str(h / n) for h in homes for n in ("settings.json", "settings.local.json")):
            return True
        return st.st_nlink > 1 and same(_kit_files())
    except (OSError, ValueError):
        return False


def _in_config_dir(path, cwd=""):
    """True when `path` is a config dir or inside one. A delete of the home folder or a drive root is the rm-rf-root rule's, with its
    own message; this is for the folders in between (<config dir>/plugins)."""
    try:
        d = norm(path, cwd)
        return any(under(d, f(h)) for h in [_wb.claude_home()] + [x for x in [_wb.installed_claude_home()] if x] for f in (norm, _as_written))
    except (OSError, ValueError):
        return False


def kit_contains(path, cwd=""):
    """True when `path` is an existing folder with a kit-protected place at or below it (D6): ~/.claude, the home folder or a
    drive root holds the settings files, so ast-grep -U there could rewrite them. A project's own .claude/settings*.json is not
    looked for (a folder with one is common and the rewrite tools name a language)."""
    try:
        d = norm(path, cwd)
        return os.path.isdir(d) and any(under(a, d) for a in _kit_anchors())
    except (OSError, ValueError):
        return False


def _kit_write(c):
    safe = None
    for f in _win_forms(c.path) if c.path else ():
        if kit_protected(f, c.cwd):
            safe = _safe_settings_change(c, f)
            if safe is None:
                block(KIT_MSG.format(path=c.path), "guard-config-write", c.path)
        elif kit_hardlinked(f, c.cwd):
            block(KIT_LINK_MSG.format(path=c.path), "guard-config-write", c.path)
        elif kit_contains(f, c.cwd):
            if getattr(c, "named", True):
                block(KIT_DIR_MSG.format(path=c.path), "guard-config-write", c.path)
            else:   # a symbol edit that names no file works in its base folder: asked about, not refused (a project may sit in a home folder)
                ask(KIT_DIR_MSG.format(path=c.path), "guard-config-write", c.path)
    if safe is not None:
        ask(SETTINGS_ASK_MSG.format(path=c.path, what=("the setting " + ", ".join(sorted(safe))) if safe else "formatting only"),
            "guard-config-write", c.path)


# ── dispatch ─────────────────────────────────────────────────────────────────────────────────────────────────
def _packs():
    out = []
    for n in PACKS:
        try:
            out.append(importlib.import_module("rulepacks." + n))
        except Exception as e:
            log(f"ERROR pack {n} failed to load (fail-open, its rules are OFF): {e!r}"[:300])
    return out


def _run(fn, c):
    """Every rule is its own unit: a crash (a guard bug) is logged and skips only that rule. A deny (Decision) and the
    nest cap (_TooDeep) are BaseExceptions and pass straight through."""
    try:
        fn(c)
    except _Soft:
        pass   # it asked instead of refusing; the ask is collected
    except Exception as e:
        log(f"ERROR rule {getattr(fn, '__module__', '?')}.{getattr(fn, '__name__', '?')} skipped (fail-open): {e!r}"[:300])


def shell_checks(cmd, data, packs, depth=0):
    """The engine's own protection, then every pack's SHELL rules, on one command (Bash, PowerShell, or a git config
    value re-judged as shell)."""
    if len(cmd) > _MAX_CMD:
        raise _TooDeep("%d chars" % len(cmd))
    cmd = squash_runs(cmd)
    ps = data.get("tool_name") == "PowerShell"
    L = lex(cmd, ps)
    c = SimpleNamespace(cmd=cmd, data=data, ps=ps, cwd=data.get("cwd") or "", L=L, depth=depth, packs=packs,
                        doc=L.text(_doc),                                       # minus cat/tee doc bodies
                        live=L.text(lambda h: _doc(h) or (h.py and h.quoted)))  # and quoted python bodies (test data)
    _run(_kit_shell, c)
    for p in packs:
        for fn in getattr(p, "SHELL", ()):
            _run(fn, c)


def _tool_path(ti, cwd):
    p = ti.get("file_path") or ti.get("notebook_path") or ti.get("path") or ""
    if not isinstance(p, str):
        return ""
    if p and cwd and not os.path.isabs(p) and not p.startswith("~"):
        p = os.path.join(cwd, p)
    return p.replace("\\", "/")


_ROOT_KEYS = ("project_root", "cwd")
# A key that looks like a base folder but is not one the guard reads: the call asks (KIT_ROOT_MSG), because the guard cannot tell which
# folder a relative path in the call is read against.
_ROOT_LIKE = re.compile(r"(?i)root|workspace|work_?dir|working|(?:base|current|cur)_?(?:dir|path|folder)|directory|^dir$|folder|"
                        r"repo(?:sitory)?_?(?:path|dir)|project_?(?:dir|path|folder)")
KIT_ROOT_MSG = ("This edit names a base folder under `{key}`, which the guard does not read, so it cannot tell which files a relative "
                "path in it means. Approve only if that folder is not one that holds your settings files or the workbench files.")


def _edit_mcp_paths(ti, cwd):
    """([(path, named?)], [root keys the guard cannot read]) for an MCP edit tool: every file it names, absolute, from `path` (and the
    `path` of each edit of a multi-edit; nested lists and objects are searched three levels deep). tokensave has no root parameter: its
    relative paths are read against the folder the server was started in, taken here to be the session cwd. A `project_root` or `cwd`
    the CALL supplies is the model's word, so a relative path is judged against the session cwd AND against each supplied root, and a
    hit through any of them counts. A symbol edit (insert_at_symbol, replace_symbol, delete_symbol) may name no file: then each of
    those bases is judged itself, as a path that was not named (named? False). A root-like key that is not project_root or cwd is
    returned as unreadable."""
    found, roots, odd, stack = [], [], [], [(ti, 0)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _PATH_KEYS and isinstance(v, str) and v:
                    found.append(v)
                elif k in _PATH_KEYS and isinstance(v, list):
                    found += [x for x in v[:500] if isinstance(x, str) and x]
                elif k in _ROOT_KEYS and v not in (None, ""):
                    if isinstance(v, str):
                        roots.append(v)
                    else:
                        odd.append(k)
                elif isinstance(k, str) and _ROOT_LIKE.search(k) and isinstance(v, (str, list, dict)) and v:
                    odd.append(k)
                if depth < 3 and isinstance(v, (dict, list)):          # whatever the key: a path can sit under any of them
                    stack.append((v, depth + 1))
        elif isinstance(node, list) and depth < 3:
            stack += [(x, depth + 1) for x in node[:500] if isinstance(x, (dict, list))]
    if len(found) > _MAX_TARGETS:
        raise _TooDeep("%d paths in one edit call" % len(found))
    rooted = lambda r: os.path.join(cwd, r) if cwd and not os.path.isabs(r) and not r.startswith("~") else r  # noqa: E731
    bases = [b for b in dict.fromkeys([cwd, *map(rooted, roots)]) if b]
    paths = []
    for p in found:
        paths += [p] if os.path.isabs(p) or p.startswith("~") or not bases else [os.path.join(b, p) for b in bases]
    named = [(p.replace("\\", "/"), True) for p in dict.fromkeys(paths) if p]
    return named or [(b.replace("\\", "/"), False) for b in bases], list(dict.fromkeys(odd))


def _bash_mechanics(cmd):
    """Bash tool only, after every rule passed: the Git Bash `cd` with a backslash Windows path and unbalanced quotes
    are denied with the fix (never rewritten: a rewritten input would be judged by the permission rules in its new
    form)."""
    if re.search(r"\bcd\s+[A-Za-z]:\\[^\"']", cmd):
        fixed = re.sub(r"(\bcd\s+)([A-Za-z]:)((?:\\[^\s\"';|&]+)+)",
                       lambda m: m.group(1) + m.group(2) + m.group(3).replace("\\", "/"), cmd)
        if fixed != cmd:
            block("Git Bash strips backslashes from an unquoted Windows path (C:\\Users becomes C:Users). Re-run it "
                  "with forward slashes: " + fixed[:400], "cd-backslash")
    if not re.search(r"['\"`]|\$\(|<\(|<<", cmd):
        return
    try:
        bash = next((p for p in (r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash"))
                     if p and os.path.exists(p)), None)
        if not bash or os.path.basename(os.path.dirname(bash)).lower() == "system32":   # WSL launcher, not a shell
            return
        r = subprocess.run([bash, "-n"], input=cmd.encode("utf-8"), capture_output=True, timeout=BASH_N_TIMEOUT,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        err = (r.stderr or b"").decode("utf-8", "replace")
        if r.returncode and "unexpected EOF" in err:
            block("Unbalanced quotes; bash says: " + (err.strip().splitlines() or [""])[-1] + ". Write the script to a "
                  "file with the Write tool and run the file, or use a quoted heredoc (bash -s <<'EOF' ... EOF).",
                  "unbalanced-quotes")
    except subprocess.TimeoutExpired:
        log(f"HOOK-TIMEOUT bash -n exceeded {BASH_N_TIMEOUT}s; quote check skipped (fail-open)")
    except Decision:
        raise
    except Exception as e:
        log(f"quote check skipped: {e!r}")


def _evaluate(data):
    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else ""
    CTX.update(sid=str(data.get("session_id") or "-")[:8], tool=tool or "-", cwd=(cwd or "-").replace("\\", "/"),
               level="standard")
    CTX["level"] = guard_level()
    _ASKS.clear()
    for cache in (_LEXED, _WALKED, _PROSED, _WT, _RAWB):
        cache.clear()
    _WORK[0] = 0
    packs = _packs()
    if tool in ("Bash", "PowerShell"):
        cmd = ti.get("command") or ""
        if not isinstance(cmd, str):
            return
        shell_checks(cmd, data, packs)
        if tool == "Bash":
            _bash_mechanics(cmd)
    elif tool in WRITE_TOOLS + READ_TOOLS + OTHER_TOOLS or BROWSER_MCP.fullmatch(tool) or DB_MCP.fullmatch(tool) \
            or EDIT_MCP.fullmatch(tool):
        edit_mcp = bool(EDIT_MCP.fullmatch(tool))
        paths, odd = _edit_mcp_paths(ti, cwd) if edit_mcp else ([(_tool_path(ti, cwd) if tool not in OTHER_TOOLS else "", True)], [])
        for key in odd:
            ask(KIT_ROOT_MSG.format(key=str(key)[:40]), "guard-config-write", str(key)[:40])
        kind = "WRITE" if tool in WRITE_TOOLS or edit_mcp else "READ" if tool in READ_TOOLS else "TOOL"
        for path, named in paths or [("", True)]:
            c = SimpleNamespace(tool=tool, ti=ti, data=data, cwd=cwd, path=path, named=named, packs=packs)
            if kind == "WRITE":
                _run(_kit_write, c)
            for p in packs:
                for fn in getattr(p, kind, ()):
                    _run(fn, c)
    if _ASKS:
        raise Decision(_out("ask", " ".join(dict.fromkeys(_ASKS))))


def evaluate(data):
    """The decision for one PreToolUse event: a hookSpecificOutput dict ("deny" or "ask"), or None (no opinion)."""
    _MEMO[0] = {}
    try:
        return _judge(data)
    finally:
        _MEMO[0] = None


def _judge(data):
    try:
        _evaluate(data if isinstance(data, dict) else {})
    except Decision as d:
        return d.out
    except _Soft:   # a soft rule outside _run: its ask must not be lost
        return _out("ask", " ".join(dict.fromkeys(_ASKS)))
    except _TooDeep as e:
        try:
            block(DEEP_MSG, "nest-cap", f"limit {e}")
        except Decision as d:
            return d.out
    return None


def main():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
    except Exception as e:
        log(f"ERROR stdin parse failed: {e!r}")
        return 0
    try:
        out = evaluate(data)
    except Exception as e:   # fail open: a crashing guard must never block a legitimate tool call
        log(f"ERROR unhandled (fail-open): {e!r}"[:300])
        return 0
    if out and out["hookSpecificOutput"]["permissionDecision"] in ("deny", "ask"):   # never anything else
        sys.stdout.write(json.dumps(out) + "\n")
    return 0
