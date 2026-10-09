#!/usr/bin/env python3
"""openapi_inventory.py: list every operation of an OpenAPI 3 document: method, path, parameters, auth, size hints.

  python openapi_inventory.py openapi.json [--json]

The inventory is the first step of curation (see templates/worksheet.md): it shows what the API offers, not what a model
should be given. JSON documents only, plus YAML when PyYAML is installed. Stdlib otherwise.
"""
import json
import sys

METHODS = ("get", "head", "post", "put", "patch", "delete")


def load(path):
    text = open(path, encoding="utf-8").read()
    if path.lower().endswith((".yaml", ".yml")):
        try:
            import yaml
        except ImportError:
            raise SystemExit("YAML needs PyYAML (pip install pyyaml); or convert the document to JSON")
        return yaml.safe_load(text)
    return json.loads(text)


def resolve(spec, node, depth=0):
    """Follow local $ref pointers (a remote $ref is left as is)."""
    while isinstance(node, dict) and "$ref" in node and node["$ref"].startswith("#/") and depth < 20:
        target = spec
        for part in node["$ref"][2:].split("/"):
            target = target.get(part.replace("~1", "/").replace("~0", "~"), {}) if isinstance(target, dict) else {}
        node, depth = target, depth + 1
    return node


def size_hint(spec, op):
    """Rough response size: number of top-level properties of the first 2xx JSON schema, and whether it is a list."""
    for code, resp in (op.get("responses") or {}).items():
        if str(code).startswith("2"):
            schema = resolve(spec, (((resolve(spec, resp).get("content") or {}).get("application/json") or {}).get("schema")) or {})
            if schema.get("type") == "array":
                return {"list": True, "properties": len(resolve(spec, schema.get("items", {})).get("properties", {}))}
            props = schema.get("properties", {})
            return {"list": any(resolve(spec, p).get("type") == "array" for p in props.values()), "properties": len(props)}
    return {"list": False, "properties": 0}


def inventory(spec):
    """[{method, path, operation_id, summary, params, body, auth, deprecated, size}] in document order."""
    if "openapi" not in spec:
        raise ValueError("not an OpenAPI 3 document (no `openapi` key)")
    default_security = spec.get("security", [])
    out = []
    for path, item in (spec.get("paths") or {}).items():
        item = resolve(spec, item)
        for method in METHODS:
            op = item.get(method)
            if not op:
                continue
            params = [resolve(spec, p) for p in item.get("parameters", []) + op.get("parameters", [])]
            body = resolve(spec, (resolve(spec, op.get("requestBody", {})).get("content") or {}).get("application/json", {}).get("schema", {}))
            schemes = sorted({k for req in op.get("security", default_security) for k in req})
            out.append({"method": method.upper(), "path": path, "operation_id": op.get("operationId", ""), "summary": op.get("summary", ""),
                        "params": [f"{p.get('name')}:{p.get('in')}{'*' if p.get('required') else ''}" for p in params],
                        "body": sorted((body.get("properties") or {}).keys()), "auth": schemes or ["none"],
                        "deprecated": bool(op.get("deprecated")), "size": size_hint(spec, op)})
    return out


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    try:
        rows = inventory(load(argv[1]))
    except (OSError, ValueError) as e:
        print(f"openapi_inventory: {e}", file=sys.stderr)
        return 2
    if "--json" in argv:
        print(json.dumps(rows, indent=2))
        return 0
    print("| method | path | operationId | params (* = required) | body fields | auth | response |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        size = f"{'list of ' if r['size']['list'] else ''}{r['size']['properties']} fields"
        print(f"| {r['method']} | `{r['path']}` | {r['operation_id']} | {', '.join(r['params']) or '-'} | {', '.join(r['body']) or '-'} | "
              f"{', '.join(r['auth'])} | {size}{' (deprecated)' if r['deprecated'] else ''} |")
    print(f"\n{len(rows)} operations ({sum(r['method'] in ('GET', 'HEAD') for r in rows)} reads, "
          f"{sum(r['method'] not in ('GET', 'HEAD') for r in rows)} writes). Curate to 5-15 workflow tools.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
