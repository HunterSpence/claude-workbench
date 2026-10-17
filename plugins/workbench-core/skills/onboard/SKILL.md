---
name: onboard
description: "Short interview that fills in USER.md (your work identity) and seeds the knowledge base."
disable-model-invocation: true
---

# /workbench-core:onboard

> Python: `${user_config.python}` is the interpreter chosen when the plugin was installed. If it
> appears unreplaced, use `py -3` on Windows and `python3` on Linux, macOS and WSL, never the
> Microsoft Store `python` stub.

Goal: a filled-in `<claude config dir>/workbench/USER.md` (imported into every session) and a few seed
lines in the knowledge base's `_shared/HOT.md`, in about five minutes.

## Rules for the interview
- **Work facts only.** Never ask for passwords, tokens, keys, one-time codes, home address, family,
  health, ID numbers or anything about the user's life outside work. If the user volunteers one, do
  not write it down, and say so.
- Ask in three short rounds, not one long form. Offer an example answer for each question; accept
  "skip" for anything. Do not guess an answer the user did not give.

## Round 1: who and when
1. What should I call you?
2. Your role and team?
3. Time zone and usual working hours?
4. Where do your organisation's rules for AI tools live (a link or a page name)?

## Round 2: how you work and write
5. How do you sign off, greet and sound in email and chat? Any phrases you never use?
6. Anything about how you like to work that differs from the kit's working style (answer length,
   what to ask before doing)?

## Round 3: repos, norms and limits
7. Which repos and tools do you use most (repos, languages, editor, ticketing, chat, CI)?
8. Review and merge norms: PR size, required approvals, who merges, branch naming, commit style?
9. What must I never do here (for example: push to main, comment on other teams' PRs, touch
   production, email customers)?

## Write it
Put the answers in a JSON file in your scratch folder (keys in the docstring of
`scripts/onboard.py`; lists for repos, tools, review norms, never-do items, work preferences and
facts), then preview and write:
```bash
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/onboard.py" --answers answers.json --dry-run
"${user_config.python}" "${CLAUDE_SKILL_DIR}/scripts/onboard.py" --answers answers.json
```
Show the user the preview before the real write. The script refuses credential-shaped answers,
copies the old USER.md to `workbench/backups/onboard-<stamp>/`, and replaces its own block in
`_shared/HOT.md` on a re-run. Delete the answers file afterwards.

## Then
- Tell the user USER.md loads at the next session start (or after `/clear`).
