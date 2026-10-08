// node test_shoot.mjs   (pure checks always; browser checks after `npm install` in a copy of scripts/)
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { execFile, execFileSync } from 'node:child_process';
import { promisify } from 'node:util';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { allowed, isFontHost, isLocal, launchArgs, pairs } from './shoot.mjs';

const LOOP = [127, 0, 0, 1].join('.');   // built, so the file holds no address literal
const PRIV = [10, 0, 0, 5].join('.');

let failed = 0;
const check = (name, fn) => Promise.resolve().then(fn).then(() => console.log(`PASS  ${name}`),
  e => { failed++; console.log(`FAIL  ${name}: ${e.message}`); });

await check('local URLs are allowed', () => {
  for (const u of ['http://localhost:3000/', `http://${LOOP}:5173/x`, 'http://[::1]:8080/', 'http://app.localhost/',
    'file:///C:/x/index.html', 'data:text/html,hi', 'ws://localhost:3000/hmr']) assert.ok(isLocal(u), u);
});
await check('non-local URLs are refused', () => {
  for (const u of ['https://example.com/', 'http://localhost.example.com/', `http://${LOOP}.example.com/`,
    `http://${PRIV}/`, 'ftp://localhost/', 'not a url']) assert.ok(!isLocal(u), u);
});
await check('--allow-fonts lets only the two Google Fonts hosts through', () => {
  for (const u of ['https://fonts.googleapis.com/css2?family=Inter', 'https://fonts.gstatic.com/s/inter/v1/x.woff2']) {
    assert.ok(isFontHost(u), u);
    assert.ok(allowed(u, true), u);
    assert.ok(!allowed(u, false), `${u} is blocked without the flag`);
  }
  for (const u of ['http://fonts.googleapis.com/css', 'https://fonts.googleapis.com.example.com/x',
    'https://evil.example/fonts.gstatic.com', 'https://fonts.gstatic.com:8443/x', 'https://use.typekit.net/x.css']) {
    assert.ok(!allowed(u, true), u);
  }
});
await check('launch args block the network below the request filter', () => {
  const a = launchArgs(false).join(' ');
  assert.match(a, /--proxy-server=http:\/\/[\d.]+:9/);
  assert.match(a, /--proxy-bypass-list=(\s|$)/);
  assert.match(a, /MAP \* ~NOTFOUND, EXCLUDE localhost, EXCLUDE \*\.localhost, EXCLUDE 127\.\*, EXCLUDE \[::1\](\s|$)/);
  assert.match(a, /disable_non_proxied_udp/);
  assert.match(readFileSync(new URL('./shoot.mjs', import.meta.url), 'utf8'), /serviceWorkers: 'block'/, 'shoot blocks service workers');
  const f = launchArgs(true).join(' ');
  assert.match(f, /--proxy-bypass-list=fonts\.googleapis\.com;fonts\.gstatic\.com/);
  assert.match(f, /EXCLUDE fonts\.googleapis\.com, EXCLUDE fonts\.gstatic\.com/);
});
await check('pairs builds a before/after table', () => {
  const d = mkdtempSync(join(tmpdir(), 'pairs-'));
  for (const f of ['before-1440-light.png', 'after-1440-light.png', 'before-390-light.png']) writeFileSync(join(d, f), '');
  const md = pairs(d);
  rmSync(d, { recursive: true, force: true });
  assert.match(md, /\| 1440-light \| !\[before\]\(before-1440-light\.png\) \| !\[after\]\(after-1440-light\.png\) \|/);
  assert.ok(!md.includes('390-light'), 'unpaired shot left out');
});

const HERE = fileURLToPath(new URL('.', import.meta.url));
// Async on purpose: a sync child would block this process's event loop and the test server with it.
const run = (...args) => promisify(execFile)(process.execPath, args, { timeout: 120000 });
const SHOOT = join(HERE, 'shoot.mjs');
await check('the CLI refuses a non-local URL with exit 2', () => {
  let code = 0;
  try { execFileSync(process.execPath, [SHOOT, 'https://example.com/', '--out', tmpdir()], { stdio: 'pipe' }); } catch (e) { code = e.status; }
  assert.equal(code, 2);
});

