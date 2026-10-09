#!/usr/bin/env python3
"""review_plugin.py: deterministic first pass over a plugin or skill someone else built.

  review_plugin.py PATH [--target cli|web|all] [--denylist FILE] [--validate] [--json]
  review_plugin.py --batch DIR_OR_LISTFILE --scorecard OUTDIR [--target ...] [--denylist FILE]
  review_plugin.py ARCHIVE --unpack EMPTY_DIR     checked unpack only (for the model pass); prints the folder to review

PATH is a folder, a .zip, a .skill or a .plugin. Archives are unpacked by this script (never by a tool that follows
links) into a fresh temporary folder after zip-slip, zip-bomb, link and reserved-name checks; an archive that fails
is refused with a rule id and nothing is written. Nothing from the input is run, imported or installed. --batch
reviews each plugin in a child Python started with -I and a timeout, then writes scorecard.csv and scorecard.md.
Exit: 0 no block or hold finding, 1 block, hold or refused, 2 usage. --validate also runs `claude plugin validate`.
Stdlib only. The rules live in plugin_rules.py; --json output follows the plugin-rules interface.
"""
import argparse
import csv
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # -I drops the script's own folder from sys.path
import plugin_rules as R  # noqa: E402

MAX_TOTAL = 200 << 20       # bytes after unpacking
MAX_FILE = 50 << 20
MAX_ENTRIES = 5000
MAX_RATIO = 100             # uncompressed / compressed for a file over 1 MiB
DEVICE = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.I)
ARCHIVES = (".zip", ".skill", ".plugin")


def refusal(rule, name, msg):
    return {"rule": rule, "group": 1, "file": name, "line": 0, "severity": "block", "msg": msg}


def check_archive(z, max_total=MAX_TOTAL):
    bad, total = [], 0
    infos = z.infolist()
    if len(infos) > MAX_ENTRIES:
        bad.append(refusal("X02-zip-bomb", "", f"{len(infos)} entries"))
    for i in infos:
        name = i.filename
        norm = name.replace("\\", "/")
        parts = norm.split("/")
        if norm.startswith("/") or ".." in parts or ":" in norm or "\0" in name:
            bad.append(refusal("X01-zip-slip", name, "entry path leaves the target folder"))
        elif any(DEVICE.match(s) for s in parts):
            bad.append(refusal("X04-reserved-device-name", name, "entry names a Windows device"))
        if (i.external_attr >> 16) & 0o170000 == 0o120000:
            bad.append(refusal("X03-zip-symlink", name, "symlink entry"))
        total += i.file_size
        if i.file_size > MAX_FILE or (i.file_size > (1 << 20) and i.compress_size and i.file_size / i.compress_size > MAX_RATIO):
            bad.append(refusal("X02-zip-bomb", name, f"{i.file_size} bytes from {i.compress_size}"))
    if total > max_total:
        bad.append(refusal("X02-zip-bomb", "", f"{total} bytes in total"))
    return bad


def unpack(src, dest, max_total=MAX_TOTAL):
    """Extract src into the empty folder dest. -> [] on success, else refusal findings (dest may hold partial output)."""
    dest = Path(dest).resolve()
    with zipfile.ZipFile(src) as z:
        bad = check_archive(z, max_total)
        if bad:
            return bad
        total = 0
        for i in z.infolist():
            target = (dest / i.filename.replace("\\", "/")).resolve()
            if dest != target and dest not in target.parents:
                return [refusal("X01-zip-slip", i.filename, "entry path leaves the target folder")]
            if i.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            n = 0
            with z.open(i) as r, open(target, "wb") as w:
                while True:
                    chunk = r.read(1 << 16)           # count real bytes: headers can lie
                    if not chunk:
                        break
                    n += len(chunk)
                    total += len(chunk)
                    if n > MAX_FILE or total > max_total:
                        return [refusal("X02-zip-bomb", i.filename, "more data than the archive header declares")]
                    w.write(chunk)
    return []


def rmtree(path):
    def fix(func, p, _):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=fix)


def descend(root):
    """A zip that wraps everything in one folder: review the folder."""
    kids = list(Path(root).iterdir())
    if len(kids) == 1 and kids[0].is_dir() and not kids[0].name.startswith("."):
        return kids[0]
    return Path(root)


