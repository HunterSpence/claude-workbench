#!/usr/bin/env python3
"""PreToolUse guard engine: one shell parse, two rule packs, fail-open.

Contract (pretooluse.py is the hook entry point):
  - stdin: the PreToolUse JSON. stdout: nothing (no opinion: the normal permission flow decides), or ONE
    hookSpecificOutput object whose permissionDecision is "deny" or "ask". This engine never answers "allow" and
    never rewrites a tool's input: an allow would let a call skip the permission rules, and a rewritten input would
    be judged by those rules in its new form. A fixable call is denied with the exact command to re-run.
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
import datetime
import importlib
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
CTX = {"sid": "-", "tool": "-", "cwd": "-"}
_ASKS = []


class Decision(BaseException):
    """Raised by block(). A BaseException, so no rule's fail-open `except Exception` swallows it."""
    def __init__(self, out):
        super().__init__("decision")
        self.out = out


def _redact(text):
    try:
        import secretscan
        for a, b in reversed(secretscan.scan_text(text)):
            text = text[:a] + "[REDACTED]" + text[b:]
    except Exception:
        pass
    return text


def log(msg):
    try:
        d = os.environ.get("GUARDS_LOG_DIR") or str(_wb.log_dir())
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "guards.log")
        if os.path.exists(p) and os.path.getsize(p) > LOG_MAX_BYTES:
            os.replace(p, p + ".1")   # keep one previous file
        with open(p, "a", encoding="utf-8") as f:
            f.write(_redact(f"{datetime.datetime.now().isoformat(timespec='seconds')} sid={CTX['sid']} "
                            f"tool={CTX['tool']} cwd={CTX['cwd']} {' '.join(str(msg).split())}") + "\n")
    except Exception:
        pass


def _out(decision, reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                   "permissionDecisionReason": reason}}


def block(reason, gid, detail=""):
    """Deny the call now."""
    log(f"BLOCK [{gid}] {(detail + ' | ' if detail else '')}{reason}"[:600])
    raise Decision(_out("deny", f"[workbench guard: {gid}] {reason}"))


def ask(reason, gid, detail=""):
    """Ask the user to confirm. Collected: it is returned only if no rule denies the call."""
    log(f"ASK [{gid}] {(detail + ' | ' if detail else '')}{reason}"[:600])
    _ASKS.append(f"[workbench guard: {gid}] {reason}")


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
_RUNNER = re.compile(r"(?i)(?<![\w.-])(ssh|bash|sh|zsh|dash|ksh|eval|su|pwsh|powershell|cmd|wsl|iex|"
                     r"invoke-expression)(?:\.exe)?(?![\w.-])")
_JOINER = re.compile(r"(?i)(?<![\w.-])(ssh|wsl|eval|pwsh|powershell|cmd)(?:\.exe)?(?![\w.-])")  # re-parse ALL their args
_SSH_WORD = re.compile(r"(?i)(?<![\w.-])ssh(?![\w.-])")
_VAR_HEAD = re.compile(r"""["']?(\$\{?\w+\}?)["']?(?=\s)(?!\s*=)""")   # `$RUN '...'`: a command held in a variable
_GIT_HOOK_NAME = (r"(?:pre-[\w-]+|post-[\w-]+|prepare-commit-msg|commit-msg|update|applypatch-msg|proc-receive|"
                  r"reference-transaction|push-to-checkout|sendemail-validate|fsmonitor-watchman|p4-[\w-]+)$")
_GIT_HOOK = re.compile(r"(?i)(?:^|[/\\])hooks[/\\]" + _GIT_HOOK_NAME)
_FS_WTGT = r"""(?:(?<![\d&<>])>>?|\btee\s+(?:-a\s+)?)\s*["']?([^\s"';&|<>()]+)"""   # a file the statement writes
_FS_PARSE_ONLY = re.compile(r"^\s*(?:ba|z|da)?sh\s+-n\b")
_HEAD_SKIP = re.compile(r"""^\s*[({!]*\s*(?:(?:\w+=(?:"[^"]*"|'[^']*'|\S*)\s*)|(?:sudo|time|nohup|exec|command|env|"""
                        r"""then|do|else|elif|if|while|until)\s+|timeout\s+(?:-\S+\s+)*\S+\s+)*""")
