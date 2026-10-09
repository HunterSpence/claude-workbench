#!/usr/bin/env python3
"""plugin_rules.py: the deterministic rules behind plugin-review, web-packager and the generated plugin CI.

A rule is a tuple (rule_id, group, severity, surfaces, check_fn) in RULES. group is 1-9 (layout, marketplace, skill
frontmatter, hooks, MCP config, prompt-injection and tool surfaces, data handling, licences, supply chain). severity is
block, hold, warn or note. surfaces names where the rule matters (cli, desktop, web): a review for one target runs only
the rules that list it. check_fn(plugin) returns [(file, line, message)]. Rule ids are stable strings.

Nothing here executes the input: files are read as text, Python is parsed with ast and never imported or run. The one
exception is rule S01, which is off unless asked for and then runs `claude plugin validate` (reads, no model call).
Stdlib only. rules_sha256() = SHA-256 of the sorted rule ids plus this module's source, so a report says which rule
set produced it.
"""
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEV_ORDER = {"block": 0, "hold": 1, "warn": 2, "note": 3}
SURFACES = ("cli", "desktop", "web")
PORTABLE_KEYS = ("name", "description", "license", "compatibility", "metadata", "allowed-tools")
NONPORTABLE_KEYS = ("argument-hint", "arguments", "disable-model-invocation", "user-invocable", "disallowed-tools",
                    "model", "effort", "context", "agent", "background", "hooks", "paths", "shell", "when_to_use",
                    "version")
RESERVED_PREFIX = ("claude-", "anthropic-", "anthropics-", "cc-plugin-")
RESERVED_NAMES = {"claude", "claude-code", "claude-mods", "anthropic", "anthropics", "claude-plugins-official", "inline", "builtin",
                  "skills-dir", "synced", "npm", "github"}
SPDX = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "MPL-2.0", "Zlib", "Unlicense", "CC0-1.0",
        "CC-BY-4.0", "CC-BY-SA-4.0", "BSL-1.0", "GPL-2.0-only", "GPL-3.0-only", "GPL-3.0-or-later", "LGPL-3.0-only",
        "AGPL-3.0-only", "UNLICENSED"}
JUNK = {".ds_store", "thumbs.db", "desktop.ini", "ehthumbs.db"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".svg"}
LICENSE_RX = re.compile(r"^(licen[cs]e|copying|unlicense|notice)(\..+)?$", re.I)
NAME_RX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PLACEHOLDER = re.compile(r"(?i)^\s*[\"']?(\$\{|\$\(|<[^>]+>|your[-_ ]|xxx|changeme|replace[-_ ]|example|placeholder|dummy|todo|\*{3}|\.{3})")
SECRETISH = re.compile(r"(?i)(token|secret|api[-_]?key|password|passwd|credential|authorization)")
MAX_TEXT = 1 << 20
MAX_PER_RULE = 20


def reserved_name(name):
    n = (name or "").lower()
    toks = set(re.split(r"[^a-z0-9]+", n))
    return n in RESERVED_NAMES or n.startswith(RESERVED_PREFIX) or ("official" in toks and bool(toks & {"claude", "anthropic"}))


