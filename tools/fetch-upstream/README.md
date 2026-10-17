# fetch-upstream

Opt-in download of third-party skills this kit recommends but does not ship, each pinned to an
exact commit or published package version and verified file by file against SHA-256.

```bash
py -3 tools/fetch-upstream/fetch_upstream.py                   # dry run: the plan, nothing written
py -3 tools/fetch-upstream/fetch_upstream.py --apply           # install the default set
py -3 tools/fetch-upstream/fetch_upstream.py --optional --apply   # default set + the optional design set
py -3 tools/fetch-upstream/fetch_upstream.py --pm --apply         # the product-management pack instead
```
Use `python3` instead of `py -3` on Linux and WSL. `fetch-upstream.ps1` (`-Apply`, `-Optional`, `-Pm`) and
`fetch-upstream.sh` are thin wrappers over the same Python file; if your machine blocks PowerShell
scripts, use the Python command above and leave the execution policy alone.

Default set (`upstream.lock.json`):

| id | upstream | pinned to | licence | what you get |
|---|---|---|---|---|
| humanizer | blader/humanizer | v3.1.0 | MIT | prose de-AI rewrite skill |
| web-interface-guidelines | vercel-labs/web-interface-guidelines | one 40-character commit | MIT | the UI review rules list (`command.md` plus its LICENSE) that the `ui-build` skill reads from disk, so a review never fetches a moving branch |
| diagram-render | garrytan/gstack, `lib/diagram-render` only | one 40-character commit | MIT (embedded fonts: SIL OFL 1.1) | the offline Mermaid and Excalidraw renderer (one HTML file, about 7.6 MB) that the `diagram` skill drives; no gstack skill text or helper script comes with it |

Both land in `<skills dir>/<id>/` as plain data folders: they hold no `SKILL.md`, so Claude Code does not load them as skills.
The `diagram` skill looks for `diagram-render/diagram-render.html` there (`DIAGRAM_RENDER_BUNDLE` overrides).

Product-management pack (`upstream.pm.lock.json`, selected by **`--pm`**, never combined with `--optional` or `--lock`):

| id | upstream | pinned to | licence | what you get |
|---|---|---|---|---|
| pm-pack | the Apache-2.0 knowledge-work plugins, product-management plugin | one 40-character commit | Apache-2.0 | eight skills (competitive brief, metrics review, product brainstorming, roadmap update, sprint planning, stakeholder update, research synthesis, write spec), each as `SKILL.md` plus the upstream `LICENSE` |

Only those two files per skill are fetched: no `.mcp.json`, no commands, no connector files. The skills use the Claude
Code-only `argument-hint` key and refer to connector placeholders, so they load in Claude Code but would need
`web-packager --strip` before a claude.ai skill upload, and nothing is connected for you. Review the installed folders with
`plugin-review` (`--target cli`) before use.

Optional set (`upstream.optional.lock.json`, added by **`--optional`**): gstack's design-review,
qa and diagram skills (plus the gstack helper folder they read) and impeccable, and the pinned
playwright-cli skill (`@playwright/cli` 0.1.22, Apache-2.0).
The gstack and impeccable entries are **not recommended on a managed laptop**: gstack's skills write local usage
logs and its full setup installs Bun and a browser, and impeccable downloads an engine binary at runtime. Details in
`THIRD-PARTY.md`. Fetch them deliberately; `--optional --only impeccable`
takes one. The playwright-cli skill sits here as the fallback for a machine where npm is blocked: the normal way to get
it is the setup step that installs the CLI from npm at a pinned version and then installs the skill from that same
package. Install the CLI itself at the same version as the skill.

How it behaves:
- **Dry run by default.** `-Apply` / `--apply` downloads to a temporary folder, checks every hash,
  and installs a source only if all its files verify. A mismatch writes nothing.
- **Never overwrites silently.** An existing folder is skipped unless you pass `-Force`; then the old
  folder moves to `<config dir>/workbench-backups/skills/` (outside the skills folder, so it is not
  loaded as a skill).
- **Licences travel with the files.** Each installed folder keeps the upstream LICENSE (and NOTICE
  where one exists) and gets an `UPSTREAM.txt` with source, version, commit and licence.
- Only permissive licences are accepted (MIT, Apache-2.0, BSD, ISC). Anthropic's `document-skills`
  are proprietary and are never fetched; see `THIRD-PARTY.md`.
- Network: plain HTTPS GETs to `raw.githubusercontent.com` (the default set and impeccable/gstack) and, for the
  optional playwright-cli skill, `cdn.jsdelivr.net`, using your proxy settings. Behind a TLS-inspecting proxy set `SSL_CERT_FILE` to your organisation's CA bundle.
  Never call this from a hook.
- The `skill-scan` skill scans third-party skills.

Re-pinning: change the lock deliberately (new commit or version, new hashes), run the dry run,
review the upstream diff, then apply. Never point a lock entry at a moving branch.

Test: `py -3 -m unittest discover -s tools/fetch-upstream` (`python3` on Linux and WSL).
