#!/usr/bin/env python3
"""kit_update.py: "check the new stuff and go". One script, three verbs (Python 3.10+, stdlib; never elevates, never touches
policy, never runs `claude update`):

  kit_update.py [update] [--repo OWNER/REPO [--new-repo]] [--check] [--wait SECONDS]
      Asks GitHub (anonymous HTTPS) for the latest release of this kit, checks the asset's published SHA-256 BEFORE and after
      the download, unpacks it to a fresh folder under <WB>/state/kit-update/, runs that release's `install.py --apply` and
      then `setup.py run --detach` with the opt-ins the last setup remembered (<WB>/state/setup-state.json). It is a chain of
      short stages kept in <WB>/state/kit-update.json: install, setup (waited for at most --wait seconds per call, 90 by
      default), then `setup.py doctor --deep` as its own background job; every call that is not the last exits 6, and the SAME
      command continues where it stopped. The last call writes <WB>/state/post-update-verify.json and prints one table plus the
      restart line. Already current: says so and runs the verify. --check only reports. Where the releases live: the
      remembered config.json "kit_repo" (a --repo that differs from it needs --new-repo), then env WB_KIT_REPO, then
      plugins/workbench-core/skills/kit-update/release-source.json; a --repo that worked is remembered.
  kit_update.py verify [--wait SECONDS]
      The pending post-update verify: every mechanical check as PASS / WARN / FAIL / NEEDS-IT on one screen, the IT asks once,
      and a FOR THE KIT AUTHOR box with only the kit's own defects (credentials redacted, user, computer, domain and company
      names and unknown hosts scrubbed). Saved to <WB>/state/field-report.md. Clears the marker. Exit 2 on a FAIL, 1 on a WARN,
      else 0; 6 while its `doctor --deep` job is still running (run the same command again).
  kit_update.py record ID PASS|WARN|FAIL TEXT [--command CMD]
      Adds one row (the live guard test, which only Claude can do) to the saved report.
Exit codes of update: 0 done and clean, 1 done with warnings, 2 usage or environment, 3 blocked by policy or a proxy (ask IT),
4 a step failed, 5 waiting on a reboot, 6 not finished (run the same command again).
"""
import argparse
import ast
import datetime
import functools
import getpass
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
sys.path.insert(0, str(HERE))
import asks as ASKS  # noqa: E402
import install as I  # noqa: E402
import setup as S  # noqa: E402
import skill_tiers as ST  # noqa: E402

API = "https://api.github.com/repos/{}/releases/latest"
DOWNLOADS = "https://github.com/{}/releases/download/"
ASSET = "claude-workbench-{tag}{ext}"            # the published asset names: claude-workbench-v0.3.1.zip / .tar.gz
SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")
SOURCE = Path("plugins/workbench-core/skills/kit-update/release-source.json")     # {"repo": "OWNER/REPO"}
RESTART = "Restart every Claude Code window, then type: go"
RUN_FILE, REPORT = "kit-update.json", "field-report.md"
NOT_KIT = {"backup", "managed policy", "knowledge: kb-index", "knowledge: capture"}   # rows about the user's own data or choices
IT_ROWS = {"TLS + network"}                                # doctor rows that name blocked hosts or inspected TLS: IT's, once, as NEEDS-IT
OWN_ROWS = {"plugin python option", "guard heartbeat", "skill listing", "IT asks"}      # the verify has its own row for these
FILE_EXT = set("py pyc json jsonl md txt log exe cmd bat ps1 sh zip gz tgz tar js mjs cjs ts yml yaml toml ini cfg xml html css "
               "dll sqlite db lock bak tmp csv whl msix pdf docx xlsx pptx png svg gif ico".split())
EXTRA_HOSTS = {"api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
               "raw.githubusercontent.com", "pypi.org", "files.pythonhosted.org", "registry.npmjs.org"}
HOSTLIKE = re.compile(r"\b(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}\b")
IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
UNC = re.compile(r"\\\\[^\\\s/<>]+")
HOSTPORT = re.compile(r"(?<![\w./\\:-])([A-Za-z][A-Za-z0-9-]{2,62}):(\d{2,5})\b")      # a one-label host with a port: a proxy
PORT_WORDS = {"http", "https", "ftp", "ssh", "line", "col", "pid", "exit", "error", "code", "port", "status", "errno", "localhost"}
COMPANY_STOP = set("ltd inc llc corp corporation limited group company gmbh onedrive sharepoint and the user host domain email".split())
COMPANY = re.compile(r"(?i)\b(OneDrive|SharePoint)( - )[^\\/\r\n\"'<>|]+")        # "OneDrive - <company name>" folders


def fwd(p):
    return str(p).replace("\\", "/")


def parse_time(s):
    try:
        d = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def nap(seconds):
    time.sleep(seconds)                                  # a seam: tests replace it


def setup_py(ctx):
    """The installed kit's setup.py (the new release once the installer has copied it), else this kit's."""
    p = ctx.wb / "kit" / "bootstrap" / "setup.py"
    return p if p.is_file() else HERE / "setup.py"


def run_py(ctx, script, *args, timeout=3600):
    """(exit code, stdout, stderr) of a kit Python program run with the console interpreter. The seam tests replace."""
    try:
        r = subprocess.run([S.PY, str(script), *[str(a) for a in args]], capture_output=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, env={**os.environ, "PATH": ctx.fresh_path(), **S.TELEMETRY_ENV},
                           creationflags=S.NO_WINDOW)
    except subprocess.TimeoutExpired:
        return -1, "", f"timed out after {timeout} s"
    except OSError as e:
        return None, "", str(e)
    return r.returncode, S.decode(r.stdout), S.decode(r.stderr)


def probe(ctx, argv, timeout=30):
    """(exit code, output) of a quick program; (None, "") when it is not found. Quiet: nothing is logged."""
    exe = ctx.which(str(argv[0]))
    if not exe:
        return None, ""
    try:
        r = subprocess.run([exe, *[str(a) for a in argv[1:]]], capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           env={**os.environ, "PATH": ctx.fresh_path()}, creationflags=S.NO_WINDOW)
    except (subprocess.TimeoutExpired, OSError):
        return None, ""
    return r.returncode, S.decode(r.stdout) + S.decode(r.stderr)


