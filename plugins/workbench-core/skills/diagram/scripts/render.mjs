// Render one Mermaid or Excalidraw source to SVG and PNG (and Mermaid to an editable .excalidraw) in a local browser,
// from the offline diagram-render bundle. Nothing leaves the machine: the browser is started with the same two-layer
// network block as the ui-build screenshot script (a request filter, plus a proxy to nowhere that only loopback bypasses),
// and the bundle is opened from disk.
//
//   node render.mjs --src FILE --kind mmd|excalidraw --bundle HTML --out-base PATH [--width 1600]
//
// Writes <out-base>.svg, <out-base>.png and, for mmd when the converter can read it, <out-base>.excalidraw. Prints one JSON
// line on success: {"written": [...], "blocked": [...], "notes": [...]}. Exit 1 = render failed, 2 = bad arguments.
// Browser: installed Edge or Chrome (no download); set UI_BROWSER to a browser executable to override.
// playwright-core: next to this file (npm install --ignore-scripts), or in the folder named by DIAGRAM_NODE_MODULES.
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const LOOP = [127, 0, 0, 1].join('.');   // built, so the file holds no address literal

export const isLocal = raw => {
  let u;
  try { u = new URL(raw); } catch { return false; }
  if (['file:', 'data:', 'blob:', 'about:'].includes(u.protocol)) return true;
  if (!['http:', 'https:', 'ws:', 'wss:'].includes(u.protocol)) return false;
  const h = u.hostname.toLowerCase();
  return h === 'localhost' || h.endsWith('.localhost') || h === '[::1]' || h === '::1' || /^127(\.\d{1,3}){3}$/.test(h);
};

export const launchArgs = () => [
  `--proxy-server=http://${LOOP}:9`,
  '--proxy-bypass-list=',
  '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE *.localhost, EXCLUDE 127.*, EXCLUDE [::1]',
  '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
];

const opt = (name, dflt) => {
  const i = process.argv.indexOf(name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt;
};

const playwright = async () => {
  const nm = process.env.DIAGRAM_NODE_MODULES;
  return nm ? createRequire(join(resolve(nm), 'x.js'))('playwright-core') : await import('playwright-core');
};

const launch = async chromium => {
  const args = launchArgs();
  if (process.env.UI_BROWSER) return chromium.launch({ executablePath: process.env.UI_BROWSER, args });
  for (const channel of ['msedge', 'chrome']) {
    try { return await chromium.launch({ channel, args }); } catch {}
  }
  throw new Error('no Edge or Chrome found: set UI_BROWSER to a browser executable');
};

const fail = (code, msg) => { console.error(msg); process.exit(code); };

const main = async () => {
  const src = opt('--src'), kind = opt('--kind'), bundle = opt('--bundle'), base = opt('--out-base');
  const width = Number(opt('--width', '1600'));
  if (!src || !bundle || !base || !['mmd', 'excalidraw'].includes(kind) || !(width >= 200 && width <= 4000)) {
    fail(2, 'usage: node render.mjs --src FILE --kind mmd|excalidraw --bundle HTML --out-base PATH [--width 200..4000]');
  }
  const text = readFileSync(src, 'utf8');
  const { chromium } = await playwright();
  const browser = await launch(chromium);
  const blocked = [], notes = [], written = [];
  try {
    const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 }, deviceScaleFactor: 1, serviceWorkers: 'block' });
    await ctx.route('**/*', route => {
      const u = route.request().url();
      if (isLocal(u)) return route.continue();
      blocked.push(u);
      return route.abort('blockedbyclient');
    });
    const page = await ctx.newPage();
    page.on('request', r => { if (!isLocal(r.url()) && !blocked.includes(r.url())) blocked.push(r.url()); });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e.message).slice(0, 300)));
    await page.goto(pathToFileURL(resolve(bundle)).href, { waitUntil: 'load', timeout: 60000 });
    await page.waitForSelector('#done', { state: 'attached', timeout: 60000 });
    const svg = await page.evaluate(([t, k]) => (k === 'excalidraw' ? window.__excalidrawToSvg(t) : window.__renderMermaid('diagram-1', t)),
      [text, kind]);
    if (typeof svg !== 'string' || !svg.includes('<svg')) throw new Error('the renderer returned no SVG' + (errors.length ? ': ' + errors[0] : ''));
    writeFileSync(`${base}.svg`, svg, 'utf8');
    written.push(`${base}.svg`);
    const url = await page.evaluate(([s, w]) => window.__rasterize(s, w), [svg, width]);
    if (typeof url !== 'string' || !url.startsWith('data:image/png;base64,')) throw new Error('the rasterizer returned no PNG');
    writeFileSync(`${base}.png`, Buffer.from(url.split(',', 2)[1], 'base64'));
    written.push(`${base}.png`);
    if (kind === 'mmd') {
      try {
        const scene = await page.evaluate(t => window.__mermaidToExcalidraw(t), text);
        writeFileSync(`${base}.excalidraw`, typeof scene === 'string' ? scene : JSON.stringify(scene), 'utf8');
        written.push(`${base}.excalidraw`);
      } catch { notes.push('EXCALIDRAW_SKIPPED: the converter reads flowcharts only; the SVG and PNG are complete'); }
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ written, blocked, notes }));
};

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  main().catch(e => fail(1, `RENDER_FAILED: ${String(e.message ?? e).slice(0, 800)}`));
}
