# Reviewing plugins and skills

A reviewer's guide for plugins, skills and MCP servers built by other people, often web users who send an archive rather
than a pull request. These are mostly prose that steers a model (skill text, commands, tool descriptions) plus
configuration, so a normal code review misses what matters: portability, injection surfaces, tool design, hook and
launcher safety, data handling and licences. The `plugin-review` skill runs the checks described here; `docs/plugins-playbook.md`
explains the plugin concepts they rest on.

## The pipeline
1. **Script pass** (`review_plugin.py`, seconds, deterministic). Folder, `.zip`, `.skill` or `.plugin` in; findings with rule
   id, file, line and severity out; `--batch` writes `scorecard.csv` and `scorecard.md` for many plugins.
2. **Model pass** (judgment, read-only). `run_review.py --local DIR --rubric references/REVIEW.md` from the `repo-review`
   skill: three read tools, no MCP server, no project settings (`--strict-mcp-config`, `--setting-sources user`). It answers
   what a script cannot: does each description match the code, is a write path reachable from untrusted content, does the
   plugin ask for more than it needs. Findings are mapped to the OWASP MCP Top 10 (2025 beta).
3. **Code review** of code inside the plugin (below).
4. **Merge, dedupe, rank, one verdict line** for the requester: ship, fix then ship (top three fixes), do not ship.

## Intake rules
The input is never executed, imported or installed; Python helper processes start with `-I`. An archive is unpacked by the
reviewer itself into a fresh temporary folder, deleted afterwards. It is refused, with nothing written, when:

| Id | Refused when |
|---|---|
| `X01-zip-slip` | an entry path is absolute, holds `..`, a drive letter or a colon, or resolves outside the target |
| `X02-zip-bomb` | more than 5,000 entries, a file over 50 MiB, a file over 1 MiB that expands more than 100 times, over 200 MiB in total, or more bytes arrive than the header declared |
| `X03-zip-symlink` | an entry is a symbolic link |
| `X04-reserved-device-name` | an entry is named like a Windows device (con, nul, com1 and so on) |

A single top-level folder inside the archive is entered automatically. Links in a folder input are reported by rule `L07`
and never followed. `--unpack DIR` performs the same checked extraction for the model pass.

## Severity and verdict
`block`: must be fixed before anything ships (the surface will refuse it, or it is unsafe as written). `hold`: ship only
after a person has looked and decided. `warn`: advice. `note`: observation. The reviewer's verdict is `do-not-ship` with any
block, `fix-then-ship` with any hold, otherwise `ship`; an unpacked archive that fails intake is `refused`. "Error" for
measurement purposes means block or hold. Each report carries `surfaces` (`cli`, `desktop`, `web`: false when a block
finding belongs to that surface), `stats`, and `rules_sha256`, the digest of the rule ids and the rules source, so a report
says which rule set produced it. Choose `--target cli`, `web` or `all`; a rule runs only for the targets it lists.

## The rules, by group
### 1. Layout and manifest

| Rule | Severity | Applies to | Flags |
|---|---|---|---|
| `L01-manifest` | block | cli, desktop, web | no plugin.json and no SKILL.md, or a config file that is not valid JSON |
| `L02-multiple-manifests` | block | cli, desktop, web | more than one plugin.json in one archive |
| `L03-name-pattern` | block | cli, desktop, web | plugin name not lowercase-hyphen or over 64 characters |
| `L04-reserved-name` | block | cli, desktop, web | name starts with a reserved prefix or is a reserved word |
| `L05-lookalike-name` | block | cli, desktop, web | invisible characters, or Latin letters mixed with look-alike letters, in name, displayName or author |
| `L06-path-outside` | block | cli, desktop, web | a component path that is absolute, climbs with .., or leaves ${CLAUDE_PLUGIN_ROOT} |
| `L07-symlink` | block | cli, desktop, web | symlink or junction, Git LFS pointer instead of the file, git submodule file |
| `L08-os-junk` | block | cli, desktop, web | DS_Store, Thumbs.db, desktop.ini, AppleDouble and __MACOSX entries |
| `L09-file-size` | hold | cli, desktop, web | a non-image file of 256 KiB or more |
| `L10-file-count` | hold | cli, desktop, web | more than 512 files |
| `L11-readme` | block | cli, desktop, web | no README, or fewer than 40 words outside code blocks |
| `L12-license` | block | cli, desktop, web | no LICENSE file and no license field (plugin); no licence beside a skill (skills bundle) |

### 2. Marketplace

| Rule | Severity | Applies to | Flags |
|---|---|---|---|
| `M01-marketplace-schema` | block | cli, desktop, web | marketplace.json not an object, no valid name, no owner.name, plugins not a list, entry without name or source |
| `M02-version-twice` | hold | cli, desktop, web | version set in both plugin.json and the marketplace entry |
| `M03-unpinned-source` | hold | cli, desktop, web | a third-party source (github, url, git-subdir, git URL) without a 40-character sha |