def table(head, rows, widths):
    out = [" ".join(f"{h:<{w}}" for h, w in zip(head, widths)).rstrip()]
    for r in rows:
        out.append(" ".join(f"{str(c)[:w]:<{w}}" if i < len(r) - 1 else str(c) for i, (c, w) in enumerate(zip(r, widths))).rstrip())
    return "\n".join(out)


# ── scrub: what may leave this machine ───────────────────────────────────────────────────────────────────────
def redact(text):
    """Credential-shaped spans out, through the kit's own scanner (_wb.redact). When it cannot load, the text is withheld."""
    scripts = str(KIT / "plugins" / "workbench-core" / "scripts")
    sys.path.insert(0, scripts)
    try:
        import _wb
        return _wb.redact(text)
    except Exception:
        return "[text withheld: the kit's redaction could not load]"
    finally:
        if scripts in sys.path:
            sys.path.remove(scripts)


def identity():
    """What identifies this person's machine: user (account and profile folder), computer, domain (and its labels) and company
    (the OneDrive tenant name, the DNS domain's own labels). Read from the environment and the home folder only."""
    ids = {"user": set(), "host": set(), "domain": set(), "company": set()}

    def add(kind, v):
        v = str(v or "").strip().strip("\\/")
        if len(v) >= 2:
            ids[kind].add(v)
            if kind == "host":
                ids[kind].add(v.split(".")[0])
    for v in (os.environ.get("USERNAME"), os.environ.get("USER"), Path.home().name, os.path.basename(os.environ.get("USERPROFILE", "")),
              os.path.basename(os.environ.get("HOME", ""))):
        add("user", v)
    try:
        add("user", getpass.getuser())
    except Exception:
        pass
    for v in (os.environ.get("COMPUTERNAME"), os.environ.get("LOGONSERVER"), platform.node()):
        add("host", v)
    for v in (os.environ.get("USERDOMAIN"), os.environ.get("USERDNSDOMAIN"), os.environ.get("USERDOMAIN_ROAMINGPROFILE")):
        add("domain", v)
    labels = str(os.environ.get("USERDNSDOMAIN") or "").strip(".").split(".")
    for lab in labels[:-1]:                                    # corp.acmeg.example -> corp, acmeg; the last label is the TLD
        if len(lab) >= 3:
            add("company", lab)
    folders = [os.environ.get(k, "") for k in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")]
    try:
        folders += I.onedrive_roots()[2]
    except Exception:
        pass
    try:
        folders += [str(p) for p in Path.home().glob("OneDrive - *")]
    except OSError:
        pass
    for f in folders:
        m = re.match(r"(?i)OneDrive - (.+)$", Path(str(f)).name)
        if m:                                                  # "OneDrive - Example Holdings Ltd": the whole name and each real word
            add("company", m.group(1))
            for w in re.split(r"[\s,.&_-]+", m.group(1)):
                if len(w) >= 4 and w.lower() not in COMPANY_STOP:
                    add("company", w)
    ids["company"] = {c for c in ids["company"] if c.lower() not in COMPANY_STOP}
    return ids


def known_hosts():
    hosts = set(EXTRA_HOSTS)
    try:
        doc = I.read_json(HERE / "packages.json")
        hosts |= {h.lower() for p in doc.get("packages") or [] for h in p.get("hosts") or []}
        hosts |= {str(e.get("host")).lower() for e in doc.get("endpoints") or [] if e.get("host")}
    except (OSError, ValueError):
        pass
    return hosts


def scrub(text, ids=None):
    """text for the kit author: credentials redacted, e-mail addresses, UNC server names, the Windows user, computer and domain
    names, "OneDrive - <company>" folder names and every place a company token occurs inside a path or a name, IP addresses,
    one-label host:port proxies and every host that is not in the kit's own package table, replaced by <user>, <host>, <domain>,
    <company>. Scrub the WHOLE text first and cut it afterwards: a cut in front of the scrub can leave a token's first letters."""
    text = redact(str(text))
    ids, allowed = ids or identity(), known_hosts()
    text = COMPANY.sub(r"\1\2<company>", UNC.sub(r"\\\\<host>", EMAIL.sub("<email>", text)))
    for kind in ("domain", "host", "user"):
        for tok in sorted(ids[kind], key=len, reverse=True):
            text = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(tok)}(?![A-Za-z0-9_])", f"<{kind}>", text, flags=re.I)
    for tok in sorted(ids["company"], key=len, reverse=True):      # inside names too: Example-Kb, ExampleSales, \\Example\\
        if len(tok) >= 4:
            text = re.sub(re.escape(tok), "<company>", text, flags=re.I)
    text = IPV4.sub("<host>", text)
    text = HOSTPORT.sub(lambda m: m.group(0) if m.group(1).lower() in PORT_WORDS else f"<host>:{m.group(2)}", text)

    def host(m):
        h = m.group(0).lower()
        if h.rsplit(".", 1)[-1] in FILE_EXT or any(h == a or h.endswith("." + a) for a in allowed):
            return m.group(0)
        return "<host>"
    return HOSTLIKE.sub(host, text)


# ── the update ───────────────────────────────────────────────────────────────────────────────────────────────
def resolve_repo(ctx, arg, new_repo=False):
    """OWNER/REPO the releases come from. A repository the kit remembers (config.json kit_repo) outranks the environment and the
    kit's own file, and --repo may not name a different one unless --new-repo says the repository really moved."""
    def ok(src, v):
        if not SLUG.fullmatch(str(v)):
            raise I.Stop(2, f"{src}: '{v}' is not an OWNER/REPO name")
        return str(v)
    remembered = ctx.cfg.get("kit_repo")
    if remembered:
        ok("config.json kit_repo", remembered)
    if arg:
        ok("--repo", arg)
        if remembered and arg.lower() != str(remembered).lower() and not new_repo:
            raise I.Stop(2, f"this kit remembers {remembered} as the repository its releases come from, and --repo names {arg}. "
                            "Nothing was downloaded. If the repository really moved, run again with --new-repo.")
        return arg
    for src, v in (("config.json kit_repo", remembered), ("env WB_KIT_REPO", os.environ.get("WB_KIT_REPO")),
                   (fwd(SOURCE), (S.jload(KIT / SOURCE, {}) or {}).get("repo"))):
        if v:
            return ok(src, v)
    raise I.Stop(2, "this copy of the kit does not say where its releases live. Run again with --repo OWNER/REPO (the repository of "
                    "the release page you downloaded the kit from); it is remembered after the first success.")


