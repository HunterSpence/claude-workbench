// Which characters survive synthetic typing into a canvas?
// Playwright's keyboard.type() falls back to CDP Input.insertText for characters it cannot map to
// a physical key, and insertText raises no keydown event. A canvas app, or a remote-desktop web
// client that forwards scancodes, listens for keydown, so those characters silently never arrive.
// A real <input> DOES receive them, which is why verifying in the wrong place looks fine.
//
//   node charfidelity.mjs        (runs off-screen with a throwaway profile; exit 1 if ASCII lost)
import { join } from 'node:path';
import { rmSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { launch, attach, closeBrowser } from './lib.mjs';

const PORT = 9231;
const WORK = join(tmpdir(), 'vdi-drive');
const PROFILE = join(WORK, 'charfid-profile');
mkdirSync(WORK, { recursive: true });

const CASES = {
  'ascii letters+digits': 'abcXYZ0189',
  'url punctuation':      'https://example.com/a?b=1&c=2#frag',
  'symbol-dense line':    'path\\to-file_v2 (draft) #3 & 50% @home {x:[1,2]} | a<b>c',
  'shifted symbols':      '~!@#$%^&*()_+{}|:"<>?',
  'unshifted symbols':    "`-=[]\\;',./",
  'em dash (U+2014)':     'a—b',
  'en dash (U+2013)':     'a–b',
  'curly quotes':         'a“b”c‘d’e',
  'accented latin':       'café naïve',
  'non-breaking space':   'a b',
  'emoji':                'a\u{1F510}b',
};

await launch({ port: PORT, profile: PROFILE, offscreen: true });
const { b, page } = await attach(PORT);

// Two sinks side by side: a keydown-only listener (what a canvas sees) and a real <input>.
// Served from file:// because about:blank enforces a CSP that blocks setContent.
const FIXTURE = join(WORK, 'charfid-fixture.html');
writeFileSync(FIXTURE, `<!doctype html><meta charset="utf-8"><input id="dom" style="width:90%">
  <script>window.__kd=''; window.addEventListener('keydown', e => {
    if (e.key === 'Backspace') window.__kd = window.__kd.slice(0,-1); else if (e.key.length === 1) window.__kd += e.key; });</script>`);
await page.goto('file:///' + FIXTURE.replace(/\\/g, '/'));

const rows = [];
for (const [label, s] of Object.entries(CASES)) {
  await page.evaluate(() => { window.__kd = ''; document.getElementById('dom').value = ''; });
  await page.click('#dom');
  await page.keyboard.type(s, { delay: 5 });
  await page.waitForTimeout(60);
  const { kd, dom } = await page.evaluate(() => ({ kd: window.__kd, dom: document.getElementById('dom').value }));
  rows.push({ label, ascii: [...s].every(c => c.codePointAt(0) < 128), sent: [...s].length, keydown: [...kd].length,
              dom: [...dom].length, lost: [...new Set([...s].filter(ch => !kd.includes(ch)))].join(' ') });
}
await b.close();
await closeBrowser(PORT);
rmSync(FIXTURE, { force: true });
await new Promise(r => setTimeout(r, 1500));
try { rmSync(PROFILE, { recursive: true, force: true }); } catch {}

console.log('\ncase                     sent  keydown  dom-input  lost to keydown');
for (const r of rows) {
  console.log(`${r.keydown === r.sent ? ' ' : '!'} ${r.label.padEnd(22)} ${String(r.sent).padStart(4)} ${String(r.keydown).padStart(8)} ${String(r.dom).padStart(10)}   ${r.lost}`);
}
const asciiLost = rows.filter(r => r.ascii && r.keydown !== r.sent);
console.log(asciiLost.length ? `\nFAIL: ASCII lost in ${asciiLost.map(r => r.label).join(', ')}`
  : '\nASCII survives; non-ASCII rows marked ! are why drive.mjs refuses non-ASCII text.');
process.exit(asciiLost.length ? 1 : 0);
