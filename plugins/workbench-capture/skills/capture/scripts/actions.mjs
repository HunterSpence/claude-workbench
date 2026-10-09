// The action layer: the only way a source module touches the browser (interface I24). Read-only by construction.
//   1. Allowlist: a module can only act on selector NAMES it declared; any other target is refused.
//   2. Element check: even an allowlisted selector is refused if the element it finds looks like a write control
//      (send, post, reply, delete, share, save, ... in many languages, an unlabelled icon button, a submit of a
//      non-GET form, a link that leaves the scope or starts a download outside download()).
//   3. Navigation stays on the hosts of the scope; the deny list is never visited; every action is paced.
//   4. The context aborts every non-GET request and records it; the first one stops the run.
//   5. Any sign-in, consent, policy or block page stops the run with no retry.
import fs from 'node:fs';
import path from 'node:path';
import { detect } from './interstitial.mjs';
import { PacingCap } from './pacing.mjs';
import { cleanUrl } from './writer.mjs';

export class Stop extends Error {
  constructor(kind, reason, url) {
    super(reason);
    this.name = 'Stop';
    this.guard = true;
    this.kind = kind;
    this.url = url ? cleanUrl(url) : null;
  }
}
export class Refused extends Error {
  constructor(reason) {
    super(reason);
    this.name = 'Refused';
    this.guard = true;
  }
}

// ---- element check -------------------------------------------------------------------------------------------
const WORDS = [
  'send post reply respond forward react reaction like unlike accept decline edit delete remove share save submit publish approve reject archive move flag pin mute invite add create compose upload paste confirm apply update rename restore discard rsvp join call dial mark star follow unfollow subscribe unsubscribe block trash logout signout',
  'markieren senden absenden antworten weiterleiten löschen loeschen entfernen teilen speichern bearbeiten akzeptieren annehmen ablehnen veröffentlichen hinzufügen erstellen hochladen bestätigen abmelden',
  'marquer envoyer répondre repondre transférer supprimer partager enregistrer sauvegarder modifier accepter refuser publier ajouter créer téléverser confirmer',
  'marcar enviar responder reenviar eliminar borrar compartir guardar editar aceptar rechazar publicar añadir agregar crear subir confirmar encaminhar excluir apagar compartilhar partilhar salvar aceitar recusar adicionar criar',
  'segna invia rispondi inoltra elimina cancella condividi salva modifica accetta rifiuta pubblica aggiungi crea',
  'verzenden beantwoorden doorsturen verwijderen delen opslaan bewerken accepteren weigeren',
  'отметить отправить ответить переслать удалить поделиться сохранить изменить редактировать принять отклонить опубликовать добавить создать загрузить',
].join(' ').split(' ');
const WIDE = ['送信', '返信', '転送', '削除', '共有', '保存', '編集', '承諾', '辞退', '追加', '作成', '发送', '回复', '转发', '删除', '分享', '编辑', '接受', '拒绝', '添加', '创建', '發送', '回覆', '刪除', '儲存', '보내기', '답장', '삭제', '공유', '저장', '편집', '수락', '거절', '추가', 'إرسال', 'حذف', 'مشاركة', 'حفظ'];
const PHRASES = ['report abuse', 'report phishing', 'report junk', 'report spam', 'report message', 'sign out', 'log out'].map((p) => p.replace(' ', '\\s+'));
const VERB = new RegExp(`(?<![\\p{L}\\p{N}])(${[...WORDS, ...PHRASES].join('|')})(?![\\p{L}\\p{N}])|${WIDE.join('|')}`, 'iu');

// Runs inside the page: the facts the element check needs, nothing else.
function infoFn(el) {
  const q = (s) => el.getAttribute(s) || '';
  const form = el.closest('form');
  const tag = el.tagName.toLowerCase();
  const kids = Array.from(el.querySelectorAll('[class],[data-icon-name],svg title')).slice(0, 6).map((c) => c.getAttribute('class') || c.getAttribute('data-icon-name') || c.textContent || '');
  return {
    tag, type: q('type').toLowerCase(), role: q('role').toLowerCase(), editable: el.isContentEditable,
    name: (el.innerText || '').trim().slice(0, 120), aria: q('aria-label'), title: q('title'), alt: q('alt') || (el.querySelector('img[alt]') || {}).alt || '', value: q('value'),
    marks: [el.id, q('class'), q('name'), q('data-testid'), q('data-tid'), q('data-automation-id'), q('data-icon-name'), ...kids].join(' '),
    href: tag === 'a' ? el.href : '', download: el.hasAttribute('download'),
    formMethod: (q('formmethod') || (form ? form.getAttribute('method') || 'get' : '')).toLowerCase(),
  };
}

