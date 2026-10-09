# Push code only to approved git hosts

Automates it: none (the corporate guard pack enforces it)

## When to use
Claude's push is refused with "No hosts are approved yet", "is blocked: company code goes only to approved hosts" or "Run the
push as its own command". The corporate guard pack is on by default: company code goes only to hosts you list.

## Steps
1. List your hosts. Either re-run the installer from the unpacked kit with the hosts (comma-separated, exact names):
   `py -3 bootstrap/install.py --apply --git-hosts ghe.example.com,git.example.com`
   or edit `corporate-allowlist.json` in your workbench folder by hand (the template is
   `plugins/workbench-core/scripts/guards/corporate-allowlist.template.json`). Names are exact and case-insensitive: list each
   subdomain and each ssh alias. Claude cannot edit this file; you do.
2. If you do not know the host or how to authorise a token for single sign-on, send the "Git host and sign-in" text in
   `docs/admin-asks.md` (guide 16 shows the sign-in).
3. Work on a feature branch and push it in the plain form, as its own command, from the repository folder:
   `git push -u origin <feature-branch>`. No `cd` first, no `&&`, `;` or pipes, no `-c` options, no variables or wrappers (`bash -c`, `eval`).
4. Merge through a pull request. Pushing to `main`, `master` or the remote's default branch is denied, as is a force-push
   to them.
5. Publishing verbs (gists, releases, uploads, package publishes, PR comments and approvals) ask you every time.

## Verify
- A plain `git push --dry-run origin <feature-branch>` to an approved host is not blocked.
- The same push to a host not on the list is blocked with a message naming that host.
- In a scratch repo, `git push --force origin main` is blocked.

## Common failures
- **"No hosts are approved yet":** `git_remote_hosts` is empty. Do step 1.
- **"That host is not in git_remote_hosts":** add the exact name. `git.example.com` does not cover `ssh.git.example.com`.
- **"Cannot tell where this push goes":** run it from inside the repository, with the plain form and a named remote.
- **A `git` alias is blocked:** an alias may only expand to a read-only command. Use the real command.
- **Pushes still refused after a config change:** `CLAUDE_CONFIG_DIR` differs from the one the installer recorded. Start Claude Code normally, or through a registered profile (guide 07).
- **The guard is not a wall:** it reads shell commands and cannot see inside a script. Your organisation's repository and network controls are the real boundary.
