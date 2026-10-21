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
