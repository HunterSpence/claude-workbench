import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { createPacer, PacingCap } from '../skills/capture/scripts/pacing.mjs';

const fakeClock = (t0 = 1_700_000_000_000) => {
  const c = { t: t0, sleeps: [], now: () => c.t, async sleep(ms) { c.sleeps.push(ms); c.t += ms; } };
  return c;
};

describe('pacing (fake clock)', () => {
  it('the 11th action inside 60 s waits for the minute window', async () => {
    const clock = fakeClock();
    const t0 = clock.t;
    const p = createPacer({ clock, rand: () => 0 });
    const at = [];
    for (let i = 0; i < 11; i++) { await p.take(); at.push(clock.now() - t0); }
    assert.ok(at[9] < 60_000, 'the first ten fit inside one minute');
    assert.ok(at[10] >= 60_000, `the 11th must wait until the first one is a minute old (was ${at[10]})`);
    assert.equal(p.count, 11);
  });

  it('never allows more than 10 in any rolling 60 s over a long run', async () => {
    const clock = fakeClock();
    const p = createPacer({ clock });
    const at = [];
    for (let i = 0; i < 60; i++) { await p.take(); at.push(clock.now()); }
    for (let i = 0; i + 10 < at.length; i++) assert.ok(at[i + 10] - at[i] >= 60_000, `window starting at ${i}`);
  });

  it('the 201st action inside an hour is refused until the window moves', async () => {
    const clock = fakeClock();
    const p = createPacer({ clock, rand: () => 0 });
    const first = clock.t;
    for (let i = 0; i < 200; i++) await p.take();
    assert.ok(clock.t - first < 3_600_000, '200 actions at the minute cap take about 20 minutes');
    await assert.rejects(p.take(), (e) => e instanceof PacingCap && e.retryAt >= first + 3_600_000);
    assert.equal(p.count, 200, 'a refused action is not counted');
    clock.t = first + 3_600_000 + 1;
    await p.take();
    assert.equal(p.count, 201);
  });

  it('jitter stays inside its bounds', async () => {
    for (const r of [0, 0.5, 0.999999]) {
      const clock = fakeClock();
      const p = createPacer({ clock, rand: () => r, jitter: [800, 2400] });
      for (let i = 0; i < 5; i++) await p.take();
      assert.equal(clock.sleeps.length, 4, 'no pause before the first action');
      for (const s of clock.sleeps) assert.ok(s >= 800 && s <= 2400, `jitter ${s}`);
    }
    const clock = fakeClock();
    const p = createPacer({ clock });
    for (let i = 0; i < 8; i++) await p.take();
    assert.ok(clock.sleeps.every((s) => s >= 800 && s <= 2400));
    assert.ok(new Set(clock.sleeps).size > 1, 'random jitter varies');
  });

  it('--max-per-hour can lower the cap but never raise it', async () => {
    const low = createPacer({ clock: fakeClock(), perHour: 3 });
    for (let i = 0; i < 3; i++) await low.take();
    await assert.rejects(low.take(), PacingCap);
    const clock = fakeClock();
    const high = createPacer({ clock, perHour: 5000, rand: () => 0 });
    for (let i = 0; i < 200; i++) await high.take();
    await assert.rejects(high.take(), PacingCap);
  });

  it('earlier actions still inside the hour count against the cap (a new run does not start from zero)', async () => {
    const clock = fakeClock();
    const history = Array.from({ length: 200 }, (_, i) => clock.t - 3_000_000 + i * 1000);
    const p = createPacer({ clock, history });
    await assert.rejects(p.take(), (e) => e instanceof PacingCap && e.retryAt === history[0] + 3_600_000);
    clock.t = history[0] + 3_600_000;
    await p.take();
    assert.equal(p.count, 1);
    assert.equal(p.stamps.at(-1), clock.t, 'the new action joined the window');
  });
});
