// intranet: a same-origin crawl that starts from the URLs in the scope and nowhere else.
// Honours robots.txt, a depth cap (max_depth, default 2) and a page cap (max_pages, default 50); every load is paced.
// It follows links by address (goto), so it needs no clickable selectors at all.

const SKIP_EXT = /\.(pdf|docx?|xlsx?|pptx?|zip|7z|gz|png|jpe?g|gif|svg|webp|ico|mp[34]|mov|avi|exe|dmg|css|js|json|xml)$/i;

// RFC 9309 style: the longest matching rule of the `*` group wins; Allow wins a tie.
export function parseRobots(text) {
  const rules = [];
  let star = false;
  let afterAgent = false;
  for (const raw of String(text).split(/\r?\n/)) {
    const m = /^\s*([A-Za-z-]+)\s*:\s*(.*?)\s*(#.*)?$/.exec(raw);
    if (!m) continue;
    const k = m[1].toLowerCase();
    if (k === 'user-agent') { star = (afterAgent && star) || m[2] === '*'; afterAgent = true; continue; }
    afterAgent = false;
    if (star && (k === 'allow' || k === 'disallow') && m[2]) {
      const re = m[2].replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\\\$$/, '$');
      rules.push({ allow: k === 'allow', re: new RegExp(`^${re}`), len: m[2].length });
    }
  }
  return (p) => {
    const hit = rules.filter((r) => r.re.test(p)).sort((x, y) => y.len - x.len || Number(y.allow) - Number(x.allow))[0];
    return !hit || hit.allow;
  };
}

export default {
  name: 'intranet',
  experimental: false,
  selectors: {},
  async run(ctx) {
    const depthCap = ctx.settings.max_depth ?? 2;
    const pageCap = ctx.settings.max_pages ?? 50;
    const starts = ctx.scope.filter((u) => /^https?:\/\//i.test(u));
    if (!starts.length) throw new Error('no start URL in the scope: capture scope add --source intranet <https URL>');
    const allowed = new Map(); // origin -> (path) => bool
    const seen = new Set();
    const queue = starts.map((u) => ({ url: u, depth: 0, prefix: new URL(u).pathname }));
    let pages = 0;
    while (queue.length && pages < pageCap) {
      const { url, depth, prefix } = queue.shift();
      const u = new URL(url);
      u.hash = '';
      const key = `${u.origin}${u.pathname}`;
      if (seen.has(key)) continue;
      seen.add(key);
      if (!ctx.inScope(u.href)) { ctx.report({ url: key, reason: 'deny list' }); continue; }
      if (!allowed.has(u.origin)) {
        let rule = () => true;
        try {
          const r = await ctx.goto(`${u.origin}/robots.txt`);
          if (r.status === 200) rule = parseRobots((await ctx.snapshot()).text);
        } catch (e) { if (e.stop) throw e; }
        allowed.set(u.origin, rule);
      }
      if (!allowed.get(u.origin)(u.pathname)) { ctx.report({ url: key, reason: 'robots.txt' }); continue; }
      let r;
      try { r = await ctx.goto(u.href); } catch (e) { if (e.stop) throw e; ctx.report({ url: key, reason: 'load failed' }); continue; }
      pages++;
      if (r.status >= 400) { ctx.report({ url: key, reason: `HTTP ${r.status}` }); continue; }
      const s = await ctx.snapshot();
      if (s.labels.length && !ctx.includeLabelled) { ctx.report({ url: key, reason: 'labelled' }); continue; }
      ctx.write({ url: s.url, title: s.title, author: s.author, modified: s.modified, labels: ctx.includeLabelled ? s.labels : [],
        scope: `site:${u.host}/path:${prefix}`, body: s.markdown });
      if (depth < depthCap) for (const l of s.links) if (new URL(l).origin === u.origin && !SKIP_EXT.test(new URL(l).pathname)) queue.push({ url: l, depth: depth + 1, prefix });
    }
    if (queue.length) ctx.report({ url: '', reason: `page cap (${pageCap}) reached; ${queue.length} discovered pages not visited` });
  },
};
