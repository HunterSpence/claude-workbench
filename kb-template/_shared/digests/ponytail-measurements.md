---
title: Digest, ponytail measurements (what the coding rules save, and how to deliver them)
domain: _shared
status: active
---
# Ponytail measurements: what the coding rules save, and why the way they arrive decides it

Read this before switching ponytail on or off, before choosing how a build session gets the rules, and when someone
asks what ponytail saves. The rules themselves are the `ponytail` skill in `workbench-core`. The plain-text
alternative and the other token levers are in `docs/token-diet.md` and [[_shared/digests/models-and-tokens]]. The
same results with charts are chapter 8 of the explainer, `workbench-explainer.pdf` in this folder
([[_shared/digests/workbench-explainer]]).

## What the author publishes (vendor claim, one party)
- Version 5, the same agent in Claude Code with and without the skill, 39 tasks [S1] including a real FastAPI and React
  repository, Opus 5.5, 5 runs each: 53% less code, 41% less time, 26% lower cost and 45% fewer tokens [S1].
- The same page says 98% of risky logic shipped with a test, against 68% without the skill [S1]. Both are the author's
  own measurement until someone else repeats them.

## How this kit delivers the rules
- **Build agents:** `flagship` and `implementer` carry the full ruleset in their definitions, so a delegated build has
  it from its first token. That is the strong form in the table below.
- **Main session:** a hook injects the rules once, on the first edit of a code file or on a prompt with clear build
  intent, and re-arms after compaction. That is the weak form in the table below.
- **The upstream plugin** stays off by default (`settings/SETTINGS.md`), because the build personas already carry its
  text.

## Single answers with no tools (our runs, one party)
- Correctness never broke on code, bug-fix and reasoning answers under any ponytail level [M1]. Most of those tasks
  were easy for these models, so this rules out large breakage only.
- Explanations suffered: about an eighth of explanation answers lost a rubric point under ponytail, none without it
  [M1]. The sample could only detect a gap of about a sixth, so read it as a direction, not a measured effect.
- Cost did not fall on single answers: the mid-tier model's bill rose a few percent from extra thinking, and the top
  model was neutral [M1].

## Real agent sessions (our runs, one party)
- Twelve one-line tickets on a public full-stack web app template, half of them written to tempt over-building, run as
  real multi-turn sessions with the upstream plugin at `full`, two repetitions [M2].
- Session cost against no rules, with 90% intervals [M2]: Opus 5.5 at xhigh −53% [−63, −41], Sonnet 5.5 at high −23%
  [−34, −11] [M2].
- The saving comes from fewer turns (about half as many on Opus): a smaller diff means fewer tool calls and fewer
  re-reads of the context [M2]. On the plain create-read-update-delete tickets alone the saving was smaller [M2].
- Two blind judges found no measurable loss of completeness, but most sessions hit the top of the scale, so small
  losses are not ruled out [M2]. There were no security gaps. Agents wrote far fewer test lines, so ask for tests when
  they matter [M2].
- A short plain instruction (be brief, build only what is asked) matched ponytail on Opus and beat it on Sonnet, and it
  kept every explanation complete in the single-answer round [M1] [M2]. It was tuned on the same tasks, so its result
  is optimistic. Its text is in `docs/token-diet.md`, section 3.
- Sonnet 5.5 saves much more at xhigh than at high: about 0.48 of the no-rules cost against about 0.77 [M2] [M3].

## The way the rules arrive decides the saving (our runs, one party)
Session cost as a share of the no-rules cost on the same twelve tickets, both models at xhigh, with 90% intervals [M3]
(bootstrap over tickets) where measured; lower is cheaper [M3]:

| How the rules arrive | Opus 5.5 | Sonnet 5.5 |
|---|---|---|
| Rules in the system prompt plus a codebase map from a SessionStart hook [M3] | 0.36 [0.29, 0.46] | 0.41 [0.34, 0.51] |
| Rules present from the start, as in the build agents [M3] | 0.42 | 0.51 |
| Hook on the first read or write of a code file [M3] | 0.62 [0.53, 0.72] | 0.66 [0.57, 0.77] |
| Hook on the first write only, as in the main session [M3] | 0.85 [0.76, 0.94] | 0.96 [0.88, 1.05] |

- Rules a hook adds are weaker than the same rules in the system prompt, and the codebase map makes up most of the gap:
  the stock plugin with its map cost about 0.79 (Opus) and 0.84 (Sonnet) of the same plugin with the map off [M3].
- The upstream plugin (rules plus map) against the plain rules text: about 0.88 of the cost on Opus [M3] with fewer turns,
  a tie on Sonnet, quality equal [M3].
- Levels: `ultra` tied `full` on cost on both models, so `full` stays the default [M3]. The version 5 text tied the
  previous version's text on cost and completeness at about half the length [M3].
- An output style holding the rules bought nothing over the stock plugin [M4]. Claude Code sends an output style as
  per-request context, not as part of the system prompt.
- Completeness stayed at about 2.9 of 3 in every arm (two blind judges) [M3].

## What this means for this kit
- **Delegate build work.** A slice handed to `implementer` or `flagship` gets the strong form. The same work typed into
  the main session gets the weak form.
- **The main-session hook arrives late.** It fires on the first code write or a build-intent prompt, the weakest
  delivery measured. A trigger on the first read of a code file did better in the test harness [M3], but the harness
  blocked the shell tool, and code read through the shell never fires a read trigger. Measure on your own sessions
  before relying on one.
- **Keep it off explanations, runbooks and documents.** The skill is scoped to code because that is where it hurts.
- **Measure before you keep it.** `tools/skill-bench` checks that a rule was actually applied in every session and
  what it cost. A saving measured with the rule silently missing is not a saving.

## Measurements
- [M1] Single answers with tools off, every ponytail level and the plain block against no rules, two blind judges for explanations · corpus sixteen tasks: code with hidden executed tests, root-cause bug fixes, reasoning with exact answers, explanations · n=about eleven hundred graded answers · tier R0
- [M2] Agent sessions, the upstream plugin at full and the plain block against no rules, two blind judges · corpus twelve one-line tickets on a public full-stack web app template · n=about seventy valid sessions per model, two repetitions per ticket · tier R0
- [M3] Delivery, level and version arms against no rules, both models at xhigh, every session checked for the rule actually being applied · corpus the same twelve tickets · n=two repetitions per ticket per arm, a few hundred sessions in all · tier R0
- [M4] An output style holding the rules against the stock plugin, both models at xhigh · corpus the same twelve tickets · n=two repetitions per ticket · tier R0

## Sources
- [S1] ponytail repository README (version 5 benchmark and licence) · https://github.com/DietrichGebert/ponytail · fetched 2026-10-20
