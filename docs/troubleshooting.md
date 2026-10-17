# Troubleshooting

Find your symptom, apply the first move, and open the numbered card in the bug playbook (`<KB>/_shared/bug-cards.md`,
seeded from `kb-template/_shared/bug-cards.md`) for the root cause, the fix and a test that proves it. Every branch
ends the same way: if it is still broken, run the doctor and give its report (or its redacted bundle) to whoever helps
you.

## First three moves
1. Copy the exact error line. "It fails" is not a symptom.
2. Search the cards: `py -3 <KIT>/plugins/workbench-kb/scripts/kb_search.py "<error words>" --domain _shared --limit 5`.
   When a tool call fails with an error the playbook knows, a hook already prints a one-line hint naming the card.
3. For Claude Code's own behaviour, start it with `claude --debug`: the log goes to `<CH>/debug/<session-id>.txt`, or
   to the path you give `--debug-file`. `/status` shows the settings sources, proxy and certificates it loaded.

## Install, setup and the kit
| Symptom | First move | Card |
|---|---|---|
| Installer or setup stops with exit 3 and a policy message | Stop. Quote the message and send the matching ask from `docs/admin-asks.md`; never retry another way | 51 |
| Setup exit 5, phase `reboot-wait` | Save your work, restart, sign in; setup resumes (guide `docs/howto/05-wsl-setup-and-resume.md`) | - |
| `/hooks` does not list the workbench hooks | Hooks are not running: check `/hooks`, the plugin's Python path, and whether policy allows only managed hooks | 10 |
| "Managed policy changed since setup" at session start | Read the change class and the matching ask in `docs/admin-asks.md` section 1 | - |
| `Hook failed to run` with `Plugin option "python" isn't set`, on every tool call | The plugin has no interpreter, so none of its hooks run. Find the path with `py -3 -c "import sys; print(sys.executable)"`, run `claude plugin install workbench-core@workbench --config python=<absolute python path>` and the same for `workbench-kb@workbench`, then close every Claude Code window and start a new one | - |
| You want the failed tool calls listed, or a failure kept to fix later | Each failed call is logged, with credential-shaped values removed, in `<WB>/state/issues.jsonl`: `py -3 <KIT>/plugins/workbench-core/scripts/issues.py show [--since YYYY-MM-DD]` prints a numbered table. An empty log after failures means the failure hook is not running: see the row above | - |
| Doctor row `hooks heartbeat` is WARN | No Claude Code session has started since the install, or the hook interpreter moved or the plugin is disabled: start a session, and if the row stays WARN re-run the installer and check `/hooks` | 10 |
| A hook or script that calls `python3` hangs or says `Permission denied` | The Microsoft Store stub: use `py -3` or the full interpreter path | 46 |
| `ModuleNotFoundError` for a package you installed | The wrong interpreter: use the knowledge environment's Python from `<WB>/config.json` | 13 |
| `find` returns nothing for a file you know | Run `find`'s status: the file may be cloud-only, labelled, too large or not indexed yet (guide `docs/howto/29-keep-the-index-fresh.md`) | - |
| Capture stops with exit 3 | Read the run report in `<WB>/capture/runs/`: a sign-in, consent or policy page stopped it, by design | - |
| "Model not allowed" | The row falls back down its chain; `py -3 <KIT>/bootstrap/setup.py routing` rebuilds routing after a policy change | - |
| A change you made by hand to a settings file disappears | A reconciler (the MCP healer or your IT tooling) owns it: change the source it reads | 60 |
| `doctor --deep` exits 2 | Read the rows marked FAIL: a doctor row, or `knowledge: <name>`, whose detail names the check (guide `docs/howto/13-run-the-doctor-and-backups.md`). A WARN never makes it exit nonzero | - |
| `knowledge: kb-machinery` is FAIL | The knowledge base's own unit tests failed on this machine; the detail names them. To see why, run the whole suite: `py -3 -m unittest discover -s <KIT>/plugins/workbench-kb/tests`. `timed out` means the run was too slow, not that a test failed: on a laptop with heavy endpoint scanning every process start is slow. The row runs only the short list in `field-tests.txt` for that reason | - |
| `knowledge: kb-retrieval`, `kb-graph` or `find-keyword` is FAIL | Search, the link graph or the how-to questions fell below the bar fixed in advance: run it again once, then give the row's detail and `doctor --bundle` to whoever supports the kit | - |
| `knowledge: hooks` or `kit-tools` is FAIL | A hook script misbehaved in its sandbox, or a kit tool failed its own `--self-test`: send the row's detail with the bundle | - |
| `knowledge: record` or `kb-state` is FAIL | The state folder is not writable or not where the code expects: check the placement rows, and that `<WB>/kb-state/` and `<WB>/state/` are outside OneDrive and writable | - |
| A `knowledge:` row is WARN with an ask-IT text, or timed out | WARN, not failure: send the text (guide `docs/howto/03-ask-it-for-access.md`), or run `doctor --deep` again after a timeout | - |
| Doctor row `updates` is WARN | A tool is deferred or failed to update: guide `docs/howto/44-update-the-tools.md` | - |
| Doctor row `claude startup warnings` is WARN | It prints what `claude doctor` reported, with the card that matches: open that card, or the next section | - |

