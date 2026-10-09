#!/usr/bin/env node
// capture: read the user's work surfaces through a dedicated, signed-in Edge profile (or the OneDrive sync folder)
// into Markdown the knowledge layer can search. Read-only, paced, scoped. See ../references/guardrails.md.
//   capture.mjs login | run --source NAME [flags] | scope add|remove|list|set | status | purge | logout | --version
// Exit codes: 0 done, 3 stopped by an interstitial or policy (a report is written), 4 error.
import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import { ASK } from './interstitial.mjs';
import { Refused, Stop, makeActions, watch } from './actions.mjs';
import { createPacer, PacingCap, realClock } from './pacing.mjs';
import * as S from './scope.mjs';
import { cleanUrl, createWriter, isoSeconds, purgeSource } from './writer.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const VERSION = JSON.parse(fs.readFileSync(path.join(HERE, 'package.json'), 'utf8')).version;
const OWN_SOURCES = ['intranet', 'shared-files', 'teams']; // what `purge` clears when no --source is given
const fwd = (p) => String(p).replaceAll('\\', '/');

export function paths(env = process.env) {
  const wb = fwd(env.WORKBENCH_HOME || path.join(env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), '.claude'), 'workbench'));
  let cfg = {};
  try { cfg = JSON.parse(fs.readFileSync(`${wb}/config.json`, 'utf8').replace(/^﻿/, '')); } catch { /* no config yet */ }
  const cap = `${wb}/capture`;
  return { wb, cap, cfg, profile: `${cap}/profile`, scopeFile: `${cap}/scope.json`, runs: `${cap}/runs`, local: `${cap}/local`, data: fwd(cfg.data_root || path.join(os.homedir(), 'Workbench')) };
}

