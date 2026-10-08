#!/usr/bin/env python3
"""Read-only health audit of a Claude Code configuration (stdlib only).

Checks the user config dir (CLAUDE_CONFIG_DIR or ~/.claude) and, optionally, a project:
archives left inside discovery paths, backup files next to live ones, dead @imports, unknown
/skill routes, missing hook targets, secret-looking values in settings env, read-only (vendor)
rule files, path-scoped rules, managed settings in force, and the always-loaded instruction size.

    python audit.py [--project DIR] [--max-kb 40] [--json]

Never prints a credential value: only file paths and key names. Never writes anything.
"""
import argparse, glob, json, os, re, sys

SEV = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
ARCHIVE_RX = re.compile(r"(archive|_old|deprecated|backup|_orphaned)", re.I)
CRED_NAME_RX = re.compile(r"(settings\.json|\.claude\.json|secret|cred|\.env|token)", re.I)
SECRET_KEY_RX = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|PRIVATE_?KEY|AUTH)", re.I)
IMPORT_RX = re.compile(r"(?<![\w`])@((?:[~./\\]|[A-Za-z]:)?(?:\\ |[^\s`)\]])+\.(?:md|txt|json))")
ROUTE_RX = re.compile(r"(?:^|[\s`(,;])/([a-z][a-z0-9-]{2,})(?=[\s`),;.:]|$)")
BUILTIN = {"compact", "clear", "help", "config", "effort", "memory", "context", "init", "model",
           "resume", "status", "login", "logout", "agents", "skills", "hooks", "plugin", "plugins",
           "mcp", "doctor", "permissions", "review", "cost", "usage", "rewind", "statusline",
           "artifacts", "tasks", "fast", "export", "add-dir", "terminal-setup", "ide", "vim"}
PATHSEG = {"opt", "root", "tmp", "dev", "etc", "var", "usr", "home", "bin", "srv", "mnt", "proc",
           "sys", "lib", "c", "d", "mnt", "users", "library", "applications", "system"}
MANAGED_DIRS = {"nt": [r"C:\Program Files\ClaudeCode"], "darwin": ["/Library/Application Support/ClaudeCode"]}


