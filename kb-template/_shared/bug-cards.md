---
title: Bug cards
domain: _shared
status: active
---
# Bug cards: recurring failures and how to fix them

Each card is one failure class that keeps coming back, written so that you can act without the history behind it.
Search by symptom words before you debug: `kb_search.py "<symptom words>" --domain _shared --limit 5`. The `repo-fix`
and `investigate` skills do this as their first step. Cards that have a recognisable error string also have a
detector in `bug-detectors.json`; the failure hook matches the error text against those patterns and shows the best card.

To add a card: take the next number, never renumber, fill all five fields, and add a detector only when the error text
is specific (it is tested against its sample and against unrelated errors). Keep personal names, hosts, dates and
numbers out; describe the class, not the incident.

### 1. Exit codes are swallowed by pipes, `|| true` and Out-Null

- **Symptom:** A job logs success for days while doing nothing. CI is green although a step failed. A verify-then-delete chain deletes after the verify failed.
- **Root cause:** A pipeline returns the status of its last command, so `cmd | tail` reports tail's zero. `|| true` erases a failure. A PowerShell script that pipes a native call into Out-Null rarely reads `$LASTEXITCODE`. A wrapper whose last line is an echo exits zero whatever happened above it.
- **Fix:** Use `set -euo pipefail` in bash scripts, or read `${PIPESTATUS[0]}`. In PowerShell check `$LASTEXITCODE` after every native call. Run verify and destroy as two separate steps. End wrappers with `exit "$rc"`. Keep `|| true` for deliberate side-effect steps only.
- **Verifying test:** Make the inner command fail on purpose (`false | tail -n 1`, a wrong path, an unreachable remote) and assert that the wrapper exits non-zero and logs a failure.
- **Spot it fast:** `grep -rnE '\|\s*(tail|head|grep|Out-Null)\b|\|\|\s*true' scripts/ .github/`, then check whether the next line reads the status.

### 2. An empty result is read as "nothing to do"

- **Symptom:** A backup, sync or migration reports "clean tree" or "nothing pending" while real work is waiting.
- **Root cause:** An earlier step failed (a staging command hit an unreadable path and staged nothing, a runner returned on its first error) and the empty output was taken for "no work".
- **Fix:** Tell "empty because done" from "empty because the producer failed": check the producer's exit status, assert a non-zero count when inputs exist, and fail loudly on an early return.
- **Verifying test:** Seed one known pending item, break the producer, and confirm the job reports a failure instead of "nothing to do".
- **Spot it fast:** Compare the tool's own claim with an independent probe, such as `git status --porcelain` next to "clean" or a row count next to "0 pending".

### 3. The console code page crashes Python on non-ASCII output

- **Symptom:** `UnicodeEncodeError: 'charmap' codec can't encode character` appears for a dash or an emoji. It works in an interactive terminal and crashes under a scheduled task, a hook or `pythonw`. A `try/except` around the check silently reports "skipped".
- **Root cause:** On Windows, Python's stdio and `open()` default to the ANSI code page unless UTF-8 mode is on. Setting `PYTHONUTF8` for one launcher leaves every other launcher on the legacy code page.
- **Fix:** Set `PYTHONUTF8=1` at the user environment level. In entry scripts call `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`. Pass `encoding="utf-8"` to `open()` and to `subprocess.run`.
- **Verifying test:** Run a scheduled task that prints a dash and a check mark; it exits zero after the fix and crashed before.
- **Spot it fast:** Under the same launcher run `py -3 -c "import sys,locale;print(sys.stdout.encoding, locale.getpreferredencoding())"`; anything other than UTF-8 is the cause.

### 4. Retrying fetches against hosts that never succeed

- **Symptom:** The same domain fails the same way in every session, and each attempt burns a long timeout.
- **Root cause:** A bot wall, a geo block, corporate egress filtering or a site that drops non-browser clients. The agent has no memory that the host is unreachable.
- **Fix:** After three identical failures from different sessions, add the host to a deny list with a message naming the alternative (a search snippet, an official API, a cached copy). Set short connect timeouts. Never retry a deterministic block.
- **Verifying test:** Replay the logged inputs against the guard: blocked hosts now fail at once with an actionable message and the success rate of the remaining fetches is unchanged.
- **Spot it fast:** Group failures by host (`grep -o 'https\?://[^/]*' errors.log | sort | uniq -c | sort -rn | head`).

### 5. A script assumes a data shape it never inspected

- **Symptom:** `KeyError`, `'NoneType' object is not subscriptable`, or `JSONDecodeError: Expecting value: line 1 column 1` from a throwaway script.
- **Root cause:** The result is wrapped (`{"data": {...}}`), a field is optional, the body is an HTML error page or empty, or the file is newline-delimited JSON.
- **Fix:** Print the type and the first record's keys before processing. Use `.get()` with explicit defaults. Check the status and `Content-Type` before `json.loads`. Parse newline-delimited JSON line by line. Fail with a message naming the missing key.
- **Verifying test:** Run the script against an empty response, an error page and a record missing the optional field; each gives a clear message instead of a traceback.
- **Spot it fast:** `python -c "import json;d=json.load(open('f.json'));print(type(d), list(d)[:5] if isinstance(d,dict) else d[0])"`.

### 6. Nested quotes across ssh, `bash -c` and `python -c`

- **Symptom:** `unexpected EOF while looking for matching quote`, a remote command that runs half of what you wrote, or a `$variable` expanded on the wrong machine.
- **Root cause:** Two shells (local and remote, or outer and inner) each strip one quoting level, and `$()` or backticks expand locally before the command is sent.
- **Fix:** Send the script on stdin with a quoted heredoc: `ssh host bash -s <<'EOF'` ... `EOF`. The quoted marker stops local expansion. For longer logic write a script file and run it. Prefer `$(...)` to backticks.
- **Verifying test:** Run a command containing a single quote, a double quote and `$HOME` through the heredoc form and check that it prints the REMOTE value of `$HOME`.
- **Spot it fast:** `bash -n -c '<the command>'` locally, and count the quote levels.

### 7. Git Bash rewrites arguments that look like paths

- **Symptom:** `gh api /repos/...` hits a filesystem path. `git show origin/main:/path` fails with `ambiguous argument 'origin\main;C:\...'`. A `/c/...` path is rejected by a native Windows program.
- **Root cause:** MSYS converts POSIX-looking arguments into Windows paths when it starts a native executable: a leading slash, or a colon-separated list whose later part starts with a slash. `origin/main:path` is left alone, but `origin/main:/abs/x` becomes `origin\main;C:\Program Files\Git\abs\x`.
- **Fix:** Drop the leading slash where the tool allows it (`gh api repos/...`). The kit's profiles set `MSYS2_ARG_CONV_EXCL=origin/;upstream/;refs/`, which stops Git Bash rewriting `origin/main:/path` into `origin\main;C:\...` and keeps `/c/...` conversion working; for another argument shape prefix that one command with `MSYS_NO_PATHCONV=1` (the blanket `MSYS2_ARG_CONV_EXCL='*'` also switches off the helpful conversions). Give Windows tools `C:/...` paths, never `/c/...`.
- **Verifying test:** The same command with the opt-out variable returns the expected object; without it, it reproduces the error.
- **Spot it fast:** Echo the argument through a native program (`cmd //c echo /repos/x`) and look at the converted form.

### 8. Quoting differs between PowerShell and Git Bash

- **Symptom:** A JSON argument reaches a native command with its double quotes stripped. `The string is missing the terminator` or `Invalid JSON primitive` appears. A `$name` is expanded when it should be literal, or the reverse. The same one-liner works in the other shell.
- **Root cause:** Each shell has its own quote and escape rules. PowerShell expands `$` inside double quotes and uses the backtick as its escape character. Windows PowerShell 5.1 drops the inner double quotes of a native-command argument. Git Bash treats single quotes as fully literal.
- **Fix:** Write the payload to a file and pass the path, or pipe it on stdin. In PowerShell use single-quoted here-strings for literal text and `--%` only when you must. Say in the script header which shell it targets, and do not paste a bash one-liner into PowerShell.
- **Verifying test:** Run the command with a payload holding a double quote, a single quote and a dollar sign in each shell, and compare what the receiving program prints.
- **Spot it fast:** Print the received arguments with a tiny program (`py -3 -c "import sys;print(sys.argv)" <args>`) before blaming the tool.

### 9. Two writers clobber one shared file

- **Symptom:** Entries written by one session vanish. A global flag flips because another session started.
- **Root cause:** Read-modify-write without a lock. On Windows the C runtime emulates append mode as seek-then-write, so concurrent appends race. One machine-wide state file is shared by every session.
- **Fix:** Use a journal: one append-only file per writer or per entry, merged later. Where a single file is unavoidable, take an OS lock around the read-modify-write (`msvcrt.locking` after `seek(0)`, `fcntl.flock`, or an exclusive-create lock file). Key per-session state by session id.
- **Verifying test:** Run eight concurrent writers in a loop and count the lines; all of them survive across many repetitions.
- **Spot it fast:** `for i in $(seq 8); do (python writer.py $i &); done; wait; wc -l file`.

### 10. A guard hook fails open on unexpected input

