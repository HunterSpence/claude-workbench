#!/usr/bin/env python3
"""run_suites.py: the one-command regression runner. Skips are failures unless they are listed in tools/skips.allow.

  py -3 tools/run_suites.py --list                 every suite it would run (nothing is executed)
  py -3 tools/run_suites.py [--require-all]        run every suite, one at a time, each under tools/memcap
  options: --only SUBSTR (repeatable)  --skips FILE  --mb N  --no-cap  --timeout SECONDS  --root DIR  --scratch DIR

Discovery is `git ls-files`: a directory holding test_*.py is a unittest suite; a directory holding *.test.mjs is a
node suite, run as `node --test "<dir>/*.test.mjs"` (newer Node releases do not recurse a directory argument). Any path segment
named `templates` is skipped: those tests only run after scaffolding, and the scaffold suites run the generated ones.
Results come from structured output (unittest result objects, node's junit reporter), never from parsing English text.

--prepare (automatic under --require-all) runs `npm install --ignore-scripts --no-audit --no-fund` in every directory
with a package.json that a node suite imports from (relative imports in its test files) when node_modules is missing;
node_modules is gitignored and never committed. WB_NPM overrides the npm command (a path or a JSON list).
The find suite and every office-* suite run under WB_KNOWLEDGE_PYTHON when it is set; --require-all without it is an
error (exit 2) naming the suites that need it.

--require-all sets WB_REQUIRE_ALL=1 for the suites and fails on any skip whose id is not allowed. skips.allow format,
one entry per line:  <module>::<Class.test>  # <reason>   (* and ? match; the reason is required). An entry that matches
no test in the suites that ran is reported as stale and fails the run. The 0.2.0 archive for the upgrade test is made
here (git archive of V020_REF into the scratch dir, env WB_V020_ARCHIVE) so that test never skips. WB_KNOWLEDGE_PYTHON,
when set, is the interpreter for the suite that holds test_find.py.
"""
import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
V020_REF = "c0ef8c4"
MEMCAP = HERE / "memcap" / "memcap.py"


# ---- discovery --------------------------------------------------------------------------------------------------
def listed(root):
    """File paths relative to the root: git ls-files in a checkout, else a walk (an unpacked release has no .git)."""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout
        return out.decode("utf-8").split("\0")
    except (OSError, subprocess.CalledProcessError):
        rels = []
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x not in ("node_modules", "__pycache__", ".venv", ".git")]
            rels += [Path(d, f).relative_to(root).as_posix() for f in files]
        return rels


def discover(root, only=()):
    """[(kind, dir)] from the listed files, sorted; kind is unittest or node."""
    found = set()
    for rel in listed(root):
        p = Path(rel)
        if "templates" in p.parts[:-1]:
            continue
        if p.name.startswith("test_") and p.suffix == ".py":
            found.add(("unittest", p.parent.as_posix()))
        elif p.name.endswith(".test.mjs"):
            found.add(("node", p.parent.as_posix()))
    return sorted(s for s in found if not only or any(o in s[1] for o in only))


