# Business skill catalog

A ranked list of skills that help people who work in Claude on the web, the desktop app or Claude Code with everyday
business documents. The first eight are built and ship in `workbench-biz` (see that plugin's README). Every other
row has a spec below, so a team can build it the same way: instructions only, portable, with one eval case.

Rules every entry follows:
- Portable to claude.ai: six frontmatter fields only (`name`, `description`, `license`, `compatibility`, `metadata`,
  `allowed-tools`), a description of 250 characters or fewer, no `bin/`, hooks, local servers or user settings, and no
  network access or package installs in the instructions.
- Anything that produces a number a customer would see (rates, prices, totals) leaves it as a placeholder for a person.
- Examples use a made-up company, made-up people and a made-up project.
- Each skill ships one eval case with a fire check and at least one outcome grader, and the plugin keeps one negative case.
- Industry-specific rows are out of scope for this catalog.

Columns: **Portable**: Y works in chat as a skill; Y* needs code execution or file creation for real files; Y/C is more
useful with a connector. **Connector** names a category, never a product. **Value** and **Effort** are the author's
estimates (H, M, L; S, M, L), not measurements.

| Rank | Name | What it does | Portable | Connector (optional) | Value | Effort | Status |
|---|---|---|---|---|---|---|---|
| 1 | `requirements-to-stories` | Requirements document or notes to epics, INVEST stories, Given/When/Then, traceability, open questions | Y | project tracker | H | S | built |
| 2 | `meeting-to-actions` | Transcript or notes to decisions, actions with owners, risks, follow-up email draft | Y | meeting transcripts, project tracker | H | S | built |
| 3 | `status-report` | Weekly or monthly RAG report in a fixed format | Y | project tracker | H | S | built |
| 4 | `test-cases-from-requirements` | Stories to a test matrix, Gherkin, coverage map | Y | test management | H | S | built |
| 5 | `excel-analyst` | Method for spreadsheet analysis: profile, clean, pivot, explain, reconcile | Y* | none | H | M | built |
| 6 | `rfp-sow-drafter` | RFP answer grid and SOW skeleton; prices stay placeholders | Y | knowledge base of past answers | H | M | built |
| 7 | `branded-deck` | Brand tokens and an outline to a slide build spec or deck | Y* | none | H | S | built |
| 8 | `policy-qa` | Cited answers from policies; says "not found" instead of guessing | Y/C | knowledge base | H | S | built |
| 9 | `estimation-helper` | Work breakdown and three-point estimates; never states a rate | Y | none | H | M | spec |
| 10 | `raid-log` | Maintain risks, assumptions, issues and dependencies from notes | Y | project tracker | M | S | spec |
| 11 | `release-notes` | Tickets or change lists to audience-specific release notes | Y/C | project tracker, source control | M | S | spec |
| 12 | `incident-postmortem` | Blameless postmortem from a timeline | Y | chat, ticketing | M | S | spec |
| 13 | `runbook-sop-writer` | Process walkthrough to a checked SOP or runbook | Y | none | M | S | spec |
| 14 | `data-quality-checks` | Nulls, duplicates, formats, ranges, outliers and code-list gaps in tabular data | Y* | none | H | M | spec |
| 15 | `onboarding-buddy` | New-joiner pack from project documents | Y/C | knowledge base | M | S | spec |
| 16 | `glossary-builder` | Terms and acronyms from documents, with conflicts flagged | Y | none | M | S | spec |
| 17 | `stakeholder-update` | One update tailored to executives, clients and the team | Y | email, chat | M | S | spec |
| 18 | `prompt-library` | Team prompt patterns, an improvement checklist, reusable templates | Y | none | M | S | spec |
| 19 | `sql-helper` | Read-only queries and explanations against a described schema | Y/C | data warehouse | M | S | spec |
| 20 | `vendor-review` | Due-diligence questionnaire and weighted comparison | Y | none | M | S | spec |
| 21 | `change-request` | Change request with impact, options and approvals | Y | project tracker | M | S | spec |
| 22 | `accessibility-review` | WCAG-oriented review of a page, screen or document | Y | none | M | S | spec |
| 23 | `kb-article` | Resolved ticket to a self-service help article | Y/C | ticketing | M | S | spec |
| 24 | `plugin-preflight` | Light pre-share check of a skill or plugin folder (deferred) | Y* | none | H for reviewers | M | spec |
| 25 | `nda-triage` | First-pass clause triage against a checklist, routed to legal | Y | none | L-M | S | spec |

Suggested build order for the specs: 9, 10, 14, 24, then by need.

## Specs

Each spec gives the trigger phrases, the inputs, the output shape and an eval-case sketch (prompt, fire check, outcome
graders). All use text-only eval cases unless noted.

### 9 estimation-helper
- Trigger: "estimate this work", "break this into tasks with effort".
- Inputs: scope text or requirements, the unit (days or points), constraints, team size if known.
- Output: work breakdown table with best, likely and worst effort per item; the combined figure and the method; a risk buffer shown on its own line; assumptions. Rates and prices appear only as `[RATE: set by a human]`.
- Eval sketch: five features as the prompt. Graders: regex for the three effort columns; regex that no currency amount appears; llm that assumptions are listed and the buffer is separate.

### 10 raid-log
- Trigger: "update the RAID log from these notes".
- Inputs: meeting or email notes and the current log as a table.
- Output: updated Risks, Assumptions, Issues and Dependencies tables (ID, description, owner, raised, status, next review) and a list of what changed.
- Eval sketch: a three-row log plus notes that close one item and add one. Graders: IDs are not renumbered; the closed item is marked closed, not deleted; llm that the new item has an owner or is flagged unowned.

### 11 release-notes
- Trigger: "write release notes from these tickets".
- Inputs: ticket or change list, version label, audiences.
- Output: one section per audience (users, support, leadership), grouped as new, improved, fixed, known issues; plain words for users.
- Eval sketch: six tickets, one internal-only. Graders: the internal item is absent from the user section; known issues are listed; llm on tone per audience.

### 12 incident-postmortem
- Trigger: "write a postmortem for this incident".
- Inputs: timeline notes, impact figures, chat excerpts.
- Output: summary, impact, timeline with sources, root cause and contributing factors, what went well, actions with owner and due date.
- Eval sketch: notes in which one person made an error. Graders: no blame wording; the cause is a process or system condition; an unknown cause is stated as unknown.

### 13 runbook-sop-writer
- Trigger: "turn this walkthrough into an SOP".
- Inputs: notes or transcript of someone doing the process, tools, roles.
- Output: purpose, prerequisites, numbered steps each with an expected result, checks, rollback or escalation, owner, review date placeholder.
- Eval sketch: a walkthrough containing "then I do the usual thing". Graders: the gap is raised as a question; steps are numbered; llm that every step has an expected result.

### 14 data-quality-checks
- Trigger: "check this data for problems".
- Inputs: a CSV or workbook, plus any rules (formats, allowed values, ranges).
- Output: issues by column and rule with counts and example rows, severity, suggested fix; no change is applied without approval.
- Eval sketch: pasted CSV with planted blanks, duplicates and a bad date. Graders: each planted issue is reported with the right count; llm that no data was altered.

### 15 onboarding-buddy
- Trigger: "make a starter pack for a new joiner".
- Inputs: project documents, the newcomer's role.
- Output: who is who, glossary, systems list, first-week plan, FAQ; every item cites its source document, unknowns become open questions.
- Eval sketch: three short documents. Graders: every fact has a citation; no invented names; llm on the first-week plan being specific.

### 16 glossary-builder
- Trigger: "extract the terms and acronyms from these documents".
- Inputs: one or more documents.
- Output: table of term, definition, source, where first seen; conflicts shown side by side.
- Eval sketch: two documents defining the same term differently. Graders: the conflict is flagged; sources named.

### 17 stakeholder-update
- Trigger: "write this update for executives and for the team".
- Inputs: one factual update and the audiences.
- Output: one version per audience (executives: outcome and ask in five lines; clients: progress and next steps without internal issues; team: detail), plus a check that the facts agree across versions.
- Eval sketch: update with three numbers. Graders: the same numbers appear in every version; the executive version contains an ask.

### 18 prompt-library
- Trigger: "improve my prompt", "save this as a team template".
- Inputs: a draft prompt, the goal, sample outputs if any.
- Output: improved prompt with context, task, format and checks; a template with `<placeholders>`; two test inputs.
- Eval sketch: a vague one-line prompt. Graders: the output format is specified; placeholders are marked; llm that the goal is unchanged.

### 19 sql-helper
- Trigger: "write a query for", "explain this query".
- Inputs: schema description, the question, the SQL dialect.
- Output: a read-only query, a line-by-line explanation, join assumptions, performance notes. Statements that change data or structure are refused unless the user asks and confirms.
- Eval sketch: a schema with three tables. Graders: only listed columns are used; no data-changing statements; llm that join assumptions are stated.

### 20 vendor-review
- Trigger: "compare these vendors", "build a due-diligence questionnaire".
- Inputs: requirements and vendor material.
- Output: questionnaire (security, privacy, support, continuity, cost structure with placeholders), weighted comparison matrix, gaps list.
- Eval sketch: two short vendor descriptions. Graders: weights are shown; missing facts say "not provided"; no price is invented.

### 21 change-request
- Trigger: "raise a change request".
- Inputs: description, reason, affected scope.
- Output: summary, reason, impact on scope, schedule, effort and risk (effort and cost as placeholders), options, recommendation, approvals table, rollback.
- Eval sketch: a scope change to a running project. Graders: effort and cost are placeholders; an approvals table exists; llm on a stated rollback.

### 22 accessibility-review
- Trigger: "check this page for accessibility".
- Inputs: markup, text, a description or an exported screen.
- Output: findings grouped by perceivable, operable, understandable, robust, with severity, how to fix, and what could not be checked from the input.
- Eval sketch: an HTML snippet with a missing image description and low-contrast text. Graders: both found; the answer says automated and manual testing are still needed.

### 23 kb-article
- Trigger: "turn this resolved ticket into a help article".
- Inputs: the ticket thread, the audience.
- Output: title in the user's symptom words, problem, cause, steps, how to check it worked, when to escalate; names and internal details removed.
- Eval sketch: a thread with a customer name and an internal machine name. Graders: neither appears in the output; steps are numbered.

### 24 plugin-preflight
- Trigger: "check my skill before I share it".
- Inputs: a skill or plugin folder (uploaded or pasted file contents).
- Output: pass or fail per check: portability (six frontmatter fields, description length, no `bin/`, hooks or local servers), instruction-override wording, secrets, README and licence; then a fix list. A lighter cousin of the kit's `plugin-review`; deferred until reviewers ask for it.
- Eval sketch: a seeded skill with a non-portable key and a token-shaped string. Graders: both findings reported; llm that fixes are specific.

### 25 nda-triage
- Trigger: "triage this NDA".
- Inputs: the agreement text and the organisation's checklist.
- Output: clause table against the checklist (parties, definition of confidential information, exclusions, term, governing law, assignment, return or destruction) rated green, amber or red, plus the clauses to route to the legal team. Never a final opinion.
- Eval sketch: an NDA with a one-sided term. Graders: the clause is flagged; the answer says it is not legal advice and names routing to legal.