def get(ctx, url, dest, header=None):
    """curl through setup's helper (so the Windows revocation retry applies): HTTPS only, redirects too, no credentials."""
    host = urlsplit(url).hostname
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    rc, out = S.curl(ctx, ["--fail", "--location", "--silent", "--show-error", "--proto", "=https", "--proto-redir", "=https",
                           *(["-H", header] if header else []), "-o", str(dest), "-w", "%{http_code}", url], timeout=900)
    if rc is None:
        raise I.Stop(4, "curl was not found on PATH (Windows 10 and later ship curl.exe); nothing was changed")
    if rc != 0:
        code = (re.findall(r"\d{3}", S.decode(out)) or [""])[-1]
        if code in ("403", "407", "429"):
            raise I.Stop(3, f"{host} answered HTTP {code}: a proxy or GitHub's anonymous rate limit stopped the request. Ask IT to "
                            "allow api.github.com, github.com and release-assets.githubusercontent.com, or try again later. "
                            "Nothing was changed.")
        raise I.Stop(4, f"could not download from {host} (curl exit {S.hx(rc)}); nothing was changed")


def published(rel, asset):
    """Every SHA-256 the release publishes for this asset: the API's digest field and the checksum table in the notes."""
    found = []
    d = str(asset.get("digest") or "").lower()
    if re.fullmatch(r"sha256:[0-9a-f]{64}", d):
        found.append(d[7:])
    for m in re.finditer(rf"{re.escape(asset['name'])}[^\n]*?\b([0-9a-fA-F]{{64}})\b", str(rel.get("body") or "")):
        found.append(m.group(1).lower())
    return found


def latest_release(ctx, repo):
    """{tag, version, asset, url, size, sha256}: the newest published release and the one hash its asset is checked against."""
    dest = ctx.state_dir / "kit-update" / "latest.json"
    get(ctx, API.format(repo), dest, "Accept: application/vnd.github+json")
    rel = S.jload(dest, None)
    tag = str((rel or {}).get("tag_name") or "")
    m = re.fullmatch(r"v(\d+\.\d+\.\d+)", tag)
    if not m or rel.get("draft") or rel.get("prerelease"):
        raise I.Stop(4, f"the latest release of {repo} is not a plain vX.Y.Z release ({tag or 'no tag'}); nothing was changed")
    name = ASSET.format(tag=tag, ext=".zip" if S.WIN else ".tar.gz")
    asset = next((a for a in rel.get("assets") or [] if isinstance(a, dict) and a.get("name") == name), None)
    if not asset:
        raise I.Stop(4, f"release {tag} has no {name}; nothing was changed")
    url = str(asset.get("browser_download_url") or "")
    if not url.startswith(DOWNLOADS.format(repo) + tag + "/"):
        raise I.Stop(4, f"the {name} download is not under {repo}'s release downloads; nothing was changed")
    hashes = published(rel, asset)
    if not hashes:
        raise I.Stop(4, f"release {tag} publishes no SHA-256 for {name}; nothing was downloaded")
    if len(set(hashes)) > 1:
        raise I.Stop(4, f"release {tag} publishes two different SHA-256 values for {name}; nothing was downloaded")
    return {"tag": tag, "version": m.group(1), "name": name, "url": url, "size": asset.get("size"), "sha256": hashes[0]}


MAX_ENTRIES, MAX_BYTES = 20_000, 500 * 1024 * 1024          # a release unpacks to a few thousand files and well under 100 MB


def too_big(entries, total):
    """The Stop for an archive over the caps (checked from the member list, before anything is written)."""
    if entries > MAX_ENTRIES or total > MAX_BYTES:
        what = f"more than {MAX_ENTRIES:,} entries" if entries > MAX_ENTRIES else f"more than {MAX_BYTES // 2**20} MB unpacked"
        raise I.Stop(4, f"the archive holds {what}, far more than any release; nothing was installed")


def unpack(archive, dest):
    """Extract into dest; any member that leaves dest (absolute, drive letter, ..) or any link/device stops everything, and so does an
    archive over MAX_ENTRIES entries or MAX_BYTES unpacked (the sizes the archive declares: zipfile and tarfile read no more than that)."""
    dest = Path(dest)
    dest.mkdir(parents=True)
    root = dest.resolve()

    def inside(name):
        n = name.replace("\\", "/")
        p = (root / n).resolve()
        return not (n.startswith("/") or re.match(r"[A-Za-z]:", n)) and (p == root or root in p.parents)
    if str(archive).endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            infos = z.infolist()
            too_big(len(infos), sum(i.file_size for i in infos))
            bad = next((i.filename for i in infos if not inside(i.filename)), None)
            if bad:
                raise I.Stop(4, f"the archive holds a path outside its folder ({bad}); nothing was installed")
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            members, total = [], 0
            for m in t:                                        # one at a time: stop at the cap instead of listing a bomb
                members.append(m)
                total += max(0, m.size)
                too_big(len(members), total)
            bad = next((m.name for m in members if not inside(m.name) or m.issym() or m.islnk() or m.isdev()), None)
            if bad:
                raise I.Stop(4, f"the archive holds an unsafe entry ({bad}); nothing was installed")
            try:
                t.extractall(dest, members=members, filter="data")
            except TypeError:                                  # Python before the extraction filters: the check above stands
                t.extractall(dest, members=members)
    for cand in (dest, *[p for p in dest.iterdir() if p.is_dir()]):
        if (cand / "bootstrap" / "install.py").is_file():
            return cand
    raise I.Stop(4, "the archive holds no bootstrap/install.py; nothing was installed")


