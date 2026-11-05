# ADR 0005: Rules set protective flags immediately; only specialists clear them

- **Status:** accepted (deviation from project.md, review)
- **Date:** 2026-11-04
- **Phase:** 1

## Context
project.md's flag table says `fraud_flag` and `hardship_flag` are set "when the rule fires *and* the specialist confirms". Between the customer's message and the specialist's review, marketing would then still be allowed for a customer reporting fraud or hardship.

## Options considered
| Option | For | Against |
|---|---|---|
| Set on specialist confirmation | Fewer false flags | Hours or days of marketing to a customer in distress; R7 can't act in the same decision |
| Set immediately by the rule; specialist clears | Safe default; suppression is instant | A wrongly flagged customer misses marketing until reviewed |

## Decision
Rules R1, R2 and R4 set their flag in the same decision. Clearing needs a role listed in `rules.yaml` (`fraud_specialist`, `hardship_specialist`, `manager`, or `system` for complaints). Every set and clear is audited.

## Consequences
- The failure mode is "too protective", which is the right way round for a regulated bank.
- The approval request still covers the *action* (block card, hardship review). The flag is protection, not the action.
- Revisit if the false-flag rate in live mode makes the specialist queue unmanageable.
