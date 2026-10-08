// How fast can you type into a real remote desktop before characters drop?
// Drives a test rig (noVNC -> TigerVNC -> a desktop in a container you control, see
// references/test-rig.md) through the same CDP path as drive.mjs, then reads ground truth from
// the remote filesystem rather than the screen, so OCR error is out of the measurement.
//
//   RIG_SSH=<user>@<rig-host> VNC_PW=<rig password> node rttsweep.mjs
// The rig's port 6901 must be tunnelled to localhost first (ssh -N -L 6901:localhost:6901 ...).
// Use only on a rig you own. Never point this at a real remote desktop.
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { rmSync } from 'node:fs';
import { launch, attach, closeBrowser } from './lib.mjs';

const PORT = 9241;
const PROFILE = join(tmpdir(), 'vdi-drive', 'rttsweep-profile');
const RIG = process.env.RIG_SSH;
const PW = process.env.VNC_PW;
if (!RIG || !PW) { console.error('set RIG_SSH and VNC_PW (see references/test-rig.md)'); process.exit(2); }
const URL = `http://localhost:6901/vnc.html?password=${encodeURIComponent(PW)}&autoconnect=1&resize=scale`;

const DELAYS = [0, 5, 10, 20, 40];   // ms between keystrokes
const TRIALS = 4;
const LEN = 150;

// Random alphanumerics with no repeated neighbours: a dropped key and a doubled key then give
// different diffs instead of both looking like a length change.
const ALPHA = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
let seed = 12345;
const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
const mkString = n => {
  let s = '';
  while (s.length < n) { const c = ALPHA[Math.floor(rnd() * ALPHA.length)]; if (c !== s[s.length - 1]) s += c; }
  return s;
};
const lcs = (a, b) => {
  let prev = new Array(b.length + 1).fill(0);
  for (let i = 1; i <= a.length; i++) {
    const cur = new Array(b.length + 1).fill(0);
    for (let j = 1; j <= b.length; j++) cur[j] = a[i - 1] === b[j - 1] ? prev[j - 1] + 1 : Math.max(prev[j], cur[j - 1]);
    prev = cur;
  }
  return prev[b.length];
};

await launch({ port: PORT, profile: PROFILE, offscreen: true, extra: ['--window-size=1500,950'] });
const { b, page } = await attach(PORT);
await page.setViewportSize({ width: 1440, height: 900 });
await page.goto(URL, { waitUntil: 'domcontentloaded' });
// noVNC's canvas may carry no id or class: query the bare element and check its size.
await page.waitForFunction(() => { const c = document.querySelector('canvas'); return c && c.width > 200 && c.height > 200; }, { timeout: 45000 });
await page.waitForTimeout(2500);
const box = await page.locator('canvas').boundingBox();
await page.mouse.click(box.x + box.width * 0.45, box.y + box.height * 0.4);   // focus the terminal sink
await page.waitForTimeout(800);

const sent = [];
for (const delay of DELAYS) {
  for (let t = 0; t < TRIALS; t++) {
    const s = mkString(LEN), t0 = Date.now();
    await page.keyboard.type(s, { delay });
    await page.keyboard.press('Enter');
    sent.push({ delay, s, cps: Math.round(LEN / ((Date.now() - t0) / 1000)) });
    await page.waitForTimeout(500);
  }
  console.log(`  typed ${TRIALS} trials at delay=${delay}ms`);
}
await page.waitForTimeout(2500);
await b.close();
await closeBrowser(PORT);

const got = execFileSync('ssh', [RIG, 'docker exec vnc-target cat /tmp/trials.txt'], { encoding: 'utf8', maxBuffer: 1 << 22 })
  .split('\n').filter(l => l.length);
console.log(`\nlines sent: ${sent.length}   received: ${got.length}\n\ndelay  eff.cps  exact  mean-loss  worst-loss`);
const per = {};
sent.forEach((row, i) => {
  const rec = got[i] ?? '';
  (per[row.delay] ??= []).push({ loss: (row.s.length - lcs(row.s, rec)) / row.s.length, exact: rec === row.s, cps: row.cps });
});
let fastest = null;
for (const d of DELAYS) {
  const rs = per[d] ?? [];
  const exact = rs.filter(r => r.exact).length;
  const mean = rs.reduce((a, r) => a + r.loss, 0) / rs.length;
  const worst = Math.max(...rs.map(r => r.loss));
  const cps = Math.round(rs.reduce((a, r) => a + r.cps, 0) / rs.length);
  console.log(`${String(d).padStart(4)}ms ${String(cps).padStart(7)} ${String(exact + '/' + rs.length).padStart(7)} ${(mean * 100).toFixed(1).padStart(8)}% ${(worst * 100).toFixed(1).padStart(10)}%`);
  if (exact === rs.length && fastest === null) fastest = { d, cps };
}
console.log(`\nfastest setting with zero loss: ${fastest ? `delay=${fastest.d}ms (~${fastest.cps} chars/s)` : 'none'}`);
await new Promise(r => setTimeout(r, 1500));
try { rmSync(PROFILE, { recursive: true, force: true }); } catch {}
