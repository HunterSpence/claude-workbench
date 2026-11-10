# Manual update to 0.3.6 (no updater)

For a machine that runs 0.3.5 and must keep its own settings untouched. Claude: do these steps yourself, in order.

## Rules
- Do NOT run the kit's updater, installer or setup, and do not "check the new stuff".
- Change only what is listed here. Every other setting, rule, hook, skill and plugin stays exactly as it is.
- Read each command's output before the next step. On a failure, a hash mismatch or a company-policy block: stop and report it. Never work around a block.

## Steps
0. **Back up and report.** Copy `%USERPROFILE%\.claude\settings.json` to `settings.json.bak-0.3.6` beside it. Report:
   - the output of `claude --version`, `node -v`, `git --version` and `claude plugin list`;
   - `kb_root` from `%USERPROFILE%\.claude\workbench\config.json`.
1. **Add four knowledge-base files.** Download each one into `<kb_root>\_shared\digests\` from
   `https://raw.githubusercontent.com/<owner>/claude-workbench/v0.3.6/kb-template/_shared/digests/<file>`, where
   `<owner>/claude-workbench` is the GitHub repository you read this file from.
   Keep a file only if its SHA-256 matches. If a file with that name already exists with different bytes, don't overwrite it; report it.

   | File | SHA-256 |
   |---|---|
   | `workbench-explainer.pdf` | `8a9464ccf9b5b80fce976334ede992c3d1053625c4bb44cdecc70a4268d3c238` |
   | `workbench-poster.pdf` | `13ad82111241d7f259b1e96b669e1dfaa914af9ce03100b59085fba2446ea8ef` |
   | `workbench-explainer.md` | `193c0eb51cc305d873bfe889d900df4d029ca4789fb19bea68f7c53f67accb67` |
   | `ponytail-measurements.md` | `1b3b29103c15ea5b5653706ba3f74e5caacdf1b9486502c6ff32f07e799abe38` |

   Then run the find skill's `refresh --all`, so both PDFs become searchable.
2. **Turn on the ponytail plugin** (with its codebase map, it measured cheapest; see `ponytail-measurements.md`). It needs `node` and `git` on PATH and Claude Code 2.1.290 or later.
   - `claude plugin marketplace add DietrichGebert/ponytail`. Use only this source; never a fork, a mirror or a search result.
   - `claude plugin install ponytail@ponytail`
   - `claude plugin list` must show ponytail 5.3 or later.
   Keep its defaults: level `full`, map on, webhook empty. Create no config file and do not set `PONYTAIL_DEFAULT_MODE`.
3. **Add one setting.** It stops `flagship` and `implementer`, which already carry the rules, from getting them twice. In `settings.json`, under `"env"`, add exactly:
   `"PONYTAIL_SUBAGENT_MATCHER": "^(?!(workbench-core:)?(flagship|implementer)$)"`
   Add only that key. If the key already exists with a different value, stop and report.
4. **Report** what you changed, then tell the user to restart every Claude Code window.

## Check after the restart
When the user says "check UPDATE.md", work inside a git repo that has code:
1. Confirm the four files above are in `_shared/digests`.
2. Run find for "what does ponytail save" and show the citations.
3. Without tools, answer in three lines: is a ruleset called ponytail active, and at which level; the exact comment prefix your instructions give for a shortcut; does your context include a section titled Codebase map?

   Expected answers: active, full · `shortcut: <the limit>, <when to upgrade>` · yes.

## Meaning-search model (when huggingface.co is blocked)
When the user says "do the model section of UPDATE.md". The same rules apply.
1. Download `https://raw.githubusercontent.com/<owner>/claude-workbench/main/models/find-embedding-model.zip` (about 61 MB) into a temporary folder outside the knowledge base. If that host is blocked, the same file is at `https://github.com/<owner>/claude-workbench/releases/download/v0.3.5/find-embedding-model.zip`.
   Keep it only if its SHA-256 is `89e377c937af56f0f7590cc73305e3bd59a4b871fe7c6b7b4d6726d4d0f75719`.
2. Run the find skill's CLI (`doc_index.py`) the way its SKILL.md says: `model import <the zip>` (it checks every file against the pins in the script; no network), then `embed`.
   If `embed` reports a missing package, stop and report it.
3. Run `status`. Success is `mode hybrid` with more than 0 vectors. A `note:` line saying a huggingface.co download failed is left over from before the import: ignore it.
4. End with exactly one line, short enough for the user to retype elsewhere:
   `MODEL download=<ok, or the blocked host> import=<ok, or the error in a few words> mode=<hybrid or keyword> vectors=<number>`
   The zip can be deleted afterwards.