### 3. Skill frontmatter per surface

| Rule | Severity | Applies to | Flags |
|---|---|---|---|
| `F01-nonportable-key` | block | web | a frontmatter key claude.ai uploads reject (the fifteen listed in the playbook) |
| `F02-unknown-key` | block | web | any other frontmatter key |
| `F03-skill-name` | block | web | no frontmatter; name not lowercase-hyphen, over 64, holds anthropic or claude, or differs from the folder |
| `F04-skill-description` | block | web | description empty, over 1,024 characters, or holding < or > |
| `F05-body-length` | warn | web | skill body of 500 lines or more |
| `F06-bin-dir` | block | desktop, web | a top-level bin/ folder |

### 4. Hook safety

| Rule | Severity | Applies to | Flags |
|---|---|---|---|
| `H01-shell-form` | warn | cli, desktop | command hook in shell form (prefer command plus args) |
| `H02-unquoted-plugin-root` | hold | cli, desktop | shell-form hook with ${CLAUDE_PLUGIN_ROOT} outside quotes |
| `H03-user-config-in-shell` | block | cli, desktop | ${user_config.*} in a shell-form hook (rejected) |
| `H04-no-timeout` | warn | cli, desktop | command or http hook with no timeout |
| `H05-broad-matcher` | warn | cli, desktop | tool event with no matcher, *, or .* |
| `H06-network-call` | hold | cli, desktop | curl, wget, Invoke-WebRequest, requests, urllib, fetch in a hook or the script it runs |
| `H07-env-credential-read` | hold | cli, desktop | hook or its script reads a *_TOKEN, *_SECRET, *_API_KEY or *_PASSWORD variable |
| `H08-write-outside-data` | warn | cli, desktop | hook script writes under the home folder instead of ${CLAUDE_PLUGIN_DATA} |
| `H09-dangerous-command` | hold | cli, desktop | recursive delete, eval, recursive Remove-Item, mkfs, dd in a hook or its script |
| `H10-inline-program` | hold | cli, desktop | python -c, node -e, bash -c, powershell -Command and similar in a hook |
| `H11-http-hook-not-https` | block | cli, desktop | http hook whose URL is not https (localhost allowed) |

### 5. MCP config pinning and secrets

| Rule | Severity | Applies to | Flags |
|---|---|---|---|
| `P01-url-not-https` | block | cli, desktop, web | remote MCP URL that is not https or wss (localhost allowed) |
| `P02-literal-credential` | block | cli, desktop, web | literal value in a secret-looking header or env entry |
| `P03-secret-not-sensitive` | hold | cli, desktop, web | secret-looking userConfig option without sensitive: true; ${user_config.X} not declared |
| `P04-env-credential-ref` | hold | cli, desktop, web | server config reads a *_TOKEN-style environment variable |
| `P05-shell-launcher` | hold | cli, desktop | local server started through sh, bash, cmd, powershell, -c, or npm run |
| `P06-unpinned-launcher` | block | cli, desktop | npx, uvx, bunx, pipx, pnpm dlx, npm exec or uv tool run without an exact version |
| `P07-registry-override` | hold | cli, desktop | .npmrc, uv.toml, bunfig.toml, pip.conf, .yarnrc, .pypirc |
| `P08-remote-bundle` | block | cli, desktop, web | .mcpb or .dxt bundle fetched from a URL |
| `P09-local-stdio-server` | block | web | a local (stdio) server: cannot run on claude.ai |
| `P10-user-config-in-url` | block | web | ${user_config.*} inside an MCP URL: ignored in chat |
| `P11-uv-run-unlocked` | hold | cli, desktop | uv run without --locked or --frozen |

### 6. Prompt-injection surfaces and tool behaviour

| Rule | Severity | Applies to | Flags |
|---|---|---|---|
| `I01-override-phrase` | hold | cli, desktop, web | wording that tells the model to ignore or override earlier instructions or hide things from the user |
| `I02-always-call` | hold | cli, desktop, web | text that says which tool to call first or before any other tool |
| `I03-fetch-rules-from-url` | hold | cli, desktop, web | tells the model to fetch its rules or instructions from a link |
| `I04-hidden-comment` | hold | cli, desktop, web | an HTML comment addressed to the model |
| `I05-invisible-characters` | block | cli, desktop, web | zero-width, bidirectional-control or tag characters |
| `I06-encoded-blob` | hold | cli, desktop, web | base64 or hex run of 100+ characters outside assets/ |
| `I07-exfil-sink` | hold | cli, desktop, web | image link with a query string, or a webhook or tunnel address |
| `I08-lethal-trifecta` | hold | cli, desktop, web | private-data access, untrusted-content reading and an outbound channel in one plugin |
| `I09-readonly-hint-lies` | hold | cli, desktop | tool marked readOnlyHint whose code writes (Python) |
| `I10-write-without-destructive-hint` | hold | cli, desktop | tool that writes but declares no destructiveHint (Python) |
| `I11-catch-all-request-tool` | hold | cli, desktop | tool taking a method plus url, path or endpoint (Python) |
| `I12-identity-argument` | hold | cli, desktop | tool argument such as as_user or impersonate (Python) |
| `C01-stdout-logging` | hold | cli, desktop | print() in an MCP server file: stdout carries the protocol (Python) |
| `C02-shell-injection` | block | cli, desktop | shell=True, os.system or os.popen with a non-literal command (Python) |
| `C03-sql-concatenation` | hold | cli, desktop | SQL passed to execute built with f-string, +, % or .format (Python) |
| `C04-path-traversal` | hold | cli, desktop | tool opens a path built from its arguments without confining it (Python) |
| `C05-eval-exec` | hold | cli, desktop | eval or exec on a non-literal (Python) |

