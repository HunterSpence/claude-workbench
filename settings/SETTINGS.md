# Settings: two profiles and optional plugin sets

| File | What it is | Installer option |
|---|---|---|
| `profiles/corporate.fragment.json` | **Default.** For a managed corporate laptop: prompts for anything beyond reads, bypass mode off, the minimal permission rules below, a Sonnet subagent default with tuned compaction, tool-search and cache settings, shorter transcript retention, stable updates. | `--profile corporate` (default) |
| `profiles/permissive.fragment.json` | **The permissive profile.** No permission prompts (bypass mode), broad allow rules, larger limits for research and subagent fan-outs, and the ponytail plugin's subagent hook kept off. | `--profile permissive` (also applies the upstream plugins) |
| `upstream-plugins.fragment.json` | Two marketplaces and the on/off state of seven plugins: security guidance, PR review and frontend design on, the rest off. | `--upstream-plugins` |
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

## Permission rules
Both profiles carry the same minimal set: rules that ask before a step that loses work for good, and none that block. There is no guard hook; a permission rule matches command text, not intent. Rules are checked deny first, then ask, then allow; an ask rule still prompts in bypass mode and beats a broader allow such as `Bash(*)`; a trailing ` *` also matches the bare command (E40, fetched Oct 2026).

**Command asks: 11 patterns, each written for both the `Bash` and the `PowerShell` tool (22 entries).**
- Force push, with a flag or a `+refspec` after `push`: `git push *--force*`, `git push -f*`, `git push * -f*`, `git push * +*`, `git push +*`. The first four again with options between `git` and `push` (`git -C <dir> push ...`, `git -c <key>=<value> push ...`): `git * push *--force*`, `git * push -f*`, `git * push * -f*`, `git * push * +*`. A plain `git push`, `git push origin main`, `git push -u origin feature` and `git -C <dir> push origin main` are not matched.
- GitHub CLI: `gh repo delete *`, `gh release delete *`.

Remove a rule and the kit never re-adds it. Earlier releases also asked before package publishes, uploads, secret and visibility changes, and denied reads of secret files; an upgrade takes those kit-written rules out (rules you wrote stay).

