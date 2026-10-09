// A tiny local web server for the capture tests. Fictional pages from ./www, a request log, and three special routes:
//   /__mutate   records every hit (a write the capture layer must never cause)
//   /api/track  records POSTs (answers 204)
//   /search?q=  a results page with a.result links; /files/report.txt is a download
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const WWW = path.join(path.dirname(fileURLToPath(import.meta.url)), 'www');
const TYPES = { '.html': 'text/html; charset=utf-8', '.txt': 'text/plain; charset=utf-8' };

export async function serve() {
  const log = []; // every request: {method, path}
  const server = http.createServer((req, res) => {
    const u = new URL(req.url, 'http://localhost');
    log.push({ method: req.method, path: u.pathname, query: u.search });
    if (u.pathname === '/__mutate' || u.pathname === '/api/track') { res.writeHead(204).end(); return; }
    if (u.pathname === '/search') {
      const q = (u.searchParams.get('q') || '').toLowerCase();
      const hits = q.includes('alpha') ? '<a class="result" href="/docs/a.html">Alpha guide</a>' : '<p>No results</p>';
      res.writeHead(200, { 'content-type': TYPES['.html'] }).end(`<!doctype html><html><head><title>Results</title></head><body><h1>Results</h1>${hits}</body></html>`);
      return;
    }
    let rel = decodeURIComponent(u.pathname).replace(/^\/+/, '') || 'index.html';
    const file = path.join(WWW, rel);
    if (!file.startsWith(WWW) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404, { 'content-type': TYPES['.html'] }).end('<!doctype html><title>Not found</title><h1>Not found</h1>'); return; }
    const headers = { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' };
    if (rel.startsWith('files/')) headers['content-disposition'] = `attachment; filename="${path.basename(file)}"`;
    res.writeHead(200, headers).end(fs.readFileSync(file));
  });
  await new Promise((r) => server.listen(0, r));
  const port = server.address().port;
  return {
    origin: `http://localhost:${port}`,
    host: `localhost:${port}`,
    log,
    hits: (p) => log.filter((x) => x.path === p),
    mutations: () => log.filter((x) => x.path === '/__mutate'),
    page: (name) => fs.readFileSync(path.join(WWW, name), 'utf8'),
    close: () => new Promise((r) => { server.closeAllConnections(); server.close(r); }),
  };
}