## Research tiers and Fable 5.2 notes (2026-11-10)
When the user says "do the 2026-11-10 section of UPDATE.md". The Rules at the top apply: no updater, change only what is
listed, and stop and report on a failure, a hash mismatch or a company-policy block. This adds one knowledge-base note,
one skill, one agent and one rule line.
1. **Download three files** into a temporary folder outside the knowledge base, from
   `https://raw.githubusercontent.com/<owner>/claude-workbench/e7dfc19ce2e57ccb489ec39c508fbf7b7f817679/<path in the repo>`,
   where `<owner>/claude-workbench` is the GitHub repository you read this file from. If that URL answers 404, use `main`
   in place of the long commit id; the SHA-256 still decides. Keep a file only if its SHA-256 matches, then copy it to
   its place (create a missing folder). If a file with that name is already there with different bytes, don't
   overwrite it; report it. `kb_root` is in `%USERPROFILE%\.claude\workbench\config.json`.

   | Path in the repo | Copy it to | SHA-256 |
   |---|---|---|
   | `kb-template/_shared/digests/fable-5-2-routing.md` | `<kb_root>\_shared\digests\fable-5-2-routing.md` | `8cb7c33fb622b4355c419437ee59c0ead50d18913992f30b0815f6113399629d` |
   | `plugins/workbench-core/skills/research/SKILL.md` | `%USERPROFILE%\.claude\skills\research\SKILL.md` | `3dd3bfb492edfbe76f29af2bf427534aaa23b8f20fc8fdb234ebbcf607b3ac10` |
   | `plugins/workbench-core/agents/searcher.md` | `%USERPROFILE%\.claude\agents\searcher.md` | `308eb064a5290a9944ecfbb1cfc172d34f0c2741b4377d8b99467dce5d870c61` |