def review(path, target="all", denylist=None, validate=False):
    """-> report dict (interface: path, kind, verdict, surfaces, stats, rules_sha256, findings)."""
    path = Path(path)
    rep = {"path": str(path), "target": target, "rules_sha256": R.rules_sha256()}
    scratch = None
    try:
        if path.is_dir():
            root = path
        elif path.is_file() and zipfile.is_zipfile(path):
            scratch = Path(tempfile.mkdtemp(prefix="wb-review-"))
            bad = unpack(path, scratch)
            if bad:
                return dict(rep, kind="archive", refused=True, verdict="refused", surfaces={s: False for s in R.SURFACES},
                            stats={}, findings=bad)
            root = descend(scratch)
        else:
            raise FileNotFoundError(f"{path}: not a folder, .zip, .skill or .plugin")
        terms = R.load_denylist(denylist) if denylist else None
        plugin = R.Plugin(root, denylist=terms, validate=validate)
        allf = R.run_rules(plugin)
        where = {r[0]: r[3] for r in R.RULES}
        findings = [f for f in allf if target == "all" or target in where[f["rule"]]]
        sev = {f["severity"] for f in findings}
        rep.update(kind=plugin.kind, refused=False, surfaces=R.surfaces_of(allf),
                   verdict="do-not-ship" if "block" in sev else "fix-then-ship" if "hold" in sev else "ship",
                   stats={"files": len(plugin.files), "bytes": sum(plugin.size(f) for f in plugin.files),
                          "skills": len(plugin.skills()), "hooks": len(plugin.hooks()), "mcp_servers": len(plugin.servers())},
                   findings=findings)
        return rep
    finally:
        if scratch:
            rmtree(scratch)


def top3(findings):
    return "; ".join(f"{f['rule']} {f['file']}:{f['line']}" for f in findings[:3])


def batch(src, out, target="all", denylist=None, validate=False):
    src = Path(src)
    if src.is_dir():
        items = sorted(p for p in src.iterdir() if p.is_dir() or p.suffix.lower() in ARCHIVES)
    else:
        items = [Path(ln.strip()) for ln in src.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    rows = []
    for it in items:
        cmd = [sys.executable, "-I", str(Path(__file__).resolve()), str(it), "--json", "--target", target]
        cmd += (["--denylist", str(denylist)] if denylist else []) + (["--validate"] if validate else [])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
            rep = json.loads(r.stdout)
        except (subprocess.TimeoutExpired, ValueError, OSError) as e:
            rep = {"verdict": "error", "findings": [{"rule": "X00-review-failed", "file": "", "line": 0, "severity": "block", "msg": str(e)[:120]}]}
        c = {s: sum(1 for f in rep["findings"] if f["severity"] == s) for s in ("block", "hold", "warn", "note")}
        rows.append([it.name, rep["verdict"], c["block"], c["hold"], c["warn"], c["note"], top3(rep["findings"])])
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    head = ["plugin", "verdict", "block", "hold", "warn", "note", "top_findings"]
    with open(out / "scorecard.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(head)
        w.writerows(rows)
    with open(out / "scorecard.md", "w", newline="\n", encoding="utf-8") as f:
        f.write("| " + " | ".join(head) + " |\n|" + "---|" * len(head) + "\n")
        for r in rows:
            f.write("| " + " | ".join(str(x).replace("|", "/") for x in r) + " |\n")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?")
    ap.add_argument("--target", choices=["cli", "web", "all"], default="all")
    ap.add_argument("--denylist")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--unpack")
    ap.add_argument("--batch")
    ap.add_argument("--scorecard")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if a.batch:
        if not a.scorecard:
            ap.error("--batch needs --scorecard OUTDIR")
        rows = batch(a.batch, a.scorecard, a.target, a.denylist, a.validate)
        print(f"{len(rows)} reviewed; scorecard.csv and scorecard.md written to {a.scorecard}")
        return 0
    if not a.path:
        ap.error("give a PATH or --batch")
    if a.unpack:
        dest = Path(a.unpack)
        if not zipfile.is_zipfile(a.path) or (dest.exists() and any(dest.iterdir())):
            print("review_plugin: --unpack needs an archive and an empty or new folder", file=sys.stderr)
            return 2
        dest.mkdir(parents=True, exist_ok=True)
        bad = unpack(a.path, dest)
        if bad:
            rmtree(dest)
            print("refused: " + ", ".join(sorted({f["rule"] for f in bad})), file=sys.stderr)
            return 1
        print(descend(dest))
        return 0
    try:
        rep = review(a.path, a.target, a.denylist, a.validate)
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        print(f"review_plugin: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(rep, indent=1))
    else:
        print(f"{rep['verdict']}: {rep['path']} ({rep.get('kind')}, target {a.target})")
        for f in rep["findings"]:
            if f["severity"] in ("block", "hold"):
                print(f"  {f['severity'].upper():5} {f['rule']} {f['file']}:{f['line']} {f['msg']}")
        n = sum(1 for f in rep["findings"] if f["severity"] in ("warn", "note"))
        print(f"  {n} warn/note finding(s); use --json for all")
    return 0 if rep["verdict"] == "ship" else 1


if __name__ == "__main__":
    sys.exit(main())
