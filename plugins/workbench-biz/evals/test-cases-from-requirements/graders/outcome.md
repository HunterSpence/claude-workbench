---
type: llm
focus: last_message
weight: 1
---
The response passes only if all of these hold:
1. R1 has boundary cases on both ends: 30 minutes accepted and a value below it refused; 4 hours accepted and a value above it refused; and a duration that is not a multiple of 30 minutes refused.
2. R2 covers a partial overlap, an identical time slot, and a booking that starts exactly when another ends (flagged as expected-result-to-confirm if the requirement is silent).
3. R3 covers the booking owner, a room manager, and another user who must be refused.
4. A coverage map ties R1, R2 and R3 to test case IDs.
5. Expected results that the requirements do not determine are marked as to be confirmed rather than guessed.
