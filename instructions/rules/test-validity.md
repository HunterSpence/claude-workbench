# Test-validity checklist (test the test before trusting a pass or a null)

Read this before any adopt or reject decision, any gate, and any benchmark claim. A null result
that fails an item is UNTESTED, not a rejection. A pass that fails an item is not evidence.
This file is read on demand; it is not imported into every session.

## Before the run
1. **Published evidence and its replication tier.** R0 author-run only, R1 one independent
   replication, R2 two or more. Vendor benchmarks count as R0.
2. **Positive control first.** Reproduce the published effect on its own benchmark and config
   before testing on your data. If the control fails, audit the harness before concluding anything.
3. **Workload match.** The test must include the workload the technique claims to help. A tool for
   multi-file agentic work tested on single-turn toy tasks with tools off proves nothing.
4. **Power.** State the minimum detectable effect from a pilot's real paired spread. Flag ceiling
   and floor effects (a baseline within a few points of the bound). A small split can only see
   large effects; say how large.
5. **Strongest baseline.** Compare against the strongest plausible version of the alternative, plus
   the published number. Never a weak baseline alone.

## During the run
6. **Prove the arm was applied.** Read component identity from the live objects, check that call
   counters are non-zero, and check that the settings dump matches the live objects. Arms get
   silently dropped by hook timeouts, plugin fallbacks and wrong defaults.
7. **No silent skips or defaults.** Fail the run on undeclared skips. Pass every case explicitly;
   a CLI default can leave a case out of the suite.
8. **Read exit codes directly.** Never through `| tail`, `| head` or `| grep`, which replace the exit
   code with their own.
9. **Test at the boundary where the bug lives.** A same-process test cannot reproduce a
   cross-process bug such as lock contention between many processes.
10. **Quiet machine for timing.** A latency run on a loaded machine is invalid: rerun it, never count it.

## After the run
11. **Calibrated statistics.** Percentile bootstraps under-cover at small or sparse n. Use a
    calibrated interval and a sign-flip or split-half null on real differences. A byte-identical
    rerun proves determinism, not power.
12. **Separate confounded arms.** Ablate: when two changes ship together, measure each alone.
13. **Check for benchmark artefacts.** Use a fresh holdout disjoint by id and by text, per-type
    splits, and a non-templated set (a gain can be template fitting).
14. **Negative flips.** Count the cases the change broke, not only the average gain.
15. **Re-measure on current code.** A documented limitation may already be fixed.
