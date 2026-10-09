#!/usr/bin/env python3
"""openapi_draft.py: print a DRAFT worksheet (JSON) with one candidate tool per operation, for reference only.

  python openapi_draft.py openapi.json [--out draft.json]

A mirror of the API is the wrong product: models pick tools better from a few workflow-shaped ones. Use the draft to see
names, parameters and modes, then hand-write the curated worksheet (merge chatty reads, drop the rest, flip a write on
deliberately). The draft carries `_draft`, which the bridge refuses until it is removed; reads default to keep, writes to
drop. Stdlib only.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from openapi_inventory import inventory, load  # noqa: E402

TYPE = {"integer": "integer", "number": "number", "boolean": "boolean"}


def snake(text):
    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text).lower()).strip("_")


def draft(spec):
    tools, seen = [], set()
    for op in inventory(spec):
        name = snake(op["operation_id"] or f"{op['method']}_{op['path']}")[:64] or "op"
        while name in seen:
            name = name[:60] + "_x"
        seen.add(name)
        write = op["method"] not in ("GET", "HEAD")
        params = []
        for p in op["params"]:
            pname, where = p.rstrip("*").split(":")
            if where in ("path", "query"):
                entry = {"name": pname, "in": where, "type": "string", "required": p.endswith("*") or where == "path", "description": ""}
                if not entry["required"]:
                    entry["default"] = ""
                params.append(entry)
        params += [{"name": b, "in": "body", "type": "string", "required": False, "default": "", "description": ""} for b in op["body"]]
        tools.append({"name": name, "title": op["summary"] or name, "description": "TODO: what it does and when to call it",
                      "operations": [f"{op['method']} {op['path']}"], "mode": "write" if write else "read", "keep": not write,
                      **({"destructive": op["method"] == "DELETE", "idempotency_header": "Idempotency-Key"} if write else {}),
                      "params": params, "max_bytes": 20000})
    return {"version": 1, "_draft": "reference only: curate before use", "service": "example", "tools": tools}


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    try:
        out = json.dumps(draft(load(argv[1])), indent=2)
    except (OSError, ValueError) as e:
        print(f"openapi_draft: {e}", file=sys.stderr)
        return 2
    if "--out" in argv:
        with open(argv[argv.index("--out") + 1], "w", encoding="utf-8", newline="\n") as f:
            f.write(out + "\n")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