Still broken: `py -3 <KIT>/bootstrap/setup.py doctor` (exit 0 ok, 1 warnings, 2 errors; with `--deep` only a FAIL row exits 2).

## Proxy, certificates and network
| Symptom | First move | Card |
|---|---|---|
| `self-signed certificate in certificate chain` or `unable to get local issuer certificate` in Node, Python, pip, git or curl, while the browser works | The proxy's root certificate must be trusted per runtime (guide `docs/howto/04-proxies-and-tls-inspection.md`); never turn verification off | 18 |
| `unable to verify the first certificate` while the browser loads the page | The server omits its intermediate certificate | 17 |
| Inside WSL `Temporary failure in name resolution` while connected to the VPN | WSL DNS under VPN | 49 |
| HTTP 407 or "proxy authentication required" | The proxy wants NTLM or Kerberos: see `docs/known-limits.md` | - |
| The same host fails the same way every session | Stop retrying it; note it as unreachable | 4 |
| A job stalls at low CPU and dies at the timeout | A network call without a timeout | 40 |
| Bursts of `Failed to fetch` while the server looks healthy | Cross-origin calls failing together | 16 |
| `Rate limit exceeded`, or every later call in a fan-out fails the same way | Stop launching; wait and retry fewer at a time | 19 |

Still broken: `py -3 <KIT>/bootstrap/setup.py doctor`.

## Windows, OneDrive and the shell
| Symptom | First move | Card |
|---|---|---|
| `The process cannot access the file because it is being used by another process`, `Unable to create '.git/index.lock'` | OneDrive holds the file: keep repos, environments and databases outside synced folders | 48 |
| `Filename too long`, or `FileNotFoundError` for a file that exists | Windows path length | 44 |
| `UnicodeEncodeError: 'charmap' codec can't encode character` | The console code page: set `PYTHONUTF8=1` | 3 |
| `The string is missing the terminator`, or JSON reaching a command without its quotes | PowerShell and Git Bash quote differently | 8 |
| `unexpected EOF while looking for matching quote` over ssh or `python -c` | Nested quotes: send a heredoc | 6 |
| `gh api /repos/...` hits a file path, or `ambiguous argument` with a `;` | Git Bash rewrote a path-like argument | 7 |
| `$'\r': command not found` or `bad interpreter` on Linux | Line endings | 11 |
| `command not found` | The tool is missing or not on `Path` yet: open a new shell, or run setup's verify | 12 |
| `The command line is too long` | Write the content to a file and pass the file | 31 |
| A subprocess hangs on Windows but not on Linux | A full pipe buffer | 43 |
| A loop keeps spawning after you killed it | Kill the whole tree (`taskkill /T`) | 42 |
| A script fed on stdin stops after an inner command | Another command consumed stdin | 41 |
| A scheduled task flashes a console, or never runs after sleep | Task Scheduler settings | 45 |
| A long headless run or an SSH session dies when the lid closes or the laptop idles | Modern standby quiesced the network in sleep: plug in and lengthen the sleep timer on mains power, or run the job where nothing sleeps (digest `kb-template/_shared/digests/windows-shell.md`) | - |
| A burst of black console windows when Claude Code starts | Each stdio server launched through a `cmd /c` wrapper can open one: start them through `tools/mcp-nowin` (digest `kb-template/_shared/digests/mcp.md`) | - |
| A blanked environment variable still has its old value | On Windows an empty value means unset | 56 |
| The desktop freezes during tests or model jobs | Too many heavy jobs at once: one at a time, memory-capped | 58 |
| Two SSH clients behave differently, or `Permission denied (publickey)` in one shell only | Two ssh programs on one machine | 52 |

Still broken: `py -3 <KIT>/bootstrap/setup.py doctor`.

