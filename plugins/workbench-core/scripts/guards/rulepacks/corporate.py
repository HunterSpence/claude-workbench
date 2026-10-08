"""Corporate rule pack: company code goes only to approved hosts, nothing is published, messages are confirmed.

ON by default. Its settings live in <claude config dir>/workbench/corporate-allowlist.json (the installer writes it;
the engine refuses agent writes into the workbench folder that it can recognise; a program that builds the path at run
time is not seen). A missing or unreadable file means the defaults: ON, no approved hosts, so every push to a remote
host is refused until the user adds hosts. So does a CLAUDE_CONFIG_DIR that differs from the one the installer
recorded (see _wb.config_redirected).
Known limits: see "_known_limits" in corporate-allowlist.template.json.
"enabled": false turns the pack off. Keys:
  enabled               default true
  git_remote_hosts      hosts code may be pushed to: exact host names, case-insensitive (list each subdomain and each
                        ssh alias). Pushes to local paths and file:// are refused.
  upload_hosts          extra hosts that file uploads (curl -T, -d @file, -F file=@...) may go to (git hosts count too)
  block_public_repos    default true
  send_endpoints        extra regexes for HTTP endpoints that send a message (added to the defaults below)
  extra_secret_paths    extra credential-file regexes (read by the generic pack's secret-path rule)

Guard ids:
  public-repo             gh/glab repo create --public, a visibility flip to public (gh repo edit, gh api)
  remote-not-allowlisted  a git push that is not the plain form (`git push [flags] [remote] [refspec...]` alone, from
                          the repo folder: see PLAIN_PUSH) or whose resolved push URL's host is not in git_remote_hosts;
                          git remote add/set-url of, or a git config URL / insteadOf / pushInsteadOf pointing at, such
                          a host; gh repo create / fork, gh gist create and gh release create / upload on such a host
  upload-not-allowlisted  a file upload (curl -T / -d @file / --data-binary @ / -F x=@file, wget --post-file,
                          Invoke-WebRequest -InFile or -Body (Get-Content ...)) to a host that is not approved
  outbound-send           email / chat / webhook sends: the user is ASKED to confirm (never auto-approved)
  publish-confirm         publishing or sharing outside the machine: the user is ASKED (never auto-approved). gh gist
                          create, gh release create / upload, npm / pnpm / yarn publish, twine upload, poetry publish,
                          cargo publish, gem push, dotnet nuget push, docker / podman push, scp / rsync / sftp to a
                          remote host, aws s3 cp|sync|mv to s3://, az storage blob upload, gsutil / gcloud storage
                          cp|rsync|mv to gs://, gh pr merge --admin, gh pr review --approve, gh pr comment, gh issue comment. A
                          copy to a host or bucket listed in upload_hosts is not asked about.
  tls-verify-off          turning TLS certificate checks off (git http.sslVerify false, NODE_TLS_REJECT_UNAUTHORIZED=0,
                          npm strict-ssl false, pip trusted-host, PYTHONHTTPSVERIFY=0). Behind a TLS-inspecting proxy
                          the fix is the corporate CA bundle, not switching verification off.
"""
import io
import ipaddress
import json
import os
import re
import shlex
import tokenize
from urllib.parse import urlsplit

import engine as E
import _wb

DEFAULTS = {"enabled": True, "git_remote_hosts": [], "upload_hosts": [],
            "block_public_repos": True, "send_endpoints": [], "extra_secret_paths": []}
DEFAULT_SEND_ENDPOINTS = [
    r"graph\.microsoft\.com/[^\s\"']*/sendMail",
    r"graph\.microsoft\.com/[^\s\"']*/(?:chats|channels)/[^\s\"']*/messages",   # Teams chat / channel post
    r"[\w.-]*\.logic\.azure\.com[^\s\"']*/triggers/",                          # Power Automate / Logic Apps
    r"[\w.-]*webhook\.office\.com/",
    r"hooks\.slack\.com/(?:services|workflows|triggers)/",
    r"slack\.com/api/chat\.(?:postMessage|scheduleMessage|postEphemeral)",
    r"api\.sendgrid\.com/v3/mail/send",
    r"api\.mailgun\.net/v3/[^\s\"']*/messages",
    r"discord(?:app)?\.com/api/webhooks/",
]