def cmd_update(ctx, repo_arg=None, check=False, budget=90, run=run_py, new_repo=False):
    t_call, run_file = time.time(), ctx.state_dir / RUN_FILE
    rs = S.jload(run_file)
    if rs and rs.get("stage") in ("setup", "doctor"):           # an earlier call got this far: carry on from there
        return advance(ctx, rs, budget, run)
    if S.lock_holder(ctx) and not check:                       # a setup run on the old kit would find its files replaced under it
        raise I.Stop(2, f"setup is already running (pid {S.lock_holder(ctx)}); wait for it to finish, then run this again")
    repo = resolve_repo(ctx, repo_arg, new_repo)
    rel = latest_release(ctx, repo)
    steps = [("latest release", "PASS", f"{rel['tag']} (installed v{I.VERSION})")]
    current = S.vkey(rel["version"]) <= S.vkey(I.VERSION)
    if check:
        print(f"The kit is already current (installed v{I.VERSION}, latest {rel['tag']})." if current else
              f"A newer kit is out: {rel['tag']} (installed v{I.VERSION}). Run kit_update.py to install it.")
        return 0
    if current:
        print(f"The kit is already current (installed v{I.VERSION}, latest {rel['tag']}). Running the verify.")
        S.set_config(ctx, kit_repo=repo)
        return cmd_verify(ctx, run, budget)
    (ctx.state_dir / "kit-update").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"{rel['tag']}-", dir=ctx.state_dir / "kit-update"))      # a fresh folder every time
    z = work / rel["name"]
    get(ctx, rel["url"], z)
    got = I.sha(z)
    if got != rel["sha256"]:
        z.unlink(missing_ok=True)
        raise I.Stop(4, f"SHA-256 mismatch for {rel['name']} (published {rel['sha256'][:12]}..., downloaded {(got or 'nothing')[:12]}...): "
                        "the download was deleted and nothing was installed")
    steps.append(("download + SHA-256", "PASS", f"{rel['name']}, {z.stat().st_size:,} bytes, matches the published value"))
    new = unpack(z, work / "kit")
    says = re.search(r'(?m)^VERSION = "(\d+\.\d+\.\d+)"', (new / "bootstrap" / "install.py").read_text(encoding="utf-8", errors="replace"))
    if not says or says.group(1) != rel["version"]:
        raise I.Stop(4, f"the package says it is v{says.group(1) if says else '?'}, the release says {rel['tag']}; nothing was installed")
    opts = sorted(ctx.with_)
    keep = ["--with", ",".join(opts)] if opts else []
    here = os.getcwd()
    os.chdir(ctx.state_dir)                                    # the installer replaces <WB>/kit: Windows cannot delete a folder that is a cwd
    try:
        rc, out, err = run(ctx, new / "bootstrap" / "install.py", "--apply", "--profile", ctx.profile, *keep, timeout=1800)
    finally:
        os.chdir(here)
    if rc != 0:
        tail = " | ".join((out + err).strip().splitlines()[-3:])
        raise I.Stop(3 if rc == 3 else 4, f"install.py --apply exited {rc}: {tail}. " + (
            "Your organisation's policy stopped it: quote this to IT, do not retry another way." if rc == 3 else f"The unpacked release is kept in {fwd(work)}."))
    steps.append(("install", "PASS", f"install.py --apply --profile {ctx.profile}" + (f" --with {','.join(opts)}" if opts else "")))
    S.set_config(ctx, kit_repo=repo)
    flags = [*(["--no-nightly"] if ctx.no_nightly else []), *(["--no-update"] if ctx.no_update else [])]
    started = S.now()
    rc, out, err = run(ctx, setup_py(ctx), "run", "--detach", *keep, *flags, timeout=300)
    if rc not in (0, 2):                                       # 2: a run is already going; wait for that one
        raise I.Stop(4, f"setup.py run --detach exited {rc}: {' | '.join((out + err).strip().splitlines()[-3:])}")
    rs = {"stage": "setup", "tag": rel["tag"], "version": rel["version"], "from_version": I.VERSION, "started": started,
          "started_t": time.time(), "work": fwd(work), "steps": [list(s) for s in steps]}
    S.jwrite(run_file, rs)
    return advance(ctx, rs, max(0, budget - (time.time() - t_call)), run)          # the download and the install were part of the wait


def setup_stopped(ctx, st, since):
    """The message for a setup run that never finished: it wrote its state in this run (it started, then died) or it did not."""
    redo = f'py -3 "{fwd(setup_py(ctx))}" run --detach'
    if not (st.get("pid") and str(st.get("updated") or "") >= since):
        return (f"setup did not start within 3 minutes. To recover, run {redo}, then run this same command again "
                "(setup.log in the state folder says why, if it was started at all)")
    tail = ""
    try:
        lines = [x.strip() for x in (ctx.state_dir / "setup.log").read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
        tail = f" Last line of setup.log: {lines[-1][:200]}" if lines else ""
    except OSError:
        pass
    return (f"setup started (pid {st['pid']}, last phase {st.get('phase')}) but stopped before it finished.{tail} To recover, run {redo}, "
            "then run this same command again")


def wait_setup(ctx, since, budget, run, t_started=None):
    """The setup state once the detached run is over, or {"running": True} when `budget` seconds pass first. The state's `updated`
    stamp tells this run from an older finished one; `t_started` (time.time() when setup was started, kept across calls) is what
    "did not start within 3 minutes" is measured from."""
    t0, seen, last = time.time(), False, None
    t_started = t0 if t_started is None else t_started
    while True:
        w = max(1, min(60, int(budget - (time.time() - t0))))            # never block a call past its own budget
        _, out, _ = run(ctx, setup_py(ctx), "status", "--json", "--wait", str(w), timeout=w + 120)
        st = S.json_in(out.encode("utf-8"))
        running = bool(st.get("running"))
        seen = seen or running
        if st.get("phase") != last:
            last = st.get("phase")
            print(f"  setup phase: {last}", flush=True)
        if not running and str(st.get("updated") or "") >= since and (st.get("exit_code") is not None or st.get("reboot_pending")):
            return st
        if not running and not seen and time.time() - t_started > 180:
            raise I.Stop(4, setup_stopped(ctx, st, since))
        if time.time() - t0 >= budget:
            return {"running": True, "phase": last}
        if not running:
            nap(2)                                       # not started yet, or between two writes of the state


def spawn(ctx, out, run):
    """Start `kit_update.py _doctor OUT` detached and return its pid. The seam tests replace (they run the job in place)."""
    cmd = [S.pythonw(), str(Path(__file__).resolve()), "_doctor", str(out)]
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, cwd=str(ctx.state_dir))
    if S.WIN:
        base = 0x00000008 | 0x00000200                          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        try:
            return subprocess.Popen(cmd, creationflags=base | 0x01000000, **kw).pid       # and out of the caller's job object
        except OSError:
            return subprocess.Popen(cmd, creationflags=base, **kw).pid
    return subprocess.Popen(cmd, start_new_session=True, **kw).pid