// Why this element may not be clicked, or null. `ctx` = {hostAllowed(host), denied(url), download}.
export function refuseReason(i, ctx) {
  const camel = (s) => String(s).replace(/([a-z])([A-Z])/g, '$1 $2');
  if (i.editable || ['textarea', 'select'].includes(i.tag)) return 'form control';
  if (i.tag === 'input' && !['submit', 'button', 'image', 'reset'].includes(i.type)) return 'form control';
  const label = [i.name, i.aria, i.title, i.alt, i.value].join(' ').trim();
  let hrefPath = '';
  if (i.tag === 'a') {
    let u;
    try { u = new URL(i.href); } catch { return 'link without a usable address'; }
    if (!/^https?:$/.test(u.protocol)) return `link scheme ${u.protocol}`;
    if (!ctx.hostAllowed(u.host)) return 'link leaves the scope';
    if (ctx.denied(u.href)) return 'link is on the deny list';
    if (i.download && !ctx.download) return 'link starts a download';
    hrefPath = decodeURIComponent(u.pathname);
  } else if (!/[\p{L}\p{N}]/u.test(label)) {
    return 'control has no label (icon only)';
  }
  if (i.formMethod && i.formMethod !== 'get') return `submits a ${i.formMethod.toUpperCase()} form`;
  const m = VERB.exec(camel(`${label} ${i.marks} ${hrefPath}`));
  return m ? `looks like a write action (${m[0].toLowerCase()})` : null;
}

// ---- page-side helpers (serialised into the page; no outer references) ---------------------------------------
function probeFn() {
  const b = document.body;
  return {
    title: document.title || '', text: b ? b.innerText.slice(0, 1500) : '',
    alerts: Array.from(document.querySelectorAll('[role=alert],[role=alertdialog],dialog[open]')).map((e) => e.innerText).join('\n').slice(0, 1000),
    password: !!document.querySelector('input[type=password]'),
  };
}

function snapFn(labelSel) {
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'TEMPLATE', 'IFRAME', 'CANVAS', 'NAV', 'HEAD']);
  const BLOCK = new Set(['p', 'div', 'section', 'article', 'main', 'header', 'footer', 'aside', 'blockquote', 'form', 'fieldset', 'details', 'summary', 'figure', 'figcaption', 'caption']);
  const clean = (h) => { try { const u = new URL(h, location.href); u.search = ''; u.hash = ''; return u.href; } catch { return ''; } };
  const inline = (n) => Array.from(n.childNodes).map(walk).join('').replace(/\s+/g, ' ').trim();
  function walk(n) {
    if (n.nodeType === 3) return n.nodeValue.replace(/\s+/g, ' ');
    if (n.nodeType !== 1 || SKIP.has(n.tagName.toUpperCase()) || n.hidden || n.getAttribute('aria-hidden') === 'true') return '';
    const t = n.tagName.toLowerCase();
    const kids = () => Array.from(n.childNodes).map(walk).join('');
    if (/^h[1-6]$/.test(t)) return `\n\n${'#'.repeat(+t[1])} ${inline(n)}\n\n`;
    if (t === 'a') { const x = inline(n); const h = /^https?:/i.test(n.href || '') ? clean(n.href) : ''; return h && x ? `[${x}](${h})` : x; }
    if (t === 'br') return '\n';
    if (t === 'pre') return `\n\n\`\`\`\n${n.innerText.replace(/\n+$/, '')}\n\`\`\`\n\n`;
    if (t === 'li') return `\n${n.parentElement && n.parentElement.tagName === 'OL' ? '1.' : '-'} ${inline(n)}`;
    if (t === 'tr') return `\n| ${Array.from(n.children).map(inline).join(' | ')} |`;
    if (t === 'ul' || t === 'ol' || t === 'table') return `\n${kids()}\n`;
    return BLOCK.has(t) ? `\n\n${kids()}\n\n` : kids();
  }
  const meta = (sel, attr) => { const e = document.querySelector(sel); return e ? (e.getAttribute(attr) || '').trim() || null : null; };
  const labels = [...new Set(Array.from(document.querySelectorAll(labelSel)).map((e) => (e.getAttribute('data-sensitivity-label') || e.getAttribute('data-label-name') || e.getAttribute('aria-label') || e.textContent || 'label').replace(/^sensitivity label:?\s*/i, '').trim() || 'label'))];
  const h1 = document.querySelector('h1');
  return {
    title: (document.title || (h1 ? h1.innerText : '')).trim(),
    markdown: walk(document.body).replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim(),
    text: document.body.innerText.slice(0, 200000),
    links: [...new Set(Array.from(document.querySelectorAll('a[href]')).map((a) => a.href).filter((h) => /^https?:/i.test(h)).map(clean))].slice(0, 500),
    author: meta('meta[name=author]', 'content'),
    modified: meta('meta[property="article:modified_time"]', 'content') || meta('meta[name=last-modified]', 'content') || meta('meta[name=modified]', 'content') || meta('time[itemprop=dateModified]', 'datetime'),
    labels,
  };
}
export const LABEL_SELECTOR = '[data-sensitivity-label],[data-label-name],[aria-label^="Sensitivity label" i],.sensitivity-label';

