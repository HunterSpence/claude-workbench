import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { detect } from '../skills/capture/scripts/interstitial.mjs';
import { refuseReason } from '../skills/capture/scripts/actions.mjs';
import intranet, { parseRobots } from '../skills/capture/scripts/sources/intranet.mjs';
import sharedFiles from '../skills/capture/scripts/sources/shared_files.mjs';

describe('robots.txt rules', () => {
  const ok = parseRobots('User-agent: other\nDisallow: /\n\nUser-agent: *\nDisallow: /private/\nAllow: /private/public/\nDisallow: /*.pdf$\n# comment\n');
  it('uses the * group only, the longest match, and * and $', () => {
    assert.equal(ok('/docs/a.html'), true);
    assert.equal(ok('/private/x.html'), false);
    assert.equal(ok('/private/public/x.html'), true);
    assert.equal(ok('/files/manual.pdf'), false);
    assert.equal(ok('/files/manual.pdf.html'), true);
  });
  it('allows everything when there is nothing to obey', () => {
    assert.equal(parseRobots('')('/anything'), true);
    assert.equal(parseRobots('User-agent: *\nDisallow:\n')('/anything'), true);
  });
});

describe('interstitial detection', () => {
  const kind = (p) => detect({ url: 'https://wiki.example.com/x', status: 200, title: 'Page', text: 'Plain text', ...p })?.kind ?? null;
  it('recognises the stop pages', () => {
    assert.equal(kind({ password: true }), 'sign-in');
    assert.equal(kind({ url: 'https://login.microsoftonline.com/x/oauth2/authorize' }), 'sign-in');
    assert.equal(kind({ url: 'https://wiki.example.com/adfs/ls/' }), 'sign-in');
    assert.equal(kind({ title: 'Sign in to your account' }), 'sign-in');
    assert.equal(kind({ title: 'Verify your identity' }), 'mfa');
    assert.equal(kind({ title: 'Permissions requested' }), 'consent');
    assert.equal(kind({ text: 'Need admin approval' }), 'consent');
    assert.equal(kind({ text: 'AADSTS53003: access has been blocked' }), 'conditional-access');
    assert.equal(kind({ alerts: "Blocked by your organization's data loss prevention policy" }), 'dlp');
    assert.equal(kind({ status: 403 }), 'block');
    assert.equal(kind({ status: 429, text: '' }), 'block');
    assert.equal(kind({ status: 404, text: 'Not found' }), null);
  });
  it('does not stop on ordinary pages that merely mention these words', () => {
    assert.equal(kind({ url: 'https://wiki.example.com/docs/sso-guide.html', title: 'How to use single sign-on' }), null);
    assert.equal(kind({ title: 'Access policy overview', text: 'Our access control standard.' }), null);
    assert.equal(kind({ text: 'x'.repeat(2000) + ' captcha' }), null, 'only the top of the page is judged');
  });
});

describe('element check (unit)', () => {
  const allow = { hostAllowed: (h) => h === 'wiki.example.com', denied: (u) => u.includes('/hr/') };
  const el = (o) => ({ tag: 'button', type: '', role: '', editable: false, name: '', aria: '', title: '', alt: '', value: '', marks: '', href: '', download: false, formMethod: '', ...o });
  it('lets plain navigation controls through', () => {
    assert.equal(refuseReason(el({ tag: 'a', href: 'https://wiki.example.com/p2', name: 'Next page' }), allow), null);
    assert.equal(refuseReason(el({ tag: 'button', name: 'Next', aria: 'Next page' }), allow), null);
    assert.equal(refuseReason(el({ tag: 'a', href: 'https://wiki.example.com/files/report.xlsx', name: 'Download report', download: true }), { ...allow, download: true }), null);
  });
  it('refuses write verbs in any field, other hosts, denied addresses, forms and unlabelled controls', () => {
    for (const o of [{ name: 'Löschen' }, { aria: 'Reply all' }, { title: 'Share' }, { marks: 'btnDeleteItem' }, { marks: 'icon-trash' }, { value: '保存', tag: 'input', type: 'submit' }, { name: 'Marcar como leído' }]) {
      assert.ok(refuseReason(el(o), allow), JSON.stringify(o));
    }
    assert.ok(refuseReason(el({ tag: 'a', href: 'https://other.example.com/', name: 'Home' }), allow));
    assert.ok(refuseReason(el({ tag: 'a', href: 'https://wiki.example.com/hr/x', name: 'Home' }), allow));
    assert.ok(refuseReason(el({ tag: 'a', href: 'https://wiki.example.com/f', name: 'File', download: true }), allow), 'a download link needs download()');
    assert.ok(refuseReason(el({ tag: 'button', name: 'Go', formMethod: 'post' }), allow));
    assert.ok(refuseReason(el({ tag: 'button', name: '\u2709' }), allow), 'a glyph is not a label');
    assert.ok(refuseReason(el({ tag: 'input', type: 'checkbox' }), allow));
    assert.ok(refuseReason(el({ tag: 'div', editable: true, name: 'Notes' }), allow));
  });
});

describe('source module shape (interface I24)', () => {
  it('both shipped modules export name, experimental, selectors and run', () => {
    for (const m of [intranet, sharedFiles]) {
      assert.match(m.name, /^[a-z][a-z0-9-]*$/);
      assert.equal(typeof m.experimental, 'boolean');
      assert.equal(typeof m.selectors, 'object');
      assert.equal(typeof m.run, 'function');
      assert.equal(m.experimental, false);
    }
    assert.equal(sharedFiles.browser, false);
  });
});