def doctor_job_main(ctx, out, run):
    """The background job: `setup.py doctor --deep --json`, its answer written whole (and atomically) to `out`."""
    rc, text, err = run(ctx, setup_py(ctx), "doctor", "--deep", "--json", timeout=3600)
    S.jwrite(out, {"rc": rc, "out": text, "err": err[-2000:]})


def doctor_job(ctx, purpose, budget, run):
    """{"rc", "out", "err"} of the doctor --deep job for `purpose` ("update" or "verify"), or None while it is still running (call
    again). A job is started once and survives the call that started it, so no single call has to outlast the doctor."""
    d = ctx.state_dir / "kit-update"
    d.mkdir(parents=True, exist_ok=True)
    jf, out = d / f"doctor-{purpose}.json", d / f"doctor-{purpose}.out.json"
    job = S.jload(jf)
    started = parse_time((job or {}).get("started"))
    if job and (not started or datetime.datetime.now(datetime.timezone.utc) - started > datetime.timedelta(hours=6)):
        job = None                                              # a job nobody collected: its answer is old, run the check again
    if not job:
        out.unlink(missing_ok=True)
        job = {"started": S.now(), "pid": spawn(ctx, out, run)}
        S.jwrite(jf, job)
    t0 = time.time()
    while True:
        res = S.jload(out) if out.is_file() else None
        if res is not None:
            break
        if not S.pid_alive(job.get("pid")):
            res = {"rc": None, "out": "", "err": "the doctor job ended without an answer"}
            break
        if time.time() - t0 >= budget:
            return None
        nap(3)
    jf.unlink(missing_ok=True)
    out.unlink(missing_ok=True)
    return res


def advance(ctx, rs, budget, run):
    """The later stages of an update, each short and resumable: setup (waited for), then the doctor job, then the marker."""
    t0, run_file = time.time(), ctx.state_dir / RUN_FILE
    steps = rs.setdefault("steps", [["download + SHA-256", "PASS", "done by the earlier call"], ["install", "PASS", "done by the earlier call"]])
    if rs["stage"] == "setup":
        st = wait_setup(ctx, rs["started"], budget, run, rs.get("started_t"))
        if st.get("running"):
            print(f"Setup is still running (phase {st.get('phase')}). Run the same command again to keep waiting.")
            return 6
        code = st.get("exit_code")
        if st.get("reboot_pending") and code is None:
            print(table(("STEP", "RESULT", "DETAIL"), [*steps, ("setup", "WARN", "a reboot is needed; after you sign in setup resumes "
                                                              "by itself. Run this command again then.")], (22, 7, 80)))
            return 5
        bad = "; ".join(f"{x['item']}: {x['error']}" for x in st.get("failed") or [])
        steps.append(["setup", "FAIL" if code == 4 else "PASS", bad or f"exit {code}" + (f", {len(st['ask_it'])} item(s) for IT" if st.get("ask_it") else "")])
        rs["stage"] = "doctor"
        S.jwrite(run_file, rs)
    res = doctor_job(ctx, "update", max(1.0, budget - (time.time() - t0)), run)
    if res is None:
        print("Setup is done; its health check (doctor --deep) is still running. Run the same command again to keep waiting.")
        return 6
    rows = S.json_in(str(res.get("out") or "").encode("utf-8")).get("rows") or []
    n = {k: sum(1 for r in rows if r.get("status") == k) for k in ("OK", "WARN", "FAIL")}
    steps.append(["doctor --deep", "FAIL" if res.get("rc") == 2 or n["FAIL"] else "WARN" if n["WARN"] else "PASS" if rows else "FAIL",
                  f"{n['OK']} OK, {n['WARN']} WARN, {n['FAIL']} FAIL" if rows else f"no result (exit {res.get('rc')})"])
    S.jwrite(ctx.state_dir / S.MARKER, {"version": rs["version"], "time": S.now(), "from_version": rs["from_version"], "source": "kit_update"})
    run_file.unlink(missing_ok=True)
    if rs.get("work"):
        shutil.rmtree(rs["work"], ignore_errors=True)
    print(f"Kit update v{rs['from_version']} -> v{rs['version']}")
    print(table(("STEP", "RESULT", "DETAIL"), steps, (22, 7, 80)))
    print(f"\nThe release's own update notes (read the \"Updating\" section; do any step it adds): {fwd(ctx.wb / 'kit' / 'IMPORT.md')}")
    print("\n" + RESTART)
    return 0 if all(s[1] == "PASS" for s in steps) else 1


# ── the verify ───────────────────────────────────────────────────────────────────────────────────────────────
def R(rid, check, status, detail, cmd="", lines=(), public=None, kit=True):
    public = detail if public is None else public
    return {"id": rid, "check": check, "status": status, "detail": detail, "public": public, "cmd": cmd,
            "lines": list(lines) or [x for x in re.split(r"\n|; ", public) if x][:3], "kit": kit}


def plugin_rows(ctx):
    sp = ctx.ch / "settings.json"
    try:
        user = I.read_json(sp) if sp.exists() else {}
    except (OSError, ValueError) as e:
        return [R("settings", "settings.json", "FAIL", f"not valid JSON ({e})", "py -3 <KIT>/bootstrap/setup.py doctor")]
    rows = []
    for pid in I.python_plugin_ids(KIT) or I.PLUGIN_IDS:
        name = pid.split("@")[0]
        fix = f"claude plugin install {pid} --config python=<python>"
        py = (((user.get("pluginConfigs") or {}).get(pid) or {}).get("options") or {}).get("python")
        if (user.get("enabledPlugins") or {}).get(pid) is not True:
            rows.append(R(f"plugin-python:{name}", f"plugin python: {name}", "FAIL", "the plugin is not enabled in settings.json", fix))
        elif not py or not isinstance(py, str):
            rows.append(R(f"plugin-python:{name}", f"plugin python: {name}", "FAIL",
                          'python option not set: every hook fails with `Plugin option "python" isn\'t set`', fix))
        elif probe(ctx, [py, "--version"])[0] != 0:
            rows.append(R(f"plugin-python:{name}", f"plugin python: {name}", "FAIL", "the configured interpreter does not run", fix))
        else:
            rows.append(R(f"plugin-python:{name}", f"plugin python: {name}", "PASS", "option set, interpreter runs"))
    return rows


