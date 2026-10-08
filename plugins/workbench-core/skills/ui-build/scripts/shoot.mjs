// Screenshot a LOCAL page at several widths and colour schemes, run an accessibility check, and
// record console errors and horizontal overflow, for the look-fix-reshoot loop. Every request that is
// not to the local app is blocked twice: by a request filter (listed in the summary, redirects
// included) and at the network layer (a proxy to nowhere that only loopback bypasses, and no DNS for
// other hosts), so nothing leaves the machine. Service workers are blocked.
//
//   node shoot.mjs <url> --out DIR [--label before|after] [--widths 1440,390] [--schemes light,dark]
//                  [--full-page] [--wait-for "css selector"] [--no-a11y] [--allow-fonts]
//   --allow-fonts  also let Google Fonts through (fonts.googleapis.com and fonts.gstatic.com only)
//   node shoot.mjs pairs DIR      print a Markdown before/after table for the PR description
//
// <url> must be http://localhost, the IPv4 loopback, [::1], *.localhost or file://. Browser: installed Edge
// or Chrome (no download); set UI_BROWSER to a browser executable to override.
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

export const isLocal = raw => {
  let u;
  try { u = new URL(raw); } catch { return false; }
  if (u.protocol === 'file:' || u.protocol === 'data:' || u.protocol === 'blob:' || u.protocol === 'about:') return true;
  if (!['http:', 'https:', 'ws:', 'wss:'].includes(u.protocol)) return false;
  const h = u.hostname.toLowerCase();
  return h === 'localhost' || h.endsWith('.localhost') || h === '[::1]' || h === '::1' || /^127(\.\d{1,3}){3}$/.test(h);
};

export const FONT_HOSTS = ['fonts.googleapis.com', 'fonts.gstatic.com'];
export const isFontHost = raw => {
  try {
    const u = new URL(raw);
    return u.protocol === 'https:' && FONT_HOSTS.includes(u.hostname.toLowerCase()) && !u.port;
  } catch { return false; }
};
export const allowed = (raw, allowFonts) => isLocal(raw) || (allowFonts && isFontHost(raw));

// Network-layer block: an HTTP proxy on a closed loopback port. Chromium sends every non-loopback
// request (host names and IP literals alike) to it and fails; loopback and *.localhost bypass proxies
// implicitly. Host-resolver rules stop DNS lookups (and prefetches) for any other name, and WebRTC may
// not send UDP around the proxy. The font hosts are exempted only with --allow-fonts.
const LOOP = [127, 0, 0, 1].join('.');   // built, so the file holds no address literal
export const launchArgs = allowFonts => {
  const keep = allowFonts ? FONT_HOSTS : [];
  return [
    `--proxy-server=http://${LOOP}:9`,
    `--proxy-bypass-list=${keep.join(';')}`,
    `--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE *.localhost, EXCLUDE 127.*, EXCLUDE [::1]${keep.map(h => `, EXCLUDE ${h}`).join('')}`,
    '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
  ];
};

const opt = (args, name, dflt) => {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : dflt;
};

const HEIGHT = { 390: 844, 768: 1024 };   // phone and tablet portrait; anything else gets 900

const launchBrowser = async allowFonts => {
  const { chromium } = await import('playwright-core');
  const args = launchArgs(allowFonts);
  if (process.env.UI_BROWSER) return chromium.launch({ executablePath: process.env.UI_BROWSER, args });
  for (const channel of ['msedge', 'chrome']) {
    try { return await chromium.launch({ channel, args }); } catch {}
  }
  throw new Error('no Edge or Chrome found: set UI_BROWSER to a browser executable');
};

