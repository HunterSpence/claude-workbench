// Schema hygiene. Some MCP clients reject $ref / anyOf / oneOf / allOf / const, so publish flat schemas.
type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const FORBIDDEN = ["$ref", "anyOf", "oneOf", "allOf", "const"];

/** Paths of forbidden keywords in a JSON schema (empty list = portable). */
export function findForbidden(schema: unknown, path = "$"): string[] {
  const out: string[] = [];
  if (Array.isArray(schema)) schema.forEach((v, i) => out.push(...findForbidden(v, `${path}[${i}]`)));
  else if (schema && typeof schema === "object") {
    for (const [k, v] of Object.entries(schema)) {
      if (FORBIDDEN.includes(k)) out.push(`${path}.${k}`);
      out.push(...findForbidden(v, `${path}.${k}`));
    }
  }
  return out;
}

/** Inline $ref, turn `X | null` into X and `const` into a one-value enum. Idempotent. */
export function lower(schema: unknown, defs?: Json): unknown {
  if (Array.isArray(schema)) return schema.map((v) => lower(v, defs));
  if (!schema || typeof schema !== "object") return schema;
  const s = schema as Json;
  const d = defs ?? s.$defs ?? {};
  if (s.$ref) {
    const { $ref, ...siblings } = s;
    return lower({ ...d[$ref.split("/").pop()], ...siblings }, d);
  }
  for (const key of ["anyOf", "oneOf"]) {
    const rest = (s[key] ?? []).filter((v: Json) => v?.type !== "null" || Object.keys(v).length !== 1);
    if (s[key] && rest.length === 1) {
      const { [key]: _drop, ...others } = s;
      return lower({ ...others, ...rest[0] }, d);
    }
  }
  const out: Json = {};
  for (const [k, v] of Object.entries(s)) if (k !== "$defs") out[k] = lower(v, d);
  if ("const" in out) {
    out.enum = [out.const];
    delete out.const;
  }
  return out;
}
