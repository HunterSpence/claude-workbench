#!/usr/bin/env python3
"""worksheet.py: the curation worksheet and the checks that decide whether a bridge may start.

  python worksheet.py worksheet.json [--spec openapi.json]      exit 0 = acceptable, 1 = refused (reasons on stdout)

The worksheet is the contract between curator and bridge: only the tools listed here exist. check() refuses a
catch-all request tool, a tool that mixes reads and writes, a caller-identity argument, a header or credential
parameter, a worksheet that forwards the caller's token or takes identity from a header, and unreviewed draft output.
Stdlib only.
"""
import json
import re
import sys

MAX_TOOLS = 15
NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
OPERATION = re.compile(r"(GET|HEAD|POST|PUT|PATCH|DELETE) (/[A-Za-z0-9_.~/-]*(\{[a-z][a-z0-9_]*\}[A-Za-z0-9_.~/-]*)*)")
TYPES = {"string", "integer", "number", "boolean"}
CATCH_ALL_PARAMS = {"method", "httpmethod", "verb", "path", "url", "uri", "endpoint", "route"}
CREDENTIAL_PARAMS = {"authorization", "token", "accesstoken", "apikey", "xapikey", "cookie", "secret", "password", "bearer"}
IDENTITY_PARAMS = {"userid", "user", "username", "email", "useremail", "asuser", "onbehalfof", "impersonate", "caller", "requester"}
INSTRUCTING = re.compile(r"\b(always call|ignore (all |any )?(previous|prior|other)|do not (tell|mention) the user|"
                         r"before (using|calling) any other tool|you must (first|always))\b", re.I)


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def kept(ws):
    return [t for t in ws.get("tools", []) if t.get("keep", True)]


def spec_operations(spec):
    """{(METHOD, path): {param names by location}} for an OpenAPI 3 document."""
    out = {}
    for path, item in (spec.get("paths") or {}).items():
        shared = item.get("parameters", [])
        for method, op in item.items():
            if method.upper() in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}:
                out[(method.upper(), path)] = {p.get("name") for p in shared + op.get("parameters", []) if p.get("in") == "path"}
    return out


def check(ws, spec=None):
    """List of reasons this worksheet must not run (empty = acceptable)."""
    errs = []
    if not isinstance(ws, dict) or ws.get("version") != 1 or not isinstance(ws.get("tools"), list):
        return ["worksheet must be an object with version 1 and a tools list"]
    if "_draft" in ws:
        errs.append("this is draft generator output (reference only): curate it into 5-15 workflow tools, then remove `_draft`")
    if "identity_header" in ws:
        errs.append("identity must come from an authenticated credential, never from an unsigned header (`identity_header`)")
    tools = kept(ws)
    if not 1 <= len(tools) <= MAX_TOOLS:
        errs.append(f"{len(tools)} kept tools; keep between 1 and {MAX_TOOLS} workflow tools (merge or drop the rest)")
    ops = spec_operations(spec) if spec else None
    seen = set()
    for t in tools:
        n = t.get("name", "")
        add = lambda msg, n=n: errs.append(f"{n or '<unnamed>'}: {msg}")  # noqa: E731
        if not NAME.fullmatch(n):
            add("name must be lowercase letters, digits and underscores, starting with a letter, at most 64 characters")
        if n in seen:
            add("duplicate name")
        seen.add(n)
        if not t.get("title") or not t.get("description"):
            add("needs a title and a description of what it does and when to call it")
        if INSTRUCTING.search(t.get("description", "")):
            add("the description tells the model how to behave; describe the tool instead")
        if t.get("forward_token") or t.get("auth", "service") != "service":
            add("must not forward the caller's token upstream; the bridge uses its own service credential")
        mode, operations = t.get("mode"), t.get("operations")
        if mode not in ("read", "write"):
            add("mode must be read or write")
        if not isinstance(operations, list) or not operations or not all(isinstance(o, str) for o in operations):
            add("operations must be a list of literal `METHOD /path` strings")
            continue
        methods = set()
        for o in operations:
            m = OPERATION.fullmatch(o)
            if not m:
                add(f"operation {o!r} is not a literal `METHOD /path` (a catch-all `api_request(method, path)` is refused)")
                continue
            methods.add(m[1])
            placeholders = set(re.findall(r"\{([a-z0-9_]+)\}", m[2]))
            declared = {p.get("name") for p in t.get("params", []) if p.get("in") == "path"}
            if placeholders != declared:
                add(f"path placeholders {sorted(placeholders)} of {o!r} must match the `in: path` params {sorted(declared)}")
            if ops is not None and (m[1], m[2]) not in ops:
                add(f"{o} is not in the OpenAPI document")
        if mode == "read" and methods - {"GET", "HEAD"}:
            add("a read tool may only use GET or HEAD")
        if mode == "write":
            if len(operations) != 1 or methods <= {"GET", "HEAD"}:
                add("a write tool is exactly one POST, PUT, PATCH or DELETE operation (never mixed with reads)")
            if not isinstance(t.get("destructive"), bool):
                add("write tools must say `destructive: true|false`")
            if not t.get("idempotency_header") and t.get("idempotent") is not True:
                add("write tools need `idempotency_header` (the bridge adds an idempotency_key argument) or `idempotent: true`")
        for p in t.get("params", []):
            pn, where = p.get("name", ""), p.get("in")
            if where not in ("path", "query", "body"):
                add(f"param {pn!r}: `in` must be path, query or body (headers and cookies come from the environment contract)")
            if p.get("type") not in TYPES:
                add(f"param {pn!r}: type must be one of {sorted(TYPES)}")
            if not p.get("required") and "default" not in p:
                add(f"param {pn!r}: optional params need a `default` (no null unions in published schemas)")
            if _norm(pn) in CATCH_ALL_PARAMS:
                add(f"param {pn!r} looks like a catch-all request argument; expose one operation per tool")
            if _norm(pn) in CREDENTIAL_PARAMS:
                add(f"param {pn!r} would carry a credential; credentials come from the environment contract")
            if _norm(pn) in IDENTITY_PARAMS:
                add(f"param {pn!r} carries caller identity; rename the model-facing name (and set `upstream_name`) or derive it from the credential")
        if not isinstance(t.get("max_bytes", 20000), int) or not 1000 <= t.get("max_bytes", 20000) <= 150000:
            add("max_bytes must be an integer from 1000 to 150000")
    return errs


def main(argv):
    if len(argv) < 2 or argv[1].startswith("-"):
        print(__doc__)
        return 2
    spec = None
    if "--spec" in argv:
        spec = json.load(open(argv[argv.index("--spec") + 1], encoding="utf-8"))
    errs = check(json.load(open(argv[1], encoding="utf-8")), spec)
    for e in errs:
        print(e)
    print("worksheet refused" if errs else "worksheet ok")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
