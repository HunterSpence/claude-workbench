#!/usr/bin/env python3
"""scrub_scan.py: find personal or sensitive identifiers before the kit is published.

  python tools/scrub_scan.py [PATH ...] [--denylist FILE] [--report SCRUB-REPORT.md] [--root DIR]

Scans text files under the given paths (default: the repository root): in a git work tree the files `git ls-files`
names (tracked plus untracked-not-ignored), elsewhere a walk that skips .git, caches and virtualenvs; binary files are
skipped either way. Two rule sets:
  built-in (G*)  G1 e-mail addresses (example.com/.org/.net, *.example, *.test, *.invalid, localhost and the
                    git@ SSH user are fine)
                 G2 IPv4 addresses (the RFC 5737 documentation ranges, loopback, the unspecified and broadcast
                    addresses and the cloud metadata address are fine)
                 G3 absolute per-user paths: C:\\Users\\<name>, /c/Users/<name>, /mnt/c/Users/<name>, /home/<name>,
                    /Users/<name> (placeholders such as <user>, %USERNAME% and Public are fine)
                 G4 phone numbers
                 G5 double-bracket wiki links (a personal knowledge-base link)
                 G6 credential shapes (the workbench secret scanner's patterns)
  denylist (D*)  --denylist FILE or the WORKBENCH_DENYLIST environment variable. One term per line, matched
                 case-insensitively wherever it is not glued to another letter or digit: `_`, `-`, `.` and a camelCase
                 step are boundaries, so foo_term_bar and fooTerm match and footerm does not. A line starting with `re:`
                 is a case-sensitive Python regex (add `(?i)` for case-insensitive); `#` starts a comment. Rule numbers
                 are the line numbers in that file.
A built-in (G) hit is allowed only when the same line contains `scrub-ok:` followed by a reason; allowed hits are still
counted. `scrub-ok:` never silences a denylist (D) hit: a private term has to leave the file.
Output never prints a denylist term: console and report name the rule number instead. The Markdown report names no
matched text at all (only rule, file and line), so it can be published. Exit 1 on any unallowed hit.
"""
import argparse
import ipaddress
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".ruff_cache",
             ".tox", "dist", "build", ".state"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".tgz", ".7z", ".exe", ".dll",
              ".so", ".dylib", ".pyc", ".db", ".sqlite", ".woff", ".woff2", ".ttf", ".otf", ".docx", ".xlsx", ".pptx"}
ALLOW = re.compile(r"scrub-ok:\s*\S")

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})(?![\w-])")  # alphabetic TLD, so npm pins like pkg@1.2.3 are not e-mail
_SAFE_MAIL = re.compile(r"(?i)(?:^|\.)(?:example\.(?:com|org|net)|example|test|invalid|localhost)$")
_IPV4 = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.]*\d)")
# Fine to publish: the RFC 5737 documentation ranges (TEST-NET-1/2/3, as integers so this file holds no address),
# loopback, unspecified, broadcast and link-local (the cloud metadata address).
_DOC_NETS = [ipaddress.ip_network((a << 8, 24)) for a in (0xC00002, 0xC63364, 0xCB0071)]


def _ip_ok(ip):
    return any(ip in n for n in _DOC_NETS) or ip.is_loopback or ip.is_unspecified or ip.is_link_local or \
        ip == ipaddress.IPv4Address(2 ** 32 - 1)
_PLACEHOLDER = (r"(?:<[^>\s]{1,20}>|%USERNAME%|%USERPROFILE%|\$USER|\$\{USER\}|\$env:USERNAME|\{\{[A-Z_]+\}\}|"
                r"Public|Default|All Users|user|username|you|me|runner|example|dev|name|USER|USERNAME|\*)")
_USERPATH = re.compile(r"(?i)(?:[A-Za-z]:[\\/]+Users|/mnt/[a-z]/Users|/[a-z]/Users|(?<![\w.~])/Users|(?<![\w.~])/home)"
                       r"[\\/]+(?!" + _PLACEHOLDER + r"(?:[\\/\s\"'`),;:]|$))([^\\/\s\"'`),;:<>]+)")
_PHONE = re.compile(r"(?<![\w.+-])(?:\+\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?![\w.-]*\d)|"
                    r"(?<![\w+])\+\d{11,15}(?!\d)")
_WIKI = re.compile(r"\[\[[^\[\]\n]{1,300}\]\]")