## Claude Code sessions
| Symptom | First move | Card |
|---|---|---|
| A command prompts although each part is allowed | Compound or inline commands are matched as a whole | 32 |
| `File content (...) exceeds maximum allowed tokens` | Read a range, or search first | 28 |
| `File does not exist`, sometimes with "did you mean" | An invented path: list the folder first | 29 |
| `File has been modified since read` | Read the file again, then edit | 30 |
| An edited hook or a new agent has no effect | Hooks and agents are loaded per session: start a new one | 26 |
| A session-start or prompt hook's text is missing under load | The hook timed out silently | 27 |
| Foreground sleeps are blocked, long waits time out | Wait on a condition in the background instead | 33 |
| `Output does not match required schema` again and again | The payload is nested one level too deep | 34 |
| An action was denied and Claude tried another route | That is the failure: stop, quote the denial, ask | 51 |
| An MCP server says `Not Acceptable` or `Missing session ID`, or lists no tools | Transport or session handling | 59 |
| An MCP server or CLI that worked yesterday fails today | An unpinned `npx` or `uvx` fetched a new version: pin it | 50 |

Still broken: `py -3 <KIT>/bootstrap/setup.py doctor`.

## Claude Code's own error messages
Errors that end a turn (API, usage limit, sign-in, network) and warnings printed at startup reach no failure hook, so search
by hand with the words Claude Code printed, or start from this table (guide `docs/howto/43-fix-a-red-error-in-claude-code.md`).
| Symptom | First move | Card |
|---|---|---|
| `Repeated ... Overloaded errors`, `Internal server error`, `Server error mid-response` | Wait, retry once, try `/model`, read the status page it names | 67 |
| `You've hit your ... limit - resets ...` | Not a bug: wait for the reset or ask the budget owner the message names | 68 |
| `Credit balance is too low`, `Invalid API key - Fix external API key`, an `apiKeyHelper` that fails | `/status`, then `Get-ChildItem Env:ANTHROPIC*` for a stray key | 69 |
| `Not logged in`, `Login expired`, `OAuth token revoked` | `/login`; a headless run uses `claude setup-token` | 70 |
| `disabled Claude subscription access`, `Request not allowed`, `Gateway refused the request` | Send the exact line to your admin (`docs/admin-asks.md`) and stop signing in again | 71 |
| `Unable to connect to API`, `ERR_PROXY_TUNNEL`, `Connection dropped (ECONNRESET)` | `curl.exe -I https://api.anthropic.com` in the same shell, then guide `docs/howto/04-proxies-and-tls-inspection.md` | 72 |
| `API returned an empty or malformed response`, `Socket is closed` | A proxy or gateway answers or buffers the stream: send the `Response:` clause to the network team | 73 |
| `Prompt is too long`, `Context limit reached`, `Autocompact is thrashing` | `/context`, then `/compact` | 74 |
| `Request too large`, `Image was too large` | `/compact`, fewer or smaller attachments | 75 |
| `There's an issue with the selected model`, `is not a recognized model id` | `/model` and pick from the list | 76 |
| `does not support this model; version ... is required` | `claude update`, then a new session | 77 |
| `due to tool use concurrency issues`, `orphaned tool_result` | `claude update`, then `/rewind` | 78 |
| MCP `Failed to connect` or `disconnected`; `needs you to sign in again` | `claude mcp get <name>`; `/mcp` | 79, 80 |
| `Managed settings document could not be parsed` | IT owns the file: send the full line | 81 |
| `hook error` with `Failed with non-blocking status code` | Run the hook by hand; a hook blocks with exit 2 | 82 |
| `requires either Git for Windows (for bash) or PowerShell` | `Path`, or `CLAUDE_CODE_GIT_BASH_PATH` | 83 |
| Installer: `running scripts is disabled`, or `<!DOCTYPE html>` | The right shell line; read the page the URL returned | 84, 85 |
| `EBADF` on resume, `Transcript writes are failing` | Ask IT to exclude the profile's projects folder from endpoint scanning | 86 |
| `is a network path` | Work on a local clone, or map the share to a drive letter and pass it with `--add-dir` | 87 |
| The temp folder or disk quota is full | Free space, or point `CLAUDE_CODE_TMPDIR` at a local folder with room, outside synced folders | 88 |
| `workspace has not been trusted`; project settings ignored | Run `claude` interactively in the folder once and accept the dialog | 89 |
| A permission rule is ignored or rejected | Write path rules as `Edit(path)` or `Read(path)` and end each rule at its closing parenthesis | 90 |
| `WebFetch cannot fetch localhost` | Fetch local and intranet pages with `curl.exe` through the shell tool | 91 |
| `can't help with this. Start a new session` | Start a new session, or `/rewind` before that turn and rephrase | 92 |
| `Failed to start OAuth callback server` | Close the process holding the port, or use the paste-code flow | 93 |
| A tool says a helper (for example `pdftoppm`) is not installed, while Git Bash finds it | `where.exe <tool>` prints nothing: install the native Windows build, or ship a `.cmd` twin | 94 |

