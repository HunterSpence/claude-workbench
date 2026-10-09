import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';

const SCRIPTS = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'skills', 'capture', 'scripts');
const files = (d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.name === 'node_modules' ? [] : e.isDirectory() ? files(path.join(d, e.name)) : [path.join(d, e.name)]));

// Nothing in scripts/ may read a session secret, attach to a running browser, or reach the network outside the guarded page.
const FORBIDDEN = [
  /cookies\s*\(/i, /storageState/i, /localStorage/i, /sessionStorage/i, /indexedDB/i, /authorization/i,
  /\.headers\s*\(/, /headerValue\s*\(/, /allHeaders\s*\(/, /connectOverCDP/, /\bfetch\s*\(/, /node:https?['"]/, /node:net['"]/,
];

describe('no secret access in scripts/ (static)', () => {
  const src = files(SCRIPTS).filter((f) => /\.(mjs|js|json)$/.test(f) && !/package-lock/.test(f));
  it('finds the scripts to scan', () => assert.ok(src.length >= 8, `only ${src.length} files`));
  for (const re of FORBIDDEN) {
    it(`no ${re}`, () => {
      const hits = src.filter((f) => re.test(fs.readFileSync(f, 'utf8'))).map((f) => path.relative(SCRIPTS, f));
      assert.deepEqual(hits, []);
    });
  }
});
