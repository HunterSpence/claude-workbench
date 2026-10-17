// Limits for remote-desktop work, in one file so they can be copied into a project in one
// step: the excluded action set and safe keys (section 3) and the authorization-note,
// screenshot-path and typing checks drive.mjs uses (section 4). A template: fill in the screen
// map for the job you are doing.
//
// The principle: a control that depends on the agent reading a screen correctly is not a
// control. The agent will eventually misread something; each of these still holds when it does.
//
// Node stdlib only. ESM.
import { readFileSync, mkdirSync, statSync } from 'node:fs';
import { join, basename, dirname, resolve } from 'node:path';
import { tmpdir } from 'node:os';

// ---------------------------------------------------------------------------
// 3. The excluded action set
// ---------------------------------------------------------------------------
// Save / Confirm / Create / Delete are not a rule the agent is asked to follow: they are
// coordinates that are never wired into its available actions. `loadScreenMap` throws if a
// map even DECLARES a commit control, so those coordinates cannot enter the agent's reach
// by editing a map file. The human clicks Save.
const COMMIT_WORDS = new Set([
  'save', 'confirm', 'create', 'delete', 'remove', 'submit', 'apply', 'ok', 'yes',
  'enable', 'disable', 'publish', 'authorize', 'authorise', 'grant', 'connect',
  'register', 'add', 'update', 'install', 'activate', 'deactivate', 'revoke', 'approve',
  'finish', 'done', 'continue', 'next', 'accept', 'allow', 'trust', 'send', 'upload', 'export',
]);
const wordsOf = s => String(s ?? '').replace(/([a-z0-9])([A-Z])/g, '$1 $2')
  .split(/[^A-Za-z0-9]+/).map(w => w.toLowerCase()).filter(Boolean);

export const looksLikeCommitControl = (...strings) =>
  strings.some(s => wordsOf(s).some(w => COMMIT_WORDS.has(w)));

/** { screen, anchor:{x,y,w,h}, fields: { name: {dx,dy,label} } }, anchor-relative only.
 *  Absolute coordinates are rejected: any scroll, resize, modal or reconnect invalidates
 *  them, and a stale absolute click lands somewhere nobody predicted. */
export const loadScreenMap = map => {
  if (!map?.screen) throw new Error('screen map needs a screen name');
  if (!map.anchor || ['x', 'y', 'w', 'h'].some(k => typeof map.anchor[k] !== 'number')) {
    throw new Error(`screen map "${map.screen}" needs an anchor {x,y,w,h}`);
  }
  for (const [name, f] of Object.entries(map.fields ?? {})) {
    if (looksLikeCommitControl(name, f?.label)) {
      throw new Error(`screen map "${map.screen}" declares commit control "${name}": those are human-only`);
    }
    if (typeof f?.dx !== 'number' || typeof f?.dy !== 'number') {
      throw new Error(`field "${name}" must be anchor-relative {dx,dy}, not absolute coordinates`);
    }
  }
  return Object.freeze({ ...map, fields: Object.freeze({ ...(map.fields ?? {}) }) });
};

/** Keys that cannot commit a form. Enter/NumpadEnter/Space are absent deliberately:
 *  Enter submits, Space activates a focused button. Delete is absent too: on a focused file, message
 *  or grid row it deletes, often without a confirmation, so it needs --allow-keys. */
export const SAFE_KEYS = new Set([
  'Tab', 'Shift+Tab', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'Home', 'End', 'PageUp', 'PageDown', 'Escape', 'Backspace',
]);