Still broken: `py -3 <KIT>/bootstrap/setup.py doctor`; its `claude startup warnings` row reads `claude doctor` for you.

## Model changes and API calls
| Symptom | First move | Card |
|---|---|---|
| Every call fails with `invalid_request_error` after a model change (a prefill, `temperature`, `top_p`, a thinking budget) | The new model rejects parameters the old one took: read its migration guide and drop them | 61 |
| Blank or cut-off replies with a success status, or the `ThinkingBlock` error | Thinking comes first and counts against `max_tokens`: select text blocks by type, raise the cap or lower the effort | 62 |
| A tool loop fails on a later call, or on its final call at the cap | Thinking blocks must come back unchanged, with the system prompt, tools and earlier messages unchanged | 63 |
| Spend reads zero or wrong after a model change | The price table has no row for the new id, or one flat rate | 64 |
| `scout` or the `haiku` alias reaches an older small model | Update Claude Code to the recommended version the capability report checks, or pin the provider's id (`docs/known-limits.md`) | - |

Still broken: `py -3 <KIT>/bootstrap/setup.py doctor`.

## Git, CI and secrets
| Symptom | First move | Card |
|---|---|---|
| Another task's files appear after `git stash pop` | The stash is shared by every worktree: use a work-in-progress commit | 22 |
| A commit lands on the wrong branch | Another session switched the shared checkout: use a worktree | 23 |
| `git branch -d` refuses: checked out elsewhere | A forgotten worktree: `git worktree list` | 24 |
| `Permission denied` running `./script.sh` on Linux after a commit from Windows | The executable bit was lost | 25 |
| `ERR_PNPM_OUTDATED_LOCKFILE` or an `npm ci` mismatch | Lockfile drift | 21 |
| A ready pull request starts no CI, or deploys are cancelled in a burst | CI trigger and concurrency rules | 54 |
| A pull request title breaks a workflow step | Untrusted text substituted into a script | 55 |
| A status loop reports the parent repository for a plain folder | git walks up to the nearest repository | 53 |
| A pre-commit scanner blocks hashes or test fixtures | Tune the scanner, never delete the check | 35 |
| A token shows in `ps` output, a clone URL or a log | Secrets leak through arguments: rotate it, then fix the call | 36 |
| Everything passes locally, production is broken | The integration tests were skipped | 38 |
| Tests in a worktree follow the main checkout's code | An editable install points at the other checkout | 47 |
| A cross-repository hit list names deleted files and misses new ones | The clones searched were behind their remote: fetch first, or search a fresh clone | 65 |
| A default changed in code, production unchanged | The deploy sets the value explicitly: change both together and read the live value | 66 |

Still broken: `py -3 <KIT>/bootstrap/setup.py doctor`.

## Scripts and data
| Symptom | First move | Card |
|---|---|---|
| A job reports success for days while doing nothing | An exit code was swallowed by a pipe, `Out-Null` or an or-true fallback | 1 |
| "Nothing to do" while work is waiting | An empty result was read as success | 2 |
| `KeyError`, `'NoneType' object is not subscriptable`, `JSONDecodeError` | Inspect the data before assuming its shape | 5 |
| Entries from one session vanish | Two writers on one file: append, or lock | 9 |
| `'coroutine' object is not iterable`, a Promise logged as text | A missing `await` | 14 |
| A deploy fails with "already exists", or a column is missing | The migration runner is not idempotent | 15 |
| Late-evening records land on the wrong day, or a daily job is called stale too early | Naive UTC dates | 20 |
| Search scores differ between two runs or machines | Results differ between processes | 37 |
| Stored notes end mid-sentence | Silent truncation | 39 |
| The error names a cause that turns out to be wrong | A broad `except` asserted one cause | 57 |

Still broken: `py -3 <KIT>/bootstrap/setup.py doctor`, and for IT `py -3 <KIT>/bootstrap/setup.py doctor --bundle support.zip`
(redacted: no notes, no tokens).