def hook_row(ctx, since):
    logs = sorted((ctx.ch / "debug").glob("*.txt"), key=lambda p: p.stat().st_mtime) if (ctx.ch / "debug").is_dir() else []
    if not logs:
        return R("hook-errors", "hook errors", "INFO", "not measured: no Claude Code debug log")
    log = logs[-1]
    when = datetime.datetime.fromtimestamp(log.stat().st_mtime, datetime.timezone.utc)
    if since and when < since:
        return R("hook-errors", "hook errors", "INFO", "not measured: the newest debug log is older than the update")
    with open(log, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 8_000_000))
        text = S.decode(f.read())
    hits = [ln.strip() for ln in text.splitlines() if "Hook failed to run" in ln or "isn't set" in ln]
    if not hits:
        return R("hook-errors", "hook errors", "PASS", f"0 'Hook failed to run' / \"isn't set\" lines in the newest debug log")
    return R("hook-errors", "hook errors", "FAIL", f"{len(hits)} 'Hook failed to run' / \"isn't set\" line(s) in the newest debug log",
             "findstr /C:\"Hook failed to run\" <newest file in ~/.claude/debug>", [x[:4000] for x in hits[:3]])


def heartbeat_row(ctx, since):
    """After an update the guard counts only when a session STARTED after the update (last_start > the marker) and the guard fired in
    it (last_fired >= last_start): a fire from before the restart proves nothing about the new plugins."""
    hb = S.jload(ctx.state_dir / "guard-heartbeat.json", {}) or {}
    fired, started = parse_time(hb.get("last_fired")), parse_time(hb.get("last_start"))
    cmd = "py -3 <KIT>/bootstrap/setup.py doctor"
    if not fired:
        return R("guard-heartbeat", "guard heartbeat", "FAIL", "the guard has not fired in any Claude Code session yet", cmd)
    if since:
        if not started or started <= since:
            return {**R("guard-heartbeat", "guard heartbeat", "FAIL", f"no Claude Code session has started since the update at "
                        f"{since:%Y-%m-%dT%H:%M:%SZ} (last session start {hb.get('last_start') or 'never'}): close every Claude Code window "
                        "and start a new one", cmd), "restart_due": True}
        if fired < started:
            return R("guard-heartbeat", "guard heartbeat", "FAIL", f"the guard last fired {hb.get('last_fired')}, before this session "
                     f"started ({hb.get('last_start')}): the plugin hooks are not running", cmd)
        return R("guard-heartbeat", "guard heartbeat", "PASS", f"fired {hb.get('last_fired')}, in the session started {hb.get('last_start')} "
                 "(after the update)")
    n = int(hb.get("sessions_since_fire") or 0)
    if n >= 3:
        return R("guard-heartbeat", "guard heartbeat", "FAIL", f"last fired {hb.get('last_fired')}; {n} session(s) since", cmd)
    return R("guard-heartbeat", "guard heartbeat", "PASS", f"last fired {hb.get('last_fired')}")


# One line of the guard log: `<local time> sid=.. tool=.. cwd=.. [level=..] BLOCK|ASK [rule-id] ...` (the engine writes it; the level field
# is newer than some kits). The engine does not quote the folder name, so the folder may hold spaces and text that looks like a decision.
# Only the time, BLOCK or ASK and a rule id the installed guard can emit are read: the rest of a line holds commands and paths.
GUARD_PREFIX = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d) sid=\S* tool=\S* cwd=(.*)$")
GUARD_DECISION = re.compile(r" (?:level=\S+ )?(BLOCK|ASK) \[([^\]\s]{1,60})\]")
GUARD_OTHER_MSG = re.compile(r" (?:ERROR|PASS|READFLOOD)\b")
RULE_ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+")


@functools.lru_cache(maxsize=4)
def guard_rule_ids(kit):
    """The rule ids the kit's guard can emit, read from its own source (the engine and its rulepacks): the second argument of every
    block(..) / ask(..) call (the first of relaxed(..)), and every hyphenated lowercase string constant (the id tables hold their ids as plain constants).
    Empty when the source is not there: every decision then counts as "other"."""
    ids, g = set(), Path(kit) / "plugins" / "workbench-core" / "scripts" / "guards"
    for f in [g / "engine.py", *sorted((g / "rulepacks").glob("*.py"))]:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", "")) in ("block", "ask", "relaxed"):
                at = 0 if getattr(n.func, "attr", getattr(n.func, "id", "")) == "relaxed" else 1             # relaxed(gid, ..), block(reason, gid, ..)
                if len(n.args) > at and isinstance(n.args[at], ast.Constant) and isinstance(n.args[at].value, str):
                    ids.add(n.args[at].value)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and RULE_ID.fullmatch(n.value):
                ids.add(n.value)
    return frozenset(ids)


def guard_decision(rest, ids):
    """(BLOCK or ASK, rule id) of a guard-log line, with "other" for an id the guard cannot emit, or None when the line holds no decision.
    `rest` is everything after `cwd=`. Folder text that looks like a decision is skipped unless its id is a real one, and an ERROR, PASS
    or READFLOOD message ends the search: its text quotes whatever it likes."""
    seen = None
    for m in GUARD_DECISION.finditer(rest):
        if GUARD_OTHER_MSG.search(rest[:m.start()]):
            break
        if m.group(2) in ids:
            return m.group(1), m.group(2)
        seen = m if seen is None or "level=" in m.group(0) else seen          # the engine's own level field marks its decision
    if seen and not GUARD_OTHER_MSG.search(rest[seen.end():]):
        return seen.group(1), "other"
    return None


