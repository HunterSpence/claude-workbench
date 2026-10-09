// The one writer of captured files (interface I5): front matter, file name, path rules, run-report entries.
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const FRONT = ['source', 'url', 'title', 'author', 'modified', 'captured_at', 'labels', 'scope'];
const EXTRA = new Set(['thread_id', 'message_ids', 'from', 'to', 'cc', 'received', 'meeting_id', 'organizer', 'attendees', 'start', 'end', 'transcript_source']);
const MAX_PATH = 240;
const MAX_BODY = 2_000_000;

// A stored URL never carries a query string or fragment: sharing links embed tokens there.
export function cleanUrl(u) {
  try {
    const x = new URL(u);
    x.search = '';
    x.hash = '';
    return x.href;
  } catch {
    return String(u).replace(/[?#].*$/s, '');
  }
}

export function slug(s, max = 60) {
  const v = String(s ?? '').normalize('NFKD').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, max).replace(/-+$/g, '');
  return v || 'untitled';
}

export const isoSeconds = (ms) => new Date(ms).toISOString().replace(/\.\d+Z$/, 'Z');

// The exact bytes of one captured file.
export function render(item, source, capturedAt) {
  const fm = { source, url: cleanUrl(item.url), title: String(item.title ?? '').replace(/\s+/g, ' ').trim().slice(0, 300),
    author: item.author ?? null, modified: item.modified ?? null, captured_at: capturedAt, labels: item.labels ?? [], scope: item.scope ?? '' };
  for (const [k, v] of Object.entries(item.extra ?? {})) {
    if (!EXTRA.has(k)) throw new Error(`unknown front matter key: ${k}`);
    fm[k] = v;
  }
  const keys = [...FRONT, ...Object.keys(fm).filter((k) => !FRONT.includes(k))];
  const body = String(item.body ?? '').slice(0, MAX_BODY).trim();
  return `---\n${keys.map((k) => `${k}: ${JSON.stringify(fm[k])}`).join('\n')}\n---\n\n${body}\n`;
}

// <base>/<source>/<scope-slug>/<YYYY-MM-DD>-<title-slug>-<8 hex of sha1(url)>.md, whole path <= 240 characters.
export function targetPath(base, source, item, capturedAt) {
  const hash = createHash('sha1').update(cleanUrl(item.url)).digest('hex').slice(0, 8);
  const dir = path.posix.join(String(base).replaceAll('\\', '/'), source, slug(item.scope));
  const fixed = path.posix.join(dir, `${capturedAt.slice(0, 10)}--${hash}.md`).length;
  const room = Math.max(1, Math.min(60, MAX_PATH - fixed));
  const file = `${capturedAt.slice(0, 10)}-${slug(item.title || path.basename(new URL(cleanUrl(item.url), 'x:/').pathname), room)}-${hash}.md`;
  const full = path.posix.join(dir, file);
  if (full.length > MAX_PATH) throw new Error(`captured path would be ${full.length} characters (limit ${MAX_PATH}); use a shorter data folder`);
  return { dir, full, hash };
}

export function createWriter({ base, source, clock, retentionDays = 90, dry = false }) {
  return {
    // Returns the run-report entry {url, path, sha256, expires}. A newer capture of the same URL replaces the older file.
    write(item) {
      const capturedAt = isoSeconds(clock.now());
      const text = render(item, source, capturedAt);
      const { dir, full, hash } = targetPath(base, source, item, capturedAt);
      const entry = { url: cleanUrl(item.url), path: full, sha256: createHash('sha256').update(text, 'utf8').digest('hex'),
        expires: isoSeconds(clock.now() + retentionDays * 86_400_000) };
      if (dry) return entry;
      fs.mkdirSync(dir, { recursive: true });
      for (const f of fs.readdirSync(dir)) if (f.endsWith(`-${hash}.md`) && path.posix.join(dir, f) !== full) fs.rmSync(path.posix.join(dir, f));
      const tmp = `${full}.tmp`;
      fs.writeFileSync(tmp, text, 'utf8');
      fs.renameSync(tmp, full);
      return entry;
    },
  };
}

// Front matter of an existing file as {key: value}, or null.
export function readFrontMatter(file) {
  const t = fs.readFileSync(file, 'utf8').split('\n');
  if (t[0].trim() !== '---') return null;
  const end = t.findIndex((l, i) => i > 0 && l.trim() === '---');
  const out = {};
  for (const l of t.slice(1, end < 0 ? 0 : end)) {
    const m = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(l.replace(/\r$/, ''));
    if (m) { try { out[m[1]] = JSON.parse(m[2]); } catch { out[m[1]] = m[2]; } }
  }
  return end < 0 ? null : out;
}

// purge: remove captured files of one source older than `days` (by captured_at), never a file this tool did not write.
export function purgeSource(base, source, days, nowMs) {
  const root = path.join(base, source);
  let removed = 0;
  let kept = 0;
  const walk = (d) => {
    for (const e of fs.existsSync(d) ? fs.readdirSync(d, { withFileTypes: true }) : []) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) { walk(p); if (!fs.readdirSync(p).length) fs.rmdirSync(p); continue; }
      if (!e.name.endsWith('.md')) continue;
      const fm = readFrontMatter(p);
      if (!fm || fm.source !== source || !fm.captured_at) { kept++; continue; }
      const at = Date.parse(fm.captured_at);
      if (days == null || (Number.isFinite(at) && nowMs - at > days * 86_400_000)) { fs.rmSync(p); removed++; } else kept++;
    }
  };
  walk(root);
  return { source, removed, kept };
}
