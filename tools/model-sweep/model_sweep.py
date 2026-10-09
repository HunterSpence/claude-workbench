#!/usr/bin/env python3
"""model_sweep.py: prove that no repository still names a retiring model id, except where you wrote it down.

  py -3 <KIT>/tools/model-sweep/model_sweep.py --pattern RX --control TEXT --allowlist FILE.tsv --repos DIR [DIR ...]
  py -3 <KIT>/tools/model-sweep/model_sweep.py --self-test

Scans every tracked text file of each repository (a folder that is not itself a git work-tree root is walked instead) for
lines matching the Python regular expression RX and prints one `repo/path:line` per hit that no allowlist row covers. Matching text is never
printed. Exit 0 = no unowned hit, 1 = at least one unowned hit, 2 = the gate itself is unusable (bad regex, bad
allowlist, missing folder, nothing scanned, or the positive control failed).

Allowlist (the frozen list of known, accepted hits): a tab-separated file, header `repo<TAB>path_glob<TAB>line_regex<TAB>reason`,
`#` lines ignored. A hit is covered when the repo name matches `repo` (glob), the path matches `path_glob` (glob, `*` crosses
folders) and `line_regex` is found in the hit's line. Every row needs a reason. Nothing is added to the list by this tool.

Positive control: --control TEXT is a line the pattern must match. Before the sweep the tool scans a throwaway folder that
holds that line and one clean line, with an empty allowlist, and requires exactly one hit. A pattern or a scan that cannot find
what it must makes the whole run exit 2 instead of reporting a clean sweep.
"""
import argparse
import fnmatch
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__"}


def load_allowlist(path):
    """[(repo glob, path glob, compiled line regex)] ; raises ValueError naming the line on a malformed row."""
    rows, header = [], False
    for n, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        cells = raw.split("\t")
        if not header:
            if [c.strip() for c in cells[:4]] != ["repo", "path_glob", "line_regex", "reason"]:
                raise ValueError(f"{path}:{n}: the first row must be the header repo, path_glob, line_regex, reason")
            header = True
            continue
        if len(cells) < 4 or not all(c.strip() for c in cells[:4]):
            raise ValueError(f"{path}:{n}: want four tab-separated cells, every one filled (the reason too)")
        try:
            rows.append((cells[0].strip(), cells[1].strip(), re.compile(cells[2])))
        except re.error as e:
            raise ValueError(f"{path}:{n}: bad line_regex ({e})")
    if not header:
        raise ValueError(f"{path}: no header row")
    return rows


def tracked_files(repo):
    """Paths relative to the repository, posix style: `git ls-files` when the folder is itself a work-tree root, else a walk."""
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    top = r.stdout.strip()
    if r.returncode == 0 and top and os.path.samefile(top, repo):
        out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True)
        if out.returncode != 0:
            raise OSError(f"git ls-files failed in {repo}")
        return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]
    rels = []
    for d, dirs, files in os.walk(repo):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        rels += [Path(d, f).relative_to(repo).as_posix() for f in files]
    return rels


def scan(repo, name, rx, allow):
    """(hits, unowned, files scanned): unowned is [`name/path:line`]."""
    hits, unowned, files = 0, [], 0
    for rel in tracked_files(repo):
        p = Path(repo, rel)
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8000]:
            continue
        files += 1
        for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            if rx.search(line):
                hits += 1
                if not any(fnmatch.fnmatchcase(name, r) and fnmatch.fnmatchcase(rel, g) and lr.search(line)
                           for r, g, lr in allow):
                    unowned.append(f"{name}/{rel}:{n}")
    return hits, unowned, files


def sweep(pattern, control, allowlist, repos, out=sys.stdout, err=sys.stderr):
    try:
        rx = re.compile(pattern)
        allow = load_allowlist(allowlist)
    except (re.error, ValueError, OSError) as e:
        print(f"model-sweep: {e}", file=err)
        return 2
    if "\n" in control or not rx.search(control):
        print("model-sweep: the control must be one line that the pattern matches", file=err)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "control.txt").write_text(control + "\nunrelated line\n", encoding="utf-8")
        _, bad, files = scan(tmp, "control", rx, [])
        if bad != ["control/control.txt:1"] or files != 1:
            print("model-sweep: the positive control failed, so a clean result would prove nothing", file=err)
            return 2
    total_hits, unowned, total_files = 0, [], 0
    for d in repos:
        if not Path(d).is_dir():
            print(f"model-sweep: no such folder: {d}", file=err)
            return 2
        root = Path(d).resolve()
        try:
            h, u, f = scan(root, root.name, rx, allow)
        except OSError as e:
            print(f"model-sweep: {e}", file=err)
            return 2
        total_hits, unowned, total_files = total_hits + h, unowned + u, total_files + f
    if total_files == 0:
        print("model-sweep: no file was scanned", file=err)
        return 2
    if unowned:
        print("\n".join(unowned), file=out)
    print(f"model-sweep: {len(repos)} repos, {total_files} files, {total_hits} hits, {len(unowned)} not allowlisted", file=err)
    return 1 if unowned else 0


def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        a = Path(tmp, "repo-a")
        a.mkdir()
        (a / "code.txt").write_text("use claude-oldmodel-1 here\nclean\n", encoding="utf-8")
        (a / "notes.txt").write_text("history: claude-oldmodel-1 was retired\n", encoding="utf-8")
        tsv = Path(tmp, "allow.tsv")
        tsv.write_text("repo\tpath_glob\tline_regex\treason\nrepo-a\tnotes.*\thistory\tkept as history\n", encoding="utf-8")
        sink = open(os.devnull, "w")
        pat = r"claude-oldmodel-\d"
        assert sweep(pat, "claude-oldmodel-1", tsv, [a], sink, sink) == 1
        (a / "code.txt").write_text("clean\n", encoding="utf-8")
        assert sweep(pat, "claude-oldmodel-1", tsv, [a], sink, sink) == 0
        assert sweep(pat, "no match", tsv, [a], sink, sink) == 2
    print("model_sweep self-test ok")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fail when a repository names a retiring model id outside the frozen allowlist.")
    ap.add_argument("--pattern")
    ap.add_argument("--control", help="a line the pattern must match (the positive control)")
    ap.add_argument("--allowlist")
    ap.add_argument("--repos", nargs="+")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    if not (a.pattern and a.control and a.allowlist and a.repos):
        ap.error("--pattern, --control, --allowlist and --repos are all required")
    return sweep(a.pattern, a.control, a.allowlist, a.repos)


if __name__ == "__main__":
    sys.exit(main())
