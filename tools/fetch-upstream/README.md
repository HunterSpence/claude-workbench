# fetch-upstream

Opt-in download of third-party skills this kit recommends but does not ship, each pinned to an
exact commit or published package version and verified file by file against SHA-256.

```powershell
.\tools\fetch-upstream\fetch-upstream.ps1                      # dry run: the plan, nothing written
.\tools\fetch-upstream\fetch-upstream.ps1 -Apply
```
```bash
tools/fetch-upstream/fetch-upstream.sh                         # dry run
tools/fetch-upstream/fetch-upstream.sh --apply
```

Default set (`upstream.lock.json`):

| id | upstream | pinned to | licence | what you get |
|---|---|---|---|---|
| humanizer | blader/humanizer | v3.1.0 | MIT | prose de-AI rewrite skill |
| playwright-cli | @playwright/cli (npm) | 0.1.22 | Apache-2.0 | the skill for the playwright-cli browser tool (install the CLI at the same version) |

`upstream.optional.lock.json` holds gstack (design-review, qa, diagram), impeccable and
web-design-guidelines. They are **not recommended on a managed laptop**; the reasons are in
`THIRD-PARTY.md`. Fetch them only deliberately: `-Lock upstream.optional.lock.json`
(`--lock ...` in bash), after reading those reasons and your organisation's policy.

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
