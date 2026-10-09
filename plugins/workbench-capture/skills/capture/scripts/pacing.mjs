// Human pacing: at most `perMinute` paced actions in any 60 s and `perHour` in any 60 min, with a random pause
// before every action. A page load, a click, a download and a file read each count as one action.
// The clock is injectable ({now(): ms, sleep(ms): Promise}) so tests never wait in real time.

export const realClock = { now: () => Date.now(), sleep: (ms) => new Promise((r) => setTimeout(r, ms)) };

export const HOUR_CAP = 200;
export const MINUTE_CAP = 10;

export class PacingCap extends Error {
  constructor(retryAt) {
    super(`hourly cap reached; the window moves at ${new Date(retryAt).toISOString()}`);
    this.name = 'PacingCap';
    this.retryAt = retryAt;
  }
}

// perHour can only be lowered (--max-per-hour N), never raised above HOUR_CAP.
// `history` = timestamps (ms) of earlier actions still inside the hour, so the cap holds across consecutive runs.
export function createPacer({ clock = realClock, perMinute = MINUTE_CAP, perHour = HOUR_CAP, jitter = [800, 2400], rand = Math.random, history = [] } = {}) {
  perHour = Math.min(perHour, HOUR_CAP);
  perMinute = Math.min(perMinute, MINUTE_CAP);
  const stamps = [...history].sort((a, b) => a - b);
  let total = 0;
  return {
    get count() { return total; },
    get stamps() { return [...stamps]; },
    async take() {
      if (stamps.length) await clock.sleep(jitter[0] + rand() * (jitter[1] - jitter[0]));
      for (;;) {
        const now = clock.now();
        while (stamps.length && now - stamps[0] >= 3_600_000) stamps.shift();
        if (stamps.length >= perHour) throw new PacingCap(stamps[0] + 3_600_000);
        const recent = stamps.filter((t) => now - t < 60_000);
        if (recent.length < perMinute) break;
        await clock.sleep(recent[recent.length - perMinute] + 60_000 - now); // until the oldest counted action leaves the minute
      }
      stamps.push(clock.now());
      total++;
    },
  };
}