def activity_row(ctx, since):
    """What the guard denied (BLOCK) and asked about, per rule id, since the update: counts and the five busiest rule ids, nothing else
    of the log; an id the installed guard cannot emit is counted as "other", never shown. Information, never a kit failure: a deny is
    the guard working."""
    d = Path(os.environ.get("GUARDS_LOG_DIR") or os.environ.get("WORKBENCH_LOG_DIR") or ctx.wb / "logs")
    per, read, ids = {}, False, guard_rule_ids(KIT)
    for f in (d / "guards.log.1", d / "guards.log"):
        try:
            with open(f, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - 8_000_000))
                text = S.decode(fh.read())
        except OSError:
            continue
        read = True
        for ln in text.splitlines():
            m = GUARD_PREFIX.match(ln)
            try:
                when = datetime.datetime.fromisoformat(m.group(1)).astimezone(datetime.timezone.utc) if m else None   # logged in local time
            except ValueError:
                when = None
            got = guard_decision(m.group(2), ids) if when else None
            if got and (not since or when >= since):
                per.setdefault(got[1], [0, 0])[got[0] == "ASK"] += 1
    if not read:
        return R("guard-activity", "guard activity", "INFO", "not measured: no guard log yet", kit=False)
    top = sorted(per.items(), key=lambda kv: (-sum(kv[1]), kv[0]))[:5]
    says = "; ".join(f"{g} ({', '.join(f'{n} {w}' for n, w in zip(c, ('deny', 'ask')) if n)})" for g, c in top)
    return R("guard-activity", "guard activity", "PASS", f"{sum(c[0] for c in per.values())} deny, {sum(c[1] for c in per.values())} ask "
             f"{'since the update' if since else 'in the guard log'}" + (f"; busiest rules: {says}" if top else ""), kit=False)


def path_row(ctx):
    if not S.WIN:
        return R("path", "PATH has <WB>/bin", "INFO", "Windows only")
    norm = lambda x: os.path.normcase(os.path.normpath(os.path.expandvars(x.strip()))) if x.strip() else ""  # noqa: E731
    want = norm(str(ctx.wb / "bin"))
    if want in {norm(x) for x in os.environ.get("PATH", "").split(os.pathsep)}:
        return R("path", "PATH has <WB>/bin", "PASS", "this Claude Code window sees it")
    reg = I.reg_get(S.ENV_KEY, "Path")
    if reg and want in {norm(x) for x in str(reg[0]).split(";")}:
        return R("path", "PATH has <WB>/bin", "WARN", "the user Path has it, this window does not: close every Claude Code window and "
                 "start a new one from a fresh terminal", kit=False)
    return R("path", "PATH has <WB>/bin", "FAIL", "neither this window nor the user Path has the workbench bin folder",
             "py -3 <KIT>/bootstrap/setup.py run --detach")


def doctor_rows(ctx, res):
    """([rows], [asks]) from a finished doctor --deep job: its rows that are not OK, minus the ones a request to IT covers (those are
    listed once, as asks). Rows about blocked hosts are IT's (NEEDS-IT, never a kit WARN); rows about the user's own machine
    (MCP servers, backup) are warnings that are not kit defects, and the public text of an MCP row names no server."""
    cmd = "py -3 <KIT>/bootstrap/setup.py doctor --deep --json"
    rows = S.json_in(str(res.get("out") or "").encode("utf-8")).get("rows")
    asks = ASKS.gather(str(ctx.state_dir))                  # after the run: the doctor's knowledge checks refreshed them
    if not isinstance(rows, list):
        return [R("doctor", "doctor --deep", "FAIL", f"no result (exit {res.get('rc')}): "
                  f"{(str(res.get('err') or '') or str(res.get('out') or '')).strip()[-4000:]}", cmd)], asks
    have_ask = {src.split()[-1] for a in asks for src in a["sources"] if src.startswith("day-1 check")}
    out_rows, ok, ask_folded = [], 0, 0
    for r in rows:
        check, status, detail = str(r.get("check")), str(r.get("status")), str(r.get("detail") or "")
        if check in OWN_ROWS or status in ("OK", "INFO"):
            ok += status == "OK"
            continue
        first = detail.split()[0] if detail.split() else ""
        if first in have_ask or (check == "setup" and "ask-IT" in detail):
            ask_folded += 1
            continue
        rid, name = f"doctor:{check}", f"doctor: {check}"
        if check in IT_ROWS:
            out_rows.append(R(rid, name, "NEEDS-IT", detail, cmd, public="hosts or TLS inspection that IT controls (see the IT asks)",
                              kit=False))
        elif check == "MCP servers":
            out_rows.append(R(rid, name, status, detail, cmd, public="one or more of the user's own MCP servers are DOWN (names withheld)",
                              kit=False))
        else:
            out_rows.append(R(rid, name, status, detail, cmd, kit=check not in NOT_KIT or status == "FAIL"))   # a crash is the kit's
    worst = "FAIL" if any(r["status"] == "FAIL" for r in out_rows) else "WARN" if any(r["status"] == "WARN" for r in out_rows) else "PASS"
    head = R("doctor", "doctor --deep", worst, f"{len(rows)} rows: {ok} OK, {len(out_rows)} not OK, {ask_folded} need IT (listed once below)",
             cmd, kit=False)
    return [head, *out_rows], asks


def skill_row(ctx):
    try:
        info = ST.measure(ctx.ch, KIT, Path.cwd(), managed=S.managed_settings())
    except Exception as e:                       # a broken skill file must not end the verify
        return R("skill-listing", "skill listing", "WARN", f"could not be measured ({type(e).__name__})")
    status, detail, public = ST.row(info)
    return R("skill-listing", "skill listing", "PASS" if status == "OK" else status, detail, "py -3 <KIT>/bootstrap/setup.py skills --dry-run",
             public=public)


def issues_row(ctx, since):
    got = []
    base = ctx.state_dir / "issues.jsonl"
    for p in (base.with_name(base.name + ".1"), base):
        try:
            for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                t = parse_time(r.get("time")) if isinstance(r, dict) else None
                if t and t >= (since or datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)):
                    got.append(r)
        except OSError:
            continue
    cmd = "py -3 <KIT>/plugins/workbench-core/scripts/issues.py show"
    if not got:
        return R("issues-log", "issues since update", "PASS", "0 failed tool calls logged")
    lines = []
    for r in got[-3:]:
        err = r.get("error")
        first = next((str(x) for x in (err if isinstance(err, list) else [err]) if str(x or "").strip()), "(no error text)")
        lines.append(f"{r.get('tool', '')}: {first}"[:4000])
    return R("issues-log", "issues since update", "WARN", f"{len(got)} failed tool call(s) logged since the update", cmd, lines)


