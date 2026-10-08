# Settings: two profiles and optional plugin sets

| File | What it is | Installer option |
|---|---|---|
| `profiles/corporate.fragment.json` | **Default.** For a managed corporate laptop: prompts for anything beyond reads, bypass mode off, documented defaults for performance settings, shorter transcript retention, stable updates. | `--profile corporate` (default) |
| `profiles/permissive.fragment.json` | **The permissive profile.** No permission prompts (bypass mode), broad allow rules, larger limits for research and subagent fan-outs, and the ponytail plugin's subagent hook kept off. | `--profile permissive` (also applies the upstream plugins) |
| `upstream-plugins.fragment.json` | Two marketplaces and the on/off state of seven plugins: security guidance and PR review on, the rest off. | `--upstream-plugins` |
| `upstream-plugins.optional.fragment.json` | Security-audit and eval plugin marketplaces, every plugin off. Not applied by default: review the licences first (see the installer's `--help` for whether it has an option for this file). | — |

The installer merges the chosen fragment into your user settings (`~/.claude/settings.json`). It
never overwrites a key you already set unless you pass `--force`, never writes a key a managed
source already sets, and adds your KB folder to `permissions.additionalDirectories` so Claude can
read it from any project. **Managed settings always win:** for every row below, a value your
organisation sets in managed settings overrides this one; `/status` shows the managed source on its
`Setting sources` line. Every key and variable here is checked against the Claude Code settings
and environment-variable references; the non-Claude variables are checked against their own
projects' docs.

Placeholders the installer substitutes: `{{PYTHON}}` (the quoted path of the Python interpreter
the installer ran with), `{{WORKBENCH_HOME}}` (`<claude config dir>/workbench`) and `{{KB_ROOT}}`
(the knowledge-base folder you choose).

## Both profiles
| Key | Value | Why | Managed note |
|---|---|---|---|
| `model` | `claude-opus-5-5` | Strongest model as the session default. | A managed `availableModels` constrains this key, `/model` and `--model`; an organisation default model can replace it. |
| `fallbackModel` | `["claude-sonnet-5-5"]` | An overloaded primary falls back to Sonnet for the turn instead of failing. | Taken whole from the highest-precedence file. |
| `effortLevel` | `xhigh` | In user settings it applies only to models older than Opus 5.5; harmless for newer ones. | A managed `effortLevel` or `maxEffortLevel` wins. |
| `modelSettings` | Opus 5.5 / Opus 5 / Fable 5.1 `xhigh`, Sonnet 5.5 `high` | Per-model effort. | Resolved per model; a managed entry or cap wins. |
| `showThinkingSummaries` | `true` | Expand thinking (Ctrl+O) to see why the model did something. Display only. | — |
| `switchModelsOnFlag` | `false` | A flagged request pauses and asks instead of silently switching model. | — |
| `permissions.deny` | Reads of `.env`, `.env.*`, `*.pem`, `*.key`, `*.pfx`, `*.p12` anywhere; `~/.ssh`, `~/.aws`, `~/.azure`, `~/.kube`, `~/.config/gcloud`, `~/.docker/config.json`, `~/.git-credentials`, `~/.netrc` | Keeps secrets out of the model's context. A Read deny also blocks Edit and Write there, and deny rules apply in every mode, bypass included. Side effects: `.env.example` and `~/.ssh/config` are blocked too. Covers Claude's file tools and the file commands it recognises in the shell, not every program. | Deny rules from every source apply. |
| `env.WORKBENCH_KB_ROOT` | `{{KB_ROOT}}` | Tells the workbench hooks and KB tools where the knowledge base lives. | — |
| `env.PYTHONUTF8` / `env.PYTHONIOENCODING` | `1` / `utf-8` | Python reads and writes UTF-8 on Windows; non-ASCII output doesn't crash a hook. (Python docs) | — |
| `env.GIT_TERMINAL_PROMPT` | `0` | Git fails instead of waiting for a password nobody can type. (Git docs) | — |
| `env.GCM_INTERACTIVE` | corporate `0`, permissive `never` | Git Credential Manager fails instead of opening a prompt that hangs the session; sign in once yourself. `never` is GCM's older spelling of `0`. (GCM docs) | — |
| `env.CLAUDE_CODE_FORK_SUBAGENT` | `0` | Fork mode off: subagents start clean with an explicit prompt, and forks fail inside workflow workers. | — |
| `env.DISABLE_FEEDBACK_COMMAND` | `1` | Disables `/feedback`, `/bug`, `/share` and Claude-drafted feedback, the paths that send feedback reports to Anthropic. | — |
| `env.CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY` | `1` | No "How is Claude doing?" survey. | — |
| `env.DISABLE_ERROR_REPORTING` | `1` | No crash reports leave the machine. Unlike `DISABLE_TELEMETRY`, it doesn't turn off feature-flag fetching. | — |
| `attribution.sessionUrl` | `false` | No claude.ai session link in commits or PRs from cloud or Remote Control sessions. | — |
| `autoMemoryEnabled` | `false` | One memory system: the workbench knowledge base. | `CLAUDE_CODE_DISABLE_AUTO_MEMORY` outranks it. |
| `claudeMdExcludes` | `["**/rules/tokensave.md"]` | A code-graph installer can write its own rules file; this keeps `code-graph.md` the one owner. | Managed CLAUDE.md files can't be excluded. |
| `respondToBashCommands` | `false` | Your own `!` commands land in context without an automatic reply. | — |
| `tui` | `default` | Pins the classic renderer; `fullscreen` is the flicker-free alternative. | — |
| `statusLine` | Written by the installer: `<python> <workbench>/statusline.py`, using Windows short paths when a path has a space, or a `powershell -Command` call if a space remains, so it parses in Git Bash, PowerShell and cmd | The workbench statusline (model, effort, context use); the model check in `model-policy.md` relies on it. | Under managed `allowManagedHooksOnly`, only a managed status line runs. |
| `$schema` | schemastore URL | Editor validation and completion. | — |

## Where the profiles differ
| Key | corporate | permissive (`permissive`) | Why | Managed note |
|---|---|---|---|---|
| `permissions.defaultMode` | `default` | `bypassPermissions` | Corporate asks before anything beyond reads. Permissive runs without prompts; the first time a session enters bypass mode, Claude Code asks you to confirm. | A managed `permissions.disableBypassPermissionsMode` stops Claude Code from entering bypass mode; check the mode indicator for the mode the session actually started in. |
| `permissions.disableBypassPermissionsMode` | `disable` | not set | Corporate: nobody, including a subagent definition, can enter bypass mode. | Usually also managed. |
| `permissions.allow` | `WebSearch`; read-only `gh pr view/diff/checks`, `gh run view`, `gh issue view` | `Bash(*)`, `Edit(*)`, `Read(*)`, `WebFetch(*)`, `WebSearch(*)`, `mcp__tokensave` | Corporate pre-approves only searches and read-only GitHub views; `WebFetch` stays in the permission flow because a fetch can carry data out in a URL. Permissive pre-approves broadly. Allow rules have no effect in bypass mode, and auto mode drops blanket `Bash(*)`; they matter when you switch to Manual or Accept Edits. | A managed `allowManagedPermissionRulesOnly` ignores user rules. |
| `env.ANTHROPIC_DEFAULT_OPUS_MODEL` / `_SONNET_` / `_HAIKU_` / `_FABLE_` | not set | `claude-opus-5-5` / `claude-sonnet-5-5` / `claude-haiku-4-5` / `claude-fable-5-1` | Pins what each alias resolves to. Corporate leaves the documented default, which suits cloud providers and gateways with their own model ids. | A managed `env` wins per variable. |
| `env.CLAUDE_CODE_SUBAGENT_MODEL` | not set | `claude-sonnet-5-5` | Default model for subagents that don't name one; personas name their own. | Same. |
| `env.CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION` | not set (200) | `600` | Larger research fan-outs. | — |
| `env.CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | not set | `75` | Compacts earlier, before a very full context degrades. Can only lower the threshold. | — |
| `env.CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY` | not set (10) | `10` | Pins the documented default. | — |
| `env.CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` | not set (20) | `40` | Wide build/attack/verify fan-outs. Lower it if the laptop struggles. | — |
| `env.ENABLE_PROMPT_CACHING_1H` | not set | `1` | 1-hour cache for API-key and cloud-provider users; seats already get it on the main conversation. 1-hour writes cost more. | — |
| `env.ENABLE_TOOL_SEARCH` | not set | `auto:1` | Defers MCP tool definitions unless they fit in 1% of context. Unset, Claude Code already defers them. | Behind an LLM gateway without `tool_reference` support, remove it if MCP calls fail. |
| `env.MCP_TIMEOUT` | not set (30 s) | `60000` | More time for slow-starting MCP servers. | — |
| `env.PONYTAIL_SUBAGENT_MATCHER` | not set | `^(none)$` | Keeps the ponytail plugin's own subagent hook off, because the build personas already carry its text. Matters only if that plugin is enabled. | — |
| `subagentPromptCacheTtl` | not set | `5m` | Cheaper cache writes for short-lived subagent requests. | Env overrides outrank it. |
| `cleanupPeriodDays` | `14` | `30` | Transcripts on disk are plaintext and can hold code or pasted secrets. Corporate keeps two weeks; permissive keeps the default 30. | Often set by IT. |
| `autoUpdatesChannel` | `stable` | `latest` | Corporate takes a build about a week old that skips releases with major regressions. | IT may pin a version or channel. |
| `theme` | not set | `dark` | Also the default. | — |

## Upstream plugins
Applied only with `--upstream-plugins` (or `--profile permissive`). Each marketplace sets
`"autoUpdate": false`, so nothing updates in the background. A managed `strictKnownMarketplaces`
or `blockedMarketplaces` decides what you may add, and the installer leaves it alone. Check your
organisation's policy before you add any marketplace.

| File | Marketplace | Source | Licence | Plugins |
|---|---|---|---|---|
| `upstream-plugins.fragment.json` | `adamsreview` | github `adamjgmiller/adamsreview` | MIT | `adamsreview` **on**. In PR mode it posts review comments: use it on your own PRs, and on others' only when asked (`rules/git.md`). |
| `upstream-plugins.fragment.json` | `ponytail` | github `DietrichGebert/ponytail` | MIT | `ponytail` off: the build personas carry its text. |
| `upstream-plugins.fragment.json` | `claude-plugins-official` (built in) | Anthropic | — | `security-guidance` **on**; `superpowers`, `hookify`, `claude-code-setup`, `frontend-design` off. |
| `upstream-plugins.optional.fragment.json` | `trailofbits` | github `trailofbits/skills` | **CC-BY-SA-4.0** | Ten security-audit plugins, all off. **Share-alike licence:** get your legal or open-source review's OK before installing, and never copy its content into your repos. |
| `upstream-plugins.optional.fragment.json` | `ai-evals-course` | git `https://github.com/ai-evals-course/evals-skills.git` | Apache-2.0 | `evals` off. |

## Optional keys (in neither profile; add them if your policy asks)
| Key | Value | Effect and trade-off |
|---|---|---|
| `DISABLE_TELEMETRY` | `1` | Opts out of usage telemetry. **Also turns off feature-flag fetching**, which disables some features (artifact comments, synced skills and plugins, the PowerShell tool default on Windows with Git Bash, and others in the env-vars reference). |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | `1` | Auto-updates, telemetry, error reporting, feedback and release notes off in one switch. Same feature-flag trade-off. |
| `DISABLE_AUTOUPDATER` | `1` | No background updates; `claude update` still works. Usually IT's call. |
| `NODE_EXTRA_CA_CERTS` | path to the proxy's root CA (PEM) | Needed inside WSL behind a TLS-inspecting proxy (`instructions/rules/corporate-setup.md`). Native Windows reads the system store already. |
| `permissions.blockReadsOutsideWorkingDirectories` | `true` | File tools refuse reads outside your working directories; the KB folder the installer adds still counts as one. |
| `sandbox.enabled` | `true` | OS-level sandbox for shell commands. WSL2 only: native Windows has none. |
| `skillOverrides` | `{"<skill>": "name-only"}` | Collapses rarely used personal skills to their name, saving context. Has no effect on plugin skills. |
| `includeGitInstructions` | `false` | Drops the built-in commit/PR instructions and git status snapshot to save context, if you rely on `rules/git.md` alone. |

## Not set by either profile
- **Hooks:** wired by the plugin's `hooks/hooks.json`.
- **`skipDangerousModePermissionPrompt`:** the bypass confirmation dialog stays on until you accept
  it yourself.
- **Variables that hold an ID, URL, host, path, phone number or another tool's config:** they are
  specific to one person's infrastructure and belong in your own settings, not a shared kit.
