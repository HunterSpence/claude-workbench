import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';
import { cleanUrl, createWriter, readFrontMatter, slug } from '../skills/capture/scripts/writer.mjs';

const GOLD = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'site', 'golden');
const AT = Date.UTC(2025, 5, 7, 8, 9, 10); // 2025-06-07T08:09:10Z
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'wbcap-w-'));
const clock = (t = AT) => ({ now: () => t });

describe('writer (interface I5)', () => {
  const item = { url: 'https://wiki.example.com/docs/guide?token=abc#intro', title: 'Room booking guide', author: 'Pat Example', modified: '2025-03-04T10:00:00Z',
    labels: [], scope: 'site:wiki.example.com/path:/docs/', body: '# Room booking guide\n\nBook a room in the calendar.\n' };

  it('matches the golden file byte for byte, with the query and fragment stripped', () => {
    const base = tmp();
    const e = createWriter({ base, source: 'intranet', clock: clock() }).write(item);
    assert.equal(e.path, `${base.replaceAll('\\', '/')}/intranet/site-wiki-example-com-path-docs/2025-06-07-room-booking-guide-c8c0add1.md`);
    const got = fs.readFileSync(e.path);
    assert.deepEqual(got, fs.readFileSync(path.join(GOLD, 'item.md')));
    assert.equal(e.url, 'https://wiki.example.com/docs/guide');
    assert.ok(!got.toString().includes('token'), 'no query string anywhere');
    assert.equal(e.sha256, createHash('sha256').update(got).digest('hex'));
    assert.equal(e.expires, '2025-09-05T08:09:10Z', 'captured_at + 90 days');
  });

  it('writes the mail keys after the eight fixed keys, in the order given', () => {
    const base = tmp();
    const e = createWriter({ base, source: 'outlook', clock: clock() }).write({ url: 'outlook-thread:0f1e2d3c', title: 'Quarterly room plan', labels: [], scope: 'folder:Inbox', body: 'Hello team.',
      extra: { thread_id: 't1', message_ids: ['m1', 'm2'], from: 'a@example.com', to: ['b@example.com'], cc: [], received: '2025-06-06T07:08:09Z' } });
    assert.deepEqual(fs.readFileSync(e.path), fs.readFileSync(path.join(GOLD, 'mail.md')));
    assert.throws(() => createWriter({ base, source: 'outlook', clock: clock() }).write({ ...item, extra: { password: 'x' } }), /unknown front matter key/);
  });

  it('keeps slugs to [a-z0-9-] and the whole path to 240 characters', () => {
    assert.match(slug('Ünïcode  Title!! with / odd * chars'), /^[a-z0-9-]{1,60}$/);
    assert.equal(slug('***'), 'untitled');
    const base = path.join(tmp(), 'x'.repeat(60));
    const e = createWriter({ base, source: 'intranet', clock: clock() }).write({ ...item, title: 'T'.repeat(300), scope: 'S'.repeat(300) });
    assert.ok(e.path.length <= 240, `${e.path.length}`);
    const name = path.posix.basename(e.path);
    assert.match(name, /^\d{4}-\d\d-\d\d-[a-z0-9-]{1,60}-[0-9a-f]{8}\.md$/);
    assert.ok(path.posix.basename(path.posix.dirname(e.path)).length <= 60);
    assert.throws(() => createWriter({ base: 'C:/' + 'y'.repeat(230), source: 'intranet', clock: clock() }).write(item), /240/);
  });

  it('a newer capture of the same URL replaces the older file; a dry run writes nothing', () => {
    const base = tmp();
    const a = createWriter({ base, source: 'intranet', clock: clock(AT) }).write(item);
    const b = createWriter({ base, source: 'intranet', clock: clock(AT + 3 * 86_400_000) }).write(item);
    assert.notEqual(a.path, b.path);
    assert.ok(!fs.existsSync(a.path) && fs.existsSync(b.path));
    assert.equal(fs.readdirSync(path.dirname(b.path)).length, 1);
    const dry = tmp();
    const d = createWriter({ base: dry, source: 'intranet', clock: clock(), dry: true }).write(item);
    assert.ok(d.sha256 && !fs.existsSync(d.path));
  });

  it('reads its own front matter back', () => {
    const e = createWriter({ base: tmp(), source: 'intranet', clock: clock() }).write(item);
    const fm = readFrontMatter(e.path);
    assert.equal(fm.source, 'intranet');
    assert.equal(fm.captured_at, '2025-06-07T08:09:10Z');
    assert.deepEqual(fm.labels, []);
    assert.equal(fm.author, 'Pat Example');
  });

  it('cleanUrl drops query and fragment and leaves non-URL strings usable', () => {
    assert.equal(cleanUrl('https://a.example.com/x/y?z=1#f'), 'https://a.example.com/x/y');
    assert.equal(cleanUrl('sync-folder:Reports/plan.md'), 'sync-folder:Reports/plan.md');
    assert.equal(cleanUrl('weird?token=1'), 'weird');
  });
});