// ---- Edge policy -----------------------------------------------------------------------------------------------
function regQuery(key, name) {
  if (process.platform !== 'win32') return null;
  try {
    const out = execFileSync('reg', ['query', key, '/v', name], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
    const m = /REG_DWORD\s+(0x[0-9a-f]+)/i.exec(out);
    return m ? parseInt(m[1], 16) : null;
  } catch { return null; }
}
// A policy that is not set allows the feature; only an explicit 0 turns it off.
export function probePolicies(query = regQuery) {
  const get = (n) => ['HKLM', 'HKCU'].map((h) => query(`${h}\\SOFTWARE\\Policies\\Microsoft\\Edge`, n)).find((v) => v !== null) ?? null;
  const raw = { RemoteDebuggingAllowed: get('RemoteDebuggingAllowed'), HeadlessModeEnabled: get('HeadlessModeEnabled') };
  return { remoteDebuggingAllowed: raw.RemoteDebuggingAllowed !== 0, headlessAllowed: raw.HeadlessModeEnabled !== 0, raw };
}

// ---- browser ---------------------------------------------------------------------------------------------------
export async function launch({ profile, headless }) {
  if (/Microsoft[\\/]+Edge[\\/]+User Data/i.test(profile)) throw new Error("refusing to use Edge's own profile folder; capture keeps a separate one");
  const { chromium } = await import('playwright-core').catch((e) => { throw new Error(`playwright-core is not installed (${e.code}); run "npm install --ignore-scripts" in ${HERE}`); });
  return chromium.launchPersistentContext(profile, { channel: 'msedge', headless, acceptDownloads: true, viewport: { width: 1280, height: 900 } });
}

// ---- sources (interface I24) -----------------------------------------------------------------------------------
export async function loadSources(dir) {
  const sources = new Map();
  const bad = [];
  for (const f of fs.readdirSync(dir).filter((x) => x.endsWith('.mjs')).sort()) {
    try {
      const m = (await import(pathToFileURL(path.join(dir, f)).href)).default;
      const ok = m && /^[a-z][a-z0-9-]*$/.test(m.name) && typeof m.run === 'function' && typeof m.experimental === 'boolean' && m.selectors && typeof m.selectors === 'object';
      if (!ok) throw new Error('needs name, experimental, selectors and run()');
      sources.set(m.name, m);
    } catch (e) { bad.push(`${f}: ${e.message}`); }
  }
  return { sources, bad };
}

// `find convert` (interface I4): the CLI is looked up, never assumed.
function converter(P, env) {
  const cli = [env.WORKBENCH_FIND_CLI, `${P.wb}/kit/plugins/workbench-core/skills/find/scripts/doc_index.py`, path.resolve(HERE, '../../../../workbench-core/skills/find/scripts/doc_index.py')]
    .filter(Boolean).find((f) => fs.existsSync(f));
  const py = P.cfg.knowledge_python ? [P.cfg.knowledge_python] : process.platform === 'win32' ? ['py', '-3'] : ['python3'];
  return (file, includeLabelled = false) => {
    if (!cli) throw new Error('the find CLI was not found (set WORKBENCH_FIND_CLI or install the workbench-core plugin)');
    const r = spawnSync(py[0], [...py.slice(1), cli, 'convert', file, ...(includeLabelled ? ['--include-labelled'] : []), '--json'],
      { encoding: 'utf8', env: { ...process.env, ...env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' }, maxBuffer: 256 * 1024 * 1024, timeout: 180000 });
    if (r.status !== 0) throw new Error(`find convert failed (exit ${r.status})`);
    return JSON.parse(r.stdout);
  };
}

const quiet = (m) => String(m).replace(/(https?:\/\/[^\s?#"')]+)[?#][^\s"')]*/g, '$1').slice(0, 300); // no query strings in reports

function infosecNote(P) {
  const f = [`${P.wb}/kit/bootstrap/infosec-note.txt`, path.resolve(HERE, '../../../../../bootstrap/infosec-note.txt')].find((x) => fs.existsSync(x));
  return f ? fs.readFileSync(f, 'utf8').trim() : 'Tell your security team before the first full run (see references/pre-clearance.md).';
}

// The hourly cap must hold across runs, so the last hour of action times is kept next to the run reports.
const readPace = (file, now) => {
  try { return fs.readFileSync(file, 'utf8').split('\n').map(Number).filter((t) => t > now - 3_600_000 && t <= now + 60_000); } catch { return []; }
};
const writePace = (file, stamps) => { try { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, `${stamps.join('\n')}\n`); } catch { /* best effort */ } };

function writeReport(P, rep, now) {
  fs.mkdirSync(P.runs, { recursive: true });
  const stamp = isoSeconds(now).replace(/[-:]/g, '');
  for (let n = 0; ; n++) {
    const f = `${P.runs}/${stamp}${n ? `-${n}` : ''}.json`;
    try { fs.writeFileSync(f, `${JSON.stringify(rep, null, 2)}\n`, { flag: 'wx' }); return f; } catch (e) { if (e.code !== 'EEXIST') throw e; }
  }
}

// ---- run -------------------------------------------------------------------------------------------------------
async function cmdRun(o, d) {
  const { P, out, clock } = d;
  const scope = S.load(o.scope ?? P.scopeFile);
  const { sources, bad } = await loadSources(d.sourcesDir);
  const src = sources.get(o.source);
  if (!o.source || !src) throw new Error(`unknown source "${o.source ?? ''}" (have: ${[...sources.keys()].join(', ')})${bad.length ? `; failed to load: ${bad.join('; ')}` : ''}`);
  if (src.experimental && !o.experimental) throw new Error(`${src.name} is experimental: add --experimental to run it`);
  const perHour = o['max-per-hour'] === undefined ? 200 : Number(o['max-per-hour']);
  if (!(perHour >= 1)) throw new Error('--max-per-hour must be 1 or more');
  const first = !fs.existsSync(P.runs) || !fs.readdirSync(P.runs).some((f) => f.endsWith('.json'));
  if (first) out(infosecNote(P));

  const browser = src.browser !== false;
  const pol = d.probe();
  const state = { violations: [], blockedNav: null, stopped: null };
  const paceFile = `${P.runs}/pace.txt`;
  const pacer = createPacer({ clock, perHour, rand: d.rand, history: readPace(paceFile, clock.now()) });
  const rep = { version: 1, tool: `capture ${VERSION}`, source: src.name, experimental: !!src.experimental, label: src.experimental ? 'experimental' : null,
    dry_run: !!o['dry-run'], headed: false, started: isoSeconds(clock.now()), finished: null, status: 'running', exit: null, stop: null, error: null,
    policy: pol.raw, counts: {}, entries: [], skipped: [], notes: [] };
  const base = scope.placement[src.name] === 'local' ? P.local : `${P.data}/captured`;
  const writer = createWriter({ base, source: src.name, clock, retentionDays: scope.retention_days, dry: rep.dry_run });
  const stop = (reason, kind = 'module') => { state.stopped ??= new Stop(kind, String(reason)); throw state.stopped; };
  let context = null;
  let actions = null;
  try {
    if (browser) {
      if (!pol.remoteDebuggingAllowed) stop('browser automation is turned off by an Edge policy (RemoteDebuggingAllowed)', 'policy');
      if (src.selectors.account && !scope.tenant) throw new Error('set the tenant first: capture scope set tenant <your tenant domain>');
      rep.headed = !!o.headed || !pol.headlessAllowed;
      context = await d.launch({ profile: P.profile, headless: !rep.headed });
      if (d.onContext) await d.onContext(context);
      const page = context.pages()[0] ?? (await context.newPage());
      const hosts = S.hosts(scope, src.name);
      const hostAllowed = (h) => hosts.has(h);
      await watch({ context, page, state, hostAllowed });
      actions = makeActions({ page, selectors: src.selectors, hostAllowed, isDenied: (u) => S.isDenied(scope, src.name, u), pacer, state, tenant: scope.tenant });
    }
    const need = (f) => (...a) => { if (!actions) throw new Refused(`${src.name} does not use a browser`); return actions[f](...a); };
    const ctx = {
      scope: S.entries(scope, src.name), deny: S.denies(scope, src.name), selectors: src.selectors, clock, dry: rep.dry_run, includeLabelled: !!o['include-labelled'],
      settings: { tenant: scope.tenant, sync_root: scope.sync_root, max_depth: scope.max_depth, max_pages: scope.max_pages, max_files: scope.max_files },
      log: (m) => { if (rep.notes.length < 200) rep.notes.push(quiet(m)); },
      inScope: actions ? actions.inScope : () => false,
      isDenied: (k) => S.isDenied(scope, src.name, k),
      goto: need('goto'), click: need('click'), search: need('search'), download: need('download'), text: need('text'), snapshot: need('snapshot'),
      pace: async () => { if (state.stopped) throw state.stopped; try { await pacer.take(); } catch (e) { if (e instanceof PacingCap) stop(e.message, 'pacing'); throw e; } },
      convert: d.convert,
      write: (item) => { const e = writer.write({ ...item, scope: item.scope ?? '' }); rep.entries.push(e); return e; },
      report: (e) => rep.skipped.push({ url: cleanUrl(e.url ?? ''), reason: String(e.reason ?? '') }),
      stop: (reason) => stop(reason),
    };
    await src.run(ctx);
    if (actions) actions.finish();
    rep.status = 'done';
    rep.exit = 0;
  } catch (e) {
    if (e instanceof Stop || e instanceof Refused) {
      rep.status = 'stopped';
      rep.exit = 3;
      rep.stop = e instanceof Stop ? { kind: e.kind, reason: quiet(e.message), url: e.url, ask: ASK[e.kind] ?? null } : { kind: 'refused', reason: quiet(e.message), url: null, ask: null };
    } else {
      rep.status = 'error';
      rep.exit = 4;
      rep.error = quiet(e.message);
    }
  } finally {
    writePace(paceFile, pacer.stamps);
    if (context) await context.close().catch(() => {});
  }
  rep.finished = isoSeconds(clock.now());
  rep.counts = { written: rep.entries.length, skipped: rep.skipped.length, paced: pacer.count };
  const file = writeReport(P, rep, clock.now());
  out(JSON.stringify({ status: rep.status, exit: rep.exit, source: src.name, experimental: rep.experimental, report: file, written: rep.counts.written, skipped: rep.counts.skipped, stop: rep.stop }));
  return rep.exit;
}

async function cmdLogin(o, d) {
  const { P, out } = d;
  const pol = d.probe();
  if (!pol.remoteDebuggingAllowed) { out(`stopped: ${ASK.policy}`); return 3; }
  const scope = S.load(o.scope ?? P.scopeFile);
  const start = Object.values(scope.scope).flat().find((u) => /^https?:\/\//i.test(u));
  const context = await d.launch({ profile: P.profile, headless: false });
  const page = context.pages()[0] ?? (await context.newPage());
  if (start) await page.goto(start).catch(() => {});
  out('Sign in in the window that opened (finish any second step yourself), then close the window.');
  await new Promise((r) => context.on('close', r));
  return 0;
}

function cmdScope(pos, o, d) {
  const { P, out } = d;
  const file = o.scope ?? P.scopeFile;
  const s = S.load(file);
  const [, sub, a, b] = pos;
  if (sub === 'list') {
    const pick = (book) => (o.source ? { [o.source]: book[o.source] ?? [] } : book);
    out(JSON.stringify({ file, tenant: s.tenant, retention_days: s.retention_days, sync_root: s.sync_root ?? '', placement: s.placement, scope: pick(s.scope), deny: pick(s.deny) }, null, 2));
    return 0;
  }
  if (sub === 'add') out(`added ${S.add(s, o.source, a, o.deny)}`);
  else if (sub === 'remove') out(S.remove(s, o.source, a, o.deny) ? 'removed' : 'not in the list');
  else if (sub === 'set') { S.set(s, a, b); out(`set ${a}`); }
  else throw new Error('usage: scope add|remove|list|set [--source S] [--deny] VALUE');
  S.save(file, s);
  return 0;
}

function cmdPurge(o, d) {
  const days = o['older-than'] === undefined ? null : Number(o['older-than']);
  if (days !== null && !(days >= 0)) throw new Error('--older-than needs a number of days');
  const res = [];
  for (const source of o.source ? [o.source] : OWN_SOURCES) for (const base of [`${d.P.data}/captured`, d.P.local]) res.push(purgeSource(base, source, days, d.clock.now()));
  d.out(JSON.stringify({ purged: res.filter((r) => r.removed || r.kept), removed: res.reduce((n, r) => n + r.removed, 0) }));
  return 0;
}

function cmdStatus(d) {
  const { P, out } = d;
  const s = S.load(P.scopeFile);
  const runs = fs.existsSync(P.runs) ? fs.readdirSync(P.runs).filter((f) => f.endsWith('.json')).sort() : [];
  let last = null;
  if (runs.length) { const r = JSON.parse(fs.readFileSync(`${P.runs}/${runs.at(-1)}`, 'utf8')); last = { file: runs.at(-1), source: r.source, status: r.status, written: r.counts?.written ?? 0 }; }
  out(JSON.stringify({ version: VERSION, profile: fs.existsSync(P.profile), tenant_set: !!s.tenant, scope: Object.fromEntries(Object.entries(s.scope).map(([k, v]) => [k, v.length])),
    deny: Object.fromEntries(Object.entries(s.deny).map(([k, v]) => [k, v.length])), policy: d.probe().raw, last_run: last }, null, 2));
  return 0;
}

export async function main(argv, deps = {}) {
  const env = deps.env ?? process.env;
  const out = deps.out ?? ((s) => console.log(s));
  const P = paths(env);
  const d = { P, out, clock: deps.clock ?? realClock, rand: deps.rand, sourcesDir: deps.sourcesDir ?? path.join(HERE, 'sources'),
    probe: deps.probe ?? probePolicies, launch: deps.launch ?? launch, onContext: deps.onContext, convert: deps.convert ?? converter(P, env) };
  try {
    const { values: o, positionals: pos } = parseArgs({ args: argv, allowPositionals: true, options: {
      source: { type: 'string' }, scope: { type: 'string' }, headed: { type: 'boolean' }, 'max-per-hour': { type: 'string' }, 'include-labelled': { type: 'boolean' },
      'dry-run': { type: 'boolean' }, experimental: { type: 'boolean' }, deny: { type: 'boolean' }, 'older-than': { type: 'string' }, version: { type: 'boolean' } } });
    if (o.version) { out(`capture ${VERSION}`); return 0; }
    switch (pos[0]) {
      case 'run': return await cmdRun(o, d);
      case 'login': return await cmdLogin(o, d);
      case 'scope': return cmdScope(pos, o, d);
      case 'purge': return cmdPurge(o, d);
      case 'status': return cmdStatus(d);
      case 'logout': fs.rmSync(P.profile, { recursive: true, force: true }); out('signed out: the capture browser profile was removed'); return 0;
      default: throw new Error('usage: capture.mjs login | run --source NAME | scope add|remove|list|set | status | purge | logout | --version');
    }
  } catch (e) {
    (deps.err ?? console.error)(`capture: ${quiet(e.message)}`);
    return 4;
  }
}

if (process.argv[1] && fwd(path.resolve(process.argv[1])).toLowerCase() === fwd(fileURLToPath(import.meta.url)).toLowerCase()) {
  process.exitCode = await main(process.argv.slice(2));
}
