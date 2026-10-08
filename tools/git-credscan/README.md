# git-credscan

A pre-commit check that blocks a commit when the lines it ADDS carry a credential-shaped value (cloud keys, tokens,
private-key headers, connection strings with passwords, `NAME=secret` assignments). It uses the kit's own pattern
set (`plugins/workbench-core/scripts/secretscan.py`), prints only masked matches, and fails closed if it cannot scan.

```bash
py -3 tools/git-credscan/credscan_staged.py --install <repo>   # writes <repo>/.git/hooks/pre-commit (never overwrites)
py -3 tools/git-credscan/credscan_staged.py                    # scan what is staged in the current repo, by hand
```
Use `python3` on Linux and WSL. Run it from the installed kit (`<claude config dir>/workbench/kit/tools/git-credscan/`)
so the hook keeps working after you delete the download.

- A repo with `core.hooksPath` or a hook framework: `--install` refuses and prints the line to add to it. For the
  `pre-commit` framework, add a `repo: local` hook whose `entry` is that command and `pass_filenames: false`.
- Your organisation's own secret scanning (server-side push protection, CI scanners) still applies; this is an
  earlier, local net, not a replacement.
- It only sees added lines. A credential already in history must be rotated; deleting it from the file does not
  remove it from the repository.

Test: `py -3 -m unittest discover -s tools/git-credscan` (needs git).
