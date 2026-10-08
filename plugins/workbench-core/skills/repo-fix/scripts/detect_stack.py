#!/usr/bin/env python3
"""detect_stack.py: read a repository's manifests and CI files and print the commands it uses to
install, build, test, lint and type-check. Reads files only; runs nothing.

  python detect_stack.py [REPO_DIR] [--json]

Sources, most authoritative first: CI workflow steps (what the project really runs), then
package.json scripts, pyproject/tox/nox, Makefile targets, go.mod, Cargo.toml, Maven/Gradle,
.NET, Ruby, PHP, pre-commit. Project folders are found up to 3 levels down (monorepos), skipping
dependency and build output. Release, deploy and publish workflows are listed as skipped, not read.
Also reports the PR template, CODEOWNERS and CONTRIBUTING files. Standard library only.
"""
import glob, json, os, re, sys

try:
    import tomllib
except ImportError:          # Python 3.10
    tomllib = None

ROLES = ("install", "build", "test", "lint", "fix", "typecheck", "format")
MAX_DEPTH = 3
SKIP_DIRS = {"node_modules", ".venv", "venv", "vendor", "dist", "build", ".git", "__pycache__", "target",
             ".tox", ".nox", "out", "coverage", ".next", ".turbo", "bower_components", "site-packages"}
MANIFESTS = ("package.json", "pyproject.toml", "setup.py", "setup.cfg", "Makefile", "makefile", "go.mod",
             "Cargo.toml", "pom.xml", "Gemfile", "composer.json")
MANIFEST_GLOBS = ("requirements*.txt", "build.gradle*", "*.sln", "*.csproj")


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _toml(path):
    text = _read(path)
    if tomllib:
        try:
            return tomllib.loads(text)
        except Exception:
            return {}
    # 3.10 fallback: only the table names matter here
    return {"_tables": re.findall(r"^\s*\[+([^\]]+)\]+", text, re.M)}


def _has_table(data, dotted):
    if "_tables" in data:
        return any(t.strip() == dotted or t.strip().startswith(dotted + ".") for t in data["_tables"])
    cur = data
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return False
        cur = cur[k]
    return True


LOCKS = (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun"), ("bun.lock", "bun"),
         ("package-lock.json", "npm"))