def _local(host):
    """localhost or a loopback address (IPv4 or IPv6)."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def allowlist_path():
    return _wb.workbench_home() / "corporate-allowlist.json"


def cfg():
    """The settings as a dict, or None when the user turned the pack off. Fails closed (ON, no hosts) when the
    config dir was redirected away from the one the installer recorded, or the file cannot be read."""
    if _wb.config_redirected():
        E.log(f"ERROR CLAUDE_CONFIG_DIR differs from the installed config dir {_wb.installed_claude_home()}: "
              "corporate pack ON with no approved hosts")
        return dict(DEFAULTS)
    d = {}
    try:
        with open(allowlist_path(), encoding="utf-8-sig") as f:
            d = json.load(f)
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        E.log(f"ERROR corporate allowlist unreadable, using the defaults (pack ON, no hosts): {e!r}"[:300])
    conf = {**DEFAULTS, **(d if isinstance(d, dict) else {})}
    return None if conf.get("enabled") is False else conf


def _hosts(conf, *keys):
    return [str(h).lower().split(":")[0].strip() for k in keys for h in conf.get(k) or [] if str(h).strip()]


def _allowed(host, conf, *keys):
    return bool(host) and host.lower() in _hosts(conf, *(keys or ("git_remote_hosts",)))   # exact, no suffix match


def _why(conf, key="git_remote_hosts"):
    src = allowlist_path().as_posix()
    if not _hosts(conf, key):
        return (f"No hosts are approved yet ({key} in {src} is empty), so this is refused. The user adds the "
                "company's hosts there by hand, or re-runs the installer with --git-hosts.")
    return f"That host is not in {key} in {src}. The user edits that file; the agent does not."


# ── public repositories ──────────────────────────────────────────────────────────────────────────────────────
def public_repo(c):
    conf = cfg()
    if not conf or conf.get("block_public_repos") is False:
        return
    for seg, _ in E.statements(c):
        h = E._head(seg)
        if h not in ("gh", "glab"):
            continue
        if re.search(r"\brepo\s+create\b", seg) and re.search(r"(?<!\S)--public\b", seg):
            E.block("Creating a PUBLIC repository is blocked: company code must not be published. Create it --private "
                    "or --internal.", "public-repo", seg[:120])
        if re.search(r"\brepo\s+edit\b", seg) and re.search(r"--visibility[=\s]+[\"']?public\b", seg):
            E.block("Making a repository public is blocked.", "public-repo", seg[:120])
        if h == "gh" and re.search(r"\bapi\b", seg) and re.search(r"(?i)\bprivate[\"']?\s*[=:]\s*[\"']?false\b|"
                                                                  r"\bvisibility[\"']?\s*[=:]\s*[\"']?public\b", seg):
            E.block("Flipping a repository to public through the API is blocked.", "public-repo", seg[:120])


# ── git remotes ──────────────────────────────────────────────────────────────────────────────────────────────
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")          # git's is_url(): scheme characters, then ://
_SCP_BAD = set("@[]\\{}*?#")


def dest_host(url):
    """The host git would send to for a destination URL, lower case; None to refuse. Read the way git reads it:
    a scheme URL (`x://`) through urlsplit, refused when its authority holds ? or # or a backslash, userinfo with a
    ':' or a second '@', or when urlsplit's host and the raw authority's host differ; an scp-like [user@]host:path,
    host = text before the first ':', refused when user or host holds @ [ ] \\ { } * ? #. Local paths, file:// and
    anything containing :// that is not a clean scheme URL (both readings would apply) are refused."""
    u = (url or "").strip().strip("\"'")
    if not u or re.search(r"[\s$%`]", u):
        return None
    m = _SCHEME.match(u)
    if m:
        if m.group(1).lower() == "file":
            return None
        auth = u[m.end():].split("/", 1)[0]
        user, at, hostport = auth.rpartition("@")
        if re.search(r"[?#\\]", auth) or (at and (":" in user or "@" in user)):
            return None
        try:
            host = urlsplit(u).hostname or ""
        except ValueError:
            return None
        raw = hostport[1:hostport.find("]")] if hostport.startswith("[") else hostport.split(":", 1)[0]
        return host if host and host == raw.lower() else None
    if "://" in u or re.match(r"^[A-Za-z]:(?:[\\/]|$)", u):            # ambiguous, or a Windows drive path
        return None
    head, colon, _ = u.partition(":")
    if not colon or "/" in head or "\\" in head:                         # git: a local path
        return None
    user, at, host = head.rpartition("@")
    if not host or (at and not user) or _SCP_BAD & set(user + host) or "@" in u[len(head):]:
        return None                                  # an '@' in the path: a naive reader would see a second host
    return host.lower()


def _is_name(t):
    """A remote NAME (origin), not a URL or path: git looks it up in the config."""
    return bool(t) and not re.search(r"[:/\\]", t)


