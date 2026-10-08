"""Generic rule pack: safety rules that mean the same thing on every machine.

Guard ids (each deny names one):
  force-push-main     force-push (--force, --force-with-lease, -f, +refspec, --mirror, a +wildcard refspec, --all
                      with force) that can rewrite main/master, or a bare force-push while on main/master
  delete-main         deleting remote main/master (push :main, --delete, gh api -X DELETE .../refs/heads/main)
  push-default-branch any push whose destination is main/master, the remote HEAD or the remote's default branch
  backdate            a commit with a forged date (--date, GIT_AUTHOR_DATE / GIT_COMMITTER_DATE)
  no-verify           skipping git hooks (--no-verify, git commit -n, core.hooksPath=/dev/null)
  git-exec-config     a git config value pointing hook/config execution at an absolute path outside the repo
  env-write           writing a .env file (examples, samples, templates and temp dirs are fine)
  secret-path         reading, copying, uploading or writing well-known credential files (SSH keys, cloud CLI
                      credentials ...), and Grep/Glob inside credential folders
  active-context-write  writing the KB's active-context.md directly (the save driver is its only writer)
  claude-json-write   writing ~/.claude.json (Claude Code's own state file)
  rm-rf-root          recursive delete of /, a drive root, a home directory or the Claude config directory
  xargs-python-repl   `xargs ... python -` (every input line becomes a looping REPL)
  runaway-output      a background task's output log past 1 GB and growing
  agent-fork          a forked subagent (fresh subagents only: a fork inherits the whole context and fails inside
                      workflow workers)
  webfetch-secret     a WebFetch URL that carries a credential-shaped value (it would leave in the request)
  encoded-command     a pwsh / powershell -EncodedCommand (any prefix, -ec, with - -- or /) whose value cannot be
                      decoded
  msys-path           on Windows, a Write/Edit/NotebookEdit path written the MSYS or WSL way (/c/..., /mnt/c/...):
                      the file tools take C:/...
  browser-url         a browser MCP tool (playwright, chrome-devtools, ...) sent to a URL with a credential-shaped
                      value or user:password@ in it, or to a file:// URL of a credential file
"""
import glob
import json
import os
import re

import engine as E
import _wb

MAIN = r"(?<![\w.-])(master|main)(?![\w./-])"

ENV_MSG = ("Writing {path} (an env file) needs the user's explicit request in this session. If they asked, tell "
           "them this hook blocked it and give them the exact command so they can run it themselves.")
AC_MSG = ("Do not write the knowledge base's active-context.md directly: parallel sessions overwrite each other "
          "and the loser never sees an error. Mid-session, journal one line with /workbench-kb:save's "
          "`save_driver.py --inbox-add \"<entry>\"`. During a save, the full rewrite goes through "
          "`save_driver.py --ac-write <draft> --base <ac_base>` (a locked 3-way merge).")
CLAUDE_JSON_MSG = ("~/.claude.json is Claude Code's own state file: the running app rewrites it, so a hand write races "
                   "it and can corrupt it. Use `claude mcp add/remove`, `claude config`, or /config. Reading it is fine.")
SECRET_MSG = ("{path} holds credentials. Reading, copying or uploading it puts a secret into the transcript or "
              "somewhere it does not belong. Use the tool that consumes it (ssh, git, gh, aws, az, gcloud, kubectl, "
              "docker) instead. If the user needs the value, they open the file themselves.")