// ---- watching the context ------------------------------------------------------------------------------------
// state = {violations: [], blockedNav: null, stopped: null}
// A page cannot be kept from following a server redirect to another host (the browser does that inside its network
// stack, past any route), so a main-frame navigation to a host outside the scope is recorded here and stops the run
// right after that one GET; nothing from the page is read or kept.
export async function watch({ context, page, state, hostAllowed }) {
  const readOnly = (m) => m === 'GET' || m === 'HEAD';
  const foreign = (r) => r.isNavigationRequest() && /^https?:/i.test(r.url()) && !hostAllowed(new URL(r.url()).host);
  const isMain = (r) => { try { return r.frame() === page.mainFrame(); } catch { return false; } };
  context.on('request', (r) => {
    if (!readOnly(r.method())) state.violations.push({ method: r.method(), url: cleanUrl(r.url()) });
    if (foreign(r) && isMain(r)) state.blockedNav ??= { url: cleanUrl(r.url()), host: new URL(r.url()).host };
  });
  context.on('page', (p) => { if (p !== page) p.close().catch(() => {}); }); // a pop-up is never followed
  await context.route('**/*', (route) => {
    const r = route.request();
    if (!readOnly(r.method())) return route.abort('blockedbyclient');
    if (r.resourceType() === 'document' && foreign(r)) return route.abort('blockedbyclient');
    return route.fallback();
  });
}

