// Everything that needs a real browser (Edge, headless) lives here so one test process launches few of them.
// The pages are fictional and served from localhost; nothing leaves this machine.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, before, describe, it } from 'node:test';
import { launch, main } from '../skills/capture/scripts/capture.mjs';
import { makeActions, Refused, Stop, watch } from '../skills/capture/scripts/actions.mjs';
import { createPacer } from '../skills/capture/scripts/pacing.mjs';
import { edgeInstalled, fakeClock, findCli, knowledgePython, REQUIRE, runCapture, spawnCapture, tempHome, walkMd } from './fixtures/site/env.mjs';
import { serve } from './fixtures/site/serve.mjs';

const tmp = (p) => fs.mkdtempSync(path.join(os.tmpdir(), p));
// Without Edge these suites skip, unless WB_REQUIRE_ALL=1, where a missing Edge is a failure.
const NEEDS_EDGE = { skip: !edgeInstalled() && !REQUIRE && 'Microsoft Edge is not installed' };
const noIco = (log) => log.filter((x) => !x.path.endsWith('.ico')).map((x) => `${x.method} ${x.path}`);

describe('action layer (G12)', NEEDS_EDGE, () => {
  let srv; let ctx; let page; let state; let hosts; let denied;
  before(async () => {
    srv = await serve();
    ctx = await launch({ profile: tmp('wbcap-p-'), headless: true });
    page = ctx.pages()[0] ?? (await ctx.newPage());
    state = { violations: [], blockedNav: null, stopped: null };
    hosts = new Set([srv.host]);
    denied = [];
    await watch({ context: ctx, page, state, hostAllowed: (h) => hosts.has(h) });
  });
  after(async () => { await ctx?.close(); await srv?.close(); });

  // A fresh action layer on the shared page: state is reset, the pacer runs on a fake clock.
  const actions = (selectors, extra = {}) => {
    Object.assign(state, { violations: [], blockedNav: null, stopped: null });
    const pacer = createPacer({ clock: fakeClock(), rand: () => 0 });
    return { a: makeActions({ page, selectors, hostAllowed: (h) => hosts.has(h), isDenied: (u) => denied.some((d) => u.includes(d)), pacer, state, ...extra }), pacer };
  };

  it('refuses every send/post/reply/react/accept/edit/delete/share/save control, localized and icon-only, even when its selector is allowlisted', async () => {
    const { a: probe } = actions({});
    await probe.goto(`${srv.origin}/buttons.html`);
    const ids = await page.$$eval('[data-zoo]', (els) => els.map((e) => e.id));
    assert.ok(ids.length >= 50, `the fixture has ${ids.length} controls`);
    const { a } = actions(Object.fromEntries(ids.map((i) => [i, `#${i}`])));
    const seen0 = srv.log.length;
    for (const id of ids) await assert.rejects(a.click(id), Refused, `#${id} was not refused`);
    assert.deepEqual(srv.mutations(), [], 'no control was ever clicked');
    assert.equal(srv.log.length, seen0, 'refusals cause no request at all');
  });

  it('refuses every target that is not an allowlisted name, so a control with an innocent label cannot be reached', async () => {
    const { a } = actions({ next: 'a.next', search: '#q' });
    await a.goto(`${srv.origin}/buttons.html`);
    for (const name of ['send', 'delete', 'plain', '#plain', '#z1', 'button', '__proto__', 'constructor', 'toString', '', undefined, null, 5]) {
      await assert.rejects(a.click(name), (e) => e instanceof Refused && /not allowlisted/.test(e.message), `click(${String(name)})`);
    }
    await assert.rejects(a.download('plain', os.tmpdir()), Refused);
    await assert.rejects(a.search('#q', 'x'), Refused);
    await assert.rejects(a.text('#plain'), Refused);
    assert.deepEqual(srv.mutations(), []);
  });

  it('search, next-page and result-link clicks and plain navigation work', async () => {
    const { a, pacer } = actions({ search: '#q', next: 'a.next', result: 'a.result' });
    const home = await a.goto(`${srv.origin}/buttons.html`);
    assert.equal(home.status, 200);
    assert.equal(await a.search('search', 'alpha'), true);
    assert.match(page.url(), /\/search\?q=alpha$/);
    assert.equal(await a.click('result'), true);
    assert.match(page.url(), /\/docs\/a\.html$/);
    await a.goto(`${srv.origin}/buttons.html`);
    assert.equal(await a.click('next'), true);
    assert.match(page.url(), /\/page2\.html$/);
    assert.equal(await a.click('next'), false, 'no next link on the last page');
    assert.equal(await a.text('result'), null);
    assert.equal(pacer.count, 5, 'goto, search, result click, goto, next click are paced; a click that finds nothing is not');
    const s = await a.snapshot();
    assert.equal(s.title, 'Second page');
  });

  it('a search box inside a POST form is refused', async () => {
    const { a } = actions({ search: '#pq' });
    await a.goto(`${srv.origin}/buttons.html`);
    await assert.rejects(a.search('search', 'x'), /POST/);
  });

  it('a page that fires a POST fails the no-non-GET assertion and the request never leaves the browser', async () => {
    const { a } = actions({ next: 'a.next' });
    await assert.rejects(a.goto(`${srv.origin}/post.html`), (e) => e instanceof Stop && e.kind === 'non-get' && /POST/.test(e.message));
    assert.equal(srv.log.some((x) => x.method === 'POST'), false, 'the POST was aborted in the browser');
    const seen = srv.log.length;
    await assert.rejects(a.goto(`${srv.origin}/page2.html`), (e) => e instanceof Stop && e.kind === 'non-get');
    await assert.rejects(a.click('next'), Stop);
    assert.equal(srv.log.length, seen, 'a stopped run navigates nowhere else');
    assert.throws(() => a.finish(), Stop);
  });

  it('never leaves the hosts of the scope and never visits a denied address', async () => {
    const { a } = actions({});
    await assert.rejects(a.goto('https://example.com/'), (e) => e instanceof Refused && /not in scope/.test(e.message));
    await assert.rejects(a.goto('file:///etc/passwd'), Refused);
    denied.push('/private/');
    try {
      await assert.rejects(a.goto(`${srv.origin}/private/secret.html`), (e) => e instanceof Refused);
      assert.equal(a.inScope(`${srv.origin}/private/secret.html`), false);
      assert.equal(a.inScope(`${srv.origin}/docs/a.html`), true);
    } finally { denied.length = 0; }
    assert.equal(srv.hits('/private/secret.html').length, 0);
  });

  it('a redirect to another origin stops the run and nothing after it is read', async () => {
    const other = await serve(); // a second local origin that is not in the scope
    await ctx.route(`${srv.origin}/redirect.html`, (r) => r.fulfill({ status: 302, headers: { location: `${other.origin}/page2.html?x=1` } }));
    try {
      const { a } = actions({ next: 'a.next' });
      await assert.rejects(a.goto(`${srv.origin}/redirect.html`), (e) => e instanceof Stop && e.kind === 'policy' && !e.message.includes('x=1') && e.message.includes(other.host));
      await assert.rejects(a.snapshot(), Stop);
      await assert.rejects(a.click('next'), Stop);
      assert.ok(other.log.length <= 1, 'the browser follows a redirect on its own (one GET); the run makes no other request there');
    } finally { await ctx.unroute(`${srv.origin}/redirect.html`); await other.close(); }
  });

  it('a link that leaves the scope, a mail link, a script link and a download link are refused by click()', async () => {
    const { a } = actions({ ext: 'a[href^="https://example.com"]', mail: 'a[href^="mailto"]', js: 'a[href^="javascript"]', file: '#dl' });
    await a.goto(`${srv.origin}/buttons.html`);
    for (const n of ['ext', 'mail', 'js']) await assert.rejects(a.click(n), Refused, n);
    await a.goto(`${srv.origin}/download.html`);
    await assert.rejects(a.click('file'), /download/);
  });

  it('download() saves into the requested folder and counts against pacing', async () => {
    const { a, pacer } = actions({ dl: '#dl' });
    await a.goto(`${srv.origin}/download.html`);
    const dest = tmp('wbcap-d-');
    const file = await a.download('dl', dest);
    assert.equal(path.dirname(file), dest.replaceAll('\\', '/'));
    assert.equal(fs.readFileSync(file, 'utf8').trim(), 'fixture report'); // a checkout may turn LF into CRLF
    assert.equal(pacer.count, 2);
  });

  it('checks that the signed-in account belongs to the scope tenant', async () => {
    const ok = actions({ account: '#acct' }, { tenant: 'example.com' }).a;
    assert.equal((await ok.goto(`${srv.origin}/account.html`)).status, 200);
    const bad = actions({ account: '#acct' }, { tenant: 'example.com' }).a;
    await assert.rejects(bad.goto(`${srv.origin}/account-other.html`), (e) => e instanceof Stop && e.kind === 'tenant');
    const none = actions({ account: '#acct' }, { tenant: 'example.com' }).a;
    await assert.rejects(none.goto(`${srv.origin}/page2.html`), (e) => e instanceof Stop && e.kind === 'tenant');
  });
});