- **Symptom:** A dangerous command passes a guard that should block it. The guard log shows a parse exception, or nothing at all.
- **Root cause:** Hooks usually catch every exception and allow, so that a bug never blocks work. A byte-order mark on stdin, an unexpected field shape or a timeout then disables the guard silently. Pattern checks also have blind spots (an even quote count hiding a broken heredoc, refspec forms such as `+ref:main`).
- **Fix:** Decode stdin with `utf-8-sig`. Log every caught exception with the hook id. Keep a corpus of known-bad commands that MUST block and run it in CI as positive controls. Parse the command with the shell (`bash -n`) whenever quotes or heredoc markers appear.
- **Verifying test:** The positive-control corpus blocks completely, and a payload with a byte-order mark is blocked rather than allowed.
- **Spot it fast:** `printf '\xef\xbb\xbf{"tool_input":{"command":"..."}}' | python hook.py; echo $?`.

### 11. Line endings: text-mode writes turn LF into CRLF

- **Symptom:** On Linux `$'\r': command not found`, `set: pipefail: invalid option name`, or `bad interpreter` with an invisible carriage return. Checksum lists report files that do not exist. Byte-size caps trip on carriage returns alone. Byte-exact tests fail only on Windows.
- **Root cause:** `open(p, "w")` and `Path.write_text` translate `\n` to `\r\n` on Windows, and git may convert on checkout when `core.autocrlf` is set.
- **Fix:** Write with `newline="\n"` or in binary mode. Commit a `.gitattributes` with `* text=auto` and `*.sh text eol=lf`. Normalise an affected file once with `dos2unix`. Measure caps on LF-normalised content.
- **Verifying test:** `grep -c $'\r' script.sh` prints zero after the writer runs on Windows, and `bash -n script.sh` passes on Linux.
- **Spot it fast:** `file script.sh` says "with CRLF line terminators", or `grep -c $'\r' file` is not zero.

### 12. A command-line tool is missing: command not found

- **Symptom:** `command not found` (a JSON processor, a document converter, a package manager), a file reader that says a renderer is not installed, or a CI step that assumed a global install. Claude Code's own wording is `Could not locate the Claude CLI on PATH` (editor extension) or `'claude' is not recognized`.
- **Root cause:** The tool was assumed to be on PATH. Git Bash, PowerShell, cmd and CI runners each have a different PATH.
- **Fix:** Preflight with `command -v tool` and print an install hint. Install through the package manager and put the shim on PATH. In CI install explicitly with a setup action. Prefer a standard-library fallback (Python `json` instead of `jq`). For Claude Code itself, put `%USERPROFILE%\.local\bin` on the user PATH (not only in a PowerShell profile, which the editor extension does not run), then restart the editor, which reads the PATH it captured at startup.
- **Verifying test:** The preflight fails fast with the hint on a clean machine and passes after the install.
- **Spot it fast:** `command -v tool || where tool` in the same shell the agent uses.

### 13. A Python script runs under the wrong interpreter

- **Symptom:** `ModuleNotFoundError` for a package you know is installed.
- **Root cause:** `python` or `py` resolves to the system interpreter instead of the project's virtual environment, or an environment created by a tool that ships no pip.
- **Fix:** Call the environment's interpreter by path, or use `uv run --with <pkg> python script.py` for ad-hoc needs. Install with `python -m pip install`, never a bare `pip`.
- **Verifying test:** The `sys.executable` printed by the script is the environment's, and the import succeeds.
- **Spot it fast:** `python -c "import sys;print(sys.executable)"` against the environment's path, and `python -m pip show <pkg>`.

### 14. An async function is called without await

- **Symptom:** `'coroutine' object is not iterable`, `RuntimeWarning: coroutine ... was never awaited`, or in JavaScript a Promise logged as `[object Promise]` while the work is silently skipped.
- **Root cause:** A function became async in one change and its call sites stayed synchronous.
- **Fix:** Await the call or add it to the gather group. Turn on the lint rule (`no-floating-promises` for TypeScript, ruff `RUF006` or flake8-async for Python). Add a dispatch test that calls every registered handler.
- **Verifying test:** The dispatch test fails on a synchronous call to an async handler and passes after the fix.
- **Spot it fast:** Run `python -X dev -W error::RuntimeWarning script.py`; in TypeScript enable the lint rule.

### 15. A migration runner halts silently or is not idempotent

- **Symptom:** A later deploy assumes a column that was never created and requests fail everywhere. The second deploy fails with "already exists". The migrations folder is not found inside the container.
- **Root cause:** The runner returned on its first failing file without failing the boot. A folder that is re-applied on every deploy held a bare `ADD COLUMN`. The folder path was resolved relative to the build output.
- **Fix:** Record each migration once in a version table and apply new ones in a transaction. Exit non-zero on any error. Keep manual-only files out of the automatic folder. Resolve the folder from the runtime working directory and copy it into the image.
- **Verifying test:** Run the runner twice on a fresh database and once with a deliberately broken file: the second run is a no-op and the broken file fails the boot.
- **Spot it fast:** Compare the migrations table with the files on disk.

### 16. Cross-origin API calls fail in bursts

- **Symptom:** Many requests fail with `TypeError: Failed to fetch` on navigation while server logs and curl probes look healthy.
- **Root cause:** Every cross-origin call with custom headers needs a preflight. Under bursts the edge drops some, and a method missing from `Access-Control-Allow-Methods` fails some verbs. Curl sends no preflight, so it cannot reproduce this.
- **Fix:** Serve the API same-origin through a path proxy, or cache preflights with `Access-Control-Max-Age` and allow every method and header in use. Reproduce in a real browser, never with curl alone.
- **Verifying test:** A scripted browser burst of concurrent calls returns every response.
- **Spot it fast:** Filter the browser's network panel to OPTIONS requests.

### 17. The server does not send its intermediate certificate

- **Symptom:** Node or Python clients fail TLS with `unable to verify the first certificate` while the browser loads the same page.
- **Root cause:** The server presents only its leaf certificate. Browsers fetch the missing intermediate themselves; most libraries do not.
- **Fix:** The site owner must serve the full chain. Client-side, add the intermediate to a CA bundle only as a stopgap. Never turn verification off.
- **Verifying test:** The same request succeeds with verification on, and `openssl s_client` reports `Verify return code: 0`.
- **Spot it fast:** `openssl s_client -connect host:<port> -showcerts </dev/null` and read the chain and the issuer.

### 18. A TLS-inspecting proxy needs its root certificate authority trusted by every runtime separately

- **Symptom:** Browsers and the operating system work, while Node, Python, pip, git, curl or a Java tool fail with `self-signed certificate in certificate chain`, `CERTIFICATE_VERIFY_FAILED` or `SSL certificate problem`.
- **Root cause:** The organisation's proxy re-signs HTTPS with its own root certificate. The browser reads the operating-system store, but each runtime keeps its own trust store and ignores it by default.
- **Fix:** Export the organisation's root certificate once, then point each runtime at it: `NODE_EXTRA_CA_CERTS` or `NODE_USE_SYSTEM_CA=1` for Node, `REQUESTS_CA_BUNDLE` and `SSL_CERT_FILE` for Python (or the `truststore` package), `pip config set global.cert`, `git config --global http.sslCAInfo` or `http.sslBackend schannel`, `CURL_CA_BUNDLE` for curl, `UV_SYSTEM_CERTS=1` for uv, and the keystore for Java. Never disable verification. Claude Code trusts the operating-system store as well as its bundled set by default (`CLAUDE_CODE_CERT_STORE` defaults to `bundled,system`). For the Windows installer, enable TLS 1.2 in PowerShell before `irm`.
- **Verifying test:** One real HTTPS call from each runtime (python, node, git, pip, curl) succeeds with verification on.
- **Spot it fast:** `openssl s_client -connect host:<port> -showcerts </dev/null` shows the organisation's issuer instead of the public one.

### 19. Parallel fan-outs hit rate limits

- **Symptom:** `Rate limit exceeded`, usage-limit errors, or every later call in a fan-out failing the same way. Unauthenticated API calls die quickly. Also `Request rejected (<status>)`, `rate_limit_error`, `Concurrent subagent limit reached` and `Agent terminated early due to an API error`.
- **Root cause:** Many simultaneous model or API calls share one key. Limits are keyed per app or per tenant, not per user, and unauthenticated tiers are small.
- **Fix:** Work in waves of three or four. Back off exponentially with jitter and honour `Retry-After`. Authenticate. Cache results. On a quota error stop launching new work instead of retrying every task. Use unmetered feeds where they exist. A rate-limit reply with no `retry-after` header is a spend cap: stop retrying and raise the cap. Claude Code also caps running subagents (the default is twenty): wait for running agents to finish, and raise `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` only on purpose.
- **Verifying test:** The same workload completes with no rate-limit errors in about the same wall time.
- **Spot it fast:** Count requests per minute per key in the logs and read `Retry-After` and `X-RateLimit-Remaining`.

### 20. Date windows are built in naive UTC instead of local time

- **Symptom:** Late-evening records land on the wrong day. A daily job is called "stale" before it was due.
- **Root cause:** "The day" was built as midnight to midnight UTC, which is a different day in every other zone. Driver date objects were stringified with a locale format. Staleness was judged in local time against a UTC schedule.
- **Fix:** Build windows from local midnight in the user's IANA zone and convert to UTC (`zoneinfo`, `Temporal`, `date-fns-tz`). Serialise in ISO format. Check the machine's clock with `date -u` before calling a job late.
- **Verifying test:** Tests for a zone far from UTC and for a daylight-saving transition day pass.
- **Spot it fast:** `grep -rn 'T00' src/`.

### 21. Lockfile drift breaks frozen installs