# ---- skips.allow ------------------------------------------------------------------------------------------------
def load_allow(path):
    """([(module pattern, id pattern, reason)], [problems])"""
    entries, problems = [], []
    if not Path(path).is_file():
        return entries, [f"{path}: no such file"]
    for n, line in enumerate(Path(path).read_text("utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        body, _, reason = s.partition("#")
        mod, sep, tid = body.strip().partition("::")
        if not (sep and mod.strip() and tid.strip() and reason.strip()):
            problems.append(f"{path}:{n}: malformed (want '<module>::<Class.test>  # <reason>'): {s[:80]}")
        else:
            entries.append((mod.strip(), tid.strip(), reason.strip()))
    return entries, problems


def allowed(entries, module, tid):
    return any(fnmatch.fnmatchcase(module, m) and fnmatch.fnmatchcase(tid, t) for m, t, _ in entries)


def stale(entries, ids, partial):
    """Entries that match no test that exists. A partial run only judges entries whose module was in the run."""
    ran_modules = {m for m, _ in ids}
    out = []
    for m, t, _ in entries:
        if not any(fnmatch.fnmatchcase(a, m) and fnmatch.fnmatchcase(b, t) for a, b in ids):
            if not partial or any(fnmatch.fnmatchcase(a, m) for a in ran_modules):
                out.append(f"{m}::{t}")
    return out


# ---- one suite --------------------------------------------------------------------------------------------------
class Collect(unittest.TextTestResult):
    def startTest(self, test):
        super().startTest(test)
        self.seen = getattr(self, "seen", [])
        self.seen.append(test.id())

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.reasons = getattr(self, "reasons", {})
        self.reasons[test.id()] = reason


def child_unittest(directory, out):
    """Runs in the child: the discover run for one directory, results written as JSON to `out`."""
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]     # tools/ must not shadow a suite's modules
    suite = unittest.TestLoader().discover(directory, pattern="test_*.py")
    r = unittest.TextTestRunner(stream=sys.stderr, resultclass=Collect, verbosity=1).run(suite)
    split = lambda i: i.split(".", 1) if "." in i else [i, i]               # noqa: E731
    seen = list(dict.fromkeys(getattr(r, "seen", []) + [t.id() for t, _ in r.skipped]))
    Path(out).write_text(json.dumps({
        "ids": [split(i) for i in seen],
        "skipped": [[*split(t.id()), reason] for t, reason in r.skipped],
        "failed": len(r.failures) + len(r.errors) + len(r.unexpectedSuccesses),
        "failures": [t.id() for t, _ in r.failures + r.errors] + [t.id() for t in r.unexpectedSuccesses]}),
        encoding="utf-8")
    return 0 if r.wasSuccessful() else 1


def parse_junit(xml_path):
    ids, skipped, failed = [], [], 0

    def walk(el, names):
        nonlocal failed
        for c in el:
            if c.tag == "testsuite":
                walk(c, names + [c.get("name", "")])
            elif c.tag == "testcase":
                mod = os.path.basename((c.get("file") or "node").replace("\\", "/")).removesuffix(".test.mjs")
                tid = " > ".join(names + [c.get("name", "")])
                ids.append([mod, tid])
                if c.find("skipped") is not None:
                    skipped.append([mod, tid, c.find("skipped").get("message") or ""])
                if c.find("failure") is not None or c.find("error") is not None:
                    failed += 1
    walk(ET.parse(xml_path).getroot(), [])
    return {"ids": ids, "skipped": skipped, "failed": failed}


def run_suite(kind, directory, a, env, py):
    tmp = Path(tempfile.mkdtemp(prefix="wb-suite-"))
    res = tmp / "result"
    if kind == "unittest":
        cmd = [py, str(Path(__file__).resolve()), "--child-unittest", str(Path(a.root) / directory),
               "--child-out", str(res)]
    else:
        cmd = ["node", "--test", "--test-reporter=junit", f"--test-reporter-destination={res}",
               f"{directory}/*.test.mjs"]
    if not a.no_cap and MEMCAP.is_file():
        cmd = [sys.executable, str(MEMCAP), "--mb", str(a.mb * (2 if kind == "node" else 1)), "--"] + cmd
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                           cwd=a.root, timeout=a.timeout)
        rc, tail = p.returncode, (p.stdout + p.stderr).strip().splitlines()[-25:]
    except subprocess.TimeoutExpired:
        rc, tail = -1, [f"timeout after {a.timeout}s"]
    try:
        data = json.loads(res.read_text("utf-8")) if kind == "unittest" else parse_junit(res)
    except (OSError, ValueError, ET.ParseError):
        data = {"ids": [], "skipped": [], "failed": 1}
        tail.append("no structured result was written")
    total = len(data["ids"])
    r = {"kind": kind, "dir": directory, "rc": rc, "secs": time.time() - t0, "ids": data["ids"],
         "skipped": data["skipped"], "failed": data["failed"], "ran": total - len(data["skipped"]), "tail": tail}
    if rc != 0 or total == 0:
        r["failed"] = max(r["failed"], 1)
        if total == 0:
            r["tail"] = tail + ["no tests were found in this suite"]
    shutil.rmtree(tmp, ignore_errors=True)
    return r


def needs_knowledge_python(root, directory):
    """The find suite and every office-* suite need the knowledge venv's packages."""
    return (Path(root) / directory / "test_find.py").is_file() or any(fnmatch.fnmatch(x, "office-*") for x in Path(directory).parts)


def suite_python(root, directory):
    """WB_KNOWLEDGE_PYTHON for a suite that needs it, when set; otherwise this interpreter."""
    return (os.environ.get("WB_KNOWLEDGE_PYTHON") if needs_knowledge_python(root, directory) else None) or sys.executable


IMPORT_RE = re.compile(r"""(?:from|import)\s*\(?\s*['"](\.{1,2}/[^'"]+)['"]""")


def npm_dirs(root, node_dir):
    """Directories holding a package.json that the node suite's test files import from (relative imports only)."""
    root, found = Path(root).resolve(), {}
    for t in sorted((root / node_dir).glob("*.test.mjs")):
        for spec in IMPORT_RE.findall(t.read_text("utf-8", errors="replace")):
            p = (t.parent / spec).resolve()
            p = p if p.is_dir() else p.parent
            while True:
                if (p / "package.json").is_file():
                    found[p] = 1
                    break
                if p == root or root not in p.parents:
                    break
                p = p.parent
    return list(found)


def npm_command():
    b = os.environ.get("WB_NPM")
    if b:
        return json.loads(b) if b.lstrip().startswith("[") else [b]
    return [shutil.which("npm") or "npm"]


