---
title: Digest, testing and evaluation
domain: _shared
status: active
---
# Testing and evaluation: lessons that keep recurring

Read this before writing a test, a gate or a benchmark, and before believing a result. The full checklist for any adopt
or reject call is `<WB>/kit/instructions/rules/test-validity.md`.

## Evidence
- **A green check is not evidence; the artifact is.** A success response is not "done". Open the output, read the file,
  call the endpoint as an outsider.
- **Test the test.** Give each checker a bad fixture and watch it fail: a missing path, an oversized set, a row with no
  evidence. A check that has never failed has never been shown to work.
- **Every test needs a positive control and a negative control.** If the positive control also matches the allowlist,
  it proves nothing.
- **Skips are failures in an acceptance run.** A missing dependency must fail loudly (an environment flag turns skips
  into failures) and the run prints how many tests were skipped and why.
- **Integration tests that skip when a connection string is unset let a broken query ship.** In CI an unset prerequisite
  is a failure.
- **Never retry until green.** A flaky test gets an owner, a cause and an expiry; a retry loop hides the next real
  failure.
- **A quiet service needs a synthetic soak after a deploy.** When real traffic is rare, a watch window with no failures
  proves nothing: send scripted requests through the changed path for the whole window.
- **A browser probe clears any interstitial first** (a consent or sign-in notice), or it tests the notice instead of
  the page.

## Designing fixtures
- **Build secret-shaped fixtures at run time** so the scanner you test does not flag the test.
- **Inject the clock.** Tests for dates need a zone far from UTC and a daylight-saving transition day.
- **Dependent behaviour needs separate processes.** A same-process determinism check misses hash-seed effects and float
  ties; run the comparison in two processes.
- **Wait for a condition, not for the network to go quiet.** Pages with polling scripts never reach network-idle.
- **Use the identity provider's official test path** for end-to-end sign-in; forging cookies re-implements an
  undocumented handshake that changes underneath you.
- **Mock at the lowest level.** Patch the client constructor or its transport, not the wrapper the code calls:
  patching the wrapper leaves a response-parsing bug green.

## Benchmarks and judges
- **An arm that is silently not applied is a second baseline.** Always run a no-treatment control and prove the
  treatment was injected in every session (log it).
- **A golden set edited by the system under test, or after anyone saw results, is invalid.** Freeze it before the
  run and discard any run that changed it.
- **Pre-register the criteria and blind the judge.** Decide the rubric before the output exists; judges should not see
  which arm produced what.
- **Judges that are models under test need calibration against a human sample,** and a ceiling (nearly every item
  passes) means the task cannot rank anything.
- **A judge that sees only a diff flags reused dependencies as missing.** Give it the repository's existing dependency
  list and conventions.
- **Never rank inside the noise.** Report tiers, sample sizes and the smallest effect you could have detected; an
  untested claim is "untested", not "no effect".
- **Answer-level verdicts on a small sample flip when the same questions are read again.** Keep deterministic
  measures primary and report the re-read disagreement as the noise floor (method: the `retrieval-eval-method` digest).
- **Replication tier matters.** One party measured it (R0), one independent replication (R1), two or more (R2); vendor
  numbers are R0 until someone else reproduces them.
- **Keep spend and personal context out of published results.** Publish direction, sample size, tier and month.

## Running suites
- **Run heavy suites one at a time, under a memory cap.** Parallel model or test jobs freeze a laptop.
- **Measure with the same launcher the real run uses,** not an interactive shell, or you test a different environment.
