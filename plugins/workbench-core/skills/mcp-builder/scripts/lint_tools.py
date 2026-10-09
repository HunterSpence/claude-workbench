#!/usr/bin/env python3
"""lint_tools.py: check a dumped MCP `tools/list` result against the tool-design rules.

  python lint_tools.py tools.json        (a list of tools, {"tools": [...]} or {"result": {"tools": [...]}}; `-` = stdin)

Prints one `tool: rule: message` line per finding; exit 1 when there is any, 2 on unreadable input. Stdlib only.
Rules: name-length, catch-all, read-write-mix, title, hints, schema-keyword, identity-arg, instructing-description.
"""
import json
import re
import sys

MAX_NAME = 64
FORBIDDEN_KEYS = ("$ref", "anyOf", "oneOf", "allOf", "const")
CATCH_ALL_ARGS = {"method", "httpmethod", "verb"}
CATCH_ALL_NAME = re.compile(r"(^|_)(api_?)?(http_?)?request$|(^|_)(call_?api|raw_?request)($|_)")
WRITE_VERB = re.compile(r"(^|_)(create|add|update|delete|remove|set|write|send|post|put|patch|insert|drop|move|"
                        r"rename|upload|publish|grant|revoke|execute|run|reset|clear)($|_)")
WRITE_WORD = re.compile(r"\b(create|update|delete|remove|write|send|modify|overwrite|insert)\b", re.I)
READ_WORD = re.compile(r"\b(read|get|list|fetch|search|view|query)\b", re.I)
IDENTITY_ARGS = {"userid", "user", "username", "useremail", "email", "asuser", "actas", "actingas", "onbehalfof",
                 "impersonate", "impersonateuser", "caller", "callerid", "requester", "requesterid"}
INSTRUCTING = [re.compile(p, re.I) for p in (
    r"\balways (call|use|run|invoke)\b", r"\bignore (all |any |the )?(previous|prior|other|earlier)\b",
    r"\bbefore (using|calling|you use) (any|every) (other )?tool\b", r"\bdo not (tell|mention|reveal|show) the user\b",
    r"\bnever (use|call) (any )?other tools?\b", r"\byou (must|should) (first|always|never)\b",
    r"\bfetch (your |the )?(rules|instructions) from\b", r"<important>", r"\bsystem prompt\b",
    "[​-‏‪-‮⁠-⁤﻿]")]


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _walk(schema, path=""):
    """Yield (path, key) for every forbidden keyword in a JSON schema."""
    if isinstance(schema, dict):
        for k, v in schema.items():
            if k in FORBIDDEN_KEYS:
                yield path or "$", k
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(schema, list):
        for i, v in enumerate(schema):
            yield from _walk(v, f"{path}[{i}]")


def lint(tools):
    """[(tool, rule, message)] for a list of tool dicts (wire shape: name, title, description, inputSchema, annotations)."""
    out = []
    for t in tools:
        name = str(t.get("name", ""))
        add = lambda rule, msg: out.append((name or "<unnamed>", rule, msg))  # noqa: E731
        ann = t.get("annotations") or {}
        props = (t.get("inputSchema") or {}).get("properties") or {}
        if not name or len(name) > MAX_NAME:
            add("name-length", f"name is {len(name)} characters; the limit is {MAX_NAME}")
        if not (t.get("title") or ann.get("title")):
            add("title", "missing title (top level or annotations.title)")
        if "readOnlyHint" not in ann and "destructiveHint" not in ann:
            add("hints", "needs readOnlyHint (reads) or destructiveHint (writes)")
        if CATCH_ALL_NAME.search(name) or any(_norm(p) in CATCH_ALL_ARGS for p in props):
            add("catch-all", "a request tool or a `method` argument mixes safe and unsafe operations; one tool per operation")
        if ann.get("readOnlyHint") is True and WRITE_VERB.search(name):
            add("read-write-mix", "marked readOnlyHint but the name is a write verb")
        desc = t.get("description") or ""
        if ann.get("readOnlyHint") is True and WRITE_WORD.search(desc) and not re.search(r"\b(never|not|no) (write|modif|creat|updat|delet)", desc, re.I):
            add("read-write-mix", "marked readOnlyHint but the description talks about writing")
        elif ann.get("readOnlyHint") is not True and WRITE_WORD.search(desc) and READ_WORD.search(desc) and "destructiveHint" not in ann:
            add("read-write-mix", "description both reads and writes and carries no destructiveHint; split the tool")
        for p, spec in props.items():
            vals = {str(v).lower() for v in (spec.get("enum") or [])} if isinstance(spec, dict) else set()
            if _norm(p) in {"action", "operation", "mode"} and vals & {"get", "list", "read"} and vals & {"post", "put", "delete", "create", "update", "write"}:
                add("read-write-mix", f"argument `{p}` selects between read and write behaviour; split the tool")
            if _norm(p) in IDENTITY_ARGS:
                add("identity-arg", f"argument `{p}` carries caller identity; derive it from the credential instead")
        for schema_key in ("inputSchema", "outputSchema"):
            for path, key in _walk(t.get(schema_key) or {}):
                add("schema-keyword", f"{schema_key} uses `{key}` at {path}; publish flat schemas")
        if any(rx.search(desc) for rx in INSTRUCTING):
            add("instructing-description", "the description tells the model how to behave; describe what the tool does and when to call it")
    return out


def load(text):
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("tools", (data.get("result") or {}).get("tools"))
    if not isinstance(data, list):
        raise ValueError("no tools list found")
    return data


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    try:
        tools = load(sys.stdin.read() if argv[1] == "-" else open(argv[1], encoding="utf-8").read())
    except (OSError, ValueError) as e:
        print(f"lint_tools: {e}", file=sys.stderr)
        return 2
    found = lint(tools)
    for tool, rule, msg in found:
        print(f"{tool}: {rule}: {msg}")
    print(f"{len(tools)} tools, {len(found)} findings")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
