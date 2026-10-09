# skill-bench

Measures what a skill costs and whether it was really applied, on neutral tasks, on any route that has the `claude`
command. It reports **cost and configuration**: tokens, the CLI's own list-price cost estimate, wall time, a per-run
arm proof, and an answer-key pass count used as a positive control. It never ranks model quality. Quality comparisons
between models come from published and third-party benchmarks (see `settings/model-evidence.json`); one output
directory holds one model on purpose.

```bash
py -3 tools/skill-bench/skill_bench.py selftest --pack smoke
py -3 tools/skill-bench/skill_bench.py run --runner mock --model m --arms baseline,terse --pack smoke --reps 6 --out <dir>
py -3 tools/skill-bench/skill_bench.py score --out <dir>            # --json for the machine form (also saved as score.json)
py -3 tools/skill-bench/skill_bench.py run --runner claude --model claude-haiku-5-5 --arms baseline --pack smoke --reps 1 --out <dir>
```

`run` resumes: finished runs are kept, so a rerun after a stop continues. Exit codes: 0 ok, 1 failed check or errored
runs, 2 usage or config error, 3 criteria changed since the run started (scoring aborts), 4 usage limit (stopped;
rerun to resume).

## Arms
An arm is `arms/<name>.md`, appended to the system prompt. `baseline` adds nothing. Put your own arm text (a skill's
output style, a short prompt alternative) in a file and pass `--arms-dir`. Every arm, baseline included, also gets one
trailer line of instruction whose code is the hash of the arm text, so arms differ only by their text.

## Arm proof
The reply must end with `[bench:<code>]` for that arm. A run without it is excluded and counted per arm, and an arm
with no proven run is reported as such. This catches a text that never reached the model. It costs about a dozen output
tokens on every arm. Components that are not system text (hooks, plugins) need their own proof: check their call
counters, not this trailer.

## Packs
`packs/<name>/` holds `tasks.json`, `keys.json` (answer keys with one good and one bad reference answer) and
`criteria.md` (the pre-registered analysis). The SHA-256 of those three files is stored when a run starts and checked
when scoring; a change aborts. `selftest` runs before every run: the good reference must pass and the bad one fail.
`smoke` is one short single-turn task, a wiring check only. It cannot say anything about multi-file or agentic work.

## Reading the report
Per arm: n, mean and a 95% t-interval for output tokens, total tokens, cost and wall time. Paired against baseline (same
task and repetition): the difference, its interval, the minimum detectable difference (80% power, two-sided 5%), and the
answer-key flips the arm caused. The verdict is `DETECTED` only when the interval excludes zero; otherwise `UNTESTED`
with the MDE. A null is never "no effect". Small n sees only large effects; a baseline at the answer-key floor or
ceiling is flagged. Before trusting a result, check it against the test-validity list: positive control, arm proof, power, strongest baseline.

## The claude runner
`claude -p --safe-mode --tools "" --strict-mcp-config --no-session-persistence --output-format json
--setting-sources project,local --model M --append-system-prompt TEXT`, the task on stdin, in an empty temporary
directory (all flags are listed by `claude --help`). Isolation comes from those flags alone. The kit never reads, copies
or writes a login file: the child uses your normal config dir and your current login. The one exception to the config
dir is a setup token you created yourself: when `CLAUDE_CODE_OAUTH_TOKEN` is set, the child gets an empty throwaway
config dir instead. API-key variables are removed from the child environment (`--keep-api-key` keeps them). User-level
settings are not loaded (`--setting-sources project,local`); a route configured only there needs the matching
environment variables instead. Usage counts once per message id. A quota, rate or overload reply stops the run
(exit 4). `SKILL_BENCH_CLAUDE` overrides the binary (a path or a JSON list), used by the tests.

Cost is the CLI's `total_cost_usd` (a list-price estimate from its own usage); on a plan that bills nothing per token,
read it as relative weight. Tests: `py -3 -m unittest discover -s tools/skill-bench` (offline, mock model).