// ---------------------------------------------------------------------------
// 4. The authorization note and where screenshots go
// ---------------------------------------------------------------------------
// drive.mjs will not touch a remote desktop until it is pointed at a local note recording who
// authorised automated input, for which desktop and task, and until when. The note is read for
// presence only; its text is never printed or sent anywhere.
export const authNotePath = (argv = [], env = {}) => {
  const i = argv.findIndex(a => a === '--auth' || a.startsWith('--auth='));
  const raw = i < 0 ? env.VDI_AUTH_NOTE : argv[i].startsWith('--auth=') ? argv[i].slice(7) : argv[i + 1];
  if (!raw) throw new Error('REFUSED: no authorization note. Pass --auth=<file> (or set VDI_AUTH_NOTE): '
    + 'a local note naming who authorised automated input, for which desktop and task, until when. See SKILL.md.');
  const p = resolve(raw);
  let st;
  try { st = statSync(p); } catch { throw new Error(`REFUSED: authorization note not found: ${p}`); }
  if (!st.isFile() || readFileSync(p, 'utf8').trim().length < 20) {
    throw new Error(`REFUSED: authorization note is empty, too short or not a file: ${p}`);
  }
  return p;
};

// Screenshots hold whatever is on the remote desktop, so they never land in the working folder
// (which may be synced or committed). Only the base name of a requested path is kept.
export const SHOT_DIR = join(tmpdir(), 'vdi-drive', 'shots');
export const shotPath = (name, fallback) => {
  mkdirSync(SHOT_DIR, { recursive: true });
  const base = basename(String(name || fallback)).replace(/[^A-Za-z0-9._-]/g, '_');
  return join(SHOT_DIR, /\.(png|jpe?g)$/i.test(base) ? base : `${base}.png`);
};

// A key outside SAFE_KEYS (Enter, Space, shortcuts) can commit whatever has focus. drive.mjs sends
// one only when the human named it for this invocation: --allow-keys=Enter[,Space,...].
export const allowedExtraKeys = (argv = []) => new Set(argv.filter(a => a.startsWith('--allow-keys='))
  .flatMap(a => a.slice('--allow-keys='.length).split(',')).map(k => k.trim()).filter(Boolean));
export const assertKeyAllowed = (key, extra = new Set()) => {
  if (SAFE_KEYS.has(key) || extra.has(key)) return key;
  throw new Error(`REFUSED: "${key}" can commit a form. The human must confirm it for this run: --allow-keys=${key}`);
};
// keyboard.type() turns a newline into an Enter press, a space into a Space press (which activates a focused
// button) and a tab into a focus move, so typed text is held to the same rule: each needs the human's per-run OK.
export const assertTypeAllowed = (text, extra = new Set()) => {
  if (/[\r\n]/.test(text) && !extra.has('Enter')) throw new Error('REFUSED: a newline in typed text presses Enter; confirm it with --allow-keys=Enter');
  if (/ /.test(text) && !extra.has('Space')) throw new Error('REFUSED: a space in typed text presses Space, which activates a focused button; confirm it with --allow-keys=Space');
  if (/\t/.test(text) && !extra.has('Tab')) throw new Error('REFUSED: a tab in typed text moves focus; confirm it with --allow-keys=Tab');
  return assertAscii(text);
};

export const assertAscii = text => {
  const bad = [...new Set([...String(text)].filter(c => c.codePointAt(0) > 127))];
  if (bad.length) throw new Error(`REFUSED: non-ASCII is sent via Input.insertText, raises no keydown, and a canvas drops it silently: ${bad.join(' ')}`);
  return text;
};

