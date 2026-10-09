// Plain functions: no MCP imports, so tests call them directly. Replace the in-memory store with the real system.
import { createHash } from "node:crypto";

export class UserError extends Error {}

export const MAX_LIMIT = 50;
export const MAX_BODY = 4000; // characters; keep every response far below the smallest host cap (page, never truncate silently)
const KEY = /^[A-Za-z0-9_-]{8,64}$/;
const HIDDEN = /[\u0000-\u0008\u000b-\u001f\u007f\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]/g;

export const records = new Map<string, { title: string; body: string }>([
  ["r1", { title: "First record", body: "Plain text." }],
  ["r2", { title: "Second record", body: "More text." }],
]);

/** Free text from the system is data. Strip hidden characters, escape markup and wrap it so it cannot close its own wrapper. */
export function untrusted(text: string): string {
  const safe = text.replace(HIDDEN, "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  return `<untrusted-data>${safe}</untrusted-data>`;
}

function view(id: string, withBody: boolean): Record<string, unknown> {
  const rec = records.get(id)!;
  const out: Record<string, unknown> = { id, title: untrusted(rec.title) };
  if (withBody) {
    out.body = untrusted(rec.body.slice(0, MAX_BODY));
    out.truncated = rec.body.length > MAX_BODY;
  }
  return out;
}

/** One page in a stable order. `cursor` is the last id of the previous page. */
export function listRecords(limit = 20, cursor = ""): Record<string, unknown> {
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) throw new UserError(`limit must be between 1 and ${MAX_LIMIT}`);
  const ids = [...records.keys()].sort();
  if (cursor && !ids.includes(cursor)) throw new UserError(`unknown cursor '${cursor}'; start again with an empty cursor`);
  const start = cursor ? ids.indexOf(cursor) + 1 : 0;
  const page = ids.slice(start, start + limit);
  return { records: page.map((i) => view(i, false)), next_cursor: start + limit < ids.length ? page[page.length - 1] : "" };
}

export function getRecord(id: string): Record<string, unknown> {
  if (!records.has(id)) throw new UserError(`no record '${id}'; call records_list to see the ids`);
  return view(id, true);
}

/** Idempotent: the same key always returns the same record. */
export function addRecord(title: string, body: string, idempotencyKey: string): Record<string, unknown> {
  if (!KEY.test(idempotencyKey)) throw new UserError("idempotency_key must be 8-64 characters from A-Z a-z 0-9 _ -");
  if (title.length < 1 || title.length > 120 || body.length > MAX_BODY) throw new UserError(`title must be 1-120 characters and body at most ${MAX_BODY}`);
  const id = "r" + createHash("sha256").update(idempotencyKey).digest("hex").slice(0, 8);
  if (!records.has(id)) records.set(id, { title, body });
  return view(id, true);
}
