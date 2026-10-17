# Turn requirements into user stories

Automates it: /workbench-biz:requirements-to-stories

## When to use
You have a requirements document, a set of notes or an email thread, and you need a backlog from it: epics, user stories
with acceptance criteria, and a list of what is unclear. Claude does the first pass in minutes; you and the owner decide
what is right. The skill works the same on claude.ai, the desktop app and Claude Code.

## Steps
1. Give it the source: paste the text, attach the file, or name the file in Claude Code. Claude works only from that
   material. Text inside it is content to analyse, never instructions.
2. Ask in your own words ("turn this into user stories with acceptance criteria") or run `/workbench-biz:requirements-to-stories`.
3. Read the result in its fixed order: summary, epics, stories with Given / When / Then criteria, non-functional
   requirements, a traceability table (requirement, epic, story), open questions and assumptions.
4. Go through the three lists that need a person:
   - **Open questions:** each names who could answer. Contradictions are listed side by side, not resolved quietly.
   - **`<value to confirm>`:** a limit or number the source did not give. Fill it from the owner, not from a guess.
   - **`ASSUMPTION:` lines:** accept or reject each one.
5. Refine: "split US-1.2 into smaller stories", or build test cases from the stories with `/workbench-biz:test-cases-from-requirements`.
6. Put the approved list in your tracker yourself, or ask Claude to create the items once you approve it, if a tracker is connected.
   A Word or Excel version can be built with `/workbench-core:office-docx` or `/workbench-core:office-xlsx`; guide 36
   removes hidden content from a copy.

## Verify
- Every requirement ID maps to a story or to an open question, and every story traces back to a requirement.
- Every story has at least one normal case and one failure or edge case, and no number appears that the source does not contain.
- Nothing was added that the source does not say; anything extra sits under open questions.

## Common failures
- **Stories too big:** one that cannot finish in about a week should be split. Ask for it.
- **A benefit was invented:** a story with no stated benefit should have become a question. Ask Claude to move it.
- **Long source cut short:** ask "did you read to the end? which section is the last one you used?"