# Well-known credential files. A user adds their own as regexes in corporate-allowlist.json "extra_secret_paths".
SECRET_PATHS = [
    r"\.ssh[/\\]+id_[A-Za-z0-9_-]+(?!\.pub)(?![\w.-])",                       # SSH private keys (not *.pub)
    r"\.ssh[/\\]+[\w.-]+\.(?:pem|key|ppk)(?![\w.-])",
    r"\.aws[/\\]+credentials(?![\w.-])",
    r"\.azure[/\\]+(?:accessTokens\.json|msal_token_cache\.[\w.]+|service_principal_entries\.json)",
    r"\.config[/\\]+gcloud[/\\]+(?:credentials\.db|access_tokens\.db|application_default_credentials\.json|"
    r"legacy_credentials)",
    r"\.config[/\\]+gh[/\\]+hosts\.ya?ml",
    r"\.docker[/\\]+config\.json",
    r"\.kube[/\\]+config(?![\w.-])",
    r"(?:^|[/\\\s\"'=:])[._]netrc(?![\w.-])",
    r"\.git-credentials(?![\w.-])",
    r"\.gnupg[/\\]+(?:private-keys-v1\.d|secring\.gpg)",
    r"\.claude[/\\]+\.credentials\.json",
]
# Commands that USE a credential file without printing it. Anything else naming one (cat, cp, scp, curl -F @..., grep,
# Get-Content, python ...) is treated as a read.
# git, gh, docker, echo and printf are NOT here: each can print or upload a file it names (git diff --no-index, gh gist
# create, docker run -v, echo "$(cat ...)").
SAFE_USERS = {"ssh", "ssh-add", "ssh-keygen", "ssh-copy-id", "aws", "az", "gcloud", "kubectl", "helm", "ls", "dir",
              "get-childitem", "gci", "stat", "test", "[", "chmod", "chown", "icacls", "rm", "remove-item", "del"}
# Folders that hold nothing but credentials: Grep and Glob inside them are reads of credentials.
SECRET_DIRS = re.compile(r"(?i)(?:^|/)(?:\.ssh|\.aws|\.azure|\.docker|\.kube|\.gnupg|\.config/+gcloud|\.config/+gh)"
                         r"(?:/|$)|(?:^|/)[._]netrc$|(?:^|/)\.git-credentials$")   # matched on forward-slash paths


def _secret_rx():
    extra = []
    try:
        with open(_wb.workbench_home() / "corporate-allowlist.json", encoding="utf-8-sig") as f:
            extra = [x for x in (json.load(f).get("extra_secret_paths") or []) if isinstance(x, str)]
    except (OSError, ValueError, AttributeError):
        pass
    pats = []
    for p in SECRET_PATHS + extra:
        try:
            pats.append(re.compile(p, re.I))
        except re.error:
            E.log(f"ERROR extra_secret_paths entry is not a valid regex, skipped: {p!r}")
    return pats


def _secret_hit(text, rx=None):
    for r in rx or _secret_rx():
        m = r.search(text or "")
        if m:
            return m.group(0).strip("\"'=: ")
    return None


def _env_hit(t, cwd):
    if not re.search(r'(^|[\s/\\"\'])\.env(\.[A-Za-z0-9_.-]+)?([\s"\']|$)', t, re.I):   # NTFS: .ENV = .env
        return False
    if t.lower().endswith((".env.example", ".env.sample", ".env.template")):
        return False
    try:   # a scratch file in the temp directory is fine: normalised first, then a directory prefix, never a substring
        p = E.norm(t, cwd)
        return not any(E.under(p, E.norm(d)) for d in {E._tmpdir(), E.tempfile.gettempdir()})
    except (OSError, ValueError):
        return True


def _ac_hit(t, cwd):
    p = os.path.expanduser(t.strip("\"'"))
    if not re.search(r"(?:^|[/\\])active-context\.md$", p, re.I):
        return False
    kb = E.norm(str(_wb.kb_root()))
    full = E.norm(p, cwd)
    tail = "/".join(p.replace("\\", "/").split("/")[-2:]).lower()
    return full == kb + "/active-context.md" or tail == os.path.basename(kb).lower() + "/active-context.md"


def _claude_json_hit(t, cwd):
    return bool(re.search(r"(?i)(?:^|[/\\])\.claude\.json$", t))


# (guard id, matcher(path, cwd), message): one table for shell writes and file tools.
PROTECTED = (
    ("env-write", _env_hit, ENV_MSG),
    ("active-context-write", _ac_hit, AC_MSG),
    ("claude-json-write", _claude_json_hit, CLAUDE_JSON_MSG),
)


# ── shell rules ──────────────────────────────────────────────────────────────────────────────────────────────
def protected(c):
    rx = _secret_rx()
    for t0, _before, rem in E.write_targets(c.cmd, c.ps):
        for t in E._win_forms(t0):
            for gid, hit, msg in PROTECTED:
                if hit(t, "" if rem else c.cwd):
                    E.block(msg.format(path=t), gid, t)
            if _secret_hit(t, rx):
                E.block(SECRET_MSG.format(path=t), "secret-path", t)


