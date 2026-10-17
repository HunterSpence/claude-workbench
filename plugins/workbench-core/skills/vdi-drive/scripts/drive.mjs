// Drive a canvas-rendered remote desktop from a browser the human already signed into.
// Attaches over CDP. Never handles credentials. Read SKILL.md (authorization gate) first.
// Every command that touches a remote desktop needs --auth=<note file> (or VDI_AUTH_NOTE).
//
//   node drive.mjs launch --auth=<note> [--offscreen]   start Edge/Chrome on :9222, dedicated profile
//   node drive.mjs shot --auth=<note> [name.jpg] [--crop=x,y,w,h] [--scale=0.5] [--full]
//                                       screenshot into the temp shot folder; half-scale JPEG default
//   node drive.mjs seq --auth=<note> [--allow-keys=Enter] click:X,Y type:"text" key:Enter wait:500
//                                       several steps in ONE connection (focus survives); keys
//                                       outside the safe set (Enter, Space, shortcuts) need the
//                                       human to name them in --allow-keys for this run
//   node drive.mjs click|type|key --auth=<note> ...   single steps
//   node drive.mjs canary --auth=<note> --allow-keys=Space   type a symbol-dense line (it holds a space)
//   node drive.mjs clean                delete screenshots (and the profile once the browser is closed)
//   node drive.mjs test                 local self-check against canvas-test.html (no remote desktop)
//
// The remote session is pixels in a canvas: there is no DOM to query, so every action is
// addressed by coordinates read from a screenshot.
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { launch, attach, viewport, assertAscii, closeBrowser, portUp } from './lib.mjs';   // assertAscii: self-test
import { execFileSync } from 'node:child_process';
import { authNotePath, shotPath, SHOT_DIR, allowedExtraKeys, assertKeyAllowed, assertTypeAllowed } from './limits.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.VDI_PORT ?? 9222);
// Outside the working folder, so a signed-in profile is never synced or committed with it.
const PROFILE = process.env.VDI_PROFILE ?? join(tmpdir(), 'vdi-drive', 'profile');
const CANARY = 'ABCabc012 !@#$%^&*()_+-={}[]|\\:";\'<>?,./~`';

// `extra` = keys outside SAFE_KEYS the human confirmed for this run (--allow-keys=Enter,...).
const step = async (page, s, extra) => {
  const [op, ...restParts] = s.split(':');
  const arg = restParts.join(':');
  if (op === 'click') { const [x, y] = arg.split(',').map(Number); await page.mouse.click(x, y); }
  else if (op === 'type') await page.keyboard.type(assertTypeAllowed(arg, extra), { delay: 10 });
  else if (op === 'key') await page.keyboard.press(assertKeyAllowed(arg, extra));
  else if (op === 'wait') await page.waitForTimeout(Number(arg));
  else throw new Error(`unknown step "${s}" (click:X,Y | type:text | key:Name | wait:ms)`);
};

const [cmd, ...argv] = process.argv.slice(2);
const EXTRA_KEYS = allowedExtraKeys(argv);
// Drop --auth (and its value) and --allow-keys so they are never mistaken for a step or a file name.
const rest = argv.filter((a, i) => a !== '--auth' && !a.startsWith('--auth=') && argv[i - 1] !== '--auth'
  && !a.startsWith('--allow-keys='));
// Every command needs the note except the local self-test, clean (deleting screenshots must
// never be blocked) and the usage text.
if (cmd && !['test', 'clean', 'help', '--help', '-h'].includes(cmd)) {
  try { console.log(`authorization note: ${authNotePath(argv, process.env)}`); }
  catch (e) { console.error(e.message); process.exit(2); }
}

