"""Schema hygiene. Some MCP clients reject $ref / anyOf / oneOf / allOf / const, so publish flat schemas."""
FORBIDDEN = ("$ref", "anyOf", "oneOf", "allOf", "const")


def find_forbidden(schema, path="$"):
    """Paths of forbidden keywords in a JSON schema (empty list = portable)."""
    out = []
    if isinstance(schema, dict):
        for k, v in schema.items():
            if k in FORBIDDEN:
                out.append(f"{path}.{k}")
            out += find_forbidden(v, f"{path}.{k}")
    elif isinstance(schema, list):
        for i, v in enumerate(schema):
            out += find_forbidden(v, f"{path}[{i}]")
    return out


def lower(schema, defs=None):
    """Inline $ref, turn `X | null` into X and `const` into a one-value enum. Idempotent; leaves other keywords alone."""
    defs = schema.get("$defs", {}) if defs is None and isinstance(schema, dict) else (defs or {})
    if isinstance(schema, list):
        return [lower(v, defs) for v in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        return lower({**defs[schema["$ref"].rsplit("/", 1)[-1]], **{k: v for k, v in schema.items() if k != "$ref"}}, defs)
    for key in ("anyOf", "oneOf"):
        rest = [v for v in schema.get(key, []) if v != {"type": "null"}]
        if key in schema and len(rest) == 1:
            return lower({**{k: v for k, v in schema.items() if k != key}, **rest[0]}, defs)
    out = {k: lower(v, defs) for k, v in schema.items() if k != "$defs"}
    if "const" in out:
        out["enum"] = [out.pop("const")]
    return out