def _json(path):
    try:
        data = json.loads(_read(path) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _pkg_manager(root, top):
    """(manager, folder that decided it, lockfile name or None). The folder's own lockfile, else its `packageManager`
    field, else the same up the tree to the repo root: a workspace member shares the root's lockfile. npm if none."""
    cur, top = os.path.abspath(root), os.path.abspath(top or root)
    while True:
        for f, pm in LOCKS:
            if os.path.exists(os.path.join(cur, f)):
                return pm, cur, f
        field = _json(os.path.join(cur, "package.json")).get("packageManager")
        m = re.match(r"(npm|pnpm|yarn|bun)@", field) if isinstance(field, str) else None
        if m:
            return m.group(1), cur, None
        if cur == top or os.path.dirname(cur) == cur:
            return "npm", os.path.abspath(root), None
        cur = os.path.dirname(cur)


def node(root, out, top=None):
    pj = os.path.join(root, "package.json")
    if not os.path.exists(pj):
        return
    data = _json(pj)
    pm, where, lock = _pkg_manager(root, top)
    if where == os.path.abspath(root):              # a workspace member installs from the root that owns the lockfile
        install = {"npm": "npm ci" if lock == "package-lock.json" else "npm install",
                   "pnpm": "pnpm install --frozen-lockfile" if lock else "pnpm install",
                   "yarn": "yarn install --frozen-lockfile" if lock else "yarn install",
                   "bun": "bun install --frozen-lockfile" if lock else "bun install"}[pm]
        out.append(("node", "install", install + "   # runs package install scripts: --ignore-scripts for a first look"))
    run = "npm run" if pm == "npm" else pm
    scripts = data.get("scripts") or {}
    for name in scripts:
        low = name.lower()
        role = ("fix" if low == "fix" or low.endswith((":fix", "-fix", "_fix")) else
                "test" if low == "test" or low.startswith("test:") else
                "lint" if low.startswith("lint") else
                "typecheck" if low in ("typecheck", "type-check", "tsc", "check-types", "types") else
                "build" if low == "build" else
                "format" if low.startswith("format") or low in ("fmt", "prettier") else None)
        if role:
            out.append(("node", role, f"{run} {name}"))
    if "test" not in scripts and os.path.exists(os.path.join(root, "tsconfig.json")):
        out.append(("node", "typecheck", "npx tsc --noEmit"))


def python(root, out):
    pp = os.path.join(root, "pyproject.toml")
    data = _toml(pp) if os.path.exists(pp) else {}
    reqs = glob.glob(os.path.join(root, "requirements*.txt"))
    if not (data or reqs or os.path.exists(os.path.join(root, "setup.py")) or os.path.exists(os.path.join(root, "setup.cfg"))):
        # No manifest: stdlib unittest files a few levels down still mean there are tests to run.
        if _unittest_only(root):
            out.append(("python", "test", "python -m unittest discover -s <dir with the tests>"))
        return
    uv = os.path.exists(os.path.join(root, "uv.lock"))
    poetry = os.path.exists(os.path.join(root, "poetry.lock")) or _has_table(data, "tool.poetry")
    prefix = "uv run " if uv else "poetry run " if poetry else "python -m "
    out.append(("python", "install", "uv sync" if uv else "poetry install" if poetry else
                ("pip install -r " + os.path.basename(sorted(reqs)[0])) if reqs else "pip install -e ."))
    if os.path.exists(os.path.join(root, "tox.ini")):
        out.append(("python", "test", "tox"))
    if os.path.exists(os.path.join(root, "noxfile.py")):
        out.append(("python", "test", "nox"))
    pytest = (_has_table(data, "tool.pytest") or os.path.exists(os.path.join(root, "pytest.ini"))
              or "[tool:pytest]" in _read(os.path.join(root, "setup.cfg"))
              or os.path.isdir(os.path.join(root, "tests")) or os.path.isdir(os.path.join(root, "test")))
    if pytest:
        out.append(("python", "test", prefix + "pytest"))
    if _has_table(data, "tool.ruff") or os.path.exists(os.path.join(root, "ruff.toml")) or os.path.exists(os.path.join(root, ".ruff.toml")):
        out.append(("python", "lint", (prefix if prefix != "python -m " else "") + "ruff check ."))
        out.append(("python", "format", (prefix if prefix != "python -m " else "") + "ruff format --check ."))
    if _has_table(data, "tool.black"):
        out.append(("python", "format", prefix + "black --check ."))
    if _has_table(data, "tool.mypy") or os.path.exists(os.path.join(root, "mypy.ini")):
        out.append(("python", "typecheck", prefix + "mypy ."))
    if _has_table(data, "tool.pyright") or os.path.exists(os.path.join(root, "pyrightconfig.json")):
        out.append(("python", "typecheck", (prefix if prefix != "python -m " else "") + "pyright"))


def make(root, out):
    text = _read(os.path.join(root, "Makefile")) or _read(os.path.join(root, "makefile"))
    for target in re.findall(r"^([A-Za-z][\w.-]*)\s*:(?!=)", text, re.M):
        low = target.lower()
        role = ("test" if low in ("test", "tests", "check", "unit") else "lint" if low in ("lint", "vet") else
                "build" if low == "build" else "format" if low in ("fmt", "format") else
                "typecheck" if low in ("typecheck", "types") else None)
        if role:
            out.append(("make", role, f"make {target}"))


def others(root, out):
    j = lambda *p: os.path.join(root, *p)
    if os.path.exists(j("go.mod")):
        out += [("go", "build", "go build ./..."), ("go", "test", "go test ./..."), ("go", "lint", "go vet ./..."),
                ("go", "format", "gofmt -l .")]
        if glob.glob(j(".golangci.*")):
            out.append(("go", "lint", "golangci-lint run"))
    if os.path.exists(j("Cargo.toml")):
        out += [("rust", "build", "cargo build"), ("rust", "test", "cargo test"),
                ("rust", "lint", "cargo clippy --all-targets -- -D warnings"), ("rust", "format", "cargo fmt --check")]
    if os.path.exists(j("pom.xml")):
        mvn = "./mvnw" if os.path.exists(j("mvnw")) else "mvn"
        out += [("java", "test", f"{mvn} -B test"), ("java", "build", f"{mvn} -B -DskipTests package")]
    if glob.glob(j("build.gradle*")):
        g = "./gradlew" if os.path.exists(j("gradlew")) else "gradle"
        out += [("java", "test", f"{g} test"), ("java", "build", f"{g} build -x test")]
    if glob.glob(j("*.sln")) or glob.glob(j("*.csproj")) or glob.glob(j("src", "*", "*.csproj")):
        out += [("dotnet", "build", "dotnet build"), ("dotnet", "test", "dotnet test"),
                ("dotnet", "format", "dotnet format --verify-no-changes")]
    if os.path.exists(j("Gemfile")):
        out.append(("ruby", "install", "bundle install"))
        out.append(("ruby", "test", "bundle exec rspec" if os.path.isdir(j("spec")) else "bundle exec rake test"))
        if os.path.exists(j(".rubocop.yml")):
            out.append(("ruby", "lint", "bundle exec rubocop"))
    if os.path.exists(j("composer.json")):
        out.append(("php", "install", "composer install"))
        if os.path.exists(j("phpunit.xml")) or os.path.exists(j("phpunit.xml.dist")):
            out.append(("php", "test", "vendor/bin/phpunit"))
    if os.path.exists(j(".pre-commit-config.yaml")):
        out.append(("pre-commit", "lint", "pre-commit run --all-files"))


def _unittest_only(root):
    for d in range(4):
        for f in glob.glob(os.path.join(root, *["*"] * d, "test_*.py")):
            if not SKIP_DIRS.intersection(os.path.relpath(f, root).replace("\\", "/").split("/")[:-1]):
                return True
    return False


def project_dirs(root):
    """The repo root plus every folder up to MAX_DEPTH levels down that holds a manifest."""
    found = [root]
    for cur, dirs, files in os.walk(root):
        rel = os.path.relpath(cur, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")) if depth < MAX_DEPTH else []
        if depth and (any(f in files for f in MANIFESTS)
                      or any(glob.glob(os.path.join(cur, g)) for g in MANIFEST_GLOBS)):
            found.append(cur)
    return found


def _unquote(v):
    """One YAML scalar: strip quotes only when the whole value is one quoted string."""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return v


def _flow_list(v):
    """Items of a YAML flow list `[a, "b, c", 'd']`, splitting only on commas outside quotes."""
    items, cur, q = [], "", None
    for ch in v.strip()[1:-1] if v.strip().endswith("]") else v.strip()[1:]:
        if q:
            cur += ch
            q = None if ch == q else q
        elif ch in "'\"":
            cur, q = cur + ch, ch
        elif ch == ",":
            items.append(cur)
            cur = ""
        else:
            cur += ch
    items.append(cur)
    return [_unquote(i) for i in items if i.strip()]


def _strip_comment(v):
    """Drop a trailing ` # comment` that sits outside quotes."""
    q = None
    for i, ch in enumerate(v):
        if q:
            q = None if ch == q else q
        elif ch in "'\"":
            q = ch
        elif ch == "#" and (i == 0 or v[i - 1] in " \t"):
            return v[:i].rstrip()
    return v


RELEASE_NAME = re.compile(r"release|deploy|publish", re.I)


def _release_workflow(path, text):
    """True for a workflow that ships rather than checks: by file name, or triggered by a release or a tag."""
    if RELEASE_NAME.search(os.path.basename(path)):
        return True
    m = re.search(r"^(?:on|'on'|\"on\"|true)\s*:(.*)$", text, re.M)
    if not m:
        return False
    if re.search(r"\brelease\b", m.group(1)):
        return True
    block = []
    for line in text[m.end():].splitlines()[1:]:
        if line.strip() and not line[0].isspace():
            break
        block.append(line)
    trig = "\n".join(block)
    return bool(re.search(r"^\s*release\s*:", trig, re.M) or re.search(r"^\s*tags\s*:", trig, re.M))


def _step_cwd(lines, i, col):
    """`working-directory:` among the keys of the step that holds lines[i] (key column `col`)."""
    def key_at(line):
        m = re.match(r"^(\s*)(-\s+)?([\w-]+)\s*:\s*(.*)$", line)
        if not m:
            return None, None, None
        kcol = len(m.group(1)) + (len(m.group(2)) if m.group(2) else 0)
        return kcol, bool(m.group(2)), (m.group(3), m.group(4))
    j = i
    while j >= 0:                                   # back to the line that starts the step
        kcol, dash, kv = key_at(lines[j])
        if kcol is None and lines[j].strip():
            if len(lines[j]) - len(lines[j].lstrip()) < col:
                break
        elif kcol is not None:
            if kcol < col:
                break
            if kcol == col and kv[0] == "working-directory":
                return _unquote(kv[1])
            if kcol == col and dash:
                break
        j -= 1
    j = i + 1
    while j < len(lines):
        kcol, dash, kv = key_at(lines[j])
        if lines[j].strip() and len(lines[j]) - len(lines[j].lstrip()) < col and not (dash and kcol == col):
            break
        if kcol is not None:
            if dash and kcol <= col:
                break
            if kcol == col and kv[0] == "working-directory":
                return _unquote(kv[1])
        j += 1
    return None


def _run_defaults(lines):
    """[(first, last, dir)] for each GitHub Actions `defaults: run: working-directory:`. A workflow-level block covers
    the file; a job-level one covers its job. A step's own `working-directory:` replaces it."""
    ind = lambda l: len(l) - len(l.lstrip())
    live = lambda l: l.strip() and not l.lstrip().startswith("#")
    spans = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)defaults\s*:\s*(?:#.*)?$", line)
        if not m:
            continue
        dcol, run_col, cwd, j = len(m.group(1)), None, None, i + 1
        while j < len(lines) and (not live(lines[j]) or ind(lines[j]) > dcol):
            if live(lines[j]):
                if run_col is not None and ind(lines[j]) <= run_col:
                    run_col = None
                if re.match(r"^\s*run\s*:\s*(?:#.*)?$", lines[j]):
                    run_col = ind(lines[j])
                elif run_col is not None:
                    w = re.match(r"^\s*working-directory\s*:\s*(.+)$", lines[j])
                    cwd = _unquote(_strip_comment(w.group(1).strip())) if w else cwd
            j += 1
        if not cwd:
            continue
        if dcol == 0:
            spans.append((0, len(lines), cwd))
            continue
        k = i - 1                                   # the job key that holds this `defaults:`
        while k >= 0 and (not live(lines[k]) or ind(lines[k]) >= dcol):
            k -= 1
        if k >= 0:
            e = k + 1
            while e < len(lines) and (not live(lines[e]) or ind(lines[e]) > ind(lines[k])):
                e += 1
            spans.append((k, e, cwd))
    return spans


def _with_cwd(cmd, cwd):
    if not cwd:
        return cmd
    if re.search(r"[^\w./-]", cwd):
        cwd = '"' + cwd.replace('"', '\\"') + '"'
    return f"cd {cwd}\n{cmd}" if "\n" in cmd else f"cd {cwd} && {cmd}"


def ci_files(root):
    return sorted(glob.glob(os.path.join(root, ".github", "workflows", "*.y*ml")) + glob.glob(os.path.join(root, ".gitlab-ci.y*ml"))
                  + glob.glob(os.path.join(root, "azure-pipelines*.y*ml")))


def ci_steps(root):
    """Shell commands the CI runs: GitHub Actions `run:`, GitLab `script:`, Azure Pipelines `script:`/`bash:`.
    A line-based reader, not a YAML parser. A block scalar (`run: |`) stays one script, so a `cd` inside it
    keeps its effect; `working-directory:` (the step's own, else a job or workflow `defaults: run:` one) and a
    `- cd x` list item become a `cd` prefix on what follows.
    Returns (steps, skipped release/deploy/publish workflow files)."""
    found, skipped = [], []
    for f in ci_files(root):
        rel = os.path.relpath(f, root).replace("\\", "/")
        text = _read(f)
        if "/workflows/" in "/" + rel and _release_workflow(f, text) or "/workflows/" not in "/" + rel and RELEASE_NAME.search(rel):
            skipped.append(rel)
            continue
        lines = text.splitlines()
        defaults = _run_defaults(lines) if "/workflows/" in "/" + rel else []
        i = 0
        while i < len(lines):
            m = re.match(r"^(\s*)(-\s+)?(run|script|bash|pwsh|powershell)\s*:\s*(.*)$", lines[i])
            if not m:
                i += 1
                continue
            col = len(m.group(1)) + (len(m.group(2)) if m.group(2) else 0)
            indent, value = len(m.group(1)), _strip_comment(m.group(4).strip())
            cwd = _step_cwd(lines, i, col) or next((d for a, b, d in sorted(defaults, reverse=True) if a <= i < b), None)
            emit = lambda cmd, c=cwd: found.append((rel, _with_cwd(cmd, c)))
            if value[:1] in ("|", ">") or value == "":
                folded, body, j = value[:1] == ">", [], i + 1
                while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > indent):
                    body.append(lines[j])
                    j += 1
                i = j
                items = [b for b in body if b.strip()]
                if value == "" and items and all(b.strip().startswith("- ") for b in items):
                    ctx = cwd                        # a list: separate commands sharing one shell
                    for b in items:
                        cmd = _unquote(_strip_comment(b.strip()[2:]))
                        cd = re.fullmatch(r"cd\s+(\S+)", cmd)
                        if cd:
                            ctx = os.path.normpath(os.path.join(ctx or "", _unquote(cd.group(1)))).replace("\\", "/")
                        elif cmd and not cmd.startswith("#"):
                            found.append((rel, _with_cwd(cmd, ctx)))
                    continue
                if value == "":                     # a mapping (e.g. `defaults: run: shell:`), not commands
                    continue
                kept = [b.strip() for b in body if b.strip() and not b.strip().startswith("#")]
                if kept:
                    emit((" " if folded else "\n").join(kept))
                continue
            if value.startswith("["):
                for cmd in _flow_list(value):
                    emit(cmd)
            elif not value.startswith("#"):
                emit(_unquote(value))
            i += 1
    return found, skipped


PR_TEMPLATE = re.compile(r"^pull_request_template\.(md|txt)$", re.I)


def repo_docs(root):
    """PR/MR templates, CODEOWNERS and CONTRIBUTING files in the locations GitHub, GitLab and Azure DevOps read."""
    out = {"pr_template": [], "codeowners": [], "contributing": []}
    for d in (".github", "", "docs", ".gitlab", ".azuredevops"):     # GitHub's own lookup order first
        base = os.path.join(root, d)
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for n in sorted(names):
            rel = f"{d}/{n}" if d else n
            path = os.path.join(base, n)
            if PR_TEMPLATE.match(n) and os.path.isfile(path):
                out["pr_template"].append(rel)
            elif n.lower() in ("pull_request_template", "merge_request_templates") and os.path.isdir(path):
                out["pr_template"] += [f"{rel}/{t}" for t in sorted(os.listdir(path)) if t.lower().endswith((".md", ".txt"))]
            elif n == "CODEOWNERS" and os.path.isfile(path):
                out["codeowners"].append(rel)
            elif re.match(r"^contributing(\.(md|rst|txt|adoc))?$", n, re.I) and os.path.isfile(path):
                out["contributing"].append(rel)
    return out


def detect(root):
    cmds = []
    for d in project_dirs(root):
        rel = os.path.relpath(d, root).replace("\\", "/")
        here = []
        node(d, here, top=root)
        for fn in (python, make, others):
            fn(d, here)
        cmds += [(s, r, c, rel) for s, r, c in here]
    seen, uniq = set(), []
    for c in cmds:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    steps, skipped = ci_steps(root)
    return {"root": os.path.abspath(root), "stacks": sorted({s for s, _, _, _ in uniq}),
            "commands": [{"stack": s, "role": r, "command": c, "dir": d} for s, r, c, d in uniq],
            "ci": [{"file": f, "run": r} for f, r in steps], "ci_skipped": skipped, "docs": repo_docs(root)}


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in a
    a = [x for x in a if x != "--json"]
    root = a[0] if a else "."
    if not os.path.isdir(root):
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    r = detect(root)
    if as_json:
        print(json.dumps(r, indent=2))
        return 0
    print(f"repo: {r['root']}\nstacks: {', '.join(r['stacks']) or 'none detected'}")
    for role in ROLES:
        rows = [c for c in r["commands"] if c["role"] == role]
        if rows:
            print(f"\n{role}:")
            for c in rows:
                where = "" if c["dir"] == "." else f", in {c['dir']}/"
                print(f"  {c['command']}    [{c['stack']}{where}]")
    if r["ci"]:
        print("\nCI runs (the project's own source of truth; prefer these when they differ):")
        for c in r["ci"]:
            print(f"  {c['run'].replace(chr(10), chr(10) + '    ')}    [{c['file']}]")
    if r["ci_skipped"]:
        print("\nSkipped (release, deploy or publish workflows; never run these): " + ", ".join(r["ci_skipped"]))
    d = r["docs"]
    print("\nPR template: " + (", ".join(d["pr_template"]) or "none (use the kit's PR.md layout)"))
    print("CODEOWNERS: " + (", ".join(d["codeowners"]) or "none"))
    print("CONTRIBUTING: " + (", ".join(d["contributing"]) or "none"))
    if not r["commands"] and not r["ci"]:
        print("\nNothing detected: read the README and CONTRIBUTING, or ask the user how they test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