def claude_home():
    return os.path.abspath(os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"))


def managed_dirs():
    if os.name == "nt":
        return MANAGED_DIRS["nt"]
    return MANAGED_DIRS["darwin"] if sys.platform == "darwin" else ["/etc/claude-code"]


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def load_json(path):
    t = read(path)
    if t is None:
        return None
    try:
        return json.loads(t)
    except ValueError:
        return "INVALID"


def strip_code(text):
    """Imports and routes inside fenced blocks or code spans are literal text, not references."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def imports_of(path, text):
    out = []
    for m in IMPORT_RX.findall(strip_code(text)):
        p = os.path.expanduser(m.replace("\\ ", " "))
        if not os.path.isabs(p):
            p = os.path.join(os.path.dirname(path), p)
        out.append((m, os.path.normpath(p)))
    return out


def frontmatter(text):
    m = re.match(r"---\s*\n(.*?)\n---", text or "", re.S)
    return m.group(1) if m else ""


def loaded_set(home, project):
    """Files Claude Code loads at launch: CLAUDE.md files, their imports (4 hops), unconditional rules."""
    roots = [os.path.join(home, "CLAUDE.md")]
    if project:
        roots += [os.path.join(project, "CLAUDE.md"), os.path.join(project, ".claude", "CLAUDE.md"),
                  os.path.join(project, "CLAUDE.local.md")]
    rules = glob.glob(os.path.join(home, "rules", "**", "*.md"), recursive=True)
    if project:
        rules += glob.glob(os.path.join(project, ".claude", "rules", "**", "*.md"), recursive=True)
    seen, dead, frontier = {}, [], [(r, 0) for r in roots if os.path.exists(r)]
    for r in rules:
        t = read(r)
        if t is not None and not re.search(r"^paths\s*:", frontmatter(t), re.M):
            frontier.append((r, 0))
    while frontier:
        p, depth = frontier.pop()
        if p in seen:
            continue
        t = read(p)
        if t is None:
            continue
        seen[p] = len(t.encode("utf-8"))
        if depth >= 4:
            continue
        for raw, q in imports_of(p, t):
            if os.path.exists(q):
                frontier.append((q, depth + 1))
            else:
                dead.append((p, raw))
    return seen, dead, rules


def known_names(home):
    names = {os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(home, "skills", "*", "SKILL.md"))}
    names |= {os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(home, "commands", "**", "*.md"), recursive=True)}
    inst = load_json(os.path.join(home, "plugins", "installed_plugins.json"))
    if isinstance(inst, dict):
        for key, entries in (inst.get("plugins") or {}).items():
            pname = key.split("@")[0]
            names.add(pname)
            for e in entries or []:
                ip = (e or {}).get("installPath") or ""
                for sk in glob.glob(os.path.join(ip, "skills", "*", "SKILL.md")) + glob.glob(os.path.join(ip, "commands", "*.md")):
                    n = os.path.splitext(os.path.basename(sk))[0] if sk.endswith(".md") and not sk.endswith("SKILL.md") \
                        else os.path.basename(os.path.dirname(sk))
                    names |= {n, f"{pname}:{n}"}
    return names


def audit(home, project=None, max_kb=40):
    F = []
    add = lambda sev, where, what, fix: F.append({"severity": sev, "file": where, "finding": what, "fix": fix})

    # 1. archives inside discovery paths (agents/rules/commands/skills are scanned recursively)
    roots = [os.path.join(home, d) for d in ("agents", "rules", "commands", "skills")]
    if project:
        roots.append(os.path.join(project, ".claude"))
    for r in roots:
        for dp, dns, _ in os.walk(r):
            dns[:] = [d for d in dns if d not in ("node_modules", ".git", "worktrees")]
            for d in list(dns):
                if ARCHIVE_RX.search(d):
                    add("HIGH", os.path.join(dp, d), "archive folder inside a discovery path is still loaded",
                        "move it OUT of the discovery root (a sibling folder)")
                    dns.remove(d)

    # 2. backup files next to live ones
    for dp, dns, fns in os.walk(home):
        dns[:] = [d for d in dns if d not in ("backups", "projects", "node_modules", ".git", "plugins")]
        if dp[len(home):].count(os.sep) > 3:
            dns[:] = []
        for fn in fns:
            if re.search(r"\.bak|\.orig$|~$", fn):
                p = os.path.join(dp, fn)
                if CRED_NAME_RX.search(fn):
                    add("CRITICAL", p, "backup of a credential-bearing file", "review, redact or move to a protected backup folder; do not open it in a shared screen")
                else:
                    add("MEDIUM", p, "backup file next to live config (grep and globs read it)", "move to a backup folder")

    # 3 + 7. always-loaded instructions, dead imports, size
    loaded, dead, rules = loaded_set(home, project)
    for src, raw in dead:
        add("MEDIUM", src, f"dead @import -> {raw}", "fix the path or remove the import")
    total = sum(loaded.values())
    sev = "MEDIUM" if total > max_kb * 1024 else "INFO"
    add(sev, home, f"always-loaded instructions: {len(loaded)} files, {total} bytes (~{total // 4} tokens)",
        "demote rarely-needed text into skills or path-scoped rules" if sev != "INFO" else "-")

    # 8 + 9. rule files: read-only (vendor-owned) and path-scoped
    for r in rules:
        t = read(r) or ""
        if not os.access(r, os.W_OK):
            add("LOW", r, "read-only rule file (written by an installer); an upgrade can rewrite it", "name the owning tool; re-check after its upgrades")
        if re.search(r"^paths\s*:", frontmatter(t), re.M):
            add("INFO", r, "path-scoped rule: absent until a matching file is read (and after /compact)", "keep anything that must always hold unconditional")

    # 4. /routes to skills that do not exist
    names = known_names(home)
    for p in loaded:
        for cmd in sorted(set(ROUTE_RX.findall(strip_code(read(p) or "")))):
            if cmd not in names and cmd not in BUILTIN and cmd not in PATHSEG:
                add("LOW", p, f"routes to /{cmd}, which is not an installed skill or command", "install it, fix the name, or drop the route")

    # 5 + 6. settings: hook targets and secret-looking env values
    for sp in [os.path.join(home, "settings.json")] + ([os.path.join(project, ".claude", "settings.json")] if project else []):
        s = load_json(sp)
        if s == "INVALID":
            add("HIGH", sp, "settings file is not valid JSON", "fix the syntax; Claude Code ignores it")
            continue
        if not isinstance(s, dict):
            continue
        for ev, entries in (s.get("hooks") or {}).items():
            for e in entries or []:
                for h in (e or {}).get("hooks") or []:
                    for m in re.findall(r"(?:[A-Za-z]:[\\/]|~[\\/]|/)[^\s\"']+\.(?:py|ps1|sh|cmd|bat|js|mjs)", h.get("command", "")):
                        if "${" not in m and not os.path.exists(os.path.expanduser(m)):
                            add("HIGH", sp, f"[{ev}] hook target missing: {m}", "fix the path; a missing target fails on every matching event")
        for k, v in (s.get("env") or {}).items():
            if SECRET_KEY_RX.search(k) and isinstance(v, str) and v and not v.startswith(("<", "${", "$")):
                add("HIGH", sp, f"env.{k} holds a literal value that looks like a credential", "move it to the OS credential store or an untracked env file; rotate it if the file was ever shared")

    # 10. managed settings in force (informational, never edited)
    for d in managed_dirs():
        for fn in ("managed-settings.json", "managed-mcp.json"):
            p = os.path.join(d, fn)
            if os.path.exists(p):
                add("INFO", p, "managed configuration present; it outranks user settings", "never edit or work around it")
        if os.path.isdir(os.path.join(d, "managed-settings.d")):
            add("INFO", os.path.join(d, "managed-settings.d"), "managed settings drop-in folder present", "-")

    F.sort(key=lambda f: SEV.index(f["severity"]))
    return F


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", default=claude_home(), help="Claude config dir (default: CLAUDE_CONFIG_DIR or ~/.claude)")
    ap.add_argument("--project", help="also audit this project's CLAUDE.md, .claude/ rules and settings")
    ap.add_argument("--max-kb", type=int, default=40, help="warn when always-loaded instructions exceed this many KB")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    F = audit(os.path.abspath(a.home), os.path.abspath(a.project) if a.project else None, a.max_kb)
    if a.json:
        print(json.dumps(F, indent=1))
        return 0
    print("| Severity | File | Finding | Fix |\n|---|---|---|---|")
    for f in F:
        print(f"| {f['severity']} | {f['file']} | {f['finding']} | {f['fix']} |")
    counts = {s: sum(1 for f in F if f["severity"] == s) for s in SEV}
    print("\n" + " · ".join(f"{s} {n}" for s, n in counts.items() if n) + "\nReport only: nothing was changed.")
    return 1 if counts["CRITICAL"] or counts["HIGH"] else 0


if __name__ == "__main__":
    sys.exit(main())