2. **Add one rule line.** First copy that file to `model-policy.md.bak-2026-11-10` beside it (rules load by name, so the
   copy is never read). Then in `%USERPROFILE%\.claude\workbench\instructions\rules\model-policy.md`, directly above the
   line that starts `- Fable 5.1 only when the user names it`, insert this one line, starting at the left margin with
   `- Web research` (keep the file's line endings):
   ```
   - Web research by tier (low, medium, high): the `research` skill; its `searcher` worker runs Sonnet xhigh, Fable 5.2 low only on a seat that includes Fable (KB note `_shared/digests/fable-5-2-routing`).
   ```
   If the `- Fable 5.1` line is missing, or a `- Web research by tier` line is already there, change nothing and report it.
3. **Leave the searcher on Sonnet 5.5 `xhigh`.** On this seat Fable 5.2 may bill usage credits. Tell the user: if `/model`
   shows the Fable 5.2 row without "Requires usage credits" (or an admin confirms the seat includes Fable) and they
   want Fable searchers, they can say "switch the searcher to Fable"; then change only the two header lines that the
   **Model switch** note at the top of `searcher.md` names.
4. Run the find skill's `refresh --all`, so the new note is searchable.
5. **Report** what you changed, then tell the user to restart every Claude Code window.

To undo: restore `model-policy.md.bak-2026-11-10` and delete the three files copied in step 1.

A later kit release ships the skill and the agent inside the workbench-core plugin. When this machine gets that
release, delete the two copies added in step 1 under `%USERPROFILE%\.claude\skills\research` and
`%USERPROFILE%\.claude\agents\searcher.md`, so each exists once.

### Check after the restart
When the user says "check the 2026-11-10 section of UPDATE.md":
1. Run find for "which effort should Fable 5.2 run at for web search" and show the citations; `fable-5-2-routing.md`
   should be in the top three.
2. Confirm that a skill named `research` is in your skill list and an agent named `searcher` is available.
3. Spawn `searcher` once with: "Which Claude Code version first supports Claude Fable 5.2? One fact, one source." Its
   reply must start with `Model: claude-sonnet-5-5` (or `claude-fable-5-2` if the user switched it) and cite a URL.
4. End with exactly one line, short enough for the user to retype elsewhere:
   `RESEARCH digest=<ok or missing> find=<rank or miss> skill=<ok or missing> searcher=<model id or the error> rule=<ok or skipped>`

## 2026-11-10 (part 2): Fable effort, Fable lanes, no headless Fable
When the user says "do the 2026-11-10 part 2 section of UPDATE.md". The Rules at the top apply: no updater, change only
what is listed, and stop and report on a failure or a company-policy block. This sets one effort level, may repoint one
model alias and adds two rule lines. Running it again changes nothing the first run did.
0. **Part 1 first.** Open `%USERPROFILE%\.claude\workbench\instructions\rules\model-policy.md`. If no line in it starts
   with `- Web research by tier`, the "Research tiers and Fable 5.2 notes (2026-11-10)" section above has not run: do
   that section now (the user restarts once, at the end of this one), then come back here. If it stops on a failure or
   skips its rule line, report that and go on; step 3 says where the lines go then.
1. **Back up and report.** Copy `%USERPROFILE%\.claude\settings.json` to `settings.json.bak-2026-11-10-part2` and that
   `model-policy.md` to `model-policy.md.bak-2026-11-10-part2`, each beside its file. If a backup with that name is
   already there, keep it and copy nothing (it holds the state before the first run). Report `claude --version`.
2. **Two settings.** In `%USERPROFILE%\.claude\settings.json`, edit the text in place (keep its formatting and line
   endings; never rewrite the whole file) and change nothing else:
   - `env.ANTHROPIC_DEFAULT_FABLE_MODEL`: if it is exactly `claude-fable-5-1`, change it to `claude-fable-5-2`, but
     only when `claude --version` is 2.1.321 or later (Fable 5.2 needs it). On an older version leave it, and tell the
     user to run `claude update` (or ask IT if the version is pinned), then this section again. If the key is absent,
     leave it absent; if it is already `claude-fable-5-2`, leave it; if it holds any other value, leave it and report it.
   - `modelSettings."claude-fable-5-2".effortLevel`: set it to `high` (Claude Code's own default for Fable 5.2 is
     `medium`). If `modelSettings` exists, add or change only that entry and keep any other key the entry has; if
     `modelSettings` is absent, add `"modelSettings": {"claude-fable-5-2": {"effortLevel": "high"}}` at the top level.

   Then read the file back with a JSON parser; if it does not parse, restore the backup and stop. A managed
   (organisation) setting for the same key wins: report it, never work around it.
3. **Two rule lines.** Insert the `- Fable 5.2 lanes` line only if `claude --version` is 2.1.321 or later,
   `env.ANTHROPIC_DEFAULT_FABLE_MODEL` is now `claude-fable-5-2` or absent, `ANTHROPIC_BASE_URL` is unset, and the user
   answers yes to "Does `/model` show Fable 5.2 without 'Requires usage credits', or has an admin confirmed your seat
   includes Fable?" Otherwise insert only the headless line and report `lanes skipped:<reason>`. In that `model-policy.md`, directly below the line that starts `- Web research by tier` (if that
   line is missing, directly above the line that starts `- Fable 5.1 only when the user names it`), insert these two
   lines, each starting at the left margin with `- ` (keep the file's line endings):
   ```
   - Fable 5.2 lanes (Agent `model: fable` with that `effort`), only on a seat that includes Fable (`/model` shows its row without "Requires usage credits", or an admin confirms): medium for hard closed-book questions, 3+ per spawn; low for chart or figure reading and fact cross-checks; high for `flagship` after an Opus build failed. These levels count as user-named. Never security, biology, medical, legal or tax: those stay on Opus xhigh citing primary sources.
   - Never start a headless `claude -p` or SDK run on a Fable model without the user's go for that run: where Fable would bill usage credits (a seat without Fable, or past its Fable cap), a headless run bills them without asking.
   ```
   A line whose start (`- Fable 5.2 lanes` or `- Never start a headless`) is already in the file is skipped, not
   doubled; report it. If neither anchor line is there, change nothing and report it.
4. **Report** what you changed and what you skipped (and why), then tell the user to restart every Claude Code window.

On a seat without Fable, step 3 leaves the lanes line out; run this section again once it includes Fable.

To undo: copy each `.bak-2026-11-10-part2` file back over the file beside it (this undoes part 2 only, and also drops
any setting changed since), or reverse by hand the edits your report lists.

### Check after the restart
When the user says "check the 2026-11-10 part 2 section of UPDATE.md":
1. Read `%USERPROFILE%\.claude\settings.json` and report `env.ANTHROPIC_DEFAULT_FABLE_MODEL` (its value, or absent) and
   `modelSettings."claude-fable-5-2".effortLevel`.
2. Without tools, answer from your instructions in one line: the effort of the Fable 5.2 lane for chart reading, and
   whether you may start `claude -p` on a Fable model without the user's go. Expected: `low` · no.
3. Run `claude --version`.
4. End with exactly one line, short enough for the user to retype elsewhere:
   `FABLE2 settings=<ok or skipped:reason> lanes=<ok or skipped> headless=<ok or skipped> cc=<version>`
   `settings=ok` means the effort is `high` and the alias is `claude-fable-5-2` or absent; `lanes=ok` and
   `headless=ok` mean that line is in `model-policy.md` and your step 2 answer matched.
