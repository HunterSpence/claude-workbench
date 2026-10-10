# Known limits

What this release does not do, or does only partly, and why. Read it before you promise a feature to a colleague or
an approver. Fixes for things that should work are in `docs/troubleshooting.md`.

## Capture, meetings and mail
- **Teams and Outlook on the web are not capture sources yet.** Those web apps read their data with POST requests,
  and capture aborts any request that is not a GET. A later release may add a short allowlist of read-only POST
  endpoints per source; that needs a live tenant to design and test.
- **Meeting Recap download is not automated,** for the same reason. Meeting transcripts reach the knowledge layer
  two ways: you click Download in Teams and save the file in the drop folder (`<DATA>/captured/_drop/meetings/`),
  and `ingest` does the rest; or the Graph route, once IT enables it.
- **A transcript you can only view is never extracted.** The organiser's download control and the tenant's
  transcript settings are respected, never worked around.
- **Graph access to transcripts is off by default in most tenants.** The Graph route then stops with an ask-IT text
  (`docs/admin-asks.md`, section 4); it never retries another way.
- **Classic Outlook covers its cached window only** (the period your Outlook keeps offline). New
  Outlook has no object model, so use the Graph route there. A security prompt or a programmatic-access block is a
  hard stop.
- **Mail and meeting ingest is experimental** and runs only after `ingest ack-infosec`.
- **Capture depends on the page layout.** Each source finds elements through a short selector list. When an intranet
  redesign moves them, capture stops with a report instead of guessing; the source needs a selector update.
- **A server redirect to a foreign host costs one GET** before capture notices and stops.
- **Capture needs Edge automation allowed.** If policy disables `RemoteDebuggingAllowed`, capture cannot run; if
  `HeadlessModeEnabled` is off, it runs in a visible window.
- **No recording.** Nothing in the kit records audio, video or the screen of a meeting.

## Platform and network
- **Native Windows has no command sandbox.** Claude Code's sandbox works in WSL2 only, so run unfamiliar code there.
  For the same reason `sandbox.failIfUnavailable` stops Claude Code at startup on native Windows: the vendor's sandbox page
  says the sandbox does not run there, so with that setting Claude Code exits. Leave it out of a profile for Windows
  machines (`settings/SETTINGS.md`).
- **SOCKS proxies are not supported by Claude Code.** A proxy that needs NTLM or Kerberos needs a gateway that speaks
  it; the capability report marks HTTP 407 as `proxy-auth` and re-tests it once with negotiate authentication.
- **GitHub Enterprise Server and MCP:** the hosted GitHub MCP endpoint serves github.com and GHE.com only. On
  Enterprise Server use the `gh` CLI (the `github` skill); the local server there is experimental
  (`mcp/README.md`).
- **Claude Code's own usage telemetry stays on by default.** `DO_NOT_TRACK` and `DISABLE_TELEMETRY` would also turn
  off feature-flag fetching and with it some features, so the profiles leave them unset; setup sets `DO_NOT_TRACK=1`
  only for the tools it runs (`settings/SETTINGS.md` has the list if your policy requires telemetry off).
- **A laptop that sleeps can end a long unattended run.** On modern-standby hardware Windows quiesces the network in sleep
  unless Remote Desktop or a background app needs it, so a headless run or an SSH session can drop when the lid closes or
  the idle timer fires. The kit does not change power settings, and a managed power policy may override yours; the digest
  `kb-template/_shared/digests/windows-shell.md` has the checks.
- **The save lock belongs to one machine.** The lock, flags and snapshots live under the workbench folder, not in the
  knowledge base, so a synced folder never holds a live lock. The same fact means two machines that save into one synced
  knowledge base do not wait for each other: save from one at a time.
- **The deep doctor tests the shipped template, not your notes.** Its retrieval and link-graph checks run on a sandbox copy
  of `kb-template/`; measure your own notes with `kb_health.py --eval` and cases you write.
- **The index can lag by up to a day** without the nightly task: `find` starts a background refresh when the last one
  is older than 24 hours, and its status shows the last refresh.
- **Online-only files are catalogued, not searched.** `find` never downloads them; keep a library on the device to
  search its content.

