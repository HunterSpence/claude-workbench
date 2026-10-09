# Capture sources

Each source is one module in `scripts/sources/`, loaded when capture starts (interface I24). Settings live in
`<WB>/capture/scope.json`; see `scripts/scope.example.json`.

## intranet
A same-origin crawl from the start URLs in the scope and nowhere else.
- Scope entries: https start URLs (plain http only for `localhost`). Deny entries: any text that appears in an address.
- Order: `robots.txt` of each origin first (the longest matching rule of the `*` group wins; Allow beats Disallow on a
  tie), then breadth first. Links are followed by address after their query and fragment are dropped.
- Caps: `max_depth` (default 2, start pages are depth 0) and `max_pages` (default 50 loads). Links to documents,
  archives, images and other non-page files are not followed.
- Output: one file per page, `scope` = `site:<host>/path:<start path>`; title, author and modified time come from the
  page's title and meta tags. A page with a label badge is skipped. Text comes from the visible page: navigation,
  scripts and hidden elements are left out; headings, lists, links, tables and code blocks become Markdown.
- Browser: yes (dedicated Edge profile, headless unless a policy or `--headed` says otherwise).

## shared-files
Files from the synced OneDrive folder, read in place. No browser.
- Setup by hand: "Add shortcut to My files" in the web app, let it sync, then `scope set sync_root <folder>`.
- Scope entries: paths relative to `sync_root`, a file or a folder. A folder is walked for readable files
  (`docx`, `pptx`, `xlsx`, `pdf`, `html`, `md`, `txt`); symbolic links met on the way are not followed. Entries that
  resolve outside `sync_root` are refused. `max_files` (default 100) bounds one run.
- Each file read is one paced hydration, converted by `find convert` (interface I4), written with `scope` =
  `folder:<entry>` and `url` = `sync-folder:<path under sync_root>`. Labelled files are skipped unless
  `--include-labelled`. The Python and the CLI come from `knowledge_python` in `<WB>/config.json` and
  `WORKBENCH_FIND_CLI`.

## teams and outlook (web) - not shipped in this version
Both were planned as experimental sources. They are deferred: they cannot be checked without a live Microsoft 365 tenant,
and the chat and mail web apps read data through POST requests, which the read-only rule stops on the first page load.
Making them work needs a ruling on which read-only POST endpoints (if any) may be allowed, then a live smoke test. Until
then, use the Graph-based or classic-client routes in the `ingest` skill, or the shared-files source.

## Writing a source module (interface I24)
```js
export default {
  name: "my-source",          // kebab-case; also the folder name under captured/
  experimental: false,         // true = refuses to run without --experimental and labels its report
  browser: true,               // optional; false = no browser is started (like shared-files)
  selectors: { next: "a[rel=next]", download: "#export-link" },   // the only things click/download can reach
  async run(ctx) { /* ... */ },
};
```
`ctx` offers: `scope`, `deny`, `settings`, `dry`, `includeLabelled`, `clock`, `log(msg)`, `inScope(url)`, `isDenied(key)`,
`goto(url)` (host list, deny list, pacing, stop checks; returns `{url, status, title}`), `click(name)` (false when
nothing matches), `search(name, query)` (a GET search box only), `download(name, destDir)` (returns the saved path),
`text(name)`, `snapshot()` (`{title, markdown, text, links, author, modified, labels, url}` of the current page),
`pace()` (count one file read), `convert(file, includeLabelled)` (the `find convert` result), `write(item)`,
`report({url, reason})` (a skipped item), `stop(reason)`. A module never touches the page directly.
`write` takes `{url, title, body, author?, modified?, labels?, scope, extra?}`; `extra` may hold only the mail or
meeting keys of interface I5. Errors thrown by the layer have `guard = true`: a module lets them through (the run stops
with exit 3) instead of swallowing them.