def claude_version(ctx):
    rc, out = probe(ctx, ["claude", "--version"], 60)
    m = re.search(r"\d+\.\d+\.\d+", out) if rc == 0 else None          # probe gives text; setup's parse_version wants bytes
    return m.group(0) if m else None


def verify_rows(ctx, run, budget=90):
    """(rows, asks, marker), or None while the doctor --deep job is still running."""
    marker = S.jload(ctx.state_dir / S.MARKER, {}) or {}
    since = parse_time(marker.get("time"))
    res = doctor_job(ctx, "verify", budget, run)
    if res is None:
        return None
    rows = plugin_rows(ctx) + [hook_row(ctx, since), heartbeat_row(ctx, since), activity_row(ctx, since), path_row(ctx)]
    drows, asks = doctor_rows(ctx, res)
    rows += drows + [skill_row(ctx), issues_row(ctx, since),
             R("it-asks", "IT asks", "NEEDS-IT" if asks else "PASS", f"{len(asks)} distinct ask(s), each listed once below" if asks
               else "none outstanding", kit=False)]
    return rows, asks, marker


def render(rows, asks, meta, public=False):
    ids = identity()
    fix = (lambda s: scrub(s, ids)) if public else (lambda s: s)       # noqa: E731
    cnt = {k: sum(1 for r in rows if r["status"] == k) for k in ("PASS", "WARN", "FAIL", "NEEDS-IT")}
    shown = [f"{'CHECK':<30} {'STATUS':<9} DETAIL"]
    for r in rows:                      # scrubbed first, then wrapped (never cut inside a word): the whole text stays on the screen
        parts = textwrap.wrap(fix(r["public"] if public else r["detail"]), 100) or [""]
        shown += [f"{r['check'][:30]:<30} {r['status']:<9} {parts[0]}", *[" " * 41 + x for x in parts[1:5]]]
    out = [f"Post-update verify · kit v{I.VERSION} · {S.now()}", "\n".join(shown),
           "", f"Result: {cnt['PASS']} PASS · {cnt['WARN']} WARN · {cnt['FAIL']} FAIL · {cnt['NEEDS-IT']} NEEDS-IT"]
    if asks:
        out += ["", "IT asks (send once; setup, the doctor and the capability report share this list):"]
        out += [f"  {i}. {fix(a['ask'])}" for i, a in enumerate(asks, 1)]
    out += ["", "FOR THE KIT AUTHOR (user, computer and domain names, unknown hosts and credentials are scrubbed; paste this box)",
            f"kit v{I.VERSION} · Claude Code {meta['claude'] or 'not found'} · {meta['os']}"]
    bad = [r for r in rows if r["status"] in ("FAIL", "WARN") and r["kit"]]
    for r in bad:
        out += [f"[{r['id']}] {r['check']} · {r['status']}", f"  command: {r['cmd'] or 'py -3 <KIT>/bootstrap/kit_update.py verify'}"]
        out += [f"  > {scrub(x, ids)[:300]}" for x in r["lines"][:3]]
    if not bad:
        out.append("none: every check passed, or needs IT.")
    return "\n".join(out)


def cmd_verify(ctx, run=run_py, budget=90):
    got = verify_rows(ctx, run, budget)
    if got is None:
        print("The health check (doctor --deep) is still running. Run the same command again to keep waiting.")
        return 6
    rows, asks, marker = got
    meta = {"claude": claude_version(ctx), "os": f"{platform.system()} {platform.version()}"}
    print(render(rows, asks, meta))
    path = ctx.state_dir / REPORT
    S.atomic_write(path, "```text\n" + render(rows, asks, meta, public=True) + "\n```\n")
    print(f"\nSaved: {fwd(path)} (scrubbed). Next: the live guard test (kit-update skill), then record it with: "
          "kit_update.py record guard-live PASS|FAIL \"<text>\"")
    if any(r.get("restart_due") for r in rows):                        # run before the restart: the next session still has to run it
        print("\nThe update marker stays: no Claude Code session has started since the update. Close every Claude Code window, start a "
              "new one and run this again.")
    else:
        (ctx.state_dir / S.MARKER).unlink(missing_ok=True)             # the verify ran
    return 2 if any(r["status"] == "FAIL" for r in rows) else 1 if any(r["status"] == "WARN" for r in rows) else 0


def cmd_record(ctx, rid, status, text, command=""):
    path = ctx.state_dir / REPORT
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    add = ("" if "## Added after the script" in old else "\n## Added after the script\n")
    add += f"- [{scrub(rid)}] {status}: {scrub(text)[:400]}\n"
    if status in ("FAIL", "WARN"):
        add += f"  command: {scrub(command) or '(not given)'}\n"
    S.atomic_write(path, old + add)
    print(f"recorded in {fwd(path)}: {rid} {status}")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    if not argv or argv[0].startswith("-"):
        argv = ["update", *argv]
    ap = argparse.ArgumentParser(description="claude-workbench kit update (see the module docstring)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("update")
    p.add_argument("--repo")
    p.add_argument("--new-repo", action="store_true", help="--repo may name a repository other than the remembered one")
    p.add_argument("--check", action="store_true")
    p.add_argument("--wait", type=float, default=90)
    p = sub.add_parser("verify")
    p.add_argument("--wait", type=float, default=90)
    sub.add_parser("_doctor").add_argument("out")
    p = sub.add_parser("record")
    p.add_argument("id")
    p.add_argument("status", choices=["PASS", "WARN", "FAIL"])
    p.add_argument("text")
    p.add_argument("--command", default="")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    ctx = S.Ctx()
    try:
        if a.cmd == "_doctor":                                  # the background job `spawn` starts; not for people
            return doctor_job_main(ctx, Path(a.out), run_py) or 0
        if a.cmd == "verify":
            return cmd_verify(ctx, budget=a.wait)
        if a.cmd == "record":
            return cmd_record(ctx, a.id, a.status, a.text, a.command)
        return cmd_update(ctx, a.repo, a.check, a.wait, new_repo=a.new_repo)
    except I.Stop as s:
        print(("STOP: " if s.code == 3 else "ERROR: ") + str(s))
        return s.code


if __name__ == "__main__":
    sys.exit(main())
