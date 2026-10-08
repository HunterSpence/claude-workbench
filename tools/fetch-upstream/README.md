# fetch-upstream

Opt-in download of third-party skills this kit recommends but does not ship, each pinned to an
exact commit or published package version and verified file by file against SHA-256.

```bash
py -3 tools/fetch-upstream/fetch_upstream.py                   # dry run: the plan, nothing written
py -3 tools/fetch-upstream/fetch_upstream.py --apply           # install the default set
py -3 tools/fetch-upstream/fetch_upstream.py --optional --apply   # default set + the optional design set
```
Use `python3` instead of `py -3` on Linux and WSL. `fetch-upstream.ps1` (`-Apply`, `-Optional`) and
`fetch-upstream.sh` are thin wrappers over the same Python file; if your machine blocks PowerShell
scripts, use the Python command above and leave the execution policy alone.

Default set (`upstream.lock.json`):

| id | upstream | pinned to | licence | what you get |
|---|---|---|---|---|
| humanizer | blader/humanizer | v3.1.0 | MIT | prose de-AI rewrite skill |
| playwright-cli | @playwright/cli (npm) | 0.1.22 | Apache-2.0 | the skill for the playwright-cli browser tool (install the CLI at the same version) |

Optional design set (`upstream.optional.lock.json`, added by **`--optional`**): gstack's design-review,
qa and diagram skills (plus the gstack helper folder they read), impeccable, and web-design-guidelines.
They are **not recommended on a managed laptop**: gstack's skills write local usage logs and its full
setup installs Bun and a browser, impeccable downloads an engine binary at runtime, and
web-design-guidelines fetches live instructions on every run. Details in `THIRD-PARTY.md`. Fetch them
only deliberately, after your organisation approves; `--optional --only impeccable` takes one.

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
- Network: plain HTTPS GETs to `raw.githubusercontent.com` and `cdn.jsdelivr.net`, using your proxy
  settings. Behind a TLS-inspecting proxy set `SSL_CERT_FILE` to your organisation's CA bundle.
  Never call this from a hook.
- Check with your organisation before installing third-party skills, and scan them first with the
  `skill-scan` skill.

Re-pinning: change the lock deliberately (new commit or version, new hashes), run the dry run,
review the upstream diff, then apply. Never point a lock entry at a moving branch.

Test: `py -3 -m unittest discover -s tools/fetch-upstream` (`python3` on Linux and WSL).