describe('interstitials stop the run with a report (exit 3)', NEEDS_EDGE, () => {
  let srv; let other;
  before(async () => { srv = await serve(); other = await serve(); });
  after(async () => { await srv.close(); await other.close(); });

  const cases = [
    ['a sign-in page', { status: 200, body: 'signin.html' }, 'sign-in'],
    ['a consent page', { status: 200, body: 'consent.html' }, 'consent'],
    ['a data-protection banner', { status: 200, body: 'dlp.html' }, 'dlp'],
    ['an HTTP 403 page', { status: 403, text: 'Forbidden' }, 'block'],
    ['a throttle response', { status: 429, text: 'Too many requests' }, 'block'],
    ['a redirect to another origin', { status: 302, location: () => `${other.origin}/authorize?code=1` }, 'policy'],
  ];
  for (const [name, reply, kind] of cases) {
    it(`${name} -> ${kind}, no retry, no further navigation`, async () => {
      const wb = tempHome();
      const scope = `${wb}/scope.json`;
      fs.writeFileSync(scope, JSON.stringify({ version: 1, scope: { intranet: [`${srv.origin}/`] } }));
      const seen0 = srv.log.length;
      let tries = 0;
      const r = await runCapture(main, wb, ['run', '--source', 'intranet', '--scope', scope], {
        onContext: (c) => c.route('**/docs/b.html', (route) => {
          tries++;
          if (reply.location) return route.fulfill({ status: 302, headers: { location: reply.location() } });
          return route.fulfill({ status: reply.status, contentType: 'text/html', body: reply.body ? srv.page(reply.body) : `<html><body>${reply.text}</body></html>` });
        }),
      });
      assert.equal(r.code, 3, JSON.stringify(r.report));
      assert.equal(r.report.status, 'stopped');
      assert.equal(r.report.exit, 3);
      assert.equal(r.report.stop.kind, kind);
      assert.equal(tries, 1, 'the page was asked for once and never retried');
      assert.ok(!JSON.stringify(r.report).includes('code=1'), 'no query string in the report');
      const seen = noIco(srv.log.slice(seen0));
      assert.deepEqual(seen, ['GET /robots.txt', 'GET /', 'GET /docs/a.html'], 'nothing is requested after the stop');
      assert.equal(r.report.entries.length, 2, 'pages read before the stop are kept');
    });
  }

  it('a page whose own scripts POST stops with kind non-get and a report', async () => {
    const wb = tempHome();
    const scope = `${wb}/scope.json`;
    fs.writeFileSync(scope, JSON.stringify({ version: 1, scope: { intranet: [`${srv.origin}/post.html`] } }));
    const r = await runCapture(main, wb, ['run', '--source', 'intranet', '--scope', scope]);
    assert.equal(r.code, 3);
    assert.equal(r.report.stop.kind, 'non-get');
  });
});

