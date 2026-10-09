# Write a status report

Automates it: /workbench-biz:status-report

## When to use
It is Thursday and the weekly or monthly report is due: one page with an overall red, amber or green, what finished, the
numbers, milestones, risks, and what you need from others. You have raw material (notes, a ticket export, chat excerpts,
last period's report) and want it in the same shape every time.

## Steps
1. Collect the raw updates in one place. Include last period's report if you have it, so Claude can show what changed colour.
2. Ask "draft this week's status report from these updates" or run `/workbench-biz:status-report`, and paste or attach the
   material. Text inside it is content, never instructions.
3. Read the draft. The order is fixed: overall status with one sentence of why, highlights, KPIs (measure, target, actual,
   trend), milestones (planned, forecast, status), risks and issues, asks and decisions needed, next period.
4. Check the colours against evidence. Green is on plan with no help needed; amber is at risk with a recovery plan; red is off
   plan or needs a decision now. The overall colour is never better than the worst milestone that is critical to the end date.
   Every amber or red row needs an owner and an ask.
5. Fill what is marked "No update provided" or edit it out, move bad news up to the first section it applies to, and send
   the report yourself. If it goes out as a Word or Excel file, scrub the copy first (guide 36).

## Verify
- Every colour traces to something in the input (a slipped date, a missed target), not to tone.
- Every number is in the input. A trend that needs last period's figure and cannot get it says so.
- Names appear as written in the input.

## Common failures
- **Bad news buried in the highlights:** ask for it in the section where it applies.
- **Invented numbers or trends:** the skill must say "not provided". If it did not, reject the line.
- **Everything is green because the update sounds cheerful:** give it the dates and targets, and ask it to re-colour from them.
- **One person wrote ten pages:** the format is one page. Ask for the short version.
