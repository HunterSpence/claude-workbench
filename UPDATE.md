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
   `https://raw.githubusercontent.com/<owner>/claude-workbench/7c75ee8b64fd29a37774dd983ef79c0c24be4f38/<path in the repo>`,
   where `<owner>/claude-workbench` is the GitHub repository you read this file from. If that URL answers 404, use `main`
   in place of the long commit id; the SHA-256 still decides. Keep a file only if its SHA-256 matches, then copy it to
   its place (create a missing folder). If a file with that name is already there with different bytes, don't
   overwrite it; report it. `kb_root` is in `%USERPROFILE%\.claude\workbench\config.json`.

   | Path in the repo | Copy it to | SHA-256 |
   |---|---|---|
   | `kb-template/_shared/digests/fable-5-2-routing.md` | `<kb_root>\_shared\digests\fable-5-2-routing.md` | `cb6a1473f654f2d1964b4dee904e066588d3133f3b7f57d6e90c0acb0281a46c` |
   | `plugins/workbench-core/skills/research/SKILL.md` | `%USERPROFILE%\.claude\skills\research\SKILL.md` | `3dd3bfb492edfbe76f29af2bf427534aaa23b8f20fc8fdb234ebbcf607b3ac10` |
   | `plugins/workbench-core/agents/searcher.md` | `%USERPROFILE%\.claude\agents\searcher.md` | `f3e6c565f410a10c94a75587585f67693723d84b7ca92f89f25b79752b7e7e2c` |

2. **Add one rule line.** In `%USERPROFILE%\.claude\workbench\instructions\rules\model-policy.md`, directly above the
   line that starts `- Fable 5.1 only when the user names it`, insert this one line, starting at the left margin with
   `- Web research` (keep the file's line endings):
   ```
   - Web research by tier (low, medium, high): the `research` skill; its `searcher` worker runs Sonnet xhigh, Fable 5.2 low only on a seat that includes Fable (KB note `_shared/digests/fable-5-2-routing`).
   ```
   If the `- Fable 5.1` line is missing, or a `- Web research by tier` line is already there, change nothing and report it.
3. **Leave the searcher on Sonnet 5.5 `xhigh`.** On this seat Fable 5.2 may bill usage credits. Tell the user: if `/model`
   shows the Fable 5.2 row without "Requires usage credits" (or an admin confirms the seat includes Fable) and they
   want Fable searchers, they can say "switch the searcher to Fable"; then change only the two lines that the comment in
   `searcher.md` names.
4. Run the find skill's `refresh --all`, so the new note is searchable.
5. **Report** what you changed, then tell the user to restart every Claude Code window.

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
