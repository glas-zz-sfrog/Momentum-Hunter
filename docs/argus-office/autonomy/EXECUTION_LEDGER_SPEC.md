# Execution Ledger Spec

## Goal
The Execution Ledger is the audit trail for simulated, paper, preview, and future live execution activity.

## Required Event Fields
- Event identifier.
- Timestamp.
- Mode.
- Ticker.
- TradePlan identifier.
- Risk Governor result identifier or summary.
- Broker adapter class.
- Approval state.
- Requested action.
- Result.
- Actor or source.
- Error or block reason when present.

## Required Event Types
- Candidate selected.
- TradePlan generated.
- TradePlan edited.
- Risk gate evaluated.
- Simulated order created.
- Paper order created.
- Broker state read.
- Live order preview generated.
- Execution blocked.
- Future confirmed live order submitted.

## Invariant
Every future simulated, paper, preview, or live order-like action must be explainable from the ledger using TradePlan, risk gate result, mode, approval state, and adapter.

## Non-Goals
This spec does not choose a database implementation and does not authorize schema changes.
