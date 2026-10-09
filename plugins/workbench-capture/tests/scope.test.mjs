import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, it } from 'node:test';
import { main, paths, probePolicies } from '../skills/capture/scripts/capture.mjs';
import * as S from '../skills/capture/scripts/scope.mjs';
import { createWriter } from '../skills/capture/scripts/writer.mjs';

const DAY = 86_400_000;
const NOW = Date.UTC(2025, 5, 7, 8, 0, 0);

function home() {
  const wb = fs.mkdtempSync(path.join(os.tmpdir(), 'wbcap-s-')).replaceAll('\\', '/');
  fs.writeFileSync(`${wb}/config.json`, JSON.stringify({ data_root: `${wb}/data` }));
  return wb;
}
async function run(wb, args, deps = {}) {
  const lines = [];
  const errs = [];
  const code = await main(args, { env: { WORKBENCH_HOME: wb }, out: (s) => lines.push(s), err: (s) => errs.push(s), clock: { now: () => NOW, sleep: async () => {} }, ...deps });
  return { code, out: lines.join('\n'), err: errs.join('\n') };
}

describe('scope add|remove|list', () => {
  it('round-trips and strips query strings and fragments from URLs', async () => {
    const wb = home();
    assert.equal((await run(wb, ['scope', 'add', '--source', 'intranet', 'https://wiki.example.com/docs/?utm=1#top'])).code, 0);
    assert.equal((await run(wb, ['scope', 'add', '--source', 'intranet', 'https://wiki.example.com/docs/'])).code, 0); // duplicate
    await run(wb, ['scope', 'add', '--source', 'shared-files', 'Reports/plan.xlsx']);
    await run(wb, ['scope', 'add', '--deny', '--source', 'intranet', '/hr/private/']);
    let l = JSON.parse((await run(wb, ['scope', 'list'])).out);
    assert.deepEqual(l.scope.intranet, ['https://wiki.example.com/docs/']);
    assert.deepEqual(l.scope['shared-files'], ['Reports/plan.xlsx']);
    assert.deepEqual(l.deny.intranet, ['/hr/private/']);
    l = JSON.parse((await run(wb, ['scope', 'list', '--source', 'shared-files'])).out);
    assert.deepEqual(Object.keys(l.scope), ['shared-files']);
    assert.match((await run(wb, ['scope', 'remove', '--source', 'intranet', 'https://wiki.example.com/docs/'])).out, /removed/);
    assert.match((await run(wb, ['scope', 'remove', '--source', 'intranet', 'https://wiki.example.com/docs/'])).out, /not in the list/);
    assert.match((await run(wb, ['scope', 'remove', '--deny', '--source', 'intranet', '/hr/private/'])).out, /removed/);
    l = JSON.parse((await run(wb, ['scope', 'list'])).out);
    assert.deepEqual(l.scope.intranet, undefined);
    assert.deepEqual(l.deny, {});
  });

  it('rejects plain http (except localhost), a missing source and unknown settings; sets known ones', async () => {
    const wb = home();
    assert.equal((await run(wb, ['scope', 'add', '--source', 'intranet', 'http://wiki.example.com/'])).code, 4);
    assert.equal((await run(wb, ['scope', 'add', '--source', 'intranet', 'http://localhost:8080/docs'])).code, 0);
    assert.equal((await run(wb, ['scope', 'add', 'https://wiki.example.com/'])).code, 4);
    assert.equal((await run(wb, ['scope', 'set', 'color', 'red'])).code, 4);
    assert.equal((await run(wb, ['scope', 'set', 'tenant', 'example.com'])).code, 0);
    assert.equal((await run(wb, ['scope', 'set', 'placement.shared-files', 'local'])).code, 0);
    assert.equal((await run(wb, ['scope', 'set', 'retention_days', '0'])).code, 4);
    const l = JSON.parse((await run(wb, ['scope', 'list'])).out);
    assert.equal(l.tenant, 'example.com');
    assert.equal(l.placement['shared-files'], 'local');
  });

  it('a deny entry matches any key that contains it, in any letter case', () => {
    const s = S.emptyScope();
    S.add(s, 'teams', 'Finance-Private', true);
    S.add(s, 'intranet', '/hr/private/', true);
    assert.ok(S.isDenied(s, 'teams', 'team/finance-private/general'));
    assert.ok(S.isDenied(s, 'intranet', 'https://wiki.example.com/HR/Private/page'));
    assert.ok(!S.isDenied(s, 'intranet', 'https://wiki.example.com/docs/'));
    assert.ok(!S.isDenied(s, 'other', '/hr/private/'));
  });

  it('derives the navigation host allowlist from the scope URLs only', () => {
    const s = S.emptyScope();
    S.add(s, 'intranet', 'https://wiki.example.com/docs/');
    S.add(s, 'intranet', 'http://localhost:8080/');
    S.add(s, 'shared-files', 'Reports');
    assert.deepEqual([...S.hosts(s, 'intranet')].sort(), ['localhost:8080', 'wiki.example.com']);
    assert.equal(S.hosts(s, 'shared-files').size, 0);
  });
});

