#!/usr/bin/env python3
"""scaffold.py: create a tested, checkable plugin inside a marketplace repository.

  scaffold.py NAME --kind content|integration|tool-check --surfaces cli|all [--mcp remote|stdio|none] --out REPO
                    [--description TEXT] [--author NAME] [--org-overlay]

Writes REPO/plugins/NAME/ (manifest, one skill, README with a surface table, LICENSE, CHANGELOG, SECURITY, tests, and
the kind's extras: tool-check = exec-form hook plus script, integration = .mcp.json and, for stdio, a stdlib server with three
example tools) and appends the marketplace entry. The first run in a repository also adds tools/check_plugin.py (with
plugin_rules.py and secretscan.py beside it), .github/workflows/plugins.yml and .gitattributes. Never touches user or
managed settings. Refuses reserved names, an existing plugin, and stdio servers for --surfaces all (claude.ai only
connects to remote servers). --org-overlay also writes REPO/org-overlay/ (mirror steps, managed-settings snippet,
coexistence notes). Stdlib only. Exit 0 done, 2 refused.
"""
import argparse
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "templates"
sys.path.insert(0, str(HERE.parent.parent / "plugin-review" / "scripts"))
import plugin_rules as R  # noqa: E402

NAME_RX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RUNS = {
    "content": "Nothing: this plugin only adds a skill, which is text that Claude reads.",
    "tool-check": "A Bash hook, `scripts/check.py`, runs before every Bash tool call. It reads the call, may block a forced git push, and writes a one-word log line to the plugin data folder. It makes no network calls.",
    "stdio": "A local server, `server/server.py`, starts with each session. It keeps an in-memory list and makes no network calls.",
    "remote": "Nothing runs locally for the server: `.mcp.json` points at a remote https URL, and Claude connects to it with your sign-in. Replace the placeholder URL first.",
}


class Refused(Exception):
    pass


def title_of(name):
    return " ".join(w.capitalize() for w in name.split("-"))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def layer(src, dest, tok, written):
    for f in sorted(src.rglob("*.tmpl")):
        rel = f.relative_to(src).as_posix()[: -len(".tmpl")]
        for k, v in tok.items():
            rel = rel.replace(k, v)
        text = f.read_text(encoding="utf-8")
        for k, v in tok.items():
            text = text.replace(k, v)
        left = re.findall(r"__[A-Z][A-Z_]{2,}__", text)
        if left:
            raise Refused(f"template {f.name} left a token unreplaced: {left[0]}")
        write(dest / rel, text)
        written.append(str(dest / rel))