describe('policy and launch decisions (no browser needed)', () => {
  it('RemoteDebuggingAllowed off -> exit 3 with the ask, and no browser is started', async () => {
    const wb = tempHome();
    fs.writeFileSync(`${wb}/scope.json`, JSON.stringify({ scope: { intranet: ['https://wiki.example.com/'] } }));
    const r = await runCapture(main, wb, ['run', '--source', 'intranet', '--scope', `${wb}/scope.json`], {
      probe: () => ({ remoteDebuggingAllowed: false, headlessAllowed: true, raw: { RemoteDebuggingAllowed: 0, HeadlessModeEnabled: null } }),
      launch: async () => { throw new Error('must not launch'); },
    });
    assert.equal(r.code, 3);
    assert.equal(r.report.stop.kind, 'policy');
    assert.match(r.report.stop.ask, /policy/i);
  });

  it('headless only when HeadlessModeEnabled allows it; --headed forces a window', async () => {
    const seen = [];
    const launch = async (o) => { seen.push(o.headless); throw new Error('stop after launch'); };
    const wb = tempHome();
    fs.writeFileSync(`${wb}/scope.json`, JSON.stringify({ scope: { intranet: ['https://wiki.example.com/'] } }));
    const run = (probe, extra = []) => runCapture(main, wb, ['run', '--source', 'intranet', '--scope', `${wb}/scope.json`, ...extra], { probe: () => probe, launch });
    await run({ remoteDebuggingAllowed: true, headlessAllowed: true, raw: {} });
    await run({ remoteDebuggingAllowed: true, headlessAllowed: false, raw: {} });
    await run({ remoteDebuggingAllowed: true, headlessAllowed: true, raw: {} }, ['--headed']);
    assert.deepEqual(seen, [true, false, false]);
  });

  it('login opens a visible window on the first scope URL, in the capture profile folder, and waits for the user to close it', async () => {
    const wb = tempHome();
    fs.writeFileSync(`${wb}/scope.json`, JSON.stringify({ scope: { intranet: ['https://wiki.example.com/start/'] } }));
    const visited = [];
    let opts;
    const win = { pages: () => [{ goto: async (u) => visited.push(u) }], on: (ev, cb) => { if (ev === 'close') cb(); } };
    const r = await runCapture(main, wb, ['login', '--scope', `${wb}/scope.json`], { launch: async (o) => { opts = o; return win; } });
    assert.equal(r.code, 0);
    assert.deepEqual(opts, { profile: `${wb}/capture/profile`, headless: false });
    assert.deepEqual(visited, ['https://wiki.example.com/start/']);
    const off = await runCapture(main, wb, ['login'], { probe: () => ({ remoteDebuggingAllowed: false, headlessAllowed: false, raw: {} }), launch: async () => { throw new Error('must not launch'); } });
    assert.equal(off.code, 3);
  });

  it('the browser profile is a separate folder and Edge\'s own profile is refused', async () => {
    await assert.rejects(launch({ profile: 'D:/profiles/AppData/Local/Microsoft/Edge/User Data', headless: true }), /own profile/);
  });
});

