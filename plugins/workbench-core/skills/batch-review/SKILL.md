---
name: batch-review
description: "Run non-interactive Claude passes (reviews, judging, scoring, bulk document passes) through the Anthropic Message Batches API at half price, or fetch a msgbatch_ result. Needs a Console API key the organisation provides. Not for interactive work: batches take minutes to hours."
---

# batch-review

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it
> appears unreplaced (the skill was copied in without the plugin), use `py -3` on Windows and
> `python3` on Linux, macOS and WSL, never the Microsoft Store `python` stub.

`scripts/batch_review.py` submits prompts to the Message Batches API, polls, and prints results
with token usage. Batches cost half of live calls for input and output, so asynchronous work that
deserves the strongest model belongs here.

## Before you can use it
- **An API key is required.** It must be an Anthropic Console API key in `ANTHROPIC_API_KEY`. A
  Claude Team or Enterprise seat, or a Claude Code login, is NOT an API key. Your organisation must
  provide one (and may route it through an approved gateway: set `ANTHROPIC_BASE_URL`). Do not use
  a personal key for work data.
- Install the SDK: `"${user_config.python}" -m pip install --user -r "${CLAUDE_SKILL_DIR}/requirements.txt"`.
- Behind a TLS-inspecting proxy, point Python at the organisation's CA bundle
  (`SSL_CERT_FILE=<path to the corporate CA .pem>`) rather than disabling verification.
- Only send content your organisation allows to go to that API.

## Commands
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/batch_review.py" "prompt one" "prompt two"
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/batch_review.py" --file review-input.md --system-file reviewer.md
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/batch_review.py" --no-poll --file big.md        # prints a batch id
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/batch_review.py" --check msgbatch_...            # fetch later
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/batch_review.py" --model <model-id> --effort high --max-tokens 32000 "..."
```
`--model` takes a full model id (the Batches API does not resolve Claude Code's `opus`/`sonnet`
aliases). Default: `$BATCH_REVIEW_MODEL`, else the id in the script; check which models your key
can use. Results stay retrievable for at least a day.

## Judgment calls
- Output tokens dominate cost, and effort drives output. Use `high` by default, lower for routine
  passes, the top level only when correctness really matters.
- Best-of-N for high-stakes one-shots: generate N candidates live with a faster model, then submit
  ONE batched judge prompt containing all of them; the judge scores, it does not generate.
- Batches usually finish in minutes but may take up to 24 hours. Need the answer in this session:
  poll (the default). Overnight work: `--no-poll` and write the batch id where the follow-up will
  look (the task notes or the knowledge base journal).