- **Symptom:** `ERR_PNPM_OUTDATED_LOCKFILE` or an `npm ci` mismatch in one job but not another. An `overrides` entry does nothing. A package-manager version conflict between the setup action and the manifest.
- **Root cause:** Dependencies were edited without regenerating the lockfile, jobs install in different frozen modes, an override selector matches the declared range text instead of the resolved version, or two lockfile systems describe one tree.
- **Fix:** Use one install mode everywhere (frozen in CI). Regenerate the lockfile in the same change as the manifest. Let the setup action read the package-manager version from the manifest. After adding an override, regenerate and grep the lockfile for the resolved version.
- **Verifying test:** The frozen install passes on a clean clone and the lockfile shows the overridden version.
- **Spot it fast:** Run the frozen install (`pnpm install --frozen-lockfile` or `npm ci`) on a clean clone.

### 22. `git stash` is shared by every worktree of a repository

- **Symptom:** After `git stash pop` in one worktree, files from another task appear, or another agent's stash is gone.
- **Root cause:** `refs/stash` belongs to the repository, not to the worktree.
- **Fix:** Never stash in parallel worktrees. Commit work in progress to the worktree's own branch, or apply by hash (`git stash apply <hash>`) and drop only your own entry.
- **Verifying test:** Two worktrees each stash and restore by hash and neither sees the other's files.
- **Spot it fast:** `git stash list` from any worktree shows the entries of all of them.

### 23. Concurrent sessions switch the branch of a shared checkout

- **Symptom:** A commit lands on the wrong branch, or files change while you are editing them.
- **Root cause:** Several agents share one working tree and each runs `git checkout`.
- **Fix:** Give each session its own worktree: `git worktree add ../wt-<task> -b <branch> origin/main`. Never switch branches in the shared checkout.
- **Verifying test:** Two parallel sessions commit to their own branches with no crossover in the reflog.
- **Spot it fast:** `git reflog -n 5` lists checkouts you did not run.

### 24. Forgotten worktrees strand branches and their fixes

- **Symptom:** `git branch -d` refuses because the branch is checked out somewhere. A fix never reached the main branch because it sat in a worktree nobody opened.
- **Root cause:** Worktrees are invisible in normal use, and `git worktree remove` leaves the branch behind.
- **Fix:** After cleanup run `git worktree prune` and `git worktree list`, then merge or delete each leftover branch. Put the worktree listing in the end-of-task checklist.
- **Verifying test:** `git worktree list` shows only the main checkout and `git branch --no-merged main` is empty or intended.
- **Spot it fast:** `git worktree list` and `git branch --no-merged main`.

### 25. Scripts lose their executable bit when committed from Windows

- **Symptom:** A service fails with an exec error, or `./script.sh` says `Permission denied` on Linux after deploy.
- **Root cause:** Windows has no executable bit, so new files are committed with the plain non-executable mode.
- **Fix:** Run `git update-index --chmod=+x path/*.sh` and commit. Add a CI check that fails on a non-executable `*.sh`. Keep a `chmod +x` backstop in the deploy script.
- **Verifying test:** The CI check fails on a non-executable script and passes after the fix.
- **Spot it fast:** `git ls-files -s '*.sh'` and look at the mode column.

### 26. Hook and agent definitions are snapshotted per session

- **Symptom:** An edited hook timeout or a new agent file has no effect in the session where you changed it. A spawned subagent ignores new instructions. `Agent type 'x' not found` appears for a file you just created. A hook that is listed by `/hooks` but never fires.
- **Root cause:** Claude Code loads hook configuration and agent definitions at session start.
- **Fix:** Verify a change in a NEW session (a headless run is enough). Say "takes effect next session" in change notes. Enumerate plugin-registered hooks as well as the settings file. For a hook that never fires, check the matcher first: it is a single string (`Edit|Write`), never an array, and a misspelled tool name matches nothing and fails silently. `claude --debug` logs which matchers were checked.
- **Verifying test:** The fresh session shows the new behaviour and the old one does not.
- **Spot it fast:** `claude -p --agent <name> "print your rules"` in a new process, and compare.

### 27. Hook timeouts silently drop injected context

- **Symptom:** A SessionStart or prompt hook works in tests, but its text is missing under load, and nothing reports the loss.
- **Root cause:** Short hook timeouts expire when the machine is busy, and the hook's output is discarded without an error.
- **Fix:** Keep hooks fast: no fresh PowerShell per call and no interpreter probing. Raise the timeout. Verify injection per session instead of assuming it.
- **Verifying test:** Under a CPU-loaded run, every session logs the injection.
- **Spot it fast:** Have the hook log `session_id` and bytes emitted, then join that log with the sessions that started.

### 28. Reading a whole large file exceeds the read limit

- **Symptom:** `File content (<n> tokens) exceeds maximum allowed tokens (<limit>)`.
- **Root cause:** Whole-file reads of logs, lockfiles or generated JSON.
- **Fix:** Grep for the region first, then read with an offset and a limit. Summarise generated files with a script. A tool result from an MCP server over ten thousand tokens triggers a warning and is capped by default: raise the cap with `MAX_MCP_OUTPUT_TOKENS` or paginate in the server.
- **Verifying test:** The next read of that file uses an offset and a limit and succeeds.
- **Spot it fast:** `wc -c file` before reading; anything beyond a few hundred lines needs paging.

### 29. Invented file paths

- **Symptom:** `File does not exist` or `Directory does not exist`, sometimes with "did you mean ...".
- **Root cause:** The agent rebuilt a path from memory: an old home folder, a renamed repository, a different worktree. Often the file name survives and the rest is invented.
- **Fix:** Run a Glob or `git ls-files | grep <name>` before Read or Edit. Keep moved-path notes in one place.
- **Verifying test:** The agent resolves the path with one search and the read succeeds.
- **Spot it fast:** Glob for the base name: `**/<basename>`.

### 30. An edit fails because the file changed since it was read

- **Symptom:** `File has been modified since read, either by the user or by a linter`.
- **Root cause:** A formatter, another session or a save hook rewrote the file between the read and the edit.
- **Fix:** Re-read immediately before editing. Prefer small targeted edits to whole-file writes on files other sessions touch.
- **Verifying test:** The retry after a fresh read applies cleanly and nothing from the other writer is lost.
- **Spot it fast:** `git diff --stat <file>` right before the edit.

### 31. The command line is too long

- **Symptom:** The shell refuses to run a huge one-liner: `The command line is too long` or `Argument list too long`.
- **Root cause:** Payloads (JSON, scripts, file lists) were passed inline as arguments, and every platform caps a process command line.
- **Fix:** Write the payload to a file and pass the path, or pipe it on stdin.
- **Verifying test:** The same payload succeeds through a file.
- **Spot it fast:** Measure the command's length; cmd.exe allows far less than PowerShell, and PowerShell far less than a pipe.

### 32. Compound and inline commands trigger permission prompts

- **Symptom:** A command prompts although each of its parts is allowed. `sh -c "..."` prompts even in a permissive mode. Broad allow rules seem ignored in auto mode.
- **Root cause:** The permission checker cannot inspect inline `-c` strings and evaluates every segment of a compound command. Some modes drop wildcard allow rules.
- **Fix:** Write multi-step logic to a script file and run that. Keep allow rules specific. Avoid inline `bash -c`.
- **Verifying test:** The script-file form runs without a prompt.
- **Spot it fast:** Split the command at `&&`, `;` and `|` and test each part alone.

### 33. Polling with fixed sleeps instead of waiting on a condition

- **Symptom:** Foreground sleeps are blocked, long waits hit the tool timeout, and background waiters are killed.
- **Root cause:** A fixed sleep guesses at timing.
- **Fix:** Run long jobs in the background and get notified on exit, or poll a real condition (`until [ -f done ]; do sleep 5; done` inside a background job). Write results to disk so a killed waiter loses nothing.
- **Verifying test:** The job's completion is detected without a fixed sleep in the foreground.
- **Spot it fast:** `grep -rnE 'sleep [0-9]+;' scripts/` and the transcript of the blocked call.

### 34. Structured output is rejected because the payload is nested

- **Symptom:** `Output does not match required schema: root: must have required property 'findings'`, repeated across retries.
- **Root cause:** The model wrapped the payload one level down (`{"result": {"findings": ...}}`) or returned a string where an array is required.
- **Fix:** Put a minimal valid example of the exact top-level shape in the prompt. Cap retries. Validate locally before submitting.
- **Verifying test:** Ten consecutive runs produce schema-valid output first time.
- **Spot it fast:** Print the top-level keys of the rejected output; the required key is usually one level down.

### 35. Secret scanners flag hashes, and fixtures trip the scanner they test

- **Symptom:** A pre-commit hook blocks thousands of "tokens" that are digests. A test fixture with literal key formats fails CI. A positive control that the allowlist already matches proves nothing.
- **Root cause:** Generic rules match any long hex string, and fixtures contain real-looking secrets.
- **Fix:** Require vendor prefixes in custom rules. Allowlist evidence folders by path. Build secret-shaped fixtures at run time. Pick positive controls the allowlist does not match.
- **Verifying test:** The scanner passes on the hash-only evidence and still fires on a positive control built at run time.
- **Spot it fast:** Group the findings by match length; one repeated length means a hash.

### 36. Secrets leak through argv, clone URLs and config tools