_LEXED, _WALKED, _PROSED, _LEX_NEST = {}, {}, {}, [0]
# Past this nesting (quotes / $( ) per walk, heredoc and runner-string re-lex levels), length or heredoc count the
# guard cannot judge a command in bounded time or stack, so it DENIES. Real commands sit far below these limits.
_MAX_NEST, _MAX_CMD, _MAX_HD = 32, 256_000, 64
DEEP_MSG = ("This command is too large or too deeply nested for the guard to judge (limits: %d nesting levels of quotes "
            "/ $( ) / heredocs / runner strings, %d KB, %d heredocs). Flatten it: write the script with the Write tool "
            "and run the file." % (_MAX_NEST, _MAX_CMD // 1000, _MAX_HD))


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
    __slots__ = ("segs", "bounds", "top", "subs", "spans", "tsubs", "notes", "st")


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
    return next(((a, b) for a, b in w.bounds if a <= pos < b), (pos, pos))


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


def _prose_texts(text, ps=False, remote=False, depth=0):
    """[(flat, remote?)] for text and, re-lexed recursively, every runner string in it (ssh '...' runs remotely)."""
    flat, inner = blank_prose(text, ps)
    out = [(flat, remote)]
    for s, r, p in inner:
        out += _prose_texts(s, p, remote or r, _deeper(depth))
    return out


def statements(c):
    """Every statement a shell runs in this command, prose blanked: [(statement, remote?)] across the top text,
    shell-run heredoc bodies and runner strings (ssh '...' is remote)."""
    out = []
    for t, rem in c.L.shell_texts():
        for flat, r in _prose_texts(t, c.ps, rem):
            out += [(s, r) for s in _walk(flat, c.ps).segs if s.strip()]
    return out


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
_REDIRECT = re.compile(r'(?<![<>=\-])>>?\|?\s*([^\s;&|<>()]+)')
_WRITER = re.compile(r'(?i)(?:^|[\s"\'(;&|`])(tee|tee-object|sed|perl|cp|mv|install|scp|rsync|copy-item|move-item|'
                     r'set-content|add-content|out-file|clear-content|dd)(?=\s)')
_PY_WRITE = re.compile(r"""(?i)\bopen\(\s*[rbuf]*["']([^"'\n]+)["']\s*,\s*(?:mode\s*=\s*)?[rbuf]*["'][rbt]*[wax+]"""
                       r"""|\(\s*[rbuf]*["']([^"'\n]+)["']\s*\)\s*\.\s*write_(?:text|bytes)\("""
                       r"""|\b(?:shutil\.(?:copy\w*|move)|os\.(?:replace|rename))\([^)\n]*,\s*[rbuf]*["']([^"'\n]+)["']""")


def write_targets(cmd, ps=False, remote=False, depth=0):
    """[(path, text before it, remote?)] for every file a shell write targets: redirects, tee / sed -i / perl -i / cp /
    mv / install / scp / rsync / dd of= / Set-Content / Add-Content / Out-File / Clear-Content / Copy-Item / Move-Item
    (-Destination), python open(<literal>, 'w') / Path(<literal>).write_text. Quoted prose writes nothing; runner
    strings and shell-run heredoc bodies are judged, remote when ssh carries them."""
    L, out = lex(cmd, ps), []
    for body, rem in L.bodies:
        out += write_targets(body, ps, remote or rem, _deeper(depth))
    flat, inner = blank_prose(L.top, ps, "words")      # a quoted path with a space in it is still a path
    for s, rem, p in inner:
        out += write_targets(s, p, remote or rem, _deeper(depth))
    cands = [(m.group(1), m.start()) for m in _REDIRECT.finditer(flat)
             if not re.search(r"<[A-Za-z/][^<>\s]*$", flat[:m.start()])]   # `<code>.env</code>` is markup
    for m in _WRITER.finditer(flat):
        rest = re.split(r"&&|\|\||[;\n|()]", flat[m.end():], maxsplit=1)[0]
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
    out += [(x, flat[:pos], remote) for t, pos in cands
            for x in {t.strip("\"'`"), re.sub(r"[\s._]+$", "", t.strip("\"'`"))} if x]
    if depth == 0:
        x = expand_vars(cmd)
        out += [(m.group(1) or m.group(2) or m.group(3), x[:m.start()], remote) for m in _PY_WRITE.finditer(x)]
    return out


# ── data arguments: a journal line or a commit message is data, not shell ─────────────────────────────────────
_TO_SHELL = re.compile(r"(?i)" + _PIPE_WRAP + r"(?:(?:ba|z|da|k)?sh|pwsh|powershell|iex|invoke-expression|"
                       r"python[\d.]*|node|xargs)\b|(?<![\w.-])(?:eval|source)\s|(?:^|[;&|(]\s*)\.\s+\S")
_DATA_ARG = re.compile(r"""(?:save_driver\.py["']?\s+(?P<f>--inbox-add)|"""
                       r"""(?<![\w.-])git\s+commit\b[^\n;&|"'#]*?\s(?P<g>-[A-Za-z]*m))\s*"""
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


def _raw_body(c):
    """The raw command minus provable prose (see raw_view)."""
    text = blank_data(c.doc, c.ps)
    w = _walk(text, c.ps)
    bounds = [(a, b) for a, b in w.bounds if text[a:b].strip()]
    segs = [(text[a:b], {os.path.basename(f.strip("\"'")) for f in _fs_wtargets(text[a:b])}, _head(text[a:b]))
            for a, b in bounds]
    edits = []
    for a, b in bounds:
        seg, h = text[a:b], _head(text[a:b])
        if re.search(r"\$\(|`|<\(", seg):
            continue                                   # a substitution runs: keep it all
        if h in _PROSE_HEADS and not (h == "rg" and re.search(r"\s--pre(?:-glob)?(?:=|\s|$)", seg)) \
                and not (h == "printf" and re.search(r"(?<![\w-])-v(?![\w-])", seg)):   # rg --pre runs a program
            nxt = text[b:b + 3].lstrip(" \t")
            targets = [f.strip("\"'") for f in _fs_wtargets(seg)]
            if (nxt.startswith("|") and not nxt.startswith("||")) or (targets and _ran(targets, segs, text)):
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
READ_TOOLS = ("Read", "Grep", "Glob")
OTHER_TOOLS = ("WebFetch", "Agent")
# Browser MCP servers (playwright, chrome-devtools, puppeteer, plugin-namespaced ones): their URL inputs go to TOOL rules.
BROWSER_MCP = re.compile(r"mcp__.*([Pp]laywright|[Cc]hrome|[Pp]uppeteer|[Bb]rowser).*")
_RM_HEADS = {"rm", "rmdir", "remove-item", "ri", "rd", "del", "erase", "unlink", "mv", "move-item", "rename-item"}
_KIT_RAW = re.compile(r"(?i)(?:^|[/\\])\.claude[/\\]+(?:settings(?:\.local)?\.json$|workbench(?:[/\\]|$)|"
                      r"plugins[/\\].*workbench)")
KIT_MSG = ("{path} configures Claude Code or the workbench guards (settings files, the workbench folder, the "
           "corporate allowlist, the installed plugins). The agent does not change the controls that apply to it: "
           "the user edits these by hand, with /config or /permissions, or re-runs the workbench installer.")


def norm(p, cwd=""):
    """An absolute, normalised, case-folded path for comparisons; a Git Bash /tmp or /c/ path is mapped first."""
    p = os.path.expanduser(str(p).strip("\"'"))
    if os.name == "nt":
        m = re.match(r"^/([A-Za-z])(/.*)?$", p)
        if re.match(r"^/tmp(/|$)", p):
            p = _tmpdir() + p[4:]
        elif m:
            p = f"{m.group(1)}:{m.group(2) or '/'}"
    if cwd and not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.normcase(os.path.realpath(os.path.abspath(p))).replace("\\", "/")


def under(path, root):
    """True when path (normalised) is root or inside it: a directory prefix, never a substring."""
    return path == root or path.startswith(root.rstrip("/") + "/")


def _as_written(p, cwd=""):
    """norm() without following symlinks: the path as the command names it."""
    p = os.path.expanduser(str(p).strip("\"'"))
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


_LINK_HEADS = {"ln", "mklink", "new-item", "ni", "cp"}


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
    if h == "ln":
        return [a for a in args if not a.startswith("-")]
    return []


_INSTALLER = re.compile(r"(?i)bootstrap[/\\]+(?:un)?install\.(?:py|sh)\b")


def _kit_shell(c):
    if _INSTALLER.search(c.cmd):   # it rewrites settings, the allowlist and the plugins: only with the user's OK
        ask("This runs the workbench installer, which changes the controls that apply to the agent (settings, the "
            "approved git hosts, the plugins). Approve only if you asked for this install, and read its options.",
            "installer-run")
    targets = [t for t, _b, rem in write_targets(c.cmd, c.ps) if not rem]
    for seg, rem in statements(c):
        if rem:
            continue
        toks = _cmd_toks(seg)
        head = os.path.basename(toks[0]).lower().removesuffix(".exe") if toks else ""
        if head in _RM_HEADS:
            targets += [t for t in toks[1:] if not t.startswith("-")]
        if head in _LINK_HEADS:
            targets += _link_targets(toks)
    for t0 in targets:
        for t in _win_forms(t0):
            if kit_protected(t, c.cwd):
                block(KIT_MSG.format(path=t), "guard-config-write", t)


def _kit_write(c):
    for f in _win_forms(c.path) if c.path else ():
        if kit_protected(f, c.cwd):
            block(KIT_MSG.format(path=c.path), "guard-config-write", c.path)


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
    except Exception as e:
        log(f"ERROR rule {getattr(fn, '__module__', '?')}.{getattr(fn, '__name__', '?')} skipped (fail-open): {e!r}"[:300])


def shell_checks(cmd, data, packs, depth=0):
    """The engine's own protection, then every pack's SHELL rules, on one command (Bash, PowerShell, or a git config
    value re-judged as shell)."""
    if len(cmd) > _MAX_CMD:
        raise _TooDeep("%d chars" % len(cmd))
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
    CTX.update(sid=str(data.get("session_id") or "-")[:8], tool=tool or "-", cwd=(cwd or "-").replace("\\", "/"))
    _ASKS.clear()
    for cache in (_LEXED, _WALKED, _PROSED):
        cache.clear()
    packs = _packs()
    if tool in ("Bash", "PowerShell"):
        cmd = ti.get("command") or ""
        if not isinstance(cmd, str):
            return
        shell_checks(cmd, data, packs)
        if tool == "Bash":
            _bash_mechanics(cmd)
    elif tool in WRITE_TOOLS + READ_TOOLS + OTHER_TOOLS or BROWSER_MCP.fullmatch(tool):
        path = _tool_path(ti, cwd) if tool not in OTHER_TOOLS else ""
        c = SimpleNamespace(tool=tool, ti=ti, data=data, cwd=cwd, path=path, packs=packs)
        if tool in WRITE_TOOLS:
            _run(_kit_write, c)
        kind = "WRITE" if tool in WRITE_TOOLS else "READ" if tool in READ_TOOLS else "TOOL"
        for p in packs:
            for fn in getattr(p, kind, ()):
                _run(fn, c)
    if _ASKS:
        raise Decision(_out("ask", " ".join(dict.fromkeys(_ASKS))))


def evaluate(data):
    """The decision for one PreToolUse event: a hookSpecificOutput dict ("deny" or "ask"), or None (no opinion)."""
    try:
        _evaluate(data if isinstance(data, dict) else {})
    except Decision as d:
        return d.out
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
