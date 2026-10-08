#!/usr/bin/env python3
"""fetch_upstream.py: opt-in download of pinned third-party skills into your skills folder.

  python fetch_upstream.py                         dry run: show what would be fetched, write nothing
  python fetch_upstream.py --apply                 download, verify every SHA-256, then install
  python fetch_upstream.py --apply --only humanizer,impeccable
  python fetch_upstream.py --apply --force         replace existing folders (old ones are moved to a backup dir)
  python fetch_upstream.py --optional [--apply]    also the optional design set (gstack design-review/qa/diagram,
                                                   impeccable, web-design-guidelines): NOT recommended on a managed
                                                   laptop, read THIRD-PARTY.md first

Reads upstream.lock.json next to this file: every file has a fixed URL (a commit or a published
package version) and a SHA-256. A source is installed only if ALL its files verify; nothing is
written for a source with any mismatch. Each installed folder gets an UPSTREAM.txt naming the
source, version and licence, next to the upstream LICENSE file.

Skills folder: --skills-dir, else $CLAUDE_CONFIG_DIR/skills, else ~/.claude/skills. Uses the system
proxy settings (HTTPS_PROXY); behind a TLS-inspecting proxy set SSL_CERT_FILE to your organisation's
CA bundle. Never run this from a hook. Stdlib only.
"""
import argparse, datetime, hashlib, json, os, shutil, sys, tempfile, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PERMISSIVE = ("MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD")


def config_dir():
    return os.path.abspath(os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"))


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "claude-workbench-fetch-upstream"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def safe_dest(root, rel):
    p = os.path.normpath(os.path.join(root, rel))
    if os.path.commonpath([os.path.abspath(root), os.path.abspath(p)]) != os.path.abspath(root):
        raise ValueError(f"lock entry escapes the skills folder: {rel}")
    return p


def fetch(lock, skills_dir, apply=False, only=None, force=False, backup_root=None, get=download, log=print):
    sources = [s for s in lock["sources"] if not only or s["id"] in only]
    unknown = set(only or ()) - {s["id"] for s in lock["sources"]}
    if unknown:
        raise SystemExit(f"unknown source(s): {', '.join(sorted(unknown))}")
    backup_root = backup_root or os.path.join(config_dir(), "workbench-backups", "skills")
    results = {}
    for s in sources:
        if not s["license"].startswith(PERMISSIVE):
            results[s["id"]] = "refused: licence not on the permissive list"
            log(f"REFUSE  {s['id']}: licence '{s['license']}'")
            continue
        try:
            for _, d, _ in s["files"]:
                safe_dest(skills_dir, d)
        except ValueError as e:
            results[s["id"]] = f"failed: {e}"
            log(f"REFUSE  {s['id']}: {e}")
            continue
        tops = sorted({d.split("/")[0] for _, d, _ in s["files"]})
        existing = [t for t in tops if os.path.exists(os.path.join(skills_dir, t))]
        log(f"{'FETCH' if apply else 'PLAN '}   {s['id']} {s['ref']} ({s['license']}): {len(s['files'])} files -> {', '.join(tops)}"
            + (f"  [exists: {', '.join(existing)}]" if existing else ""))
        if not apply:
            results[s["id"]] = "planned"
            continue
        if existing and not force:
            results[s["id"]] = "skipped: already installed (use --force to replace)"
            log(f"  skip: {', '.join(existing)} already present")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            try:
                for src, dest, want in s["files"]:
                    data = get(s["base"] + src)
                    got = hashlib.sha256(data).hexdigest()
                    if got != want:
                        raise ValueError(f"SHA-256 mismatch for {src}: expected {want[:12]}..., got {got[:12]}...")
                    p = safe_dest(tmp, dest)
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    with open(p, "wb") as f:
                        f.write(data)
            except Exception as e:
                results[s["id"]] = f"failed: {e}"
                log(f"  FAILED, nothing written: {e}")
                continue
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            for t in tops:
                target = safe_dest(skills_dir, t)
                if os.path.exists(target):
                    os.makedirs(backup_root, exist_ok=True)
                    shutil.move(target, os.path.join(backup_root, f"{t}-{stamp}"))
                with open(os.path.join(tmp, t, "UPSTREAM.txt"), "w", encoding="utf-8") as f:
                    f.write(f"Fetched by claude-workbench tools/fetch-upstream on {stamp}\nsource: {s['upstream']}\n"
                            f"version: {s['ref']}{' (commit ' + s['commit'] + ')' if s.get('commit') else ''}\n"
                            f"licence: {s['license']}\nnote: {s['note']}\n")
                os.makedirs(skills_dir, exist_ok=True)
                shutil.copytree(os.path.join(tmp, t), target)
        results[s["id"]] = "installed"
        log(f"  installed into {skills_dir}")
    if not apply:
        log("Dry run: nothing written. Re-run with --apply after reading the licences and notes in upstream.lock.json.")
    return results


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", help="comma-separated source ids")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--skills-dir", default=os.path.join(config_dir(), "skills"))
    ap.add_argument("--lock", default=os.path.join(HERE, "upstream.lock.json"))
    ap.add_argument("--optional", action="store_true",
                    help="add upstream.optional.lock.json (runtime downloads and local usage logs; see THIRD-PARTY.md)")
    a = ap.parse_args(argv)
    with open(a.lock, encoding="utf-8") as f:
        lock = json.load(f)
    if a.optional:
        with open(os.path.join(HERE, "upstream.optional.lock.json"), encoding="utf-8") as f:
            opt = json.load(f)
        print("OPTIONAL SET: " + opt.get("_readme", ""))
        lock = dict(lock, sources=lock["sources"] + [s for s in opt["sources"]
                                                    if s["id"] not in {x["id"] for x in lock["sources"]}])
    res = fetch(lock, a.skills_dir, a.apply, set(a.only.split(",")) if a.only else None, a.force)
    return 1 if any(v.startswith(("failed", "refused")) for v in res.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