- **Symptom:** A token visible in `ps` output or CI logs. A temporary clone's git config file holds a token. A config command prints a fresh OAuth token to stdout.
- **Root cause:** Credentials were passed as command arguments or embedded in URLs, and some tools echo secrets.
- **Fix:** Pass secrets through environment variables or credential helpers. Delete temporary clones. Redirect config-tool output to a protected file. Mask values in CI.
- **Verifying test:** `ps`, the clone's config and the CI log contain no token after the change.
- **Spot it fast:** `git config --get remote.origin.url | grep -E '//[^@]+@'`, and grep CI logs for the token's prefix.

### 37. Results differ between processes

- **Symptom:** The same query scores differently in two runs, and the top results flip on another machine.
- **Root cause:** Iteration order of sets and dicts of strings depends on `PYTHONHASHSEED`, and float ties break differently across CPUs. A determinism test inside one process cannot see either.
- **Fix:** Sort explicitly with a stable tie-breaker. Pin `PYTHONHASHSEED` for identity proofs. Run paired comparisons in one process or container.
- **Verifying test:** A two-process determinism test passes many times in a row.
- **Spot it fast:** Run the same input in two fresh processes and diff the output.

### 38. A green local suite skipped the integration tests

- **Symptom:** Every test passes locally, yet the production query is broken.
- **Root cause:** Integration tests auto-skip when a connection string or an optional dependency is missing.
- **Fix:** In CI make missing integration prerequisites a failure, not a skip. Print a skip summary. Point the tests at a dedicated database.
- **Verifying test:** CI fails when the connection string is unset and passes when it is set.
- **Spot it fast:** `pytest -rs | tail` shows how many tests were skipped and why.

### 39. Silent truncation of text

- **Symptom:** Stored notes end mid-sentence with no marker.
- **Root cause:** A defensive slice such as `text[:N]` with no marker and no warning.
- **Fix:** Refuse or split oversized input. If truncating, append an explicit marker and log it.
- **Verifying test:** A long input is stored whole or rejected with an error, never cut silently.
- **Spot it fast:** `grep -rn 'text\[:[0-9]\+\]\|\.slice(0, *[0-9]\+)' src/`.

### 40. Network clients without a timeout hang forever

- **Symptom:** A job stalls at low CPU and dies exactly at an outer timeout.
- **Root cause:** Some standard clients (mail protocols, raw sockets, some HTTP libraries) have no default timeout, and nested timeouts in the wrong order kill the outer layer first.
- **Fix:** Pass explicit connect and read timeouts everywhere. Order nested timeouts inner < middle < outer.
- **Verifying test:** Point the client at an address that never answers; it fails within the configured timeout.
- **Spot it fast:** A stack dump (`py-spy dump --pid <pid>`) shows a blocking socket read.

### 41. stdin is consumed by the wrong command

- **Symptom:** A script fed on stdin stops after an inner `ssh`. `python3 - <<EOF` reads nothing from `sys.stdin`.
- **Root cause:** An inner `ssh` reads the rest of the script from stdin, and with `python3 -` the heredoc IS stdin.
- **Fix:** Use `ssh -n` (or `< /dev/null`) for inner ssh calls. Pass data to `python3 -` scripts through a file or an argument.
- **Verifying test:** The lines after the inner ssh now run.
- **Spot it fast:** Add `echo after` lines; if they never print, stdin was eaten.

### 42. Killing a process does not stop its tree, and pgrep matches itself

- **Symptom:** A loop keeps spawning after you killed the child. A "still running" alarm is the check itself.
- **Root cause:** Only the leaf was killed. `pgrep -af X | grep Y` sees its own command line.
- **Fix:** Kill the tree (`taskkill /T /PID`, or `kill -- -<pgid>`). Use `pgrep -f '[X]pattern'` or match by exact process name.
- **Verifying test:** After the kill no descendant remains, and the check reports zero when nothing runs.
- **Spot it fast:** `ps -ef --forest` on Linux, or `Get-CimInstance Win32_Process | ? ParentProcessId -eq <pid>` on Windows.

### 43. A child process deadlocks on a small Windows pipe

- **Symptom:** A subprocess hangs on Windows but not on Linux.
- **Root cause:** Windows pipe buffers are small compared with Linux. A parent that polls without reading leaves the child blocked in a write.
- **Fix:** Send the child's output to a file, or use `communicate()`, or read in a thread.
- **Verifying test:** A child that prints a megabyte completes on Windows.
- **Spot it fast:** The child is blocked in a write while the parent never reads its pipe.

### 44. Path length limit breaks deep paths on Windows

- **Symptom:** `FileNotFoundError` for a file that exists. Zipping, copying or checking out a deep tree fails with `Filename too long`.
- **Root cause:** The legacy path limit applies to paths without the long-path prefix, and the opt-in must be set in the operating system AND in the application's manifest.
- **Fix:** Prefix absolute paths with `\\?\` in your own code. Where policy allows, enable long paths in the operating system (otherwise ask IT: `docs/admin-asks.md`) and run `git config --global core.longpaths true`. Keep checkouts near the drive root (a short folder name). Skip junctions when walking a profile.
- **Verifying test:** A walk or checkout of the deepest file in the tree completes without error.
- **Spot it fast:** `python -c "import os;print(max(len(os.path.join(r,f)) for r,_,fs in os.walk('.') for f in fs))"` and compare it with the limit.

### 45. Scheduled-task quirks on Windows

- **Symptom:** A console window flashes on every run. A daily task never runs after the laptop slept. The scheduler reports the task as already running, or a wrapper dies and the next trigger starts a second copy.
- **Root cause:** A `.cmd` target always opens a console (the "Hidden" box only hides the task from the list). Missed triggers are skipped unless StartWhenAvailable is set. IgnoreNew refuses a start while an old instance lives.
- **Fix:** Launch through a windowless interpreter (`pythonw.exe` or a no-window launcher). Set StartWhenAvailable. Take a named mutex at script start so a second copy exits.
- **Verifying test:** Trigger the task twice quickly: one run, no window, and the second exits cleanly.
- **Spot it fast:** `Get-ScheduledTask <name> | Select -Expand Settings` and `Get-ScheduledTaskInfo <name>`.

### 46. The Microsoft Store Python alias stub hangs or denies

- **Symptom:** A hook or shim that probes `python3` hangs until its timeout, or says `Permission denied` through a bash shim.
- **Root cause:** App execution aliases are placeholders that open the Store or block when no real Python was installed through it.
- **Fix:** Turn off the Python aliases (Settings, Apps, App execution aliases) and call the real interpreter by full path or through `py -3`.
- **Verifying test:** `python3 --version` returns at once with the expected version.
- **Spot it fast:** `where python python3` lists a `WindowsApps` entry first.

### 47. Editable installs and worktrees import the wrong checkout

- **Symptom:** Tests in a worktree pass or fail according to the MAIN checkout's code. Editing a file in one virtual environment changes another.
- **Root cause:** An editable install points at the main checkout's source folder, and some environment tools hardlink package files between environments.
- **Fix:** Use `PYTHONPATH=src`, or a per-worktree environment with its own editable install, when testing a worktree. Copy a file instead of editing inside a shared environment.
- **Verifying test:** `pkg.__file__` points into the worktree.
- **Spot it fast:** `python -c "import pkg;print(pkg.__file__)"` from the worktree.

### 48. OneDrive holds a lock on files, or syncs a git repository, virtual environment or database

- **Symptom:** `The process cannot access the file because it is being used by another process` on a file nobody has open. `Unable to create '.git/index.lock'`. A git repository, a virtual environment or a SQLite file inside a synced folder is corrupt or full of conflict copies. Builds are slow because the sync client rescans every write.
- **Root cause:** The sync client opens files while it uploads or rescans them, and keeps placeholders for files that are not on disk. Tools that write many small files, lock files or database journals race it. Two machines syncing one repository merge object files byte by byte.
- **Fix:** Keep git repositories, virtual environments, `node_modules`, build output and databases outside any synced folder (a plain folder under the user profile, or a Dev Drive). Keep the knowledge base in the synced work cloud only as plain Markdown, and never as a git repository there. Mark a folder "always keep on this device" when tools must read it. Retry a locked file after a short wait instead of killing the sync client. For `Failed to download binary: The process cannot access the file` during a Claude Code install, close other installer windows, wait for antivirus scans to release the file, delete `%USERPROFILE%\.claude\downloads` and run the installer again.
- **Verifying test:** A clone, build and test run in the unsynced folder finishes with no lock errors, and the synced folder holds no `.git`.
- **Spot it fast:** `git rev-parse --show-toplevel` and `echo %OneDrive%` (or the OneDrive environment variables) show the repository under a synced root.

### 49. WSL DNS stops working while a VPN is connected

- **Symptom:** Inside WSL `Temporary failure in name resolution` or `Could not resolve host`, while Windows itself resolves the same name. It starts when the VPN connects, or after a sleep.
- **Root cause:** WSL generates its resolver file from the Windows side. A VPN client replaces the Windows DNS servers or adds a split-DNS suffix list that the generated file does not carry, and the virtual network adapter may also lose its route.
- **Fix:** Check `/etc/resolv.conf`. Set `generateResolvConf = false` under `[network]` in `/etc/wsl.conf`, write the organisation's DNS servers and search suffixes into `resolv.conf`, then run `wsl --shutdown` from Windows. Where policy allows, switch the networking mode to mirrored in the WSL settings file. If policy blocks that, ask IT (`docs/admin-asks.md`) instead of working around it.
- **Verifying test:** `getent hosts example.com` and `curl -I https://example.com` succeed inside WSL with the VPN connected, and still succeed after a restart of the VPN.
- **Spot it fast:** In WSL `cat /etc/resolv.conf` and `getent hosts <internal host>`; compare with `ipconfig /all` on Windows.

