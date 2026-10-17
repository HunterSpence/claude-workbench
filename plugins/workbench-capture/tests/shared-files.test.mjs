import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it } from 'node:test';
import { main } from '../skills/capture/scripts/capture.mjs';
import { fakeClock, findCli, knowledgePython, REQUIRE, runCapture, tempHome, walkMd } from './fixtures/site/env.mjs';

const py = knowledgePython();
const PY_LABEL = `
import sys, zipfile
ns = 'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"'
prop = '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="MSIP_Label_0a1b2c3d-0000-0000-0000-000000000001_Name"><vt:lpwstr>Confidential</vt:lpwstr></property>'
with zipfile.ZipFile(sys.argv[1], "w") as z:
    z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    z.writestr("docProps/custom.xml", "<Properties " + ns + ">" + prop + "</Properties>")
    z.writestr("word/document.xml", "<w:document/>")
`;

function syncFolder() {
  const wb = tempHome();
  const sync = `${wb}/OneDrive`;
  fs.mkdirSync(`${sync}/Reports`, { recursive: true });
  fs.mkdirSync(`${sync}/Reports/Archive`, { recursive: true });
  fs.writeFileSync(`${sync}/Reports/plan.md`, '# Plan\n\nThe pelican rollout plan has three phases.\n');
  fs.writeFileSync(`${sync}/Reports/budget.txt`, 'The heron budget notes list two items.\n');
  fs.writeFileSync(`${sync}/Reports/unlisted.md`, 'The ibis unlisted note must never be read.\n');
  fs.writeFileSync(`${sync}/Reports/internal.md`, '---\nsource: "x"\ncaptured_at: "2025-01-01T00:00:00Z"\nlabels: ["Internal"]\n---\n\nThe osprey internal note.\n');
  fs.writeFileSync(`${sync}/Reports/Archive/old.md`, 'The kiwi archive note.\n');
  const r = spawnSync(py, ['-c', PY_LABEL, `${sync}/Reports/labelled.docx`]);
  assert.equal(r.status, 0, String(r.stderr));
  return { wb, sync };
}
const scopeFile = (wb, sync, entries, extra = {}) => {
  const f = `${wb}/scope.json`;
  fs.writeFileSync(f, JSON.stringify({ version: 1, sync_root: sync, scope: { 'shared-files': entries }, deny: {}, placement: {}, ...extra }));
  return f;
};

