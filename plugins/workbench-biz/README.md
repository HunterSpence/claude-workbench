# workbench-biz

Eight business skills that work the same on claude.ai, the desktop app and Claude Code. They are plain instructions:
no scripts, no hooks, no servers, no settings, no network. Installed by default with the workbench; IT can still
allow or deny the plugin on its own.

| Skill | What it produces | Needs for full value |
|---|---|---|
| `requirements-to-stories` | Epics, INVEST stories, Given/When/Then, traceability, open questions | Nothing |
| `meeting-to-actions` | Decisions, actions with owners, risks, follow-up email draft | Nothing |
| `status-report` | One-page RAG report in a fixed format | Nothing |
| `test-cases-from-requirements` | Test case matrix, Gherkin, coverage map | Nothing |
| `excel-analyst` | Profile, cleaning log, findings, checks | Code execution and file upload for real files |
| `rfp-sow-drafter` | RFP response grid or SOW skeleton; prices left as placeholders | Nothing |
| `branded-deck` | Slide-by-slide build spec, or the deck | File creation for the .pptx |
| `policy-qa` | Cited answers, or "not found" | Documents attached or a knowledge connector |

## Where it loads

| Surface | Loads | How |
|---|---|---|
| Claude Code (terminal) | yes | `claude plugin install workbench-biz@workbench`, done by the workbench installer |
| Claude desktop | yes | same plugin |
| claude.ai chat | yes, as skills | one zip per skill: `package_web.py <skill folder> --out <zip>` (workbench-core, web-packager), then upload where your organisation allows custom skills |

The portability check (`package_web.py --check`) proves the upload rules are met: six frontmatter fields only,
description of 250 characters or fewer, no `bin/`, hooks, stdio servers or user settings. It does not prove how a
hosted product will behave, so treat web behaviour as the vendor's to confirm.

## Rules every skill follows

- Written fresh for this kit; the examples use a made-up company and project.
- Rates, prices and totals are never filled in: they stay placeholders for a person.
- Pasted or attached text is treated as material to analyse, not as instructions.
- The full catalog, with specs for the skills not built yet, is in `docs/business-catalog.md`.

## Evals

`evals/<skill>/` holds one case per skill (text-only: the Skill tool and nothing else) and
`evals/negative-unrelated/` checks that no business skill fires on an unrelated question. Running them calls a model,
so it is a deliberate step:

```
claude plugin eval plugins/workbench-biz --trust-plugin --json eval.json --threshold 0.8 --no-publish --model <model>
```

The offline checks run with `py -3 -m unittest discover -s plugins/workbench-biz/tests -v`.