describe('source modules (interface I24)', NEEDS_EDGE, () => {
  let srv;
  before(async () => { srv = await serve(); });
  after(async () => { await srv.close(); });

  it('loads a module dropped into a sources folder; it can only click its own names; download() lands where asked and is paced', async () => {
    const dir = tmp('wbcap-src-');
    const dest = tmp('wbcap-dl-').replaceAll('\\', '/');
    fs.writeFileSync(`${dir}/probe_src.mjs`, `
export default {
  name: 'probe-src', experimental: false, selectors: { next: 'a.next', dl: '#dl' },
  async run(ctx) {
    const results = {};
    await ctx.goto(ctx.scope[0] + 'buttons.html');
    for (const n of ['send', 'delete', '#plain']) { try { await ctx.click(n); results[n] = 'clicked'; } catch (e) { results[n] = e.name; } }
    results.next = await ctx.click('next');
    await ctx.goto(ctx.scope[0] + 'download.html');
    results.file = await ctx.download('dl', ${JSON.stringify(dest)});
    ctx.write({ url: ctx.scope[0] + 'probe', title: 'probe results', scope: 'probe', body: JSON.stringify(results) });
  },
};`);
    fs.writeFileSync(`${dir}/broken.mjs`, 'export default { name: "Broken Name" };');
    const wb = tempHome();
    const scope = `${wb}/scope.json`;
    fs.writeFileSync(scope, JSON.stringify({ scope: { 'probe-src': [`${srv.origin}/`] } }));
    const r = await runCapture(main, wb, ['run', '--source', 'probe-src', '--scope', scope], { sourcesDir: dir });
    assert.equal(r.code, 0, r.err + JSON.stringify(r.report));
    const [file] = walkMd(`${wb}/data/captured/probe-src`);
    const body = JSON.parse(fs.readFileSync(file, 'utf8').split('---\n\n')[1]);
    assert.deepEqual({ send: body.send, delete: body.delete, plain: body['#plain'], next: body.next }, { send: 'Refused', delete: 'Refused', plain: 'Refused', next: true });
    assert.equal(fs.readFileSync(body.file, 'utf8').trim(), 'fixture report');
    assert.equal(path.dirname(body.file), dest);
    assert.equal(r.report.counts.paced, 4, 'goto + next click + goto + download; refusals are not paced');
    assert.deepEqual(srv.mutations(), []);
    const bad = await runCapture(main, wb, ['run', '--source', 'broken'], { sourcesDir: dir });
    assert.equal(bad.code, 4);
    assert.match(bad.err, /failed to load: broken\.mjs/);
  });

  it('an experimental module refuses to run without --experimental and labels its report', async () => {
    const dir = tmp('wbcap-src-');
    fs.writeFileSync(`${dir}/exp_src.mjs`, `export default { name: 'exp-src', experimental: true, browser: false, selectors: {}, async run(ctx) { ctx.write({ url: 'sync-folder:x', title: 'x', scope: 'x', body: 'x' }); } };`);
    const wb = tempHome();
    const no = await runCapture(main, wb, ['run', '--source', 'exp-src'], { sourcesDir: dir });
    assert.equal(no.code, 4);
    assert.match(no.err, /--experimental/);
    assert.equal(walkMd(`${wb}/data`).length, 0);
    const yes = await runCapture(main, wb, ['run', '--source', 'exp-src', '--experimental'], { sourcesDir: dir });
    assert.equal(yes.code, 0);
    assert.equal(yes.report.experimental, true);
    assert.equal(yes.report.label, 'experimental');
    assert.equal(JSON.parse(yes.out.split('\n').at(-1)).experimental, true);
  });

  it('a module that stops the run gets exit 3 and a report', async () => {
    const dir = tmp('wbcap-src-');
    fs.writeFileSync(`${dir}/stop_src.mjs`, `export default { name: 'stop-src', experimental: false, browser: false, selectors: {}, async run(ctx) { ctx.stop('banner seen'); } };`);
    const wb = tempHome();
    const r = await runCapture(main, wb, ['run', '--source', 'stop-src'], { sourcesDir: dir });
    assert.equal(r.code, 3);
    assert.equal(r.report.stop.kind, 'module');
  });
});

