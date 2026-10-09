# skill-probe

Does a skill start when it should and stay quiet when it should not? Write the prompts that should start it and the near misses
that should not as patterns; the tool reads your existing transcripts and counts how often each kind was followed by a `Skill`
tool call for that skill (`docs/howto/51-check-that-skills-fire-and-rules-hold.md`).

```
py -3 <KIT>/tools/skill-probe/skill_probe.py --spec probe.json [--transcripts DIR] [--json]
py -3 <KIT>/tools/skill-probe/skill_probe.py --kit [--transcripts DIR] [--json]
py -3 <KIT>/tools/skill-probe/skill_probe.py --self-test
```

`--kit` is the shortcut for the kit's own cases, `probe.kit.json` in this folder: 5 should and 5 should-not patterns for each
kit skill that carries a `when_to_use` line, plus one example prompt per pattern (the kit's tests check each pattern against its
example; the tool ignores the examples). Use Claude Code normally for a while, then run it: a skill under 80 percent on its
should side, or over 20 percent on its should-not side, needs its description reworded. For a skill that ships in a plugin,
`claude plugin eval` is the vendor's own check (it runs each prompt with and without the plugin; `docs/howto/51-check-that-skills-fire-and-rules-hold.md`).

`probe.json`:

```json
{"version": 1, "skills": {"diagram": {"should": ["draw a (diagram|flowchart)"], "should_not": ["what is a flowchart"]}}}
```

- Offline: it never calls a model. Only a `Skill` tool call counts; a Read of the skill file, a Bash command or a subagent task that
  mentions the skill does not. A skill you started with a slash command is not a model decision and is not counted.
- Output is counts, rates and prompt ids. Prompt text is never printed. Under 5 matching prompts there is no verdict.
- Verdict floor and ceiling: at least 80 percent of "should" prompts fire the skill, at most 20 percent of "should_not" prompts do.
- Exit 0 = report printed, 2 = unusable input (bad spec, no transcripts).