## Windows quirks setup works around (and you may meet by hand)
- winget configuration has no user or machine scope, so machine packages install one at a time.
- An elevated session cannot uninstall user-scope winget packages (error 0x8A15007D): uninstall them unelevated.
- A non-admin portable install adds its folder to the user `Path`; an uninstall can leave a trailing `;` behind.
- `wsl.exe` prints UTF-16LE without a byte-order mark, on stderr when piped, with doubled carriage returns.
- `setx` truncates long values (setup never uses it); a RunOnce command line is limited to 260 characters.

## Browser automation, failure hints and hidden text
- **The browser-command guard reads only the command line.** On the corporate profile `playwright-cli` asks before it uploads,
  evaluates code, attaches, loads saved state, calls a page tool, opens an address that is not local or allowed, uses
  `--profile`, `--persistent`, `--extension` or a `--cdp` target that is not localhost, or prints or saves cookies and
  storage. A profile or endpoint set another way is not gated: the variables `PLAYWRIGHT_MCP_USER_DATA_DIR`,
  `PLAYWRIGHT_MCP_EXTENSION` and `PLAYWRIGHT_MCP_CDP_ENDPOINT`, and the configuration keys `userDataDir` and `cdpEndpoint`.
  A quoted value with spaces is split by the shared tokenizer (the call is still asked). `route` is allowed on purpose.
  The permissive profile asks nothing.
- **The hint after a turn that ended in an API error needs a recent Claude Code.** The relay hooks (`StopFailure` and a
  prompt hook) are installed only from Claude Code 2.1.78, the first version with the event, and never under
  managed `allowManagedHooksOnly`. The bell comes from 2.1.141; before that the hint still arrives and the bell is ignored.
  `invalid_request`, `max_output_tokens` and `unknown` have no card, so they get the bell and no hint.
- **Some failures may never reach the failure hook.** It runs when a tool that started executing fails. The hooks reference
  says the event does not fire for calls rejected before execution: an unknown tool, input that fails validation, or a
  permission denial. Cards 30 (an edit refused because the file changed since it was read) and 32 (a command that prompts
  although each part is allowed) may therefore never produce the one-line hint. Search the cards by hand (guide 43). This was
  not tested live.
- **The issues log holds only what the failure hook sees, and only what its scanner knows to hide.** It records the same
  failures as the hint above, so the same blind spot, and not a call you interrupted. Each entry keeps the first ten error lines;
  credential-shaped values are replaced by the shared scanner (known key, token and password shapes), which cannot recognise every
  secret. Read `<WB>/state/issues.jsonl` before you send it to anyone.
- **A key body with no BEGIN line is not recognised.** The credential scanners take a private key block whole (PEM and PuTTY) and
  most credential shapes by their value, but base64 lines of key material that lost their header look like any other base64
  (certificates, images, hashes), so they are not matched. The issues log keeps only ten lines per failure and cannot show a body
  that began before them.
- **The guard knows eight tokensave edit tools by name.** `str_replace`, `multi_str_replace`, `insert_at`, `insert_at_symbol`,
  `replace_symbol`, `ast_grep_rewrite`, `replace_lines` and `delete_symbol` get the same path checks as Edit and Write (any MCP
  tool ending in one of those words does). The pinned 7.12.1 input shapes were not checked against the running server in this
  kit. A relative path is read against the session's folder and also against any `project_root` or `cwd` the call supplies (that
  root is the model's word, not the server's), and it is refused if it hits a protected file through any of them; a call that names a
  base folder under any other key that looks like one (`root`, `workspace`, `directory`, ...) is asked about, because the guard
  cannot tell which folder it means. A symbol edit that names no file works in its base folder: when the session's folder or a
  supplied root holds the settings files or the workbench files (a session started in the Claude home folder) it is asked about. A server
  started on another root, for example with `-p`, is judged by the path as written. A project's own `.claude/settings.json` beneath a
  folder given to a rewrite tool is not looked for, and an edit tool a newer release adds is not covered until its name is added to
  `EDIT_MCP_VERBS` in `plugins/workbench-core/scripts/guards/engine.py` and to the hooks matcher.
