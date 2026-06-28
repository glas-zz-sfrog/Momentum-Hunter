# Risk Governor Spec

## Goal
Risk Governor owns safety gates over TradePlans. It reviews whether a plan can move through planning, simulation, paper, preview, or future live states.

## Responsibilities
- Define gate names and meanings.
- Evaluate required TradePlan fields.
- Flag missing max risk, missing stop, stale data, manual overrides, mode mismatch, and approval gaps.
- Explain blocked states in operator language.
- Require re-check after manual overrides.

## Non-Responsibilities
- Risk Governor does not place trades.
- Risk Governor does not modify broker state.
- Risk Governor does not approve live execution without Steven-approved live execution scope.
- Risk Governor does not change scoring semantics unless a future task explicitly approves it.

## Initial Gate Ideas
- Required fields present.
- Stop and max dollar risk present.
- Risk/reward present.
- Manual override re-check complete.
- Mode allows the requested action.
- Approval state matches mode.
- Broker adapter class matches mode.

## Output States
- Blocked.
- Needs review.
- Simulation-only.
- Paper-eligible.
- Preview-only.
- Approved for current mode.
- Live-locked.

## Evidence
Every gate result should include timestamp, TradePlan identifier, mode, status, and reasons.