### 50. Unpinned npx and uvx runs fetch whatever is newest today

- **Symptom:** An MCP server or CLI that worked yesterday fails to start today, changes its tool list or behaviour, or `npm ERR! notarget No matching version found`. Start-up is slow because every launch resolves the package again.
- **Root cause:** `npx -y pkg` and `uvx pkg` resolve the newest version on every launch. A new release, a yanked version or a registry outage changes what runs, and a hijacked package runs with your permissions.
- **Fix:** Pin an exact version (`npx -y pkg@<exact>`, `uvx pkg==<exact>`), record the pin in one place, and update it on purpose after reading the changelog. Prefer the organisation's package mirror. Run `skill-scan` or a review on a server before the first launch.
- **Verifying test:** Two launches on different days print the same version, and the lock or pin file is the only place the version lives.
- **Spot it fast:** `grep -rnE 'npx (-y )?[^@ ]+( |$)|uvx [^= ]+( |$)' .mcp.json settings/ mcp/` lists launches without a version.

### 51. A policy denial is retried in another shape

- **Symptom:** A hook, a permission rule, a gateway or a managed setting refuses an action, and the agent tries the same goal through a different shell, tool or path. Each retry produces a new log line for the security team.
- **Root cause:** The denial was read as a bug to route around instead of as a decision. Retrying through another route can breach the policy, and it hides the real fix: an approval.
- **Fix:** Stop. Report the denial verbatim: the tool, the command, the message and the rule id. Do not retry by another route or shell. Use the matching ask-IT text from `docs/admin-asks.md`, continue with the work that is not blocked, and record the blocked step.
- **Verifying test:** A forced denial in a test session ends in a stop and a verbatim report, with no second attempt in the log.
- **Spot it fast:** Two or more near-identical attempts in a row after a denial message.

### 52. Two SSH clients on one Windows machine

- **Symptom:** An `ssh_config` option works in Git Bash and breaks the Windows ssh, or the reverse. `Permission denied (publickey)` appears in one shell only.
- **Root cause:** Git for Windows ships its own OpenSSH, often newer than the Windows one. Both read the same config and may use different agents and key paths.
- **Fix:** Guard new options with `IgnoreUnknown <Option>`. Pin `IdentityFile` and the user per host. Pick one agent.
- **Verifying test:** `ssh host true` works from both shells.
- **Spot it fast:** `where ssh` and `ssh -V` in each shell, then `ssh -vv host 2>&1 | grep -E 'identity|Offering'`.

### 53. git in a plain folder reports a parent repository

- **Symptom:** A status loop over folders reports the home repository's state for a folder that has none, or dies with a fatal error halfway.
- **Root cause:** Git searches parent directories for a repository.
- **Fix:** Test `[ -e "$d/.git" ]` before calling git, or set `GIT_CEILING_DIRECTORIES`. Continue the loop on a per-folder error and report it.
- **Verifying test:** The loop reports "not a repo" for plain folders and finishes.
- **Spot it fast:** `git -C <dir> rev-parse --show-toplevel` and compare the result with `<dir>`.

### 54. CI trigger and concurrency surprises

- **Symptom:** Marking a draft pull request ready starts nothing. Deploys are cancelled during a burst of merges and production stays on an old build. A same-day date filter on the runs API returns nothing.
- **Root cause:** The default `pull_request` types exclude `ready_for_review`. A concurrency group with cancel-in-progress cancels deploys. Date filters exclude the current day.
- **Fix:** Add `ready_for_review` to the types. Use `cancel-in-progress: false` for deploy workflows so they queue. Query runs without the date filter and filter locally.
- **Verifying test:** After a burst of merges the last commit's deploy completes.
- **Spot it fast:** `gh run list --workflow <file> --limit 5` and look for cancelled runs.

### 55. Untrusted text is substituted into a workflow script

- **Symptom:** A linter warns that an expression is untrusted. A pull request title with quotes breaks a step, or runs code.
- **Root cause:** Workflow expressions are substituted into the shell script before it runs.
- **Fix:** Pass untrusted values through `env:` and reference `"$VAR"` in the script. Run a workflow linter in CI.
- **Verifying test:** A pull request titled with a quote, a semicolon and a command prints the title literally.
- **Spot it fast:** `grep -n '\${{ *github\.event\.' .github/workflows/*.yml` inside `run:` blocks.

### 56. An empty environment variable means unset on Windows

- **Symptom:** A test that blanks a variable still reads the real value from a fallback. A setting present in one launcher is missing in tasks started elsewhere.
- **Root cause:** On Windows, setting a variable to an empty string removes it, so the code falls back to its default. Environment set in one tool's settings does not reach other launchers.
- **Fix:** Isolate tests with an explicit sentinel (such as the null device path) instead of a blank. Set machine-wide needs at user or machine level.
- **Verifying test:** The child sees the sentinel and never touches the fallback.
- **Spot it fast:** In the child run `python -c "import os;print('X' in os.environ)"`.

### 57. A broad `except` asserts one cause

- **Symptom:** The error message names a cause that is not the real one, and debugging goes the wrong way for days.
- **Root cause:** One handler covers many failure modes and prints a fixed message.
- **Fix:** Catch the narrow exception, or include the original error text in the message.
- **Verifying test:** Forcing a different failure shows that failure's real text.
- **Spot it fast:** `grep -n 'except OSError\|except Exception' -A2` where the handler prints a specific reason.

### 58. Parallel test jobs exhaust the machine

- **Symptom:** The desktop freezes. Background shells and waiters are reaped.
- **Root cause:** Many agents each start a full test suite.
- **Fix:** Use a slot limiter (a few heavy jobs at once), a per-job memory cap, and write results to disk so a reaped waiter loses nothing. The memory-capped runner in `tools/memcap/README.md` does the cap.
- **Verifying test:** Several agents queue through the limiter and the machine stays responsive.
- **Spot it fast:** Watch committed memory and CPU while the jobs run.

### 59. MCP connection gotchas

- **Symptom:** `Not Acceptable`, `Bad Request: Missing session ID`, an empty tool list, or authentication that never completes.
- **Root cause:** Authentication lives on a different host from the MCP endpoint. A protocol-version header is required after initialisation. The Accept header must list both JSON and event-stream types. A licence or scope gate returns an empty list instead of an error. Tool descriptions can change after approval.
- **Fix:** Follow the server's discovery documents for authentication. Send the required headers. Treat an empty list as "check licence and scope". Pin and review tool descriptions when they change.
- **Verifying test:** A scripted handshake (initialise, then list the tools with the session and protocol headers) returns the expected tools.
- **Spot it fast:** Run the handshake by hand and read the status of each step.

### 60. Hand edits to a reconciled config are overwritten

- **Symptom:** A change to a settings file disappears minutes later.
- **Root cause:** The file is generated from a source of truth, by a reconciler, a generator or a vendor tool.
- **Fix:** Edit the source of truth and run the generator. Mark generated files with a header.
- **Verifying test:** The change survives the next reconcile run.
- **Spot it fast:** Look for a header, a scheduled task or a healer that owns the file.

### 61. A model change is rejected by the API

- **Symptom:** After the model id changes to Haiku 5.5, every call fails with `invalid_request_error`, with messages such as "`temperature` is deprecated for this model" or "the conversation must end with a user message". A fix made for one model breaks a sibling model that still takes the old parameters.
- **Root cause:** Haiku 5.5 accepts `temperature` only as one and `top_p` only as zero point nine nine (its default), rejects the two together, and rejects any `top_k`. A thinking `budget_tokens` setting is rejected, and so is a request that ends on an assistant turn (a prefill), even with thinking off. On the API, turning thinking off with `thinking: {type: "disabled"}` works on Haiku 5.5 only at effort high or below. Sonnet 5.5 rejects `disabled` at every effort level (and rejects the thinking budget too), while Sonnet 5 accepts `disabled`; on Sonnet 5.5 the off switch is `thinking: {type: "between_tools"}`, accepted at effort high or below only. Above that level both models fail with "effort is not supported when thinking is disabled". A prefix test such as `startswith("claude-sonnet-5")` also matches `claude-sonnet-5-5`, so a rule written for one model silently covers its successor.
- **Fix:** Read the vendor's migration guide before you change the id. To turn up-front thinking off on Sonnet 5.5, send `thinking: {type: "between_tools"}` at effort high or below; on Haiku 5.5 send `disabled` only at effort high or below, and at higher effort leave thinking adaptive and lower the effort instead. Drop sampling values outside the allowed ones, thinking budgets and prefill; steer the format with the prompt or structured output, and thinking depth with effort. Keep per-model parameters in one table keyed by exact id, never by id prefix.
- **Verifying test:** Build the request for every supported model id and assert that nothing Haiku 5.5 rejects reaches it (no sampling values, no budget, last message from the user), then make one live call per model id.
- **Spot it fast:** `grep -rnE 'temperature|top_p|top_k|budget_tokens|startswith\(.claude-' src/`, and any messages list that ends on an assistant turn.

### 62. A model change returns blank or cut-off text

