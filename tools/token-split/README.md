# token-split

Shows where the spend in your own Claude Code sessions goes: uncached input, cache writes, cache reads, thinking, prose and
tool-call arguments. Context size is usually the big lever, and this puts a number on it before you change anything
(`docs/token-diet.md`, `docs/howto/11-keep-token-use-low.md`).

```
py -3 <KIT>/tools/token-split/token_split.py [--days 14] [--projects DIR] [--prices FILE] [--json]
py -3 <KIT>/tools/token-split/token_split.py startup [--json] [--timeout 180]
py -3 <KIT>/tools/token-split/token_split.py --self-test
```

- Reads only the usage fields of each assistant message and the character count of its text and tool-call blocks, from
  `<CH>/projects/**/*.jsonl`. It never prints, stores or sends text, tool arguments, paths or folder names.
- Claude Code repeats the usage on every content block of a message, so usage is taken as the maximum per message id.
- Visible output is split into prose and tool-call arguments by character share. Thinking tokens come from the transcript's
  thinking count when it has one; otherwise the report says so.
- Prices come from the `prices` key of `settings/model-evidence.json`, the one home for them (rendered in `docs/models.md`,
  checked against `docs/token-diet.md` by `tools/test_models_doc.py`). A model that table does not list is counted and
  named, never priced at another model's rate. Add it to the table, with its vendor evidence row, to price it.
- The total is what the same tokens would cost at the vendor's API rates. It is not your bill.

Exit 0 on a report, 2 when the transcript folder or the price table is unusable.

## `startup`: how big is the context before you type?

The report above prices what you already spent. `startup` measures what every new session costs before your first word:
it runs `claude -p --output-format json` twice on one fixed trivial prompt, once with your current settings and once with
`--safe-mode` (CLAUDE.md files, skills, plugins, hooks, MCP servers and the rest switched off; your organisation's managed
settings still apply), and prints the prompt tokens of each and the difference.

```
startup context, one headless turn on a fixed prompt (tokens)
                       input  cache write   cache read   context
  current settings         3       40,000            0    40,003
  --safe-mode              3          100       14,900    15,003
  difference                                            25,000   <- what your customisations add before you type
```

(The numbers above are made up.) How to read it:

- **Compare the `context` column,** which is input + cache write + cache read: the whole prompt the model was sent. A prefix
  that an earlier run cached is billed as a cache read instead of fresh input, and the second run can reuse the first
  run's cached prefix, so the first two columns alone move around between runs and would overstate the difference.
- **The difference is the cost of your customisations at the start of every session:** the instruction files, the skill
  listing, hook and plugin text, and the tool descriptions of the servers that load at startup. The `--safe-mode` row is the
  floor Claude Code itself costs with your account's policy.
- **Run it from the folder where you normally start Claude Code:** project instructions and project servers count as yours.
- **Change one thing, run it again.** The same command before and after a settings change is the measurement; one number on
  its own says little. Two runs of the same settings can differ slightly (the date, folder and git state are part of the prompt).
- **It makes two real model calls with your own sign-in,** each sending the opening context once, so it costs about what
  opening two sessions costs. Nothing is read from or written to your transcripts, and the reply text is never printed or kept.
- **A negative difference** means the current-settings run came out smaller than the `--safe-mode` run. That should not
  happen: the table and the JSON both say so; run it again, and if it repeats do not rely on the number.
- **Each call is limited to one turn** (`--max-turns 1`). If the model chose to call a tool, Claude Code ends the call as
  `error_max_turns` (exit 1, `is_error` true, two turns counted on 2.1.295). The usage is still read and the table says the run
  stopped at the limit and that the numbers are not the opening context alone, so run it again.
- **`--timeout` (180 seconds per call) stops the call and everything it started,** also behind the `.cmd` launcher that npm
  installs for Claude Code. A `claude --help` that never answers ends the command with "timed out", not with a claim that
  the flag is missing.
- Exit 2 when `claude` is missing, a call fails or times out, or this Claude Code does not list `--safe-mode` (the
  current-settings row is still printed).
