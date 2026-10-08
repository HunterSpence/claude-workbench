# Environment and shell (managed Windows: Git Bash, PowerShell, WSL)

Shell mechanics; the environment itself is `rules/corporate-environment.md`.

## Paths and quoting
- Python and the Edit/Write tools take `C:/...` paths, never Git Bash's `/c/...` form. In Git Bash,
  use forward slashes.
- Remote or quote-heavy commands: send a heredoc, `ssh <host> bash -s <<'EOF'` ... `EOF`, never
  nested quotes inside `ssh <host> "..."`. The same applies to `python -c`, `awk` and `eval`.
- Command substitution: `$(...)` only, never backticks. End diagnostic chains with `; true` so one
  missing item doesn't abort the sweep.

## PowerShell
- **Windows PowerShell 5.1 has no `&&` or `||`** (a parser error); PowerShell 7 has both. In 5.1
  chain with `; if ($?) { ... }`.
- **5.1 writes UTF-16 by default** with `Out-File` and `>`. Pass `-Encoding utf8` (5.1 then adds a
  BOM) or use PowerShell 7, which writes UTF-8 without a BOM.
- The PowerShell tool's path check can misread `/s`, `/inheritance:r` and `*` as `Remove-Item`
  targets when `Remove-Item` shares the command. Run `Remove-Item` alone, with `-LiteralPath`.
- If script execution is blocked by policy, ask IT. Don't work around it.
- If `$ExecutionContext.SessionState.LanguageMode` says `ConstrainedLanguage`, the organisation
  restricts PowerShell on purpose: `Add-Type` and many .NET calls fail by design. Don't try to
  escape it; use another approved tool or ask IT.

## Where files live
- Keep repos outside OneDrive-synced folders (for example `%USERPROFILE%\src`): Desktop and
  Documents are often redirected into OneDrive, and a synced `.git` means conflicts and uploads.

## Processes and long jobs
- **Never fork a subagent:** spawn a fresh one and pass the context. Both settings profiles turn
  fork mode off (`CLAUDE_CODE_FORK_SUBAGENT=0`); forks fail inside workflow workers.
- A background shell command is killed at its timeout. Longer work needs a scheduled task or a
  detached process. **Never `sleep N; cmd`:** poll with a real check.
- Pass a script to an interpreter as a file (or with `-c`). Never feed it line by line into an
  interactive interpreter, for example through `xargs`: it can loop and flood the log.
- Stopping a background task on Windows can leave its children running: kill the tree
  (`taskkill /T /PID <pid>`).

## Memory and parallelism on a laptop
- **Keep concurrent heavy jobs** (test suites, evals, local models) within what the machine's
  memory allows, give each a memory cap, and run the heaviest one at a time. Parallel subagents each
  starting a test suite add up quickly.
- Run stress, fuzz or pathological-input tests under an OS memory cap (a Windows job object, or
  `ulimit -v` / a cgroup inside WSL), so a runaway input can't exhaust memory.
- **Parallel sessions isolate code, not shared state.** Two sessions writing one memory file clobber
  each other, which is why the KB is journalled (`rules/memory-protocol.md`).

## WSL
- WSL has its own Claude Code configuration; a Windows user setting doesn't reach it. (Admins can
  extend managed policy to WSL with `wslInheritsWindowsSettings`; that is theirs to set.) Memory
  caps, sandbox and certificates: `rules/corporate-environment.md`.
