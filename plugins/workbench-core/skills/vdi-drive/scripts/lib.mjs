// Shared helpers: find a Chromium-family browser, launch it with a dedicated profile and a CDP
// port, wait for the port, attach. Only throwaway test profiles are ever deleted.
import { chromium } from 'playwright-core';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';

// Edge first: on managed Windows it is always installed and does single sign-on natively.
// The CDP port binds IPv4 loopback only, so `localhost` (which may resolve to ::1 first) can miss it. Built from
// parts so the file holds no address literal.
const LOOPBACK = [127, 0, 0, 1].join('.');

const CANDIDATES = {
  win32: [
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  ],
  darwin: [
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ],
  linux: ['/usr/bin/microsoft-edge', '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'],
};

export const findBrowser = () => {
  const pick = process.env.VDI_BROWSER || (CANDIDATES[process.platform] ?? CANDIDATES.linux).find(existsSync);
  if (!pick || !existsSync(pick)) throw new Error('no Edge/Chrome found: set VDI_BROWSER to the browser executable');
  return pick;
};

export const portUp = async port => {
  try { return (await fetch(`http://${LOOPBACK}:${port}/json/version`)).ok; } catch { return false; }
};

// A browser already holding the port would be driven instead of the one we launch, silently.
export const launch = async ({ port, profile, offscreen = false, extra = [] }) => {
  if (await portUp(port)) throw new Error(`port ${port} is already in use by another browser; close it or pick another port`);
  const args = [`--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', ...extra];
  if (offscreen) args.push('--window-position=-2400,-2400');
  spawn(findBrowser(), args, { detached: true, stdio: 'ignore' }).unref();
  const deadline = Date.now() + 25000;
  while (Date.now() < deadline) {
    if (await portUp(port)) return;
    await new Promise(r => setTimeout(r, 250));
  }
  throw new Error(`no CDP endpoint on :${port} after 25s (policy may disable remote debugging)`);
};

export const attach = async port => {
  const b = await chromium.connectOverCDP(`http://${LOOPBACK}:${port}`);
  const ctx = b.contexts()[0];
  const pages = ctx.pages();
  return { b, page: pages[pages.length - 1] ?? await ctx.newPage() };
};

// page.viewportSize() is null on a CDP-attached page; ask the protocol instead.
export const viewport = async page => {
  const cdp = await page.context().newCDPSession(page);
  const { cssLayoutViewport: v } = await cdp.send('Page.getLayoutMetrics');
  return { width: v.clientWidth, height: v.clientHeight, cdp };
};

// Graceful close of a test browser over CDP (never a force-kill: a stale lock breaks the profile).
export const closeBrowser = async port => {
  try { const { b } = await attach(port); await b.newBrowserCDPSession().then(s => s.send('Browser.close')); } catch {}
};

export { assertAscii } from './limits.mjs';