describe('purge', () => {
  it('--older-than removes only old captured files and never a foreign file', async () => {
    const wb = home();
    const base = `${wb}/data/captured`;
    const put = (source, url, daysAgo) => createWriter({ base, source, clock: { now: () => NOW - daysAgo * DAY } }).write({ url, title: url.split('/').pop(), scope: 'site:example.com/path:/', body: 'x' }).path;
    const old = put('intranet', 'https://example.com/old', 100);
    const mid = put('intranet', 'https://example.com/mid', 31);
    const fresh = put('intranet', 'https://example.com/fresh', 2);
    const other = put('shared-files', 'sync-folder:old.md', 100);
    const foreign = `${base}/intranet/site-example-com-path/notes.md`;
    fs.writeFileSync(foreign, 'my own notes, no front matter');
    const r = await run(wb, ['purge', '--older-than', '30']);
    assert.equal(r.code, 0);
    assert.ok(!fs.existsSync(old) && !fs.existsSync(mid) && !fs.existsSync(other), 'old files are gone');
    assert.ok(fs.existsSync(fresh) && fs.existsSync(foreign), 'recent and foreign files stay');
    assert.equal(JSON.parse(r.out).removed, 3);
    await run(wb, ['purge', '--source', 'intranet']);
    assert.ok(!fs.existsSync(fresh) && fs.existsSync(foreign), 'without --older-than a source is cleared, foreign files still stay');
  });

  it('also clears a source kept local by the placement setting', async () => {
    const wb = home();
    const f = createWriter({ base: `${wb}/capture/local`, source: 'shared-files', clock: { now: () => NOW - 200 * DAY } }).write({ url: 'sync-folder:a.md', title: 'a', scope: 'folder:x', body: 'x' }).path;
    assert.ok(fs.existsSync(f));
    await run(wb, ['purge', '--older-than', '30']);
    assert.ok(!fs.existsSync(f));
  });
});

describe('status, version, policy probe', () => {
  it('prints the version and a status summary', async () => {
    const wb = home();
    assert.match((await run(wb, ['--version'])).out, /^capture \d+\.\d+\.\d+$/);
    const st = JSON.parse((await run(wb, ['status'], { probe: () => ({ raw: {} }) })).out);
    assert.equal(st.profile, false);
    assert.equal(st.last_run, null);
  });

  it('logout removes the saved browser profile and nothing else', async () => {
    const wb = home();
    fs.mkdirSync(`${wb}/capture/profile/Default`, { recursive: true });
    fs.writeFileSync(`${wb}/capture/profile/Default/state`, 'x');
    fs.writeFileSync(`${wb}/capture/scope.json`, '{}');
    assert.equal((await run(wb, ['logout'])).code, 0);
    assert.ok(!fs.existsSync(`${wb}/capture/profile`));
    assert.ok(fs.existsSync(`${wb}/capture/scope.json`), 'the scope file is the user\'s and stays');
  });

  it('an unset policy allows the feature; only an explicit 0 turns it off', () => {
    const q = (map) => (key, name) => map[name] ?? null;
    assert.deepEqual(probePolicies(q({})), { remoteDebuggingAllowed: true, headlessAllowed: true, raw: { RemoteDebuggingAllowed: null, HeadlessModeEnabled: null } });
    assert.equal(probePolicies(q({ HeadlessModeEnabled: 0 })).headlessAllowed, false);
    assert.equal(probePolicies(q({ RemoteDebuggingAllowed: 0 })).remoteDebuggingAllowed, false);
    assert.equal(probePolicies(q({ RemoteDebuggingAllowed: 1, HeadlessModeEnabled: 1 })).headlessAllowed, true);
  });

  it('resolves the workbench folders from WORKBENCH_HOME and config.json', () => {
    const wb = home();
    const P = paths({ WORKBENCH_HOME: wb });
    assert.equal(P.profile, `${wb}/capture/profile`);
    assert.equal(P.data, `${wb}/data`);
    assert.equal(P.scopeFile, `${wb}/capture/scope.json`);
  });
});
