---
type: llm
focus: last_message
weight: 1
---
The response passes only if all of these hold:
1. It contains at least four distinct user stories in the form "As a <role>, I want <capability>, so that <benefit>", covering room search, the 4-hour limit, the cancellation email and booking history.
2. It gives Given / When / Then acceptance criteria, including at least one failing case for the 4-hour limit.
3. Its open questions include how a manager extends a booking, what "fast" means as a measurable target, and the retention period.
4. It does not invent a number for the page-load target or for the retention period.
5. It includes a traceability table or list linking requirement IDs to stories.
