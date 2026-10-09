// scope.json: what may be captured (scope), what never may (deny), and a few settings. User-owned, never in the kit.
import fs from 'node:fs';
import path from 'node:path';

const SETTINGS = { tenant: 'string', retention_days: 'number', sync_root: 'string', max_depth: 'number', max_pages: 'number', max_files: 'number' };
const NAME = /^[a-z][a-z0-9-]{0,30}$/;

export const emptyScope = () => ({ version: 1, tenant: '', retention_days: 90, placement: {}, scope: {}, deny: {} });

export function load(file) {
  if (!fs.existsSync(file)) return emptyScope();
  const s = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^﻿/, ''));
  const out = { ...emptyScope(), ...s };
  for (const k of ['scope', 'deny', 'placement']) out[k] = s[k] && typeof s[k] === 'object' && !Array.isArray(s[k]) ? s[k] : {};
  return out;
}

export function save(file, s) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(s, null, 2)}\n`, 'utf8');
  fs.renameSync(tmp, file);
}

// A URL entry is stored without query string and fragment; anything else (a folder, a channel name) is kept as typed.
export function normalise(value) {
  const v = String(value).trim();
  if (!v) throw new Error('empty value');
  if (!/^https?:\/\//i.test(v)) return v;
  const u = new URL(v);
  if (u.protocol === 'http:' && u.hostname !== 'localhost') throw new Error('only https URLs (or http://localhost) can be listed');
  u.search = '';
  u.hash = '';
  return u.href;
}

export function add(s, source, value, deny = false) {
  if (!NAME.test(source ?? '')) throw new Error('--source NAME is required (lower-case letters, digits, hyphen)');
  const list = ((deny ? s.deny : s.scope)[source] ??= []);
  const v = normalise(value);
  if (!list.includes(v)) list.push(v);
  return v;
}

export function remove(s, source, value, deny = false) {
  const book = deny ? s.deny : s.scope;
  const v = normalise(value);
  const had = (book[source] ?? []).includes(v);
  book[source] = (book[source] ?? []).filter((x) => x !== v);
  if (!book[source].length) delete book[source];
  return had;
}

export function set(s, key, value) {
  const m = /^placement\.([a-z][a-z0-9-]*)$/.exec(key);
  if (m) {
    if (!['local', 'data'].includes(value)) throw new Error('placement is "local" or "data"');
    s.placement[m[1]] = value;
    return;
  }
  const kind = SETTINGS[key];
  if (!kind) throw new Error(`unknown setting ${key} (use ${Object.keys(SETTINGS).join(', ')}, placement.<source>)`);
  s[key] = kind === 'number' ? Number(value) : String(value);
  if (kind === 'number' && !(s[key] > 0)) throw new Error(`${key} must be a positive number`);
}

export const entries = (s, source) => [...(s.scope[source] ?? [])];
export const denies = (s, source) => [...(s.deny[source] ?? [])];

// Deny is conservative: any deny entry that appears inside the key (case-insensitive) blocks it.
export const isDenied = (s, source, key) => denies(s, source).some((d) => String(key).toLowerCase().includes(d.toLowerCase()));

// Hosts (host:port) the browser may navigate to: exactly those of the URL entries in this source's scope.
export function hosts(s, source) {
  const out = new Set();
  for (const e of entries(s, source)) if (/^https?:\/\//i.test(e)) out.add(new URL(e).host);
  return out;
}
