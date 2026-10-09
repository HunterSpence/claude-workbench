# How we work

One page on how the kit is laid out and how work flows through it. It is read on demand, never loaded every
session. When this page and a live value disagree (a model pin, a setting), trust the live value.

## 1. Where things are after install

```
<CH>/                         Claude configuration folder (CLAUDE_CONFIG_DIR, else ~/.claude)
  CLAUDE.md                   your user instructions; the installer adds one @import line to the kit's
  settings.json               your user settings (the chosen profile is merged in, never over managed keys)
  workbench/                  <WB>, everything the kit owns
    kit/                      <KIT>, the copy of this release: instructions, plugins, settings, tools, docs
    USER.md                   your work profile (/workbench-core:onboard fills it in)
    config.json               the interpreter, the knowledge-base root and other kit settings
    state/                    probe and setup state, logs, flags (safe to delete; rebuilt on demand)
    backups/                  a copy of every file the installer changed
<DATA>/                       your data folder: the work OneDrive's Workbench folder when exactly one work
                              OneDrive account exists, else a Workbench folder in your profile
  kb/                         the knowledge base (plain Markdown; never a git repository inside OneDrive)
  captured/                   captured pages, shared files, mail and meetings, kept beside the KB
  backup/                     dated backups of the KB and your profile
```

The installer's layout file under `bootstrap` is the authoritative list of runtime paths; uninstall removes only the
entries it marks removable and keeps your data. Runtime locations start with a token: `<CH>`, `<WB>`, `<KIT>` or `<DATA>`, as in the map above.

## 2. What lives where, and who wins

| Piece | Where it lives | Notes |
|---|---|---|
| Core instructions | `instructions/CLAUDE.md` and the rules it imports | Loaded every session. Keep them small: they are re-read on every call. |
| Read-on-demand rules | `instructions/rules/work-workflows.md` before fixing or reviewing repos, writing code, building UIs, making spreadsheets, decks or documents, or drafting replies; `instructions/rules/judgment.md` when a call feels ambiguous or no rule fires; `instructions/rules/model-profiles.md` when routing or writing a worker prompt; `instructions/rules/test-validity.md` before any gate or benchmark claim; `instructions/rules/corporate-setup.md` for setup steps | The core instructions point here instead of listing them. |
| Your profile | `templates/USER.md`, copied into the workbench folder as `USER.md` | Your preferences win over the shared working style. |
| Agents (personas) | `plugins/workbench-core/agents/` | One Markdown file each; model and effort are in the frontmatter. |
| Skills | `plugins/workbench-core/skills/` and `plugins/workbench-kb/` (see `plugins/workbench-core/README.md`) | `/workbench-core:<skill>`; Claude also picks one when its description fits. |
| Business skills | `plugins/workbench-biz/` | Portable to Claude web and desktop; catalog in `docs/business-catalog.md`. |
| Capture and ingest | `plugins/workbench-capture/` | Opt-in, user-invoked only; tell your security team before the first run. |
| How-to guides | `docs/howto/README.md` | Task recipes, read on demand; `find` searches them as the root `howto`. |
| Approver and coworker docs | `docs/security-overview.md`, `docs/known-limits.md`, `docs/troubleshooting.md`, `docs/rules-card.md`, `docs/runbooks.md` | What leaves the machine, what doesn't work yet, fixes by symptom, the rules on one page, incident and offboarding procedures. |
| Hooks and guards | `plugins/workbench-core/hooks/hooks.json`, `plugins/workbench-core/scripts/` | Guards live in two rule packs: `plugins/workbench-core/scripts/guards/rulepacks/generic.py` and `corporate.py`. |
| Settings profiles | `settings/profiles/` and `settings/SETTINGS.md` | `corporate` is the default; every key is explained in the guide. |
| MCP servers | `mcp/README.md` | A catalog, every entry off by default, each with where its data goes. |
| Knowledge base | `<DATA>/kb/` (or the root you chose) | Seeded from `kb-template/`. |

Precedence, highest first: organisation policy (managed settings, a managed instruction file, written policy) wins over
the Red Lines, then the Standing Orders, then the rules, then a project's own `CLAUDE.md`, then skills and agents, then
anything a plugin or MCP server injects. A contradiction inside one tier is a bug: fix the text. Settings follow the
same idea: managed settings are never overridden, and the installer refuses to write a key a managed source sets.

Your own skills, agents and hooks go in your user folder or a project's `.claude` folder, not in the kit copy: the next
release replaces the kit copy. `docs/AUTHORING.md` shows how to write and test each kind.

## 3. The working loop

1. **Understand, then act.** Read the task and the code it touches before choosing a fix. A bug fix is the root cause,
   found by looking at every caller of the thing you are about to change.
2. **Search the known failures first.** `kb-template/_shared/bug-cards.md` holds recurring failures with fixes;
   `repo-fix` and `investigate` search it before they look at code.
3. **Smallest change that fully solves it.** Reuse what exists, then the standard library, then a native feature, then
   a few lines of your own.
4. **Prove it.** A green check is not evidence; open the artifact. Section 6.
5. **An Office file leaving the organisation:** check its render (`office-render`), scrub a copy
   (`plugins/workbench-core/skills/office-render/scripts/scrub.py`), and send only the scrubbed copy.