def secret_read(c):
    rx = _secret_rx()
    for seg, _ in E.statements(c):
        hit = _secret_hit(seg, rx)
        if hit and E._head(seg) not in SAFE_USERS:
            E.block(SECRET_MSG.format(path=hit), "secret-path", seg[:120])
    for h in c.L.hd:   # a python / node body this command runs is code, not prose
        if h.run == "code" and h.b is not None:
            hit = _secret_hit(h.body, rx)
            if hit:
                E.block(SECRET_MSG.format(path=hit), "secret-path", "code body")


def git_config(c):
    """An absolute hooksPath / include.path / templateDir moves git's execution outside the repo, where no guard sees
    what runs. Every other executable config value is judged as shell by every rule (depth-capped)."""
    if c.depth >= 3:
        return
    for k, v in E.git_config_pairs(c.cmd, c.ps):
        kl = k.lower()
        if v and v != "/dev/null" and (kl in ("core.hookspath", "include.path", "init.templatedir", "git_template_dir")
                                       or (kl.startswith("includeif.") and kl.endswith(".path"))) \
                and re.match(r"(?:~|/(?!dev/null\b)|\\\\|[A-Za-z]:[\\/])", v):
            E.block(f"git -c {k}={v} points git's hook or config execution at an absolute path outside the repo, "
                    "where no guard can see what runs. Use the repo's own hooks directory (a relative "
                    "core.hooksPath such as .husky), or run the step directly.", "git-exec-config", kl)
        if v and not E.GIT_NONEXEC.match(k):
            E.shell_checks(v, c.data, c.packs, c.depth + 1)


