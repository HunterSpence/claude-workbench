#!/usr/bin/env python3
"""package_web.py: can this skill or plugin folder be uploaded to claude.ai, and if so, zip it.

  package_web.py PATH --check [--json]       PATH: a skill folder (SKILL.md at its root) or a plugin folder
  package_web.py PATH --out ZIP [--strip]    write the upload zip; refuses while the check fails
  --strip                                    first remove non-portable frontmatter keys (and fold when_to_use into
                                             the description); every change is listed in PACKAGING.md in the zip

--check --json prints {"path","surface":"web","portable","rules_sha256","findings":[...]}; exit 0 portable, 1 not
portable, 2 usage. Portable = no block or hold finding from the rules that apply to claude.ai. The zip is built from
the folder itself: forward-slash names, LF line endings, sorted entries, fixed timestamps (so two runs are identical),
no caches or OS junk. A skill folder is zipped under a folder named after the skill; a plugin folder at the zip root.
This script never uploads anything. Stdlib only; the rules come from the plugin-review skill.
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin-review" / "scripts"))   # also under python -I
import plugin_rules as R  # noqa: E402

JUNK_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git", "__MACOSX"}
JUNK_FILES = {".ds_store", "thumbs.db", "desktop.ini", "ehthumbs.db"}


def junk(rel):
    parts = rel.split("/")
    return bool(set(parts[:-1]) & JUNK_DIRS) or parts[-1].lower() in JUNK_FILES or parts[-1].endswith(".pyc") or parts[-1].startswith("._")


def check(path):
    p = R.Plugin(path)
    findings = R.run_rules(p, target="web")
    portable = not any(f["severity"] in ("block", "hold") for f in findings)
    return p, {"path": str(path), "surface": "web", "portable": portable, "rules_sha256": R.rules_sha256(), "findings": findings}


def strip_frontmatter(text):
    """-> (new text, [change descriptions]). Keeps the six portable keys; folds when_to_use into description."""
    lines = text.replace("\r\n", "\n").split("\n")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None) if lines and lines[0].strip() == "---" else None
    if end is None:
        return text, []
    fm = R.frontmatter(text)[0]
    fold = fm.get("when_to_use", [""])[0]
    desc = (fm.get("description", [""])[0] + " " + fold).strip()[:1024] if fold else None
    out, changes, drop = [lines[0]], [], False
    for ln in lines[1:end]:
        m = re.match(r"^([A-Za-z0-9_][\w-]*)\s*:", ln)
        if m:
            k = m.group(1)
            drop = k not in R.PORTABLE_KEYS or (desc is not None and k == "description")
            if k not in R.PORTABLE_KEYS:
                changes.append(f"removed frontmatter key '{k}'")
            if desc is not None and k == "description":
                out.append("description: " + json.dumps(desc, ensure_ascii=False))
        if not drop:
            out.append(ln)
    if fold:
        changes.append("folded when_to_use into description (at most 1024 characters)")
    return "\n".join(out + lines[end:]), changes


def build(src, out, strip=False):
    """Zip src to out. -> (check report, entry names). Raises ValueError when the folder is not portable."""
    src = Path(src)
    work = None
    try:
        if strip:
            work = Path(tempfile.mkdtemp(prefix="wb-pack-"))
            shutil.copytree(src, work / "p", ignore=lambda d, names: [n for n in names if n in JUNK_DIRS or n.lower() in JUNK_FILES or n.endswith(".pyc")], symlinks=True)
            root, notes = work / "p", []
            for sk in sorted(root.rglob("SKILL.md")):
                new, ch = strip_frontmatter(sk.read_text(encoding="utf-8"))
                if ch:
                    sk.write_bytes(new.encode("utf-8"))
                    notes += [f"- `{sk.relative_to(root).as_posix()}`: {c}" for c in ch]
            for sk in sorted(root.rglob("*")):
                if sk.suffix == ".md" and sk.is_file() and "${CLAUDE_SKILL_DIR}" in sk.read_text(encoding="utf-8", errors="ignore"):
                    notes.append(f"- `{sk.relative_to(root).as_posix()}`: refers to scripts through ${{CLAUDE_SKILL_DIR}}; scripts need code execution and get no network access on default organisation settings")
            (root / "PACKAGING.md").write_bytes(("# Packaging notes\n\nChanges made to the source folder before zipping:\n\n" + ("\n".join(notes) or "- none") + "\n").encode("utf-8"))
            src = root
        p, rep = check(src)
        if not rep["portable"]:
            raise ValueError(json.dumps(rep["findings"]))
        skill_root = "SKILL.md" in p.fileset and p.kind != "plugin"
        prefix = ""
        if skill_root:
            fm = R.frontmatter(p.text("SKILL.md"))
            prefix = (fm[0]["name"][0] if fm and "name" in fm[0] else src.name) + "/"
        names = []
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for rel in sorted(f for f in p.files if not junk(f)):
                data = (src / rel).read_bytes()
                if p.is_text(rel):
                    data = data.replace(b"\r\n", b"\n")
                zi = zipfile.ZipInfo(prefix + rel, (1980, 1, 1, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = 0o644 << 16
                z.writestr(zi, data)
                names.append((prefix + rel, len(data)))
        return rep, names
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--strip", action="store_true")
    a = ap.parse_args(argv)
    if not Path(a.path).is_dir() or not (a.check or a.out):
        print("package_web: give a folder and --check or --out ZIP", file=sys.stderr)
        return 2
    if a.out:
        try:
            rep, names = build(a.path, a.out, a.strip)
        except ValueError as e:
            print("not portable to claude.ai; nothing written" + ("" if a.strip else " (--strip can rewrite frontmatter)"), file=sys.stderr)
            for f in json.loads(str(e)):
                if f["severity"] in ("block", "hold"):
                    print(f"  {f['severity']:5} {f['rule']} {f['file']}:{f['line']} {f['msg']}", file=sys.stderr)
            return 1
        print(f"wrote {a.out}")
        for n, size in names:
            print(f"  {size:>8}  {n}")
        print("Upload in claude.ai: Customize > Skills for a skill, Customize > Plugins > Add > Upload plugin for a plugin.")
        return 0
    _, rep = check(a.path)
    if a.json:
        print(json.dumps(rep, indent=1))
    else:
        print("portable to claude.ai" if rep["portable"] else "NOT portable to claude.ai")
        for f in rep["findings"]:
            print(f"  {f['severity']:5} {f['rule']} {f['file']}:{f['line']} {f['msg']}")
    return 0 if rep["portable"] else 1


if __name__ == "__main__":
    sys.exit(main())