describe('shared-files (no browser, real find CLI)', () => {
  it('writes two I5 files, skips the labelled one and never reads an unlisted file', async (t) => {
    if (!py) { assert.ok(!REQUIRE, 'no python for the find CLI'); return t.skip('no python'); }
    const { wb, sync } = syncFolder();
    const clock = fakeClock();
    const f = scopeFile(wb, sync, ['Reports/plan.md', 'Reports/budget.txt', 'Reports/labelled.docx']);
    const r = await runCapture(main, wb, ['run', '--source', 'shared-files', '--scope', f], { clock });
    assert.equal(r.code, 0, r.err + r.out);
    const files = walkMd(`${wb}/data/captured/shared-files`);
    assert.equal(files.length, 2, files.join('\n'));
    assert.deepEqual(r.report.skipped.map((s) => s.reason), ['labelled']);
    assert.equal(r.report.counts.paced, 3, 'every read is a paced hydration');
    assert.equal(r.report.entries.length, 2);
    for (const e of r.report.entries) { assert.match(e.sha256, /^[0-9a-f]{64}$/); assert.match(e.expires, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/); }
    const text = files.map((x) => fs.readFileSync(x, 'utf8')).join('\n');
    assert.ok(text.includes('pelican') && text.includes('heron'));
    assert.ok(!text.includes('ibis') && !text.includes('Confidential'));
    const plan = fs.readFileSync(files.find((x) => x.includes('plan')), 'utf8');
    assert.match(plan, /^---\nsource: "shared-files"\nurl: "sync-folder:Reports\/plan.md"\ntitle: "plan"\nauthor: null\nmodified: "[^"]+"\ncaptured_at: "[^"]+"\nlabels: \[\]\nscope: "folder:Reports\/plan.md"\n---\n\n/);
    assert.equal(r.report.label, null);
    // the first run starts at once: no note to acknowledge
    assert.doesNotMatch(r.out, /security team/i);
    // the knowledge layer finds the copies with url and source
    const db = `${wb}/index.sqlite`;
    assert.equal(findCli(py, ['--db', db, 'add-root', `${wb}/data/captured`, '--label', 'captured']).code, 0);
    assert.equal(findCli(py, ['--db', db, 'refresh', '--all', '--embed', 'off']).code, 0);
    const hit = JSON.parse(findCli(py, ['--db', db, 'search', 'pelican rollout', '--mode', 'keyword', '--json']).out).hits[0];
    assert.equal(hit.url, 'sync-folder:Reports/plan.md');
    assert.equal(hit.source, 'shared-files');
  });

  it('--include-labelled reads a labelled file and records its label', async (t) => {
    if (!py) { assert.ok(!REQUIRE, 'no python for the find CLI'); return t.skip('no python'); }
    const { wb, sync } = syncFolder();
    const f = scopeFile(wb, sync, ['Reports/internal.md']);
    const skipped = await runCapture(main, wb, ['run', '--source', 'shared-files', '--scope', f]);
    assert.deepEqual(skipped.report.skipped.map((s) => s.reason), ['labelled']);
    assert.equal(walkMd(`${wb}/data/captured`).length, 0);
    const r = await runCapture(main, wb, ['run', '--source', 'shared-files', '--scope', f, '--include-labelled']);
    assert.equal(r.code, 0);
    const [file] = walkMd(`${wb}/data/captured/shared-files`);
    assert.match(fs.readFileSync(file, 'utf8'), /\nlabels: \["Internal"\]\n/);
  });

  it('a folder entry walks its files; deny and entries outside the sync folder are never read', async (t) => {
    if (!py) { assert.ok(!REQUIRE, 'no python for the find CLI'); return t.skip('no python'); }
    const { wb, sync } = syncFolder();
    const f = scopeFile(wb, sync, ['Reports', '../elsewhere'], { deny: { 'shared-files': ['archive', 'unlisted', 'labelled'] } });
    const r = await runCapture(main, wb, ['run', '--source', 'shared-files', '--scope', f]);
    assert.equal(r.code, 0, r.err);
    const text = walkMd(`${wb}/data/captured/shared-files`).map((x) => fs.readFileSync(x, 'utf8')).join('\n');
    assert.ok(text.includes('pelican') && text.includes('heron'));
    assert.ok(!text.includes('kiwi') && !text.includes('ibis'), 'denied paths are not read');
    const reasons = r.report.skipped.map((s) => s.reason);
    assert.ok(reasons.includes('entry is outside the sync folder') && reasons.includes('deny list') && reasons.includes('labelled'));
  });

  it('a dry run lists the files and writes nothing; a local placement writes under the capture folder', async (t) => {
    if (!py) { assert.ok(!REQUIRE, 'no python for the find CLI'); return t.skip('no python'); }
    const { wb, sync } = syncFolder();
    const f = scopeFile(wb, sync, ['Reports/plan.md']);
    const dry = await runCapture(main, wb, ['run', '--source', 'shared-files', '--scope', f, '--dry-run']);
    assert.equal(dry.code, 0);
    assert.equal(dry.report.dry_run, true);
    assert.equal(walkMd(`${wb}/data`).length + walkMd(`${wb}/capture/local`).length, 0);
    assert.equal(dry.report.counts.paced, 0, 'a dry run reads nothing');
    const f2 = scopeFile(wb, sync, ['Reports/plan.md'], { placement: { 'shared-files': 'local' } });
    const r = await runCapture(main, wb, ['run', '--source', 'shared-files', '--scope', f2]);
    assert.equal(r.code, 0);
    assert.equal(walkMd(`${wb}/capture/local/shared-files`).length, 1);
    assert.equal(walkMd(`${wb}/data/captured`).length, 0);
  });

  it('stops with a report at the hourly cap and writes what it had read', async (t) => {
    if (!py) { assert.ok(!REQUIRE, 'no python for the find CLI'); return t.skip('no python'); }
    const { wb, sync } = syncFolder();
    const f = scopeFile(wb, sync, ['Reports/plan.md', 'Reports/budget.txt']);
    const r = await runCapture(main, wb, ['run', '--source', 'shared-files', '--scope', f, '--max-per-hour', '1']);
    assert.equal(r.code, 3);
    assert.equal(r.report.stop.kind, 'pacing');
    assert.equal(r.report.entries.length, 1);
  });

  it('the hourly cap holds across runs: a second run right after the first is stopped until the window moves', async (t) => {
    if (!py) { assert.ok(!REQUIRE, 'no python for the find CLI'); return t.skip('no python'); }
    const { wb, sync } = syncFolder();
    const f = scopeFile(wb, sync, ['Reports/plan.md', 'Reports/budget.txt', 'Reports/Archive/old.md']);
    const clock = fakeClock();
    const one = await runCapture(main, wb, ['run', '--source', 'shared-files', '--scope', f, '--max-per-hour', '3'], { clock });
    assert.equal(one.code, 0);
    assert.equal(one.report.entries.length, 3);
    const two = await runCapture(main, wb, ['run', '--source', 'shared-files', '--scope', f, '--max-per-hour', '3'], { clock });
    assert.equal(two.code, 3);
    assert.equal(two.report.stop.kind, 'pacing');
    assert.equal(two.report.entries.length, 0);
    clock.t += 3_600_001;
    const three = await runCapture(main, wb, ['run', '--source', 'shared-files', '--scope', f, '--max-per-hour', '3'], { clock });
    assert.equal(three.code, 0);
    assert.equal(three.report.entries.length, 3);
  });

  it('refuses a source with no sync folder and an unknown source', async () => {
    const wb = tempHome();
    fs.writeFileSync(`${wb}/scope.json`, JSON.stringify({ scope: { 'shared-files': ['Reports'] } }));
    const r = await runCapture(main, wb, ['run', '--source', 'shared-files', '--scope', `${wb}/scope.json`]);
    assert.equal(r.code, 4);
    assert.match(r.report.error, /sync_root/);
    const u = await runCapture(main, wb, ['run', '--source', 'nope']);
    assert.equal(u.code, 4);
    assert.match(u.err, /unknown source/);
  });
});