def prepare(root, suites):
    """npm install where a node suite imports from a package whose node_modules is missing. Returns problems."""
    problems = []
    for d in sorted({d for kind, s in suites if kind == "node" for d in npm_dirs(root, s)}):
        if (d / "node_modules").is_dir():
            continue
        print(f"prepare: npm install in {d.relative_to(Path(root).resolve()).as_posix()}", flush=True)
        try:
            r = subprocess.run(npm_command() + ["install", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=d,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
            if r.returncode:
                problems.append(f"prepare failed in {d}: exit {r.returncode}: {(r.stderr or r.stdout).strip()[-200:]}")
        except (OSError, subprocess.TimeoutExpired) as e:
            problems.append(f"prepare failed in {d}: {e}")
    return problems


def make_archive(root, ref, dest):
    """git archive of `ref` as a tar at dest; the path, or None with the reason printed."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(["git", "-C", str(root), "archive", "--format=tar", "-o", str(dest), ref], capture_output=True,
                       text=True)
    if p.returncode:
        print(f"note: no 0.2.0 archive ({ref}): {p.stderr.strip()[:120]}; the upgrade test will fail, not skip")
        return None
    return dest


# ---- main -------------------------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--require-all", action="store_true")
    ap.add_argument("--prepare", action="store_true", help="npm install for node suites first (implied by --require-all)")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--root", default=str(HERE.parent))
    ap.add_argument("--skips")
    ap.add_argument("--mb", type=int, default=1024)
    ap.add_argument("--no-cap", action="store_true")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--scratch", default=str(Path(tempfile.gettempdir()) / "wb-run-suites"))
    ap.add_argument("--v020-ref", default=V020_REF)
    ap.add_argument("--child-unittest")
    ap.add_argument("--child-out")
    a = ap.parse_args(argv)
    if a.child_unittest:
        return child_unittest(a.child_unittest, a.child_out)
    a.root = str(Path(a.root).resolve())
    suites = discover(a.root, a.only)
    entries, problems = load_allow(a.skips or Path(a.root) / "tools" / "skips.allow")
    if a.list:
        for kind, d in suites:
            print(f"{kind:9} {d}")
        print(f"{len(suites)} suites; skips.allow: {len(entries)} entries, {len(problems)} problems")
        for p in problems:
            print("PROBLEM", p)
        return 1 if problems else 0
    needy = [d for _, d in suites if needs_knowledge_python(a.root, d)]
    kp = os.environ.get("WB_KNOWLEDGE_PYTHON")
    if a.require_all and needy and not (kp and (Path(kp).is_file() or shutil.which(kp))):
        print("ERROR: WB_KNOWLEDGE_PYTHON must name the knowledge venv's python (" + ("not found: " + kp if kp else "not set")
              + ") for --require-all; these suites need its packages:\n  " + "\n  ".join(needy))
        return 2
    env = dict(os.environ)
    if a.require_all:
        env["WB_REQUIRE_ALL"] = "1"
    problems += prepare(a.root, suites) if (a.prepare or a.require_all) else []
    if not (env.get("WB_V020_ARCHIVE") and Path(env["WB_V020_ARCHIVE"]).is_file()):
        arc = make_archive(a.root, a.v020_ref, Path(a.scratch) / "v020.tar")
        if arc:
            env["WB_V020_ARCHIVE"] = str(arc)
    results, ids, unlisted, bad_suites = [], [], [], 0
    for i, (kind, d) in enumerate(suites, 1):
        r = run_suite(kind, d, a, env, suite_python(a.root, d))
        results.append(r)
        ids += [tuple(x) for x in r["ids"]]
        for m, t, why in r["skipped"]:
            if not allowed(entries, m, t):
                unlisted.append((d, m, t, why))
        bad_suites += r["failed"] > 0
        print(f"[{i}/{len(suites)}] {'FAIL' if r['failed'] else 'ok  '} {d} ({kind}) ran {r['ran']} failed "
              f"{r['failed']} skipped {len(r['skipped'])} in {r['secs']:.0f}s", flush=True)
        if r["failed"]:
            print("\n".join("    | " + x for x in r["tail"]), flush=True)
    stale_entries = stale(entries, ids, bool(a.only))
    print("\nsuite".ljust(60) + "ran  failed  skipped")
    for r in results:
        print(f"{r['dir']:58}{r['ran']:5}{r['failed']:7}{len(r['skipped']):9}")
    for d, m, t, why in unlisted:
        print(f"SKIP {'NOT ALLOWED' if a.require_all else 'unlisted'}: {m}::{t} ({why[:60]}) in {d}")
    for s in stale_entries:
        print(f"STALE skips.allow entry matches no test: {s}")
    for p in problems:
        print("PROBLEM", p)
    fail = bad_suites or stale_entries or problems or (a.require_all and unlisted)
    print(f"RESULT: {'FAIL' if fail else 'PASS'}  suites {len(results)}  failed suites {bad_suites}  "
          f"skips {sum(len(r['skipped']) for r in results)} (unlisted {len(unlisted)})  stale {len(stale_entries)}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
