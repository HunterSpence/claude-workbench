# smoke pack: pre-registered criteria

Fixed before any run. The runner stores the SHA-256 of this file, `keys.json` and `tasks.json` when a run starts and
re-checks it when scoring; a difference aborts scoring.

## Purpose
A wiring check for the bench itself: one short, single-turn, tools-off task. It proves the runner starts, usage is
recorded, the arm text reached the model, and the scorer works. It says nothing about a skill's effect on real
multi-file or agentic work, so a result here is never evidence for such a claim (UNTESTED for that workload).

## Task
`primes-sum`: name the three smallest primes above twenty and add them up.

## Answer key (positive control)
A reply passes when every pattern in `all` matches (case-insensitive) and no pattern in `none` does. The key ships with
one reference answer that must pass and one that must fail; `skill_bench.py selftest` checks both before every run.
The pass count is a control that the pipeline works. It is not a model comparison.

## Measured (cost and configuration only)
- output tokens, total tokens (input, output, cache write, cache read), list-price cost reported by the CLI, wall time.
- `arm_applied` per run, from the trailer proof described in the README.
- the answer-key pass count per arm and, for paired runs, how many pairs the arm broke or fixed.

## Analysis
- Pairing: the same task and repetition under baseline and under the arm.
- Per arm and metric: n, mean and a 95% t-interval. Paired difference: mean, 95% t-interval, and the minimum
  detectable difference (80% power, two-sided 5%) from the observed spread.
- A paired difference is DETECTED only when its 95% interval excludes zero. Otherwise it is printed UNTESTED with the
  MDE; the bench never prints "no effect".
- A run without arm proof is excluded and counted per arm. An arm with no proven run is reported as such.

## Not produced
No ranking of models and no quality score. One output directory holds one model. Quality comparisons between models
come from published benchmarks (see `settings/model-evidence.json`).