def scaffold(name, kind, surfaces, mcp, out, description=None, author=None, overlay=False):
    """-> list of written paths. Raises Refused."""
    if not NAME_RX.match(name) or len(name) > 64:
        raise Refused("name must be lowercase letters, digits and single hyphens, at most 64 characters")
    if R.reserved_name(name):
        raise Refused(f"'{name}' is a reserved name (claude-, anthropic- and similar prefixes are not allowed)")
    mcp = mcp or ("remote" if kind == "integration" else "none")
    if kind == "integration" and mcp == "none":
        raise Refused("an integration plugin needs --mcp remote or stdio")
    if surfaces == "all" and mcp == "stdio":
        raise Refused("claude.ai only connects to remote servers: use --mcp remote with --surfaces all, or --surfaces cli")
    out = Path(out)
    plugin = out / "plugins" / name
    if plugin.exists():
        raise Refused(f"{plugin} already exists")
    market_file = out / ".claude-plugin" / "marketplace.json"
    market = json.loads(market_file.read_text(encoding="utf-8")) if market_file.is_file() else None
    if market and any(e.get("name") == name for e in market.get("plugins", [])):
        raise Refused(f"the marketplace already lists '{name}'")
    desc = description or f"Describe what {name} does and when Claude should use it."
    if re.search(r"[<>]", desc):
        raise Refused("the description may not contain < or >")
    author = author or "Plugin Author"
    runs = RUNS["tool-check"] if kind == "tool-check" else RUNS[mcp] if mcp != "none" else RUNS["content"]
    if kind == "tool-check" and mcp != "none":
        runs += " " + RUNS[mcp]
    tok = {"__NAME__": name, "__SKILL__": name, "__TITLE__": title_of(name), "__DESCRIPTION__": desc, "__AUTHOR__": author,
           "__YEAR__": str(datetime.date.today().year), "__KIND__": kind, "__SURFACES__": "Claude Code only" if surfaces == "cli" else "every surface",
           "__RUNS_LOCALLY__": runs, "__CLI_FRONTMATTER__\n": 'argument-hint: "[topic]"\n' if surfaces == "cli" else ""}
    written = []
    layer(TEMPLATES / "content", plugin, tok, written)
    if kind == "tool-check":
        layer(TEMPLATES / "tool-check", plugin, tok, written)
    if mcp != "none":
        layer(TEMPLATES / "integration" / mcp, plugin, tok, written)
    manifest = {"name": name, "displayName": title_of(name), "version": "0.1.0", "description": desc, "author": {"name": author},
                "license": "MIT", "keywords": [kind], "metadata": {"surfaces": surfaces}}
    if kind == "tool-check" or mcp == "stdio":
        manifest["userConfig"] = {"python": {"type": "string", "title": "Python interpreter",
                                             "description": "Python 3.10 or newer that runs this plugin's scripts: a name on PATH or an absolute path.",
                                             "default": "python3"}}
    write(plugin / ".claude-plugin" / "plugin.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    written.append(str(plugin / ".claude-plugin" / "plugin.json"))
    # repository-level files, first run only
    if market is None:
        base = re.sub(r"[^a-z0-9]+", "-", out.resolve().name.lower()).strip("-") or "my-plugins"
        market = {"name": base if not R.reserved_name(base) else "my-plugins", "description": "Plugins built with plugin-factory.",
                  "owner": {"name": "Your Organisation"}, "plugins": []}
    market["plugins"].append({"name": name, "source": f"./plugins/{name}", "description": desc, "category": "productivity"})
    write(market_file, json.dumps(market, indent=2, ensure_ascii=False) + "\n")
    tools = out / "tools"
    for f in (HERE / "check_plugin.py", R.HERE / "plugin_rules.py", R.HERE.parents[2] / "scripts" / "secretscan.py"):
        if not (tools / f.name).exists():
            write(tools / f.name, f.read_text(encoding="utf-8"))
            written.append(str(tools / f.name))
    for rel, src in ((".github/workflows/plugins.yml", TEMPLATES / "ci" / "plugins.yml"),):
        if not (out / rel).exists():
            write(out / rel, src.read_text(encoding="utf-8"))
            written.append(str(out / rel))
    for rel, text in ((".gitattributes", "* text=auto eol=lf\n"), (".gitignore", "__pycache__/\n*.pyc\n")):
        if not (out / rel).exists():
            write(out / rel, text)
    if overlay:
        layer(TEMPLATES / "org-overlay", out / "org-overlay", dict(tok, **{"__MARKET__": market["name"]}), written)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name")
    ap.add_argument("--kind", choices=["content", "integration", "tool-check"], required=True)
    ap.add_argument("--surfaces", choices=["cli", "all"], required=True)
    ap.add_argument("--mcp", choices=["remote", "stdio", "none"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--description")
    ap.add_argument("--author")
    ap.add_argument("--org-overlay", action="store_true")
    a = ap.parse_args(argv)
    try:
        written = scaffold(a.name, a.kind, a.surfaces, a.mcp, a.out, a.description, a.author, a.org_overlay)
    except Refused as e:
        print(f"scaffold: refused: {e}", file=sys.stderr)
        return 2
    print(f"created {len(written)} files for {a.name} in {a.out}")
    print(f"next: python {a.out}/tools/check_plugin.py {a.out}/plugins/{a.name} && python -m unittest discover -s {a.out}/plugins/{a.name}/tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
