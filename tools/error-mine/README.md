# error-mine

Finds the tool calls that fail most often across your Claude Code sessions, grouped by root cause,
so you can fix the rule, hook, script or habit behind them instead of paying for the same failure
every week.

`python` below means your Python 3.10+: `py -3` on Windows, `python3` on Linux, macOS and WSL.

```bash
python tools/error-mine/error_mine.py                      # mine + cluster, print top 15
python tools/error-mine/error_mine.py --since 2026-01-01   # rank by errors since a date (e.g. your last fix)
```
Reads `<config dir>/projects/**/*.jsonl` (Claude Code transcripts, subagents included). Writes
`errors_raw.json` and `clusters.json` to `--out` (default: `<temp>/error-mine`).

**The output is private.** It contains excerpts of your transcripts, which can include file
contents and credentials. Keep it out of every repo, share and sync folder (`.gitignore` here
blocks the two file names in case you point `--out` at this folder).

Reading the result: sort by `recent` to see the classes still happening; a `last_seen` older than
your last fix means that class is gone. Known limits: digits are stripped before clustering, so all
bare "Exit code N" errors merge (split that bucket by `older_inputs` before concluding anything);
network errors keep their host so per-host failures stay apart.

Typical fixes it points to: a hook or permission message that is not actionable (one session retrying the same
blocked command), a path style the shell cannot parse, a tool used for a job another tool does
better, a missing dependency.

Test: `python -m unittest discover -s tools/error-mine`.