if (cmd === 'launch') {
  await launch({ port: PORT, profile: PROFILE, offscreen: rest.includes('--offscreen') });
  console.log(`browser up on :${PORT}, profile ${PROFILE}`);
  console.log('The human signs in and completes MFA now. Then: shot / seq / click / type / key.');
} else if (cmd === 'shot') {
  // Image cost tracks pixel dimensions, not bytes (roughly width x height / 750 tokens), so
  // crop and scale are the real savings.
  const full = rest.includes('--full');
  const crop = rest.find(a => a.startsWith('--crop='))?.split('=')[1];
  const scale = full ? 1 : Number(rest.find(a => a.startsWith('--scale='))?.split('=')[1] ?? 0.5);
  const out = shotPath(rest.find(a => !a.startsWith('--')), full ? 'shot.png' : 'shot.jpg');
  const { b, page } = await attach(PORT);
  const { width, height, cdp } = await viewport(page);
  const [x, y, w, h] = crop ? crop.split(',').map(Number) : [0, 0, width, height];
  const { data } = await cdp.send('Page.captureScreenshot', full
    ? { format: 'png', clip: { x, y, width: w, height: h, scale: 1 } }
    : { format: 'jpeg', quality: 60, clip: { x, y, width: w, height: h, scale } });
  writeFileSync(out, Buffer.from(data, 'base64'));
  console.log(`saved ${out}: ${Math.round(w * scale)}x${Math.round(h * scale)}, ~${Math.round((w * scale * h * scale) / 750)} image tokens`);
  console.log('Frames can be stale on an idle session: confirm against something that changes (a clock) before concluding an action failed.');
  await b.close();
} else if (cmd === 'seq') {
  // Each process opens a new CDP connection and the canvas can lose keyboard focus between them,
  // so click-to-focus, typing and Enter must run in one invocation.
  const { b, page } = await attach(PORT);
  for (const s of rest) { await step(page, s, EXTRA_KEYS); console.log(`ok ${s.startsWith('type:') ? `type:<${s.length - 5} chars>` : s}`); }
  await b.close();
} else if (cmd === 'click' || cmd === 'type' || cmd === 'key') {
  const { b, page } = await attach(PORT);
  await step(page, cmd === 'click' ? `click:${rest[0]},${rest[1]}` : `${cmd}:${rest.join(' ')}`, EXTRA_KEYS);
  console.log(`${cmd} sent; verify with a screenshot`);
  await b.close();
} else if (cmd === 'canary') {
  // The remote session maps physical keys with ITS OWN layout. A mismatch rewrites symbols with no
  // error. Type this into a scratch text field in the session (e.g. an empty editor) and compare.
  const { b, page } = await attach(PORT);
  try { assertTypeAllowed(CANARY, EXTRA_KEYS); }   // the canary holds a space: --allow-keys=Space
  catch (e) { console.error(e.message); await b.close(); process.exit(2); }
  await page.keyboard.type(CANARY, { delay: 40 });
  await page.waitForTimeout(400);
  const out = shotPath(rest[0], 'canary.png');
  await page.screenshot({ path: out });
  console.log(`expected: ${CANARY}\ncompare against ${out}; any mismatch = layout mismatch, fix it before typing anything else`);
  await b.close();
} else if (cmd === 'clean') {
  // Screenshots are copies of the remote desktop: delete them when the task ends.
  rmSync(SHOT_DIR, { recursive: true, force: true });
  console.log(`deleted ${SHOT_DIR}`);
  if (await portUp(PORT)) console.log(`browser still running on :${PORT}: close it, then run clean again to delete the profile`);
  else if (!process.env.VDI_PROFILE) { rmSync(PROFILE, { recursive: true, force: true }); console.log(`deleted ${PROFILE}`); }
} else if (cmd === 'test') {
  const port = PORT + 30, profile = join(tmpdir(), 'vdi-drive', 'selftest-profile');
  await launch({ port, profile, offscreen: true });
  const { b, page } = await attach(port);
  await page.setViewportSize({ width: 1000, height: 620 });
  await page.goto('file:///' + join(HERE, 'canvas-test.html').replace(/\\/g, '/'));   // file:// avoids about:blank's CSP
  await page.waitForTimeout(400);
  const before = await page.evaluate(() => window.__state);
  await step(page, 'click:200,150');
  await step(page, 'type:https://example.com/path?q=1');
  let spaceRefused = false;
  try { await step(page, 'type:a b', new Set()); } catch { spaceRefused = true; }
  let enterRefused = false;
  try { await step(page, 'key:Enter', new Set()); } catch { enterRefused = true; }
  await step(page, 'key:Enter', new Set(['Enter']));
  await page.waitForTimeout(200);
  const after = await page.evaluate(() => window.__state);
  const clickOk = after.clicks === before.clicks + 1;
  const typeOk = after.typed === 'https://example.com/path?q=1' && after.enters === 1;
  let refused = false;
  try { assertAscii('a—b'); } catch { refused = true; }
  console.log(`click reached canvas: ${clickOk ? 'PASS' : 'FAIL'}`);
  console.log(`keystrokes reached canvas exactly: ${typeOk ? 'PASS' : 'FAIL'} (${JSON.stringify(after.typed)})`);
  console.log(`non-ASCII refused: ${refused ? 'PASS' : 'FAIL'}`);
  console.log(`Enter refused without --allow-keys: ${enterRefused ? 'PASS' : 'FAIL'}`);
  console.log(`typed space refused without --allow-keys=Space: ${spaceRefused ? 'PASS' : 'FAIL'}`);
  // The CLI itself must refuse to drive anything without an authorization note.
  let gate = false;
  try { execFileSync(process.execPath, [fileURLToPath(import.meta.url), 'shot'], { env: { ...process.env, VDI_AUTH_NOTE: '' }, stdio: 'pipe' }); }
  catch (e) { gate = e.status === 2; }
  console.log(`no authorization note: refused with exit 2: ${gate ? 'PASS' : 'FAIL'}`);
  await b.close();
  await closeBrowser(port);
  await new Promise(r => setTimeout(r, 1500));
  try { rmSync(profile, { recursive: true, force: true }); } catch {}
  process.exit(clickOk && typeOk && refused && enterRefused && spaceRefused && gate ? 0 : 1);
} else {
  console.log(readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n').slice(0, 18).join('\n'));
}