6. **Big or risky work gets three roles:** a builder, an attacker on a different model, and a final verifier that
   gates. Section 4.
7. **Save before you stop.** Journal the state and write a handoff another session can execute. Section 7.

## 4. Spawning and model routing

- **Personas** are fixed by role so findings stay attributable: BLUE builds and gates (`flagship`, `blue-verify`,
  `security-auditor`), GREEN offers an independent alternative (`green-team`), RED attacks and never gates
  (`red-team`), and workers do the legwork (`general-purpose`, `implementer`, `researcher`, `ops-runner`).
  `sonnet-max` runs only when you ask for it.
- **Routing is data.** `docs/model-routing.md` lists, for each kind of work, the persona, the preference order of
  models and efforts, what never to use, and the evidence behind the row. Setup drops models your organisation does
  not allow and shows the five most common rows at session start. Opus and Sonnet run at high or xhigh only unless
  you name another effort.
- **Effort.** The Agent tool takes an `effort` parameter; use it only when you were told a level. Otherwise the persona's
  frontmatter decides. Lower effort on the same model is usually cheaper than switching model.
- **On "model not allowed", step down the preference order;** never retry the same model, and never route around the
  restriction.
- **Delegating:** the `spawn` skill is the action card. The prompt carries the goal, the owned files, the constraints,
  what is pre-authorised, the output shape and the stop conditions, because the worker starts with none of your
  context. Give each parallel worker its own worktree and disjoint files.
- **Fan-out etiquette:** waves of three or four; results written to files; stop launching after a usage-limit error;
  never land worker output without a review gate. The digest `kb-template/_shared/digests/orchestration.md` has the rest.

## 5. Token economy

- Context size is the big lever, because most spend is cache reads and writes. `docs/token-diet.md` has the free levers
  (`/clear` between unrelated tasks, `/compact` with what to keep, subagents for exploration, deliberate `/effort`) and
  which way each change moved cost.
- Keep always-loaded files small. A new rule costs a demotion elsewhere. The budget is checked by
  `py -3 tools/test_docs.py --budget`.
- Keep MCP servers off unless the task needs one, and keep tool search on.
- Brevity instructions are safe for code and wrong for explanations and runbooks; do not apply them there.
- Measure your own use (`/usage`, `/context`) before and after any change.

## 6. Testing discipline

- **Evidence over claims.** Open the output, run the command, call the endpoint as an outsider. `instructions/rules/verification.md`.
- **Test the test.** Every checker gets a bad fixture it must fail on, and every comparison gets a positive control.
  `instructions/rules/test-validity.md` is the checklist for any gate or benchmark claim.
- **Skips are failures** in an acceptance run: a missing dependency fails loudly, and the run reports what was skipped.
- **Heavy runs one at a time, memory-capped:** `tools/memcap/README.md`. Parallel suites freeze a laptop.
- **Read exit codes directly,** never through `| tail` or `| grep`.
- **Do not weaken a gate to pass it.** Fix the cause, or report the blocker by name.
- **One command runs every suite:** `tools/run_suites.py --require-all`, one suite at a time under the memory cap;
  a skip fails unless `tools/skips.allow` lists it with a reason.
- **Skill cost and configuration:** `tools/skill-bench/skill_bench.py` (`tools/skill-bench/README.md`) proves an arm
  was applied and measures cost; it never ranks quality, which rests on published benchmarks only.
- The digest `kb-template/_shared/digests/testing.md` collects the recurring traps.

## 7. Knowledge base, journal and save

- **Read path:** before a task, read the domain's `HOT.md` and `_shared/HOT.md`; go deeper with the KB search script
  (`kb_search.py "<terms>"`). A miss is not proof of absence; retry once with the note's own words.
- **Write path: journal, don't edit shared state.** After a significant response, add one line with `save_driver.py --inbox-add`.
  The in-flight file is rewritten only by the `save` skill (`/workbench-kb:save`), which merges under a lock.
- **Save is due after:** a file edited outside the KB, a root cause found, a decision a later session needs, a tracked
  number changed, a new credential *reference* (never a value), a non-obvious routing call.
- **One fact, one home.** Link to the note that owns a fact; keep old values as `SUPERSEDED` lines in the owner note.
- **Where it may live:** the work OneDrive is fine (its version history is the backup) but never as a git repository
  inside any OneDrive folder. `kb-template/README.md` has the folder taxonomy.
- **Digests and cards** in `kb-template/_shared/` are on-demand knowledge: six topic digests and the bug cards.

## 8. When something is blocked or broken

- A hook, permission or policy denial is a stop. Report it verbatim and use the matching ask-IT text in
  `docs/admin-asks.md`; continue with the work that is not blocked.
- Unattended runs and scheduled tasks: `docs/headless-and-scheduling.md`.
- Something fails: `docs/troubleshooting.md` (by symptom); every branch ends with
  `py -3 <KIT>/bootstrap/setup.py doctor`. Known gaps: `docs/known-limits.md`.
- An incident, a re-image or offboarding: `docs/runbooks.md`.
- Settings questions: `settings/SETTINGS.md`.