**One deny, added by the installer and not by the profiles:** `Edit(//<drive>/<kb folder>/active-context.md)` (the path in Claude Code's POSIX form, drive letter lower case). The memory file has a single writer, the save driver. Claude Code consults `Edit(path)` rules for every built-in edit tool, so the Edit deny stops the Edit and Write tools; a shell or MCP write is not stopped. A `Write(path)` rule would be accepted and never consulted (E40).

**Protected by Claude Code itself, with no rule from the kit:** `rm` and `rmdir` of a critical path (the home folder, the working folder and its parents, drive roots) are never approved by an allow rule or a hook, and `Remove-Item` of the home folder or a drive root is denied in every mode (E40).

**Residual limits (documented, not chased).** A rule matches the command text as written. A rule does not match an alias, `bash -c '...'` or a script that runs the command, a command built in a variable, a git configuration trick, bundled short flags (`git push -uf ...`, `git push -vf ...`), which force-push without a prompt, a `+refspec` with options between `git` and `push` (`git -C <dir> push +main`), or a `+` after a colon in a refspec (`git push origin HEAD:+main`). A managed `allowManagedPermissionRulesOnly: true` makes every one of these user rules inert; the kit can only report it.

## Both profiles
| Key | Value | Why | Managed note |
|---|---|---|---|
| `model` | `claude-opus-5-5` | Strongest model as the session default. | A managed `availableModels` constrains this key, `/model` and `--model`; an organisation default model can replace it. |
| `fallbackModel` | `["claude-sonnet-5-5"]` | An overloaded primary falls back to Sonnet for the turn instead of failing. A request a safety classifier flags re-runs on the fallback model Claude Code names for its category (`switchModelsOnFlag` below makes it ask first). When the organisation's allowed-models list blocks that model, no fallback occurs and you see the refusal as an error. | Taken whole from the highest-precedence file. |
| `effortLevel` | `xhigh` | In user settings a top-level `effortLevel` applies only to older models (Opus 5, Fable 5.1 and earlier), not to Opus 5.5 or later ones; in project, local or managed settings, or passed with `--settings`, it applies to every model (E38, fetched Oct 2026). | A managed `effortLevel` or `maxEffortLevel` wins. |
| `modelSettings` | Opus 5.5 / Opus 5 / Sonnet 5.5 `xhigh`, Fable 5.1 `high`, Haiku 5.5 `medium` | Per-model effort for any agent or session that sets none. Sonnet 5.5 at `xhigh` matches the BREADTH and CODE rows of `docs/model-routing.md`. Fable 5.1 at `high` is the vendor's starting level; `xhigh` and `max` are for evals that show a gain (E33, fetched Oct 2026). Haiku 5.5 at `medium` is the vendor's recommended starting level for most work; the `scout` persona pins its own `high`, which wins over it. Without an entry a model runs at Claude Code's own default level (`medium` for Opus 5.5, Sonnet 5.5 and Haiku 5.5; Fable 5.1 is not named on that page, so its general rule of `high` applies), because a top-level `effortLevel` in user settings does not reach Opus 5.5 or later models (E38, fetched Oct 2026). | Resolved per model; a managed entry or cap wins. |
| `showThinkingSummaries` | `true` | Expand thinking (Ctrl+O) to see why the model did something. Display only. | — |
| `switchModelsOnFlag` | `false` | A flagged request pauses and asks instead of silently switching model. | — |
| `skillListingBudgetFraction` | `0.02` | The share of the context window Claude Code may spend on the skill listing each turn (default `0.01`). **A ceiling, not a cost:** the listing grows only to the text that exists, so a small listing costs nothing extra and a large one costs a few hundred tokens a turn. Why: a listing with organisation and plugin skills can pass the 30,000-character default; past the limit Claude Code keeps every skill name but drops the descriptions of the least-used skills, so Claude stops choosing them. The kit also keeps its own part short (`docs/token-diet.md`, "The skill listing"). Any settings file may carry it. | A managed value wins. |
| `permissions.ask` | 22 rules: the 11 command patterns for each of Bash and PowerShell, listed under "Permission rules" above | Asks before a force push, a repository delete or a release delete. **These prompt even in bypass mode** (E40, fetched Oct 2026). The only deny is the installer's rule on the KB's `active-context.md`. | Ask rules from every source apply. |
| `env.WORKBENCH_KB_ROOT` | `{{KB_ROOT}}` | Tells the workbench hooks and KB tools where the knowledge base lives. | — |
| `env.PYTHONUTF8` / `env.PYTHONIOENCODING` | `1` / `utf-8` | Python reads and writes UTF-8 on Windows; non-ASCII output doesn't crash a hook. (Python docs) | — |
| `env.GIT_TERMINAL_PROMPT` | `0` | Git fails instead of waiting for a password nobody can type. (Git docs) | — |
| `env.GCM_INTERACTIVE` | corporate `0`, permissive `never` | Git Credential Manager fails instead of opening a prompt that hangs the session; sign in once yourself. `never` is GCM's older spelling of `0`. (GCM docs) | — |
| `env.CLAUDE_CODE_FORK_SUBAGENT` | `0` | Fork mode off: subagents start clean with an explicit prompt, and forks fail inside workflow workers. | — |
| `env.DISABLE_FEEDBACK_COMMAND` | `1` | Disables `/feedback`, `/bug`, `/share` and Claude-drafted feedback, the paths that send feedback reports to Anthropic. A feedback report carries the session transcript and is kept for five years. | — |
| `env.CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY` | `1` | No "How is Claude doing?" survey. | — |
| `env.DISABLE_ERROR_REPORTING` | `1` | No crash reports leave the machine. | — |
| `env.HF_HUB_DISABLE_TELEMETRY` | `1` | The embedding-model download sends no usage telemetry to Hugging Face. | — |
| `env.PIP_DISABLE_PIP_VERSION_CHECK` | `1` | pip doesn't call out to check for a newer pip on every run. | — |
| `env.NPM_CONFIG_UPDATE_NOTIFIER` | `false` | npm doesn't call out to check for a newer npm. | — |
| `env.MCP_TIMEOUT` | `60000` | Milliseconds an MCP server may take to start (default `30000`). Slow stdio servers (npx, uvx, ssh-backed) miss the default window where antivirus scanning and TLS inspection slow the first start, and then show as failed. It only lengthens the wait for a server that is starting; a dead server still fails. | — |
| `env.MSYS2_ARG_CONV_EXCL` | `origin/;upstream/;refs/` | Git Bash on Windows only; harmless elsewhere. Git Bash rewrites an argument shaped like a path list before a native Windows program sees it: `origin/main:/path` arrives as `origin\main;C:\...` and `refs/heads/a:/b` as `refs\heads\a;B:\`. Arguments that start with one of these prefixes are left alone, so `git show origin/main:/path` reaches git unchanged, while the conversion that helps (`/c/...` to a Windows path) keeps working. (`origin/main:path`, with no slash after the colon, is never rewritten.) Prefer it to the blanket `MSYS2_ARG_CONV_EXCL=*`, which turns every conversion off. Reproduced and fixed on Git for Windows 2.55. | — |
| `env.CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` | corporate `8`, permissive `12` | Caps parallel subagents per session (Claude Code's default is 20) so a fan-out doesn't freeze a laptop. Raise it if the machine copes. | — |
| `env.CLAUDE_CODE_SUBAGENT_MODEL` | `claude-sonnet-5-5` | The default model for subagents, agent-team teammates and workflow agents that nothing else assigns a model. The built-in `general-purpose` subagent has no definition of its own, so with this set it runs Sonnet 5.5 and the BREADTH row of `docs/model-routing.md` is real; unset, it inherits the session's model (Opus 5.5 here). Order: the model Claude passes for that call, the definition's `model` field (every kit persona names its own), this variable, then the session's model (E36, fetched Oct 2026). **Needs Claude Code 2.1.251 or newer:** before that the variable overrode both of the first two, which would turn every Opus persona into Sonnet, so the installer writes it only when `claude --version` reports 2.1.251 or newer. It does not change the built-in Explore and Plan subagents. The kit never sets `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` (2.1.257 or newer), which would make this variable override every persona. If an allowed-models list excludes Sonnet 5.5, the subagent runs on the inherited model instead. | A managed `env` value wins; a managed `availableModels` constrains it. |
| `env.CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | `75` | Compacts earlier, before a very full context degrades. A percentage from 1 to 100 that can only lower the threshold; it applies to the main conversation and to subagents (E41, fetched Oct 2026). | A managed `env` value wins. |
| `env.ENABLE_TOOL_SEARCH` | `auto:1` | Defers MCP tool definitions unless they fit in 1% of context (E41, fetched Oct 2026). Unset, Claude Code already defers them. | Behind an LLM gateway without `tool_reference` support, remove it if MCP calls fail. |
| `subagentPromptCacheTtl` | `5m` | Subagents, compaction and other requests outside the main conversation keep the five-minute lifetime: cheaper writes for short-lived requests. Takes `5m` or `1h` and needs Claude Code 2.1.242 or newer; it outranks `ENABLE_PROMPT_CACHING_1H` (E37, fetched Oct 2026). | Env overrides outrank it. |
| `crossSessionInbound` | `hold` | A message from another of your Claude Code sessions shows as a notice and is not delivered to Claude, so one session can't steer another. | A stricter managed value wins. |
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
| `permissions.allow` | `WebSearch`; read-only `gh pr view/diff/checks`, `gh run view`, `gh issue view` | `Bash(*)`, `Edit(*)`, `Read(*)`, `WebFetch(*)`, `WebSearch(*)` | Corporate pre-approves only searches and read-only GitHub views; `WebFetch` stays in the permission flow because a fetch can carry data out in a URL. Permissive pre-approves broadly. Allow rules have no effect in bypass mode, and auto mode drops blanket `Bash(*)`; they matter when you switch to Manual or Accept Edits. There is no server-wide allow for the code-graph server (`mcp__tokensave`): a whole-server rule would also pre-approve its edit tools. | A managed `allowManagedPermissionRulesOnly` ignores user rules. |
| `env.ANTHROPIC_DEFAULT_OPUS_MODEL` / `_SONNET_` / `_HAIKU_` / `_FABLE_` | not set | `claude-opus-5-5` / `claude-sonnet-5-5` / `claude-haiku-5-5` / `claude-fable-5-1` | Pins what each alias resolves to; the Haiku variable also picks the background model. Corporate leaves the documented default, which suits cloud providers and gateways with their own model ids. On the Anthropic API `haiku` already means Haiku 5.5 with a recent Claude Code (the capability report checks the recommended minimum). On Claude Platform on AWS, Bedrock, Vertex or Foundry it still resolves to the previous small model, so set `ANTHROPIC_DEFAULT_HAIKU_MODEL` to the provider's Haiku 5.5 id from `docs/model-routing.md` (Claude Platform on AWS uses the Anthropic API id). | A managed `env` wins per variable. |
| `env.CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION` | not set (200) | `600` | Larger research fan-outs. | — |
| `env.CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY` | not set (10) | `10` | Pins the documented default. | — |
| `env.ENABLE_PROMPT_CACHING_1H` | not set (optional) | `1` | Optional, off in corporate: helps only on billed usage (API key, cloud provider, usage credits) with frequent 5 to 60 minute idle gaps; one-hour cache writes cost twice the input price (E32, fetched Oct 2026). It adds nothing for the main conversation on a seat within plan usage, which already gets one hour, and the one-hour lifetime is not available through a Claude apps gateway (E37, fetched Oct 2026). Permissive sets it. | `FORCE_PROMPT_CACHING_5M` and the TTL variables and settings outrank it. |
| `env.PONYTAIL_SUBAGENT_MATCHER` | not set | `^(none)$` | Keeps the ponytail plugin's own subagent hook off, because the build personas already carry its text. Matters only if that plugin is enabled. | — |
| `cleanupPeriodDays` | `14` | `30` | How long transcripts stay on disk. Corporate keeps two weeks; permissive keeps the default 30. | Often set by IT. |
| `autoUpdatesChannel` | `stable` | `latest` | Corporate takes a build about a week old that skips releases with major regressions. | IT may pin a version or channel. |
| `theme` | not set | `dark` | Also the default. | — |
| `includeGitInstructions` | not set (`true`) | `false` | Drops the built-in commit/PR instructions and git status snapshot to save context; `rules/git.md` carries the git rules instead. Corporate keeps the built-ins. | — |

## Command approvals on the corporate profile (`--approvals off`)
The corporate profile asks before every command that is not on the allow list. `install.py --apply --approvals off` (or,
from an installed kit, `kit_update.py set --approvals off`, which repeats your profile and opt-ins) keeps the corporate profile
and changes only this:
- `permissions.defaultMode` becomes `bypassPermissions`, so new windows run ordinary commands without a prompt;
- the kit's own `permissions.disableBypassPermissionsMode` is removed (recorded, so uninstall or `--approvals ask` puts it back);
- `Bash(*)`, `PowerShell(*)` and `Edit(*)` join `permissions.allow`. They matter when bypass mode is not available: a managed
  `disableBypassPermissionsMode`, or one you set yourself, is kept, and new windows then start in `acceptEdits` instead.

What does not change: the minimal ask set and the `active-context.md` deny (see "Permission rules"; ask rules prompt in bypass
mode too). The choice is kept across upgrades (`config.json` `approvals`); `--approvals ask` restores the prompts. The permissive
profile already runs without prompts and ignores this option.

## Upstream plugins
Applied only with `--upstream-plugins` (or `--profile permissive`). Each marketplace sets
`"autoUpdate": false`, so nothing updates in the background. A managed `strictKnownMarketplaces`
or `blockedMarketplaces` decides what you may add, and the installer leaves it alone. Check your
organisation's policy before you add any marketplace.

| File | Marketplace | Source | Licence | Plugins |
|---|---|---|---|---|
| `upstream-plugins.fragment.json` | `adamsreview` | github `adamjgmiller/adamsreview` | MIT | `adamsreview` **on**. In PR mode it posts review comments to the PR. |
| `upstream-plugins.fragment.json` | `ponytail` | github `DietrichGebert/ponytail` | MIT | `ponytail` off: the build personas carry its text. |
| `upstream-plugins.fragment.json` | `claude-plugins-official` (built in) | Anthropic | `frontend-design`: Apache-2.0 (its `LICENSE`, checked with `gh api`) | `security-guidance` **on**; `frontend-design` **on** (design guidance for building UIs; `rules/work-workflows.md`); `superpowers`, `hookify`, `claude-code-setup` off. |
| `upstream-plugins.optional.fragment.json` | `trailofbits` | github `trailofbits/skills` | **CC-BY-SA-4.0** | Ten security-audit plugins, all off. **Share-alike licence:** get your legal or open-source review's OK before installing, and never copy its content into your repos. |
| `upstream-plugins.optional.fragment.json` | `ai-evals-course` | git `https://github.com/ai-evals-course/evals-skills.git` | Apache-2.0 | `evals` off. |

## Code intelligence plugins (optional)
Claude Code's official marketplace has one plugin per language that connects Claude to that language's language server, so
Claude sees type errors after its own edits and finds definitions and references by symbol. The plugin does not include the
server: you install the language server binary first (the vendor's page has the table: for example `pyright-langserver` for
Python), then the plugin, then check the server starts. They work in terminal sessions only, not in cloud sessions. The
kit applies none of them; a managed `strictKnownMarketplaces` or `blockedMarketplaces` decides whether you may. Licences:
check the language server's own licence as you would any tool's (`THIRD-PARTY.md` lists what the kit installs).

## Optional keys (in neither profile; add them if your policy asks)
| Key | Value | Effect and trade-off |
|---|---|---|
| `DISABLE_TELEMETRY` | `1` | Opts out of usage telemetry. It (and `DO_NOT_TRACK`, which Claude Code treats the same way) also turns off feature-flag fetching, which disables some features (artifact comments, claude.ai skills and plugins synced into the terminal, Remote Control, the PowerShell tool by default on Windows with Git Bash; the full list is in Claude Code's environment-variable reference). Neither profile sets them; setup passes `DO_NOT_TRACK=1` only to the tools it runs. |
| `skipWebFetchPreflight` | `true` | WebFetch stops sending each hostname to the Claude API host for its safety blocklist check; set it where policy blocks that host (cloud providers, gateways). **Caveat:** with the check off, WebFetch tries any URL, so add `WebFetch(domain:...)` permission rules if you need to limit which domains Claude can reach. |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | `1` | Auto-updates, telemetry, error reporting, feedback and release notes off in one switch. Same feature-flag trade-off. |
| `DISABLE_AUTOUPDATER` | `1` | No background updates; `claude update` still works. Usually IT's call. |
| `NODE_EXTRA_CA_CERTS` | path to the proxy's root CA (PEM) | Needed inside WSL behind a TLS-inspecting proxy (`instructions/rules/corporate-setup.md`). Native Windows reads the system store already. |
| `permissions.blockReadsOutsideWorkingDirectories` | `true` | File tools refuse reads outside your working directories; the KB folder the installer adds still counts as one. |
| `sandbox.enabled` | `true` | OS-level sandbox for shell commands. WSL2 only: native Windows has none. |
| `sandbox.failIfUnavailable` | `true` | Claude Code exits at startup when the sandbox cannot start, instead of running commands unsandboxed. The vendor's sandbox page says the sandbox does not run on native Windows, so with this set Claude Code exits there: use it only where the sandbox works (WSL2, Linux), never in a profile for Windows machines. A managed value of a Boolean sandbox key wins over a local one. |
| `outputStyle` | `"Concise"` | The built-in Concise style: the first sentence of a reply states what happened or what the answer is, with no lead-in, narration or closing recap, and the work is done as thoroughly as in the default style. Needs Claude Code v2.1.237 or later. The value is case-sensitive (`concise` gives the default style); `/output-style concise` switches for one session, and a project's own settings take precedence over the user value. Fewer output tokens (`docs/token-diet.md`). |
| `CLAUDE_CODE_ENABLE_TELEMETRY` with `OTEL_METRICS_EXPORTER=console` and `OTEL_METRIC_EXPORT_INTERVAL=1000` | `1` / `console` / `1000` | The vendor's own recipe for looking at Claude Code's OpenTelemetry metrics on this machine: the console exporter, one-second interval, no collector needed. It is off in both profiles. Prompt text, response text and tool content are logged only when you also set `OTEL_LOG_USER_PROMPTS`, `OTEL_LOG_TOOL_CONTENT` or `OTEL_LOG_RAW_API_BODIES`; each is disabled by default, so leave them unset. Managed settings can lock the exporter selectors, and a repository's own settings files cannot set them. |
| `skillOverrides` | `{"<skill>": "name-only"}` | Collapses a rarely used skill to its name, saving context (`user-invocable-only` hides one from the model). It covers your own and project skills, **never the kit's**: Claude Code documents that plugin skills are not affected by `skillOverrides`, and every kit skill is a plugin skill. (Whether it applies to skills synced from your claude.ai account into `skills/synced/` is not stated by the vendor: check the state in `/skills`.) The kit tiers its own skills in their frontmatter instead: the authoring and admin skills carry `disable-model-invocation: true`, which keeps their descriptions out of the listing. `setup` computes tiers for the skills that are not plugin skills and never overwrites a value you set. Why and how: `docs/token-diet.md`, "The skill listing". |

## Not set by either profile
- **Hooks:** wired by the plugin's `hooks/hooks.json`.
- **`CLAUDE_CODE_SUBAGENT_MODEL_FORCE`, `--effort` and `CLAUDE_CODE_EFFORT_LEVEL`:** never set by the kit. The first would make
  one model override every persona; the other two outrank every saved effort level (`instructions/rules/model-policy.md`).
- **`skipDangerousModePermissionPrompt`:** the bypass confirmation dialog stays on until you accept
  it yourself.
- **Variables that hold an ID, URL, host, path, phone number or another tool's config:** they are
  specific to your own infrastructure, so they belong in your own settings, not a shared kit.