- **Symptom:** Replies are blank or stop mid-sentence while the status says success. `AttributeError: 'ThinkingBlock' object has no attribute 'text'` in Python, or `TypeError: Cannot read properties of undefined (reading 'text')` in Node. An evaluation with a small output cap scores nothing or errors on every item. A blank answer was cached and now repeats.
- **Root cause:** Thinking is on by default (the adaptive kind), so a reply can open with a thinking block and `content[0].text` fails. Thinking counts against `max_tokens`, so a small cap can end the reply after the thinking and before any text. The thinking text comes back empty unless a summarised display is asked for. A declined request (`stop_reason` `refusal`) and a cut-off (`max_tokens`) both return as ordinary successes, and Haiku 5.5 has no server-side fallback (a list of fallback models is rejected). A reply can also arrive with no content blocks at all (the vendor documents an empty reply with an `end_turn` stop reason), which breaks any read of the first block. Third-party wrapper libraries may hard-code a read of the first block.
- **Fix:** Select text blocks by type and join them, and check that the content list is not empty. Raise `max_tokens` or lower the effort. Treat `refusal`, `max_tokens` and empty text as failures, never cache them, and log `stop_reason` and the block types of every call. Wrap a library's client only after reading its installed source.
- **Verifying test:** Recorded responses (thinking first, `max_tokens` with no text, a refusal) each give a handled failure, never an empty success or a cache write.
- **Spot it fast:** `grep -rnE 'content\[0\]\.text|\.content\[0\]' src/`, and a log query for successful replies with empty text.

### 63. A tool loop with thinking on fails on a later call

- **Symptom:** A tool loop fails with `invalid_request_error` when it sends tool results back, or on the final call at its step cap. With thinking off and JSON output requested, a tool call the task needs can be skipped.
- **Root cause:** Thinking blocks must come back complete and unchanged with the tool results, and a block stays valid only while the system prompt, the tools list and every earlier message are unchanged. Trimming or rebuilding earlier turns, or dropping the tools list to force a final answer, invalidates them. On Haiku 5.5 a forced `tool_choice` makes the reply start with the tool call and skip thinking.
- **Fix:** Keep assistant turns exactly as received and the conversation append-only. To end a loop at its cap, resend the same tools list with `tool_choice` set to none, because `tool_choice` is outside the checked prefix. Keep thinking on where a tool call matters. Where thinking is off and JSON output is requested, the vendor's fixes are to remove the JSON format request from any request that must call a tool, or to force the call with `tool_choice` (the model then writes no text before the call).
- **Verifying test:** A loop that reaches its cap ends with a text reply and no error, and the thinking blocks sent back match what was received byte for byte. The vendor documents the rules above; ending a capped loop with `tool_choice` set to none is our reading of them and was not reproduced here, so run this test before relying on it.
- **Spot it fast:** Diff the failing request body against the previous one: system prompt, tools list, earlier messages.

### 64. A table keyed by model id goes wrong silently after a model change