def _secret_patterns(root):
    """The workbench secret scanner's combined pattern (one home), else a small built-in set."""
    sys.path.insert(0, str(root / "plugins" / "workbench-core" / "scripts"))
    sys.dont_write_bytecode = True           # no __pycache__ left in the tree being scanned
    try:
        import secretscan
        return secretscan.scan_text
    except ImportError:
        rx = re.compile(r"AKIA[0-9A-Z]{16}|gh[pousr]_[0-9a-zA-Z]{36}|github_pat_\w{40,}|xox[baprs]-[\w-]{20,}|"
                        r"glpat-[\w-]{20,}|AIza[\w-]{35}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
        return lambda text: [(m.start(), m.end()) for m in rx.finditer(text)]


def generic_hits(line, scan_secrets):
    """[(rule, start, end)] for the built-in rules on one line."""
    out = []
    for m in _EMAIL.finditer(line):
        if not _SAFE_MAIL.search(m.group(1)) and not m.group(0).startswith("git@"):   # git@host: the SSH git user
            out.append(("G1", m.start(), m.end()))
    for m in _IPV4.finditer(line):
        try:
            ip = ipaddress.ip_address(m.group(1))
        except ValueError:
            continue
        if not _ip_ok(ip):
            out.append(("G2", m.start(1), m.end(1)))
    out += [("G3", m.start(), m.end()) for m in _USERPATH.finditer(line)]
    out += [("G4", m.start(), m.end()) for m in _PHONE.finditer(line)]
    out += [("G5", m.start(), m.end()) for m in _WIKI.finditer(line)]
    out += [("G6", a, b) for a, b in scan_secrets(line)]
    return out


def load_denylist(path):
    """[(rule id, compiled regex)]. Rule id = D<line number>. Never returns or prints the terms themselves."""
    rules = []
    for n, raw in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        try:
            rx = re.compile(s[3:].strip()) if s.startswith("re:") else re.compile(   # boundaries case-sensitive
                r"(?:(?<![A-Za-z0-9])|(?<=[a-z])(?=[A-Z]))(?i:" + re.escape(s) + r")(?:(?![A-Za-z0-9])|(?<=[a-z])(?=[A-Z]))")
        except re.error as e:
            raise SystemExit(f"denylist line {n} is not a valid regex: {e}")
        rules.append((f"D{n}", rx))
    return rules


def git_files(d):
    """The files git would publish from directory d (tracked plus untracked-not-ignored), or None outside a work tree."""
    try:
        r = subprocess.run(["git", "-C", str(d), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return sorted({Path(d) / f for f in r.stdout.decode("utf-8", "replace").split("\0") if f})


def iter_files(paths, skip):
    for p in paths:
        p = Path(p)
        if p.is_file():
            yield p
            continue
        listed = git_files(p)
        if listed is not None:
            for fp in listed:
                if fp.is_file() and fp.suffix.lower() not in BINARY_EXT and fp.resolve() not in skip and \
                        not SKIP_DIRS & set(fp.relative_to(p).parts[:-1]):
                    yield fp
            continue
        for dirpath, dirs, files in os.walk(p):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for f in sorted(files):
                fp = Path(dirpath) / f
                if fp.suffix.lower() not in BINARY_EXT and fp.resolve() not in skip:
                    yield fp


def read_text(fp):
    try:
        b = fp.read_bytes()
    except OSError:
        return None
    if b"\0" in b[:8192]:
        return None
    return b.decode("utf-8", errors="replace")


def scan(paths, root, deny_rules, skip=()):
    """-> (files scanned, hits). A hit is (path, line, rule, allowed, shown text) where shown text is the match for a
    built-in rule and None for a denylist rule."""
    scan_secrets = _secret_patterns(root)
    hits, nfiles = [], 0
    skip = {Path(s).resolve() for s in skip}
    for fp in iter_files(paths, skip):
        text = read_text(fp)
        if text is None:
            continue
        nfiles += 1
        try:
            rel = fp.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = fp.as_posix()
        for n, line in enumerate(text.splitlines(), 1):
            ok = bool(ALLOW.search(line))
            for rule, a, b in generic_hits(line, scan_secrets):
                hits.append((rel, n, rule, ok, line[a:b]))
            for rule, rx in deny_rules:
                if rx.search(line):
                    hits.append((rel, n, rule, False, None))      # scrub-ok never covers a denylist term
    return nfiles, hits


def write_report(path, nfiles, hits, deny_count):
    bad = [h for h in hits if not h[3]]
    allowed = [h for h in hits if h[3]]
    by_rule = Counter(h[2] for h in bad)
    lines = ["# Scrub report", "", f"- Files scanned: {nfiles}",
             f"- Denylist rules loaded: {deny_count}" + ("" if deny_count else " (no denylist given)"),
             f"- Unallowed hits: {len(bad)}", f"- Allowed hits (`scrub-ok:` with a reason): {len(allowed)}", "",
             "Rules G1-G6 are built in (see `tools/scrub_scan.py`); D<n> is line n of the private denylist, which is "
             "not published. This report names no matched text.", ""]
    if by_rule:
        lines += ["## Unallowed hits by rule", "", "| Rule | Hits |", "|---|---|"]
        lines += [f"| {r} | {c} |" for r, c in sorted(by_rule.items())]
        lines += ["", "## Locations", ""] + [f"- `{h[0]}:{h[1]}` {h[2]}" for h in bad]
    if allowed:
        lines += ["", "## Allowed hits", ""] + [f"- `{h[0]}:{h[1]}` {h[2]}" for h in allowed]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scan for personal or sensitive identifiers (see the module docstring).")
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--denylist", default=os.environ.get("WORKBENCH_DENYLIST"))
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    root = Path(a.root)
    deny = load_denylist(a.denylist) if a.denylist else []
    skip = [x for x in (a.report, a.denylist) if x]
    nfiles, hits = scan(a.paths or [root], root, deny, skip)
    bad = [h for h in hits if not h[3]]
    for rel, n, rule, ok, shown in hits:
        if not ok:
            print(f"{rel}:{n}  {rule}" + (f"  {shown[:80]}" if shown is not None else "  (denylist term)"))
    print(f"scanned {nfiles} files, {len(deny)} denylist rules: {len(bad)} unallowed hit(s), "
          f"{len(hits) - len(bad)} allowed by scrub-ok")
    if a.report:
        write_report(a.report, nfiles, hits, len(deny))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
