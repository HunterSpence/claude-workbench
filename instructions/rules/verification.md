# Verification and measurement

## Evidence
- **A green check is not evidence: verify the artifact.** HTTP 200 is not "done". A passing CI run
  says the checks passed, not that the change works.
- **0 tool calls = not research.** If you did not fetch or run it this session, you did not verify it.
- **Research first:** a current research pass shapes any build or improvement before code.
- **Replicate, then test, then test the test.** An adopt or reject decision cites published results
  with a replication tier (R0 author-only, R1 one independent, R2 two or more) AND our own run. Before
  you trust that run: reproduce a known result first (positive control), prove the change under test
  was actually applied, test the workload the technique claims to help, read exit codes directly
  (never through `| tail` or `| grep`), fail on silent skips, and count what the change broke, not
  only the average gain. A run that misses any of these is UNTESTED, not rejected and not passed.
  Full checklist, read before any gate or benchmark claim: `rules/test-validity.md`.
- **Label every claim** in a report VERIFIED (you checked it this session), PLAUSIBLE (consistent
  with what you saw, not checked) or ASSUMED.
- **"Public" means re-test unauthenticated**, from outside your own session.
- **"The page was empty" is a fact about your fetcher**, not about the page. Say which fetcher.
- **A 401 that names the caller's IP is an allowlist problem**, not a dead key.
- **A live screen beats vendor docs.** A dropdown can be the policy: test it live.
- **A quote or a landing page is not the product.** Read the individual listing or contract, not
  only the overview.
- Don't ship visual work unseen: the loop is in `rules/browser.md`.

## Measurement
- **Never rank inside the noise floor: report tiers.**
- **A gauge is not the system.** A metric that re-implements the rule it reports drifts silently.
- **A warning nobody may act on trains everyone to skip warnings**, including the ones that matter.
  If a check fires every session, fix the check or fix the rule.
- **Removing a real constraint is not removing the binding one.** Say which one you removed.
- **A diagnostic that asserts an unmeasured cause misdirects.** Name what you measured.

## Systems
- **Find the invariant first.** Hangs only under a service manager = environment, not code. Low CPU
  and death exactly at the timeout = blocked on I/O.
- **Config outside deploy control is a latent bug.** Never resolve drift by copying one side over
  the other: diff both ways first.
- **A rule that works only because nothing restarts is a latent outage.**
- **Before an irreversible step, read the shared journal** (the `save` skill's inbox). A later
  instruction from the user in another session beats an earlier approval in this one.
- **"Pushed OK" is not "pushed to the branch you restore from".** Check the branch and remote.

## Source tiers
**Published > in-ticket > researched = rumour.** Never present a researched date or number as a
vendor commitment.