def _default_branches(cwd):
    """main, master, HEAD, plus the remote default branch git already knows locally (refs/remotes/origin/HEAD)."""
    names = {"main", "master", "HEAD"}
    if cwd and os.path.isdir(cwd):
        try:
            r = E.subprocess.run(["git", "-C", cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                                 capture_output=True, text=True, timeout=3,
                                 creationflags=getattr(E.subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
            if r.count("/") >= 1:
                names.add(r.split("/", 1)[1])
        except Exception as e:
            E.log(f"default-branch lookup skipped: {e!r}")
    return names


def _current_branch(cwd):
    if not (cwd and os.path.isdir(cwd)):
        return ""
    try:
        return E.subprocess.run(["git", "-C", cwd, "symbolic-ref", "--short", "HEAD"], capture_output=True, text=True,
                                timeout=3, creationflags=getattr(E.subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    except Exception as e:
        E.log(f"current-branch lookup skipped: {e!r}")
        return ""


def _push_dest(spec, cwd):
    """The remote branch a refspec writes: `src:dst` -> dst (`x:HEAD` = the remote's HEAD), `x` -> x, a bare `HEAD`
    -> the current branch; refs/heads/ dropped; None for a delete (`:branch`, judged by delete-main)."""
    spec = spec.strip("\"'").lstrip("+").rstrip("\"')]}\\;,")   # code around it: `...push origin main')"`
    if ":" in spec:
        src, dst = spec.split(":", 1)
        return re.sub(r"^refs/heads/", "", dst) if src else None
    if spec in ("HEAD", "@"):
        return _current_branch(cwd) or None
    return re.sub(r"^refs/heads/", "", spec)


def push(c):
    """Force-push / +refspec / remote delete of main or master, and any push whose destination is the default
    branch, judged per push statement on the prose-blanked statements (commit messages, echo/grep arguments and
    cat/tee heredocs are data; bash -c / sh -c / eval / pwsh -Command / cmd /c payloads are judged), with a flag held
    in a variable this command assigned expanded."""
    # Both views (see engine.raw_view): a push hidden in python -c / node -e / a written-then-run file is judged too.
    live = E.expand_vars("\n".join(seg for seg, _ in E.statements(c)) + "\n" + E.raw_view(c))
    if None in E.live_encoded(c):
        E.block("This runs a PowerShell -EncodedCommand (or a prefix of it) whose payload the guard cannot decode. "
                "Run the command as plain text so it can be checked.", "encoded-command", c.cmd[:120])
    for m in re.finditer(r"\bgit\b[^\n;|&]*\bpush\b[^\n;|&]*", live):
        seg = m.group(0)
        forced = re.search(r"(--force(?:-with-lease|-if-includes)?\b|\s-(?!-)[a-eg-z]*f[a-z]*\b)", seg)
        to_main = re.search(MAIN, seg)
        if forced and to_main:
            E.block("Force-push to main/master is blocked, --force-with-lease included. Push to a feature branch and "
                    "merge through review.", "force-push-main", seg[:120])
        if re.search(r"(?<![\w-])--mirror\b", seg):
            E.block("git push --mirror force-updates and deletes every remote branch, main included. Push the branches "
                    "you mean by name.", "force-push-main", seg[:120])
        if re.search(r"(?:^|\s)[\"']?\+[^\s\"']*\*", seg) or (forced and re.search(r"(?<![\w-])--all\b", seg)):
            E.block("A forced push of every branch (a +wildcard refspec, or --all with force) rewrites main/master "
                    "too. Push the branches you mean by name, without force.", "force-push-main", seg[:120])
        ptoks = seg.split()
        if re.search(r"\+\S*:(refs/heads/)?(master|main)(?![\w./-])", seg) or ("push" in ptoks and any(
                re.fullmatch(r"\+(?:refs/heads/)?(?:master|main)", t.strip("\"'"))
                for t in ptoks[ptoks.index("push") + 1:])):
            E.block("Force-push to main/master via a +refspec is blocked: a leading + on the refspec IS --force.",
                    "force-push-main", seg[:120])
        if re.search(r"(\s:(refs/heads/)?(master|main)(?![\w./-])|(--delete|\s-d\b)[^\n]*" + MAIN + ")", seg):
            E.block("Deleting remote main/master is blocked (push :main, --delete and -d all remove the branch).",
                    "delete-main", seg[:120])
        try:
            args = [t for t in ptoks[ptoks.index("push") + 1:] if not t.startswith("-")]
        except ValueError:
            args = []
        deleting = re.search(r"(?<![\w-])(?:--delete|-d)(?![\w-])", seg)
        if not deleting and not forced and not re.search(r"(?<![\w-])--tags(?![\w-])", seg):   # forced: rules above
            defaults = _default_branches(c.cwd)
            dests = [_push_dest(a, c.cwd) for a in args[1:]] if args[1:] else [_current_branch(c.cwd)]
            hit = next((d for d in dests if d and d in defaults), None)
            if hit:
                E.block(f"Pushing to {hit} (a default branch) is blocked: push a feature branch "
                        "(`git push <remote> <feature-branch>`) and open a pull request.", "push-default-branch", seg[:120])
        if forced and not to_main:
            if len(args) <= 1 and c.cwd and os.path.isdir(c.cwd):   # no refspec: the CURRENT branch is pushed
                try:
                    cur = E.subprocess.run(["git", "-C", c.cwd, "symbolic-ref", "--short", "HEAD"],
                                           capture_output=True, text=True, timeout=3,
                                           creationflags=getattr(E.subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
                except Exception as e:
                    E.log(f"bare force-push branch check skipped: {e!r}")
                    cur = ""
                if cur in ("master", "main"):
                    E.block(f"Force-push blocked: no refspec given and the current branch is {cur}, so a bare "
                            f"force-push rewrites {cur}.", "force-push-main", seg[:120])
    for m in re.finditer(r"\bgh\s+api\b[^\n;|&]*", live):
        g = m.group(0)
        if re.search(r"(?i)(?:-X|--method)[\s=]*DELETE\b", g) and re.search(r"refs/heads/(master|main)(?![\w./-])", g):
            E.block("Deleting remote main/master through the API is blocked.", "delete-main", g[:120])


def backdate(c):
    if re.search(r"GIT_(AUTHOR|COMMITTER)_DATE\s*=", E.blank_data(c.live, c.ps)) or \
            any(re.search(r"git\s+commit[^\n]*\s--date[= ]", f) for f, _ in E._prose_texts(c.live, c.ps)):
        E.block("Never backdate a commit. A commit timestamp is a record, not a statement: a forged one corrupts every "
                "'what changed when' audit. Commit with the real time and explain the history in the message.",
                "backdate")


_VALUE_FLAGS = "mFCctSu"   # git commit short flags that take a value (the rest of the cluster is that value)


def no_verify(c):
    for k, v in E.git_config_pairs(c.cmd, c.ps):
        if k.lower() == "core.hookspath" and v.strip().lower() in ("", "/dev/null", "nul", "/dev/null/"):
            E.block("Pointing core.hooksPath at nothing skips the repository's git hooks. Fix what the hook "
                    "reports instead.", "no-verify", f"{k}={v}")
    for flat, _ in E._prose_texts(E.blank_data(c.live, c.ps), c.ps):
        for seg in E._walk(flat, c.ps).segs:
            if E._head(seg) != "git":
                continue
            toks, k = E.git_sub(seg)
            if k is None:
                continue
            if any(re.fullmatch(r"--no-verify", t.strip("\"'")) for t in toks[k + 1:]):
                E.block("--no-verify skips the repository's git hooks (lint, tests, secret scans). Fix what the hook "
                        "reports instead.", "no-verify", seg[:120])
            if toks[k] == "commit":
                for t in toks[k + 1:]:
                    if re.fullmatch(r"-[A-Za-z]+", t):
                        for ch in t[1:]:
                            if ch in _VALUE_FLAGS:
                                break
                            if ch == "n":
                                E.block("git commit -n is --no-verify: it skips the repository's git hooks. Fix what "
                                        "the hook reports instead.", "no-verify", seg[:120])


_RM_HEADS = {"rm", "rmdir", "remove-item", "ri", "rd", "del", "erase"}
_RECURSIVE = re.compile(r"(?i)(?<!\S)(?:--recursive|/s|-r(?:e(?:c(?:u(?:r(?:s(?:e)?)?)?)?)?)?)(?!\S)|"
                        r"(?<!\S)-[fFrRiIvd]*[rR][fFrRiIvd]*(?!\S)")
_DANGER = re.compile(r"(?i)^(?:|~|\$home|\$\{home\}|%userprofile%|\$env:userprofile|\$\{env:userprofile\}|"
                     r"%systemdrive%|%homedrive%|\$env:systemdrive|\$env:homedrive|[a-z]:|/[a-z]|/mnt/[a-z]|"
                     r"/home|/users|/root|/etc|/usr|/var|/boot|/opt|"
                     r"(?:/home|/users|[a-z]:/users|/[a-z]/users|/mnt/[a-z]/users)/[^/]+|"
                     r"(?:~|\$home|\$\{home\}|%userprofile%|\$env:userprofile)/\.claude)$")


def _danger_target(tok):
    t = tok.strip("\"'").replace("\\", "/")
    while re.search(r"/\*?$|/\.$", t) and t not in ("/",):
        t = re.sub(r"(?:/\*|/\.|/)$", "", t)
    t = "" if t == "/" else t
    if _DANGER.match(t):
        return True
    try:   # only an absolute or ~ path: a relative one would resolve against the HOOK's cwd, not the shell's
        full = E.norm(t) if t.startswith("~") or os.path.isabs(t) else None
    except Exception:
        full = None
    return bool(full) and full in (E.norm("~"), E.norm(str(_wb.claude_home())))


def rm_root(c):
    for seg, _ in E.statements(c):
        if E._head(seg) not in _RM_HEADS:
            continue
        rest = E._HEAD_SKIP.sub("", seg, 1).split()[1:]
        if "--no-preserve-root" in rest:
            E.block("rm --no-preserve-root is blocked: it exists only to delete /.", "rm-rf-root", seg[:120])
        if not _RECURSIVE.search(" ".join(rest)):
            continue
        for t in rest:
            if (not t.startswith("-") or t in ("-",)) and not re.fullmatch(r"(?i)/[sq]", t) and _danger_target(t):
                E.block(f"Recursive delete of {t} is blocked: it targets a filesystem root, a home directory or the "
                        "Claude config directory. Delete the specific subdirectory you mean.", "rm-rf-root", seg[:120])


def xargs_python(c):
    if re.search(r"\bxargs\b[^\n;&|]*\bpython[\d.]*(?:\.exe)?\s+-(?:\s|$)", c.L.top):
        E.block("`xargs ... python -` turns every input line into a python REPL that can loop forever. Give python the "
                "script on stdin (python - <<'PY' ... PY) or as a file, and the values as arguments.",
                "xargs-python-repl")


def runaway(c):
    """A looping background command can grow its task log without bound. For every extra GB, deny ONE shell call with
    the fix, so the next call (the kill) goes through."""
    sid = str(c.data.get("session_id") or "")
    if not sid or c.depth:
        return
    for f in glob.glob(os.path.join(E._tmpdir(), "claude", "*", glob.escape(sid), "tasks", "*.output")):
        try:
            gb = os.path.getsize(f) >> 30
            seen = 0
            if os.path.exists(f + ".warned"):
                with open(f + ".warned") as r:
                    seen = int(r.read() or 0)
        except (OSError, ValueError):
            continue
        if gb > seen:
            with open(f + ".warned", "w") as w:
                w.write(str(gb))
            E.block(f"A background task's output is {gb} GB and growing ({f}): a looping command is filling the disk. "
                    "Kill its whole process tree (Windows: taskkill /T /F /PID <pid>; Linux: kill -- -<pgid>), then "
                    "delete that file.", "runaway-output")


SHELL = (git_config, protected, secret_read, push, backdate, no_verify, rm_root, xargs_python, runaway)


# ── file tools ───────────────────────────────────────────────────────────────────────────────────────────────
def write_tool(c):
    raw = str(c.ti.get("file_path") or c.ti.get("notebook_path") or "")
    m = re.match(r"^/(?:mnt/)?([A-Za-z])(/.*)?$", raw)
    if os.name == "nt" and m:
        E.block(f"{raw} is an MSYS/WSL-style path; on Windows the file tools need the drive form: use "
                f"{m.group(1).upper()}:{m.group(2) or '/'} (C:/... with forward slashes).", "msys-path", raw)
    if not c.path:
        return
    rx = _secret_rx()
    for f in E._win_forms(c.path):
        for gid, hit, msg in PROTECTED:
            if hit(f, c.cwd):
                E.block(msg.format(path=c.path), gid, c.path)
        if _secret_hit(f, rx):
            E.block(SECRET_MSG.format(path=c.path), "secret-path", c.path)


def read_tool(c):
    """Read: a credential file. Grep / Glob: a search rooted in, or reaching into, a credential folder or file."""
    if c.path and _secret_hit(c.path):
        E.block(SECRET_MSG.format(path=c.path), "secret-path", c.path)
    if c.tool in ("Grep", "Glob"):
        pattern = str(c.ti.get("glob") or "") + " " + str(c.ti.get("pattern") or "" if c.tool == "Glob" else "")
        for cand in [c.path] + [os.path.join(c.path or ".", p) for p in pattern.split()]:
            if cand and (SECRET_DIRS.search(cand.replace("\\", "/").rstrip("/")) or _secret_hit(cand)):
                E.block(SECRET_MSG.format(path=cand), "secret-path", cand)


def agent_fork(c):
    if c.tool == "Agent" and str(c.ti.get("subagent_type") or "").lower() == "fork":
        E.block("Forked subagents are not used here: spawn a fresh subagent (for example general-purpose) and pass "
                "the context it needs in the prompt.", "agent-fork")


def webfetch_secret(c):
    if c.tool != "WebFetch":
        return
    import secretscan   # scripts/ is on sys.path (engine adds it)
    found = secretscan.findings(str(c.ti.get("url") or ""))
    if found:
        E.block(f"This URL carries a credential-shaped value ({found[0]['match']}), which would leave in the request "
                "and in proxy logs. Fetch without it, or let the user run the authenticated call themselves.",
                "webfetch-secret")


def browser_url(c):
    if not E.BROWSER_MCP.fullmatch(c.tool):
        return
    import secretscan
    from urllib.parse import unquote, urlsplit
    for key in ("url", "uri", "href"):
        url = str(c.ti.get(key) or "").strip()
        if not url:
            continue
        found = secretscan.findings(url)
        parts = urlsplit(url)
        if found or (parts.scheme in ("http", "https", "ws", "wss") and parts.password):
            E.block("This browser URL carries a credential (a token-shaped value or user:password@), which would land "
                    "in browser history, logs and the page. Open it without the credential; the user signs in "
                    "themselves.", "browser-url")
        if parts.scheme == "file":
            path = unquote(parts.path)
            path = path[1:] if re.match(r"^/[A-Za-z]:", path) else path
            if _secret_hit(path):
                E.block(SECRET_MSG.format(path=path), "browser-url", path)


WRITE = (write_tool,)
READ = (read_tool,)
TOOL = (agent_fork, webfetch_secret, browser_url)
