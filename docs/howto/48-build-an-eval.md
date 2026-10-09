# Build an eval for a feature that calls Claude

Automates it: /claude-api build-eval and /claude-api hillclimb (the bundled claude-api skill)

## When to use
You are about to change a prompt, a model, an effort level or a skill in a product that calls Claude, and you want to know
whether the change helped, not just whether it looked fine on three examples. The `claude-api` skill builds the eval
inside your repository and then improves the product against it, one change at a time, with cases held back to catch
overfitting. Every eval run is a real model call on your plan or API bill. `<KIT>` is the kit folder (guide 01).

## Steps
1. Write down the question the eval answers ("does prompt B beat prompt A on refunds?", "does the skill trigger?") and the
   result you would act on. Evals answer one question each.
2. In Claude Code (2.1.259 or later), in the product's repository, run `/claude-api build-eval`. It interviews you, builds the eval in the
   repository and stops for your approval at set points. It takes inputs in this order: production transcripts (after
   asking about retention and sensitive data), bug reports and tickets, five to ten cases you write by hand, then cases
   synthesised from the code. Before it uses any real transcript or ticket, get the data owner's agreement and confirm
   your organisation allows that text to go to the model service; otherwise write the cases by hand.
3. Approve the inputs on the page it generates, one by one. Pick hard cases because a human can say why they are hard,
   not because today's model fails them.
4. Approve the grader. It proposes the cheapest one that fits: a code check when the output is constrained (exact match, a
   label from a fixed set, schema-valid JSON, passing tests), otherwise a second model with a rubric written as checkable
   claims. The judge must not be the model under test. Read a sample of scored transcripts and say which you would have
   scored differently.
5. Read the baseline summary before anything is changed: cases, repeats and models with a time estimate, then the score with
   a confidence interval. The skill also checks that the grader gives the same verdict twice on the same output, that there
   are no timeouts, errors or cut-off answers, and how far the baseline is from a perfect score.
6. Apply the kit's test-validity rule (`instructions/rules/test-validity.md`): a case that must fail has to fail, a pass
   needs a positive control, and a null result that fails an item is untested, not rejected.
7. Run `/claude-api hillclimb`, name the goal (quality, or cost while quality holds) and what it may change: the system
   prompt, skills or instruction files, tool descriptions, model and effort, or harness code. It splits the cases into a
   train set it may read and a test set it never sees, and it reverts a change that helps train but not test.
8. Read its report: the test-set result against the baseline with confidence intervals. If the gain is within noise it says
   so and recommends against merging; take that advice.

## Verify
- The baseline score has a confidence interval, the grader agreed with itself on a repeat, and the plumbing check found
  nothing.
- The strongest setting scores well below the top. A baseline of about 95 percent or higher leaves almost no room to
  improve quality: aim the climb at cost or latency instead.
- The final configuration beats the baseline on the held-out cases, not only on the train cases, and the report says by how
  much and how sure it is.
- You can say, for each hard case, why it is hard.

## Common failures
- **A case fails in every run:** the task is ambiguous or impossible, or the grader is wrong. Fix the case; do not keep it as
  "hard".
- **Train improves and test stays flat:** overfitting. Revert the change; do not paste failing transcripts into the prompt.
- **Scores jump between identical runs:** variance from an ambiguous grader, an effort setting that is not applied every
  time, or state left over from an earlier run. Add repeats or tighten the rubric before climbing.
- **The judge is the same model as the one under test:** pick a different judge.
- **The answers sit where the model can read them:** keep them out of its reach (a separate folder it has no tool for).
- **Evaluating a skill that ships in a plugin:** use `claude plugin eval` instead (Claude Code 2.1.269 or later; `claude
  plugin eval init` proposes the cases). It runs each prompt in an isolated session with and without the plugin, scores it,
  and exits non-zero below a threshold, so CI can gate on it.
- **A harness on a shared machine:** start Claude with `claude --restricted -p "<query>"` (2.1.248 or later). It removes the
  command-running tools and WebFetch unless you name them in `--tools`, confines the file tools to the working folder and
  loads only managed settings and `--settings`.