const LOGIN_HOST = /(^|\.)(login\.microsoftonline\.com|login\.live\.com|login\.windows\.net)$/i;
const safeName = (n) => (String(n || '').replace(/[\\/]/g, '_').replace(/[<>:"|?*\x00-\x1f]/g, '_').slice(0, 120) || 'download');

export function makeActions({ page, selectors = {}, hostAllowed, isDenied, pacer, state, tenant = '' }) {
  let tenantOk = !(tenant && selectors.account);
  const stop = (kind, reason, url) => { state.stopped ??= new Stop(kind, reason, url ?? page.url()); throw state.stopped; };
  const live = () => { if (state.stopped) throw state.stopped; };
  const pace = async () => { live(); try { await pacer.take(); } catch (e) { if (e instanceof PacingCap) stop('pacing', e.message); throw e; } };
  const inScope = (u) => { try { const x = new URL(u); return /^https?:$/.test(x.protocol) && hostAllowed(x.host) && !isDenied(cleanUrl(u)) && !isDenied(u); } catch { return false; } };

  const nonGet = () => { if (state.violations.length) { const v = state.violations[0]; stop('non-get', `the page issued a ${v.method} request (${v.url})`); } };

  async function settle() {
    await page.waitForLoadState('networkidle', { timeout: 4000 }).catch(() => {});
  }

  async function verify(status) {
    live();
    nonGet();
    if (state.blockedNav) {
      const b = state.blockedNav;
      stop(LOGIN_HOST.test(b.host.split(':')[0]) ? 'sign-in' : 'policy', LOGIN_HOST.test(b.host.split(':')[0]) ? 'redirected to a sign-in page' : `navigation left the scope (${b.host})`, b.url);
    }
    const p = await page.evaluate(probeFn);
    const hit = detect({ url: page.url(), status: status ?? 200, ...p });
    if (hit) stop(hit.kind, hit.reason);
    if (!tenantOk) {
      const e = page.locator(selectors.account).first();
      const t = (await e.count()) ? `${(await e.getAttribute('aria-label')) ?? ''} ${await e.innerText().catch(() => '')}` : '';
      const dom = /@([a-z0-9.-]+)/i.exec(t);
      if (!dom || dom[1].toLowerCase() !== tenant.toLowerCase()) stop('tenant', dom ? 'signed-in account is outside the scope tenant' : 'could not verify the signed-in tenant');
      tenantOk = true;
    }
  }

  async function resolve(name, download = false) {
    live();
    if (typeof name !== 'string' || !Object.hasOwn(selectors, name)) throw new Refused(`target is not allowlisted: ${String(name).slice(0, 40)}`);
    const loc = page.locator(selectors[name]).first();
    if (!(await loc.count())) return null;
    const why = refuseReason(await loc.evaluate(infoFn, undefined, { timeout: 5000 }), { hostAllowed, denied: isDenied, download });
    if (why) throw new Refused(`${name}: ${why}`);
    return loc;
  }

  return {
    inScope,
    async goto(url) {
      live();
      if (!inScope(url)) throw new Refused(`not in scope: ${cleanUrl(url)}`);
      await pace();
      let resp = null;
      try {
        resp = await page.goto(url, { waitUntil: 'load', timeout: 30000 });
      } catch (e) {
        if (!state.blockedNav) throw e;
      }
      await settle();
      await verify(resp ? resp.status() : 200);
      return { url: cleanUrl(page.url()), status: resp ? resp.status() : 200, title: await page.title() };
    },
    async click(name) {
      const loc = await resolve(name);
      if (!loc) return false;
      await pace();
      await loc.click({ timeout: 10000 });
      await settle();
      await verify(null);
      return true;
    },
    async search(name, query) {
      live();
      if (typeof name !== 'string' || !Object.hasOwn(selectors, name)) throw new Refused(`target is not allowlisted: ${String(name).slice(0, 40)}`);
      const loc = page.locator(selectors[name]).first();
      if (!(await loc.count())) return false;
      const i = await loc.evaluate(infoFn, undefined, { timeout: 5000 });
      if (!(i.tag === 'input' && ['search', 'text', ''].includes(i.type)) && i.role !== 'searchbox') throw new Refused(`${name}: not a search box`);
      if (i.formMethod && i.formMethod !== 'get') throw new Refused(`${name}: search form submits a ${i.formMethod.toUpperCase()}`);
      await pace();
      await loc.fill(String(query), { timeout: 10000 });
      await loc.press('Enter', { timeout: 10000 });
      await settle();
      await verify(null);
      return true;
    },
    async download(name, destDir) {
      const loc = await resolve(name, true);
      if (!loc) throw new Refused(`nothing matches ${name}`);
      await pace();
      const wait = page.waitForEvent('download', { timeout: 30000 });
      try { await loc.click({ timeout: 10000 }); } catch (e) { wait.catch(() => {}); throw e; }
      const dl = await wait;
      fs.mkdirSync(destDir, { recursive: true });
      const file = path.join(destDir, safeName(dl.suggestedFilename()));
      await dl.saveAs(file);
      await verify(null);
      return file.replaceAll('\\', '/');
    },
    async text(name) {
      live();
      if (typeof name !== 'string' || !Object.hasOwn(selectors, name)) throw new Refused(`target is not allowlisted: ${String(name).slice(0, 40)}`);
      const loc = page.locator(selectors[name]).first();
      return (await loc.count()) ? (await loc.innerText({ timeout: 5000 })).trim() : null;
    },
    async snapshot() {
      live();
      const s = await page.evaluate(snapFn, LABEL_SELECTOR);
      const t = s.modified ? Date.parse(s.modified) : NaN;
      return { ...s, modified: Number.isFinite(t) ? new Date(t).toISOString().replace(/\.\d+Z$/, 'Z') : null, url: cleanUrl(page.url()) };
    },
    // The run is over: a non-GET request seen since the last check still fails it.
    finish() { live(); nonGet(); },
  };
}