### 7. Data handling

| Rule | Severity | Applies to | Flags |
|---|---|---|---|
| `D01-credential-shape` | block | cli, desktop, web | credential-shaped value in any text file (the kit's secret scanner) |
| `D02-denylist` | block | cli, desktop, web | a line of the optional denylist file matches a file name or text; the report names the rule number only |
| `D03-pii-shape` | warn | cli, desktop, web | e-mail address outside example domains, phone number or id-number shape |

### 8. Licences

| Rule | Severity | Applies to | Flags |
|---|---|---|---|
| `V01-license-spdx` | warn | cli, desktop, web | license not a recognised SPDX id |
| `V02-vendored-without-license` | hold | cli, desktop, web | vendored skill (UPSTREAM.txt or vendor folder) with no LICENSE or NOTICE |
| `V03-source-available-skill` | block | cli, desktop, web | skill licence says all rights reserved, proprietary or source-available |
| `V04-share-alike-vendored` | hold | cli, desktop, web | share-alike or GPL-family licence on vendored content in a permissive plugin |

### 9. Supply chain

| Rule | Severity | Applies to | Flags |
|---|---|---|---|
| `S01-claude-validate` | hold | cli | claude plugin validate --strict failed (only with --validate) |

Python-only rules parse code with `ast` and never run it; JavaScript and TypeScript servers get the text rules only.

## How the rules are measured
`tests/make_fixtures.py` builds fictional plugins into a scratch folder at test time (nothing is committed): a clean
control with decoys, near-miss negatives (an exactly pinned `npx` package, the word "ignore" in ordinary prose, a
placeholder key, `curl` inside a fenced example, a base64 image under `assets/`, a checksum in prose), one plugin per
seeded defect with an `expected.json` (rule, file, line range, severity), and a hold-out set of six defects drawn from a pool
by `WB_HOLDOUT_SEED`. The test requires 80 percent recall by rule id and file, 100 percent on block-severity defects, and
no block or hold finding on the control or any near-miss. It reports hold-out recall separately; never tune a rule against
that number, and treat an edit to a fixture after seeing results as tampering. A "test the test" step deletes each rule in
turn and requires the fixtures that depend on it to stop matching. A checker that was only ever shown the cases it was
written for proves little: re-run with a new seed before trusting a recall figure, and add the missed pattern to the seeded
set only after reading why it was missed.

## Reviewing the code inside a plugin
The built-in `/code-review` and `/security-review` read a diff, so give them one. Do this on a throwaway repository, never
inside the reviewed folder:
1. Create a folder whose path contains `wb-review/` (the `repo-review` settings exclude instruction files under that
   path), run `git init` there, make an empty initial commit on the default branch, and add a local bare repository as
   `origin`.
2. Create a branch, copy the unpacked plugin into it, commit.
3. Start Claude Code in that folder with `--setting-sources user --strict-mcp-config --settings` pointing at the
   `repo-review` skill's `review-settings.json` (hooks off, instruction files excluded), then run `/code-review high` and
   `/security-review`.
Not yet tested: that `/security-review` accepts a local bare origin, and that both commands run under these flags. If either
fails, fall back to the model pass in the pipeline above. For servers, also dump the tools/list reply and read each tool's
title, safety hint and description against the tool-design questions in `references/REVIEW.md`.

## Batch reviews
Put the archives in one folder (or list their paths in a text file) and run
`review_plugin.py --batch DIR --scorecard OUT`. Each plugin is reviewed in a separate Python process with a timeout, so
a hostile or broken input cannot stop the batch. The scorecard has one row per plugin: verdict, counts by severity, top
three findings. Sort by verdict, send the authors of `do-not-ship` plugins the block findings, and keep the report for
the audit trail. Private terms for `--denylist` stay in a file outside every plugin and repository.

## Limits
A clean report is not a security clearance: the rules are heuristics, and the lethal-trifecta rule (private data, untrusted
content and an outbound channel in one plugin) is a keyword check. External scanners are not run because their accuracy
is unmeasured here. A marketplace repository is checked at its root for the marketplace file only; review each
folder under plugins as its own input.