const axeSource = () => {
  try { return readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8'); } catch { return null; }
};

// Runs in the page: horizontal overflow and the elements that cause it: the first overflowing element
// down each branch (its parent still fits), at most 10.
export const overflowCheck = () => {
  const vw = window.innerWidth;
  const sw = document.documentElement.scrollWidth;
  const name = el => el.tagName.toLowerCase() + (el.id ? `#${el.id}` : '')
    + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
  const hits = [];
  if (sw > vw) {
    for (const el of document.body.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      if (r.width && (r.right > vw + 1 || r.left < -1) && getComputedStyle(el).position !== 'fixed') {
        hits.push({ el, text: `${name(el)} (left ${Math.round(r.left)}, right ${Math.round(r.right)}, width ${Math.round(r.width)})` });
      }
    }
  }
  const roots = hits.filter(h => !hits.some(o => o !== h && o.el.contains(h.el)));
  return { scrollWidth: sw, innerWidth: vw, overflows: sw > vw, offenders: roots.slice(0, 10).map(h => h.text) };
};

export const shoot = async (url, args) => {
  if (!isLocal(url)) throw Object.assign(new Error(`REFUSED: ${url} is not a local app (localhost, the IPv4 loopback, [::1] or file://)`), { code: 2 });
  const out = opt(args, '--out', null);
  if (!out) throw Object.assign(new Error('--out DIR is required'), { code: 2 });
  mkdirSync(out, { recursive: true });
  const label = opt(args, '--label', 'shot').replace(/[^A-Za-z0-9_-]/g, '_');
  const widths = opt(args, '--widths', '1440,390').split(',').map(Number).filter(Boolean);
  const schemes = opt(args, '--schemes', 'light,dark').split(',').filter(s => s === 'light' || s === 'dark');
  const waitFor = opt(args, '--wait-for', null);
  const axe = args.includes('--no-a11y') ? null : axeSource();
  const allowFonts = args.includes('--allow-fonts');
  const summary = { url, label, shots: [], blocked: [], redirects: [], overflow: {}, consoleErrors: [], a11y: {}, notes: [] };
  const block = u => { if (!summary.blocked.includes(u)) summary.blocked.push(u); };
  const browser = await launchBrowser(allowFonts);
  try {
    for (const width of widths) {
      const pngs = {};
      for (const colorScheme of schemes) {
        const ctx = await browser.newContext({ viewport: { width, height: HEIGHT[width] ?? 900 }, colorScheme,
          deviceScaleFactor: 1, serviceWorkers: 'block' });
        await ctx.route('**/*', route => {
          const u = route.request().url();
          if (allowed(u, allowFonts)) return route.continue();
          block(u);
          return route.abort('blockedbyclient');
        });
        if (ctx.routeWebSocket) await ctx.routeWebSocket(/.*/, ws => (isLocal(ws.url()) ? ws.connectToServer() : ws.close()));
        const page = await ctx.newPage();
        // Redirect hops are not always routed: record every hop, and list any that left the local app.
        page.on('request', r => {
          if (!allowed(r.url(), allowFonts)) block(r.url());
          const hops = [];
          for (let q = r; q; q = q.redirectedFrom()) hops.unshift(q.url());
          if (hops.length > 1 && hops.some(h => !allowed(h, allowFonts))) {
            const chain = hops.join(' -> ');
            if (!summary.redirects.includes(chain)) summary.redirects.push(chain);
          }
        });
        page.on('console', m => { if (m.type() === 'error') summary.consoleErrors.push(`${width}/${colorScheme}: ${m.text().slice(0, 300)}`); });
        page.on('pageerror', e => summary.consoleErrors.push(`${width}/${colorScheme}: ${String(e.message).slice(0, 300)}`));
        try { await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 }); }
        catch { await page.goto(url, { waitUntil: 'load', timeout: 30000 }); summary.notes.push('network never went idle; shot after load'); }
        if (!allowed(page.url(), allowFonts)) throw Object.assign(new Error(`REFUSED: the page navigated away from the local app to ${page.url()}`), { code: 2 });
        if (waitFor) await page.waitForSelector(waitFor, { timeout: 15000 });
        await page.evaluate(() => document.fonts?.ready);
        if (colorScheme === schemes[0]) summary.overflow[width] = await page.evaluate(overflowCheck);
        const file = join(out, `${label}-${width}-${colorScheme}.png`);
        pngs[colorScheme] = await page.screenshot({ path: file, fullPage: args.includes('--full-page') });
        summary.shots.push(file);
        if (colorScheme === schemes[0]) {
          if (axe) {
            await page.evaluate(axe);   // evaluate is not subject to the page's CSP, unlike a script tag
            const r = await page.evaluate(() => window.axe.run(document, { resultTypes: ['violations'] }));
            summary.a11y[width] = r.violations.map(v => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length,
              targets: v.nodes.slice(0, 5).map(n => n.target.join(' ')) }));
          } else {
            writeFileSync(join(out, `${label}-${width}-aria.txt`), await page.locator('body').ariaSnapshot());
            summary.notes.push('axe-core not installed: wrote the ARIA snapshot instead (npm install in the scripts copy)');
          }
        }
        await ctx.close();
      }
      if (pngs.light && pngs.dark && Buffer.compare(pngs.light, pngs.dark) === 0) {
        rmSync(join(out, `${label}-${width}-dark.png`), { force: true });
        summary.shots = summary.shots.filter(f => !f.endsWith(`${label}-${width}-dark.png`));
        if (!summary.notes.includes('no dark mode: the page ignores prefers-color-scheme')) summary.notes.push('no dark mode: the page ignores prefers-color-scheme');
      }
    }
  } finally {
    await browser.close();
  }
  writeFileSync(join(out, `${label}-summary.json`), JSON.stringify(summary, null, 2));
  return summary;
};

export const pairs = dir => {
  const files = readdirSync(dir).filter(f => f.endsWith('.png'));
  const rows = files.filter(f => f.startsWith('before-')).map(b => [b, b.replace(/^before-/, 'after-')])
    .filter(([, a]) => files.includes(a));
  return ['| View | Before | After |', '|---|---|---|',
    ...rows.map(([b, a]) => `| ${b.slice(7, -4)} | ![before](${b}) | ![after](${a}) |`)].join('\n');
};

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [first, ...rest] = process.argv.slice(2);
  try {
    if (first === 'pairs') console.log(pairs(rest[0] ?? '.'));
    else if (!first || first.startsWith('-')) { console.log(readFileSync(new URL(import.meta.url), 'utf8').split('\n').slice(0, 12).join('\n')); process.exit(2); }
    else {
      const s = await shoot(first, rest);
      s.shots.forEach(f => console.log(f));
      for (const [w, v] of Object.entries(s.a11y)) {
        console.log(`a11y ${w}px: ${v.length ? v.map(x => `${x.impact ?? '?'} ${x.id} (${x.nodes})`).join(', ') : 'no violations found'}`);
      }
      for (const [w, o] of Object.entries(s.overflow)) {
        if (o.overflows) console.log(`OVERFLOW ${w}px: page is ${o.scrollWidth}px wide in a ${o.innerWidth}px viewport; ${o.offenders.join('; ') || 'no single element found'}`);
      }
      if (s.blocked.length) console.log(`blocked ${s.blocked.length} non-local request(s): ${s.blocked.slice(0, 5).join(' ')}`);
      if (s.redirects.length) console.log(`redirects that left the local app (blocked): ${s.redirects.join(' | ')}`);
      if (s.consoleErrors.length) console.log(`console errors: ${s.consoleErrors.length} (see summary)`);
      s.notes.forEach(n => console.log(`note: ${n}`));
      if (!existsSync(join(opt(rest, '--out', '.'), `${s.label}-summary.json`))) process.exit(1);
    }
  } catch (e) {
    console.error(e.message);
    process.exit(e.code ?? 1);
  }
}