- **Symptom:** Spend reads zero or the wrong amount after a model change, a spend guard never trips, a capability flag is wrong for the new model, or an old model's history series is lost.
- **Root cause:** An unknown id falls back to a default (zero, or another model's rate). A flat per-model rate cannot express a model that charges more above a prompt-length threshold, as Haiku 5.5 does. Deleting old rows re-prices history. Token caps and estimates were tuned on another tokenizer: Haiku 5.5 counts approximately thirty percent more tokens for the same text than the small model before it, and its minimum cacheable prompt length is much lower.
- **Fix:** Fail on unknown ids. Price each request by its own size, tier and token class (input, output, cache write, cache read). Keep old rows. Recount token caps and cost models with the new model's own counts.
- **Verifying test:** Price a request below and above the threshold for each model; an unknown id raises.
- **Spot it fast:** `grep -rnE 'claude-[a-z]+-[0-9]' src/ config/` lists every table or default keyed by id.

### 65. A search across many clones finds deleted files and misses new ones

- **Symptom:** A rename, an audit or an "every use" list names files that no longer exist and misses files that were added.
- **Root cause:** The search ran over working trees that sit behind their remote, or over clones nobody fetches.
- **Fix:** Fetch first. Search a fresh worktree of the remote default branch, or a shallow clone, and record the commit each list came from.
- **Verifying test:** The same search on a fresh clone gives the same list.
- **Spot it fast:** `git -C <repo> status -sb` says the clone is behind.

### 66. A default changed in code does not change production

- **Symptom:** A model id, limit or flag is changed in code and the tests pass, yet production keeps the old value.
- **Root cause:** The deployment (an environment file, a compose file, a manifest) sets the value explicitly and wins over the code default, while the tests run with it unset.
- **Fix:** Change both in one commit, add a test that parses the deploy file and compares it with the code default, and read the live value after the deploy.
- **Verifying test:** The compare test fails when only one side changes.
- **Spot it fast:** Search the deploy files for the variable, then print what the running process sees.

### 67. The API is at capacity or failed on its side

- **Symptom:** `Repeated ... Overloaded errors`, `is experiencing high load`, `Internal server error. This is a server-side issue`, `Server error mid-response`, or the API types `api_error`, `timeout_error`, `overloaded_error`.
- **Root cause:** Capacity or a fault inside the service, not your prompt, account or quota. Claude Code has already retried before it shows the error.
- **Fix:** Wait and retry once. Switch model with `/model`, since capacity is tracked per model. Check the status page the message names. A proxy error page shows its own title: send that to the network team. For unattended jobs set `CLAUDE_CODE_RETRY_WATCHDOG=1`.
- **Verifying test:** The same prompt succeeds later or on the other model, and the status page shows the incident.
- **Spot it fast:** The message names a status page and says "temporary"; a quota error names a reset time instead.

### 68. A plan usage window or spend limit ran out

- **Symptom:** `You've hit your session limit - resets ...`, weekly, model-specific, monthly spend, individual or team budget messages.
- **Root cause:** The plan's rolling allowance or a usage-credit cap is used up. Higher effort, long sessions and auto-compaction use it faster.
- **Fix:** Not a bug. Stop launching work, note the reset time, switch to a smaller model or lower effort, or ask the budget owner the message names. Never retry in a loop.
- **Verifying test:** After the reset, one short prompt succeeds and the usage page shows allowance left.
- **Spot it fast:** The message contains "You've hit your" and a reset time or an owner to ask.

### 69. A credential in the environment overrides or breaks the sign-in

- **Symptom:** `Credit balance is too low` on a subscription, `Invalid API key - Fix external API key`, `Your apiKeyHelper script is failing`, `Invalid auth token - Fix external auth token`, `organization has disabled API key authentication`, or `billing_error`.
- **Root cause:** An `ANTHROPIC_API_KEY` or helper in the user or machine environment takes precedence over the login, or the value carries an invisible character from a chat or document paste, or the helper prints more than the key.
- **Fix:** Run `/status` and read the key row. List `Get-ChildItem Env:ANTHROPIC*` and check the user and machine variables. Remove the stray key or re-enter it from a secrets manager. A helper must print only the key on one line.
- **Verifying test:** `/status` shows the intended credential and one prompt succeeds.
- **Spot it fast:** The message says "external", "helper" or names an environment variable.

### 70. The saved sign-in expired or was revoked

- **Symptom:** `Not logged in - Please run /login`, `Login expired`, `OAuth token revoked`, `OAuth token has expired`, `Invalid authentication credentials`, `Could not resolve authentication method`, or `authentication_error`.
- **Root cause:** The refresh failed, an admin removed access, or a long-lived `CLAUDE_CODE_OAUTH_TOKEN` used for headless runs expired. Background and cloud workers start without a credential unless it is set in the environment that launches them.
- **Fix:** Run `/login`. Check the clock. For headless runs mint a long-lived token with `claude setup-token` and keep it in a secrets manager. Put credentials and proxy variables in the settings `env` block so background agents get them. If `/status` shows an API key, `/login` will not replace it.
- **Verifying test:** A fresh headless `claude -p` call succeeds after a restart.
- **Spot it fast:** The message says `/login`; `/status` names the credential in use.

### 71. The organization refuses this account or sign-in method

- **Symptom:** `disabled Claude subscription access`, `Claude Code access has not been granted for this account`, `This organization has been disabled`, `Your account is on hold`, `Gateway refused the request`, `Request not allowed`, `permission_error`.
- **Root cause:** A server-side organization, role or gateway decision. Local settings, variables and flags cannot override it.
- **Fix:** Stop signing in again. Send the exact line to the administrator with the matching ask from `docs/admin-asks.md`. Where the org allows it, use the other sign-in method. Then check the proxy, which can also produce a refusal.
- **Verifying test:** After the admin change, a fresh sign-in succeeds with no local change.
- **Spot it fast:** The message names the organization, a role, a gateway or an administrator.

### 72. Claude Code cannot reach the API through the corporate network

- **Symptom:** `Unable to connect to API`, `Connection refused - a firewall or proxy`, `Can't reach the API server`, `No internet route`, `Couldn't connect through your proxy (ERR_PROXY_TUNNEL)`, `Connection dropped (ECONNRESET)`, `Unable to connect to Anthropic services`, `proxy refused the connection`.
- **Root cause:** No route, a VPN that blocks the API host, an unset or wrong proxy, a proxy that wants NTLM or Kerberos, a SOCKS proxy, a missing allow-list entry, or a leftover base URL pointing at a dead local gateway.
- **Fix:** From the same shell run `curl.exe -I https://api.anthropic.com`. Set `HTTPS_PROXY` (in the settings `env` block for background agents). Ask IT to allow the hosts in the network-access list. For NTLM or Kerberos use a local authenticating proxy or the corporate gateway. Unset a stale `ANTHROPIC_BASE_URL`.
- **Verifying test:** `curl.exe` through the proxy and one `claude -p` call both succeed.
- **Spot it fast:** The message keeps the network code in parentheses: refused, not found, unreachable, tunnel.

### 73. A proxy or gateway rewrites, buffers or cuts the model stream

- **Symptom:** `API returned an empty or malformed response`, `Streaming response ended before any complete data was received`, `Extra inputs are not permitted ... context_management`, `Socket is closed`, `No response from API`, `Request timed out`.
- **Root cause:** Something between Claude Code and the API answers in its place (a sign-in or block page), buffers streaming responses until they complete, drops long-lived tunnels, or strips the `anthropic-beta` header.
- **Fix:** Read the `Response:` clause and send the server name and headers to the network team. Ask for streaming pass-through and header forwarding. Meanwhile raise `API_TIMEOUT_MS` or `CLAUDE_STREAM_FIRST_BYTE_TIMEOUT_MS`, set `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`, and update Claude Code.
- **Verifying test:** A long turn completes and the response carries a request id.
- **Spot it fast:** A success status with an HTML or empty body, or a cut that happens at about the same elapsed time every turn.

### 74. The conversation no longer fits the context window

- **Symptom:** `Prompt is too long`, `Context limit reached - /compact or /clear to continue`, `Input is too long for requested model`, `Autocompact is thrashing`, `Agent descriptions are over the ... limit`.
- **Root cause:** History, attachments and everything loaded at startup (tools, memory files, agent descriptions) exceed the window. A subagent started as a fork inherits the whole parent context.
- **Fix:** `/compact` with a focus, or `/clear`. Run `/context` and cut the largest row: disable idle MCP servers, trim memory files, shorten agent descriptions. Read big files in ranges. Start subagents with a named type, not as a fork.
- **Verifying test:** `/context` shows free space and the same task completes.
- **Spot it fast:** `/context`: if `Messages` is not the largest row, startup load is the cause.

### 75. The request body is over the API byte limit

- **Symptom:** `Request too large (max ...)`, `Image was too large`, `image dimensions exceed max allowed size`, `request_too_large`.
- **Root cause:** Raw bytes (images, documents, pasted logs) exceed the request limit, which is separate from the token window.
- **Fix:** `/compact`, or press Esc twice and step back past the attachment. Resize images and take tighter screenshots. Pass large files by path and read them in ranges.
- **Verifying test:** The same request without the attachment succeeds.
- **Spot it fast:** The message counts megabytes, not tokens.

### 76. The selected model is unknown, not on the plan or blocked by policy

- **Symptom:** `There's an issue with the selected model`, `is not a recognized model id`, `Model '...' not found`, `is restricted by your organization's settings`, `managed settings block the default model`, `is not available with the Claude ... plan`, `not_found_error`, `model_not_found`.
- **Root cause:** A display name used as an id, a stale id in env, settings or agent frontmatter, a model the provider or plan does not offer, or an organization allow or deny list.
- **Fix:** Run `/model` and pick from the list. Prefer aliases. Search `ANTHROPIC_MODEL`, the `model` setting and agent frontmatter for stale ids. Your own settings cannot widen a managed list: ask the admin.
- **Verifying test:** A fresh session starts on the intended model with no substitution notice.
- **Spot it fast:** The notice names the substituted model, or the hint says "Did you mean".

### 77. Claude Code is older than the model or policy requires

- **Symptom:** `does not support this model; version ... or newer is required`, or `older than the minimum version required by your organization's policy`.
- **Root cause:** The binary that made the request is below a per-model or organization minimum. A second, older install earlier on PATH is common.
- **Fix:** `claude update`, then start a new session. Run `where.exe claude` and remove or reorder extra installs. On managed laptops ask for the update channel to be opened.
- **Verifying test:** `claude --version` meets the minimum and the model answers.
- **Spot it fast:** `where.exe claude` prints more than one path.

### 78. Tool-use history is out of step

- **Symptom:** `due to tool use concurrency issues`, `orphaned tool_result`, `duplicate tool_use ID`, `unexpected tool_use_id found in tool_result blocks`, `thinking blocks ... cannot be modified`.
- **Root cause:** The saved sequence of tool calls, results and thinking blocks no longer matches what the API expects, often after an interrupted parallel tool turn.
- **Fix:** Update Claude Code first, then `/rewind` (or Esc twice) to a checkpoint before the broken turn.
- **Verifying test:** The next turn after the rewind succeeds and the error does not return on resume.
- **Spot it fast:** The message itself says `Run /rewind`.

### 79. An MCP server fails to start or drops

- **Symptom:** `Failed to connect` in `claude mcp list`, `MCP server "..." disconnected`, `No such tool available`, or an invalid `input_schema` error.
- **Root cause:** The server's launch command fails: a relative path (it breaks when Claude Code starts from another folder), a command that is not on the PATH Claude Code sees, a missing environment variable, a start that takes longer than the startup timeout, or a package that changed because it was not pinned.
- **Fix:** Read the `Issue:` line from `claude mcp get <name>`. Run the server command by hand and read stderr. Use absolute paths for local scripts, pin versions, set the server's variables in its config, raise `MCP_TIMEOUT` for a slow start, and allow the package registry. Then `/mcp reconnect all`.
- **Verifying test:** `claude mcp list` shows the server connected in a new session.
- **Spot it fast:** The server's command fails the same way when run in a plain shell.

### 80. An MCP server needs its sign-in again

- **Symptom:** `needs you to sign in again`, `requires re-authorization (token expired)`, `needs additional permissions (scope: ...)`, `rejected the credential from its headersHelper`, `Issuer mismatch`, `Incompatible auth server: does not support dynamic client registration`.
- **Root cause:** The server's sign-in expired, lacks a scope, or the helper returns a credential it rejects. Some servers do not support automatic client registration and need credentials registered in advance.
- **Fix:** `/mcp`, choose the server, sign in again. Fix the helper so it prints an accepted credential. For a server without automatic registration, register an app in its developer portal and pass the client ID to `claude mcp add`.
- **Verifying test:** One tool call on that server succeeds.
- **Spot it fast:** `/mcp` marks the server as needing authentication.

### 81. A managed settings document cannot be read

- **Symptom:** `Managed settings document could not be parsed as a JSON object`, `Remote managed settings failed to load`, `Unable to read managed policy settings`, `drop-in directory could not be read`.
- **Root cause:** The organization's policy file, registry value or server copy is broken or unreachable. Some forms stop Claude Code at startup.
- **Fix:** This file belongs to IT. Send the full line, which names the source (file path or registry key), with the matching ask from `docs/admin-asks.md`. For a network cause, check that the API host is reachable.
- **Verifying test:** Claude Code starts and `/status` lists the managed source.
- **Spot it fast:** The line starts with the policy source path.

### 82. A hook fails and the action goes ahead anyway

- **Symptom:** `<hook name> hook error` with `Failed with non-blocking status code: ...`.
- **Root cause:** The hook's path or interpreter is wrong, it printed invalid JSON, or it exited with a code other than two. Only exit two blocks by code alone, so a policy hook can be silently off.
- **Fix:** Run the hook command by hand with a sample event. Use the full interpreter path. Enforce with exit two or a JSON decision. Watch the first run of every new policy hook.
- **Verifying test:** The kit's guard test is blocked and `claude --debug` shows the hook's exit code.
- **Spot it fast:** `claude --debug`, trigger the tool, read the hook line in the debug log.

### 83. No usable shell on Windows

- **Symptom:** `requires either Git for Windows (for bash) or PowerShell`, `but Git Bash was not found`, `Denying Bash also turns off the PowerShell tool`.
- **Root cause:** Neither shell is found where Claude Code looks, or a bare Bash deny rule also removes the PowerShell tool.
- **Fix:** Put the Windows PowerShell folder on PATH, or set `CLAUDE_CODE_GIT_BASH_PATH` to `bash.exe`. Set `CLAUDE_CODE_USE_POWERSHELL_TOOL=1` when Bash is denied. Use scoped deny rules instead of a bare `Bash`.
- **Verifying test:** A new session runs a harmless command in the intended shell.
- **Spot it fast:** `where.exe bash` and `where.exe powershell` from the same environment.

### 84. The installer runs in the wrong shell or is blocked by script policy

- **Symptom:** `The token '&&' is not a valid statement separator`, `A parameter cannot be found that matches parameter name 'fsSL'`, `'irm' is not recognized`, `running scripts is disabled on this system`, or a refusal to run on thirty-two-bit Windows.
- **Root cause:** A command for another shell, the x86 PowerShell entry, or an execution policy that blocks npm's script shims.
- **Fix:** Use the installer line for the shell you are in. Open the standard PowerShell entry. Prefer the native installer over npm, or call the `.cmd` shim. Changing execution policy on a managed laptop is an admin decision.
- **Verifying test:** `claude --version` prints a version in a new window.
- **Spot it fast:** The error names a PowerShell token or the execution policy help page.

### 85. The installer download returns a web page

- **Symptom:** `syntax error near unexpected token '<'` with `<!DOCTYPE html>`, PowerShell parse errors quoting HTML, `App unavailable in region`, `Failed to fetch version`, `The connection dropped while downloading the update`.
- **Root cause:** The install host returned a page instead of a script: a regional block, a proxy block page or a proxy that cuts large downloads.
- **Fix:** Open the install URL in a browser and read the page. If it is the proxy's page, ask IT to allow the install and download hosts, including large downloads. Do not run the saved page.
- **Verifying test:** The script text downloads and the install finishes.
- **Spot it fast:** The first line of the failure quotes an HTML tag.

### 86. Endpoint security software intercepts Claude Code's own files

- **Symptom:** `Windows reported an error (EBADF)` on resume, `Transcript writes are failing`, intermittent failures to read or write session files.
- **Root cause:** Security, encryption or endpoint-management tools intercept reads and writes in the Claude Code profile folder.
- **Fix:** Ask IT to exclude `%USERPROFILE%\.claude\projects` (or the folder `CLAUDE_CONFIG_DIR` names), or to allow-list Claude Code. Keep the profile out of synced folders.
- **Verifying test:** Resume of the same session works several times in a row.
- **Spot it fast:** The failure comes and goes with no change on your side.

### 87. A network share is refused as a working directory

- **Symptom:** `is a network path, which cannot be added as a working directory`, `path is network-shaped`, `that file is on a network share`.
- **Root cause:** Looking up a UNC path can send your credentials to its host, so Claude Code refuses it.
- **Fix:** Work on a local clone. If you must, map the share to a drive letter and pass it at launch with `--add-dir`.
- **Verifying test:** The directory appears in the session's working directories at startup.
- **Spot it fast:** The path starts with two backslashes.

### 88. The temp filesystem or disk quota is full

- **Symptom:** `Your disk quota is full on the filesystem with Claude Code's temp directory`, `is full (ENOSPC)`, `Command output was lost`.
- **Root cause:** The volume or your quota under the temp directory is full. Output was lost, not truncated.
- **Fix:** Free space, or start Claude Code with `CLAUDE_CODE_TMPDIR` on a local folder with room and outside synced folders. Re-run the command.
- **Verifying test:** The same command returns its output.
- **Spot it fast:** A command that exits non-zero with no output at all.

### 89. Project settings are ignored until the workspace is trusted

- **Symptom:** `Ignoring ... permissions.allow entries ... this workspace has not been trusted`, `headersHelper not run - this workspace has no persisted trust`.
- **Root cause:** Allow rules and helpers from project settings apply only after the trust dialog is accepted for that folder.
- **Fix:** Run `claude` interactively in the folder once and accept the dialog. Do not trust a home directory for project work.
- **Verifying test:** The warning is gone and an allowed command runs without a prompt.
- **Spot it fast:** Permission prompts appear for commands the project allows.

### 90. A permission rule is malformed or names the wrong tool

- **Symptom:** `Malformed Tool(content) rule`, `is not matched by file permission checks - only Edit(path) rules are`, `has a wildcard before the rest of the command`.
- **Root cause:** The rule has text after the closing parenthesis, or a path rule names `Write`, `MultiEdit` or `Glob`, which file checks never read.
- **Fix:** Rewrite path rules as `Edit(path)` or `Read(path)` and end each rule at its closing parenthesis.
- **Verifying test:** `claude doctor` lists no invalid rule and a deny rule blocks its target.
- **Spot it fast:** `claude doctor` invalid-settings section.

### 91. WebFetch cannot reach intranet hosts or its safety check is blocked

- **Symptom:** `WebFetch cannot fetch localhost or other hostnames without a dot`, `Unable to verify if domain ... is safe to fetch`, `The safety check for domain ... is rate-limited`.
- **Root cause:** Bare host names are refused before any request. Each new domain is checked through the API host, which a firewall can block or a shared quota can exhaust.
- **Fix:** Use `curl.exe` through the shell tool for local and intranet pages. Ask IT to allow the API host, or the admin to set `skipWebFetchPreflight`. On a rate limit continue without the page and retry once later.
- **Verifying test:** A public page fetches, and the intranet page returns through `curl.exe`.
- **Spot it fast:** The URL has no dot, or every new domain fails the same way.

### 92. A safety check declines the conversation

- **Symptom:** `can't help with this. Start a new session to continue`, `appears to violate our Usage Policy`, `safeguards flagged this message`, `Output blocked by content filtering policy`.
- **Root cause:** A policy check over the whole conversation, or the output filter. Resuming keeps the triggering content.
- **Fix:** Start a new session, or `/rewind` before the triggering turn and rephrase. For defensive security work state the context. Quote the request id if you think it is wrong.
- **Verifying test:** The new session proceeds with the rephrased request.
- **Spot it fast:** The same refusal returns after `--resume`.

### 93. Browser sign-in cannot open its local callback port

- **Symptom:** `Failed to start OAuth callback server`, `OAuth callback port ... is already in use`, `No available ports for OAuth redirect`, `OAuth error: Invalid code`.
- **Root cause:** Sign-in needs a loopback listener; endpoint firewalls or another process can block it. A code expires or gets truncated when copied.
- **Fix:** Close the process holding the port. Use the paste-code flow, or run `claude setup-token` where sign-in works and keep the token in a secrets manager. Copy the full code quickly.
- **Verifying test:** `/login` completes and `/status` shows the account.
- **Spot it fast:** `netstat -ano | findstr LISTENING` shows the port taken.

### 94. A helper program exists only as a shell script, so Windows cannot start it

- **Symptom:** A tool reports a helper as not installed (for example `pdftoppm is not installed`) while it runs fine in Git Bash.
- **Root cause:** An extensionless shell shim on PATH works in Git Bash but Windows process creation cannot start it.
- **Fix:** Install the native Windows build and put its folder on the user PATH, or ship a `.cmd` twin next to each shim.
- **Verifying test:** `where.exe <tool>` prints an `.exe` or `.cmd` and the original tool call succeeds.
- **Spot it fast:** `where.exe <tool>` prints nothing while `which <tool>` in Git Bash finds it.

### 95. A recursive delete through a Windows junction empties the folder it points to

- **Symptom:** After a worktree or folder was deleted with `rm -rf`, `git worktree remove --force` or a similar recursive delete, files are missing from the main checkout or from a shared folder that was never part of what you deleted, and `git status` in the main repository shows deletions nobody made. The error that invites `--force` is `contains modified or untracked files, use --force to delete it`.
- **Root cause:** A worktree folder can hold a Windows junction or symlink to a shared folder, for example a dependency, data or cache folder linked in to save space. `rm -rf <link>/` with a trailing slash, and some older tools, walk through the link and empty the folder it points to instead of removing only the link. A repeat test with a current `git worktree remove --force` and with PowerShell `Remove-Item -Recurse` did not follow the link, but a field report says a forced removal did, so do not rely on the tool.
- **Fix:** Before deleting a worktree or any folder that may hold links, list them and remove each one without following it: `dir /AL /S` in `cmd` lists junctions and symlinks, and `rmdir <link>` removes only the link. Never `rm -rf <link>/`. Only then run `git worktree remove` (add `--force` after the links are gone), then `git worktree prune`.
- **Verifying test:** In a scratch repository, link a folder holding a marker file into a worktree with `mklink /J`, run the steps above, and check that the marker file is still in the target.
- **Spot it fast:** `dir /AL /S <worktree>` prints `<JUNCTION>` or `<SYMLINKD>` entries, and `git -C <main> status` shows deleted files right after a removal.

### 96. A container restart keeps the environment it was created with

- **Symptom:** You changed an environment variable, an env file or a compose environment entry and restarted the container, and the application still behaves as before. `docker exec <name> printenv NAME` shows the old value. Compose may warn `The "NAME" variable is not set. Defaulting to a blank string.`
- **Root cause:** A container's environment is fixed when the container is created. `docker restart` and `docker compose restart` start the same container again with its stored environment and never re-read the env file or the compose file.
- **Fix:** Recreate the container: `docker compose up -d --force-recreate <service>`, or `docker rm -f <name>` and start it again. A value baked into the image needs a rebuild instead. If compose warns that a variable is not set, the env file it read is not the one you edited: keep it next to the compose file or pass it with `--env-file`. If a failed `up` or `pull` ends with `port is already allocated` or a certificate error (`x509`), that is the real error (another process holds the port, or a proxy certificate is not trusted) and the variable warning above it is only a hint.
- **Verifying test:** After the change, `docker exec <name> printenv NAME` prints the new value and `docker inspect` shows a new creation time for the container.
- **Spot it fast:** Compare `docker exec <name> printenv NAME` with the file you edited.

### 97. A bulk search-and-replace rewrites binary files

- **Symptom:** After a folder-wide regex replace, a database, image, archive or office file no longer opens: `file is not a database`, `database disk image is malformed`, a corrupt-archive message. `git status` lists binary files as modified that no text edit should touch.
- **Root cause:** The replace opened every file as text. Decoding and re-encoding a binary file, or replacing a byte pattern inside it, changes bytes that were never text, and the file is damaged without any error. Backup and copy folders are hit too. The same message appears when a git-lfs pointer, a small text file, sits where the database should be because the real file was never pulled.
- **Fix:** Restore the binary files from version control or a backup first (if the file opens as a few lines of text that start with the word `version` and name git-lfs, it is an unpulled pointer: `git lfs pull` fetches the real file). Then limit the replace to text files: take the list from `git ls-files` filtered by an extension allow-list, or skip any file with a NUL byte in its first few kilobytes, and leave out backup, vendor and data folders. Run it once as a dry run that prints the file list, and read the list before it writes.
- **Verifying test:** Run the replace on a scratch copy that holds a small SQLite file and compare checksums of the binary files before and after: they are identical.
- **Spot it fast:** `git diff --numstat` prints `-` for both counts on every changed binary file.
