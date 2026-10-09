// Test helpers: find an interpreter for the find CLI, run capture as a child process, build a temp workbench home.
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const KIT = path.resolve(HERE, '../../../../..'); // the repository root this plugin sits in
export const CAPTURE = path.join(KIT, 'plugins/workbench-capture/skills/capture/scripts/capture.mjs');
export const FIND_CLI = path.join(KIT, 'plugins/workbench-core/skills/find/scripts/doc_index.py');
export const REQUIRE = process.env.WB_REQUIRE_ALL === '1';

// Where Microsoft Edge lives on this machine (the browser tests need it), or null.
export function edgeInstalled() {
  const win = ['ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'].map((v) => process.env[v] && path.join(process.env[v], 'Microsoft/Edge/Application/msedge.exe'));
  return [...win, '/Applications/Microsoft Edge.app', '/opt/microsoft/msedge/msedge'].filter(Boolean).find((f) => fs.existsSync(f)) ?? null;
}

// WB_TEST_PYTHON, else a sibling "_venvs/knowledge" next to the repository, else whatever python the machine has.
export function knowledgePython() {
  const venv = path.resolve(KIT, '..', '_venvs', 'knowledge', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  for (const c of [process.env.WB_TEST_PYTHON, venv]) if (c && fs.existsSync(c)) return c.replaceAll('\\', '/');
  for (const [cmd, ...args] of ['py -3', 'python3', 'python'].map((c) => c.split(' '))) {
    const r = spawnSync(cmd, [...args, '-c', 'import sys;print(sys.executable)'], { encoding: 'utf8' });
    if (r.status === 0 && r.stdout.trim()) return r.stdout.trim().replaceAll('\\', '/');
  }
  return null;
}

export function tempHome(config = {}) {
  const wb = fs.mkdtempSync(path.join(os.tmpdir(), 'wbcap-')).replaceAll('\\', '/');
  fs.writeFileSync(`${wb}/config.json`, JSON.stringify({ data_root: `${wb}/data`, knowledge_python: knowledgePython(), ...config }));
  return wb;
}

export const fakeClock = (t0 = Date.now()) => {
  const c = { t: t0, sleeps: [], now: () => c.t, sleep: async (ms) => { c.sleeps.push(ms); c.t += ms; } };
  return c;
};

// In-process `capture.mjs ...`: returns {code, out, err}. deps may replace clock, launch, probe, sourcesDir, onContext.
export async function runCapture(main, wb, args, deps = {}) {
  const out = [];
  const err = [];
  const code = await main(args, { env: { WORKBENCH_HOME: wb }, out: (s) => out.push(s), err: (s) => err.push(s), clock: fakeClock(), ...deps });
  const reports = fs.existsSync(`${wb}/capture/runs`) ? fs.readdirSync(`${wb}/capture/runs`).filter((f) => f.endsWith('.json')).sort() : [];
  const report = reports.length ? JSON.parse(fs.readFileSync(`${wb}/capture/runs/${reports.at(-1)}`, 'utf8')) : null;
  return { code, out: out.join('\n'), err: err.join('\n'), report };
}

// `node capture.mjs ...` as a real child process (asynchronous, so a fixture server in this process keeps answering).
export function spawnCapture(wb, args, env = {}) {
  return new Promise((resolve) => {
    const p = spawn(process.execPath, [CAPTURE, ...args], { env: { ...process.env, WORKBENCH_HOME: wb, WB_FIND_LAZY: '0', ...env } });
    let stdout = '';
    let stderr = '';
    p.stdout.on('data', (d) => (stdout += d));
    p.stderr.on('data', (d) => (stderr += d));
    p.on('close', (code) => resolve({ code, stdout, stderr }));
  });
}

export function findCli(py, args, env = {}) {
  const r = spawnSync(py, [FIND_CLI, ...args], { encoding: 'utf8', env: { ...process.env, WB_FIND_LAZY: '0', PYTHONUTF8: '1', ...env } });
  return { code: r.status, out: r.stdout, err: r.stderr };
}

export function walkMd(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walkMd(path.join(dir, e.name)) : e.name.endsWith('.md') ? [path.join(dir, e.name).replaceAll('\\', '/')] : []));
}