// ---------------------------------------------------------------------------
// self-check: node limits.mjs
// ---------------------------------------------------------------------------
if (process.argv[1]?.endsWith('limits.mjs')) {
  const { mkdtempSync, rmSync, writeFileSync } = await import('node:fs');
  const A = (c, l) => console.log(`${c ? 'PASS' : 'FAIL'}  ${l}`) || (c ? 0 : process.exitCode = 1);
  const good = { screen: 's', anchor: { x: 0, y: 0, w: 1, h: 1 }, fields: { fieldA: { dx: 1, dy: 1, label: 'Field A' }, fieldB: { dx: 1, dy: 2, label: 'Field B' }, fieldC: { dx: 1, dy: 3, label: 'Field C' } } };
  A(!!loadScreenMap(good), 'a field-only screen map loads');
  for (const bad of ['save', 'Confirm', 'create_item', 'deleteThing', 'sendReport']) {
    let t = false;
    try { loadScreenMap({ ...good, fields: { [bad]: { dx: 1, dy: 1 } } }); } catch { t = true; }
    A(t, `screen map rejects commit control "${bad}"`);
  }
  let t2 = false; try { loadScreenMap({ ...good, fields: { a: { x: 1, y: 1 } } }); } catch { t2 = true; }
  A(t2, 'absolute coordinates are rejected');
  A(!SAFE_KEYS.has('Enter') && !SAFE_KEYS.has('Space'), 'Enter and Space are not in the safe key set');
  A(!SAFE_KEYS.has('Delete'), 'Delete is not in the safe key set: it deletes the focused item');
  let t3 = false; try { assertAscii('a—b'); } catch { t3 = true; }
  A(t3, 'non-ASCII typing is refused');

  const refuses = (argv, env) => { try { authNotePath(argv, env); return false; } catch { return true; } };
  const nd = mkdtempSync(join(tmpdir(), 'vdi-auth-'));
  const note = join(nd, 'auth.txt'), empty = join(nd, 'empty.txt');
  writeFileSync(note, 'Authorised by: <owner>. Desktop: <name>. Task: <task>. Until: <date>.\n');
  writeFileSync(empty, '  \n');
  A(refuses([], {}), 'no authorization note: refused');
  A(refuses(['--auth=' + join(nd, 'missing.txt')], {}), 'missing authorization note: refused');
  A(refuses(['--auth', empty], {}), 'empty authorization note: refused');
  A(refuses(['--auth', nd], {}), 'a directory is not an authorization note');
  A(authNotePath(['--auth', note], {}) === note && authNotePath([], { VDI_AUTH_NOTE: note }) === note,
    'an authorization note is accepted by flag or VDI_AUTH_NOTE');
  rmSync(nd, { recursive: true, force: true });
  let k1 = false; try { assertKeyAllowed('Enter'); } catch { k1 = true; }
  A(k1, 'Enter is refused without a human-confirmed --allow-keys');
  A(assertKeyAllowed('Enter', allowedExtraKeys(['--allow-keys=Enter'])) === 'Enter', '--allow-keys=Enter lets Enter through');
  A(assertKeyAllowed('Tab') === 'Tab', 'a safe key needs no override');
  let kDel = false; try { assertKeyAllowed('Delete'); } catch { kDel = true; }
  A(kDel && assertKeyAllowed('Delete', allowedExtraKeys(['--allow-keys=Delete'])) === 'Delete', 'Delete needs --allow-keys=Delete');
  let k2 = false; try { assertKeyAllowed('Control+s', allowedExtraKeys(['--allow-keys=Enter'])); } catch { k2 = true; }
  A(k2, 'an override names keys one by one (Control+s still refused)');
  let k3 = false; try { assertTypeAllowed('abc\n'); } catch { k3 = true; }
  A(k3 && assertTypeAllowed('abc\n', new Set(['Enter'])) === 'abc\n', 'a typed newline counts as Enter');
  let k4 = false; try { assertTypeAllowed('a b'); } catch { k4 = true; }
  A(k4 && assertTypeAllowed('a b', new Set(['Space'])) === 'a b', 'a typed space needs --allow-keys=Space');
  let k5 = false; try { assertTypeAllowed('a\tb'); } catch { k5 = true; }
  A(k5 && assertTypeAllowed('a\tb', new Set(['Tab'])) === 'a\tb', 'a typed tab needs --allow-keys=Tab');

  const sp = shotPath('../../somewhere/else/s.jpg', 'shot.jpg');
  A(sp.startsWith(SHOT_DIR) && basename(sp) === 's.jpg', 'screenshot paths are forced into the temp shot folder');
  A(dirname(shotPath('', 'shot.jpg')) === SHOT_DIR, 'the default screenshot never lands in the working folder');
}