def _git(cwd, *args):
    try:
        r = E.subprocess.run(["git", "-C", cwd, *args], capture_output=True, timeout=5,
                             creationflags=getattr(E.subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.decode("utf-8", "replace").strip() if r.returncode == 0 else ""
    except Exception as e:
        E.log(f"git lookup skipped: {e!r}")
        return ""


def _push_urls(target, cwd):
    """Every URL a plain `git push [target]` run in cwd would send to: insteadOf, pushurl and pushInsteadOf applied.
    Resolved with `git ls-remote --get-url` and `git remote get-url --push --all` (no network, nothing forwarded from
    the command). None when that cannot be told (no repository at cwd, or git names no URL): the caller refuses."""
    explicit = target if target and not _is_name(target) else None
    if not cwd or not os.path.isdir(cwd):
        return [explicit] if explicit else None
    if explicit:
        urls = [_git(cwd, "ls-remote", "--get-url", explicit) or explicit]
    else:
        name = target
        if not name:
            up = _git(cwd, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{push}")
            name = up.split("/", 1)[0] if "/" in up else "origin"
        urls = _git(cwd, "remote", "get-url", "--push", "--all", name).splitlines() + \
            [_git(cwd, "ls-remote", "--get-url", name)]
    rules = []
    for line in _git(cwd, "config", "--get-regexp", r"^url\..*\.pushinsteadof$").splitlines():
        key, _, prefix = line.partition(" ")
        m = re.fullmatch(r"(?i)url\.(.+)\.pushinsteadof", key)
        if m and prefix:
            rules.append((prefix, m.group(1)))
    urls = [u for u in urls if u and not _is_name(u)]       # ls-remote --get-url echoes an unknown NAME back
    if not urls:
        return None
    out = []
    for u in urls:
        best = max((r for r in rules if u.startswith(r[0])), key=lambda r: len(r[0]), default=None)
        out.append(best[1] + u[len(best[0]):] if best else u)
    return out


def _gh_host(seg, toks, cwd, repo_flag=False):
    """The host a gh command acts on: HOST/OWNER/REPO in -R/--repo or an argument, else GH_HOST, else the current
    repository's origin (repo_flag), else github.com."""
    m = re.search(r"(?:^|\s)GH_HOST=(\S+)", seg)
    host = (m.group(1) if m else os.environ.get("GH_HOST") or "").strip("\"'").lower()
    for k, t in enumerate(toks):
        val = t.split("=", 1)[1] if t.startswith("--repo=") else toks[k + 1] if t in ("-R", "--repo") and \
            k + 1 < len(toks) else t if not t.startswith("-") and t.count("/") >= 2 else None
        if val:
            return val.strip("\"'").split("/")[0].lower() if val.count("/") >= 2 else host or "github.com"
    if repo_flag and not host and cwd and os.path.isdir(cwd):
        h = dest_host(_git(cwd, "remote", "get-url", "origin"))
        if h:
            return h
    return host or "github.com"


# A push passes only in its plain form: the whole command is `git push [flags] [remote] [refspec...]`, one statement,
# no git options before `push`, no environment prefix, no shell operators, variables or substitutions, and only the
# flags below (force flags are the generic pack's business). Anything else is refused with one instruction. This is an
# allowlist on purpose: every blacklist of "shapes that switch repo or config" (cd, GIT_DIR, -c include.path, export,
# read, source, Set-Item env:, ...) had another gap.
PLAIN_PUSH = ("Run the push as its own command, exactly `git push <remote> <branch>`, from the repo folder: no `cd` "
              "first, no `&&`, `;` or pipes, no `-c` options, variables or wrappers (bash -c, eval, cmd /c). Then the "
              "guard can check where it goes.")
_PUSH_FLAGS = {"-u", "--set-upstream", "--tags", "--follow-tags", "--dry-run", "-n", "--porcelain", "-q", "--quiet",
               "-v", "--verbose", "--no-verify", "-f", "--force", "--force-if-includes", "-d", "--delete"}
_PUSH_ANY = re.compile(r"(?i)(?<![\w.-])git(?:\.exe)?[\"']?(?:\s+-\S+(?:\s+[^\s-]\S*)?)*\s+push(?![\w-])")  # any form
_PUSH_WORDS = re.compile(r"(?i)(?<![\w.-])git(?:\.exe)?[\"']?\s+(?:\S+\s+)*?push(?![\w.-])")   # xargs git push ...
_NOT_PLAIN = re.compile(r"[;&|`()$%\r\n]")
_PUSH_SUBS = {"push", "send-pack", "http-push"}
_PUSH_VERBS = {"subtree": {"push"}, "lfs": {"push"}, "svn": {"dcommit", "set-tree"}, "p4": {"submit"}}   # git x <verb>
_GIT_BUILTINS = frozenset("""add am annotate apply archive bisect blame branch bugreport bundle cat-file check-attr
    check-ignore check-mailmap check-ref-format checkout checkout-index cherry cherry-pick citool clean clone column
    commit commit-graph commit-tree config count-objects credential describe diagnose diff diff-files diff-index
    diff-tree difftool fast-export fast-import fetch fetch-pack filter-branch fmt-merge-msg for-each-ref for-each-repo
    format-patch fsck gc get-tar-commit-id grep gui hash-object help hook index-pack init instaweb interpret-trailers
    log ls-files ls-remote ls-tree mailinfo mailsplit maintenance merge merge-base merge-file merge-index merge-tree
    mergetool mktag mktree multi-pack-index mv name-rev notes pack-objects pack-refs patch-id prune prune-packed pull
    push range-diff read-tree rebase reflog refs remote repack replace request-pull rerere reset restore rev-list
    rev-parse revert rm send-email send-pack shortlog show show-branch show-index show-ref sparse-checkout stage stash
    status stripspace submodule switch symbolic-ref tag unpack-file unpack-objects update-index update-ref
    update-server-info var verify-commit verify-pack verify-tag version whatchanged worktree write-tree""".split())
# With an unknown subcommand and no alias on disk, these in the command could supply one (alias.x via -c / env /
# `git config`, or a different config file / home): refused.
_ALIAS_SOURCES = re.compile(r"(?i:alias\.|include\.path|includeif|--git-dir)|GIT_CONFIG|GIT_DIR|HOME|USERPROFILE|"
                            r"XDG_CONFIG")
# What an alias may expand to: read-only builtins only. Anything else (rebase --exec, submodule foreach, bisect run,
# filter-branch, difftool --extcmd, a push, a shell alias ...) is refused.
_READ_ONLY = {"status", "log", "diff", "show", "fetch", "pull", "blame", "grep", "ls-files", "rev-parse", "describe",
              "shortlog"}
_LIST_CHANGES = {"-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy", "-f", "--force", "-u",
                 "--set-upstream-to", "--unset-upstream", "--edit-description", "-t", "--track", "-a", "-s", "-F",
                 "--annotate", "--sign", "--file", "--create-reflog"}


def _read_only(words):
    """True when git <words> is one of the read-only commands an alias may expand to."""
    cmd, args = words[0], words[1:]
    if cmd in _READ_ONLY:
        return True
    if cmd in ("branch", "tag"):                                  # list only
        opts = {x.split("=")[0] for x in args if x.startswith("-")}
        pos = [x for x in args if not x.startswith("-")]
        changes = _LIST_CHANGES - ({"-a"} if cmd == "branch" else set())   # branch -a lists all; tag -a annotates
        return not opts & changes and (not pos or bool(opts & {"-l", "--list"}))
    return (cmd == "remote" and args in ([], ["-v"], ["--verbose"])) or (cmd == "stash" and args[:1] == ["list"]) \
        or (cmd == "config" and args[:1] in (["--get"], ["--get-all"], ["--get-regexp"]))


def _alias(sub, cwd, cmdline=()):
    """How `git <sub> <cmdline>` resolves through aliases on disk: "none" (no alias: git will error), "ok" (it ends at
    a read-only builtin), "deny" (anything else, including a chain too long or looping)."""
    seen, extra = [], list(cmdline)
    while True:
        v = _git(cwd, "config", "--get", "alias." + sub)
        if not v:
            return "none" if not seen else "deny"
        seen.append(sub)
        try:
            words = shlex.split(v)
        except ValueError:
            return "deny"
        if v.lstrip().startswith("!") or not words or len(seen) > 8 or words[0] in seen:
            return "deny"
        extra = words[1:] + extra
        if words[0] in _GIT_BUILTINS:
            return "ok" if _read_only([words[0]] + extra) else "deny"
        sub = words[0]


def _plain_push(c):
    """The remote a plain push names (None for git's default), after denying anything that is not the plain form."""
    stmts = E.statements(c)
    raw = re.sub(r"\s\d?>&\d\s*$", " ", c.cmd).strip()                 # a trailing 2>&1 is fine
    try:
        toks = shlex.split(raw, posix=not c.ps)
    except ValueError:
        toks = []
    toks = [t.strip("\"'") for t in toks]
    args = toks[2:]
    pos = [t for t in args if not t.startswith("-")]
    if len(stmts) != 1 or stmts[0][1] or _NOT_PLAIN.search(raw) or len(toks) < 2 \
            or os.path.basename(toks[0]).lower() not in ("git", "git.exe") or toks[1] != "push" \
            or any(t.startswith("-") and t not in _PUSH_FLAGS and not t.startswith("--force-with-lease")
                   for t in args):
        E.block(PLAIN_PUSH, "remote-not-allowlisted", c.cmd[:160])
    return pos[0] if pos else None


def remotes(c):
    conf = cfg()
    if not conf:
        return

    def check(url, what, seg):
        host = dest_host(url)
        if host is None or not _allowed(host, conf):
            E.block(f"{what} {host or url} is blocked: company code goes only to approved hosts (exact host names; "
                    "local paths and unclear URLs are refused). " + _why(conf), "remote-not-allowlisted", seg[:160])

    for k, v in E.git_config_pairs(c.cmd, c.ps):     # -c, GIT_CONFIG_* env, `git config` writes
        if re.fullmatch(r"(?i)remote\..+\.(?:url|pushurl)", k):
            check(v, "Setting a remote URL to", f"{k}={v}")
        m = re.fullmatch(r"(?i)url\.(.+)\.(?:push)?insteadof", k)
        if m:
            check(m.group(1), "Rewriting git URLs to", f"{k}={v}")
    if None in E.live_encoded(c):   # an encoded payload nobody can read may push anywhere
        E.block("A PowerShell encoded command the guard cannot decode may push anywhere. " + PLAIN_PUSH,
                "remote-not-allowlisted", c.cmd[:160])
    stmts = E.statements(c)   # quoted prose and cat/tee heredocs blanked; bash -c / eval / cmd /c payloads included
    # Both views: the statements, and the raw command minus provable prose (python -c, node -e, written-then-run
    # files and decoded -EncodedCommand payloads stay in it).
    pushing = any(_PUSH_ANY.search(seg) for seg, _ in stmts) or bool(_PUSH_ANY.search(E.raw_view(c)))
    for seg, remote in stmts:
        h = E._head(seg)
        if h == "git":
            toks, sub = E.git_sub(seg)
            if sub is None:
                continue
            name = toks[sub]
            nxt = next((t for t in toks[sub + 1:] if not t.startswith("-")), "")
            if name in _PUSH_SUBS or nxt in _PUSH_VERBS.get(name, ()):
                pushing = True
            elif name not in _GIT_BUILTINS:                             # an alias, or git-<name> on PATH
                cwd = c.cwd if not remote else ""
                how = "deny" if sub > 1 or not cwd or not os.path.isdir(cwd) else _alias(name, cwd, toks[sub + 1:])
                if how == "deny" or (how == "none" and _ALIAS_SOURCES.search(c.cmd)):
                    E.block(f"`git {name}` is not a git builtin; as an alias it may only expand to a read-only command "
                            "(status, log, diff, show, ...) with no git options before it. " + PLAIN_PUSH,
                            "remote-not-allowlisted", seg[:160])
            elif name == "remote":
                pos, skip = [], False
                for t in toks[sub + 1:]:
                    if skip:
                        skip = False
                    elif t in ("-t", "-m"):
                        skip = True
                    elif not t.startswith("-"):
                        pos.append(t)
                if pos[:1] in (["add"], ["set-url"]) and len(pos) >= 3:
                    check(pos[2], "Pointing a remote at", seg)
        elif h == "gh":
            toks = E._HEAD_SKIP.sub("", seg, 1).split()
            what = ("Creating or forking a repository on" if re.search(r"\brepo\s+(?:create|fork)\b", seg) else
                    "Creating a gist on" if re.search(r"\bgist\s+create\b", seg) else
                    "Publishing a release on" if re.search(r"\brelease\s+(?:create|upload)\b", seg) else None)
            if what:
                host = _gh_host(seg, toks[2:], c.cwd, repo_flag=what.startswith("Publishing"))
                if not _allowed(host, conf):
                    E.block(f"{what} {host} is blocked: company code and files go only to approved hosts. "
                            + _why(conf), "remote-not-allowlisted", seg[:160])
        elif _PUSH_WORDS.search(seg):                                   # xargs git push, find -exec git push, ...
            pushing = True
    if pushing:
        urls = _push_urls(_plain_push(c), c.cwd)
        if urls is None or any(re.search(r"[$%`\s]", u) for u in urls):
            E.block("The guard cannot tell where this push goes (no repository here, git names no push URL for that "
                    "remote, or the URL holds a variable). " + PLAIN_PUSH, "remote-not-allowlisted", c.cmd[:160])
        for url in urls:
            check(url, "Pushing to", c.cmd)


# ── file uploads ─────────────────────────────────────────────────────────────────────────────────────────────
_UPLOAD = re.compile(r"""(?ix)
      (?:^|\s)(?-i:-[A-Za-z]*T)(?:\s|=|$) | --upload-file\b
    | (?:^|\s)(?:(?-i:-[A-Za-z]*d)|--data(?:-binary|-urlencode|-ascii)?|--json)[\s=]+["']?@
    | (?:^|\s)(?:(?-i:-F)|--form(?:-string)?)[\s=]+["']?[^\s=]+=["']?[@<]
    | --post-file\b | --body-file\b
    | -InFile\b | -Body\s+[(\$]*\s*(?:Get-Content|gc|cat|type|\[(?:System\.)?IO\.File\])""")
_PS_HEADS = {"invoke-webrequest", "iwr", "invoke-restmethod", "irm"}
_UPLOAD_HEADS = {"curl", "wget"} | _PS_HEADS
# Every word that is not an option or an option's value is a possible URL (curl and wget take bare words as URLs).
# An option these tables do not know is assumed to take no value, so the word after it is checked too (fails closed).
_SHORT_VAL = {"curl": set("dFTHouXAebcEKmrCwyYzQtx"), "wget": set("oOaPUtTwQeiBlDAIRX")}
_LONG_VAL = {"data", "data-binary", "data-urlencode", "data-ascii", "data-raw", "json", "form", "form-string",
             "upload-file", "header", "output", "user", "request", "user-agent", "referer", "cookie", "cookie-jar",
             "cert", "key", "cacert", "capath", "max-time", "connect-timeout", "retry", "range", "continue-at",
             "write-out", "limit-rate", "proxy-user", "oauth2-bearer", "resolve", "connect-to", "interface",
             "post-file", "post-data", "body-file", "body-data", "method", "output-document", "output-file",
             "directory-prefix", "password", "http-user", "http-password", "tries", "timeout", "level",
             "url", "proxy", "config", "input-file", "execute"}
_DEST = {"--url", "--proxy", "-x", "uri", "proxy"}                 # their value IS where the data goes
_HIDDEN = {"curl": {"-K", "--config"}, "wget": {"-i", "--input-file", "-e", "--execute"}}   # a file / command names it
_PS_VAL = {"uri", "proxy", "infile", "body", "method", "headers", "outfile", "contenttype", "credential",
           "proxycredential", "useragent", "websession", "sessionvariable", "form", "timeoutsec", "maximumredirection",
           "maximumretrycount", "retryintervalsec", "certificatethumbprint", "certificate", "transferencoding",
           "authentication", "token", "custommethod", "sslprotocol", "httpversion", "responseheadersvariable",
           "statuscodevariable", "connectiontimeoutseconds", "operationtimeoutseconds", "maximumfollowrellink"}
_PS_SWITCH = {"usebasicparsing", "usedefaultcredentials", "disablekeepalive", "passthru", "skipcertificatecheck",
              "skipheadervalidation", "skiphttperrorcheck", "noproxy", "allowunencryptedauthentication",
              "preserveauthorizationonredirect", "resume", "allowinsecureredirect", "preservehttpmethodonredirect",
              "proxyusedefaultcredentials", "followrellink"}


def _url_host(word):
    """The host a URL-ish word names, with or without a scheme and for any scheme; None when it cannot be told
    (a variable, a glob, a file:// path, an empty word)."""
    w = word.strip("\"'")
    if not w or any(ch in w for ch in "$`{}()<>*") or w.startswith("@"):
        return None
    m = re.match(r"(?i)^(?:[a-z][a-z0-9+.-]*:)?//", w)
    auth = re.split(r"[/?#]", w[m.end():] if m else w, maxsplit=1)[0].rpartition("@")[2]   # past user:password@
    m = re.match(r"^(\[(?:[^\]])+\]|[^:\s]+)", auth)   # [v6] or name
    return m.group(1).strip("[]").lower() if m else None


def _ps_param(p):
    """The full PowerShell parameter name an (abbreviated) -Name means, or None when unknown or ambiguous."""
    names = _PS_VAL | _PS_SWITCH
    hits = [n for n in names if n.startswith(p)]
    return p if p in names else hits[0] if len(hits) == 1 else None


def _upload_targets(seg, ps):
    """(destination words, hidden?) of a curl / wget / Invoke-WebRequest statement."""
    body = E._HEAD_SKIP.sub("", seg, 1)
    try:
        toks = shlex.split(body, posix=not ps)
    except ValueError:
        toks = body.split()
    toks = [t.strip("\"'") for t in toks]
    head = os.path.basename(toks[0]).lower().removesuffix(".exe") if toks else ""
    out, hidden, k = [], False, 1
    while k < len(toks):
        t = toks[k]
        k += 1
        if not t.startswith("-") or t == "-":
            out.append(t)
            continue
        if head in _PS_HEADS:
            name, sep, val = t[1:].lower().partition(":")
            name = _ps_param(name)
            takes, dest = name in _PS_VAL, name in ("uri", "proxy")
        elif t.startswith("--"):
            name, sep, val = t.partition("=")
            takes, dest = name[2:] in _LONG_VAL, name in _DEST
            hidden |= name in _HIDDEN.get(head, ())
        else:                       # -sSLT f: letters until the first one that takes a value; the rest is its value
            sep = val = ""
            takes = dest = False
            for i, ch in enumerate(t[1:], 1):
                if ch in _SHORT_VAL.get(head, ()):
                    takes, dest = True, ch == "x" and head == "curl"
                    hidden |= "-" + ch in _HIDDEN.get(head, ())
                    sep, val = ("=", t[i + 1:]) if i < len(t) - 1 else ("", "")
                    break
        if not takes or sep:
            if sep and dest:
                out.append(val)
            continue
        if k >= len(toks):
            break
        v = toks[k]
        k += 1
        if v.startswith(("(", "@{")):                  # a PowerShell (expression) or @{hashtable}: up to its close
            depth = v.count("(") + v.count("{") - v.count(")") - v.count("}")
            while depth > 0 and k < len(toks):
                depth += toks[k].count("(") + toks[k].count("{") - toks[k].count(")") - toks[k].count("}")
                k += 1
        if dest:
            out.append(v)
    return out, hidden


def uploads(c):
    conf = cfg()
    if not conf:
        return
    for seg, _ in E.statements(c):
        if E._head(seg) not in _UPLOAD_HEADS or not _UPLOAD.search(seg):
            continue
        dests, hidden = _upload_targets(seg, c.ps)
        hosts = [_url_host(d) for d in dests]
        if hidden or not hosts or None in hosts:
            E.block("This uploads a file and the guard cannot tell where to (no URL, or a variable, glob or config "
                    "file names it), so it is refused. Write the destination URL out in full.",
                    "upload-not-allowlisted", seg[:160])
        for host in hosts:
            if not _local(host) and not _allowed(host, conf, "git_remote_hosts", "upload_hosts"):
                E.block(f"Uploading a file to {host} is blocked: files leave only for approved hosts. "
                        + _why(conf, "upload_hosts"), "upload-not-allowlisted", seg[:160])


# ── publishing and sharing (ask) ─────────────────────────────────────────────────────────────────────────────
_REMOTE_PATH = re.compile(r"^(?:[^@/\s:]+@)?(\x5b[0-9A-Fa-f:.]+\x5d|[^:/\\\s]{2,}):")   # [user@]host:path, [v6]:path (not C:\path)


def _publish_what(toks):
    """What a statement publishes or shares, and the host/bucket it goes to (None when it names none), or None."""
    h = os.path.basename(toks[0]).lower().removesuffix(".exe") if toks else ""
    a = [t.strip("\"'") for t in toks[1:]]
    pos = [t for t in a if not t.startswith("-")]
    w = " ".join(a)
    if h == "gh":
        if pos[:2] == ["gist", "create"]:
            return "creates a gist", None
        if pos[:1] == ["release"] and pos[1:2] in (["create"], ["upload"]):
            return "publishes a release", None
        if pos[:2] == ["pr", "merge"] and "--admin" in a:
            return "merges with --admin, skipping branch protection", None
        if pos[:2] == ["pr", "review"] and ("--approve" in a or "-a" in a):
            return "posts an approving review", None
        if pos[:2] in (["pr", "comment"], ["issue", "comment"]):
            return "posts a comment others will read", None
    if (h in ("npm", "pnpm") and pos[:1] == ["publish"]) or (h == "yarn" and (pos[:1] == ["publish"] or pos[:2] == ["npm", "publish"])):
        return "publishes a package to a registry", None
    if (h == "twine" and pos[:1] == ["upload"]) or (h in ("poetry", "cargo") and pos[:1] == ["publish"]) \
            or (h == "gem" and pos[:1] == ["push"]) or (h == "dotnet" and pos[:2] == ["nuget", "push"]):
        return "publishes a package to a registry", None
    if h in ("docker", "podman") and (pos[:1] == ["push"] or pos[:2] == ["image", "push"]):
        img = (pos[1:2] or pos[2:3] or [""])[0]
        return "pushes an image to a registry", img.split("/")[0] if "/" in img and "." in img.split("/")[0] else None
    if h in ("scp", "rsync") and len(pos) >= 2:
        m = re.match(r"^rsync://(?:[^@/]+@)?([^/:]+)", pos[-1]) or _REMOTE_PATH.match(pos[-1])
        if m:
            return "copies files to a remote host", m.group(1).strip("[]").lower()
    if h == "sftp" and pos:
        return "opens a file transfer session with", pos[-1].rpartition("@")[2].split(":")[0].lower()
    if h == "aws" and pos[:1] == ["s3"] and pos[1:2] and pos[1] in ("cp", "sync", "mv") and pos[-1].startswith("s3://"):
        return "uploads files to a cloud bucket", pos[-1][5:].split("/")[0].lower()
    if (h == "gsutil" and pos[:1] and pos[0] in ("cp", "rsync", "mv") and pos[-1].startswith("gs://")) or \
            (h == "gcloud" and pos[:1] == ["storage"] and pos[1:2] and pos[1] in ("cp", "rsync", "mv")
             and pos[-1].startswith("gs://")):
        return "uploads files to a cloud bucket", pos[-1][5:].split("/")[0].lower()
    if h == "az" and pos[:2] == ["storage", "blob"] and pos[2:3] and pos[2].startswith("upload"):
        m = re.search(r"--account-name[=\s]+(\S+)", w)
        return "uploads files to cloud storage", m.group(1).lower() if m else None
    return None


def publish(c):
    conf = cfg()
    if not conf:
        return
    for seg, _ in E.statements(c):
        hit = _publish_what(E._cmd_toks(seg))
        if not hit:
            continue
        what, host = hit
        if host and (_local(host) or _allowed(host, conf, "upload_hosts")):
            continue
        E.ask(f"This {what}" + (f" ({host})" if host else "") + ": it leaves this machine and others can see it. "
              "Approve only if you meant to and your organisation allows it.", "publish-confirm", seg[:160])


# ── outbound sends ───────────────────────────────────────────────────────────────────────────────────────────
SEND_RE = re.compile(r"(?i:\.sendmail\()|\bsend_message\(|\bswaks\b|\bsmtps?://|"
                     r"(?i:Send-MailMessage|Send-MgUserMail|New-MgChatMessage|New-MgTeamChannelMessage|"
                     r"Send-MgUserMessage)\b|"
                     r"(?<![\w.-])sendmail\s+-t\b")
_SEND_INERT = {"grep", "egrep", "fgrep", "rg", "findstr", "select-string", "sls", "echo", "printf"}
# A write signal beside an HTTP send endpoint: an HTTP method, a body / form / upload flag, an SDK send call.
_WRITE_SIG = re.compile(r"""(?ix)
      -X\s*(?:POST|PUT|PATCH)\b | --(?:request|method)[ =]"?(?:POST|PUT|PATCH)\b
    | (?:^|\s)(?-i:-[A-Za-z]*[dF])(?:[ =]|$) | (?:^|\s)(?-i:-[A-Za-z]*T)(?:[ =]|$)(?!\d+(?:\s|$))
    | -Method\s+["']?(?:Post|Put|Patch)\b | -Body\b
    | --data(?:-raw|-binary|-ascii|-urlencode)?\b | --json\b | --form(?:-string)?\b | --upload-file\b | --post-data\b
    | \.(?:post|send|create|sendMail)\s*\( | \brequests\.(?:post|put|patch)\b
    | urlopen\([^)]*\bdata\s*= | Request\([^)]*\bdata\s*=""")
PY_FILE_RE = re.compile(r'\bpython[\d.]*(?:\.exe)?["\']?\s+(?:-[A-Za-z]\S*\s+)*["\']?([^\s;&|<>"\']+\.py)\b')


def _endpoints(conf):
    out = []
    for p in DEFAULT_SEND_ENDPOINTS + [x for x in conf.get("send_endpoints") or [] if isinstance(x, str)]:
        try:
            out.append(re.compile(p, re.I))
        except re.error:
            E.log(f"ERROR send_endpoints entry is not a valid regex, skipped: {p!r}")
    return out


def _send_hit(text, eps):
    """First outbound send in shell text, skipping one in the args of a statement whose HEAD searches or prints.
    An HTTP endpoint counts only when its statement carries a write signal (a GET of the same URL is a read)."""
    hits = [(m, False) for m in SEND_RE.finditer(text)] + [(m, True) for rx in eps for m in rx.finditer(text)]
    for m, is_ep in sorted(hits, key=lambda x: x[0].start()):
        a, b = E._stage(text, m.start())
        if E._head(text[a:b]) in _SEND_INERT:
            continue
        if is_ep and not _WRITE_SIG.search(text[a:max(b, m.end())]):
            continue
        return m.group(0)
    return None


def _code_send_hit(src, eps):
    """Send evidence in python source at token level: a .sendmail( / .send_message( call, or a string literal that IS
    a send endpoint. A file that only QUOTES those patterns in comments is not a send."""
    skip = {tokenize.COMMENT, getattr(tokenize, "FSTRING_MIDDLE", -1)}
    code = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.STRING:
                body = re.sub(r"^[A-Za-z]*(\"\"\"|'''|\"|')", "", tok.string)
                if re.match(r"(?i)smtps?://", body) or any(rx.match(re.sub(r"(?i)^https?://", "", body)) for rx in eps):
                    return body[:40]
                code.append('""')
            elif tok.type not in skip:
                code.append(tok.string)
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return None
    m = re.search(r"(?i)\.\s*(sendmail|send_message)\s*\(", " ".join(code))
    return m and m.group(0)


def send(c):
    """A send is never blocked and never auto-approved: the user is asked, after seeing the command."""
    conf = cfg()
    if not conf:
        return
    eps = _endpoints(conf)
    live = c.L.text(lambda h: h.py or h.run is None)     # docs and data bodies send nothing
    hit = _send_hit(live, eps) or next((x for h in c.L.hd if h.py == "fed" and h.b is not None
                                        for x in [_code_send_hit(h.body, eps)] if x), None)
    if not hit and PY_FILE_RE.search(live):
        # `cat > x.py <<'EOF' ... EOF && python x.py`: the script does not exist yet at hook time, so judge the body
        hit = next((x for h in c.L.hd if h.py == "written" and h.b is not None
                    for x in [_code_send_hit(h.body, eps)] if x), None) or \
            next((x for _, s in E.local_files(c.cmd, c.cwd, [m.group(1) for m in PY_FILE_RE.finditer(c.cmd)])
                  for x in [_code_send_hit(s, eps)] if x), None)
    if hit:
        E.ask("This sends a message (email, chat or webhook) that other people will see. Check the recipients and "
              "the final text before you approve it.", "outbound-send", hit)


# ── TLS verification ─────────────────────────────────────────────────────────────────────────────────────────
_TLS_OFF = re.compile(r"""(?ix)
      (?<![\w-])http\.sslverify[\s=]+["']?(?:false|0|no|off)\b
    | (?<![\w-])GIT_SSL_NO_VERIFY\s*=\s*["']?(?:1|true|yes)\b
    | (?<![\w-])NODE_TLS_REJECT_UNAUTHORIZED["']?\s*=\s*["']?0\b
    | (?<![\w-])PYTHONHTTPSVERIFY\s*=\s*["']?0\b
    | (?<![\w-])strict-ssl[\s=]+["']?false\b
    | (?<![\w-])(?:set\s+)?global\.trusted-host\b | (?<![\w-])--trusted-host\b
    | (?<![\w-])ssl_verify[\s=:]+["']?(?:false|0)\b
    | (?<![\w-])--(?:no-check-certificate|insecure)\b(?=[^\n;&|]*\b(?:config|install|clone|set)\b)""")


def tls_verify_off(c):
    if not cfg():
        return
    for seg, _ in E.statements(c):
        m = _TLS_OFF.search(seg)
        if m:
            E.block("Turning TLS certificate verification off is blocked. Behind a TLS-inspecting proxy, point the tool "
                    "at the corporate CA bundle instead: git config http.sslCAInfo <bundle>, NODE_EXTRA_CA_CERTS, "
                    "pip config set global.cert <bundle> (or REQUESTS_CA_BUNDLE / SSL_CERT_FILE), npm config set "
                    "cafile <bundle>. Your IT team publishes the bundle.", "tls-verify-off", m.group(0))


SHELL = (public_repo, remotes, uploads, publish, tls_verify_off, send)
