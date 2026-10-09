// shared-files: files from the synced OneDrive folder, read in place (no browser).
// The user adds "Add shortcut to My files" by hand in the web UI; capture never clicks it. Only the folders and
// files listed in the scope (relative to the sync_root setting) are touched, each read is one paced hydration,
// and each file is converted by the find CLI. A file with a sensitivity label is skipped unless --include-labelled.
import fs from 'node:fs';
import path from 'node:path';

const EXTS = new Set(['.docx', '.pptx', '.xlsx', '.pdf', '.html', '.htm', '.md', '.markdown', '.txt']); // what `find convert` reads
const posix = (p) => p.split(path.sep).join('/');

export default {
  name: 'shared-files',
  experimental: false,
  browser: false,
  selectors: {},
  async run(ctx) {
    const root = ctx.settings.sync_root;
    if (!root || !fs.existsSync(root)) throw new Error('sync_root is not set or missing: capture scope set sync_root <your OneDrive folder>');
    const cap = ctx.settings.max_files ?? 100;
    const base = path.resolve(root);
    const files = [];
    const walk = (dir, entry) => {
      for (const e of fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
        const p = path.join(dir, e.name);
        const rel = posix(path.relative(base, p));
        if (ctx.isDenied(rel)) { ctx.report({ url: `sync-folder:${rel}`, reason: 'deny list' }); continue; }
        if (e.isSymbolicLink()) continue; // links found while walking are never followed
        if (e.isDirectory()) walk(p, entry);
        else if (EXTS.has(path.extname(e.name).toLowerCase())) files.push({ p, rel, entry });
      }
    };
    for (const entry of ctx.scope) {
      const abs = path.resolve(base, entry);
      const rel = posix(path.relative(base, abs));
      if (rel.startsWith('..') || path.isAbsolute(rel)) { ctx.report({ url: '', reason: 'entry is outside the sync folder' }); continue; }
      if (ctx.isDenied(rel)) { ctx.report({ url: `sync-folder:${rel}`, reason: 'deny list' }); continue; }
      if (!fs.existsSync(abs)) { ctx.report({ url: `sync-folder:${rel}`, reason: 'not found' }); continue; }
      if (fs.statSync(abs).isDirectory()) walk(abs, entry);
      else files.push({ p: abs, rel, entry });
    }
    if (files.length > cap) ctx.report({ url: '', reason: `file cap (${cap}) reached; ${files.length - cap} listed files not read` });
    for (const f of files.slice(0, cap)) {
      const url = `sync-folder:${f.rel}`;
      if (ctx.dry) { ctx.report({ url, reason: 'dry run: would read' }); continue; }
      await ctx.pace(); // reading a file is the hydration
      const c = ctx.convert(f.p, ctx.includeLabelled);
      if (c.error) { ctx.report({ url, reason: `could not convert: ${String(c.error).slice(0, 120)}` }); continue; }
      if (c.label && !ctx.includeLabelled) { ctx.report({ url, reason: 'labelled' }); continue; }
      const t = fs.statSync(f.p).mtime;
      ctx.write({ url, title: path.basename(f.p, path.extname(f.p)), author: null, modified: new Date(t).toISOString().replace(/\.\d+Z$/, 'Z'),
        labels: c.label ? [c.label] : [], scope: `folder:${f.entry}`, body: c.markdown });
    }
  },
};