describe('end to end: intranet crawl -> files -> find (G12, G5)', NEEDS_EDGE, () => {
  let srv;
  before(async () => { srv = await serve(); });
  after(async () => { await srv.close(); });

  it('crawls the fixture site in a child process and the knowledge layer finds the text with its url and source', { timeout: 180000 }, async (t) => {
    const py = knowledgePython();
    if (!py) { assert.ok(!REQUIRE, 'no python for the find CLI'); return t.skip('no python'); }
    const wb = tempHome();
    assert.equal((await spawnCapture(wb, ['--version'])).stdout.trim().split(' ')[0], 'capture');
    for (const args of [['scope', 'add', '--source', 'intranet', `${srv.origin}/?utm=1#x`], ['scope', 'add', '--deny', '--source', 'intranet', '/private/']]) {
      assert.equal((await spawnCapture(wb, args)).code, 0);
    }
    const r = await spawnCapture(wb, ['run', '--source', 'intranet']);
    assert.equal(r.code, 0, r.stderr + r.stdout.slice(-600));
    assert.match(r.stdout, /security team/i, 'the first run prints the InfoSec note');
    const summary = JSON.parse(r.stdout.trim().split('\n').at(-1));
    assert.equal(summary.status, 'done');
    const rep = JSON.parse(fs.readFileSync(summary.report, 'utf8'));

    // what was reached: home, alpha, beta, deep (depth two); not the labelled, denied, robots-blocked or too-deep pages
    const files = walkMd(`${wb}/data/captured/intranet`);
    assert.equal(files.length, 4, files.join('\n'));
    const all = files.map((f) => fs.readFileSync(f, 'utf8')).join('\n');
    for (const gone of ['narwhal', 'walrus', 'robots.txt says no', 'Depth three', 'SECRET123', 'utm=1']) assert.ok(!all.includes(gone), gone);
    assert.ok(all.includes('zebra crossing') && all.includes('quokka onboarding') && all.includes('| Maple | 8 |'));
    assert.equal(srv.hits('/private/secret.html').length, 0, 'a denied page is never visited');
    assert.equal(srv.hits('/blocked/x.html').length, 0, 'robots.txt is honoured');
    assert.equal(srv.hits('/docs/deep/d.html').length, 0, 'the depth cap is honoured');
    assert.ok(srv.log.every((x) => x.method === 'GET'));
    assert.ok(rep.entries.every((e) => /^[0-9a-f]{64}$/.test(e.sha256) && e.expires && e.url.startsWith('http://localhost:') && !e.url.includes('?')));
    assert.deepEqual(rep.skipped.map((s) => s.reason).sort(), ['deny list', 'labelled', 'robots.txt']);
    assert.equal(rep.counts.paced, 6, 'robots.txt, home, alpha, beta, the labelled page and the deep page are the paced loads');
    const fm = fs.readFileSync(files.find((f) => f.includes('beta')), 'utf8');
    assert.match(fm, new RegExp(`^---\\nsource: "intranet"\\nurl: "${srv.origin.replaceAll('.', '\\.')}/docs/b\\.html"\\ntitle: "Beta handbook"\\nauthor: null\\nmodified: null\\ncaptured_at: "[^"]+"\\nlabels: \\[\\]\\nscope: "site:${srv.host}/path:/"\\n---\\n\\n# Beta handbook`));
    assert.match(fs.readFileSync(files.find((f) => f.includes('alpha')), 'utf8'), /author: "Pat Example"\nmodified: "2025-03-04T10:00:00Z"/);

    // the knowledge layer
    const db = `${wb}/index.sqlite`;
    assert.equal(findCli(py, ['--db', db, 'add-root', `${wb}/data/captured`, '--label', 'captured']).code, 0);
    assert.equal(findCli(py, ['--db', db, 'refresh', '--all', '--embed', 'off']).code, 0);
    const res = JSON.parse(findCli(py, ['--db', db, 'search', 'quokka onboarding checklist', '--mode', 'keyword', '--json']).out);
    assert.equal(res.hits[0].url, `${srv.origin}/docs/b.html`);
    assert.equal(res.hits[0].source, 'intranet');
    const none = JSON.parse(findCli(py, ['--db', db, 'search', 'narwhal budget memo', '--mode', 'keyword', '--json']).out);
    assert.equal(none.hits.length, 0);
    assert.equal((await spawnCapture(wb, ['purge', '--source', 'intranet'])).code, 0);
    assert.deepEqual(walkMd(`${wb}/data/captured/intranet`), []);
  });
});
