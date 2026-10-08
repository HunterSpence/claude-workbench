---
name: cleanup
description: Archive confirmed dead or legacy code. Re-verifies each candidate is unused (zero references on every live surface, scheduler check, build/typecheck/test gate), then git-mv's it into _archive/<date>/ with a restore manifest. Never hard-deletes; confirm-gated at every risky step; deploy-gated repos get a branch and PR, never a merge.
---

# /cleanup: confirm-gated archival of dead code

**Voice:** plain, cautious, factual. When in doubt, keep the file.

## Non-negotiable safety rules
1. **Never hard-delete.** Archival is `git mv` into `_archive/<date>/` (history preserved) plus a
   manifest with a one-line restore command per item.
2. **Never push to a deploy-gated default branch.** If merging to `main` triggers a deploy, archive
   on a branch, open a PR, and STOP. Merging is the owner's call through normal review.
3. **Never archive without explicit approval of the specific file list.** The default is archive
   NOTHING. Silence is not approval.
4. **Prove code is unused before moving it:** a clean build, typecheck and test run on the
   post-archive tree is the final gate. Anything breaks: abort and restore.
5. **Precision over recall.** Skip anything uncertain. Leaving dead code is fine; removing live
   code is not.
6. **Scripts may be scheduler entry points.** A script with zero in-repo references may still run
   from Task Scheduler, cron, systemd, CI or a launcher, all invisible to `git grep`. Check
   programmatically before proposing it:
   - Windows: `Get-ScheduledTask | ForEach-Object { $_.Actions.Execute + ' ' + $_.Actions.Arguments } | Select-String <name>`
   - Linux: `crontab -l; ls /etc/cron.d; grep -rl <name> /etc/cron.d /etc/systemd/system ~/.config/systemd 2>/dev/null`
   - CI: `grep -rn <name> .github/ .gitlab-ci.yml azure-pipelines.yml 2>/dev/null`
   A hit, or an inconclusive check, means leave it.

## Step 1: candidates
- **Named targets** (the user or an audit listed files): never skip verification.
- **Discovery** (no targets): use what the stack offers (`knip` for JS/TS, `vulture` for Python,
  `deadcode` for Go, the code graph's dead-code query if one is installed), plus files unchanged for
  a long time (`git log -1 --format=%cs -- <file>`).
- For each candidate: (a) zero-reference grep across every live surface (source, configs, CI,
  scripts, launchers, instruction files, skills and hooks), excluding the target's own subtree,
  `_archive/**` and historical docs (a doc mentioning a path is not a runtime dependency: note it,
  don't count it); (b) the scheduler check above for any script. A target with live references
  drops out; report why.
- Directories archive as whole units (one manifest row per directory).

## Step 2: present and HARD CONFIRM
Show a table: path, why it is considered dead (tool finding, zero refs, age), last modified. Ask
which to archive. Proceed only on an explicit answer naming the set ("all of them", "just these 3").

## Step 3: archive on a branch
```bash
date=$(date +%F)
git switch -c "chore/archive-legacy-$date"
for f in <approved paths>; do
  mkdir -p "_archive/$date/$(dirname "$f")"
  git mv -- "$f" "_archive/$date/$f"
done
```
PowerShell: `$date = Get-Date -Format yyyy-MM-dd`, then the same `git mv` per file after
`New-Item -ItemType Directory -Force`.

Write `_archive/<date>/MANIFEST.md`:
```markdown
# Archive <date>
Approved by: <who> | Evidence: <tools and checks run>
| Archived path | Original path | Reason | Restore |
|---|---|---|---|
| _archive/<date>/<f> | <f> | 0 refs; unchanged N days; scheduler check clean | `git mv _archive/<date>/<f> <f>` |
```
Add `_archive/**` to the dead-code tool's ignore list so archived files never resurface.

## Step 4: prove nothing broke
Run what the repo's own config dictates (lockfile picks the package manager): install with the
frozen lockfile, build, typecheck, test. All pass: commit
`chore: archive confirmed legacy code (<date>)`. Anything fails: the file was not dead. Restore
(`git restore --staged --worktree .` then switch back and delete the branch) and report which file
broke what. Never open a PR on a red build.

## Step 5: PR, then stop
Push the branch and open a PR whose body is the manifest plus "build, typecheck and tests passed on
the archived tree". If merging deploys, say so in the PR body. Do not merge a deploy-gated repo.

## Report
Target, branch, PR link or commit, count archived, gate results, one-line restore. For a
deploy-gated repo state plainly: **not merged, not deployed.**