let havePw = true;
try { createRequire(import.meta.url).resolve('playwright-core'); } catch { havePw = false; }
if (!havePw) console.log('SKIP  browser checks: run `npm install --ignore-scripts` in a copy of scripts/ first');
else {
  const pages = {
    '/dark.html': `<!doctype html><html lang="en"><meta charset="utf-8"><title>t</title>
      <style>body{background:#fff;color:#111} @media (prefers-color-scheme: dark){body{background:#111;color:#eee}}</style>
      <h1>Fixture</h1><img src="https://example.com/remote.png"><img src="/local.svg"></html>`,
    '/plain.html': `<!doctype html><html lang="en"><meta charset="utf-8"><title>t</title><h1>Plain</h1><p>No dark mode.</p></html>`,
    '/local.svg': `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>`,
    '/wide.html': `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
      <title>t</title><h1>Wide</h1><div class="table-wrap"><table id="big" style="width:900px"><tr><td>x</td></tr></table></div></html>`,
    '/sw.html': `<!doctype html><html lang="en"><meta charset="utf-8"><title>t</title><h1>SW</h1><p id="r">pending</p>
      <script>navigator.serviceWorker.register('/sw.js').then(() => r.textContent = 'registered',
        e => r.textContent = 'refused')</script></html>`,
    '/sw.js': `self.addEventListener('fetch', () => {});`,
  };
  let localHits = 0;
  const server = createServer((req, res) => {
    if (req.url === '/go') { res.writeHead(302, { location: 'http://example.com/landing' }); return res.end(); }
    if (req.url === '/redir.html') {
      res.writeHead(200, { 'content-type': 'text/html' });
      return res.end('<!doctype html><html lang="en"><meta charset="utf-8"><title>t</title><h1>R</h1><img alt="x" src="/go"></html>');
    }
    const body = pages[req.url];
    if (req.url === '/local.svg') localHits++;
    const type = req.url.endsWith('.svg') ? 'image/svg+xml' : req.url.endsWith('.js') ? 'text/javascript' : 'text/html';
    res.writeHead(body ? 200 : 404, { 'content-type': type });
    res.end(body ?? '');
  });
  await new Promise(r => server.listen(0, LOOP, r));
  const base = `http://${LOOP}:${server.address().port}`;
  const out = mkdtempSync(join(tmpdir(), 'shoot-'));
  try {
    await check('shoots 1440 and 390 in light and dark, blocks the remote image, finds the missing alt', async () => {
      await run(SHOOT, `${base}/dark.html`, '--out', out, '--label', 'before');
      for (const f of ['before-1440-light.png', 'before-1440-dark.png', 'before-390-light.png', 'before-390-dark.png']) {
        assert.ok(existsSync(join(out, f)), f);
      }
      const s = JSON.parse(readFileSync(join(out, 'before-summary.json'), 'utf8'));
      assert.deepEqual(s.blocked, ['https://example.com/remote.png']);
      assert.ok(localHits > 0, 'the local asset still loads');
      let haveAxe = true;
      try { createRequire(import.meta.url).resolve('axe-core'); } catch { haveAxe = false; }
      if (haveAxe) assert.ok(s.a11y['1440'].some(v => v.id === 'image-alt'), 'axe reports image-alt');
    });
    await check('a page without dark mode keeps only the light shots', async () => {
      await run(SHOOT, `${base}/plain.html`, '--out', out, '--label', 'plain', '--widths', '390');
      assert.ok(existsSync(join(out, 'plain-390-light.png')));
      assert.ok(!existsSync(join(out, 'plain-390-dark.png')));
    });
    await check('reports horizontal overflow at 390px and names the element', async () => {
      await run(SHOOT, `${base}/wide.html`, '--out', out, '--label', 'wide', '--widths', '1440,390', '--schemes', 'light', '--no-a11y');
      const s = JSON.parse(readFileSync(join(out, 'wide-summary.json'), 'utf8'));
      assert.equal(s.overflow['1440'].overflows, false);
      assert.equal(s.overflow['390'].overflows, true);
      assert.ok(s.overflow['390'].scrollWidth > s.overflow['390'].innerWidth);
      assert.ok(s.overflow['390'].offenders.some(o => o.startsWith('table#big')), JSON.stringify(s.overflow['390']));
    });
    await check('a redirect from the local app to a remote host is blocked and listed', async () => {
      await run(SHOOT, `${base}/redir.html`, '--out', out, '--label', 'redir', '--widths', '390', '--schemes', 'light', '--no-a11y');
      const s = JSON.parse(readFileSync(join(out, 'redir-summary.json'), 'utf8'));
      assert.ok(s.blocked.includes('http://example.com/landing'), JSON.stringify(s));
      assert.ok(s.redirects.some(r => r.endsWith('/go -> http://example.com/landing')), JSON.stringify(s.redirects));
    });
    await check('service workers cannot register', async () => {
      const { chromium } = await import('playwright-core');
      let b;
      for (const channel of ['msedge', 'chrome']) { try { b = await chromium.launch({ channel, args: launchArgs(false) }); break; } catch {} }
      try {
        const ctx = await b.newContext({ serviceWorkers: 'block' });
        const page = await ctx.newPage();
        await page.goto(`${base}/sw.html`);
        await page.waitForFunction(() => document.getElementById('r').textContent !== 'pending', null, { timeout: 5000 }).catch(() => {});
        await page.waitForTimeout(500);
        assert.equal(await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length), 0);
        assert.equal(ctx.serviceWorkers().length, 0);
      } finally { await b.close(); }
    });
    await check('the network layer alone refuses a remote host and keeps the local app', async () => {
      const { chromium } = await import('playwright-core');
      let b;
      for (const channel of ['msedge', 'chrome']) { try { b = await chromium.launch({ channel, args: launchArgs(false) }); break; } catch {} }
      try {
        const page = await (await b.newContext()).newPage();   // no request filter here: only the launch args
        assert.equal((await page.goto(`${base}/plain.html`)).status(), 200);
        let failed = false;
        try { await page.goto('http://example.com/', { timeout: 15000 }); } catch { failed = true; }
        assert.ok(failed, 'a remote navigation must fail below the request filter');
      } finally { await b.close(); }
    });
  } finally {
    server.close();
    rmSync(out, { recursive: true, force: true });
  }
}
process.exit(failed ? 1 : 0);