def is_link(entry_path):
    """Symlink or Windows junction; never followed. (Cloud-sync placeholders are reparse points too, but not links.)"""
    try:
        st = os.lstat(entry_path)
    except OSError:
        return False
    tag = getattr(st, "st_reparse_tag", None)
    if tag is not None:
        return os.path.islink(entry_path) or tag in (0xA000000C, 0xA0000003)
    return os.path.islink(entry_path) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def frontmatter(text):
    """-> (dict key -> [value, line], body_line_count) or None. Minimal YAML: top-level keys, folded/literal/nested
    continuation lines are joined into the value."""
    lines = text.lstrip("\ufeff").replace("\r\n", "\n").rstrip("\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None
    fm, key = {}, None
    for i in range(1, end):
        m = re.match(r"^([A-Za-z0-9_][\w-]*)\s*:\s*(.*)$", lines[i])
        if m:
            key = m.group(1)
            fm[key] = [m.group(2).strip(), i + 1]
        elif key and (not lines[i].strip() or lines[i][0] in " \t-"):
            fm[key][0] += " " + lines[i].strip()
    for v in fm.values():
        s = re.sub(r"^[>|][+-]?\s*", "", v[0]).strip()
        if len(s) > 1 and s[0] == s[-1] and s[0] in "\"'":
            s = s[1:-1]
        v[0] = s
    return fm, len(lines) - end - 1


class Plugin:
    """A directory tree seen read-only. Links are listed, never followed."""

    def __init__(self, root, **options):
        self.root = Path(root)
        self.opt = options
        self.files, self.dirs, self.links = [], [], []
        self._text, self._json, self._ast = {}, {}, {}
        self._walk(self.root, "")
        self.fileset = set(self.files)
        self.manifest_path = ".claude-plugin/plugin.json"
        self.manifest = self.json(self.manifest_path) if self.manifest_path in self.fileset else None
        if not isinstance(self.manifest, dict):
            self.manifest = {}
        if self.manifest_path in self.fileset:
            self.kind = "plugin"
        elif ".claude-plugin/marketplace.json" in self.fileset:
            self.kind = "marketplace"
        elif any(f.split("/")[-1] == "SKILL.md" for f in self.files):
            self.kind = "skills"
        else:
            self.kind = "empty"

    def _walk(self, d, prefix):
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError:
            return
        for e in entries:
            rel = prefix + e.name
            if is_link(e.path):
                self.links.append(rel)
            elif e.is_dir(follow_symlinks=False):
                if e.name != ".git":
                    self.dirs.append(rel)
                    self._walk(e.path, rel + "/")
            else:
                self.files.append(rel)

    def size(self, rel):
        try:
            return (self.root / rel).stat().st_size
        except OSError:
            return 0

    def is_text(self, rel):
        if Path(rel).suffix.lower() in IMG_EXT - {".svg"} or self.size(rel) > MAX_TEXT:
            return False
        try:
            with open(self.root / rel, "rb") as f:
                return b"\0" not in f.read(4096)
        except OSError:
            return False

    def text(self, rel):
        if rel not in self._text:
            t = None
            if self.is_text(rel):
                with open(self.root / rel, "rb") as f:
                    t = f.read().decode("utf-8", "replace")
            self._text[rel] = t
        return self._text[rel]

    def json(self, rel):
        if rel not in self._json:
            try:
                self._json[rel] = json.loads((self.text(rel) or "").lstrip("\ufeff"))
            except (ValueError, RecursionError):
                self._json[rel] = None
        return self._json[rel]

    def line_of(self, rel, needle):
        t = self.text(rel) or ""
        i = t.find(needle) if needle else -1
        return t.count("\n", 0, i) + 1 if i >= 0 else 1

    def text_files(self):
        return [f for f in self.files if self.text(f) is not None]

    def md_files(self):
        return [f for f in self.files if f.lower().endswith(".md") and self.text(f) is not None]

    def skills(self):
        return [f for f in self.files if f.split("/")[-1] == "SKILL.md"]

    def py_trees(self):
        out = {}
        for f in self.files:
            if f.endswith(".py") and not is_test_path(f) and self.text(f):
                if f not in self._ast:
                    try:
                        self._ast[f] = ast.parse(self.text(f))
                    except (SyntaxError, ValueError, RecursionError):
                        self._ast[f] = None
                if self._ast[f] is not None:
                    out[f] = self._ast[f]
        return out

    def hooks(self):
        """[(file, event, matcher, handler, line)] from hooks/hooks.json and an inline manifest `hooks` object."""
        out = []
        for rel, obj in (("hooks/hooks.json", self.json("hooks/hooks.json") if "hooks/hooks.json" in self.fileset else None),
                         (self.manifest_path, self.manifest.get("hooks"))):
            if not isinstance(obj, dict):
                continue
            events = obj.get("hooks", obj)
            for event, groups in (events.items() if isinstance(events, dict) else ()):
                for g in groups if isinstance(groups, list) else ():
                    for h in (g.get("hooks") or []) if isinstance(g, dict) else ():
                        if isinstance(h, dict):
                            out.append((rel, event, g.get("matcher"), h, self.line_of(rel, str(h.get("command") or h.get("url") or event))))
        return out

    def servers(self):
        """[(file, name, config)] from .mcp.json and an inline manifest `mcpServers` object."""
        out = []
        for rel, obj in ((".mcp.json", self.json(".mcp.json") if ".mcp.json" in self.fileset else None),
                         (self.manifest_path, self.manifest.get("mcpServers"))):
            if isinstance(obj, dict):
                m = obj.get("mcpServers", obj)
                out += [(rel, n, c) for n, c in (m.items() if isinstance(m, dict) else ()) if isinstance(c, dict)]
        return out

    def descriptions(self):
        """[(file, line, text)] tool/skill descriptions found in code and JSON: text that steers the model."""
        out = []
        for f in self.files:
            if f.lower().endswith((".py", ".js", ".mjs", ".ts", ".json")) and self.text(f):
                for n, line in enumerate(self.text(f).split("\n"), 1):
                    line = line[:4000]
                    for m in re.finditer(r"""\bdescription["']?\s*[=:]\s*[rf]?(["'])(.{10,}?)\1""", line):
                        out.append((f, n, m.group(2)))
        for f, tree in self.py_trees().items():
            for fn in ast.walk(tree):
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and tool_decorator(fn):
                    doc = ast.get_docstring(fn)
                    if doc:
                        out.append((f, fn.lineno, doc))
        return out


def is_test_path(rel):
    parts = rel.lower().split("/")
    return any(p in ("tests", "test", "__tests__") or p.startswith("test_") for p in parts)


def tool_decorator(fn):
    """Source of the first decorator that looks like an MCP tool registration, else None."""
    for d in fn.decorator_list:
        try:
            s = ast.unparse(d)
        except Exception:
            continue
        if re.search(r"(^|\.)tool\b|call_tool", s):
            return s
    return None


RULES = []


def rule(rid, group, sev, surfaces="cli,desktop,web"):
    def deco(fn):
        RULES.append((rid, group, sev, tuple(surfaces.split(",")), fn))
        return fn
    return deco


def walk_strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from walk_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk_strings(v)


# ---- group 1: layout and manifest -------------------------------------------------------------------------------
@rule("L01-manifest", 1, "block")
def _(p):
    out = []
    if p.kind == "empty":
        out.append(("", 0, "no .claude-plugin/plugin.json and no SKILL.md: nothing to review"))
    for rel in (p.manifest_path, "hooks/hooks.json", ".mcp.json", ".claude-plugin/marketplace.json"):
        if rel in p.fileset and p.json(rel) is None:
            out.append((rel, 1, "not valid JSON"))
    return out


@rule("L02-multiple-manifests", 1, "block")
def _(p):
    if p.kind == "marketplace":
        return []
    extra = [f for f in p.files if f.endswith("/.claude-plugin/plugin.json") or (f.endswith(".claude-plugin/plugin.json") and f != p.manifest_path)]
    return [(f, 1, "more than one plugin.json: a plugin archive holds exactly one") for f in extra]


@rule("L03-name-pattern", 1, "block")
def _(p):
    if p.kind != "plugin":
        return []
    n = p.manifest.get("name")
    if not isinstance(n, str) or not NAME_RX.match(n) or len(n) > 64:
        return [(p.manifest_path, p.line_of(p.manifest_path, '"name"'), "name must be lowercase-hyphen, at most 64 characters")]
    return []


@rule("L04-reserved-name", 1, "block")
def _(p):
    n = p.manifest.get("name")
    if p.kind == "plugin" and isinstance(n, str) and reserved_name(n):
        return [(p.manifest_path, p.line_of(p.manifest_path, '"name"'), "reserved name: " + n)]
    return []


CONFUSABLE = ("CYRILLIC", "GREEK", "ARMENIAN", "CHEROKEE", "COPTIC")


def lookalike(s):
    for tok in s.split():
        if any(unicodedata.category(c) in ("Cf", "Cc") for c in tok):
            return "invisible or control character"
        if any(c.isascii() and c.isalpha() for c in tok) and any(unicodedata.name(c, "").startswith(CONFUSABLE) for c in tok):
            return "mixes Latin letters with look-alike letters from another script"
        if any(not c.isascii() and unicodedata.normalize("NFKC", c).isascii() for c in tok):
            return "full-width or compatibility form of an ASCII character"
    return None


@rule("L05-lookalike-name", 1, "block")
def _(p):
    m, out = p.manifest, []
    author = m.get("author") if isinstance(m.get("author"), dict) else {}
    for key, val in (("name", m.get("name")), ("displayName", m.get("displayName")), ("author.name", author.get("name"))):
        if isinstance(val, str) and lookalike(val):
            out.append((p.manifest_path, p.line_of(p.manifest_path, val), f"{key}: {lookalike(val)}"))
    return out


@rule("L06-path-outside", 1, "block")
def _(p):
    out = []
    for key in ("skills", "commands", "agents", "hooks", "mcpServers", "lspServers", "outputStyles", "workflows",
                "themes", "monitors"):
        v = p.manifest.get(key)
        for s in ([v] if isinstance(v, str) else [x for x in v if isinstance(x, str)] if isinstance(v, list) else []):
            segs = re.split(r"[\\/]", s)
            if s.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", s) or ".." in segs:
                out.append((p.manifest_path, p.line_of(p.manifest_path, s), f"{key} points outside the plugin folder: {s}"))
    for rel in ("hooks/hooks.json", ".mcp.json", p.manifest_path):
        if rel in p.fileset and re.search(r"CLAUDE_PLUGIN_ROOT\}?[\\/]+\.\.", p.text(rel) or ""):
            out.append((rel, p.line_of(rel, "CLAUDE_PLUGIN_ROOT}/.."), "path climbs out of ${CLAUDE_PLUGIN_ROOT}"))
    return out


@rule("L07-symlink", 1, "block")
def _(p):
    out = [(f, 1, "symlink or junction (never followed)") for f in p.links]
    out += [(f, 1, "git submodule file") for f in p.files if f.split("/")[-1] == ".gitmodules"]
    out += [(f, 1, "Git LFS pointer, not the real file") for f in p.files
            if p.size(f) < 1024 and (p.text(f) or "").startswith("version https://git-lfs.github.com/spec")]
    return out


@rule("L08-os-junk", 1, "block")
def _(p):
    out = [(f, 1, "OS junk file") for f in p.files
           if f.split("/")[-1].lower() in JUNK or f.split("/")[-1].startswith("._") or "__MACOSX" in f.split("/")]
    return out + [(d, 1, "OS junk folder") for d in p.dirs if d.split("/")[-1] == "__MACOSX"]


@rule("L09-file-size", 1, "hold")
def _(p):
    return [(f, 1, f"{p.size(f) // 1024} KiB: non-image files must stay under 256 KiB") for f in p.files
            if Path(f).suffix.lower() not in IMG_EXT and p.size(f) >= 256 * 1024]


@rule("L10-file-count", 1, "hold")
def _(p):
    return [("", 0, f"{len(p.files)} files: at most 512")] if len(p.files) > 512 else []


@rule("L11-readme", 1, "block")
def _(p):
    if p.kind != "plugin":
        return []
    rd = next((f for f in p.files if f.lower() in ("readme.md", "readme", "readme.txt")), None)
    if not rd:
        return [("", 0, "no README at the plugin root")]
    words = len(re.findall(r"\w+", re.sub(r"```.*?```", "", p.text(rd) or "", flags=re.S)))
    return [(rd, 1, f"README has {words} words outside code blocks: at least 40")] if words < 40 else []


def license_text_files(p, folder=""):
    pre = folder + "/" if folder else ""
    return [f for f in p.files if f.startswith(pre) and "/" not in f[len(pre):] and LICENSE_RX.match(f[len(pre):])]


@rule("L12-license", 1, "block")
def _(p):
    root_lic = license_text_files(p) or isinstance(p.manifest.get("license"), str) and p.manifest["license"]
    if p.kind == "plugin":
        return [] if root_lic else [(p.manifest_path, 1, "no LICENSE file and no license field")]
    out = []
    for s in p.skills():
        d = s.rsplit("/", 1)[0] if "/" in s else ""
        fm = frontmatter(p.text(s) or "")
        has = any(license_text_files(p, d if d else "")) or (fm and "license" in fm[0]) or root_lic
        while not has and "/" in d:
            d = d.rsplit("/", 1)[0]
            has = bool(license_text_files(p, d))
        if not has:
            out.append((s, 1, "no LICENSE beside the skill and no license field"))
    return out


# ---- group 2: marketplace ---------------------------------------------------------------------------------------
MKT = ".claude-plugin/marketplace.json"


@rule("M01-marketplace-schema", 2, "block")
def _(p):
    if MKT not in p.fileset or p.json(MKT) is None:
        return []
    m, out = p.json(MKT), []
    if not isinstance(m, dict):
        return [(MKT, 1, "marketplace.json must be an object")]
    if not isinstance(m.get("name"), str) or not NAME_RX.match(m["name"]) or reserved_name(m["name"]):
        out.append((MKT, p.line_of(MKT, '"name"'), "marketplace name missing, malformed or reserved"))
    if not isinstance(m.get("owner"), dict) or not m["owner"].get("name"):
        out.append((MKT, p.line_of(MKT, '"owner"'), "owner.name is required"))
    if not isinstance(m.get("plugins"), list):
        return out + [(MKT, 1, "plugins must be a list")]
    for e in m["plugins"]:
        if not isinstance(e, dict) or not e.get("name") or not e.get("source"):
            out.append((MKT, 1, "each plugin entry needs name and source"))
    return out


@rule("M02-version-twice", 2, "hold")
def _(p):
    m = p.json(MKT) if MKT in p.fileset else None
    out = []
    for e in (m.get("plugins") if isinstance(m, dict) and isinstance(m.get("plugins"), list) else []):
        if isinstance(e, dict) and "version" in e and isinstance(e.get("source"), str):
            rel = e["source"].lstrip("./").rstrip("/") + "/" + p.manifest_path
            pj = p.json(rel) if rel in p.fileset else None
            if isinstance(pj, dict) and "version" in pj:
                out.append((MKT, p.line_of(MKT, '"version"'), f"version for {e.get('name')} is set in plugin.json and in the marketplace entry"))
    return out


@rule("M03-unpinned-source", 2, "hold")
def _(p):
    m = p.json(MKT) if MKT in p.fileset else None
    out = []
    for e in (m.get("plugins") if isinstance(m, dict) and isinstance(m.get("plugins"), list) else []):
        s = e.get("source") if isinstance(e, dict) else None
        remote = isinstance(s, dict) and s.get("source") in ("github", "url", "git-subdir") or isinstance(s, str) and re.match(r"^(https?|git)[:@]", s)
        if remote and not (isinstance(s, dict) and re.fullmatch(r"[0-9a-f]{40}", str(s.get("sha", "")))):
            out.append((MKT, p.line_of(MKT, str(e.get("name"))), f"third-party source for {e.get('name')} is not pinned by a 40-character sha"))
    return out


# ---- group 3: skill frontmatter, per surface --------------------------------------------------------------------
@rule("F01-nonportable-key", 3, "block", "web")
def _(p):
    out = []
    for s in p.skills():
        fm = frontmatter(p.text(s) or "")
        for k, (_v, line) in (fm[0].items() if fm else ()):
            if k in NONPORTABLE_KEYS:
                out.append((s, line, f"frontmatter key '{k}' is rejected by claude.ai uploads"))
    return out


@rule("F02-unknown-key", 3, "block", "web")
def _(p):
    out = []
    for s in p.skills():
        fm = frontmatter(p.text(s) or "")
        for k, (_v, line) in (fm[0].items() if fm else ()):
            if k not in PORTABLE_KEYS and k not in NONPORTABLE_KEYS:
                out.append((s, line, f"unknown frontmatter key '{k}'"))
    return out


@rule("F03-skill-name", 3, "block", "web")
def _(p):
    out = []
    for s in p.skills():
        fm = frontmatter(p.text(s) or "")
        if not fm:
            out.append((s, 1, "no YAML frontmatter"))
            continue
        v, line = fm[0].get("name", ["", 1])
        parent = s.split("/")[-2] if "/" in s else None      # a SKILL.md at the root has no folder name to compare
        if not v or not NAME_RX.match(v) or len(v) > 64:
            out.append((s, line, "name must be lowercase-hyphen, 1-64 characters"))
        elif re.search(r"anthropic|claude", v):
            out.append((s, line, "name contains a reserved word"))
        elif parent and parent != v:
            out.append((s, line, f"name '{v}' must equal its folder '{parent}'"))
    return out


@rule("F04-skill-description", 3, "block", "web")
def _(p):
    out = []
    for s in p.skills():
        fm = frontmatter(p.text(s) or "")
        d = fm[0].get("description") if fm else None
        if fm and (not d or not d[0]):
            out.append((s, 1, "description is missing or empty"))
        elif d and len(d[0]) > 1024:
            out.append((s, d[1], f"description is {len(d[0])} characters: at most 1024"))
        elif d and re.search(r"[<>]", d[0]):
            out.append((s, d[1], "description contains < or >"))
    return out


@rule("F05-body-length", 3, "warn", "web")
def _(p):
    return [(s, 1, f"body is {fm[1]} lines: keep skills under 500") for s in p.skills()
            for fm in [frontmatter(p.text(s) or "")] if fm and fm[1] >= 500]


@rule("F06-bin-dir", 3, "block", "desktop,web")
def _(p):
    return [(d, 1, "a top-level bin/ makes claude.ai and Cowork refuse the whole plugin") for d in p.dirs if d == "bin"]


# ---- group 4: hook safety ---------------------------------------------------------------------------------------
def hook_texts(p, h):
    """The hook's own command text plus the plugin files it runs: [(file, text)]."""
    args = h.get("args") if isinstance(h.get("args"), list) else []
    cmd = " ".join([str(h.get("command") or "")] + [str(a) for a in args])
    out = [(None, cmd)]
    for m in re.finditer(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s\"']+)", cmd):
        if m.group(1) in p.fileset and p.text(m.group(1)) is not None:
            out.append((m.group(1), p.text(m.group(1))))
    return out


def hook_scan(p, rx, what, flags=0):
    out = []
    for rel, event, _m, h, line in p.hooks():
        for f, t in hook_texts(p, h):
            for n, ln in enumerate(t.split("\n"), 1):
                if re.search(rx, ln, flags):
                    out.append((f or rel, n if f else line, f"{what} in the {event} hook"))
                    break
    return out


@rule("H01-shell-form", 4, "warn", "cli,desktop")
def _(p):
    return [(r, ln, f"{e} hook uses shell form; prefer exec form with args") for r, e, _m, h, ln in p.hooks()
            if h.get("type", "command") == "command" and not isinstance(h.get("args"), list)]


@rule("H02-unquoted-plugin-root", 4, "hold", "cli,desktop")
def _(p):
    out = []
    for r, e, _m, h, ln in p.hooks():
        cmd = str(h.get("command") or "")
        if h.get("type", "command") == "command" and not isinstance(h.get("args"), list):
            if "${CLAUDE_PLUGIN_ROOT}" in re.sub(r"\"[^\"]*\"|'[^']*'", "", cmd):
                out.append((r, ln, f"{e} hook: quote \"${{CLAUDE_PLUGIN_ROOT}}\" in shell form (paths with spaces break)"))
    return out


@rule("H03-user-config-in-shell", 4, "block", "cli,desktop")
def _(p):
    return [(r, ln, f"{e} hook: ${{user_config.*}} is rejected in shell form") for r, e, _m, h, ln in p.hooks()
            if not isinstance(h.get("args"), list) and "${user_config." in str(h.get("command") or "")]


@rule("H04-no-timeout", 4, "warn", "cli,desktop")
def _(p):
    return [(r, ln, f"{e} hook has no explicit timeout") for r, e, _m, h, ln in p.hooks()
            if h.get("type", "command") in ("command", "http") and "timeout" not in h]


@rule("H05-broad-matcher", 4, "warn", "cli,desktop")
def _(p):
    return [(r, ln, f"{e} hook matches every tool; narrow the matcher") for r, e, m, h, ln in p.hooks()
            if e in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest") and (m in (None, "", "*", ".*"))]


@rule("H06-network-call", 4, "hold", "cli,desktop")
def _(p):
    return hook_scan(p, r"\b(curl|wget|Invoke-WebRequest|Invoke-RestMethod|iwr|irm)\b|\brequests\.(get|post|put|patch)\b|urllib\.request|http\.client|urlopen\(|\bfetch\(|create_connection\(", "network call")


@rule("H07-env-credential-read", 4, "hold", "cli,desktop")
def _(p):
    rx = (r"\$\{?(?!CLAUDE_PLUGIN_OPTION_)[A-Z0-9_]*(TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIAL)[A-Z0-9_]*\}?"
          r"|environ(\.get)?\s*[\(\[]\s*[\"'](?!CLAUDE_PLUGIN_OPTION_)[A-Za-z0-9_]*(TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIAL)"
          r"|getenv\(\s*[\"'](?!CLAUDE_PLUGIN_OPTION_)[A-Za-z0-9_]*(TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIAL)"
          r"|process\.env\.[A-Z0-9_]*(TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIAL)|\$env:\w*(TOKEN|SECRET|PASSWORD|KEY)")
    return hook_scan(p, rx, "environment credential read", re.I)


@rule("H08-write-outside-data", 4, "warn", "cli,desktop")
def _(p):
    out = []
    for rel, event, _m, h, line in p.hooks():
        for f, t in hook_texts(p, h):
            if f and re.search(r"open\([^)]*[\"'][wax]|write_text|write_bytes|Set-Content|Out-File|>>?\s*\S", t) \
                    and re.search(r"expanduser|~/|\$HOME|/etc/|%USERPROFILE%", t):
                out.append((f, 1, f"{event} hook writes under the home folder; keep state in ${{CLAUDE_PLUGIN_DATA}}"))
    return out


@rule("H09-dangerous-command", 4, "hold", "cli,desktop")
def _(p):
    return hook_scan(p, r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*|\beval\b[\s(]|Remove-Item[^\n]*-Recurse|shutil\.rmtree|\bmkfs\b|\bdd\s+if=", "destructive or eval command")


@rule("H10-inline-program", 4, "hold", "cli,desktop")
def _(p):
    out = []
    for r, e, _m, h, ln in p.hooks():
        args = h.get("args") if isinstance(h.get("args"), list) else None
        if args is not None:
            bad = any(str(a) in ("-c", "-e", "-Command", "-EncodedCommand", "/c", "/C") for a in args)
        else:
            bad = bool(re.search(r"\b(python3?|py|node|bash|sh|zsh|pwsh|powershell|perl|ruby)\b\s+(-\w+\s+)*(-c|-e|-Command|-EncodedCommand)\b", str(h.get("command") or "")))
        if bad:
            out.append((r, ln, f"{e} hook runs an inline program; ship a script file instead"))
    return out


@rule("H11-http-hook-not-https", 4, "block", "cli,desktop")
def _(p):
    return [(r, ln, f"{e} http hook posts to a non-https URL") for r, e, _m, h, ln in p.hooks()
            if h.get("type") == "http" and not re.match(r"^(https://|http://localhost[:/])", str(h.get("url") or ""))]


# ---- group 5: MCP config pinning and secrets --------------------------------------------------------------------
def stdio(cfg):
    return "command" in cfg or cfg.get("type") == "stdio"


@rule("P01-url-not-https", 5, "block")
def _(p):
    return [(f, p.line_of(f, str(c["url"])), f"server '{n}': remote URL must be https or wss")
            for f, n, c in p.servers() if isinstance(c.get("url"), str) and not re.match(r"^(https|wss)://|^http://localhost[:/]", c["url"])]


@rule("P02-literal-credential", 5, "block")
def _(p):
    out = []
    for f, n, c in p.servers():
        for blk in ("headers", "env"):
            for k, v in (c.get(blk) or {}).items() if isinstance(c.get(blk), dict) else ():
                if SECRETISH.search(k) and isinstance(v, str) and v.strip() and "${" not in v and not PLACEHOLDER.match(re.sub(r"(?i)^bearer\s+", "", v)):
                    out.append((f, p.line_of(f, k), f"server '{n}': literal value for {blk[:-1]} '{k}'; use a sensitive userConfig option"))
    return out


@rule("P03-secret-not-sensitive", 5, "hold")
def _(p):
    out = []
    uc = p.manifest.get("userConfig") if isinstance(p.manifest.get("userConfig"), dict) else {}
    for k, v in uc.items():
        if SECRETISH.search(k) and not (isinstance(v, dict) and v.get("sensitive") is True):
            out.append((p.manifest_path, p.line_of(p.manifest_path, f'"{k}"'), f"userConfig '{k}' looks like a secret but is not sensitive: true"))
    for f, n, c in p.servers():
        for s in walk_strings(c):
            for m in re.finditer(r"\$\{user_config\.([A-Za-z0-9_]+)\}", s):
                if p.kind == "plugin" and m.group(1) not in uc:
                    out.append((f, p.line_of(f, m.group(0)), f"server '{n}': ${{user_config.{m.group(1)}}} is not declared in userConfig"))
    return out


@rule("P04-env-credential-ref", 5, "hold")
def _(p):
    out = []
    for f, n, c in p.servers():
        for s in walk_strings(c):
            m = re.search(r"\$\{?(?!CLAUDE_PLUGIN_OPTION_)([A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIAL)[A-Z0-9_]*)\}?", s)
            if m:
                out.append((f, p.line_of(f, m.group(0)), f"server '{n}' reads the environment credential {m.group(1)}"))
    return out


def launcher(cfg):
    """Package spec an npx/uvx/bunx/pipx/pnpm/npm/uv launcher would fetch, '' when none given, None for any other command."""
    cmd = re.sub(r"\.(exe|cmd|bat)$", "", os.path.basename(str(cfg.get("command") or "")).lower())
    args = [str(a) for a in cfg.get("args") or []] if isinstance(cfg.get("args"), list) else []
    words = [a for a in args if not a.startswith("-")]
    if cmd in ("npx", "bunx", "uvx"):
        return words[0] if words else ""
    if cmd == "uv":
        return (words[2] if len(words) > 2 else "") if words[:2] == ["tool", "run"] else None
    sub = {"pipx": ("run",), "pnpm": ("dlx",), "yarn": ("dlx",), "npm": ("exec",)}
    if cmd in sub and words[:1] and words[0] in sub[cmd]:
        return words[1] if len(words) > 1 else ""
    return None


@rule("P05-shell-launcher", 5, "hold", "cli,desktop")
def _(p):
    out = []
    for f, n, c in p.servers():
        if not stdio(c):
            continue
        cmd = re.sub(r"\.(exe|cmd|bat)$", "", os.path.basename(str(c.get("command") or "")).lower())
        args = [str(a) for a in c.get("args") or []] if isinstance(c.get("args"), list) else []
        if cmd in ("sh", "bash", "zsh", "cmd", "powershell", "pwsh") or any(a in ("-c", "/c", "/C", "-Command", "-e") for a in args) \
                or (cmd in ("npm", "yarn", "pnpm") and args[:1] in (["run"], ["start"])):
            out.append((f, p.line_of(f, n), f"server '{n}' starts through a shell or script runner; run a plugin file with plain args"))
    return out


@rule("P06-unpinned-launcher", 5, "block", "cli,desktop")
def _(p):
    out = []
    for f, n, c in p.servers():
        spec = launcher(c)
        if spec is not None and not (re.search(r"(?<=.)@v?\d+\.\d+\.\d+[\w.+-]*$", spec) or re.search(r"==\d+(\.\d+)*[\w.+-]*$", spec)):
            out.append((f, p.line_of(f, n), f"server '{n}': launcher package '{spec or '?'}' is not pinned to an exact version"))
    return out


@rule("P07-registry-override", 5, "hold", "cli,desktop")
def _(p):
    names = {".npmrc", "uv.toml", "bunfig.toml", "pip.conf", "pip.ini", ".yarnrc", ".yarnrc.yml", ".pypirc"}
    return [(f, 1, "package registry override file") for f in p.files if f.split("/")[-1] in names]


@rule("P08-remote-bundle", 5, "block")
def _(p):
    out = []
    for f, n, c in p.servers():
        for s in walk_strings(c):
            if re.match(r"^https?://\S+\.(mcpb|dxt)(\?\S*)?$", s):
                out.append((f, p.line_of(f, s), f"server '{n}' installs a bundle fetched from a URL"))
    mv = p.manifest.get("mcpServers")
    for s in ([mv] if isinstance(mv, str) else mv if isinstance(mv, list) else []):
        if isinstance(s, str) and re.match(r"^https?://\S+\.(mcpb|dxt)", s):
            out.append((p.manifest_path, p.line_of(p.manifest_path, s), "mcpServers installs a bundle fetched from a URL"))
    return out


@rule("P09-local-stdio-server", 5, "block", "web")
def _(p):
    return [(f, p.line_of(f, n), f"server '{n}' runs on this machine; claude.ai only connects to remote servers") for f, n, c in p.servers() if stdio(c)]


@rule("P10-user-config-in-url", 5, "block", "web")
def _(p):
    return [(f, p.line_of(f, "user_config"), f"server '{n}': ${{user_config.*}} in a URL is ignored in chat") for f, n, c in p.servers()
            if isinstance(c.get("url"), str) and "${user_config." in c["url"]]


@rule("P11-uv-run-unlocked", 5, "hold", "cli,desktop")
def _(p):
    return [(f, p.line_of(f, n), f"server '{n}': use uv run --locked") for f, n, c in p.servers()
            if os.path.basename(str(c.get("command") or "")).lower().startswith("uv") and isinstance(c.get("args"), list)
            and c["args"][:1] == ["run"] and not {"--locked", "--frozen"} & set(map(str, c["args"]))]


# ---- group 6: prompt-injection surfaces and tool behaviour ------------------------------------------------------
OVERRIDE = re.compile(
    r"(?i)\b(ignore|disregard|forget|override)\s+(all\s+|any\s+|the\s+|your\s+)?(previous|prior|above|earlier|system|safety)\s+(instructions?|rules?|prompts?|guidelines?|constraints?)"
    r"|\b(do not|don't|never)\s+(tell|inform|alert)\s+the\s+user|\byou are now (in )?(developer|dan|unrestricted)\b|\bnew (system )?instructions?\s*:")
ALWAYS_CALL = re.compile(r"(?i)\b(always|must|first)\s+(call|invoke|run|execute|use)\s+(the\s+)?[`'\"]?[a-z]+_[a-z0-9_]+[`'\"]?")
BEFORE_ANY = re.compile(r"(?i)\bbefore\s+(using|calling|invoking|running|any|every)\s+(any\s+|every\s+)?(other\s+)?tool|\bbefore (doing )?anything else\b[^.\n]{0,40}\b(call|run|invoke)")
FETCH_RULES = re.compile(r"(?i)\b(fetch|download|load|retrieve|obtain|pull|read|get)\b[^.\n]{0,60}\b(rules|instructions|guidelines|prompt|policy|policies)\b[^.\n]{0,60}https?://"
                         r"|\bfollow (the )?(rules|instructions)\b[^.\n]{0,40}https?://")


def prose_hits(p, rx, md=True, desc=True):
    out = []
    if md:
        for f in p.md_files():
            for n, ln in enumerate(p.text(f).split("\n"), 1):
                m = rx.search(ln)
                if m:
                    out.append((f, n, m.group(0)[:80]))
    if desc:
        for f, n, t in p.descriptions():
            m = rx.search(t)
            if m and not f.lower().endswith(".md"):
                out.append((f, n, m.group(0)[:80]))
    return out


@rule("I01-override-phrase", 6, "hold")
def _(p):
    return [(f, n, f"instruction-override wording: '{t}'") for f, n, t in prose_hits(p, OVERRIDE)]


@rule("I02-always-call", 6, "hold")
def _(p):
    return [(f, n, f"text steers which tool runs first: '{t}'") for f, n, t in prose_hits(p, ALWAYS_CALL, md=False)
            + prose_hits(p, BEFORE_ANY)]


@rule("I03-fetch-rules-from-url", 6, "hold")
def _(p):
    return [(f, n, f"tells the model to load its rules from a URL: '{t}'") for f, n, t in prose_hits(p, FETCH_RULES)]


@rule("I04-hidden-comment", 6, "hold")
def _(p):
    cue = re.compile(r"(?i)ignore|disregard|system prompt|assistant|the model|you (must|should|will)|do not (tell|reveal|mention)|secret|silent|exfil|upload|send\b[^>]{0,30}\bto\b|curl")
    out = []
    for f in p.md_files():
        t = p.text(f)
        for m in re.finditer(r"<!--(.*?)-->", t, re.S):
            if cue.search(m.group(1)):
                out.append((f, t.count("\n", 0, m.start()) + 1, "hidden HTML comment addressed to the model"))
    return out


INVISIBLE = re.compile("[\u200b\u200c\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\u061c\u180e\U000e0000-\U000e007f\ufeff\u200d\ufe00-\ufe0f]")


@rule("I05-invisible-characters", 6, "block")
def _(p):
    out = []
    for f in p.text_files():
        t = p.text(f)
        for n, ln in enumerate(t.split("\n"), 1):
            for m in INVISIBLE.finditer(ln):
                c = m.group(0)
                prev = ln[m.start() - 1] if m.start() else ""
                if c == "\ufe0f" and ln[m.end():m.end() + 1] == "\u20e3":
                    continue
                if (c == "\ufeff" and n == 1 and m.start() == 0) or (c in "\u200d\ufe00\ufe01\ufe02\ufe03\ufe04\ufe05\ufe06\ufe07\ufe08\ufe09\ufe0a\ufe0b\ufe0c\ufe0d\ufe0e\ufe0f" and prev and ord(prev) >= 0x2190):
                    continue
                out.append((f, n, f"invisible or bidirectional control character U+{ord(c):04X}"))
                break
    return out


@rule("I06-encoded-blob", 6, "hold")
def _(p):
    out = []
    for f in p.text_files():
        if f.startswith("assets/") or "/assets/" in f or f.endswith(".lock") or f.endswith("package-lock.json"):
            continue
        for n, ln in enumerate(p.text(f).split("\n"), 1):
            if "data:image/" in ln or "data:font" in ln:
                continue
            if re.search(r"[A-Za-z0-9+/]{120,}={0,2}", ln) or re.search(r"\b[0-9a-fA-F]{100,}\b", ln):
                out.append((f, n, "long base64 or hex blob"))
                break
    return out


EXFIL = re.compile(r"(?i)!\[.{0,200}?\]\((https?:)?//[^)\s]*\?[^)\s]*\)|<img[^>]+src=[\"']https?://[^\"']*\?[^\"']*[\"']"
                   r"|hooks\.slack\.com/services|discord(app)?\.com/api/webhooks|webhook\.site|requestbin|pipedream\.net|ngrok(-free)?\.(io|app|dev)|interact\.sh|oast\.")


@rule("I07-exfil-sink", 6, "hold")
def _(p):
    return [(f, n, "possible data-exfiltration sink (image with query string or webhook)") for f in p.text_files() if not is_test_path(f)
            for n, ln in enumerate(p.text(f).split("\n"), 1) if EXFIL.search(ln)][:MAX_PER_RULE]


@rule("I08-lethal-trifecta", 6, "hold")
def _(p):
    srv, hk = p.servers(), p.hooks()
    if not srv and not any(h[3].get("type") == "http" for h in hk):
        return []
    blob = " ".join(json.dumps(c).lower() for _f, _n, c in srv) + " " + " ".join(json.dumps(h[3]).lower() for h in hk)
    prose = " ".join((p.text(f) or "").lower() for f in p.md_files())
    private = re.search(r"mail|calendar|drive|sharepoint|crm|database|\bdb\b|postgres|sql|slack|teams|jira|github|files?\b|filesystem", blob)
    untrusted = re.search(r"fetch|browse|web[- ]?search|scrape|crawl|puppeteer|playwright|\bweb page|incoming (mail|email)|inbox", blob + " " + prose)
    outbound = re.search(r"send[-_ ]?(mail|email|message)|post[-_ ]?message|webhook|upload|smtp|publish", blob) \
        or any(h[3].get("type") == "http" for h in hk)
    if private and untrusted and outbound:
        return [((srv[0][0] if srv else hk[0][0]), 1, "private-data access, untrusted-content reading and an outbound channel in one plugin")]
    return []


def py_functions(p):
    for f, tree in p.py_trees().items():
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield f, fn, tool_decorator(fn)


def write_ops(fn):
    for c in ast.walk(fn):
        if not isinstance(c, ast.Call):
            continue
        f = c.func
        if isinstance(f, ast.Name) and f.id == "open":
            mode = c.args[1] if len(c.args) > 1 else next((k.value for k in c.keywords if k.arg == "mode"), None)
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and set(mode.value) & set("wax+"):
                return True
        elif isinstance(f, ast.Attribute):
            if f.attr in ("write_text", "write_bytes", "unlink", "rmdir", "rmtree", "makedirs", "rename", "touch",
                          "truncate", "post", "put", "patch", "delete"):
                return True
            if f.attr == "write" and not (isinstance(f.value, ast.Attribute) and f.value.attr in ("stdout", "stderr")):
                return True
            if f.attr in ("execute", "executemany") and c.args:
                if re.search(r"(?i)\b(insert|update|delete|drop|alter|create)\b", ast.unparse(c.args[0])):
                    return True
    return False


@rule("I09-readonly-hint-lies", 6, "hold", "cli,desktop")
def _(p):
    return [(f, fn.lineno, f"tool '{fn.name}' is marked readOnlyHint but writes") for f, fn, d in py_functions(p)
            if d and re.search(r"readOnlyHint['\"]?\s*[:=]\s*True", d) and write_ops(fn)]


@rule("I10-write-without-destructive-hint", 6, "hold", "cli,desktop")
def _(p):
    return [(f, fn.lineno, f"tool '{fn.name}' writes but declares no destructiveHint") for f, fn, d in py_functions(p)
            if d and write_ops(fn) and "destructiveHint" not in d and not re.search(r"readOnlyHint['\"]?\s*[:=]\s*True", d)]


@rule("I11-catch-all-request-tool", 6, "hold", "cli,desktop")
def _(p):
    out = []
    for f, fn, d in py_functions(p):
        args = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        if d and ("method" in args and args & {"url", "path", "endpoint", "uri"} or re.match(r"^(api|http|rest)_?request$|^request$|^(call|execute)_?(api|request)$", fn.name)):
            out.append((f, fn.lineno, f"tool '{fn.name}' is a catch-all request tool mixing safe and unsafe methods"))
    return out


@rule("I12-identity-argument", 6, "hold", "cli,desktop")
def _(p):
    bad = {"as_user", "impersonate", "impersonate_user", "on_behalf_of", "run_as", "acting_as", "act_as", "sudo"}
    return [(f, fn.lineno, f"tool '{fn.name}' takes an identity argument ({', '.join(sorted(bad & {a.arg for a in fn.args.args + fn.args.kwonlyargs}))})")
            for f, fn, d in py_functions(p) if d and bad & {a.arg for a in fn.args.args + fn.args.kwonlyargs}]


@rule("C01-stdout-logging", 6, "hold", "cli,desktop")
def _(p):
    out = []
    for f, tree in p.py_trees().items():
        t = p.text(f)
        if not re.search(r"^\s*(?:from|import)\s+(?:mcp|fastmcp)\b|\"jsonrpc\"|tools/list", t, re.M):
            continue
        for c in ast.walk(tree):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "print" and not any(k.arg == "file" for k in c.keywords):
                out.append((f, c.lineno, "print() writes to stdout, which carries the stdio protocol; log to stderr"))
                break
    return out


@rule("C02-shell-injection", 6, "block", "cli,desktop")
def _(p):
    out = []
    for f, tree in p.py_trees().items():
        for c in ast.walk(tree):
            if not isinstance(c, ast.Call) or not isinstance(c.func, ast.Attribute) or not c.args:
                continue
            owner = ast.unparse(c.func.value)
            shell = any(k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in c.keywords)
            if ((owner == "subprocess" and shell) or (owner == "os" and c.func.attr in ("system", "popen"))) \
                    and not isinstance(c.args[0], ast.Constant):
                out.append((f, c.lineno, "shell command built from a variable"))
    return out


@rule("C03-sql-concatenation", 6, "hold", "cli,desktop")
def _(p):
    # ponytail: flags only SQL text that mixes in a function parameter by name; a value copied through another variable first is missed
    out, seen = [], set()
    for f, tree in p.py_trees().items():
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = {a.arg for a in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs} - {"self", "cls"}
            for c in ast.walk(fn):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in ("execute", "executemany", "executescript", "exec_driver_sql") \
                        and c.args and (f, c.lineno) not in seen:
                    a = c.args[0]
                    dyn = isinstance(a, ast.JoinedStr) or (isinstance(a, ast.BinOp) and isinstance(a.op, (ast.Add, ast.Mod))) \
                        or (isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute) and a.func.attr == "format")
                    if dyn and re.search(r"(?i)\b(select|insert|update|delete|drop|create|alter)\b", ast.unparse(a)) \
                            and any(isinstance(n, ast.Name) and n.id in params for n in ast.walk(a)):
                        seen.add((f, c.lineno))
                        out.append((f, c.lineno, "SQL built from a function argument by string formatting; use parameters"))
    return out


@rule("C04-path-traversal", 6, "hold", "cli,desktop")
def _(p):
    out = []
    for f, fn, d in py_functions(p):
        params = {a.arg for a in fn.args.args + fn.args.kwonlyargs} - {"self", "cls"}
        if not d or not params:
            continue
        src = ast.unparse(fn)
        uses = False
        for c in ast.walk(fn):
            if isinstance(c, ast.Call) and re.search(r"(^|\.)(open|Path|join|read_text|read_bytes|write_text|write_bytes)$", ast.unparse(c.func)):
                if any(isinstance(n, ast.Name) and n.id in params for a in c.args for n in ast.walk(a)):
                    uses = True
        if uses and not re.search(r"resolve\(|realpath|commonpath|is_relative_to|startswith\(|abspath|\.\.", src):
            out.append((f, fn.lineno, f"tool '{fn.name}' opens a path from its arguments without confining it"))
    return out


@rule("C05-eval-exec", 6, "hold", "cli,desktop")
def _(p):
    return [(f, c.lineno, f"{c.func.id}() on a non-literal value") for f, tree in p.py_trees().items() for c in ast.walk(tree)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in ("eval", "exec") and c.args
            and not isinstance(c.args[0], ast.Constant)]


# ---- group 7: data handling -------------------------------------------------------------------------------------
_SS = []


def secretscan():
    if not _SS:
        for d in [HERE] + ([HERE.parents[2] / "scripts"] if len(HERE.parents) > 2 else []):
            if (d / "secretscan.py").is_file():
                sys.path.insert(0, str(d))
                import secretscan as mod
                _SS.append(mod)
                break
        else:
            raise ImportError("secretscan.py not found beside plugin_rules.py or in workbench-core/scripts")
    return _SS[0]


@rule("D01-credential-shape", 7, "block")
def _(p):
    ss = secretscan()
    out = []
    for f in p.text_files():
        for fi in ss.findings(p.text(f)):
            out.append((f, fi["line"], "credential-shaped value " + fi["match"]))
    return out


@rule("D02-denylist", 7, "block")
def _(p):
    terms, out = p.opt.get("denylist") or [], []
    for f in p.text_files():
        for n, ln in enumerate((f + "\n" + p.text(f)).split("\n"), 0):
            for no, rx in terms:
                if rx.search(ln):
                    out.append((f, max(n, 1), f"matches denylist rule {no}"))
    return out[:MAX_PER_RULE]


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
PHONE = re.compile(r"(?<![\d.])(?:\+?\d{1,2}[ .-])?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\d.])")
SSN = re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?![\d-])")


@rule("D03-pii-shape", 7, "warn")
def _(p):
    out = []
    for f in p.text_files():
        if f in (p.manifest_path, MKT) or f.endswith(".lock"):
            continue
        for n, ln in enumerate(p.text(f).split("\n"), 1):
            ln = ln[:4000]                      # a megabyte-long line must not make the regex quadratic
            m = EMAIL.search(ln) if "@" in ln else None
            bad = m and not re.search(r"(?i)(^|\.)(example\.(com|org|net)|localhost)$|\.(example|test|invalid)$", m.group(1))
            if bad or PHONE.search(ln) or SSN.search(ln):
                out.append((f, n, "personal-data shape (address, phone or id number)"))
    return out[:MAX_PER_RULE]


# ---- group 8: licences ------------------------------------------------------------------------------------------
PROPRIETARY = re.compile(r"(?i)all rights reserved|source[- ]available|\bproprietary\b|may not be (copied|redistributed)")
SHARE_ALIKE = re.compile(r"(?i)share[- ]?alike|CC-BY-SA|GNU (Affero )?General Public License|\bAGPL\b|\bGPL-?[23]")


def skill_dirs(p):
    return [s.rsplit("/", 1)[0] if "/" in s else "" for s in p.skills()]


def vendored(p, d):
    pre = d + "/" if d else ""
    return pre + "UPSTREAM.txt" in p.fileset or any(seg in ("vendor", "vendored", "third_party", "third-party") for seg in d.split("/"))


@rule("V01-license-spdx", 8, "warn")
def _(p):
    lic = p.manifest.get("license")
    if isinstance(lic, str) and any(t not in SPDX for t in re.split(r"\s+(?:OR|AND|WITH)\s+|[()]", lic) if t.strip()):
        return [(p.manifest_path, p.line_of(p.manifest_path, '"license"'), f"'{lic}' is not a recognised SPDX identifier")]
    return []


@rule("V02-vendored-without-license", 8, "hold")
def _(p):
    return [((d + "/" if d else "") + "SKILL.md", 1, "vendored skill carries no LICENSE or NOTICE") for d in skill_dirs(p)
            if vendored(p, d) and not license_text_files(p, d)]


@rule("V03-source-available-skill", 8, "block")
def _(p):
    out = []
    for d in skill_dirs(p):
        for f in license_text_files(p, d):
            if LICENSE_RX.match(f.split("/")[-1]) and not f.split("/")[-1].lower().startswith("notice") and PROPRIETARY.search(p.text(f) or ""):
                out.append((f, 1, "skill licence is proprietary or source-available; it cannot be redistributed in this plugin"))
    return out


@rule("V04-share-alike-vendored", 8, "hold")
def _(p):
    permissive = str(p.manifest.get("license") or "MIT") in SPDX and not str(p.manifest.get("license") or "").startswith(("GPL", "AGPL", "LGPL", "CC-BY-SA"))
    return [(f, 1, "share-alike licence on vendored content in a permissive plugin") for d in skill_dirs(p) if vendored(p, d)
            for f in license_text_files(p, d) if permissive and SHARE_ALIKE.search(p.text(f) or "")]


# ---- group 9: supply chain --------------------------------------------------------------------------------------
@rule("S01-claude-validate", 9, "hold", "cli")
def _(p):
    exe = shutil.which("claude")
    if not p.opt.get("validate") or not exe or p.kind not in ("plugin", "marketplace"):
        return []
    with tempfile.TemporaryDirectory() as cfg:
        env = dict(os.environ, CLAUDE_CONFIG_DIR=cfg)
        try:
            r = subprocess.run([exe, "plugin", "validate", str(p.root), "--strict"], capture_output=True, text=True,
                               timeout=60, env=env, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            return [("", 0, f"claude plugin validate did not run: {e}")]
    if r.returncode == 0:
        return []
    return [("", 0, "claude plugin validate --strict failed: " + " | ".join((r.stdout + r.stderr).strip().splitlines()[:3])[:300])]


# ---- running ----------------------------------------------------------------------------------------------------
def run_rules(p, rules=None, target="all"):
    """Findings as dicts, sorted by severity then place. target: cli, desktop, web or all."""
    out = []
    for rid, group, sev, surfaces, fn in (RULES if rules is None else rules):
        if target != "all" and target not in surfaces:
            continue
        try:
            hits = fn(p)
        except Exception as e:                      # a rule that dies on hostile input must not pass silently
            hits = [("", 0, f"rule crashed: {type(e).__name__}: {e}")]
            sev = "hold"
        for f, line, msg in list(hits)[:MAX_PER_RULE]:
            out.append({"rule": rid, "group": group, "file": f, "line": line, "severity": sev, "msg": str(msg)[:240]})
    return sorted(out, key=lambda x: (SEV_ORDER[x["severity"]], x["file"], x["line"], x["rule"]))


def surfaces_of(findings, rules=None):
    """{cli, desktop, web}: False when a block finding comes from a rule that lists that surface."""
    sm = {rid: s for rid, _g, _v, s, _f in (RULES if rules is None else rules)}
    ok = {s: True for s in SURFACES}
    for f in findings:
        if f["severity"] == "block":
            for s in sm.get(f["rule"], ()):
                ok[s] = False
    return ok


def rules_sha256(rules=None, source=None):
    ids = sorted(r[0] for r in (RULES if rules is None else rules))
    src = source if source is not None else Path(__file__).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256("\n".join(ids).encode() + b"\0" + src).hexdigest()


def load_denylist(path):
    """scrub_scan syntax: one term per line, `re:` for a regex, `#` comments. -> [(line_number, compiled)]"""
    terms = []
    for no, ln in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        rx = ln[3:] if ln.startswith("re:") else r"(?<![A-Za-z0-9])" + re.escape(ln) + r"(?![A-Za-z0-9])"
        terms.append((no, re.compile(rx, 0 if ln.startswith("re:") else re.I)))
    return terms
