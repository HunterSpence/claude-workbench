# rules-quiz

Do your rules actually hold? Four everyday scenarios each tempt the assistant to break one rule from `docs/rules-card.md`. You
put each one to a fresh session that has your rules loaded, save the replies, and the tool grades them against expected patterns
(`docs/howto/51-check-that-skills-fire-and-rules-hold.md`).

```
py -3 <KIT>/tools/rules-quiz/rules_quiz.py list [--json]
py -3 <KIT>/tools/rules-quiz/rules_quiz.py grade --answers DIR [--json]
py -3 <KIT>/tools/rules-quiz/rules_quiz.py --self-test
```

- Offline: it never calls a model and never runs anything. `list` prints each scenario's id and prompt; save the reply to
  `DIR/<id>.txt`.
- A scenario passes when every `require` pattern is found in the reply and no `forbid` pattern is. Under nine of ten (all 4 of the 4)
  means reword the rule that failed; exit 1.
- The patterns are a coarse first filter. Read a failed reply before rewording a rule: it may be right in words the patterns do not
  know. The scenarios are in the script, each with its patterns beside its prompt.
- Output names the scenario, the rule it tests and the pattern numbers. Reply text is never printed.
- Exit 0 = rules hold, 1 = reword, 2 = unusable input.
