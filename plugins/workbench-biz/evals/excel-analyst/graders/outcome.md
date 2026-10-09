---
type: llm
focus: last_message
weight: 1
---
The response passes only if all of these hold:
1. It profiles the data (nine rows, four columns) and flags the quality issues: a possible duplicate row (Design, 03 Mar), a blank hours value (Finance, Tue) and a blank date (Ops, Fri).
2. It states how each issue was treated (kept, dropped or excluded) as an assumption, rather than silently choosing.
3. It names Ops as the team with the most hours, with per-team totals that are consistent with the stated treatment (Ops 8.5 if the blank-date row is kept, 7.5 if excluded).
4. It shows a check that the team totals add up to an overall total.
5. It cautions that nine rows over one week is too small to conclude much about weekday differences and does not invent a cause.