- **The command guards read the command text, not what a program does.** They see a command word typed as the command, also
  inside a substitution (`$(...)`, backticks), a script block, a `try` or `foreach` body, an assignment, a `sudo`, `env` or
  `time` prefix and a `pwsh` or `powershell` `-Command` string (quoted or not). They do not see one that something else starts or
  that is spelled indirectly:
  - prefixes and launchers: `nice`, `stdbuf`, `setsid`, `builtin`, `env -i`, `xargs`, `find -exec`, `cmd /c start` and `call`,
    `wsl`, `npx`, `Start-Process`, `eval`;
  - spelling: quote splitting (`to""kensave`), cmd carets, backslash and PowerShell backtick escapes inside a name;
  - indirection: `which` or `Get-Command` output, command names held in variables, shell aliases and functions;
  - wrappers: `.cmd` and `.ps1` shims, and another program that runs the command (`python` with `subprocess`, a build tool).

  A refusal is a net for a mistake, not a boundary against an agent that is working to get around it.
- **Links to the guards' own files are judged by what the command shows, then by the file's identity.** A hard link, symlink or
  junction whose target is a settings or guard file is refused at creation when the target is written out (`fsutil`, `mklink`,
  `ln`, `New-Item`, or a string in a script that calls `os.link`, `symlink_to`, `CreateHardLink` and the like). A target a script
  builds at run time is not visible then. A later write through a symlink or junction is still caught (the path is resolved, also
  for `\\?\Volume{id}\` and `\\?\GLOBALROOT\` spellings), a write to a file that is the same file (device and inode) as a settings
  file is refused under any spelling, and so is one that is the same file as a file in the workbench folder or the workbench plugin
  folders when it has a second name.
- **The standard level trades a refusal for a question.** A push or upload to a host that is not approved, and skipping git hooks, ask
  instead of being refused: when you approve, the code or file goes. The ask is for that one command and is not remembered. Plain
  `playwright-cli` navigation to an ordinary address passes without a question (it is in the guard log). The strict level (`guard_level`
  in `corporate-allowlist.json`, see `settings/SETTINGS.md`) refuses them. A missing file or key, or a value that is neither word, means `standard`; a file that exists but does not parse means `strict`.
- **The guard reads text, so a switch assembled at run time gets past it.** The prompts before turning approvals off or
  lowering the guard catch the switch written out in a command, in inline code (`python -c`) or in an import of the
  installer; a script file, a program that builds the words from pieces (`'--appro' + 'vals'`), or one that writes the
  settings file itself is not seen, like any other step done inside a program. This check reads no files from disk:
  a hook that runs past its time limit decides nothing. A `gh` alias made before the kit was installed runs whatever it names
  under its own name; making a new one asks.
- **The minimal level refuses nothing.** It asks only before the steps `settings/SETTINGS.md` lists (irreversible, outward, credential
  and guard-control steps, and commands it cannot read). Everything else it would have refused or asked about runs, and is in the
  guard log as `PASS [rule] (minimal level ...)`. With command approvals off too, nothing else asks: the guard's few questions are the
  only stop, and a guard that is not running (the doctor's plugin rows FAIL) means none at all.
- **Deleting or moving the guards' folders is judged the same way.** `rm`, `mv`, `rmdir`, `Remove-Item`, `Move-Item`, `rd` and `del`
  typed as the command are refused when the target is, or holds, the workbench plugins, the workbench folder or the settings files
  (so `rm -rf <config folder>/plugins` is refused and a stale cache is refreshed with the `claude plugin` commands instead). So are a
  glob that would match them (`rm -rf <config folder>/plugins/*`, expanded the way the shell would, up to 500 matches and then the folder
  itself), `find <folder> ... -delete` or `-exec rm`, and a `Get-ChildItem <folder> | Remove-Item` or `ls <folder> | xargs rm` pipeline;
  with no folder named the session folder is judged. Not seen: a `cd` earlier in the same command (paths are read against the session
  folder), a filter that only a person could read (`find <config folder> -name '*.tmp' -delete` is refused too, because the guard cannot
  tell it will leave the plugins alone), and a deletion started by another program (the list above). A `-EncodedCommand` payload is decoded
  and judged like the text it carries, up to three levels deep; one that cannot be decoded, or that holds a fourth level, is refused.
  `$HOME`, `${HOME}`, `$env:HOME`, `$env:USERPROFILE`, `%USERPROFILE%` and the same spellings of `CLAUDE_CONFIG_DIR` in a path are expanded
  the way the shell would; variables beyond these (one the command sets itself, a computed path, `$env:APPDATA`) are not followed.
- **The installer and kit-update rule reads the command's text.** It matches the text of a command, not what the shell finally runs,
  so deliberate disguises (globs, quote-splitting, backticks, importing the script from Python) can get past it. Plain options such as
  `--check` are exempt only when the statement holds nothing else; the updater itself still refuses a new repository without `--new-repo`.
- **The first update trusts the repository you name.** `release-source.json` ships with an empty `repo` on purpose, so the first update
  uses the repository named in your message and remembers it (`kit_repo`). The SHA-256 comes from the same release: it shows the
  download is intact, not who published it. Give the link of the release page your kit came from; release signing is deferred.
- **A very long command is judged within limits, or refused.** The hook has 30 seconds, and a hook that times out lets the call
  through, so the guard keeps its own limits. A run of 2,000 or more of one character (base64 of zero-filled data, a row of spaces) is cut
  to 256 before the command is judged. A command with more than 2,000 paths to delete, move, link or write (in practice about 1,000
  separate write statements already reach the next limit), or with text that makes a rule
  re-read its statement over two million characters in all, is refused as too large to judge (`nest-cap`: write the script with the
  Write tool and run the file), and so is one past 256,000 characters. A command that names an outbound-send address more than 64 times
  is asked about without the guard reading each mention.
- **The hidden-text check is a screen, not a guarantee** (`plugins/workbench-core/skills/office-render/scripts/hidden_text.py`).
  It does not see text under a picture, a pattern or other text; an OCR layer that differs from its image; PDF annotations,
  form fields, attachments or XMP metadata; Word text boxes placed off the page, squeezed spacing, table-style fills,
  comments, field codes or embedded objects; or look-alike letters beyond Cyrillic and Greek. It does not scan `.pptx`,
  `.xlsx`, HTML or mail files. Instructions written in plain view pass, because they are not hidden, and a faint
  watermark is reported as hidden text. Ingest does not run it: check a file by hand before it enters the flow
  (`plugins/workbench-capture/skills/ingest/references/quarantine.md`, guide 52).

## Models and evidence
- **Business skills trigger less reliably on the smallest model.** The workbench-biz evals pass every case on the
  mid-tier model; on the small model some skills (policy Q&A, spreadsheet analysis) are not always invoked, so name
  the skill (`/workbench-biz:<skill>`) when you use the small model.
- **Quality picks rest on published benchmarks only.** The kit's own runs set cost and configuration; their quality
  observations are listed as direction-only internal rows that never rank a pick (`docs/model-routing.md`).
- **The routing table can only choose among models your organisation allows.** A row whose first model is not
  allowed falls back down its chain; SessionStart marks a fallback row with `*`.
- **The `haiku` alias reaches Haiku 5.5 only on the Anthropic API.** On Claude Platform on AWS, Bedrock, Vertex and Foundry
  the alias and the background model still resolve to the previous small model; pin the provider's id
  (`settings/SETTINGS.md`). The vendor recommends a recent Claude Code for Haiku 5.5, and the capability report checks the
  recommended minimum version.
- **Claude Code cannot turn thinking off** on Opus 5.5, Sonnet 5.5, Haiku 5.5 or the Fable models. Lower the effort
  instead (`docs/token-diet.md`).
- **Scripts that call the API need changes for Haiku 5.5.** `top_k`, most `temperature` and `top_p` values, thinking
  budgets and assistant prefill are rejected; thinking counts against `max_tokens`; a safeguard refusal and a cut-off
  reply arrive as a normal response with a stop reason, and there is no server-side fallback; Priority Tier is not
  supported. Bug cards 61 to 64 cover these (`kb-template/_shared/bug-cards.md`).
